from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.p0c_v3_common import (
    DEVELOPMENT_RUN_VERSION,
    development_truth_by_key,
    ensure_private_new_output,
    file_sha256,
    git_head,
    git_status,
    json_dump,
    load_v3_keyword_outputs,
    partial_development_metrics,
    relation_counts,
)
from src.intelligence.contracts import HumanCreatorTopicReview


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the single frozen P0-C v3 development calibration."
    )
    parser.add_argument("stage_one", type=Path)
    parser.add_argument("human_import", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    stage_one_path = args.stage_one.resolve()
    human_import_path = args.human_import.resolve()
    output = args.output.resolve()
    ensure_private_new_output(repo, output)

    human_import = json.loads(human_import_path.read_text(encoding="utf-8"))
    if human_import.get("reviewer_count") != 1:
        raise ValueError("P0-C v3 development requires truthful reviewer_count=1")
    if human_import.get("conflict_count") != 0:
        raise ValueError("P0-C v3 development cannot use unresolved human conflicts")
    reviews = [
        HumanCreatorTopicReview.model_validate(item)
        for item in human_import.get("reviews") or []
    ]
    if len(reviews) != 53 or len({item.review_id for item in reviews}) != 53:
        raise ValueError("P0-C v3 development requires the exact 53-item review set")

    keyword_outputs = load_v3_keyword_outputs(stage_one_path)
    if len(keyword_outputs) != 20:
        raise ValueError("P0-C v3 development requires exactly 20 keyword outputs")
    truth_by_key = development_truth_by_key(keyword_outputs, reviews)
    v2_metrics = partial_development_metrics(
        keyword_outputs,
        truth_by_key,
        selected_field="v2_selected_mids",
    )
    v3_metrics = partial_development_metrics(
        keyword_outputs,
        truth_by_key,
        selected_field="v3_selected_mids",
    )

    v2_selected = {
        (item["keyword_id"], mid)
        for item in keyword_outputs
        for mid in item["v2_selected_mids"]
    }
    v3_selected = {
        (item["keyword_id"], mid)
        for item in keyword_outputs
        for mid in item["v3_selected_mids"]
    }
    removed = v2_selected - v3_selected
    added = v3_selected - v2_selected
    removed_truth = Counter(
        (
            truth_by_key[key].relation.value
            if key in truth_by_key
            else "unreviewed"
        )
        for key in removed
    )
    added_truth = Counter(
        (
            truth_by_key[key].relation.value
            if key in truth_by_key
            else "unreviewed"
        )
        for key in added
    )
    v2_correct = v2_metrics["correct_reviewed_core_count"]
    v3_correct = v3_metrics["correct_reviewed_core_count"]
    correct_retention = v3_correct / v2_correct if v2_correct else None
    false_removal = (
        v2_metrics["known_reviewed_noncore_count"]
        - v3_metrics["known_reviewed_noncore_count"]
    )
    true_removal = v2_correct - v3_correct
    candidate_valid = bool(
        v3_metrics["reviewed_selected_precision"] is not None
        and v3_metrics["reviewed_selected_precision"] >= 0.8
        and v3_metrics["strict_precision_on_reviewed_core_slots"] is not None
        and v3_metrics["strict_precision_on_reviewed_core_slots"] >= 0.8
        and correct_retention is not None
        and correct_retention >= 0.8
        and false_removal > true_removal
    )
    summary = {
        "run_version": DEVELOPMENT_RUN_VERSION,
        "status": (
            "development_candidate_valid_for_blind_holdout"
            if candidate_valid
            else "development_candidate_invalid_stop"
        ),
        "generated_at": datetime.now(timezone.utc),
        "code_commit_sha": git_head(repo),
        "working_tree_clean": not bool(git_status(repo)),
        "reviewer_count": 1,
        "review_count": len(reviews),
        "development_set_not_holdout": True,
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "evaluation_truth_uses_system_prediction": False,
        "evaluation_truth_uses_system_confidence": False,
        "evaluation_truth_uses_system_score": False,
        "evaluation_truth_uses_selection_state": False,
        "v2_partial_development_metrics": v2_metrics,
        "v3_partial_development_metrics": v3_metrics,
        "selection_change": {
            "v2_selected_count": len(v2_selected),
            "v3_selected_count": len(v3_selected),
            "removed_count": len(removed),
            "added_count": len(added),
            "unchanged_count": len(v2_selected.intersection(v3_selected)),
            "removed_truth_counts": dict(removed_truth),
            "added_truth_counts": dict(added_truth),
            "correct_core_retention": correct_retention,
            "known_noncore_removed": false_removal,
            "known_core_removed": true_removal,
        },
        "v3_relation_counts": relation_counts(keyword_outputs),
        "development_candidate_valid": candidate_valid,
        "overfitting_risks": [
            "the 53 labels were routed by v2 and are not an independent holdout",
            "seven full-pool v3 selected positions remain unreviewed by the development set",
            "generic role signals remain sparse",
            "high-confidence adjacent-topic semantic errors can remain indistinguishable from true positives",
            "reviewer_count remains 1",
        ],
        "entered_p0d": False,
    }
    assessments_path = output / "v3-keyword-assessments.json"
    selections_path = output / "v3-frozen-selections.json"
    summary_path = output / "development-summary.json"
    json_dump(assessments_path, keyword_outputs)
    json_dump(selections_path, {
        "run_version": DEVELOPMENT_RUN_VERSION,
        "code_commit_sha": summary["code_commit_sha"],
        "selection_version": "competitor-selection.p0.3",
        "qualification_policy_version": "creator-qualification.p0.2",
        "assessment_version": "creator-topic-assessment.p0.2",
        "keywords": [
            {
                "keyword_id": item["keyword_id"],
                "selected_mids": item["v3_selected_mids"],
            }
            for item in keyword_outputs
        ],
        "entered_p0d": False,
    })
    json_dump(summary_path, summary)
    manifest = {
        "run_version": DEVELOPMENT_RUN_VERSION,
        "created_at": datetime.now(timezone.utc),
        "inputs": {
            "stage_one_sha256": file_sha256(stage_one_path),
            "human_import_sha256": file_sha256(human_import_path),
        },
        "outputs": {
            "v3_keyword_assessments_sha256": file_sha256(assessments_path),
            "v3_frozen_selections_sha256": file_sha256(selections_path),
            "development_summary_sha256": file_sha256(summary_path),
        },
        "code_commit_sha": summary["code_commit_sha"],
        "network_calls": 0,
        "new_llm_calls": 0,
        "uapi_attempts": 0,
        "entered_p0d": False,
    }
    json_dump(output / "manifest.json", manifest)
    print(json.dumps({
        "status": summary["status"],
        "v2_reviewed_selected_precision": v2_metrics["reviewed_selected_precision"],
        "v3_reviewed_selected_precision": v3_metrics["reviewed_selected_precision"],
        "v3_strict_precision": v3_metrics["strict_precision_on_reviewed_core_slots"],
        "v3_selected_count": v3_metrics["selected_count"],
        "entered_p0d": False,
        "output": str(output),
    }, ensure_ascii=False))
    return 0 if candidate_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
