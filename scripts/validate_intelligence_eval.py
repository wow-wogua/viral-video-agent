from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intelligence.evaluation import validate_evaluation_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a private content-intelligence evaluation suite.")
    parser.add_argument("path", type=Path)
    parser.add_argument("--require-reviewed", action="store_true")
    args = parser.parse_args()
    try:
        suite = validate_evaluation_file(args.path, require_reviewed=args.require_reviewed)
    except (OSError, ValueError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1
    category_counts = Counter(item.category.value for item in suite.keywords)
    review_counts = Counter(item.review_status.value for item in suite.keywords)
    reviewer_counts = Counter(item.reviewer_count for item in suite.keywords)
    snapshot_count = sum(len(item.snapshots) for item in suite.keywords)
    qualified_reference_count = sum(len(item.qualified_reference_creators) for item in suite.keywords)
    print(
        f"validated {len(suite.keywords)} keywords; categories={dict(category_counts)}; "
        f"reviews={dict(review_counts)}; reviewers={dict(reviewer_counts)}; "
        f"snapshots={snapshot_count}; qualified_references={qualified_reference_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
