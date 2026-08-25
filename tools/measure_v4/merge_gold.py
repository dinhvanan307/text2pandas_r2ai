#!/usr/bin/env python3
"""Compare two independent annotation passes, adjudicate, emit gold.

METHOD NAME MATTERS. This is **two independent model passes with disjoint
context**, not a human blinded recheck. Two runs of the same model share a
prior, so their agreement is an upper bound on reliability, not proof of
correctness. The artifacts say so explicitly and the report must repeat it.

Adjudication rule, applied per field:
  * both passes agree            -> gold takes the agreed value, field AGREED
  * either pass says AMBIGUOUS   -> gold record is AMBIGUOUS
  * passes disagree              -> gold field is UNRESOLVED and the
                                    disagreement is logged with both readings
Nothing is silently broken in favour of one pass.
"""
from __future__ import annotations

import argparse, collections, json
from pathlib import Path

#: fields compared for agreement, and how to normalise them first
SCALAR_FIELDS = ["basis", "basis_explicit", "operation_family", "result_kind",
                 "annotation_status"]


def load(p: Path):
    return {json.loads(l)["qid"]: json.loads(l)
            for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}


def norm_periods(rec):
    return sorted((p.get("year"), p.get("point")) for p in rec.get("requested_periods") or [])


def norm_entities(rec):
    return sorted((e.get("ticker"), (e.get("name") or "").strip().lower() or None)
                  for e in rec.get("entity_set") or [])


def norm_entity_tickers(rec):
    return sorted(t for t in ((e.get("ticker") for e in rec.get("entity_set") or [])) if t)


def norm_roles(rec):
    return [o.get("role") for o in rec.get("operand_specs") or []]


def norm_role_metrics(rec):
    return sorted((o.get("role"), o.get("metric_id")) for o in rec.get("operand_specs") or [])


def norm_metrics(rec):
    return sorted({o.get("metric_id") for o in rec.get("operand_specs") or [] if o.get("metric_id")})


def norm_unit(rec):
    u = rec.get("requested_unit") or {}
    return (u.get("dimension"), u.get("scale_exponent"))


COMPARATORS = {
    "basis": lambda r: r.get("basis"),
    "basis_explicit": lambda r: r.get("basis_explicit"),
    "operation_family": lambda r: r.get("operation_family"),
    "result_kind": lambda r: r.get("result_kind"),
    "requested_unit": norm_unit,
    "periods": norm_periods,
    "entity_tickers": norm_entity_tickers,
    "operand_roles": norm_roles,
    "operand_role_metrics": norm_role_metrics,
    "metric_set": norm_metrics,
    "rank_direction": lambda r: (r.get("rank_spec") or {}).get("direction"),
    "return_result_kind": lambda r: (r.get("return_spec") or {}).get("result_kind"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pass-a", required=True)
    ap.add_argument("--pass-b", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    A, B = load(Path(a.pass_a)), load(Path(a.pass_b))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    qids = sorted(set(A) | set(B))

    field_stats = {f: {"agree": 0, "disagree": 0, "n": 0} for f in COMPARATORS}
    disagreements = []
    gold = []

    for q in qids:
        ra, rb = A.get(q), B.get(q)
        if ra is None or rb is None:
            disagreements.append({"qid": q, "field": "__presence__",
                                  "pass_a": ra is not None, "pass_b": rb is not None,
                                  "resolution": "UNRESOLVED"})
            continue

        rec = dict(ra)                       # start from A, then adjudicate field by field
        unresolved_fields, ambiguous_fields = [], []

        for fname, fn in COMPARATORS.items():
            va, vb = fn(ra), fn(rb)
            field_stats[fname]["n"] += 1
            if va == vb:
                field_stats[fname]["agree"] += 1
                continue
            field_stats[fname]["disagree"] += 1
            unresolved_fields.append(fname)
            disagreements.append({
                "qid": q, "field": fname,
                "pass_a": va, "pass_b": vb,
                "pass_a_note": ra.get("annotator_notes", "")[:220],
                "pass_b_note": rb.get("annotator_notes", "")[:220],
                "resolution": "UNRESOLVED_FIELD",
            })

        if ra.get("annotation_status") != "RESOLVED":
            ambiguous_fields.append(f"pass_a:{ra.get('annotation_status')}")
        if rb.get("annotation_status") != "RESOLVED":
            ambiguous_fields.append(f"pass_b:{rb.get('annotation_status')}")

        if ambiguous_fields:
            status = "AMBIGUOUS"
        elif unresolved_fields:
            status = "UNRESOLVED"
        else:
            status = "RESOLVED"

        rec["annotation_status"] = status
        rec["agreement"] = {
            "method": "two_independent_model_passes_disjoint_context",
            "NOT": "human_blinded_recheck",
            "fields_agreed": [f for f in COMPARATORS if f not in unresolved_fields],
            "fields_disagreed": unresolved_fields,
            "pass_a_status": ra.get("annotation_status"),
            "pass_b_status": rb.get("annotation_status"),
        }
        # a field the two passes disagree on is NOT gold; blank it out so nobody
        # can accidentally score against a coin flip
        for f in unresolved_fields:
            rec[f"__unresolved_{f}"] = {"pass_a": COMPARATORS[f](ra),
                                        "pass_b": COMPARATORS[f](rb)}
        rec["gold_usable_fields"] = [f for f in COMPARATORS if f not in unresolved_fields]
        gold.append(rec)

    gold.sort(key=lambda r: r["qid"])
    with open(out / "semantic_gold.jsonl", "w", encoding="utf-8") as fh:
        for r in gold:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with open(out / "disagreement_log.jsonl", "w", encoding="utf-8") as fh:
        for d in disagreements:
            fh.write(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n")

    case_agree = sum(1 for r in gold if not r["agreement"]["fields_disagreed"])
    coverage = {
        "method": "two_independent_model_passes_disjoint_context",
        "method_caveat": "NOT a human blinded recheck. Two runs of one model share "
                         "a prior; agreement bounds reliability from above and is "
                         "not evidence of correctness.",
        "n_cases": len(gold),
        "case_level_full_agreement": case_agree,
        "case_level_agreement_rate": round(case_agree / len(gold), 4) if gold else 0.0,
        "status_distribution": dict(collections.Counter(r["annotation_status"] for r in gold)),
        "field_agreement": {
            f: {"n": s["n"], "agree": s["agree"], "disagree": s["disagree"],
                "rate": round(s["agree"] / s["n"], 4) if s["n"] else 0.0}
            for f, s in field_stats.items()},
        "n_disagreements": len(disagreements),
        "provenance_status": dict(collections.Counter(
            r.get("provenance_status") for r in gold)),
    }
    (out / "field_coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({k: coverage[k] for k in
                      ("n_cases", "case_level_full_agreement", "case_level_agreement_rate",
                       "status_distribution", "n_disagreements", "provenance_status")},
                     ensure_ascii=False, indent=2))
    print("\nfield agreement:")
    for f, s in sorted(coverage["field_agreement"].items(), key=lambda kv: kv[1]["rate"]):
        print(f"  {f:24s} {s['agree']:3d}/{s['n']:3d}  {s['rate']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
