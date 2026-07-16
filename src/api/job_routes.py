import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from src.api.errors import AppError, ERROR_MESSAGES
from src.api.schemas import JobCreate, JobEventRead, JobRead
from src.auth.dependencies import get_current_user
from src.config import USER_MONTHLY_JOB_LIMIT
from src.db.models import User
from src.db.session import get_db
from src.intelligence.contracts import SearchRequest
from src.intelligence.providers import ImportSearchProvider, validate_local_filters
from src.intelligence.snapshots import get_search_snapshot
from src.queue import JobQueue, get_job_queue
from src.repositories import JobRepository, ReportRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
    try:
        validate_local_filters(payload.filters)
    except ValueError as exc:
        raise AppError(422, "SEARCH_FILTER_INVALID", str(exc)) from exc
    provider_config: dict = {"kind": payload.search_provider}
    if payload.search_provider == "import":
        try:
            import_provider = (
                ImportSearchProvider.from_json(payload.import_data)
                if payload.import_format == "json"
                else ImportSearchProvider.from_csv(payload.import_data)
            )
            request = SearchRequest(
                keyword=payload.keyword,
                sort_mode=payload.sort_mode,
                time_range=payload.time_range,
                partition=payload.partition,
                max_pages=payload.max_pages,
                analysis_mode=payload.analysis_mode,
                filters=payload.filters,
                idempotency_key=payload.idempotency_key,
            )
            mismatch = import_provider.request_mismatch(request)
            if mismatch:
                raise ValueError(mismatch)
        except (ValueError, TypeError) as exc:
            if isinstance(exc, ValidationError) and exc.errors():
                error = exc.errors()[0]
                location = ".".join(str(item) for item in error.get("loc", ()))
                detail = f"{location}: {error.get('msg', 'invalid value')}" if location else error.get("msg", "invalid value")
            else:
                detail = str(exc)[:240]
            raise AppError(422, "IMPORT_VALIDATION_FAILED", f"导入快照校验失败：{detail}") from exc
        provider_config.update({"format": payload.import_format, "data": payload.import_data})
    job = await repo.create(
        user_id=user.id,
        query=payload.query,
        platforms=payload.platforms,
        analysis_mode=payload.analysis_mode,
        idempotency_key=payload.idempotency_key,
        task_mode=payload.task_mode,
        keyword=payload.keyword,
        sort_mode=payload.sort_mode,
        time_range=payload.time_range,
        partition=payload.partition,
        max_pages=payload.max_pages,
        request_filters={"filters": payload.filters, "provider": provider_config},
    )
    await repo.add_event(job.id, "queued", "任务已创建，等待后台 Worker。", 0)
    try:
        job.arq_job_id = await queue.enqueue(str(job.id))
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


@router.get("/{job_id}/search-snapshot", response_model=dict)
async def get_job_search_snapshot(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    snapshot = await get_search_snapshot(db, job_id)
    if snapshot is None:
        raise AppError(404, "SEARCH_SNAPSHOT_NOT_FOUND", "该任务尚无可查询的搜索快照。")
    snapshot["attempt_state"] = (
        "previous_attempt"
        if job.retry_count > 0 and job.status in {"pending", "running"}
        else "current"
    )
    return snapshot


@router.post("/{job_id}/cancel", response_model=JobRead)
async def cancel_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    if job.status not in {"pending", "running"}:
        return job
    job.status, job.cancelled_at, job.error_code, job.error_message = "cancelled", datetime.now(timezone.utc), "JOB_CANCELLED", ERROR_MESSAGES["JOB_CANCELLED"]
    await JobRepository(db).save(job)
    await JobRepository(db).add_event(job.id, "cancelled", "用户已取消任务。", job.progress, "warning")
    return job


@router.post("/{job_id}/retry", response_model=JobRead, status_code=202)
async def retry_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), queue: JobQueue = Depends(get_job_queue)):
    job = await require_job(job_id, user, db)
    if job.status not in {"failed", "cancelled", "partial"}:
        raise AppError(409, "JOB_NOT_RETRYABLE", "当前任务状态不能重试。")
    await JobRepository(db).clear_outputs(job.id)
    set_committed_value(job, "reports", [])
    job.retry_count += 1
    job.status, job.progress, job.error_code, job.error_message, job.cancelled_at = "pending", 0, None, None, None
    job.arq_job_id = await queue.enqueue(str(job.id), job.retry_count)
    await JobRepository(db).save(job)
    await JobRepository(db).add_event(job.id, "queued", f"任务已重新入队（第 {job.retry_count} 次重试）。", 0)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await require_job(job_id, user, db)
    if job.status in {"pending", "running"}:
        raise AppError(409, "JOB_RUNNING", "运行中的任务请先取消。")
    await JobRepository(db).delete_owned(job)
