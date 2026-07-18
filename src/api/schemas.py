import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_active: bool


class JobCreate(BaseModel):
    query: str = Field(min_length=3, max_length=2000)
    platforms: list[str] = Field(default_factory=lambda: ["bilibili"])
    analysis_mode: Literal["standard", "deep"] = "standard"
    task_mode: Literal["legacy", "content_intelligence"] = "legacy"
    keyword: str | None = Field(default=None, min_length=1, max_length=200)
    sort_mode: Literal["relevance", "newest", "most_viewed"] = "relevance"
    time_range: Literal["all", "day", "week", "month", "quarter", "year"] = "all"
    partition: str | None = Field(default=None, max_length=80)
    max_pages: int | None = Field(default=None, ge=1, le=5)
    filters: dict[str, Any] = Field(default_factory=dict)
    search_provider: Literal["development", "import"] = "development"
    import_format: Literal["json", "csv"] | None = None
    import_data: dict[str, Any] | str | None = None
    include_competitors: bool = False
    keyword_category: Literal["broad", "vertical", "brand", "ambiguous", "low_result"] = "vertical"
    intent_definition: str = Field(default="", max_length=2000)
    allowed_subtopics: list[str] = Field(default_factory=list, max_length=20)
    exclusion_rules: list[str] = Field(default_factory=list, max_length=20)
    creator_provider: Literal["development", "uapi", "import"] = "development"
    creator_import_format: Literal["json", "csv"] | None = None
    creator_import_data: dict[str, Any] | str | None = None
    idempotency_key: str = Field(min_length=8, max_length=128)

    @field_validator("platforms")
    @classmethod
    def bilibili_only(cls, value: list[str]) -> list[str]:
        if value != ["bilibili"]:
            raise ValueError("only bilibili is supported")
        return value

    @model_validator(mode="after")
    def validate_task_mode(self) -> "JobCreate":
        if self.max_pages is None:
            self.max_pages = 5 if self.task_mode == "content_intelligence" else 1
        if self.task_mode == "legacy":
            if (
                self.search_provider != "development"
                or self.import_data is not None
                or self.import_format is not None
                or self.include_competitors
                or self.creator_provider != "development"
                or self.creator_import_data is not None
                or self.creator_import_format is not None
            ):
                raise ValueError("legacy jobs do not accept content-intelligence provider inputs")
            return self
        if not self.keyword:
            raise ValueError("content_intelligence jobs require keyword")
        if self.analysis_mode != "standard":
            raise ValueError("P0-B content_intelligence jobs do not enable ASR")
        if self.search_provider == "import":
            if self.import_format is None or self.import_data is None:
                raise ValueError("import jobs require import_format and import_data")
            if self.import_format == "json" and not isinstance(self.import_data, (dict, str)):
                raise ValueError("JSON import_data must be an object or JSON string")
            if self.import_format == "csv" and not isinstance(self.import_data, str):
                raise ValueError("CSV import_data must be text")
        elif self.import_format is not None or self.import_data is not None:
            raise ValueError("development provider does not accept import data")
        if not self.include_competitors:
            if self.creator_provider != "development" or self.creator_import_format is not None or self.creator_import_data is not None:
                raise ValueError("creator provider inputs require include_competitors=true")
            return self
        if self.creator_provider == "import":
            if self.creator_import_format is None or self.creator_import_data is None:
                raise ValueError("creator import requires creator_import_format and creator_import_data")
            if self.creator_import_format == "json" and not isinstance(self.creator_import_data, (dict, str)):
                raise ValueError("creator JSON import data must be an object or JSON string")
            if self.creator_import_format == "csv" and not isinstance(self.creator_import_data, str):
                raise ValueError("creator CSV import data must be text")
        elif self.creator_import_format is not None or self.creator_import_data is not None:
            raise ValueError("development creator provider does not accept import data")
        return self


class JobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    message: str
    progress: int
    level: str
    created_at: datetime


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    query: str
    platforms: list[str]
    analysis_mode: str
    task_mode: str
    keyword: str | None
    sort_mode: str
    time_range: str
    partition: str | None
    max_pages: int
    status: str
    progress: int
    retry_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    report_id: uuid.UUID | None = None


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    evidence_id: str
    tool: str
    source_type: str
    title: str
    source_url: str | None
    platform: str
    fetched_at: datetime
    raw_data: dict
    summary: str | None
    data_fields: dict
    transcript_segment: dict | None


class UsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    asr_seconds: float


class ReportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    job_id: uuid.UUID
    title: str
    content: str
    structured_claims: list[dict]
    status: str
    model_info: dict
    evidence: list[EvidenceRead] = Field(default_factory=list)
    usage: UsageRead | None = None
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    useful: bool
    reason: str = Field(default="", max_length=100)
    comment: str = Field(default="", max_length=2000)
    adopted: bool | None = None


class ShareCreate(BaseModel):
    expires_in_days: int = Field(default=7, ge=1, le=90)
