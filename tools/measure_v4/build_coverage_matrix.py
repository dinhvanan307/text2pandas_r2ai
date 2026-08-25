#!/usr/bin/env python3
"""Select the semantic-gold cohort by COVERAGE, not by convenience.

Picks QIDs that exercise the semantic failure modes we actually need to
measure, using only surface features of the *question text* plus the parent's
structural metadata (how many evidence dataframes it used). It never reads a
parent answer or a prediction trace -- those must not influence which cases
become gold, let alone what the gold says.

Output feeds manual annotation; it is NOT gold itself.
"""
from __future__ import annotations

import argparse, collections, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from text2pandas.answer_pipeline.frame import classify_operation, extract_basis  # noqa: E402
from unitlex import scan_question_unit  # noqa: E402
from audit_candidate_coverage import expand_ranges  # noqa: E402

_TICKER = re.compile(r"\b([A-Z]{3,4})\b")
_STOP = {"TMCP", "CTCP", "VND", "USD", "TNHH", "NHNN", "BCTC", "ROE", "ROA",
         "EPS", "CFO", "LNST", "TSC", "XDCB", "DN", "GTCG"}

# ------------------------------------------------- surface semantic detectors
PAT = {
    "percentage_point": re.compile(r"đi[ểe]m\s*ph[ầa]n\s*tr[ăa]m|đi[ểe]m\s*%", re.I),
    "extremum": re.compile(r"cao\s*nh[ấa]t|th[ấa]p\s*nh[ấa]t|l[ớo]n\s*nh[ấa]t|nh[ỏo]\s*nh[ấa]t", re.I),
    "arg_period": re.compile(r"n[ăa]m\s*n[àa]o", re.I),
    "arg_entity": re.compile(r"(c[ôo]ng\s*ty|doanh\s*nghi[ệe]p|m[ãa])\s*n[àa]o", re.I),
    "select_at_arg": re.compile(r"(t[ạa]i\s*n[ăa]m|[ởo]\s*n[ăa]m|v[àa]o\s*n[ăa]m)\s*.{0,60}?"
                                r"(cao\s*nh[ấa]t|th[ấa]p\s*nh[ấa]t|l[ớo]n\s*nh[ấa]t)", re.I),
    "count": re.compile(r"c[óo]\s*bao\s*nhi[êe]u\s*(c[ôo]ng\s*ty|doanh\s*nghi[ệe]p|m[ãa])"
                        r"|s[ốo]\s*l[ưu][ợo]ng\s*(c[ôo]ng\s*ty|doanh\s*nghi[ệe]p)", re.I),
    "filter": re.compile(r"ch[ỉi]\s*x[ée]t|ch[ỉi]\s*t[íi]nh|c[áa]c\s*n[ăa]m\s*c[óo]"
                         r"|x[ée]t\s*c[áa]c|th[ỏo]a\s*m[ãa]n|trung\s*v[ịi]", re.I),
    "basis_explicit": re.compile(r"c[ôo]ng\s*ty\s*m[ẹe]|h[ợo]p\s*nh[ấa]t|ri[êe]ng\s*l[ẻe]", re.I),
    "opening_closing": re.compile(r"s[ốo]\s*đ[ầa]u\s*n[ăa]m|s[ốo]\s*cu[ốo]i\s*n[ăa]m"
                                  r"|đ[ầa]u\s*k[ỳy]|cu[ốo]i\s*k[ỳy]", re.I),
    "derived_metric": re.compile(r"t[ỷy]\s*l[ệe]|t[ỷy]\s*tr[ọo]ng|bi[êe]n\s*l[ợo]i\s*nhu[ậa]n"
                                 r"|roe|roa|eps|v[òo]ng\s*quay|h[ệe]\s*s[ốo]", re.I),
    "difference": re.compile(r"ch[êe]nh\s*l[ệe]ch|m[ứu]c\s*thay\s*đ[ổo]i|hi[ệe]u\s*s[ốo]", re.I),
    "growth": re.compile(r"t[ăa]ng\s*tr[ưu][ởo]ng|t[ốo]c\s*đ[ộo]\s*t[ăa]ng", re.I),
    "sum": re.compile(r"t[ổo]ng\s*c[ộo]ng|c[ộo]ng\s*l[ạa]i", re.I),
    "avg": re.compile(r"trung\s*b[ìi]nh|b[ìi]nh\s*qu[âa]n", re.I),
    "ratio_relational": re.compile(r"tr[êe]n\s+(?![\d,.])[a-zà-ỹ]|chi[ếe]m\s*bao\s*nhi[êe]u"
                                   r"|g[ấa]p\s*(?:bao\s*nhi[êe]u\s*)?l[ầa]n", re.I),
}


