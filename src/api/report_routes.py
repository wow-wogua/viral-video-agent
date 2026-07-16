import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.errors import AppError
from src.api.schemas import FeedbackCreate, ReportRead, ShareCreate
from src.auth.dependencies import get_current_user
from src.config import USER_MONTHLY_JOB_LIMIT
from src.db.models import Report, User
from src.db.session import get_db
from src.repositories import ReportRepository
from src.intelligence.providers import provider_capability_catalog
from src.tools.capabilities import capability_snapshot

router = APIRouter(tags=["reports"])


@router.get("/capabilities", response_model=dict)
async def capabilities():
    return {
        "items": capability_snapshot(),
        "platforms": ["bilibili"],
        "search_providers": provider_capability_catalog(),
    }


def serialize_report(report: Report, usage=None, public: bool = False) -> ReportRead:
    return ReportRead(
        id=report.id, job_id=report.job_id, title=report.title, content=report.content,
        structured_claims=report.structured_claims, status=report.status,
        model_info={} if public else report.model_info,
        evidence=report.evidence_items, usage=None if public else usage,
        created_at=report.created_at, updated_at=report.updated_at,
    )


async def require_report(report_id: uuid.UUID, user: User, db: AsyncSession) -> Report:
    report = await ReportRepository(db).get_owned(report_id, user.id)
    if not report:
        raise AppError(404, "REPORT_NOT_FOUND", "未找到该报告。")
    return report


@router.get("/reports/{report_id}", response_model=ReportRead)
async def get_report(report_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    report = await require_report(report_id, user, db)
    usage = await ReportRepository(db).usage_for_job(report.job_id)
    return serialize_report(report, usage)


@router.post("/reports/{report_id}/feedback", status_code=204)
async def create_feedback(report_id: uuid.UUID, payload: FeedbackCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_report(report_id, user, db)
    await ReportRepository(db).add_feedback(report_id=report_id, user_id=user.id, **payload.model_dump())


@router.post("/reports/{report_id}/shares", response_model=dict, status_code=201)
async def create_share(report_id: uuid.UUID, payload: ShareCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_report(report_id, user, db)
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
    link = await ReportRepository(db).add_share(report_id=report_id, user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=expires_at)
    return {"id": link.id, "token": token, "expires_at": expires_at}


@router.delete("/reports/{report_id}/shares/{share_id}", status_code=204)
async def revoke_share(report_id: uuid.UUID, share_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await require_report(report_id, user, db)
    link = await ReportRepository(db).get_share_owned(share_id, report_id, user.id)
    if not link:
        raise AppError(404, "SHARE_NOT_FOUND", "未找到该分享链接。")
    link.revoked_at = datetime.now(timezone.utc)
    await db.commit()


@router.get("/shares/{token}", response_model=ReportRead)
async def get_shared_report(token: str, db: AsyncSession = Depends(get_db)):
    link = await ReportRepository(db).get_share(hashlib.sha256(token.encode()).hexdigest())
    now = datetime.now(timezone.utc)
    expires_at = link.expires_at.replace(tzinfo=timezone.utc) if link and link.expires_at.tzinfo is None else (link.expires_at if link else now)
    if not link or link.revoked_at or expires_at <= now:
        raise AppError(404, "SHARE_NOT_FOUND", "分享链接不存在、已过期或已撤销。")
    report = await ReportRepository(db).get_public(link.report_id)
    if not report:
        raise AppError(404, "SHARE_NOT_FOUND", "分享报告不存在。")
    return serialize_report(report, public=True)


@router.get("/usage", response_model=dict)
async def get_usage(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    since = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    usage = await ReportRepository(db).usage_summary(user.id, since)
    return {**usage, "jobs_limit": USER_MONTHLY_JOB_LIMIT}
