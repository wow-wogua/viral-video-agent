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
    CreatorRequestAttempt,
    CreatorRequestAudit,
    CreatorSample,
    CreatorSampleStatus,
    CreatorVideo,
    StrictModel,
)
from src.intelligence.providers import CancelCheck, raw_payload_hash


CREATOR_IMPORT_SCHEMA_VERSION = "creator-import.p0.1"
CREATOR_IMPORT_PROVIDER_VERSION = "import-creator.p0-c.2"
BILIBILI_CREATOR_PROVIDER_VERSION = "bilibili-public-creator.p0-c.2"
BILIBILI_NAV_ENDPOINT = "https://api.bilibili.com/x/web-interface/nav"
BILIBILI_UPLOAD_ENDPOINT = "https://api.bilibili.com/x/space/wbi/arc/search"
BILIBILI_FOLLOWER_ENDPOINT = "https://api.bilibili.com/x/relation/stat"
LATEST_UPLOAD_LIMIT = 20
CREATOR_MAX_RETRIES = 2
CREATOR_BACKOFF_BASE_SECONDS = 0.5
CREATOR_RISK_CONTROL_THRESHOLD = 3
CREATOR_RISK_CONTROL_COOLDOWN_SECONDS = 15 * 60
CREATOR_RISK_CONTROL_HTTP_STATUSES = frozenset({412})
CREATOR_RISK_CONTROL_PROVIDER_CODES = frozenset({-412, -352, -401, -403})
CREATOR_RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})

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


