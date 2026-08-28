#!/usr/bin/env python3
"""Evaluate output-N policies on canonical scorer-facing table references.

The 95 manually labeled questions are development diagnostics, never official
metrics.  All 1,012 records are still compared so every table addition/removal
and every scorer-facing change is explicit before a candidate is built.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots
from text2pandas.infrastructure.source_identity import git_source_identity
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.evalkit.attribution import classify_stage_loss
from text2pandas.pipelines.retrieval.submission_adapter import (
    RetrievalToSubmission,
    to_submission_ref,
)

DEFAULT_RECORDS = ROOT / (
    "artifacts/runs/answer/table-retrieval-full-recovery-7ed2bfe-a-20260828-01/records.jsonl"
)
DEFAULT_GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _ranked(retrieval: dict[str, Any]) -> list[dict[str, Any]]:
    return list(retrieval["s2"]["top_k"])


def _current(retrieval: dict[str, Any]) -> list[str]:
    return [str(value) for value in retrieval["output_policy"]["selected_table_ids"]]


def _fixed(retrieval: dict[str, Any], n: int) -> list[str]:
    return [str(item["table_uid"]) for item in _ranked(retrieval)[:n]]


def _score_margin(retrieval: dict[str, Any], margin: float, maximum: int = 10) -> list[str]:
    ranked = _ranked(retrieval)
    if not ranked:
        return []
    n = len(_current(retrieval))
    threshold = float(ranked[0]["score"]) - margin
    while n < min(maximum, len(ranked)) and float(ranked[n]["score"]) >= threshold:
        n += 1
    return [str(item["table_uid"]) for item in ranked[:n]]


def _scope_multiplier(retrieval: dict[str, Any], multiplier: int, maximum: int) -> list[str]:
    n = min(maximum, max(1, multiplier * len(_current(retrieval))))
    return [str(item["table_uid"]) for item in _ranked(retrieval)[:n]]


Policy = Callable[[dict[str, Any]], list[str]]


def _policies() -> dict[str, Policy]:
    return {
        "E0_current": _current,
        "E1_fixed_5": lambda record: _fixed(record, 5),
        "E2_fixed_7": lambda record: _fixed(record, 7),
        "E3_fixed_10": lambda record: _fixed(record, 10),
        "E4_margin_0_10": lambda record: _score_margin(record, 0.10),
        "E4_margin_0_20": lambda record: _score_margin(record, 0.20),
        "E4_margin_0_30": lambda record: _score_margin(record, 0.30),
        "E4_margin_0_50": lambda record: _score_margin(record, 0.50),
        "E5_legacy_scope_x3_cap30": lambda record: _scope_multiplier(record, 3, 30),
    }


def _uid_maps(database: Path) -> tuple[dict[str, str], dict[str, set[str]]]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
    uid_to_ref: dict[str, str] = {}
    ref_to_uids: dict[str, set[str]] = {}
    try:
        for uid, evidence_ref in connection.execute(
            "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL"
        ):
            ref = to_submission_ref(str(evidence_ref))
            uid_to_ref[str(uid)] = ref
            ref_to_uids.setdefault(ref, set()).add(str(uid))
    finally:
        connection.close()
    return uid_to_ref, ref_to_uids


def _final_refs(
    record: dict[str, Any], selected_uids: list[str], uid_to_ref: dict[str, str]
) -> list[str]:
    # Output-N does not weaken authoritative evidence on successful answers.
    if record.get("status") == "OK":
        return [str(value) for value in record.get("relevant_tables") or ()]
    return _dedupe([uid_to_ref[uid] for uid in selected_uids if uid in uid_to_ref])


def _per_question_score(
    refs: list[str], gold: set[str], ref_to_uids: dict[str, set[str]]
) -> tuple[float, float, float, float]:
    hits = [index for index, ref in enumerate(refs, 1) if ref_to_uids.get(ref, set()) & gold]
    h = len({uid for ref in refs for uid in ref_to_uids.get(ref, set())} & gold)
    n = len(refs)
    g = len(gold)
    precision = h / n if n else 0.0
    recall = h / g if g else 0.0
    f2 = 5 * h / (4 * g + n) if g or n else 0.0
    best = min(hits) if hits else None
    mrr5 = 1.0 / best if best is not None and best <= 5 else 0.0
    return precision, recall, f2, mrr5


def _metrics(
    predictions: dict[int, list[str]],
    gold: dict[int, set[str]],
    ref_to_uids: dict[str, set[str]],
) -> tuple[dict[str, Any], dict[int, dict[str, float]]]:
    per_qid: dict[int, dict[str, float]] = {}
    for qid, expected in gold.items():
        p, r, f2, mrr5 = _per_question_score(predictions[qid], expected, ref_to_uids)
        per_qid[qid] = {"precision": p, "recall": r, "f2": f2, "mrr5": mrr5}
    n = len(per_qid) or 1
    return (
        {
            "classification": "DEVELOPMENT_PROXY_NOT_OFFICIAL",
            "questions": len(per_qid),
            "tables_precision": sum(row["precision"] for row in per_qid.values()) / n,
            "tables_recall": sum(row["recall"] for row in per_qid.values()) / n,
            "tables_f2_macro": sum(row["f2"] for row in per_qid.values()) / n,
            "tables_mrr5": sum(row["mrr5"] for row in per_qid.values()) / n,
            "mean_tables": sum(len(predictions[qid]) for qid in per_qid) / n,
            "execution_accuracy": "UNCHANGED_BY_CONSTRUCTION",
            "answer_accuracy": "UNCHANGED_BY_CONSTRUCTION",
        },
        per_qid,
    )


def run(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_repo_root(ROOT)
    active = ActiveSnapshots.load(paths)
    records_path = args.records.resolve()
    gold_path = args.gold.resolve()
    records = {int(row["qid"]): row for row in _read_jsonl(records_path)}
    if len(records) != 1012:
        raise ValueError(f"expected 1012 canonical records, found {len(records)}")
    gold = {
        int(row["id"]): {str(uid) for uid in row.get("gold_table_uids") or ()}
        for row in _read_jsonl(gold_path)
        if row.get("gold_table_uids") and not row.get("uncertain")
    }
    uid_to_ref, ref_to_uids = _uid_maps(active.retrieval_path / "retrieval.db")
    questions_path = active.raw_path / "questions/questions.jsonl"
    questions = {int(row["id"]): str(row["question"]) for row in _read_jsonl(questions_path)}
    if set(records) != set(questions):
        raise ValueError("canonical record IDs do not match the active question set")
    output = paths.run_dir("retrieval", args.run_id)
    output.mkdir(parents=True, exist_ok=False)

    traces_input = args.traces.resolve() if args.traces else None
    if traces_input:
        retrieval_by_qid = {int(row["qid"]): row for row in _read_jsonl(traces_input)}
        if set(retrieval_by_qid) != set(records):
            raise ValueError("retrieval trace IDs do not match canonical record IDs")
    else:
        adapter = RetrievalToSubmission(
            load_aliases("a6"), top_k_rank=50, top_k_rerank=50, max_n=10
        )
        retrieval_by_qid: dict[int, dict[str, Any]] = {}
        connection = sqlite3.connect(
            f"file:{(active.retrieval_path / 'retrieval.db').resolve()}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            for qid in sorted(records):
                retrieval_by_qid[qid] = adapter.refs_for(connection, qid, questions[qid]).trace
        finally:
            connection.close()
    trace_path = output / "retrieval_traces.jsonl"
    with trace_path.open("x", encoding="utf-8") as handle:
        for qid in sorted(retrieval_by_qid):
            handle.write(
                json.dumps(retrieval_by_qid[qid], ensure_ascii=False, sort_keys=True) + "\n"
            )

    baseline = {
        qid: [str(value) for value in record.get("relevant_tables") or ()]
        for qid, record in records.items()
    }
    baseline_metrics, baseline_per_qid = _metrics(baseline, gold, ref_to_uids)
    policy_results: dict[str, dict[str, Any]] = {}
    policy_predictions: dict[str, dict[int, list[str]]] = {}
    policy_per_qid: dict[str, dict[int, dict[str, float]]] = {}
    for name, policy in _policies().items():
        predictions = {
            qid: _final_refs(record, policy(retrieval_by_qid[qid]), uid_to_ref)
            for qid, record in records.items()
        }
        metrics, per_qid = _metrics(predictions, gold, ref_to_uids)
        additions = sum(len(set(predictions[qid]) - set(baseline[qid])) for qid in records)
        removals = sum(len(set(baseline[qid]) - set(predictions[qid])) for qid in records)
        changed = sum(predictions[qid] != baseline[qid] for qid in records)
        wins = sum(per_qid[qid]["f2"] > baseline_per_qid[qid]["f2"] for qid in gold)
        losses = sum(per_qid[qid]["f2"] < baseline_per_qid[qid]["f2"] for qid in gold)
        policy_results[name] = {
            **metrics,
            "full_1012": {
                "changed_qids": changed,
                "table_additions": additions,
                "table_removals": removals,
                "new_answer_regressions": 0,
                "new_execution_regressions": 0,
            },
            "development_qid_f2_wins": wins,
            "development_qid_f2_losses": losses,
        }
        policy_predictions[name] = predictions
        policy_per_qid[name] = per_qid

    failure_path = output / "failure_matrix.jsonl"
    with failure_path.open("x", encoding="utf-8") as handle:
        for qid in sorted(gold):
            record = records[qid]
            retrieval = retrieval_by_qid[qid]
            s1_ids = [str(uid) for uid in retrieval["s1"]["candidate_table_ids"]]
            s1 = set(s1_ids)
            s2 = [str(item["table_uid"]) for item in retrieval["s2"]["top_k"]]
            # Counterfactual policies use top-50 scores, while governed stage
            # attribution retains the production S3 boundary of ten tables.
            s3 = [str(item["table_uid"]) for item in retrieval["s3"]["top_k"][:10]]
            gold_positions = [i for i, uid in enumerate(s2, 1) if uid in gold[qid]]
            output_uids = _current(retrieval)
            evidence = record.get("evidence") or []
            binding_ids = (
                [Path(str(item["csv_path"])).stem for item in evidence]
                if record.get("status") == "OK"
                else None
            )
            bound = set(binding_ids or ())
            final_uids = {uid for ref in baseline[qid] for uid in ref_to_uids.get(ref, set())}
            stage = classify_stage_loss(
                gold_table_ids=gold[qid],
                s1_table_ids=s1_ids,
                s2_table_ids=s2,
                s3_table_ids=s3,
                output_table_ids=output_uids,
                binding_table_ids=binding_ids,
                final_table_ids=final_uids,
            )
            handle.write(
                json.dumps(
                    {
                        "qid": qid,
                        "gold_table_ids": sorted(gold[qid]),
                        "s1_table_ids": s1_ids,
                        "s1_hit": bool(s1 & gold[qid]),
                        "s2_table_ids": s2,
                        "s2_hit": bool(set(s2) & gold[qid]),
                        "gold_rank": min(gold_positions) if gold_positions else None,
                        "all_gold_ranks": gold_positions,
                        "output_n": len(output_uids),
                        "minimum_n_for_first_gold": (
                            min(gold_positions) if gold_positions else None
                        ),
                        "gold_survives_output": bool(set(output_uids) & gold[qid]),
                        "binding_survives": (
                            bool(bound & gold[qid]) if record.get("status") == "OK" else None
                        ),
                        "binding_table_ids": binding_ids,
                        "final_table_ids": sorted(final_uids),
                        "final_relevant_tables": baseline[qid],
                        "failure_stage": stage.value,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    diff_path = output / "per_qid_policy_diff.jsonl"
    with diff_path.open("x", encoding="utf-8") as handle:
        for qid in sorted(records):
            row: dict[str, Any] = {"qid": qid, "baseline": baseline[qid], "policies": {}}
            for name in _policies():
                after = policy_predictions[name][qid]
                before_set, after_set = set(baseline[qid]), set(after)
                row["policies"][name] = {
                    "relevant_tables": after,
                    "added": sorted(after_set - before_set),
                    "removed": sorted(before_set - after_set),
                    "classification": "UNCHANGED" if after == baseline[qid] else "TABLE_CHANGED",
                    "development_f2_delta": (
                        policy_per_qid[name][qid]["f2"] - baseline_per_qid[qid]["f2"]
                        if qid in gold
                        else None
                    ),
                }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    metrics_path = output / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "classification": "DEVELOPMENT_PROXY_NOT_OFFICIAL",
                "baseline_final": baseline_metrics,
                "policies": policy_results,
                "official_baseline": {
                    "submission_id": 3766,
                    "tables_precision": 0.2921,
                    "tables_recall": 0.2461,
                    "tables_f2_macro": 0.2500,
                    "tables_mrr5": 0.3360,
                    "execution_accuracy": 0.2589,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_path = output / "manifest.json"
    source = git_source_identity(ROOT)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": "text2pandas.output_n_experiment_matrix",
                "run_id": args.run_id,
                "status": "DIAGNOSTIC_COMPLETE",
                "source": source,
                "snapshots": {
                    "raw_snapshot_id": active.raw_snapshot_id,
                    "a6_build_id": active.a6_build_id,
                    "retrieval_index_id": active.retrieval_index_id,
                },
                "inputs": {
                    "records": {
                        "path": str(records_path.relative_to(ROOT)),
                        "sha256": _sha(records_path),
                    },
                    "questions": {
                        "path": str(questions_path.relative_to(ROOT)),
                        "sha256": _sha(questions_path),
                    },
                    "retrieval_traces": (
                        {
                            "path": str(traces_input.relative_to(ROOT)),
                            "sha256": _sha(traces_input),
                        }
                        if traces_input
                        else "GENERATED_BY_THIS_RUN"
                    ),
                    "gold": {"path": str(gold_path.relative_to(ROOT)), "sha256": _sha(gold_path)},
                },
                "outputs": {
                    path.name: {"sha256": _sha(path)}
                    for path in (trace_path, failure_path, diff_path, metrics_path)
                },
                "official_metrics": "NOT_MEASURED",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(policy_results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--traces", type=Path)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