def tickers(q: str) -> list[str]:
    seen, out = set(), []
    for m in _TICKER.finditer(q):
        t = m.group(1)
        if t not in _STOP and t not in seen:
            seen.add(t); out.append(t)
    return out


def features(rec: dict) -> dict:
    q = rec["question"]
    years = expand_ranges(q)
    tk = tickers(q)
    f = {k: bool(p.search(q)) for k, p in PAT.items()}
    f.update({
        "qid": rec["id"],
        "n_years": len(years),
        "years": sorted(years),
        "n_tickers": len(tk),
        "tickers": tk,
        "multi_entity": len(tk) > 1,
        "two_period": len(years) == 2,
        "multi_period": len(years) >= 2,
        "parser_operation": classify_operation(q).op,
        "parser_basis": extract_basis(q),
        "parser_unit": scan_question_unit(q)[0],
        "parent_n_evidence": len(rec.get("evidence") or []),
        "question": q,
    })
    return f


#: (category, predicate, required count) -- see 175 §2 for the rationale
CATEGORIES = [
    ("single_lookup",     lambda f: f["parser_operation"] == "LOOKUP" and f["n_years"] <= 1
                                    and not f["extremum"] and not f["derived_metric"], 4),
    ("two_period",        lambda f: f["two_period"] and not f["extremum"], 4),
    ("subtract_pct_point", lambda f: f["percentage_point"], 4),
    ("divide_ratio",      lambda f: f["ratio_relational"] and not f["extremum"], 4),
    ("growth",            lambda f: f["growth"], 3),
    ("sum",               lambda f: f["sum"], 3),
    ("avg",               lambda f: f["avg"], 3),
    ("count",             lambda f: f["count"], 2),
    ("extreme_value",     lambda f: f["extremum"] and not f["arg_period"]
                                    and not f["select_at_arg"], 3),
    ("arg_extreme_period", lambda f: f["arg_period"] and f["extremum"], 2),
    ("multi_entity",      lambda f: f["multi_entity"], 2),
    ("basis_distinction", lambda f: f["basis_explicit"], 2),
    ("nested_operation",  lambda f: f["select_at_arg"] or (f["filter"] and f["extremum"]), 2),
    ("period_year_result", lambda f: f["arg_period"], 2),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", type=int, default=40)
    a = ap.parse_args()

    recs = json.loads(Path(a.submission).read_text(encoding="utf-8"))
    feats = {r["id"]: features(r) for r in recs}
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    # deterministic selection: for each category take the lowest QIDs that
    # match and are not yet chosen, so the cohort is reproducible and unbiased
    # by anything downstream.
    chosen: dict[int, list[str]] = {}
    per_cat: dict[str, list[int]] = {}
    for name, pred, need in CATEGORIES:
        pool = sorted(q for q, f in feats.items() if pred(f))
        picked = []
        # prefer QIDs already chosen (overlap is allowed and desirable)
        for q in sorted(chosen, key=lambda x: x):
            if len(picked) >= need:
                break
            if pred(feats[q]):
                picked.append(q)
        for q in pool:
            if len(picked) >= need:
                break
            if q not in picked:
                picked.append(q)
        per_cat[name] = picked
        for q in picked:
            chosen.setdefault(q, []).append(name)

    # top up to target with the most semantically loaded unchosen questions
    def load(f):
        return sum(bool(f[k]) for k in PAT) + (1 if f["multi_period"] else 0)
    if len(chosen) < a.target:
        rest = sorted((q for q in feats if q not in chosen),
                      key=lambda q: (-load(feats[q]), q))
        for q in rest[: a.target - len(chosen)]:
            chosen[q] = ["topup_high_semantic_load"]

    matrix = {
        "n_selected": len(chosen),
        "target": a.target,
        "categories": {n: {"required": need, "selected": per_cat[n],
                           "n_available_in_corpus": sum(1 for f in feats.values() if pred(f))}
                       for n, pred, need in CATEGORIES},
        "selection_rule": "lowest QID matching each category predicate, reusing already "
                          "chosen QIDs first so categories overlap; deterministic",
        "excluded_signals": ["parent answer", "parent pandas_query", "pipeline prediction",
                             "heuristic subtype audit"],
        "qid_to_categories": {str(q): cats for q, cats in sorted(chosen.items())},
    }
    (out / "coverage_matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    with open(out / "annotation_worksheet.jsonl", "w", encoding="utf-8") as fh:
        for q in sorted(chosen):
            f = dict(feats[q]); f["categories"] = chosen[q]
            fh.write(json.dumps(f, ensure_ascii=False, sort_keys=True) + "\n")

    print(json.dumps({"n_selected": len(chosen),
                      "per_category": {n: len(per_cat[n]) for n, _, _ in CATEGORIES},
                      "available": {n: matrix["categories"][n]["n_available_in_corpus"]
                                    for n, _, _ in CATEGORIES}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
