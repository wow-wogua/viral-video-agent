"""Versioned P0 contracts for the Bilibili content-intelligence workflow."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CONTENT_INTELLIGENCE_SCHEMA_VERSION = "content-intelligence.p0.1"
SCORING_VERSION = "competitor-score.p0.1"
METRIC_FORMULA_VERSION = "content-metrics.p0.1"
CREATOR_QUALIFICATION_POLICY_VERSION = "creator-qualification.p0.1"
TOPIC_SPEC_VERSION = "topic-spec.p0.1"
CREATOR_TOPIC_ASSESSMENT_VERSION = "creator-topic-assessment.p0.1"
SYSTEM_CONFIDENCE_VERSION = "system-confidence.p0.1"
REVIEW_ROUTING_VERSION = "review-routing.p0.1"
CREATOR_SELECTION_VERSION_V2 = "competitor-selection.p0.2"
MAX_SEARCH_PAGES = 5
MAX_COMPETITORS = 5
REPRESENTATIVE_VIDEO_TARGET = 6


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SortMode(StrEnum):
    RELEVANCE = "relevance"
    NEWEST = "newest"
    MOST_VIEWED = "most_viewed"


class TimeRange(StrEnum):
    ALL = "all"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class AnalysisMode(StrEnum):
    STANDARD = "standard"
    DEEP = "deep"


class PageStatus(StrEnum):
    SUCCESS = "success"
    EMPTY = "empty"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CrawlStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RelevanceLabel(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class SampleAvailability(StrEnum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    MISSING = "missing"


class CreatorSampleStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    MISSING = "missing"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class CreatorQualificationStatus(StrEnum):
    DISCOVERY_ONLY = "discovery_only"
    EMERGING_CANDIDATE = "emerging_candidate"
    QUALIFIED_REFERENCE = "qualified_reference"
    EXCLUDED = "excluded"


class AccountTopicRelevance(StrEnum):
    RELEVANT = "relevant"
    IRRELEVANT = "irrelevant"
    UNCERTAIN = "uncertain"


class SpecializationLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class CreatorTopicRole(StrEnum):
    SPECIALIST = "specialist"
    GENERALIST = "generalist"
    OFFICIAL = "official"
    MEDIA = "media"
    EDUCATOR = "educator"
    REVIEWER = "reviewer"
    SERVICE = "service"
    AGGREGATOR = "aggregator"
    UNRELATED = "unrelated"
    UNKNOWN = "unknown"


class CreatorProductRelation(StrEnum):
    CORE_COMPETITOR = "core_competitor"
    ADJACENT_BENCHMARK = "adjacent_benchmark"
    OCCASIONAL_HIT = "occasional_hit"
    EXCLUDED = "excluded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class BoundaryRisk(StrEnum):
    SINGLE_VIDEO_BIAS = "single_video_bias"
    SEARCH_ONLY_RELEVANCE = "search_only_relevance"
    OCCASIONAL_HIT = "occasional_hit"
    MIXED_CONTENT = "mixed_content"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    INSUFFICIENT_90D_CONTINUITY = "insufficient_90d_continuity"
    LOW_RELEVANT_RATIO = "low_relevant_ratio"
    PROFILE_CONTENT_CONFLICT = "profile_content_conflict"
    AGGREGATION_OR_REUPLOAD = "aggregation_or_reupload"
    MISSING_EVIDENCE = "missing_evidence"
    SEMANTIC_RULE_CONFLICT = "semantic_rule_conflict"


class MetricName(StrEnum):
    INTERACTION_RATE = "interaction_rate"
    FAVORITE_RATE = "favorite_rate"
    COIN_RATE = "coin_rate"
    REPLY_RATE = "reply_rate"
    POSTING_FREQUENCY = "posting_frequency"
    VIEW_MEDIAN = "view_median"
    INTERACTION_MEDIAN = "interaction_median"
    VIRAL_RATE = "viral_rate"
    RELEVANT_CONTENT_RATIO = "relevant_content_ratio"
    SAMPLE_COVERAGE = "sample_coverage"
    SEARCH_VISIBILITY = "search_visibility"
    SAMPLE_SHARE = "sample_share"


class ASROptions(StrictModel):
    enabled: bool = False
    max_videos_per_competitor: int = Field(default=1, ge=1, le=3)
    task_max_videos: int = Field(default=5, ge=1, le=15)


class SearchRequest(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    keyword: str = Field(min_length=1, max_length=200)
    sort_mode: SortMode = SortMode.RELEVANCE
    time_range: TimeRange = TimeRange.ALL
    partition: str | None = Field(default=None, max_length=80)
    max_pages: int = Field(default=5, ge=1, le=MAX_SEARCH_PAGES)
    analysis_mode: AnalysisMode = AnalysisMode.STANDARD
    asr: ASROptions = Field(default_factory=ASROptions)
    filters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=128)


class ProviderCapabilities(StrictModel):
    provider_name: str
    provider_version: str
    provider_kind: Literal["development", "import", "fixture", "production"]
    supports_search: bool
    supports_creator_samples: bool
    supports_native_sort: list[SortMode] = Field(default_factory=list)
    supports_native_time_range: list[TimeRange] = Field(default_factory=list)
    supports_native_partition: bool = False
    requires_login: bool = False
    commercial_authorization: Literal["unknown", "development_only", "authorized"] = "unknown"


class SearchPage(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    page_number: int = Field(ge=1, le=MAX_SEARCH_PAGES)
    status: PageStatus
    requested_at: datetime
    completed_at: datetime
    request_duration_ms: int = Field(ge=0)
    source_url: str | None = None
    raw_result_count: int = Field(ge=0)
    normalized_result_count: int = Field(ge=0)
    provider_name: str
    provider_version: str
    native_filters: dict[str, Any] = Field(default_factory=dict)
    local_filters: dict[str, Any] = Field(default_factory=dict)
    raw_payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    error_code: str | None = None
    error_summary: str | None = None

    @property
    def completed_successfully(self) -> bool:
        return self.status in {PageStatus.SUCCESS, PageStatus.EMPTY}

    @model_validator(mode="after")
    def validate_page_outcome(self) -> "SearchPage":
        if self.completed_at < self.requested_at:
            raise ValueError("completed_at cannot be before requested_at")
        if self.normalized_result_count > self.raw_result_count:
            raise ValueError("normalized_result_count cannot exceed raw_result_count")
        if self.status == PageStatus.SUCCESS and self.normalized_result_count == 0:
            raise ValueError("success pages require at least one normalized result")
        if self.status == PageStatus.EMPTY and self.normalized_result_count != 0:
            raise ValueError("empty pages cannot contain normalized results")
        if self.status in {PageStatus.FAILED, PageStatus.TIMEOUT, PageStatus.CANCELLED}:
            if self.normalized_result_count != 0:
                raise ValueError("unsuccessful pages cannot contain normalized results")
        return self


class Video(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    bvid: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    aid: int | None = Field(default=None, ge=1)
    creator_mid: str | None = None
    creator_name: str | None = None
    title: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    partition: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    cover_url: str | None = None
    source_url: str
    view: int | None = Field(default=None, ge=0)
    like: int | None = Field(default=None, ge=0)
    coin: int | None = Field(default=None, ge=0)
    favorite: int | None = Field(default=None, ge=0)
    reply: int | None = Field(default=None, ge=0)
    share: int | None = Field(default=None, ge=0)
    danmaku: int | None = Field(default=None, ge=0)
    observed_at: datetime
    provider_name: str
    provider_version: str
    source_page: int = Field(ge=1, le=MAX_SEARCH_PAGES)
    source_rank: int = Field(ge=1)
    raw_payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    missing_fields: list[str] = Field(default_factory=list)


class Creator(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    mid: str
    name: str
    profile_url: str | None = None
    avatar_url: str | None = None
    follower_count: int | None = Field(default=None, ge=0)
    observed_at: datetime
    provider_name: str
    provider_version: str
    recent_sample_availability: SampleAvailability = SampleAvailability.MISSING
    recent_sample_count: int = Field(default=0, ge=0)
    missing_reason: str | None = None


class CreatorVideo(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    bvid: str = Field(pattern=r"^BV[0-9A-Za-z]{10}$")
    creator_mid: str
    creator_name: str
    title: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    partition: str | None = None
    published_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=0)
    cover_url: str | None = None
    source_url: str
    view: int | None = Field(default=None, ge=0)
    like: int | None = Field(default=None, ge=0)
    coin: int | None = Field(default=None, ge=0)
    favorite: int | None = Field(default=None, ge=0)
    reply: int | None = Field(default=None, ge=0)
    share: int | None = Field(default=None, ge=0)
    danmaku: int | None = Field(default=None, ge=0)
    observed_at: datetime
    provider_name: str
    provider_version: str
    sample_rank: int = Field(ge=1, le=20)
    raw_payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    missing_fields: list[str] = Field(default_factory=list)


class CreatorRequestAttempt(StrictModel):
    operation: Literal["wbi_nav", "uploads", "follower", "uapi_archives", "uapi_userinfo"]
    attempt_number: int = Field(ge=1, le=5)
    started_at: datetime
    completed_at: datetime
    rate_limit_wait_seconds: float = Field(default=0.0, ge=0)
    retry_backoff_seconds: float = Field(default=0.0, ge=0)
    classification: Literal[
        "success",
        "cancelled",
        "timeout",
        "connection_error",
        "authentication_missing",
        "authentication_error",
        "not_found",
        "http_429",
        "http_5xx",
        "http_error",
        "risk_control",
        "invalid_json",
        "invalid_payload",
        "provider_error",
    ]
    http_status: int | None = Field(default=None, ge=100, le=599)
    provider_code: int | None = None
    error_type: str | None = None


class CreatorRequestAudit(StrictModel):
    attempt_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    total_rate_limit_wait_seconds: float = Field(default=0.0, ge=0)
    total_backoff_seconds: float = Field(default=0.0, ge=0)
    final_classification: Literal[
        "success",
        "partial",
        "cancelled",
        "timeout",
        "connection_error",
        "authentication_missing",
        "authentication_error",
        "not_found",
        "http_429",
        "http_5xx",
        "http_error",
        "risk_control",
        "invalid_json",
        "invalid_payload",
        "provider_error",
        "circuit_open",
        "missing_mid",
    ]
    risk_control: bool = False
    consecutive_risk_control_count: int = Field(default=0, ge=0)
    circuit_state: Literal["closed", "opened", "open"] = "closed"
    circuit_opened_at: datetime | None = None
    cooldown_seconds: int = Field(default=0, ge=0)
    attempts: list[CreatorRequestAttempt] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_attempts(self) -> "CreatorRequestAudit":
        if self.attempt_count != len(self.attempts):
            raise ValueError("creator request attempt_count must match attempts")
        retries = sum(attempt.attempt_number > 1 for attempt in self.attempts)
        if self.retry_count != retries:
            raise ValueError("creator request retry_count must match attempts")
        return self


class CreatorSample(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    creator_mid: str
    creator_name: str
    profile_url: str
    status: CreatorSampleStatus
    observed_at: datetime
    provider_name: str
    provider_version: str
    provider_kind: Literal["development", "import", "fixture", "production"]
    source_provider_name: str
    source_provider_version: str
    source_url: str
    follower_count: int | None = Field(default=None, ge=0)
    uploads: list[CreatorVideo] = Field(default_factory=list, max_length=20)
    recent_30d_upload_count: int = Field(default=0, ge=0, le=20)
    recent_90d_upload_count: int = Field(default=0, ge=0, le=20)
    missing_reason: str | None = None
    raw_payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    request_audit: CreatorRequestAudit | None = None

    @model_validator(mode="after")
    def validate_sample(self) -> "CreatorSample":
        if any(video.creator_mid != self.creator_mid for video in self.uploads):
            raise ValueError("creator sample videos must match creator_mid")
        ranks = [video.sample_rank for video in self.uploads]
        if len(ranks) != len(set(ranks)):
            raise ValueError("creator sample ranks must be unique")
        if self.recent_30d_upload_count > self.recent_90d_upload_count:
            raise ValueError("recent_30d_upload_count cannot exceed recent_90d_upload_count")
        if self.recent_90d_upload_count > len(self.uploads):
            raise ValueError("recent_90d_upload_count cannot exceed the upload sample")
        if self.status == CreatorSampleStatus.SUCCESS and not self.uploads:
            raise ValueError("successful creator samples require at least one upload")
        if self.status in {
            CreatorSampleStatus.MISSING,
            CreatorSampleStatus.FAILED,
            CreatorSampleStatus.TIMEOUT,
            CreatorSampleStatus.CANCELLED,
        } and self.uploads:
            raise ValueError("unsuccessful creator samples cannot contain uploads")
        if self.status != CreatorSampleStatus.SUCCESS and not self.missing_reason:
            raise ValueError("non-success creator samples require missing_reason")
        return self


class CreatorQualificationEvidence(StrictModel):
    """Keyword-scoped account evidence; search-result relevance is not sufficient."""

    profile_url: str = Field(min_length=1)
    observed_at: datetime
    audited_upload_count: int = Field(ge=0, le=20)
    recent_90d_upload_count: int = Field(ge=0, le=20)
    relevant_video_count: int = Field(ge=0, le=20)
    irrelevant_video_count: int = Field(ge=0, le=20)
    uncertain_video_count: int = Field(ge=0, le=20)
    recent_90d_relevant_video_count: int = Field(ge=0, le=20)
    follower_count: int | None = Field(default=None, ge=0)
    relevant_view_median: float | None = Field(default=None, ge=0)
    evidence_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_sample_counts(self) -> "CreatorQualificationEvidence":
        labeled_count = self.relevant_video_count + self.irrelevant_video_count + self.uncertain_video_count
        if labeled_count != self.audited_upload_count:
            raise ValueError("qualification label counts must equal audited_upload_count")
        if self.recent_90d_upload_count > self.audited_upload_count:
            raise ValueError("recent_90d_upload_count cannot exceed audited_upload_count")
        if self.recent_90d_relevant_video_count > self.recent_90d_upload_count:
            raise ValueError("recent_90d_relevant_video_count cannot exceed recent_90d_upload_count")
        if self.recent_90d_relevant_video_count > self.relevant_video_count:
            raise ValueError("recent_90d_relevant_video_count cannot exceed relevant_video_count")
        return self

    @property
    def relevant_ratio(self) -> float | None:
        denominator = self.relevant_video_count + self.irrelevant_video_count
        if denominator == 0:
            return None
        return self.relevant_video_count / denominator


class RelevanceDecision(StrictModel):
    bvid: str
    label: RelevanceLabel
    reason: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    labeler: str
    labeler_version: str


class CreatorSemanticAssessment(StrictModel):
    generalist: bool | None = None
    risk_flags: list[
        Literal[
            "aggregator",
            "reupload",
            "course_matrix",
            "content_farm",
            "news_repost",
            "occasional_hit",
        ]
    ] = Field(default_factory=list)
    reason: str
    confidence: float = Field(ge=0, le=1)
    labeler: str
    labeler_version: str


class TopicSpec(StrictModel):
    version: Literal[TOPIC_SPEC_VERSION] = TOPIC_SPEC_VERSION
    keyword_id: str = Field(min_length=1, max_length=120)
    keyword: str = Field(min_length=1, max_length=200)
    category: Literal["broad", "vertical", "brand", "ambiguous", "low_result"]
    intent_definition: str = Field(min_length=1, max_length=2000)
    allowed_subtopics: list[str] = Field(default_factory=list, max_length=20)
    exclusion_rules: list[str] = Field(default_factory=list, max_length=20)


class CreatorTopicVideoEvidence(StrictModel):
    bvid: str
    title: str
    description: str | None = None
    published_at: datetime | None = None
    view: int | None = Field(default=None, ge=0)
    source_url: str
    evidence_ids: list[str] = Field(default_factory=list)


class CreatorTopicEvidence(StrictModel):
    creator_mid: str
    creator_name: str
    profile_url: str | None = None
    sample_status: CreatorSampleStatus
    observed_at: datetime | None = None
    search_video_count: int = Field(ge=0)
    search_relevant_video_count: int = Field(ge=0)
    search_irrelevant_video_count: int = Field(ge=0)
    search_uncertain_video_count: int = Field(ge=0)
    sampled_upload_count: int = Field(ge=0, le=20)
    decided_upload_count: int = Field(ge=0, le=20)
    relevant_upload_count: int = Field(ge=0, le=20)
    irrelevant_upload_count: int = Field(ge=0, le=20)
    uncertain_upload_count: int = Field(ge=0, le=20)
    relevant_ratio: float | None = Field(default=None, ge=0, le=1)
    recent_30d_upload_count: int = Field(ge=0, le=20)
    recent_90d_upload_count: int = Field(ge=0, le=20)
    relevant_30d_upload_count: int = Field(ge=0, le=20)
    relevant_90d_upload_count: int = Field(ge=0, le=20)
    follower_count: int | None = Field(default=None, ge=0)
    relevant_view_median: float | None = Field(default=None, ge=0)
    published_at_completeness: float = Field(ge=0, le=1)
    label_coverage: float = Field(ge=0, le=1)
    sample_coverage: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    search_examples: list[CreatorTopicVideoEvidence] = Field(default_factory=list)
    upload_examples: list[CreatorTopicVideoEvidence] = Field(default_factory=list)
    relevant_examples: list[CreatorTopicVideoEvidence] = Field(default_factory=list)
    irrelevant_examples: list[CreatorTopicVideoEvidence] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_topic_evidence_counts(self) -> "CreatorTopicEvidence":
        if (
            self.search_relevant_video_count
            + self.search_irrelevant_video_count
            + self.search_uncertain_video_count
            != self.search_video_count
        ):
            raise ValueError("search topic-evidence label counts must equal search videos")
        if self.decided_upload_count != self.relevant_upload_count + self.irrelevant_upload_count:
            raise ValueError("decided upload count must equal relevant plus irrelevant uploads")
        if (
            self.relevant_upload_count
            + self.irrelevant_upload_count
            + self.uncertain_upload_count
            != self.sampled_upload_count
        ):
            raise ValueError("topic evidence label counts must equal sampled uploads")
        if self.relevant_30d_upload_count > self.relevant_90d_upload_count:
            raise ValueError("relevant 30-day uploads cannot exceed relevant 90-day uploads")
        if self.relevant_90d_upload_count > self.relevant_upload_count:
            raise ValueError("relevant 90-day uploads cannot exceed relevant uploads")
        return self


class SystemConfidenceComponent(StrictModel):
    value: float = Field(ge=0, le=1)
    weight: float = Field(gt=0, le=1)
    reason: str = Field(min_length=1, max_length=300)


class SystemConfidence(StrictModel):
    version: Literal[SYSTEM_CONFIDENCE_VERSION] = SYSTEM_CONFIDENCE_VERSION
    score: float = Field(ge=0, le=1)
    components: dict[str, SystemConfidenceComponent]
    formula: str

    @model_validator(mode="after")
    def validate_confidence_formula(self) -> "SystemConfidence":
        total_weight = sum(component.weight for component in self.components.values())
        if abs(total_weight - 1.0) > 1e-6:
            raise ValueError("system-confidence component weights must sum to 1")
        expected = sum(component.value * component.weight for component in self.components.values())
        if abs(self.score - round(expected, 6)) > 1e-6:
            raise ValueError("system-confidence score must equal the weighted components")
        return self


class CreatorTopicAssessment(StrictModel):
    version: Literal[CREATOR_TOPIC_ASSESSMENT_VERSION] = CREATOR_TOPIC_ASSESSMENT_VERSION
    topic_spec_version: Literal[TOPIC_SPEC_VERSION] = TOPIC_SPEC_VERSION
    selection_version: Literal[CREATOR_SELECTION_VERSION_V2] = CREATOR_SELECTION_VERSION_V2
    base_scoring_version: Literal[SCORING_VERSION] = SCORING_VERSION
    keyword_id: str
    creator_mid: str
    creator_name: str
    relevance: AccountTopicRelevance
    specialization: SpecializationLevel
    role: CreatorTopicRole
    product_relation: CreatorProductRelation
    model_confidence: float = Field(ge=0, le=1)
    system_confidence: SystemConfidence
    boundary_risks: list[BoundaryRisk] = Field(default_factory=list)
    evidence: CreatorTopicEvidence
    base_score: float = Field(ge=0, le=100)
    base_tie_break_values: list[str | int | float] = Field(default_factory=list)
    selected: bool = False
    selection_rank: int | None = Field(default=None, ge=1, le=MAX_COMPETITORS)
    rationale: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_v2_selection(self) -> "CreatorTopicAssessment":
        if self.selected and self.product_relation != CreatorProductRelation.CORE_COMPETITOR:
            raise ValueError("only core_competitor accounts can be selected by v2")
        if self.selected != (self.selection_rank is not None):
            raise ValueError("v2 selected and selection_rank must be set together")
        return self


class ReviewRoutingDecision(StrictModel):
    version: Literal[REVIEW_ROUTING_VERSION] = REVIEW_ROUTING_VERSION
    review_id: str = Field(pattern=r"^review_[a-f0-9]{16}$")
    keyword_id: str
    creator_mid: str
    requires_human_review: bool
    priority: int | None = Field(default=None, ge=1, le=5)
    reasons: list[str] = Field(default_factory=list)
    include_in_blind_workbook: bool
    existing_human_label: bool = False

    @model_validator(mode="after")
    def validate_review_route(self) -> "ReviewRoutingDecision":
        if self.requires_human_review and self.priority is None:
            raise ValueError("human-review routes require a priority")
        if self.include_in_blind_workbook and not self.requires_human_review:
            raise ValueError("blind workbook entries must require human review")
        if self.existing_human_label and self.include_in_blind_workbook:
            raise ValueError("existing frozen human labels must not be reviewed again")
        return self


class HumanCreatorTopicReview(StrictModel):
    review_id: str = Field(pattern=r"^review_[a-f0-9]{16}$")
    keyword_id: str
    creator_mid: str
    human_relevance: AccountTopicRelevance | None = None
    human_specialization: SpecializationLevel | None = None
    human_role: CreatorTopicRole | None = None
    human_reason: str = Field(default="", max_length=1000)
    review_complete: bool = False

    @model_validator(mode="after")
    def validate_completed_review(self) -> "HumanCreatorTopicReview":
        if not self.review_complete:
            return self
        if self.human_relevance is None or self.human_specialization is None or self.human_role is None:
            raise ValueError("completed human reviews require relevance, specialization, and role")
        if not self.human_reason.strip():
            raise ValueError("completed human reviews require a reason")
        if (
            self.human_relevance == AccountTopicRelevance.RELEVANT
            and self.human_specialization == SpecializationLevel.UNKNOWN
        ):
            raise ValueError("relevant completed reviews require a known specialization")
        if (
            self.human_relevance == AccountTopicRelevance.IRRELEVANT
            and self.human_specialization in {SpecializationLevel.HIGH, SpecializationLevel.MEDIUM}
        ):
            raise ValueError("irrelevant accounts cannot have high or medium topic specialization")
        return self


class ScoreComponent(StrictModel):
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    numerator: float | None = None
    denominator: float | None = None
    sample_size: int = Field(ge=0)
    formula: str
    missing_reason: str | None = None

    @model_validator(mode="after")
    def validate_score_boundary(self) -> "ScoreComponent":
        if self.score > self.max_score:
            raise ValueError("component score cannot exceed max_score")
        return self


class CompetitorScore(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    scoring_version: Literal[SCORING_VERSION] = SCORING_VERSION
    creator_mid: str
    creator_name: str
    component_scores: dict[str, float]
    component_details: dict[str, ScoreComponent]
    penalty_scores: dict[str, float] = Field(default_factory=dict)
    total_score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    qualification_status: CreatorQualificationStatus
    selected: bool = False
    selection_rank: int | None = Field(default=None, ge=1, le=MAX_COMPETITORS)
    inclusion_reason: str | None = None
    exclusion_reason: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    search_candidate_sources: list[str] = Field(default_factory=list)
    creator_sample_sources: list[str] = Field(default_factory=list)
    tie_break_values: list[str | int | float] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score_shape(self) -> "CompetitorScore":
        if set(self.component_scores) != set(self.component_details):
            raise ValueError("component_scores and component_details must have identical keys")
        for name, value in self.component_scores.items():
            if abs(value - self.component_details[name].score) > 1e-9:
                raise ValueError("component score does not match component detail")
        if sum(self.penalty_scores.values()) > 20.000001:
            raise ValueError("competitor penalties cannot exceed 20")
        if self.selected and self.qualification_status != CreatorQualificationStatus.QUALIFIED_REFERENCE:
            raise ValueError("only qualified_reference creators can be selected")
        if self.selected and self.selection_rank is None:
            raise ValueError("selected competitors require selection_rank")
        if not self.selected and self.selection_rank is not None:
            raise ValueError("unselected competitors cannot have selection_rank")
        return self


class RepresentativeVideo(StrictModel):
    bvid: str
    selection_type: Literal["recent_relevant", "high_view", "high_engagement", "fill"]
    selection_rank: int = Field(ge=1, le=REPRESENTATIVE_VIDEO_TARGET)
    reason: str
    evidence_ids: list[str] = Field(default_factory=list)


class RepresentativeSelection(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    creator_mid: str
    target_count: Literal[REPRESENTATIVE_VIDEO_TARGET] = REPRESENTATIVE_VIDEO_TARGET
    selected_videos: list[RepresentativeVideo] = Field(max_length=REPRESENTATIVE_VIDEO_TARGET)
    shortfall_reason: str | None = None


class MetricResult(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    formula_version: Literal[METRIC_FORMULA_VERSION] = METRIC_FORMULA_VERSION
    metric_name: MetricName
    value: float | None
    unit: str
    numerator: float | None = None
    denominator: float | None = None
    sample_size: int = Field(ge=0)
    time_window: str
    missing_rule: str
    small_sample_warning: str | None = None
    extreme_value_rule: str
    evidence_ids: list[str] = Field(default_factory=list)


class CoverageSummary(StrictModel):
    requested_pages: int = Field(ge=1, le=MAX_SEARCH_PAGES)
    successful_pages: int = Field(ge=0, le=MAX_SEARCH_PAGES)
    raw_result_count: int = Field(ge=0)
    deduplicated_video_count: int = Field(ge=0)
    candidate_creator_count: int = Field(ge=0)
    actual_competitor_count: int = Field(ge=0, le=MAX_COMPETITORS)
    partial_success: bool
    truncation_reason: str | None = None

    @model_validator(mode="after")
    def validate_count_boundaries(self) -> "CoverageSummary":
        if self.successful_pages > self.requested_pages:
            raise ValueError("successful_pages cannot exceed requested_pages")
        if self.deduplicated_video_count > self.raw_result_count:
            raise ValueError("deduplicated_video_count cannot exceed raw_result_count")
        if self.candidate_creator_count > self.deduplicated_video_count:
            raise ValueError("candidate_creator_count cannot exceed deduplicated_video_count")
        if self.actual_competitor_count > self.candidate_creator_count:
            raise ValueError("actual_competitor_count cannot exceed candidate_creator_count")
        expected_partial = 0 < self.successful_pages < self.requested_pages
        if self.partial_success != expected_partial:
            raise ValueError("partial_success must match the successful/requested page boundary")
        return self


class CrawlRun(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    crawl_run_id: str
    request: SearchRequest
    provider: ProviderCapabilities
    started_at: datetime
    completed_at: datetime | None = None
    status: CrawlStatus
    pages: list[SearchPage] = Field(max_length=MAX_SEARCH_PAGES)
    coverage: CoverageSummary

    @model_validator(mode="after")
    def validate_coverage(self) -> "CrawlRun":
        if self.coverage.requested_pages != self.request.max_pages:
            raise ValueError("coverage.requested_pages must equal request.max_pages")
        page_numbers = [page.page_number for page in self.pages]
        if len(page_numbers) != len(set(page_numbers)):
            raise ValueError("crawl pages must have unique page numbers")
        if any(page_number > self.request.max_pages for page_number in page_numbers):
            raise ValueError("crawl pages cannot exceed request.max_pages")
        if self.coverage.raw_result_count != sum(page.raw_result_count for page in self.pages):
            raise ValueError("coverage.raw_result_count must equal the page raw-result total")
        completed_pages = sum(page.completed_successfully for page in self.pages)
        if completed_pages != self.coverage.successful_pages:
            raise ValueError("successful_pages must count success and empty page responses")
        if completed_pages == 0:
            if self.status not in {CrawlStatus.FAILED, CrawlStatus.CANCELLED}:
                raise ValueError("zero successful pages must be failed or cancelled")
            if self.coverage.partial_success:
                raise ValueError("zero successful pages cannot set partial_success")
            if self.coverage.deduplicated_video_count != 0:
                raise ValueError("zero successful pages cannot contain deduplicated videos")
        elif completed_pages < self.request.max_pages:
            if self.status != CrawlStatus.PARTIAL or not self.coverage.partial_success:
                raise ValueError("fewer than all requested successful pages must be partial")
        else:
            if self.coverage.partial_success:
                raise ValueError("all requested pages succeeded, so partial_success must be false")
            expected_status = (
                CrawlStatus.EMPTY
                if self.coverage.deduplicated_video_count == 0
                else CrawlStatus.SUCCESS
            )
            if self.status != expected_status:
                raise ValueError(f"all requested pages require status={expected_status.value}")
        return self

    @property
    def can_generate_normal_report(self) -> bool:
        return self.status == CrawlStatus.SUCCESS and self.coverage.deduplicated_video_count > 0


class IntelligenceCompetitor(StrictModel):
    creator: Creator
    score: CompetitorScore
    representatives: RepresentativeSelection
    metrics: list[MetricResult]
    themes: list[str] = Field(default_factory=list)
    formats: list[str] = Field(default_factory=list)
    title_patterns: list[str] = Field(default_factory=list)
    transcript_patterns: list[str] = Field(default_factory=list)


class IntelligenceReport(StrictModel):
    schema_version: Literal[CONTENT_INTELLIGENCE_SCHEMA_VERSION] = CONTENT_INTELLIGENCE_SCHEMA_VERSION
    report_id: str
    crawl_run_id: str
    generated_at: datetime
    report_status: Literal["success", "partial", "failed", "insufficient_data"]
    query: SearchRequest
    provider: ProviderCapabilities
    coverage: CoverageSummary
    competitors: list[IntelligenceCompetitor] = Field(max_length=MAX_COMPETITORS)
    current_landscape: list[str] = Field(default_factory=list)
    competitive_gaps: list[str] = Field(default_factory=list)
    risks_and_uncertainties: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    partial_success_notice: str | None = None
    truncation_notice: str | None = None

    @model_validator(mode="after")
    def validate_report_status(self) -> "IntelligenceReport":
        if self.coverage.actual_competitor_count != len(self.competitors):
            raise ValueError("actual_competitor_count must equal the serialized competitor count")
        if self.coverage.successful_pages == 0 and self.report_status in {"success", "partial"}:
            raise ValueError("zero successful pages cannot produce a normal report")
        if self.coverage.partial_success and self.report_status == "success":
            raise ValueError("partial crawl cannot produce a success report")
        if self.report_status == "partial" and not self.coverage.partial_success:
            raise ValueError("partial report status requires partial coverage")
        if self.coverage.partial_success and not self.partial_success_notice:
            raise ValueError("partial report requires a visible notice")
        if self.coverage.deduplicated_video_count == 0 and self.report_status in {"success", "partial"}:
            raise ValueError("an empty result set cannot produce a normal report")
        if self.report_status == "success" and not self.competitors:
            raise ValueError("a success report requires at least one competitor")
        return self
