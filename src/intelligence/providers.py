"""Replaceable search providers for P0-B Bilibili snapshots."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import html
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from pydantic import Field, ValidationError, model_validator

from src.intelligence.contracts import (
    MAX_SEARCH_PAGES,
    Creator,
    PageStatus,
    ProviderCapabilities,
    SampleAvailability,
    SearchPage,
    SearchRequest,
    SortMode,
    StrictModel,
    TimeRange,
    Video,
)


IMPORT_SCHEMA_VERSION = "search-import.p0.1"
BILIBILI_SEARCH_PROVIDER_VERSION = "bilibili-public-search.p0-b.1"
IMPORT_PROVIDER_VERSION = "import-search.p0-b.1"
BILIBILI_SEARCH_ENDPOINT = "https://api.bilibili.com/x/web-interface/wbi/search/type"
BILIBILI_SEARCH_PAGE = "https://search.bilibili.com/all"
LOCAL_FILTER_NAMES = {"min_view", "max_duration_seconds"}

CancelCheck = Callable[[], Awaitable[bool]]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def raw_payload_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_local_filters(filters: dict[str, Any]) -> None:
    unknown = sorted(set(filters) - LOCAL_FILTER_NAMES)
    if unknown:
        raise ValueError(f"unsupported local filters: {', '.join(unknown)}")
    for name in LOCAL_FILTER_NAMES:
        if name not in filters:
            continue
        value = filters[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")


def _safe_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    text = str(value).strip().replace(",", "")
    if not text or text in {"--", "-"}:
        return None
    try:
        parsed = int(float(text))
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        text = str(value).strip()
        if text.isdigit():
            parsed = datetime.fromtimestamp(int(text), tz=timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_duration(value: Any) -> int | None:
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


def _parse_count_text(value: Any) -> int | None:
    parsed = _safe_int(value)
    if parsed is not None:
        return parsed
    text = str(value or "").strip().replace(",", "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*([万亿]?)", text)
    if not match:
        return None
    multiplier = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
    return int(float(match.group(1)) * multiplier)


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()


def _absolute_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return f"https:{text}" if text.startswith("//") else text


def _local_filter_metadata(request: SearchRequest) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if request.time_range != TimeRange.ALL:
        metadata["time_range"] = request.time_range.value
    if request.partition:
        metadata["partition"] = request.partition
    if request.filters:
        metadata["filters"] = request.filters
    return metadata


def _matches_local_filters(video: Video, request: SearchRequest, observed_at: datetime) -> bool:
    if request.time_range != TimeRange.ALL:
        windows = {
            TimeRange.DAY: timedelta(days=1),
            TimeRange.WEEK: timedelta(days=7),
            TimeRange.MONTH: timedelta(days=30),
            TimeRange.QUARTER: timedelta(days=90),
            TimeRange.YEAR: timedelta(days=365),
        }
        published_at = video.published_at
        if published_at is None or published_at < observed_at - windows[request.time_range]:
            return False
    if request.partition:
        partition = (video.partition or "").strip().lower()
        if request.partition.strip().lower() not in partition:
            return False
    if "min_view" in request.filters:
        if video.view is None or video.view < request.filters["min_view"]:
            return False
    if "max_duration_seconds" in request.filters:
        if video.duration_seconds is None or video.duration_seconds > request.filters["max_duration_seconds"]:
            return False
    return True


@dataclass(slots=True)
class ProviderPageResult:
    page: SearchPage
    videos: list[Video]
    creators: list[Creator]
    raw_payload: Any | None = None


class SearchProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def search_page(
        self,
        request: SearchRequest,
        page_number: int,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderPageResult: ...

    async def close(self) -> None: ...


class SearchCancelled(RuntimeError):
    pass


async def _cancelled(cancel_check: CancelCheck | None) -> bool:
    return bool(cancel_check and await cancel_check())


async def _sleep_with_cancellation(
    seconds: float,
    cancel_check: CancelCheck | None,
    sleep: Callable[[float], Awaitable[None]],
) -> None:
    remaining = max(0.0, seconds)
    while remaining > 0:
        if await _cancelled(cancel_check):
            raise SearchCancelled
        step = min(0.1, remaining)
        await sleep(step)
        remaining -= step


async def _await_with_cancellation(awaitable, cancel_check: CancelCheck | None):
    task = asyncio.create_task(awaitable)
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if done:
                break
            if await _cancelled(cancel_check):
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise SearchCancelled
        return await task
    except BaseException:
        if not task.done():
            task.cancel()
        raise


class BilibiliDevelopmentSearchProvider:
    """Low-frequency, unauthenticated development adapter for public search results."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.5,
        min_interval_seconds: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], datetime] = utcnow,
        enable_html_fallback: bool = True,
    ) -> None:
        if not 0 <= max_retries <= 4:
            raise ValueError("max_retries must be between 0 and 4")
        if timeout_seconds <= 0 or backoff_base_seconds < 0 or min_interval_seconds < 0:
            raise ValueError("provider timing settings must be non-negative")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ViralVideoAgent-Development/0.1)",
                "Referer": "https://search.bilibili.com/",
                "Accept": "application/json, text/plain, */*",
            },
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._backoff_base_seconds = backoff_base_seconds
        self._min_interval_seconds = min_interval_seconds
        self._sleep = sleep
        self._now = now
        self._enable_html_fallback = enable_html_fallback
        self._last_request_started: float | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return development_provider_capabilities()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _wait_for_rate_limit(self, cancel_check: CancelCheck | None) -> None:
        if self._last_request_started is None:
            return
        remaining = self._min_interval_seconds - (time.monotonic() - self._last_request_started)
        if remaining > 0:
            await _sleep_with_cancellation(remaining, cancel_check, self._sleep)

    def _params(self, request: SearchRequest, page_number: int) -> dict[str, Any]:
        order = {
            SortMode.RELEVANCE: "totalrank",
            SortMode.NEWEST: "pubdate",
            SortMode.MOST_VIEWED: "click",
        }[request.sort_mode]
        return {
            "search_type": "video",
            "keyword": request.keyword,
            "page": page_number,
            "page_size": 20,
            "order": order,
        }

    def _page_url(self, params: dict[str, Any]) -> str:
        return f"{BILIBILI_SEARCH_ENDPOINT}?{urlencode(params)}"

    def _html_page_url(self, request: SearchRequest, page_number: int) -> str:
        order = self._params(request, page_number)["order"]
        return f"{BILIBILI_SEARCH_PAGE}?{urlencode({'keyword': request.keyword, 'page': page_number, 'order': order})}"

    async def search_page(
        self,
        request: SearchRequest,
        page_number: int,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderPageResult:
        if not 1 <= page_number <= min(request.max_pages, MAX_SEARCH_PAGES):
            raise ValueError("page_number is outside the requested 1-5 boundary")
        validate_local_filters(request.filters)
        params = self._params(request, page_number)
        source_url = self._page_url(params)
        request_started_at = self._now()
        started_monotonic = time.monotonic()
        last_error: tuple[PageStatus, str, str, Any | None] | None = None

        for attempt in range(self._max_retries + 1):
            if await _cancelled(cancel_check):
                return self._cancelled_page(request, page_number, request_started_at, started_monotonic, source_url, attempt)
            if attempt:
                try:
                    await _sleep_with_cancellation(
                        self._backoff_base_seconds * (2 ** (attempt - 1)),
                        cancel_check,
                        self._sleep,
                    )
                except SearchCancelled:
                    return self._cancelled_page(request, page_number, request_started_at, started_monotonic, source_url, attempt)
            try:
                await self._wait_for_rate_limit(cancel_check)
                self._last_request_started = time.monotonic()
                response = await _await_with_cancellation(self._client.get(BILIBILI_SEARCH_ENDPOINT, params=params), cancel_check)
            except SearchCancelled:
                return self._cancelled_page(request, page_number, request_started_at, started_monotonic, source_url, attempt + 1)
            except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
                last_error = (PageStatus.TIMEOUT, "PROVIDER_TIMEOUT", type(exc).__name__, None)
                continue
            except httpx.RequestError as exc:
                last_error = (PageStatus.FAILED, "PROVIDER_REQUEST_ERROR", type(exc).__name__, None)
                continue

            source_url = str(response.request.url)
            if response.status_code != 200:
                retryable = response.status_code in {429, 500, 502, 503, 504}
                last_error = (
                    PageStatus.FAILED,
                    f"HTTP_{response.status_code}",
                    f"provider returned HTTP {response.status_code}",
                    None,
                )
                if retryable:
                    continue
                break
            try:
                payload = response.json()
            except ValueError:
                last_error = (PageStatus.FAILED, "INVALID_JSON", "provider returned invalid JSON", None)
                continue
            if not isinstance(payload, dict):
                last_error = (PageStatus.FAILED, "INVALID_PAYLOAD", "provider payload must be an object", payload)
                break
            code = payload.get("code")
            if code != 0:
                summary = _clean_text(payload.get("message") or payload.get("msg") or f"provider code {code}")
                last_error = (PageStatus.FAILED, f"BILIBILI_{code}", summary, payload)
                if code in {-412, -352, -401, -403}:
                    break
                continue

            data = payload.get("data")
            if not isinstance(data, dict):
                last_error = (PageStatus.FAILED, "INVALID_DATA_OBJECT", "provider data must be an object", payload)
                break
            if "result" not in data:
                if data.get("v_voucher"):
                    last_error = (
                        PageStatus.FAILED,
                        "BILIBILI_CHALLENGE",
                        "provider returned a risk-control challenge instead of search results",
                        payload,
                    )
                else:
                    last_error = (
                        PageStatus.FAILED,
                        "INVALID_RESULT_LIST",
                        "provider response omitted the result list",
                        payload,
                    )
                break
            raw_items = data["result"]
            if not isinstance(raw_items, list):
                last_error = (PageStatus.FAILED, "INVALID_RESULT_LIST", "provider result must be a list", payload)
                break
            completed_at = self._now()
            page_hash = raw_payload_hash(payload)
            videos: list[Video] = []
            creators_by_mid: dict[str, Creator] = {}
            for rank, item in enumerate(raw_items, 1):
                normalized = self._normalize_item(item, page_number, rank, completed_at, page_hash)
                if normalized is None or not _matches_local_filters(normalized, request, completed_at):
                    continue
                videos.append(normalized)
                if normalized.creator_mid and normalized.creator_mid not in creators_by_mid:
                    creator_name = normalized.creator_name or ""
                    creators_by_mid[normalized.creator_mid] = Creator(
                        mid=normalized.creator_mid,
                        name=creator_name,
                        profile_url=f"https://space.bilibili.com/{normalized.creator_mid}",
                        observed_at=completed_at,
                        provider_name=self.capabilities.provider_name,
                        provider_version=self.capabilities.provider_version,
                        recent_sample_availability=SampleAvailability.MISSING,
                        recent_sample_count=0,
                        missing_reason="creator_samples_not_supported" if creator_name else "creator_name_missing",
                    )
            status = PageStatus.SUCCESS if videos else PageStatus.EMPTY
            return ProviderPageResult(
                page=SearchPage(
                    page_number=page_number,
                    status=status,
                    requested_at=request_started_at,
                    completed_at=completed_at,
                    request_duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                    source_url=source_url,
                    raw_result_count=len(raw_items),
                    normalized_result_count=len(videos),
                    provider_name=self.capabilities.provider_name,
                    provider_version=self.capabilities.provider_version,
                    native_filters={
                        "search_type": "video",
                        "order": params["order"],
                        "page_size": 20,
                        "attempt_count": attempt + 1,
                    },
                    local_filters=_local_filter_metadata(request),
                    raw_payload_hash=page_hash,
                ),
                videos=videos,
                creators=list(creators_by_mid.values()),
                raw_payload=payload,
            )

        status, error_code, error_summary, payload = last_error or (
            PageStatus.FAILED,
            "PROVIDER_FAILED",
            "provider failed without a response",
            None,
        )
        if self._enable_html_fallback and error_code in {"BILIBILI_CHALLENGE", "INVALID_RESULT_LIST"}:
            return await self._search_html_page(
                request,
                page_number,
                request_started_at,
                started_monotonic,
                cancel_check,
                original_error_code=error_code,
            )
        completed_at = self._now()
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=status,
                requested_at=request_started_at,
                completed_at=completed_at,
                request_duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                source_url=source_url,
                raw_result_count=0,
                normalized_result_count=0,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={
                    "search_type": "video",
                    "order": params["order"],
                    "page_size": 20,
                    "attempt_count": self._max_retries + 1,
                },
                local_filters=_local_filter_metadata(request),
                raw_payload_hash=raw_payload_hash(payload) if payload is not None else None,
                error_code=error_code,
                error_summary=error_summary[:300],
            ),
            videos=[],
            creators=[],
            raw_payload=payload,
        )

    async def _search_html_page(
        self,
        request: SearchRequest,
        page_number: int,
        requested_at: datetime,
        started_monotonic: float,
        cancel_check: CancelCheck | None,
        *,
        original_error_code: str,
    ) -> ProviderPageResult:
        source_url = self._html_page_url(request, page_number)
        try:
            await self._wait_for_rate_limit(cancel_check)
            self._last_request_started = time.monotonic()
            response = await _await_with_cancellation(self._client.get(source_url), cancel_check)
        except SearchCancelled:
            return self._cancelled_page(request, page_number, requested_at, started_monotonic, source_url, 1)
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            return self._html_failure(
                request, page_number, requested_at, started_monotonic, source_url,
                "HTML_FALLBACK_TIMEOUT", type(exc).__name__, original_error_code,
            )
        except httpx.RequestError as exc:
            return self._html_failure(
                request, page_number, requested_at, started_monotonic, source_url,
                "HTML_FALLBACK_REQUEST_ERROR", type(exc).__name__, original_error_code,
            )
        source_url = str(response.request.url)
        if response.status_code != 200:
            return self._html_failure(
                request, page_number, requested_at, started_monotonic, source_url,
                f"HTML_HTTP_{response.status_code}", f"HTML fallback returned HTTP {response.status_code}", original_error_code,
            )
        payload = response.text
        payload_hash = raw_payload_hash(payload)
        soup = BeautifulSoup(payload, "html.parser")
        cards = soup.select("div.bili-video-card__wrap")
        videos: list[Video] = []
        creators_by_mid: dict[str, Creator] = {}
        observed_at = self._now()
        seen_in_page: set[str] = set()
        for card in cards:
            video_link = card.find("a", href=lambda value: bool(value and "/video/BV" in value))
            match = re.search(r"BV[0-9A-Za-z]{10}", str(video_link.get("href") if video_link else ""))
            if not match or match.group(0) in seen_in_page:
                continue
            bvid = match.group(0)
            seen_in_page.add(bvid)
            raw_rank = len(seen_in_page)
            title_node = card.find("h3")
            title = _clean_text(title_node.get("title") if title_node and title_node.get("title") else title_node.get_text(" ", strip=True) if title_node else "")
            if not title:
                continue
            owner_link = card.find("a", href=lambda value: bool(value and "space.bilibili.com/" in value))
            owner_href = str(owner_link.get("href") if owner_link else "")
            mid_match = re.search(r"space\.bilibili\.com/(\d+)", owner_href)
            creator_mid = mid_match.group(1) if mid_match else None
            creator_name = _clean_text(owner_link.get_text(" ", strip=True) if owner_link else "") or None
            source = _absolute_url(video_link.get("href")) or f"https://www.bilibili.com/video/{bvid}"
            duration_node = card.select_one(".bili-video-card__stats__duration")
            stats = card.select(".bili-video-card__stats--item")
            view = _parse_count_text(stats[0].get_text(" ", strip=True)) if stats else None
            danmaku = _parse_count_text(stats[1].get_text(" ", strip=True)) if len(stats) > 1 else None
            image = card.find("img")
            cover_url = _absolute_url(
                image.get("src") or image.get("data-src") if image else None
            )
            optional = {
                "aid": None,
                "creator_mid": creator_mid,
                "creator_name": creator_name,
                "description": None,
                "partition": None,
                "published_at": None,
                "duration_seconds": _parse_duration(duration_node.get_text(" ", strip=True) if duration_node else None),
                "cover_url": cover_url,
                "view": view,
                "like": None,
                "coin": None,
                "favorite": None,
                "reply": None,
                "share": None,
                "danmaku": danmaku,
            }
            missing_fields = [name for name, value in optional.items() if value is None]
            missing_fields.append("tags")
            try:
                video = Video(
                    bvid=bvid,
                    title=title,
                    tags=[],
                    source_url=source,
                    observed_at=observed_at,
                    provider_name=self.capabilities.provider_name,
                    provider_version=self.capabilities.provider_version,
                    source_page=page_number,
                    source_rank=raw_rank,
                    raw_payload_hash=raw_payload_hash(str(card)),
                    missing_fields=sorted(set(missing_fields)),
                    **optional,
                )
            except ValidationError:
                continue
            if not _matches_local_filters(video, request, observed_at):
                continue
            videos.append(video)
            if creator_mid and creator_mid not in creators_by_mid:
                creators_by_mid[creator_mid] = Creator(
                    mid=creator_mid,
                    name=creator_name or "",
                    profile_url=_absolute_url(owner_href) or f"https://space.bilibili.com/{creator_mid}",
                    observed_at=observed_at,
                    provider_name=self.capabilities.provider_name,
                    provider_version=self.capabilities.provider_version,
                    recent_sample_availability=SampleAvailability.MISSING,
                    recent_sample_count=0,
                    missing_reason="creator_samples_not_supported",
                )
        if not seen_in_page:
            return self._html_failure(
                request, page_number, requested_at, started_monotonic, source_url,
                "HTML_RESULT_PARSE_FAILED", "HTML fallback contained no parseable search cards", original_error_code,
                raw_payload=payload,
            )
        status = PageStatus.SUCCESS if videos else PageStatus.EMPTY
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=status,
                requested_at=requested_at,
                completed_at=observed_at,
                request_duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                source_url=source_url,
                raw_result_count=len(seen_in_page),
                normalized_result_count=len(videos),
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={
                    "adapter": "public_search_html_fallback",
                    "order": self._params(request, page_number)["order"],
                    "original_error_code": original_error_code,
                    "parsed_card_count": len(seen_in_page),
                },
                local_filters=_local_filter_metadata(request),
                raw_payload_hash=payload_hash,
            ),
            videos=videos,
            creators=list(creators_by_mid.values()),
            raw_payload=payload,
        )

    def _html_failure(
        self,
        request: SearchRequest,
        page_number: int,
        requested_at: datetime,
        started_monotonic: float,
        source_url: str,
        error_code: str,
        error_summary: str,
        original_error_code: str,
        *,
        raw_payload: Any | None = None,
    ) -> ProviderPageResult:
        completed_at = self._now()
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=PageStatus.FAILED,
                requested_at=requested_at,
                completed_at=completed_at,
                request_duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                source_url=source_url,
                raw_result_count=0,
                normalized_result_count=0,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={"adapter": "public_search_html_fallback", "original_error_code": original_error_code},
                local_filters=_local_filter_metadata(request),
                raw_payload_hash=raw_payload_hash(raw_payload) if raw_payload is not None else None,
                error_code=error_code,
                error_summary=error_summary[:300],
            ),
            videos=[],
            creators=[],
            raw_payload=raw_payload,
        )

    def _cancelled_page(
        self,
        request: SearchRequest,
        page_number: int,
        requested_at: datetime,
        started_monotonic: float,
        source_url: str,
        attempt_count: int,
    ) -> ProviderPageResult:
        completed_at = self._now()
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=PageStatus.CANCELLED,
                requested_at=requested_at,
                completed_at=completed_at,
                request_duration_ms=max(0, int((time.monotonic() - started_monotonic) * 1000)),
                source_url=source_url,
                raw_result_count=0,
                normalized_result_count=0,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={"attempt_count": attempt_count},
                local_filters=_local_filter_metadata(request),
                error_code="CANCELLED",
                error_summary="search page cancelled",
            ),
            videos=[],
            creators=[],
        )

    def _normalize_item(
        self,
        item: Any,
        page_number: int,
        rank: int,
        observed_at: datetime,
        page_hash: str,
    ) -> Video | None:
        if not isinstance(item, dict):
            return None
        bvid = str(item.get("bvid") or "").strip()
        title = _clean_text(item.get("title"))
        if not bvid or not title:
            return None
        creator_mid = str(item.get("mid")).strip() if item.get("mid") not in {None, ""} else None
        tags_value = item.get("tag") or item.get("tags")
        if isinstance(tags_value, list):
            tags = [_clean_text(value) for value in tags_value if _clean_text(value)]
        elif tags_value:
            tags = [_clean_text(value) for value in str(tags_value).split(",") if _clean_text(value)]
        else:
            tags = []
        source_url = _absolute_url(item.get("arcurl")) or f"https://www.bilibili.com/video/{bvid}"
        optional = {
            "aid": _safe_int(item.get("aid")),
            "creator_mid": creator_mid,
            "creator_name": _clean_text(item.get("author") or item.get("up_name")) or None,
            "description": _clean_text(item.get("description")) or None,
            "partition": _clean_text(item.get("typename") or item.get("partition")) or None,
            "published_at": _parse_datetime(item.get("pubdate") or item.get("senddate")),
            "duration_seconds": _parse_duration(item.get("duration")),
            "cover_url": _absolute_url(item.get("pic") or item.get("cover")),
            "view": _safe_int(item.get("play") if item.get("play") is not None else item.get("view")),
            "like": _safe_int(item.get("like")),
            "coin": _safe_int(item.get("coin")),
            "favorite": _safe_int(item.get("favorites") if item.get("favorites") is not None else item.get("favorite")),
            "reply": _safe_int(item.get("review") if item.get("review") is not None else item.get("reply")),
            "share": _safe_int(item.get("share")),
            "danmaku": _safe_int(item.get("video_review") if item.get("video_review") is not None else item.get("danmaku")),
        }
        missing_fields = [name for name, value in optional.items() if value is None]
        if not tags:
            missing_fields.append("tags")
        try:
            return Video(
                bvid=bvid,
                title=title,
                tags=tags,
                source_url=source_url,
                observed_at=observed_at,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                source_page=page_number,
                source_rank=rank,
                raw_payload_hash=raw_payload_hash(item) or page_hash,
                missing_fields=sorted(set(missing_fields)),
                **optional,
            )
        except ValidationError:
            return None


