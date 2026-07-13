import pytest

import src.tools.transcript as transcript_module
from src.tools.transcript import AudioExtractionError, AudioTooLargeError, MiMoASRProvider, _validate_public_bilibili_url


class FakeMessage:
    content = "测试转写"


class FakeChoice:
    message = FakeMessage()


class FakeCompletion:
    choices = [FakeChoice()]


class FakeCompletions:
    def __init__(self): self.kwargs = None
    async def create(self, **kwargs): self.kwargs = kwargs; return FakeCompletion()


class FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": FakeCompletions()})()


@pytest.mark.asyncio
async def test_mimo_asr_request_uses_input_audio_and_asr_options(monkeypatch):
    client = FakeClient()
    provider = MiMoASRProvider(client=client)
    result = await provider.transcribe(audio_bytes=b"audio", audio_format="mp3", audio_hash="abc", video_url="https://www.bilibili.com/video/BV1xx411c7mD")
    payload = client.chat.completions.kwargs
    assert payload["model"] == "mimo-v2.5-asr"
    assert payload["messages"][0]["content"][0]["type"] == "input_audio"
    assert payload["messages"][0]["content"][0]["input_audio"]["data"].startswith("data:audio/mpeg;base64,")
    assert payload["extra_body"]["asr_options"]["language"] in {"auto", "zh", "en"}
    assert result["provider"] == "mimo"


@pytest.mark.asyncio
async def test_mimo_asr_rejects_oversized_base64_before_api_call(monkeypatch):
    monkeypatch.setattr(transcript_module, "ASR_MAX_BASE64_BYTES", 4)
    client = FakeClient()
    provider = MiMoASRProvider(client=client)
    with pytest.raises(AudioTooLargeError):
        await provider.transcribe(audio_bytes=b"audio", audio_format="wav", audio_hash="abc", video_url="https://www.bilibili.com/video/BV1xx411c7mD")
    assert client.chat.completions.kwargs is None


def test_audio_extraction_accepts_only_public_bilibili_https_urls():
    _validate_public_bilibili_url("https://www.bilibili.com/video/BV1xx411c7mD")
    _validate_public_bilibili_url("https://b23.tv/example")
    with pytest.raises(AudioExtractionError): _validate_public_bilibili_url("http://www.bilibili.com/video/BV1xx411c7mD")
    with pytest.raises(AudioExtractionError): _validate_public_bilibili_url("https://example.com/video.mp3")
