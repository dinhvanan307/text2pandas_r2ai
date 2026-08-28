#!/usr/bin/env python3
"""Create immutable per-QID and package comparison artifacts for two runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_FIELDS = (
    "status",
    "answer",
    "relevant_tables",
    "relevant_docs",
    "evidence",
    "pandas_query",
    "confidence",
    "reason",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> dict[int, dict]:
    return {
        int(row["qid"]): row
        for row in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )
    }


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _record_metrics(records: dict[int, dict], run_manifest: dict, submission: dict) -> dict:
    table_sizes = [len(row.get("relevant_tables") or ()) for row in records.values()]
    doc_sizes = [len(row.get("relevant_docs") or ()) for row in records.values()]
    reasons = Counter(str(row.get("reason") or "OK") for row in records.values())
    return {
        "classification": "MEASURED",
        "questions": len(records),
        "answered": sum(row.get("status") == "OK" for row in records.values()),
        "abstained": sum(row.get("status") != "OK" for row in records.values()),
        "empty_relevant_tables": sum(not size for size in table_sizes),
        "mean_relevant_tables": sum(table_sizes) / max(len(table_sizes), 1),
        "max_relevant_tables": max(table_sizes, default=0),
        "mean_relevant_docs": sum(doc_sizes) / max(len(doc_sizes), 1),
        "abstain_reasons": dict(sorted(reasons.items())),
        "validator": submission["validation"],
        "replay": submission["replay"],
        "seconds": run_manifest["metrics"]["seconds"],
        "table_precision": "NOT_MEASURED",
        "table_recall": "NOT_MEASURED",
        "table_f2": "NOT_MEASURED",
        "answer_accuracy": "NOT_MEASURED",
        "execution_accuracy": "NOT_MEASURED",
    }


def run(args: argparse.Namespace) -> int:
    baseline_dir = args.baseline.resolve()
    upgraded_dir = args.upgraded.resolve()
    out = ROOT / "artifacts/runs/evaluation" / args.run_id
    try:
        out.mkdir(parents=True)
    except FileExistsError as error:
        raise RuntimeError(f"immutable output already exists: {out}") from error

    baseline = _jsonl(baseline_dir / "records.jsonl")
    upgraded = _jsonl(upgraded_dir / "records.jsonl")
    if set(baseline) != set(upgraded):
        raise ValueError("baseline/upgraded QID sets differ")
    baseline_manifest = _json(baseline_dir / "manifest.json")
    upgraded_manifest = _json(upgraded_dir / "manifest.json")
    baseline_submission = _json(baseline_dir / "submission_manifest.json")
    upgraded_submission = _json(upgraded_dir / "submission_manifest.json")

    per_qid_path = out / "per_qid_regression.jsonl"
    changed_fields: Counter[str] = Counter()
    classifications: Counter[str] = Counter()
    with per_qid_path.open("x", encoding="utf-8") as handle:
        for qid in sorted(baseline):
            before = baseline[qid]
            after = upgraded[qid]
            changes = [field for field in OUTPUT_FIELDS if before.get(field) != after.get(field)]
            changed_fields.update(changes)
            classification = "UNCHANGED" if not changes else "CHANGED_UNMEASURED"
            classifications[classification] += 1
            handle.write(
                json.dumps(
                    {
                        "qid": qid,
                        "baseline": {
                            "tables": before.get("relevant_tables") or [],
                            "answer": before.get("answer"),
                            "status": before.get("status"),
                            "reason": before.get("reason"),
                        },
                        "upgraded": {
                            "tables": after.get("relevant_tables") or [],
                            "answer": after.get("answer"),
                            "status": after.get("status"),
                            "reason": after.get("reason"),
                        },
                        "classification": classification,
                        "changed_fields": changes,
                        "reason": "byte-equivalent scorer-facing fields" if not changes else "gold unavailable",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    baseline_metrics = _record_metrics(baseline, baseline_manifest, baseline_submission)
    upgraded_metrics = _record_metrics(upgraded, upgraded_manifest, upgraded_submission)
    baseline_zip = Path(str(baseline_submission["package"]["published_path"]))
    upgraded_zip = Path(str(upgraded_submission["package"]["published_path"]))
    if not baseline_zip.is_absolute():
        baseline_zip = ROOT / baseline_zip
    if not upgraded_zip.is_absolute():
        upgraded_zip = ROOT / upgraded_zip
    baseline_sha = _sha(baseline_zip)
    upgraded_sha = _sha(upgraded_zip)

    diagnostic_baseline = _json(args.diagnostic_baseline.resolve())
    diagnostic_upgraded = _json(args.diagnostic_upgraded.resolve())
    paired = {
        "classification": "MEASURED_AND_DIAGNOSTIC",
        "questions": len(baseline),
        "classifications": dict(sorted(classifications.items())),
        "changed_fields": dict(sorted(changed_fields.items())),
        "new_wins": [],
        "new_losses": [],
        "new_table_wins": [],
        "new_table_losses": [],
        "answer_wins": [],
        "answer_losses": [],
        "scorer_facing_outputs_identical": not changed_fields,
        "submission_zip_identical": baseline_sha == upgraded_sha,
        "baseline_zip_sha256": baseline_sha,
        "upgraded_zip_sha256": upgraded_sha,
        "manual_95": {
            "baseline": diagnostic_baseline,
            "upgraded": diagnostic_upgraded,
            "classification": "DIAGNOSTIC",
        },
        "official_score_delta": "NOT_MEASURED",
        "decision": "KEEP_BASELINE" if not changed_fields else "BLOCKED",
    }

    validation = {
        "schema_version": "1.0",
        "run_id": upgraded_manifest["run_id"],
        "validation": upgraded_submission["validation"],
        "replay": upgraded_submission["replay"],
        "package": upgraded_submission["package"],
        "invariants": {
            "questions": len(upgraded),
            "unique_qids": len(set(upgraded)),
            "duplicate_relevant_tables": sum(
                len(row.get("relevant_tables") or ())
                != len(set(row.get("relevant_tables") or ()))
                for row in upgraded.values()
            ),
            "docs_derived_without_duplicates": sum(
                len(row.get("relevant_docs") or ())
                == len(set(row.get("relevant_docs") or ()))
                for row in upgraded.values()
            ),
        },
    }
    final_metrics = {
        "schema_version": "1.0",
        "baseline": baseline_metrics,
        "upgraded": upgraded_metrics,
        "paired": paired,
        "official_metrics": "NOT_MEASURED",
    }
    final_submission = {
        "schema_version": "1.0",
        "run_id": upgraded_manifest["run_id"],
        "decision": paired["decision"],
        "git_source": upgraded_manifest["source"],
        "snapshots": upgraded_manifest["snapshots"],
        "parameters": upgraded_manifest["parameters"],
        "package": {
            "path": str(upgraded_zip.relative_to(ROOT)),
            "sha256": upgraded_sha,
            "bytes": upgraded_zip.stat().st_size,
        },
        "validation": upgraded_submission["validation"],
        "replay": upgraded_submission["replay"],
        "upload": {
            "status": "NOT_UPLOADED",
            "submission_id": None,
            "timestamp": None,
            "receipt": None,
        },
    }

    payloads = {
        "baseline_metrics.json": baseline_metrics,
        "upgraded_metrics.json": upgraded_metrics,
        "paired_metrics.json": paired,
        "submission_validation_report.json": validation,
        "FINAL_E2E_METRICS.json": final_metrics,
        "FINAL_SUBMISSION_MANIFEST.json": final_submission,
    }
    for name, payload in payloads.items():
        (out / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (out / "FINAL_SUBMISSION_SHA256.txt").write_text(
        f"{upgraded_sha}  {upgraded_zip.relative_to(ROOT)}\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "kind": "text2pandas.table_retrieval_recovery_final_comparison",
        "run_id": args.run_id,
        "status": "COMPLETED",
        "decision": paired["decision"],
        "inputs": {
            "baseline_manifest_sha256": _sha(baseline_dir / "manifest.json"),
            "upgraded_manifest_sha256": _sha(upgraded_dir / "manifest.json"),
            "diagnostic_baseline_sha256": _sha(args.diagnostic_baseline.resolve()),
            "diagnostic_upgraded_sha256": _sha(args.diagnostic_upgraded.resolve()),
        },
        "outputs": {
            name: {"sha256": _sha(out / name)}
            for name in (*payloads, per_qid_path.name, "FINAL_SUBMISSION_SHA256.txt")
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": args.run_id,
        "questions": len(baseline),
        "classifications": paired["classifications"],
        "zip_sha256": upgraded_sha,
        "zip_identical": paired["submission_zip_identical"],
        "decision": paired["decision"],
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--upgraded", type=Path, required=True)
    parser.add_argument("--diagnostic-baseline", type=Path, required=True)
    parser.add_argument("--diagnostic-upgraded", type=Path, required=True)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
