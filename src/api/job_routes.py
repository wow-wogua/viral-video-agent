import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from src.api.errors import AppError, ERROR_MESSAGES
from src.api.schemas import JobCreate, JobEventRead, JobRead
from src.auth.dependencies import get_current_user
from src.briefing.schemas import ClarificationAnswer, ClarificationRead
from src.config import USER_MONTHLY_JOB_LIMIT
from src.db.models import AnalysisJob, JobEvent, User
from src.db.session import get_db
from src.queue import JobQueue, get_job_queue
from src.repositories import JobRepository, ReportRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _mark_enqueue_failed(db: AsyncSession, job_id: uuid.UUID, execution_version: int) -> None:
    repo = JobRepository(db)
    job = await repo.get_for_update(job_id)
    if job and job.execution_version == execution_version and job.status == "pending":
        job.status = "failed"
        job.error_code = "WORKER_FAILED"
        job.error_message = ERROR_MESSAGES["WORKER_FAILED"]
        db.add(JobEvent(job_id=job.id, event_type="failed", message=job.error_message, progress=job.progress, level="error"))
        await db.commit()
        return
    await db.rollback()


async def _enqueue_committed_job(db: AsyncSession, queue: JobQueue, job_id: uuid.UUID, execution_version: int) -> AnalysisJob | None:
    try:
        arq_job_id = await queue.enqueue(str(job_id), execution_version)
    except Exception:
        await _mark_enqueue_failed(db, job_id, execution_version)
        raise

    repo = JobRepository(db)
    job = await repo.get_for_update(job_id)
    if job and job.execution_version == execution_version:
        job.arq_job_id = arq_job_id
        await db.commit()
        return job
    await db.rollback()
    return job


async def require_job(job_id: uuid.UUID, user: User, db: AsyncSession):
    job = await JobRepository(db).get_owned(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    return job


@router.post("", response_model=JobRead, status_code=202)
async def create_job(payload: JobCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), queue: JobQueue = Depends(get_job_queue)):
    if payload.analysis_mode == "deep":
        from src.tools.capabilities import get_tool_capabilities
        if not get_tool_capabilities()["get_transcript"].enabled:
            raise AppError(409, "ASR_UNAVAILABLE", ERROR_MESSAGES["ASR_UNAVAILABLE"])
    repo = JobRepository(db)
    existing = await repo.get_by_idempotency(user.id, payload.idempotency_key)
    if existing:
        return existing
    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = await ReportRepository(db).usage_summary(user.id, since)
    if usage["jobs_used"] >= USER_MONTHLY_JOB_LIMIT:
        raise AppError(429, "USAGE_LIMIT_REACHED", "本月公开测试用量已用完。")
    job = await repo.create(user_id=user.id, query=payload.query, platforms=payload.platforms, analysis_mode=payload.analysis_mode, idempotency_key=payload.idempotency_key)
    await repo.add_event(job.id, "queued", "任务已创建，等待后台 Worker。", 0)
    try:
        job.arq_job_id = await queue.enqueue(str(job.id), job.execution_version)
        await repo.save(job)
    except Exception as exc:
        job.status, job.error_code, job.error_message = "failed", "WORKER_FAILED", "任务队列暂时不可用，请稍后重试。"
        await repo.save(job)
        await repo.add_event(job.id, "failed", job.error_message, 0, "error")
        raise AppError(503, "WORKER_FAILED", job.error_message) from exc
    return job


@router.get("", response_model=dict)
async def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), status: str | None = None, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    items, total = await JobRepository(db).list_owned(user.id, limit, offset, status)
    return {"items": [JobRead.model_validate(item) for item in items], "total": total}


@router.get("/{job_id}", response_model=JobRead)
async def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await require_job(job_id, user, db)


