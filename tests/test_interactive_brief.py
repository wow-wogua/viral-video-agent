import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.briefing.schemas import BriefDecision, BriefOption, TopicSpec
from src.briefing.service import BriefValidationResult, validate_job_brief
from src.briefing.validator import BriefValidator
from src.db.models import AnalysisJob, JobClarification, JobEvent, UsageRecord, User
from src.db.session import Base, get_db
from src.gateway.cost_tracker import cost_tracker
from src.main import app
from src.queue import get_job_queue


def topic_spec(**overrides):
    values = {
        "topic": "相机",
        "target_content": ["相机测评"],
        "include_creator_types": ["reviewer"],
        "exclude_content": ["旅行日志"],
        "time_window_days": 365,
        "allow_generalist": False,
        "competitor_definition": "持续发布相机相关内容的账号",
        "platform": "bilibili",
        "assumptions": [],
        "confidence": 0.88,
    }
    values.update(overrides)
    return values


def clarification_decision() -> BriefDecision:
    return BriefDecision(
        need_clarification=True,
        question="是否只纳入专业账号？",
        options=[
            BriefOption(id="strict", label="专业账号", description="排除综合账号"),
            BriefOption(id="generalist", label="综合账号", description="允许稳定发布相关内容的综合账号"),
        ],
        allow_custom=True,
        verification="缺少账号范围",
        confidence=0.6,
    )


def test_topic_spec_and_brief_decision_are_strict():
    assert TopicSpec.model_validate(topic_spec()).platform == "bilibili"
    for invalid in (
        topic_spec(platform="douyin"),
        topic_spec(confidence=1.1),
        topic_spec(topic="x" * 121),
        {**topic_spec(), "unexpected": True},
    ):
        with pytest.raises(ValueError):
            TopicSpec.model_validate(invalid)
    with pytest.raises(ValueError):
        BriefDecision.model_validate({
            "need_clarification": True,
            "question": "范围？",
            "options": [{"id": "only", "label": "一个", "description": "不足两个选项"}],
            "allow_custom": True,
            "verification": "x",
            "topic_spec": None,
            "confidence": 0.5,
        })


@pytest.mark.asyncio
async def test_invalid_llm_json_uses_conservative_clarification():
    class FakeLlm:
        async def ainvoke(self, _messages):
            return SimpleNamespace(content="not-json", usage_metadata={"input_tokens": 3, "output_tokens": 2})

    validator = BriefValidator(llm_factory=lambda: FakeLlm())
    first = await validator.validate("分析相机账号", [], 1)
    second = await validator.validate("分析相机账号", [], 2)
    assert first.need_clarification is True
    assert len(first.options) == 2
    assert second.need_clarification is True
    assert len(second.options) == 2


@pytest_asyncio.fixture
async def session_factory(tmp_path):
    database_path = (tmp_path / "interactive-brief.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


async def create_user_job(factory, *, status="pending", interaction_usage=None):
    async with factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="hashed")
        db.add(user)
        await db.flush()
        job = AnalysisJob(
            user_id=user.id,
            query="分析B站相机赛道的竞争账号",
            platforms=["bilibili"],
            analysis_mode="standard",
            status=status,
            idempotency_key=str(uuid.uuid4()),
            interaction_usage=interaction_usage or {},
        )
        db.add(job)
        await db.commit()
        return user.id, job.id


@pytest.mark.asyncio
async def test_brief_state_survives_new_sessions_and_usage_accumulates(session_factory, monkeypatch):
    from src.briefing import service

    monkeypatch.setattr(service, "async_session_factory", session_factory)
    _, job_id = await create_user_job(session_factory, status="running")

    class SequenceValidator:
        calls = 0

        async def validate(self, _query, _history, _round):
            self.calls += 1
            cost_tracker.log_usage("planner", "deepseek-v4-pro", 10, 5)
            if self.calls == 1:
                return clarification_decision()
            return BriefDecision(
                need_clarification=False,
                verification="范围明确",
                topic_spec=TopicSpec.model_validate(topic_spec()),
                confidence=0.9,
            )

    validator = SequenceValidator()
    cost_tracker.reset()
    paused = await validate_job_brief(job_id, validator)
    assert paused.ready is False

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        clarification = (await db.execute(select(JobClarification).where(JobClarification.job_id == job_id))).scalar_one()
        assert job.status == "waiting_user"
        clarification.status = "answered"
        clarification.selected_option_id = "strict"
        job.status = "running"
        await db.commit()

    cost_tracker.reset()
    ready = await validate_job_brief(job_id, validator)
    assert ready.ready is True
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        assert job.topic_spec["topic"] == "相机"
        assert job.interaction_usage["input_tokens"] == 20
        assert job.interaction_usage["output_tokens"] == 10
        assert job.interaction_usage["estimated_cost"] > 0
        assert job.interaction_usage["calls"] == 2


