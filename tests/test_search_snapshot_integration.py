import asyncio
import json
import uuid
from datetime import timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.worker as worker
from src.db.models import (
    AnalysisJob,
    CrawlRun,
    CrawlRunCreatorObservation,
    CrawlRunVideo,
    CreatorRecord,
    Report,
    SearchPageRecord,
    User,
    VideoRecord,
)
from src.db.session import Base
from src.intelligence.contracts import CrawlStatus, SearchRequest
from src.intelligence.providers import FixtureSearchProvider, ImportSearchProvider
from src.intelligence.search_service import execute_search_snapshot
from src.intelligence.snapshots import get_search_snapshot, persist_search_snapshot


FIXTURE = Path(__file__).parent / "fixtures" / "search_provider" / "import_snapshot.json"


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("PRAGMA foreign_keys=ON"))
        await connection.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


async def create_job(factory, *, keyword="脱敏关键词", task_mode="content_intelligence"):
    async with factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.test", hashed_password="hash")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query=f"分析B站{keyword}",
            platforms=["bilibili"],
            task_mode=task_mode,
            keyword=keyword if task_mode == "content_intelligence" else None,
            sort_mode="relevance",
            time_range="all",
            max_pages=2 if task_mode == "content_intelligence" else 1,
            analysis_mode="standard",
            request_filters={"filters": {}, "provider": {"kind": "development"}},
            idempotency_key=f"integration-{uuid.uuid4()}",
        )
        db.add(job)
        await db.commit()
        return job.id


def one_page_payload(
    *,
    bvid="BV1000000001",
    mid="3003",
    title="first-title",
    creator_name="first-creator",
    view=100,
    observed_at="2026-07-16T01:00:00+00:00",
    provider_version="first-provider",
):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["provider_version"] = provider_version
    payload["snapshot_at"] = observed_at
    payload["pages"] = [payload["pages"][0]]
    payload["pages"][0]["requested_at"] = observed_at
    payload["pages"][0]["completed_at"] = observed_at
    payload["pages"][0]["results"] = [payload["pages"][0]["results"][0]]
    result = payload["pages"][0]["results"][0]
    result.update({
        "bvid": bvid,
        "title": title,
        "source_url": f"https://www.bilibili.com/video/{bvid}",
        "creator_mid": mid,
        "creator_name": creator_name,
        "view": view,
        "observed_at": observed_at,
    })
    return payload


async def bundle_from_payload(payload, idempotency_key, crawl_run_id=None):
    return await execute_search_snapshot(
        ImportSearchProvider.from_json(payload),
        SearchRequest(keyword=payload["keyword"], max_pages=len(payload["pages"]), idempotency_key=idempotency_key),
        crawl_run_id=crawl_run_id,
    )


@pytest.mark.asyncio
async def test_provider_output_persists_complete_page_snapshot(session_factory):
    job_id = await create_job(session_factory)
    provider = FixtureSearchProvider.from_json(FIXTURE.read_text(encoding="utf-8"))
    bundle = await execute_search_snapshot(
        provider,
        SearchRequest(keyword="脱敏关键词", max_pages=2, idempotency_key="integration-snapshot"),
    )
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, bundle)
        await db.commit()
        snapshot = await get_search_snapshot(db, job_id)
    assert snapshot["status"] == "success"
    assert snapshot["coverage"]["successful_pages"] == 2
    assert [page["status"] for page in snapshot["pages"]] == ["success", "empty"]
    assert len(snapshot["videos"]) == 2
    assert snapshot["videos"][0]["source_page"] == 1
    assert snapshot["pages"][0]["raw_payload_hash"]


@pytest.mark.asyncio
async def test_partial_snapshot_remains_queryable(session_factory):
    job_id = await create_job(session_factory)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["pages"][1] = {
        "page_number": 2,
        "status": "failed",
        "source_url": "https://example.test/search?page=2",
        "error_code": "FIXTURE_PAGE_FAILED",
        "error_summary": "injected page failure",
        "results": [],
    }
    provider = ImportSearchProvider.from_json(payload)
    bundle = await execute_search_snapshot(
        provider,
        SearchRequest(keyword="脱敏关键词", max_pages=2, idempotency_key="integration-partial"),
    )
    assert bundle.crawl_run.status == CrawlStatus.PARTIAL
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, bundle)
        await db.commit()
        snapshot = await get_search_snapshot(db, job_id)
    assert snapshot["partial_success"] is True
    assert snapshot["pages"][1]["error_code"] == "FIXTURE_PAGE_FAILED"
    assert len(snapshot["videos"]) == 2


