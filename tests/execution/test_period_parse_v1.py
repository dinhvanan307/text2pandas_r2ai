#!/usr/bin/env python3
"""Test parser kỳ — phủ đủ 6 nhóm ca doc 140 §3.6 yêu cầu.

    1. 31/12/2024 · 31 tháng 12 năm 2024 · 2024
    2. số đầu năm · số cuối năm · năm nay · năm trước
    3. nhiều năm trong cùng path
    4. cột ghi chú / thuyết minh
    5. path không có kỳ
    6. xung đột giữa năm tuyệt đối và vai trò tương đối
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from execution.period_parse_v1 import parse_col_period, period_match  # noqa: E402

CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


# ── nhóm 1 · dạng ngày/năm ─────────────────────────────────────────────────
@ca("1 · 31/12/2024Triệu VND → 2024, point_in_time, conf 1.0")
def _():
    p = parse_col_period("31/12/2024Triệu VND")
    assert p["year"] == 2024 and p["period_type"] == "point_in_time"
    assert p["confidence"] == 1.0


@ca("1 · 'Ngày 31 tháng 12 năm 2016' → 2016")
def _():
    p = parse_col_period("Ngày 31 tháng 12 năm 2016")
    assert p["year"] == 2016 and p["confidence"] == 1.0


@ca("1 · '2015Triệu VND' (năm trần) → 2015, full_year, conf thấp hơn ngày đủ")
def _():
    p = parse_col_period("2015Triệu VND")
    assert p["year"] == 2015 and p["period_type"] == "full_year"
    assert p["confidence"] < parse_col_period("31/12/2015")["confidence"]


@ca("1 · ngày KHÔNG phải 31/12 vẫn nhận năm nhưng ghi bằng chứng")
def _():
    p = parse_col_period("30/06/2024")
    assert p["year"] == 2024
    assert any("khong_phai_31_12" in e for e in p["evidence_tokens"])


# ── nhóm 2 · vai trò tương đối ─────────────────────────────────────────────
@ca("2 · 'Số cuối năm' + doc_year 2022 → 2022, closing")
def _():
    p = parse_col_period("Số cuối nămTriệu đồng", 2022)
    assert p["role"] == "closing" and p["year"] == 2022


@ca("2 · 'Số đầu năm' + doc_year 2022 → 2021 (KHÔNG phải 2022)")
def _():
    """Đây là ca mà `col_year` sai: nó thấy '2022' ở doc rồi thưởng cho cột đầu
    năm, trong khi số dư đầu năm 2022 chính là 31/12/2021."""
    p = parse_col_period("Số đầu nămTriệu đồng", 2022)
    assert p["role"] == "opening" and p["year"] == 2021


@ca("2 · 'Năm nay' → current; 'Năm trước' → previous, lệch 1 năm")
def _():
    a = parse_col_period("Năm nay Triệu đồng", 2020)
    b = parse_col_period("Năm trước Triệu đồng", 2020)
    assert a["role"] == "current" and a["year"] == 2020
    assert b["role"] == "previous" and b["year"] == 2019


@ca("2 · không có doc_year thì KHÔNG bịa năm")
def _():
    p = parse_col_period("Số cuối năm")
    assert p["year"] is None and p["role"] == "closing" and p["confidence"] == 0.0


# ── nhóm 3 · nhiều năm ─────────────────────────────────────────────────────
@ca("3 · nhiều năm trong path ⇒ confidence bị hạ")
def _():
    p = parse_col_period("So sánh 2022 và 2023")
    assert p["year"] == 2023
    assert p["confidence"] <= 0.4, "nhiều năm ⇒ không được tự tin"


# ── nhóm 4 · cột ghi chú ───────────────────────────────────────────────────
@ca("4 · cột thuyết minh có số ⇒ confidence thấp")
def _():
    p = parse_col_period("Thuyết minh 2024")
    assert p["confidence"] <= 0.3


@ca("4 · 'Đơn vị tính: VND' ⇒ không có năm")
def _():
    assert parse_col_period("Đơn vị tính: VND")["year"] is None


# ── nhóm 5 · không có kỳ ───────────────────────────────────────────────────
@ca("5 · path không kỳ ⇒ unknown toàn phần, conf 0")
def _():
    for s in ("Nguyên giá", "TÀI SẢN", "Ngắn hạn", "", None):
        p = parse_col_period(s)
        assert p["year"] is None and p["confidence"] == 0.0, s


# ── nhóm 6 · xung đột ──────────────────────────────────────────────────────
@ca("6 · năm tuyệt đối THẮNG vai trò tương đối")
def _():
    p = parse_col_period("Năm trước 31/12/2023", 2024)
    assert p["year"] == 2023, "năm tuyệt đối là bằng chứng trực tiếp"


@ca("6 · mâu thuẫn năm↔vai trò ⇒ hạ confidence và ghi bằng chứng")
def _():
    p = parse_col_period("Năm nay 31/12/2019", 2024)
    assert p["confidence"] <= 0.5
    assert any(e.startswith("xung_dot") for e in p["evidence_tokens"])


# ── feature period_match ───────────────────────────────────────────────────
@ca("feature · đúng năm ⇒ dương, sai năm ⇒ ÂM (khác col_year: có phạt)")
def _():
    ctx = {"years": {"2024"}}
    dung = {"col_path": "31/12/2024", "doc_year": 2024}
    sai = {"col_path": "31/12/2023", "doc_year": 2024}
    assert period_match(dung, ctx) > 0
    assert period_match(sai, ctx) < 0, \
        "col_year chỉ 'không thưởng' ô sai năm; ở đây phải PHẠT, nếu không thì " \
        "khoảng cách giữa ô đúng và ô sai vẫn chỉ là 0,6"


@ca("feature · không xác định được kỳ ⇒ 0, im lặng chứ không đoán")
def _():
    assert period_match({"col_path": "Nguyên giá", "doc_year": 2024},
                        {"years": {"2024"}}) == 0.0


@ca("feature · 'Số đầu năm' của doc 2022 bị PHẠT khi hỏi 2022")
def _():
    """Ca TEMPORAL kinh điển. col_year hiện thưởng +0,6 cho ô này nếu chuỗi
    '2022' xuất hiện đâu đó trong path."""
    assert period_match({"col_path": "Số đầu nămTriệu đồng", "doc_year": 2022},
                        {"years": {"2022"}}) < 0


@ca("hợp đồng · schema đủ 5 khoá, kiểu đúng")
def _():
    p = parse_col_period("31/12/2024", 2024)
    assert set(p) == {"year", "period_type", "role", "confidence", "evidence_tokens"}
    assert isinstance(p["confidence"], float) and isinstance(p["evidence_tokens"], list)
    assert p["period_type"] in ("point_in_time", "full_year", "quarter",
                                "half_year", "unknown")
    assert p["role"] in ("opening", "closing", "current", "previous", "unknown")


def chay() -> tuple[int, int, list]:
    xanh, do = 0, []
    for ten, f in CA:
        try:
            f()
            xanh += 1
        except AssertionError as e:
            do.append((ten, str(e) or "assert failed"))
        except Exception as e:
            do.append((ten, f"{type(e).__name__}: {e}"))
    return xanh, len(CA), do


if __name__ == "__main__":
    x, n, d = chay()
    for ten, msg in d:
        print(f"✗ {ten}\n    {msg}")
    print(f"\n{x}/{n} xanh")
    raise SystemExit(0 if not d else 1)
