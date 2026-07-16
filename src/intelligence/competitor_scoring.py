"""Deterministic P0-C competitor qualification, scoring, and Top 5 selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from src.intelligence.contracts import (
    MAX_COMPETITORS,
    SCORING_VERSION,
    CompetitorScore,
    CreatorQualificationStatus,
    CreatorSample,
    CreatorSampleStatus,
    CreatorSemanticAssessment,
    RelevanceDecision,
    RelevanceLabel,
    ScoreComponent,
    Video,
)
from src.intelligence.relevance import RelevanceContext


COMPONENT_WEIGHTS = {
    "search_relevant_video_count": 20.0,
    "recent_relevant_ratio": 20.0,
    "semantic_relevance": 20.0,
    "activity_and_frequency": 15.0,
    "interaction_performance": 10.0,
    "content_focus": 10.0,
    "sample_sufficiency": 5.0,
}
PENALTY_CAP = 20.0
MAX_CREATOR_AUDITS = 20
INITIAL_CREATOR_AUDIT_BATCH = 8
CREATOR_AUDIT_BATCH_SIZE = 4
MIN_RELEVANT_VIDEOS = 3
MIN_RECENT_90D_RELEVANT_VIDEOS = 3
MIN_FOLLOWER_COUNT = 10_000
MIN_RELEVANT_VIEW_MEDIAN = 5_000
INTERACTION_PROXY_TARGET = 0.08
TIE_BREAK_VERSION = "competitor-tie-break.p0.1"


@dataclass(slots=True)
class CandidateCreator:
    creator_mid: str
    creator_name: str
    search_videos: list[Video] = field(default_factory=list)

    @property
    def best_search_position(self) -> int:
        return min(video.source_page * 1000 + video.source_rank for video in self.search_videos)


@dataclass(slots=True)
class ScoringInput:
    candidate: CandidateCreator
    creator_sample: CreatorSample
    search_decisions: list[RelevanceDecision]
    sample_decisions: list[RelevanceDecision]
    assessment: CreatorSemanticAssessment
    search_evidence_ids: list[str]
    sample_evidence_ids: list[str]


@dataclass(slots=True)
class QualificationOutcome:
    status: CreatorQualificationStatus
    reason: str


def aggregate_candidates(videos: Sequence[Video]) -> list[CandidateCreator]:
    by_mid: dict[str, CandidateCreator] = {}
    for video in videos:
        if not video.creator_mid:
            continue
        candidate = by_mid.setdefault(
            video.creator_mid,
            CandidateCreator(video.creator_mid, video.creator_name or ""),
        )
        if not candidate.creator_name and video.creator_name:
            candidate.creator_name = video.creator_name
        candidate.search_videos.append(video)
    for candidate in by_mid.values():
        candidate.search_videos.sort(key=lambda video: (video.source_page, video.source_rank, video.bvid))
    return sorted(by_mid.values(), key=lambda candidate: candidate.creator_mid)


def rank_creator_audits(candidates: Sequence[CandidateCreator], context: RelevanceContext) -> list[CandidateCreator]:
    terms = [context.keyword, *context.allowed_subtopics]
    normalized_terms = ["".join(term.lower().split()) for term in terms if len("".join(term.split())) >= 2]

    def exact_hits(candidate: CandidateCreator) -> int:
        hits = 0
        for video in candidate.search_videos:
            text = "".join(" ".join([video.title, video.description or "", " ".join(video.tags)]).lower().split())
            if any(term in text for term in normalized_terms):
                hits += 1
        return hits

    def max_view(candidate: CandidateCreator) -> int:
        return max((video.view or -1 for video in candidate.search_videos), default=-1)

    return sorted(
        candidates,
        key=lambda candidate: (
            -exact_hits(candidate),
            -len(candidate.search_videos),
            candidate.best_search_position,
            -max_view(candidate),
            candidate.creator_mid,
        ),
    )


def _component(
    score: float,
    max_score: float,
    *,
    numerator: float | None,
    denominator: float | None,
    sample_size: int,
    formula: str,
    missing_reason: str | None = None,
) -> ScoreComponent:
    return ScoreComponent(
        score=round(max(0.0, min(score, max_score)), 6),
        max_score=max_score,
        numerator=numerator,
        denominator=denominator,
        sample_size=sample_size,
        formula=formula,
        missing_reason=missing_reason,
    )


def _decisions_by_bvid(decisions: Sequence[RelevanceDecision]) -> dict[str, RelevanceDecision]:
    return {decision.bvid: decision for decision in decisions}


def _relevance_probability(decision: RelevanceDecision) -> float:
    if decision.label == RelevanceLabel.RELEVANT:
        return decision.confidence
    if decision.label == RelevanceLabel.IRRELEVANT:
        return 1.0 - decision.confidence
    return 0.5


def _decided_counts(decisions: Sequence[RelevanceDecision]) -> tuple[int, int, int]:
    relevant = sum(decision.label == RelevanceLabel.RELEVANT for decision in decisions)
    irrelevant = sum(decision.label == RelevanceLabel.IRRELEVANT for decision in decisions)
    uncertain = sum(decision.label == RelevanceLabel.UNCERTAIN for decision in decisions)
    return relevant, irrelevant, uncertain


def _interaction_proxy(videos: Sequence[Video | object]) -> tuple[float | None, int]:
    values: list[float] = []
    for video in videos:
        required = (video.like, video.favorite, video.reply, video.danmaku)
        if video.view is None or video.view <= 0 or any(value is None for value in required):
            continue
        values.append(sum(required) / video.view)
    return (float(median(values)), len(values)) if values else (None, 0)


def _relevant_view_median(sample: CreatorSample, decisions: Sequence[RelevanceDecision]) -> float | None:
    labels = _decisions_by_bvid(decisions)
    views = [
        video.view
        for video in sample.uploads
        if video.view is not None
        and labels.get(video.bvid)
        and labels[video.bvid].label == RelevanceLabel.RELEVANT
    ]
    return float(median(views)) if views else None


def _recent_relevant_counts(sample: CreatorSample, decisions: Sequence[RelevanceDecision]) -> tuple[int, int]:
    labels = _decisions_by_bvid(decisions)
    relevant_30d = relevant_90d = 0
    for video in sample.uploads:
        decision = labels.get(video.bvid)
        if not decision or decision.label != RelevanceLabel.RELEVANT or video.published_at is None:
            continue
        age_days = (sample.observed_at - video.published_at).total_seconds() / 86400
        if 0 <= age_days <= 90:
            relevant_90d += 1
            if age_days <= 30:
                relevant_30d += 1
    return relevant_30d, relevant_90d


def qualify_creator(scoring_input: ScoringInput, context: RelevanceContext) -> QualificationOutcome:
    sample = scoring_input.creator_sample
    assessment = scoring_input.assessment
    relevant, irrelevant, uncertain = _decided_counts(scoring_input.sample_decisions)
    decided = relevant + irrelevant
    relevant_ratio = relevant / decided if decided else None
    _, recent_90d_relevant = _recent_relevant_counts(sample, scoring_input.sample_decisions)
    published_count = sum(video.published_at is not None for video in sample.uploads)
    hard_risks = {"aggregator", "reupload", "course_matrix", "content_farm", "news_repost"}

    if context.category == "low_result":
        return QualificationOutcome(
            CreatorQualificationStatus.DISCOVERY_ONLY,
            "low_result requires a separately versioned qualification policy",
        )
    if sample.status in {
        CreatorSampleStatus.MISSING,
        CreatorSampleStatus.FAILED,
        CreatorSampleStatus.TIMEOUT,
        CreatorSampleStatus.CANCELLED,
    } or not sample.uploads:
        return QualificationOutcome(CreatorQualificationStatus.DISCOVERY_ONLY, "creator upload sample is unavailable")
    if decided < MIN_RELEVANT_VIDEOS or published_count < MIN_RELEVANT_VIDEOS:
        return QualificationOutcome(CreatorQualificationStatus.DISCOVERY_ONLY, "creator sample is insufficient for qualification")
    if assessment.confidence < 0.55:
        return QualificationOutcome(CreatorQualificationStatus.DISCOVERY_ONLY, "semantic assessment confidence is insufficient")
    if hard_risks.intersection(assessment.risk_flags):
        return QualificationOutcome(CreatorQualificationStatus.EXCLUDED, "creator semantic audit found aggregation or matrix risk")
    minimum_ratio = 0.2 if context.category == "broad" or assessment.generalist is True else 0.3
    if relevant < MIN_RELEVANT_VIDEOS:
        return QualificationOutcome(CreatorQualificationStatus.EXCLUDED, "fewer than three audited uploads are relevant")
    if recent_90d_relevant < MIN_RECENT_90D_RELEVANT_VIDEOS:
        return QualificationOutcome(CreatorQualificationStatus.EXCLUDED, "fewer than three relevant uploads were observed in 90 days")
    if relevant_ratio is None or relevant_ratio < minimum_ratio:
        return QualificationOutcome(CreatorQualificationStatus.EXCLUDED, "audited relevant-content ratio is below policy")
    view_median = _relevant_view_median(sample, scoring_input.sample_decisions)
    influence = (
        sample.follower_count is not None and sample.follower_count >= MIN_FOLLOWER_COUNT
    ) or (
        view_median is not None and view_median >= MIN_RELEVANT_VIEW_MEDIAN
    )
    if influence:
        return QualificationOutcome(CreatorQualificationStatus.QUALIFIED_REFERENCE, "continuity and influence policy passed")
    return QualificationOutcome(CreatorQualificationStatus.EMERGING_CANDIDATE, "continuity passed but influence threshold did not")


def score_creator(scoring_input: ScoringInput, context: RelevanceContext) -> CompetitorScore:
    candidate = scoring_input.candidate
    sample = scoring_input.creator_sample
    search_relevant, _, _ = _decided_counts(scoring_input.search_decisions)
    sample_relevant, sample_irrelevant, sample_uncertain = _decided_counts(scoring_input.sample_decisions)
    sample_decided = sample_relevant + sample_irrelevant
    sample_ratio = sample_relevant / sample_decided if sample_decided else None
    all_decisions = [*scoring_input.search_decisions, *scoring_input.sample_decisions]
    probabilities = [_relevance_probability(decision) for decision in all_decisions]
    semantic_value = sum(probabilities) / len(probabilities) if probabilities else None
    relevant_30d, relevant_90d = _recent_relevant_counts(sample, scoring_input.sample_decisions)
    interaction_value, interaction_sample_size = _interaction_proxy([*candidate.search_videos, *sample.uploads])

    details = {
        "search_relevant_video_count": _component(
            min(search_relevant / 3, 1.0) * 20,
            20,
            numerator=float(search_relevant),
            denominator=3.0,
            sample_size=len(scoring_input.search_decisions),
            formula="min(relevant_search_videos / 3, 1) * 20",
            missing_reason="no semantic search labels" if not scoring_input.search_decisions else None,
        ),
        "recent_relevant_ratio": _component(
            (sample_ratio or 0.0) * 20,
            20,
            numerator=float(sample_relevant) if sample_decided else None,
            denominator=float(sample_decided) if sample_decided else None,
            sample_size=sample_relevant + sample_irrelevant + sample_uncertain,
            formula="relevant / (relevant + irrelevant) * 20; uncertain excluded from denominator",
            missing_reason="no decided creator-upload labels" if sample_ratio is None else None,
        ),
        "semantic_relevance": _component(
            (semantic_value or 0.0) * 20,
            20,
            numerator=sum(probabilities) if probabilities else None,
            denominator=float(len(probabilities)) if probabilities else None,
            sample_size=len(probabilities),
            formula="mean(relevant=confidence, irrelevant=1-confidence, uncertain=0.5) * 20",
            missing_reason="no relevance decisions" if semantic_value is None else None,
        ),
        "activity_and_frequency": _component(
            min(relevant_30d / 4, 1.0) * 8 + min(relevant_90d / 8, 1.0) * 7,
            15,
            numerator=float(relevant_30d + relevant_90d),
            denominator=12.0,
            sample_size=len(sample.uploads),
            formula="min(relevant_30d/4,1)*8 + min(relevant_90d/8,1)*7",
            missing_reason="creator upload list is unavailable" if not sample.uploads else None,
        ),
        "interaction_performance": _component(
            min((interaction_value or 0.0) / INTERACTION_PROXY_TARGET, 1.0) * 10,
            10,
            numerator=interaction_value,
            denominator=INTERACTION_PROXY_TARGET if interaction_value is not None else None,
            sample_size=interaction_sample_size,
            formula="min(median((like+favorite+reply+danmaku)/view) / 0.08, 1) * 10",
            missing_reason="no video has complete observable interaction proxy fields" if interaction_value is None else None,
        ),
        "content_focus": _component(
            (sample_ratio or 0.0) * 10,
            10,
            numerator=float(sample_relevant) if sample_decided else None,
            denominator=float(sample_decided) if sample_decided else None,
            sample_size=sample_relevant + sample_irrelevant + sample_uncertain,
            formula="relevant / (relevant + irrelevant) * 10; uncertain excluded from denominator",
            missing_reason="no decided creator-upload labels" if sample_ratio is None else None,
        ),
        "sample_sufficiency": _component(
            min(sample_decided / 10, 1.0) * 5,
            5,
            numerator=float(sample_decided),
            denominator=10.0,
            sample_size=len(sample.uploads),
            formula="min(decided_creator_uploads / 10, 1) * 5",
            missing_reason="no decided creator-upload labels" if sample_decided == 0 else None,
        ),
    }

    penalties: dict[str, float] = {}

    def add_penalty(name: str, value: float) -> None:
        remaining = PENALTY_CAP - sum(penalties.values())
        applied = min(max(value, 0.0), remaining)
        if applied > 0:
            penalties[name] = round(applied, 6)

    if search_relevant == 1 and relevant_90d < MIN_RECENT_90D_RELEVANT_VIDEOS:
        add_penalty("single_hit_without_continuity", 5)
    if sample.uploads and relevant_90d == 0:
        add_penalty("inactive_90d", 5)
    elif sample.uploads and relevant_90d < MIN_RECENT_90D_RELEVANT_VIDEOS:
        add_penalty("weak_90d_continuity", 2)
    if sample_decided < 3:
        add_penalty("insufficient_sample", 4)
    elif sample_decided < 5:
        add_penalty("small_sample", 2)
    if sample.status in {
        CreatorSampleStatus.MISSING,
        CreatorSampleStatus.FAILED,
        CreatorSampleStatus.TIMEOUT,
        CreatorSampleStatus.CANCELLED,
    }:
        add_penalty("missing_upload_list", 5)
    elif sample.status == CreatorSampleStatus.PARTIAL:
        add_penalty("partial_upload_list", 2 if not sample.uploads else 1)
    missing_published = sum(video.published_at is None for video in sample.uploads)
    if sample.uploads and missing_published / len(sample.uploads) >= 0.5:
        add_penalty("missing_publish_time", 1)
    if interaction_value is None:
        add_penalty("missing_interaction_fields", 2)
    if sample.follower_count is None and _relevant_view_median(sample, scoring_input.sample_decisions) is None:
        add_penalty("missing_influence_fields", 1)
    hard_risk_count = len({"aggregator", "reupload", "course_matrix", "content_farm", "news_repost"}.intersection(scoring_input.assessment.risk_flags))
    if hard_risk_count:
        add_penalty("aggregation_or_matrix_risk", 4)
    elif "occasional_hit" in scoring_input.assessment.risk_flags:
        add_penalty("occasional_hit_risk", 3)
    decision_confidences = [decision.confidence for decision in all_decisions]
    mean_decision_confidence = sum(decision_confidences) / len(decision_confidences) if decision_confidences else 0.0
    semantic_confidence = min(mean_decision_confidence, scoring_input.assessment.confidence)
    if semantic_confidence < 0.55:
        add_penalty("semantic_confidence_low", 3)
    elif semantic_confidence < 0.7:
        add_penalty("semantic_confidence_medium", 1.5)

    qualification = qualify_creator(scoring_input, context)
    positive_score = sum(component.score for component in details.values())
    total_score = round(max(0.0, min(100.0, positive_score - sum(penalties.values()))), 6)
    available_status = {
        CreatorSampleStatus.SUCCESS: 1.0,
        CreatorSampleStatus.PARTIAL: 0.6,
    }.get(sample.status, 0.0)
    label_coverage = (
        (sample_relevant + sample_irrelevant) / len(sample.uploads)
        if sample.uploads else 0.0
    )
    sample_coverage = min(len(sample.uploads) / 20, 1.0)
    field_checks = [
        sample.follower_count is not None,
        bool(sample.uploads) and all(video.published_at is not None for video in sample.uploads),
        interaction_value is not None,
        _relevant_view_median(sample, scoring_input.sample_decisions) is not None,
    ]
    field_completeness = sum(field_checks) / len(field_checks)
    confidence = round(max(0.0, min(1.0,
        available_status * 0.25
        + label_coverage * 0.25
        + sample_coverage * 0.20
        + field_completeness * 0.15
        + semantic_confidence * 0.15
    )), 6)
    evidence_ids = list(dict.fromkeys([*scoring_input.search_evidence_ids, *scoring_input.sample_evidence_ids]))
    component_scores = {name: component.score for name, component in details.items()}
    return CompetitorScore(
        scoring_version=SCORING_VERSION,
        creator_mid=candidate.creator_mid,
        creator_name=candidate.creator_name,
        component_scores=component_scores,
        component_details=details,
        penalty_scores=penalties,
        total_score=total_score,
        confidence=confidence,
        qualification_status=qualification.status,
        selected=False,
        exclusion_reason=qualification.reason,
        evidence_ids=evidence_ids,
        search_candidate_sources=[video.source_url for video in candidate.search_videos],
        creator_sample_sources=[video.source_url for video in sample.uploads] or [sample.source_url],
        tie_break_values=[
            total_score,
            confidence,
            search_relevant,
            relevant_90d,
            candidate.best_search_position,
            candidate.creator_mid,
        ],
    )


def _sort_key(score: CompetitorScore) -> tuple:
    total, confidence, search_relevant, recent_90d, best_position, creator_mid = score.tie_break_values
    return (-float(total), -float(confidence), -int(search_relevant), -int(recent_90d), int(best_position), str(creator_mid))


def select_top_competitors(scores: Sequence[CompetitorScore]) -> tuple[list[CompetitorScore], str | None]:
    ordered = sorted(scores, key=_sort_key)
    qualified = [
        score for score in ordered
        if score.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE
    ][:MAX_COMPETITORS]
    ranks = {score.creator_mid: rank for rank, score in enumerate(qualified, 1)}
    result = []
    for score in ordered:
        rank = ranks.get(score.creator_mid)
        if rank is not None:
            result.append(score.model_copy(update={
                "selected": True,
                "selection_rank": rank,
                "inclusion_reason": "qualified_reference selected by deterministic score and tie-break",
                "exclusion_reason": None,
            }))
        else:
            result.append(score)
    shortfall = None
    if len(qualified) < MAX_COMPETITORS:
        shortfall = f"only {len(qualified)} qualified_reference creators were available; weak candidates were not used as filler"
    return result, shortfall
