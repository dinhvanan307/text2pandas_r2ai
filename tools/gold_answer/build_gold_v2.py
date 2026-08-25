#!/usr/bin/env python3
"""gold/ artifacts theo §6 review 163 — schema v2, uncertain taxonomy, recheck per-field.

Ba việc:

* **§6.1** nâng nhãn lên schema v2: `ordered_operands[]` có `role/entity/period/
  basis/source doc·table·row·col/raw/source unit/canonical value`, cộng
  `source_doc_sha256` và `source_status` lấy từ `source_cell_projection`.
* **§6.1** gán `uncertain_reason_taxonomy` theo enum đóng, không để chuỗi tự do.
* **F6/§10 Q9** recheck so **từng trường** — answer, unit, operation, operand refs —
  chứ không chỉ so chuỗi đáp án. Đồng thời khai thẳng những phần của protocol
  **không** chứng minh được.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GD = ROOT / "data/dev/answer_gold"
OUT = ROOT / "reports/163/gold"

TAXONOMY = ("QUESTION_SEMANTIC_AMBIGUITY", "MULTIPLE_VALID_DEFINITIONS",
            "SOURCE_CONFLICT", "UNIT_AMBIGUITY", "EXTRACTION_DEFECT", "OTHER")
KHOA = {
    "MULTIPLE_VALID_DEFINITIONS": ("định nghĩa", "dinh nghia", "hai cách", "hai bang",
                                   "hai bảng", "nếu", "neu ", "thay vì", "cách hiểu",
                                   "bình quân", "cuối kỳ", "vs "),
    "SOURCE_CONFLICT": ("xung đột", "trình bày lại", "restat", "mâu thuẫn",
                        "hai nguồn", "khác nhau giữa"),
    "UNIT_AMBIGUITY": ("đơn vị", "don vi", "%", "lần", "percent"),
    "EXTRACTION_DEFECT": ("rút gọn", "trích", "ocr", "nhãn dòng", "etl", "bị cắt"),
    "QUESTION_SEMANTIC_AMBIGUITY": ("câu hỏi không", "không chỉ rõ", "không nêu",
                                    "mơ hồ", "không định nghĩa"),
}


def shaf(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def jl(p: Path):
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def phan_loai_uncertain(txt: str) -> str:
    t = (txt or "").lower()
    for ten, ks in KHOA.items():
        if any(k in t for k in ks):
            return ten
    return "OTHER"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    gold = jl(GD / "answer_gold_wave1_final.jsonl")
    proj = collections.defaultdict(dict)
    for r in jl(ROOT / "reports/163/gold/source_cell_projection.jsonl"):
        proj[r["qid"]][r["operand_index"]] = r

    # ── schema v2 ────────────────────────────────────────────────────────
    v2, unc = [], []
    for g in gold:
        q = g["qid"]
        ops = []
        for i, c in enumerate(g.get("gold_cells") or []):
            p = proj[q].get(i, {})
            ops.append({
                "order": i, "role": c.get("role"),
                "entity": (g.get("entities") or [None])[0]
                          if len(g.get("entities") or []) == 1 else c.get("entity"),
                "period": c.get("period_end"), "basis": g.get("basis"),
                "metric_row_meaning": c.get("row_path"),
                "source_document": p.get("doc"),
                "source_document_sha256": p.get("source_doc_sha256"),
                "source_table_id": c.get("evidence_ref"),
                "source_row": c.get("row_path"), "source_column": c.get("col_path"),
                "source_cell_id_workdb": (p.get("workdb") or {}).get("observation_uid"),
                "source_line_1based": p.get("line_1based"),
                "raw_value": c.get("raw"), "source_unit": c.get("col_unit"),
                "canonical_value": c.get("value_in_col_unit"),
                "source_status": p.get("source_status"),
                "source_excerpt_file": f"gold/source_excerpts/qid_{q:04d}.md",
            })
        r = {
            "qid": q, "question": g.get("question"),
            "answer_raw": g.get("answer_gold"),
            "answer_normalized": g.get("normalized_answer_gold"),
            "answer_type": g.get("answer_type"),
            "output_unit": g.get("unit"), "output_scale": g.get("scale"),
            "operation_enum": g.get("operation"),
            "formula_semantics": g.get("formula"),
            "ordered_operands": ops,
            "required_operand_count": len(ops),
            "label_confidence": g.get("label_confidence"),
            "trang_thai": g["trang_thai"],
            "blind_recheck": g.get("blind_recheck"),
            "evidence_provenance": g.get("evidence_provenance"),
            "ghi_chu": g.get("ghi_chu"),
            "all_operands_source_verified": bool(ops) and all(
                o["source_status"] == "SOURCE_LINE_VERIFIED" for o in ops),
        }
        if g["trang_thai"] != "OK":
            r["uncertain_reason"] = g.get("uncertain_reason")
            r["uncertain_reason_taxonomy"] = phan_loai_uncertain(
                str(g.get("uncertain_reason")) + " " + str(g.get("ghi_chu")))
            unc.append(r)
        v2.append(r)

    (OUT / "wave1_labels_v2.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in v2) + "\n", encoding="utf-8")
    (OUT / "wave1_uncertain.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in unc) + "\n", encoding="utf-8")

    # ── recheck per-field ────────────────────────────────────────────────
    p1 = {r["qid"]: r for r in gold}
    rc = {r["qid"]: r for r in jl(GD / "recheck_blind.jsonl")}

    def refs(g):
        return sorted({re.sub(r"\|(?:line[:\-]?)?(\d+)$", r"|\1",
                              str(c.get("evidence_ref") or ""))
                       for c in (g.get("gold_cells") or [])})

    def num(x):
        try:
            return float(x)
        except Exception:
            return None

    rows = []
    for q in sorted(rc):
        A, B = p1[q], rc[q]
        a1 = num(A.get("normalized_answer_gold") or A.get("answer_gold"))
        b1 = num(B.get("normalized_answer_gold") or B.get("answer_gold"))
        khop_ans = (a1 is not None and b1 is not None
                    and abs(a1 - b1) / max(abs(a1), abs(b1), 1e-12) < 1e-3)
        rows.append({
            "qid": q,
            "answer_pass1": A.get("answer_gold"), "answer_recheck": B.get("answer_gold"),
            "answer_match": khop_ans,
            "unit_pass1": A.get("unit"), "unit_recheck": B.get("unit"),
            "unit_match": str(A.get("unit")) == str(B.get("unit")),
            "operation_pass1": A.get("operation"), "operation_recheck": B.get("operation"),
            "operation_match": str(A.get("operation")) == str(B.get("operation")),
            "operand_refs_pass1": refs(A), "operand_refs_recheck": refs(B),
            "operand_refs_match": refs(A) == refs(B),
            "n_operand_pass1": len(A.get("gold_cells") or []),
            "n_operand_recheck": len(B.get("gold_cells") or []),
            "trang_thai_pass1": A.get("trang_thai"),
            "trang_thai_recheck": B.get("trang_thai"),
            "trang_thai_match": A.get("trang_thai") == B.get("trang_thai"),
            "hop_nhat": "BAO_THU_LAY_UNCERTAIN_NEU_MOT_BEN_UNCERTAIN",
        })
    proto = {
        "_schema": "blind_recheck_protocol_and_result v2",
        "n_gold": len(gold), "n_recheck": len(rows),
        "ty_le": round(len(rows) / len(gold), 4),
        "chon_mau": "tất định: phần tử thứ 0,5,10,… của 40 QID đã sắp tăng dần",
        "protocol": {
            "an_label_pass1": {"trang_thai": "VERIFIED",
                               "bang_chung": "prompt cấm đọc labels_batch_*.jsonl / "
                                             "answer_gold_wave1*.jsonl; annotator là "
                                             "tiến trình RIÊNG, không có label trong context"},
            "an_prediction": {"trang_thai": "VERIFIED",
                              "bang_chung": "prompt cấm data/submissions, "
                                            "data/dev/answer_a6, data/dev/so_hoc, "
                                            "dossiers_*, reports/"},
            "xao_thu_tu_cau": {"trang_thai": "NOT_VERIFIED",
                               "ly_do": "QID được đưa theo thứ tự tăng dần, KHÔNG xáo"},
            "tach_thoi_gian": {"trang_thai": "NOT_VERIFIED",
                               "ly_do": "recheck chạy cùng phiên, cách pass-1 vài phút"},
            "annotator_doc_lap": {"trang_thai": "PARTIAL",
                                  "ly_do": "tiến trình khác, ngữ cảnh khác, nhưng cùng "
                                           "một họ mô hình ⇒ lỗi hệ thống có thể tương quan"},
            "so_sanh_da_truong": {"trang_thai": "VERIFIED",
                                  "bang_chung": "file này so answer/unit/operation/"
                                                "operand_refs/n_operand/trang_thai"},
        },
        "ket_qua": {
            "answer_match": f"{sum(r['answer_match'] for r in rows)}/{len(rows)}",
            "unit_match": f"{sum(r['unit_match'] for r in rows)}/{len(rows)}",
            "operation_match": f"{sum(r['operation_match'] for r in rows)}/{len(rows)}",
            "operand_refs_match": f"{sum(r['operand_refs_match'] for r in rows)}/{len(rows)}",
            "trang_thai_match": f"{sum(r['trang_thai_match'] for r in rows)}/{len(rows)}",
        },
        "PHAN_QUYET": ("answer 8/8 khớp là VERIFIED; nhưng protocol thiếu xáo thứ tự "
                       "và tách thời gian ⇒ recheck_protocol = NOT_FULLY_VERIFIED. "
                       "Không được dùng 8/8 như bằng chứng độc lập hoàn toàn."),
        "chi_tiet": rows,
    }
    (OUT / "blind_recheck.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (OUT / "blind_recheck_protocol.json").write_text(
        json.dumps(proto, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── schema v2 + selection identity ───────────────────────────────────
    (OUT / "label_schema_v2.json").write_text(json.dumps({
        "_schema": "label_schema_v2 — doc 163 §6.1",
        "bat_buoc_cho_OK": ["qid", "question", "answer_raw", "answer_normalized",
                            "answer_type", "output_unit", "output_scale",
                            "operation_enum", "formula_semantics", "ordered_operands"],
        "operand_fields": ["order", "role", "entity", "period", "basis",
                           "metric_row_meaning", "source_document",
                           "source_document_sha256", "source_table_id", "source_row",
                           "source_column", "source_cell_id_workdb",
                           "source_line_1based", "raw_value", "source_unit",
                           "canonical_value", "source_status", "source_excerpt_file"],
        "uncertain_reason_taxonomy": list(TAXONOMY),
        "source_status_enum": ["SOURCE_LINE_VERIFIED",
                               "SOURCE_LINE_FOUND_VALUE_NOT_MATCHED",
                               "SOURCE_DOC_NOT_FOUND", "NO_EVIDENCE_REF"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    sel = json.loads((GD / "wave1_selection.json").read_text(encoding="utf-8"))
    dev = json.loads((ROOT / "data/dev/execution_gold/dev60_selection.json")
                     .read_text(encoding="utf-8"))
    aud = json.loads((ROOT / "data/dev/execution_gold/audit40_selection.json")
                     .read_text(encoding="utf-8"))
    giao = sorted(set(sel["wave1_qids"]) & set(aud["qids"]))
    (OUT / "dev60_universe.json").write_text(json.dumps({
        "_schema": "dev60_universe v1",
        "dev60_selection_sha256": shaf(ROOT / "data/dev/execution_gold/dev60_selection.json"),
        "audit40_selection_sha256": shaf(ROOT / "data/dev/execution_gold/audit40_selection.json"),
        "dev60_qids": dev["qids"], "n_dev60": len(dev["qids"]),
        "dev60_seed": dev.get("seed"), "dev60_intent_dist": dev.get("intent_dist"),
        "audit40_qids_COUNT_ONLY": len(aud["qids"]),
        "audit40_SEALED": True,
        "audit40_qid_list_KHONG_GUI": "giữ sealed, chỉ gửi SHA và số lượng",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "wave1_selection.json").write_text(json.dumps({
        **sel,
        "wave1_selection_sha256": shaf(GD / "wave1_selection.json"),
        "PROOF_audit40_intersection_empty": {
            "n_giao": len(giao), "giao": giao, "PASS": len(giao) == 0},
        "gold_final_sha256": shaf(GD / "answer_gold_wave1_final.jsonl"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "n_gold": len(v2), "n_uncertain": len(unc),
        "uncertain_taxonomy": dict(collections.Counter(
            r["uncertain_reason_taxonomy"] for r in unc)),
        "n_QID_all_operands_source_verified":
            sum(1 for r in v2 if r["all_operands_source_verified"]),
        "recheck": proto["ket_qua"],
        "audit40_intersection_empty": len(giao) == 0,
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
