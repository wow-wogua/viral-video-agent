"""Structured semantic relevance labeling for P0-C."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agents.supervisor import extract_text
from src.gateway.llm_router import get_llm
from src.intelligence.contracts import (
    CreatorSemanticAssessment,
    RelevanceDecision,
    RelevanceLabel,
)
from src.prompts.manager import prompt_manager


RELEVANCE_LABELER_VERSION = "content-relevance.p0.1"
UNAUDITED_LABELER_VERSION = "not-audited.p0.1"


@dataclass(frozen=True, slots=True)
class RelevanceContext:
    keyword: str
    category: str = "vertical"
    intent_definition: str = ""
    allowed_subtopics: tuple[str, ...] = ()
    exclusion_rules: tuple[str, ...] = ()


@dataclass(slots=True)
class CreatorLabelingResult:
    decisions: list[RelevanceDecision]
    assessment: CreatorSemanticAssessment


class RelevanceLabeler(Protocol):
    async def label_creator(
        self,
        context: RelevanceContext,
        creator_mid: str,
        creator_name: str,
        videos: Sequence[Any],
        evidence_ids: dict[str, list[str]],
    ) -> CreatorLabelingResult: ...


class _LLMLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bvid: str
    label: RelevanceLabel
    reason: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0, le=1)


class _LLMResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[_LLMLabel]
    generalist: bool | None = None
    risk_flags: list[
        str
    ] = Field(default_factory=list)
    assessment_reason: str = Field(min_length=1, max_length=400)
    assessment_confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_risk_flags(self) -> "_LLMResult":
        allowed = {
            "aggregator", "reupload", "course_matrix", "content_farm", "news_repost", "occasional_hit",
        }
        unknown = sorted(set(self.risk_flags) - allowed)
        if unknown:
            raise ValueError(f"unsupported risk flags: {', '.join(unknown)}")
        return self


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("relevance labeler did not return a JSON object")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("relevance labeler output must be a JSON object")
    return value


def _video_payload(video: Any) -> dict[str, Any]:
    return {
        "bvid": video.bvid,
        "title": video.title,
        "description": video.description,
        "tags": list(video.tags or []),
        "partition": video.partition,
        "published_at": video.published_at.isoformat() if video.published_at else None,
    }


def uncertain_creator_result(
    videos: Sequence[Any],
    evidence_ids: dict[str, list[str]],
    *,
    reason: str,
    labeler: str = "system",
    labeler_version: str = UNAUDITED_LABELER_VERSION,
) -> CreatorLabelingResult:
    return CreatorLabelingResult(
        decisions=[
            RelevanceDecision(
                bvid=video.bvid,
                label=RelevanceLabel.UNCERTAIN,
                reason=reason,
                confidence=0.0,
                evidence_ids=evidence_ids.get(video.bvid, []),
                labeler=labeler,
                labeler_version=labeler_version,
            )
            for video in videos
        ],
        assessment=CreatorSemanticAssessment(
            generalist=None,
            risk_flags=[],
            reason=reason,
            confidence=0.0,
            labeler=labeler,
            labeler_version=labeler_version,
        ),
    )


class LLMRelevanceLabeler:
    def __init__(self, *, agent_name: str = "competitor_relevance") -> None:
        self.agent_name = agent_name

    async def label_creator(
        self,
        context: RelevanceContext,
        creator_mid: str,
        creator_name: str,
        videos: Sequence[Any],
        evidence_ids: dict[str, list[str]],
    ) -> CreatorLabelingResult:
        if not videos:
            return uncertain_creator_result(videos, evidence_ids, reason="creator sample contains no videos")
        prompt = prompt_manager.get(
            "competitor_relevance",
            keyword=context.keyword,
            category=context.category,
            intent_definition=context.intent_definition or context.keyword,
            allowed_subtopics=json.dumps(list(context.allowed_subtopics), ensure_ascii=False),
            exclusion_rules=json.dumps(list(context.exclusion_rules), ensure_ascii=False),
            creator_name=creator_name,
            videos=json.dumps([_video_payload(video) for video in videos], ensure_ascii=False),
        )
        try:
            response = await get_llm(self.agent_name, temperature=0.0).ainvoke([HumanMessage(content=prompt)])
            parsed = _LLMResult.model_validate(_parse_json_object(extract_text(response)))
            expected = [video.bvid for video in videos]
            actual = [item.bvid for item in parsed.labels]
            if len(actual) != len(set(actual)) or set(actual) != set(expected):
                raise ValueError("relevance labeler must return exactly one label per input BVID")
        except Exception as exc:
            return uncertain_creator_result(
                videos,
                evidence_ids,
                reason=f"semantic labeler unavailable: {type(exc).__name__}",
                labeler="llm",
                labeler_version=RELEVANCE_LABELER_VERSION,
            )
        by_bvid = {item.bvid: item for item in parsed.labels}
        return CreatorLabelingResult(
            decisions=[
                RelevanceDecision(
                    bvid=video.bvid,
                    label=by_bvid[video.bvid].label,
                    reason=by_bvid[video.bvid].reason,
                    confidence=by_bvid[video.bvid].confidence,
                    evidence_ids=evidence_ids.get(video.bvid, []),
                    labeler="llm",
                    labeler_version=RELEVANCE_LABELER_VERSION,
                )
                for video in videos
            ],
            assessment=CreatorSemanticAssessment(
                generalist=parsed.generalist,
                risk_flags=parsed.risk_flags,
                reason=parsed.assessment_reason,
                confidence=parsed.assessment_confidence,
                labeler="llm",
                labeler_version=RELEVANCE_LABELER_VERSION,
            ),
        )


class FixtureRelevanceLabeler:
    """Deterministic labeler for tests; it never calls an external model."""

    def __init__(
        self,
        labels: dict[str, RelevanceLabel | str],
        *,
        generalist: bool | None = False,
        risk_flags: list[str] | None = None,
        confidence: float = 0.9,
    ) -> None:
        self.labels = {bvid: RelevanceLabel(label) for bvid, label in labels.items()}
        self.generalist = generalist
        self.risk_flags = risk_flags or []
        self.confidence = confidence

    async def label_creator(
        self,
        context: RelevanceContext,
        creator_mid: str,
        creator_name: str,
        videos: Sequence[Any],
        evidence_ids: dict[str, list[str]],
    ) -> CreatorLabelingResult:
        decisions = []
        for video in videos:
            label = self.labels.get(video.bvid, RelevanceLabel.UNCERTAIN)
            decisions.append(RelevanceDecision(
                bvid=video.bvid,
                label=label,
                reason=f"fixture {label.value}",
                confidence=self.confidence if label != RelevanceLabel.UNCERTAIN else 0.5,
                evidence_ids=evidence_ids.get(video.bvid, []),
                labeler="fixture",
                labeler_version=RELEVANCE_LABELER_VERSION,
            ))
        return CreatorLabelingResult(
            decisions=decisions,
            assessment=CreatorSemanticAssessment(
                generalist=self.generalist,
                risk_flags=self.risk_flags,
                reason="fixture creator assessment",
                confidence=self.confidence,
                labeler="fixture",
                labeler_version=RELEVANCE_LABELER_VERSION,
            ),
        )