@pytest.mark.asyncio
async def test_real_validator_allows_two_rounds_without_third_llm_call(session_factory, monkeypatch):
    from src.briefing import service

    monkeypatch.setattr(service, "async_session_factory", session_factory)
    _, job_id = await create_user_job(session_factory, status="running")

    class FakeLlm:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return SimpleNamespace(
                content=json.dumps(clarification_decision().model_dump(mode="json"), ensure_ascii=False),
                usage_metadata={"input_tokens": 3, "output_tokens": 2},
            )

    fake_llm = FakeLlm()
    validator = BriefValidator(llm_factory=lambda: fake_llm)

    for expected_round in (1, 2):
        cost_tracker.reset()
        result = await validate_job_brief(job_id, validator)
        assert result.ready is False
        async with session_factory() as db:
            row = await db.scalar(select(JobClarification).where(JobClarification.job_id == job_id, JobClarification.round == expected_round))
            row.status = "answered"
            row.selected_option_id = "strict"
            job = await db.get(AnalysisJob, job_id)
            job.status = "running"
            await db.commit()

    cost_tracker.reset()
    final = await validate_job_brief(job_id, validator)
    assert final.ready is True
    assert final.topic_spec.assumptions
    assert final.topic_spec.confidence <= 0.5
    assert fake_llm.calls == 2
    async with session_factory() as db:
        rows = list((await db.scalars(select(JobClarification).where(JobClarification.job_id == job_id))).all())
        job = await db.get(AnalysisJob, job_id)
        assert len(rows) == 2
        assert job.interaction_usage["calls"] == 2


class CapturingQueue:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.calls = []
        self.observed = []
        self.fail_next = False

    async def enqueue(self, job_id: str, execution_version: int = 0) -> str:
        self.calls.append((job_id, execution_version))
        async with self.session_factory() as db:
            job = await db.get(AnalysisJob, uuid.UUID(job_id))
            self.observed.append((job.status, job.execution_version))
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("queue unavailable")
        return f"fake:{job_id}:v{execution_version}"


@pytest_asyncio.fixture
async def api_client(session_factory):
    queue = CapturingQueue(session_factory)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_job_queue] = lambda: queue
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session_factory, queue
    app.dependency_overrides.clear()


async def register(client: AsyncClient, email: str):
    response = await client.post("/auth/register", json={"email": email, "password": "strong-pass-123"})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def create_waiting_job(factory, user_id):
    async with factory() as db:
        job = AnalysisJob(user_id=user_id, query="分析相机账号", platforms=["bilibili"], analysis_mode="standard", status="waiting_user", progress=5, clarification_round=1, idempotency_key=str(uuid.uuid4()))
        db.add(job)
        await db.flush()
        request = JobClarification(job_id=job.id, round=1, question="范围？", options=[{"id": "strict", "label": "专业", "description": "只纳入专业账号"}, {"id": "generalist", "label": "综合", "description": "允许综合账号"}], allow_custom=True, status="pending")
        db.add(request)
        await db.commit()
        return job.id, request.request_id


@pytest.mark.asyncio
async def test_clarification_api_is_owned_idempotent_and_conflict_safe(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "brief-owner@example.com")
    job_id, request_id = await create_waiting_job(factory, owner_id)

    current = await client.get(f"/jobs/{job_id}/clarification")
    assert current.status_code == 200
    assert current.json()["current"]["request_id"] == str(request_id)

    payload = {"request_id": str(request_id), "selected_option_id": "strict", "custom_answer": "排除偶尔发布者"}
    first = await client.post(f"/jobs/{job_id}/clarification", json=payload)
    duplicate = await client.post(f"/jobs/{job_id}/clarification", json=payload)
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["status"] == "pending"
    assert first.json()["execution_version"] == 1
    assert len(queue.calls) == 1
    assert queue.observed == [("pending", 1)]

    conflict = await client.post(f"/jobs/{job_id}/clarification", json={**payload, "custom_answer": "改成纳入综合账号"})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "CLARIFICATION_CONFLICT"

    await client.post("/auth/logout")
    await register(client, "brief-other@example.com")
    assert (await client.get(f"/jobs/{job_id}/clarification")).status_code == 404
    assert (await client.post(f"/jobs/{job_id}/clarification", json=payload)).status_code == 404


