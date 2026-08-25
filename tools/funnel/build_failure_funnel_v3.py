#!/usr/bin/env python3
"""Failure Funnel v3 — §5 directive 165, §5 review 165.

Bốn thay đổi kiến trúc so với v2:

1. **Hai nhánh, không phải một chuỗi.** `relevant_tables` KHÔNG cấp đầu vào cho
   `fact_rank_v1.fetch_pool` — đã xác minh trên source. Vì vậy một tầng không nằm
   trên đường chạy answer **không được** là nguyên nhân đầu tiên làm answer sai.
   `RETRIEVAL_BRANCH` phục vụ TABLES/DOCS F2; `ANSWER_BRANCH` phục vụ Execution.
2. **`None` chặn quy trách nhiệm.** Một node chỉ được gọi là first attributable
   failure khi MỌI tiền đề của nó đã `PASS`. Có tiền đề `NOT_MEASURABLE` ⇒
   `NOT_ATTRIBUTABLE`, không được nhảy cóc xuống node sau.
3. **Gold eligibility là cổng trước, không phải một stage.** Chỉ
   `EVALUABLE_GOLD` mới được dùng để quy nguyên nhân.
4. **Multilabel.** Xuất `failed_nodes[] · unmeasurable_nodes[] ·
   root_attributable_nodes[] · downstream_symptoms[]` thay vì ép một nhãn.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from semantic import predicates as P            # noqa: E402
from semantic.contract import danh_gia          # noqa: E402

# node -> tiền đề trực tiếp (DAG, KHÔNG phải chuỗi tuyến tính)
TIEN_DE = {
    "C1_CANDIDATE_COVERAGE": [],
    "I1_OPERATION_INTENT": [],
    "S1_OPERAND_BINDING": ["C1_CANDIDATE_COVERAGE"],
    "U1_UNIT_CONTRACT": ["S1_OPERAND_BINDING"],
    "Q1_EXECUTABLE": [],
    "Q2_SELF_CONSISTENT": ["Q1_EXECUTABLE"],
    "A1_LOCAL_MATCH": ["Q1_EXECUTABLE"],
    "E0_EVIDENCE_FILES_PRESENT": [],
    "E1_QUERY_VARIABLE_RESOLVES": ["E0_EVIDENCE_FILES_PRESENT"],
    "E3_GOLD_OPERANDS_COVERED": ["E0_EVIDENCE_FILES_PRESENT"],
}
THU_TU = list(TIEN_DE)


def chuan_tid(s):
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", str(s or ""))
    return f"{m.group(1)}|{m.group(2)}" if m else str(s or "")


def tid_tu_csv(p):
    n = str(p or "").split("/")[-1]
    n = re.sub(r"^(a6_|v3_)", "", n)
    m = re.match(r"^(.*)_line(\d+)\.csv$", n)
    return f"{m.group(1)}|{m.group(2)}" if m else n


def gold_eligibility(g) -> str:
    if g.get("trang_thai") != "OK":
        return "GOLD_UNCERTAIN"
    ops = g.get("gold_cells") or []
    if not ops or not g.get("operation"):
        return "GOLD_PARTIAL"
    if not all(c.get("evidence_ref") for c in ops):
        return "NOT_SOURCE_VERIFIED"
    return "EVALUABLE_GOLD"


def quy_trach_nhiem(st: dict) -> dict:
    """First attributable failure chỉ hợp lệ khi mọi tiền đề đã PASS."""
    failed = [n for n in THU_TU if st.get(n) == P.FAIL]
    unmeas = [n for n in THU_TU if st.get(n) in (P.NOT_MEASURABLE, P.UNCERTAIN, None)]
    root, downstream = [], []
    for n in failed:
        td = TIEN_DE[n]
        if any(st.get(t) != P.PASS for t in td):
            downstream.append(n)
        else:
            root.append(n)
    if not failed:
        att = "NO_FAILURE" if not unmeas else "NOT_ATTRIBUTABLE"
    elif root:
        att = "ATTRIBUTED"
    else:
        att = "UNRESOLVED_DUE_TO_MISSING_MEASUREMENT"
    return {"failed_nodes": failed, "unmeasurable_nodes": unmeas,
            "root_attributable_nodes": root, "downstream_symptoms": downstream,
            "attribution_status": att}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path,
                    default=ROOT / "artifacts/submissions/legacy/submission_P0I.zip")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/165/funnel_v3")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    gold = {r["qid"]: r for r in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/answer_gold/answer_gold_wave1_final.jsonl")
            .open(encoding="utf-8") if l.strip())}
    plans = {r["qid"]: r for r in (json.loads(l) for l in
             (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8")
             if l.strip())}
    zf = zipfile.ZipFile(a.zip)
    names = set(zf.namelist())
    sub = {r["id"]: r for r in json.loads(zf.read("submission.json"))}
    cand = {}
    p_cand = ROOT / "reports/163/funnel/candidate_presence_per_qid.jsonl"
    if p_cand.is_file():
        cand = {r["qid"]: r for r in (json.loads(l) for l in
                p_cand.open(encoding="utf-8") if l.strip())}

    retr_rows, ans_rows, attr_rows = [], [], []
    for q in sorted(gold):
        g, rec, plan = gold[q], sub[q], plans[q]
        cells = g.get("gold_cells") or []
        elig = gold_eligibility(g)

        # ── nhánh RETRIEVAL (phục vụ TABLES/DOCS F2, KHÔNG vào causal answer) ─
        gt = sorted({chuan_tid(c.get("evidence_ref")) for c in cells
                     if c.get("evidence_ref")})
        rt = sorted({chuan_tid(x) for x in (rec.get("relevant_tables") or [])})
        gd = sorted({str(c.get("evidence_ref") or "").split("|")[0] for c in cells
                     if c.get("evidence_ref")})
        rd = sorted(rec.get("relevant_docs") or [])
        retr_rows.append({
            "qid": q, "gold_eligibility": elig,
            "RT1_GOLD_TABLE_ID_RECALL": (round(len(set(gt) & set(rt)) / len(gt), 4)
                                         if gt else None),
            "RT2_ALL_GOLD_TABLES_RETRIEVED": (set(gt) <= set(rt)) if gt else None,
            "RD1_GOLD_DOC_ID_RECALL": (round(len(set(gd) & set(rd)) / len(gd), 4)
                                       if gd else None),
            "RD2_ALL_GOLD_DOCS_RETRIEVED": (set(gd) <= set(rd)) if gd else None,
            "missing_gold_tables": sorted(set(gt) - set(rt)),
            "GHI_CHU": "KHÔNG dùng làm first failure của answer",
        })

        # ── nhánh ANSWER ────────────────────────────────────────────────────
        qry = str(rec.get("pandas_query") or "")
        evs = rec.get("evidence") or []
        sels, ast_st = P.tach_selection(qry)
        sel_docs = [tid_tu_csv(e.get("csv_path")).split("|")[0] for e in evs]

        st, ev_detail = {}, {}

        def dat(name, v):
            st[name] = v.status
            ev_detail[name] = {"reason": v.reason, "evidence": v.evidence}

        c = cand.get(q) or {}
        dat("C1_CANDIDATE_COVERAGE",
            P.Verdict(P.PASS if c.get("C1") is True else
                      P.FAIL if c.get("C1") is False else P.NOT_MEASURABLE,
                      f"fact_recall={c.get('fact_recall')}", {"nguon": c.get("nguon")}))
        dat("I1_OPERATION_INTENT",
            P.operation_match(g.get("operation"), plan.get("intent_v1")))
        dat("S1_OPERAND_BINDING", P.operand_binding(cells, sels))
        src_unit = cells[0].get("col_path") if cells else None
        dat("U1_UNIT_CONTRACT",
            P.unit_contract(src_unit, rec.get("question"), qry))
        dat("E0_EVIDENCE_FILES_PRESENT", P.evidence_files_present(evs, names))
        dat("E1_QUERY_VARIABLE_RESOLVES", P.query_variable_resolves(sels, evs))
        dat("E3_GOLD_OPERANDS_COVERED", P.gold_operands_covered(cells, sels))

        val, err = None, None
        if qry.strip():
            try:
                import io

                import pandas as pd
                dfs = {e["variable"]: pd.read_csv(io.BytesIO(zf.read(e["csv_path"])))
                       for e in evs}
                env = {"pd": pd, "float": float, "int": int, "abs": abs,
                       "round": round, "min": min, "max": max, "sum": sum,
                       "len": len, "str": str, "__builtins__": {}, **dfs}
                val = float(eval(qry, env))          # noqa: S307
            except Exception as ex:                   # noqa: BLE001
                err = f"{type(ex).__name__}: {ex}"[:160]
        dat("Q1_EXECUTABLE", P.Verdict(P.PASS if val is not None else P.FAIL,
                                       err or "eval OK", {"value": val}))
        ans = rec.get("answer")

        def gan(x, y, tol=5e-3):
            try:
                x, y = float(x), float(y)
            except Exception:
                return False
            m = max(abs(x), abs(y))
            return abs(x - y) <= (tol * m if m else 1e-9)
        dat("Q2_SELF_CONSISTENT",
            P.Verdict(P.PASS if (val is not None and gan(val, ans)) else
                      P.NOT_MEASURABLE if val is None else P.FAIL,
                      "eval(query) vs answer trong ZIP", {"eval": val, "answer": ans}))
        gv = g.get("normalized_answer_gold")
        gv = g.get("answer_gold") if gv is None else gv
        dat("A1_LOCAL_MATCH",
            P.Verdict(P.PASS if gan(ans, gv) else P.FAIL,
                      "dung sai tương đối 0,5% — CHƯA khoá với evaluator chính thức",
                      {"pred": ans, "gold": gv}))

        attr = quy_trach_nhiem(st)
        if elig != "EVALUABLE_GOLD":
            attr = {**attr, "attribution_status": "NOT_ATTRIBUTABLE",
                    "ly_do": f"gold_eligibility={elig}"}

        ct = danh_gia({
            "entity": P.entity_match(g.get("entities"), sel_docs),
            "metric": P.Verdict(P.NOT_MEASURABLE, "cần gold metric_id — chưa có"),
            "period": P.period_match([c.get("period_end") for c in cells],
                                     [c.get("period_end") for c in cells]),
            "basis": P.basis_match(g.get("basis"),
                                   [tid_tu_csv(e.get("csv_path")) for e in evs]),
            "operation": P.Verdict(st["I1_OPERATION_INTENT"],
                                   ev_detail["I1_OPERATION_INTENT"]["reason"]),
            "operands": P.Verdict(st["S1_OPERAND_BINDING"]),
            "unit": P.Verdict(st["U1_UNIT_CONTRACT"]),
            "computation": P.Verdict(st["Q2_SELF_CONSISTENT"]),
            "evidence": P.Verdict(st["E3_GOLD_OPERANDS_COVERED"]),
        }, answer_exact=(st["A1_LOCAL_MATCH"] == P.PASS))

        ans_rows.append({"qid": q, "gold_eligibility": elig, **st,
                         "node_detail": ev_detail,
                         "answer_pred": ans, "answer_gold": gv,
                         "ast_status": ast_st, "n_selection": len(sels)})
        attr_rows.append({"qid": q, "gold_eligibility": elig, **attr,
                          "semantic_correctness": ct.semantic_correctness,
                          "primary_failure": ct.primary_failure,
                          "diagnostic_flags": ct.flags})

    def w(n, d):
        (a.out / n).write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                         for r in d) + "\n", encoding="utf-8")
    w("retrieval_branch.jsonl", retr_rows)
    w("answer_branch.jsonl", ans_rows)
    w("attribution.jsonl", attr_rows)

    ev = [r for r in attr_rows if r["gold_eligibility"] == "EVALUABLE_GOLD"]
    tom = {
        "_schema": "failure_funnel_v3_summary",
        "n_gold": len(attr_rows),
        "gold_eligibility": dict(collections.Counter(
            r["gold_eligibility"] for r in attr_rows)),
        "n_EVALUABLE_GOLD": len(ev),
        "attribution_status": dict(collections.Counter(
            r["attribution_status"] for r in ev)),
        "root_attributable_nodes": dict(collections.Counter(
            n for r in ev for n in r["root_attributable_nodes"])),
        "unmeasurable_nodes": dict(collections.Counter(
            n for r in ev for n in r["unmeasurable_nodes"])),
        "semantic_correctness": dict(collections.Counter(
            r["semantic_correctness"] for r in ev)),
        "measurement_coverage": {
            n: f"{sum(1 for r in ans_rows if r.get(n) in (P.PASS, P.FAIL))}/{len(ans_rows)}"
            for n in THU_TU},
        "retrieval_branch": {
            "RT2_ALL_GOLD_TABLES_RETRIEVED":
                f"{sum(1 for r in retr_rows if r['RT2_ALL_GOLD_TABLES_RETRIEVED'])}"
                f"/{len(retr_rows)}",
            "GHI_CHU": "nhánh riêng, KHÔNG vào causal chain của answer"},
    }
    (a.out / "summary.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    (a.out / "contract.json").write_text(json.dumps({
        "_schema": "funnel_v3_contract",
        "nhanh": {"RETRIEVAL_BRANCH": ["RT1", "RT2", "RD1", "RD2"],
                  "ANSWER_BRANCH": THU_TU},
        "tien_de": TIEN_DE,
        "luat_quy_trach_nhiem": (
            "root_attributable_node = node FAIL mà MỌI tiền đề đã PASS. "
            "Node FAIL có tiền đề chưa PASS ⇒ downstream_symptom. "
            "Không có root nào ⇒ UNRESOLVED_DUE_TO_MISSING_MEASUREMENT. "
            "gold_eligibility ≠ EVALUABLE_GOLD ⇒ NOT_ATTRIBUTABLE."),
        "gold_eligibility_enum": ["EVALUABLE_GOLD", "GOLD_PARTIAL",
                                  "GOLD_UNCERTAIN", "NOT_SOURCE_VERIFIED"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
