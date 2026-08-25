#!/usr/bin/env python3
"""Đo dữ liệu bị `_detect_header_rows` xoá âm thầm (D-01) — bản 2.

Bản 1 có ĐIỂM MÙ: nó chỉ đếm ô TIỀN. Corpus có 168.650 observation không phải
tiền (phần trăm, số cổ phiếu, lãi suất, số ngày) = 6,55%. Vì thế luật R2 quét
hết 4 dòng ở những bảng KHÔNG có số tiền nào — bảng tỷ lệ sở hữu công ty con,
bảng nhân sự — làm `n_header` TĂNG và xoá thêm dòng dữ liệu, mà bản 1 không
nhìn thấy vì thiệt hại đó không nằm ở ô tiền.

Đo được: 11.386 bảng (7,79%) có `n_header` tăng dưới luật R2.

Bản 2 chạy BA luật cạnh nhau và đếm thiệt hại theo TỪNG LOẠI GIÁ TRỊ.

    R1  luật hiện tại — mẫu số là số ô khác rỗng
    R2  dừng khi gặp SỐ TIỀN                     (đề xuất ban đầu, có hồi quy)
    R3  dừng khi gặp BẤT KỲ GIÁ TRỊ nào          (đề xuất sửa lại)

R3 coi là giá trị: số tiền, phần trăm, và số ≥3 chữ số. Cố ý KHÔNG tính số
1–2 chữ số, vì biểu mẫu Thông tư 200 có dòng đánh số cột `A | B | 1 | 2` nằm
trong vùng tiêu đề, và ngày `31/12/2023` là nhãn kỳ chứ không phải giá trị.

CHỈ ĐỌC. Không ghi một byte nào vào DB.

    python tools/diag_header_loss.py /tmp/dp_work/silver.sqlite
    python tools/diag_header_loss.py /tmp/dp_work/silver.sqlite --limit 5000
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections import Counter, defaultdict

MAX_HEADER_ROWS = 4
SCAN_ROWS = MAX_HEADER_ROWS + 2

_PURE_SYMBOLIC = re.compile(r"^[\d.,()%\-–—\s/]+$")
_DIGIT = re.compile(r"\d")
_GROUPED = re.compile(r"\d[.,]\d")
_PERCENT = re.compile(r"\d\s*[.,]?\s*\d*\s*%")
_DATE_LIKE = re.compile(r"\d{1,2}\s*[/.-]\s*\d{1,2}\s*[/.-]\s*(?:19|20)\d{2}")
_BARE_YEAR = re.compile(r"^\s*\(?\s*(?:19|20)\d{2}\s*\)?\s*$")
_MONTH_YEAR = re.compile(r"^\s*(?:tháng\s*)?\d{1,2}\s*/\s*(?:19|20)\d{2}\s*$", re.I)

KINDS = ("tien", "phan_tram", "so_khac")


def looks_numeric(t: str) -> bool:
    """Bản sao chính xác của `structure._looks_numeric` — để tái hiện luật R1."""
    t = t.strip()
    return bool(t) and bool(_DIGIT.search(t)) and bool(_PURE_SYMBOLIC.match(t))


def _nhan_ky(t: str) -> bool:
    """Ngày, năm trần, tháng/năm — nhãn KỲ của tiêu đề, không phải giá trị."""
    return bool(_DATE_LIKE.search(t) or _BARE_YEAR.match(t) or _MONTH_YEAR.match(t))


def value_kind(t: str) -> str | None:
    """Phân loại ô theo KIỂU. Trả None nếu ô không mang giá trị nào."""
    t = (t or "").strip()
    if not t or _nhan_ky(t):
        return None
    if _PERCENT.search(t):
        return "phan_tram"
    if not _PURE_SYMBOLIC.match(t):
        return None
    n = len(_DIGIT.findall(t))
    if n >= 6 or (n >= 4 and _GROUPED.search(t)):
        return "tien"
    if n >= 3:
        return "so_khac"
    return None                       # 1–2 chữ số: STT, đánh số cột, mã ngắn


def is_money(t: str) -> bool:
    return value_kind(t) == "tien"


def has_value(t: str) -> bool:
    return value_kind(t) is not None


# ── ba luật ────────────────────────────────────────────────────────────────

def r1_hien_tai(grid: list[list[str]]) -> int:
    n = 0
    for r in range(min(MAX_HEADER_ROWS, len(grid))):
        texts = [t for t in grid[r] if t.strip()]
        if not texts:
            if n == r:
                n = r + 1
            continue
        if sum(1 for t in texts if looks_numeric(t)) > len(texts) // 2:
            break
        n = r + 1
    return max(n, 1) if grid else 0


def r2_dung_o_tien(grid: list[list[str]]) -> int:
    n = 0
    for r in range(min(MAX_HEADER_ROWS, len(grid))):
        if any(is_money(t) for t in grid[r]):
            break
        n = r + 1
    return n


def r3_dung_o_gia_tri(grid: list[list[str]]) -> int:
    n = 0
    for r in range(min(MAX_HEADER_ROWS, len(grid))):
        if any(has_value(t) for t in grid[r]):
            break
        n = r + 1
    return n


RULES = (("R1_hien_tai", r1_hien_tai),
         ("R2_dung_o_tien", r2_dung_o_tien),
         ("R3_dung_o_gia_tri", r3_dung_o_gia_tri))


# ── dựng lại lưới văn bản từ Silver ────────────────────────────────────────

def load_grids(con, limit: int = 0):
    where = ""
    if limit:
        where = (" WHERE tf.table_uid IN "
                 f"(SELECT table_uid FROM table_features LIMIT {limit})")
    sql = f"""
    SELECT g.table_uid, g.grid_row_idx, g.grid_col_idx, COALESCE(sc.text_clean, ''),
           tf.n_grid_cols, tf.statement_type
    FROM grid_cells g
    JOIN table_features tf ON tf.table_uid = g.table_uid
    LEFT JOIN source_cells sc ON sc.source_cell_uid = g.source_cell_uid
    {where}
      {'AND' if where else 'WHERE'} g.grid_row_idx < {SCAN_ROWS}
    ORDER BY g.table_uid, g.grid_row_idx, g.grid_col_idx
    """
    cur_uid, buf, meta = None, defaultdict(dict), None
    for tuid, r, c, txt, ncols, stype in con.execute(sql):
        if cur_uid is not None and tuid != cur_uid:
            yield cur_uid, _to_grid(buf, meta[0]), meta
            buf = defaultdict(dict)
        cur_uid, meta = tuid, (ncols, stype)
        buf[r][c] = txt
    if cur_uid is not None:
        yield cur_uid, _to_grid(buf, meta[0]), meta


def _to_grid(buf, ncols):
    if not buf:
        return []
    return [[buf.get(r, {}).get(c, "") for c in range(ncols)]
            for r in range(max(buf) + 1)]


def _mat(grid, n_header) -> Counter:
    """Giá trị nằm trong vùng bị coi là tiêu đề — tức là bị xoá."""
    out = Counter()
    for r in range(min(n_header, len(grid))):
        for t in grid[r]:
            k = value_kind(t)
            if k:
                out[k] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--samples", type=int, default=12)
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)

    n_tab = 0
    mat = {name: Counter() for name, _ in RULES}
    bang_mat = Counter()
    delta = {"R2_dung_o_tien": Counter(), "R3_dung_o_gia_tri": Counter()}
    theo_stype = defaultdict(Counter)
    khong_header = Counter()
    mau_am = []          # bảng mà luật mới coi NHIỀU dòng là tiêu đề hơn

    for tuid, grid, (ncols, stype) in load_grids(con, a.limit):
        if not grid:
            continue
        n_tab += 1
        nh = {name: fn(grid) for name, fn in RULES}
        for name in nh:
            m = _mat(grid, nh[name])
            mat[name] += m
            if m:
                bang_mat[name] += 1
                theo_stype[name][stype] += sum(m.values())
            if nh[name] == 0:
                khong_header[name] += 1
        for name in delta:
            delta[name][nh["R1_hien_tai"] - nh[name]] += 1

        if nh["R3_dung_o_gia_tri"] > nh["R1_hien_tai"] and len(mau_am) < a.samples:
            r0 = min(nh["R1_hien_tai"], len(grid) - 1)
            mau_am.append((tuid[:12], stype, nh["R1_hien_tai"],
                           nh["R2_dung_o_tien"], nh["R3_dung_o_gia_tri"],
                           [t for t in grid[r0] if t.strip()][:4]))

    p = print
    p("╔════════ D-01 · ba luật nhận diện tiêu đề, đo cạnh nhau ════════╗")
    p(f"  bảng đã quét: {n_tab:,}")
    p("")
    p(f"  {'luật':<20}{'tiền':>10}{'phần trăm':>12}{'số khác':>10}"
      f"{'TỔNG':>10}{'bảng mất':>10}{'n_hdr=0':>9}")
    for name, _ in RULES:
        m = mat[name]
        p(f"  {name:<20}{m['tien']:>10,}{m['phan_tram']:>12,}"
          f"{m['so_khac']:>10,}{sum(m.values()):>10,}"
          f"{bang_mat[name]:>10,}{khong_header[name]:>9,}")
    p("")
    p("  ── Chênh lệch n_header so với R1 (dương = thu hồi, âm = xoá thêm) ──")
    for name in ("R2_dung_o_tien", "R3_dung_o_gia_tri"):
        d = delta[name]
        am = sum(v for k, v in d.items() if k < 0)
        duong = sum(v for k, v in d.items() if k > 0)
        p(f"    {name:<20} thu hồi {duong:>7,} bảng | "
          f"XOÁ THÊM {am:>7,} bảng | không đổi {d[0]:>7,}")
        for k in sorted(d):
            if k:
                p(f"        {k:+d} dòng : {d[k]:>7,}")
    p("")
    p("  ── Thiệt hại còn lại theo loại báo cáo (luật R3) ──")
    for k, v in theo_stype["R3_dung_o_gia_tri"].most_common(8):
        p(f"    {k:<20}{v:>10,}")
    p("")
    p(f"  ── {len(mau_am)} bảng R3 VẪN xoá thêm so với R1 (nếu có) ──")
    for tuid, stype, n1, n2, n3, cells in mau_am:
        p(f"    {tuid} {stype:<14} R1={n1} R2={n2} R3={n3}  {cells}")
    if not mau_am:
        p("    (không có — R3 không bao giờ xoá nhiều hơn R1)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
