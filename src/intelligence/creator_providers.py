"""Replaceable public creator-sample providers for P0-C."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

import httpx
from pydantic import Field, model_validator

from src.intelligence.contracts import (
    CreatorSample,
    CreatorSampleStatus,
    CreatorVideo,
    StrictModel,
)
from src.intelligence.providers import CancelCheck, raw_payload_hash


CREATOR_IMPORT_SCHEMA_VERSION = "creator-import.p0.1"
CREATOR_IMPORT_PROVIDER_VERSION = "import-creator.p0-c.1"
BILIBILI_CREATOR_PROVIDER_VERSION = "bilibili-public-creator.p0-c.1"
BILIBILI_NAV_ENDPOINT = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_UPLOAD_ENDPOINT = "https://api.bilibili.com/x/space/wbi/arc/search"
BILIBILI_FOLLOWER_ENDPOINT = "https://api.bilibili.com/x/relation/stat"
LATEST_UPLOAD_LIMIT = 20

_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_int(value: Any) -> int | None:
    if value in {None, ""} or isinstance(value, bool):
        return None
    try:
        parsed = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) or str(value).isdigit():
        parsed = datetime.fromtimestamp(int(value), tz=timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _duration_seconds(value: Any) -> int | None:
    parsed = _safe_int(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip()
    if not text or ":" not in text:
        return None
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return None


class CreatorProviderCapabilities(StrictModel):
    provider_name: str
    provider_version: str
    provider_kind: Literal["development", "import", "fixture", "production"]
    latest_upload_limit: Literal[LATEST_UPLOAD_LIMIT] = LATEST_UPLOAD_LIMIT
    requires_login: bool = False
    uses_personal_cookie: bool = False
    commercial_authorization: Literal["unknown", "development_only", "authorized"] = "unknown"


class CreatorProvider(Protocol):
    @property
    def capabilities(self) -> CreatorProviderCapabilities: ...

    async def fetch_creator(
        self,
        creator_mid: str,
        creator_name: str,
        cancel_check: CancelCheck | None = None,
    ) -> CreatorSample: ...

    async def close(self) -> None: ...


async def _is_cancelled(cancel_check: CancelCheck | None) -> bool:
    return bool(cancel_check and await cancel_check())


class BilibiliDevelopmentCreatorProvider:
    """Low-frequency, unauthenticated adapter for public creator uploads."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        min_interval_seconds: float = 1.0,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0 or min_interval_seconds < 0:
            raise ValueError("creator provider timing settings are invalid")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ViralVideoAgent-Development/0.1)",
                "Referer": "https://space.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
            },
        )
        self._min_interval_seconds = min_interval_seconds
        self._now = now
        self._sleep = sleep
        self._last_request_started: float | None = None
        self._mixin_key: str | None = None
        self._mixin_key_expires_at = 0.0

    @property
    def capabilities(self) -> CreatorProviderCapabilities:
        return CreatorProviderCapabilities(
            provider_name="bilibili-public-creator",
            provider_version=BILIBILI_CREATOR_PROVIDER_VERSION,
            provider_kind="development",
            commercial_authorization="development_only",
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _wait(self, cancel_check: CancelCheck | None) -> None:
        if await _is_cancelled(cancel_check):
            raise asyncio.CancelledError
        if self._last_request_started is None:
            return
        remaining = self._min_interval_seconds - (time.monotonic() - self._last_request_started)
        while remaining > 0:
            if await _is_cancelled(cancel_check):
                raise asyncio.CancelledError
            step = min(0.1, remaining)
            await self._sleep(step)
            remaining -= step

    async def _get(self, url: str, *, params: dict[str, Any] | None, cancel_check: CancelCheck | None):
        await self._wait(cancel_check)
        self._last_request_started = time.monotonic()
        task = asyncio.create_task(self._client.get(url, params=params))
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=0.25)
                if done:
                    break
                if await _is_cancelled(cancel_check):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise asyncio.CancelledError
            return await task
        except BaseException:
            if not task.done():
                task.cancel()
            raise

    async def _wbi_mixin_key(self, cancel_check: CancelCheck | None) -> str:
        if self._mixin_key and time.monotonic() < self._mixin_key_expires_at:
            return self._mixin_key
        response = await self._get(BILIBILI_NAV_ENDPOINT, params=None, cancel_check=cancel_check)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        wbi = data.get("wbi_img") if isinstance(data, dict) else None
        if not isinstance(wbi, dict) or not wbi.get("img_url") or not wbi.get("sub_url"):
            raise ValueError("public nav response omitted WBI material")
        original = PurePosixPath(wbi["img_url"]).stem + PurePosixPath(wbi["sub_url"]).stem
        if len(original) <= max(_MIXIN_KEY_ENC_TAB):
            raise ValueError("public nav response returned invalid WBI material")
        self._mixin_key = "".join(original[index] for index in _MIXIN_KEY_ENC_TAB)[:32]
        self._mixin_key_expires_at = time.monotonic() + 600
        return self._mixin_key

    async def _signed_upload_params(self, creator_mid: str, cancel_check: CancelCheck | None) -> dict[str, Any]:
        mixin_key = await self._wbi_mixin_key(cancel_check)
        params: dict[str, Any] = {
            "mid": creator_mid,
            "pn": 1,
            "ps": LATEST_UPLOAD_LIMIT,
            "order": "pubdate",
            "platform": "web",
            "web_location": "1550101",
            "wts": int(self._now().timestamp()),
        }
        sanitized = {
            key: "".join(char for char in str(value) if char not in "!'()*")
            for key, value in params.items()
        }
        query = urlencode(sorted(sanitized.items()))
        sanitized["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return sanitized

    async def fetch_creator(
        self,
        creator_mid: str,
        creator_name: str,
        cancel_check: CancelCheck | None = None,
    ) -> CreatorSample:
        observed_at = self._now()
        profile_url = f"https://space.bilibili.com/{creator_mid}" if creator_mid else "https://space.bilibili.com/"
        if not creator_mid:
            return self._failure("", creator_name, profile_url, observed_at, CreatorSampleStatus.MISSING, "creator_mid_missing")
        if await _is_cancelled(cancel_check):
            return self._failure(creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.CANCELLED, "cancelled")
        try:
            params = await self._signed_upload_params(creator_mid, cancel_check)
            response = await self._get(BILIBILI_UPLOAD_ENDPOINT, params=params, cancel_check=cancel_check)
            if response.status_code != 200:
                return self._failure(
                    creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.FAILED,
                    f"uploads_http_{response.status_code}",
                )
            payload = response.json()
        except asyncio.CancelledError:
            return self._failure(creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.CANCELLED, "cancelled")
        except (httpx.TimeoutException, asyncio.TimeoutError):
            return self._failure(creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.TIMEOUT, "uploads_timeout")
        except (httpx.RequestError, ValueError, json.JSONDecodeError) as exc:
            return self._failure(
                creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.FAILED,
                f"uploads_{type(exc).__name__}",
            )

        if not isinstance(payload, dict) or payload.get("code") != 0:
            code = payload.get("code") if isinstance(payload, dict) else "invalid"
            return self._failure(
                creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.FAILED,
                f"uploads_provider_{code}",
                raw_hash=raw_payload_hash(payload),
            )
        data = payload.get("data")
        upload_list = data.get("list") if isinstance(data, dict) else None
        raw_uploads = upload_list.get("vlist") if isinstance(upload_list, dict) else None
        if not isinstance(raw_uploads, list):
            return self._failure(
                creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.FAILED,
                "uploads_list_missing",
                raw_hash=raw_payload_hash(payload),
            )

        uploads = [
            video
            for rank, item in enumerate(raw_uploads[:LATEST_UPLOAD_LIMIT], 1)
            if (video := self._normalize_video(item, creator_mid, creator_name, rank, observed_at)) is not None
        ]
        follower_count: int | None = None
        follower_error: str | None = None
        try:
            follower_response = await self._get(
                BILIBILI_FOLLOWER_ENDPOINT,
                params={"vmid": creator_mid},
                cancel_check=cancel_check,
            )
            follower_payload = follower_response.json() if follower_response.status_code == 200 else {}
            follower_data = follower_payload.get("data") if isinstance(follower_payload, dict) else None
            if follower_payload.get("code") == 0 and isinstance(follower_data, dict):
                follower_count = _safe_int(follower_data.get("follower"))
            else:
                follower_error = "follower_unavailable"
        except asyncio.CancelledError:
            return self._failure(creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.CANCELLED, "cancelled")
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            follower_error = "follower_unavailable"

        recent_30d = sum(
            video.published_at is not None and video.published_at >= observed_at - timedelta(days=30)
            for video in uploads
        )
        recent_90d = sum(
            video.published_at is not None and video.published_at >= observed_at - timedelta(days=90)
            for video in uploads
        )
        risk_marked = bool(data.get("is_risk")) if isinstance(data, dict) else False
        if not uploads:
            status = CreatorSampleStatus.PARTIAL
            missing_reason = "no_public_uploads"
        elif follower_error or risk_marked or len(uploads) < len(raw_uploads[:LATEST_UPLOAD_LIMIT]):
            status = CreatorSampleStatus.PARTIAL
            reasons = [value for value in (follower_error, "provider_risk_flag" if risk_marked else None) if value]
            missing_reason = ",".join(reasons) or "some_uploads_failed_normalization"
        else:
            status = CreatorSampleStatus.SUCCESS
            missing_reason = None
        return CreatorSample(
            creator_mid=creator_mid,
            creator_name=creator_name,
            profile_url=profile_url,
            status=status,
            observed_at=observed_at,
            provider_name=self.capabilities.provider_name,
            provider_version=self.capabilities.provider_version,
            provider_kind=self.capabilities.provider_kind,
            source_provider_name=self.capabilities.provider_name,
            source_provider_version=self.capabilities.provider_version,
            source_url=profile_url,
            follower_count=follower_count,
            uploads=uploads,
            recent_30d_upload_count=recent_30d,
            recent_90d_upload_count=recent_90d,
            missing_reason=missing_reason,
            raw_payload_hash=raw_payload_hash(payload),
        )

    def _failure(
        self,
        creator_mid: str,
        creator_name: str,
        profile_url: str,
        observed_at: datetime,
        status: CreatorSampleStatus,
        reason: str,
        *,
        raw_hash: str | None = None,
    ) -> CreatorSample:
        return CreatorSample(
            creator_mid=creator_mid,
            creator_name=creator_name,
            profile_url=profile_url,
            status=status,
            observed_at=observed_at,
            provider_name=self.capabilities.provider_name,
            provider_version=self.capabilities.provider_version,
            provider_kind=self.capabilities.provider_kind,
            source_provider_name=self.capabilities.provider_name,
            source_provider_version=self.capabilities.provider_version,
            source_url=profile_url,
            missing_reason=reason,
            raw_payload_hash=raw_hash,
        )

    def _normalize_video(
        self,
        item: Any,
        creator_mid: str,
        creator_name: str,
        rank: int,
        observed_at: datetime,
    ) -> CreatorVideo | None:
        if not isinstance(item, dict):
            return None
        bvid = str(item.get("bvid") or "").strip()
        title = str(item.get("title") or "").strip()
        if not bvid or not title:
            return None
        published_at = _parse_datetime(item.get("created"))
        fields = {
            "description": str(item.get("description") or "").strip() or None,
            "tags": [],
            "partition": str(item.get("typeid") or "").strip() or None,
            "published_at": published_at,
            "duration_seconds": _duration_seconds(item.get("length")),
            "cover_url": str(item.get("pic") or "").strip() or None,
            "view": _safe_int(item.get("play")),
            "like": None,
            "coin": None,
            "favorite": None,
            "reply": _safe_int(item.get("comment")),
            "share": None,
            "danmaku": _safe_int(item.get("video_review")),
        }
        missing_fields = [name for name, value in fields.items() if value is None or value == []]
        return CreatorVideo(
            bvid=bvid,
            creator_mid=creator_mid,
            creator_name=creator_name or str(item.get("author") or "").strip(),
            title=title,
            source_url=f"https://www.bilibili.com/video/{bvid}",
            observed_at=observed_at,
            provider_name=self.capabilities.provider_name,
            provider_version=self.capabilities.provider_version,
            sample_rank=rank,
            raw_payload_hash=raw_payload_hash(item),
            missing_fields=missing_fields,
            **fields,
        )


class CreatorImportVideoPayload(StrictModel):
    bvid: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    partition: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    cover_url: str | None = None
    view: int | None = Field(default=None, ge=0)
    like: int | None = Field(default=None, ge=0)
    coin: int | None = Field(default=None, ge=0)
    favorite: int | None = Field(default=None, ge=0)
    reply: int | None = Field(default=None, ge=0)
    share: int | None = Field(default=None, ge=0)
    danmaku: int | None = Field(default=None, ge=0)
    missing_fields: list[str] = Field(default_factory=list)


class CreatorImportEntry(StrictModel):
    creator_mid: str
    creator_name: str
    profile_url: str
    status: CreatorSampleStatus
    observed_at: datetime
    source_url: str
    source_provider_name: str
    source_provider_version: str
    follower_count: int | None = Field(default=None, ge=0)
    uploads: list[CreatorImportVideoPayload] = Field(default_factory=list, max_length=LATEST_UPLOAD_LIMIT)
    missing_reason: str | None = None
    raw_payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_status(self) -> "CreatorImportEntry":
        if self.status == CreatorSampleStatus.SUCCESS and not self.uploads:
            raise ValueError("successful imported creator samples require uploads")
        if self.status in {
            CreatorSampleStatus.MISSING,
            CreatorSampleStatus.FAILED,
            CreatorSampleStatus.TIMEOUT,
            CreatorSampleStatus.CANCELLED,
        } and self.uploads:
            raise ValueError("unsuccessful imported creator samples cannot contain uploads")
        if self.status != CreatorSampleStatus.SUCCESS and not self.missing_reason:
            raise ValueError("non-success imported creator samples require missing_reason")
        return self


class CreatorImportPayload(StrictModel):
    schema_version: str = Field(default=CREATOR_IMPORT_SCHEMA_VERSION, pattern=r"^creator-import\.p0\.1$")
    source_name: str = Field(min_length=1, max_length=120)
    provider_version: str = Field(default=CREATOR_IMPORT_PROVIDER_VERSION, min_length=1, max_length=40)
    creators: list[CreatorImportEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_creators(self) -> "CreatorImportPayload":
        mids = [creator.creator_mid for creator in self.creators]
        if len(mids) != len(set(mids)):
            raise ValueError("creator import MIDs must be unique")
        return self


CREATOR_CSV_COLUMNS = {
    "source_name", "provider_version", "creator_mid", "creator_name", "profile_url", "status",
    "observed_at", "source_url", "source_provider_name", "source_provider_version", "follower_count",
    "missing_reason", "raw_payload_hash", "bvid", "title", "video_source_url", "description", "tags",
    "partition", "published_at", "duration_seconds", "cover_url", "view", "like", "coin", "favorite",
    "reply", "share", "danmaku", "missing_fields",
}
CREATOR_CSV_REQUIRED = {
    "source_name", "provider_version", "creator_mid", "creator_name", "profile_url", "status",
    "observed_at", "source_url", "source_provider_name", "source_provider_version",
}


class ImportCreatorProvider:
    def __init__(self, payload: CreatorImportPayload, *, fixture: bool = False) -> None:
        self.payload = payload
        self._fixture = fixture
        self._creators = {creator.creator_mid: creator for creator in payload.creators}

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> "ImportCreatorProvider":
        value = json.loads(payload) if isinstance(payload, str) else payload
        return cls(CreatorImportPayload.model_validate(value))

    @classmethod
    def from_csv(cls, payload: str) -> "ImportCreatorProvider":
        reader = csv.DictReader(StringIO(payload))
        headers = set(reader.fieldnames or [])
        missing = CREATOR_CSV_REQUIRED - headers
        unknown = headers - CREATOR_CSV_COLUMNS
        if missing:
            raise ValueError(f"creator CSV missing required columns: {', '.join(sorted(missing))}")
        if unknown:
            raise ValueError(f"creator CSV contains unknown columns: {', '.join(sorted(unknown))}")
        rows = list(reader)
        if not rows:
            raise ValueError("creator CSV import requires at least one row")
        metadata = {name: (rows[0].get(name) or "").strip() for name in ("source_name", "provider_version")}
        if any((row.get(name) or "").strip() != metadata[name] for row in rows for name in metadata):
            raise ValueError("creator CSV source metadata must be identical across rows")
        grouped: dict[str, list[dict[str, str]]] = {}
        for row in rows:
            grouped.setdefault((row.get("creator_mid") or "").strip(), []).append(row)
        creators = []
        for mid, creator_rows in grouped.items():
            first = creator_rows[0]
            fixed_names = (
                "creator_name", "profile_url", "status", "observed_at", "source_url",
                "source_provider_name", "source_provider_version", "follower_count", "missing_reason",
                "raw_payload_hash",
            )
            if any((row.get(name) or "").strip() != (first.get(name) or "").strip() for row in creator_rows for name in fixed_names):
                raise ValueError("creator CSV metadata must be identical within one MID")
            uploads = []
            for row in creator_rows:
                bvid = (row.get("bvid") or "").strip()
                if not bvid:
                    continue
                uploads.append({
                    "bvid": bvid,
                    "title": (row.get("title") or "").strip(),
                    "source_url": (row.get("video_source_url") or "").strip(),
                    "description": (row.get("description") or "").strip() or None,
                    "tags": [value.strip() for value in (row.get("tags") or "").split("|") if value.strip()],
                    "partition": (row.get("partition") or "").strip() or None,
                    "published_at": _parse_datetime(row.get("published_at")),
                    "duration_seconds": _duration_seconds(row.get("duration_seconds")),
                    "cover_url": (row.get("cover_url") or "").strip() or None,
                    "view": _safe_int(row.get("view")),
                    "like": _safe_int(row.get("like")),
                    "coin": _safe_int(row.get("coin")),
                    "favorite": _safe_int(row.get("favorite")),
                    "reply": _safe_int(row.get("reply")),
                    "share": _safe_int(row.get("share")),
                    "danmaku": _safe_int(row.get("danmaku")),
                    "missing_fields": [value.strip() for value in (row.get("missing_fields") or "").split("|") if value.strip()],
                })
            creators.append({
                "creator_mid": mid,
                "creator_name": (first.get("creator_name") or "").strip(),
                "profile_url": (first.get("profile_url") or "").strip(),
                "status": (first.get("status") or "").strip(),
                "observed_at": _parse_datetime(first.get("observed_at")),
                "source_url": (first.get("source_url") or "").strip(),
                "source_provider_name": (first.get("source_provider_name") or "").strip(),
                "source_provider_version": (first.get("source_provider_version") or "").strip(),
                "follower_count": _safe_int(first.get("follower_count")),
                "missing_reason": (first.get("missing_reason") or "").strip() or None,
                "raw_payload_hash": (first.get("raw_payload_hash") or "").strip() or None,
                "uploads": uploads,
            })
        return cls(CreatorImportPayload.model_validate({**metadata, "creators": creators}))

    @property
    def capabilities(self) -> CreatorProviderCapabilities:
        return CreatorProviderCapabilities(
            provider_name="fixture" if self._fixture else "import",
            provider_version=self.payload.provider_version,
            provider_kind="fixture" if self._fixture else "import",
            commercial_authorization="development_only" if self._fixture else "unknown",
        )

    async def close(self) -> None:
        return None

    async def fetch_creator(
        self,
        creator_mid: str,
        creator_name: str,
        cancel_check: CancelCheck | None = None,
    ) -> CreatorSample:
        now = utcnow()
        if await _is_cancelled(cancel_check):
            return self._missing(creator_mid, creator_name, now, CreatorSampleStatus.CANCELLED, "cancelled")
        entry = self._creators.get(creator_mid)
        if entry is None:
            return self._missing(creator_mid, creator_name, now, CreatorSampleStatus.MISSING, "creator_absent_from_import")
        uploads = []
        for rank, item in enumerate(entry.uploads, 1):
            payload = item.model_dump()
            uploads.append(CreatorVideo(
                **payload,
                creator_mid=entry.creator_mid,
                creator_name=entry.creator_name,
                observed_at=entry.observed_at,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                sample_rank=rank,
                raw_payload_hash=raw_payload_hash(payload),
            ))
        recent_30d = sum(
            video.published_at is not None and video.published_at >= entry.observed_at - timedelta(days=30)
            for video in uploads
        )
        recent_90d = sum(
            video.published_at is not None and video.published_at >= entry.observed_at - timedelta(days=90)
            for video in uploads
        )
        return CreatorSample(
            creator_mid=entry.creator_mid,
            creator_name=entry.creator_name,
            profile_url=entry.profile_url,
            status=entry.status,
            observed_at=entry.observed_at,
            provider_name=self.capabilities.provider_name,
            provider_version=self.capabilities.provider_version,
            provider_kind=self.capabilities.provider_kind,
            source_provider_name=entry.source_provider_name,
            source_provider_version=entry.source_provider_version,
            source_url=entry.source_url,
            follower_count=entry.follower_count,
            uploads=uploads,
            recent_30d_upload_count=recent_30d,
            recent_90d_upload_count=recent_90d,
            missing_reason=entry.missing_reason,
            raw_payload_hash=entry.raw_payload_hash or raw_payload_hash(entry.model_dump(mode="json")),
        )

    def _missing(
        self,
        creator_mid: str,
        creator_name: str,
        observed_at: datetime,
        status: CreatorSampleStatus,
        reason: str,
    ) -> CreatorSample:
        profile_url = f"https://space.bilibili.com/{creator_mid}" if creator_mid else "https://space.bilibili.com/"
        return CreatorSample(
            creator_mid=creator_mid,
            creator_name=creator_name,
            profile_url=profile_url,
            status=status,
            observed_at=observed_at,
            provider_name=self.capabilities.provider_name,
            provider_version=self.capabilities.provider_version,
            provider_kind=self.capabilities.provider_kind,
            source_provider_name=self.payload.source_name,
            source_provider_version=self.payload.provider_version,
            source_url=profile_url,
            missing_reason=reason,
        )


class FixtureCreatorProvider(ImportCreatorProvider):
    def __init__(self, payload: CreatorImportPayload) -> None:
        super().__init__(payload, fixture=True)

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> "FixtureCreatorProvider":
        value = json.loads(payload) if isinstance(payload, str) else payload
        return cls(CreatorImportPayload.model_validate(value))


def creator_provider_capability_catalog() -> list[dict[str, Any]]:
    return [
        CreatorProviderCapabilities(
            provider_name="bilibili-public-creator",
            provider_version=BILIBILI_CREATOR_PROVIDER_VERSION,
            provider_kind="development",
            commercial_authorization="development_only",
        ).model_dump(mode="json"),
        CreatorProviderCapabilities(
            provider_name="import",
            provider_version=CREATOR_IMPORT_PROVIDER_VERSION,
            provider_kind="import",
        ).model_dump(mode="json"),
        CreatorProviderCapabilities(
            provider_name="fixture",
            provider_version=CREATOR_IMPORT_PROVIDER_VERSION,
            provider_kind="fixture",
            commercial_authorization="development_only",
        ).model_dump(mode="json"),
    ]
