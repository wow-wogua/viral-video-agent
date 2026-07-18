from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.intelligence.contracts import (
    AccountTopicRelevance,
    BoundaryRisk,
    CreatorProductRelation,
    CreatorTopicRole,
    HumanCreatorTopicReview,
    SpecializationLevel,
    SystemConfidence,
    SystemConfidenceComponent,
    TopicSpec,
)
from src.intelligence.creator_topic import (
    apply_human_review,
    assess_creator_topic,
    route_keyword_reviews,
    select_v2_top_competitors,
    validate_human_review_rows,
)


NOW = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
TOPIC = TopicSpec(
    keyword_id="sanitized-keyword",
    keyword="sanitized topic",
    category="vertical",
    intent_definition="sustained sanitized-topic publishing",
    allowed_subtopics=["sanitized subtopic"],
    exclusion_rules=["exclude unrelated reposts"],
)


def candidate(
    mid: str = "90001",
    *,
    relevant: int = 6,
    irrelevant: int = 4,
    days: int = 10,
    generalist: bool | None = False,
    risk_flags: list[str] | None = None,
    status: str = "success",
    follower_count: int | None = 20_000,
    sample_count: int = 10,
    include_assessment_fields: bool = True,
    score: float = 80,
) -> tuple[dict, list[dict]]:
    uploads = []
    evidence = []
    for index in range(sample_count):
        bvid = f"BV{int(mid) + index:010d}"
        label = "relevant" if index < relevant else "irrelevant" if index < relevant + irrelevant else "uncertain"
        published_at = NOW - timedelta(days=days + index)
        evidence_id = f"ev_upload_{mid}_{index}"
        uploads.append({
            "bvid": bvid,
            "title": f"sanitized upload {index}",
            "source_url": f"https://example.test/video/{bvid}",
            "published_at": published_at.isoformat(),
            "label": label,
            "reason": "cached semantic label",
            "confidence": 0.9,
            "evidence_ids": [evidence_id],
            "labeler": "llm",
            "labeler_version": "content-relevance.p0.1",
        })
        evidence.append({
            "evidence_id": evidence_id,
            "title": f"sanitized upload {index}",
            "source_url": f"https://example.test/video/{bvid}",
            "data_fields": {"view": 10_000 + index, "published_at": published_at.isoformat()},
        })
    search_labels = []
    for index in range(3):
        bvid = f"BV{70_000 + index:010d}"
        evidence_id = f"ev_search_{mid}_{index}"
        search_labels.append({
            "bvid": bvid,
            "title": f"sanitized search {index}",
            "source_url": f"https://example.test/search/{bvid}",
            "published_at": (NOW - timedelta(days=index)).isoformat(),
            "label": "relevant",
            "reason": "cached semantic label",
            "confidence": 0.9,
            "evidence_ids": [evidence_id],
            "labeler": "llm",
            "labeler_version": "content-relevance.p0.1",
        })
        evidence.append({
            "evidence_id": evidence_id,
            "title": f"sanitized search {index}",
            "source_url": f"https://example.test/search/{bvid}",
            "data_fields": {"view": 5_000 + index, "published_at": NOW.isoformat()},
        })
    sample = {
        "status": status,
        "profile_url": f"https://example.test/creator/{mid}",
        "observed_at": NOW.isoformat(),
        "provider_name": "import",
        "provider_version": "import-creator.p0-c.2",
        "follower_count": follower_count,
        "sample_count": sample_count,
        "recent_30d_upload_count": sum(days + index <= 30 for index in range(sample_count)),
        "recent_90d_upload_count": sum(days + index <= 90 for index in range(sample_count)),
        "missing_reason": None if status == "success" else "fixture missing",
    }
    if include_assessment_fields:
        sample.update({
            "generalist": generalist,
            "risk_flags": risk_flags or [],
            "assessment_reason": "cached semantic assessment",
            "assessment_confidence": 0.9,
        })
    return {
        "creator_mid": mid,
        "creator_name": f"creator-{mid}",
        "total_score": score,
        "confidence": 0.8,
        "tie_break_values": [score, 0.8, 3, relevant, 1, mid],
        "creator_sample": sample,
        "search_relevance_labels": search_labels,
        "creator_relevance_labels": uploads,
    }, evidence


def test_topic_spec_is_versioned_and_forbids_unknown_fields():
    assert TOPIC.version == "topic-spec.p0.1"
    with pytest.raises(ValidationError):
        TopicSpec.model_validate({**TOPIC.model_dump(), "unknown": True})


