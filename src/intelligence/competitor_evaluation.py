"""Frozen P0-C evaluation formulas for selected precision, coverage, and recall."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

from src.intelligence.contracts import (
    AccountTopicRelevance,
    CreatorProductRelation,
    CreatorQualificationStatus,
    CreatorTopicEvidence,
    CreatorTopicRole,
    HumanCreatorTopicReview,
    SpecializationLevel,
)
from src.intelligence.evaluation import CreatorReviewDecision, EvaluationKeyword


EVALUATION_FORMULA_VERSION = "competitor-evaluation.p0.1"
EVALUATION_FORMULA_VERSION_V3 = "competitor-evaluation.p0.2"
EVALUATION_TRUTH_MIN_DECIDED_UPLOADS = 10
EVALUATION_TRUTH_MIN_RELEVANT_UPLOADS = 5
EVALUATION_TRUTH_MIN_RELEVANT_RATIO = 0.50
EVALUATION_TRUTH_MIN_RELEVANT_30D_UPLOADS = 1
EVALUATION_TRUTH_MIN_RELEVANT_90D_UPLOADS = 3
EVALUATION_TRUTH_MIN_FOLLOWER_COUNT = 10_000
EVALUATION_TRUTH_MIN_RELEVANT_VIEW_MEDIAN = 5_000


@dataclass(slots=True)
class KeywordCompetitorMetrics:
    keyword_id: str
    category: str
    selected_count: int
    correct_selected_count: int
    known_irrelevant_selected_count: int
    unresolved_selected_count: int
    qualified_reference_count: int
    retrieved_qualified_reference_count: int
    eligible_top5_slots: int
    selected_precision: float | None
    strict_precision_at_5: float | None
    irrelevant_false_positive_rate: float | None
    unresolved_selection_rate: float | None
    output_coverage: float | None
    retrieval_recall: float | None
    abstained: bool
    shortfall_count: int


def evaluate_keyword(
    keyword: EvaluationKeyword,
    *,
    selected_mids: Sequence[str],
    retrieved_mids: Iterable[str],
) -> KeywordCompetitorMetrics:
    selected = list(dict.fromkeys(selected_mids))[:5]
    retrieved = set(retrieved_mids)
    qualified = {
        creator.mid
        for creator in [*keyword.top_creators, *keyword.expected_relevant_creators]
        if creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE
    }
    known_irrelevant = {
        creator.mid
        for creator in keyword.top_creators
        if creator.qualification_status == CreatorQualificationStatus.EXCLUDED
        or creator.decision == CreatorReviewDecision.EXCLUDE
    }
    retrieved_qualified = qualified.intersection(retrieved)
    correct = sum(mid in qualified for mid in selected)
    irrelevant = sum(mid in known_irrelevant for mid in selected)
    unresolved = sum(mid not in qualified and mid not in known_irrelevant for mid in selected)
    eligible_slots = min(5, len(retrieved_qualified))
    selected_count = len(selected)
    return KeywordCompetitorMetrics(
        keyword_id=keyword.id,
        category=keyword.category.value,
        selected_count=selected_count,
        correct_selected_count=correct,
        known_irrelevant_selected_count=irrelevant,
        unresolved_selected_count=unresolved,
        qualified_reference_count=len(qualified),
        retrieved_qualified_reference_count=len(retrieved_qualified),
        eligible_top5_slots=eligible_slots,
        selected_precision=correct / selected_count if selected_count else None,
        strict_precision_at_5=correct / eligible_slots if eligible_slots else None,
        irrelevant_false_positive_rate=irrelevant / selected_count if selected_count else None,
        unresolved_selection_rate=unresolved / selected_count if selected_count else None,
        output_coverage=min(selected_count, eligible_slots) / eligible_slots if eligible_slots else None,
        retrieval_recall=len(retrieved_qualified) / len(qualified) if qualified else None,
        abstained=selected_count == 0,
        shortfall_count=max(eligible_slots - selected_count, 0),
    )


def _aggregate(metrics: Sequence[KeywordCompetitorMetrics]) -> dict:
    selected = sum(item.selected_count for item in metrics)
    correct = sum(item.correct_selected_count for item in metrics)
    irrelevant = sum(item.known_irrelevant_selected_count for item in metrics)
    unresolved = sum(item.unresolved_selected_count for item in metrics)
    eligible = sum(item.eligible_top5_slots for item in metrics)
    qualified = sum(item.qualified_reference_count for item in metrics)
    retrieved = sum(item.retrieved_qualified_reference_count for item in metrics)
    covered_slots = sum(min(item.selected_count, item.eligible_top5_slots) for item in metrics)
    return {
        "keyword_count": len(metrics),
        "selected_count": selected,
        "correct_selected_count": correct,
        "known_irrelevant_selected_count": irrelevant,
        "unresolved_selected_count": unresolved,
        "eligible_top5_slots": eligible,
        "selected_precision": correct / selected if selected else None,
        "strict_precision_at_5": correct / eligible if eligible else None,
        "irrelevant_false_positive_rate": irrelevant / selected if selected else None,
        "unresolved_selection_rate": unresolved / selected if selected else None,
        "output_coverage": covered_slots / eligible if eligible else None,
        "raw_output_capacity_coverage": selected / (len(metrics) * 5) if metrics else None,
        "retrieval_recall": retrieved / qualified if qualified else None,
        "abstention_keyword_count": sum(item.abstained for item in metrics),
        "shortfall_count": sum(item.shortfall_count for item in metrics),
    }


def aggregate_evaluation(metrics: Sequence[KeywordCompetitorMetrics]) -> dict:
    by_category: dict[str, list[KeywordCompetitorMetrics]] = defaultdict(list)
    for item in metrics:
        by_category[item.category].append(item)
    overall = _aggregate(metrics)
    return {
        "formula_version": EVALUATION_FORMULA_VERSION,
        "definitions": {
            "selected_precision": "qualified_reference selected / all selected; unknown selections count against precision",
            "strict_precision_at_5": "qualified_reference selected / min(5, retrieved qualified_reference count); unfilled eligible slots count against the metric",
            "irrelevant_false_positive_rate": "human-excluded selected / all selected",
            "unresolved_selection_rate": "selected accounts without a frozen qualified or excluded human decision / all selected",
            "output_coverage": "filled eligible slots / min(5, retrieved qualified_reference count)",
            "retrieval_recall": "retrieved qualified_reference / all frozen qualified_reference",
            "abstention": "selected_count equals zero; reported separately even when no qualified reference exists",
        },
        "overall": overall,
        "by_category": {category: _aggregate(items) for category, items in sorted(by_category.items())},
        "keywords": [asdict(item) for item in metrics],
    }


@dataclass(slots=True)
class CreatorEvaluationTruthV3:
    formula_version: str
    keyword_id: str
    creator_mid: str
    relation: CreatorProductRelation
    human_relevance: AccountTopicRelevance
    human_specialization: SpecializationLevel
    human_role: CreatorTopicRole
    objective_checks: dict[str, bool]
    reasons: list[str]


def _truth_influence_passes(evidence: CreatorTopicEvidence) -> bool:
    return (
        evidence.follower_count is not None
        and evidence.follower_count >= EVALUATION_TRUTH_MIN_FOLLOWER_COUNT
    ) or (
        evidence.relevant_view_median is not None
        and evidence.relevant_view_median >= EVALUATION_TRUTH_MIN_RELEVANT_VIEW_MEDIAN
    )


def map_review_to_evaluation_truth_v3(
    review: HumanCreatorTopicReview,
    evidence: CreatorTopicEvidence,
    *,
    category: str,
) -> CreatorEvaluationTruthV3:
    """Map human dimensions and independent evidence to truth without system outputs."""
    if not review.review_complete:
        raise ValueError("v3 evaluation truth requires a complete human review")
    if (
        review.human_relevance is None
        or review.human_specialization is None
        or review.human_role is None
    ):
        raise ValueError("v3 evaluation truth requires all human dimensions")
    checks = {
        "decided_sample": (
            evidence.decided_upload_count >= EVALUATION_TRUTH_MIN_DECIDED_UPLOADS
        ),
        "relevant_uploads": (
            evidence.relevant_upload_count >= EVALUATION_TRUTH_MIN_RELEVANT_UPLOADS
        ),
        "relevant_ratio": (
            evidence.relevant_ratio is not None
            and evidence.relevant_ratio >= EVALUATION_TRUTH_MIN_RELEVANT_RATIO
        ),
        "continuity_30d": (
            evidence.relevant_30d_upload_count
            >= EVALUATION_TRUTH_MIN_RELEVANT_30D_UPLOADS
        ),
        "continuity_90d": (
            evidence.relevant_90d_upload_count
            >= EVALUATION_TRUTH_MIN_RELEVANT_90D_UPLOADS
        ),
        "influence": _truth_influence_passes(evidence),
        "not_low_result": category != "low_result",
    }
    excluded_roles = {CreatorTopicRole.AGGREGATOR, CreatorTopicRole.UNRELATED}
    adjacent_roles = {CreatorTopicRole.GENERALIST, CreatorTopicRole.SERVICE}
    core_roles = {
        CreatorTopicRole.SPECIALIST,
        CreatorTopicRole.EDUCATOR,
        CreatorTopicRole.REVIEWER,
        CreatorTopicRole.OFFICIAL,
        CreatorTopicRole.MEDIA,
    }
    if (
        review.human_relevance == AccountTopicRelevance.IRRELEVANT
        or review.human_role in excluded_roles
    ):
        relation = CreatorProductRelation.EXCLUDED
        reasons = ["human_irrelevant_or_excluded_role"]
    elif (
        review.human_relevance == AccountTopicRelevance.UNCERTAIN
        or review.human_specialization == SpecializationLevel.UNKNOWN
    ):
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["human_relation_uncertain"]
    elif review.human_relevance != AccountTopicRelevance.RELEVANT:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["human_relevance_not_relevant"]
    elif (
        review.human_role in adjacent_roles
        or review.human_specialization in {
            SpecializationLevel.LOW,
            SpecializationLevel.MEDIUM,
        }
    ):
        relation = CreatorProductRelation.ADJACENT_BENCHMARK
        reasons = ["human_role_or_specialization_is_adjacent"]
    elif review.human_role not in core_roles:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["human_role_not_core_eligible"]
    elif not checks["decided_sample"] or not checks["influence"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["independent_sample_or_influence_evidence_insufficient"]
    elif not all(
        checks[key]
        for key in [
            "relevant_uploads",
            "relevant_ratio",
            "continuity_30d",
            "continuity_90d",
            "not_low_result",
        ]
    ):
        relation = CreatorProductRelation.OCCASIONAL_HIT
        reasons = ["independent_continuity_or_focus_policy_not_met"]
    else:
        relation = CreatorProductRelation.CORE_COMPETITOR
        reasons = ["human_dimensions_and_independent_evidence_support_core"]
    return CreatorEvaluationTruthV3(
        formula_version=EVALUATION_FORMULA_VERSION_V3,
        keyword_id=review.keyword_id,
        creator_mid=review.creator_mid,
        relation=relation,
        human_relevance=review.human_relevance,
        human_specialization=review.human_specialization,
        human_role=review.human_role,
        objective_checks=checks,
        reasons=reasons,
    )
