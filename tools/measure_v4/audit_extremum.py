#!/usr/bin/env python3
"""Audit the EXTREMUM cohort: is it one operation or several?

171 is right that "226 EXTREMUM" is a parser prediction, not a proven cohort.
This script (a) re-derives it, (b) splits it into the semantic subtypes that
need *different* emitters, and (c) measures the candidate-pool shape each
subtype needs, which is what actually decides implementation cost.

Subtypes, by what the answer IS:
  ARG_LABEL          "Năm nào ... cao nhất?"      -> answer is a label
  EXTREME_VALUE      "... cao nhất là bao nhiêu?" -> answer is the value
  SELECT_AT_ARG      "tại năm ... cao nhất, <other metric> là bao nhiêu?"
                     -> two stages: argmax, then look up a DIFFERENT metric
  UNCLASSIFIED       superlative present, shape not recognised

Orthogonal difficulty axes measured separately (a question can carry several):
  multi_entity       ranks across >1 company
  multi_period       ranks across >1 year
  has_filter         has a qualifying predicate ("các năm có ... > 10%")
  derived_key        ranks by a computed metric (ROE, tỷ lệ, biên, vòng quay)
"""
from __future__ import annotations

import argparse, collections, json, re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.answering.frame import classify_operation  # noqa: E402

ARG_LABEL = "ARG_LABEL"
EXTREME_VALUE = "EXTREME_VALUE"
SELECT_AT_ARG = "SELECT_AT_ARG"
UNCLASSIFIED = "UNCLASSIFIED"

_SUP = re.compile(r"(cao\s*nh[ấa]t|th[ấa]p\s*nh[ấa]t|l[ớo]n\s*nh[ấa]t|nh[ỏo]\s*nh[ấa]t)")
# "năm nào", "công ty nào", "doanh nghiệp nào", "mã nào", "đơn vị nào"
_WHICH = re.compile(r"\b(n[ăa]m|c[ôo]ng\s*ty|doanh\s*nghi[ệe]p|m[ãa]|đơn\s*v[ịi]|t[ổo]\s*ch[ứu]c)\s+n[àa]o\b")
# superlative inside a subordinate clause that qualifies a *different* subject
_AT_CLAUSE = re.compile(
    r"(t[ạa]i\s+n[ăa]m|[ởo]\s+n[ăa]m|v[àa]o\s+n[ăa]m|trong\s+n[ăa]m|c[ủu]a\s+n[ăa]m"
    r"|c[ủu]a\s+(?:c[ôo]ng\s*ty|doanh\s*nghi[ệe]p)|t[ạa]i\s+cu[ốo]i\s+n[ăa]m"
    r"|[ởo]\s+doanh\s*nghi[ệe]p|c[ủu]a\s+m[ãa])")
_FILTER = re.compile(
    r"(ch[ỉi]\s*x[ée]t|ch[ỉi]\s*t[íi]nh|trong\s*c[áa]c\s*n[ăa]m\s*c[óo]|c[áa]c\s*n[ăa]m\s*c[óo]"
    r"|c[óo]\s*.{0,40}(l[ớo]n\s*h[ơo]n|nh[ỏo]\s*h[ơo]n|tr[êe]n|d[ưu][ớo]i|d[ưu][ơo]ng|[âa]m)"
    r"|th[ỏo]a\s*m[ãa]n|đi[ềe]u\s*ki[ệe]n|lo[ạa]i\s*tr[ừư])")
_DERIVED = re.compile(
    r"(t[ỷy]\s*l[ệe]|t[ỷy]\s*tr[ọo]ng|bi[êe]n\s*l[ợo]i\s*nhu[ậa]n|roe|roa|eps"
    r"|v[òo]ng\s*quay|h[ệe]\s*s[ốo]|tr[êe]n\s*m[ỗo]i|/|t[ăa]ng\s*tr[ưu][ởo]ng"
    r"|trung\s*v[ịi]|trung\s*b[ìi]nh|m[ứu]c\s*t[ăa]ng)")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_TICKER = re.compile(r"\b([A-Z]{3,4})\b")
