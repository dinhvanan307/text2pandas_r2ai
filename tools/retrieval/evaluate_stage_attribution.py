#!/usr/bin/env python3
"""Evaluate canonical retrieval transitions on governed local table gold.

This is a diagnostic tool.  It never feeds gold into production retrieval and
never claims an official score.  Outputs are immutable and checksum-bound.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots
from text2pandas.pipelines.answering import classify_operation
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.evalkit.attribution import classify_stage_loss
from text2pandas.pipelines.retrieval.submission_adapter import (
    RetrievalToSubmission,
    to_submission_ref,
)

DEFAULT_GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"
DEFAULT_RECORDS = (
    ROOT
    / "artifacts/runs/answer/canonical-v2-a2d3ef030861-b-e2e-01/records.jsonl"
)
EXPECTED_BASELINE = {
    "questions": 95,
    "gold_items": 554,
    "s1_question_any_hit": 95,
    "s1_gold_items_hit": 554,
    "question_hit_at_10": 86,
    "dynamic_policy_question_hit": 50,
}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uid_list(items: Iterable[dict[str, object]]) -> list[str]:
    return [str(item["table_uid"]) for item in items]


def _positions(ranked: list[str], gold: frozenset[str]) -> list[int]:
    return [index for index, uid in enumerate(ranked, 1) if uid in gold]


def _macro_metrics(rows: list[dict[str, object]], key: str, k: int | None = None) -> dict:
    precision: list[float] = []
    recall: list[float] = []
    f2: list[float] = []
    hit = 0
    for row in rows:
        gold = frozenset(str(value) for value in row["gold_table_ids"])
        predicted = [str(value) for value in row[key]]
        if k is not None:
            predicted = predicted[:k]
        n = len(predicted)
        h = len(gold & set(predicted))
        g = len(gold)
        hit += bool(h)
        precision.append(h / n if n else 0.0)
        recall.append(h / g if g else 0.0)
        f2.append(5 * h / (4 * g + n) if g or n else 0.0)
    total = len(rows) or 1
    return {
        "question_hits": hit,
        "question_hit_rate": hit / total,
        "macro_precision": sum(precision) / total,
        "macro_recall": sum(recall) / total,
        "macro_f2": sum(f2) / total,
    }


def _git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def run(args: argparse.Namespace) -> int:
    paths = ProjectPaths.from_repo_root(ROOT)
    active = ActiveSnapshots.load(paths)
    database = active.retrieval_path / "retrieval.db"
    questions_path = active.raw_path / "questions/questions.jsonl"
    gold_path = args.gold.resolve()
    records_path = args.canonical_records.resolve()
    out = paths.run_dir("retrieval", args.run_id)
    try:
        out.mkdir(parents=True)
    except FileExistsError as error:
        raise RuntimeError(f"immutable output already exists: {out}") from error

    questions = {
        int(row["id"]): str(row["question"])
        for row in _read_jsonl(questions_path)
    }
    gold = {
        int(row["id"]): frozenset(str(uid) for uid in row.get("gold_table_uids") or ())
        for row in _read_jsonl(gold_path)
        if row.get("gold_table_uids") and not row.get("uncertain")
    }
    canonical = {int(row["qid"]): row for row in _read_jsonl(records_path)}
    missing = sorted(set(gold) - set(canonical))
    if missing:
        raise ValueError(f"canonical records missing gold QIDs: {missing}")

    connection = sqlite3.connect(
        f"file:{database.resolve()}?mode=ro&immutable=1", uri=True
    )
    adapter = RetrievalToSubmission(
        load_aliases("a6"),
        top_k_rank=args.top_k_rank,
        top_k_rerank=args.top_k_rerank,
        max_n=args.max_tables,
    )
    ref_to_uids: dict[str, set[str]] = {}
    for uid, evidence_ref in connection.execute(
        "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL"
    ):
        try:
            ref = to_submission_ref(str(evidence_ref))
        except ValueError:
            continue
        ref_to_uids.setdefault(ref, set()).add(str(uid))

    rows: list[dict[str, object]] = []
    try:
        for qid in sorted(gold):
            question = questions[qid]
            refs = adapter.refs_for(connection, qid, question)
            retrieval = refs.trace
            s1 = [str(value) for value in retrieval["s1"]["candidate_table_ids"]]
            s2 = _uid_list(retrieval["s2"]["top_k"])
            s3 = _uid_list(retrieval["s3"]["top_k"])
            output_ids = [
                str(value) for value in retrieval["output_policy"]["selected_table_ids"]
            ]
            record = canonical[qid]
            final_refs = [str(value) for value in record.get("relevant_tables") or ()]
            final_ids = sorted(
                {uid for ref in final_refs for uid in ref_to_uids.get(ref, set())}
            )
            evidence = record.get("evidence") or []
            binding_ids = (
                [Path(str(item["csv_path"])).stem for item in evidence]
                if record.get("status") == "OK"
                else None
            )
            gold_ids = gold[qid]
            loss = classify_stage_loss(
                gold_table_ids=gold_ids,
                s1_table_ids=s1,
                s2_table_ids=s2,
                s3_table_ids=s3,
                output_table_ids=output_ids,
                binding_table_ids=binding_ids,
                final_table_ids=final_ids,
            )
            rows.append(
                {
                    "qid": qid,
                    "question": question,
                    "mode": retrieval["intent"]["mode"],
                    "operation": classify_operation(question).op,
                    "gold_table_ids": sorted(gold_ids),
                    "s1_table_ids": s1,
                    "s2_table_ids": s2,
                    "s3_table_ids": s3,
                    "output_table_ids": output_ids,
                    "binding_table_ids": binding_ids,
                    "final_table_ids": final_ids,
                    "final_relevant_tables": final_refs,
                    "unmapped_final_refs": [
                        ref for ref in final_refs if ref not in ref_to_uids
                    ],
                    "gold_positions_s2": _positions(s2, gold_ids),
                    "gold_positions_s3": _positions(s3, gold_ids),
                    "stage_loss": loss.value,
                    "retrieval_trace": retrieval,
                }
            )
    finally:
        connection.close()

    gold_items = sum(len(row["gold_table_ids"]) for row in rows)
    s1_question_hit = sum(
        bool(set(row["gold_table_ids"]) & set(row["s1_table_ids"])) for row in rows
    )
    s1_item_hit = sum(
        len(set(row["gold_table_ids"]) & set(row["s1_table_ids"])) for row in rows
    )
    ranking = {
        str(k): _macro_metrics(rows, "s2_table_ids", k)
        for k in (1, 5, 10, 20)
    }
    output_metrics = _macro_metrics(rows, "output_table_ids")
    final_metrics = _macro_metrics(rows, "final_table_ids")
    mrr5 = sum(
        (1 / min(row["gold_positions_s2"]))
        if row["gold_positions_s2"] and min(row["gold_positions_s2"]) <= 5
        else 0.0
        for row in rows
    ) / max(len(rows), 1)
    gate_actual = {
        "questions": len(rows),
        "gold_items": gold_items,
        "s1_question_any_hit": s1_question_hit,
        "s1_gold_items_hit": s1_item_hit,
        "question_hit_at_10": ranking["10"]["question_hits"],
        "dynamic_policy_question_hit": output_metrics["question_hits"],
    }
    gate_errors = {
        key: {"expected": expected, "actual": gate_actual.get(key)}
        for key, expected in EXPECTED_BASELINE.items()
        if gate_actual.get(key) != expected
    }
    status = "PASS" if not gate_errors else "BLOCKED"
    metrics = {
        "schema_version": "1.0",
        "classification": "DIAGNOSTIC",
        "status": status,
        "questions": len(rows),
        "gold_items": gold_items,
        "s1": {
            "question_any_hit": s1_question_hit,
            "question_any_hit_rate": s1_question_hit / max(len(rows), 1),
            "gold_items_hit": s1_item_hit,
            "gold_item_recall": s1_item_hit / max(gold_items, 1),
        },
        "ranking": ranking,
        "mrr_at_5": mrr5,
        "dynamic_output_policy": output_metrics,
        "canonical_final": final_metrics,
        "stage_loss_counts": dict(sorted(Counter(row["stage_loss"] for row in rows).items())),
        "baseline_gate": {
            "expected": EXPECTED_BASELINE,
            "actual": gate_actual,
            "errors": gate_errors,
        },
        "official_metrics": "NOT_MEASURED",
    }

    rows_path = out / "stage_attribution.jsonl"
    with rows_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    metrics_path = out / "metrics.json"
    metrics_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "1.0",
        "kind": "text2pandas.table_retrieval_stage_attribution",
        "run_id": args.run_id,
        "status": status,
        "source": {"git_head": _git_head(), "git_dirty_expected": True},
        "snapshots": {
            "raw_snapshot_id": active.raw_snapshot_id,
            "a6_build_id": active.a6_build_id,
            "retrieval_index_id": active.retrieval_index_id,
        },
        "inputs": {
            "questions": {"path": str(questions_path.relative_to(ROOT)), "sha256": _sha(questions_path)},
            "gold": {"path": str(gold_path.relative_to(ROOT)), "sha256": _sha(gold_path)},
            "canonical_records": {"path": str(records_path.relative_to(ROOT)), "sha256": _sha(records_path)},
        },
        "parameters": {
            "top_k_rank": args.top_k_rank,
            "top_k_rerank": args.top_k_rerank,
            "max_tables": args.max_tables,
        },
        "outputs": {
            "stage_attribution": {"path": rows_path.name, "sha256": _sha(rows_path), "records": len(rows)},
            "metrics": {"path": metrics_path.name, "sha256": _sha(metrics_path)},
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"run_id": args.run_id, "status": status, **gate_actual}, indent=2))
    return 0 if status == "PASS" or args.no_baseline_gate else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--canonical-records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--top-k-rank", type=int, default=50)
    parser.add_argument("--top-k-rerank", type=int, default=10)
    parser.add_argument("--max-tables", type=int, default=10)
    parser.add_argument("--no-baseline-gate", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
