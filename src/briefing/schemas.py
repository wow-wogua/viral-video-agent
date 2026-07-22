import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BriefOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)


class TopicSpec(BaseModel):
    """The durable, bounded research scope passed to the existing graph."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str = Field(min_length=1, max_length=120)
    target_content: list[str] = Field(min_length=1, max_length=8)
    include_creator_types: list[str] = Field(default_factory=list, max_length=8)
    exclude_content: list[str] = Field(default_factory=list, max_length=8)
    time_window_days: int = Field(default=365, ge=1, le=3650)
    allow_generalist: bool = False
    competitor_definition: str = Field(min_length=1, max_length=300)
    platform: Literal["bilibili"] = "bilibili"
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_collections(self) -> "TopicSpec":
        for values in (
            self.target_content,
            self.include_creator_types,
            self.exclude_content,
            self.assumptions,
        ):
            if any(not item.strip() or len(item.strip()) > 200 for item in values):
                raise ValueError("TopicSpec list values must be non-empty and at most 200 characters")
        return self


class BriefDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    need_clarification: bool
    question: str | None = Field(default=None, max_length=500)
    options: list[BriefOption] = Field(default_factory=list, max_length=4)
    allow_custom: bool = False
    verification: str = Field(default="", max_length=500)
    topic_spec: TopicSpec | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_shape(self) -> "BriefDecision":
        if self.need_clarification:
            if not self.question or not 2 <= len(self.options) <= 4:
                raise ValueError("clarification decisions require one question and 2-4 options")
            if not self.allow_custom:
                raise ValueError("clarification decisions must allow custom answers")
            if self.topic_spec is not None:
                raise ValueError("clarification decisions cannot include a topic_spec")
        elif self.topic_spec is None:
            raise ValueError("non-clarification decisions require a topic_spec")
        return self


class ClarificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: uuid.UUID
    selected_option_id: str | None = Field(default=None, min_length=1, max_length=64)
    custom_answer: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def require_answer(self) -> "ClarificationAnswer":
        if not self.selected_option_id and not self.custom_answer:
            raise ValueError("select an option or provide a custom answer")
        return self


class ClarificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_id: uuid.UUID
    job_id: uuid.UUID
    round: int
    question: str
    options: list[BriefOption]
    allow_custom: bool
    status: Literal["pending", "answered"]
    selected_option_id: str | None
    custom_answer: str | None
    created_at: datetime
    answered_at: datetime | None
