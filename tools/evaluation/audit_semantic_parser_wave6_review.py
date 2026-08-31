#!/usr/bin/env python3
"""Audit completed Semantic Parser Wave 6 A/B/C responses without model output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.semantic_parser_review import (
    audit_semantic_parser_review_packet,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--annotator-a", type=Path, required=True)
    parser.add_argument("--annotator-b", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    scope = json.loads(args.scope.read_text(encoding="utf-8"))
    records = scope.get("records")
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        parser.error("scope records must be a list of objects")
    audit = audit_semantic_parser_review_packet(
        records,
        _jsonl(args.annotator_a),
        _jsonl(args.annotator_b),
        _jsonl(args.adjudication),
    )
    payload = json.dumps(audit.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        output = args.output.expanduser().resolve()
        if output.exists():
            parser.error(f"immutable audit output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if audit.sealable else 2


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


if __name__ == "__main__":
    raise SystemExit(main())
