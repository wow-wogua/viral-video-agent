import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from src.intelligence.contracts import (
    CrawlStatus,
    Creator,
    PageStatus,
    ProviderCapabilities,
    SearchPage,
    SearchRequest,
    Video,
)
from src.intelligence.providers import (
    BilibiliDevelopmentSearchProvider,
    ImportSearchProvider,
    ProviderPageResult,
    provider_capability_catalog,
)
from src.intelligence.search_service import execute_search_snapshot


NOW = datetime(2026, 7, 16, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "search_provider"


def request(max_pages=5, **values):
    return SearchRequest(
        keyword="脱敏关键词",
        max_pages=max_pages,
        idempotency_key="search-provider-test",
        **values,
    )


def video(index: int, page: int, rank: int, mid: str | None = None) -> Video:
    return Video(
        bvid=f"BV{index:010d}",
        creator_mid=mid,
        creator_name=f"创作者{mid}" if mid else None,
        title=f"视频{index}",
        source_url=f"https://www.bilibili.com/video/BV{index:010d}",
        observed_at=NOW,
        provider_name="fixture",
        provider_version="1",
        source_page=page,
        source_rank=rank,
    )


def page_result(page_number: int, status: PageStatus, videos=None) -> ProviderPageResult:
    videos = videos or []
    creators = [
        Creator(
            mid=item.creator_mid,
            name=item.creator_name or "",
            observed_at=NOW,
            provider_name="fixture",
            provider_version="1",
        )
        for item in videos
        if item.creator_mid
    ]
    return ProviderPageResult(
        page=SearchPage(
            page_number=page_number,
            status=status,
            requested_at=NOW,
            completed_at=NOW,
            request_duration_ms=1,
            raw_result_count=len(videos),
            normalized_result_count=len(videos),
            provider_name="fixture",
            provider_version="1",
            error_code=None if status in {PageStatus.SUCCESS, PageStatus.EMPTY} else status.value.upper(),
            error_summary=None if status in {PageStatus.SUCCESS, PageStatus.EMPTY} else status.value,
        ),
        videos=videos,
        creators=creators,
    )


class ScriptedProvider:
    def __init__(self, results):
        self.results = results
        self.calls = []
        self.capabilities = ProviderCapabilities(
            provider_name="fixture",
            provider_version="1",
            provider_kind="fixture",
            supports_search=True,
            supports_creator_samples=False,
            commercial_authorization="development_only",
        )

    async def search_page(self, search_request, page_number, cancel_check=None):
        self.calls.append(page_number)
        return self.results[page_number]

    async def close(self):
        return None


@pytest.mark.parametrize("max_pages", [1, 2, 3, 4, 5])
def test_max_pages_accepts_only_one_to_five(max_pages):
    assert request(max_pages).max_pages == max_pages


@pytest.mark.parametrize("max_pages", [0, 6])
def test_max_pages_rejects_out_of_range(max_pages):
    with pytest.raises(ValidationError):
        request(max_pages)


@pytest.mark.asyncio
async def test_sixth_page_is_never_requested():
    provider = ScriptedProvider({
        page: page_result(page, PageStatus.SUCCESS, [video(page, page, 1, str(page))])
        for page in range(1, 6)
    })
    bundle = await execute_search_snapshot(provider, request(5))
    assert provider.calls == [1, 2, 3, 4, 5]
    assert bundle.crawl_run.status == CrawlStatus.SUCCESS


@pytest.mark.asyncio
async def test_zero_success_partial_full_empty_and_cancelled_statuses():
    failed = ScriptedProvider({1: page_result(1, PageStatus.FAILED)})
    assert (await execute_search_snapshot(failed, request(1))).crawl_run.status == CrawlStatus.FAILED

    partial = ScriptedProvider({
        1: page_result(1, PageStatus.SUCCESS, [video(1, 1, 1, "10")]),
        2: page_result(2, PageStatus.FAILED),
    })
    assert (await execute_search_snapshot(partial, request(2))).crawl_run.status == CrawlStatus.PARTIAL

    empty = ScriptedProvider({1: page_result(1, PageStatus.EMPTY)})
    assert (await execute_search_snapshot(empty, request(1))).crawl_run.status == CrawlStatus.EMPTY

    completed = ScriptedProvider({1: page_result(1, PageStatus.SUCCESS, [video(2, 1, 1, "20")])})
    assert (await execute_search_snapshot(completed, request(1))).crawl_run.status == CrawlStatus.SUCCESS

    cancelled = ScriptedProvider({1: page_result(1, PageStatus.CANCELLED)})
    assert (await execute_search_snapshot(cancelled, request(5))).crawl_run.status == CrawlStatus.CANCELLED
    assert cancelled.calls == [1]


@pytest.mark.asyncio
async def test_page_two_failure_and_page_four_timeout_are_auditable():
    provider = ScriptedProvider({
        1: page_result(1, PageStatus.SUCCESS, [video(1, 1, 1, "10")]),
        2: page_result(2, PageStatus.FAILED),
        3: page_result(3, PageStatus.EMPTY),
        4: page_result(4, PageStatus.TIMEOUT),
        5: page_result(5, PageStatus.SUCCESS, [video(5, 5, 1, "50")]),
    })
    bundle = await execute_search_snapshot(provider, request(5))
    assert bundle.crawl_run.status == CrawlStatus.PARTIAL
    assert bundle.crawl_run.coverage.successful_pages == 3
    assert bundle.crawl_run.coverage.truncation_reason == "page_2_failed,page_4_timeout"


def _recorded_transport():
    page_1 = json.loads((FIXTURES / "development_page_1.json").read_text(encoding="utf-8"))
    page_2 = json.loads((FIXTURES / "development_page_2.json").read_text(encoding="utf-8"))

    def handler(http_request: httpx.Request):
        page = int(http_request.url.params["page"])
        return httpx.Response(200, json=page_1 if page == 1 else page_2, request=http_request)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_recorded_development_pages_normalize_and_deduplicate():
    client = httpx.AsyncClient(transport=_recorded_transport())
    provider = BilibiliDevelopmentSearchProvider(
        client=client,
        max_retries=0,
        min_interval_seconds=0,
        enable_html_fallback=False,
    )
    try:
        bundle = await execute_search_snapshot(provider, request(2))
    finally:
        await client.aclose()
    assert [page.raw_result_count for page in bundle.crawl_run.pages] == [3, 2]
    assert [page.normalized_result_count for page in bundle.crawl_run.pages] == [3, 2]
    assert bundle.crawl_run.coverage.raw_result_count == 5
    assert bundle.crawl_run.coverage.deduplicated_video_count == 4
    assert bundle.crawl_run.coverage.candidate_creator_count == 2
    duplicate = next(item for item in bundle.videos if item.bvid == "BV0000000002")
    assert (duplicate.source_page, duplicate.source_rank) == (1, 2)
    missing_mid = next(item for item in bundle.videos if item.bvid == "BV0000000003")
    assert missing_mid.creator_mid is None
    assert "creator_mid" in missing_mid.missing_fields


@pytest.mark.asyncio
async def test_local_filters_are_applied_and_recorded():
    client = httpx.AsyncClient(transport=_recorded_transport())
    provider = BilibiliDevelopmentSearchProvider(client=client, max_retries=0, min_interval_seconds=0)
    try:
        result = await provider.search_page(
            request(1, partition="知识", filters={"min_view": 150, "max_duration_seconds": 150}),
            1,
        )
    finally:
        await client.aclose()
    assert [item.bvid for item in result.videos] == ["BV0000000002"]
    assert result.page.local_filters == {
        "partition": "知识",
        "filters": {"min_view": 150, "max_duration_seconds": 150},
    }


@pytest.mark.asyncio
async def test_development_provider_retry_and_backoff_are_finite():
    fixture = json.loads((FIXTURES / "development_page_1.json").read_text(encoding="utf-8"))
    attempts = 0
    sleeps = []

    def handler(http_request: httpx.Request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, request=http_request)
        return httpx.Response(200, json=fixture, request=http_request)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BilibiliDevelopmentSearchProvider(
        client=client,
        max_retries=2,
        backoff_base_seconds=0.2,
        min_interval_seconds=0,
        sleep=fake_sleep,
    )
    try:
        result = await provider.search_page(request(1), 1)
    finally:
        await client.aclose()
    assert result.page.status == PageStatus.SUCCESS
    assert attempts == 3
    assert sum(sleeps) == pytest.approx(0.6)
    assert result.page.native_filters["attempt_count"] == 3


@pytest.mark.asyncio
async def test_development_provider_timeout_is_not_counted_as_success():
    def handler(http_request: httpx.Request):
        raise httpx.ReadTimeout("timeout", request=http_request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BilibiliDevelopmentSearchProvider(
        client=client,
        max_retries=0,
        min_interval_seconds=0,
        enable_html_fallback=False,
    )
    try:
        result = await provider.search_page(request(1), 1)
    finally:
        await client.aclose()
    assert result.page.status == PageStatus.TIMEOUT
    assert not result.page.completed_successfully
    assert result.page.error_code == "PROVIDER_TIMEOUT"


@pytest.mark.asyncio
async def test_risk_control_voucher_is_failed_not_empty():
    def handler(http_request: httpx.Request):
        return httpx.Response(
            200,
            json={"code": 0, "message": "OK", "data": {"v_voucher": "sanitized"}},
            request=http_request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BilibiliDevelopmentSearchProvider(
        client=client,
        max_retries=0,
        min_interval_seconds=0,
        enable_html_fallback=False,
    )
    try:
        result = await provider.search_page(request(1), 1)
    finally:
        await client.aclose()
    assert result.page.status == PageStatus.FAILED
    assert result.page.error_code == "BILIBILI_CHALLENGE"
    assert result.page.raw_payload_hash


@pytest.mark.asyncio
async def test_risk_control_can_fall_back_to_public_search_html():
    html_payload = (FIXTURES / "development_search_page.html").read_text(encoding="utf-8")
    requests = []

    def handler(http_request: httpx.Request):
        requests.append(str(http_request.url))
        if http_request.url.host == "api.bilibili.com":
            return httpx.Response(
                200,
                json={"code": 0, "message": "OK", "data": {"v_voucher": "sanitized"}},
                request=http_request,
            )
        return httpx.Response(200, text=html_payload, request=http_request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BilibiliDevelopmentSearchProvider(client=client, max_retries=0, min_interval_seconds=0)
    try:
        result = await provider.search_page(request(1), 1)
    finally:
        await client.aclose()
    assert result.page.status == PageStatus.SUCCESS
    assert result.page.native_filters["adapter"] == "public_search_html_fallback"
    assert result.page.raw_result_count == 2
    assert result.page.normalized_result_count == 2
    assert result.videos[0].view == 12000
    assert result.videos[0].creator_mid == "5005"
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_development_provider_cancellation_stops_before_http_request():
    requests = 0

    def handler(http_request: httpx.Request):
        nonlocal requests
        requests += 1
        return httpx.Response(200, json={"code": 0, "data": {"result": []}}, request=http_request)

    async def cancelled():
        return True

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = BilibiliDevelopmentSearchProvider(client=client, max_retries=0, min_interval_seconds=0)
    try:
        result = await provider.search_page(request(1), 1, cancelled)
    finally:
        await client.aclose()
    assert result.page.status == PageStatus.CANCELLED
    assert requests == 0


def test_provider_capabilities_distinguish_development_import_and_fixture():
    catalog = provider_capability_catalog()
    assert {item["provider_kind"] for item in catalog} == {"development", "import", "fixture"}
    development = next(item for item in catalog if item["provider_kind"] == "development")
    assert development["requires_login"] is False
    assert development["commercial_authorization"] == "development_only"


@pytest.mark.asyncio
async def test_import_json_and_csv_use_the_same_normalized_contract():
    json_provider = ImportSearchProvider.from_json((FIXTURES / "import_snapshot.json").read_text(encoding="utf-8"))
    csv_provider = ImportSearchProvider.from_csv((FIXTURES / "import_snapshot.csv").read_text(encoding="utf-8"))
    json_bundle = await execute_search_snapshot(json_provider, request(2))
    csv_bundle = await execute_search_snapshot(csv_provider, request(2))
    assert json_bundle.crawl_run.status == CrawlStatus.SUCCESS
    assert csv_bundle.crawl_run.status == CrawlStatus.SUCCESS
    assert json_bundle.crawl_run.pages[1].status == PageStatus.EMPTY
    assert csv_bundle.crawl_run.pages[1].status == PageStatus.EMPTY
    assert json_bundle.videos[1].creator_mid is None
    assert "view" in json_bundle.videos[1].missing_fields


def test_import_validation_rejects_unknown_json_fields_and_bad_csv_headers():
    payload = json.loads((FIXTURES / "import_snapshot.json").read_text(encoding="utf-8"))
    payload["private_reference_creators"] = []
    with pytest.raises(ValidationError):
        ImportSearchProvider.from_json(payload)
    bad_csv = (FIXTURES / "import_snapshot.csv").read_text(encoding="utf-8").replace(
        "missing_fields\n", "missing_fields,unknown_private_column\n", 1
    )
    with pytest.raises(ValueError, match="unknown columns"):
        ImportSearchProvider.from_csv(bad_csv)


@pytest.mark.asyncio
async def test_import_request_mismatch_fails_instead_of_bypassing_contract():
    provider = ImportSearchProvider.from_json((FIXTURES / "import_snapshot.json").read_text(encoding="utf-8"))
    result = await execute_search_snapshot(provider, request(1, sort_mode="newest"))
    assert result.crawl_run.status == CrawlStatus.FAILED
    assert result.crawl_run.pages[0].error_code == "IMPORT_REQUEST_MISMATCH"
