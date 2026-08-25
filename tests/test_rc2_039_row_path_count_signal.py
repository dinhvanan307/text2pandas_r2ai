"""RC2-039 · tín hiệu đếm phải được đọc ở CẢ nhãn dòng lẫn nhãn cột.

Kiểm toán độc lập (Doc 56) đo trên build `7aa8b4c22984bf5f`: 98 ô mang đơn vị
chưa kết luận vẫn nằm trong `execution_ready`, và 65 ô trong đó có tín hiệu
đếm tường minh. Đo lại chi tiết hơn: **50 ô có tín hiệu CHỈ ở nhãn dòng, 0 ô
chỉ ở nhãn cột** — luật cũ đọc mỗi nhãn cột nên mù hoàn toàn với lớp này.

Nhóm test này khoá cả HAI chiều. Chiều thiếu (không nhận ra đếm) là lỗi đang
sửa; chiều thừa (biến tiền thành đếm) là lỗi mà bản sửa dễ tạo ra, và nó tệ
hơn vì âm thầm.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from data_pipeline.number_parser import (          # noqa: E402
    classify_value_kind,
    is_unit_ambiguous_share_cell,
)

# Bốn ca reviewer nêu, chép nguyên nhãn thật trong DB `7aa8b4c22984bf5f`.
REVIEWER = [
    ("046b9d0c35ab22a7", "(6.090.000)",
     "19.1 Tỉnh hình thay đổi vốn chủ sở hữu (tiếp theo) Chi tiết cổ phiếu của "
     "Ngân hàng › Số lượng cổ phiếu được mua lại", "31/12/2024"),
    ("0ace1532a7632682", "(3.800.000)",
     "24.6 Cổ phiếu › Số lượng cổ phiếu được mua lại", "6. Cổ phiếu › 31/12/2024"),
    ("187636700d6fa227", "(3.930.698)",
     "27.3 Cổ phiếu › Cổ phiếu ưu đãi › Số lượng cổ phiếu quỹ",
     "Đơn vị tính: cổ phiếu"),
]

# Trong ba ca trên, ca `187636700d6fa227` có nhãn CỘT tự khai đơn vị
# ("Đơn vị tính: cổ phiếu"). Nó được nhận nhờ mở rộng bộ tín hiệu ở nhãn cột,
# không nhờ đọc nhãn dòng. Tách ra để phép kiểm "luật cũ không bắt được" đo
# đúng thứ nó định đo.
REVIEWER_ROW_ONLY = [c for c in REVIEWER if c[0] != "187636700d6fa227"]


@pytest.mark.parametrize("uid,text,row_path,col_path", REVIEWER)
def test_tin_hieu_dem_o_nhan_dong_phai_thanh_share_count(uid, text, row_path, col_path):
    got = classify_value_kind(text, "value", col_path, False, row_path=row_path)
    assert got.value == "share_count", f"{uid}: {got.value}"


@pytest.mark.parametrize("uid,text,row_path,col_path", REVIEWER_ROW_ONLY)
def test_khong_doc_nhan_dong_thi_KHONG_bat_duoc(uid, text, row_path, col_path):
    """Chứng minh test trên thật sự đo bản sửa, không phải trùng hợp.

    Không có bước này thì các assert ở trên có thể đã xanh từ trước và cả nhóm
    test không chứng minh được gì.
    """
    cu = classify_value_kind(text, "value", col_path, False)
    assert cu.value != "share_count", f"{uid} vốn đã đúng — test không đo gì"


def test_nhan_COT_tu_khai_don_vi_thi_khong_can_nhan_dong():
    """`Đơn vị tính: cổ phiếu` là lời khai tường minh nhất có thể có ở nhãn
    cột. Bản trước không bắt nó; bản này bắt, và không cần tới nhãn dòng."""
    got = classify_value_kind("(3.930.698)", "value", "Đơn vị tính: cổ phiếu", False)
    assert got.value == "share_count"


TIEN = [
    ("14.6 Dự phòng giảm giá chứng khoán › Cổ phiếu niêm yết", "31/12/2024"),
    ("14.6 Dự phòng giảm giá chứng khoán › Cổ phiếu do các TCTD phát hành", "c2"),
    ("Thặng dư vốn cổ phần", "31/12/2023"),
    ("Vốn cổ phần › Cổ phiếu phổ thông", "Giá trị (VND)"),
]


@pytest.mark.parametrize("row_path,col_path", TIEN)
def test_nhan_TIEN_phai_giu_money(row_path, col_path):
    """Chiều thừa: sửa quá tay biến khoản dự phòng thành số lượng cổ phiếu."""
    got = classify_value_kind("(72.263.527.283)", "value", col_path, False,
                              row_path=row_path)
    assert got.value != "share_count", f"{row_path[:40]} → {got.value}"


def test_tin_hieu_YEU_o_nhan_dong_KHONG_duoc_tinh():
    """"Cổ phiếu phổ thông" ở nhãn DÒNG hầu hết là khoản mục vốn tính bằng VND.

    Đo trên A3: áp bộ tín hiệu yếu sang nhãn dòng làm 30.622 ô đổi sang đếm,
    gấp sáu lần bán kính đã khảo sát. Đó là lý do nó bị giữ ở nhãn cột.
    """
    got = classify_value_kind("(1.234.567)", "value", "31/12/2024", False,
                              row_path="Cổ phiếu phổ thông")
    assert got.value != "share_count"


def test_phan_du_chua_ket_luan_duoc_gan_co():
    """Ca thứ tư của reviewer: có "Về số lượng" nhưng ngữ cảnh không nêu cổ
    phiếu ở dạng đếm. Không kết luận được thì phải BỊ CHẶN, không được ready."""
    assert is_unit_ambiguous_share_cell(
        "(103.720)", "Bán trong năm › Lý do thay đổi", "6 CÁC KHOẢN ĐẦU TƯ TÀI "
        "CHÍNH (TIẾP THEO) › Về số lượng", True) is False, (
        "cột không nêu cổ phiếu nên không thuộc cohort RC2-039")
    assert is_unit_ambiguous_share_cell(
        "(103.720)", "6. Cổ phiếu › 31/12/2024", "Một khoản mục nào đó",
        True) is True


def test_ca_da_ket_luan_KHONG_bi_gan_co_mo_ho():
    """Cờ mơ hồ chỉ dành cho PHẦN DƯ. Gắn cả lên ca đã kết luận là chặn nhầm."""
    assert is_unit_ambiguous_share_cell(
        "(3.800.000)", "6. Cổ phiếu › 31/12/2024",
        "24.6 Cổ phiếu › Số lượng cổ phiếu được mua lại", True) is False
    assert is_unit_ambiguous_share_cell(
        "(1.000)", "Cổ phiếu › Giá trị (VND)", "Thặng dư", True) is False


def test_o_duong_khong_thuoc_cohort():
    """Cohort RC2-039 định nghĩa trên giá trị ÂM. Ô dương không được kéo vào."""
    assert is_unit_ambiguous_share_cell(
        "1.000", "6. Cổ phiếu › 31/12/2024", "Khoản mục", False) is False
