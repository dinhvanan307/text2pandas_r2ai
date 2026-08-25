"""Cổng phát hành phải phân biệt ĐO RỒI HỎNG với CHƯA ĐO ĐƯỢC.

Đây là bộ kiểm cho một lỗi quản trị, không phải một lỗi dữ liệu. Cả hai trạng
thái đều cho `pass=False` trong `quality_report.json`, và khi gộp chúng lại thì
hai điều tồi tệ xảy ra cùng lúc:

1. RC không bao giờ phát hành được — G3 "độ chính xác role trên gold" sẽ đỏ
   vĩnh viễn cho tới khi có Structure Gold, mà Retrieval thì không cần nó.
2. Áp lực "gỡ cổng cho xong việc" tăng lên, và lần sau một FAIL thật đi lọt
   cùng. Đây không phải giả thuyết: build a94013318c97ad30 đã từng publish
   trong lúc G4 FAIL.

Doc 12 §7: RC ĐƯỢC PHÉP mang gate `BLOCKED` **miễn khai rõ**. Hai chữ "khai
rõ" cũng được kiểm ở đây — im lặng về một cổng chưa đo đọc như một cổng đã qua.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_pipeline.gates import (  # noqa: E402
    BLOCKED, FAIL, PASS, legacy_check_status, split_legacy_gates)
from data_pipeline.release import _gate_rollup  # noqa: E402


def _c(name, ok, **kw):
    return {"name": name, "value": kw.pop("value", "x"),
            "threshold": kw.pop("threshold", "y"), "pass": ok, **kw}


# ── ba trạng thái, không phải hai ───────────────────────────────────────────

@pytest.mark.parametrize("check, want", [
    (_c("đạt", True), PASS),
    (_c("hỏng", False), FAIL),
    (_c("chưa đo", False, blocked=True), BLOCKED),
    # Đường dự phòng cho report cũ chưa có cờ `blocked`: quy ước giá trị mở
    # đầu bằng "BLOCKED". Giữ nó để một `quality_report.json` sinh trước bản
    # vá này vẫn đọc đúng, thay vì lặng lẽ tụt xuống FAIL.
    (_c("chưa đo, report cũ", False, value="BLOCKED — chưa có gold"), BLOCKED),
])
def test_ba_trang_thai(check, want):
    assert legacy_check_status(check) == want


def test_blocked_khong_bao_gio_thanh_pass():
    """Luật cứng số 2 của `gates.py`. Nếu test này đỏ, gói sẽ tuyên bố sai."""
    assert legacy_check_status(_c("x", False, blocked=True)) is not PASS


# ── tách hai luồng ──────────────────────────────────────────────────────────

GATES = {
    "G2 Parsing": [_c("bảng parse ok", True)],
    "G3 Structure": [
        _c("bảng có cột giá trị", True),
        _c("độ chính xác role trên gold", False, blocked=True,
           value="BLOCKED — chưa có gold", threshold="≥ 98%"),
    ],
}


def test_blocked_khong_chan_phat_hanh():
    failed, blocked = split_legacy_gates(GATES)
    assert failed == [], "BLOCKED không được nằm trong nhánh chặn"
    assert len(blocked) == 1


def test_fail_van_chan():
    g = {**GATES, "G4": [_c("dash thành 0", False, value=12, threshold="0")]}
    failed, blocked = split_legacy_gates(g)
    assert len(failed) == 1 and "dash thành 0" in failed[0]
    assert len(blocked) == 1, "một FAIL không được nuốt mất BLOCKED"


def test_blocked_phai_khai_du_gia_tri_va_nguong():
    """"Khai rõ" nghĩa là đọc được, không phải chỉ đếm được."""
    _, blocked = split_legacy_gates(GATES)
    assert "G3 Structure" in blocked[0]
    assert "chưa có gold" in blocked[0]
    assert "≥ 98%" in blocked[0]


def test_gates_rong_khong_sinh_canh_bao_ma():
    assert split_legacy_gates(None) == ([], [])
    assert split_legacy_gates({}) == ([], [])


# ── tổng hợp theo cụm ───────────────────────────────────────────────────────

@pytest.mark.parametrize("checks, want", [
    ([_c("a", True), _c("b", True)], PASS),
    ([_c("a", True), _c("b", False, blocked=True)], BLOCKED),
    ([_c("a", False), _c("b", False, blocked=True)], FAIL),
])
def test_rollup_fail_thang_blocked_thang_pass(checks, want):
    """Manifest phải mang ba trạng thái. `false` cho cả hai là mất thông tin
    quan trọng nhất với người nhận: cái nào chờ ta sửa, cái nào ta chưa đo."""
    assert _gate_rollup(checks) == want


# ── nhãn suy ra từ cổng, không do người đặt ─────────────────────────────────

def test_quality_py_danh_dau_g3_la_blocked():
    """Kiểm tận nguồn: nếu ai đó bỏ cờ `blocked` khỏi `quality.py`, RC lại
    tắc và test ở trên vẫn xanh vì chúng dùng dữ liệu giả."""
    src = (Path(__file__).resolve().parents[1]
           / "src" / "data_pipeline" / "quality.py").read_text(encoding="utf-8")
    i = src.index("độ chính xác role trên gold")
    assert '"blocked": True' in src[i:i + 400], \
        "G3 gold check phải mang cờ blocked, nếu không publish sẽ chặn nhầm"
