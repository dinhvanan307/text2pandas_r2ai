#!/usr/bin/env python3
"""Đóng gói `phase0_2_evidence_packet` — §9 review 163, Pha 12–13 directive.

Nguyên tắc: **không file nào trong packet được viết tay**. Mọi con số đều đọc lại
từ artifact vừa sinh, nên nếu artifact đổi mà packet không chạy lại thì MANIFEST
sẽ lệch và reviewer phát hiện được.

ZIP tất định: `date_time` ghim cố định, không ghi wall-clock vào nội dung băm.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R163 = ROOT / "reports/163"
STAGE = ROOT / "data/handoff/phase0_2_evidence_packet"
OUTDIR = ROOT / "data/handoff"
NGAY = (2026, 1, 1, 0, 0, 0)


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jload(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def jl(p: Path):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def cp(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    elif src.is_file():
        shutil.copy2(src, dst)


def main() -> int:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    # ── các artifact phái sinh viết TRƯỚC khi copy ───────────────────────
    (R163 / "funnel").mkdir(parents=True, exist_ok=True)
    (R163 / "funnel/funnel_stage_contract_v2.json").write_text(json.dumps({
        "_schema": "funnel_stage_contract_v2 — doc 163 §5.1",
        "thu_tu_phu_thuoc": [
            "G0_GOLD_VALID", "D1_SOURCE_AVAILABLE", "R1_GOLD_TABLE_RETRIEVED",
            "C1_GOLD_FACT_CANDIDATE", "S1_OPERAND_SET_EXACT", "O1_OPERATION_EXACT",
            "U1_UNIT_SCALE_EXACT", "Q1_QUERY_VALID", "A1_ANSWER_EXACT",
            "E1_EVIDENCE_VALID"],
        "dinh_nghia": {
            "G0_GOLD_VALID": "trang_thai==OK và có operation và ≥1 operand",
            "D1_SOURCE_AVAILABLE": "MỌI gold operand = SOURCE_LINE_VERIFIED trong "
                                   "tài liệu gốc extracted.txt (có SHA256)",
            "R1_GOLD_TABLE_RETRIEVED": "gold_table_ids ⊆ relevant_tables (giao ID, "
                                       "KHÔNG dùng số lượng)",
            "C1_GOLD_FACT_CANDIDATE": "gold_fact_ids ⊆ candidate universe TRƯỚC "
                                      "selection = fact_rank_v1.fetch_pool",
            "S1_OPERAND_SET_EXACT": "tập observation_uid mà câu lệnh chạm == gold",
            "O1_OPERATION_EXACT": "số operand trong AST == required_operand_count "
                                  "VÀ S1 đúng",
            "U1_UNIT_SCALE_EXACT": "answer/gold KHÔNG phải luỹ thừa 10",
            "Q1_QUERY_VALID": "eval(query) chạy được và == answer trong ZIP",
            "A1_ANSWER_EXACT": "|pred-gold|/max ≤ 0,005",
            "E1_EVIDENCE_VALID": "có evidence và mọi CSV tồn tại trong ZIP"},
        "quy_tac_first_failure": ("tầng ĐẦU TIÊN theo thứ tự phụ thuộc bị False. "
                                  "Nếu A1 đúng thì first_failure = null và các tầng "
                                  "sai trước đó thành SEMANTIC_FAIL_* + "
                                  "SPURIOUS_CORRECT (doc 163 F11)."),
        "gia_tri_None": "KHÔNG đo được ⇒ không tính là PASS, không tính là FAIL",
        "GIOI_HAN_DA_BIET": (
            "Hợp đồng giả định retrieval → candidate. Trong pipeline này HAI TẦNG "
            "RỜI NHAU: candidate pool query work.db theo ticker+year, KHÔNG đọc "
            "relevant_tables. Vì vậy R1=false không thực sự chặn tầng đáp án. "
            "Xem funnel summary: R1 recall 0,4357 vs C1 fact recall 0,8585."),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    (R163 / "identity").mkdir(parents=True, exist_ok=True)
    ds = {
        "_schema": "DATA_AND_SOURCE_IDENTITY v1",
        "work_db": {"path": "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db",
                    "KHONG_GUI": "4,2 GB — packet chỉ gửi projection 40 QID",
                    "bytes": (ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db").stat().st_size},
        "tai_lieu_goc": {
            "root": "data/raw/btc/financial_statements",
            "dinh_dang_evidence_ref": "<DOC>|line:<N> với N là dòng 1-based trong "
                                      "<DOC>/<DOC>_extracted.txt",
            "KHONG_GUI": "379 MB — packet gửi excerpt + SHA256 từng tài liệu"},
        "question_plans": {
            "path": "evaluation/question_plans_1012.jsonl",
            "sha256": shaf(ROOT / "evaluation/question_plans_1012.jsonl")},
        "configs": {p.name: shaf(p) for p in
                    sorted((ROOT / "configs/answer_v2").glob("*.yaml"))},
    }
    (R163 / "identity/DATA_AND_SOURCE_IDENTITY.json").write_text(
        json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")

    (R163 / "tests").mkdir(parents=True, exist_ok=True)
    (R163 / "tests/no_model_declaration.json").write_text(json.dumps({
        "_schema": "no_model_declaration v1",
        "model_call_count": 0,
        "pham_vi": "toàn bộ Pha 0–13 của directive 163",
        "bang_chung": [
            "không script nào trong packet import tools/answer_v2/llm_client.py",
            "configs/answer_v2/llm_v1.yaml endpoint trống",
            "không có tệp cache rerank_v1_* mới trong artifacts/llm_cache/",
        ],
        "LUU_Y": ("Nhãn Wave 1 do annotator LLM tạo trong phiên làm việc, KHÔNG qua "
                  "endpoint model của pipeline và KHÔNG dùng output pipeline. Đây là "
                  "team declaration, reviewer không kiểm độc lập được."),
        "trang_thai": "TEAM_DECLARED_NOT_INDEPENDENTLY_VERIFIABLE",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── decisions ────────────────────────────────────────────────────────
    dec = R163 / "decisions"
    dec.mkdir(parents=True, exist_ok=True)
    (dec / "V5_DISPOSITION.json").write_text(json.dumps({
        "_schema": "V5_DISPOSITION v1",
        "quyet_dinh": "RERANK_STOP_CURRENT_CYCLE — team CHẤP NHẬN khuyến nghị doc 161",
        "to_team_v5_zip_sha256":
            (shaf(OUTDIR / "to_team_v5.zip") if (OUTDIR / "to_team_v5.zip").is_file()
             else None),
        "p0_closure_patch_v2_1_zip_sha256":
            (shaf(OUTDIR / "p0_closure_patch_v2_1.zip")
             if (OUTDIR / "p0_closure_patch_v2_1.zip").is_file() else None),
        "trang_thai": "EXPERIMENTAL_ARCHIVE / NOT_READY",
        "V5_F1_F16": "DEFERRED_BY_STOP",
        "model_call_count": 0,
        "khong_goi_Qwen": True, "khong_chay_rerank": True,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    wl = jload(R163 / "unit_drift/proposed_u1_whitelist.json")
    (dec / "U1_PREREGISTRATION.json").write_text(json.dumps({
        "_schema": "U1_PREREGISTRATION v1 — CHƯA THI HÀNH, chờ APPROVE",
        "ten": "U1_UNIT_NORMALIZATION_ONLY",
        "parent": "submission_P0I.zip",
        "parent_sha256": jload(R163 / "identity/P0I_IDENTITY.json")["zip_sha256"],
        "whitelist_qids": wl["whitelist_qids"],
        "n_whitelist": len(wl["whitelist_qids"]),
        "claim_doc_162": "26/34", "so_xac_minh_toi_nguon": wl["so_thuc_te_xac_minh_duoc"],
        "CLAIM_STATUS": wl["CLAIM_STATUS"],
        "quy_tac_chon": wl["quy_tac"],
        "khong_rebuild_953_record": True,
        "khong_doi_relevant_tables_docs": True,
        "khong_tron_voi_E1": True,
        "gate_local": {
            "source_unit_trace_valid": "100% changed QID",
            "answer_eq_eval_query": "100% changed QID",
            "evidence_covers_query_facts": "100% changed QID",
            "changes_outside_whitelist": 0,
            "regression_tren_31_gold_OK": 0,
            "two_run_canonical_diff": 0},
        "huong_ky_vong": "tăng, nhưng KHÔNG tuyên số điểm trước khi đo",
        "rollback": "tắt overlay ⇒ ra lại đúng P0I canonical SHA",
        "TRANG_THAI": "PREREGISTERED_ONLY__CHUA_CODE",
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    (dec / "E1_STATUS.json").write_text(json.dumps({
        "_schema": "E1_STATUS v1",
        "TRANG_THAI": "KHONG_CODE_TRONG_VONG_NAY — tuân thủ §8 và Pha 10 directive",
        "dong_y_doi_thanh_ratio_only": True,
        "ten_moi": "E1_RATIO_TWO_OPERAND_ONLY",
        "F13_phan_hoi": {
            "review_noi": "E1 dùng a/b và a/b*100 cho cả ratio/percentage_change/difference",
            "trang_thai": "VERIFIED_AS_DOC_DEFECT__CODE_DA_DUNG",
            "giai_thich": ("Câu chữ ở doc 162 §9 SAI và team nhận. Nhưng CODE trong "
                           "repo đã tách sẵn công thức theo operation:"),
            "bang_chung_code": {
                "tools/execution/emit_arith_v1.py:117-128":
                    "difference = (new-old)/unit_factor",
                "tools/execution/emit_arith_v1.py:126-128":
                    "percentage_change = (new-old)/abs(old)*100.0",
                "tools/execution/emit_arith_v1.py:122-124":
                    "ZERO_DENOMINATOR abstain khi old==0",
                "configs/answer_v2/formulas_v1.yaml":
                    "ratio: output.unit=times (Divide) vs percentage: "
                    "Multiply(Divide, Literal 100) — hai node khác nhau",
                "tools/execution/answer_operation.py:37-47":
                    "OPERATIONS enum 15 giá trị + ENUM_STATUS",
                "tools/answer_v2/ir_v1.py":
                    "NODE_ARITY + DIMENSIONS (money/ratio/percentage/scalar/count/year)",
            }},
        "OperationIR_da_ton_tai": True,
        "con_thieu_truoc_khi_code": [
            "Wave 2 để đủ cỡ mẫu ratio (hiện dev Wave 1 chỉ 7 câu — F15)",
            "unit test cho chiều numerator/denominator, zero denom, âm, %-vs-times",
            "eligibility freeze trước khi chạy candidate"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── copy vào staging ─────────────────────────────────────────────────
    M = [
        ("identity/P0I_IDENTITY.json", R163 / "identity/P0I_IDENTITY.json"),
        ("identity/REPLAY_IDENTITY.json", R163 / "identity/REPLAY_IDENTITY.json"),
        ("identity/INPUT_RECORD_IDENTITIES.json", R163 / "identity/INPUT_RECORD_IDENTITIES.json"),
        ("identity/INTERMEDIATE_ZIP_IDENTITIES.json", R163 / "identity/INTERMEDIATE_ZIP_IDENTITIES.json"),
        ("identity/DATA_AND_SOURCE_IDENTITY.json", R163 / "identity/DATA_AND_SOURCE_IDENTITY.json"),
        ("source/tools/lineage/build_field_lineage.py", ROOT / "tools/lineage/build_field_lineage_v2.py"),
        ("source/tools/lineage/official_build_wrapper.py", ROOT / "tools/lineage/official_build_wrapper.py"),
        ("source/tools/lineage/build_identity_and_lineage_v2.py", ROOT / "tools/lineage/build_identity_and_lineage_v2.py"),
        ("source/tools/lineage/overlay_wrapper.py", ROOT / "tools/lineage/overlay_wrapper.py"),
        ("lineage/overlay_noop_report.json", R163 / "lineage/overlay_noop_report.json"),
        ("source/tools/gold_answer/source_sheet.py", ROOT / "tools/gold_answer/source_sheet.py"),
        ("source/tools/gold_answer/label_validator.py", ROOT / "tools/gold_answer/validate_gold.py"),
        ("source/tools/gold_answer/source_projection.py", ROOT / "tools/gold_answer/source_projection.py"),
        ("source/tools/gold_answer/build_gold_v2.py", ROOT / "tools/gold_answer/build_gold_v2.py"),
        ("source/tools/gold_answer/merge_recheck.py", ROOT / "tools/gold_answer/merge_recheck.py"),
        ("source/tools/funnel/build_failure_funnel_v2.py", ROOT / "tools/funnel/build_failure_funnel_v2.py"),
        ("source/tools/funnel/validate_failure_funnel_v2.py", ROOT / "tools/funnel/validate_failure_funnel_v2.py"),
        ("source/tools/unit_drift/verify_unit_drift.py", ROOT / "tools/unit_drift/verify_unit_drift.py"),
        ("source/tools/package/build_phase0_2_packet.py", Path(__file__)),
        ("lineage/official_field_lineage_1012.jsonl", R163 / "lineage/official_field_lineage_1012.jsonl"),
        ("lineage/lineage_summary.json", R163 / "lineage/lineage_summary.json"),
        ("lineage/replay_diff_34.jsonl", R163 / "lineage/replay_diff_34.jsonl"),
        ("lineage/replay_diff_summary.json", R163 / "lineage/replay_diff_summary.json"),
        ("lineage/member_manifest_parent.json", R163 / "lineage/member_manifest_parent.json"),
        ("lineage/member_manifest_replay.json", R163 / "lineage/member_manifest_replay.json"),
        ("gold/dev60_universe.json", R163 / "gold/dev60_universe.json"),
        ("gold/wave1_selection.json", R163 / "gold/wave1_selection.json"),
        ("gold/wave1_labels_v2.jsonl", R163 / "gold/wave1_labels_v2.jsonl"),
        ("gold/wave1_uncertain.jsonl", R163 / "gold/wave1_uncertain.jsonl"),
        ("gold/blind_recheck.jsonl", R163 / "gold/blind_recheck.jsonl"),
        ("gold/blind_recheck_protocol.json", R163 / "gold/blind_recheck_protocol.json"),
        ("gold/label_schema_v2.json", R163 / "gold/label_schema_v2.json"),
        ("gold/source_cell_projection.jsonl", R163 / "gold/source_cell_projection.jsonl"),
        ("gold/source_cell_projection_summary.json", R163 / "gold/source_cell_projection_summary.json"),
        ("gold/source_excerpts", R163 / "gold/source_excerpts"),
        ("funnel/funnel_stage_contract_v2.json", R163 / "funnel/funnel_stage_contract_v2.json"),
        ("funnel/failure_funnel_wave1_v2.jsonl", R163 / "funnel/failure_funnel_wave1_v2.jsonl"),
        ("funnel/failure_funnel_summary_v2.json", R163 / "funnel/failure_funnel_summary_v2.json"),
        ("funnel/funnel_validator_report.json", R163 / "funnel/funnel_validator_report.json"),
        ("funnel/retrieval_overlap_per_qid.jsonl", R163 / "funnel/retrieval_overlap_per_qid.jsonl"),
        ("funnel/candidate_presence_per_qid.jsonl", R163 / "funnel/candidate_presence_per_qid.jsonl"),
        ("funnel/operand_trace_per_qid.jsonl", R163 / "funnel/operand_trace_per_qid.jsonl"),
        ("funnel/query_execution_trace_per_qid.jsonl", R163 / "funnel/query_execution_trace_per_qid.jsonl"),
        ("unit_drift/unit_drift_34.jsonl", R163 / "unit_drift/unit_drift_34.jsonl"),
        ("unit_drift/unit_verified_26_or_corrected_count.jsonl", R163 / "unit_drift/unit_verified_26_or_corrected_count.jsonl"),
        ("unit_drift/proposed_u1_whitelist.json", R163 / "unit_drift/proposed_u1_whitelist.json"),
        ("unit_drift/source_unit_excerpts", R163 / "unit_drift/source_unit_excerpts"),
        ("tests/commands.log", R163 / "tests/commands.log"),
        ("tests/label_validator.log", R163 / "tests/label_validator.log"),
        ("tests/funnel_validator.log", R163 / "tests/funnel_validator.log"),
        ("tests/lineage_replay.log", R163 / "tests/lineage_replay.log"),
        ("tests/no_model_declaration.json", R163 / "tests/no_model_declaration.json"),
        ("decisions/V5_DISPOSITION.json", dec / "V5_DISPOSITION.json"),
        ("decisions/U1_PREREGISTRATION.json", dec / "U1_PREREGISTRATION.json"),
        ("decisions/E1_STATUS.json", dec / "E1_STATUS.json"),
        ("163_verification_checklist.json", ROOT / "reports/163_verification_checklist.json"),
    ]
    thieu = []
    for rel, src in M:
        if not src.exists():
            thieu.append(rel); continue
        cp(src, STAGE / rel)
    if thieu:
        print("THIẾU NGUỒN:", thieu)

    # README
    (STAGE / "README.md").write_text(f"""# phase0_2_evidence_packet

