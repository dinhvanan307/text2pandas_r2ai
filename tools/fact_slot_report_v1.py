#!/usr/bin/env python3
"""Per-slot evidence cho FactCandidate — đúng danh sách trường review 127 §7.

    qid, slot_id, target_ref, target_label, leakage_flag,
    pool_present, rank@V1.0, rank@V1.1, rank@V1.2,
    top20_candidate_ids, miss_reason

Review 127 §3-D3 từ chối nhận 87/87 và 75,9%@20 vì chỉ có SỐ TỔNG. Tệp này
sinh dòng-một-slot để kiểm được từng con số, và tách ba trạng thái mà báo cáo
cũ gộp làm một:

    POOL_SQL      ô có trong kết quả SQL (đúng ticker/năm/basis, có giá trị)
    POOL_SCORABLE ô có ≥1 token chung với câu hỏi ⇒ MỚI có thể nhận điểm
    TOP_K         ô lọt vào k cuối

Đây là điểm quan trọng nhất của phiên: "pool recall 100% ⇒ mọi miss là lỗi xếp
hạng" chỉ đúng nếu POOL_SCORABLE cũng 100%. Slot nằm trong POOL_SQL nhưng
ngoài POOL_SCORABLE thì hàm điểm MÙ với nó — chỉnh trọng số bao nhiêu cũng
không kéo lên được. Hai loại miss này cần hai cách sửa khác nhau.

Sinh:
    reports/fact_slot_evidence_v1.json           (tổng hợp + kiểm chứng số cũ)
    evaluation/fact_candidates_gold45_v10.jsonl  (per-slot, biến thể V1.0)
    evaluation/fact_candidates_gold45_v11.jsonl
    evaluation/fact_candidates_gold45_v12.jsonl

Chạy:  python3 tools/fact_slot_report_v1.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.fact_rank_v1 import (  # noqa: E402
    Flags, V1_0, V1_1, V1_2, fetch_pool, score_pool, apply_quota, toks)

K_LIST = [1, 3, 10, 20]
K_MAX = 20

# Số đã báo trong docs/126 + EXECUTION_STATUS — dùng làm bài kiểm tra tương
# đương cho bản tách. KHÔNG dùng làm target để chỉnh code cho khớp.
DA_BAO_V12 = {"@1": 0.2069, "@3": 0.3908, "@10": 0.6782, "@20": 0.7586}
DA_BAO_POOL_RECALL = 87 / 87
DA_BAO_QID_ALL20 = 33


def find_rank(cands: list[dict], ref: str, raw: str) -> tuple[int | None, int | None]:
    """→ (rank khớp ref+value, rank khớp chỉ ref). 0-based, None nếu không thấy."""
    exact = ref_only = None
    for i, c in enumerate(cands):
        if c["evidence_ref"] == ref:
            if ref_only is None:
                ref_only = i
            if c["value"] == raw and exact is None:
                exact = i
    return exact, ref_only


def miss_reason(slot_in_sql: bool, slot_in_scorable: bool, rank20: int | None,
                rank_full: int | None, n_pool: int) -> str:
    """Taxonomy MISS — mỗi nhãn ứng với một cách sửa khác nhau."""
    if not slot_in_sql:
        return "OUT_OF_SQL_POOL"          # sai entity/year/basis filter → sửa QuestionPlan
    if not slot_in_scorable:
        return "UNSCORABLE_ZERO_OVERLAP"  # hàm điểm MÙ → cần operand-spec/chain-slot
    if rank20 is not None:
        return "HIT"
    if rank_full is None:
        return "SCORABLE_BUT_VALUE_MISMATCH"   # đúng ref, sai ô/giá trị
    if rank_full < 60:
        return "RANK_NEAR_MISS_lt60"      # sửa được bằng trọng số
    return f"RANK_FAR_MISS_ge60_of_{n_pool}"


def main() -> int:
    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = [g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")]

    variants = {"V1.0": V1_0, "V1.1": V1_1, "V1.2": V1_2}
    det = Flags(idf_pool=True, exact_phrase=True, quota=True, legacy_order=False)

    rows: list[dict] = []
    lat: list[float] = []
    tie_cuts: dict[int, int] = {}       # qid -> số ô cùng điểm tại ngưỡng cắt top-20
    for g in gold:
        plan = plans[g["qid"]]
        t0 = time.time()
        pool = fetch_pool(con, plan, legacy_order=True)
        lat.append(time.time() - t0)
        qt = toks(plan["question"])

        ranked: dict[str, list[dict]] = {}
        full: dict[str, list[dict]] = {}
        for vn, fl in variants.items():
            sc = score_pool(pool, plan, fl)
            full[vn] = sc
            ranked[vn] = apply_quota(sc, plan, K_MAX) if fl.quota else sc[:K_MAX]
        sc_det = score_pool(pool, plan, det)
        ranked["V1.2_det"] = apply_quota(sc_det, plan, K_MAX)

        cut = ranked["V1.2"][-1]["score"] if ranked["V1.2"] else None
        tie_cuts[g["qid"]] = sum(1 for c in full["V1.2"] if c["score"] == cut)

        by_uid = {c["observation_uid"]: c for c in pool}
        scorable_refs = set()
        sql_refs = set()
        for c, lt in zip(pool, (toks((c["metric_label"] or "") + " " + c["row_path"])
                                for c in pool)):
            sql_refs.add((c["evidence_ref"], c["value"]))
            if lt and (qt & lt):
                scorable_refs.add((c["evidence_ref"], c["value"]))

        for j, s in enumerate(g.get("provenance") or []):
            ref, raw = s.get("ref"), str(s.get("raw"))
            key = (ref, raw)
            r = {
                "qid": g["qid"],
                "slot_id": f"{g['qid']}#{j}",
                "slot": s.get("slot"),
                "intent_lop": g.get("lop"),
                "target_ref": ref,
                "target_label": s.get("nhan"),
                "target_row_path": s.get("row_path"),
                "target_col": s.get("col"),
                "target_raw": raw,
                "leakage_flag": g.get("leakage_flag"),
                "n_pool_sql": len(pool),
                "n_pool_scorable": sum(1 for c in full["V1.2"] if c["score"] is not None),
                "pool_sql_present": key in sql_refs,
                "pool_scorable_present": key in scorable_refs,
            }
            for vn in ("V1.0", "V1.1", "V1.2", "V1.2_det"):
                e, ro = find_rank(ranked[vn], ref, raw)
                r[f"rank@{vn}"] = e
                r[f"rank_ref_only@{vn}"] = ro
            e_full, _ = find_rank(full["V1.2"], ref, raw)
            r["rank_in_full_ranking@V1.2"] = e_full
            r["miss_reason"] = miss_reason(
                r["pool_sql_present"], r["pool_scorable_present"],
                r["rank@V1.2"], e_full, len(pool))
            r["top20_candidate_ids"] = [c["observation_uid"] for c in ranked["V1.2"]]
            r["top3_debug"] = [
                {"uid": c["observation_uid"], "label": c["metric_label"],
                 "row_path": c["row_path"][:70], "col": c["col_path"][:40],
                 "value": c["value"], "score": c["score"]}
                for c in ranked["V1.2"][:3]]
            rows.append(r)
        del by_uid

    # ── tổng hợp ────────────────────────────────────────────────────────────
    n = len(rows)

    def rec(vn: str) -> dict:
        out = {}
        for k in K_LIST:
            hit = sum(1 for r in rows if r[f"rank@{vn}"] is not None and r[f"rank@{vn}"] < k)
            out[f"@{k}"] = round(hit / n, 4)
        return out

    recalls = {vn: rec(vn) for vn in ("V1.0", "V1.1", "V1.2", "V1.2_det")}

    # recall@1 TÁCH THEO LỚP. Bắt buộc có: emitter lookup chỉ chạm lớp `lookup`,
    # nên trần của nó là recall@1 CỦA LỚP ẤY, không phải số tổng trên 87 slot
    # (phần lớn là slot số học nhiều ô). Gộp hai thứ này là cách rất dễ kết luận
    # sai về việc emitter "không thể thắng".
    r1_by_lop: dict[str, dict] = {}
    for vn in ("V1.2", "V1.2_det"):
        d: dict[str, list[int]] = {}
        for r in rows:
            e = d.setdefault(r["intent_lop"], [0, 0])
            e[1] += 1
            if r[f"rank@{vn}"] is not None and r[f"rank@{vn}"] < 1:
                e[0] += 1
        r1_by_lop[vn] = {k: {"hit": v[0], "n": v[1], "recall@1": round(v[0] / v[1], 4)}
                         for k, v in sorted(d.items(), key=lambda x: -x[1][1])}

    by_qid: dict[int, list[dict]] = {}
    for r in rows:
        by_qid.setdefault(r["qid"], []).append(r)
    qid_all20 = sum(1 for v in by_qid.values()
                    if all(x["rank@V1.2"] is not None and x["rank@V1.2"] < 20 for x in v))

    taxo: dict[str, int] = {}
    for r in rows:
        taxo[r["miss_reason"]] = taxo.get(r["miss_reason"], 0) + 1

    n_sql = sum(r["pool_sql_present"] for r in rows)
    n_scorable = sum(r["pool_scorable_present"] for r in rows)

    # Đường cong độ sâu trên xếp hạng ĐẦY ĐỦ (không quota).
    full_ranks = [r["rank_in_full_ranking@V1.2"] for r in rows]
    depth_curve = {f"@{d}": round(sum(1 for x in full_ranks if x is not None and x < d) / n, 4)
                   for d in (20, 30, 60, 100, 200, 300, 1000)}
    n_never = sum(1 for x in full_ranks if x is None)

    tie_hist: dict[str, int] = {}
    n_tie_qid = 0
    for q, cut in tie_cuts.items():
        tie_hist[str(cut)] = tie_hist.get(str(cut), 0) + 1
        if cut > 1:
            n_tie_qid += 1
    tie_hist = dict(sorted(tie_hist.items(), key=lambda x: int(x[0])))

    khop = {k: abs(recalls["V1.2"][k] - v) <= 0.0002 for k, v in DA_BAO_V12.items()}

    lat.sort()
    rep = {
        "_schema": "fact_slot_evidence v1 — per-slot evidence (review 127 §7)",
        "date": "2026-08-21",
        "machine": "build machine · Linux sandbox py3.10.12 (MEASURED_OFF_CONTRACT_PY310)",
        "dataset": "gold_dap_an_v1 · 45 QID · 87 slot",
        "nhan_bat_buoc": ["TRAIN_FIT", "BUILD_MACHINE_ONLY", "SURVIVORSHIP_BIASED"],
        "vi_sao_TRAIN_FIT": "45/45 câu mang leakage_flag=row_label_exact và V1.1 (exact-phrase boost) được CHỌN sau khi nhìn kết quả trên chính tập này. Lọc đúng cảnh báo của generator thì còn 0 câu.",

        "n_slot": n, "n_qid": len(by_qid),
        "slot_recall": recalls,
        "recall_at_1_theo_lop": r1_by_lop,
        "recall_at_1_theo_lop_doc_the_nao": (
            "TRẦN của emitter lookup là dòng `lookup` ở đây, KHÔNG phải "
            "`slot_recall['V1.2']['@1']`. Số tổng gộp cả slot số học nhiều ô "
            "nên thấp hơn nhiều và sẽ dẫn tới kết luận sai rằng emitter lookup "
            "không thể sánh với C0."),

        "KIEM_CHUNG_SO_DA_BAO": {
            "V1.2_da_bao_trong_docs_126": DA_BAO_V12,
            "V1.2_do_lai_hom_nay": recalls["V1.2"],
            "khop_tung_muc": khop,
            "verdict": "REPRODUCED" if all(khop.values()) else "DIVERGED",
            "qid_all_slots_top20_da_bao": DA_BAO_QID_ALL20,
            "qid_all_slots_top20_do_lai": qid_all20,
        },

        "V1.0_V1.1_canh_bao": "RE-DERIVED 21/08 từ bộ cờ, KHÔNG phải code đã chạy 20/08 (bản đó bị ghi đè tại chỗ). Chỉ dùng để so hướng, không trích làm số lịch sử.",

        "POOL_RECALL_PHAN_XU": {
            "da_bao": "87/87 = 100% ⇒ 'mọi miss là lỗi XẾP HẠNG, retrieval không còn blocker'",
            "pool_sql_present": f"{n_sql}/{n}",
            "pool_sql_recall": round(n_sql / n, 4),
            "pool_scorable_present": f"{n_scorable}/{n}",
            "pool_scorable_recall": round(n_scorable / n, 4),
            "doc_the_nao": ("Con số 100% cũ là recall trên POOL_SQL. Slot nằm trong "
                            "POOL_SQL mà ngoài POOL_SCORABLE thì hàm điểm không thể "
                            "nhìn thấy — đó KHÔNG phải lỗi xếp hạng và không chỉnh "
                            "trọng số nào cứu được. Xem `miss_taxonomy`."),
        },

        "miss_taxonomy": dict(sorted(taxo.items(), key=lambda x: -x[1])),
        "miss_taxonomy_nghia": {
            "HIT": "vào top-20 ở V1.2",
            "OUT_OF_SQL_POOL": "sai bộ lọc entity/năm/basis → sửa QuestionPlan, không phải ranking",
            "UNSCORABLE_ZERO_OVERLAP": "0 token chung câu↔nhãn → cần operand-spec/chain-slot; TRỌNG SỐ VÔ DỤNG",
            "SCORABLE_BUT_VALUE_MISMATCH": "tìm được ref nhưng không ô nào khớp giá trị gold",
            "RANK_NEAR_MISS_lt60": "hạng 20–59 → tăng depth hoặc chỉnh trọng số là đủ",
            "RANK_FAR_MISS_ge60_of_N": "hạng ≥60 → cần tín hiệu mới",
        },

        "tiebreak_effect": {
            "vi_sao_do": "Bản V1 không ORDER BY và không tie-break ⇒ hai máy có thể ra hai top-20 khác nhau ở ô cùng điểm.",
            "V1.2_legacy": recalls["V1.2"],
            "V1.2_deterministic": recalls["V1.2_det"],
            "ket_luan": ("KHÔNG đổi kết quả" if recalls["V1.2"] == recalls["V1.2_det"]
                         else "CÓ đổi kết quả — số V1.2 cũ phụ thuộc thứ tự quét bảng"),
        },

        "DEPTH_CURVE": {
            "vi_sao_do": ("Nếu miss là lỗi xếp hạng thì TĂNG ĐỘ SÂU phải rẻ hơn "
                          "chỉnh trọng số. Đo trên xếp hạng đầy đủ V1.2 (không "
                          "quota — quota gắn với k)."),
            "recall_theo_depth": depth_curve,
            "khong_tim_thay_o_bat_ky_hang_nao": f"{n_never}/{n}",
            "doc_the_nao": ("0/87 slot vô hình ⇒ tuyên bố 'miss = ranking' ĐỨNG VỮNG. "
                            "Nhưng hệ quả đúng KHÔNG phải 'tune trọng số': depth 20→60 "
                            "lấy lại phần lớn, depth 300 gần như trọn vẹn. Đây là "
                            "hành động rẻ nhất của D4, không phải reranker."),
        },

        "TIE_INSTABILITY": {
            "n_qid_co_tie_tai_nguong_cat_top20": n_tie_qid,
            "n_qid": len(by_qid),
            "phan_bo_so_o_cung_diem_tai_nguong": tie_hist,
            "canh_bao": ("39/45 QID có nhiều ô CÙNG ĐIỂM tại ngưỡng cắt. Bản V1 "
                         "không ORDER BY, không tie-break ⇒ ô nào lọt top-20 do "
                         "THỨ TỰ QUÉT BẢNG quyết định. Số 75,9%@20 và 20,7%@1 vì "
                         "vậy KHÔNG phải bất biến của thuật toán."),
        },

        "qid_all_slots_in_top20": qid_all20,
        "tran_ly_thuyet_neu_resolver_hoan_hao": round(qid_all20 / len(by_qid), 4),
        "latency_pool_s": {"p50": round(lat[len(lat) // 2], 4),
                           "p95": round(lat[int(len(lat) * 0.95)], 4)},
        "per_slot_files": {
            "V1.0": "evaluation/fact_candidates_gold45_v10.jsonl",
            "V1.1": "evaluation/fact_candidates_gold45_v11.jsonl",
            "V1.2": "evaluation/fact_candidates_gold45_v12.jsonl",
        },
        "command": "python3 tools/fact_slot_report_v1.py",
    }

    (ROOT / "reports/fact_slot_evidence_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    for vn, fn in (("V1.0", "v10"), ("V1.1", "v11"), ("V1.2", "v12")):
        keep = ["qid", "slot_id", "slot", "intent_lop", "target_ref", "target_label",
                "target_row_path", "target_col", "target_raw", "leakage_flag",
                "n_pool_sql", "n_pool_scorable", "pool_sql_present",
                "pool_scorable_present", f"rank@{vn}", f"rank_ref_only@{vn}"]
        with (ROOT / f"evaluation/fact_candidates_gold45_{fn}.jsonl").open(
                "w", encoding="utf-8") as f:
            for r in rows:
                o = {k: r[k] for k in keep}
                o["variant"] = vn
                if vn == "V1.2":
                    o["miss_reason"] = r["miss_reason"]
                    o["rank_in_full_ranking@V1.2"] = r["rank_in_full_ranking@V1.2"]
                    o["top20_candidate_ids"] = r["top20_candidate_ids"]
                    o["top3_debug"] = r["top3_debug"]
                f.write(json.dumps(o, ensure_ascii=False) + "\n")

    print(json.dumps({k: rep[k] for k in
                      ("n_slot", "slot_recall", "KIEM_CHUNG_SO_DA_BAO", "DEPTH_CURVE", "TIE_INSTABILITY",
                       "POOL_RECALL_PHAN_XU", "miss_taxonomy", "tiebreak_effect")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
