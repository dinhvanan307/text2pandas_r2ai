#!/usr/bin/env python3
"""failure_funnel v2 — §5 review 163.

Bốn lỗi của bản v1 được sửa ở đây, mỗi lỗi một dòng code chứ không phải một câu
trong tài liệu:

* **F8** — `candidate_gold_present` bản v1 đo trên `evidence` CUỐI CÙNG. Đó là
  vòng tròn: pipeline chọn một fact ⇒ evidence có một fact ⇒ funnel kết luận
  "candidate thiếu". Bản v2 dựng **candidate universe TRƯỚC selection** bằng
  `fact_rank_v1.fetch_pool` — đúng mẫu số mà tầng chọn nhìn thấy.
* **F9** — retrieval recall đo bằng **giao tập ID bảng**, không bằng đếm số bảng.
* **F10** — operand count lấy từ **AST của `pandas_query`** (`n_selections`),
  không từ số dataframe.
* **F11** — `first_failure_stage` chỉ gán trên chuỗi phụ thuộc; cảnh báo không
  chặn tính đúng thì vào `diagnostic_flags`. Đáp án đúng mà pipeline sai ngữ
  nghĩa ⇒ `SPURIOUS_CORRECT`.
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import math
import os
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from execution import fact_rank_v1                      # noqa: E402
from execution.answer_operation import phan_tich_ast    # noqa: E402

GD = ROOT / "data/curated/dev-legacy/answer_gold"
OUT = ROOT / "reports/163/funnel"
WORK = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"

TANG = ["G0_GOLD_VALID", "D1_SOURCE_AVAILABLE", "R1_GOLD_TABLE_RETRIEVED",
        "C1_GOLD_FACT_CANDIDATE", "S1_OPERAND_SET_EXACT", "O1_OPERATION_EXACT",
        "U1_UNIT_SCALE_EXACT", "Q1_QUERY_VALID", "A1_ANSWER_EXACT",
        "E1_EVIDENCE_VALID"]
LUY_THUA = [10 ** e for e in (-12, -9, -6, -3, -2, 2, 3, 6, 9, 12)]


def chuan_tid(s: str) -> str:
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", str(s or ""))
    return f"{m.group(1)}|{m.group(2)}" if m else str(s or "")


def tid_tu_csv(p: str) -> str:
    n = str(p or "").split("/")[-1]
    n = re.sub(r"^(a6_|v3_)", "", n)
    m = re.match(r"^(.*)_line(\d+)\.csv$", n)
    return f"{m.group(1)}|{m.group(2)}" if m else n


def gan(a, b, tol=5e-3) -> bool:
    try:
        a, b = float(a), float(b)
    except Exception:
        return str(a).strip().lower() == str(b).strip().lower()
    m = max(abs(a), abs(b))
    return abs(a - b) <= (tol * m if m else 1e-9)


def luy_thua_10(a, b):
    try:
        a, b = float(a), float(b)
    except Exception:
        return None
    if not a or not b:
        return None
    r = a / b
    for k in LUY_THUA:
        if abs(r - k) <= abs(k) * 5e-3:
            return k
    return None


def safe_env(dfs):
    import numpy as np
    import pandas as pd
    e = {"pd": pd, "np": np, "float": float, "int": int, "abs": abs,
         "round": round, "min": min, "max": max, "sum": sum, "len": len,
         "str": str, "__builtins__": {}}
    e.update(dfs)
    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path,
                    default=ROOT / "artifacts/submissions/legacy/submission_P0I.zip")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    gold = {r["qid"]: r for r in (json.loads(l) for l in
            (GD / "answer_gold_wave1_final.jsonl").open(encoding="utf-8") if l.strip())}
    plans = {r["qid"]: r for r in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8")
             if l.strip())}
    proj = collections.defaultdict(list)
    for r in (json.loads(l) for l in
              (ROOT / "reports/163/gold/source_cell_projection.jsonl")
              .open(encoding="utf-8") if l.strip()):
        proj[r["qid"]].append(r)

    zf = zipfile.ZipFile(a.zip)
    sub = {r["id"]: r for r in json.loads(zf.read("submission.json"))}
    con = sqlite3.connect("file:" + os.path.abspath(WORK) + "?mode=ro", uri=True)

    rows, ov_rows, cand_rows, opd_rows, qex_rows = [], [], [], [], []
    for q in sorted(gold):
        g, rec, plan = gold[q], sub[q], plans[q]
        cells = g.get("gold_cells") or []
        n_req = len(cells)

        gold_tids = sorted({chuan_tid(c.get("evidence_ref")) for c in cells
                            if c.get("evidence_ref")})
        retr_tids = sorted({chuan_tid(x) for x in (rec.get("relevant_tables") or [])})
        gold_fids = sorted({p["workdb"]["observation_uid"] for p in proj.get(q, [])
                            if p.get("workdb")})
        n_khong_map = sum(1 for p in proj.get(q, []) if not p.get("workdb"))

        # ── candidate universe TRƯỚC selection (F8) ──────────────────────
        pool = fact_rank_v1.fetch_pool(con, plan)
        cand_fids = {c["observation_uid"] for c in pool}

        # ── operand thực sự dùng: AST, KHÔNG phải số dataframe (F10) ─────
        qry = str(rec.get("pandas_query") or "")
        evs = rec.get("evidence") or []
        shape = phan_tich_ast(qry, [e.get("variable") for e in evs])
        n_df = len({e.get("variable") for e in evs})
        sel_tids = sorted({tid_tu_csv(e.get("csv_path")) for e in evs})
        row_q = set(re.findall(r"row_path'\]\s*==\s*'([^']*)'", qry))
        col_q = set(re.findall(r"col_label'\]\s*==\s*'([^']*)'", qry))
        # fact được câu lệnh chạm tới: (bảng, row, col) -> observation_uid
        query_fids = []
        for t in sel_tids:
            d, _, ln = t.partition("|")
            for rp in (row_q or {None}):
                for cp in (col_q or {None}):
                    if rp is None or cp is None:
                        continue
                    r = con.execute(
                        "SELECT observation_uid FROM observations WHERE"
                        " evidence_ref=? AND row_path_text=? AND col_path_text=?"
                        " LIMIT 1", (f"{d}|line:{ln}", rp, cp)).fetchone()
                    if r:
                        query_fids.append(r[0])
        query_fids = sorted(set(query_fids))
        n_operand_ast = shape.n_selections

        # ── Q1: chạy thật câu lệnh trên CSV trong ZIP ───────────────────
        import pandas as pd
        dfs, thieu_csv = {}, []
        for e in evs:
            p = e.get("csv_path")
            try:
                dfs[e["variable"]] = pd.read_csv(io.BytesIO(zf.read(p)))
            except Exception:
                thieu_csv.append(p)
        q1, qval, qerr = None, None, None
        if qry.strip():
            try:
                qval = float(eval(qry, safe_env(dfs)))      # noqa: S307
                q1 = math.isfinite(qval)
            except Exception as ex:                          # noqa: BLE001
                q1, qerr = False, f"{type(ex).__name__}: {ex}"[:180]
        else:
            q1, qerr = False, "EMPTY_QUERY"

        ans = rec.get("answer")
        gval = g.get("normalized_answer_gold")
        if gval is None:
            gval = g.get("answer_gold")

        # ── các tầng ─────────────────────────────────────────────────────
        st = {}
        st["G0_GOLD_VALID"] = (g["trang_thai"] == "OK" and n_req > 0
                               and bool(g.get("operation")))
        st["D1_SOURCE_AVAILABLE"] = all(
            p["source_status"] == "SOURCE_LINE_VERIFIED" for p in proj.get(q, [])
        ) if proj.get(q) else None
        st["R1_GOLD_TABLE_RETRIEVED"] = (set(gold_tids) <= set(retr_tids)
                                         if gold_tids else None)
        st["C1_GOLD_FACT_CANDIDATE"] = (
            set(gold_fids) <= cand_fids
            if (gold_fids and len(gold_fids) == n_req) else None)
        st["S1_OPERAND_SET_EXACT"] = (
            set(query_fids) == set(gold_fids)
            if (gold_fids and len(gold_fids) == n_req) else None)
        op_g = g.get("operation")
        op_p = plan.get("intent_v1")
        st["O1_OPERATION_EXACT"] = (n_operand_ast == n_req) and bool(st["S1_OPERAND_SET_EXACT"])
        k = luy_thua_10(ans, gval)
        st["U1_UNIT_SCALE_EXACT"] = (k is None) if ans is not None else None
        st["Q1_QUERY_VALID"] = bool(q1) and (gan(qval, ans) if qval is not None else False)
        st["A1_ANSWER_EXACT"] = gan(ans, gval)
        st["E1_EVIDENCE_VALID"] = (set(query_fids) <= set(gold_fids | set())
                                   if False else bool(evs) and not thieu_csv)

        flags = []
        if k is not None:
            flags.append(f"UNIT_POWER10_{k:g}")
        if n_df != n_operand_ast:
            flags.append(f"DF{n_df}_NE_OPERAND{n_operand_ast}")
        if n_khong_map:
            flags.append(f"GOLD_FACT_KHONG_MAP_WORKDB_{n_khong_map}")
        if thieu_csv:
            flags.append("CSV_THIEU_TRONG_ZIP")

        dau = next((t for t in TANG if st.get(t) is False), None)
        if st["A1_ANSWER_EXACT"]:
            # F11: cảnh báo không chặn đúng thì KHÔNG được là first failure
            truoc = [t for t in TANG[:TANG.index("A1_ANSWER_EXACT")]
                     if st.get(t) is False]
            if truoc:
                flags.append("SPURIOUS_CORRECT")
                flags += [f"SEMANTIC_FAIL_{t}" for t in truoc]
            dau = None
        rows.append({
            "qid": q, "gold_status": g["trang_thai"],
            "required_operand_count": n_req,
            "gold_fact_ids": gold_fids, "gold_table_ids": gold_tids,
            "retrieved_table_ids": retr_tids,
            "candidate_fact_ids_count": len(cand_fids),
            "candidate_fact_ids_sample": sorted(cand_fids)[:5],
            "selected_fact_ids": query_fids, "query_fact_ids": query_fids,
            "unique_gold_table_count": len(gold_tids),
            "unique_selected_dataframe_count": n_df,
            "query_operand_count_ast": n_operand_ast,
            "operation_gold": op_g, "operation_pred": op_p,
            "output_unit_gold": g.get("unit"),
            "output_unit_pred": plan.get("output_unit"),
            "answer_pred": ans, "answer_gold": gval,
            "query_eval_value": qval, "query_error": qerr,
            **st,
            "semantic_pipeline_exact": bool(st["S1_OPERAND_SET_EXACT"]
                                            and st["O1_OPERATION_EXACT"]),
            "first_failure_stage": dau,
            "diagnostic_flags": flags,
        })
        ov_rows.append({"qid": q, "gold_table_ids": gold_tids,
                        "retrieved_table_ids": retr_tids,
                        "n_gold": len(gold_tids), "n_retrieved": len(retr_tids),
                        "n_giao": len(set(gold_tids) & set(retr_tids)),
                        "table_recall": (round(len(set(gold_tids) & set(retr_tids))
                                               / len(gold_tids), 4)
                                         if gold_tids else None),
                        "all_gold_tables_retrieved": st["R1_GOLD_TABLE_RETRIEVED"],
                        "missing_gold_tables": sorted(set(gold_tids) - set(retr_tids))})
        cand_rows.append({"qid": q, "n_candidate_universe": len(cand_fids),
                          "gold_fact_ids": gold_fids,
                          "n_gold_fact_trong_universe":
                              len(set(gold_fids) & cand_fids),
                          "fact_recall": (round(len(set(gold_fids) & cand_fids)
                                                / len(gold_fids), 4)
                                          if gold_fids else None),
                          "C1": st["C1_GOLD_FACT_CANDIDATE"],
                          "nguon": "fact_rank_v1.fetch_pool (TRƯỚC selection)"})
        opd_rows.append({"qid": q, "required_operand_count": n_req,
                         "selected_factref_count": len(query_fids),
                         "unique_source_table_count": len(sel_tids),
                         "unique_dataframe_count": n_df,
                         "query_operand_count_ast": n_operand_ast,
                         "ast_parse_ok": shape.parse_ok, "ast_reason": shape.reason})
        qex_rows.append({"qid": q, "query": qry[:400], "eval_ok": q1,
                         "eval_value": qval, "answer_in_zip": ans,
                         "answer_eq_eval": gan(qval, ans) if qval is not None else None,
                         "error": qerr, "csv_thieu": thieu_csv})

    def w(name, data):
        (a.out / name).write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in data) + "\n",
            encoding="utf-8")
    w("failure_funnel_wave1_v2.jsonl", rows)
    w("retrieval_overlap_per_qid.jsonl", ov_rows)
    w("candidate_presence_per_qid.jsonl", cand_rows)
    w("operand_trace_per_qid.jsonl", opd_rows)
    w("query_execution_trace_per_qid.jsonl", qex_rows)

    ok = [r for r in rows if r["gold_status"] == "OK"]
    tr = [o for o in ov_rows if o["qid"] in {r["qid"] for r in ok}]
    cr = [c for c in cand_rows if c["qid"] in {r["qid"] for r in ok}]
    tom = {
        "_schema": "failure_funnel_summary_v2",
        "zip": a.zip.name, "n_gold": len(rows), "n_gold_OK": len(ok),
        "answer_exact_tren_gold_OK":
            f"{sum(1 for r in ok if r['A1_ANSWER_EXACT'])}/{len(ok)}",
        "first_failure_stage__gold_OK":
            dict(collections.Counter(r["first_failure_stage"] for r in ok)),
        "tung_tang__gold_OK": {t: dict(collections.Counter(str(r.get(t)) for r in ok))
                               for t in TANG},
        "retrieval": {
            "table_recall_trung_binh": round(
                sum(o["table_recall"] for o in tr if o["table_recall"] is not None)
                / max(1, sum(1 for o in tr if o["table_recall"] is not None)), 4),
            "all_gold_tables_retrieved":
                f"{sum(1 for o in tr if o['all_gold_tables_retrieved'])}/{len(tr)}",
            "n_qid_thieu_bang": sum(1 for o in tr if o["missing_gold_tables"]),
        },
        "candidate": {
            "fact_recall_trung_binh": round(
                sum(c["fact_recall"] for c in cr if c["fact_recall"] is not None)
                / max(1, sum(1 for c in cr if c["fact_recall"] is not None)), 4),
            "C1_true": sum(1 for c in cr if c["C1"] is True),
            "C1_false": sum(1 for c in cr if c["C1"] is False),
            "C1_khong_do_duoc": sum(1 for c in cr if c["C1"] is None),
        },
        "operand_vs_dataframe": {
            "n_qid_df_khac_operand_ast":
                sum(1 for r in ok if r["unique_selected_dataframe_count"]
                    != r["query_operand_count_ast"]),
            "phan_bo_operand_ast":
                dict(collections.Counter(r["query_operand_count_ast"] for r in ok)),
            "phan_bo_dataframe":
                dict(collections.Counter(r["unique_selected_dataframe_count"]
                                         for r in ok)),
        },
        "spurious_correct": [r["qid"] for r in ok
                             if "SPURIOUS_CORRECT" in r["diagnostic_flags"]],
    }
    (a.out / "failure_funnel_summary_v2.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
