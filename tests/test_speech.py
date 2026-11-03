import json
from unittest.mock import Mock

import pytest
import requests
from conftest import wav_bytes

from speech_service import SpeechError, SpeechService, validate_wav


class Upstream:
    def __init__(self, body=b"", status=200):
        self.body, self.status_code = body, status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        for index in range(0, len(self.body), size):
            yield self.body[index : index + size]


@pytest.fixture
def service():
    return SpeechService("test-only-key", "eastus")


@pytest.mark.parametrize(
    "audio",
    [
        b"",
        b"garbage",
        wav_bytes(100),
        wav_bytes(480001),
        wav_bytes(channels=2),
        wav_bytes(rate=48000),
        wav_bytes(width=3),
        wav_bytes()[:-10],
    ],
)
def test_invalid_audio_never_leaves_server(monkeypatch, service, audio):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError):
        service.recognize(audio)
    post.assert_not_called()


def test_audio_boundaries():
    validate_wav(wav_bytes(1600))
    validate_wav(wav_bytes(480000))


def test_recognition_protocol(monkeypatch, service):
    post = Mock(
        return_value=Upstream(
            json.dumps({"RecognitionStatus": "Success", "DisplayText": "List items."}).encode()
        )
    )
    monkeypatch.setattr(requests, "post", post)
    assert service.recognize(wav_bytes()) == "List items."
    args, options = post.call_args
    assert (
        args[0]
        == "https://eastus.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
    )
    assert options["headers"]["Ocp-Apim-Subscription-Key"] == "test-only-key"
    assert options["params"] == {"language": "en-US", "format": "simple"}
    assert options["allow_redirects"] is False
    assert options["timeout"] == (5, 45)


def test_ssml_injection_is_spoken_as_plain_text(monkeypatch, service):
    post = Mock(return_value=Upstream(wav_bytes()))
    monkeypatch.setattr(requests, "post", post)
    text = 'Title <break time="10s"/> & another <audio src="https://evil.example"/>'
    assert service.synthesize(text).startswith(b"RIFF")
    ssml = post.call_args.kwargs["data"].decode()
    assert "&lt;break" in ssml and "&amp;" in ssml
    assert "<break" not in ssml and "<audio" not in ssml
    assert post.call_args.args[0] == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"


@pytest.mark.parametrize(
    "status,expected", [(301, 502), (400, 502), (401, 503), (403, 503), (429, 429), (500, 502)]
)
def test_upstream_errors_do_not_expose_provider_bodies(
    monkeypatch, service, status, expected, caplog
):
    monkeypatch.setattr(
        requests, "post", Mock(return_value=Upstream(b"private-provider-detail", status))
    )
    with pytest.raises(SpeechError) as captured:
        service.recognize(wav_bytes())
    assert captured.value.status_code == expected
    assert "private-provider-detail" not in str(captured.value) + caplog.text
    assert "test-only-key" not in str(captured.value) + caplog.text


@pytest.mark.parametrize(
    "error,status",
    [(requests.Timeout("test-only-key"), 504), (requests.ConnectionError("test-only-key"), 502)],
)
def test_transport_exceptions_are_sanitized(monkeypatch, service, error, status):
    monkeypatch.setattr(requests, "post", Mock(side_effect=error))
    with pytest.raises(SpeechError) as captured:
        service.synthesize("Done")
    assert captured.value.status_code == status
    assert "test-only-key" not in str(captured.value)


@pytest.mark.parametrize(
    "payload,status",
    [
        (b"not-json", 502),
        (b"[]", 502),
        (b"", 502),
        (b'{"RecognitionStatus":"NoMatch"}', 422),
        (b'{"RecognitionStatus":"InitialSilenceTimeout"}', 422),
        (b'{"RecognitionStatus":"Success","DisplayText":""}', 422),
        (json.dumps({"RecognitionStatus": "Success", "DisplayText": "x" * 1201}).encode(), 422),
        (b"x" * 64001, 502),
    ],
)
def test_failed_or_malformed_recognition(monkeypatch, service, payload, status):
    monkeypatch.setattr(requests, "post", Mock(return_value=Upstream(payload)))
    with pytest.raises(SpeechError) as captured:
        service.recognize(wav_bytes())
    assert captured.value.status_code == status


@pytest.mark.parametrize("text", [None, "", " ", "x" * 2001, "bad\0text", "\ud800", "\ufffe", 3])
def test_invalid_synthesis_text_does_not_call_azure(monkeypatch, service, text):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(ValueError):
        service.synthesize(text)
    post.assert_not_called()


@pytest.mark.parametrize(
    "key,region",
    [
        ("", "eastus"),
        ("test", ""),
        ("test", "eastus.evil.example"),
        ("test", "eastus/path"),
        ("test", "x\nheader"),
    ],
)
def test_missing_configuration_or_invalid_host_never_calls_azure(monkeypatch, key, region):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    service = SpeechService(key, region)
    assert service.configured is False
    with pytest.raises(SpeechError):
        service.synthesize("Done")
    post.assert_not_called()


def test_busy_service_returns_without_network(monkeypatch, service):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    service._slots.acquire()
    service._slots.acquire()
    try:
        with pytest.raises(SpeechError) as captured:
            service.synthesize("Done")
        assert captured.value.status_code == 429
        post.assert_not_called()
    finally:
        service._slots.release()
        service._slots.release()


@pytest.mark.parametrize(
    "audio", [b"not-wave", b"RIFFxxxxWAVE", wav_bytes()[:-10], wav_bytes(rate=48000)]
)
def test_malformed_synthesis_audio_is_rejected(monkeypatch, service, audio):
    monkeypatch.setattr(requests, "post", Mock(return_value=Upstream(audio)))
    with pytest.raises(SpeechError) as captured:
        service.synthesize("Completed.")
    assert captured.value.status_code == 502
