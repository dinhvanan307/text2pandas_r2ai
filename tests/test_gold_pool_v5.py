"""P0-d · khoá phép nhận VAI TRÒ đã siết của pool v5.

VÌ SAO CẦN v5 — và vì sao bài học đáng ghi
------------------------------------------
Ở v4 tôi cố ý để `_vai_tro` nhận diện RỘNG, với lập luận: "đây là bộ lọc để
đưa ứng viên VÀO pool, sai về phía rộng chỉ làm pool to hơn". Lập luận ấy SAI,
và phân xử thật ở P0-d chứng minh bằng số:

    90 ô × nhu cầu không có bảng dùng được trên pool v4
    → tra vào A6: 89/90 slot ĐÃ CÓ bảng đúng vai trò, đúng phạm vi, obs > 0

Hạn ngạch là hữu hạn và được cấp THEO nhu cầu. Một BÁO CÁO LƯU CHUYỂN TIỀN TỆ
bị tính là đã đáp ứng nhu cầu "nửa tài sản của bảng cân đối" (chỉ vì có dòng
"tăng, giảm hàng tồn kho") sẽ **tiêu mất suất** dành cho bảng cân đối thật, và
bảng cân đối thật không bao giờ được gọi vào pool. Nhận diện rộng không chỉ làm
thống kê đẹp lên — nó phân bổ sai.

Bộ test này khoá cả hai phía: bốn đường KHỚP NHẦM phải bị loại, hai đường BỎ
SÓT phải được nhận lại. Cả sáu đều là chuỗi có thật, lấy từ `work.db`.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_pool_v5 import vai_tro_chat  # noqa: E402

# Trích từ `table_cards_fts` thật, rút gọn nhưng giữ nguyên cách viết của A6.
CF_HPG = ("loi nhuan truoc thue | dieu chinh cho cac khoan | khau hao va phan bo "
          "| bien dong hang ton kho | bien dong cac khoan phai thu "
          "| tien chi de mua sam, xay dung tscd va cac tai san dai han khac "
          "| luu chuyen tien thuan tu hoat dong kinh doanh")
CF_VRE = ("tien lai vay da tra | thue thu nhap doanh nghiep da nop "
          "| luu chuyen tien thuan tu hoat dongkinh doanh "      # OCR mất dấu cách
          "| luu chuyen tien tu hoat dong dau tu")
CF_GOP_VON = ("tien thu tu phat hanh co phieu, nhan von gop cua chu so huu "
              "| tien thu tu di vay | luu chuyen tien thuan tu hoat dong tai chinh")
BS_NV_DPM = ("c | i | phai tra nguoi ban ngan han | nguoi mua tra tien truoc ngan han "
             "| thue va cac khoan phai nop nha nuoc | d | i | von gop cua chu so huu "
             "| thang du von co phan | loi nhuan sau thue chua phan phoi")
BS_TS = ("tai san ngan han | tien va cac khoan tuong duong tien | hang ton kho "
         "| tai san dai han | tai san co dinh huu hinh | nguyen gia")
IS_HPG_RIENG = ("doanh thu cung cap dich vu | gia von dich vu cung cap "
                "| loi nhuan gop (20 = 01 - 11) | doanh thu hoat dong tai chinh")
IS_NGAN_HANG = ("thu nhap lai va cac khoan thu nhap tuong tu | thu nhap lai thuan "
                "| lai thuan tu hoat dong dich vu | tong loi nhuan truoc thue "
                "| loi nhuan sau thue")
GIA_VON = ("gia von cac tram thu phi bot | gia von hang ban | gia von xay lap | cong")


# ═════════════════════════════════════════════════════════════════════════════
# 1 · BỐN đường KHỚP NHẦM của v4 — phải bị loại
# ═════════════════════════════════════════════════════════════════════════════

def test_bclctt_khong_duoc_tinh_la_nua_tai_san_vi_co_dong_hang_ton_kho():
    """Đường tốn kém nhất: nó tiêu mất suất của bảng cân đối thật."""
    v = vai_tro_chat("cash_flow", CF_HPG)
    assert "balance_sheet_tai_san" not in v
    assert v == {"cash_flow"}


def test_bclctt_khong_duoc_tinh_la_nua_tai_san_vi_cum_tai_san_dai_han_khac():
    assert "balance_sheet_tai_san" not in vai_tro_chat(
        "cash_flow", "tien chi de mua sam, xay dung tscd va cac tai san dai han khac")


def test_bclctt_khong_duoc_tinh_la_nua_nguon_von_vi_dong_nhan_von_gop():
    assert "balance_sheet_nguon_von" not in vai_tro_chat("cash_flow", CF_GOP_VON)


def test_thuyet_minh_gia_von_khong_duoc_tinh_la_bckqkd():
    """Có `gia von hang ban` nhưng không có doanh thu thuần ⇒ không phải BCKQKD."""
    assert "income_statement" not in vai_tro_chat("note", GIA_VON)


# ═════════════════════════════════════════════════════════════════════════════
# 2 · HAI đường BỎ SÓT — phải được nhận lại
# ═════════════════════════════════════════════════════════════════════════════

def test_nua_nguon_von_dung_ky_hieu_muc_van_duoc_nhan():
    """A6 nhiều khi in tiêu đề mục thành "c" / "i" thay vì "NỢ PHẢI TRẢ".

    DPM/2018 `56221c1e` và DCM/2022 `f9fe8c28` là nửa nguồn vốn thật nhưng không
    có một tiêu đề nào khớp. Nhận bằng chỉ tiêu đặc trưng của nửa ấy.
    """
    assert "balance_sheet_nguon_von" in vai_tro_chat("note", BS_NV_DPM)


def test_bckqkd_bi_gan_nham_nhan_cash_flow_van_duoc_nhan():
    """A6 gán BCKQKD RIÊNG của HPG/2018 (`b545aa2d`) nhãn `cash_flow`.

    Nếu tin `statement_type`, q519 mất vế mẫu số và bị xử oan là thiếu bằng chứng.
    """
    assert "income_statement" in vai_tro_chat("cash_flow", IS_HPG_RIENG)


# ═════════════════════════════════════════════════════════════════════════════
# 3 · các đường đúng phải giữ nguyên
# ═════════════════════════════════════════════════════════════════════════════

def test_bckqkd_ngan_hang_van_duoc_nhan():
    assert "income_statement" in vai_tro_chat("note", IS_NGAN_HANG)


def test_bang_can_doi_nhan_du_ca_hai_nua_khi_bang_gom_ca_hai():
    v = vai_tro_chat("balance_sheet", BS_TS + " | " + BS_NV_DPM)
    assert {"balance_sheet_tai_san", "balance_sheet_nguon_von"} <= v


def test_dong_cfo_bi_mat_dau_cach_do_ocr_van_duoc_nhan():
    """`luu chuyen tien thuan tu hoat dongkinh doanh` — VRE/2023 `5dfd3bf6`."""
    assert "cash_flow" in vai_tro_chat("note", CF_VRE)


def test_thuyet_minh_khong_lien_quan_van_khong_nhan_vai_tro_nao():
    assert vai_tro_chat("note", "chi phi lai vay va cac khoan tuong tu") == set()