class ImportVideoPayload(StrictModel):
    bvid: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    title: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    aid: int | None = Field(default=None, ge=1)
    creator_mid: str | None = None
    creator_name: str | None = None
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
    observed_at: datetime | None = None
    missing_fields: list[str] = Field(default_factory=list)


class ImportPagePayload(StrictModel):
    page_number: int = Field(ge=1, le=MAX_SEARCH_PAGES)
    status: PageStatus
    source_url: str | None = None
    requested_at: datetime | None = None
    completed_at: datetime | None = None
    native_filters: dict[str, Any] = Field(default_factory=dict)
    local_filters: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_summary: str | None = None
    results: list[ImportVideoPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status(self) -> "ImportPagePayload":
        if self.requested_at and self.completed_at and self.completed_at < self.requested_at:
            raise ValueError("import completed_at cannot be before requested_at")
        if self.status == PageStatus.SUCCESS and not self.results:
            raise ValueError("import success pages require at least one result")
        if self.status == PageStatus.EMPTY and self.results:
            raise ValueError("import empty pages cannot contain results")
        if self.status in {PageStatus.FAILED, PageStatus.TIMEOUT, PageStatus.CANCELLED} and self.results:
            raise ValueError("import unsuccessful pages cannot contain results")
        return self


class ImportSnapshotPayload(StrictModel):
    schema_version: str = Field(default=IMPORT_SCHEMA_VERSION, pattern=r"^search-import\.p0\.1$")
    source_name: str = Field(min_length=1, max_length=120)
    provider_version: str = Field(default=IMPORT_PROVIDER_VERSION, min_length=1, max_length=40)
    snapshot_at: datetime
    keyword: str = Field(min_length=1, max_length=200)
    sort_mode: SortMode = SortMode.RELEVANCE
    time_range: TimeRange = TimeRange.ALL
    partition: str | None = Field(default=None, max_length=80)
    pages: list[ImportPagePayload] = Field(min_length=1, max_length=MAX_SEARCH_PAGES)

    @model_validator(mode="after")
    def validate_pages(self) -> "ImportSnapshotPayload":
        page_numbers = [page.page_number for page in self.pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("import pages must have unique page numbers")
        return self


CSV_COLUMNS = {
    "source_name",
    "provider_version",
    "keyword",
    "snapshot_at",
    "sort_mode",
    "time_range",
    "partition",
    "page_number",
    "page_status",
    "page_source_url",
    "requested_at",
    "completed_at",
    "error_code",
    "error_summary",
    "bvid",
    "title",
    "video_source_url",
    "aid",
    "creator_mid",
    "creator_name",
    "description",
    "tags",
    "video_partition",
    "published_at",
    "duration_seconds",
    "cover_url",
    "view",
    "like",
    "coin",
    "favorite",
    "reply",
    "share",
    "danmaku",
    "observed_at",
    "missing_fields",
}
CSV_REQUIRED_COLUMNS = {
    "source_name",
    "provider_version",
    "keyword",
    "snapshot_at",
    "page_number",
    "page_status",
}


class ImportSearchProvider:
    def __init__(self, snapshot: ImportSnapshotPayload) -> None:
        self.snapshot = snapshot
        self._pages = {page.page_number: page for page in snapshot.pages}

    @classmethod
    def from_json(cls, payload: str | dict[str, Any]) -> "ImportSearchProvider":
        value = json.loads(payload) if isinstance(payload, str) else payload
        return cls(ImportSnapshotPayload.model_validate(value))

    @classmethod
    def from_csv(cls, payload: str) -> "ImportSearchProvider":
        reader = csv.DictReader(StringIO(payload))
        headers = set(reader.fieldnames or [])
        missing_headers = CSV_REQUIRED_COLUMNS - headers
        unknown_headers = headers - CSV_COLUMNS
        if missing_headers:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing_headers))}")
        if unknown_headers:
            raise ValueError(f"CSV contains unknown columns: {', '.join(sorted(unknown_headers))}")
        rows = list(reader)
        if not rows:
            raise ValueError("CSV import requires at least one row")
        metadata_names = ["source_name", "provider_version", "keyword", "snapshot_at", "sort_mode", "time_range", "partition"]
        metadata = {name: (rows[0].get(name) or "").strip() for name in metadata_names}
        for row in rows[1:]:
            for name in metadata_names:
                if (row.get(name) or "").strip() != metadata[name]:
                    raise ValueError(f"CSV metadata column {name} must be identical across rows")
        grouped: dict[int, list[dict[str, str]]] = {}
        for row in rows:
            try:
                page_number = int(row["page_number"])
            except (TypeError, ValueError) as exc:
                raise ValueError("CSV page_number must be an integer") from exc
            grouped.setdefault(page_number, []).append(row)
        pages = []
        for page_number, page_rows in sorted(grouped.items()):
            statuses = {(row.get("page_status") or "").strip() for row in page_rows}
            if len(statuses) != 1:
                raise ValueError("CSV page_status must be identical within a page")
            status = next(iter(statuses))
            results = []
            for row in page_rows:
                bvid = (row.get("bvid") or "").strip()
                if not bvid:
                    continue
                results.append({
                    "bvid": bvid,
                    "title": (row.get("title") or "").strip(),
                    "source_url": (row.get("video_source_url") or "").strip(),
                    "aid": _safe_int(row.get("aid")),
                    "creator_mid": (row.get("creator_mid") or "").strip() or None,
                    "creator_name": (row.get("creator_name") or "").strip() or None,
                    "description": (row.get("description") or "").strip() or None,
                    "tags": [item.strip() for item in (row.get("tags") or "").split("|") if item.strip()],
                    "partition": (row.get("video_partition") or "").strip() or None,
                    "published_at": _parse_datetime(row.get("published_at")),
                    "duration_seconds": _safe_int(row.get("duration_seconds")),
                    "cover_url": (row.get("cover_url") or "").strip() or None,
                    "view": _safe_int(row.get("view")),
                    "like": _safe_int(row.get("like")),
                    "coin": _safe_int(row.get("coin")),
                    "favorite": _safe_int(row.get("favorite")),
                    "reply": _safe_int(row.get("reply")),
                    "share": _safe_int(row.get("share")),
                    "danmaku": _safe_int(row.get("danmaku")),
                    "observed_at": _parse_datetime(row.get("observed_at")),
                    "missing_fields": [item.strip() for item in (row.get("missing_fields") or "").split("|") if item.strip()],
                })
            first = page_rows[0]
            pages.append({
                "page_number": page_number,
                "status": status,
                "source_url": (first.get("page_source_url") or "").strip() or None,
                "requested_at": _parse_datetime(first.get("requested_at")),
                "completed_at": _parse_datetime(first.get("completed_at")),
                "error_code": (first.get("error_code") or "").strip() or None,
                "error_summary": (first.get("error_summary") or "").strip() or None,
                "results": results,
            })
        snapshot = ImportSnapshotPayload.model_validate({
            "source_name": metadata["source_name"],
            "provider_version": metadata["provider_version"] or IMPORT_PROVIDER_VERSION,
            "snapshot_at": _parse_datetime(metadata["snapshot_at"]),
            "keyword": metadata["keyword"],
            "sort_mode": metadata["sort_mode"] or SortMode.RELEVANCE,
            "time_range": metadata["time_range"] or TimeRange.ALL,
            "partition": metadata["partition"] or None,
            "pages": pages,
        })
        return cls(snapshot)

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_name="import",
            provider_version=self.snapshot.provider_version,
            provider_kind="import",
            supports_search=True,
            supports_creator_samples=False,
            supports_native_sort=[self.snapshot.sort_mode],
            supports_native_time_range=[self.snapshot.time_range],
            supports_native_partition=self.snapshot.partition is not None,
            requires_login=False,
            commercial_authorization="unknown",
        )

    async def close(self) -> None:
        return None

    async def search_page(
        self,
        request: SearchRequest,
        page_number: int,
        cancel_check: CancelCheck | None = None,
    ) -> ProviderPageResult:
        validate_local_filters(request.filters)
        now = utcnow()
        if await _cancelled(cancel_check):
            return self._failure(request, page_number, now, PageStatus.CANCELLED, "CANCELLED", "import cancelled")
        mismatch = self.request_mismatch(request)
        if mismatch:
            return self._failure(request, page_number, now, PageStatus.FAILED, "IMPORT_REQUEST_MISMATCH", mismatch)
        page = self._pages.get(page_number)
        if page is None:
            return self._failure(request, page_number, now, PageStatus.FAILED, "IMPORT_PAGE_MISSING", "requested page is absent from import")
        requested_at = page.requested_at or self.snapshot.snapshot_at
        completed_at = page.completed_at or self.snapshot.snapshot_at
        page_payload = page.model_dump(mode="json")
        payload_hash = raw_payload_hash(page_payload)
        if page.status in {PageStatus.FAILED, PageStatus.TIMEOUT, PageStatus.CANCELLED}:
            return ProviderPageResult(
                page=SearchPage(
                    page_number=page_number,
                    status=page.status,
                    requested_at=requested_at,
                    completed_at=completed_at,
                    request_duration_ms=max(0, int((completed_at - requested_at).total_seconds() * 1000)),
                    source_url=page.source_url,
                    raw_result_count=0,
                    normalized_result_count=0,
                    provider_name=self.capabilities.provider_name,
                    provider_version=self.capabilities.provider_version,
                    native_filters={"import_source": self.snapshot.source_name, **page.native_filters},
                    local_filters={**_local_filter_metadata(request), **page.local_filters},
                    raw_payload_hash=payload_hash,
                    error_code=page.error_code or f"IMPORT_{page.status.value.upper()}",
                    error_summary=page.error_summary or f"imported page status is {page.status.value}",
                ),
                videos=[],
                creators=[],
                raw_payload=page_payload,
            )
        videos: list[Video] = []
        creators_by_mid: dict[str, Creator] = {}
        for rank, item in enumerate(page.results, 1):
            item_payload = item.model_dump()
            missing_fields = set(item.missing_fields)
            for name in (
                "aid", "creator_mid", "creator_name", "description", "partition", "published_at",
                "duration_seconds", "cover_url", "view", "like", "coin", "favorite", "reply", "share", "danmaku",
            ):
                if item_payload[name] is None:
                    missing_fields.add(name)
            if not item.tags:
                missing_fields.add("tags")
            observed_at = item.observed_at or self.snapshot.snapshot_at
            item_payload.pop("observed_at")
            item_payload.pop("missing_fields")
            video = Video(
                **item_payload,
                observed_at=observed_at,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                source_page=page_number,
                source_rank=rank,
                raw_payload_hash=raw_payload_hash(item_payload),
                missing_fields=sorted(missing_fields),
            )
            if not _matches_local_filters(video, request, completed_at):
                continue
            videos.append(video)
            if video.creator_mid and video.creator_mid not in creators_by_mid:
                creators_by_mid[video.creator_mid] = Creator(
                    mid=video.creator_mid,
                    name=video.creator_name or "",
                    profile_url=f"https://space.bilibili.com/{video.creator_mid}",
                    observed_at=observed_at,
                    provider_name=self.capabilities.provider_name,
                    provider_version=self.capabilities.provider_version,
                    recent_sample_availability=SampleAvailability.MISSING,
                    recent_sample_count=0,
                    missing_reason="import_does_not_include_creator_samples",
                )
        status = PageStatus.SUCCESS if videos else PageStatus.EMPTY
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=status,
                requested_at=requested_at,
                completed_at=completed_at,
                request_duration_ms=max(0, int((completed_at - requested_at).total_seconds() * 1000)),
                source_url=page.source_url,
                raw_result_count=len(page.results),
                normalized_result_count=len(videos),
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={"import_source": self.snapshot.source_name, **page.native_filters},
                local_filters={**_local_filter_metadata(request), **page.local_filters},
                raw_payload_hash=payload_hash,
            ),
            videos=videos,
            creators=list(creators_by_mid.values()),
            raw_payload=page_payload,
        )

    def request_mismatch(self, request: SearchRequest) -> str | None:
        checks = {
            "keyword": (request.keyword, self.snapshot.keyword),
            "sort_mode": (request.sort_mode, self.snapshot.sort_mode),
            "time_range": (request.time_range, self.snapshot.time_range),
            "partition": (request.partition, self.snapshot.partition),
        }
        mismatches = [name for name, (requested, imported) in checks.items() if requested != imported]
        if mismatches:
            return f"import metadata does not match request: {', '.join(mismatches)}"
        return None

    def _failure(
        self,
        request: SearchRequest,
        page_number: int,
        now: datetime,
        status: PageStatus,
        error_code: str,
        error_summary: str,
    ) -> ProviderPageResult:
        return ProviderPageResult(
            page=SearchPage(
                page_number=page_number,
                status=status,
                requested_at=now,
                completed_at=now,
                request_duration_ms=0,
                raw_result_count=0,
                normalized_result_count=0,
                provider_name=self.capabilities.provider_name,
                provider_version=self.capabilities.provider_version,
                native_filters={"import_source": self.snapshot.source_name},
                local_filters=_local_filter_metadata(request),
                error_code=error_code,
                error_summary=error_summary,
            ),
            videos=[],
            creators=[],
        )


