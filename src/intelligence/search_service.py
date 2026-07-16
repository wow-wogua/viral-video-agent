"""P0-B search orchestration, deduplication, and crawl status semantics."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.intelligence.contracts import (
    CrawlRun,
    CrawlStatus,
    CoverageSummary,
    Creator,
    PageStatus,
    SearchPage,
    SearchRequest,
    Video,
)
from src.intelligence.providers import CancelCheck, ProviderPageResult, SearchProvider, validate_local_filters


@dataclass(slots=True)
class SearchSnapshotBundle:
    crawl_run: CrawlRun
    videos: list[Video]
    creators: list[Creator]
    raw_payloads: dict[int, Any] = field(default_factory=dict)


def _failed_page(
    provider: SearchProvider,
    request: SearchRequest,
    page_number: int,
    exc: Exception,
) -> ProviderPageResult:
    now = datetime.now(timezone.utc)
    return ProviderPageResult(
        page=SearchPage(
            page_number=page_number,
            status=PageStatus.FAILED,
            requested_at=now,
            completed_at=now,
            request_duration_ms=0,
            raw_result_count=0,
            normalized_result_count=0,
            provider_name=provider.capabilities.provider_name,
            provider_version=provider.capabilities.provider_version,
            local_filters={
                "time_range": request.time_range.value,
                "partition": request.partition,
                "filters": request.filters,
            },
            error_code="PROVIDER_UNEXPECTED_ERROR",
            error_summary=type(exc).__name__,
        ),
        videos=[],
        creators=[],
    )


def _truncation_reason(pages: list[SearchPage]) -> str | None:
    unsuccessful = [page for page in pages if not page.completed_successfully]
    if not unsuccessful:
        return None
    if any(page.status == PageStatus.CANCELLED for page in unsuccessful):
        return "cancelled"
    return ",".join(f"page_{page.page_number}_{page.status.value}" for page in unsuccessful)


async def execute_search_snapshot(
    provider: SearchProvider,
    request: SearchRequest,
    *,
    crawl_run_id: str | None = None,
    cancel_check: CancelCheck | None = None,
) -> SearchSnapshotBundle:
    """Request exactly pages 1..max_pages unless cancellation stops the task."""

    validate_local_filters(request.filters)
    started_at = datetime.now(timezone.utc)
    pages: list[SearchPage] = []
    videos_by_bvid: dict[str, Video] = {}
    creators_by_mid: dict[str, Creator] = {}
    raw_payloads: dict[int, Any] = {}

    for page_number in range(1, request.max_pages + 1):
        try:
            result = await provider.search_page(request, page_number, cancel_check)
        except Exception as exc:
            result = _failed_page(provider, request, page_number, exc)
        pages.append(result.page)
        if result.raw_payload is not None:
            raw_payloads[page_number] = result.raw_payload
        for video in result.videos:
            videos_by_bvid.setdefault(video.bvid, video)
        for creator in result.creators:
            creators_by_mid.setdefault(creator.mid, creator)
        if result.page.status == PageStatus.CANCELLED:
            break

    successful_pages = sum(page.completed_successfully for page in pages)
    raw_result_count = sum(page.raw_result_count for page in pages)
    deduplicated_video_count = len(videos_by_bvid)
    candidate_creator_count = len(creators_by_mid)
    truncation_reason = _truncation_reason(pages)

    if successful_pages == 0:
        status = CrawlStatus.CANCELLED if any(page.status == PageStatus.CANCELLED for page in pages) else CrawlStatus.FAILED
    elif successful_pages < request.max_pages:
        status = CrawlStatus.PARTIAL
    elif deduplicated_video_count == 0:
        status = CrawlStatus.EMPTY
    else:
        status = CrawlStatus.SUCCESS

    coverage = CoverageSummary(
        requested_pages=request.max_pages,
        successful_pages=successful_pages,
        raw_result_count=raw_result_count,
        deduplicated_video_count=deduplicated_video_count,
        candidate_creator_count=candidate_creator_count,
        actual_competitor_count=0,
        partial_success=0 < successful_pages < request.max_pages,
        truncation_reason=truncation_reason,
    )
    crawl_run = CrawlRun(
        crawl_run_id=crawl_run_id or str(uuid.uuid4()),
        request=request,
        provider=provider.capabilities,
        started_at=started_at,
        completed_at=datetime.now(timezone.utc),
        status=status,
        pages=pages,
        coverage=coverage,
    )
    return SearchSnapshotBundle(
        crawl_run=crawl_run,
        videos=list(videos_by_bvid.values()),
        creators=list(creators_by_mid.values()),
        raw_payloads=raw_payloads,
    )
