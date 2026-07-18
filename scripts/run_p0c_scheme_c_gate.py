from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intelligence.competitor_evaluation import aggregate_evaluation, evaluate_keyword
from src.intelligence.contracts import (
    CreatorProductRelation,
    CreatorQualificationStatus,
    CreatorTopicAssessment,
    ReviewRoutingDecision,
    TopicSpec,
)
from src.intelligence.creator_topic import (
    apply_human_review,
    select_hitl_assisted_top_competitors,
    select_v2_top_competitors,
    validate_human_review_rows,
)
from src.intelligence.evaluation import CreatorReviewDecision, validate_evaluation_file


GATE_RUN_VERSION = "p0c-scheme-c-gate.p0.2"
HUMAN_IMPORT_VERSION = "p0c-scheme-c-human-review-import.p0.1"
HITL_ASSISTED_OUTPUT_VERSION = "p0c-scheme-c-hitl-assisted.p0.1"
HUMAN_LABEL_RATIONALE_PREFIXES = (
    "human_review_id=",
    "human_relevance=",
    "human_specialization=",
    "human_role=",
    "human_reason=",
    "frozen_human_status=",
)


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_human_status(keyword: Any) -> dict[str, str]:
    status: dict[str, str] = {}

    def add(mid: str, value: str) -> None:
        existing = status.get(mid)
        if existing is not None and existing != value:
            raise ValueError(f"conflicting frozen human status for keyword={keyword.id}")
        status[mid] = value

    for creator in keyword.top_creators:
        if creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE:
            add(creator.mid, "qualified_reference")
        elif (
            creator.qualification_status == CreatorQualificationStatus.EXCLUDED
            or creator.decision == CreatorReviewDecision.EXCLUDE
        ):
            add(creator.mid, "excluded")
    for creator in keyword.expected_relevant_creators:
        if creator.qualification_status == CreatorQualificationStatus.QUALIFIED_REFERENCE:
            add(creator.mid, "qualified_reference")
        elif creator.qualification_status == CreatorQualificationStatus.EXCLUDED:
            add(creator.mid, "excluded")
    return status


def apply_hitl_frozen_status(
    assessment: CreatorTopicAssessment,
    status: str | None,
) -> CreatorTopicAssessment:
    if status is None:
        return assessment.model_copy(update={"selected": False, "selection_rank": None})
    relation = {
        "qualified_reference": CreatorProductRelation.CORE_COMPETITOR,
        "excluded": CreatorProductRelation.EXCLUDED,
    }.get(status)
    if relation is None:
        raise ValueError(f"unsupported frozen human status: {status}")
    return assessment.model_copy(update={
        "product_relation": relation,
        "selected": False,
        "selection_rank": None,
        "rationale": [*assessment.rationale, f"frozen_human_status={status}"],
    })


def select_unbiased_gate_competitors(
    assessments: list[CreatorTopicAssessment],
) -> list[CreatorTopicAssessment]:
    if any(
        rationale.startswith(HUMAN_LABEL_RATIONALE_PREFIXES)
        for assessment in assessments
        for rationale in assessment.rationale
    ):
        raise ValueError("unbiased Gate selection cannot consume human-label overlays")
    return select_v2_top_competitors(assessments)


