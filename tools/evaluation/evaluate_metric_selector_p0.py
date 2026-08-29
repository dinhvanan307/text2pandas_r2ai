#!/usr/bin/env python3
"""Evaluate the P0 metric selector from a canonical shadow run.

The report keeps three populations separate:

* all 1,012 shadow records for coverage and differential counts;
* independently adjudicated ``OK`` answer-gold records for correctness;
* the supplied leaderboard ZIP for non-causal provenance comparison only.

No MODEL_GOLD record is read or used by this evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.sandbox.query import execute_query


JsonObject = dict[str, Any]


def _read_jsonl(path: Path) -> list[JsonObject]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _close(actual: object, expected: object, tolerance: float) -> bool:
    left = _numeric(actual)
    right = _numeric(expected)
    return (
        left is not None
        and right is not None
        and abs(left - right) <= tolerance * max(1.0, abs(right))
    )


def _normalise(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _leaf(value: object) -> str:
    return _normalise(str(value or "").split("›")[-1])


def _metric_payload(record: JsonObject) -> JsonObject:
    value = record.get("metric_p0")
    return value if isinstance(value, dict) else {}


def _candidate_trace(record: JsonObject) -> JsonObject | None:
    value = _metric_payload(record).get("candidate_trace")
    return value if isinstance(value, dict) else None


def _guarded_view(record: JsonObject) -> JsonObject:
    """Project the exact guarded decision from a shadow record."""

    metric = _metric_payload(record)
    candidate = _candidate_trace(record)
    if not metric.get("eligible") or candidate is None:
        return record
    return {
        "qid": record["qid"],
        "status": candidate.get("status"),
        "answer": candidate.get("answer"),
        "pandas_query": candidate.get("pandas_query"),
        "evidence": candidate.get("evidence") or [],
        "trace": candidate,
        "reason": candidate.get("reason"),
    }


def _replay(
    prediction: JsonObject,
    data_root: Path,
    tolerance: float,
    cache: dict[Path, pd.DataFrame],
) -> tuple[bool, str | None]:
    query = str(prediction.get("pandas_query") or "")
    evidence = prediction.get("evidence") or []
    answer = _numeric(prediction.get("answer"))
    if not query or not evidence or answer is None:
        return False, "NOT_EXECUTABLE"
    missing_paths = [
        str(data_root / str(item["csv_path"]))
        for item in evidence
        if not (data_root / str(item["csv_path"])).is_file()
    ]
    if missing_paths:
        return False, "NOT_MATERIALIZED:" + ",".join(missing_paths)
    try:
        frames: dict[str, object] = {}
        for item in evidence:
            csv_path = data_root / str(item["csv_path"])
            if csv_path not in cache:
                cache[csv_path] = pd.read_csv(csv_path)
            frames[str(item["variable"])] = cache[csv_path]
        actual = execute_query(query, frames)
    except Exception as error:  # noqa: BLE001 - recorded per case
        return False, f"{type(error).__name__}:{error}"
    if not _close(actual, answer, tolerance):
        return False, f"REPLAY_MISMATCH:{actual!r}!={answer!r}"
    return True, None


def _uid_to_ref(retrieval_db: Path) -> dict[str, str]:
    connection = sqlite3.connect(
        f"file:{retrieval_db.resolve()}?mode=ro&immutable=1",
        uri=True,
    )
    try:
        rows = connection.execute(
            "SELECT table_uid, evidence_ref FROM table_cards"
        ).fetchall()
    finally:
        connection.close()
    return {
        str(uid): str(reference).replace("|line:", "|")
        for uid, reference in rows
        if uid and reference
    }


def _operands(prediction: JsonObject) -> list[JsonObject]:
    trace = prediction.get("trace")
    if not isinstance(trace, dict):
        return []
    values = trace.get("operands")
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _cell_match(
    prediction: JsonObject,
    gold: JsonObject,
    uid_refs: dict[str, str],
) -> bool:
    """Strict table + row-leaf + year match for all adjudicated gold cells."""

    operands = _operands(prediction)
    gold_cells = gold.get("gold_cells")
    if not operands or not isinstance(gold_cells, list) or not gold_cells:
        return False
    for cell in gold_cells:
        if not isinstance(cell, dict):
            return False
        expected_ref = str(cell.get("evidence_ref") or "").replace("|line:", "|")
        expected_row = _leaf(cell.get("row_path"))
        expected_year = str(cell.get("period_end") or "")[:4]
        matched = False
        for operand in operands:
            provenance = operand.get("provenance")
            provenance = provenance if isinstance(provenance, dict) else {}
            actual_ref = uid_refs.get(str(provenance.get("table_uid") or ""), "")
            actual_row = _leaf(provenance.get("row_path") or (operand.get("cell") or {}).get("row_path"))
            period_text = " ".join(
                str(value or "")
                for value in (
                    operand.get("period"),
                    provenance.get("col_label"),
                    (operand.get("cell") or {}).get("col_label"),
                )
            )
            if (
                actual_ref == expected_ref
                and actual_row == expected_row
                and (not expected_year or expected_year in period_text)
            ):
                matched = True
                break
        if not matched:
            return False
    return True


def _load_submission(archive: Path) -> tuple[list[JsonObject], str]:
    with zipfile.ZipFile(archive) as bundle:
        names = [name for name in bundle.namelist() if name.endswith("submission.json")]
        if names != ["submission.json"]:
            raise ValueError(f"expected root submission.json, found: {names}")
        payload = bundle.read(names[0])
    records = json.loads(payload)
    if not isinstance(records, list):
        raise ValueError("submission.json must contain a list")
    return records, hashlib.sha256(payload).hexdigest()


def _emitted(record: JsonObject) -> bool:
    return bool(
        _numeric(record.get("answer")) is not None
        and record.get("pandas_query")
        and record.get("evidence")
    )


def _baseline_comparison(
    archive: Path,
    current: dict[int, JsonObject],
    gold: dict[int, JsonObject],
    tolerance: float,
) -> dict[str, object]:
    rows, submission_sha = _load_submission(archive)
    baseline = {int(item["id"]): item for item in rows}
    if set(baseline) != set(current):
        raise ValueError("baseline ZIP and shadow run do not contain the same QIDs")
    exact = 0
    baseline_only = 0
    current_only = 0
    differing_answer = 0
    for qid, before in baseline.items():
        after = current[qid]
        if before == {key: after.get(key) for key in before}:
            exact += 1
        before_emitted = _emitted(before)
        after_emitted = _emitted(after)
        baseline_only += before_emitted and not after_emitted
        current_only += after_emitted and not before_emitted
        differing_answer += not _close(before.get("answer"), after.get("answer"), tolerance)
    evaluable = len(gold)
    correct = sum(
        _emitted(baseline[qid])
        and _close(baseline[qid].get("answer"), item["normalized_answer_gold"], tolerance)
        for qid, item in gold.items()
    )
    return {
        "interpretation": "NON_CAUSAL_PROVENANCE_COMPARISON_ONLY",
        "reason": "supplied ZIP does not identify its generation commit/config",
        "zip": {"path": str(archive), "sha256": sha256_file(archive)},
        "submission_json_sha256": submission_sha,
        "records": len(baseline),
        "emitted": sum(_emitted(item) for item in baseline.values()),
        "current_shadow_legacy_emitted": sum(_emitted(item) for item in current.values()),
        "exact_records": exact,
        "baseline_only_emissions": baseline_only,
        "current_only_emissions": current_only,
        "differing_numeric_answers": differing_answer,
        "local_gold": {
            "evaluable": evaluable,
            "answer_correct": correct,
            "answer_accuracy": correct / evaluable if evaluable else None,
        },
    }


def evaluate(
    shadow_records: Path,
    gold_path: Path,
    data_root: Path,
    retrieval_db: Path,
    baseline_zip: Path,
    *,
    tolerance: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    records = {int(row["qid"]): row for row in _read_jsonl(shadow_records)}
    gold = {
        int(row["qid"]): row
        for row in _read_jsonl(gold_path)
        if row.get("trang_thai") == "OK"
    }
    if missing := sorted(set(gold) - set(records)):
        raise ValueError(f"shadow run is missing adjudicated QIDs: {missing}")

    uid_refs = _uid_to_ref(retrieval_db)
    cache: dict[Path, pd.DataFrame] = {}
    cases: list[dict[str, object]] = []
    answer_wins = answer_losses = cell_wins = cell_losses = 0
    legacy_answer_correct = guarded_answer_correct = 0
    legacy_cell_correct = guarded_cell_correct = 0
    eligible_gold = 0
    protected_losses: list[int] = []

    for qid, gold_row in sorted(gold.items()):
        legacy = records[qid]
        guarded = _guarded_view(legacy)
        metric = _metric_payload(legacy)
        is_eligible = bool(metric.get("eligible"))
        eligible_gold += is_eligible
        expected = gold_row["normalized_answer_gold"]
        legacy_answer = _close(legacy.get("answer"), expected, tolerance)
        guarded_answer = _close(guarded.get("answer"), expected, tolerance)
        legacy_cell = _cell_match(legacy, gold_row, uid_refs)
        guarded_cell = _cell_match(guarded, gold_row, uid_refs)
        legacy_answer_correct += legacy_answer
        guarded_answer_correct += guarded_answer
        legacy_cell_correct += legacy_cell
        guarded_cell_correct += guarded_cell
        answer_wins += guarded_answer and not legacy_answer
        answer_losses += legacy_answer and not guarded_answer
        cell_wins += guarded_cell and not legacy_cell
        cell_losses += legacy_cell and not guarded_cell
        if legacy_answer and not guarded_answer:
            protected_losses.append(qid)
        resolution = metric.get("resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        cases.append(
            {
                "qid": qid,
                "eligible": is_eligible,
                "differential": metric.get("differential") or "NOT_ELIGIBLE",
                "metric_id": resolution.get("selected_metric_id"),
                "gold_answer": expected,
                "legacy_answer": legacy.get("answer"),
                "guarded_answer": guarded.get("answer"),
                "legacy_answer_correct": legacy_answer,
                "guarded_answer_correct": guarded_answer,
                "legacy_cell_exact": legacy_cell,
                "guarded_cell_exact": guarded_cell,
            }
        )

    candidate_ok = candidate_replayed = candidate_materialized = 0
    candidate_not_materialized = 0
    replay_failures: list[dict[str, object]] = []
    for qid, record in sorted(records.items()):
        candidate = _candidate_trace(record)
        if candidate is None or candidate.get("status") != "OK":
            continue
        candidate_ok += 1
        replayed, failure = _replay(candidate, data_root, tolerance, cache)
        candidate_replayed += replayed
        if failure and failure.startswith("NOT_MATERIALIZED:"):
            candidate_not_materialized += 1
            continue
        candidate_materialized += 1
        if not replayed:
            replay_failures.append({"qid": qid, "failure": failure})

    total_gold = len(gold)
    metric_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()
    differential_counts: Counter[str] = Counter()
    eligible_total = 0
    for record in records.values():
        metric = _metric_payload(record)
        resolution = metric.get("resolution")
        resolution = resolution if isinstance(resolution, dict) else {}
        resolution_counts[str(resolution.get("status") or "UNRESOLVED")] += 1
        selected = resolution.get("selected_metric_id")
        if selected:
            metric_counts[str(selected)] += 1
        differential_counts[str(metric.get("differential") or "NOT_ELIGIBLE")] += 1
        eligible_total += bool(metric.get("eligible"))

    gate_pass = answer_wins > answer_losses and not protected_losses
    summary: dict[str, object] = {
        "schema_version": "1.0",
        "measurement_scope": "P0_SHADOW_DIFFERENTIAL_WITH_LOCAL_INDEPENDENT_GOLD",
        "official_accuracy": "NOT_MEASURED",
        "metric_resolution_correctness": "NOT_MEASURED_NO_INDEPENDENT_METRIC_ID_LABELS",
        "inputs": {
            "shadow_records": {
                "path": str(shadow_records),
                "sha256": sha256_file(shadow_records),
            },
            "gold": {"path": str(gold_path), "sha256": sha256_file(gold_path)},
            "retrieval_db": {"path": str(retrieval_db)},
        },
        "full_corpus": {
            "records": len(records),
            "eligible": eligible_total,
            "resolution_status": dict(sorted(resolution_counts.items())),
            "resolved_metrics": dict(sorted(metric_counts.items())),
            "differential": dict(sorted(differential_counts.items())),
            "candidate_replay": {
                "candidate_ok": candidate_ok,
                "materialized_by_shadow": candidate_materialized,
                "not_materialized_by_shadow": candidate_not_materialized,
                "replayed": candidate_replayed,
                "materialization_coverage": (
                    candidate_materialized / candidate_ok if candidate_ok else None
                ),
                "consistency_on_materialized": (
                    candidate_replayed / candidate_materialized
                    if candidate_materialized
                    else None
                ),
                "execution_failures": replay_failures,
                "interpretation": (
                    "shadow mode materializes selected legacy evidence only; "
                    "unmaterialized P0-only evidence is not a replay failure"
                ),
            },
        },
        "local_independent_gold": {
            "evaluable": total_gold,
            "eligible": eligible_gold,
            "answer": {
                "legacy_correct": legacy_answer_correct,
                "guarded_correct": guarded_answer_correct,
                "legacy_accuracy": legacy_answer_correct / total_gold if total_gold else None,
                "guarded_accuracy": guarded_answer_correct / total_gold if total_gold else None,
                "wins": answer_wins,
                "losses": answer_losses,
            },
            "selected_cell_exact": {
                "definition": "all gold cells match table reference, strict row leaf, and year",
                "legacy_correct": legacy_cell_correct,
                "guarded_correct": guarded_cell_correct,
                "wins": cell_wins,
                "losses": cell_losses,
            },
            "protected_correct_losses": protected_losses,
        },
        "baseline_zip_comparison": _baseline_comparison(
            baseline_zip, records, gold, tolerance
        ),
        "promotion_gate": {
            "rule": "answer_wins > answer_losses AND protected_correct_losses == 0",
            "pass": gate_pass,
            "decision": "PROMOTE_GUARDED" if gate_pass else "KEEP_OFF",
            "guarded_submission_built": False,
        },
    }
    return summary, cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow-records", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--retrieval-db", type=Path, required=True)
    parser.add_argument("--baseline-zip", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--output-cases", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.005)
    args = parser.parse_args()
    if not 0 <= args.tolerance < 1:
        parser.error("--tolerance must be in [0, 1)")
    for output in (args.output_summary, args.output_cases):
        if output.exists():
            parser.error(f"immutable output already exists: {output}")
    summary, cases = evaluate(
        args.shadow_records,
        args.gold,
        args.data_root,
        args.retrieval_db,
        args.baseline_zip,
        tolerance=args.tolerance,
    )
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_cases.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_cases.write_text(
        "".join(json.dumps(case, ensure_ascii=False, sort_keys=True) + "\n" for case in cases),
        encoding="utf-8",
    )
    print(json.dumps(summary["promotion_gate"], ensure_ascii=False, indent=2))
    print(json.dumps(summary["local_independent_gold"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
