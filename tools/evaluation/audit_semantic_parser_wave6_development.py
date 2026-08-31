#!/usr/bin/env python3
"""Build an immutable 40-QID development differential checkpoint."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path

from text2pandas.application.usecases.run_manifest import write_manifest
from text2pandas.application.usecases.semantic_parser_development import (
    build_development_records,
    summarize_development_records,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.source_identity import git_source_identity


ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    scope_payload = _json(args.scope)
    review_payload = _json(args.review)
    scope = scope_payload.get("records")
    review = review_payload.get("records")
    if not isinstance(scope, list) or not isinstance(review, list):
        raise TypeError("scope/review records must be arrays")
    records = build_development_records(
        scope,
        review,
        _jsonl(args.baseline),
        _jsonl(args.candidate),
    )
    summary = summarize_development_records(records)
    records_path = output / "records.jsonl"
    summary_path = output / "summary.json"
    with records_path.open("x", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path = output / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "schema_version": 1,
            "kind": "text2pandas.semantic_parser_wave6_development_checkpoint",
            "measurement_scope": "DEVELOPMENT_SUPERVISION_NOT_GOLD",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "source": git_source_identity(ROOT),
            "inputs": {
                label: {"path": str(path), "sha256": sha256_file(path)}
                for label, path in {
                    "scope": args.scope,
                    "review": args.review,
                    "baseline": args.baseline,
                    "candidate": args.candidate,
                }.items()
            },
            "metrics": summary,
            "outputs": {
                "records": {
                    "path": str(records_path),
                    "sha256": sha256_file(records_path),
                    "records": len(records),
                },
                "summary": {
                    "path": str(summary_path),
                    "sha256": sha256_file(summary_path),
                },
            },
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"records={records_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
