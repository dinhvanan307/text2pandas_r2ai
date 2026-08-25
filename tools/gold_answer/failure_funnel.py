#!/usr/bin/env python3
"""failure_funnel_40 — doc 161 §6 Pha 2 / PHASE 2 của directive.

Chấm **exact official baseline** (`submission_P0I.zip`, ID 3241, EXECUTION 0,1225)
trên 40 answer-gold Wave 1, và chấm song song trạng thái CURRENT của repo để tách
phần đã trôi. Không sửa pipeline trước khi có kết quả.

Định nghĩa từng tầng — ghi rõ vì mỗi tầng là một *phép đo*, không phải cảm nhận:

| tầng | PASS nghĩa là |
|---|---|
| `retrieval_gold_present` | ít nhất một `doc|line` của gold nằm trong `relevant_tables` |
| `candidate_gold_present` | bảng chứa gold thực sự được đính vào `evidence` (đã tới tay câu lệnh) |
| `entity_correct` | ticker của bảng được chọn ∈ entity gold |
| `period_correct` | `col_label` trong câu lệnh khớp `col_path` của một gold cell |
| `basis_correct` | consolidated/separate của bảng chọn == `basis` gold |
| `metric_correct` | `row_path` trong câu lệnh khớp `row_path` của một gold cell |
| `operand_correct` | số toán hạng dùng == số `gold_cells` |
| `operation_correct` | operand đúng VÀ đáp án khớp gold sau khi bỏ qua sai số đơn vị |
| `unit_scale_correct` | tỉ số đáp án/gold không phải một luỹ thừa 10 (10^±3/6/9/12) |
| `answer_exact` | khớp gold trong dung sai tương đối 0,5% |

`first_failure_stage` = tầng ĐẦU TIÊN theo đúng thứ tự trên bị FAIL.

Câu `GOLD_UNCERTAIN` được chấm nhưng ĐẾM RIÊNG — không trộn vào mẫu số kết luận.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GD = ROOT / "data/curated/dev-legacy/answer_gold"

TANG = ["retrieval_gold_present", "candidate_gold_present", "entity_correct",
        "period_correct", "basis_correct", "metric_correct", "operand_correct",
        "operation_correct", "unit_scale_correct", "answer_exact"]

LUY_THUA = [10 ** e for e in (-12, -9, -6, -3, -2, 2, 3, 6, 9, 12)]


def chuan_ev(s: str) -> str:
    """`DOC|line:1539` và `DOC|1539` là cùng một bảng — chuẩn hoá về một dạng."""
    s = str(s or "")
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", s)
    return f"{m.group(1)}|{m.group(2)}" if m else s


def tu_csv(p: str) -> str:
    """`data/a6_NAB_..._line1539.csv` -> `NAB_...|1539`"""
    n = str(p or "").split("/")[-1]
    n = re.sub(r"^(a6_|v3_)", "", n)
    m = re.match(r"^(.*)_line(\d+)\.csv$", n)
    return f"{m.group(1)}|{m.group(2)}" if m else n


def gan_bang(a, b, tol=5e-3) -> bool:
    try:
        a, b = float(a), float(b)
    except Exception:
        return str(a).strip().lower() == str(b).strip().lower()
    m = max(abs(a), abs(b))
    return abs(a - b) <= (tol * m if m else 1e-9)


def la_luy_thua_10(a, b) -> bool:
    try:
        a, b = float(a), float(b)
    except Exception:
        return False
    if not a or not b:
        return False
    r = a / b
    return any(abs(r - k) <= abs(k) * 5e-3 for k in LUY_THUA)


def cham(rec: dict, g: dict) -> dict:
    q = rec["id"]
    ans = rec.get("answer")
    qry = str(rec.get("pandas_query") or "")
    rt = {chuan_ev(x) for x in (rec.get("relevant_tables") or [])}
    ev = {tu_csv(e.get("csv_path")) for e in (rec.get("evidence") or [])}
    cells = g.get("gold_cells") or []
    gev = {chuan_ev(c.get("evidence_ref")) for c in cells}
    grow = {str(c.get("row_path") or "").strip() for c in cells}
    gcol = {str(c.get("col_path") or "").strip() for c in cells}
    gold = g.get("normalized_answer_gold")
    if gold is None:
        gold = g.get("answer_gold")

    row_q = set(re.findall(r"row_path'\]\s*==\s*'([^']*)'", qry))
    col_q = set(re.findall(r"col_label'\]\s*==\s*'([^']*)'", qry))
    n_toan_hang = max(len(re.findall(r"\.values\[0\]", qry)), len(ev))

    r = {}
    r["retrieval_gold_present"] = bool(gev & rt) if gev else None
    r["candidate_gold_present"] = bool(gev & ev) if gev else None
    tick_chon = {e.split("_")[0] for e in ev}
    ents = set(g.get("entities") or [])
    r["entity_correct"] = bool(tick_chon & ents) if (ents and tick_chon) else None
    r["period_correct"] = bool(col_q & gcol) if (col_q and gcol) else None
    gb = g.get("basis")
    if gb in ("consolidated", "separate") and ev:
        r["basis_correct"] = any(gb in e for e in ev)
    else:
        r["basis_correct"] = None
    r["metric_correct"] = bool(row_q & grow) if (row_q and grow) else None
    r["operand_correct"] = (n_toan_hang == len(cells)) if cells else None
    khop = gan_bang(ans, gold) if (ans is not None and gold is not None) else False
    sai_don_vi = (la_luy_thua_10(ans, gold)
                  if (ans is not None and gold is not None) else False)
    r["operation_correct"] = (khop or sai_don_vi) if r["operand_correct"] else None
    r["unit_scale_correct"] = (not sai_don_vi) if ans is not None else None
    r["answer_exact"] = khop

    dau = next((t for t in TANG if r.get(t) is False), None)
    return {"qid": q, "baseline_correct": khop, "first_failure_stage": dau,
            "answer_pred": ans, "answer_gold": gold,
            "ty_le_pred_tren_gold": (round(float(ans) / float(gold), 8)
                                     if (ans not in (None, "") and gold
                                         and str(gold) != "0") else None),
            "n_toan_hang_pred": n_toan_hang, "n_gold_cells": len(cells),
            "trang_thai_gold": g.get("trang_thai"), **r}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path,
                    default=ROOT / "artifacts/submissions/legacy/submission_P0I.zip")
    ap.add_argument("--arm", default="PRIMARY_OFFICIAL_BUILD_P0I")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/funnel")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    gold = {r["qid"]: r for r in
            (json.loads(l) for l in
             (GD / "answer_gold_wave1_final.jsonl").open(encoding="utf-8")
             if l.strip())}
    sub = {r["id"]: r for r in
           json.loads(zipfile.ZipFile(a.zip).read("submission.json"))}

    rows = [cham(sub[q], gold[q]) for q in sorted(gold) if q in sub]

    chac = [r for r in rows if r["trang_thai_gold"] == "OK"]
    dem_stage = collections.Counter(r["first_failure_stage"] for r in chac)
    dem_all = collections.Counter(r["first_failure_stage"] for r in rows)
    per_tang = {t: collections.Counter(str(r.get(t)) for r in chac) for t in TANG}

    tom = {
        "_schema": "failure_funnel_summary v1",
        "arm": a.arm,
        "zip": a.zip.name,
        "n_gold": len(rows),
        "n_gold_OK": len(chac),
        "n_gold_UNCERTAIN": len(rows) - len(chac),
        "baseline_correct_tren_gold_OK":
            f"{sum(1 for r in chac if r['baseline_correct'])}/{len(chac)}",
        "baseline_correct_tren_ca_40":
            f"{sum(1 for r in rows if r['baseline_correct'])}/{len(rows)}",
        "first_failure_stage__gold_OK": dict(dem_stage),
        "first_failure_stage__ca_40": dict(dem_all),
        "tung_tang__gold_OK": {t: dict(c) for t, c in per_tang.items()},
        "ghi_chu": ("None = không đo được vì thiếu tín hiệu (vd gold_cells rỗng "
                    "hoặc câu lệnh không có ràng buộc row/col); KHÔNG tính là PASS."),
    }
    hau = a.arm.lower()
    (a.out / f"failure_funnel_40_{hau}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    (a.out / f"failure_funnel_summary_{hau}.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
