"""A5-A · bậc nhân chỉ là bằng chứng còn thiếu ở nơi CÓ bậc nhân.

Mọi test ở đây đi theo cặp: một vế chứng minh luật MỞ đúng chỗ, một vế chứng
minh nó KHÔNG mở chỗ khác. Chỉ có vế đầu thì bài test không phân biệt được bản
vá đúng với bản vá xoá sạch guard.
"""
from decimal import Decimal

import pytest
import yaml

from data_pipeline.models import ValueKind
from data_pipeline.number_parser import (
    PERCENT_ABS_MAX,
    is_percent_value_implausible,
)
from data_pipeline.readiness import load_policy

POL = load_policy()
COND = [c for c in POL.raw["confidence"]["low_if_conditions"] if "scale_source" in c]


def test_chi_co_dung_mot_ve_scale_trong_low_if():
    assert len(COND) == 1, COND


@pytest.mark.parametrize("unit", ["percent", "shares", "days"])
def test_unit_khong_co_bac_nhan_duoc_mien(unit):
    assert f"'{unit}'" in COND[0]


@pytest.mark.parametrize("unit", ["money", "unknown", "rate"])
def test_unit_can_bang_chung_bac_khong_duoc_mien(unit):
    """`rate` nằm đây có chủ đích: 3/73 ca đọc tay ra 545 · 580 · 780 cho
    `Tiền gửi của khách hàng`. Chưa xác định nguyên nhân thì chưa mở."""
    assert f"'{unit}'" not in COND[0]


def test_ve_scale_viet_dang_NOT_IN_de_fail_closed():
    """Unit kind mới thêm sau này phải MẶC ĐỊNH rơi vào diện cần bằng chứng."""
    assert "NOT IN" in COND[0]


def test_guard_tien_van_con_nguyen_trong_bieu_thuc():
    e = POL.confidence_expr()
    assert "scale_source IN ('assumed','none')" in e
    assert "period_end IS NULL" in e


def test_policy_version_da_tang():
    assert POL.policy_version == "2.2"


# ── cờ chặn A5-A2 ────────────────────────────────────────────────────────
def test_co_percent_implausible_da_dang_ky_la_blocking():
    assert "percent_value_implausible" in [f for f, _ in POL.blocking]


@pytest.mark.parametrize("v", ["1000", "1000.01", "38708428190000", "-3900000000000"])
def test_percent_qua_lon_bi_gan_co(v):
    assert is_percent_value_implausible(ValueKind.PERCENTAGE, Decimal(v))


@pytest.mark.parametrize("v", ["0", "15", "50.99", "100", "144.19", "999.99", "-99.9"])
def test_percent_hop_ly_khong_bi_gan_co(v):
    """144,19% nợ thuần/vốn chủ sở hữu là con số THẬT trong corpus."""
    assert not is_percent_value_implausible(ValueKind.PERCENTAGE, Decimal(v))


@pytest.mark.parametrize("kind", [ValueKind.MONEY, ValueKind.SHARE_COUNT])
def test_co_chi_ap_cho_percentage(kind):
    assert not is_percent_value_implausible(kind, Decimal("38708428190000"))


def test_gia_tri_None_khong_gan_co():
    assert not is_percent_value_implausible(ValueKind.PERCENTAGE, None)


def test_nguong_dung_bang_1000_khong_phai_so_khac():
    """Ngưỡng đến từ số đo (102.748/103.193 ô nằm dưới 1.000). Đổi nó là đổi
    một quyết định đã ghi trong AMD-A5-01, không phải chỉnh một hằng số."""
    assert PERCENT_ABS_MAX == Decimal("1000")


# ── bảng nối defect ──────────────────────────────────────────────────────
def test_moi_reason_moi_deu_map_duoc_ve_defect_id():
    d = yaml.safe_load(open("configs/defect_taxonomy_v1.yaml"))
    codes = set(d["defects"])
    rr = d["readiness_reasons"]
    for r in ("percent_value_implausible", "period_inferred_from_row_path",
              "period_row_path_not_addressable"):
        assert r in rr, r
        assert rr[r] in codes, (r, rr[r])