@pytest.mark.asyncio
async def test_retry_commits_new_state_before_enqueue(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "brief-retry@example.com")
    async with factory() as db:
        job = AnalysisJob(
            user_id=owner_id,
            query="分析相机账号",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="failed",
            retry_count=1,
            execution_version=3,
            error_code="WORKER_FAILED",
            error_message="failed",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    response = await client.post(f"/jobs/{job_id}/retry")
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["retry_count"] == 2
    assert response.json()["execution_version"] == 4
    assert queue.calls == [(str(job_id), 4)]
    assert queue.observed == [("pending", 4)]


@pytest.mark.asyncio
async def test_enqueue_failure_is_recoverable_without_losing_answer(api_client):
    client, factory, queue = api_client
    owner_id = await register(client, "brief-queue-failure@example.com")
    job_id, request_id = await create_waiting_job(factory, owner_id)
    payload = {"request_id": str(request_id), "selected_option_id": "strict", "custom_answer": "只看专业账号"}
    queue.fail_next = True

    failed = await client.post(f"/jobs/{job_id}/clarification", json=payload)
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "WORKER_FAILED"
    assert queue.observed == [("pending", 1)]

    async with factory() as db:
        job = await db.get(AnalysisJob, job_id)
        clarification = await db.scalar(select(JobClarification).where(JobClarification.request_id == request_id))
        events = list((await db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.created_at))).all())
        assert job.status == "failed"
        assert job.error_code == "WORKER_FAILED"
        assert job.execution_version == 1
        assert clarification.status == "answered"
        assert clarification.selected_option_id == "strict"
        assert clarification.custom_answer == "只看专业账号"
        assert any(event.event_type == "failed" for event in events)

    recovered = await client.post(f"/jobs/{job_id}/retry")
    assert recovered.status_code == 202
    assert recovered.json()["status"] == "pending"
    assert recovered.json()["execution_version"] == 2
    assert recovered.json()["retry_count"] == 1
    assert queue.calls == [(str(job_id), 1), (str(job_id), 2)]
    assert queue.observed == [("pending", 1), ("pending", 2)]


@pytest.mark.asyncio
async def test_waiting_job_can_cancel_but_cannot_use_regular_retry(api_client):
    client, factory, _ = api_client
    owner_id = await register(client, "brief-cancel@example.com")
    job_id, _ = await create_waiting_job(factory, owner_id)
    retry = await client.post(f"/jobs/{job_id}/retry")
    assert retry.status_code == 409
    cancelled = await client.post(f"/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert (await client.post(f"/jobs/{job_id}/retry")).status_code == 409


@pytest.mark.asyncio
async def test_worker_stops_before_graph_when_brief_waits(session_factory, monkeypatch):
    from src import worker

    _, job_id = await create_user_job(session_factory, status="pending")
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)

    async def fake_brief(current_job_id, expected_execution_version=None):
        assert expected_execution_version == 0
        async with session_factory() as db:
            job = await db.get(AnalysisJob, current_job_id)
            job.status = "waiting_user"
            await db.commit()
        return BriefValidationResult(ready=False)

    async def forbidden_graph(*_args, **_kwargs):
        raise AssertionError("graph must not run before clarification")

    monkeypatch.setattr(worker, "validate_job_brief", fake_brief)
    monkeypatch.setattr(worker, "_invoke_graph", forbidden_graph)
    await worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id), 0)
    async with session_factory() as db:
        assert (await db.get(AnalysisJob, job_id)).status == "waiting_user"


