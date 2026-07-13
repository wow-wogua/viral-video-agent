import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_job_user_idempotency"),
        Index("ix_jobs_user_created", "user_id", "created_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    platforms: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["bilibili"])
    analysis_mode: Mapped[str] = mapped_column(String(20), default="standard")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    arq_job_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reports: Mapped[list["Report"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def report_id(self) -> uuid.UUID | None:
        return self.reports[-1].id if self.reports else None


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    structured_claims: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    model_info: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    job: Mapped[AnalysisJob] = relationship(back_populates="reports")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="report")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (UniqueConstraint("job_id", "evidence_id", name="uq_evidence_job_id"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evidence_id: Mapped[str] = mapped_column(String(40), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), nullable=True, index=True)
    tool: Mapped[str] = mapped_column(String(80))
    source_type: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(String(32), default="bilibili")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    transcript_segment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job: Mapped[AnalysisJob] = relationship(back_populates="evidence_items")
    report: Mapped[Report | None] = relationship(back_populates="evidence_items")


class ReportFeedback(Base):
    __tablename__ = "report_feedback"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    useful: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(100), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    adopted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), unique=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0)
    asr_seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ShareLink(Base):
    __tablename__ = "share_links"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    progress: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(20), default="info")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