class FixtureSearchProvider(ImportSearchProvider):
    @property
    def capabilities(self) -> ProviderCapabilities:
        base = super().capabilities
        return base.model_copy(update={
            "provider_name": "fixture",
            "provider_kind": "fixture",
            "commercial_authorization": "development_only",
        })


def development_provider_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_name="bilibili-public-search",
        provider_version=BILIBILI_SEARCH_PROVIDER_VERSION,
        provider_kind="development",
        supports_search=True,
        supports_creator_samples=False,
        supports_native_sort=list(SortMode),
        supports_native_time_range=[TimeRange.ALL],
        supports_native_partition=False,
        requires_login=False,
        commercial_authorization="development_only",
    )


def provider_capability_catalog() -> list[dict[str, Any]]:
    return [
        development_provider_capabilities().model_dump(mode="json"),
        ProviderCapabilities(
            provider_name="import",
            provider_version=IMPORT_PROVIDER_VERSION,
            provider_kind="import",
            supports_search=True,
            supports_creator_samples=False,
            requires_login=False,
            commercial_authorization="unknown",
        ).model_dump(mode="json"),
        ProviderCapabilities(
            provider_name="fixture",
            provider_version=IMPORT_PROVIDER_VERSION,
            provider_kind="fixture",
            supports_search=True,
            supports_creator_samples=False,
            requires_login=False,
            commercial_authorization="development_only",
        ).model_dump(mode="json"),
    ]
