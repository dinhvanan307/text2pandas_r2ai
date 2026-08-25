#!/usr/bin/env python3
"""Set-relation reconciliation for every disputed count in 170/171.

Emits, for each named cohort: an exact predicate, a denominator, and the exact
QID list. Then emits pairwise intersections/differences so no two numbers can
be quoted as if they measured the same thing.

    python3 tools/measure_v4/reconcile_sets.py \
        --measure artifacts/measurement_closure_v4 \
        --pinned  artifacts/pipeline_e2e_v4 \
        --out     artifacts/reconciliation_v4
"""
from __future__ import annotations

import argparse, json, collections
from pathlib import Path

U1_7 = [42, 52, 238, 284, 317, 321, 322]


def load_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", required=True)
    ap.add_argument("--pinned", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    m = {r["qid"]: r for r in load_jsonl(Path(a.measure) / "unit_convention_per_qid.jsonl")}
    p = {r["qid"]: r for r in load_jsonl(Path(a.pinned) / "pipeline_per_qid.jsonl")}
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- cohorts
    cohorts = {}

    cohorts["FACTOR_MISMATCH_SET"] = {
        "predicate": "unit_convention.verdict == 'FACTOR_MISMATCH'",
        "denominator": "1012 submission records",
        "qids": sorted(q for q, r in m.items() if r["verdict"] == "FACTOR_MISMATCH"),
    }
    cohorts["REQUIRED_FACTOR_ONE_SET"] = {
        "predicate": "verdict == FACTOR_MISMATCH and required_factor == 1.0 "
                     "and actual_query_factor == 1e-6",
        "denominator": "FACTOR_MISMATCH_SET",
        "qids": sorted(q for q, r in m.items()
                       if r["verdict"] == "FACTOR_MISMATCH"
                       and r.get("required_factor") == 1.0
                       and r.get("actual_query_factor") == 1e-06),
    }
    cohorts["PINNED_PRODUCED_SET"] = {
        "predicate": "pinned pipeline run status == 'OK'",
        "denominator": "1012",
        "qids": sorted(q for q, r in p.items() if r["status"] == "OK"),
    }
    cohorts["PINNED_CHANGED_SET"] = {
        "predicate": "pinned status == OK and answer differs from parent (rel tol 1e-6)",
        "denominator": "PINNED_PRODUCED_SET",
        "qids": sorted(q for q, r in p.items()
                       if r["status"] == "OK" and not r["answer_matches_parent"]),
    }
    cohorts["PINNED_POOL_UNDERUSED_SET"] = {
        "predicate": "pinned pool offered more cells than the compiled IR consumed "
                     "(operation-recall miss, NOT a unit defect)",
        "denominator": "1012",
        "qids": sorted(q for q, r in p.items() if r.get("operand_pool_underused")),
    }
    changed = set(cohorts["PINNED_CHANGED_SET"]["qids"])
    underused = set(cohorts["PINNED_POOL_UNDERUSED_SET"]["qids"])
    cohorts["PURE_UNIT_CHANGED_SET"] = {
        "predicate": "PINNED_CHANGED_SET minus PINNED_POOL_UNDERUSED_SET "
                     "(causal precedence: an operand defect outranks a unit defect)",
        "denominator": "PINNED_CHANGED_SET",
        "qids": sorted(changed - underused),
    }
    cohorts["U1_7_REGRESSION_SET"] = {
        "predicate": "the seven QIDs review 167 proposed to patch by whitelist",
        "denominator": "n/a (externally supplied list)",
        "qids": sorted(U1_7),
    }

    # ------------------------------------------------------- pairwise relations
    names = list(cohorts)
    rel = {}
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            sx, sy = set(cohorts[x]["qids"]), set(cohorts[y]["qids"])
            rel[f"{x} vs {y}"] = {
                "n_x": len(sx), "n_y": len(sy),
                "intersection": len(sx & sy),
                "x_minus_y": sorted(sx - sy),
                "y_minus_x": sorted(sy - sx),
                "x_subset_of_y": sx <= sy,
                "y_subset_of_x": sy <= sx,
            }

    # ------------------------------- why FACTOR_MISMATCH did not become CHANGED
    fm = set(cohorts["FACTOR_MISMATCH_SET"]["qids"])
    blocked = []
    for q in sorted(fm - changed):
        pr = p.get(q, {})
        blocked.append({
            "qid": q,
            "pinned_status": pr.get("status"),
            "stage_failed": pr.get("stage_failed"),
            "reason": pr.get("reason"),
            "required_factor": m[q].get("required_factor"),
            "actual_query_factor": m[q].get("actual_query_factor"),
            "answer_matches_parent": pr.get("answer_matches_parent"),
        })

    # ---------------------- changed cases that were NOT flagged FACTOR_MISMATCH
    unexplained = []
    for q in sorted(changed - fm):
        unexplained.append({
            "qid": q,
            "measure_verdict": m[q]["verdict"],
            "measure_reason": m[q].get("reason_code"),
            "pinned_operation": p[q].get("operation"),
            "n_operands": len(p[q].get("operands") or []),
            "pool_underused": p[q].get("operand_pool_underused"),
            "parent_answer": p[q].get("parent_answer"),
            "new_answer": p[q].get("answer"),
        })

    # ------------------------------------- per-QID primary causal attribution
    # single primary cause, assigned by causal precedence, no double counting
    PRECEDENCE = ["ROUTE", "BIND", "RENDER", "EXECUTE", "VALIDATE"]
    attribution = []
    for q in sorted(p):
        pr, mr = p[q], m[q]
        if pr["status"] == "OK":
            if pr.get("operand_pool_underused"):
                primary = "OPERATION_RECALL_MISS"
            elif not pr["answer_matches_parent"]:
                primary = "UNIT_FACTOR_CORRECTED"
            else:
                primary = "PARENT_EQUIVALENT"
        else:
            primary = f"{pr['stage_failed']}:{(pr.get('reason') or '').split(':')[0]}"
        attribution.append({
            "qid": q,
            "primary_cause": primary,
            "pinned_status": pr["status"],
            "stage_failed": pr.get("stage_failed"),
            "operation": pr.get("operation"),
            "unit_verdict": mr["verdict"],
            "unit_reason": mr.get("reason_code"),
            "original_factor": mr.get("actual_query_factor"),
            "required_factor": mr.get("required_factor"),
            "parent_answer": pr.get("parent_answer"),
            "new_answer": pr.get("answer"),
        })

    with open(out / "per_qid_attribution.jsonl", "w", encoding="utf-8") as fh:
        for r in attribution:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "cohorts": {k: {**v, "n": len(v["qids"])} for k, v in cohorts.items()},
        "pairwise_relations": rel,
        "factor_mismatch_not_changed": blocked,
        "changed_not_factor_mismatch": unexplained,
        "primary_cause_distribution":
            dict(sorted(collections.Counter(r["primary_cause"] for r in attribution).items())),
        "primary_cause_sums_to_1012":
            sum(collections.Counter(r["primary_cause"] for r in attribution).values()) == 1012,
    }
    (out / "unit_set_relations.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    # console digest
    for k, v in cohorts.items():
        print(f"{k:32s} n={len(v['qids']):4d}")
    print()
    print("FACTOR_MISMATCH but NOT changed in pinned run:", len(blocked))
    print("CHANGED but NOT FACTOR_MISMATCH:", len(unexplained))
    print()
    print(json.dumps(summary["primary_cause_distribution"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
