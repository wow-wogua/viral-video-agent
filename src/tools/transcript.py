import asyncio
import base64
import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI

from src.config import (
    ASR_MAX_BASE64_BYTES,
    ASR_MAX_VIDEO_SECONDS,
    MIMO_API_KEY,
    MIMO_ASR_BASE_URL,
    MIMO_ASR_LANGUAGE,
    MIMO_ASR_MODEL,
    REDIS_URL,
    TRANSCRIPT_PROVIDER,
    XFYUN_APPID,
    XFYUN_SECRET_KEY,
)

PROJECT_TMP = Path(__file__).resolve().parents[2] / "tmp"
BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")


class TranscriptError(RuntimeError):
    code = "ASR_FAILED"


class AudioTooLargeError(TranscriptError):
    code = "ASR_FILE_TOO_LARGE"


class AudioExtractionError(TranscriptError):
    code = "AUDIO_EXTRACTION_FAILED"


class TranscriptProvider(ABC):
    name: str

    @property
    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    async def transcribe(self, *, audio_bytes: bytes, audio_format: str, audio_hash: str, video_url: str) -> dict: ...


class MiMoASRProvider(TranscriptProvider):
    name = "mimo"

    def __init__(self, client=None):
        self._injected_client = client is not None
        self.client = client or (AsyncOpenAI(api_key=MIMO_API_KEY, base_url=MIMO_ASR_BASE_URL) if MIMO_API_KEY else None)

    @property
    def available(self) -> bool:
        return bool(self.client and (MIMO_API_KEY or self._injected_client))

    async def transcribe(self, *, audio_bytes: bytes, audio_format: str, audio_hash: str, video_url: str) -> dict:
        if not self.available:
            raise TranscriptError("MiMo ASR is not configured")
        encoded = base64.b64encode(audio_bytes)
        if len(encoded) > ASR_MAX_BASE64_BYTES:
            raise AudioTooLargeError("base64 audio exceeds 10MB")
        mime = "audio/mpeg" if audio_format == "mp3" else "audio/wav"
        try:
            completion = await self.client.chat.completions.create(
                model=MIMO_ASR_MODEL,
                messages=[{"role": "user", "content": [{"type": "input_audio", "input_audio": {"data": f"data:{mime};base64,{encoded.decode('ascii')}"}}]}],
                extra_body={"asr_options": {"language": MIMO_ASR_LANGUAGE}},
            )
        except Exception as exc:
            raise TranscriptError(f"MiMo ASR request failed: {type(exc).__name__}") from exc
        text = completion.choices[0].message.content or ""
        return {"text": text, "segments": [], "language": MIMO_ASR_LANGUAGE, "provider": self.name, "model": MIMO_ASR_MODEL, "audio_hash": audio_hash, "fetched_at": datetime.now(timezone.utc).isoformat(), "source_url": video_url}


class XFYunProvider(TranscriptProvider):
    name = "xfyun"

    @property
    def available(self) -> bool:
        return bool(XFYUN_APPID and XFYUN_SECRET_KEY)

    async def transcribe(self, *, audio_bytes: bytes, audio_format: str, audio_hash: str, video_url: str) -> dict:
        if not self.available:
            raise TranscriptError("XFYun is not configured")
        ts = str(int(time.time()))
        sign = hashlib.md5((XFYUN_APPID + ts + XFYUN_SECRET_KEY).encode()).hexdigest()
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post("https://raasr.xfyun.cn/v2/api/submit", params={"appid": XFYUN_APPID, "ts": ts, "sign": sign}, json={"url": video_url})
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != "00000": raise TranscriptError("XFYun submit failed")
            task_id = payload.get("data", {}).get("task_id", "")
            for _ in range(30):
                await asyncio.sleep(10)
                result = (await client.get("https://raasr.xfyun.cn/v2/api/result", params={"appid": XFYUN_APPID, "ts": ts, "sign": sign, "task_id": task_id})).json()
                if result.get("code") == "00000":
                    return {"text": result.get("data", {}).get("result", ""), "segments": [], "language": "zh", "provider": self.name, "model": "xfyun-raasr", "audio_hash": audio_hash, "fetched_at": datetime.now(timezone.utc).isoformat(), "source_url": video_url}
        raise TranscriptError("XFYun result timeout")


