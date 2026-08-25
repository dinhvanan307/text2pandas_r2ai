#!/usr/bin/env python3
"""Bảng chứng cứ NGUỒN cho người gán nhãn — doc 161 §6 Pha 1.

Vì sao KHÔNG dùng dossier cũ: `dossiers_dev60/*.md` liệt kê **top-10 của chính hệ
thống**. Gán nhãn từ đó thì `candidate_gold_present` sẽ đúng 100% **theo cấu tạo**,
và failure funnel ở Pha 2 mất hết ý nghĩa — đúng cái vòng tròn doc 161 §5 cảnh báo.

Ở đây truy thẳng `work.db.observations`, lọc bằng **ticker + năm + từ khoá lấy từ
CÂU HỎI**, không dùng scorer, không dùng thứ hạng, không giới hạn top-N. Người gán
nhìn toàn bộ dòng khớp rồi tự chọn.

  python3 tools/gold_answer/source_sheet.py --qid 52 --kw "chuyển tiền nhanh"
  python3 tools/gold_answer/source_sheet.py --qid 52 --kw "phải thu" --max 60
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "artifacts/retrieval/work.db"


def bo_dau(s: str) -> str:
    """Bỏ dấu tiếng Việt.

    NFD KHÔNG tách được `Đ`/`đ` (U+0110/U+0111) vì chúng là ký tự riêng, không
    phải D + dấu tổ hợp. Phải thay tay TRƯỚC khi chuẩn hoá — nếu không thì
    `--kw "hoat dong"` trượt sạch "hoạt động" và người gán nhãn sẽ kết luận
    DATA_MISSING nhầm. Hai annotator độc lập đã vấp đúng lỗi này.
    """
    s = (s or "").replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qid", type=int, required=True)
    ap.add_argument("--kw", action="append", default=[],
                    help="từ khoá lấy TỪ CÂU HỎI (không dấu cũng được)")
    ap.add_argument("--year", type=int, action="append", default=[])
    ap.add_argument("--ticker", action="append", default=[])
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    plans = {r["qid"]: r for r in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8")
             if l.strip())}
    p = plans[a.qid]
    tickers = a.ticker or (p.get("entities") or [])
    years = a.year or (p.get("years") or [])

    print(f"# QID {a.qid}")
    print(f"Q: {p['question']}")
    print(f"parse: entities={p.get('entities')} years={p.get('years')} "
          f"basis={p.get('basis')} unit={p.get('output_unit')} "
          f"intent={p.get('intent_v1')}")
    if not tickers:
        print("!! parse không có entity — phải chỉ định --ticker")
        return 1

    c = sqlite3.connect("file:" + os.path.abspath(WORK) + "?mode=ro", uri=True)
    # doc_year của tài liệu thường lớn hơn năm hỏi (BCTC năm N chứa cả N-1)
    dy = sorted({y for yy in years for y in (yy, yy + 1)}) or None

    q = ("SELECT ticker, doc_year, statement_type, evidence_ref, row_path_text,"
         " col_path_text, value_source_raw, value_decimal_text, scale_exponent,"
         " unit_kind, period_end, period_role, metric_label_clean"
         " FROM observations WHERE ticker IN (%s)" % ",".join("?" * len(tickers)))
    par = list(tickers)
    if dy:
        q += " AND doc_year IN (%s)" % ",".join("?" * len(dy)); par += dy
    rows = c.execute(q, par).fetchall()

    kws = [bo_dau(k) for k in a.kw]
    hit = [r for r in rows
           if all(k in bo_dau(str(r[4]) + " " + str(r[12])) for k in kws)] if kws else rows

    print(f"\nquan sát của {tickers} doc_year={dy}: {len(rows)}  ·  khớp từ khoá "
          f"{a.kw}: {len(hit)}   (KHÔNG xếp hạng, KHÔNG top-N của hệ thống)")
    if a.json:
        print(json.dumps([dict(zip(
            "ticker doc_year stmt evidence_ref row_path col_path raw dec scale "
            "unit period_end period_role metric".split(), r)) for r in hit[:a.max]],
            ensure_ascii=False, indent=1))
        return 0

    print(f"\n{'#':>3} {'yr':>4} {'stmt':<10} {'period_end':<11} {'raw':>16} "
          f"{'sc':>3} {'row_path'} || {'col_path'}")
    for i, r in enumerate(hit[:a.max], 1):
        (tk, yr, st, ev, rp, cp, raw, dec, sc, uk, pe, pr, ml) = r
        print(f"{i:>3} {yr:>4} {str(st)[:10]:<10} {str(pe):<11} {str(raw):>16} "
              f"{str(sc):>3} {str(rp)[:66]} || {str(cp)[:34]}")
        print(f"      ev={ev}")
    if len(hit) > a.max:
        print(f"... còn {len(hit)-a.max} dòng (tăng --max)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