def test_sustained_specialist_becomes_core_with_separate_confidences():
    payload, evidence = candidate()
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert assessment.relevance == AccountTopicRelevance.RELEVANT
    assert assessment.specialization == SpecializationLevel.HIGH
    assert assessment.role == CreatorTopicRole.SPECIALIST
    assert assessment.product_relation == CreatorProductRelation.CORE_COMPETITOR
    assert assessment.base_scoring_version == "competitor-score.p0.1"
    assert assessment.selection_version == "competitor-selection.p0.2"
    assert assessment.model_confidence == 0.9
    assert assessment.system_confidence.score != assessment.model_confidence


def test_relevant_low_specialization_is_a_valid_independent_human_combination():
    review = HumanCreatorTopicReview(
        review_id="review_1234567890abcdef",
        keyword_id="sanitized-keyword",
        creator_mid="90001",
        human_relevance="relevant",
        human_specialization="low",
        human_role="generalist",
        human_reason="relevant but only a small share of the account",
        review_complete=True,
    )
    assert review.human_relevance == AccountTopicRelevance.RELEVANT
    assert review.human_specialization == SpecializationLevel.LOW


def test_human_review_overlay_recomputes_product_relation_and_clears_selection():
    payload, evidence = candidate(relevant=7, irrelevant=3, generalist=False)
    assessment = select_v2_top_competitors([
        assess_creator_topic(TOPIC, payload, evidence),
    ])[0]
    assert assessment.selected
    review = HumanCreatorTopicReview(
        review_id="review_1234567890abcdef",
        keyword_id=assessment.keyword_id,
        creator_mid=assessment.creator_mid,
        human_relevance="relevant",
        human_specialization="low",
        human_role="generalist",
        human_reason="relevant but not sufficiently specialized for core selection",
        review_complete=True,
    )

    overlaid = apply_human_review(assessment, review)

    assert overlaid.relevance == AccountTopicRelevance.RELEVANT
    assert overlaid.specialization == SpecializationLevel.LOW
    assert overlaid.role == CreatorTopicRole.GENERALIST
    assert overlaid.product_relation == CreatorProductRelation.ADJACENT_BENCHMARK
    assert not overlaid.selected
    assert overlaid.selection_rank is None


def test_human_aggregator_role_preserves_hard_exclusion():
    payload, evidence = candidate(relevant=6, irrelevant=1, generalist=False)
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    review = HumanCreatorTopicReview(
        review_id="review_1234567890abcdef",
        keyword_id=assessment.keyword_id,
        creator_mid=assessment.creator_mid,
        human_relevance="relevant",
        human_specialization="high",
        human_role="aggregator",
        human_reason="the account primarily aggregates or republishes material",
        review_complete=True,
    )

    overlaid = apply_human_review(assessment, review)

    assert overlaid.product_relation == CreatorProductRelation.EXCLUDED
    assert BoundaryRisk.AGGREGATION_OR_REUPLOAD in overlaid.boundary_risks


def test_generalist_with_sustained_medium_focus_is_adjacent_not_core():
    payload, evidence = candidate(relevant=4, irrelevant=6, generalist=True)
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert assessment.relevance == AccountTopicRelevance.RELEVANT
    assert assessment.specialization == SpecializationLevel.MEDIUM
    assert assessment.role == CreatorTopicRole.GENERALIST
    assert assessment.product_relation == CreatorProductRelation.ADJACENT_BENCHMARK
    selected = select_v2_top_competitors([assessment])
    assert not selected[0].selected


def test_single_video_search_only_and_small_samples_are_not_upgraded():
    payload, evidence = candidate(relevant=0, irrelevant=1, sample_count=1)
    payload["search_relevance_labels"] = payload["search_relevance_labels"][:1]
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert assessment.product_relation != CreatorProductRelation.CORE_COMPETITOR
    assert BoundaryRisk.SINGLE_VIDEO_BIAS in assessment.boundary_risks
    assert BoundaryRisk.SEARCH_ONLY_RELEVANCE in assessment.boundary_risks
    assert BoundaryRisk.INSUFFICIENT_SAMPLE in assessment.boundary_risks


def test_mixed_content_and_missing_90d_continuity_are_explicit():
    payload, evidence = candidate(relevant=3, irrelevant=7, days=120, generalist=True)
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert BoundaryRisk.MIXED_CONTENT in assessment.boundary_risks
    assert BoundaryRisk.INSUFFICIENT_90D_CONTINUITY in assessment.boundary_risks
    assert assessment.product_relation == CreatorProductRelation.OCCASIONAL_HIT


def test_profile_topic_claim_conflicting_with_content_is_explicit():
    payload, evidence = candidate(relevant=1, irrelevant=9)
    payload["creator_sample"]["profile_description"] = "sanitized topic specialist"
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert BoundaryRisk.PROFILE_CONTENT_CONFLICT in assessment.boundary_risks