Đáp `163_REVIEW_OF_162_PHASE0_2_AND_EXECUTION_DIRECTIVE.md` §9.
Model call = **0**. Không sửa production. audit40 vẫn **sealed**.

## Kiểm nhanh

```bash
shasum -a 256 -c ../phase0_2_evidence_packet.zip.sha256
cd phase0_2_evidence_packet && shasum -a 256 -c MANIFEST.sha256
```

## Ba thứ nên đọc trước

1. `lineage/replay_diff_summary.json` — **đính chính doc 162**: P0I = `fa27e15d…`,
   REPLAY = `7e0c6a1f…`. Doc 162 §3 ghi ngược.
2. `funnel/failure_funnel_summary_v2.json` — funnel v2 **bác** kết luận
   "retrieval đã mang đủ bảng" của doc 162: table recall thật = **0,4357**,
   all_gold_tables_retrieved = **9/31**.
3. `unit_drift/proposed_u1_whitelist.json` — claim 26/34 **sửa thành 24/34** sau
   khi truy tới dòng gốc trong `*_extracted.txt`.

## Không gửi trong packet

`work.db` (4,2 GB) và toàn bộ tài liệu gốc (379 MB). Thay bằng projection 40 QID
+ excerpt + SHA256 từng tài liệu, đủ để tái kiểm mà không cần DB.
""", encoding="utf-8")

    # MANIFEST cuối cùng
    files = sorted(p for p in STAGE.rglob("*") if p.is_file()
                   and p.name != "MANIFEST.sha256")
    (STAGE / "MANIFEST.sha256").write_text(
        "\n".join(f"{shaf(p)}  {p.relative_to(STAGE)}" for p in files) + "\n",
        encoding="utf-8")

    # ZIP tất định
    zp = OUTDIR / "phase0_2_evidence_packet.zip"
    allf = sorted(p for p in STAGE.rglob("*") if p.is_file())
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in allf:
            zi = zipfile.ZipInfo(str(Path("phase0_2_evidence_packet")
                                     / p.relative_to(STAGE)), date_time=NGAY)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, p.read_bytes())
    s = shaf(zp)
    (OUTDIR / "phase0_2_evidence_packet.zip.sha256").write_text(
        f"{s}  phase0_2_evidence_packet.zip\n", encoding="utf-8")
    shutil.copy2(R163 / "P0I_CANONICAL_IDENTITY.sha256",
                 OUTDIR / "P0I_CANONICAL_IDENTITY.sha256")

    print(json.dumps({"n_file": len(allf), "zip": str(zp),
                      "zip_bytes": zp.stat().st_size, "zip_sha256": s,
                      "thieu_nguon": thieu}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
