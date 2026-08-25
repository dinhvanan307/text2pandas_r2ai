#!/usr/bin/env python3
"""Cầu nối pytest ↔ runner `chay()`.

LÝ DO TỒN TẠI (doc 155 §3.1): bảy tệp `test_*.py` trong thư mục này khai báo ca
kiểm bằng decorator `@ca(...)` và gom vào hàm `chay()`, không theo quy ước
discovery của pytest. Hệ quả đo được: reviewer chạy `pytest -q source/tests/answer_v2`
nhận `no tests ran` — **exit code 0**. Một CI gọi pytest sẽ báo XANH trong khi
chưa chạy một ca nào. Đó là false-green, nguy hiểm hơn đỏ.

Tệp này để pytest nhìn thấy đúng các ca ấy. Không thay thế runner cũ — cả hai
cùng đọc một nguồn `CA`, nên không có chuyện hai con số khác nhau.

Tên tệp có tiền tố `zz_` để chạy sau, giữ thứ tự báo cáo dễ đọc.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(HERE))

from _moitruong import BoQua, nhan_tang  # noqa: E402


def _nap():
    """→ [(tên_tệp, tên_ca, hàm_ca)] cho mọi module có `CA`."""
    ra = []
    for f in sorted(HERE.glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for ten, fn in getattr(mod, "CA", []):
            ra.append((f.stem, ten, fn))
    return ra


_CASES = _nap()

# Fail closed: nếu discovery không thấy ca nào thì đó chính là tình huống
# false-green mà tệp này sinh ra để chặn — phải đỏ, không được xanh im lặng.
assert _CASES, "không nạp được ca nào từ tests/answer_v2 — kiểm tra runner"


@pytest.mark.parametrize(
    "tep,ten,fn",
    _CASES,
    ids=[f"{tep}::{ten}" for tep, ten, _ in _CASES],
)
def test_ca(tep, ten, fn):
    # `BoQua` = thiếu đầu vào (thường là work.db) → SKIP, KHÔNG phải PASS.
    # Doc 157 §B4: bản cũ dùng `return` nên pytest đếm là passed; khi không có
    # DB, suite báo "160 passed" mà chưa chạy một ca integration nào.
    try:
        fn()
    except BoQua as e:
        pytest.skip(str(e))


def test_so_luong_ca_khop_runner():
    """Số ca pytest thấy phải bằng tổng `chay()` — chống lệch hai đường."""
    tong = 0
    for f in sorted(HERE.glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        spec = importlib.util.spec_from_file_location(f.stem, f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        tong += len(getattr(mod, "CA", []))
    assert tong == len(_CASES)
