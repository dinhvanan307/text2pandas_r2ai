#!/usr/bin/env python3
"""Does the parent's candidate pool physically contain the operands a question needs?

This separates two things 170 conflated:
  * the pipeline could not BIND      (a binding/selector defect)
  * the operands were never there    (a candidate-generation defect)

Method, per question:
  needed_years   = years named in the question text
  pool_years     = years appearing in col_label of every cell in the parent's
                   evidence CSVs (a single CSV usually holds several years)
  coverage       = |needed ∩ pool| / |needed|

A question whose pool covers < 2 of its needed years cannot be answered by any
multi-period operation, no matter how good the emitter is.
"""
from __future__ import annotations

import argparse, collections, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from text2pandas.pipelines.answering.adapters import load_cells  # noqa: E402
from text2pandas.pipelines.answering.frame import classify_operation  # noqa: E402

_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def expand_ranges(question: str) -> set[str]:
    """'giai đoạn 2021-2024' names four years, not two."""
    years = set(_YEAR.findall(question))
    for m in re.finditer(r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})", question):
        a, b = int(m.group(1)), int(m.group(2))
        if 0 < b - a <= 12:
            years |= {str(y) for y in range(a, b + 1)}
    return years


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="dir with submission.json + data/")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    recs = json.loads((root / "submission.json").read_text(encoding="utf-8"))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    cache: dict[str, list] = {}
    rows = []
    for r in recs:
        q = r["question"]
        needed = expand_ranges(q)
        pool_years: set[str] = set()
        n_cells = 0
        for e in (r.get("evidence") or []):
            key = f"{e.get('variable')}|{e.get('csv_path')}"
            if key not in cache:
                try:
                    cache[key] = load_cells(e["csv_path"], e["variable"], root=root)
                except Exception:
                    cache[key] = []
            for c in cache[key]:
                n_cells += 1
                if c.period:
                    pool_years.add(c.period)
        hit = needed & pool_years
        rows.append({
            "qid": r["id"],
            "operation": classify_operation(q).op,
            "n_needed_years": len(needed),
            "needed_years": sorted(needed),
            "n_pool_years": len(pool_years),
            "pool_years": sorted(pool_years),
            "n_periods_covered": len(hit),
            "coverage": round(len(hit) / len(needed), 3) if needed else None,
            "n_pool_cells": n_cells,
            "n_evidence": len(r.get("evidence") or []),
            # NAMING (review 173 §5.2): ">=2 years present" proves neither that
            # the question is answerable nor that the ranking set is complete.
            # A max/min over 2021-2024 with only two years in the pool can pick
            # the wrong argmax. Keep the weak and strong predicates separate and
            # never call the weak one "feasible".
            "at_least_two_covered": len(hit) >= 2,
            "all_explicit_periods_covered": bool(needed) and len(hit) == len(needed),
            # filled in once semantic gold exists; None means "not yet measurable"
            "all_gold_operand_slots_covered": None,
        })
    rows.sort(key=lambda x: x["qid"])
    with open(out / "candidate_coverage_per_qid.jsonl", "w", encoding="utf-8") as fh:
        for x in rows:
            fh.write(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n")

    def bucket(pred, label):
        sel = [x for x in rows if pred(x)]
        multi = [x for x in sel if x["n_needed_years"] >= 2]
        ge2 = sum(1 for x in multi if x["at_least_two_covered"])
        alle = sum(1 for x in multi if x["all_explicit_periods_covered"])
        return {
            "n": len(sel),
            "n_needing_2plus_periods": len(multi),
            "at_least_two_covered": ge2,
            "all_explicit_periods_covered": alle,
            "partial_two_or_more_but_not_all": ge2 - alle,
            "fewer_than_two_covered": len(multi) - ge2,
            "all_gold_operand_slots_covered": None,
            "pct_all_explicit_covered": round(100.0 * alle / len(multi), 1) if multi else 0.0,
        }

    summary = {
        "all": bucket(lambda x: True, "all"),
        "EXTREMUM": bucket(lambda x: x["operation"] == "EXTREMUM", "extremum"),
        "multi_operand_ops": bucket(
            lambda x: x["operation"] in ("DIVIDE", "GROWTH", "SUBTRACT", "SUM", "AVG"), "multi"),
        "LOOKUP": bucket(lambda x: x["operation"] == "LOOKUP", "lookup"),
        "pool_years_histogram": dict(sorted(collections.Counter(
            x["n_pool_years"] for x in rows).items())),
        "periods_covered_histogram": dict(sorted(collections.Counter(
            x["n_periods_covered"] for x in rows if x["n_needed_years"] >= 2).items())),
        "metric_definitions": {
            "at_least_two_covered": "pool contains >=2 of the years the question names "
                                    "-- a COVERAGE signal only, NOT feasibility",
            "all_explicit_periods_covered": "pool contains EVERY year the question names "
                                            "-- the minimum bar for a correct ranking/aggregate",
            "all_gold_operand_slots_covered": "null until semantic gold exists; this is the "
                                              "only true feasibility predicate",
        },
    }
    (out / "candidate_coverage_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
