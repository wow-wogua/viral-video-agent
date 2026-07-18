from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.p0c_v3_common import (
    HOLDOUT_PACKAGE_VERSION,
    ensure_private_new_output,
    file_sha256,
    git_head,
    git_status,
    json_dump,
    load_v3_keyword_outputs,
)
from src.intelligence.contracts import CreatorTopicAssessmentV3, HumanCreatorTopicReview


MIN_HOLDOUT_ITEMS = 40
MAX_HOLDOUT_ITEMS = 80


def review_id(keyword_id: str, creator_mid: str) -> str:
    digest = hashlib.sha256(
        f"p0c-v3|{keyword_id}|{creator_mid}".encode("utf-8")
    ).hexdigest()[:16]
    return f"review_{digest}"


def summary_text(values: list[str], *, maximum: int = 320) -> str:
    text = "；".join(value.strip() for value in values if value.strip())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def visible_review_item(item: dict[str, Any]) -> dict[str, Any]:
    assessment = CreatorTopicAssessmentV3.model_validate(item["assessment"])
    topic_spec = item["topic_spec"]
    evidence = assessment.evidence
    neutral = [
        f"主页：{evidence.profile_url}" if evidence.profile_url else "主页：缺失",
        f"粉丝数：{evidence.follower_count}"
        if evidence.follower_count is not None
        else "粉丝数：缺失",
        f"样本状态：{evidence.sample_status.value}",
    ]
    return {
        "review_id": item["review_id"],
        "keyword_id": assessment.keyword_id,
        "keyword": topic_spec["keyword"],
        "category": topic_spec["category"],
        "intent_definition": topic_spec["intent_definition"],
        "allowed_subtopics_summary": summary_text(topic_spec["allowed_subtopics"]),
        "exclusion_rules_summary": summary_text(topic_spec["exclusion_rules"]),
        "creator_name": assessment.creator_name,
        "creator_mid": assessment.creator_mid,
        "neutral_public_info": "；".join(neutral),
        "sample_upload_count": evidence.sampled_upload_count,
        "recent_30d_upload_count": evidence.recent_30d_upload_count,
        "recent_90d_upload_count": evidence.recent_90d_upload_count,
        "human_relevance": None,
        "human_specialization": None,
        "human_role": None,
        "human_reason": "",
        "review_complete": None,
    }


