"""P0-f · KHOÁ bộ lọc CỘT PHI GIÁ TRỊ của tầng đáp án.

BẰNG CHỨNG ĐÃ DẪN TỚI BỘ LỌC NÀY
--------------------------------
Đo trên chính gói đã nộp: **162/1012 đáp án (16,0%)** được lấy từ một cột không
chứa giá trị — `Mã số`, `Thuyết minh`, `TT`. Đó là số hiệu chỉ tiêu (100, 110,
221) hoặc số hiệu thuyết minh (13.1, 20), **không phải số tiền**. Không cần
gold cũng khẳng định được những câu ấy sai. Kiểm tay bắt tận tay ba ca:

    q492  "lưu chuyển tiền thuần ..."     -> 20.0    (mã số 20)
    q664  "tỷ lệ hao mòn TSCĐ hữu hình"   -> 221.0   (mã số 221)
    q235  "dự phòng rủi ro cho vay ..."   -> 13.1    (số hiệu thuyết minh)

Sau khi lọc: 162 → 3.

HAI CẠM BẪY ĐỀU CÓ TEST
-----------------------
1. **Bỏ sót**: nhãn cột trong corpus này hay bị dính cả nội dung dòng vào
   ("Mã số I. LƯU CHUYỂN TIỀN TỪ HOẠT ĐỘNG KINH DOANH"). Bản đầu nhận bất kỳ
   chữ `dong` nào là dấu hiệu "cột giá trị", nên nhãn ấy thoát lọc — vì
   "hoạt động" chứa "dong". Dấu hiệu cột giá trị phải là ĐƠN VỊ hoặc KỲ.
2. **Nhận nhầm**: một nhãn có "Mã số" ở đầu NHƯNG kèm ngày/đơn vị
   ("Mã số TÀI SẢN 31/12/2024 VND") là cột giá trị thật bị dính chữ — không
   được loại, nếu không thì mất cả bảng cân đối.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGUON = ROOT / "tools/answer_v2/06_loc_cot_phi_gia_tri.py"

_spec = importlib.util.spec_from_file_location("p0f_loc_cot", NGUON)
loc = importlib.util.module_from_spec(_spec)
sys.modules["p0f_loc_cot"] = loc
_spec.loader.exec_module(loc)

la = loc.la_cot_phi_gia_tri


# ═════════════════════════════════════════════════════════════════════════════
# 1 · phải LOẠI — đây là số hiệu, không phải số tiền
# ═════════════════════════════════════════════════════════════════════════════

def test_cot_ma_so_bi_loai():
    assert la("Mã số")
    assert la("Mãsố")


def test_cot_thuyet_minh_bi_loai():
    assert la("Thuyết minh")
    assert la("Thuyếtminh")


def test_cot_stt_bi_loai():
    assert la("STT") and la("TT")


def test_nhan_dinh_noi_dung_dong_van_bi_loai():
    """q492: "Mã số I. LƯU CHUYỄN TIỀN TỪ HOẠT ĐỘNG KINH DOANH".

    "hoạt động" chứa "dong". Nếu coi mọi chữ `dong` là dấu hiệu đơn vị tiền thì
    nhãn này thoát lọc và câu hỏi trả về mã số 20.
    """
    assert la("Mã số I. LƯU CHUYỄN TIỀN TỪ HOẠT ĐỘNG KINH DOANH")


def test_thuyet_minh_dinh_tieu_de_van_bi_loai():
    assert la("Thuyết minh TÀI SẢN")
    assert la("Mã số NGUỒN VỐN")


# ═════════════════════════════════════════════════════════════════════════════
# 2 · phải GIỮ — cột giá trị thật, dù nhãn có dính chữ
# ═════════════════════════════════════════════════════════════════════════════

def test_cot_co_ngay_thang_duoc_giu():
    assert not la("31/12/2024 VND")
    assert not la("Mã số TÀI SẢN 31/12/2024 VND")


def test_cot_co_don_vi_duoc_giu():
    assert not la("Số cuối năm Triệu đồng TÀI SẢN")
    assert not la("Năm nayTriệu đồng")


def test_cot_ky_tuong_doi_duoc_giu():
    for x in ("Năm nay", "Năm trước", "Số cuối năm", "Số đầu năm"):
        assert not la(x), x


def test_cot_ty_le_duoc_giu():
    """Câu hỏi tỷ lệ sở hữu lấy số ngay ở cột "Tỷ lệ lợi ích" — không được loại."""
    assert not la("Tỷ lệ lợi ích")
    assert not la("Tỷ lệ sở hữu %")


def test_nhan_tu_sinh_va_nhan_rong_duoc_giu():
    """`c0`, `c1` là nhãn tự sinh khi bảng không có tiêu đề — nhiều bảng để giá
    trị ở đó. Nhãn rỗng cũng vậy."""
    assert not la("c0") and not la("c1") and not la("")


# ═════════════════════════════════════════════════════════════════════════════
# 3 · bất biến an toàn: không bao giờ làm bảng rỗng
# ═════════════════════════════════════════════════════════════════════════════

class _O:
    def __init__(self, col):
        self.col_label = col


def test_loc_het_thi_tra_lai_nguyen_ban():
    """Nếu mọi cột đều bị loại thì trả nguyên bản — mất một ô đúng còn hơn mất
    cả bảng, vì khi đó `answer` rỗng và câu chắc chắn 0 điểm."""
    loc._GOC.clear()
    loc._GOC.append(lambda g: [_O("Mã số"), _O("Thuyết minh")])
    ra = loc.to_long_format_loc(None)
    assert len(ra) == 2


def test_loc_mot_phan_thi_chi_giu_cot_gia_tri():
    loc._GOC.clear()
    loc._GOC.append(lambda g: [_O("Mã số"), _O("31/12/2024 VND"), _O("Thuyết minh")])
    ra = loc.to_long_format_loc(None)
    assert [x.col_label for x in ra] == ["31/12/2024 VND"]
