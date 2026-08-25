#!/usr/bin/env python3
"""Validator bất biến cho funnel v2 — §5.3 review 163.

Mọi bất biến ở đây đều là **fail-closed**: vi phạm là FAIL và exit 1. Một funnel
tự mâu thuẫn còn nguy hiểm hơn không có funnel, vì nó vẫn cho ra một bảng số
trông như bằng chứng.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
F = ROOT / "reports/163/funnel"
TANG_TRUOC_A1 = ["G0_GOLD_VALID", "D1_SOURCE_AVAILABLE", "R1_GOLD_TABLE_RETRIEVED",
                 "C1_GOLD_FACT_CANDIDATE", "S1_OPERAND_SET_EXACT",
                 "O1_OPERATION_EXACT", "U1_UNIT_SCALE_EXACT", "Q1_QUERY_VALID"]


def main() -> int:
    rows = [json.loads(l) for l in
            (F / "failure_funnel_wave1_v2.jsonl").open(encoding="utf-8") if l.strip()]
    loi = []

    def bad(q, ten, **kw):
        loi.append({"qid": q, "bat_bien": ten, **kw})

    for r in rows:
        q = r["qid"]
        if r["gold_status"] == "OK":
            if not r["required_operand_count"] or not r["operation_gold"]:
                bad(q, "gold_OK_phai_co_operand_va_operation")
            # answer đúng ⇒ không được có first failure
            if r["A1_ANSWER_EXACT"] and r["first_failure_stage"] is not None:
                bad(q, "answer_exact_nhung_co_first_failure",
                    stage=r["first_failure_stage"])
            # answer sai ⇒ phải có first failure
            if (not r["A1_ANSWER_EXACT"]) and r["first_failure_stage"] is None:
                bad(q, "answer_sai_nhung_khong_co_first_failure")
        if r["R1_GOLD_TABLE_RETRIEVED"] is True and not (
                set(r["gold_table_ids"]) <= set(r["retrieved_table_ids"])):
            bad(q, "R1_true_nhung_gold_table_khong_subset")
        if r["C1_GOLD_FACT_CANDIDATE"] is True and not r["gold_fact_ids"]:
            bad(q, "C1_true_nhung_khong_co_gold_fact_id")
        if r["S1_OPERAND_SET_EXACT"] is True and (
                set(r["selected_fact_ids"]) != set(r["gold_fact_ids"])):
            bad(q, "S1_true_nhung_operand_set_khac_gold")
        if r["Q1_QUERY_VALID"] is True and r["query_eval_value"] is None:
            bad(q, "Q1_true_nhung_khong_eval_duoc")
        if r["E1_EVIDENCE_VALID"] is True and not r["unique_selected_dataframe_count"]:
            bad(q, "E1_true_nhung_khong_co_evidence")
        # SPURIOUS_CORRECT phải đi kèm answer đúng + có SEMANTIC_FAIL
        fl = r["diagnostic_flags"]
        if "SPURIOUS_CORRECT" in fl:
            if not r["A1_ANSWER_EXACT"]:
                bad(q, "SPURIOUS_CORRECT_nhung_answer_sai")
            if not any(x.startswith("SEMANTIC_FAIL_") for x in fl):
                bad(q, "SPURIOUS_CORRECT_nhung_khong_co_SEMANTIC_FAIL")

    kq = {"_schema": "funnel_validator_v2", "n_row": len(rows),
          "n_loi": len(loi), "loi": loi[:30],
          "VERDICT": "PASS" if not loi else "FAIL"}
    (F / "funnel_validator_report.json").write_text(
        json.dumps(kq, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(kq, ensure_ascii=False, indent=1))
    return 0 if not loi else 1


if __name__ == "__main__":
    raise SystemExit(main())