@pytest.mark.asyncio
async def test_worker_preserves_cancellation_during_real_brief_service(api_client, monkeypatch):
    from src import worker
    from src.briefing import service

    client, session_factory, _ = api_client
    owner_id = await register(client, "brief-validator-cancel@example.com")
    async with session_factory() as db:
        job = AnalysisJob(
            user_id=owner_id,
            query="分析相机账号",
            platforms=["bilibili"],
            analysis_mode="standard",
            status="pending",
            idempotency_key=str(uuid.uuid4()),
        )
        db.add(job)
        await db.commit()
        job_id = job.id
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(service, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingValidator:
        async def validate(self, _query, _history, _round):
            started.set()
            await release.wait()
            cost_tracker.log_usage("planner", "deepseek-v4-pro", 7, 3)
            return clarification_decision()

    monkeypatch.setattr(service, "BriefValidator", BlockingValidator)

    async def forbidden_graph(*_args, **_kwargs):
        raise AssertionError("cancelled job must not enter graph")

    monkeypatch.setattr(worker, "_invoke_graph", forbidden_graph)
    task = asyncio.create_task(worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id), 0))
    await asyncio.wait_for(started.wait(), timeout=2)
    cancelled = await client.post(f"/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release.set()
    await asyncio.wait_for(task, timeout=2)

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        clarifications = list((await db.scalars(select(JobClarification).where(JobClarification.job_id == job_id))).all())
        assert job.status == "cancelled"
        assert job.cancelled_at is not None
        assert job.topic_spec is None
        assert job.interaction_usage["input_tokens"] == 7
        assert job.interaction_usage["output_tokens"] == 3
        assert job.interaction_usage["calls"] == 1
        assert clarifications == []


@pytest.mark.asyncio
async def test_stale_execution_version_cannot_write_brief_result(session_factory, monkeypatch):
    from src.briefing import service

    monkeypatch.setattr(service, "async_session_factory", session_factory)
    _, job_id = await create_user_job(session_factory, status="running")
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingValidator:
        async def validate(self, _query, _history, _round):
            started.set()
            await release.wait()
            cost_tracker.log_usage("planner", "deepseek-v4-pro", 11, 4)
            return clarification_decision()

    cost_tracker.reset()
    task = asyncio.create_task(validate_job_brief(job_id, BlockingValidator(), expected_execution_version=0))
    await asyncio.wait_for(started.wait(), timeout=2)
    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        job.execution_version = 1
        await db.commit()
    release.set()
    result = await asyncio.wait_for(task, timeout=2)
    assert result.ready is False

    async with session_factory() as db:
        job = await db.get(AnalysisJob, job_id)
        clarifications = list((await db.scalars(select(JobClarification).where(JobClarification.job_id == job_id))).all())
        assert job.status == "running"
        assert job.execution_version == 1
        assert job.topic_spec is None
        assert job.interaction_usage["input_tokens"] == 11
        assert job.interaction_usage["output_tokens"] == 4
        assert job.interaction_usage["calls"] == 1
        assert clarifications == []


@pytest.mark.asyncio
async def test_feature_off_skips_brief_and_preserves_graph_entry(session_factory, monkeypatch):
    from src import worker

    _, job_id = await create_user_job(session_factory, status="pending")
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", False)
    called = {"graph": 0}

    async def forbidden_brief(_job_id):
        raise AssertionError("brief validator must be disabled")

    async def fake_graph(*_args, **_kwargs):
        called["graph"] += 1
        return {"report_final": "# mock", "analysis": {"claims": []}, "evidence": []}

    async def fake_persist(_job_id, _result):
        return uuid.uuid4()

    monkeypatch.setattr(worker, "validate_job_brief", forbidden_brief)
    monkeypatch.setattr(worker, "_invoke_graph", fake_graph)
    monkeypatch.setattr(worker, "_persist_result", fake_persist)
    await worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id), 0)
    assert called["graph"] == 1


@pytest.mark.asyncio
async def test_clear_brief_passes_topic_spec_into_existing_graph(session_factory, monkeypatch):
    from src import worker

    _, job_id = await create_user_job(session_factory, status="pending")
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    monkeypatch.setattr(worker, "ENABLE_INTERACTIVE_BRIEF", True)
    captured = {}

    async def ready_brief(_job_id, expected_execution_version=None):
        assert expected_execution_version == 0
        return BriefValidationResult(ready=True, topic_spec=TopicSpec.model_validate(topic_spec()))

    async def fake_graph(_job_id, _user_id, _query, _platforms, structured_scope, execution_version):
        captured["topic_spec"] = structured_scope
        captured["execution_version"] = execution_version
        return {"report_final": "# mock", "analysis": {"claims": []}, "evidence": []}

    async def fake_persist(_job_id, _result):
        return uuid.uuid4()

    monkeypatch.setattr(worker, "validate_job_brief", ready_brief)
    monkeypatch.setattr(worker, "_invoke_graph", fake_graph)
    monkeypatch.setattr(worker, "_persist_result", fake_persist)
    await worker.run_analysis_job({"provider_semaphore": asyncio.Semaphore(1)}, str(job_id), 0)
    assert captured["topic_spec"]["topic"] == "相机"
    assert captured["execution_version"] == 0


@pytest.mark.asyncio
async def test_final_usage_includes_all_brief_calls(session_factory, monkeypatch):
    from src import worker

    user_id, job_id = await create_user_job(session_factory, status="running", interaction_usage={"input_tokens": 10, "output_tokens": 5, "estimated_cost": 0.1, "calls": 2})
    monkeypatch.setattr(worker, "async_session_factory", session_factory)
    cost_tracker.reset()
    cost_tracker.log_usage("planner", "deepseek-v4-pro", 100, 50)
    await worker._persist_result(job_id, {"report_final": "# 测试报告", "analysis": {"claims": []}, "evidence": [], "workflow_version": "v2"})
    async with session_factory() as db:
        usage = await db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
        assert usage.user_id == user_id
        assert usage.input_tokens == 110
        assert usage.output_tokens == 55
        assert usage.estimated_cost > 0.1
