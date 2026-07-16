from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intelligence.contracts import PageStatus, SearchRequest
from src.intelligence.evaluation import validate_evaluation_file
from src.intelligence.providers import BilibiliDevelopmentSearchProvider, ImportSearchProvider
from src.intelligence.search_service import SearchSnapshotBundle, execute_search_snapshot


PAGE_REQUIRED_FIELDS = (
    "page_number",
    "status",
    "requested_at",
    "completed_at",
    "request_duration_ms",
    "raw_result_count",
    "normalized_result_count",
    "provider_name",
    "provider_version",
    "native_filters",
    "local_filters",
)


def _json_dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _bundle_payload(bundle: SearchSnapshotBundle) -> dict[str, Any]:
    return {
        "crawl_run": bundle.crawl_run.model_dump(mode="json"),
        "videos": [item.model_dump(mode="json") for item in bundle.videos],
        "creators": [item.model_dump(mode="json") for item in bundle.creators],
        "raw_payloads": bundle.raw_payloads,
    }


def _page_complete(page) -> bool:
    if any(getattr(page, field) is None for field in PAGE_REQUIRED_FIELDS):
        return False
    if not page.source_url:
        return False
    if page.status in {PageStatus.SUCCESS, PageStatus.EMPTY}:
        return bool(page.raw_payload_hash)
    return bool(page.error_code and page.error_summary)


def _manual_entry(baseline_root: Path, keyword_item: dict, cache: dict[Path, dict]) -> dict:
    snapshot_meta = keyword_item["snapshots"][0]
    snapshot_path = (baseline_root / snapshot_meta["snapshot_file"]).resolve()
    if snapshot_path not in cache:
        cache[snapshot_path] = json.loads(snapshot_path.read_text(encoding="utf-8"))
    entries = cache[snapshot_path].get("entries", [])
    for entry in entries:
        if entry.get("keyword") == keyword_item.get("keyword"):
            return entry
    raise ValueError("manual snapshot entry not found for a baseline keyword")


def _import_payload(keyword_item: dict, manual_entry: dict) -> dict[str, Any]:
    results = []
    for item in manual_entry.get("results", []):
        bvid = str(item.get("bvid") or "").strip()
        title = str(item.get("title") or "").strip()
        if not bvid or not title:
            continue
        results.append({
            "bvid": bvid,
            "title": title,
            "source_url": item.get("source_url") or f"https://www.bilibili.com/video/{bvid}",
            "creator_mid": str(item.get("mid")).strip() if item.get("mid") not in {None, ""} else None,
            "creator_name": str(item.get("author") or "").strip() or None,
            "missing_fields": [
                "aid", "description", "tags", "partition", "published_at", "duration_seconds",
                "cover_url", "view", "like", "coin", "favorite", "reply", "share", "danmaku",
            ],
        })
    searched_at = keyword_item["snapshots"][0]["searched_at"]
    return {
        "schema_version": "search-import.p0.1",
        "source_name": "manual-browser-public-search",
        "provider_version": "manual-browser-import.p0-b.1",
        "snapshot_at": searched_at,
        "keyword": keyword_item["keyword"],
        "sort_mode": "relevance",
        "time_range": "all",
        "partition": None,
        "pages": [{
            "page_number": 1,
            "status": "success" if results else "empty",
            "source_url": manual_entry.get("source_url"),
            "requested_at": searched_at,
            "completed_at": searched_at,
            "results": results,
        }],
    }


