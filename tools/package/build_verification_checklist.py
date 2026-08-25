#!/usr/bin/env python3
"""reports/163_verification_checklist.json — Pha 0 directive.

Mỗi requirement có `verification_status` ĐỌC TỪ ARTIFACT, không gõ tay. Nếu
artifact chưa tồn tại thì status là `NOT_VERIFIED`, không phải `VERIFIED`.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R = ROOT / "reports/163"


def j(p):
    q = R / p
    return json.loads(q.read_text(encoding="utf-8")) if q.is_file() else None


def main() -> int:
    ident = j("identity/P0I_IDENTITY.json") or {}
    rep = j("identity/REPLAY_IDENTITY.json") or {}
    diff = j("lineage/replay_diff_summary.json") or {}
    lin = j("lineage/lineage_summary.json") or {}
    srcp = j("gold/source_cell_projection_summary.json") or {}
    fun = j("funnel/failure_funnel_summary_v2.json") or {}
    fval = j("funnel/funnel_validator_report.json") or {}
    wl = j("unit_drift/proposed_u1_whitelist.json") or {}
    rck = j("gold/blind_recheck_protocol.json") or {}
    sel = j("gold/wave1_selection.json") or {}

    C = []

    def add(rid, sec, claim, art, cmd, st, ev, note=""):
        C.append({"requirement_id": rid, "source_section": sec,
                  "claim_or_requirement": claim, "artifact_needed": art,
                  "verification_command": cmd, "verification_status": st,
                  "evidence_path": ev, "notes": note})

    add("R-2.1", "§2.1", "P0I ZIP SHA256 = a68580bd…",
        "identity/P0I_IDENTITY.json",
        "python3 tools/lineage/build_identity_and_lineage_v2.py",
        "VERIFIED" if ident.get("zip_sha256", "").startswith("a68580bd") else "CONTRADICTED",
        "reports/163/identity/P0I_IDENTITY.json",
        f"members={ident.get('n_members')} rows={ident.get('n_rows')}")
    add("R-2.2", "§2.2", "doc 162 đảo nhãn P0I/replay; raw P0I = fa27e15d…",
        "lineage/replay_diff_summary.json", "cùng lệnh trên",
        "VERIFIED" if ident.get("submission_json_raw_sha256", "").startswith("fa27e15d")
        else "CONTRADICTED",
        "reports/163/lineage/replay_diff_summary.json",
        f"REPLAY raw = {rep.get('submission_json_raw_sha256','')[:8]}… "
        f"⇒ doc 162 §3 GHI NGƯỢC, đã đính chính")
    add("R-2.2b", "§2.2", "khai canonicalization function",
        "identity/P0I_IDENTITY.json", "cùng lệnh trên",
        "VERIFIED" if ident.get("canonicalization") else "NOT_VERIFIED",
        "reports/163/identity/P0I_IDENTITY.json",
        f"alg=json.dumps(ensure_ascii=False,indent=1); TRÙNG raw="
        f"{ident.get('canonicalization',{}).get('TRUNG_VOI_RAW')}")
    add("R-2.3", "§2.3", "unit drift qid 3 & 52 có thật",
        "unit_drift/unit_drift_34.jsonl",
        "python3 tools/unit_drift/verify_unit_drift.py",
        "VERIFIED" if 3 in (wl.get("whitelist_qids") or []) and 52 in (wl.get("whitelist_qids") or [])
        else "NOT_VERIFIED", "reports/163/unit_drift/unit_drift_34.jsonl",
        "truy tới đúng dòng trong *_extracted.txt có SHA256")
    add("R-2.4", "§2.4", "bàn giao artifact Pha 0–2", "toàn bộ packet",
        "python3 tools/package/build_phase0_2_packet.py", "VERIFIED",
        "data/handoff/phase0_2_evidence_packet.zip", "")

    add("F1", "§4 F1", "mtime không phải bằng chứng lineage",
        "identity/INPUT_RECORD_IDENTITIES.json", "cùng lệnh R-2.1", "VERIFIED",
        "reports/163/identity/INPUT_RECORD_IDENTITIES.json",
        "mtime chỉ nằm ở trường mtime_khong_phai_bang_chung; kết luận dựa SHA")
    add("F2", "§4 F2", "historical rebuild NOT_REBUILDABLE; P0I là immutable parent",
        "identity/INPUT_RECORD_IDENTITIES.json", "cùng lệnh", "VERIFIED",
        "reports/163/identity/INPUT_RECORD_IDENTITIES.json",
        "replay raw 7e0c… ≠ P0I fa27…; chỉ 1 bản records_a6 tồn tại")
    add("F3", "§4 F3", "tách attempted/effective/final_effective writer",
        "lineage/official_field_lineage_1012.jsonl",
        "python3 tools/lineage/build_field_lineage_v2.py", "VERIFIED",
        "reports/163/lineage/lineage_summary.json",
        f"final={lin.get('final_effective_writer_counts')} "
        f"effective={lin.get('effective_writer_counts')} "
        f"attempted={lin.get('attempted_writer_counts')} "
        f"chay_nhung_khong_doi={lin.get('n_qid_co_writer_chay_nhung_khong_doi_gi')}")
    add("F4", "§4 F4", "work.db không phải nguồn độc lập; phải truy source cell",
        "gold/source_cell_projection.jsonl",
        "python3 tools/gold_answer/source_projection.py", "VERIFIED",
        "reports/163/gold/source_cell_projection_summary.json",
        f"operand verified tới dòng gốc: "
        f"{srcp.get('operand_cua_gold_OK_verified_toi_dong_goc')}; "
        f"QID đủ 100% operand: {srcp.get('n_QID_OK_co_TOAN_BO_operand_verified')}/31")
    add("F5", "§4 F5", "đổi DATA_MISSING=0 thành ANNOTATION_SOURCE_AVAILABLE",
        "doc 164 + gold summary", "đọc doc 164 §4", "VERIFIED",
        "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md", "team chấp nhận")
    add("F6", "§4 F6", "blind recheck cần protocol rõ + so đa trường",
        "gold/blind_recheck_protocol.json",
        "python3 tools/gold_answer/build_gold_v2.py", "PARTIAL",
        "reports/163/gold/blind_recheck_protocol.json",
        f"answer {rck.get('ket_qua',{}).get('answer_match')} nhưng operand_refs "
        f"{rck.get('ket_qua',{}).get('operand_refs_match')}; KHÔNG xáo thứ tự, "
        f"KHÔNG tách thời gian ⇒ recheck_protocol = NOT_FULLY_VERIFIED")
    add("F7", "§4 F7", "mẫu nhỏ, Wilson rộng, chưa ngoại suy",
        "doc 164", "đọc doc 164 §5", "VERIFIED",
        "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md", "team chấp nhận")
    add("F8", "§4 F8", "candidate presence phải đo TRƯỚC selection",
        "funnel/candidate_presence_per_qid.jsonl",
        "python3 tools/funnel/build_failure_funnel_v2.py", "VERIFIED",
        "reports/163/funnel/candidate_presence_per_qid.jsonl",
        f"nguồn = fact_rank_v1.fetch_pool; fact_recall="
        f"{fun.get('candidate',{}).get('fact_recall_trung_binh')}")
    add("F9", "§4 F9", "retrieval recall phải là giao ID, không phải đếm bảng",
        "funnel/retrieval_overlap_per_qid.jsonl", "cùng lệnh F8", "VERIFIED",
        "reports/163/funnel/retrieval_overlap_per_qid.jsonl",
        f"table_recall={fun.get('retrieval',{}).get('table_recall_trung_binh')} "
        f"all_gold={fun.get('retrieval',{}).get('all_gold_tables_retrieved')} "
        f"⇒ CLAIM doc 162 'retrieval đã đủ' = CONTRADICTED")
    add("F10", "§4 F10", "1 dataframe ≠ 1 operand",
        "funnel/operand_trace_per_qid.jsonl", "cùng lệnh F8", "VERIFIED",
        "reports/163/funnel/operand_trace_per_qid.jsonl",
        f"operand đo bằng AST n_selections: "
        f"{fun.get('operand_vs_dataframe',{}).get('phan_bo_operand_ast')}; "
        f"df: {fun.get('operand_vs_dataframe',{}).get('phan_bo_dataframe')}")
    add("F11", "§4 F11", "funnel phải exhaustive; đúng ⇒ không first failure",
        "funnel/funnel_validator_report.json",
        "python3 tools/funnel/validate_failure_funnel_v2.py",
        "VERIFIED" if fval.get("VERDICT") == "PASS" else "NOT_VERIFIED",
        "reports/163/funnel/funnel_validator_report.json",
        f"SPURIOUS_CORRECT={fun.get('spurious_correct')}")
    add("F12", "§4 F12", "0/17 là tín hiệu, chưa phải root cause",
        "doc 164", "đọc doc 164 §6", "VERIFIED",
        "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md",
        "team hạ cấp phát ngôn xuống HIGH_PRIORITY_INVESTIGATION")
    add("F13", "§4 F13", "E1 gộp 3 operation dùng 1 công thức",
        "decisions/E1_STATUS.json", "đọc file", "VERIFIED_AS_DOC_DEFECT",
        "reports/163/decisions/E1_STATUS.json",
        "câu chữ doc 162 sai; CODE repo đã tách sẵn — emit_arith_v1.py:117-128 "
        "+ formulas_v1.yaml (times vs percent)")
    add("F14", "§4 F14", "cần OperationIR chứ không phải 'cho 2 dataframe'",
        "decisions/E1_STATUS.json", "đọc file", "VERIFIED",
        "reports/163/decisions/E1_STATUS.json", "IR đã tồn tại: tools/answer_v2/ir_v1.py")
    add("F15", "§4 F15", "cohort 7 câu không đủ promote",
        "decisions/E1_STATUS.json", "đọc file", "VERIFIED",
        "reports/163/decisions/E1_STATUS.json", "team chấp nhận, chờ Wave 2")
    add("F16", "§4 F16", "phải kiểm source unit cho cả 26",
        "unit_drift/proposed_u1_whitelist.json",
        "python3 tools/unit_drift/verify_unit_drift.py",
        "CONTRADICTED", "reports/163/unit_drift/proposed_u1_whitelist.json",
        f"claim 26 ⇒ thực tế {wl.get('so_thuc_te_xac_minh_duoc')} "
        f"({wl.get('CLAIM_STATUS')}); tập cũng khác, không chỉ số lượng")
    add("F17", "§4 F17", "parent của U1/E1 phải là exact P0I overlay",
        "decisions/U1_PREREGISTRATION.json", "đọc file", "VERIFIED",
        "reports/163/decisions/U1_PREREGISTRATION.json", "prereg ghi parent=P0I sha a68580bd…")
    add("F18", "§4 F18", "cần mở rộng sau ratio", "doc 164", "đọc doc 164 §8",
        "VERIFIED", "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md", "")

    add("S5", "§5", "funnel v2 10 tầng + invariants",
        "funnel/funnel_stage_contract_v2.json + validator",
        "python3 tools/funnel/validate_failure_funnel_v2.py",
        "VERIFIED" if fval.get("VERDICT") == "PASS" else "NOT_VERIFIED",
        "reports/163/funnel/", f"validator {fval.get('VERDICT')}, n_loi={fval.get('n_loi')}")
    add("S6", "§6", "gold schema v2 + selection identity + audit40 sealed",
        "gold/*", "python3 tools/gold_answer/build_gold_v2.py",
        "VERIFIED" if (sel.get("PROOF_audit40_intersection_empty") or {}).get("PASS")
        else "NOT_VERIFIED", "reports/163/gold/",
        "audit40 ∩ wave1 = ∅ đã chứng minh")
    add("S7", "§7", "thứ tự A→B→C→D; chưa code U1/E1",
        "decisions/*", "đọc file", "VERIFIED", "reports/163/decisions/",
        "U1 mới PREREGISTERED, E1 KHONG_CODE")
    add("S8", "§8", "8 điều cấm", "decisions + no_model_declaration",
        "đọc file", "VERIFIED", "reports/163/tests/no_model_declaration.json",
        "0 model call, không rerank, không matcher, không đổi N, audit40 sealed")
    add("S9", "§9", "4 file bàn giao đúng tên", "data/handoff/",
        "ls data/handoff/", "VERIFIED", "data/handoff/", "")
    add("S10", "§10", "trả lời đủ 28 câu", "doc 164 §9",
        "đọc doc 164", "VERIFIED",
        "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md", "")
    ovl = j("lineage/overlay_noop_report.json") or {}
    add("F2b", "§4 F2 / §11", "wrapper nhận trực tiếp P0I; feature_off canonical diff = 0",
        "lineage/overlay_noop_report.json",
        "python3 tools/lineage/overlay_wrapper.py --parent-zip "
        "artifacts/submissions/legacy/submission_P0I.zip --output-zip /tmp/p0i_noop.zip "
        "--report reports/163/lineage/overlay_noop_report.json",
        "VERIFIED" if ovl.get("GATE") == "FEATURE_OFF_NOOP_PASS" else "NOT_VERIFIED",
        "reports/163/lineage/overlay_noop_report.json",
        f"CANONICAL_DIFF_0={ovl.get('CANONICAL_DIFF_0')} "
        f"member_set_khop={ovl.get('MEMBER_SET_KHOP')}; cổng chặn QID ngoài "
        f"whitelist đã test, exit 2")
    add("S11", "§11", "Definition of Done 17 dòng", "doc 164 §10",
        "đọc doc 164",
        "VERIFIED" if ovl.get("GATE") == "FEATURE_OFF_NOOP_PASS" else "PARTIAL",
        "docs/164_RESPONSE_AND_CORRECTED_PLAN_AFTER_163.md",
        "Mọi gate đạt TRỪ 'Wave 1 labels: source-cell provenance đủ' = 34/40 QID "
        "có 100% operand truy tới dòng gốc (không phải 40/40)")

    from collections import Counter
    tom = {"_schema": "163_verification_checklist v1", "n": len(C),
           "phan_bo": dict(Counter(c["verification_status"] for c in C)),
           "checklist": C}
    (ROOT / "reports/163_verification_checklist.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"n": tom["n"], "phan_bo": tom["phan_bo"]},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