@pytest.mark.asyncio
async def test_cross_job_video_observations_are_immutable(session_factory):
    job_a = await create_job(session_factory)
    job_b = await create_job(session_factory)
    bundle_a = await bundle_from_payload(
        one_page_payload(title="first-title", view=100, observed_at="2026-07-16T01:00:00+00:00", provider_version="first-provider"),
        "cross-job-video-a",
    )
    bundle_b = await bundle_from_payload(
        one_page_payload(title="second-title", view=200, observed_at="2026-07-16T02:00:00+00:00", provider_version="second-provider"),
        "cross-job-video-b",
    )
    async with session_factory() as db:
        await persist_search_snapshot(db, job_a, bundle_a)
        await db.commit()
        await persist_search_snapshot(db, job_b, bundle_b)
        await db.commit()
        snapshot_a = await get_search_snapshot(db, job_a)
        snapshot_b = await get_search_snapshot(db, job_b)
        global_video = await db.get(VideoRecord, "BV1000000001")
    assert snapshot_a["videos"][0]["title"] == "first-title"
    assert snapshot_a["videos"][0]["view"] == 100
    assert snapshot_a["videos"][0]["provider_version"] == "first-provider"
    observed_at = snapshot_a["videos"][0]["observed_at"]
    assert observed_at.replace(tzinfo=observed_at.tzinfo or timezone.utc).isoformat() == "2026-07-16T01:00:00+00:00"
    assert snapshot_b["videos"][0]["title"] == "second-title"
    assert snapshot_b["videos"][0]["view"] == 200
    assert global_video.title == "second-title"


@pytest.mark.asyncio
async def test_cross_job_creator_observations_are_immutable(session_factory):
    job_a = await create_job(session_factory)
    job_b = await create_job(session_factory)
    bundle_a = await bundle_from_payload(
        one_page_payload(bvid="BV1000000001", creator_name="first-creator", observed_at="2026-07-16T01:00:00+00:00", provider_version="first-provider"),
        "cross-job-creator-a",
    )
    bundle_b = await bundle_from_payload(
        one_page_payload(bvid="BV1000000003", creator_name="second-creator", observed_at="2026-07-16T02:00:00+00:00", provider_version="second-provider"),
        "cross-job-creator-b",
    )
    bundle_a.creators[0] = bundle_a.creators[0].model_copy(update={"follower_count": 100, "profile_url": "https://example.test/first"})
    bundle_b.creators[0] = bundle_b.creators[0].model_copy(update={"follower_count": 200, "profile_url": "https://example.test/second"})
    async with session_factory() as db:
        await persist_search_snapshot(db, job_a, bundle_a)
        await db.commit()
        await persist_search_snapshot(db, job_b, bundle_b)
        await db.commit()
        snapshot_a = await get_search_snapshot(db, job_a)
        snapshot_b = await get_search_snapshot(db, job_b)
        global_creator = await db.get(CreatorRecord, "3003")
    assert snapshot_a["creators"][0]["name"] == "first-creator"
    assert snapshot_a["creators"][0]["follower_count"] == 100
    assert snapshot_a["creators"][0]["profile_url"] == "https://example.test/first"
    assert snapshot_a["creators"][0]["provider_version"] == "first-provider"
    assert snapshot_b["creators"][0]["name"] == "second-creator"
    assert snapshot_b["creators"][0]["follower_count"] == 200
    assert global_creator.name == "second-creator"


