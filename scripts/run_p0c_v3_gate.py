from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.p0c_v3_common import (
    GATE_RUN_VERSION,
    HOLDOUT_PACKAGE_VERSION,
    HUMAN_IMPORT_VERSION,
    ensure_private_new_output,
    file_sha256,
    git_head,
    git_status,
    json_dump,
)
from src.intelligence.competitor_evaluation import (
    EVALUATION_FORMULA_VERSION_V3,
    map_review_to_evaluation_truth_v3,
)
from src.intelligence.contracts import (
    AccountTopicRelevance,
    CreatorProductRelation,
    CreatorTopicAssessmentV3,
    HumanCreatorTopicReview,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the frozen P0-C v3 blind-holdout Gate without reranking."
    )
    parser.add_argument("holdout_round", type=Path)
    parser.add_argument("human_import", type=Path)
    parser.add_argument("frozen_workbook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    holdout_round = args.holdout_round.resolve()
    human_import_path = args.human_import.resolve()
    frozen_workbook = args.frozen_workbook.resolve()
    output = args.output.resolve()
    if git_status(repo):
        raise ValueError("P0-C v3 Gate requires the unchanged clean candidate-freeze worktree")
    ensure_private_new_output(repo, output)

    manifest = json.loads((holdout_round / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != HOLDOUT_PACKAGE_VERSION:
        raise ValueError("unsupported P0-C v3 holdout package version")
    if manifest.get("code_commit_sha") != git_head(repo):
        raise ValueError("current code is not the frozen v3 candidate commit")
    expected_outputs = {
        "review_data_sha256": holdout_round / "p0c-v3-blind-holdout-data.json",
        "private_map_sha256": holdout_round / "p0c-v3-blind-holdout-private-map.json",
        "frozen_selection_sha256": holdout_round / "p0c-v3-frozen-holdout-selection.json",
        "summary_sha256": holdout_round / "holdout-summary.json",
    }
    for key, path in expected_outputs.items():
        if file_sha256(path) != manifest["outputs"][key]:
            raise ValueError(f"holdout artifact changed after freeze: {path.name}")

    human_import = json.loads(human_import_path.read_text(encoding="utf-8"))
    if human_import.get("schema_version") != HUMAN_IMPORT_VERSION:
        raise ValueError("unsupported P0-C v3 human-review import version")
    if human_import.get("reviewer_count") != 1:
        raise ValueError("P0-C v3 Gate requires truthful reviewer_count=1")
    if human_import.get("source_workbook_sha256") != file_sha256(frozen_workbook):
        raise ValueError("human import does not match the frozen blind workbook")
    if human_import.get("holdout_manifest_sha256") != file_sha256(
        holdout_round / "manifest.json"
    ):
        raise ValueError("human import holdout manifest hash mismatch")
    if human_import.get("review_data_sha256") != file_sha256(
        holdout_round / "p0c-v3-blind-holdout-data.json"
    ):
        raise ValueError("human import review-data hash mismatch")
    if human_import.get("code_commit_sha") != git_head(repo):
        raise ValueError("human import code SHA does not match the frozen candidate")
    if human_import.get("review_count") != len(human_import.get("reviews") or []):
        raise ValueError("human import review_count does not match review rows")
    if human_import.get("conflict_count") != 0:
        raise ValueError("human import reports unresolved review conflicts")

    review_data = json.loads(
        (holdout_round / "p0c-v3-blind-holdout-data.json").read_text(encoding="utf-8")
    )
    private_map = json.loads(
        (holdout_round / "p0c-v3-blind-holdout-private-map.json").read_text(encoding="utf-8")
    )
    frozen_selection = json.loads(
        (holdout_round / "p0c-v3-frozen-holdout-selection.json").read_text(encoding="utf-8")
    )
    expected_items = {item["review_id"]: item for item in private_map["items"]}
    if len(expected_items) != len(private_map["items"]):
        raise ValueError("holdout private map contains duplicate review IDs")
    visible_by_id = {item["review_id"]: item for item in review_data["review_items"]}
    if set(visible_by_id) != set(expected_items):
        raise ValueError("visible holdout and private map review coverage differ")

    reviews = [
        HumanCreatorTopicReview.model_validate(item)
        for item in human_import.get("reviews") or []
    ]
    review_by_id = {item.review_id: item for item in reviews}
    if len(review_by_id) != len(reviews):
        raise ValueError("human import contains duplicate review IDs")
    if set(review_by_id) != set(expected_items):
        raise ValueError("human import must cover the complete frozen holdout exactly once")

    truth_by_key = {}
    assessment_by_key = {}
    review_id_by_key = {}
    for review_id, item in expected_items.items():
        review = review_by_id[review_id]
        if review.keyword_id != item["keyword_id"] or review.creator_mid != item["creator_mid"]:
            raise ValueError(f"human review identity mismatch: {review_id}")
        visible = visible_by_id[review_id]
        assessment = CreatorTopicAssessmentV3.model_validate(item["v3_assessment"])
        truth = map_review_to_evaluation_truth_v3(
            review,
            assessment.evidence,
            category=visible["category"],
        )
        key = (review.keyword_id, review.creator_mid)
        if key in truth_by_key:
            raise ValueError("holdout contains duplicate account-keyword relations")
        truth_by_key[key] = truth
        assessment_by_key[key] = assessment
        review_id_by_key[key] = review_id

    selected_by_keyword = {
        item["keyword_id"]: list(dict.fromkeys(item["selected_mids"]))[:5]
        for item in frozen_selection["keywords"]
    }
    selected_keys = {
        (keyword_id, mid)
        for keyword_id, mids in selected_by_keyword.items()
        for mid in mids
    }
    missing_selected_reviews = selected_keys - set(truth_by_key)
    if missing_selected_reviews:
        raise ValueError(
            f"blind holdout omitted {len(missing_selected_reviews)} frozen selected relations"
        )

    keyword_metrics = []
    totals = Counter()
    false_negative_samples = []
    selected_assessments = []
    for keyword_id, selected_mids in selected_by_keyword.items():
        selected_truth = [truth_by_key[(keyword_id, mid)] for mid in selected_mids]
        correct = sum(
            truth.relation == CreatorProductRelation.CORE_COMPETITOR
            for truth in selected_truth
        )
        irrelevant = sum(
            truth.human_relevance == AccountTopicRelevance.IRRELEVANT
            for truth in selected_truth
        )
        unresolved = sum(
            truth.relation == CreatorProductRelation.INSUFFICIENT_EVIDENCE
            for truth in selected_truth
        )
        reviewed_core = {
            mid
            for (review_keyword_id, mid), truth in truth_by_key.items()
            if review_keyword_id == keyword_id
            and truth.relation == CreatorProductRelation.CORE_COMPETITOR
        }
        eligible_slots = min(5, len(reviewed_core))
        selected_set = set(selected_mids)
        sampled_false_negatives = sorted(reviewed_core - selected_set)
        for mid in sampled_false_negatives:
            false_negative_samples.append({
                "review_id": review_id_by_key[(keyword_id, mid)],
                "keyword_id": keyword_id,
                "creator_mid": mid,
                "truth_relation": CreatorProductRelation.CORE_COMPETITOR.value,
            })
        selected_assessments.extend(
            assessment_by_key[(keyword_id, mid)] for mid in selected_mids
        )
        metric = {
            "keyword_id": keyword_id,
            "selected_count": len(selected_mids),
            "correct_selected_count": correct,
            "irrelevant_selected_count": irrelevant,
            "unresolved_selected_count": unresolved,
            "reviewed_core_count": len(reviewed_core),
            "eligible_top5_slots": eligible_slots,
            "selected_precision": correct / len(selected_mids) if selected_mids else None,
            "strict_precision_at_5": correct / eligible_slots if eligible_slots else None,
            "irrelevant_false_positive_rate": (
                irrelevant / len(selected_mids) if selected_mids else None
            ),
            "unresolved_selection_rate": (
                unresolved / len(selected_mids) if selected_mids else None
            ),
            "output_coverage": (
                min(len(selected_mids), eligible_slots) / eligible_slots
                if eligible_slots else None
            ),
            "shortfall_count": max(eligible_slots - len(selected_mids), 0),
            "sampled_false_negative_count": len(sampled_false_negatives),
            "abstained": len(selected_mids) == 0,
        }
        keyword_metrics.append(metric)
        totals.update({
            "selected": len(selected_mids),
            "correct": correct,
            "irrelevant": irrelevant,
            "unresolved": unresolved,
            "eligible": eligible_slots,
            "covered": min(len(selected_mids), eligible_slots),
            "shortfall": metric["shortfall_count"],
            "false_negative_sample": len(sampled_false_negatives),
            "abstained": metric["abstained"],
        })

    selected = totals["selected"]
    eligible = totals["eligible"]
    overall = {
        "keyword_count": len(keyword_metrics),
        "selected_count": selected,
        "correct_selected_count": totals["correct"],
        "irrelevant_selected_count": totals["irrelevant"],
        "unresolved_selected_count": totals["unresolved"],
        "eligible_top5_slots": eligible,
        "selected_precision": totals["correct"] / selected if selected else None,
        "strict_precision_at_5": totals["correct"] / eligible if eligible else None,
        "irrelevant_false_positive_rate": (
            totals["irrelevant"] / selected if selected else None
        ),
        "unresolved_selection_rate": (
            totals["unresolved"] / selected if selected else None
        ),
        "output_coverage": totals["covered"] / eligible if eligible else None,
        "shortfall_count": totals["shortfall"],
        "sampled_false_negative_count": totals["false_negative_sample"],
        "abstention_keyword_count": totals["abstained"],
    }
    traceability_passed = all(
        assessment.evidence.evidence_ids and assessment.evidence.source_urls
        for assessment in selected_assessments
    )
    explainability_passed = all(
        assessment.qualification.checks
        and assessment.qualification.reasons
        and assessment.rationale
        for assessment in selected_assessments
    )
    selected_precision_passed = (
        overall["selected_precision"] is not None
        and overall["selected_precision"] >= 0.8
    )
    strict_precision_passed = (
        overall["strict_precision_at_5"] is not None
        and overall["strict_precision_at_5"] >= 0.8
    )
    false_positive_passed = (
        overall["irrelevant_false_positive_rate"] is not None
        and overall["irrelevant_false_positive_rate"] <= 0.10
    )
    technical_passed = all([
        selected_precision_passed,
        strict_precision_passed,
        false_positive_passed,
        traceability_passed,
        explainability_passed,
    ])
    gate_status = "candidate_pass" if technical_passed else "failed"

    evaluation_path = output / "holdout-evaluation.json"
    truth_path = output / "holdout-evaluation-truth.json"
    gate_path = output / "gate-summary.json"
    json_dump(evaluation_path, {
        "status": "new_blind_holdout_evaluation",
        "formula_version": EVALUATION_FORMULA_VERSION_V3,
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "human_labels_are_evaluation_truth_only": True,
        "holdout_pool_excludes_53_item_development_set": True,
        "sampled_false_negative_audit_is_not_full_recall": True,
        "overall": overall,
        "keywords": keyword_metrics,
        "false_negative_samples": false_negative_samples,
    })
    json_dump(truth_path, {
        "formula_version": EVALUATION_FORMULA_VERSION_V3,
        "reviewer_count": 1,
        "items": [
            {
                "review_id": review_id_by_key[key],
                **asdict(truth),
            }
            for key, truth in sorted(truth_by_key.items())
        ],
    })
    gate = {
        "run_version": GATE_RUN_VERSION,
        "gate_status": gate_status,
        "technical_passed": technical_passed,
        "reviewer_count": 1,
        "single_reviewer_reservation": True,
        "selected_precision_gate_passed": selected_precision_passed,
        "strict_precision_at_5_gate_passed": strict_precision_passed,
        "false_positive_gate_passed": false_positive_passed,
        "traceability_gate_passed": traceability_passed,
        "explainability_gate_passed": explainability_passed,
        **overall,
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "human_labels_are_evaluation_truth_only": True,
        "review_source_workbook_sha256": human_import["source_workbook_sha256"],
        "sampled_false_negative_audit_is_not_full_recall": True,
        "entered_p0d": False,
        "p0d_allowed": False,
        "decision": (
            "p0c_v3_gate_candidate_pass_waiting_for_control_review"
            if technical_passed
            else "freeze_p0c_after_v3_holdout_failure"
        ),
    }
    json_dump(gate_path, gate)
    json_dump(output / "manifest.json", {
        "run_version": GATE_RUN_VERSION,
        "created_at": datetime.now(timezone.utc),
        "code_commit_sha": git_head(repo),
        "inputs": {
            "holdout_manifest_sha256": file_sha256(holdout_round / "manifest.json"),
            "review_data_sha256": file_sha256(
                holdout_round / "p0c-v3-blind-holdout-data.json"
            ),
            "private_map_sha256": file_sha256(
                holdout_round / "p0c-v3-blind-holdout-private-map.json"
            ),
            "frozen_selection_sha256": file_sha256(
                holdout_round / "p0c-v3-frozen-holdout-selection.json"
            ),
            "human_import_sha256": file_sha256(human_import_path),
            "frozen_workbook_sha256": file_sha256(frozen_workbook),
        },
        "outputs": {
            "holdout_evaluation_sha256": file_sha256(evaluation_path),
            "holdout_truth_sha256": file_sha256(truth_path),
            "gate_summary_sha256": file_sha256(gate_path),
        },
        "network_calls": 0,
        "new_llm_calls": 0,
        "uapi_attempts": 0,
        "entered_p0d": False,
    })
    print(
        f"gate_status={gate_status} selected_precision={overall['selected_precision']} "
        f"strict_precision_at_5={overall['strict_precision_at_5']} output={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
