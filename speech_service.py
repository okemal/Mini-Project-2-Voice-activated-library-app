"""Server-only Azure Speech adapter with bounded inputs and private errors."""

import json
import os
import re
import wave
from io import BytesIO
from threading import BoundedSemaphore
from xml.sax.saxutils import escape

import requests

MAX_RECORDING_SECONDS = 30
MAX_AUDIO_BYTES = 16_000 * 2 * MAX_RECORDING_SECONDS + 4096
MAX_SPEECH_TEXT = 2000


class SpeechError(Exception):
    """An intentionally public error; provider bodies are never exposed."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


def validate_wav(audio: bytes) -> None:
    """Accept only complete, bounded mono 16 kHz, 16-bit PCM WAV recordings."""
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("Record between 0.1 and 30 seconds of audio")
    try:
        with wave.open(BytesIO(audio), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (
                1,
                2,
                16_000,
                "NONE",
            ):
                raise ValueError("Audio must be mono 16 kHz, 16-bit PCM WAV")
            frames = wav.getnframes()
            if not 1600 <= frames <= 16_000 * MAX_RECORDING_SECONDS:
                raise ValueError("Record between 0.1 and 30 seconds of audio")
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError("The audio recording is incomplete; record it again")
    except (wave.Error, EOFError, OSError) as from_error:
        raise ValueError("Audio must be a valid PCM WAV recording") from from_error


class SpeechService:
    """Send short recordings and escaped SSML to fixed Azure HTTPS hosts.

    The REST interface avoids putting a subscription key or reusable Azure
    access token in the browser, and works without native SDK dependencies.
    No audio, transcript, key, or upstream response is logged or stored here.
    """

    def __init__(self, key: str = "", region: str = "") -> None:
        self._key = key.strip()
        self._region = region.strip().lower()
        self._slots = BoundedSemaphore(2)

    @classmethod
    def from_environment(cls) -> "SpeechService":
        """Support the conventional key name and the supplied .env alias."""
        return cls(
            os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_API_KEY_1", ""),
            os.getenv("AZURE_SPEECH_REGION", ""),
        )

    @property
    def configured(self) -> bool:
        """Return configuration readiness without revealing either value."""
        return bool(
            self._key
            and len(self._key) <= 512
            and all(33 <= ord(char) <= 126 for char in self._key)
            and re.fullmatch(r"[a-z][a-z0-9-]{1,62}", self._region)
        )

    def _post(
        self, kind: str, data: bytes, headers: dict, limit: int, params: dict | None = None
    ) -> bytes:
        if not self.configured:
            raise SpeechError(
                "Azure Speech is not configured. Set the key and region in the server's .env file."
            )
        if not self._slots.acquire(blocking=False):
            raise SpeechError("Speech is busy. Please try again shortly.", 429)
        try:
            suffix = (
                "stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
                if kind == "stt"
                else "tts.speech.microsoft.com/cognitiveservices/v1"
            )
            # Do not follow redirects with an authentication header attached.
            with requests.post(
                f"https://{self._region}.{suffix}",
                headers={"Ocp-Apim-Subscription-Key": self._key, **headers},
                params=params,
                data=data,
                timeout=(5, 45),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code in {401, 403}:
                    raise SpeechError(
                        "Azure Speech authentication failed. Check the server's key and region."
                    )
                if response.status_code == 429:
                    raise SpeechError(
                        "Azure Speech quota or rate limit reached. Try again later.", 429
                    )
                if response.status_code != 200:
                    raise SpeechError(
                        "Azure Speech could not complete the request. Please try again.", 502
                    )
                content = bytearray()
                for chunk in response.iter_content(8192):
                    content.extend(chunk)
                    if len(content) > limit:
                        raise SpeechError("Azure Speech returned an oversized response.", 502)
                if not content:
                    raise SpeechError("Azure Speech returned an empty response.", 502)
                return bytes(content)
        except requests.Timeout:
            raise SpeechError("Azure Speech timed out. Please try again.", 504) from None
        except requests.RequestException:
            # Request exceptions can carry credential-bearing request objects.
            raise SpeechError(
                "Azure Speech is unavailable. Check your connection and try again.", 502
            ) from None
        finally:
            self._slots.release()

    def recognize(self, audio: bytes) -> str:
        """Transcribe one recording, failing explicitly on silence/no match."""
        validate_wav(audio)
        raw = self._post(
            "stt",
            audio,
            {
                "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                "Accept": "application/json",
            },
            64_000,
            {"language": "en-US", "format": "simple"},
        )
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SpeechError(
                "Azure Speech returned an invalid recognition response.", 502
            ) from None
        if not isinstance(result, dict):
            raise SpeechError("Azure Speech returned an invalid recognition response.", 502)
        if result.get("RecognitionStatus") != "Success":
            raise SpeechError("No speech was recognized. Try again closer to the microphone.", 422)
        text = result.get("DisplayText")
        if not isinstance(text, str) or not text.strip():
            raise SpeechError("No speech was recognized. Please try again.", 422)
        if len(text) > 1200:
            raise SpeechError("The command is too long. Record a shorter command.", 422)
        return text.strip()

    def synthesize(self, text: str) -> bytes:
        """Synthesize plain text; user text cannot inject SSML elements."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_SPEECH_TEXT:
            raise ValueError(f"Speech text must contain 1 to {MAX_SPEECH_TEXT} characters")
        if any(
            not (
                char in "\t\n\r"
                or 0x20 <= ord(char) <= 0xD7FF
                or 0xE000 <= ord(char) <= 0xFFFD
                or 0x10000 <= ord(char) <= 0x10FFFF
            )
            for char in text
        ):
            raise ValueError("Speech text must contain printable characters")
        ssml = (
            '<speak version="1.0" xml:lang="en-US">'
            '<voice name="en-US-JennyNeural">' + escape(text) + "</voice></speak>"
        )
        audio = self._post(
            "tts",
            ssml.encode("utf-8"),
            {
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "riff-16khz-16bit-mono-pcm",
                "User-Agent": "VoiceLibrary/1.0",
            },
            8_000_000,
        )
        try:
            with wave.open(BytesIO(audio), "rb") as wav:
                if (
                    wav.getnchannels(),
                    wav.getsampwidth(),
                    wav.getframerate(),
                    wav.getcomptype(),
                ) != (1, 2, 16_000, "NONE"):
                    raise ValueError("Unexpected audio format")
                frames = wav.getnframes()
                if (
                    frames < 1
                    or frames * 2 > 8_000_000
                    or len(wav.readframes(frames)) != frames * 2
                ):
                    raise ValueError("Incomplete audio")
        except (wave.Error, EOFError, OSError, ValueError):
            raise SpeechError("Azure Speech returned an invalid audio response.", 502) from None
        return audio