@pytest.mark.asyncio
async def test_partial_snapshot_observations_survive_later_jobs(session_factory):
    job_a = await create_job(session_factory)
    job_b = await create_job(session_factory)
    payload_a = one_page_payload(title="partial-title", creator_name="partial-creator", provider_version="partial-provider")
    payload_a["pages"].append({
        "page_number": 2,
        "status": "failed",
        "source_url": "https://example.test/search?page=2",
        "requested_at": "2026-07-16T01:01:00+00:00",
        "completed_at": "2026-07-16T01:01:01+00:00",
        "error_code": "INJECTED_FAILURE",
        "error_summary": "injected partial page",
        "results": [],
    })
    bundle_a = await bundle_from_payload(payload_a, "partial-isolation-a")
    bundle_b = await bundle_from_payload(
        one_page_payload(title="later-title", creator_name="later-creator", provider_version="later-provider"),
        "partial-isolation-b",
    )
    async with session_factory() as db:
        await persist_search_snapshot(db, job_a, bundle_a)
        await db.commit()
        await persist_search_snapshot(db, job_b, bundle_b)
        await db.commit()
        snapshot_a = await get_search_snapshot(db, job_a)
    assert snapshot_a["status"] == "partial"
    assert [page["status"] for page in snapshot_a["pages"]] == ["success", "failed"]
    assert snapshot_a["pages"][1]["error_code"] == "INJECTED_FAILURE"
    assert snapshot_a["videos"][0]["title"] == "partial-title"
    assert snapshot_a["creators"][0]["name"] == "partial-creator"


@pytest.mark.asyncio
async def test_latest_snapshot_preserves_missing_mid_as_null(session_factory):
    job_id = await create_job(session_factory)
    first_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first_payload["pages"] = [first_payload["pages"][0]]
    first_payload["pages"][0]["results"] = [first_payload["pages"][0]["results"][0]]
    first = await execute_search_snapshot(
        ImportSearchProvider.from_json(first_payload),
        SearchRequest(keyword="脱敏关键词", max_pages=1, idempotency_key="latest-mid-first"),
    )
    second_payload = json.loads(json.dumps(first_payload, ensure_ascii=False))
    second_payload["pages"][0]["results"][0]["creator_mid"] = None
    second_payload["pages"][0]["results"][0]["creator_name"] = None
    second = await execute_search_snapshot(
        ImportSearchProvider.from_json(second_payload),
        SearchRequest(keyword="脱敏关键词", max_pages=1, idempotency_key="latest-mid-second"),
        crawl_run_id=first.crawl_run.crawl_run_id,
    )
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, first)
        await db.commit()
        await persist_search_snapshot(db, job_id, second)
        await db.commit()
        snapshot = await get_search_snapshot(db, job_id)
    assert snapshot["videos"][0]["creator_mid"] is None
    assert "creator_mid" in snapshot["videos"][0]["missing_fields"]


@pytest.mark.asyncio
async def test_same_job_retry_replaces_only_its_own_observations(session_factory):
    job_id = await create_job(session_factory)
    first = await bundle_from_payload(one_page_payload(title="retry-first"), "same-job-retry-first")
    second = await bundle_from_payload(
        one_page_payload(title="retry-second", creator_name="retry-second-creator", view=999, provider_version="retry-second-provider"),
        "same-job-retry-second",
        crawl_run_id=first.crawl_run.crawl_run_id,
    )
    async with session_factory() as db:
        run = await persist_search_snapshot(db, job_id, first)
        await db.commit()
        first_run_id = run.id
        run = await persist_search_snapshot(db, job_id, second)
        await db.commit()
        snapshot = await get_search_snapshot(db, job_id)
        run_count = await db.scalar(select(func.count()).select_from(CrawlRun).where(CrawlRun.job_id == job_id))
        page_count = await db.scalar(select(func.count()).select_from(SearchPageRecord).where(SearchPageRecord.crawl_run_id == run.id))
        video_count = await db.scalar(select(func.count()).select_from(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run.id))
        creator_count = await db.scalar(select(func.count()).select_from(CrawlRunCreatorObservation).where(CrawlRunCreatorObservation.crawl_run_id == run.id))
    assert run.id == first_run_id
    assert run_count == page_count == video_count == creator_count == 1
    assert snapshot["videos"][0]["title"] == "retry-second"
    assert snapshot["videos"][0]["view"] == 999
    assert snapshot["creators"][0]["name"] == "retry-second-creator"


