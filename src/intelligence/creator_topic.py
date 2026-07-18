"""Deterministic P0-C v2 creator-topic assessment and review routing."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from statistics import median
from typing import Any

from src.intelligence.contracts import (
    MAX_COMPETITORS,
    AccountTopicRelevance,
    BoundaryRisk,
    CreatorProductRelation,
    CreatorSampleStatus,
    CreatorTopicAssessment,
    CreatorTopicEvidence,
    CreatorTopicRole,
    CreatorTopicVideoEvidence,
    HumanCreatorTopicReview,
    ReviewRoutingDecision,
    SpecializationLevel,
    SystemConfidence,
    SystemConfidenceComponent,
    TopicSpec,
)


HIGH_SPECIALIZATION_RATIO = 0.6
HIGH_SPECIALIZATION_MIN_RELEVANT = 5
CORE_SYSTEM_CONFIDENCE_MIN = 0.6
MIN_RELEVANT_UPLOADS = 3
MIN_RELEVANT_90D_UPLOADS = 3
MIN_FOLLOWER_COUNT = 10_000
MIN_RELEVANT_VIEW_MEDIAN = 5_000
HARD_SEMANTIC_RISKS = {"aggregator", "reupload", "course_matrix", "content_farm", "news_repost"}


def topic_spec_from_evaluation_keyword(keyword: Any) -> TopicSpec:
    return TopicSpec(
        keyword_id=keyword.id,
        keyword=keyword.keyword,
        category=keyword.category.value,
        intent_definition=keyword.intent_definition,
        allowed_subtopics=list(keyword.allowed_subtopics),
        exclusion_rules=list(keyword.exclusion_rules),
    )


def minimum_relevant_ratio(topic_spec: TopicSpec, *, generalist: bool | None) -> float | None:
    if topic_spec.category == "low_result":
        return None
    if topic_spec.category == "broad" or generalist is True:
        return 0.2
    return 0.3


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _label_counts(labels: Sequence[Mapping[str, Any]]) -> tuple[int, int, int]:
    relevant = sum(item.get("label") == "relevant" for item in labels)
    irrelevant = sum(item.get("label") == "irrelevant" for item in labels)
    uncertain = sum(item.get("label") == "uncertain" for item in labels)
    return relevant, irrelevant, uncertain


def _evidence_by_id(evidence_items: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["evidence_id"]): item
        for item in evidence_items
        if item.get("evidence_id")
    }


def _video_evidence(
    label: Mapping[str, Any],
    evidence_lookup: Mapping[str, Mapping[str, Any]],
) -> CreatorTopicVideoEvidence:
    evidence_ids = list(dict.fromkeys(str(item) for item in label.get("evidence_ids") or []))
    source = next((evidence_lookup[item] for item in evidence_ids if item in evidence_lookup), {})
    data_fields = source.get("data_fields") or {}
    return CreatorTopicVideoEvidence(
        bvid=str(label["bvid"]),
        title=str(label.get("title") or source.get("title") or ""),
        description=label.get("description"),
        published_at=_parse_datetime(label.get("published_at") or data_fields.get("published_at")),
        view=data_fields.get("view"),
        source_url=str(label.get("source_url") or source.get("source_url") or ""),
        evidence_ids=evidence_ids,
    )


def build_creator_topic_evidence(
    candidate: Mapping[str, Any],
    evidence_items: Sequence[Mapping[str, Any]],
) -> CreatorTopicEvidence:
    sample = candidate.get("creator_sample") or {}
    search_labels = list(candidate.get("search_relevance_labels") or [])
    upload_labels = list(candidate.get("creator_relevance_labels") or [])
    search_relevant, search_irrelevant, search_uncertain = _label_counts(search_labels)
    relevant, irrelevant, uncertain = _label_counts(upload_labels)
    decided = relevant + irrelevant
    relevant_ratio = relevant / decided if decided else None
    observed_at = _parse_datetime(sample.get("observed_at"))
    lookup = _evidence_by_id(evidence_items)
    search_examples = [_video_evidence(item, lookup) for item in search_labels]
    upload_examples = [_video_evidence(item, lookup) for item in upload_labels]
    relevant_examples = [
        evidence
        for label, evidence in zip(upload_labels, upload_examples, strict=True)
        if label.get("label") == "relevant"
    ]
    irrelevant_examples = [
        evidence
        for label, evidence in zip(upload_labels, upload_examples, strict=True)
        if label.get("label") == "irrelevant"
    ]
    relevant_30d = relevant_90d = 0
    if observed_at is not None:
        for evidence in relevant_examples:
            if evidence.published_at is None:
                continue
            age_days = (observed_at - evidence.published_at).total_seconds() / 86400
            if 0 <= age_days <= 90:
                relevant_90d += 1
                if age_days <= 30:
                    relevant_30d += 1
    relevant_views = [item.view for item in relevant_examples if item.view is not None]
    published_count = sum(item.published_at is not None for item in upload_examples)
    evidence_ids = list(dict.fromkeys(
        item
        for label in [*search_labels, *upload_labels]
        for item in (label.get("evidence_ids") or [])
    ))
    source_urls = list(dict.fromkeys(
        item.source_url
        for item in [*search_examples, *upload_examples]
        if item.source_url
    ))
    missing_fields = []
    if sample.get("missing_reason"):
        missing_fields.append(str(sample["missing_reason"]))
    if upload_examples and published_count < len(upload_examples):
        missing_fields.append("published_at")
    if upload_examples and decided < len(upload_examples):
        missing_fields.append("decided_relevance_labels")
    if not sample.get("profile_url"):
        missing_fields.append("profile_url")
    if sample.get("follower_count") is None and not relevant_views:
        missing_fields.append("influence_fields")
    return CreatorTopicEvidence(
        creator_mid=str(candidate["creator_mid"]),
        creator_name=str(candidate.get("creator_name") or ""),
        profile_url=sample.get("profile_url"),
        sample_status=CreatorSampleStatus(sample.get("status", "missing")),
        observed_at=observed_at,
        search_video_count=len(search_labels),
        search_relevant_video_count=search_relevant,
        search_irrelevant_video_count=search_irrelevant,
        search_uncertain_video_count=search_uncertain,
        sampled_upload_count=len(upload_labels),
        decided_upload_count=decided,
        relevant_upload_count=relevant,
        irrelevant_upload_count=irrelevant,
        uncertain_upload_count=uncertain,
        relevant_ratio=relevant_ratio,
        recent_30d_upload_count=int(sample.get("recent_30d_upload_count") or 0),
        recent_90d_upload_count=int(sample.get("recent_90d_upload_count") or 0),
        relevant_30d_upload_count=relevant_30d,
        relevant_90d_upload_count=relevant_90d,
        follower_count=sample.get("follower_count"),
        relevant_view_median=float(median(relevant_views)) if relevant_views else None,
        published_at_completeness=(published_count / len(upload_examples) if upload_examples else 0.0),
        label_coverage=(decided / len(upload_examples) if upload_examples else 0.0),
        sample_coverage=min(len(upload_examples) / 20, 1.0),
        evidence_ids=evidence_ids,
        source_urls=source_urls,
        search_examples=search_examples,
        upload_examples=upload_examples,
        relevant_examples=relevant_examples,
        irrelevant_examples=irrelevant_examples,
        missing_fields=list(dict.fromkeys(missing_fields)),
    )


def _model_confidence(candidate: Mapping[str, Any]) -> float:
    sample_labels = list(candidate.get("creator_relevance_labels") or [])
    search_labels = list(candidate.get("search_relevance_labels") or [])
    confidences = [float(item.get("confidence") or 0) for item in [*search_labels, *sample_labels]]
    assessment_confidence = float((candidate.get("creator_sample") or {}).get("assessment_confidence") or 0)
    if not confidences:
        return 0.0
    return round(min(sum(confidences) / len(confidences), assessment_confidence), 6)


def _initial_dimensions(
    topic_spec: TopicSpec,
    candidate: Mapping[str, Any],
    evidence: CreatorTopicEvidence,
) -> tuple[AccountTopicRelevance, SpecializationLevel, CreatorTopicRole, bool, set[str]]:
    sample = candidate.get("creator_sample") or {}
    generalist = sample.get("generalist")
    risk_flags = set(sample.get("risk_flags") or [])
    hard_risk = bool(risk_flags.intersection(HARD_SEMANTIC_RISKS))
    ratio_min = minimum_relevant_ratio(topic_spec, generalist=generalist)
    sample_available = evidence.sample_status in {CreatorSampleStatus.SUCCESS, CreatorSampleStatus.PARTIAL}

    if hard_risk:
        relevance = AccountTopicRelevance.IRRELEVANT
    elif not sample_available or evidence.decided_upload_count < MIN_RELEVANT_UPLOADS:
        relevance = AccountTopicRelevance.UNCERTAIN
    elif evidence.relevant_upload_count == 0:
        relevance = AccountTopicRelevance.IRRELEVANT
    elif (
        ratio_min is not None
        and evidence.relevant_upload_count >= MIN_RELEVANT_UPLOADS
        and evidence.relevant_90d_upload_count >= MIN_RELEVANT_90D_UPLOADS
        and evidence.relevant_ratio is not None
        and evidence.relevant_ratio >= ratio_min
    ):
        relevance = AccountTopicRelevance.RELEVANT
    else:
        relevance = AccountTopicRelevance.UNCERTAIN

    if not sample_available or evidence.decided_upload_count < MIN_RELEVANT_UPLOADS:
        specialization = SpecializationLevel.UNKNOWN
    elif (
        evidence.relevant_ratio is not None
        and evidence.relevant_ratio >= HIGH_SPECIALIZATION_RATIO
        and evidence.relevant_upload_count >= HIGH_SPECIALIZATION_MIN_RELEVANT
        and evidence.relevant_90d_upload_count >= MIN_RELEVANT_90D_UPLOADS
    ):
        specialization = SpecializationLevel.HIGH
    elif (
        ratio_min is not None
        and evidence.relevant_ratio is not None
        and evidence.relevant_ratio >= ratio_min
        and evidence.relevant_upload_count >= MIN_RELEVANT_UPLOADS
        and evidence.relevant_90d_upload_count >= MIN_RELEVANT_90D_UPLOADS
    ):
        specialization = SpecializationLevel.MEDIUM
    elif evidence.relevant_upload_count > 0 or evidence.decided_upload_count >= MIN_RELEVANT_UPLOADS:
        specialization = SpecializationLevel.LOW
    else:
        specialization = SpecializationLevel.UNKNOWN

    if hard_risk:
        role = CreatorTopicRole.AGGREGATOR
    elif generalist is True:
        role = CreatorTopicRole.GENERALIST
    elif generalist is False:
        role = CreatorTopicRole.SPECIALIST
    else:
        role = CreatorTopicRole.UNKNOWN
    return relevance, specialization, role, hard_risk, risk_flags


def _boundary_risks(
    topic_spec: TopicSpec,
    candidate: Mapping[str, Any],
    evidence: CreatorTopicEvidence,
    relevance: AccountTopicRelevance,
    specialization: SpecializationLevel,
    *,
    hard_risk: bool,
    semantic_risk_flags: set[str],
) -> list[BoundaryRisk]:
    sample = candidate.get("creator_sample") or {}
    ratio_min = minimum_relevant_ratio(topic_spec, generalist=sample.get("generalist"))
    risks: list[BoundaryRisk] = []
    if evidence.search_relevant_video_count == 1 and evidence.relevant_upload_count < MIN_RELEVANT_UPLOADS:
        risks.append(BoundaryRisk.SINGLE_VIDEO_BIAS)
    if evidence.search_relevant_video_count > 0 and evidence.relevant_upload_count == 0:
        risks.append(BoundaryRisk.SEARCH_ONLY_RELEVANCE)
    if (
        "occasional_hit" in semantic_risk_flags
        or 0 < evidence.relevant_upload_count < MIN_RELEVANT_UPLOADS
    ):
        risks.append(BoundaryRisk.OCCASIONAL_HIT)
    if sample.get("generalist") is True or (
        evidence.relevant_upload_count > 0 and evidence.irrelevant_upload_count > 0
    ):
        risks.append(BoundaryRisk.MIXED_CONTENT)
    if evidence.decided_upload_count < MIN_RELEVANT_UPLOADS:
        risks.append(BoundaryRisk.INSUFFICIENT_SAMPLE)
    if evidence.relevant_90d_upload_count < MIN_RELEVANT_90D_UPLOADS:
        risks.append(BoundaryRisk.INSUFFICIENT_90D_CONTINUITY)
    if ratio_min is None or evidence.relevant_ratio is None or evidence.relevant_ratio < ratio_min:
        risks.append(BoundaryRisk.LOW_RELEVANT_RATIO)
    profile_text = str(sample.get("profile_text") or sample.get("profile_description") or "")
    normalized_profile = "".join(profile_text.lower().split())
    normalized_terms = [
        "".join(term.lower().split())
        for term in [topic_spec.keyword, *topic_spec.allowed_subtopics]
        if len("".join(term.split())) >= 2
    ]
    profile_claims_topic = bool(normalized_profile) and any(
        term in normalized_profile for term in normalized_terms
    )
    if profile_claims_topic and relevance != AccountTopicRelevance.RELEVANT:
        risks.append(BoundaryRisk.PROFILE_CONTENT_CONFLICT)
    if hard_risk:
        risks.append(BoundaryRisk.AGGREGATION_OR_REUPLOAD)
    if (
        evidence.sample_status not in {CreatorSampleStatus.SUCCESS, CreatorSampleStatus.PARTIAL}
        or not evidence.evidence_ids
        or evidence.label_coverage < 0.75
        or evidence.published_at_completeness < 0.75
    ):
        risks.append(BoundaryRisk.MISSING_EVIDENCE)
    rule_supports_sustained_relation = (
        relevance == AccountTopicRelevance.RELEVANT
        and specialization in {SpecializationLevel.HIGH, SpecializationLevel.MEDIUM}
    )
    if rule_supports_sustained_relation and semantic_risk_flags.intersection(
        {*HARD_SEMANTIC_RISKS, "occasional_hit"}
    ):
        risks.append(BoundaryRisk.SEMANTIC_RULE_CONFLICT)
    return list(dict.fromkeys(risks))


def _system_confidence(
    topic_spec: TopicSpec,
    candidate: Mapping[str, Any],
    evidence: CreatorTopicEvidence,
    risks: Sequence[BoundaryRisk],
) -> SystemConfidence:
    sample = candidate.get("creator_sample") or {}
    ratio_min = minimum_relevant_ratio(topic_spec, generalist=sample.get("generalist"))
    availability = {
        CreatorSampleStatus.SUCCESS: 1.0,
        CreatorSampleStatus.PARTIAL: 0.75,
    }.get(evidence.sample_status, 0.0)
    ratio_margin = (
        min(abs(evidence.relevant_ratio - ratio_min) / 0.2, 1.0)
        if evidence.relevant_ratio is not None and ratio_min is not None
        else 0.0
    )
    continuity = min(evidence.relevant_90d_upload_count / 3, 1.0) * 0.7 + min(
        evidence.relevant_30d_upload_count / 1, 1.0
    ) * 0.3
    if BoundaryRisk.SEMANTIC_RULE_CONFLICT in risks:
        semantic_agreement = 0.0
    elif sample.get("assessment_confidence") is None:
        semantic_agreement = 0.5
    else:
        semantic_agreement = 1.0
    evidence_checks = [
        bool(evidence.profile_url),
        bool(evidence.evidence_ids),
        bool(evidence.source_urls),
        evidence.follower_count is not None or evidence.relevant_view_median is not None,
    ]
    evidence_completeness = sum(evidence_checks) / len(evidence_checks)
    components = {
        "sample_availability": SystemConfidenceComponent(
            value=availability,
            weight=0.20,
            reason="success=1, partial=0.75, unavailable=0",
        ),
        "video_label_coverage": SystemConfidenceComponent(
            value=evidence.label_coverage,
            weight=0.20,
            reason="decided creator-upload labels / sampled uploads",
        ),
        "upload_sample_coverage": SystemConfidenceComponent(
            value=evidence.sample_coverage,
            weight=0.15,
            reason="sampled uploads / frozen maximum 20",
        ),
        "published_at_completeness": SystemConfidenceComponent(
            value=evidence.published_at_completeness,
            weight=0.10,
            reason="uploads with published_at / sampled uploads",
        ),
        "relevant_ratio_margin": SystemConfidenceComponent(
            value=ratio_margin,
            weight=0.15,
            reason="absolute relevant-ratio distance from the applicable policy threshold, capped at 0.2",
        ),
        "continuity": SystemConfidenceComponent(
            value=continuity,
            weight=0.10,
            reason="70% recent-90d continuity plus 30% recent-30d continuity",
        ),
        "semantic_rule_agreement": SystemConfidenceComponent(
            value=semantic_agreement,
            weight=0.05,
            reason="deterministic agreement state between cached semantic risks and evidence rules",
        ),
        "evidence_completeness": SystemConfidenceComponent(
            value=evidence_completeness,
            weight=0.05,
            reason="profile, Evidence IDs, source URLs, and influence evidence availability",
        ),
    }
    score = round(sum(item.value * item.weight for item in components.values()), 6)
    return SystemConfidence(
        score=score,
        components=components,
        formula="sum(component.value * component.weight); weights total 1.0",
    )


def _influence_passes(evidence: CreatorTopicEvidence) -> bool:
    return (
        evidence.follower_count is not None and evidence.follower_count >= MIN_FOLLOWER_COUNT
    ) or (
        evidence.relevant_view_median is not None
        and evidence.relevant_view_median >= MIN_RELEVANT_VIEW_MEDIAN
    )


def _product_relation(
    *,
    relevance: AccountTopicRelevance,
    specialization: SpecializationLevel,
    role: CreatorTopicRole,
    evidence: CreatorTopicEvidence,
    system_confidence: SystemConfidence,
    risks: Sequence[BoundaryRisk],
) -> CreatorProductRelation:
    hard_risk = (
        BoundaryRisk.AGGREGATION_OR_REUPLOAD in risks
        or role in {CreatorTopicRole.AGGREGATOR, CreatorTopicRole.UNRELATED}
    )
    if relevance == AccountTopicRelevance.IRRELEVANT or hard_risk:
        return CreatorProductRelation.EXCLUDED
    if relevance == AccountTopicRelevance.UNCERTAIN:
        return (
            CreatorProductRelation.OCCASIONAL_HIT
            if evidence.relevant_upload_count > 0 or evidence.search_relevant_video_count > 0
            else CreatorProductRelation.INSUFFICIENT_EVIDENCE
        )
    if (
        system_confidence.score < CORE_SYSTEM_CONFIDENCE_MIN
        or BoundaryRisk.MISSING_EVIDENCE in risks
        or BoundaryRisk.SEMANTIC_RULE_CONFLICT in risks
        or not _influence_passes(evidence)
    ):
        return CreatorProductRelation.INSUFFICIENT_EVIDENCE
    if specialization == SpecializationLevel.LOW or (
        role == CreatorTopicRole.GENERALIST and specialization != SpecializationLevel.HIGH
    ):
        return CreatorProductRelation.ADJACENT_BENCHMARK
    return CreatorProductRelation.CORE_COMPETITOR


def assess_creator_topic(
    topic_spec: TopicSpec,
    candidate: Mapping[str, Any],
    evidence_items: Sequence[Mapping[str, Any]],
) -> CreatorTopicAssessment:
    evidence = build_creator_topic_evidence(candidate, evidence_items)
    relevance, specialization, role, hard_risk, semantic_risk_flags = _initial_dimensions(
        topic_spec,
        candidate,
        evidence,
    )
    risks = _boundary_risks(
        topic_spec,
        candidate,
        evidence,
        relevance,
        specialization,
        hard_risk=hard_risk,
        semantic_risk_flags=semantic_risk_flags,
    )
    system_confidence = _system_confidence(topic_spec, candidate, evidence, risks)
    influence = _influence_passes(evidence)
    relation = _product_relation(
        relevance=relevance,
        specialization=specialization,
        role=role,
        evidence=evidence,
        system_confidence=system_confidence,
        risks=risks,
    )
    rationale = [
        f"relevance={relevance.value}",
        f"specialization={specialization.value}",
        f"role={role.value}",
        f"system_confidence={system_confidence.score:.6f}",
        f"influence_passed={str(influence).lower()}",
    ]
    if risks:
        rationale.append("boundary_risks=" + ",".join(item.value for item in risks))
    return CreatorTopicAssessment(
        keyword_id=topic_spec.keyword_id,
        creator_mid=evidence.creator_mid,
        creator_name=evidence.creator_name,
        relevance=relevance,
        specialization=specialization,
        role=role,
        product_relation=relation,
        model_confidence=_model_confidence(candidate),
        system_confidence=system_confidence,
        boundary_risks=risks,
        evidence=evidence,
        base_score=float(candidate.get("total_score") or 0),
        base_tie_break_values=list(candidate.get("tie_break_values") or []),
        rationale=rationale,
    )


def apply_human_review(
    assessment: CreatorTopicAssessment,
    review: HumanCreatorTopicReview,
) -> CreatorTopicAssessment:
    if not review.review_complete:
        raise ValueError("human review must be complete before overlay")
    if review.keyword_id != assessment.keyword_id or review.creator_mid != assessment.creator_mid:
        raise ValueError(f"human review identity mismatch: {review.review_id}")
    if review.human_relevance is None or review.human_specialization is None or review.human_role is None:
        raise ValueError("completed human review is missing a required dimension")

    resolved_risks = [
        risk
        for risk in assessment.boundary_risks
        if risk not in {BoundaryRisk.SEMANTIC_RULE_CONFLICT, BoundaryRisk.AGGREGATION_OR_REUPLOAD}
        and not (
            risk == BoundaryRisk.PROFILE_CONTENT_CONFLICT
            and review.human_relevance == AccountTopicRelevance.RELEVANT
        )
    ]
    if review.human_role == CreatorTopicRole.AGGREGATOR:
        resolved_risks.append(BoundaryRisk.AGGREGATION_OR_REUPLOAD)
    resolved_risks = list(dict.fromkeys(resolved_risks))
    relation = _product_relation(
        relevance=review.human_relevance,
        specialization=review.human_specialization,
        role=review.human_role,
        evidence=assessment.evidence,
        system_confidence=assessment.system_confidence,
        risks=resolved_risks,
    )
    return assessment.model_copy(update={
        "relevance": review.human_relevance,
        "specialization": review.human_specialization,
        "role": review.human_role,
        "product_relation": relation,
        "boundary_risks": resolved_risks,
        "selected": False,
        "selection_rank": None,
        "rationale": [
            *assessment.rationale,
            f"human_review_id={review.review_id}",
            f"human_relevance={review.human_relevance.value}",
            f"human_specialization={review.human_specialization.value}",
            f"human_role={review.human_role.value}",
            f"human_reason={review.human_reason.strip()}",
        ],
    })


def _selection_key(assessment: CreatorTopicAssessment) -> tuple[Any, ...]:
    tie = assessment.base_tie_break_values
    search_relevant = int(tie[2]) if len(tie) > 2 else assessment.evidence.search_relevant_video_count
    relevant_90d = int(tie[3]) if len(tie) > 3 else assessment.evidence.relevant_90d_upload_count
    best_position = int(tie[4]) if len(tie) > 4 else 999_999
    return (
        -assessment.base_score,
        -assessment.system_confidence.score,
        -search_relevant,
        -relevant_90d,
        best_position,
        assessment.creator_mid,
    )


def _select_top_competitors(
    assessments: Sequence[CreatorTopicAssessment],
    *,
    preferred_mids: set[str],
) -> list[CreatorTopicAssessment]:
    ordered = sorted(
        assessments,
        key=lambda item: (
            0 if item.creator_mid in preferred_mids else 1,
            *_selection_key(item),
        ),
    )
    selected_mids = {
        item.creator_mid: rank
        for rank, item in enumerate(
            (item for item in ordered if item.product_relation == CreatorProductRelation.CORE_COMPETITOR),
            1,
        )
        if rank <= MAX_COMPETITORS
    }
    return [
        item.model_copy(update={
            "selected": item.creator_mid in selected_mids,
            "selection_rank": selected_mids.get(item.creator_mid),
        })
        for item in ordered
    ]


def select_v2_top_competitors(
    assessments: Sequence[CreatorTopicAssessment],
) -> list[CreatorTopicAssessment]:
    """Select the unbiased system Top 5 without human-label preferences."""
    return _select_top_competitors(assessments, preferred_mids=set())


def select_hitl_assisted_top_competitors(
    assessments: Sequence[CreatorTopicAssessment],
    *,
    preferred_mids: set[str],
) -> list[CreatorTopicAssessment]:
    """Select a product-assistance Top 5 that may use explicit human preferences."""
    return _select_top_competitors(assessments, preferred_mids=preferred_mids)


def review_id(keyword_id: str, creator_mid: str) -> str:
    digest = hashlib.sha256(f"{keyword_id}|{creator_mid}".encode("utf-8")).hexdigest()[:16]
    return f"review_{digest}"


def route_keyword_reviews(
    assessments: Sequence[CreatorTopicAssessment],
    *,
    v1_selected_mids: set[str],
    frozen_human_status: Mapping[str, str],
) -> list[ReviewRoutingDecision]:
    by_mid = {item.creator_mid: item for item in assessments}
    v2_selected_mids = {item.creator_mid for item in assessments if item.selected}
    false_negative_mid = next((
        item.creator_mid
        for item in sorted(assessments, key=_selection_key)
        if not item.selected
        and item.product_relation not in {CreatorProductRelation.EXCLUDED, CreatorProductRelation.INSUFFICIENT_EVIDENCE}
        and item.creator_mid not in frozen_human_status
    ), None)
    routes = []
    for mid, assessment in by_mid.items():
        existing_human = mid in frozen_human_status
        reasons = []
        priority = None
        if not existing_human and mid in v2_selected_mids:
            priority = 1
            reasons.append("provisional_v2_selected_without_frozen_human_label")
        if not existing_human and mid in v1_selected_mids:
            if priority is None or priority > 2:
                priority = 2
            reasons.append("v1_unresolved_selected_position")
        if not existing_human and ((mid in v1_selected_mids) != (mid in v2_selected_mids)):
            if priority is None or priority > 3:
                priority = 3
            reasons.append("v1_v2_selection_conflict")
        if not existing_human and BoundaryRisk.SEMANTIC_RULE_CONFLICT in assessment.boundary_risks:
            if priority is None or priority > 4:
                priority = 4
            reasons.append("semantic_rule_conflict")
        if not existing_human and mid == false_negative_mid:
            if priority is None or priority > 5:
                priority = 5
            reasons.append("sampled_high_score_unselected_false_negative_audit")
        requires = priority is not None
        routes.append(ReviewRoutingDecision(
            review_id=review_id(assessment.keyword_id, assessment.creator_mid),
            keyword_id=assessment.keyword_id,
            creator_mid=assessment.creator_mid,
            requires_human_review=requires,
            priority=priority,
            reasons=list(dict.fromkeys(reasons)),
            include_in_blind_workbook=requires and not existing_human,
            existing_human_label=existing_human,
        ))
    return routes


def validate_human_review_rows(
    rows: Sequence[Mapping[str, Any]],
    expected_routes: Sequence[ReviewRoutingDecision],
) -> list[HumanCreatorTopicReview]:
    expected = {
        route.review_id: route
        for route in expected_routes
        if route.include_in_blind_workbook
    }
    if len(expected) != len([route for route in expected_routes if route.include_in_blind_workbook]):
        raise ValueError("expected review routes contain duplicate review_id values")
    seen: set[str] = set()
    reviews = []
    for row in rows:
        review = HumanCreatorTopicReview.model_validate(row)
        if review.review_id in seen:
            raise ValueError(f"duplicate review_id: {review.review_id}")
        seen.add(review.review_id)
        route = expected.get(review.review_id)
        if route is None:
            raise ValueError(f"unexpected review_id: {review.review_id}")
        if route.keyword_id != review.keyword_id or route.creator_mid != review.creator_mid:
            raise ValueError(f"review identity mismatch: {review.review_id}")
        reviews.append(review)
    missing = sorted(set(expected) - seen)
    if missing:
        raise ValueError(f"missing review_id values: {len(missing)}")
    incomplete = [review.review_id for review in reviews if not review.review_complete]
    if incomplete:
        raise ValueError(f"incomplete human reviews: {len(incomplete)}")
    return reviews
