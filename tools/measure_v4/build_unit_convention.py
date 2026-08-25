#!/usr/bin/env python3
"""Per-QID unit-convention reconciliation.

For every QID we derive, from data only (no QID whitelist):

  question_dimension / question_scale_exponent   <- question text
  column_dimension   / column_scale_exponent     <- selected cell col_label (+row_path fallback)
  storage_exp                                    <- value / parse(value_raw)
  required_factor = 10^(column_exp - question_exp) / 10^storage_exp
  actual_factor   = net multiplicative constant of the emitted pandas_query (AST)

Verdict:
  FACTOR_MATCH        required == actual (rel tol)
  FACTOR_MISMATCH     both known and different
  NOT_MEASURABLE      with an explicit reason_code

reason_code vocabulary is closed and every QID gets exactly one verdict.
"""
from __future__ import annotations
import ast, csv, json, argparse, sys, collections
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unitlex import (parse_raw_number, storage_ratio, snap_power_of_ten,
                     scan_unit, scan_question_unit, MONEY, PERCENT, RATIO,
                     COUNT, SHARES, UNKNOWN)
from cellref import extract_cellrefs
from scan_query_factors import scan_one, net_factor

REASONS = [
    "QUERY_PARSE_FAILED",
    "NO_CELLREF",
    "MULTI_CELL_QUERY",
    "EVIDENCE_MISSING",
    "CSV_MISSING",
    "CELL_NOT_FOUND",
    "RAW_UNPARSEABLE",
    "STORAGE_RATIO_NOT_POWER_OF_TEN",
    "COLUMN_UNIT_UNKNOWN",
    "QUESTION_UNIT_UNKNOWN",
    "DIMENSION_MISMATCH",
    "NON_MONEY_DIMENSION",
    "QUERY_FACTOR_UNKNOWN",
]


def load_csv(path: Path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def find_cell(rows, filters):
    for r in rows:
        if all(str(r.get(k, "")) == str(v) for k, v in filters.items()):
            return r
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="dir containing submission.json + data/")
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary", required=True)
    a = ap.parse_args()
    root = Path(a.root)
    recs = json.loads((root / "submission.json").read_text(encoding="utf-8"))
    csv_cache: dict[str, list] = {}

    out = []
    for r in recs:
        qid = r["id"]
        q = r.get("pandas_query") or ""
        rec = {"qid": qid, "verdict": None, "reason_code": None}
        qdim, qexp, qtok = scan_question_unit(r.get("question", ""))
        rec.update(question_dimension=qdim, question_scale_exponent=qexp,
                   question_unit_token=qtok)

        refs, ok, err = extract_cellrefs(q)
        ast_rec = scan_one(q)
        af = net_factor(ast_rec)
        rec["actual_query_factor"] = af
        rec["n_cellrefs"] = len(refs)

        if not ok:
            rec.update(verdict="NOT_MEASURABLE", reason_code="QUERY_PARSE_FAILED")
            out.append(rec); continue
        if not refs:
            rec.update(verdict="NOT_MEASURABLE", reason_code="NO_CELLREF")
            out.append(rec); continue
        if len(refs) > 1:
            rec.update(verdict="NOT_MEASURABLE", reason_code="MULTI_CELL_QUERY")
            out.append(rec); continue

        ref = refs[0]
        ev = {e.get("variable"): e.get("csv_path") for e in (r.get("evidence") or [])}
        path = ev.get(ref.df_var)
        rec["csv_path"] = path
        if not path:
            rec.update(verdict="NOT_MEASURABLE", reason_code="EVIDENCE_MISSING")
            out.append(rec); continue
        full = root / path
        if not full.exists():
            rec.update(verdict="NOT_MEASURABLE", reason_code="CSV_MISSING")
            out.append(rec); continue
        if path not in csv_cache:
            csv_cache[path] = load_csv(full)
        cell = find_cell(csv_cache[path], ref.filters)
        if cell is None:
            rec.update(verdict="NOT_MEASURABLE", reason_code="CELL_NOT_FOUND")
            out.append(rec); continue

        rec["value_raw"] = cell.get("value_raw")
        rec["value"] = cell.get("value")
        rec["row_path"] = cell.get("row_path")
        rec["col_label"] = cell.get("col_label")
        praw, pst = parse_raw_number(cell.get("value_raw"))
        rec["parsed_raw"] = praw
        ratio, rst = storage_ratio(cell.get("value"), cell.get("value_raw"))
        rec["storage_ratio"] = ratio
        sexp = snap_power_of_ten(ratio) if rst == "OK" else None
        rec["storage_exp"] = sexp
        # column unit: col_label first, row_path as fallback
        cdim, cexp, ctok = scan_unit(cell.get("col_label", ""))
        if cdim == UNKNOWN:
            cdim, cexp, ctok = scan_unit(cell.get("row_path", ""))
            rec["column_unit_source"] = "row_path" if cdim != UNKNOWN else "none"
        else:
            rec["column_unit_source"] = "col_label"
        rec.update(column_dimension=cdim, column_scale_exponent=cexp, column_unit_token=ctok)

        if pst != "OK" or rst != "OK":
            rec.update(verdict="NOT_MEASURABLE", reason_code="RAW_UNPARSEABLE")
            out.append(rec); continue
        if sexp is None:
            rec.update(verdict="NOT_MEASURABLE", reason_code="STORAGE_RATIO_NOT_POWER_OF_TEN")
            out.append(rec); continue
        if qdim != MONEY or cdim != MONEY:
            if qdim == UNKNOWN:
                rec.update(verdict="NOT_MEASURABLE", reason_code="QUESTION_UNIT_UNKNOWN")
            elif cdim == UNKNOWN:
                rec.update(verdict="NOT_MEASURABLE", reason_code="COLUMN_UNIT_UNKNOWN")
            elif qdim != cdim:
                rec.update(verdict="NOT_MEASURABLE", reason_code="DIMENSION_MISMATCH")
            else:
                rec.update(verdict="NOT_MEASURABLE", reason_code="NON_MONEY_DIMENSION")
            out.append(rec); continue
        if af is None:
            rec.update(verdict="NOT_MEASURABLE", reason_code="QUERY_FACTOR_UNKNOWN")
            out.append(rec); continue

        required = 10.0 ** (cexp - qexp - sexp)
        rec["required_factor"] = required
        rec["canonical_vnd"] = praw * (10.0 ** cexp)
        rec["expected_answer"] = praw * (10.0 ** (cexp - qexp))
        rec["emitted_answer"] = r.get("answer")
        ok_factor = abs(required - af) <= 1e-9 * max(1.0, abs(required), abs(af))
        rec["verdict"] = "FACTOR_MATCH" if ok_factor else "FACTOR_MISMATCH"
        out.append(rec)

    out.sort(key=lambda x: x["qid"])
    with open(a.out, "w", encoding="utf-8") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    verd = collections.Counter(r["verdict"] for r in out)
    reasons = collections.Counter(r["reason_code"] for r in out if r["reason_code"])
    mism = sorted(r["qid"] for r in out if r["verdict"] == "FACTOR_MISMATCH")
    summary = {
        "n_records": len(out),
        "verdicts": dict(sorted(verd.items())),
        "not_measurable_reasons": dict(sorted(reasons.items())),
        "n_factor_mismatch_distinct_qid": len(mism),
        "factor_mismatch_qids": mism,
        "sum_check": sum(verd.values()),
    }
    Path(a.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
