import asyncio
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import (
    AnalysisJob,
    CompetitorScoreRecord,
    CreatorAuditRecord,
    CreatorSampleVideoRecord,
    EvidenceItem,
    Report,
    User,
)
from src.db.session import Base
import src.worker as worker
from src.intelligence.competitor_service import analyze_competitors
from src.intelligence.competitor_store import get_competitor_results, persist_competitor_analysis
from src.intelligence.contracts import RelevanceLabel, SearchRequest
from src.intelligence.creator_providers import FixtureCreatorProvider
from src.intelligence.providers import ImportSearchProvider
from src.intelligence.relevance import FixtureRelevanceLabeler, RelevanceContext
from src.intelligence.search_service import execute_search_snapshot
from src.intelligence.snapshots import get_search_snapshot, persist_search_snapshot


CREATOR_FIXTURE = Path(__file__).parent / "fixtures" / "creator_provider" / "import_creator_sample.json"


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


def search_payload(keyword="sanitized topic"):
    return {
        "schema_version": "search-import.p0.1",
        "source_name": "p0-b-frozen-import-replay",
        "provider_version": "fixture-search-replay-v1",
        "snapshot_at": "2026-07-16T10:00:00Z",
        "keyword": keyword,
        "sort_mode": "relevance",
        "time_range": "all",
        "partition": None,
        "pages": [{
            "page_number": 1,
            "status": "success",
            "source_url": "https://example.test/search",
            "requested_at": "2026-07-16T10:00:00Z",
            "completed_at": "2026-07-16T10:00:01Z",
            "native_filters": {"lineage": "import replay"},
            "results": [
                {
                    "bvid": f"BV{index:010d}",
                    "title": f"sanitized topic search {index}",
                    "source_url": f"https://www.bilibili.com/video/BV{index:010d}",
                    "creator_mid": "90001",
                    "creator_name": "sanitized-specialist",
                    "published_at": f"2026-07-{10 + index:02d}T10:00:00Z",
                    "view": 10000 + index,
                    "like": 500,
                    "favorite": 200,
                    "reply": 80,
                    "danmaku": 40,
                    "missing_fields": ["coin", "share"],
                }
                for index in range(1, 4)
            ],
        }],
    }


async def create_job(factory, keyword="sanitized topic", *, worker_competitors=False):
    async with factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.test", hashed_password="hash")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query=f"analyze {keyword}",
            platforms=["bilibili"],
            task_mode="content_intelligence",
            keyword=keyword,
            sort_mode="relevance",
            time_range="all",
            max_pages=1,
            analysis_mode="standard",
            request_filters={
                "filters": {},
                "provider": {"kind": "import"},
                **({
                    "competitors": {
                        "enabled": True,
                        "context": {"category": "vertical"},
                        "creator_provider": {"kind": "fixture"},
                    }
                } if worker_competitors else {}),
            },
            idempotency_key=f"p0c-{uuid.uuid4()}",
        )
        db.add(job)
        await db.commit()
        return job.id


async def build_analysis(keyword="sanitized topic", category="vertical", label=RelevanceLabel.RELEVANT, crawl_run_id=None):
    payload = search_payload(keyword)
    search_bundle = await execute_search_snapshot(
        ImportSearchProvider.from_json(payload),
        SearchRequest(keyword=keyword, max_pages=1, idempotency_key=f"search-{uuid.uuid4()}"),
        crawl_run_id=crawl_run_id,
    )
    creator_provider = FixtureCreatorProvider.from_json(CREATOR_FIXTURE.read_text(encoding="utf-8"))
    creator_bvids = ["BV1000000101", "BV1000000102", "BV1000000103"]
    search_bvids = [f"BV{index:010d}" for index in range(1, 4)]
    analysis = await analyze_competitors(
        search_bundle,
        creator_provider,
        FixtureRelevanceLabeler({bvid: label for bvid in [*creator_bvids, *search_bvids]}),
        RelevanceContext(keyword=keyword, category=category),
    )
    return search_bundle, analysis