def test_cached_semantic_risk_conflict_downgrades_instead_of_upgrading():
    payload, evidence = candidate(risk_flags=["occasional_hit"])
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert BoundaryRisk.SEMANTIC_RULE_CONFLICT in assessment.boundary_risks
    assert assessment.product_relation == CreatorProductRelation.INSUFFICIENT_EVIDENCE


def test_old_cache_shape_without_new_fields_remains_compatible():
    payload, evidence = candidate(include_assessment_fields=False)
    assessment = assess_creator_topic(TOPIC, payload, evidence)
    assert assessment.role == CreatorTopicRole.UNKNOWN
    assert assessment.model_confidence == 0


def test_system_confidence_requires_exact_weighted_formula():
    components = {
        "one": SystemConfidenceComponent(value=1, weight=0.5, reason="fixture"),
        "two": SystemConfidenceComponent(value=0, weight=0.5, reason="fixture"),
    }
    assert SystemConfidence(score=0.5, components=components, formula="fixture").score == 0.5
    with pytest.raises(ValidationError):
        SystemConfidence(score=0.6, components=components, formula="fixture")


def test_v2_top5_only_uses_core_is_unpadded_and_input_order_stable():
    core_a_payload, core_a_evidence = candidate("90001", score=80)
    core_b_payload, core_b_evidence = candidate("90002", score=70)
    adjacent_payload, adjacent_evidence = candidate("90003", relevant=4, irrelevant=6, generalist=True, score=99)
    assessments = [
        assess_creator_topic(TOPIC, core_a_payload, core_a_evidence),
        assess_creator_topic(TOPIC, core_b_payload, core_b_evidence),
        assess_creator_topic(TOPIC, adjacent_payload, adjacent_evidence),
    ]
    forward = select_v2_top_competitors(assessments)
    reverse = select_v2_top_competitors(list(reversed(assessments)))
    assert [(item.creator_mid, item.selection_rank) for item in forward] == [
        (item.creator_mid, item.selection_rank) for item in reverse
    ]
    assert [item.creator_mid for item in forward if item.selected] == ["90001", "90002"]
    assert sum(item.selected for item in forward) == 2


def test_v2_selection_prioritizes_frozen_qualified_references_without_hardcoding_accounts():
    payloads = [candidate(str(90_001 + index), score=90 - index) for index in range(6)]
    assessments = [
        assess_creator_topic(TOPIC, payload, evidence)
        for payload, evidence in payloads
    ]
    preferred_mid = assessments[-1].creator_mid

    selected = select_v2_top_competitors(assessments, preferred_mids={preferred_mid})

    assert preferred_mid in {item.creator_mid for item in selected if item.selected}
    assert sum(item.selected for item in selected) == 5


def test_review_router_prioritizes_unlabelled_selected_and_reuses_frozen_labels():
    first_payload, first_evidence = candidate("90001")
    second_payload, second_evidence = candidate("90002")
    assessments = select_v2_top_competitors([
        assess_creator_topic(TOPIC, first_payload, first_evidence),
        assess_creator_topic(TOPIC, second_payload, second_evidence),
    ])
    routes = route_keyword_reviews(
        assessments,
        v1_selected_mids={"90001", "90002"},
        frozen_human_status={"90002": "qualified_reference"},
    )
    by_mid = {item.creator_mid: item for item in routes}
    assert by_mid["90001"].priority == 1
    assert by_mid["90001"].include_in_blind_workbook
    assert by_mid["90002"].existing_human_label
    assert not by_mid["90002"].include_in_blind_workbook


def test_strict_human_review_import_rejects_missing_duplicate_and_invalid_rows():
    payload, evidence = candidate()
    assessment = select_v2_top_competitors([assess_creator_topic(TOPIC, payload, evidence)])[0]
    route = route_keyword_reviews(
        [assessment],
        v1_selected_mids=set(),
        frozen_human_status={},
    )[0]
    valid = {
        "review_id": route.review_id,
        "keyword_id": route.keyword_id,
        "creator_mid": route.creator_mid,
        "human_relevance": "relevant",
        "human_specialization": "high",
        "human_role": "specialist",
        "human_reason": "sustained account-level evidence",
        "review_complete": True,
    }
    assert len(validate_human_review_rows([valid], [route])) == 1
    with pytest.raises(ValueError, match="duplicate review_id"):
        validate_human_review_rows([valid, valid], [route])
    with pytest.raises(ValueError, match="missing review_id"):
        validate_human_review_rows([], [route])
    with pytest.raises(ValidationError):
        validate_human_review_rows([{**valid, "human_relevance": "irrelevant", "human_specialization": "high"}], [route])
