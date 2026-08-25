#!/usr/bin/env python3
"""Workstream C · parser kỳ từ `col_path`. Contract cố định, doc 140 §3.6.

VÌ SAO C QUAN TRỌNG HƠN DỰ KIẾN (reports/diag_weight_scale_v1.json)

Phân rã khoảng cách điểm giữa top-1 và gold trên 33 slot sai:

    idf_overlap   18/33
    col_year      12/33     ← MỘT hằng số +0,6 quyết định 36% số ca sai
    exact_phrase   2/33

`col_year` hiện là một phép kiểm chuỗi con:

    if any(y in col_path for y in years): s += 0.6

Nó cho +0,6 cho **mọi** cột chứa chuỗi "2024" — kể cả `Số đầu năm` của báo cáo
2024 (là số dư 31/12/2023), kể cả cột ghi chú, kể cả `Năm trước` trong file
2024. Đó chính là 9 ca TEMPORAL còn lại sau S5.

Parser này thay phép kiểm chuỗi con bằng một hợp đồng có kiểm được:

    {
      "year": 2024 | None,
      "period_type": "point_in_time" | "full_year" | "quarter" | "half_year" | "unknown",
      "role": "opening" | "closing" | "current" | "previous" | "unknown",
      "confidence": 0.0..1.0,
      "evidence_tokens": [...]
    }

XUNG ĐỘT NĂM TUYỆT ĐỐI vs VAI TRÒ TƯƠNG ĐỐI — quy ước khai trước:
    năm tuyệt đối trong cột ("31/12/2023") THẮNG vai trò tương đối ("Năm nay"),
    vì con số là bằng chứng trực tiếp còn vai trò phải suy từ `doc_year`.
    Khi cả hai cùng có và MÂU THUẪN, `confidence` bị hạ xuống 0,5 và
    `evidence_tokens` ghi cả hai để người đọc truy được.
"""
from __future__ import annotations

import re
import unicodedata

SEP = re.compile(r"\s*›\s*")

# `31/12/2024`, `31.12.2024`, `31-12-2024`
#
# ⚠️ KHÔNG dùng `\b` ở cuối. Dạng phổ biến NHẤT trong dữ liệu thật là
# `31/12/2024Triệu VND` (567 lần trong work.db) — giữa `4` và `T` KHÔNG có ranh
# giới từ vì cả hai đều là ký tự từ, nên `\b` làm regex trượt và ô rơi xuống
# nhánh "năm trần" với confidence 0,6 thay vì 1,0. Test nhóm 1 bắt được.
NGAY = re.compile(r"(?<!\d)(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{4})(?!\d)")
# `31 tháng 12 năm 2024`, `ngày 31 tháng 12 năm 2024`
NGAY_CHU = re.compile(r"(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", re.I)
# `2024` đứng một mình hoặc dính đơn vị: `2024Triệu VND`
NAM_TRAN = re.compile(r"(?<!\d)(19|20)(\d{2})(?!\d)")

DAU_KY = re.compile(r"số\s*đầu\s*(năm|kỳ)|đầu\s*kỳ|số\s*dư\s*đầu", re.I)
CUOI_KY = re.compile(r"số\s*cuối\s*(năm|kỳ)|cuối\s*kỳ|số\s*dư\s*cuối", re.I)
NAM_NAY = re.compile(r"năm\s*nay|kỳ\s*này|kỳ\s*báo\s*cáo", re.I)
NAM_TRUOC = re.compile(r"năm\s*trước|kỳ\s*trước|cùng\s*kỳ", re.I)
GHI_CHU = re.compile(r"thuyết\s*minh|ghi\s*chú|mã\s*số|chỉ\s*tiêu|đơn\s*vị\s*tính",
                     re.I)
QUY = re.compile(r"\bquý\s*([1-4IV]+)", re.I)
BAN_NIEN = re.compile(r"bán\s*niên|6\s*tháng", re.I)