@pytest.mark.asyncio
async def test_frozen_snapshot_to_labels_scores_and_unpadded_top5_persists_without_report(session_factory):
    job_id = await create_job(session_factory)
    search_bundle, analysis = await build_analysis()
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, search_bundle)
        before = await get_search_snapshot(db, job_id)
        await persist_competitor_analysis(db, job_id, analysis)
        await db.commit()
        results = await get_competitor_results(db, job_id)
        after = await get_search_snapshot(db, job_id)
        report_count = await db.scalar(select(func.count()).select_from(Report))
    assert results["selected_count"] == 1
    assert results["shortfall_reason"]
    assert results["selected"][0]["qualification_status"] == "qualified_reference"
    assert len(results["selected"][0]["search_relevance_labels"]) == 3
    assert len(results["selected"][0]["creator_relevance_labels"]) == 3
    assert results["evidence"]
    assert before["videos"] == after["videos"]
    assert before["pages"] == after["pages"]
    assert report_count == 0


@pytest.mark.asyncio
async def test_same_task_retry_atomically_replaces_its_scores_and_evidence(session_factory):
    job_id = await create_job(session_factory)
    first_search, first_analysis = await build_analysis()
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, first_search)
        await persist_competitor_analysis(db, job_id, first_analysis)
        await db.commit()
        run_id = first_search.crawl_run.crawl_run_id

    retry_search, retry_analysis = await build_analysis(label=RelevanceLabel.IRRELEVANT, crawl_run_id=run_id)
    async with session_factory() as db:
        await persist_search_snapshot(db, job_id, retry_search)
        await persist_competitor_analysis(db, job_id, retry_analysis)
        await db.commit()
        results = await get_competitor_results(db, job_id)
        score_count = await db.scalar(select(func.count()).select_from(CompetitorScoreRecord))
        audit_count = await db.scalar(select(func.count()).select_from(CreatorAuditRecord))
        sample_count = await db.scalar(select(func.count()).select_from(CreatorSampleVideoRecord))
        evidence_count = await db.scalar(select(func.count()).select_from(EvidenceItem))
    assert results["selected_count"] == 0
    assert score_count == 1
    assert audit_count == 1
    assert sample_count == 3
    assert evidence_count == 6


@pytest.mark.asyncio
async def test_same_creator_is_scored_independently_across_keywords_and_runs(session_factory):
    first_job = await create_job(session_factory, "sanitized topic")
    second_job = await create_job(session_factory, "sanitized low result")
    first_search, first_analysis = await build_analysis("sanitized topic", "vertical")
    second_search, second_analysis = await build_analysis("sanitized low result", "low_result")
    async with session_factory() as db:
        await persist_search_snapshot(db, first_job, first_search)
        await persist_competitor_analysis(db, first_job, first_analysis)
        await persist_search_snapshot(db, second_job, second_search)
        await persist_competitor_analysis(db, second_job, second_analysis)
        await db.commit()
        first = await get_competitor_results(db, first_job)
        second = await get_competitor_results(db, second_job)
    assert first["selected_count"] == 1
    assert second["selected_count"] == 0
    assert first["crawl_run_id"] != second["crawl_run_id"]
    assert first["candidates"][0]["creator_mid"] == second["candidates"][0]["creator_mid"]


@pytest.mark.asyncio
async def test_pre_immutable_revision_run_is_rejected_for_p0c(session_factory):
    job_id = await create_job(session_factory)
    search_bundle, analysis = await build_analysis()
    async with session_factory() as db:
        run = await persist_search_snapshot(db, job_id, search_bundle)
        run.snapshot_revision = None
        await db.flush()
        with pytest.raises(ValueError, match="immutable snapshot revision"):
            await persist_competitor_analysis(db, job_id, analysis)


@pytest.mark.asyncio
async def test_worker_p0c_path_persists_competitors_and_never_creates_a_report(session_factory, monkeypatch):
    job_id = await create_job(session_factory, worker_competitors=True)
    labels = {
        **{f"BV{index:010d}": RelevanceLabel.RELEVANT for index in range(1, 4)},
        **{bvid: RelevanceLabel.RELEVANT for bvid in ("BV1000000101", "BV1000000102", "BV1000000103")},
    }
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "_search_provider_for_job", lambda job: ImportSearchProvider.from_json(search_payload()))
    monkeypatch.setattr(worker, "_creator_provider_for_job", lambda job: FixtureCreatorProvider.from_json(CREATOR_FIXTURE.read_text(encoding="utf-8")))
    monkeypatch.setattr(worker, "LLMRelevanceLabeler", lambda: FixtureRelevanceLabeler(labels))
    await worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id))
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        results = await get_competitor_results(db, job_id)
        report_count = await db.scalar(select(func.count()).select_from(Report).where(Report.job_id == job_id))
    assert job.status == "completed"
    assert results["selected_count"] == 1
    assert report_count == 0
