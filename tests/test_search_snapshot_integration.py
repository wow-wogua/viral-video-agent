import asyncio
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import src.worker as worker
from src.db.models import (
    AnalysisJob,
    CrawlRun,
    CrawlRunVideo,
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
        report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.job_id == job_id))
    assert job.status == "completed"
    assert run_ids and len(run_ids) == 1
    assert page_count == 2
    assert video_count == 2
    assert link_count == 2
    assert report_count == 0


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
