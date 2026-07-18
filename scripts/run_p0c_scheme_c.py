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
from src.intelligence.contracts import CreatorQualificationStatus, CreatorProductRelation
from src.intelligence.creator_topic import (
    assess_creator_topic,
    route_keyword_reviews,
    select_v2_top_competitors,
    topic_spec_from_evaluation_keyword,
)
from src.intelligence.evaluation import CreatorReviewDecision, validate_evaluation_file


SCHEME_C_RUN_VERSION = "p0c-scheme-c-run.p0.1"
REVIEW_PACKAGE_VERSION = "p0c-scheme-c-account-review.p0.1"
MAX_REVIEW_ITEMS = 120


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


def _frozen_human_status(keyword: Any) -> dict[str, str]:
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


def _summary_text(values: list[str], *, maximum: int = 320) -> str:
    text = "；".join(value.strip() for value in values if value.strip())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _review_selection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items.sort(key=lambda item: (
        item["route"].priority or 99,
        -int(item["assessment"].selected),
        -item["assessment"].base_score,
        item["topic_spec"].keyword_id,
        item["assessment"].creator_mid,
    ))
    required_selected = [
        item for item in items
        if "provisional_v2_selected_without_frozen_human_label" in item["route"].reasons
    ]
    if len(required_selected) > MAX_REVIEW_ITEMS:
        raise ValueError(
            f"{len(required_selected)} unlabelled v2 selected accounts exceed the {MAX_REVIEW_ITEMS}-item hard limit"
        )
    selected = items[:MAX_REVIEW_ITEMS]
    selected_ids = {item["route"].review_id for item in selected}
    missing_required = [
        item["route"].review_id for item in required_selected
        if item["route"].review_id not in selected_ids
    ]
    if missing_required:
        raise ValueError("review trimming omitted provisional v2 selected accounts")
    return selected


def _visible_review_item(item: dict[str, Any]) -> dict[str, Any]:
    route = item["route"]
    assessment = item["assessment"]
    topic_spec = item["topic_spec"]
    evidence = assessment.evidence
    sample = item["candidate"].get("creator_sample") or {}
    neutral = [
        f"主页：{evidence.profile_url}" if evidence.profile_url else "主页：缺失",
        f"粉丝数：{evidence.follower_count}" if evidence.follower_count is not None else "粉丝数：缺失",
        f"冻结来源：{sample.get('provider_name', 'unknown')}/{sample.get('provider_version', 'unknown')}",
    ]
    return {
        "review_id": route.review_id,
        "keyword_id": topic_spec.keyword_id,
        "keyword": topic_spec.keyword,
        "intent_definition": topic_spec.intent_definition,
        "allowed_subtopics_summary": _summary_text(topic_spec.allowed_subtopics),
        "exclusion_rules_summary": _summary_text(topic_spec.exclusion_rules),
        "creator_name": assessment.creator_name,
        "creator_mid": assessment.creator_mid,
        "neutral_public_info": "；".join(neutral),
        "sample_status": evidence.sample_status.value,
        "sample_upload_count": evidence.sampled_upload_count,
        "recent_30d_upload_count": evidence.recent_30d_upload_count,
        "recent_90d_upload_count": evidence.recent_90d_upload_count,
        "human_relevance": None,
        "human_specialization": None,
        "human_role": None,
        "human_reason": "",
        "review_complete": None,
    }


