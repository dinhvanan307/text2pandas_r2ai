"""Evaluate a canonical run against independently adjudicated local answer gold.

This is a local engineering metric, never a substitute for organiser-held gold.
The denominator contains only records explicitly marked ``trang_thai=OK``.
Execution Accuracy requires both a matching answer and a successful clean
replay from the run's materialized evidence CSV files.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.sandbox.query import execute_query


@dataclass(frozen=True, slots=True)
class CaseResult:
    qid: int
    operation: str
    status: str
    predicted: float | None
    gold: float
    answer_match: bool
    executable: bool
    replay_match: bool
    execution_correct: bool
    failure: str | None


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _close(actual: float, expected: float, tolerance: float) -> bool:
    return math.isfinite(actual) and abs(actual - expected) <= tolerance * max(
        1.0, abs(expected)
    )


def _numeric_answer(value: object) -> float | None:
    """Decode the JSON numeric contract used by both canonical and V3 runs.

    Semantic V3 preserves ``Decimal`` answers as JSON strings. Treating those
    strings as abstentions silently understates accuracy, while accepting
    arbitrary strings or non-finite values would weaken the submission
    contract. This decoder therefore accepts only finite JSON numbers and
    finite numeric strings.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        decoded = float(value)
    except ValueError:
        return None
    return decoded if math.isfinite(decoded) else None


def evaluate(
    records_path: Path,
    gold_path: Path,
    data_root: Path,
    *,
    tolerance: float,
) -> dict[str, object]:
    records = {int(record["qid"]): record for record in _read_jsonl(records_path)}
    gold_rows = [
        record
        for record in _read_jsonl(gold_path)
        if record.get("trang_thai") == "OK"
    ]
    expected_ids = {int(record["qid"]) for record in gold_rows}
    missing = sorted(expected_ids - records.keys())
    unexpected = sorted(records.keys() - expected_ids)
    if missing:
        raise ValueError(f"run is missing adjudicated qids: {missing}")

    cases: list[CaseResult] = []
    cache: dict[Path, pd.DataFrame] = {}
    for gold in sorted(gold_rows, key=lambda item: int(item["qid"])):
        qid = int(gold["qid"])
        record = records[qid]
        expected = float(gold["normalized_answer_gold"])
        raw_answer = record.get("answer")
        predicted = _numeric_answer(raw_answer)
        answer_match = predicted is not None and _close(predicted, expected, tolerance)
        evidence = record.get("evidence") or []
        query = str(record.get("pandas_query") or "")
        executable = bool(evidence and query)
        replay_match = False
        failure: str | None = None
        if executable:
            try:
                frames: dict[str, object] = {}
                for item in evidence:
                    relative = Path(str(item["csv_path"]))
                    csv_path = data_root / relative
                    if csv_path not in cache:
                        cache[csv_path] = pd.read_csv(csv_path)
                    frames[str(item["variable"])] = cache[csv_path]
                replayed = execute_query(query, frames)
                replay_match = predicted is not None and _close(
                    replayed, predicted, tolerance
                )
                if not replay_match:
                    failure = "REPLAY_MISMATCH"
            except Exception as error:  # noqa: BLE001 - error is reported per case
                failure = f"REPLAY_ERROR:{type(error).__name__}:{error}"
        elif predicted is None:
            failure = str(record.get("reason") or "ABSTAIN")
        else:
            failure = "MISSING_EXECUTABLE_EVIDENCE"
        if executable and replay_match and not answer_match:
            failure = "ANSWER_MISMATCH"

        cases.append(
            CaseResult(
                qid=qid,
                operation=str(gold.get("operation") or "unknown"),
                status=str(record.get("status") or "UNKNOWN"),
                predicted=predicted,
                gold=expected,
                answer_match=answer_match,
                executable=executable,
                replay_match=replay_match,
                execution_correct=answer_match and replay_match,
                failure=failure,
            )
        )

    total = len(cases)
    answer_correct = sum(case.answer_match for case in cases)
    emitted = sum(case.executable for case in cases)
    replayed = sum(case.replay_match for case in cases)
    execution_correct = sum(case.execution_correct for case in cases)
    operations = sorted({case.operation for case in cases})
    return {
        "schema_version": "1.1",
        "measurement_scope": "LOCAL_ADJUDICATED_GOLD_NOT_OFFICIAL",
        "tolerance": {"kind": "relative_with_absolute_floor", "value": tolerance},
        "inputs": {
            "records": {"path": str(records_path), "sha256": sha256_file(records_path)},
            "gold": {"path": str(gold_path), "sha256": sha256_file(gold_path)},
        },
        "population": {
            "gold_total": len(_read_jsonl(gold_path)),
            "gold_evaluable": total,
            "run_records": len(records),
            "unexpected_run_ids": unexpected,
        },
        "metrics": {
            "answer_accuracy": answer_correct / total if total else None,
            "answer_correct": answer_correct,
            "execution_accuracy": execution_correct / total if total else None,
            "execution_correct": execution_correct,
            "executable_coverage": emitted / total if total else None,
            "executable": emitted,
            "replay_consistency": replayed / emitted if emitted else None,
            "replayed": replayed,
        },
        "by_operation": {
            operation: {
                "n": len(group := [case for case in cases if case.operation == operation]),
                "answer_correct": sum(case.answer_match for case in group),
                "execution_correct": sum(case.execution_correct for case in group),
            }
            for operation in operations
        },
        "cases": [asdict(case) for case in cases],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.005)
    args = parser.parse_args()
    if not 0 <= args.tolerance < 1:
        parser.error("--tolerance must be in [0, 1)")
    if args.output.exists():
        parser.error(f"immutable output already exists: {args.output}")
    report = evaluate(
        args.records,
        args.gold,
        args.data_root,
        tolerance=args.tolerance,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metrics = report["metrics"]
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
