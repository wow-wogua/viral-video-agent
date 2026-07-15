import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), index=True)
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
    task_mode: Mapped[str] = mapped_column(String(32), default="legacy")
    keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_mode: Mapped[str] = mapped_column(String(32), default="relevance")
    time_range: Mapped[str] = mapped_column(String(32), default="all")
    partition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    max_pages: Mapped[int] = mapped_column(Integer, default=1)
    asr_options: Mapped[dict] = mapped_column(JSON, default=dict)
    request_filters: Mapped[dict] = mapped_column(JSON, default=dict)
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
    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    structured_claims: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    model_info: Mapped[dict] = mapped_column(JSON, default=dict)
    intelligence_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
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
    crawl_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crawl_runs.id", ondelete="SET NULL"), nullable=True, index=True)
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
    __table_args__ = (UniqueConstraint("token_hash"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reports.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
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


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    __table_args__ = (
        UniqueConstraint("job_id"),
        Index("ix_crawl_runs_keyword_started", "keyword", "started_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    schema_version: Mapped[str] = mapped_column(String(40))
    keyword: Mapped[str] = mapped_column(Text)
    requested_pages: Mapped[int] = mapped_column(Integer)
    successful_pages: Mapped[int] = mapped_column(Integer, default=0)
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    deduplicated_video_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_creator_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_name: Mapped[str] = mapped_column(String(80))
    provider_version: Mapped[str] = mapped_column(String(40))
    sort_mode: Mapped[str] = mapped_column(String(32), default="relevance")
    time_range: Mapped[str] = mapped_column(String(32), default="all")
    partition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    partial_success: Mapped[bool] = mapped_column(Boolean, default=False)
    truncation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SearchPageRecord(Base):
    __tablename__ = "search_pages"
    __table_args__ = (UniqueConstraint("crawl_run_id", "page_number", name="uq_search_page_run_number"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_duration_ms: Mapped[int] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    normalized_result_count: Mapped[int] = mapped_column(Integer, default=0)
    provider_name: Mapped[str] = mapped_column(String(80))
    provider_version: Mapped[str] = mapped_column(String(40))
    native_filters: Mapped[dict] = mapped_column(JSON, default=dict)
    local_filters: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class CreatorRecord(Base):
    __tablename__ = "creators"
    mid: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    follower_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_name: Mapped[str] = mapped_column(String(80))
    provider_version: Mapped[str] = mapped_column(String(40))
    recent_sample_availability: Mapped[str] = mapped_column(String(20), default="missing")
    recent_sample_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class VideoRecord(Base):
    __tablename__ = "videos"
    bvid: Mapped[str] = mapped_column(String(12), primary_key=True)
    aid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creator_mid: Mapped[str | None] = mapped_column(ForeignKey("creators.mid", ondelete="SET NULL"), nullable=True, index=True)
    creator_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    partition: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    view: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    favorite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reply: Mapped[int | None] = mapped_column(Integer, nullable=True)
    share: Mapped[int | None] = mapped_column(Integer, nullable=True)
    danmaku: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider_name: Mapped[str] = mapped_column(String(80))
    provider_version: Mapped[str] = mapped_column(String(40))
    missing_fields: Mapped[list[str]] = mapped_column(JSON, default=list)


class CrawlRunVideo(Base):
    __tablename__ = "crawl_run_videos"
    __table_args__ = (UniqueConstraint("crawl_run_id", "bvid", name="uq_crawl_run_video"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    bvid: Mapped[str] = mapped_column(ForeignKey("videos.bvid", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    result_rank: Mapped[int] = mapped_column(Integer)
    relevance_label: Mapped[str] = mapped_column(String(20), default="uncertain")
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CompetitorScoreRecord(Base):
    __tablename__ = "competitor_scores"
    __table_args__ = (UniqueConstraint("crawl_run_id", "creator_mid", "scoring_version", name="uq_competitor_score_version"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    creator_mid: Mapped[str] = mapped_column(ForeignKey("creators.mid", ondelete="CASCADE"), index=True)
    scoring_version: Mapped[str] = mapped_column(String(40))
    component_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    penalty_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    total_score: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    metric_results: Mapped[list[dict]] = mapped_column(JSON, default=list)


class RepresentativeVideoSelectionRecord(Base):
    __tablename__ = "representative_video_selections"
    __table_args__ = (UniqueConstraint("crawl_run_id", "creator_mid", "bvid", name="uq_representative_video"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crawl_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crawl_runs.id", ondelete="CASCADE"), index=True)
    creator_mid: Mapped[str] = mapped_column(ForeignKey("creators.mid", ondelete="CASCADE"), index=True)
    bvid: Mapped[str] = mapped_column(ForeignKey("videos.bvid", ondelete="CASCADE"), index=True)
    selection_type: Mapped[str] = mapped_column(String(32))
    selection_rank: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