def get_transcript_providers() -> list[TranscriptProvider]:
    preferred = MiMoASRProvider() if TRANSCRIPT_PROVIDER == "mimo" else XFYunProvider()
    fallback = XFYunProvider() if TRANSCRIPT_PROVIDER == "mimo" else MiMoASRProvider()
    return [provider for provider in (preferred, fallback) if provider.available]


def transcript_capability() -> tuple[bool, str]:
    providers = get_transcript_providers()
    return (bool(providers), providers[0].name if providers else "unconfigured")


def _validate_public_bilibili_url(video_url: str) -> None:
    parsed = urlparse(video_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "b23.tv" or host.endswith("bilibili.com")):
        raise AudioExtractionError("only public bilibili https URLs are allowed")


def _extract_audio_sync(video_url: str) -> tuple[bytes, str, float]:
    _validate_public_bilibili_url(video_url)
    PROJECT_TMP.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
        with TemporaryDirectory(prefix="asr-", dir=PROJECT_TMP) as temp_dir:
            output = str(Path(temp_dir) / "audio.%(ext)s")
            options = {
                "format": "bestaudio/best", "outtmpl": output, "noplaylist": True,
                "quiet": True, "no_warnings": True, "cachedir": False,
                "match_filter": lambda info, *, incomplete=False: "video too long" if info.get("duration") and info["duration"] > ASR_MAX_VIDEO_SECONDS else None,
                "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}],
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(video_url, download=True)
            candidates = list(Path(temp_dir).glob("audio.*"))
            if not candidates: raise AudioExtractionError("audio file was not produced")
            data = candidates[0].read_bytes()
            if len(base64.b64encode(data)) > ASR_MAX_BASE64_BYTES: raise AudioTooLargeError("base64 audio exceeds 10MB")
            return data, candidates[0].suffix.lstrip(".").lower(), float(info.get("duration") or 0)
    except TranscriptError:
        raise
    except Exception as exc:
        raise AudioExtractionError(type(exc).__name__) from exc


async def _cache_get(key: str) -> dict | None:
    try:
        import redis.asyncio as redis
        client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            value = await client.get(key)
            return json.loads(value) if value else None
        finally:
            await client.aclose()
    except Exception:
        return None


async def _cache_set(keys: list[str], value: dict) -> None:
    try:
        import redis.asyncio as redis
        client = redis.from_url(REDIS_URL, decode_responses=True)
        try:
            payload = json.dumps(value, ensure_ascii=False)
            for key in keys: await client.set(key, payload, ex=86400 * 30)
        finally:
            await client.aclose()
    except Exception:
        return


async def get_transcript(video_url: str) -> dict | None:
    providers = get_transcript_providers()
    if not providers: return None
    bvid_match = BVID_RE.search(video_url)
    bvid_key = f"transcript:bvid:{bvid_match.group(0)}" if bvid_match else f"transcript:url:{hashlib.sha256(video_url.encode()).hexdigest()[:20]}"
    cached = await _cache_get(bvid_key)
    if cached: return cached
    audio_bytes, audio_format, duration_seconds = await asyncio.to_thread(_extract_audio_sync, video_url)
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()
    hash_key = f"transcript:audio:{audio_hash}"
    cached = await _cache_get(hash_key)
    if cached: return cached
    last_error = None
    for provider in providers:
        try:
            result = await provider.transcribe(audio_bytes=audio_bytes, audio_format=audio_format, audio_hash=audio_hash, video_url=video_url)
            result["asr_seconds"] = duration_seconds
            await _cache_set([bvid_key, hash_key], result)
            return result
        except TranscriptError as exc:
            last_error = exc
    if last_error: raise last_error
    return None
