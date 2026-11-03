"""Isolated state and local speech doubles; default tests never use Azure."""

import wave
from io import BytesIO

import pytest

from app import create_app
from speech_service import validate_wav


def wav_bytes(frames=3200, *, channels=1, rate=16000, width=2):
    stream = BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\0" * frames * width * channels)
    return stream.getvalue()


class FakeSpeech:
    configured = True

    def __init__(self):
        self.transcript = "List available books."
        self.recognitions = []
        self.spoken = []

    def recognize(self, audio):
        validate_wav(audio)
        self.recognitions.append(audio)
        return self.transcript

    def synthesize(self, text):
        self.spoken.append(text)
        return wav_bytes()


@pytest.fixture
def speech():
    return FakeSpeech()


@pytest.fixture
def app(speech):
    return create_app({"TESTING": True}, speech_service=speech)


@pytest.fixture
def client(app):
    client = app.test_client()
    client.environ_base["HTTP_X_LIBRARY_REQUEST"] = "1"
    return client
