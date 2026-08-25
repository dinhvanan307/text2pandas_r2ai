#!/usr/bin/env python3
"""Chẩn đoán per-slot scoring — CƠ CHẾ lỗi, không phải "operand bị chọn sai".

Quyết định D1(a): bỏ joint search làm đòn bẩy chính, chuyển trọng tâm sang
per-slot scoring. Trước khi chạm bất kỳ trọng số nào, phải có **failure
taxonomy có số lượng và tỷ lệ**.

SCORING HIỆN TẠI (S0) — đọc từ `fact_rank_v1.score_pool`, 5 thành phần:

    idf_overlap   Σ log(1 + n_pool/df[t]) trên token CHUNG giữa `scoring_text`
                  và `metric_label + row_path`, chia √(len(label_tokens))
    exact_phrase  +3,0 nếu nhãn metric (>=8 ký tự) là chuỗi con của câu
    col_year      +0,6 nếu năm hỏi xuất hiện trong `col_path`
    doc_year      +0,3 nếu `doc_year` thuộc năm hỏi
    ready         +0,3 × `execution_ready`

BỐN GIỚI HẠN CẤU TRÚC nhìn thấy ngay từ code, trước khi chạy số:

  1. `scoring_text` DÙNG CHUNG cho mọi slot của một câu. `metric_phrase` lấy
     nhãn registry dài nhất là chuỗi con của TOÀN CÂU — nên hai slot của cùng
     câu nhận y hệt một truy vấn. Không có operand-specific phrase.
  2. KHÔNG có tín hiệu `statement_type`, `section`, `basis`, `unit_kind`,
     `value_kind`, `period_end`. Chúng có trong dữ liệu nhưng không vào điểm.
  3. `col_year` chỉ kiểm `"2022" in col_path` — một cột "31.12.2022" và một
     cột "2022VND › ghi chú 2022" cùng +0,6.
  4. Mẫu số `√(len(lt))` phạt nhãn DÀI. Nhãn cụ thể thường dài hơn nhãn tổng
     quát, nên chuẩn hoá này ưu ái nhãn NGẮN — ngược chiều với thứ ta cần.

Tệp này KHÔNG sửa gì. Nó chỉ đo, và phân loại từng slot sai theo cơ chế.

Chạy:  python3 tools/diag_slot_scoring_v1.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.fact_rank_v1 import V1_2, fetch_pool, norm, toks  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.operand_pipeline_v1 import (PipelineFlags, candidates_for_slot,  # noqa: E402
                                           load_aliases, slots_for)
from execution.joint_search_v1 import semantic_collapse  # noqa: E402
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402

LATTICE_M = 8


def decompose(c: dict, qt: set, qnorm: str, tgt_years: set,
              df: dict, n_pool: int) -> dict:
    """Tách điểm S0 thành 5 thành phần — để trả lời 'feature nào làm gold thua'."""
    lt = toks((c["metric_label"] or "") + " " + c["row_path"])
    inter = qt & lt
    if not (lt and inter):
        return {"scorable": False, "total": None}
    idf = sum(math.log(1 + n_pool / df[t]) for t in inter) / (len(lt) ** 0.5)
    labn = norm(c["metric_label"])
    ph = 3.0 if (len(labn) >= 8 and labn in qnorm) else 0.0
    cy = 0.6 if any(y in (c["col_path"] or "") for y in tgt_years) else 0.0
    dy = 0.3 if str(c["doc_year"]) in tgt_years else 0.0
    rd = 0.3 * (c.get("ready") or 0)
    return {"scorable": True, "idf_overlap": round(idf, 4), "exact_phrase": ph,
            "col_year": cy, "doc_year": dy, "ready": round(rd, 4),
            "n_token_overlap": len(inter), "n_label_tokens": len(lt),
            "total": round(idf + ph + cy + dy + rd, 4)}


def mismatch_dims(gold_c: dict | None, top1: dict, gs_ref: str,
                  gs_raw: str) -> dict:
    """Gold khác predicted ở CHIỀU nào. Không có gold cell thì so với gold ref."""
    d = {}
    if gold_c:
        gl, tl = toks(gold_c["metric_label"] or ""), toks(top1["metric_label"] or "")
        u = gl | tl
        d["metric_jaccard"] = round(len(gl & tl) / len(u), 3) if u else 1.0
        d["row_label_khac"] = norm(gold_c["metric_label"]) != norm(top1["metric_label"])
        d["col_khac"] = norm(gold_c["col_path"]) != norm(top1["col_path"])
        d["statement_khac"] = gold_c.get("statement_type") != top1.get("statement_type")
        d["unit_kind_khac"] = gold_c.get("unit_kind") != top1.get("unit_kind")
        d["value_kind_khac"] = gold_c.get("value_kind") != top1.get("value_kind")
        d["scale_khac"] = gold_c.get("scale_exponent") != top1.get("scale_exponent")
        gsec = (gold_c["row_path"] or "").split("›")[0].strip()
        tsec = (top1["row_path"] or "").split("›")[0].strip()
        d["section_khac"] = norm(gsec) != norm(tsec)
        d["cung_gia_tri"] = str(gold_c["value"]) == str(top1["value"])
    d["evidence_ref_khac"] = gs_ref != top1.get("evidence_ref")
    d["doc_khac"] = gs_ref.split("|")[0] != (top1.get("evidence_ref") or "").split("|")[0]
    return d


def classify(pool_ok: bool, scorable: bool, in_lattice: bool, rank,
             dm: dict, gold_dec: dict | None, top_dec: dict) -> str:
    """Taxonomy — mỗi nhãn ứng với MỘT cách sửa khác nhau."""
    if not pool_ok:
        return "POOL_MISS_candidate_generation"
    if not scorable:
        return "UNSCORABLE_zero_token_overlap"
    if in_lattice and rank == 0:
        return "HIT"
    # gold có trong pool và chấm được — vậy nó thua vì gì?
    if dm.get("cung_gia_tri"):
        return "AMBIGUITY_cung_gia_tri_khac_o"
    if dm.get("statement_khac"):
        return "ACCOUNTING_CONTEXT_statement_khac"
    if dm.get("col_khac") and not dm.get("row_label_khac"):
        return "TEMPORAL_cung_nhan_khac_cot"
    if dm.get("section_khac") and not dm.get("row_label_khac"):
        return "STRUCTURAL_cung_nhan_khac_section"
    j = dm.get("metric_jaccard", 0.0)
    if j >= 0.5:
        return "SEMANTIC_nhan_gan_giong_khac_nghia"
    if gold_dec and top_dec and gold_dec.get("total") is not None:
        if top_dec["exact_phrase"] > gold_dec["exact_phrase"]:
            return "LEXICAL_top1_trung_nguyen_van_cum_trong_cau"
        if top_dec["idf_overlap"] > gold_dec["idf_overlap"]:
            return "LEXICAL_top1_trung_nhieu_token_hon"
    return "LEXICAL_khac"


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    al = load_aliases()
    qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)

    pipe_full = PipelineFlags(depth=400, shortlist_m=400)
    rows = []
    for q in qids:
        g, plan = gold[q], plans[q]
        st = spec_text(plan, metric_phrase(plan, labs))
        gs = {s["slot"]: (s["ref"], str(s["raw"])) for s in g["provenance"]}
        tgt_years = {str(y) for y in (plan.get("years") or [])}
        qt, qnorm = toks(st), norm(st)

        for s in slots_for(plan, g["lop"], al):
            want = gs.get(s.name)
            if not want:
                continue
            sub = dict(plan)
            sub["entities"], sub["years"], sub["question"] = [s.ticker], [s.year], st
            pool = fetch_pool(con, sub, legacy_order=False)
            lts = [toks((c["metric_label"] or "") + " " + c["row_path"]) for c in pool]
            df: dict[str, int] = {}
            for lt in lts:
                for t in lt:
                    df[t] = df.get(t, 0) + 1
            n_pool = max(len(pool), 1)

            gold_c = next((c for c in pool if c["evidence_ref"] == want[0]
                           and str(c["value"]) == want[1]), None)
            ranked, _ = candidates_for_slot(con, plan, s, pipe_full, scoring_text=st)
            lattice = semantic_collapse(ranked, LATTICE_M)
            rank = next((i for i, c in enumerate(ranked)
                         if c["evidence_ref"] == want[0] and str(c["value"]) == want[1]),
                        None)
            in_lat = any(c["evidence_ref"] == want[0] and str(c["value"]) == want[1]
                         for c in lattice)
            top1 = ranked[0] if ranked else None
            if top1 is None:
                continue

            gd = decompose(gold_c, qt, qnorm, tgt_years, df, n_pool) if gold_c else None
            td = decompose(top1, qt, qnorm, tgt_years, df, n_pool)
            dm = mismatch_dims(gold_c, top1, want[0], want[1])
            tax = classify(gold_c is not None,
                           bool(gd and gd.get("scorable")), in_lat, rank, dm, gd, td)

            gap = None
            if gd and gd.get("total") is not None and td.get("total") is not None:
                gap = {k: round(td[k] - gd[k], 4)
                       for k in ("idf_overlap", "exact_phrase", "col_year",
                                 "doc_year", "ready")}
            rows.append({
                "qid": q, "intent": g["lop"], "slot": s.name, "role": s.role,
                "n_pool": len(pool), "gold_trong_pool": gold_c is not None,
                "gold_scorable": bool(gd and gd.get("scorable")),
                "gold_rank": rank, "gold_trong_lattice_top8": in_lat,
                "taxonomy": tax,
                "gold_label": (gold_c or {}).get("metric_label"),
                "top1_label": top1.get("metric_label"),
                "gold_col": (gold_c or {}).get("col_path", "")[:50],
                "top1_col": (top1.get("col_path") or "")[:50],
                "gold_statement": (gold_c or {}).get("statement_type"),
                "top1_statement": top1.get("statement_type"),
                "gold_score": gd, "top1_score": td,
                "khoang_cach_theo_feature": gap,
                "mismatch": dm,
            })

    n = len(rows)
    tax = Counter(r["taxonomy"] for r in rows)
    NHOM = {
        "HIT": "HIT",
        "POOL_MISS_candidate_generation": "POOL_MISS",
        "UNSCORABLE_zero_token_overlap": "UNSCORABLE",
        "AMBIGUITY_cung_gia_tri_khac_o": "AMBIGUITY",
        "ACCOUNTING_CONTEXT_statement_khac": "ACCOUNTING_CONTEXT",
        "TEMPORAL_cung_nhan_khac_cot": "TEMPORAL",
        "STRUCTURAL_cung_nhan_khac_section": "STRUCTURAL",
        "SEMANTIC_nhan_gan_giong_khac_nghia": "SEMANTIC",
    }
    nhom = Counter(NHOM.get(k, "LEXICAL") for k in
                   (r["taxonomy"] for r in rows))

    fails = [r for r in rows if r["taxonomy"] != "HIT"]
    feat_blame = Counter()
    for r in fails:
        gap = r.get("khoang_cach_theo_feature")
        if not gap:
            continue
        k = max(gap, key=lambda x: gap[x])
        if gap[k] > 0:
            feat_blame[k] += 1

    rep = {
        "_schema": "diag_slot_scoring v1 — failure taxonomy TRƯỚC khi tuning (D1a)",
        "date": "2026-08-21",
        "dataset": "gold_dap_an_v1 · 24 câu non-lookup",
        "denominator": {"n_slot": n, "n_qid": len(qids)},
        "evaluation_mode": "TRAIN_FIT / RESEARCH-ONLY",
        "provenance": "gold 45/45 row_label_exact; lattice = top-400 → semantic collapse → top-8",
        "scoring_S0_thanh_phan": {
            "idf_overlap": "Σ log(1+n_pool/df[t]) trên token chung / √(len(label_tokens))",
            "exact_phrase": "+3,0 nếu nhãn metric (>=8 ký tự) là chuỗi con của câu",
            "col_year": "+0,6 nếu năm hỏi xuất hiện trong col_path",
            "doc_year": "+0,3 nếu doc_year thuộc năm hỏi",
            "ready": "+0,3 × execution_ready",
        },
        "gioi_han_cau_truc_nhin_tu_code": [
            "scoring_text DÙNG CHUNG cho mọi slot — không có operand-specific phrase",
            "KHÔNG có statement_type/section/basis/unit_kind/value_kind/period_end trong điểm",
            "col_year chỉ kiểm chuỗi con '2022' — không phân biệt cột kỳ với cột ghi chú",
            "mẫu số √(len(lt)) PHẠT nhãn dài ⇒ ưu ái nhãn tổng quát hơn nhãn cụ thể",
        ],
        "taxonomy_chi_tiet": dict(tax.most_common()),
        "taxonomy_theo_nhom": dict(nhom.most_common()),
        "taxonomy_ty_le": {k: round(v / n, 4) for k, v in nhom.most_common()},
        "feature_lam_gold_thua": dict(feat_blame.most_common()),
        "tom_tat": {
            "n_slot": n,
            "gold_trong_pool": sum(r["gold_trong_pool"] for r in rows),
            "gold_scorable": sum(r["gold_scorable"] for r in rows),
            "gold_trong_lattice_top8": sum(r["gold_trong_lattice_top8"] for r in rows),
            "gold_top1": sum(1 for r in rows if r["gold_rank"] == 0),
        },
        "per_slot": rows,
        "command": "python3 tools/diag_slot_scoring_v1.py",
    }
    (ROOT / "reports/diag_slot_scoring_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    t = rep["tom_tat"]
    print(f"n_slot = {n} (trên {len(qids)} câu)\n")
    print(f"  gold trong POOL SQL      {t['gold_trong_pool']:>3}/{n}")
    print(f"  gold SCORABLE            {t['gold_scorable']:>3}/{n}")
    print(f"  gold trong LATTICE top-8 {t['gold_trong_lattice_top8']:>3}/{n}")
    print(f"  gold TOP-1               {t['gold_top1']:>3}/{n}")
    print("\nFAILURE TAXONOMY (nhóm):")
    for k, v in nhom.most_common():
        print(f"  {k:22} {v:>3}  {v/n:>6.1%}")
    print("\nchi tiết:")
    for k, v in tax.most_common():
        print(f"  {k:46} {v:>3}")
    print("\nfeature làm gold THUA (khoảng cách lớn nhất):")
    for k, v in feat_blame.most_common():
        print(f"  {k:16} {v:>3}")
    print("\n-> reports/diag_slot_scoring_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
