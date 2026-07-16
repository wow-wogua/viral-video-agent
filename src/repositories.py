import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import AnalysisJob, EvidenceItem, JobEvent, Report, ReportFeedback, ShareLink, UsageRecord, User


class UserRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: return await self.db.get(User, user_id)
    async def get_by_email(self, email: str) -> User | None: return await self.db.scalar(select(User).where(User.email == email.lower()))
    async def create(self, email: str, hashed_password: str) -> User:
        user = User(email=email.lower(), hashed_password=hashed_password); self.db.add(user); await self.db.commit(); await self.db.refresh(user); return user


class JobRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_owned(self, job_id: uuid.UUID, user_id: uuid.UUID) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports)).where(AnalysisJob.id == job_id, AnalysisJob.user_id == user_id))
    async def get(self, job_id: uuid.UUID) -> AnalysisJob | None: return await self.db.get(AnalysisJob, job_id)
    async def get_by_idempotency(self, user_id: uuid.UUID, key: str) -> AnalysisJob | None:
        return await self.db.scalar(select(AnalysisJob).options(selectinload(AnalysisJob.reports)).where(AnalysisJob.user_id == user_id, AnalysisJob.idempotency_key == key))
    async def create(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        platforms: list[str],
        analysis_mode: str,
        idempotency_key: str,
        task_mode: str = "legacy",
        keyword: str | None = None,
        sort_mode: str = "relevance",
        time_range: str = "all",
        partition: str | None = None,
        max_pages: int = 1,
        request_filters: dict | None = None,
    ) -> AnalysisJob:
        job = AnalysisJob(
            user_id=user_id,
            query=query,
            platforms=platforms,
            analysis_mode=analysis_mode,
            idempotency_key=idempotency_key,
            task_mode=task_mode,
            keyword=keyword,
            sort_mode=sort_mode,
            time_range=time_range,
            partition=partition,
            max_pages=max_pages,
            request_filters=request_filters or {},
        )
        job.reports = []
        self.db.add(job)
        await self.db.commit()
        return job
    async def list_owned(self, user_id: uuid.UUID, limit: int, offset: int, status: str | None = None) -> tuple[list[AnalysisJob], int]:
        filters = [AnalysisJob.user_id == user_id];
        if status: filters.append(AnalysisJob.status == status)
        rows = list((await self.db.scalars(select(AnalysisJob).options(selectinload(AnalysisJob.reports)).where(*filters).order_by(AnalysisJob.created_at.desc()).limit(limit).offset(offset))).all())
        total = await self.db.scalar(select(func.count()).select_from(AnalysisJob).where(*filters)) or 0
        return rows, total
    async def save(self, job: AnalysisJob) -> AnalysisJob: await self.db.commit(); return job
    async def delete_owned(self, job: AnalysisJob) -> None: await self.db.delete(job); await self.db.commit()
    async def clear_outputs(self, job_id: uuid.UUID) -> None:
        await self.db.execute(delete(EvidenceItem).where(EvidenceItem.job_id == job_id))
        await self.db.execute(delete(UsageRecord).where(UsageRecord.job_id == job_id))
        await self.db.execute(delete(Report).where(Report.job_id == job_id))
        await self.db.commit()
    async def add_event(self, job_id: uuid.UUID, event_type: str, message: str, progress: int, level: str = "info") -> JobEvent:
        event = JobEvent(job_id=job_id, event_type=event_type, message=message, progress=progress, level=level); self.db.add(event); await self.db.commit(); return event
    async def events(self, job_id: uuid.UUID) -> list[JobEvent]: return list((await self.db.scalars(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.created_at))).all())


class ReportRepository:
    def __init__(self, db: AsyncSession): self.db = db
    async def get_owned(self, report_id: uuid.UUID, user_id: uuid.UUID) -> Report | None:
        return await self.db.scalar(select(Report).options(selectinload(Report.evidence_items)).where(Report.id == report_id, Report.user_id == user_id))
    async def get_public(self, report_id: uuid.UUID) -> Report | None:
        return await self.db.scalar(select(Report).options(selectinload(Report.evidence_items)).where(Report.id == report_id))
    async def usage_for_job(self, job_id: uuid.UUID) -> UsageRecord | None: return await self.db.scalar(select(UsageRecord).where(UsageRecord.job_id == job_id))
    async def add_feedback(self, **values) -> None: self.db.add(ReportFeedback(**values)); await self.db.commit()
    async def add_share(self, **values) -> ShareLink: link = ShareLink(**values); self.db.add(link); await self.db.commit(); await self.db.refresh(link); return link
    async def get_share(self, token_hash: str) -> ShareLink | None: return await self.db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash))
    async def get_share_owned(self, share_id: uuid.UUID, report_id: uuid.UUID, user_id: uuid.UUID) -> ShareLink | None:
        return await self.db.scalar(select(ShareLink).where(ShareLink.id == share_id, ShareLink.report_id == report_id, ShareLink.user_id == user_id))
    async def usage_summary(self, user_id: uuid.UUID, since: datetime) -> dict:
        row = (await self.db.execute(select(func.count(UsageRecord.id), func.coalesce(func.sum(UsageRecord.input_tokens), 0), func.coalesce(func.sum(UsageRecord.output_tokens), 0), func.coalesce(func.sum(UsageRecord.estimated_cost), 0.0), func.coalesce(func.sum(UsageRecord.asr_seconds), 0.0)).where(UsageRecord.user_id == user_id, UsageRecord.created_at >= since))).one()
        return {"jobs_used": row[0], "input_tokens": row[1], "output_tokens": row[2], "estimated_cost": row[3], "asr_seconds": row[4]}
