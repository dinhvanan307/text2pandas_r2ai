#!/usr/bin/env python3
"""Sinh `p0_rr_prep_v2/` — 12 file cấu hình + FREEZE_MANIFEST. Doc 159 §6.7–§6.10.

Mọi file sinh TỪ code thật (prompt template, schema, K đo được), không chép tay —
nhờ vậy `prompt_template_sha` trong config **bằng đúng** băm của `PROMPT` đang
chạy, và verify_patch bắt được ngay nếu ai sửa một bên mà quên bên kia.

Chạy:  python3 tools/answer_v2/build_rr_prep_v2.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

import cell_reranker as CR  # noqa: E402


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=ROOT / "reports/answer_v2/p0_rr_prep_v2")
    ap.add_argument("--preflight", type=Path,
                    default=ROOT / "reports/answer_v2/r0_preflight")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    rk = json.loads((a.preflight / "recall_at_k.json").read_text(encoding="utf-8"))
    el = json.loads((a.preflight / "eligibility_report_66.json").read_text(encoding="utf-8"))

    def ghi(ten: str, d) -> None:
        p = a.out / ten
        if isinstance(d, str):
            p.write_text(d, encoding="utf-8")
        else:
            p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

    # 1 · prompt (đúng template đang chạy)
    ghi("prompt_v2.txt", CR.PROMPT)

    # 2 · output schema
    ghi("output_schema_v2.json", {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "cell_reranker output v2",
        "type": "object",
        "required": ["selected_candidate_id", "confidence", "reason_codes"],
        "additionalProperties": False,
        "properties": {
            "selected_candidate_id": {
                "type": ["string", "null"],
                "description": ("stable candidate ID trong whitelist của LƯỢT GỌI "
                                "đó; null = abstain, KHÔNG ô nào khớp"),
            },
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "reason_codes": {"type": "array", "minItems": 0,
                             "items": {"enum": list(CR.REASON_CODES)}},
        },
        "schema_sha": CR.schema_hash(),
        "vi_sao_khong_con_parse_so_nguyen": (
            "Chỉ số là VỊ TRÍ trình bày ⇒ cùng một ô ở hai thứ tự mang hai tên "
            "khác nhau ⇒ không đối chiếu A/B/C và không cache ổn định được. "
            "Ngoài ra regex bắt số đầu tiên có thể bắt nhầm năm trong câu."),
    })

    # 3 · eligibility v2
    ghi("eligibility_v2.json", {
        "version": "v2",
        "dinh_nghia_SUPPORTED_SLOT": [
            "OperandKey/FactRef hợp lệ",
            "semantic operation của slot được hỗ trợ",
            "candidate pool qua hard filter đúng entity/period/scope/type",
            "pool có ít nhất HAI candidate để lựa chọn",
        ],
        "answer_route": "trường BÁO CÁO, KHÔNG dùng làm điều kiện loại",
        "ambiguity_trigger": [
            "SCORE_MARGIN_LE_0.5 — hai ứng viên đầu sát điểm",
            "TOP3_METRIC_LABEL_DIFFERS — ba ứng viên đầu khác nhãn chỉ tiêu",
        ],
        "do_duoc_tren_66": {
            "total": el["total"], "supported_slot": el["supported_slot"],
            "eligible": el["eligible"], "ambiguous": el["ambiguous"],
            "attempted_by_policy": el["attempted_by_policy"],
            "slot_theo_answer_route": el["slot_theo_answer_route"],
            "n_qid_route_R2": el["n_qid_route_R2"],
        },
    })

    # 4 · K rule — KHAI TRẦN, không hạ ngưỡng
    chosen = rk["chosen_K"]
    ghi("k_rule_v2.json", {
        "version": "v2",
        "nguong_recall": rk["nguong"],
        "recall_do_duoc": {f"K={k}": rk[f"recall_at_{k}"]["ty_le"]
                           for k in (4, 8, 12, 16)},
        "chosen_K_theo_luat_goc": chosen,
        "verdict_luat_goc": rk["verdict"],
        "QUYET_DINH": "K=12 · PREREG_V2_CEILING_DECLARED",
        "vi_sao": (
            "KHÔNG K nào đạt 0,90 — trần là 0,8485 ở cả K=12 và K=16. Theo §6.9 "
            "có hai đường: STOP, hoặc prereg v2 khai rõ trần + rủi ro + lý do "
            "chọn K. Chọn đường thứ hai và chọn K=12 vì K=16 KHÔNG thêm recall "
            "(56/66 ở cả hai) mà chỉ thêm token và thêm nhiễu vị trí."),
        "TRAN_CUA_THI_NGHIEM": {
            "gold_in_top12": rk["recall_at_12"]["n"],
            "tren": rk["recall_at_12"]["tren"],
            "y_nghia": ("Reranker HOÀN HẢO cũng chỉ đạt 56/66. Gate "
                        "policy_correct ≥37/66 vẫn đạt được, nhưng mọi phát ngôn "
                        "phải nói kèm trần 56, không được ngụ ý trần 66."),
        },
        "RUI_RO": [
            "10/66 slot có gold ngoài top-12 ⇒ model không thể chọn đúng dù giỏi",
            "trần 0,8485 làm hẹp biên phát hiện gain: khoảng giữa 29 và 56",
            "nếu gain đo được nhỏ, KHÔNG kết luận 'LLM vô dụng' — có thể do trần",
        ],
        "KHONG_DUOC_LAM": "hạ ngưỡng 0,90 để gate xanh; đổi ngưỡng phải tạo version mới TRƯỚC model call",
        "missing_gold_taxonomy": rk["missing_gold_taxonomy"],
    })

    # 5 · gates — TÁCH HAI MẪU SỐ
    ghi("train_fit_gates_v2.json", {
        "version": "v2",
        "A_MODEL_CAPABILITY_66": {
            "mau_so": "gold_in_topK",
            "do": ["valid_schema/model_attempted", "correct/gold_in_topK",
                   "invalid_schema", "id_not_in_whitelist", "endpoint_error",
                   "timeout", "abstain"],
            "gate": {"valid_schema_rate_min": 0.90,
                     "ghi_chu": "áp trên mẫu số model_attempted của A"},
        },
        "B_PRODUCTION_POLICY_66": {
            "mau_so": 66,
            "baseline_correct": "29/66",
            "gate": {"policy_correct_min": 37, "regressed_max": 2},
            "ghi_chu": ("chỉ B mới áp gate 37/66 và regressed≤2. Slot không gọi "
                        "model dùng deterministic fallback."),
        },
        "CAM": ("Không được vừa 'chỉ gọi ambiguous' vừa đòi valid_schema≥60/66 "
                "khi attempted < 60. Mọi tỉ lệ phải ghi kèm mẫu số."),
        "G_LLM_6_thien_vi_vi_tri": {
            "do": "tỉ lệ hai cách trình bày chọn CÙNG một stable_candidate_id",
            "nguong": 0.80,
            "khi_khong_exercised": "NOT_MEASURED — KHÔNG được trả PASS",
        },
    })

    # 6 · cache key
    ghi("cache_key_v2.json", {
        "version": "v2",
        "thanh_phan": [
            "exact AG1B parent SHA", "candidate-affecting source SHA",
            "router/ontology/scorer config SHA", "prompt-template SHA",
            "rendered-prompt SHA", "output-schema SHA", "eligibility-rule SHA",
            "K-rule SHA", "model/revision/tokenizer/quantization identity",
            "decoding config", "stable candidate-content SHA",
            "exact candidate-order SHA", "presentation A/B/C",
        ],
        "prompt_template_sha": sha_text(CR.PROMPT),
        "output_schema_sha": CR.schema_hash(),
        "hien_thuc": ("llm_client.LLMIdentity.key() băm model/revision/quant/"
                      "runtime/temperature/top_p/seed/max_tokens/"
                      "prompt_template_hash; rendered-prompt SHA là khoá dòng "
                      "cache. Đổi BẤT KỲ trường nào ⇒ cache miss ⇒ gọi lại."),
        "ly_do": ("Hai cấu hình khác nhau KHÔNG được dùng chung kết quả — nếu "
                  "dùng chung thì mọi so sánh A/B mất nghĩa."),
    })

    # 7 · fallback
    ghi("fallback_v2.json", {
        "version": "v2",
        "quy_tac": "MỌI trường hợp hỏng → giữ nguyên thứ tự scorer tất định (AG1B S5)",
        "ma_loi": ["EMPTY_RESPONSE", "NOT_JSON", "INVALID_JSON", "NOT_JSON_OBJECT",
                   "MISSING_FIELD_selected_candidate_id", "BAD_TYPE_selected_candidate_id",
                   "ID_NOT_IN_WHITELIST", "BAD_CONFIDENCE", "BAD_REASON_CODES",
                   "REASON_CODE_NOT_IN_ENUM", "ENDPOINT_ERROR", "ABSTAIN",
                   "IT_HON_2_UNG_VIEN"],
        "hop_dong": ("rerank trả về CÙNG phần tử, chỉ đổi thứ tự — không thêm, "
                     "không bớt. Nhờ vậy binder/evidence/renderer/verifier không "
                     "cần biết có LLM."),
        "abstain": "selected_candidate_id=null là schema HỢP LỆ, đếm riêng, vẫn fallback",
    })

    # 8 · fresh audit protocol
    ghi("fresh_audit_protocol_v2.json", {
        "version": "v2",
        "muc_dich": ("gold-45 vừa là tập chỉnh S5 vừa là tập đo LLM ⇒ nhánh A "
                     "TRAIN_FIT-lạc quan. Fresh audit là tập ĐỘC LẬP để kiểm."),
        "thu_tu_bat_buoc": [
            "1. sampler chạy, sinh danh sách QID/slot",
            "2. SEAL danh sách (ghi SHA) TRƯỚC khi nhìn bất kỳ prediction nào",
            "3. gán nhãn theo label_schema_v1, KHÔNG xem output của candidate",
            "4. chỉ sau khi seal + label xong mới được chạy model trên tập này",
        ],
        "cam": ["dùng Qwen prefill nhãn cho sealed audit",
                "gán nhãn sau khi đã xem prediction",
                "mở seal rồi thêm/bớt slot"],
        "trang_thai": "CHUA_CHAY — sampler và schema đã sẵn, chưa seal",
    })

    # 9 · sampling
    ghi("sampling_v1.json", {
        "version": "v1",
        "khung": "phân tầng theo answer_route × ambiguous × statement_type",
        "n_muc_tieu": 40,
        "uu_tien": "lookup — lớp chiếm 56,5% đề thi và hiện KHÔNG có gold nào",
        "seed": 20260823,
        "quy_tac_tat_dinh": "sort theo (qid, slot_id) rồi lấy mẫu theo seed cố định",
        "ghi_chu": ("Đây là khoản đầu tư có đòn bẩy cao nhất còn lại: nó mở khoá "
                    "phép đo cho hơn nửa đề thi và dùng lại được cho mọi vòng sau."),
    })

    # 10 · label schema
    ghi("label_schema_v1.json", {
        "version": "v1",
        "fields": {
            "qid": "int", "slot_id": "str",
            "gold_candidate_id": "str|null — null nghĩa là KHÔNG ô nào đúng",
            "gold_evidence_ref": "str", "gold_row_path": "str",
            "gold_col_label": "str",
            "nguoi_gan": "str", "thoi_diem": "ISO8601",
            "do_kho": "DE|VUA|KHO",
            "ghi_chu": "str — bắt buộc khi gold_candidate_id=null",
        },
        "quy_tac": ["không xem prediction trước khi gán",
                    "null là nhãn HỢP LỆ, không phải bỏ trống",
                    "mỗi nhãn phải truy được về một ô cụ thể trong CSV"],
    })

    # 11 · model identity — CÒN UNKNOWN, khai thẳng
    ghi("model_identity_v2.json", {
        "version": "v2",
        "model_repository": "UNKNOWN",
        "exact_revision_commit": "UNKNOWN",
        "weight_or_served_model_identity": "UNKNOWN",
        "tokenizer_revision": "UNKNOWN",
        "quantization_dtype": "UNKNOWN",
        "runtime": "UNKNOWN",
        "decoding": {"temperature": 0.0, "top_p": 1.0, "seed": 0, "max_tokens": 64},
        "TRANG_THAI": "BLOCKER_TRUOC_REQUEST_DAU_TIEN",
        "ghi_chu": ("Doc 159 yêu cầu KHÔNG còn UNKNOWN trước request đầu tiên. "
                    "Các trường trên chỉ điền được sau khi dựng endpoint thật "
                    "trên máy có GPU — máy build không có. Đây là mục CHƯA đóng "
                    "được, khai thẳng thay vì điền giá trị giả."),
        "cach_dien": ["ollama show <model> --modelfile → digest",
                      "hoặc HuggingFace commit hash của repo model"],
    })

    # 12 · FREEZE_MANIFEST — băm chính 11 file trên
    files = sorted(p for p in a.out.iterdir()
                   if p.is_file() and p.name != "FREEZE_MANIFEST.json")
    ghi("FREEZE_MANIFEST.json", {
        "_schema": "FREEZE_MANIFEST v2",
        "n_file": len(files),
        "files": {p.name: sha_file(p) for p in files},
        "prompt_template_sha": sha_text(CR.PROMPT),
        "output_schema_sha": CR.schema_hash(),
        "dong_bang_luc": "trước mọi model call",
        "quy_tac": ("Đổi bất kỳ file nào trong đây SAU khi đã gọi model ⇒ kết quả "
                    "cũ KHÔNG còn so sánh được, phải tạo version mới."),
        "model_call_count_tai_thoi_diem_freeze": 0,
    })

    print(f"đã sinh {len(files) + 1} file → {a.out}")
    for p in files:
        print(f"  {p.name}")
    print(f"\nK rule: chosen={chosen} · quyết định K=12 kèm khai trần "
          f"{rk['recall_at_12']['n']}/{rk['recall_at_12']['tren']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
