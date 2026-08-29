#!/usr/bin/env python3
"""Evaluate frozen canonical parser predictions against model semantic gold."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from text2pandas.application.usecases.model_semantic_gold_v1 import (  # noqa: E402
    canonical_json_bytes,
    canonicalize_record,
    evaluate_canonical_predictions,
    sha256_bytes,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"expected JSON object: {path}:{line_number}")
            rows.append(value)
    return rows


def _prediction_frame(row: dict[str, Any]) -> dict[str, Any]:
    semantic = row.get("semantic")
    if isinstance(semantic, dict):
        frame = dict(semantic)
        frame.setdefault("qid", row.get("qid"))
        frame.setdefault("question_sha256", row.get("question_sha256"))
        return frame
    if "generation" in row or "source_evidence" in row or "notes" in row:
        return canonicalize_record(row)
    return row


def _verify_release(release: Path) -> None:
    checksum_path = release / "checksums.sha256"
    if not checksum_path.is_file():
        raise FileNotFoundError(f"missing release checksums: {checksum_path}")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", maxsplit=1)
        path = release / relative
        if not path.is_file() or sha256_bytes(path.read_bytes()) != digest:
            raise ValueError(f"release checksum mismatch: {relative}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="evaluate_model_semantic_gold_v1")
    parser.add_argument("--release", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        release = Path(args.release).resolve()
        _verify_release(release)
        gold = _read_jsonl(release / "canonical_frames.jsonl")
        predictions = [
            _prediction_frame(row) for row in _read_jsonl(Path(args.predictions).resolve())
        ]
        result = evaluate_canonical_predictions(gold, predictions)
        report = {
            "release_id": json.loads(
                (release / "manifest.json").read_text(encoding="utf-8")
            )["release_id"],
            "gold_records": len(gold),
            "evaluated_qids": len(result.evaluated_qids),
            "missing_prediction_qids": list(result.missing_prediction_qids),
            "extra_prediction_qids": list(result.extra_prediction_qids),
            "metrics": {
                name: {
                    "passed": metric.passed,
                    "total": metric.total,
                    "accuracy": metric.accuracy,
                }
                for name, metric in result.metrics.items()
            },
            "explicitly_not_measured": [
                "retrieval_accuracy",
                "binding_accuracy",
                "numeric_answer_accuracy",
                "execution_accuracy",
            ],
        }
        rendered = canonical_json_bytes(report)
        if args.output:
            Path(args.output).write_bytes(rendered)
        sys.stdout.buffer.write(rendered)
        return 0
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
