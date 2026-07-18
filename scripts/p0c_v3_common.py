from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.intelligence.competitor_evaluation import map_review_to_evaluation_truth_v3
from src.intelligence.contracts import (
    CreatorProductRelation,
    CreatorTopicAssessment,
    CreatorTopicAssessmentV3,
    HumanCreatorTopicReview,
)
from src.intelligence.creator_topic_v3 import (
    calibrate_creator_topic_v3,
    select_v3_top_competitors,
)


DEVELOPMENT_RUN_VERSION = "p0c-v3-development.p0.1"
HOLDOUT_PACKAGE_VERSION = "p0c-v3-blind-holdout.p0.1"
HUMAN_IMPORT_VERSION = "p0c-v3-human-review-import.p0.1"
GATE_RUN_VERSION = "p0c-v3-holdout-gate.p0.1"


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def git_status(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "status", "--short"], cwd=repo, text=True
    ).strip()


def ensure_private_new_output(repo: Path, output: Path) -> None:
    output = output.resolve()
    try:
        output.relative_to(repo.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("P0-C v3 private output must remain outside the Git repository")
    if output.exists() and any(output.iterdir()):
        raise ValueError("P0-C v3 output directory must be new and empty")
    output.mkdir(parents=True, exist_ok=False)


def load_v3_keyword_outputs(
    stage_one_path: Path,
    *,
    excluded_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    stage_one = json.loads(stage_one_path.read_text(encoding="utf-8"))
    excluded_keys = excluded_keys or set()
    outputs = []
    for item in stage_one:
        category = item["topic_spec"]["category"]
        assessments = [
            calibrate_creator_topic_v3(
                CreatorTopicAssessment.model_validate(assessment),
                category=category,
            )
            for assessment in item["assessments"]
            if (item["keyword_id"], assessment["creator_mid"]) not in excluded_keys
        ]
        selected = select_v3_top_competitors(assessments)
        outputs.append({
            "keyword_id": item["keyword_id"],
            "topic_spec": item["topic_spec"],
            "v2_selected_mids": list(item["v2_selected_mids"]),
            "v3_selected_mids": [
                assessment.creator_mid
                for assessment in sorted(
                    selected,
                    key=lambda value: value.selection_rank or 999,
                )
                if assessment.selected
            ],
            "assessments": [assessment.model_dump(mode="json") for assessment in selected],
        })
    return outputs


def development_truth_by_key(
    keyword_outputs: Sequence[dict[str, Any]],
    reviews: Sequence[HumanCreatorTopicReview],
) -> dict[tuple[str, str], Any]:
    assessment_by_key = {
        (item["keyword_id"], assessment["creator_mid"]): (
            item["topic_spec"]["category"],
            CreatorTopicAssessmentV3.model_validate(assessment),
        )
        for item in keyword_outputs
        for assessment in item["assessments"]
    }
    truth = {}
    for review in reviews:
        category, assessment = assessment_by_key[(review.keyword_id, review.creator_mid)]
        truth[(review.keyword_id, review.creator_mid)] = map_review_to_evaluation_truth_v3(
            review,
            assessment.evidence,
            category=category,
        )
    return truth


def partial_development_metrics(
    keyword_outputs: Sequence[dict[str, Any]],
    truth_by_key: dict[tuple[str, str], Any],
    *,
    selected_field: str,
) -> dict[str, Any]:
    totals = Counter()
    keyword_metrics = []
    for item in keyword_outputs:
        keyword_id = item["keyword_id"]
        selected = list(dict.fromkeys(item[selected_field]))[:5]
        selected_truth = [truth_by_key.get((keyword_id, mid)) for mid in selected]
        correct = sum(
            truth is not None
            and truth.relation == CreatorProductRelation.CORE_COMPETITOR
            for truth in selected_truth
        )
        known_noncore = sum(
            truth is not None
            and truth.relation != CreatorProductRelation.CORE_COMPETITOR
            for truth in selected_truth
        )
        unresolved = sum(truth is None for truth in selected_truth)
        eligible_slots = min(
            5,
            sum(
                key[0] == keyword_id
                and truth.relation == CreatorProductRelation.CORE_COMPETITOR
                for key, truth in truth_by_key.items()
            ),
        )
        totals.update({
            "selected": len(selected),
            "correct": correct,
            "known_noncore": known_noncore,
            "unresolved": unresolved,
            "eligible_slots": eligible_slots,
        })
        keyword_metrics.append({
            "keyword_id": keyword_id,
            "category": item["topic_spec"]["category"],
            "selected_count": len(selected),
            "correct_reviewed_core_count": correct,
            "known_reviewed_noncore_count": known_noncore,
            "unresolved_unreviewed_count": unresolved,
            "eligible_reviewed_core_slots": eligible_slots,
        })
    selected = totals["selected"]
    reviewed_selected = totals["correct"] + totals["known_noncore"]
    eligible = totals["eligible_slots"]
    return {
        "selected_count": selected,
        "correct_reviewed_core_count": totals["correct"],
        "known_reviewed_noncore_count": totals["known_noncore"],
        "unresolved_unreviewed_count": totals["unresolved"],
        "reviewed_selected_count": reviewed_selected,
        "reviewed_selected_precision": (
            totals["correct"] / reviewed_selected if reviewed_selected else None
        ),
        "all_selected_precision_with_unreviewed_as_unresolved": (
            totals["correct"] / selected if selected else None
        ),
        "strict_precision_on_reviewed_core_slots": (
            totals["correct"] / eligible if eligible else None
        ),
        "shortfall_count_on_reviewed_core_slots": max(eligible - totals["correct"], 0),
        "keywords": keyword_metrics,
    }


def relation_counts(keyword_outputs: Iterable[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(
        assessment["qualification"]["relation"]
        for item in keyword_outputs
        for assessment in item["assessments"]
    ))
