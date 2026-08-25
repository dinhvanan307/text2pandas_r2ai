"""RC2-036/037 · `value_kind` và `unit_kind` phải nói cùng một điều.

Defect gốc, đo trên bản dựng thật `4c86c9e43915694a`:

  `classify_value_kind` có cổng hình dạng `_shape_allows` (thêm ở semantic v1.3)
  nên ô `10.805.901` dưới nhãn cột "Thời hạn định lại lãi suất" được kết luận
  `value_kind = money` — đúng, vì hình dạng loại trừ lãi suất.

  Nhưng `unit_resolver._find_kind` KHÔNG có cổng đó. Từ khoá "lãi suất" trong
  nhãn cột vẫn lật `unit_kind` sang `rate`. Kết quả: **20.378 bản ghi tự mâu
  thuẫn** — tiền mang đơn vị lãi suất — và **2.599 ô** trên cột ghi rõ
  "Số cổ phiếu" bị đẩy sang `money` vì cổ phiếu quỹ ghi trong ngoặc đơn.

  Cổng G4 có đo tỷ lệ này, nhưng ngưỡng 93% không phân biệt được "chưa biết"
  với "biết sai": RC2 đạt 93,41% và PASS, trong khi RC1 đạt 94,11%.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data_pipeline.models import UnitKind, ValueKind          # noqa: E402
from data_pipeline.number_parser import (                     # noqa: E402
    _explicit_share_count_column, classify_value_kind,
)
from data_pipeline.unit_resolver import resolve_unit          # noqa: E402


# ── RC2-036 · money_view chặn từ khoá nhãn lật đơn vị ─────────────────────

@pytest.mark.parametrize("header,kind_cu", [
    ("Thời hạn định lại lãi suất › Trên 5 năm", UnitKind.RATE),
    ("Số cổ phiếu › Số cuối năm", UnitKind.SHARES),
    ("Kỳ thu tiền (ngày)", UnitKind.DAYS),
    ("Số lượng › Cuối kỳ", UnitKind.COUNT),
])
def test_money_view_khong_cho_tu_khoa_nhan_lat_don_vi(header, kind_cu):
    """Không có `money_view`, nhãn quyết định. Có `money_view`, nó không được
    quyền mâu thuẫn với kết luận đã có ở tầng trên."""
    thuong = resolve_unit("", header, "", "", "")
    assert thuong.unit_kind is kind_cu

    tien = resolve_unit("", header, "", "", "", money_view=True)
    assert tien.unit_kind is not kind_cu
    assert tien.unit_kind in (UnitKind.MONEY, UnitKind.UNKNOWN)


def test_money_view_KHONG_ep_money_khi_khong_co_bang_chung():
    """`unknown` là "chưa xác định được" — trung thực. Ép `money` ở đây sẽ thổi
    phồng G4 bằng phỏng đoán, tức đổi một lỗi lấy một lỗi khác."""
    r = resolve_unit("", "Số cổ phiếu › Số cuối năm", "", "", "", money_view=True)
    assert r.unit_kind is UnitKind.UNKNOWN
    assert r.currency is None and r.scale_exponent is None


def test_money_view_van_lay_tien_te_va_bac_tu_bang_chung():
    r = resolve_unit("", "Thời hạn định lại lãi suất › Triệu đồng", "", "", "",
                     money_view=True)
    assert r.unit_kind is UnitKind.MONEY
    assert r.currency == "VND" and r.scale_exponent == 6


def test_money_view_khong_dung_thi_hanh_vi_cu_giu_nguyen():
    """Đường không phải tiền phải KHÔNG đổi — nếu không, ta vừa sửa một hồi quy
    bằng cách tạo một hồi quy khác."""
    for h in ("Lãi suất (%/năm)", "Số cổ phiếu", "Số ngày"):
        assert resolve_unit("", h, "", "", "").unit_kind is not UnitKind.MONEY


# ── RC2-037 · cột đếm cổ phiếu tường minh ─────────────────────────────────

@pytest.mark.parametrize("hdr,mong_doi", [
    ("số cổ phiếu › số cuối năm", True),
    ("31/12/2015 › số cổ phiếu", True),
    ("số cuối năm › cổ phiếu thường", True),
    ("cổ phiếu quỹ", True),
    ("số lượng cp", True),
    # tình cờ có chữ "cổ phần"/"cổ phiếu" nhưng là TIỀN
    ("thặng dư vốn cổ phần › năm trước", False),
    ("vốn cổ phần vnd", False),
    ("lãi cơ bản trên cổ phiếu", False),
    ("mệnh giá cổ phiếu", False),
    ("số cổ phiếu › triệu đồng", False),
])
def test_nhan_dien_cot_dem_co_phieu(hdr, mong_doi):
    assert _explicit_share_count_column(hdr) is mong_doi


def test_co_phieu_quy_trong_ngoac_van_la_SO_LUONG():
    """Ca thật `36ed1e467f8e228c`: "Số cổ phiếu › Số cuối năm" ·
    "Cổ phiếu quỹ Cổ phiếu phổ thông" · `(978.328)`.

    RC1 gán `share_count` — ĐÚNG. RC2 gán `money` — SAI, vì luật "số cổ phiếu
    âm không tồn tại" đúng với số lưu hành nhưng sai với cổ phiếu quỹ, vốn là
    khoản TRỪ khỏi vốn chủ sở hữu nên được trình bày trong ngoặc.
    """
    assert classify_value_kind("(978.328)", "unknown",
                               "Số cổ phiếu › Số cuối năm", False) \
        is ValueKind.SHARE_COUNT


def test_nhan_chi_TINH_CO_co_chu_co_phan_thi_van_la_TIEN():
    """`c677fffe7b24ac9c`: "Thặng dư vốn cổ phần" · 2.499.887.606.238."""
    assert classify_value_kind("2.499.887.606.238", "unknown",
                               "Thặng dư vốn cổ phần › Năm trước", False) \
        is ValueKind.MONEY


def test_lai_co_ban_tren_co_phieu_la_TIEN_khong_phai_dem():
    assert classify_value_kind("2.345", "unknown",
                               "Lãi cơ bản trên cổ phiếu", False) \
        is ValueKind.MONEY


def test_so_luong_co_phieu_duong_van_la_dem_nhu_cu():
    assert classify_value_kind("1.000.000", "unknown",
                               "Số cổ phiếu phổ thông", False) \
        is ValueKind.SHARE_COUNT


def test_so_qua_lon_tren_cot_co_phieu_khong_phai_dem():
    """3.935.483.020.000 trên "Cổ phiếu phổ thông" là VỐN, không phải số cổ
    phiếu — toàn thị trường Việt Nam chưa tới 10¹¹ cổ phiếu."""
    assert classify_value_kind("3.935.483.020.000", "unknown",
                               "Cổ phiếu phổ thông có quyền biểu quyết", False) \
        is ValueKind.MONEY


# ── đường gọi thật trong observation_builder ──────────────────────────────

def test_observation_builder_dung_ban_don_vi_danh_cho_o_TIEN():
    src = (ROOT / "src" / "data_pipeline" / "observation_builder.py").read_text(
        encoding="utf-8")
    assert "col_unit_money" in src
    assert "money_view=True" in src
    i = src.index("unit = col_unit_money[col.grid_col_idx]")
    assert "else:" in src[max(0, i - 300):i], "phải là nhánh cho ô TIỀN"


def test_semantic_version_da_bump():
    src = (ROOT / "src" / "data_pipeline" / "observation_builder.py").read_text(
        encoding="utf-8")
    assert 'SEMANTIC_VERSION = "1.4"' in src