class _CreatorRequestFailure(RuntimeError):
    def __init__(
        self,
        classification: str,
        reason: str,
        *,
        risk_control: bool = False,
        raw_hash: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.classification = classification
        self.reason = reason
        self.risk_control = risk_control
        self.raw_hash = raw_hash


class BilibiliDevelopmentCreatorProvider:
    """Low-frequency, unauthenticated adapter for public creator uploads."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = CREATOR_MAX_RETRIES,
        backoff_base_seconds: float = CREATOR_BACKOFF_BASE_SECONDS,
        min_interval_seconds: float = 1.0,
        now: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not 0 <= max_retries <= 4:
            raise ValueError("creator provider max_retries must be between 0 and 4")
        if timeout_seconds <= 0 or backoff_base_seconds < 0 or min_interval_seconds < 0:
            raise ValueError("creator provider timing settings are invalid")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ViralVideoAgent-Development/0.1)",
                "Referer": "https://space.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
            },
        )
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._min_interval_seconds = min_interval_seconds
        self._now = now
        self._sleep = sleep
        self._last_request_started: float | None = None
        self._mixin_key: str | None = None
        self._mixin_key_expires_at = 0.0
        self._consecutive_risk_control_count = 0
        self._circuit_opened_at: datetime | None = None

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

    @property
    def circuit_open(self) -> bool:
        return self._circuit_opened_at is not None

    @property
    def consecutive_risk_control_count(self) -> int:
        return self._consecutive_risk_control_count

    def circuit_snapshot(self) -> dict[str, Any]:
        cooldown_until = (
            self._circuit_opened_at + timedelta(seconds=CREATOR_RISK_CONTROL_COOLDOWN_SECONDS)
            if self._circuit_opened_at
            else None
        )
        return {
            "state": "open" if self.circuit_open else "closed",
            "consecutive_risk_control_count": self._consecutive_risk_control_count,
            "threshold": CREATOR_RISK_CONTROL_THRESHOLD,
            "opened_at": self._circuit_opened_at,
            "cooldown_seconds": CREATOR_RISK_CONTROL_COOLDOWN_SECONDS,
            "cooldown_until": cooldown_until,
            "automatic_resume": False,
        }

    def restore_risk_control_state(
        self,
        consecutive_count: int,
        *,
        opened_at: datetime | str | None = None,
    ) -> None:
        if consecutive_count < 0:
            raise ValueError("consecutive risk-control count cannot be negative")
        self._consecutive_risk_control_count = consecutive_count
        parsed_opened_at = _parse_datetime(opened_at)
        if consecutive_count >= CREATOR_RISK_CONTROL_THRESHOLD:
            self._circuit_opened_at = parsed_opened_at or self._now()
        elif parsed_opened_at is not None:
            raise ValueError("open circuit state requires the fixed risk-control threshold")

    async def _sleep_with_cancellation(
        self,
        seconds: float,
        cancel_check: CancelCheck | None,
    ) -> None:
        remaining = max(0.0, seconds)
        while remaining > 0:
            if await _is_cancelled(cancel_check):
                raise asyncio.CancelledError
            step = min(0.1, remaining)
            await self._sleep(step)
            remaining -= step

    async def _wait(self, cancel_check: CancelCheck | None) -> float:
        if await _is_cancelled(cancel_check):
            raise asyncio.CancelledError
        if self._last_request_started is None:
            return 0.0
        remaining = self._min_interval_seconds - (time.monotonic() - self._last_request_started)
        waited = max(0.0, remaining)
        if waited:
            await self._sleep_with_cancellation(waited, cancel_check)
        return waited

    async def _get(self, url: str, *, params: dict[str, Any] | None, cancel_check: CancelCheck | None):
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

    def _append_attempt(
        self,
        attempts: list[CreatorRequestAttempt],
        *,
        operation: Literal["wbi_nav", "uploads", "follower"],
        attempt_number: int,
        started_at: datetime,
        rate_limit_wait_seconds: float,
        retry_backoff_seconds: float,
        classification: str,
        http_status: int | None = None,
        provider_code: int | None = None,
        error_type: str | None = None,
    ) -> None:
        attempts.append(CreatorRequestAttempt(
            operation=operation,
            attempt_number=attempt_number,
            started_at=started_at,
            completed_at=self._now(),
            rate_limit_wait_seconds=rate_limit_wait_seconds,
            retry_backoff_seconds=retry_backoff_seconds,
            classification=classification,
            http_status=http_status,
            provider_code=provider_code,
            error_type=error_type,
        ))

    async def _request_json(
        self,
        operation: Literal["wbi_nav", "uploads", "follower"],
        url: str,
        *,
        params: dict[str, Any] | None,
        accepted_provider_codes: set[int] | None,
        attempts: list[CreatorRequestAttempt],
        cancel_check: CancelCheck | None,
    ) -> dict[str, Any]:
        for attempt_index in range(self._max_retries + 1):
            backoff_seconds = self._backoff_base_seconds * (2 ** (attempt_index - 1)) if attempt_index else 0.0
            if backoff_seconds:
                await self._sleep_with_cancellation(backoff_seconds, cancel_check)
            rate_limit_wait_seconds = await self._wait(cancel_check)
            started_at = self._now()
            self._last_request_started = time.monotonic()
            try:
                response = await self._get(url, params=params, cancel_check=cancel_check)
            except asyncio.CancelledError:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="cancelled",
                )
                raise
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="timeout",
                    error_type=type(exc).__name__,
                )
                if attempt_index < self._max_retries:
                    continue
                raise _CreatorRequestFailure("timeout", f"{operation}_timeout") from exc
            except httpx.RequestError as exc:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="connection_error",
                    error_type=type(exc).__name__,
                )
                if attempt_index < self._max_retries:
                    continue
                raise _CreatorRequestFailure("connection_error", f"{operation}_{type(exc).__name__}") from exc

            status_code = response.status_code
            if status_code in CREATOR_RISK_CONTROL_HTTP_STATUSES:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="risk_control",
                    http_status=status_code,
                )
                raise _CreatorRequestFailure(
                    "risk_control",
                    f"{operation}_http_{status_code}_risk_control",
                    risk_control=True,
                )
            if status_code in CREATOR_RETRYABLE_HTTP_STATUSES:
                classification = "http_429" if status_code == 429 else "http_5xx"
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification=classification,
                    http_status=status_code,
                )
                if attempt_index < self._max_retries:
                    continue
                raise _CreatorRequestFailure(classification, f"{operation}_http_{status_code}")
            if status_code != 200:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="http_error",
                    http_status=status_code,
                )
                raise _CreatorRequestFailure("http_error", f"{operation}_http_{status_code}")
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="invalid_json",
                    http_status=status_code,
                    error_type=type(exc).__name__,
                )
                raise _CreatorRequestFailure("invalid_json", f"{operation}_invalid_json") from exc
            if not isinstance(payload, dict):
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="invalid_payload",
                    http_status=status_code,
                )
                raise _CreatorRequestFailure(
                    "invalid_payload",
                    f"{operation}_invalid_payload",
                    raw_hash=raw_payload_hash(payload),
                )
            code = payload.get("code") if isinstance(payload.get("code"), int) else None
            if code in CREATOR_RISK_CONTROL_PROVIDER_CODES:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="risk_control",
                    http_status=status_code,
                    provider_code=code,
                )
                raise _CreatorRequestFailure(
                    "risk_control",
                    f"{operation}_provider_{code}_risk_control",
                    risk_control=True,
                    raw_hash=raw_payload_hash(payload),
                )
            if accepted_provider_codes is not None and code not in accepted_provider_codes:
                self._append_attempt(
                    attempts,
                    operation=operation,
                    attempt_number=attempt_index + 1,
                    started_at=started_at,
                    rate_limit_wait_seconds=rate_limit_wait_seconds,
                    retry_backoff_seconds=backoff_seconds,
                    classification="provider_error",
                    http_status=status_code,
                    provider_code=code,
                )
                raise _CreatorRequestFailure(
                    "provider_error",
                    f"{operation}_provider_{code if code is not None else 'invalid'}",
                    raw_hash=raw_payload_hash(payload),
                )
            self._append_attempt(
                attempts,
                operation=operation,
                attempt_number=attempt_index + 1,
                started_at=started_at,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
                retry_backoff_seconds=backoff_seconds,
                classification="success",
                http_status=status_code,
                provider_code=code,
            )
            return payload
        raise AssertionError("bounded creator request loop exhausted unexpectedly")

    async def _wbi_mixin_key(
        self,
        cancel_check: CancelCheck | None,
        attempts: list[CreatorRequestAttempt],
    ) -> str:
        if self._mixin_key and time.monotonic() < self._mixin_key_expires_at:
            return self._mixin_key
        payload = await self._request_json(
            "wbi_nav",
            BILIBILI_NAV_ENDPOINT,
            params=None,
            accepted_provider_codes=None,
            attempts=attempts,
            cancel_check=cancel_check,
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        wbi = data.get("wbi_img") if isinstance(data, dict) else None
        if not isinstance(wbi, dict) or not wbi.get("img_url") or not wbi.get("sub_url"):
            raise _CreatorRequestFailure(
                "invalid_payload",
                "wbi_nav_material_missing",
                raw_hash=raw_payload_hash(payload),
            )
        original = PurePosixPath(wbi["img_url"]).stem + PurePosixPath(wbi["sub_url"]).stem
        if len(original) <= max(_MIXIN_KEY_ENC_TAB):
            raise _CreatorRequestFailure(
                "invalid_payload",
                "wbi_nav_material_invalid",
                raw_hash=raw_payload_hash(payload),
            )
        self._mixin_key = "".join(original[index] for index in _MIXIN_KEY_ENC_TAB)[:32]
        self._mixin_key_expires_at = time.monotonic() + 600
        return self._mixin_key

    async def _signed_upload_params(
        self,
        creator_mid: str,
        cancel_check: CancelCheck | None,
        attempts: list[CreatorRequestAttempt],
    ) -> dict[str, Any]:
        mixin_key = await self._wbi_mixin_key(cancel_check, attempts)
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

    def _record_final_outcome(self, *, risk_control: bool, observed_at: datetime) -> Literal["closed", "opened"]:
        if not risk_control:
            self._consecutive_risk_control_count = 0
            return "closed"
        self._consecutive_risk_control_count += 1
        if self._consecutive_risk_control_count >= CREATOR_RISK_CONTROL_THRESHOLD and not self.circuit_open:
            self._circuit_opened_at = observed_at
            return "opened"
        return "closed"

    def _request_audit(
        self,
        attempts: list[CreatorRequestAttempt],
        final_classification: str,
        *,
        risk_control: bool,
        circuit_state: Literal["closed", "opened", "open"],
    ) -> CreatorRequestAudit:
        return CreatorRequestAudit(
            attempt_count=len(attempts),
            retry_count=sum(attempt.attempt_number > 1 for attempt in attempts),
            total_rate_limit_wait_seconds=sum(attempt.rate_limit_wait_seconds for attempt in attempts),
            total_backoff_seconds=sum(attempt.retry_backoff_seconds for attempt in attempts),
            final_classification=final_classification,
            risk_control=risk_control,
            consecutive_risk_control_count=self._consecutive_risk_control_count,
            circuit_state=circuit_state,
            circuit_opened_at=self._circuit_opened_at,
            cooldown_seconds=CREATOR_RISK_CONTROL_COOLDOWN_SECONDS if self.circuit_open else 0,
            attempts=attempts,
        )

    def not_attempted_sample(self, creator_mid: str, creator_name: str) -> CreatorSample:
        observed_at = self._now()
        profile_url = f"https://space.bilibili.com/{creator_mid}" if creator_mid else "https://space.bilibili.com/"
        return self._failure(
            creator_mid,
            creator_name,
            profile_url,
            observed_at,
            CreatorSampleStatus.MISSING,
            "not_attempted_due_to_risk_control",
            request_audit=self._request_audit(
                [],
                "circuit_open",
                risk_control=True,
                circuit_state="open",
            ),
        )

    async def fetch_creator(
        self,
        creator_mid: str,
        creator_name: str,
        cancel_check: CancelCheck | None = None,
    ) -> CreatorSample:
        observed_at = self._now()
        profile_url = f"https://space.bilibili.com/{creator_mid}" if creator_mid else "https://space.bilibili.com/"
        if not creator_mid:
            return self._failure(
                "",
                creator_name,
                profile_url,
                observed_at,
                CreatorSampleStatus.MISSING,
                "creator_mid_missing",
                request_audit=self._request_audit(
                    [], "missing_mid", risk_control=False, circuit_state="open" if self.circuit_open else "closed"
                ),
            )
        if self.circuit_open:
            return self.not_attempted_sample(creator_mid, creator_name)
        if await _is_cancelled(cancel_check):
            return self._failure(
                creator_mid,
                creator_name,
                profile_url,
                observed_at,
                CreatorSampleStatus.CANCELLED,
                "cancelled",
                request_audit=self._request_audit(
                    [], "cancelled", risk_control=False, circuit_state="closed"
                ),
            )
        attempts: list[CreatorRequestAttempt] = []
        try:
            params = await self._signed_upload_params(creator_mid, cancel_check, attempts)
            payload = await self._request_json(
                "uploads",
                BILIBILI_UPLOAD_ENDPOINT,
                params=params,
                accepted_provider_codes={0},
                attempts=attempts,
                cancel_check=cancel_check,
            )
        except asyncio.CancelledError:
            self._record_final_outcome(risk_control=False, observed_at=observed_at)
            return self._failure(
                creator_mid,
                creator_name,
                profile_url,
                observed_at,
                CreatorSampleStatus.CANCELLED,
                "cancelled",
                request_audit=self._request_audit(
                    attempts, "cancelled", risk_control=False, circuit_state="closed"
                ),
            )
        except _CreatorRequestFailure as exc:
            circuit_state = self._record_final_outcome(risk_control=exc.risk_control, observed_at=observed_at)
            status = CreatorSampleStatus.TIMEOUT if exc.classification == "timeout" else CreatorSampleStatus.FAILED
            return self._failure(
                creator_mid,
                creator_name,
                profile_url,
                observed_at,
                status,
                exc.reason,
                raw_hash=exc.raw_hash,
                request_audit=self._request_audit(
                    attempts,
                    exc.classification,
                    risk_control=exc.risk_control,
                    circuit_state=circuit_state,
                ),
            )
        data = payload.get("data")
        upload_list = data.get("list") if isinstance(data, dict) else None
        raw_uploads = upload_list.get("vlist") if isinstance(upload_list, dict) else None
        if not isinstance(raw_uploads, list):
            self._record_final_outcome(risk_control=False, observed_at=observed_at)
            return self._failure(
                creator_mid, creator_name, profile_url, observed_at, CreatorSampleStatus.FAILED,
                "uploads_list_missing",
                raw_hash=raw_payload_hash(payload),
                request_audit=self._request_audit(
                    attempts, "invalid_payload", risk_control=False, circuit_state="closed"
                ),
            )

        uploads = [
            video
            for rank, item in enumerate(raw_uploads[:LATEST_UPLOAD_LIMIT], 1)
            if (video := self._normalize_video(item, creator_mid, creator_name, rank, observed_at)) is not None
        ]
        follower_count: int | None = None
        follower_error: str | None = None
        risk_marked = bool(data.get("is_risk")) if isinstance(data, dict) else False
        if risk_marked:
            circuit_state = self._record_final_outcome(risk_control=True, observed_at=observed_at)
            return CreatorSample(
                creator_mid=creator_mid,
                creator_name=creator_name,
                profile_url=profile_url,
                status=CreatorSampleStatus.PARTIAL,
                observed_at=observed_at,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                provider_kind=self.capabilities.provider_kind,
                source_provider_name=self.capabilities.provider_name,
                source_provider_version=self.capabilities.provider_version,
                source_url=profile_url,
                uploads=uploads,
                recent_30d_upload_count=sum(
                    video.published_at is not None and video.published_at >= observed_at - timedelta(days=30)
                    for video in uploads
                ),
                recent_90d_upload_count=sum(
                    video.published_at is not None and video.published_at >= observed_at - timedelta(days=90)
                    for video in uploads
                ),
                missing_reason="provider_risk_flag",
                raw_payload_hash=raw_payload_hash(payload),
                request_audit=self._request_audit(
                    attempts, "risk_control", risk_control=True, circuit_state=circuit_state
                ),
            )
        try:
            follower_payload = await self._request_json(
                "follower",
                BILIBILI_FOLLOWER_ENDPOINT,
                params={"vmid": creator_mid},
                accepted_provider_codes={0},
                attempts=attempts,
                cancel_check=cancel_check,
            )
            follower_data = follower_payload.get("data") if isinstance(follower_payload, dict) else None
            if isinstance(follower_data, dict):
                follower_count = _safe_int(follower_data.get("follower"))
            else:
                follower_error = "follower_unavailable"
        except asyncio.CancelledError:
            self._record_final_outcome(risk_control=False, observed_at=observed_at)
            return self._failure(
                creator_mid,
                creator_name,
                profile_url,
                observed_at,
                CreatorSampleStatus.CANCELLED,
                "cancelled",
                request_audit=self._request_audit(
                    attempts, "cancelled", risk_control=False, circuit_state="closed"
                ),
            )
        except _CreatorRequestFailure as exc:
            if exc.risk_control:
                circuit_state = self._record_final_outcome(risk_control=True, observed_at=observed_at)
                follower_error = exc.reason
                final_classification = "risk_control"
            else:
                circuit_state = self._record_final_outcome(risk_control=False, observed_at=observed_at)
                follower_error = "follower_unavailable"
                final_classification = "partial"
        else:
            circuit_state = self._record_final_outcome(risk_control=False, observed_at=observed_at)
            final_classification = "success"

        recent_30d = sum(
            video.published_at is not None and video.published_at >= observed_at - timedelta(days=30)
            for video in uploads
        )
        recent_90d = sum(
            video.published_at is not None and video.published_at >= observed_at - timedelta(days=90)
            for video in uploads
        )
        if not uploads:
            status = CreatorSampleStatus.PARTIAL
            missing_reason = "no_public_uploads"
            if final_classification == "success":
                final_classification = "partial"
        elif follower_error or len(uploads) < len(raw_uploads[:LATEST_UPLOAD_LIMIT]):
            status = CreatorSampleStatus.PARTIAL
            reasons = [value for value in (follower_error,) if value]
            missing_reason = ",".join(reasons) or "some_uploads_failed_normalization"
            if final_classification == "success":
                final_classification = "partial"
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
            request_audit=self._request_audit(
                attempts,
                final_classification,
                risk_control=final_classification == "risk_control",
                circuit_state=circuit_state,
            ),
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
        request_audit: CreatorRequestAudit | None = None,
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
            request_audit=request_audit,
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
    request_audit: CreatorRequestAudit | None = None

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


def creator_scope_hash(creator_mids: list[str] | set[str] | tuple[str, ...]) -> str:
    normalized = "\n".join(sorted({str(mid).strip() for mid in creator_mids if str(mid).strip()}))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class CreatorImportCoverageReport(StrictModel):
    expected_count: int = Field(ge=0)
    imported_count: int = Field(ge=0)
    covered_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    unexpected_count: int = Field(ge=0)
    exact_coverage: bool
    source_basis: Literal[
        "unspecified",
        "public_unauthenticated_capture",
        "user_authorized_export",
        "authorized_supplier_export",
        "fixture",
    ]
    authorization_status: Literal[
        "unknown",
        "development_only",
        "user_attested",
        "written_authorization",
        "fixture",
    ]
    source_declared: bool
    authorization_documented: bool


class CreatorImportPayload(StrictModel):
    schema_version: str = Field(default=CREATOR_IMPORT_SCHEMA_VERSION, pattern=r"^creator-import\.p0\.1$")
    source_name: str = Field(min_length=1, max_length=120)
    provider_version: str = Field(default=CREATOR_IMPORT_PROVIDER_VERSION, min_length=1, max_length=40)
    source_basis: Literal[
        "unspecified",
        "public_unauthenticated_capture",
        "user_authorized_export",
        "authorized_supplier_export",
        "fixture",
    ] = "unspecified"
    authorization_status: Literal[
        "unknown",
        "development_only",
        "user_attested",
        "written_authorization",
        "fixture",
    ] = "unknown"
    capture_round_id: str | None = Field(default=None, min_length=1, max_length=120)
    coverage_scope_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    coverage_target_count: int | None = Field(default=None, ge=1)
    creators: list[CreatorImportEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_creators(self) -> "CreatorImportPayload":
        mids = [creator.creator_mid for creator in self.creators]
        if len(mids) != len(set(mids)):
            raise ValueError("creator import MIDs must be unique")
        coverage_declared = self.coverage_scope_sha256 is not None or self.coverage_target_count is not None
        if coverage_declared and (self.coverage_scope_sha256 is None or self.coverage_target_count is None):
            raise ValueError("creator import coverage hash and target count must be declared together")
        if coverage_declared:
            if self.coverage_target_count != len(mids):
                raise ValueError("creator import coverage target count must match creator records")
            if self.coverage_scope_sha256 != creator_scope_hash(mids):
                raise ValueError("creator import coverage hash does not match creator records")
        if self.capture_round_id and not coverage_declared:
            raise ValueError("creator import capture rounds require declared coverage")
        if self.source_basis == "public_unauthenticated_capture":
            if self.authorization_status != "development_only":
                raise ValueError("public unauthenticated capture must remain development_only")
            if not self.capture_round_id:
                raise ValueError("public unauthenticated capture requires capture_round_id")
        elif self.source_basis == "user_authorized_export":
            if self.authorization_status not in {"user_attested", "written_authorization"}:
                raise ValueError("user-authorized exports require attested or written authorization")
        elif self.source_basis == "authorized_supplier_export":
            if self.authorization_status != "written_authorization":
                raise ValueError("supplier exports require written authorization")
        elif self.source_basis == "fixture" and self.authorization_status != "fixture":
            raise ValueError("fixture imports require fixture authorization status")
        elif self.source_basis == "unspecified" and self.authorization_status != "unknown":
            raise ValueError("unspecified imports cannot claim authorization")
        return self


CREATOR_CSV_COLUMNS = {
    "source_name", "provider_version", "creator_mid", "creator_name", "profile_url", "status",
    "observed_at", "source_url", "source_provider_name", "source_provider_version", "follower_count",
    "missing_reason", "raw_payload_hash", "bvid", "title", "video_source_url", "description", "tags",
    "partition", "published_at", "duration_seconds", "cover_url", "view", "like", "coin", "favorite",
    "reply", "share", "danmaku", "missing_fields", "source_basis", "authorization_status",
    "capture_round_id", "coverage_scope_sha256", "coverage_target_count",
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
        metadata_names = ["source_name", "provider_version"]
        metadata_names.extend(
            name
            for name in (
                "source_basis", "authorization_status", "capture_round_id",
                "coverage_scope_sha256", "coverage_target_count",
            )
            if name in headers
        )
        metadata = {name: (rows[0].get(name) or "").strip() for name in metadata_names}
        if any((row.get(name) or "").strip() != metadata[name] for row in rows for name in metadata):
            raise ValueError("creator CSV source metadata must be identical across rows")
        metadata = {name: value for name, value in metadata.items() if value}
        if "coverage_target_count" in metadata:
            metadata["coverage_target_count"] = int(metadata["coverage_target_count"])
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

    def validate_coverage(
        self,
        expected_creator_mids: set[str] | list[str] | tuple[str, ...],
        *,
        require_exact: bool = True,
        require_source_declared: bool = False,
        require_authorized: bool = False,
    ) -> CreatorImportCoverageReport:
        expected = {str(mid).strip() for mid in expected_creator_mids if str(mid).strip()}
        imported = set(self._creators)
        covered = expected.intersection(imported)
        missing_count = len(expected - imported)
        unexpected_count = len(imported - expected)
        source_declared = self.payload.source_basis != "unspecified"
        authorization_documented = self.payload.authorization_status in {
            "user_attested",
            "written_authorization",
            "fixture",
        }
        report = CreatorImportCoverageReport(
            expected_count=len(expected),
            imported_count=len(imported),
            covered_count=len(covered),
            missing_count=missing_count,
            unexpected_count=unexpected_count,
            exact_coverage=missing_count == 0 and unexpected_count == 0,
            source_basis=self.payload.source_basis,
            authorization_status=self.payload.authorization_status,
            source_declared=source_declared,
            authorization_documented=authorization_documented,
        )
        if require_exact and not report.exact_coverage:
            raise ValueError(
                "creator import coverage mismatch: "
                f"missing={report.missing_count}, unexpected={report.unexpected_count}"
            )
        if require_source_declared and not report.source_declared:
            raise ValueError("creator import source basis is not declared")
        if require_authorized and not report.authorization_documented:
            raise ValueError("creator import authorization is not documented")
        return report

    @property
    def capabilities(self) -> CreatorProviderCapabilities:
        if self.payload.authorization_status == "written_authorization":
            commercial_authorization = "authorized"
        elif self._fixture or self.payload.authorization_status == "development_only":
            commercial_authorization = "development_only"
        else:
            commercial_authorization = "unknown"
        return CreatorProviderCapabilities(
            provider_name="fixture" if self._fixture else "import",
            provider_version=self.payload.provider_version,
            provider_kind="fixture" if self._fixture else "import",
            commercial_authorization=commercial_authorization,
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
            request_audit=entry.request_audit,
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