def visible_evidence_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = CreatorTopicAssessmentV3.model_validate(item["assessment"])
    examples = assessment.evidence.upload_examples or assessment.evidence.search_examples
    evidence_type = (
        "creator_upload"
        if assessment.evidence.upload_examples
        else "search_snapshot_fallback"
    )
    return [
        {
            "review_id": item["review_id"],
            "evidence_sequence": index,
            "evidence_type": evidence_type,
            "title": evidence.title,
            "description_summary": evidence.description or "",
            "published_at": evidence.published_at,
            "frozen_snapshot_metrics": (
                f"播放量={evidence.view}" if evidence.view is not None else "播放量=缺失"
            ),
            "source_url": evidence.source_url,
            "evidence_reference": "|".join(evidence.evidence_ids),
        }
        for index, evidence in enumerate(examples, 1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the frozen P0-C v3 unseen blind-holdout package."
    )
    parser.add_argument("stage_one", type=Path)
    parser.add_argument("development_human_import", type=Path)
    parser.add_argument("development_round", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    stage_one_path = args.stage_one.resolve()
    human_import_path = args.development_human_import.resolve()
    development_round = args.development_round.resolve()
    output = args.output.resolve()
    if git_status(repo):
        raise ValueError("holdout generation requires a clean v3 candidate-freeze worktree")
    ensure_private_new_output(repo, output)

    development_manifest = json.loads(
        (development_round / "manifest.json").read_text(encoding="utf-8")
    )
    current_sha = git_head(repo)
    if development_manifest.get("code_commit_sha") != current_sha:
        raise ValueError("development round code SHA does not match current frozen commit")
    if file_sha256(stage_one_path) != development_manifest["inputs"]["stage_one_sha256"]:
        raise ValueError("stage-one input changed after the frozen development round")
    expected_development_outputs = {
        "v3_keyword_assessments_sha256": development_round / "v3-keyword-assessments.json",
        "v3_frozen_selections_sha256": development_round / "v3-frozen-selections.json",
        "development_summary_sha256": development_round / "development-summary.json",
    }
    for key, path in expected_development_outputs.items():
        if file_sha256(path) != development_manifest["outputs"][key]:
            raise ValueError(f"development artifact changed after freeze: {path.name}")

    development_import = json.loads(human_import_path.read_text(encoding="utf-8"))
    reviews = [
        HumanCreatorTopicReview.model_validate(item)
        for item in development_import.get("reviews") or []
    ]
    if len(reviews) != 53:
        raise ValueError("holdout generation requires the exact 53-item development set")
    development_keys = {(item.keyword_id, item.creator_mid) for item in reviews}

    keyword_outputs = load_v3_keyword_outputs(
        stage_one_path,
        excluded_keys=development_keys,
    )
    selected_items = []
    reserve_by_keyword: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for keyword in keyword_outputs:
        keyword_id = keyword["keyword_id"]
        for assessment in keyword["assessments"]:
            item = {
                "keyword_id": keyword_id,
                "topic_spec": keyword["topic_spec"],
                "assessment": assessment,
            }
            if assessment["selected"]:
                item["holdout_reason"] = "frozen_v3_selected_unseen_relation"
                selected_items.append(item)
            else:
                reserve_by_keyword[keyword_id].append(item)

    chosen = list(selected_items)
    chosen_keys = {
        (item["keyword_id"], item["assessment"]["creator_mid"])
        for item in chosen
    }
    selected_counts = Counter(item["keyword_id"] for item in selected_items)
    for keyword in keyword_outputs:
        keyword_id = keyword["keyword_id"]
        target = 5 if selected_counts[keyword_id] else 1
        current = sum(item["keyword_id"] == keyword_id for item in chosen)
        for item in reserve_by_keyword[keyword_id]:
            if current >= target:
                break
            key = (keyword_id, item["assessment"]["creator_mid"])
            if key in chosen_keys:
                continue
            item = {**item, "holdout_reason": "high_score_unselected_false_negative_audit"}
            chosen.append(item)
            chosen_keys.add(key)
            current += 1

    reserve_positions = Counter()
    while len(chosen) < MIN_HOLDOUT_ITEMS:
        added = False
        for keyword in keyword_outputs:
            keyword_id = keyword["keyword_id"]
            position = reserve_positions[keyword_id]
            reserve = reserve_by_keyword[keyword_id]
            while position < len(reserve):
                item = reserve[position]
                position += 1
                key = (keyword_id, item["assessment"]["creator_mid"])
                if key in chosen_keys:
                    continue
                chosen.append({
                    **item,
                    "holdout_reason": "category_balanced_unselected_false_negative_audit",
                })
                chosen_keys.add(key)
                reserve_positions[keyword_id] = position
                added = True
                break
            if len(chosen) >= MIN_HOLDOUT_ITEMS:
                break
        if not added:
            raise ValueError("unseen candidate pool cannot produce the 40-item minimum holdout")

    if len(chosen) > MAX_HOLDOUT_ITEMS:
        raise ValueError(
            f"holdout requires {len(chosen)} items, above the {MAX_HOLDOUT_ITEMS}-item control limit"
        )
    categories = Counter(item["topic_spec"]["category"] for item in chosen)
    required_categories = {"broad", "vertical", "brand", "ambiguous", "low_result"}
    if not required_categories.issubset(categories):
        raise ValueError("holdout does not cover every required keyword category")

    chosen.sort(key=lambda item: (
        item["keyword_id"],
        0 if item["assessment"]["selected"] else 1,
        item["assessment"]["selection_rank"] or 999,
        -item["assessment"]["base_score"],
        item["assessment"]["creator_mid"],
    ))
    for item in chosen:
        item["review_id"] = review_id(
            item["keyword_id"], item["assessment"]["creator_mid"]
        )
    review_ids = [item["review_id"] for item in chosen]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("holdout review IDs are not unique")

    review_items = [visible_review_item(item) for item in chosen]
    evidence_rows = [row for item in chosen for row in visible_evidence_rows(item)]
    visible_payload = {
        "schema_version": HOLDOUT_PACKAGE_VERSION,
        "mode": "new_blind_holdout_unseen_account_keyword_relations",
        "reviewer_count": 1,
        "review_items": review_items,
        "evidence_rows": evidence_rows,
        "allowed_values": {
            "human_relevance": ["relevant", "irrelevant", "uncertain"],
            "human_specialization": ["high", "medium", "low", "unknown"],
            "human_role": [
                "specialist", "generalist", "official", "media", "educator",
                "reviewer", "service", "aggregator", "unrelated", "unknown",
            ],
            "review_complete": [True, False],
        },
        "review_standard_sheet": "审核说明",
    }
    forbidden_visible_keys = {
        "relevance", "specialization", "role", "product_relation", "qualification",
        "base_score", "system_confidence", "model_confidence", "selected",
        "selection_rank", "v2_selected", "v3_selected", "gate_status",
        "qualification_status", "frozen_human_status",
    }
    visible_keys = set().union(*(item.keys() for item in review_items))
    if visible_keys.intersection(forbidden_visible_keys):
        raise ValueError("blind review payload exposes hidden system fields")

    review_data_path = output / "p0c-v3-blind-holdout-data.json"
    private_map_path = output / "p0c-v3-blind-holdout-private-map.json"
    selection_path = output / "p0c-v3-frozen-holdout-selection.json"
    summary_path = output / "holdout-summary.json"
    json_dump(review_data_path, visible_payload)
    json_dump(private_map_path, {
        "schema_version": HOLDOUT_PACKAGE_VERSION,
        "mode": "private_hidden_mapping_not_for_blind_workbook",
        "items": [{
            "review_id": item["review_id"],
            "keyword_id": item["keyword_id"],
            "creator_mid": item["assessment"]["creator_mid"],
            "holdout_reason": item["holdout_reason"],
            "frozen_v3_selected": item["assessment"]["selected"],
            "frozen_v3_selection_rank": item["assessment"]["selection_rank"],
            "v3_assessment": item["assessment"],
        } for item in chosen],
    })
    json_dump(selection_path, {
        "schema_version": HOLDOUT_PACKAGE_VERSION,
        "code_commit_sha": current_sha,
        "selection_pool": "all frozen account-keyword relations excluding the 53-item development set",
        "selection_uses_human_labels": False,
        "qualification_uses_human_labels": False,
        "ranking_uses_human_labels": False,
        "keywords": [{
            "keyword_id": keyword["keyword_id"],
            "selected_mids": keyword["v3_selected_mids"],
        } for keyword in keyword_outputs],
        "entered_p0d": False,
    })
    selected_total = sum(
        item["assessment"]["selected"] for item in chosen
    )
    summary = {
        "schema_version": HOLDOUT_PACKAGE_VERSION,
        "created_at": datetime.now(timezone.utc),
        "code_commit_sha": current_sha,
        "review_item_count": len(chosen),
        "evidence_row_count": len(evidence_rows),
        "frozen_v3_selected_review_item_count": selected_total,
        "false_negative_audit_item_count": len(chosen) - selected_total,
        "category_counts": dict(categories),
        "development_relation_count_excluded": len(development_keys),
        "old_human_labels_in_workbook": False,
        "system_labels_in_workbook": False,
        "system_scores_in_workbook": False,
        "selection_state_in_workbook": False,
        "gate_metrics_in_workbook": False,
        "reviewer_count": 1,
        "network_calls": 0,
        "new_llm_calls": 0,
        "uapi_attempts": 0,
        "entered_p0d": False,
    }
    json_dump(summary_path, summary)
    json_dump(output / "manifest.json", {
        "schema_version": HOLDOUT_PACKAGE_VERSION,
        "created_at": datetime.now(timezone.utc),
        "code_commit_sha": current_sha,
        "inputs": {
            "stage_one_sha256": file_sha256(stage_one_path),
            "development_human_import_sha256": file_sha256(human_import_path),
            "development_manifest_sha256": file_sha256(development_round / "manifest.json"),
            "development_selection_sha256": file_sha256(
                development_round / "v3-frozen-selections.json"
            ),
        },
        "outputs": {
            "review_data_sha256": file_sha256(review_data_path),
            "private_map_sha256": file_sha256(private_map_path),
            "frozen_selection_sha256": file_sha256(selection_path),
            "summary_sha256": file_sha256(summary_path),
        },
        "network_calls": 0,
        "new_llm_calls": 0,
        "uapi_attempts": 0,
        "entered_p0d": False,
    })
    print(json.dumps({
        "review_item_count": len(chosen),
        "frozen_v3_selected_review_item_count": selected_total,
        "false_negative_audit_item_count": len(chosen) - selected_total,
        "category_counts": dict(categories),
        "output": str(output),
        "entered_p0d": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
