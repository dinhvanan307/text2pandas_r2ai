#!/usr/bin/env python3
"""Apply one governed user review to a Semantic Parser Wave 6 review queue."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.semantic_parser_user_review import apply_user_review


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-queue", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args()

    queue = _jsonl(args.queue)
    review = _json(args.review)
    reviewed, summary = apply_user_review(queue, review)
    _write(args.output_queue, canonical_jsonl(reviewed))
    _write(
        args.output_summary,
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"expected JSON object: {path}")
    return payload


def _jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"expected JSON object at {path}:{line_number}")
        records.append(payload)
    return records


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
