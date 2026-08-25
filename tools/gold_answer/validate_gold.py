#!/usr/bin/env python3
"""Gộp + validate answer-gold Wave 1 — doc 161 §6 Pha 1 exit gate.

Kiểm 8 điều. Thiếu trường hoặc mâu thuẫn nội tại là FAIL, không cảnh báo suông:
gold sai còn nguy hiểm hơn gold trống vì Pha 2 sẽ tin nó.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GD = ROOT / "data/curated/dev-legacy/answer_gold"

BAT_BUOC = ("qid", "question", "answer_gold", "normalized_answer_gold",
            "answer_type", "unit", "entities", "periods", "basis", "operation",
            "gold_cells", "formula", "evidence_provenance", "label_confidence",
            "trang_thai")
TRANG_THAI = {"OK", "GOLD_UNCERTAIN", "DATA_MISSING"}
CONF = {"high", "medium", "low"}


def main() -> int:
    sel = json.loads((GD / "wave1_selection.json").read_text(encoding="utf-8"))
    can = set(sel["wave1_qids"])

    rows, nguon = [], {}
    for p in sorted(GD.glob("labels_batch_*.jsonl")):
        for l in p.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                rows.append(r)
                nguon[r["qid"]] = p.name

    loi, canh = [], []
    thay = {r["qid"] for r in rows}
    if thay != can:
        loi.append({"kiem": "phu_du_40_qid", "thieu": sorted(can - thay),
                    "thua": sorted(thay - can)})
    d = collections.Counter(r["qid"] for r in rows)
    trung = [q for q, n in d.items() if n > 1]
    if trung:
        loi.append({"kiem": "khong_trung_qid", "trung": trung})

    for r in rows:
        q = r["qid"]
        thieu = [f for f in BAT_BUOC if f not in r]
        if thieu:
            loi.append({"qid": q, "kiem": "du_truong", "thieu": thieu}); continue
        if r["trang_thai"] not in TRANG_THAI:
            loi.append({"qid": q, "kiem": "trang_thai_hop_le", "co": r["trang_thai"]})
        if r["label_confidence"] not in CONF:
            loi.append({"qid": q, "kiem": "confidence_hop_le",
                        "co": r["label_confidence"]})
        if r["trang_thai"] == "OK":
            if r["answer_gold"] is None:
                loi.append({"qid": q, "kiem": "OK_phai_co_dap_an"})
            if not r.get("gold_cells"):
                loi.append({"qid": q, "kiem": "OK_phai_co_gold_cells"})
            if not r.get("formula"):
                loi.append({"qid": q, "kiem": "OK_phai_co_formula"})
        if r["trang_thai"] != "OK" and not r.get("uncertain_reason"):
            loi.append({"qid": q, "kiem": "khong_OK_phai_co_ly_do"})
        # normalized phải là số và khớp answer_gold khi answer_gold là số
        na = r.get("normalized_answer_gold")
        if r["trang_thai"] == "OK":
            if not isinstance(na, (int, float)):
                loi.append({"qid": q, "kiem": "normalized_phai_la_so", "co": na})
            elif isinstance(r["answer_gold"], (int, float)):
                # `answer_gold` là bản HIỂN THỊ đã làm tròn, `normalized` là bản
                # đủ độ chính xác — đúng theo schema. Phép kiểm đúng là "làm tròn
                # normalized về đúng số chữ số của answer_gold thì phải trùng",
                # KHÔNG phải bằng nhau tuyệt đối.
                a = float(r["answer_gold"])
                s = repr(r["answer_gold"])
                nd = len(s.split(".")[1]) if "." in s else 0
                if round(float(na), nd) != round(a, nd):
                    loi.append({"qid": q, "kiem": "normalized_lam_tron_ve_answer",
                                "answer": a, "normalized": na, "so_le": nd})
        # gold_cells phải có evidence_ref dạng doc|line:N
        for i, c in enumerate(r.get("gold_cells") or []):
            ev = str(c.get("evidence_ref") or "")
            if "|line:" not in ev:
                canh.append({"qid": q, "kiem": "evidence_ref_dinh_dang",
                             "cell": i, "co": ev})
        # số toán hạng trong formula phải ≤ số gold_cells
        # Chỉ đếm biến ĐỘC LẬP (a, b, c…), không đếm chữ nằm trong tên hàm
        # (abs/max/median/sum) — bản trước đếm cả nên báo nhầm hàng loạt.
        import re as _re
        f = str(r.get("formula") or "")
        nc = len(r.get("gold_cells") or [])
        dung = {t for t in _re.findall(r"\b[a-z]\b", f)}
        if r["trang_thai"] == "OK" and nc and len(dung) > nc:
            canh.append({"qid": q, "kiem": "formula_nhieu_hon_gold_cells",
                         "bien": sorted(dung), "n_cell": nc})

    hop = sorted(rows, key=lambda r: r["qid"])
    (GD / "answer_gold_wave1.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in hop) + "\n",
        encoding="utf-8")

    tt = collections.Counter(r["trang_thai"] for r in hop)
    cf = collections.Counter(r["label_confidence"] for r in hop)
    op = collections.Counter(r.get("operation") for r in hop)
    n_cell = collections.Counter(len(r.get("gold_cells") or []) for r in hop)

    tom = {
        "_schema": "answer_gold_wave1_validation v1",
        "n": len(hop),
        "sha256_gold": hashlib.sha256(
            (GD / "answer_gold_wave1.jsonl").read_bytes()).hexdigest(),
        "trang_thai": dict(tt),
        "label_confidence": dict(cf),
        "operation": dict(op),
        "so_gold_cell_moi_cau": dict(sorted(n_cell.items())),
        "n_loi": len(loi), "loi": loi[:25],
        "n_canh_bao": len(canh), "canh_bao": canh[:15],
        "EXIT_GATE": "PASS" if not loi else "FAIL",
    }
    (GD / "validation_report.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0 if not loi else 1


if __name__ == "__main__":
    raise SystemExit(main())
