"""Frozen P0-C v3 creator prediction, qualification, and core-only ranking."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from src.intelligence.contracts import (
    MAX_COMPETITORS,
    AccountTopicRelevance,
    BoundaryRisk,
    CreatorProductRelation,
    CreatorQualificationDecisionV3,
    CreatorSampleStatus,
    CreatorTopicAssessment,
    CreatorTopicAssessmentV3,
    CreatorTopicPredictionV3,
    CreatorTopicRole,
    SpecializationLevel,
)


MODEL_CONFIDENCE_MIN = 0.85
MIN_DECIDED_UPLOADS = 10
MIN_RELEVANT_UPLOADS = 5
MIN_RELEVANT_RATIO = 0.60
MIN_RELEVANT_30D_UPLOADS = 1
MIN_RELEVANT_90D_UPLOADS = 3
MIN_FOLLOWER_COUNT = 10_000
MIN_RELEVANT_VIEW_MEDIAN = 5_000

ROLE_TERMS = {
    CreatorTopicRole.AGGREGATOR: (
        "搬运", "转载", "转发", "合集", "合辑", "汇总", "剪辑", "混剪", "字幕组",
        "资讯速递", "新闻速递", "每日新闻", "每日资讯", "素材库",
    ),
    CreatorTopicRole.SERVICE: (
        "客服", "咨询", "报名", "招生", "培训", "代办", "接单", "服务商", "解决方案",
        "工作室", "旗舰店", "专卖店", "就业班", "训练营",
    ),
    CreatorTopicRole.REVIEWER: (
        "测评", "评测", "对比", "横评", "开箱", "体验报告", "深度体验", "使用体验",
    ),
    CreatorTopicRole.EDUCATOR: (
        "教程", "教学", "入门", "进阶", "实战", "讲解", "课堂", "课程", "学习", "知识点",
    ),
}
CORE_ELIGIBLE_ROLES = {
    CreatorTopicRole.SPECIALIST,
    CreatorTopicRole.EDUCATOR,
    CreatorTopicRole.REVIEWER,
    CreatorTopicRole.OFFICIAL,
    CreatorTopicRole.MEDIA,
}


def _normalized_text(value: str) -> str:
    return "".join(re.findall(r"[0-9a-z\u4e00-\u9fff]+", value.lower()))


def _role_prediction(
    assessment: CreatorTopicAssessment,
) -> tuple[CreatorTopicRole, dict[str, int], dict[str, bool], bool]:
    creator_name = _normalized_text(assessment.creator_name)
    upload_texts = [
        _normalized_text(f"{item.title} {item.description or ''}")
        for item in assessment.evidence.upload_examples
    ]
    counts = {
        role.value: sum(
            any(_normalized_text(term) in text for term in terms)
            for text in upload_texts
        )
        for role, terms in ROLE_TERMS.items()
    }
    name_matches = {
        role.value: any(_normalized_text(term) in creator_name for term in terms)
        for role, terms in ROLE_TERMS.items()
    }
    if name_matches[CreatorTopicRole.AGGREGATOR.value] or counts[
        CreatorTopicRole.AGGREGATOR.value
    ] >= 2:
        role = CreatorTopicRole.AGGREGATOR
    elif name_matches[CreatorTopicRole.SERVICE.value] or counts[
        CreatorTopicRole.SERVICE.value
    ] >= 2:
        role = CreatorTopicRole.SERVICE
    elif name_matches[CreatorTopicRole.REVIEWER.value] or counts[
        CreatorTopicRole.REVIEWER.value
    ] >= 2:
        role = CreatorTopicRole.REVIEWER
    elif name_matches[CreatorTopicRole.EDUCATOR.value] or counts[
        CreatorTopicRole.EDUCATOR.value
    ] >= 3:
        role = CreatorTopicRole.EDUCATOR
    else:
        role = assessment.role
    aggregation_signal = (
        name_matches[CreatorTopicRole.AGGREGATOR.value]
        or counts[CreatorTopicRole.AGGREGATOR.value] >= 1
    )
    return role, counts, name_matches, aggregation_signal


def _influence_passes(assessment: CreatorTopicAssessment) -> bool:
    evidence = assessment.evidence
    return (
        evidence.follower_count is not None
        and evidence.follower_count >= MIN_FOLLOWER_COUNT
    ) or (
        evidence.relevant_view_median is not None
        and evidence.relevant_view_median >= MIN_RELEVANT_VIEW_MEDIAN
    )


def _prediction(assessment: CreatorTopicAssessment) -> CreatorTopicPredictionV3:
    role, counts, name_matches, aggregation_signal = _role_prediction(assessment)
    risks = list(assessment.boundary_risks)
    if aggregation_signal:
        risks.append(BoundaryRisk.AGGREGATION_OR_REUPLOAD)
    if role == CreatorTopicRole.SERVICE:
        risks.append(BoundaryRisk.SERVICE_ACCOUNT)
    if assessment.evidence.relevant_30d_upload_count < MIN_RELEVANT_30D_UPLOADS:
        risks.append(BoundaryRisk.INSUFFICIENT_30D_CONTINUITY)
    if assessment.model_confidence < MODEL_CONFIDENCE_MIN:
        risks.append(BoundaryRisk.LOW_SEMANTIC_CONFIDENCE)
    return CreatorTopicPredictionV3(
        relevance=assessment.relevance,
        specialization=assessment.specialization,
        role=role,
        model_confidence=assessment.model_confidence,
        system_confidence=assessment.system_confidence,
        boundary_risks=list(dict.fromkeys(risks)),
        role_signal_counts=counts,
        role_name_matches=name_matches,
    )


def _qualification(
    assessment: CreatorTopicAssessment,
    prediction: CreatorTopicPredictionV3,
    *,
    category: str,
) -> CreatorQualificationDecisionV3:
    evidence = assessment.evidence
    risks = set(prediction.boundary_risks)
    checks = {
        "relevance_relevant": prediction.relevance == AccountTopicRelevance.RELEVANT,
        "not_low_result": category != "low_result",
        "semantic_confidence": prediction.model_confidence >= MODEL_CONFIDENCE_MIN,
        "sample_available": evidence.sample_status in {
            CreatorSampleStatus.SUCCESS,
            CreatorSampleStatus.PARTIAL,
        },
        "decided_sample": evidence.decided_upload_count >= MIN_DECIDED_UPLOADS,
        "evidence_consistent": not risks.intersection({
            BoundaryRisk.MISSING_EVIDENCE,
            BoundaryRisk.SEMANTIC_RULE_CONFLICT,
        }),
        "specialization_high": prediction.specialization == SpecializationLevel.HIGH,
        "role_core_eligible": prediction.role in CORE_ELIGIBLE_ROLES,
        "no_aggregation_boundary": BoundaryRisk.AGGREGATION_OR_REUPLOAD not in risks,
        "relevant_uploads": evidence.relevant_upload_count >= MIN_RELEVANT_UPLOADS,
        "relevant_ratio": (
            evidence.relevant_ratio is not None
            and evidence.relevant_ratio >= MIN_RELEVANT_RATIO
        ),
        "continuity_90d": (
            evidence.relevant_90d_upload_count >= MIN_RELEVANT_90D_UPLOADS
        ),
        "continuity_30d": (
            evidence.relevant_30d_upload_count >= MIN_RELEVANT_30D_UPLOADS
        ),
        "influence": _influence_passes(assessment),
    }

    if prediction.relevance == AccountTopicRelevance.IRRELEVANT:
        relation = CreatorProductRelation.EXCLUDED
        reasons = ["system_relevance_irrelevant"]
    elif (
        prediction.role in {CreatorTopicRole.AGGREGATOR, CreatorTopicRole.UNRELATED}
        or not checks["no_aggregation_boundary"]
    ):
        relation = CreatorProductRelation.EXCLUDED
        reasons = ["aggregation_or_reupload_boundary"]
    elif prediction.relevance != AccountTopicRelevance.RELEVANT:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["system_relevance_not_relevant"]
    elif not checks["not_low_result"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["low_result_requires_separate_policy"]
    elif not checks["semantic_confidence"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["semantic_confidence_below_0_85"]
    elif not checks["sample_available"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["creator_sample_unavailable"]
    elif not checks["decided_sample"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["fewer_than_10_decided_uploads"]
    elif not checks["evidence_consistent"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["missing_or_conflicting_evidence"]
    elif not checks["specialization_high"]:
        relation = CreatorProductRelation.ADJACENT_BENCHMARK
        reasons = ["specialization_not_high"]
    elif prediction.role in {CreatorTopicRole.GENERALIST, CreatorTopicRole.SERVICE}:
        relation = CreatorProductRelation.ADJACENT_BENCHMARK
        reasons = [f"role_boundary_{prediction.role.value}"]
    elif not checks["relevant_uploads"]:
        relation = CreatorProductRelation.OCCASIONAL_HIT
        reasons = ["fewer_than_5_relevant_uploads"]
    elif not checks["relevant_ratio"]:
        relation = CreatorProductRelation.ADJACENT_BENCHMARK
        reasons = ["relevant_ratio_below_0_60"]
    elif not checks["continuity_90d"]:
        relation = CreatorProductRelation.OCCASIONAL_HIT
        reasons = ["insufficient_90d_continuity"]
    elif not checks["continuity_30d"]:
        relation = CreatorProductRelation.OCCASIONAL_HIT
        reasons = ["insufficient_30d_continuity"]
    elif not checks["influence"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["influence_threshold_not_met"]
    elif not checks["role_core_eligible"]:
        relation = CreatorProductRelation.INSUFFICIENT_EVIDENCE
        reasons = ["role_not_core_eligible"]
    else:
        relation = CreatorProductRelation.CORE_COMPETITOR
        reasons = ["core_policy_passed"]
    return CreatorQualificationDecisionV3(
        relation=relation,
        core_eligible=relation == CreatorProductRelation.CORE_COMPETITOR,
        checks=checks,
        reasons=reasons,
    )


def calibrate_creator_topic_v3(
    assessment: CreatorTopicAssessment,
    *,
    category: str,
) -> CreatorTopicAssessmentV3:
    prediction = _prediction(assessment)
    qualification = _qualification(assessment, prediction, category=category)
    return CreatorTopicAssessmentV3(
        keyword_id=assessment.keyword_id,
        creator_mid=assessment.creator_mid,
        creator_name=assessment.creator_name,
        prediction=prediction,
        qualification=qualification,
        evidence=assessment.evidence,
        base_score=assessment.base_score,
        base_tie_break_values=assessment.base_tie_break_values,
        rationale=[
            f"prediction_relevance={prediction.relevance.value}",
            f"prediction_specialization={prediction.specialization.value}",
            f"prediction_role={prediction.role.value}",
            f"qualification_relation={qualification.relation.value}",
            *[f"qualification_reason={reason}" for reason in qualification.reasons],
        ],
    )


def _selection_key(assessment: CreatorTopicAssessmentV3) -> tuple[Any, ...]:
    tie = assessment.base_tie_break_values
    search_relevant = int(tie[2]) if len(tie) > 2 else 0
    relevant_90d = (
        int(tie[3])
        if len(tie) > 3
        else assessment.evidence.relevant_90d_upload_count
    )
    best_position = int(tie[4]) if len(tie) > 4 else 999_999
    return (
        -assessment.base_score,
        -assessment.prediction.system_confidence.score,
        -search_relevant,
        -relevant_90d,
        best_position,
        assessment.creator_mid,
    )


def select_v3_top_competitors(
    assessments: Sequence[CreatorTopicAssessmentV3],
) -> list[CreatorTopicAssessmentV3]:
    ordered = sorted(assessments, key=_selection_key)
    selected_mids = {
        assessment.creator_mid: rank
        for rank, assessment in enumerate(
            (
                item
                for item in ordered
                if item.qualification.relation == CreatorProductRelation.CORE_COMPETITOR
            ),
            1,
        )
        if rank <= MAX_COMPETITORS
    }
    return [
        assessment.model_copy(update={
            "selected": assessment.creator_mid in selected_mids,
            "selection_rank": selected_mids.get(assessment.creator_mid),
        })
        for assessment in ordered
    ]


def v3_selection_key(assessment: CreatorTopicAssessmentV3) -> tuple[Any, ...]:
    """Expose the frozen ordering for deterministic holdout false-negative sampling."""
    return _selection_key(assessment)
