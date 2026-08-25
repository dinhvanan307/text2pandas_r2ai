#!/usr/bin/env python3
"""Mutually-exclusive funnel reconciliation + the 182/166 decomposition.

Answers 171 §5.1, §5.3 and §5.4 with exact sets:
  * where the 182 compiled multi-operand IRs actually went;
  * whether the ROUTE / RENDER reason tables are complete (they must sum);
  * the four distinct cell concepts that 170 called "pinned_cells".
"""
from __future__ import annotations

import argparse, collections, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cellref import extract_cellrefs  # noqa: E402

MULTI_OPS = {"DIVIDE", "GROWTH", "SUBTRACT", "SUM", "AVG"}


def load_jsonl(p: Path):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pinned", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rows = load_jsonl(Path(a.pinned) / "pipeline_per_qid.jsonl")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------- exclusive stage x reason table
    table = collections.Counter()
    for r in rows:
        if r["status"] == "OK":
            table[("PRODUCED", "OK")] += 1
        else:
            reason = (r.get("reason") or "")
            # normalise to the leading reason code, keep the discriminating tail
            head = reason.split(":")[0]
            if head == "UNIT_CONTRACT_ABSTAIN":
                head = f"UNIT_CONTRACT_ABSTAIN/{reason.split(':')[-1]}"
            table[(r["stage_failed"], head)] += 1

    by_stage = collections.Counter()
    for (stage, _reason), n in table.items():
        by_stage[stage] += n

    # -------------------------------------------- 182 multi-operand decomposition
    compiled_multi = [r for r in rows if r.get("operation") in MULTI_OPS]
    decomposition = collections.Counter()
    for r in compiled_multi:
        if r["status"] == "OK":
            decomposition[f"PRODUCED/{len(r['operands'])}_operands"] += 1
        else:
            decomposition[f"{r['stage_failed']}/{(r.get('reason') or '').split(':')[0]}"] += 1

    bind_failed = {r["qid"] for r in compiled_multi if r["stage_failed"] == "BIND"}
    not_bind_failed = sorted({r["qid"] for r in compiled_multi} - bind_failed)

    # --------------------------------------- the four distinct "cells" concepts
    cell_concepts = []
    for r in rows:
        refs, ok, _ = extract_cellrefs(r.get("parent_query") or "")
        uniq = {(x.df_var, tuple(sorted(x.filters.items()))) for x in refs} if ok else set()
        cell_concepts.append({
            "qid": r["qid"],
            "parent_query_cell_references": len(refs) if ok else None,
            "parent_unique_physical_cells": len(uniq) if ok else None,
            "parent_evidence_dataframes": r.get("parent_n_evidence"),
            "pinned_pool_cells": r.get("pinned_cells"),
            "bound_operand_cells": len(r.get("operands") or []),
            "compiled_operation": r.get("operation"),
            "status": r["status"],
        })
    with open(out / "cell_concepts_per_qid.jsonl", "w", encoding="utf-8") as fh:
        for c in cell_concepts:
            fh.write(json.dumps(c, ensure_ascii=False, sort_keys=True) + "\n")

    multi_ok = [c for c in cell_concepts
                if c["status"] == "OK" and c["bound_operand_cells"] > 1]

    summary = {
        "exclusive_stage_reason_table": {
            f"{s}|{r}": n for (s, r), n in sorted(table.items(), key=lambda kv: (kv[0][0], -kv[1]))
        },
        "stage_totals": dict(sorted(by_stage.items())),
        "stage_totals_sum": sum(by_stage.values()),
        "sums_to_n_records": sum(by_stage.values()) == len(rows),
        "multi_operand_ir_compiled": len(compiled_multi),
        "multi_operand_decomposition": dict(sorted(decomposition.items())),
        "multi_operand_not_bind_failed": {
            "n": len(not_bind_failed),
            "qids": not_bind_failed,
        },
        "cell_concept_note":
            "parent_query_cell_references / parent_unique_physical_cells / "
            "parent_evidence_dataframes / pinned_pool_cells / bound_operand_cells "
            "are FIVE different quantities. 170 used the single word 'pinned_cells' "
            "for several of them.",
        "pinned_pool_size_histogram_all":
            dict(sorted(collections.Counter(c["pinned_pool_cells"] for c in cell_concepts).items())),
        "pinned_pool_size_histogram_bind_failures":
            dict(sorted(collections.Counter(
                c["pinned_pool_cells"] for c in cell_concepts if c["qid"] in bind_failed).items())),
        "multi_operand_answers": {
            "n": len(multi_ok),
            "detail": [{k: c[k] for k in
                        ("qid", "compiled_operation", "parent_query_cell_references",
                         "parent_evidence_dataframes", "pinned_pool_cells",
                         "bound_operand_cells")} for c in multi_ok],
        },
    }
    (out / "funnel_reconciliation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items()
                      if k != "cell_concept_note"}, ensure_ascii=False, indent=2,
                     sort_keys=True)[:3800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
