#!/usr/bin/env python3
"""Score the semantic PARSER against semantic gold.

This is **not** answer accuracy. It measures one thing only: how well the
current parser reads what the question asks for. No candidate generation, no
binding, no execution.

Only fields where the two independent annotation passes AGREED are scored. A
field the annotators could not agree on is not a measuring stick -- scoring
against it would report noise as parser error.
"""
from __future__ import annotations

import argparse, collections, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from text2pandas.pipelines.answering.frame import (  # noqa: E402
    RETURN_FILTERED_VALUE, RETURN_PERIOD, RETURN_SELECT_AT_ARG,
    classify_operation, extract_basis, extract_entities, extract_entity,
    extract_periods, resolve_basis)
from text2pandas.domain.units.lexicon import scan_question_unit  # noqa: E402
from audit_candidate_coverage import expand_ranges  # noqa: E402

#: how the parser's vocabulary maps onto the gold vocabulary. EXTREMUM is the
#: parser's single bucket for four different gold operations, which is itself a
#: finding rather than a mapping problem.
PARSER_TO_GOLD_OP = {
    "LOOKUP": {"LOOKUP"},
    "SUBTRACT": {"SUBTRACT"},
    "DIVIDE": {"DIVIDE"},
    "GROWTH": {"GROWTH"},
    "SUM": {"SUM"},
    "AVG": {"AVG"},
    "EXTREMUM": {"EXTREME_VALUE", "ARG_EXTREME_PERIOD", "SELECT_AT_ARG"},
    "COUNT": {"COUNT"},
}

