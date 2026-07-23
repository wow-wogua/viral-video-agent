from datetime import datetime, timedelta, timezone

from src.config import DISPATCH_RECONCILE_BATCH_SIZE, DISPATCH_RECONCILE_MIN_AGE_SECONDS
from src.db.models import JobEvent
from src.db.session import async_session_factory
from src.queue import JobQueue
from src.repositories import JobRepository


DISPATCH_PENDING_MESSAGE = "任务派发暂时未恢复。系统会稍后自动重试；如需立即处理，可先取消任务。"


async def reconcile_pending_dispatches(
    _ctx: dict | None = None,
    *,
    queue: JobQueue | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Lease and re-dispatch old pending jobs without changing their execution identity."""
    queue = queue or JobQueue((_ctx or {}).get("redis"))
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=DISPATCH_RECONCILE_MIN_AGE_SECONDS)

    async with async_session_factory() as db:
        repo = JobRepository(db)
        jobs = await repo.lease_pending_dispatches(cutoff, now, DISPATCH_RECONCILE_BATCH_SIZE)
        leased = [(job.id, job.execution_version) for job in jobs]
        for job in jobs:
            db.add(JobEvent(
                job_id=job.id,
                event_type="dispatch_recovery_started",
                message="检测到未确认的队列派发，开始按原执行版本恢复。",
                progress=job.progress,
                level="warning",
            ))
        await db.commit()

    recovered = 0
    failed = 0
    for job_id, execution_version in leased:
        try:
            arq_job_id = await queue.enqueue(str(job_id), execution_version)
        except Exception:
            failed += 1
            async with async_session_factory() as db:
                job = await JobRepository(db).get_for_update(job_id)
                if job and job.status == "pending" and job.execution_version == execution_version and job.arq_job_id is None:
                    job.dispatch_pending_at = now
                    job.error_code = "DISPATCH_PENDING"
                    job.error_message = DISPATCH_PENDING_MESSAGE
                    db.add(JobEvent(
                        job_id=job.id,
                        event_type="dispatch_recovery_failed",
                        message=DISPATCH_PENDING_MESSAGE,
                        progress=job.progress,
                        level="error",
                    ))
                    await db.commit()
                else:
                    await db.rollback()
            continue

        async with async_session_factory() as db:
            job = await JobRepository(db).get_for_update(job_id)
            if job and job.status == "pending" and job.execution_version == execution_version and job.arq_job_id is None:
                job.arq_job_id = arq_job_id
                job.dispatch_pending_at = None
                if job.error_code == "DISPATCH_PENDING":
                    job.error_code = None
                    job.error_message = None
                db.add(JobEvent(
                    job_id=job.id,
                    event_type="dispatch_recovered",
                    message="任务已按原执行版本恢复派发。",
                    progress=job.progress,
                    level="info",
                ))
                await db.commit()
                recovered += 1
            else:
                await db.rollback()

    return {"leased": len(leased), "recovered": recovered, "failed": failed}