def _visible_evidence_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    assessment = item["assessment"]
    examples = assessment.evidence.upload_examples or assessment.evidence.search_examples
    evidence_type = "creator_upload" if assessment.evidence.upload_examples else "search_snapshot_fallback"
    rows = []
    for index, evidence in enumerate(examples, 1):
        metrics = f"播放量={evidence.view}" if evidence.view is not None else "播放量=缺失"
        rows.append({
            "review_id": item["route"].review_id,
            "evidence_sequence": index,
            "evidence_type": evidence_type,
            "title": evidence.title,
            "description_summary": evidence.description or "",
            "published_at": evidence.published_at,
            "frozen_snapshot_metrics": metrics,
            "source_url": evidence.source_url,
            "evidence_reference": "|".join(evidence.evidence_ids),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the offline P0-C scheme-C assessment and blind-review package.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("v1_gate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    baseline = args.baseline.resolve()
    v1_gate = args.v1_gate.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("private scheme-C output must remain outside the Git repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("scheme-C output directory must be new and empty")
    required_gate_files = [
        v1_gate / "creator-import-replay.json",
        v1_gate / "evaluation-after.json",
        v1_gate / "gate-summary.json",
    ]
    if any(not path.is_file() for path in required_gate_files):
        raise ValueError("v1 Gate directory is incomplete")
    cache_files = list((v1_gate / "llm-label-cache").glob("*.json"))
    keyword_files = list((v1_gate / "keywords").glob("*.json"))
    if len(cache_files) != 400 or len(keyword_files) != 20:
        raise ValueError("v1 Gate must retain exactly 400 cached semantic results and 20 keyword outputs")
    output.mkdir(parents=True, exist_ok=False)

    suite = validate_evaluation_file(baseline, require_reviewed=True)
    saved_v1 = json.loads((v1_gate / "evaluation-after.json").read_text(encoding="utf-8"))
    v1_metrics = []
    provisional_v2_metrics = []
    topic_specs = []
    private_keyword_outputs = []
    routed_items = []
    relation_counts: Counter[str] = Counter()
    v1_selected_total = v2_selected_total = selection_difference_total = 0

    for keyword in suite.keywords:
        result_path = v1_gate / "keywords" / f"{keyword.id}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        retrieved_mids = [item["creator_mid"] for item in result["candidates"]]
        v1_selected_mids = {item["creator_mid"] for item in result["selected"]}
        v1_metrics.append(evaluate_keyword(
            keyword,
            selected_mids=list(v1_selected_mids),
            retrieved_mids=retrieved_mids,
        ))
        topic_spec = topic_spec_from_evaluation_keyword(keyword)
        topic_specs.append(topic_spec.model_dump(mode="json"))
        assessments = [
            assess_creator_topic(topic_spec, candidate, result.get("evidence") or [])
            for candidate in result["candidates"]
        ]
        assessments = select_v2_top_competitors(assessments)
        v2_selected_mids = {item.creator_mid for item in assessments if item.selected}
        provisional_v2_metrics.append(evaluate_keyword(
            keyword,
            selected_mids=[item.creator_mid for item in assessments if item.selected],
            retrieved_mids=retrieved_mids,
        ))
        human_status = _frozen_human_status(keyword)
        routes = route_keyword_reviews(
            assessments,
            v1_selected_mids=v1_selected_mids,
            frozen_human_status=human_status,
        )
        candidate_by_mid = {item["creator_mid"]: item for item in result["candidates"]}
        assessment_by_mid = {item.creator_mid: item for item in assessments}
        for route in routes:
            if route.include_in_blind_workbook:
                routed_items.append({
                    "route": route,
                    "assessment": assessment_by_mid[route.creator_mid],
                    "topic_spec": topic_spec,
                    "candidate": candidate_by_mid[route.creator_mid],
                    "frozen_human_status": human_status.get(route.creator_mid),
                    "v1_selected": route.creator_mid in v1_selected_mids,
                })
        relation_counts.update(item.product_relation.value for item in assessments)
        v1_selected_total += len(v1_selected_mids)
        v2_selected_total += len(v2_selected_mids)
        selection_difference_total += len(v1_selected_mids.symmetric_difference(v2_selected_mids))
        private_keyword_outputs.append({
            "keyword_id": keyword.id,
            "topic_spec": topic_spec.model_dump(mode="json"),
            "v1_selected_mids": sorted(v1_selected_mids),
            "v2_selected_mids": sorted(v2_selected_mids),
            "selection_difference_mids": sorted(v1_selected_mids.symmetric_difference(v2_selected_mids)),
            "assessments": [item.model_dump(mode="json") for item in assessments],
            "review_routes": [item.model_dump(mode="json") for item in routes],
        })

    recomputed_v1 = aggregate_evaluation(v1_metrics)
    if recomputed_v1 != saved_v1:
        raise ValueError("current code cannot exactly reproduce the frozen v1 Gate evaluation")
    expected = {
        "selected_count": 38,
        "correct_selected_count": 7,
        "known_irrelevant_selected_count": 2,
        "unresolved_selected_count": 29,
        "selected_precision": 7 / 38,
        "strict_precision_at_5": 7 / 21,
        "irrelevant_false_positive_rate": 2 / 38,
        "retrieval_recall": 21 / 36,
        "output_coverage": 17 / 21,
    }
    if any(recomputed_v1["overall"].get(key) != value for key, value in expected.items()):
        raise ValueError("v1 Gate metrics do not match the frozen acceptance baseline")

    selected_review_items = _review_selection(routed_items)
    review_rows = [_visible_review_item(item) for item in selected_review_items]
    evidence_rows = [
        row
        for item in selected_review_items
        for row in _visible_evidence_rows(item)
    ]
    review_ids = [item["review_id"] for item in review_rows]
    if len(review_ids) != len(set(review_ids)):
        raise ValueError("scheme-C blind-review package contains duplicate review_id values")
    if len(review_rows) > MAX_REVIEW_ITEMS:
        raise ValueError("scheme-C blind-review package exceeds the hard item limit")
    required_v2_selected = {
        item["route"].review_id
        for item in routed_items
        if "provisional_v2_selected_without_frozen_human_label" in item["route"].reasons
    }
    if not required_v2_selected.issubset(set(review_ids)):
        raise ValueError("scheme-C blind-review package omitted an unlabelled v2 selected account")

    priority_counts = Counter(item["route"].priority for item in selected_review_items)
    reason_counts = Counter(
        reason
        for item in selected_review_items
        for reason in item["route"].reasons
    )
    provisional_v2 = aggregate_evaluation(provisional_v2_metrics)
    baseline_reproduction_path = output / "baseline-reproduction.json"
    json_dump(baseline_reproduction_path, {
        "formula_version": recomputed_v1["formula_version"],
        "exact_match_to_v1_gate": True,
        "evaluation": recomputed_v1,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
    })
    json_dump(output / "topic-specs.json", topic_specs)
    json_dump(output / "v2-keyword-assessments.json", private_keyword_outputs)
    json_dump(output / "provisional-v2-evaluation.json", {
        "status": "pre_human_overlay_not_a_final_gate",
        "evaluation": provisional_v2,
        "recall_scope": "frozen qualified_reference set only",
        "sampled_false_negative_audit_is_not_full_recall": True,
    })
    review_data_path = output / "p0c-scheme-c-account-review-v1-data.json"
    json_dump(review_data_path, {
        "schema_version": REVIEW_PACKAGE_VERSION,
        "mode": "gate_blind_review",
        "reviewer_count": 1,
        "review_items": review_rows,
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
    })
    private_map_path = output / "p0c-scheme-c-account-review-v1-private-map.json"
    json_dump(private_map_path, {
        "schema_version": REVIEW_PACKAGE_VERSION,
        "mode": "private_hidden_mapping_not_for_blind_sheets",
        "items": [{
            "review_id": item["route"].review_id,
            "keyword_id": item["topic_spec"].keyword_id,
            "creator_mid": item["assessment"].creator_mid,
            "v1_selected": item["v1_selected"],
            "v2_selected": item["assessment"].selected,
            "frozen_human_status": item["frozen_human_status"],
            "review_route": item["route"].model_dump(mode="json"),
            "system_assessment": item["assessment"].model_dump(mode="json"),
            "evidence_ids": item["assessment"].evidence.evidence_ids,
        } for item in selected_review_items],
    })
    summary_path = output / "scheme-c-summary.json"
    json_dump(summary_path, {
        "run_version": SCHEME_C_RUN_VERSION,
        "generated_at": datetime.now(timezone.utc),
        "entered_p0d": False,
        "v1_selected_count": v1_selected_total,
        "v2_provisional_selected_count": v2_selected_total,
        "v1_v2_selection_difference_count": selection_difference_total,
        "product_relation_counts": dict(relation_counts),
        "review_item_count": len(review_rows),
        "review_evidence_row_count": len(evidence_rows),
        "review_priority_counts": {str(key): value for key, value in sorted(priority_counts.items())},
        "review_reason_counts": dict(reason_counts),
        "all_unlabelled_v2_selected_in_review": True,
        "reviewer_count": 1,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
        "gate_status": "waiting_for_scheme_c_blind_human_review",
    })
    manifest_path = output / "scheme-c-manifest.json"
    json_dump(manifest_path, {
        "run_version": SCHEME_C_RUN_VERSION,
        "created_at": datetime.now(timezone.utc),
        "inputs": {
            "baseline_sha256": file_sha256(baseline),
            "creator_import_replay_sha256": file_sha256(v1_gate / "creator-import-replay.json"),
            "v1_evaluation_sha256": file_sha256(v1_gate / "evaluation-after.json"),
            "v1_gate_summary_sha256": file_sha256(v1_gate / "gate-summary.json"),
            "llm_cache_file_count": len(cache_files),
            "keyword_result_file_count": len(keyword_files),
        },
        "outputs": {
            "baseline_reproduction_sha256": file_sha256(baseline_reproduction_path),
            "review_data_sha256": file_sha256(review_data_path),
            "private_map_sha256": file_sha256(private_map_path),
            "summary_sha256": file_sha256(summary_path),
        },
        "network_calls": 0,
        "uapi_attempts": 0,
        "new_llm_calls": 0,
        "entered_p0d": False,
    })
    print(json.dumps({
        "output": str(output),
        "review_item_count": len(review_rows),
        "v1_selected_count": v1_selected_total,
        "v2_provisional_selected_count": v2_selected_total,
        "v1_v2_selection_difference_count": selection_difference_total,
        "product_relation_counts": dict(relation_counts),
        "uapi_attempts": 0,
        "new_llm_calls": 0,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
