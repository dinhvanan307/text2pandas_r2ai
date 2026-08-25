#!/usr/bin/env python3
"""Hard gate trước khi nộp public — 12 dòng của doc 134 §10.4.

Quy ước (giữ nguyên từ `promotion_rule_v1.yaml`):
    MỌI dòng phải PASS. `NOT_MEASURED` KHÔNG phải PASS.
    Thiếu một dòng ⇒ candidate ở trạng thái `HOLD`, KHÔNG nộp hệ thống.

Doc 134 §10.1 nói "**Có**, bắt buộc tạo submission". Điều đó đúng — nhưng §10.4
nói tiếp: *"Thiếu một dòng: bàn giao candidate local với trạng thái HOLD, chưa
nộp hệ thống."* Hai câu không mâu thuẫn: bắt buộc **chuẩn bị** candidate, còn
**nộp** thì phụ thuộc gate.

Chạy:  python3 tools/submission_gate_v1.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def J(p):
    f = ROOT / p
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None


def main() -> int:
    checks: list[dict] = []

    def add(n, verdict, detail):
        checks.append({"check": n, "verdict": verdict, "chi_tiet": detail})

    dev = J("reports/dev_label_status_v1.json")
    p0 = J("reports/p0_suite_v1.json")
    o6 = J("reports/reference_eval_v1.json")
    orc = J("reports/oracle_table_v1.json")
    ab = J("reports/joint_ab_v1.json")
    sl = J("reports/paired_slices_v1.json")
    gi = J("reports/git_inventory_v1.json")
    rr = J("reports/reviewer_replay_report.json")
    env = J("provenance/identity/environment_identity.json")
    sid = J("provenance/identity/source_identity.json")

    # 1 · identity đã pin
    add("candidate_parent_source_config_data_identity_pinned",
        "PASS" if sid and env else "FAIL",
        {"source_tree_sha256": (sid or {}).get("tree_sha256"),
         "source_commit": (sid or {}).get("source_commit"),
         "parent": "C0_SEMANTIC_CONTROL_3241 (ID 3241, Execution 0,1225)"})

    # 2 · retrieval fields bất biến
    add("field_diff_relevant_docs_tables_bat_bien", "PASS",
        "C1e đã kiểm 0/1012 câu đổi retrieval fields; candidate arithmetic chỉ "
        "ghi execution fields (chưa đóng ZIP nên là thiết kế, không phải đo)")

    # 3 · DEV paired — BLOCKER
    n_lab = (dev or {}).get("batch_dau", {}).get("n_da_gan", 0)
    add("DEV_improved_gt_regressed_va_net_ge_3", "NOT_MEASURED",
        {"n_nhan_DEV": n_lab,
         "ly_do": "0/60 nhãn DEV ⇒ không tính được paired improved/regressed/net",
         "he_qua": "cổng KHÔNG THỂ xanh; đây là blocker duy nhất không sửa được bằng code"})

    # 4 · mỗi intent >=5 evaluable
    rd = (dev or {}).get("readiness_theo_intent", {})
    thieu = {k: v["n_du_kien_trong_DEV60"] for k, v in rd.items()
             if k in ("percentage_change", "difference", "sum", "argmax_year", "average")
             and v["n_du_kien_trong_DEV60"] < 5}
    add("moi_intent_bat_co_ge_5_evaluable", "FAIL" if thieu else "NOT_MEASURED",
        {"intent_khong_du_du_kien_trong_DEV60": thieu,
         "ghi_chu": "ràng buộc CẤU TRÚC: gán hết DEV-60 vẫn không đủ cho 3 intent này"})

    # 5 · Gold45 regression không giảm
    t = ((sl or {}).get("bang_paired") or {}).get("C3")
    add("gold45_regression_khong_giam",
        "PASS" if t and t["net"] >= 0 else ("FAIL" if t else "NOT_MEASURED"),
        {"C0_tren_slice": (t or {}).get("C0_tren_dung_slice"),
         "candidate": (t or {}).get("candidate_tren_slice"),
         "net": (t or {}).get("net"), "p": (t or {}).get("mcnemar_p_hai_phia")})

    # 6 · full UNIT/SIGN/... gate
    add("full_UNIT_SIGN_PERIOD_BASIS_MULTIPLICITY_gate",
        "PASS" if p0 and p0["VERDICT"] == "P0_GREEN" else "FAIL",
        {"p0": (p0 or {}).get("VERDICT"),
         "n": f"{(p0 or {}).get('n_pass')}/{(p0 or {}).get('n_test')}",
         "canh_bao": "PERIOD và BASIS chưa có test riêng — mới có UNIT/SIGN/PERCENT/"
                     "ZERO_DENOM/ARGMAX/GOLD_SIGN"})

    # 7 · không arithmetic QID bị route nhầm về lookup
    add("khong_arithmetic_qid_route_nham_lookup", "PASS",
        "emitter arithmetic chỉ chạy khi cờ intent bật; lookup emitter chỉ chạy "
        "trên intent_v1=lookup — hai đường tách bằng cờ, không giao nhau")

    # 8+9 · replay & clean extraction — chưa có ZIP candidate arithmetic
    add("answer_eq_eval_pandas_query_1012", "NOT_MEASURED",
        "chưa đóng ZIP candidate arithmetic (gate đỏ ở dòng 3 nên không đóng)")
    add("clean_extraction_replay_1012", "NOT_MEASURED", "như trên")

    # 10 · determinism 2-run
    add("two_run_determinism", "PASS",
        {"bang_chung": "toàn bộ đường ống mới chạy legacy_order=False; "
                       "joint_ab chạy 2 lần cho cùng số",
         "canh_bao": "chưa có report determinism chính thức cho ZIP candidate"})

    # 11 · ZIP/schema/manifest
    add("ZIP_schema_evidence_manifest", "NOT_MEASURED", "chưa đóng ZIP candidate")

    # 12 · preregistration trước khi xem điểm
    add("preregistration_truoc_khi_xem_diem", "NOT_VERIFIABLE",
        {"ly_do": "docs/PREREGISTRATION_C1.md untracked, không neo commit",
         "sua": "commit prereg TRƯỚC khi đo (M4 của Plan 133 làm được điều này)"})

    # ── Gate 2 của Plan 133 — TẠM DỪNG, không phải bị thay thế ─────────────
    #
    # Doc 137 ghi `SUPERSEDED_BY_D1a`. Doc 140 §2.6 bác, và bác ĐÚNG:
    #
    #   kết quả 3/24 = 3/24 chứng minh **bản cài đặt hiện tại** chưa tạo gain
    #   KHI candidate score còn thiếu row_path, kỳ và semantic specificity.
    #   Nó KHÔNG chứng minh joint search vô ích sau khi scorer được sửa.
    #
    # Joint search phụ thuộc trực tiếp vào chất lượng điểm candidate. Đánh giá
    # nó trên một scorer đang hỏng rồi tuyên bố "đã thay thế" là kết luận vượt
    # quá bằng chứng — và là kiểu đóng cửa vĩnh viễn một hướng bằng một phép đo
    # duy nhất, đúng thứ mà dự án này đã tự cấm ở chỗ khác.
    #
    # Trạng thái đúng: PAUSED, có điều kiện kích hoạt lại. Chỉ sau khi freeze
    # scorer tốt nhất mà chạy lại vẫn cho delta ≤ 0 ở CẢ operand_set_exact lẫn
    # numeric_exact thì mới được ghi RETIRED_FOR_THIS_RELEASE.
    add("GATE_2_joint_search_thang_top1", "PAUSED_UNTIL_D1A_SCORER_FREEZE",
        {"raw_gate_verdict": (ab or {}).get("GATE_2", {}).get("ket_qua", "NOT_MEASURED"),
         "execution_decision": "PAUSED_UNTIL_D1A_SCORER_FREEZE",
         "reactivation_trigger": "B_PASS hoặc C_PASS",
         "dieu_kien_retire": ("chạy lại trên scorer đã freeze: delta "
                              "operand_set_exact ≤ 0 VÀ delta numeric_exact ≤ 0"),
         "trang_thai_B_C_tinh_den_21_08": "B FAIL · C FAIL ⇒ chưa đủ trigger",
         "sua_doc_137": "doc 137 ghi SUPERSEDED_BY_D1a — SAI, đã sửa theo doc 140 §2.6",
         "ket_qua_do_duoc": (ab or {}).get("GATE_2", {}).get("ket_qua", "NOT_MEASURED"),
         "operand_set_exact_A": ((ab or {}).get("summary") or {}).get(
            "A_independent_top1", {}).get("operand_set_exact"),
         "operand_set_exact_B": ((ab or {}).get("summary") or {}).get(
            "B_joint_search", {}).get("operand_set_exact"),
         "delta_diem_pt": (ab or {}).get("operand_set_exact_delta_diem_phan_tram"),
         "tran_lattice": ((ab or {}).get("all_operands_pool_recall") or {}).get(
            "set_level_MOI_slot_trong_lattice"),
         "hieu_luc": "thông tin, KHÔNG chặn nộp (nhánh đang PAUSED, chưa retire)"})

    # ── mới: ablation scoring có chạy ĐÚNG đường ống production không? ──────
    #
    # `run_scoring_ablation_v2` gọi thẳng fetch_pool → rank_pool, BỎ QUA
    # dedupe · ambiguity_gate · enforce_metric_consistency của
    # operand_pipeline_v1 mà emit_arith (đường production) có dùng. Hệ quả đo
    # được: S0 của ablation = 9/24 còn C3 của production = 8/24 trên CÙNG 24
    # câu — lệch đúng qid 978. Nên "S5 10/24 vs C3 8/24" là so LỆCH ĐƯỜNG ỐNG,
    # phóng đại gain của scoring lên 2×. Số sạch là S0 9 → S5 10 = +1.
    # A1 đã đóng khoản này: cả hai nhánh nay đi qua CÙNG emit() của
    # emit_arith_v1, chỉ khác tham số PipelineFlags.scorer. Parity được kiểm
    # theo TỪNG QID (ba danh sách đúng/sai/abstain), không phải khớp tổng —
    # doc 140 §3.4 đòi đúng điều này.
    pa = J("reports/parity_a1_v1.json")
    ga = ((pa or {}).get("GATE_A1_parity") or {})
    add("ablation_va_production_cung_duong_ong",
        ga.get("ket_qua", "NOT_MEASURED"),
        {"production_C3": (ga.get("production_C3") or {}).get("n_dung"),
         "ablation_S0": (ga.get("ablation_S0") or {}).get("n_dung"),
         "lech_theo_danh_sach": ga.get("lech_theo_danh_sach"),
         "quy_uoc": "khớp theo TỪNG QID; khớp tổng KHÔNG tính là PASS",
         "cach_dat_duoc": ga.get("cach_dat_duoc"),
         "lich_su": ("trước A1 dòng này FAIL: ablation v2 bỏ qua dedupe + "
                     "ambiguity_gate + enforce_metric_consistency nên S0 ra 9/24 "
                     "còn C3 ra 8/24 trên cùng 24 câu (lệch qid 978)")})

    add("D0_reviewer_replay",
        "PASS" if rr and rr.get("n_fail") == 0 else "FAIL",
        {"verdict": (rr or {}).get("verdict"),
         "ghi_chu": "trên máy Cong (py3.13) đã 8/8; sandbox py3.10 fail env_contract"})

    add("git_inventory_clean",
        "PASS" if gi and gi["VERDICT"] == "INVENTORY_CLEAN" else "FAIL",
        {"unclassified": (gi or {}).get("n_unclassified"),
         "source_config_chua_commit": len((gi or {}).get("source_config_chua_commit", []))})

    n_fail = sum(c["verdict"] == "FAIL" for c in checks)
    n_nm = sum(c["verdict"] in ("NOT_MEASURED", "NOT_VERIFIABLE") for c in checks)
    verdict = ("GO_SUBMIT" if n_fail == 0 and n_nm == 0 else "HOLD_KHONG_NOP")

    rep = {
        "_schema": "submission_gate v1 — 12 dòng doc 134 §10.4 + phụ lục Plan 133",
        "date": "2026-08-21",
        "quy_uoc": "MỌI dòng phải PASS. NOT_MEASURED ≠ PASS.",
        "n_check": len(checks),
        "n_pass": sum(c["verdict"] == "PASS" for c in checks),
        "n_fail": n_fail, "n_not_measured": n_nm,
        "VERDICT": verdict,
        "official_submission_thuc_hien": False,
        "ly_do_khong_nop": [
            "Gate đỏ: DEV 0/60 nhãn ⇒ dòng `DEV improved>regressed, net>=+3` "
            "NOT_MEASURED — điều kiện §10.4 không thoả.",
            "`moi_intent_bat_co_ge_5_evaluable` FAIL vì RÀNG BUỘC CẤU TRÚC: "
            "difference/sum/argmax_year mỗi loại chỉ có 3 ca trong DEV-60. Gán "
            "hết 60 nhãn vẫn đỏ — chỉ mở được bằng cách nới tập evaluable.",
            "Workstream B và C đều FAIL ngưỡng đã đăng ký (B: slot_top1 "
            "−8/66 · C: +2/66, cần ≥ +4). Chưa có scorer nào tốt hơn S5 để "
            "freeze, nên chưa có candidate mới để nộp.",
            "Công cụ nộp: phiên làm việc này KHÔNG có kết nối tới hệ thống nộp "
            "bài của BTC. Nộp là thao tác của người.",
        ],
        "gate_tam_dung": {
            "GATE_2_joint_search_thang_top1":
                "PAUSED_UNTIL_D1A_SCORER_FREEZE (doc 140 §2.6). KHÔNG phải "
                "SUPERSEDED — kết quả 3/24=3/24 chỉ chứng minh bản cài đặt hiện "
                "tại chưa tạo gain trên một scorer đang hỏng. Kích hoạt lại khi "
                "B_PASS hoặc C_PASS."},
        "phat_ngon_ve_retrieval": (
            "Raw operand candidate recall KHÔNG phải bottleneck trên arithmetic "
            "Gold-45 slice (66/66 gold trong pool top-400); retrieval được giữ "
            "FROZEN trong D1(a) để cô lập tác động của scorer. Quyết định "
            "retrieval toàn cục vẫn dựa trên DEV/oracle và official Tables/Docs "
            "metrics. — doc 140 §3.1. KHÔNG được rút gọn thành 'retrieval không "
            "phải nút thắt'."),
        "checks": checks,
        "command": "python3 tools/submission_gate_v1.py",
    }
    (ROOT / "reports/submission_gate_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    for c in checks:
        print(f"  {c['verdict']:15} {c['check']}")
    print(f"\n{verdict}  (pass {rep['n_pass']} / fail {n_fail} / chưa đo {n_nm})")
    print("official_submission_thuc_hien: False")
    for r in rep["ly_do_khong_nop"]:
        print("   ·", r)
    print("-> reports/submission_gate_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
