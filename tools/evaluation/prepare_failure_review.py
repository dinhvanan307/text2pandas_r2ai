"""Materialize a non-promotable diagnostic Semantic V3 review backlog."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.review_backlog import build_failure_review_backlog
from text2pandas.infrastructure.checksums import sha256_file

DEFAULT_PRIORITY_REASONS = (
    "REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION",
    "BINDING_TIE",
)


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=300)
    parser.add_argument(
        "--priority-reason",
        action="append",
        dest="priority_reasons",
        default=[],
    )
    parser.add_argument("--seed", default="semantic-v3-failure-review-v1")
    args = parser.parse_args()
    records_path = args.records.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    reasons = tuple(args.priority_reasons) or DEFAULT_PRIORITY_REASONS
    backlog = build_failure_review_backlog(
        _rows(records_path),
        target_count=args.target_count,
        priority_reasons=reasons,
        seed=args.seed,
    )
    output.mkdir(parents=True)
    queue = canonical_jsonl(backlog.records)
    queue_path = output / "review_queue.jsonl"
    queue_path.write_bytes(queue)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_v3_diagnostic_review_packet",
        "status": "OPEN_FOR_HUMAN_DIAGNOSTIC_REVIEW",
        "promotion_eligible": False,
        "model_outputs_included": True,
        "selection_seed": args.seed,
        "priority_reasons": list(reasons),
        "source": {
            "records": str(records_path),
            "sha256": sha256_file(records_path),
        },
        "metrics": {
            "records": len(backlog.records),
            "priority_records": backlog.priority_records,
            "filler_records": backlog.filler_records,
            "source_reason_counts": backlog.source_reason_counts,
            "selected_reason_counts": backlog.selected_reason_counts,
        },
        "assets": {
            "review_queue.jsonl": {
                "records": len(backlog.records),
                "sha256": hashlib.sha256(queue).hexdigest(),
            }
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["metrics"], ensure_ascii=False, indent=2))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