@pytest.mark.asyncio
async def test_worker_content_intelligence_path_is_idempotent_and_creates_no_report(session_factory, monkeypatch):
    job_id = await create_job(session_factory)
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(
        worker,
        "_search_provider_for_job",
        lambda job: FixtureSearchProvider.from_json(FIXTURE.read_text(encoding="utf-8")),
    )
    ctx = {"provider_semaphore": asyncio.Semaphore(1)}
    await worker.run_analysis_job(ctx, str(job_id))
    await worker.run_analysis_job(ctx, str(job_id))

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        run_ids = list((await db.scalars(select(CrawlRun.id).where(CrawlRun.job_id == job_id))).all())
        page_count = await db.scalar(select(func.count()).select_from(SearchPageRecord))
        video_count = await db.scalar(select(func.count()).select_from(VideoRecord))
        link_count = await db.scalar(select(func.count()).select_from(CrawlRunVideo))
        creator_observation_count = await db.scalar(select(func.count()).select_from(CrawlRunCreatorObservation))
        report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.job_id == job_id))
    assert job.status == "completed"
    assert run_ids and len(run_ids) == 1
    assert page_count == 2
    assert video_count == 2
    assert link_count == 2
    assert creator_observation_count == 1
    assert report_count == 0


@pytest.mark.asyncio
async def test_crawl_run_and_job_deletion_cleanup_observations_only(session_factory):
    job_a = await create_job(session_factory)
    job_b = await create_job(session_factory)
    bundle_a = await bundle_from_payload(one_page_payload(title="delete-a"), "delete-observation-a")
    bundle_b = await bundle_from_payload(one_page_payload(title="delete-b"), "delete-observation-b")
    async with session_factory() as db:
        run_a = await persist_search_snapshot(db, job_a, bundle_a)
        run_b = await persist_search_snapshot(db, job_b, bundle_b)
        await db.commit()
        run_a_id, run_b_id = run_a.id, run_b.id

        await db.delete(run_a)
        await db.commit()
        assert await db.get(CrawlRun, run_a_id) is None
        assert await db.scalar(select(func.count()).select_from(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run_a_id)) == 0
        assert await db.scalar(select(func.count()).select_from(CrawlRunCreatorObservation).where(CrawlRunCreatorObservation.crawl_run_id == run_a_id)) == 0
        assert await db.scalar(select(func.count()).select_from(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run_b_id)) == 1
        assert await db.get(VideoRecord, "BV1000000001") is not None
        assert await db.get(CreatorRecord, "3003") is not None

        job = await db.get(AnalysisJob, job_b)
        await db.delete(job)
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(CrawlRun).where(CrawlRun.id == run_b_id)) == 0
        assert await db.scalar(select(func.count()).select_from(CrawlRunVideo).where(CrawlRunVideo.crawl_run_id == run_b_id)) == 0
        assert await db.scalar(select(func.count()).select_from(CrawlRunCreatorObservation).where(CrawlRunCreatorObservation.crawl_run_id == run_b_id)) == 0
        assert await db.get(VideoRecord, "BV1000000001") is not None
        assert await db.get(CreatorRecord, "3003") is not None


@pytest.mark.asyncio
async def test_zero_success_snapshot_never_creates_normal_report(session_factory):
    job_id = await create_job(session_factory)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["pages"] = [{
        "page_number": 1,
        "status": "failed",
        "source_url": "https://example.test/search?page=1",
        "error_code": "FIXTURE_FAILED",
        "error_summary": "injected failure",
        "results": [],
    }]
    provider = ImportSearchProvider.from_json(payload)
    bundle = await execute_search_snapshot(
        provider,
        SearchRequest(keyword="脱敏关键词", max_pages=1, idempotency_key="integration-failed"),
    )
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, bundle)
        await db.commit()
        report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.job_id == job_id))
        snapshot = await get_search_snapshot(db, job_id)
    assert snapshot["status"] == "failed"
    assert snapshot["coverage"]["successful_pages"] == 0
    assert report_count == 0
