from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


TEXT_SUFFIXES = {".py", ".md", ".json", ".csv", ".toml", ".yml", ".yaml", ".ts", ".tsx", ".js", ".mjs"}
KEYWORD_RUNTIME_PATHS = (
    "src/api/",
    "src/intelligence/",
    "src/tools/search.py",
    "src/worker.py",
    "src/repositories.py",
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _private_values(payload: dict) -> dict[str, set[str]]:
    keywords: set[str] = set()
    mids: set[str] = set()
    names: set[str] = set()
    for item in payload.get("keywords", []):
        keyword = str(item.get("keyword") or "").strip()
        if keyword:
            keywords.add(keyword)
        for field in ("top_creators", "expected_relevant_creators"):
            for creator in item.get(field, []):
                mid = str(creator.get("mid") or "").strip()
                name = str(creator.get("name") or "").strip()
                if len(mid) >= 4:
                    mids.add(mid)
                if len(name) >= 4:
                    names.add(name)
    return {"keyword": keywords, "mid": mids, "creator_name": names}


def _candidate_files(repo: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    files = []
    for relative in result.stdout.splitlines():
        path = repo / relative
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan P0-B working files for private evaluation hardcoding.")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    repo = args.repo.resolve()
    baseline = args.baseline.resolve()
    output = args.output.resolve()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    values = _private_values(payload)
    private_paths = {str(baseline), str(baseline.parent), baseline.name}
    hits = []
    candidate_files = _candidate_files(repo)

    for path in candidate_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        relative = path.relative_to(repo).as_posix()
        for kind, candidates in values.items():
            scan_text = text if kind != "keyword" or relative.startswith(KEYWORD_RUNTIME_PATHS) else ""
            for value in candidates:
                if value and value in scan_text:
                    hits.append({"kind": kind, "value_sha256_12": _digest(value), "file": relative})
        for value in private_paths:
            if value and value in text:
                hits.append({"kind": "private_path", "value_sha256_12": _digest(value), "file": relative})

    result = {
        "repo": str(repo),
        "scanned_file_count": len(candidate_files),
        "private_value_counts": {kind: len(items) for kind, items in values.items()},
        "hit_count": len(hits),
        "hits": hits,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"scanned={result['scanned_file_count']} hits={result['hit_count']} output={output}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