def quality_gate_checks(
    overall: dict[str, Any],
    *,
    traceability_passed: bool,
    explainability_passed: bool,
) -> dict[str, bool]:
    selected_precision_passed = (
        overall["selected_precision"] is not None
        and overall["selected_precision"] >= 0.8
    )
    strict_precision_at_5_passed = (
        overall["strict_precision_at_5"] is not None
        and overall["strict_precision_at_5"] >= 0.8
    )
    false_positive_passed = (
        overall["irrelevant_false_positive_rate"] is not None
        and overall["irrelevant_false_positive_rate"] <= 0.10
    )
    precision_passed = selected_precision_passed and strict_precision_at_5_passed
    return {
        "selected_precision_passed": selected_precision_passed,
        "strict_precision_at_5_passed": strict_precision_at_5_passed,
        "precision_passed": precision_passed,
        "false_positive_passed": false_positive_passed,
        "traceability_passed": traceability_passed,
        "explainability_passed": explainability_passed,
        "technical_passed": (
            precision_passed
            and false_positive_passed
            and traceability_passed
            and explainability_passed
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply scheme-C human reviews and run the frozen P0-C v2 Gate.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("v1_gate", type=Path)
    parser.add_argument("scheme_c_round", type=Path)
    parser.add_argument("human_import", type=Path)
    parser.add_argument("frozen_workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    baseline = args.baseline.resolve()
    v1_gate = args.v1_gate.resolve()
    scheme_c_round = args.scheme_c_round.resolve()
    human_import_path = args.human_import.resolve()
    frozen_workbook = args.frozen_workbook.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("private scheme-C Gate output must remain outside the Git repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("scheme-C Gate output directory must be new and empty")

    manifest = json.loads((scheme_c_round / "scheme-c-manifest.json").read_text(encoding="utf-8"))
    if file_sha256(baseline) != manifest["inputs"]["baseline_sha256"]:
        raise ValueError("baseline hash does not match the frozen scheme-C round")
    expected_round_hashes = {
        "baseline_reproduction_sha256": scheme_c_round / "baseline-reproduction.json",
        "review_data_sha256": scheme_c_round / "p0c-scheme-c-account-review-v1-data.json",
        "private_map_sha256": scheme_c_round / "p0c-scheme-c-account-review-v1-private-map.json",
        "summary_sha256": scheme_c_round / "scheme-c-summary.json",
    }
    for key, path in expected_round_hashes.items():
        if file_sha256(path) != manifest["outputs"][key]:
            raise ValueError(f"scheme-C round input changed after generation: {path.name}")

    human_import = json.loads(human_import_path.read_text(encoding="utf-8"))
    if human_import.get("schema_version") != HUMAN_IMPORT_VERSION:
        raise ValueError("unsupported scheme-C human import version")
    if human_import.get("reviewer_count") != 1:
        raise ValueError("scheme-C Gate requires the truthful reviewer_count=1")
    if human_import.get("source_workbook_sha256") != file_sha256(frozen_workbook):
        raise ValueError("human import source hash does not match the frozen workbook")
    if human_import.get("conflict_count") != 0:
        raise ValueError("human import reports unresolved frozen-label conflicts")

    suite = validate_evaluation_file(baseline, require_reviewed=True)
    keyword_by_id = {keyword.id: keyword for keyword in suite.keywords}
    saved_v1 = json.loads((v1_gate / "evaluation-after.json").read_text(encoding="utf-8"))
    recomputed_v1_metrics = []
    for keyword in suite.keywords:
        frozen_keyword = json.loads(
            (v1_gate / "keywords" / f"{keyword.id}.json").read_text(encoding="utf-8")
        )
        recomputed_v1_metrics.append(evaluate_keyword(
            keyword,
            selected_mids=[item["creator_mid"] for item in frozen_keyword["selected"]],
            retrieved_mids=[item["creator_mid"] for item in frozen_keyword["candidates"]],
        ))
    recomputed_v1 = aggregate_evaluation(recomputed_v1_metrics)
    if recomputed_v1 != saved_v1:
        raise ValueError("current code cannot exactly reproduce the frozen v1 Gate evaluation")
    baseline_reproduction = json.loads(
        (scheme_c_round / "baseline-reproduction.json").read_text(encoding="utf-8")
    )
    if (
        baseline_reproduction.get("exact_match_to_v1_gate") is not True
        or baseline_reproduction.get("evaluation") != recomputed_v1
    ):
        raise ValueError("scheme-C baseline reproduction no longer matches the frozen v1 Gate")
    stage_one_outputs = json.loads(
        (scheme_c_round / "v2-keyword-assessments.json").read_text(encoding="utf-8")
    )
    stage_one_by_keyword = {item["keyword_id"]: item for item in stage_one_outputs}
    if set(stage_one_by_keyword) != set(keyword_by_id):
        raise ValueError("scheme-C stage-one keyword coverage mismatch")

    all_routes = [
        ReviewRoutingDecision.model_validate(route)
        for item in stage_one_outputs
        for route in item["review_routes"]
    ]
    reviews = validate_human_review_rows(human_import["reviews"], all_routes)
    if len(reviews) != human_import.get("review_count"):
        raise ValueError("human import review_count does not match validated reviews")
    review_by_key = {(review.keyword_id, review.creator_mid): review for review in reviews}

    conflicts = []
    for review in reviews:
        frozen = frozen_human_status(keyword_by_id[review.keyword_id]).get(review.creator_mid)
        if (
            frozen == "qualified_reference"
            and review.human_relevance is not None
            and review.human_relevance.value != "relevant"
        ) or (
            frozen == "excluded"
            and review.human_relevance is not None
            and review.human_relevance.value != "irrelevant"
        ):
            conflicts.append({
                "review_id": review.review_id,
                "keyword_id": review.keyword_id,
                "creator_mid": review.creator_mid,
                "frozen_human_status": frozen,
                "new_human_relevance": review.human_relevance.value,
            })
    if conflicts:
        output.mkdir(parents=True, exist_ok=False)
        json_dump(output / "review-conflicts.json", {
            "status": "requires_human_adjudication",
            "conflict_count": len(conflicts),
            "conflicts": conflicts,
            "entered_p0d": False,
        })
        print(f"gate_status=not_run conflict_count={len(conflicts)} output={output}", flush=True)
        return 2

    output.mkdir(parents=True, exist_ok=False)
    unbiased_keyword_outputs = []
    hitl_keyword_outputs = []
    unbiased_keyword_metrics = []
    hitl_diagnostic_metrics = []
    unbiased_relation_counts: Counter[str] = Counter()
    hitl_relation_counts: Counter[str] = Counter()
    review_relation_counts: Counter[str] = Counter()
    applied_review_ids: set[str] = set()
    v1_selected_total = provisional_selected_total = 0
    unbiased_selected_total = hitl_selected_total = 0
    v1_unbiased_difference_total = provisional_unbiased_difference_total = 0
    v1_hitl_difference_total = provisional_hitl_difference_total = 0
    unbiased_selected_assessments = []
    reviewed_nonselected_count = reviewed_nonselected_core_count = 0
    reviewed_mids_by_keyword = {
        keyword_id: {
            review.creator_mid for review in reviews if review.keyword_id == keyword_id
        }
        for keyword_id in keyword_by_id
    }

    for keyword in suite.keywords:
        item = stage_one_by_keyword[keyword.id]
        topic_spec = TopicSpec.model_validate(item["topic_spec"])
        provisional_assessments = [
            CreatorTopicAssessment.model_validate(assessment)
            for assessment in item["assessments"]
        ]
        provisional_selected_order = [
            assessment.creator_mid
            for assessment in sorted(
                provisional_assessments,
                key=lambda value: value.selection_rank or 999,
            )
            if assessment.selected
        ]
        provisional_selected = set(provisional_selected_order)

        unbiased_assessments = select_unbiased_gate_competitors(provisional_assessments)
        unbiased_selected_order = [
            assessment.creator_mid
            for assessment in sorted(
                unbiased_assessments,
                key=lambda value: value.selection_rank or 999,
            )
            if assessment.selected
        ]
        if unbiased_selected_order != provisional_selected_order:
            raise ValueError("unbiased Gate selection does not reproduce the pre-HITL system output")
        unbiased_selected = set(unbiased_selected_order)
        retrieved = [assessment.creator_mid for assessment in unbiased_assessments]
        unbiased_keyword_metrics.append(evaluate_keyword(
            keyword,
            selected_mids=unbiased_selected_order,
            retrieved_mids=retrieved,
        ))
        unbiased_relation_counts.update(
            assessment.product_relation.value for assessment in unbiased_assessments
        )
        unbiased_selected_assessments.extend(
            assessment for assessment in unbiased_assessments if assessment.selected
        )

        human_status = frozen_human_status(keyword)
        hitl_overlaid = []
        for assessment in provisional_assessments:
            review = review_by_key.get((keyword.id, assessment.creator_mid))
            if review is not None:
                updated = apply_human_review(assessment, review)
                applied_review_ids.add(review.review_id)
                review_relation_counts.update([updated.product_relation.value])
            else:
                updated = apply_hitl_frozen_status(
                    assessment,
                    human_status.get(assessment.creator_mid),
                )
            hitl_overlaid.append(updated)
        preferred_mids = {
            mid for mid, status in human_status.items() if status == "qualified_reference"
        }
        hitl_assessments = select_hitl_assisted_top_competitors(
            hitl_overlaid,
            preferred_mids=preferred_mids,
        )
        hitl_selected_order = [
            assessment.creator_mid
            for assessment in sorted(
                hitl_assessments,
                key=lambda value: value.selection_rank or 999,
            )
            if assessment.selected
        ]
        hitl_selected = set(hitl_selected_order)
        hitl_diagnostic_metrics.append(evaluate_keyword(
            keyword,
            selected_mids=hitl_selected_order,
            retrieved_mids=retrieved,
        ))
        hitl_relation_counts.update(
            assessment.product_relation.value for assessment in hitl_assessments
        )
        reviewed_nonselected = [
            assessment
            for assessment in hitl_assessments
            if assessment.creator_mid in reviewed_mids_by_keyword[keyword.id]
            and not assessment.selected
        ]
        reviewed_nonselected_count += len(reviewed_nonselected)
        reviewed_nonselected_core_count += sum(
            assessment.product_relation == CreatorProductRelation.CORE_COMPETITOR
            for assessment in reviewed_nonselected
        )

        v1_selected = set(item["v1_selected_mids"])
        v1_selected_total += len(v1_selected)
        provisional_selected_total += len(provisional_selected)
        unbiased_selected_total += len(unbiased_selected)
        hitl_selected_total += len(hitl_selected)
        v1_unbiased_difference_total += len(v1_selected.symmetric_difference(unbiased_selected))
        provisional_unbiased_difference_total += len(
            provisional_selected.symmetric_difference(unbiased_selected)
        )
        v1_hitl_difference_total += len(v1_selected.symmetric_difference(hitl_selected))
        provisional_hitl_difference_total += len(
            provisional_selected.symmetric_difference(hitl_selected)
        )
        unbiased_keyword_outputs.append({
            "keyword_id": keyword.id,
            "topic_spec": topic_spec.model_dump(mode="json"),
            "v1_selected_mids": sorted(v1_selected),
            "pre_hitl_system_selected_mids": unbiased_selected_order,
            "v1_unbiased_selection_difference_mids": sorted(
                v1_selected.symmetric_difference(unbiased_selected)
            ),
            "assessments": [
                assessment.model_dump(mode="json") for assessment in unbiased_assessments
            ],
        })
        hitl_keyword_outputs.append({
            "keyword_id": keyword.id,
            "topic_spec": topic_spec.model_dump(mode="json"),
            "v1_selected_mids": sorted(v1_selected),
            "pre_hitl_system_selected_mids": provisional_selected_order,
            "hitl_assisted_selected_mids": hitl_selected_order,
            "v1_hitl_selection_difference_mids": sorted(
                v1_selected.symmetric_difference(hitl_selected)
            ),
            "pre_hitl_hitl_selection_difference_mids": sorted(
                provisional_selected.symmetric_difference(hitl_selected)
            ),
            "assessments": [
                assessment.model_dump(mode="json") for assessment in hitl_assessments
            ],
        })

    if applied_review_ids != {review.review_id for review in reviews}:
        raise ValueError("not every validated human review was applied exactly once")

    unbiased_evaluation = aggregate_evaluation(unbiased_keyword_metrics)
    unbiased_overall = unbiased_evaluation["overall"]
    hitl_diagnostic_evaluation = aggregate_evaluation(hitl_diagnostic_metrics)
    hitl_overall = hitl_diagnostic_evaluation["overall"]
    traceability_passed = all(
        assessment.evidence.evidence_ids and assessment.evidence.source_urls
        for assessment in unbiased_selected_assessments
    )
    explainability_passed = all(
        assessment.rationale
        and assessment.system_confidence.components
        and assessment.system_confidence.formula
        for assessment in unbiased_selected_assessments
    )
    checks = quality_gate_checks(
        unbiased_overall,
        traceability_passed=traceability_passed,
        explainability_passed=explainability_passed,
    )
    gate_status = "with_reservation" if checks["technical_passed"] else "failed"

    unbiased_assessment_path = output / "unbiased-quality-gate-assessments.json"
    unbiased_evaluation_path = output / "unbiased-quality-gate-evaluation.json"
    hitl_assessment_path = output / "hitl-assisted-assessments.json"
    hitl_diagnostic_path = output / "hitl-assisted-diagnostics.json"
    audit_path = output / "hitl-assisted-human-overlay-audit.json"
    hitl_summary_path = output / "hitl-assisted-summary.json"
    gate_path = output / "gate-summary.json"
    json_dump(unbiased_assessment_path, unbiased_keyword_outputs)
    json_dump(unbiased_evaluation_path, {
        "status": "unbiased_quality_gate_evaluation",
        "formula_version": unbiased_evaluation["formula_version"],
        "evaluation": unbiased_evaluation,
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "frozen_labels_are_metrics_only": True,
        "recall_scope": "frozen qualified_reference set only",
        "sampled_false_negative_audit_is_not_full_recall": True,
    })
    json_dump(hitl_assessment_path, hitl_keyword_outputs)
    json_dump(hitl_diagnostic_path, {
        "status": "hitl_assisted_diagnostic_not_quality_gate",
        "formula_version": hitl_diagnostic_evaluation["formula_version"],
        "evaluation": hitl_diagnostic_evaluation,
        "selection_uses_scheme_c_human_reviews": True,
        "selection_uses_frozen_evaluation_labels": True,
        "eligible_as_unbiased_quality_gate": False,
        "metrics_cannot_prove_unbiased_quality": True,
        "recall_scope": "frozen qualified_reference set only",
        "sampled_false_negative_audit_is_not_full_recall": True,
    })
    json_dump(audit_path, {
        "schema_version": HUMAN_IMPORT_VERSION,
        "output_version": HITL_ASSISTED_OUTPUT_VERSION,
        "source_workbook": human_import["source_workbook"],
        "source_workbook_sha256": human_import["source_workbook_sha256"],
        "imported_at": human_import["imported_at"],
        "reviewer_count": human_import["reviewer_count"],
        "review_count": len(reviews),
        "applied_review_count": len(applied_review_ids),
        "conflict_count": 0,
        "review_product_relation_counts": dict(review_relation_counts),
        "reviewed_nonselected_count": reviewed_nonselected_count,
        "reviewed_nonselected_core_count": reviewed_nonselected_core_count,
        "sampled_false_negative_audit_is_not_full_recall": True,
        "eligible_as_unbiased_quality_gate": False,
    })
    hitl_summary = {
        "run_version": HITL_ASSISTED_OUTPUT_VERSION,
        "status": "workflow_validated_not_quality_gate",
        "reviewer_count": human_import["reviewer_count"],
        "review_count": len(reviews),
        "review_conflict_count": 0,
        "pre_hitl_system_selected_count": provisional_selected_total,
        "hitl_assisted_selected_count": hitl_selected_total,
        "v1_hitl_selection_difference_count": v1_hitl_difference_total,
        "pre_hitl_hitl_selection_difference_count": provisional_hitl_difference_total,
        "product_relation_counts": dict(hitl_relation_counts),
        "diagnostic_selected_precision": hitl_overall["selected_precision"],
        "diagnostic_strict_precision_at_5": hitl_overall["strict_precision_at_5"],
        "diagnostic_irrelevant_false_positive_rate": hitl_overall[
            "irrelevant_false_positive_rate"
        ],
        "diagnostic_unresolved_selection_rate": hitl_overall["unresolved_selection_rate"],
        "diagnostic_output_coverage": hitl_overall["output_coverage"],
        "diagnostic_retrieval_recall": hitl_overall["retrieval_recall"],
        "selection_uses_scheme_c_human_reviews": True,
        "selection_uses_frozen_evaluation_labels": True,
        "eligible_as_unbiased_quality_gate": False,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
        "network_calls": 0,
        "entered_p0d": False,
    }
    json_dump(hitl_summary_path, hitl_summary)
    gate = {
        "run_version": GATE_RUN_VERSION,
        "gate_scope": "unbiased_pre_hitl_system_output",
        "gate_status": gate_status,
        "technical_passed": checks["technical_passed"],
        "reviewer_count": human_import["reviewer_count"],
        "single_reviewer_reservation": True,
        "selected_precision_gate_passed": checks["selected_precision_passed"],
        "strict_precision_at_5_gate_passed": checks["strict_precision_at_5_passed"],
        "precision_gate_passed": checks["precision_passed"],
        "false_positive_gate_passed": checks["false_positive_passed"],
        "traceability_gate_passed": checks["traceability_passed"],
        "explainability_gate_passed": checks["explainability_passed"],
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "frozen_labels_are_metrics_only": True,
        "v1_selected_count": v1_selected_total,
        "pre_hitl_system_selected_count": provisional_selected_total,
        "unbiased_selected_count": unbiased_selected_total,
        "v1_unbiased_selection_difference_count": v1_unbiased_difference_total,
        "pre_hitl_unbiased_selection_difference_count": provisional_unbiased_difference_total,
        "product_relation_counts": dict(unbiased_relation_counts),
        "selected_precision": unbiased_overall["selected_precision"],
        "strict_precision_at_5": unbiased_overall["strict_precision_at_5"],
        "irrelevant_false_positive_rate": unbiased_overall[
            "irrelevant_false_positive_rate"
        ],
        "unresolved_selection_rate": unbiased_overall["unresolved_selection_rate"],
        "output_coverage": unbiased_overall["output_coverage"],
        "retrieval_recall": unbiased_overall["retrieval_recall"],
        "hitl_assisted_summary": hitl_summary_path.name,
        "v1_exact_reproduction": True,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
        "network_calls": 0,
        "entered_p0d": False,
        "p0d_allowed": False,
        "decision": (
            "candidate_pass_waiting_for_control_review"
            if checks["technical_passed"]
            else "p0c_unbiased_quality_gate_failed"
        ),
    }
    json_dump(gate_path, gate)
    summary_lines = [
        "# P0-C v2 Scheme-C Gate Integrity Review",
        "",
        "## Unbiased quality Gate",
        "",
        f"- Status: {gate_status}",
        "- Selection, qualification, ranking: no human labels used; frozen labels are metrics only.",
        f"- Pre-HITL system selected positions: {unbiased_selected_total}",
        f"- Selected precision: {unbiased_overall['selected_precision']:.2%}",
        f"- Strict Precision@5: {unbiased_overall['strict_precision_at_5']:.2%}",
        f"- Irrelevant false-positive rate: {unbiased_overall['irrelevant_false_positive_rate']:.2%}",
        f"- Unresolved selection rate: {unbiased_overall['unresolved_selection_rate']:.2%}",
        f"- Eligible output coverage: {unbiased_overall['output_coverage']:.2%}",
        f"- Retrieval Recall: {unbiased_overall['retrieval_recall']:.2%}",
        "",
        "## HITL-assisted product output",
        "",
        f"- Human reviews: {len(reviews)} (reviewer_count=1)",
        f"- HITL-assisted selected positions: {hitl_selected_total}",
        f"- Diagnostic selected precision: {hitl_overall['selected_precision']:.2%}",
        f"- Diagnostic strict Precision@5: {hitl_overall['strict_precision_at_5']:.2%}",
        f"- Diagnostic irrelevant false-positive rate: {hitl_overall['irrelevant_false_positive_rate']:.2%}",
        "- These diagnostics are not an unbiased quality Gate because human labels affected qualification and ranking.",
        "",
        "- The earlier with_reservation decision is corrected to failed.",
        "- UAPI attempts: 0; new LLM calls: 0; entered P0-D: false.",
    ]
    (output / "gate-summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    json_dump(output / "manifest.json", {
        "run_version": GATE_RUN_VERSION,
        "created_at": datetime.now(timezone.utc),
        "inputs": {
            "baseline_sha256": file_sha256(baseline),
            "v1_evaluation_sha256": file_sha256(v1_gate / "evaluation-after.json"),
            "scheme_c_manifest_sha256": file_sha256(scheme_c_round / "scheme-c-manifest.json"),
            "baseline_reproduction_sha256": file_sha256(
                scheme_c_round / "baseline-reproduction.json"
            ),
            "stage_one_assessments_sha256": file_sha256(
                scheme_c_round / "v2-keyword-assessments.json"
            ),
            "review_data_sha256": file_sha256(
                scheme_c_round / "p0c-scheme-c-account-review-v1-data.json"
            ),
            "private_map_sha256": file_sha256(
                scheme_c_round / "p0c-scheme-c-account-review-v1-private-map.json"
            ),
            "human_import_sha256": file_sha256(human_import_path),
            "frozen_workbook_sha256": file_sha256(frozen_workbook),
        },
        "outputs": {
            "unbiased_assessment_sha256": file_sha256(unbiased_assessment_path),
            "unbiased_evaluation_sha256": file_sha256(unbiased_evaluation_path),
            "hitl_assessment_sha256": file_sha256(hitl_assessment_path),
            "hitl_diagnostic_sha256": file_sha256(hitl_diagnostic_path),
            "hitl_human_overlay_audit_sha256": file_sha256(audit_path),
            "hitl_summary_sha256": file_sha256(hitl_summary_path),
            "gate_summary_sha256": file_sha256(gate_path),
        },
        "network_calls": 0,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
        "entered_p0d": False,
    })
    print(
        f"gate_status={gate_status} selected_precision={unbiased_overall['selected_precision']:.6f} "
        f"strict_precision_at_5={unbiased_overall['strict_precision_at_5']:.6f} "
        f"hitl_status={hitl_summary['status']} output={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