async def main_async(args) -> int:
    repo = Path(__file__).resolve().parents[1]
    baseline_path = args.baseline.resolve()
    output = args.output.resolve()
    try:
        output.relative_to(repo)
    except ValueError:
        pass
    else:
        raise ValueError("real smoke output must be outside the Git repository")

    validate_evaluation_file(baseline_path, require_reviewed=True)
    baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    keywords = baseline_payload["keywords"]
    baseline_root = baseline_path.parent
    output.mkdir(parents=True, exist_ok=False)

    provider = BilibiliDevelopmentSearchProvider(
        timeout_seconds=args.timeout,
        max_retries=args.retries,
        backoff_base_seconds=args.backoff,
        min_interval_seconds=args.min_interval,
    )
    manual_cache: dict[Path, dict] = {}
    records = []
    page_statuses: Counter[str] = Counter()
    adapter_counts: Counter[str] = Counter()
    original_error_counts: Counter[str] = Counter()
    request_distribution: Counter[int] = Counter()
    complete_pages = 0
    total_pages = 0
    dedup_checks = 0
    mid_dedup_checks = 0
    import_successes = 0
    overlap_numerator = 0
    overlap_denominator = 0

    try:
        for index, keyword_item in enumerate(keywords, 1):
            request = SearchRequest(
                keyword=keyword_item["keyword"],
                max_pages=args.max_pages,
                idempotency_key=f"p0b-smoke-{index:02d}",
            )
            bundle = await execute_search_snapshot(provider, request)
            _json_dump(output / "development" / f"keyword-{index:02d}.json", _bundle_payload(bundle))

            pages = bundle.crawl_run.pages
            page_statuses.update(page.status.value for page in pages)
            adapter_counts.update(
                page.native_filters.get("adapter")
                for page in pages
                if page.native_filters.get("adapter")
            )
            original_error_counts.update(
                page.native_filters.get("original_error_code")
                for page in pages
                if page.native_filters.get("original_error_code")
            )
            request_distribution[request.max_pages] += 1
            total_pages += len(pages)
            complete_pages += sum(_page_complete(page) for page in pages)
            bvids = [video.bvid for video in bundle.videos]
            mids = [creator.mid for creator in bundle.creators]
            dedup_ok = len(bvids) == len(set(bvids)) == bundle.crawl_run.coverage.deduplicated_video_count
            mid_dedup_ok = len(mids) == len(set(mids)) == bundle.crawl_run.coverage.candidate_creator_count
            dedup_checks += int(dedup_ok)
            mid_dedup_checks += int(mid_dedup_ok)

            manual_entry = _manual_entry(baseline_root, keyword_item, manual_cache)
            manual_bvids = [str(item.get("bvid") or "") for item in manual_entry.get("results", [])[:20] if item.get("bvid")]
            current_page_one = [video.bvid for video in bundle.videos if video.source_page == 1][:20]
            overlap = len(set(manual_bvids) & set(current_page_one))
            overlap_numerator += overlap
            overlap_denominator += len(set(manual_bvids))

            import_provider = ImportSearchProvider.from_json(_import_payload(keyword_item, manual_entry))
            import_bundle = await execute_search_snapshot(
                import_provider,
                SearchRequest(
                    keyword=keyword_item["keyword"],
                    max_pages=1,
                    idempotency_key=f"p0b-import-{index:02d}",
                ),
            )
            import_successes += int(import_bundle.crawl_run.coverage.successful_pages == 1)
            _json_dump(
                output / "import-validation" / f"keyword-{index:02d}.json",
                {
                    "crawl_run": import_bundle.crawl_run.model_dump(mode="json"),
                    "videos": [item.model_dump(mode="json") for item in import_bundle.videos],
                    "creators": [item.model_dump(mode="json") for item in import_bundle.creators],
                },
            )
            records.append({
                "keyword_index": index,
                "crawl_status": bundle.crawl_run.status.value,
                "successful_pages": bundle.crawl_run.coverage.successful_pages,
                "requested_pages": request.max_pages,
                "raw_result_count": bundle.crawl_run.coverage.raw_result_count,
                "deduplicated_video_count": bundle.crawl_run.coverage.deduplicated_video_count,
                "candidate_creator_count": bundle.crawl_run.coverage.candidate_creator_count,
                "page_statuses": [page.status.value for page in pages],
                "page_errors": [
                    {"page_number": page.page_number, "status": page.status.value, "error_code": page.error_code, "error_summary": page.error_summary}
                    for page in pages
                    if not page.completed_successfully
                ],
                "page_field_completeness": sum(_page_complete(page) for page in pages) / len(pages) if pages else 0,
                "bvid_dedup_ok": dedup_ok,
                "mid_dedup_ok": mid_dedup_ok,
                "manual_top20_overlap_count": overlap,
                "manual_top20_count": len(set(manual_bvids)),
            })
            print(
                f"keyword {index:02d}/{len(keywords)}: status={bundle.crawl_run.status.value} "
                f"successful_pages={bundle.crawl_run.coverage.successful_pages}/{request.max_pages}"
            )
    finally:
        await provider.close()

    successful_keywords = sum(record["successful_pages"] >= 1 for record in records)
    page_completeness = complete_pages / total_pages if total_pages else 0
    bvid_accuracy = dedup_checks / len(records) if records else 0
    mid_accuracy = mid_dedup_checks / len(records) if records else 0
    overlap_rate = overlap_numerator / overlap_denominator if overlap_denominator else None
    gate_passed = (
        successful_keywords >= 19
        and page_completeness == 1
        and bvid_accuracy == 1
        and mid_accuracy == 1
        and max(request_distribution or {0: 0}) <= 5
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider.capabilities.model_dump(mode="json"),
        "keyword_count": len(records),
        "keywords_with_at_least_one_successful_page": successful_keywords,
        "keyword_success_rate": successful_keywords / len(records) if records else 0,
        "requested_pages_distribution": dict(sorted(request_distribution.items())),
        "page_status_counts": dict(sorted(page_statuses.items())),
        "adapter_counts": dict(sorted(adapter_counts.items())),
        "original_error_counts": dict(sorted(original_error_counts.items())),
        "page_field_completeness": page_completeness,
        "bvid_dedup_accuracy": bvid_accuracy,
        "mid_dedup_accuracy": mid_accuracy,
        "manual_top20_overlap_count": overlap_numerator,
        "manual_top20_denominator": overlap_denominator,
        "manual_top20_overlap_rate": overlap_rate,
        "import_fallback_successes": import_successes,
        "import_fallback_success_rate": import_successes / len(records) if records else 0,
        "development_provider_gate_passed": gate_passed,
        "records": records,
    }
    _json_dump(output / "validation-summary.json", summary)

    markdown = [
        "# P0-B real smoke validation",
        "",
        f"- Development Provider Gate: {'passed' if gate_passed else 'not passed'}",
        f"- Keywords with at least one successful page: {successful_keywords}/{len(records)} ({summary['keyword_success_rate']:.1%})",
        f"- Requested page distribution: {summary['requested_pages_distribution']}",
        f"- Page status counts: {summary['page_status_counts']}",
        f"- Required page field completeness: {page_completeness:.1%}",
        f"- BVID dedup validation: {bvid_accuracy:.1%}",
        f"- MID dedup validation: {mid_accuracy:.1%}",
        f"- Manual Top 20 overlap baseline: {overlap_numerator}/{overlap_denominator} ({overlap_rate:.1%})" if overlap_rate is not None else "- Manual Top 20 overlap baseline: unavailable",
        f"- Import Provider fallback validation: {import_successes}/{len(records)} ({summary['import_fallback_success_rate']:.1%})",
        "",
        "This is a low-frequency execution-time public search snapshot. It is not full-site coverage, production authorization, or a success-rate guarantee.",
    ]
    (output / "gate-candidate.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(f"summary={output / 'validation-summary.json'} gate_passed={gate_passed}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the private P0-B 20-keyword low-frequency smoke validation.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-pages", type=int, default=5, choices=range(1, 6))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=2, choices=range(0, 5))
    parser.add_argument("--backoff", type=float, default=0.5)
    parser.add_argument("--min-interval", type=float, default=1.0)
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