_STOP = {"TMCP", "CTCP", "VND", "USD", "TNHH", "NHNN", "BCTC", "ROE", "ROA", "EPS",
         "CFO", "LNST", "TSCĐ", "TSC"}


def norm(s):
    return unicodedata.normalize("NFC", s or "").lower()


def subtype(question: str) -> str:
    t = norm(question)
    m = _SUP.search(t)
    if not m:
        return UNCLASSIFIED
    head = t[:m.start()]
    tail = t[m.end():]
    if _WHICH.search(t):
        # "năm nào ... cao nhất" -> label, UNLESS a further metric is asked after
        if re.search(r"(l[àa]|b[ằa]ng)\s*bao\s*nhi[êe]u", tail):
            return SELECT_AT_ARG
        return ARG_LABEL
    # superlative qualifies a subordinate clause and something else is asked
    if _AT_CLAUSE.search(head) and re.search(r"bao\s*nhi[êe]u", tail):
        return SELECT_AT_ARG
    if re.search(r"bao\s*nhi[êe]u", tail) or re.search(r"bao\s*nhi[êe]u", t):
        return EXTREME_VALUE
    return UNCLASSIFIED


def entities(question: str) -> int:
    return len({m.group(1) for m in _TICKER.finditer(question) if m.group(1) not in _STOP})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    recs = json.loads(Path(a.submission).read_text(encoding="utf-8"))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    rows = []
    for r in recs:
        hint = classify_operation(r["question"])
        if hint.op != "EXTREMUM":
            continue
        q = r["question"]
        t = norm(q)
        rows.append({
            "qid": r["id"],
            "question": q,
            "matched_cue": hint.matched,
            "direction": "MIN" if re.search(r"(th[ấa]p|nh[ỏo])\s*nh[ấa]t", t) else "MAX",
            "subtype": subtype(q),
            "n_entities": entities(q),
            "n_years": len(set(_YEAR.findall(q))),
            "has_filter": bool(_FILTER.search(t)),
            "derived_key": bool(_DERIVED.search(t)),
            "parent_n_evidence": len(r.get("evidence") or []),
            "parent_answer": r.get("answer"),
        })
    rows.sort(key=lambda x: x["qid"])
    with open(out / "extremum_per_qid.jsonl", "w", encoding="utf-8") as fh:
        for x in rows:
            fh.write(json.dumps(x, ensure_ascii=False, sort_keys=True) + "\n")

    def pct(n):
        return round(100.0 * n / len(rows), 1) if rows else 0.0

    summary = {
        "n_extremum": len(rows),
        "cue_distribution": dict(collections.Counter(x["matched_cue"] for x in rows)),
        "direction": dict(collections.Counter(x["direction"] for x in rows)),
        "subtype": dict(collections.Counter(x["subtype"] for x in rows)),
        "difficulty_axes": {
            "multi_entity(>1 ticker)": sum(1 for x in rows if x["n_entities"] > 1),
            "multi_period(>1 year)": sum(1 for x in rows if x["n_years"] > 1),
            "has_qualifying_filter": sum(1 for x in rows if x["has_filter"]),
            "ranks_by_derived_metric": sum(1 for x in rows if x["derived_key"]),
            "none_of_the_above": sum(1 for x in rows if x["n_entities"] <= 1
                                     and x["n_years"] <= 1 and not x["has_filter"]
                                     and not x["derived_key"]),
        },
        "parent_evidence_shape": dict(collections.Counter(x["parent_n_evidence"] for x in rows)),
        "simple_cohort": {
            "predicate": "single entity, no qualifying filter, ranking key is a raw "
                         "stored metric -- i.e. what a plain max()/min() emitter could serve",
            "n": sum(1 for x in rows if x["n_entities"] <= 1 and not x["has_filter"]
                     and not x["derived_key"]),
            "qids": sorted(x["qid"] for x in rows if x["n_entities"] <= 1
                           and not x["has_filter"] and not x["derived_key"]),
        },
    }
    summary["simple_cohort"]["pct_of_extremum"] = pct(summary["simple_cohort"]["n"])
    (out / "extremum_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)[:2600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