def _bo_dau(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def parse_col_period(col_path: str | None, doc_year: int | None = None) -> dict:
    """`col_path` → hợp đồng kỳ. Không bao giờ ném lỗi; không rõ thì `unknown`."""
    txt = col_path or ""
    ev: list[str] = []

    # ── năm tuyệt đối ──────────────────────────────────────────────────────
    nam, ptype = None, "unknown"
    m = NGAY_CHU.search(txt) or NGAY.search(txt)
    if m:
        d, mth, y = m.group(1), m.group(2), m.group(3)
        nam, ptype = int(y), "point_in_time"
        ev.append(m.group(0).strip())
        # 31/12 là điểm chốt kỳ; ngày khác vẫn là point_in_time nhưng ghi rõ
        if not (int(d) == 31 and int(mth) == 12):
            ev.append(f"khong_phai_31_12:{d}/{mth}")
    else:
        cac_nam = [int(a + b) for a, b in NAM_TRAN.findall(txt)]
        if cac_nam:
            # NHIỀU năm trong một path: lấy năm LỚN NHẤT và hạ confidence ở dưới
            nam = max(cac_nam)
            ptype = "full_year"
            ev.append(f"nam_tran:{sorted(set(cac_nam))}")

    if QUY.search(txt):
        ptype = "quarter"
        ev.append(QUY.search(txt).group(0).strip())
    elif BAN_NIEN.search(txt):
        ptype = "half_year"
        ev.append("ban_nien")

    # ── vai trò tương đối ──────────────────────────────────────────────────
    vai = "unknown"
    if CUOI_KY.search(txt):
        vai = "closing"
        ev.append("cuoi_ky")
    elif DAU_KY.search(txt):
        vai = "opening"
        ev.append("dau_ky")
    elif NAM_NAY.search(txt):
        vai = "current"
        ev.append("nam_nay")
    elif NAM_TRUOC.search(txt):
        vai = "previous"
        ev.append("nam_truoc")

    # ── suy năm từ vai trò khi không có năm tuyệt đối ─────────────────────
    # `Số đầu năm` của báo cáo năm Y là số dư 31/12 của năm Y−1. Đây chính là
    # chỗ phép kiểm chuỗi con của `col_year` sai: nó thấy "Y" ở đâu đó trong
    # path rồi thưởng, trong khi ô ấy thuộc về Y−1.
    suy_ra = False
    if nam is None and doc_year:
        if vai in ("closing", "current"):
            nam, ptype, suy_ra = doc_year, ptype if ptype != "unknown" else "point_in_time", True
        elif vai in ("opening", "previous"):
            nam, ptype, suy_ra = doc_year - 1, ptype if ptype != "unknown" else "point_in_time", True
        if suy_ra:
            ev.append(f"suy_tu_doc_year:{doc_year}")

    # ── confidence ─────────────────────────────────────────────────────────
    if nam is None:
        conf = 0.0
    elif GHI_CHU.search(txt) and not m:
        conf = 0.3                       # cột ghi chú, số năm có thể là mã
    elif m:
        conf = 1.0                       # ngày đầy đủ
    elif suy_ra:
        conf = 0.7                       # suy từ vai trò + doc_year
    else:
        conf = 0.6                       # chỉ có năm trần

    # nhiều năm trong path ⇒ bớt chắc chắn
    if any(e.startswith("nam_tran:[") and "," in e for e in ev):
        conf = min(conf, 0.4)

    # xung đột: năm tuyệt đối nói một đằng, vai trò tương đối nói một nẻo
    if nam is not None and doc_year and not suy_ra and vai != "unknown":
        ky_vong = doc_year if vai in ("closing", "current") else doc_year - 1
        if nam != ky_vong:
            conf = min(conf, 0.5)
            ev.append(f"xung_dot:nam={nam}_vai={vai}_doc_year={doc_year}")

    return {"year": nam, "period_type": ptype, "role": vai,
            "confidence": round(conf, 2), "evidence_tokens": ev}


def period_match(c: dict, ctx: dict) -> float:
    """Feature thay `col_year`. → [−1, 1], nhân trọng số ở score_cell.

    +conf  cột thuộc ĐÚNG năm được hỏi
    −conf  cột thuộc năm KHÁC (phạt, vì đây là ca TEMPORAL)
     0     không xác định được kỳ ⇒ im lặng, không đoán

    Khác `col_year` ở hai chỗ quyết định: (1) biết `Số đầu năm` thuộc năm
    trước; (2) PHẠT khi sai năm thay vì chỉ không thưởng — nên ô đúng năm
    được tách khỏi ô sai năm bằng khoảng 2×conf chứ không phải 0,6.
    """
    p = parse_col_period(c.get("col_path"), c.get("doc_year"))
    if p["year"] is None:
        return 0.0
    return p["confidence"] * (1.0 if str(p["year"]) in ctx["years"] else -1.0)
