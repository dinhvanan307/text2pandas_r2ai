#!/usr/bin/env python3
"""Chẩn đoán Silver — chỉ ĐỌC. Không ghi, không sửa, không publish.

    python tools/diagnose_silver.py

Trả lời bốn câu hỏi mà build vừa rồi đặt ra:

  1. 29.032 cột giá trị còn trống kỳ là loại gì? Bậc bằng chứng nào còn cứu được?
  2. 12,66% bảng không có cột giá trị nào — chúng là bảng gì?
  3. `row_path` bị nhiễm bao nhiêu do `_extract_section` nuốt dòng kế tiếp?
  4. 199.326 nhãn dòng chung chung có được `row_path` phân biệt không?

Mọi con số ở đây là ĐẦU VÀO cho quyết định, không phải kết luận.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

DB = Path(os.environ.get("DATA_PIPELINE_SCRATCH", "/tmp/dp_work")) / "silver.sqlite"


def h(title: str) -> None:
    print(f"\n{'═' * 78}\n  {title}\n{'═' * 78}")


def rows(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return r[0] if r else 0


def main() -> int:
    if not DB.exists():
        print(f"không thấy {DB}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    n_val = one(conn, "SELECT COUNT(*) FROM columns WHERE column_role='value'")
    n_tab = one(conn, "SELECT COUNT(*) FROM table_features")

    # ── 1. Cột giá trị còn trống kỳ ──────────────────────────────────────
    h("1 · CỘT GIÁ TRỊ CÒN TRỐNG KỲ")
    n_un = one(conn, "SELECT COUNT(*) FROM columns"
                     " WHERE column_role='value' AND period_end IS NULL")
    print(f"  {n_un:,} / {n_val:,} cột giá trị  ({100*n_un/n_val:.2f}%)")

    n_empty_hdr = one(conn, "SELECT COUNT(*) FROM columns"
                            " WHERE column_role='value' AND period_end IS NULL"
                            " AND (header_path_text IS NULL OR TRIM(header_path_text)='')")
    print(f"  trong đó nhãn cột RỖNG: {n_empty_hdr:,} ({100*n_empty_hdr/max(n_un,1):.1f}%)")

    print("\n  ── nhãn cột phổ biến nhất (top 25) ──")
    for lbl, c in rows(conn,
        "SELECT COALESCE(NULLIF(TRIM(header_path_text),''),'‹rỗng›'), COUNT(*)"
        " FROM columns WHERE column_role='value' AND period_end IS NULL"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 25"):
        print(f"    {c:>7,}  {lbl[:62]}")

    print("\n  ── loại bảng chứa chúng ──")
    for st, c in rows(conn,
        "SELECT t.statement_type, COUNT(*) FROM columns c"
        " JOIN table_features t USING(table_uid)"
        " WHERE c.column_role='value' AND c.period_end IS NULL"
        " GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {c:>7,}  {st}")

    # Bảng có cột trống kỳ mà ngữ cảnh CÓ chứa năm → bậc `section`/`document`
    # còn cứu được. Không có năm ở đâu cả → chỉ còn `doc_year`, và đó là đoán.
    print("\n  ── còn bằng chứng ở bậc nào? (mẫu 4.000 cột) ──")
    smp = rows(conn,
        "SELECT c.table_uid, t.section_text, t.context_clean, t.doc_year"
        " FROM columns c JOIN table_features t USING(table_uid)"
        " WHERE c.column_role='value' AND c.period_end IS NULL LIMIT 4000")
    yr = re.compile(r"\b20[0-2]\d\b")
    in_section = sum(1 for _, s, _, _ in smp if s and yr.search(s))
    in_context = sum(1 for _, _, x, _ in smp if x and yr.search(x))
    has_docyear = sum(1 for _, _, _, d in smp if d)
    n = max(len(smp), 1)
    print(f"    có năm trong `section` : {in_section:>6,}  ({100*in_section/n:.1f}%)")
    print(f"    có năm trong `context` : {in_context:>6,}  ({100*in_context/n:.1f}%)")
    print(f"    có `doc_year`          : {has_docyear:>6,}  ({100*has_docyear/n:.1f}%)")
    print(f"    KHÔNG còn bằng chứng   : "
          f"{sum(1 for _, s, x, _ in smp if not (s and yr.search(s)) and not (x and yr.search(x))):>6,}")

    # ── 2. Bảng không có cột giá trị ─────────────────────────────────────
    h("2 · BẢNG KHÔNG CÓ CỘT GIÁ TRỊ NÀO")
    n_novalue = one(conn,
        "SELECT COUNT(*) FROM table_features t WHERE NOT EXISTS"
        " (SELECT 1 FROM columns c WHERE c.table_uid=t.table_uid"
        "  AND c.column_role='value')")
    print(f"  {n_novalue:,} / {n_tab:,} bảng  ({100*n_novalue/n_tab:.2f}%)")

    print("\n  ── loại bảng ──")
    for st, c, nr, nc, ratio in rows(conn,
        "SELECT t.statement_type, COUNT(*), ROUND(AVG(t.n_grid_rows),1),"
        " ROUND(AVG(t.n_grid_cols),1), ROUND(AVG(t.numeric_ratio),3)"
        " FROM table_features t WHERE NOT EXISTS"
        " (SELECT 1 FROM columns c WHERE c.table_uid=t.table_uid AND c.column_role='value')"
        " GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {c:>7,}  {st:<18} tb {nr}×{nc} ô  numeric_ratio {ratio}")

    print("\n  ── chúng có sinh observation không? ──")
    n_obs_nv = one(conn,
        "SELECT COUNT(*) FROM observations o WHERE NOT EXISTS"
        " (SELECT 1 FROM columns c WHERE c.table_uid=o.table_uid"
        "  AND c.column_role='value')")
    print(f"    {n_obs_nv:,} observation  → nếu >0 thì có cột giá trị bị phân loại nhầm")

    print("\n  ── mẫu 8 bảng, kèm nhãn cột thực tế ──")
    for tid, sec in rows(conn,
        "SELECT t.table_uid, t.section_text FROM table_features t WHERE NOT EXISTS"
        " (SELECT 1 FROM columns c WHERE c.table_uid=t.table_uid AND c.column_role='value')"
        " AND t.numeric_ratio > 0.2 LIMIT 8"):
        hdrs = rows(conn, "SELECT column_role, header_path_text FROM columns"
                          " WHERE table_uid=? ORDER BY grid_col_idx LIMIT 6", (tid,))
        desc = " | ".join("%s:%s" % (r, (t or "")[:20]) for r, t in hdrs)
        print("    § %s" % (sec or "")[:56])
        print("      %s" % desc)

    # ── 3. Nhiễm row_path ────────────────────────────────────────────────
    h("3 · NHIỄM `row_path` DO `_extract_section`")
    n_sec = one(conn, "SELECT COUNT(*) FROM table_features WHERE section_text<>''")
    print(f"  bảng rút được section: {n_sec:,} / {n_tab:,}")
    for lo, hi in ((0, 40), (40, 60), (60, 80), (80, 100), (100, 999)):
        c = one(conn, "SELECT COUNT(*) FROM table_features"
                      " WHERE section_text<>'' AND LENGTH(section_text)>=? AND LENGTH(section_text)<?",
                (lo, hi))
        print(f"    độ dài {lo:>3}–{hi:<3} : {c:>7,}  ({100*c/max(n_sec,1):.1f}%)")

    n_sec_date = one(conn,
        "SELECT COUNT(*) FROM table_features WHERE section_text<>''"
        " AND (section_text GLOB '*[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]*'"
        "      OR section_text LIKE '%tháng%năm%' OR section_text LIKE '%ngày%')")
    print(f"\n  section CHỨA ngày/tháng (không nên có): {n_sec_date:,}"
          f"  ({100*n_sec_date/max(n_sec,1):.1f}%)")

    print("\n  ── 10 section dài nhất ──")
    for s, in rows(conn, "SELECT section_text FROM table_features WHERE section_text<>''"
                         " ORDER BY LENGTH(section_text) DESC LIMIT 10"):
        print(f"    [{len(s):>3}] {s[:100]}")

    print("\n  ── phân bố độ dài row_path (mẫu 200.000 obs) ──")
    for lo, hi in ((0, 60), (60, 100), (100, 150), (150, 250), (250, 9999)):
        c = one(conn, "SELECT COUNT(*) FROM (SELECT row_path_text FROM observations"
                      " LIMIT 200000) WHERE LENGTH(row_path_text)>=? AND LENGTH(row_path_text)<?",
                (lo, hi))
        print(f"    {lo:>3}–{hi:<4} ký tự : {c:>7,}")

    # ── 4. Nhãn chung chung ──────────────────────────────────────────────
    h("4 · NHÃN DÒNG CHUNG CHUNG — `row_path` có phân biệt được không?")
    n_gen = one(conn, "SELECT COUNT(*) FROM observations"
                      " WHERE quality_flags_json LIKE '%generic_row_label%'")
    print(f"  {n_gen:,} observation ({100*n_gen/max(one(conn,'SELECT COUNT(*) FROM observations'),1):.1f}%)")

    print("\n  ── nhãn phổ biến nhất, kèm số row_path KHÁC NHAU ──")
    for lbl, c, d in rows(conn,
        "SELECT metric_label_clean, COUNT(*), COUNT(DISTINCT row_path_text)"
        " FROM observations WHERE quality_flags_json LIKE '%generic_row_label%'"
        " GROUP BY 1 ORDER BY 2 DESC LIMIT 20"):
        # tỷ lệ càng gần 1 nghĩa là row_path phân biệt càng tốt
        print(f"    {c:>7,}  path khác nhau {d:>7,}  ({d/max(c,1):.3f})  {(lbl or '')[:40]}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
