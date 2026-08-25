#!/usr/bin/env python3
"""Sinh dossier gán nhãn one-pass + đo COMPLEXITY → khuyến nghị batch size.

- DEV-60: dossier KÈM top-10 FactCandidate (tăng tốc gán; DEV là tập phát triển,
  được phép nhìn hệ thống).
- AUDIT-40: dossier BLIND — chỉ câu hỏi + slot template, KHÔNG prediction/ranking
  (125 §P0-C). Không in candidates, không in answer của C0.

Complexity bucket (đo từ dữ liệu, thời gian/câu là ƯỚC LƯỢNG KẾ HOẠCH cho tới
khi pilot người thật xác nhận — ghi rõ trong report):
    FAST  ~3′  lookup 1-slot, top-1 chứa nguyên văn nhãn, margin rõ
    MED   ~6′  lookup mơ hồ, hoặc arithmetic ≤3 slot đủ candidate
    HARD ~10′  ≥4 slot, screen/count/multi-entity, hoặc thiếu candidate

Sinh:
    data/curated/dev-legacy/execution_gold/dossiers_dev60/qid_XXXX.md
    data/curated/dev-legacy/execution_gold/dossiers_audit40_blind/qid_XXXX.md
    data/curated/dev-legacy/execution_gold/label_template_schema.json
    reports/labeling_batch_size_report.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fact_candidates_v1 import candidates_for, ROOT  # noqa: E402

EST_MIN = {"FAST": 3, "MED": 6, "HARD": 10}
BLOCKS = {"1.5h": 90, "2h": 120}

SCHEMA = {
    "qid": "int",
    "dap_an_gold": "number — đáp án cuối theo ĐÚNG đơn vị câu hỏi",
    "don_vi_dap_an": "trieu|ty|tram_ty|nghin_ty|percent|lan|dong|co_phieu",
    "intent_gold": "lookup|difference|ratio|percentage_change|average|max_min|argmax_year|sum|count|multi",
    "operands": "[{role, evidence_ref, row_path, col, raw_value, scale_exponent}]",
    "cong_thuc": "biểu thức từ operands (vd (a-b)/abs(b)*100)",
    "basis_gold": "separate|consolidated",
    "trang_thai": "OK|GOLD_UNCERTAIN|DATA_MISSING",
    "ghi_chu": "string",
    "thoi_gian_phut": "number — BẮT BUỘC ghi để hiệu chỉnh batch size",
}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s.lower())).strip()


def complexity(p: dict, cands: list[dict]) -> str:
    n_slots = max(1, len(p["years"] or [1])) * max(1, len(p["entities"] or [1]))
    it = p["intent_v1"]
    if it in ("count", "multi_entity_aggregate") or "screen_filter" in p["flags"] or n_slots >= 4:
        return "HARD"
    if not cands:
        return "HARD"
    if it == "lookup" and n_slots == 1:
        top = cands[0]
        if norm(top["metric_label"] or "") and norm(top["metric_label"]) in norm(p["question"]):
            margin = top["score"] - (cands[1]["score"] if len(cands) > 1 else 0)
            if margin > 0.5:
                return "FAST"
        return "MED"
    return "MED"


def dossier_md(p: dict, cands: list[dict] | None, blind: bool) -> str:
    L = [f"# QID {p['qid']}" + ("  ·  [AUDIT — BLIND]" if blind else ""),
         "", f"**Câu hỏi:** {p['question']}", "",
         f"- entities: {p['entities']} · years: {p['years']} · basis(parse): {p['basis']}",
         f"- đơn vị hỏi (parse): {p['output_unit']} · intent(parse, THAM KHẢO): "
         + ("(ẩn với audit)" if blind else p['intent_v1']), ""]
    if not blind and cands:
        L += ["## Top-10 candidates (hệ thống — kiểm chứng lại, đừng tin mù)", "",
              "| # | metric_label | row_path | col | value | evidence_ref |",
              "|---|---|---|---|---|---|"]
        for i, c in enumerate(cands[:10], 1):
            L.append(f"| {i} | {c['metric_label'] or ''} | {c['row_path']} | "
                     f"{c['col_path']} | {c['value']} | {c['evidence_ref']} |")
        L.append("")
    L += ["## Nhãn (điền theo label_template_schema.json)", "", "```json",
          json.dumps({k: None for k in SCHEMA}, ensure_ascii=False, indent=1),
          "```", ""]
    return "\n".join(L)


def main() -> int:
    plans = {p["qid"]: p for p in
             (json.loads(l) for l in
              (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    dev = json.loads((ROOT / "data/curated/dev-legacy/execution_gold/dev60_selection.json").read_text())
    aud = json.loads((ROOT / "data/curated/dev-legacy/execution_gold/audit40_selection.json").read_text())
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)

    (ROOT / "data/curated/dev-legacy/execution_gold/label_template_schema.json").write_text(
        json.dumps(SCHEMA, ensure_ascii=False, indent=1), encoding="utf-8")

    ddir = ROOT / "data/curated/dev-legacy/execution_gold/dossiers_dev60"
    adir = ROOT / "data/curated/dev-legacy/execution_gold/dossiers_audit40_blind"
    ddir.mkdir(parents=True, exist_ok=True)
    adir.mkdir(parents=True, exist_ok=True)

    buckets: dict[int, str] = {}
    for qid in dev["qids"]:
        p = plans[qid]
        cands = candidates_for(con, p, k=10)
        buckets[qid] = complexity(p, cands)
        (ddir / f"qid_{qid:04d}.md").write_text(
            dossier_md(p, cands, blind=False), encoding="utf-8")
    for qid in aud["qids"]:
        p = plans[qid]
        cands = candidates_for(con, p, k=10)  # chỉ để đo complexity, KHÔNG in
        buckets[qid] = complexity(p, cands)
        (adir / f"qid_{qid:04d}.md").write_text(
            dossier_md(p, None, blind=True), encoding="utf-8")

    def summarize(qids: list[int], blind_penalty: float = 0.0) -> dict:
        c = Counter(buckets[q] for q in qids)
        minutes = sum((EST_MIN[buckets[q]] + blind_penalty) for q in qids)
        return {"buckets": dict(c), "est_total_min": round(minutes),
                "est_total_h": round(minutes / 60, 1)}

    dev_s = summarize(dev["qids"])
    aud_s = summarize(aud["qids"], blind_penalty=2.0)  # blind chậm hơn ~2′/câu

    def batch_plan(total_min: float) -> dict:
        return {b: {"cau_per_block_FAST": mins // EST_MIN["FAST"],
                    "cau_per_block_MED": mins // EST_MIN["MED"],
                    "cau_per_block_HARD": mins // EST_MIN["HARD"],
                    "n_blocks_needed": -(-int(total_min) // mins)}
                for b, mins in BLOCKS.items()}

    rep = {
        "machine": "build", "date": "2026-08-20",
        "status": "ƯỚC LƯỢNG KẾ HOẠCH theo complexity đo được — pilot người thật "
                  "(10 câu, ghi thoi_gian_phut) sẽ hiệu chỉnh; mapping 125 §P0-C áp sau pilot",
        "est_min_per_bucket": EST_MIN,
        "dev60": dev_s, "audit40_blind": aud_s,
        "block_capacity": batch_plan(dev_s["est_total_min"]),
        "khuyen_nghi": None,  # điền dưới
        "command": " ".join(sys.argv),
    }
    rec = {
        "pilot": "10 câu ĐẦU của DEV theo thứ tự file, ghi thoi_gian_phut từng câu",
        "neu_median_le_4p5": "DEV batch 20 câu/1,5h — giữ DEV 60 trong 3 tối (D2–D4)",
        "neu_median_4p5_den_6": "DEV batch 15 câu/1,5h → DEV 60 cần 4 tối; giữ 60, mượn tối D5",
        "neu_median_6_den_8": "DEV batch 11–13 câu/1,5h → hạ DEV 60→48 (bỏ 2 câu/lớp đông nhất) hoặc nâng block 2h",
        "audit40": f"blind ≈ {aud_s['est_total_h']}h → 3 tối × ~90′ (D5/D6/D7, 13+13+14) khớp lịch 124 §4",
        "du_bao_theo_complexity_hien_tai":
            f"DEV60 ≈ {dev_s['est_total_h']}h ⇒ 3 tối 1,5h là KHÍT nếu tỷ lệ FAST giữ nguyên; "
            "nếu pilot chậm hơn 20%, chuyển block 2h thay vì cắt DEV",
    }
    rep["khuyen_nghi"] = rec
    (ROOT / "reports/labeling_batch_size_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
