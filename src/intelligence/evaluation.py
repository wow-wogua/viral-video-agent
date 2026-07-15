"""Private evaluation-suite schema and validation helpers."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    CREATOR_QUALIFICATION_POLICY_VERSION,
    CreatorQualificationEvidence,
    CreatorQualificationStatus,
)


EVALUATION_SCHEMA_VERSION = "content-intelligence-eval.p0.3"


class KeywordCategory(StrEnum):
    BROAD = "broad"
    VERTICAL = "vertical"
    BRAND = "brand"
    AMBIGUOUS = "ambiguous"
    LOW_RESULT = "low_result"


class ReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    INITIAL_LABELED = "initial_labeled"
    USER_REVIEWED = "user_reviewed"
    ADJUDICATED = "adjudicated"


class CreatorReviewDecision(StrEnum):
    UNREVIEWED = "unreviewed"
    KEEP = "keep"
    EXCLUDE = "exclude"
    UNCERTAIN = "uncertain"


class CreatorRole(StrEnum):
    SPECIALIST = "specialist"
    GENERALIST = "generalist"
    OFFICIAL = "official"
    MEDIA = "media"
    EDUCATOR = "educator"
    RESELLER_SERVICE = "reseller_service"
    AGGREGATOR = "aggregator"
    CONTENT_FARM = "content_farm"
    UNRELATED = "unrelated"
    UNKNOWN = "unknown"


class FocusLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class DiscoverySource(StrEnum):
    RETRIEVED_SNAPSHOT = "retrieved_snapshot"
    TARGETED_MANUAL_SEARCH = "targeted_manual_search"
    REVIEWER_KNOWN = "reviewer_known"


class CreatorQualificationPolicy(BaseModel):
    """Frozen p0.1 policy for account-level reference qualification."""

    model_config = ConfigDict(extra="forbid")
    policy_version: Literal[CREATOR_QUALIFICATION_POLICY_VERSION] = CREATOR_QUALIFICATION_POLICY_VERSION
    latest_upload_limit: Literal[20] = 20
    recent_window_days: Literal[90] = 90
    min_relevant_videos: Literal[3] = 3
    min_recent_90d_relevant_videos: Literal[3] = 3
    broad_or_generalist_min_relevant_ratio: Literal[0.2] = 0.2
    vertical_min_relevant_ratio: Literal[0.3] = 0.3
    min_follower_count: Literal[10000] = 10000
    min_relevant_view_median: Literal[5000] = 5000
    low_result_policy: Literal["separate_required"] = "separate_required"

    def minimum_relevant_ratio(self, *, category: KeywordCategory, role: CreatorRole) -> float | None:
        if category == KeywordCategory.LOW_RESULT:
            return None
        if category == KeywordCategory.BROAD or role == CreatorRole.GENERALIST:
            return self.broad_or_generalist_min_relevant_ratio
        return self.vertical_min_relevant_ratio


class SnapshotReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    searched_at: datetime
    provider: str
    source_url: str | None = None
    snapshot_file: str
    successful_pages: int = Field(ge=0, le=5)
    raw_result_count: int = Field(ge=0)


class TopCreatorLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mid: str
    name: str
    relevant: bool | None = None
    decision: CreatorReviewDecision = CreatorReviewDecision.UNREVIEWED
    role: CreatorRole = CreatorRole.UNKNOWN
    focus_level: FocusLevel = FocusLevel.UNKNOWN
    in_retrieved_pool: bool = True
    reason: str
    rank: int | None = Field(default=None, ge=1, le=5)
    qualification_status: CreatorQualificationStatus = CreatorQualificationStatus.DISCOVERY_ONLY
    qualification_policy_version: str | None = None
    qualification_evidence: CreatorQualificationEvidence | None = None

    @model_validator(mode="after")
    def validate_qualification_shape(self) -> "TopCreatorLabel":
        if self.qualification_status in {
            CreatorQualificationStatus.EMERGING_CANDIDATE,
            CreatorQualificationStatus.QUALIFIED_REFERENCE,
        }:
            if self.decision != CreatorReviewDecision.KEEP or self.relevant is not True:
                raise ValueError("emerging and qualified Top 5 creators require relevant=true and decision=keep")
            if not self.qualification_policy_version:
                raise ValueError("emerging and qualified Top 5 creators require qualification_policy_version")
            if self.qualification_evidence is None:
                raise ValueError("emerging and qualified Top 5 creators require account-level qualification_evidence")
        if (
            self.qualification_status == CreatorQualificationStatus.EXCLUDED
            and self.decision != CreatorReviewDecision.EXCLUDE
        ):
            raise ValueError("excluded Top 5 creators require decision=exclude")
        return self


class ExpectedRelevantCreator(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mid: str
    name: str
    role: CreatorRole
    focus_level: FocusLevel
    discovery_source: DiscoverySource
    in_retrieved_pool: bool
    reason: str
    evidence_urls: list[str] = Field(default_factory=list)
    qualification_status: CreatorQualificationStatus = CreatorQualificationStatus.DISCOVERY_ONLY
    review_decision: CreatorReviewDecision = CreatorReviewDecision.UNREVIEWED
    qualification_policy_version: str | None = None
    qualification_evidence: CreatorQualificationEvidence | None = None

    @model_validator(mode="after")
    def validate_qualification_shape(self) -> "ExpectedRelevantCreator":
        if self.qualification_status in {
            CreatorQualificationStatus.EMERGING_CANDIDATE,
            CreatorQualificationStatus.QUALIFIED_REFERENCE,
        }:
            if self.review_decision != CreatorReviewDecision.KEEP:
                raise ValueError("emerging and qualified creators require review_decision=keep")
            if not self.qualification_policy_version:
                raise ValueError("emerging and qualified creators require qualification_policy_version")
            if self.qualification_evidence is None:
                raise ValueError("emerging and qualified creators require account-level qualification_evidence")
        if (
            self.qualification_status == CreatorQualificationStatus.EXCLUDED
            and self.review_decision != CreatorReviewDecision.EXCLUDE
        ):
            raise ValueError("excluded creators require review_decision=exclude")
        return self


class EvaluationKeyword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    keyword: str
    category: KeywordCategory
    rationale: str
    intent_definition: str = ""
    allowed_subtopics: list[str] = Field(default_factory=list)
    exclusion_rules: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED
    reviewer_count: int = Field(default=0, ge=0, le=2)
    snapshots: list[SnapshotReference] = Field(default_factory=list)
    top_creators: list[TopCreatorLabel] = Field(default_factory=list, max_length=5)
    expected_relevant_creators: list[ExpectedRelevantCreator] = Field(default_factory=list)
    qualified_top5_count: int = Field(default=0, ge=0, le=5)
    notes: str = ""

    @model_validator(mode="after")
    def validate_qualified_top5_count(self) -> "EvaluationKeyword":
        if self.review_status in {ReviewStatus.UNREVIEWED, ReviewStatus.INITIAL_LABELED}:
            if self.reviewer_count != 0:
                raise ValueError("unreviewed and initial_labeled items must have reviewer_count=0")
        elif self.review_status == ReviewStatus.USER_REVIEWED:
            if self.reviewer_count < 1:
                raise ValueError("user_reviewed items require at least one human reviewer")
        elif self.review_status == ReviewStatus.ADJUDICATED and self.reviewer_count != 2:
            raise ValueError("adjudicated items require two human reviewers")
        actual_count = len(self.qualified_top_creators)
        if self.qualified_top5_count != actual_count:
            raise ValueError(
                f"qualified_top5_count={self.qualified_top5_count} does not match "
                f"{actual_count} account-qualified Top 5 creators"
            )
        return self

    @property
    def qualified_top_creators(self) -> list[TopCreatorLabel]:
        return [
            creator
            for creator in self.top_creators
            if creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE
        ]

    @property
    def reference_candidates(self) -> list[ExpectedRelevantCreator]:
        """Compatibility alias with semantics that do not assume qualification."""

        return self.expected_relevant_creators

    @property
    def qualified_reference_creators(self) -> list[ExpectedRelevantCreator]:
        return [
            creator
            for creator in self.expected_relevant_creators
            if creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE
        ]

    @property
    def retrieval_recall(self) -> float | None:
        references = self.qualified_reference_creators
        if not references:
            return None
        retrieved_count = sum(creator.in_retrieved_pool for creator in references)
        return retrieved_count / len(references)

    def validate_reference_qualifications(self, policy: CreatorQualificationPolicy) -> None:
        for creator in [*self.top_creators, *self.expected_relevant_creators]:
            if creator.qualification_status not in {
                CreatorQualificationStatus.EMERGING_CANDIDATE,
                CreatorQualificationStatus.QUALIFIED_REFERENCE,
            }:
                continue

            if self.category == KeywordCategory.LOW_RESULT:
                raise ValueError(
                    f"{self.keyword}/{creator.name}: low_result creators require a separately versioned qualification policy"
                )
            if creator.qualification_policy_version != policy.policy_version:
                raise ValueError(f"{self.keyword}/{creator.name}: qualification policy version mismatch")

            evidence = creator.qualification_evidence
            if evidence is None:  # Kept defensive for callers that construct without normal model validation.
                raise ValueError(f"{self.keyword}/{creator.name}: qualification evidence is missing")
            if evidence.audited_upload_count > policy.latest_upload_limit:
                raise ValueError(f"{self.keyword}/{creator.name}: audited upload count exceeds policy limit")
            if evidence.relevant_video_count < policy.min_relevant_videos:
                raise ValueError(
                    f"{self.keyword}/{creator.name}: at least {policy.min_relevant_videos} relevant videos are required"
                )
            if evidence.recent_90d_relevant_video_count < policy.min_recent_90d_relevant_videos:
                raise ValueError(
                    f"{self.keyword}/{creator.name}: at least "
                    f"{policy.min_recent_90d_relevant_videos} relevant videos in the recent 90-day window are required"
                )

            minimum_ratio = policy.minimum_relevant_ratio(category=self.category, role=creator.role)
            if evidence.relevant_ratio is None or minimum_ratio is None or evidence.relevant_ratio < minimum_ratio:
                raise ValueError(
                    f"{self.keyword}/{creator.name}: relevant content ratio is below the qualification threshold"
                )
            if len(evidence.evidence_urls) < policy.min_relevant_videos:
                raise ValueError(
                    f"{self.keyword}/{creator.name}: qualification evidence requires at least "
                    f"{policy.min_relevant_videos} account-sample URLs"
                )

            passes_influence = (
                evidence.follower_count is not None
                and evidence.follower_count >= policy.min_follower_count
            ) or (
                evidence.relevant_view_median is not None
                and evidence.relevant_view_median >= policy.min_relevant_view_median
            )
            if (
                creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE
                and not passes_influence
            ):
                raise ValueError(f"{self.keyword}/{creator.name}: qualified_reference does not meet influence threshold")
            if creator.qualification_status == CreatorQualificationStatus.EMERGING_CANDIDATE and passes_influence:
                raise ValueError(f"{self.keyword}/{creator.name}: influence-qualified creator cannot remain emerging")


class EvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[EVALUATION_SCHEMA_VERSION] = EVALUATION_SCHEMA_VERSION
    dataset_id: str
    created_at: datetime
    contains_hidden_holdout: bool = False
    qualification_policy: CreatorQualificationPolicy = Field(default_factory=CreatorQualificationPolicy)
    keywords: list[EvaluationKeyword]

    @model_validator(mode="after")
    def validate_distribution(self) -> "EvaluationSuite":
        if len(self.keywords) != 20:
            raise ValueError("the private baseline must contain exactly 20 keywords")
        normalized = [item.keyword.strip().lower() for item in self.keywords]
        if len(set(normalized)) != len(normalized):
            raise ValueError("keywords must be unique")
        counts = {category: 0 for category in KeywordCategory}
        for item in self.keywords:
            counts[item.category] += 1
        minimums = {
            KeywordCategory.BROAD: 4,
            KeywordCategory.VERTICAL: 4,
            KeywordCategory.BRAND: 3,
            KeywordCategory.AMBIGUOUS: 2,
            KeywordCategory.LOW_RESULT: 2,
        }
        missing = [f"{category.value}>={minimum}" for category, minimum in minimums.items() if counts[category] < minimum]
        if missing:
            raise ValueError(f"keyword category coverage is incomplete: {', '.join(missing)}")
        return self

    def validate_reference_qualifications(self) -> None:
        for item in self.keywords:
            item.validate_reference_qualifications(self.qualification_policy)


def load_evaluation_suite(path: Path) -> EvaluationSuite:
    return EvaluationSuite.model_validate(json.loads(path.read_text(encoding="utf-8")))


def validate_evaluation_file(path: Path, *, require_reviewed: bool = False) -> EvaluationSuite:
    suite = load_evaluation_suite(path)
    suite.validate_reference_qualifications()
    if require_reviewed:
        incomplete = [
            item.keyword
            for item in suite.keywords
            if item.review_status not in {ReviewStatus.USER_REVIEWED, ReviewStatus.ADJUDICATED}
            or item.reviewer_count < 1
            or not item.snapshots
            or not item.intent_definition.strip()
            or any(label.decision == CreatorReviewDecision.UNREVIEWED for label in item.top_creators)
            or any(
                label.decision == CreatorReviewDecision.KEEP
                and label.qualification_status
                not in {
                    CreatorQualificationStatus.EMERGING_CANDIDATE,
                    CreatorQualificationStatus.QUALIFIED_REFERENCE,
                }
                for label in item.top_creators
            )
            or any(
                label.decision == CreatorReviewDecision.EXCLUDE
                and label.qualification_status != CreatorQualificationStatus.EXCLUDED
                for label in item.top_creators
            )
        ]
        if incomplete:
            raise ValueError(
                f"reviewed baseline is incomplete: {len(incomplete)} of {len(suite.keywords)} keywords"
            )
    return suite
