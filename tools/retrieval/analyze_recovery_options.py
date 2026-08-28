#!/usr/bin/env python3
"""Analyze ranking, output-policy and binding counterfactuals from P1 traces."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.rank_s2 import BONUSES  # noqa: E402

DEFAULT_TRACE = ROOT / (
    "artifacts/runs/retrieval/"
    "table-f2-recovery-p1-attribution-a2d3ef-20260828-01/stage_attribution.jsonl"
)


def _read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedupe(values: list[str], cap: int | None = None) -> list[str]:
    result = list(dict.fromkeys(values))
    return result if cap is None else result[:cap]


def _metrics(rows: list[dict], prediction: Callable[[dict], list[str]]) -> dict:
    precision: list[float] = []
    recall: list[float] = []
    f2: list[float] = []
    hits = 0
    sizes: list[int] = []
    for row in rows:
        gold = set(row["gold_table_ids"])
        predicted = _dedupe(prediction(row))
        h = len(gold & set(predicted))
        n = len(predicted)
        g = len(gold)
        hits += bool(h)
        sizes.append(n)
        precision.append(h / n if n else 0.0)
        recall.append(h / g if g else 0.0)
        f2.append(5 * h / (4 * g + n) if g or n else 0.0)
    denominator = len(rows) or 1
    return {
        "questions": len(rows),
        "question_hits": hits,
        "question_hit_rate": hits / denominator,
        "macro_precision": sum(precision) / denominator,
        "macro_recall": sum(recall) / denominator,
        "macro_f2": sum(f2) / denominator,
        "mean_tables": sum(sizes) / denominator,
    }


def _final_for(row: dict, selected: list[str]) -> list[str]:
    bound = row["binding_table_ids"]
    return list(bound) if bound is not None else selected


def _margin_policy(row: dict, margin: float) -> list[str]:
    ranked = row["retrieval_trace"]["s2"]["top_k"]
    base = len(row["output_table_ids"])
    n = base
    if ranked:
        threshold = float(ranked[0]["score"]) - margin
        while n < min(10, len(ranked)) and float(ranked[n]["score"]) >= threshold:
            n += 1
    return row["s2_table_ids"][:n]


def _union_bound(row: dict, extra: list[str]) -> list[str]:
    bound = row["binding_table_ids"]
    if bound is None:
        return row["output_table_ids"]
    return _dedupe(list(bound) + extra, 10)


def _rank_bucket(row: dict) -> str:
    if not set(row["gold_table_ids"]) & set(row["s1_table_ids"]):
        return "GOLD_NOT_IN_S1"
    positions = row["gold_positions_s2"]
    if not positions:
        return "GOLD_NOT_IN_TOP50"
    rank = min(positions)
    if rank == 1:
        return "GOLD_RANK_1"
    if rank <= 5:
        return "GOLD_RANK_2_5"
    if rank <= 10:
        return "GOLD_RANK_6_10"
    if rank <= 20:
        return "GOLD_RANK_11_20"
    return "GOLD_RANK_21_50"


def _feature_audit(rows: list[dict]) -> dict:
    samples: dict[str, list[dict]] = {"gold": [], "non_gold": []}
    for row in rows:
        gold = set(row["gold_table_ids"])
        for item in row["retrieval_trace"]["s2"]["top_k"]:
            reasons = set(item["reasons"])
            clean = BONUSES["clean_floor"] + BONUSES["clean_span"] * float(item["clean_ratio"])
            bonus = sum(
                BONUSES[name]
                for name in ("period", "unit", "stmt", "basis", "code", "primary")
                if name in reasons
            )
            normalized_lexical = max(0.0, float(item["score"]) / clean - bonus)
            samples["gold" if item["table_uid"] in gold else "non_gold"].append(
                {
                    "rank": int(item["rank"]),
                    "score": float(item["score"]),
                    "normalized_lexical": normalized_lexical,
                    "clean_multiplier": clean,
                    "reasons": reasons,
                }
            )
    output: dict[str, dict] = {}
    for label, values in samples.items():
        output[label] = {
            "items": len(values),
            "mean_rank": mean(value["rank"] for value in values) if values else None,
            "mean_score": mean(value["score"] for value in values) if values else None,
            "mean_normalized_lexical": (
                mean(value["normalized_lexical"] for value in values) if values else None
            ),
            "mean_clean_multiplier": (
                mean(value["clean_multiplier"] for value in values) if values else None
            ),
            "feature_rates": {
                feature: (
                    sum(feature in value["reasons"] for value in values) / len(values)
                    if values
                    else 0.0
                )
                for feature in ("bm25", "period", "unit", "stmt", "basis", "code", "primary")
            },
        }
    return output


def run(args: argparse.Namespace) -> int:
    rows = _read(args.trace.resolve())
    out = ROOT / "artifacts/runs/retrieval" / args.run_id
    try:
        out.mkdir(parents=True)
    except FileExistsError as error:
        raise RuntimeError(f"immutable output already exists: {out}") from error

    buckets = Counter(_rank_bucket(row) for row in rows)
    by_operation: dict[str, Counter] = defaultdict(Counter)
    by_mode: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        bucket = _rank_bucket(row)
        by_operation[row["operation"]][bucket] += 1
        by_mode[row["mode"]][bucket] += 1
    ranking = {
        "classification": "DIAGNOSTIC",
        "rank_buckets": dict(sorted(buckets.items())),
        "by_operation": {key: dict(sorted(value.items())) for key, value in sorted(by_operation.items())},
        "by_mode": {key: dict(sorted(value.items())) for key, value in sorted(by_mode.items())},
        "feature_contribution": _feature_audit(rows),
        "promotion_decision": "KEEP_BASELINE",
        "blocker": "The 95-question labels are development gold; untouched sealed held-out gold is absent.",
    }

    policy: dict[str, dict] = {
        "baseline_output": _metrics(rows, lambda row: row["output_table_ids"]),
        "baseline_final": _metrics(rows, lambda row: row["final_table_ids"]),
    }
    for n in (5, 8, 10):
        policy[f"fixed_{n}_output"] = _metrics(rows, lambda row, n=n: row["s2_table_ids"][:n])
        policy[f"fixed_{n}_final"] = _metrics(
            rows, lambda row, n=n: _final_for(row, row["s2_table_ids"][:n])
        )
    for margin in (0.05, 0.1, 0.2, 0.3, 0.5):
        key = str(margin).replace(".", "_")
        policy[f"margin_{key}_output"] = _metrics(
            rows, lambda row, margin=margin: _margin_policy(row, margin)
        )
        policy[f"margin_{key}_final"] = _metrics(
            rows,
            lambda row, margin=margin: _final_for(row, _margin_policy(row, margin)),
        )
    policy["classification"] = "DIAGNOSTIC"
    policy["promotion_decision"] = "KEEP_BASELINE"
    policy["blocker"] = (
        "A/B uses the same 95-question development slice that motivated the hypotheses; "
        "it cannot promote a production N policy."
    )

    binding = {
        "classification": "DIAGNOSTIC",
        "baseline_final": _metrics(rows, lambda row: row["final_table_ids"]),
        "union_bound_and_output": _metrics(
            rows, lambda row: _union_bound(row, row["output_table_ids"])
        ),
        "union_bound_and_top5": _metrics(
            rows, lambda row: _union_bound(row, row["s2_table_ids"][:5])
        ),
        "union_bound_and_top10": _metrics(
            rows, lambda row: _union_bound(row, row["s2_table_ids"][:10])
        ),
        "promotion_decision": "KEEP_BASELINE",
        "blocker": (
            "The local union gain is development-only and the submission scorer contract "
            "does not prove its precision impact on hidden gold."
        ),
    }

    per_qid_path = out / "per_qid_options.jsonl"
    with per_qid_path.open("x", encoding="utf-8") as handle:
        for row in rows:
            candidate = _margin_policy(row, 0.2)
            handle.write(
                json.dumps(
                    {
                        "qid": row["qid"],
                        "operation": row["operation"],
                        "mode": row["mode"],
                        "rank_bucket": _rank_bucket(row),
                        "stage_loss": row["stage_loss"],
                        "baseline_output": row["output_table_ids"],
                        "margin_0_2_output": candidate,
                        "baseline_final": row["final_table_ids"],
                        "union_bound_and_output": _union_bound(row, row["output_table_ids"]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    outputs = {
        "ranking_audit.json": ranking,
        "policy_sweep.json": policy,
        "binding_sweep.json": binding,
    }
    for name, payload in outputs.items():
        (out / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "schema_version": "1.0",
        "kind": "text2pandas.table_retrieval_recovery_options",
        "run_id": args.run_id,
        "status": "DIAGNOSTIC_ONLY",
        "input": {"path": str(args.trace.resolve().relative_to(ROOT)), "sha256": _sha(args.trace.resolve())},
        "outputs": {
            name: {"sha256": _sha(out / name)}
            for name in (*outputs, per_qid_path.name)
        },
        "decision": "KEEP_BASELINE",
        "official_metrics": "NOT_MEASURED",
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "run_id": args.run_id,
        "rank_buckets": ranking["rank_buckets"],
        "baseline_final_f2": binding["baseline_final"]["macro_f2"],
        "union_final_f2": binding["union_bound_and_output"]["macro_f2"],
        "decision": "KEEP_BASELINE",
    }, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
