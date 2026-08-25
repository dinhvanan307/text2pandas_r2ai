#!/usr/bin/env python3
"""Môi trường test — phân biệt SKIP với PASS. Trả lời B4 của doc 157.

VẤN ĐỀ ĐANG SỬA
Các ca cần `work.db` trước đây dùng `return` khi không thấy DB. Cả runner
`chay()` lẫn pytest đều tính đó là **PASS**. Hệ quả đo được:

    không có work.db      → 160 passed      ← false-green
    có minimal DB v1      → 158 passed, 2 failed

Con số `160 passed` vì thế **không** chứng minh runtime integration xanh. Một ca
không chạy phải hiện ra là *không chạy*.

CÁCH SỬA
`work_db()` ném `BoQua` khi thiếu DB. `chay_chung()` đếm riêng, và
`test_zz_pytest_wrapper.py` đổi `BoQua` thành `pytest.skip`. Không đường nào
biến "thiếu DB" thành xanh nữa.

BA TẦNG TEST (doc 157 §B4)
    unit                 không cần DB              — phải 0 failed
    minimal integration  TEXT2PANDAS_WORK_DB=<v2>  — phải 0 failed, 0 silent-return
    full integration     work.db 4,2 GB            — TEAM_VERIFIED, ghi đúng nhãn

Chọn DB theo thứ tự: `TEXT2PANDAS_WORK_DB` → `artifacts/retrieval/work.db`.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAC_DINH = ROOT / "artifacts/retrieval/work.db"


class BoQua(Exception):
    """Ca không chạy được vì thiếu đầu vào — KHÔNG phải pass, KHÔNG phải fail."""


def duong_dan_db() -> Path:
    p = os.environ.get("TEXT2PANDAS_WORK_DB")
    return Path(p) if p else MAC_DINH


def work_db() -> Path:
    """→ đường dẫn DB, hoặc ném `BoQua`. Không bao giờ trả None âm thầm."""
    p = duong_dan_db()
    if not p.is_file():
        raise BoQua(f"work.db unavailable: {p}")
    return p


def nhan_tang() -> str:
    """Nhãn tầng đang chạy — để log không nhập nhằng ba tầng với nhau."""
    p = duong_dan_db()
    if not p.is_file():
        return "unit-only (no DB)"
    if os.environ.get("TEXT2PANDAS_WORK_DB"):
        return f"minimal-db integration ({p.name})"
    return "full-db integration (artifacts/retrieval/work.db)"


def chay_chung(CA):
    """Runner dùng chung. Giữ chữ ký `(xanh, tong, do)` cho tương thích ngược.

    Ca `BoQua` KHÔNG vào `xanh` và KHÔNG vào `do`, nên người gọi tính được
    `bo_qua = tong - xanh - len(do)`. Bản cũ không có khái niệm này — đó là chỗ
    false-green chui qua.
    """
    xanh, do = 0, []
    for ten, f in CA:
        try:
            f()
            xanh += 1
        except BoQua:
            continue
        except AssertionError as e:
            do.append((ten, str(e) or "assert failed"))
        except Exception as e:
            do.append((ten, f"{type(e).__name__}: {e}"))
    return xanh, len(CA), do


def in_ket_qua(ten_tep: str, xanh: int, tong: int, do) -> int:
    bo_qua = tong - xanh - len(do)
    for t, m in do:
        print(f"✗ {t}\n    {m}")
    print(f"\n{ten_tep}: {xanh} passed · {len(do)} failed · {bo_qua} skipped "
          f"/ {tong} · tầng: {nhan_tang()}")
    return 0 if not do else 1
