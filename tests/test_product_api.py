import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.db.models import AnalysisJob, EvidenceItem, Report, ShareLink, UsageRecord, User
from src.db.session import Base, get_db
from src.main import app
from src.queue import get_job_queue


class FakeQueue:
    async def enqueue(self, job_id: str, retry_count: int = 0) -> str:
        return f"fake:{job_id}:{retry_count}"


@pytest_asyncio.fixture
async def api_client():
    engine = create_async_engine("sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: FakeQueue()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def register(client: AsyncClient, email: str):
    response = await client.post("/auth/register", json={"email": email, "password": "strong-pass-123"})
    assert response.status_code == 201, response.text
    return response


@pytest.mark.asyncio
async def test_register_login_cookie_and_logout(api_client):
    client, _ = api_client
    response = await register(client, "owner@example.com")
    assert response.cookies.get("viral_video_session")
    assert (await client.get("/auth/me")).status_code == 200
    assert (await client.post("/auth/logout")).status_code == 204
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.post("/auth/login", json={"email": "owner@example.com", "password": "strong-pass-123"})).status_code == 200


@pytest.mark.asyncio
async def test_unauthenticated_job_access_is_rejected(api_client):
    client, _ = api_client
    response = await client.get("/jobs")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_job_creation_is_idempotent_and_cancellable(api_client):
    client, _ = api_client
    await register(client, "jobs@example.com")
    payload = {"query": "分析B站AI编程赛道的热门标题结构", "platforms": ["bilibili"], "analysis_mode": "standard", "idempotency_key": "stable-key-123"}
    first = await client.post("/jobs", json=payload)
    second = await client.post("/jobs", json=payload)
    assert first.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    cancelled = await client.post(f"/jobs/{first.json()['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_job_ownership_is_enforced(api_client):
    client, _ = api_client
    await register(client, "first@example.com")
    created = await client.post("/jobs", json={"query": "分析B站科技视频", "platforms": ["bilibili"], "analysis_mode": "standard", "idempotency_key": "owner-job-123"})
    job_id = created.json()["id"]
    await client.post("/auth/logout")
    await register(client, "second@example.com")
    response = await client.get(f"/jobs/{job_id}")
    assert response.status_code == 404
    assert response.json()["error_code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_report_share_is_read_only_and_redacted(api_client):
    client, session_factory = api_client
    user_response = await register(client, "report@example.com")
    user_id = uuid.UUID(user_response.json()["id"])
    async with session_factory() as db:
        job = AnalysisJob(user_id=user_id, query="B站科技赛道", platforms=["bilibili"], analysis_mode="standard", status="completed", progress=100, idempotency_key="report-job-123")
        db.add(job); await db.flush()
        report = Report(job_id=job.id, user_id=user_id, title="测试报告", content="# 测试", structured_claims=[{"claim": "观察", "claim_type": "observation", "evidence_ids": ["ev_12345678"], "confidence": 0.9}], status="completed", model_info={"trace": {"secret": "internal"}})
        db.add(report); await db.flush()
        db.add(EvidenceItem(evidence_id="ev_12345678", job_id=job.id, report_id=report.id, tool="search_videos", source_type="bilibili_video", title="真实视频", source_url="https://www.bilibili.com/video/BV1", platform="bilibili", raw_data={"bvid": "BV1"}, data_fields={"view": 1}))
        db.add(UsageRecord(user_id=user_id, job_id=job.id, input_tokens=10, output_tokens=20, estimated_cost=0.1, asr_seconds=0)); await db.commit()
        report_id = report.id
    share = await client.post(f"/reports/{report_id}/shares", json={"expires_in_days": 7})
    assert share.status_code == 201
    public_client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    try:
        shared = await public_client.get(f"/shares/{share.json()['token']}")
    finally:
        await public_client.aclose()
    assert shared.status_code == 200
    assert shared.json()["model_info"] == {}
    assert shared.json()["usage"] is None
    assert shared.json()["evidence"][0]["source_url"].startswith("https://www.bilibili.com/")


@pytest.mark.asyncio
async def test_expired_share_is_rejected(api_client):
    client, session_factory = api_client
    user_response = await register(client, "expired@example.com")
    user_id = uuid.UUID(user_response.json()["id"])
    async with session_factory() as db:
        job = AnalysisJob(user_id=user_id, query="x", platforms=["bilibili"], analysis_mode="standard", status="completed", progress=100, idempotency_key="expired-job")
        db.add(job); await db.flush(); report = Report(job_id=job.id, user_id=user_id, title="x", content="# x", structured_claims=[], status="completed", model_info={}); db.add(report); await db.flush()
        import hashlib
        db.add(ShareLink(report_id=report.id, user_id=user_id, token_hash=hashlib.sha256(b"expired-token").hexdigest(), expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))); await db.commit()
    response = await client.get("/shares/expired-token")
    assert response.status_code == 404