UNIT_TO_RESULT_KIND = {
    "MONEY": "MONEY", "PERCENT": "PERCENT_VALUE", "PERCENT_POINT": "PERCENT_POINT",
    "RATIO": "RATIO_FRACTION", "COUNT": "COUNT", "SHARES": "SHARES",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_fingerprint(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def strict_operation_family(hint):
    """Translate the typed EXTREMUM hint without collapsing its return mode."""
    if hint.op != "EXTREMUM":
        return hint.op
    if hint.return_mode == RETURN_PERIOD:
        return "ARG_EXTREME_PERIOD"
    if hint.return_mode in (RETURN_SELECT_AT_ARG, RETURN_FILTERED_VALUE):
        return "SELECT_AT_ARG"
    return "EXTREME_VALUE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--worksheet", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    gold = {json.loads(l)["qid"]: json.loads(l)
            for l in Path(a.gold).read_text(encoding="utf-8").splitlines() if l.strip()}
    qs = {json.loads(l)["qid"]: json.loads(l)["question"]
          for l in Path(a.worksheet).read_text(encoding="utf-8").splitlines() if l.strip()}
    gold_path = Path(a.gold)
    worksheet_path = Path(a.worksheet)
    out = Path(a.out)
    if out.exists():
        raise SystemExit(f"immutable output already exists: {out}")
    out.mkdir(parents=True)

    stats = collections.defaultdict(lambda: {"scored": 0, "correct": 0, "skipped": 0})
    rows = []

    for qid in sorted(gold):
        g, q = gold[qid], qs[qid]
        usable = set(g.get("gold_usable_fields") or [])
        rec = {"qid": qid}

        # ---- operation family (parser EXTREMUM covers 3 gold ops) -----------
        operation = classify_operation(q)
        p_op = operation.op
        g_op = g.get("operation_family")
        if "operation_family" in usable:
            ok = g_op in PARSER_TO_GOLD_OP.get(p_op, set())
            stats["operation_family"]["scored"] += 1
            stats["operation_family"]["correct"] += ok
            strict = strict_operation_family(operation) == g_op
            stats["operation_family_strict"]["scored"] += 1
            stats["operation_family_strict"]["correct"] += strict
            rec.update(parser_operation=p_op, gold_operation=g_op,
                       operation_ok=ok, operation_ok_strict=strict)
        else:
            stats["operation_family"]["skipped"] += 1

        # ---- basis -----------------------------------------------------------
        if "basis" in usable:
            p_basis, p_explicit_flag = resolve_basis(q)
            ok = p_basis == g.get("basis")
            stats["basis"]["scored"] += 1; stats["basis"]["correct"] += ok
            rec.update(parser_basis=p_basis, gold_basis=g.get("basis"), basis_ok=ok)
            # does the parser know it is *defaulting* rather than reading?
            ok2 = p_explicit_flag == g.get("basis_explicit")
            stats["basis_explicit"]["scored"] += 1; stats["basis_explicit"]["correct"] += ok2
            rec.update(basis_explicit_ok=ok2)

        # ---- requested unit --------------------------------------------------
        if "requested_unit" in usable:
            dim, exp, _ = scan_question_unit(q)
            if operation.return_mode == RETURN_PERIOD:
                dim, exp = "PERIOD_YEAR", None
            gu = g.get("requested_unit") or {}
            ok = (dim == gu.get("dimension")) and (exp == gu.get("scale_exponent"))
            ok_dim = dim == gu.get("dimension")
            stats["unit_full"]["scored"] += 1; stats["unit_full"]["correct"] += ok
            stats["unit_dimension"]["scored"] += 1; stats["unit_dimension"]["correct"] += ok_dim
            rec.update(parser_unit=[dim, exp],
                       gold_unit=[gu.get("dimension"), gu.get("scale_exponent")],
                       unit_ok=ok, unit_dimension_ok=ok_dim)

        # ---- result kind (derived from unit -- parser has no ResultKind) -----
        if "result_kind" in usable:
            dim, _, _ = scan_question_unit(q)
            p_kind = (
                "PERIOD_YEAR"
                if operation.return_mode == RETURN_PERIOD
                else UNIT_TO_RESULT_KIND.get(dim)
            )
            ok = p_kind == g.get("result_kind")
            stats["result_kind"]["scored"] += 1; stats["result_kind"]["correct"] += ok
            rec.update(parser_result_kind=p_kind, gold_result_kind=g.get("result_kind"),
                       result_kind_ok=ok)

        # ---- periods ---------------------------------------------------------
        if "periods" in usable:
            # Gold's period field is year-granular. A parser returning the more
            # precise ``2016-12-31`` must not be marked wrong against ``2016``.
            p_years = {period[:4] for period in extract_periods(q)}
            g_years = {p.get("year") for p in g.get("requested_periods") or []}
            ok = p_years == g_years
            stats["periods_exact"]["scored"] += 1; stats["periods_exact"]["correct"] += ok
            # does range expansion close the gap?
            ok_exp = expand_ranges(q) == g_years
            stats["periods_exact_with_range_expansion"]["scored"] += 1
            stats["periods_exact_with_range_expansion"]["correct"] += ok_exp
            rec.update(parser_periods=sorted(p_years), gold_periods=sorted(g_years),
                       periods_ok=ok, periods_ok_with_expansion=ok_exp)

        # ---- entity ----------------------------------------------------------
        if "entity_tickers" in usable:
            p_ents = list(extract_entities(q))
            p_ent = p_ents[0] if p_ents else None
            g_ent = sorted(t for t in ((e.get("ticker") for e in g.get("entity_set") or [])) if t)
            ok_any = (p_ent in g_ent) if g_ent else (p_ent is None)
            ok_all = sorted(p_ents) == g_ent
            stats["entity_first_in_gold"]["scored"] += 1
            stats["entity_first_in_gold"]["correct"] += ok_any
            stats["entity_set_exact"]["scored"] += 1
            stats["entity_set_exact"]["correct"] += ok_all
            rec.update(parser_entity=p_ent, parser_entities=sorted(p_ents), gold_entities=g_ent,
                       entity_ok=ok_any, entity_set_ok=ok_all)

        rows.append(rec)

    with open(out / "parser_vs_gold_per_qid.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    summary = {
        "schema_version": "1.0",
        "disclaimer": "SEMANTIC PARSE ACCURACY ONLY. Not answer accuracy, not "
                      "candidate/binding accuracy. Fields the two annotation "
                      "passes disagreed on are SKIPPED, not scored.",
        "n_gold_cases": len(gold),
        "inputs": {
            "gold": {"path": str(gold_path), "sha256": sha256_file(gold_path)},
            "worksheet": {
                "path": str(worksheet_path),
                "sha256": sha256_file(worksheet_path),
            },
            "implementation_sha256": implementation_fingerprint((
                ROOT / "src/text2pandas/pipelines/answering/frame.py",
                ROOT / "src/text2pandas/pipelines/answering/ir.py",
                ROOT / "src/text2pandas/pipelines/answering/units.py",
                ROOT / "src/text2pandas/domain/units/lexicon.py",
                ROOT / "tools/measure_v4/audit_candidate_coverage.py",
            )),
        },
        "metrics": {k: {"scored": v["scored"], "correct": v["correct"],
                        "accuracy": round(v["correct"] / v["scored"], 4) if v["scored"] else None,
                        "skipped_no_agreed_gold": v["skipped"]}
                    for k, v in sorted(stats.items())},
        "not_measurable": {
            "metric_exact_match": "gold agreement 0.175 -- no controlled vocabulary",
            "operand_role_exact_match": "gold agreement 0.250 -- schema underspecified",
            "operand_role_metric_match": "gold agreement 0.150",
        },
    }
    (out / "parser_vs_gold_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
