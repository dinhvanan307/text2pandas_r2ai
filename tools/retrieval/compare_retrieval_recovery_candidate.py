#!/usr/bin/env python3
"""Compare a full retrieval-recovery candidate with its canonical baseline.

Official gold is hidden.  Table metrics and TABLE_WIN/TABLE_LOSS labels are
therefore restricted to the governed 95-question development gold.  Output
and execution transitions are measured over all 1,012 questions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.infrastructure.paths import ProjectPaths  # noqa: E402
from text2pandas.infrastructure.snapshots import ActiveSnapshots  # noqa: E402
from text2pandas.pipelines.retrieval.submission_adapter import (  # noqa: E402
    to_submission_ref,
)

DEFAULT_GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"
SCORER_FIELDS = (
    "status",
    "answer",
    "relevant_tables",
    "relevant_docs",
    "evidence",
    "pandas_query",
    "confidence",
    "reason",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path, id_key: str) -> dict[int, dict[str, Any]]:
    return {
        int(row[id_key]): row
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ref_to_uids(database: Path) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        for uid, evidence_ref in connection.execute(
            "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL"
        ):
            result.setdefault(to_submission_ref(str(evidence_ref)), set()).add(str(uid))
    finally:
        connection.close()
    return result


def _table_score(
    refs: list[str], gold: set[str], ref_to_uids: dict[str, set[str]]
) -> dict[str, float]:
    predicted_uids = {uid for ref in refs for uid in ref_to_uids.get(ref, set())}
    hits = len(predicted_uids & gold)
    positions = [index for index, ref in enumerate(refs, 1) if ref_to_uids.get(ref, set()) & gold]
    n_predictions = len(refs)
    n_gold = len(gold)
    return {
        "precision": hits / n_predictions if n_predictions else 0.0,
        "recall": hits / n_gold if n_gold else 0.0,
        "f2_macro": (5 * hits / (4 * n_gold + n_predictions) if n_gold or n_predictions else 0.0),
        "mrr5": 1.0 / min(positions) if positions and min(positions) <= 5 else 0.0,
    }


def _manual_metrics(
    records: dict[int, dict[str, Any]],
    gold: dict[int, set[str]],
    ref_to_uids: dict[str, set[str]],
) -> tuple[dict[str, Any], dict[int, dict[str, float]]]:
    per_qid = {
        qid: _table_score(
            [str(ref) for ref in records[qid].get("relevant_tables") or ()],
            expected,
            ref_to_uids,
        )
        for qid, expected in gold.items()
    }
    denominator = len(per_qid) or 1
    return (
        {
            "classification": "DEVELOPMENT_PROXY_NOT_OFFICIAL",
            "questions": len(per_qid),
            "tables_precision": sum(row["precision"] for row in per_qid.values()) / denominator,
            "tables_recall": sum(row["recall"] for row in per_qid.values()) / denominator,
            "tables_f2_macro": sum(row["f2_macro"] for row in per_qid.values()) / denominator,
            "tables_mrr5": sum(row["mrr5"] for row in per_qid.values()) / denominator,
            "mean_tables": sum(len(records[qid].get("relevant_tables") or ()) for qid in per_qid)
            / denominator,
        },
        per_qid,
    )


def _full_metrics(records: dict[int, dict[str, Any]]) -> dict[str, Any]:
    sizes = [len(row.get("relevant_tables") or ()) for row in records.values()]
    return {
        "classification": "FULL_OUTPUT_MEASURED_OFFICIAL_QUALITY_HIDDEN",
        "questions": len(records),
        "answered": sum(row.get("status") == "OK" for row in records.values()),
        "abstained": sum(row.get("status") != "OK" for row in records.values()),
        "empty_relevant_tables": sum(size == 0 for size in sizes),
        "mean_relevant_tables": sum(sizes) / max(len(sizes), 1),
        "max_relevant_tables": max(sizes, default=0),
        "reasons": dict(
            sorted(Counter(str(row.get("reason") or "OK") for row in records.values()).items())
        ),
    }


def run(args: argparse.Namespace) -> int:
    baseline_dir = args.baseline.resolve()
    candidate_dir = args.candidate.resolve()
    baseline_records_path = baseline_dir / "records.jsonl"
    candidate_records_path = candidate_dir / "records.jsonl"
    baseline = _read_jsonl(baseline_records_path, "qid")
    candidate = _read_jsonl(candidate_records_path, "qid")
    if set(baseline) != set(candidate) or len(candidate) != 1012:
        raise ValueError("baseline and candidate must contain the same 1,012 QIDs")

    gold_rows = _read_jsonl(args.gold.resolve(), "id")
    gold = {
        qid: {str(uid) for uid in row.get("gold_table_uids") or ()}
        for qid, row in gold_rows.items()
        if row.get("gold_table_uids") and not row.get("uncertain")
    }
    active = ActiveSnapshots.load(ProjectPaths.from_repo_root(ROOT))
    ref_to_uids = _ref_to_uids(active.retrieval_path / "retrieval.db")
    baseline_manual, baseline_per_qid = _manual_metrics(baseline, gold, ref_to_uids)
    candidate_manual, candidate_per_qid = _manual_metrics(candidate, gold, ref_to_uids)

    output_dir = ROOT / "artifacts/runs/evaluation" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    diff_path = output_dir / "per_qid_diff.jsonl"
    class_counts: Counter[str] = Counter()
    changed_fields: Counter[str] = Counter()
    table_additions = 0
    table_removals = 0
    changed_qids = 0
    with diff_path.open("x", encoding="utf-8") as handle:
        for qid in sorted(baseline):
            before = baseline[qid]
            after = candidate[qid]
            fields = [field for field in SCORER_FIELDS if before.get(field) != after.get(field)]
            changed_fields.update(fields)
            changed_qids += bool(fields)
            before_tables = [str(value) for value in before.get("relevant_tables") or ()]
            after_tables = [str(value) for value in after.get("relevant_tables") or ()]
            table_additions += len(set(after_tables) - set(before_tables))
            table_removals += len(set(before_tables) - set(after_tables))
            classifications: list[str] = []
            if not fields:
                classifications.append("UNCHANGED")
            if before_tables != after_tables:
                if qid in gold:
                    delta = candidate_per_qid[qid]["f2_macro"] - baseline_per_qid[qid]["f2_macro"]
                    if delta > 0:
                        classifications.append("TABLE_WIN")
                    elif delta < 0:
                        classifications.append("TABLE_LOSS")
                    else:
                        classifications.append("TABLE_CHANGED_NEUTRAL")
                else:
                    classifications.append("TABLE_CHANGED_UNMEASURED")
            before_ok = before.get("status") == "OK"
            after_ok = after.get("status") == "OK"
            if not before_ok and after_ok:
                classifications.extend(("ANSWER_WIN", "EXECUTION_WIN"))
            elif before_ok and not after_ok:
                classifications.extend(("ANSWER_LOSS", "EXECUTION_LOSS"))
            elif before_ok and after_ok and before.get("answer") != after.get("answer"):
                classifications.append("ANSWER_CHANGED_UNMEASURED")
            class_counts.update(classifications)
            handle.write(
                json.dumps(
                    {
                        "qid": qid,
                        "classifications": classifications,
                        "changed_fields": fields,
                        "baseline": {
                            "status": before.get("status"),
                            "answer": before.get("answer"),
                            "relevant_tables": before_tables,
                            "reason": before.get("reason"),
                        },
                        "candidate": {
                            "status": after.get("status"),
                            "answer": after.get("answer"),
                            "relevant_tables": after_tables,
                            "reason": after.get("reason"),
                        },
                        "development_gold_table_uids": sorted(gold[qid]) if qid in gold else None,
                        "development_table_metrics": (
                            {
                                "baseline": baseline_per_qid[qid],
                                "candidate": candidate_per_qid[qid],
                            }
                            if qid in gold
                            else None
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    baseline_manifest = _read_json(baseline_dir / "manifest.json")
    candidate_manifest = _read_json(candidate_dir / "manifest.json")
    candidate_submission = _read_json(candidate_dir / "submission_manifest.json")
    metrics = {
        "schema_version": "1.0",
        "classification": "LOCAL_DIAGNOSTIC_OFFICIAL_QUALITY_HIDDEN",
        "official_baseline": {
            "submission_id": 3766,
            "execution_accuracy": 0.2589,
            "tables_f2_macro": 0.2500,
            "tables_precision": 0.2921,
            "tables_recall": 0.2461,
            "tables_mrr5": 0.3360,
        },
        "full_1012": {
            "baseline": _full_metrics(baseline),
            "candidate": _full_metrics(candidate),
            "changed_qids": changed_qids,
            "table_additions": table_additions,
            "table_removals": table_removals,
            "changed_fields": dict(sorted(changed_fields.items())),
            "classifications": dict(sorted(class_counts.items())),
        },
        "manual_95": {"baseline": baseline_manual, "candidate": candidate_manual},
        "official_candidate": "NOT_MEASURED",
    }
    regression_report = {
        "schema_version": "1.0",
        "questions": 1012,
        "NEW_TABLE_REGRESSION": class_counts["TABLE_LOSS"],
        "NEW_ANSWER_REGRESSION": class_counts["ANSWER_LOSS"],
        "NEW_EXECUTION_REGRESSION": class_counts["EXECUTION_LOSS"],
        "table_wins": class_counts["TABLE_WIN"],
        "answer_wins": class_counts["ANSWER_WIN"],
        "execution_wins": class_counts["EXECUTION_WIN"],
        "unmeasured_table_changes": class_counts["TABLE_CHANGED_UNMEASURED"],
        "decision": (
            "LOCAL_WINNER_PENDING_OFFICIAL"
            if candidate_manual["tables_recall"] > baseline_manual["tables_recall"]
            and class_counts["ANSWER_LOSS"] == 0
            and class_counts["EXECUTION_LOSS"] == 0
            else "REJECT_LOCAL_CANDIDATE"
        ),
    }
    metrics_path = output_dir / "metrics.json"
    regression_path = output_dir / "regression_report.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    regression_path.write_text(
        json.dumps(regression_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "kind": "text2pandas.retrieval_recovery_candidate_comparison",
        "run_id": args.run_id,
        "source": candidate_manifest["source"],
        "snapshots": candidate_manifest["snapshots"],
        "parameters": candidate_manifest["parameters"],
        "inputs": {
            "baseline_records": {
                "path": str(baseline_records_path.relative_to(ROOT)),
                "sha256": _sha(baseline_records_path),
                "source": baseline_manifest["source"],
            },
            "candidate_records": {
                "path": str(candidate_records_path.relative_to(ROOT)),
                "sha256": _sha(candidate_records_path),
            },
            "gold": {
                "path": str(args.gold.resolve().relative_to(ROOT)),
                "sha256": _sha(args.gold.resolve()),
            },
        },
        "package": candidate_submission["package"],
        "outputs": {
            path.name: {"sha256": _sha(path)} for path in (metrics_path, diff_path, regression_path)
        },
        "status": "COMPLETED",
        "official_candidate": "NOT_MEASURED",
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_id": args.run_id,
                "manual_95": metrics["manual_95"],
                "full_1012": metrics["full_1012"],
                "regressions": regression_report,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
