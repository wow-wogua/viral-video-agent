from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.models import AnalysisJob, User
from src.db.session import Base
from src.intelligence.competitor_evaluation import aggregate_evaluation, evaluate_keyword
from src.intelligence.competitor_scoring import MAX_CREATOR_AUDITS, aggregate_candidates, rank_creator_audits
from src.intelligence.competitor_service import analyze_competitors
from src.intelligence.competitor_store import get_competitor_results, persist_competitor_analysis
from src.intelligence.contracts import CreatorSample, CreatorSemanticAssessment, RelevanceDecision, SearchRequest
from src.intelligence.creator_providers import (
    BILIBILI_CREATOR_PROVIDER_VERSION,
    CREATOR_IMPORT_PROVIDER_VERSION,
    BilibiliDevelopmentCreatorProvider,
    ImportCreatorProvider,
)
from src.intelligence.evaluation import EvaluationKeyword, validate_evaluation_file
from src.intelligence.providers import ImportSearchProvider
from src.intelligence.relevance import CreatorLabelingResult, LLMRelevanceLabeler, RelevanceContext
from src.intelligence.search_service import SearchSnapshotBundle, execute_search_snapshot
from src.intelligence.snapshots import persist_search_snapshot


def json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def sha12(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def load_frozen_snapshots(path: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for snapshot_path in sorted((path / "development").glob("*.json")):
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        keyword = payload["crawl_run"]["request"]["keyword"]
        if keyword in result:
            raise ValueError("P0-B evidence contains duplicate development snapshots for one keyword")
        result[keyword] = payload
    return result


def frozen_search_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    crawl_run = payload["crawl_run"]
    request = crawl_run["request"]
    source_provider = crawl_run["provider"]
    videos_by_page: dict[int, list[dict[str, Any]]] = {}
    for video in payload["videos"]:
        videos_by_page.setdefault(int(video["source_page"]), []).append(video)
    pages = []
    for page in crawl_run["pages"]:
        results = []
        for video in sorted(videos_by_page.get(page["page_number"], []), key=lambda item: item["source_rank"]):
            results.append({
                key: video.get(key)
                for key in (
                    "bvid", "title", "source_url", "aid", "creator_mid", "creator_name", "description",
                    "tags", "partition", "published_at", "duration_seconds", "cover_url", "view", "like",
                    "coin", "favorite", "reply", "share", "danmaku", "observed_at", "missing_fields",
                )
            })
        pages.append({
            "page_number": page["page_number"],
            "status": page["status"],
            "source_url": page.get("source_url"),
            "requested_at": page.get("requested_at"),
            "completed_at": page.get("completed_at"),
            "native_filters": {
                **(page.get("native_filters") or {}),
                "import_replay": True,
                "source_provider_name": source_provider["provider_name"],
                "source_provider_version": source_provider["provider_version"],
                "source_crawl_run_id": crawl_run["crawl_run_id"],
                "source_raw_result_count": page["raw_result_count"],
                "source_normalized_result_count": page["normalized_result_count"],
            },
            "local_filters": page.get("local_filters") or {},
            "error_code": page.get("error_code"),
            "error_summary": page.get("error_summary"),
            "results": results,
        })
    return {
        "schema_version": "search-import.p0.1",
        "source_name": "p0-b-frozen-snapshot-import-replay",
        "provider_version": source_provider["provider_version"],
        "snapshot_at": crawl_run["completed_at"] or crawl_run["started_at"],
        "keyword": request["keyword"],
        "sort_mode": request["sort_mode"],
        "time_range": request["time_range"],
        "partition": request.get("partition"),
        "pages": pages,
    }


async def replay_search(keyword: EvaluationKeyword, frozen_payload: dict[str, Any]) -> SearchSnapshotBundle:
    import_payload = frozen_search_import_payload(frozen_payload)
    provider = ImportSearchProvider.from_json(import_payload)
    return await execute_search_snapshot(
        provider,
        SearchRequest(
            keyword=keyword.keyword,
            sort_mode=import_payload["sort_mode"],
            time_range=import_payload["time_range"],
            partition=import_payload["partition"],
            max_pages=len(import_payload["pages"]),
            idempotency_key=f"p0c-replay-{keyword.id}-{uuid.uuid4()}",
        ),
    )


def sample_to_import_entry(sample: CreatorSample) -> dict[str, Any]:
    return {
        "creator_mid": sample.creator_mid,
        "creator_name": sample.creator_name,
        "profile_url": sample.profile_url,
        "status": sample.status.value,
        "observed_at": sample.observed_at,
        "source_url": sample.source_url,
        "source_provider_name": sample.source_provider_name,
        "source_provider_version": sample.source_provider_version,
        "follower_count": sample.follower_count,
        "uploads": [{
            key: getattr(video, key)
            for key in (
                "bvid", "title", "source_url", "description", "tags", "partition", "published_at",
                "duration_seconds", "cover_url", "view", "like", "coin", "favorite", "reply", "share",
                "danmaku", "missing_fields",
            )
        } for video in sample.uploads],
        "missing_reason": sample.missing_reason,
        "raw_payload_hash": sample.raw_payload_hash,
    }


class CachingLabeler:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.delegate = LLMRelevanceLabeler()
        self.calls = 0
        self.cache_hits = 0

    async def label_creator(self, context, creator_mid, creator_name, videos, evidence_ids):
        identity = json.dumps({
            "keyword": context.keyword,
            "category": context.category,
            "intent": context.intent_definition,
            "creator_mid": creator_mid,
            "videos": [(video.bvid, video.title, video.description, list(video.tags or [])) for video in videos],
        }, ensure_ascii=False, sort_keys=True, default=str)
        path = self.root / f"{sha12(identity)}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.cache_hits += 1
            return CreatorLabelingResult(
                decisions=[
                    RelevanceDecision.model_validate(item).model_copy(
                        update={"evidence_ids": evidence_ids.get(item["bvid"], [])}
                    )
                    for item in payload["decisions"]
                ],
                assessment=CreatorSemanticAssessment.model_validate(payload["assessment"]),
            )
        result = await self.delegate.label_creator(context, creator_mid, creator_name, videos, evidence_ids)
        self.calls += 1
        json_dump(path, {
            "decisions": [item.model_dump(mode="json") for item in result.decisions],
            "assessment": result.assessment.model_dump(mode="json"),
        })
        return result


async def capture_creator_samples(
    bundles: dict[str, SearchSnapshotBundle],
    keywords: list[EvaluationKeyword],
    output: Path,
    *,
    max_creator_audits: int,
) -> dict[str, dict[str, Any]]:
    progress_path = output / "creator-capture-progress.json"
    cache: dict[str, dict[str, Any]] = {}
    if progress_path.exists():
        existing = json.loads(progress_path.read_text(encoding="utf-8"))
        cache = {entry["creator_mid"]: entry for entry in existing.get("creators", [])}
    targets: dict[str, tuple[str, str]] = {}
    for keyword in keywords:
        context = RelevanceContext(
            keyword=keyword.keyword,
            category=keyword.category.value,
            intent_definition=keyword.intent_definition,
            allowed_subtopics=tuple(keyword.allowed_subtopics),
            exclusion_rules=tuple(keyword.exclusion_rules),
        )
        candidates = rank_creator_audits(aggregate_candidates(bundles[keyword.id].videos), context)
        for candidate in candidates[:max_creator_audits]:
            targets.setdefault(candidate.creator_mid, (candidate.creator_mid, candidate.creator_name))
    pending = [target for mid, target in targets.items() if mid not in cache]
    provider = BilibiliDevelopmentCreatorProvider()
    try:
        for index, (mid, name) in enumerate(pending, 1):
            sample = await provider.fetch_creator(mid, name)
            cache[mid] = sample_to_import_entry(sample)
            if index % 5 == 0 or index == len(pending):
                json_dump(progress_path, {
                    "provider": provider.capabilities.model_dump(mode="json"),
                    "target_count": len(targets),
                    "completed_count": len(cache),
                    "creators": list(cache.values()),
                })
            print(f"creator_capture {index}/{len(pending)} status={sample.status.value}", flush=True)
    finally:
        await provider.close()
    return cache


async def prelabel_creator_samples(
    bundles: dict[str, SearchSnapshotBundle],
    keywords: list[EvaluationKeyword],
    creator_provider: ImportCreatorProvider,
    labeler: CachingLabeler,
    *,
    max_creator_audits: int,
) -> None:
    semaphore = asyncio.Semaphore(4)
    completed = 0
    lock = asyncio.Lock()

    async def label_one(candidate, context: RelevanceContext) -> None:
        nonlocal completed
        async with semaphore:
            sample = await creator_provider.fetch_creator(candidate.creator_mid, candidate.creator_name)
            combined = {video.bvid: video for video in candidate.search_videos}
            for video in sample.uploads:
                combined[video.bvid] = video
            await labeler.label_creator(
                context,
                candidate.creator_mid,
                candidate.creator_name,
                list(combined.values()),
                {},
            )
        async with lock:
            completed += 1
            if completed % 20 == 0:
                print(f"llm_prelabel {completed}", flush=True)

    tasks = []
    for keyword in keywords:
        context = RelevanceContext(
            keyword=keyword.keyword,
            category=keyword.category.value,
            intent_definition=keyword.intent_definition,
            allowed_subtopics=tuple(keyword.allowed_subtopics),
            exclusion_rules=tuple(keyword.exclusion_rules),
        )
        candidates = rank_creator_audits(aggregate_candidates(bundles[keyword.id].videos), context)
        tasks.extend(
            label_one(candidate, context)
            for candidate in candidates[:max_creator_audits]
        )
    await asyncio.gather(*tasks)


async def create_database(output: Path):
    database_path = output / "p0c-evaluation.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        user = User(email=f"p0c-{uuid.uuid4()}@example.test", hashed_password="x")
        db.add(user)
        await db.commit()
        return engine, factory, user.id


async def create_job(factory, user_id, keyword: EvaluationKeyword) -> uuid.UUID:
    async with factory() as db:
        job = AnalysisJob(
            user_id=user_id,
            query=f"P0-C private evaluation {keyword.id}",
            platforms=["bilibili"],
            task_mode="content_intelligence",
            keyword=keyword.keyword,
            sort_mode="relevance",
            time_range="all",
            max_pages=5,
            analysis_mode="standard",
            request_filters={"private_evaluation": True},
            idempotency_key=f"p0c-eval-{keyword.id}-{uuid.uuid4()}",
        )
        db.add(job)
        await db.commit()
        return job.id


def traceability_check(result: dict[str, Any]) -> dict[str, Any]:
    failures = []
    for selected in result["selected"]:
        if not selected["search_candidate_sources"]:
            failures.append("selected creator missing search candidate source")
        if not selected["creator_sample_sources"]:
            failures.append("selected creator missing creator sample source")
        if not selected["evidence_ids"]:
            failures.append("selected creator missing evidence ids")
        if set(selected["component_scores"]) != set(selected["component_details"]):
            failures.append("selected creator score is not decomposable")
    return {"passed": not failures, "failure_count": len(failures), "failures": failures}


async def main_async(args) -> int:
    repo = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("private P0-C evaluation output must remain outside the Git repository")
    output.mkdir(parents=True, exist_ok=True)

    suite = validate_evaluation_file(args.baseline.resolve(), require_reviewed=True)
    frozen = load_frozen_snapshots(args.p0b.resolve())
    if set(frozen) != {keyword.keyword for keyword in suite.keywords}:
        raise ValueError("P0-B development evidence does not match the frozen 20-keyword baseline")

    bundles: dict[str, SearchSnapshotBundle] = {}
    for keyword in suite.keywords:
        bundles[keyword.id] = await replay_search(keyword, frozen[keyword.keyword])
    json_dump(output / "input-crawl-runs.json", [{
        "keyword_id": keyword.id,
        "new_crawl_run_id": bundles[keyword.id].crawl_run.crawl_run_id,
        "source_crawl_run_id": frozen[keyword.keyword]["crawl_run"]["crawl_run_id"],
        "source_provider": frozen[keyword.keyword]["crawl_run"]["provider"],
        "replay_provider": bundles[keyword.id].crawl_run.provider.model_dump(mode="json"),
        "source_snapshot_at": frozen[keyword.keyword]["crawl_run"]["completed_at"],
        "replay_identity": "import replay; not a live search on the evaluation date",
    } for keyword in suite.keywords])

    creator_cache = await capture_creator_samples(
        bundles,
        suite.keywords,
        output,
        max_creator_audits=args.max_creator_audits,
    )
    creator_import_payload = {
        "schema_version": "creator-import.p0.1",
        "source_name": "p0-c-public-creator-capture-import-replay",
        "provider_version": CREATOR_IMPORT_PROVIDER_VERSION,
        "creators": list(creator_cache.values()),
    }
    json_dump(output / "creator-import-replay.json", creator_import_payload)
    creator_provider = ImportCreatorProvider.from_json(creator_import_payload)
    labeler = CachingLabeler(output / "llm-label-cache")
    await prelabel_creator_samples(
        bundles,
        suite.keywords,
        creator_provider,
        labeler,
        max_creator_audits=args.max_creator_audits,
    )
    engine, factory, user_id = await create_database(output)
    keyword_metrics = []
    detailed_index = []
    traceability = []
    sample_statuses = Counter()
    try:
        for index, keyword in enumerate(suite.keywords, 1):
            context = RelevanceContext(
                keyword=keyword.keyword,
                category=keyword.category.value,
                intent_definition=keyword.intent_definition,
                allowed_subtopics=tuple(keyword.allowed_subtopics),
                exclusion_rules=tuple(keyword.exclusion_rules),
            )
            analysis = await analyze_competitors(
                bundles[keyword.id],
                creator_provider,
                labeler,
                context,
                max_creator_audits=args.max_creator_audits,
            )
            job_id = await create_job(factory, user_id, keyword)
            async with factory() as db:
                await persist_search_snapshot(db, job_id, bundles[keyword.id])
                await persist_competitor_analysis(db, job_id, analysis)
                await db.commit()
                result = await get_competitor_results(db, job_id)
            keyword_path = output / "keywords" / f"{keyword.id}.json"
            json_dump(keyword_path, result)
            detailed_index.append({
                "keyword_id": keyword.id,
                "category": keyword.category.value,
                "crawl_run_id": result["crawl_run_id"],
                "candidate_creator_count": result["candidate_creator_count"],
                "audited_creator_count": result["audited_creator_count"],
                "selected_count": result["selected_count"],
                "result_file": str(keyword_path.relative_to(output)),
            })
            for candidate in result["candidates"]:
                sample = candidate.get("creator_sample") or {}
                sample_statuses[sample.get("status", "missing")] += 1
            metric = evaluate_keyword(
                keyword,
                selected_mids=[item["creator_mid"] for item in result["selected"]],
                retrieved_mids=[candidate.creator_mid for candidate in aggregate_candidates(bundles[keyword.id].videos)],
            )
            keyword_metrics.append(metric)
            traceability.append(traceability_check(result))
            print(f"keyword_evaluation {index}/{len(suite.keywords)} selected={result['selected_count']}", flush=True)
    finally:
        await creator_provider.close()
        await engine.dispose()

    evaluation = aggregate_evaluation(keyword_metrics)
    traceability_passed = all(item["passed"] for item in traceability)
    overall = evaluation["overall"]
    precision_passed = (
        overall["selected_precision"] is not None
        and overall["selected_precision"] >= 0.8
        and overall["strict_precision_at_5"] is not None
        and overall["strict_precision_at_5"] >= 0.8
    )
    false_positive_passed = (
        overall["irrelevant_false_positive_rate"] is not None
        and overall["irrelevant_false_positive_rate"] <= 0.1
    )
    technical_passed = precision_passed and false_positive_passed and traceability_passed
    single_reviewer = all(keyword.reviewer_count == 1 for keyword in suite.keywords)
    gate_status = "with_reservation" if technical_passed and single_reviewer else "passed" if technical_passed else "failed"
    gate = {
        "generated_at": datetime.now(timezone.utc),
        "gate_status": gate_status,
        "entered_p0d": False,
        "scoring_version": "competitor-score.p0.1",
        "qualification_policy_version": "creator-qualification.p0.1",
        "schema_version": "content-intelligence.p0.1",
        "creator_provider_capture_version": BILIBILI_CREATOR_PROVIDER_VERSION,
        "creator_import_provider_version": CREATOR_IMPORT_PROVIDER_VERSION,
        "max_creator_audits_per_keyword": args.max_creator_audits,
        "precision_gate_passed": precision_passed,
        "false_positive_gate_passed": false_positive_passed,
        "traceability_gate_passed": traceability_passed,
        "single_human_reviewer": single_reviewer,
        "inter_reviewer_agreement_available": False,
        "sample_status_counts": dict(sample_statuses),
        "llm_calls": labeler.calls,
        "llm_cache_hits": labeler.cache_hits,
        "evaluation": evaluation,
        "traceability": {
            "passed": traceability_passed,
            "keyword_failure_count": sum(not item["passed"] for item in traceability),
        },
        "truthfulness_boundaries": [
            "search inputs are imported replays of the frozen P0-B public snapshots, not live searches on the evaluation date",
            "sample share is not market share",
            "Development Providers do not establish production commercial authorization or SLA",
            "the evaluation has one real human reviewer and no inter-reviewer agreement evidence",
            "P0-C does not include representative videos, ASR, deterministic business metrics, IntelligenceReport, frontend report, or deployment",
        ],
    }
    calibration = {
        "initial_policy": "competitor-score.p0.1",
        "adjustment_applied": False,
        "reason": (
            "initial frozen policy met the technical Gate; no calibration was needed"
            if technical_passed
            else "no weight adjustment was applied because remaining errors require provider, label coverage, or human review evidence rather than keyword-specific tuning"
        ),
        "calibration_cycles_used": 0,
        "maximum_allowed_cycles": 1,
        "before": evaluation,
        "after": evaluation,
        "negative_changes": [],
    }
    json_dump(output / "keyword-index.json", detailed_index)
    json_dump(output / "evaluation-before.json", evaluation)
    json_dump(output / "evaluation-after.json", evaluation)
    json_dump(output / "calibration-decision.json", calibration)
    json_dump(output / "gate-summary.json", gate)
    summary_lines = [
        "# P0-C Gate candidate",
        "",
        f"- Status: {gate_status}",
        f"- Selected precision: {overall['selected_precision']}",
        f"- Strict Precision@5: {overall['strict_precision_at_5']}",
        f"- Irrelevant false-positive rate: {overall['irrelevant_false_positive_rate']}",
        f"- Retrieval Recall: {overall['retrieval_recall']}",
        f"- Output coverage: {overall['output_coverage']}",
        f"- Abstention keywords: {overall['abstention_keyword_count']}",
        f"- Single real human reviewer: {single_reviewer}",
        "- Inter-reviewer agreement: unavailable",
        "- Entered P0-D: no",
    ]
    (output / "gate-summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"gate_status={gate_status} output={output}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded P0-C private 20-keyword evaluation.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("p0b", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-creator-audits", type=int, default=MAX_CREATOR_AUDITS, choices=range(1, MAX_CREATOR_AUDITS + 1))
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
