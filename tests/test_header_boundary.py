"""D-01 — ranh giới tiêu đề. Bộ kiểm bảo vệ khiếm khuyết MẤT dữ liệu.

Luật cũ tính "đa số ô parse được thành số" với mẫu số là **số ô KHÁC RỖNG**.
Dòng thưa làm mẫu số co lại và phép so sánh đảo chiều, nên dòng dữ liệu bị gán
`HEADER`. Mà `observation_builder` bỏ qua mọi dòng `HEADER` — tức là **xoá
cứng**, đi vòng qua DI-02, không cờ, không log.

Đo trên toàn corpus (`tools/diag_header_loss.py`):

    R1 hiện tại    mất 85.095 giá trị / 29.071 bảng
                   (tiền 63.414 · phần trăm 17.537 · số khác 4.144)
    R2 "dừng ở SỐ TIỀN"   mất 27.413 · xoá thêm ở 12.013 bảng
    R3 "dừng ở GIÁ TRỊ"   mất 0      · thu hồi 29.071 bảng

Mỗi ca dưới đây là một hình dạng bảng đã quan sát được trong corpus, và mỗi ca
ÂM là một luật trung gian đã bị số đo bác bỏ. Đừng gỡ ca âm nào.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_pipeline.html_parser import parse_table
from data_pipeline.structure import (
    _cell_value_kind, _detect_header_rows, interpret_structure)


def _tbl(rows: list[list[str]]) -> str:
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{tr}</table>"


def _detect(rows):
    return _detect_header_rows(parse_table("t", _tbl(rows), 120_000))


# ── phân loại ô theo KIỂU ───────────────────────────────────────────────────

@pytest.mark.parametrize("text, kind", [
    ("323.162.400.000", "money"),
    ("(50.000.000)", "money"),
    ("1.245", "money"),                # 4 chữ số CÓ phân nhóm
    ("29,28%", "percent"),
    ("4,50 %", "percent"),
    ("8061", "number"),                # 4 chữ số không phân nhóm
    ("123", "number"),
    # Nhãn KỲ — nhiều chữ số nhưng không phải giá trị. Đây chính là chỗ luật
    # "ô ≥6 chữ số thì dòng không thể là tiêu đề" tự mâu thuẫn.
    ("31/12/2023", None),
    ("01/01/2023", None),
    ("2023", None),
    ("(2023)", None),
    ("12/2023", None),
    ("tháng 6/2024", None),
    # Số 1–2 chữ số: dòng đánh số cột TT200, STT, Mã số ngắn.
    ("1", None),
    ("12", None),
    # Token đơn vị và chữ.
    ("VND", None),
    ("triệu đồng", None),
    ("%", None),
    ("Chỉ tiêu", None),
    ("", None),
])
def test_cell_value_kind(text, kind):
    assert _cell_value_kind(text) == kind


# ── ranh giới tiêu đề ───────────────────────────────────────────────────────

def test_dong_thua_khong_bi_nuot():
    """Mẫu thật: 1 số trên 2 ô khác rỗng làm luật cũ đảo chiều."""
    n, flags = _detect([
        ["Giá gốc VND", "", "", ""],
        ["Đầu tư góp vốn vào:", "", "", ""],
        ["Các công ty con", "", "", "323.162.400.000"],
        ["Công ty A", "", "", "100.000.000.000"],
    ])
    assert n == 2


def test_tieu_de_ngay_thang_duoc_giu():
    """CA ÂM: `31/12/2023` có tám chữ số mà vẫn là nhãn cột hợp lệ."""
    n, _ = _detect([
        ["BẢNG CÂN ĐỐI KẾ TOÁN", "", "", ""],
        ["Chỉ tiêu", "Mã số", "31/12/2023", "01/01/2023"],
        ["A. TÀI SẢN NGẮN HẠN", "100", "1.000.000.000", "900.000.000"],
    ])
    assert n == 2


def test_dong_danh_so_cot_tt200():
    """CA ÂM: biểu mẫu TT200 có dòng `A | B | C | 1` NẰM TRONG vùng tiêu đề."""
    n, _ = _detect([
        ["Chỉ tiêu", "Mã số", "Thuyết minh", "31/12/2023"],
        ["A", "B", "C", "1"],
        ["A. TÀI SẢN NGẮN HẠN", "100", "5.1", "1.000.000.000"],
    ])
    assert n == 2


def test_bang_ty_le_so_huu_khong_bi_nuot():
    """CA ÂM cho luật R2: bảng này KHÔNG có đồng nào.

    R2 "dừng ở số tiền" quét hết 4 dòng và xoá 21.967 ô phần trăm trên corpus.
    """
    n, _ = _detect([
        ["Công ty", "Nơi thành lập", "Tỷ lệ sở hữu", "Quyền biểu quyết"],
        ["Kính nổi VFG", "Bắc Ninh", "29,28%", "29,28%"],
        ["Máy điện VN-HU", "Hà Nội", "34,27%", "34,27%"],
    ])
    assert n == 1


def test_bang_khong_co_tieu_de():
    """`n_header=0` là trạng thái HỢP LỆ. Sàn `max(...,1)` cũ xoá dòng đầu."""
    n, flags = _detect([
        ["Tiền mặt", "5.639.613.726", "1.000.000"],
        ["Tiền gửi NH", "236.753.569.124", "2.000.000"],
    ])
    assert n == 0
    assert "no_header_row" in flags


def test_tieu_de_tang_hai_duoc_nhan():
    """Luật cũ cắt tiêu đề ở 1 dòng nên tầng hai rơi xuống thành body.

    Đây là 10.384 bảng có `n_header` TĂNG dưới luật mới — không phải hồi quy
    mà là bản vá thứ hai: `col_path` lấy lại nhãn phân biệt cột.
    """
    n, _ = _detect([
        ["Số cuối năm", "Số cuối năm", "Số đầu năm", "Số đầu năm"],
        ["Giá gốc", "Dự phòng", "Giá gốc", "Dự phòng"],
        ["Cổ phiếu ABC", "1.000.000.000", "(50.000.000)", "900.000.000"],
    ])
    assert n == 2


def test_tieu_de_tang_hai_tach_duoc_cot():
    """Hệ quả phải kiểm: bốn cột có bốn `col_path` KHÁC NHAU.

    Đây là một phần của D-03 (42.743 nhóm đụng độ trục cột) được sửa kèm.
    """
    st = interpret_structure(parse_table("t", _tbl([
        ["Số cuối năm", "Số cuối năm", "Số đầu năm", "Số đầu năm"],
        ["Giá gốc", "Dự phòng", "Giá gốc", "Dự phòng"],
        ["Cổ phiếu ABC", "1.000.000.000", "(50.000.000)", "900.000.000"],
    ]), 120_000), "", "5 ĐẦU TƯ")
    paths = [c.header_path_text for c in st.columns]
    assert len(set(paths)) == len(paths), paths
    assert "Số cuối năm › Giá gốc" in paths


# ── DI-02: không bao giờ được xoá trọn bảng ─────────────────────────────────

def test_khong_duoc_nhan_tron_ca_bang():
    """Bảng đếm toàn số 1–2 chữ số khớp điều kiện tiêu đề ở MỌI dòng.

    Không chặn thì `n_header = n_grid_rows` và cả bảng biến mất. Giữ dữ liệu
    kèm cờ luôn tốt hơn xoá dữ liệu không dấu vết (DI-02).
    """
    n, flags = _detect([
        ["Số lao động nam", "12", "34"],
        ["Số lao động nữ", "21", "43"],
    ])
    assert n == 0
    assert "header_would_consume_table" in flags
    assert "header_row_has_small_numbers" in flags


def test_bang_rong():
    n, flags = _detect([])
    assert n == 0


# ── cờ chẩn đoán phải sạch trên bảng bình thường ────────────────────────────

@pytest.mark.parametrize("rows", [
    [["BẢNG CÂN ĐỐI KẾ TOÁN", "", "", ""],
     ["Chỉ tiêu", "Mã số", "31/12/2023", "01/01/2023"],
     ["A. TÀI SẢN NGẮN HẠN", "100", "1.000.000.000", "900.000.000"]],
    [["Chỉ tiêu", "Mã số", "Thuyết minh", "31/12/2023"],
     ["A", "B", "C", "1"],
     ["A. TÀI SẢN NGẮN HẠN", "100", "5.1", "1.000.000.000"]],
])
def test_khong_gan_co_bua(rows):
    """Nhãn kỳ và nhãn ngắn KHÔNG được kích hoạt cờ rủi ro."""
    _, flags = _detect(rows)
    assert "header_row_has_small_numbers" not in flags
    assert "header_would_consume_table" not in flags