@router.get("/{job_id}/events", response_model=dict)
async def get_events(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_job(job_id, user, db)
    events = await JobRepository(db).events(job_id)
    return {"items": [JobEventRead.model_validate(event) for event in events]}


@router.get("/{job_id}/clarification", response_model=dict)
async def get_clarification(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_job(job_id, user, db)
    items = await JobRepository(db).clarifications(job_id)
    current = next((item for item in reversed(items) if item.status == "pending"), None)
    return {
        "job_id": job_id,
        "max_rounds": 2,
        "current": ClarificationRead.model_validate(current) if current else None,
        "history": [ClarificationRead.model_validate(item) for item in items],
    }


@router.post("/{job_id}/clarification", response_model=JobRead, status_code=202)
async def answer_clarification(
    job_id: uuid.UUID,
    payload: ClarificationAnswer,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    queue: JobQueue = Depends(get_job_queue),
):
    repo = JobRepository(db)
    job = await repo.get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    request = await repo.clarification_by_request_for_update(job_id, payload.request_id)
    if request and request.status == "answered":
        if request.selected_option_id == payload.selected_option_id and request.custom_answer == payload.custom_answer:
            return job
        raise AppError(409, "CLARIFICATION_CONFLICT", ERROR_MESSAGES["CLARIFICATION_CONFLICT"])
    if job.status != "waiting_user" or not request or request.status != "pending":
        raise AppError(409, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])
    if payload.selected_option_id:
        option_ids = {str(item.get("id", "")) for item in request.options if isinstance(item, dict)}
        if payload.selected_option_id not in option_ids:
            raise AppError(422, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])
    if payload.custom_answer and not request.allow_custom:
        raise AppError(422, "CLARIFICATION_INVALID", ERROR_MESSAGES["CLARIFICATION_INVALID"])

    request.status = "answered"
    request.selected_option_id = payload.selected_option_id
    request.custom_answer = payload.custom_answer
    request.answered_at = datetime.now(timezone.utc)
    job.status = "pending"
    job.progress = max(job.progress, 5)
    job.error_code = None
    job.error_message = None
    job.execution_version += 1
    job.arq_job_id = None
    execution_version = job.execution_version
    db.add(JobEvent(job_id=job.id, event_type="clarification_answered", message="已收到研究范围补充，任务将重新判断范围。", progress=job.progress, level="info"))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or job


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    if job.status not in {"pending", "running", "waiting_user"}:
        return job
    job.status, job.cancelled_at, job.error_code, job.error_message = "cancelled", datetime.now(timezone.utc), "JOB_CANCELLED", ERROR_MESSAGES["JOB_CANCELLED"]
    await JobRepository(db).save(job)
    await JobRepository(db).add_event(job.id, "cancelled", "用户已取消任务。", job.progress, "warning")
    return job


@router.post("/{job_id}/retry", response_model=JobRead, status_code=202)
async def retry_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), queue: JobQueue = Depends(get_job_queue)):
    repo = JobRepository(db)
    job = await repo.get_owned_for_update(job_id, user.id)
    if not job:
        raise AppError(404, "JOB_NOT_FOUND", ERROR_MESSAGES["JOB_NOT_FOUND"])
    if job.status not in {"failed", "cancelled", "partial"}:
        raise AppError(409, "JOB_NOT_RETRYABLE", ERROR_MESSAGES["JOB_NOT_RETRYABLE"])
    if await repo.pending_clarification(job.id):
        raise AppError(409, "JOB_NOT_RETRYABLE", ERROR_MESSAGES["JOB_NOT_RETRYABLE"])
    await repo.clear_outputs(job.id)
    set_committed_value(job, "reports", [])
    job.retry_count += 1
    job.execution_version += 1
    job.status, job.progress, job.error_code, job.error_message, job.cancelled_at = "pending", 0, None, None, None
    job.arq_job_id = None
    execution_version = job.execution_version
    db.add(JobEvent(job_id=job.id, event_type="queued", message=f"任务已重新入队（第 {job.retry_count} 次重试）。", progress=0, level="info"))
    await db.commit()
    try:
        scheduled_job = await _enqueue_committed_job(db, queue, job.id, execution_version)
    except Exception as exc:
        raise AppError(503, "WORKER_FAILED", ERROR_MESSAGES["WORKER_FAILED"]) from exc
    return scheduled_job or job


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    if job.status in {"pending", "running"}:
        raise AppError(409, "JOB_RUNNING", "运行中的任务请先取消。")
    await JobRepository(db).delete_owned(job)
