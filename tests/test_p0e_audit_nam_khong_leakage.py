"""P0-e · KHOÁ tính TRUNG LẬP của gold audit năm, và khoá năm lỗi đã bắt được.

VÌ SAO FILE NÀY TỒN TẠI
-----------------------
docs/87 kết luận `BLOCKED` vì cả hai đặc trưng được đề xuất cho S3 đều được đo
trên một tập gold đã bị chính chúng định hình. P0-e dựng lại gold cho trục NĂM
theo cách trung lập. Nhưng "trung lập" là một *tuyên bố*, và tuyên bố thì phải
kiểm được — nếu không thì P0-e chỉ là vòng tròn thứ hai.

Điều kiện trung lập cần chứng minh, và mỗi điều được một test khoá lại:

  (1) Phép phân xử KHÔNG được là `doc_year == năm hỏi` trá hình.
      → với tiêu đề TUYỆT ĐỐI, kết quả phải KHÔNG đổi dù truyền năm báo cáo nào
      → với tiêu đề TƯƠNG ĐỐI, "Năm trước" phải cho năm KHÁC năm báo cáo

  (2) Phép phân xử phải CÓ THỂ sinh ra nhãn `doc_year != năm hỏi`.
      → chứng cứ dương: báo cáo 2021 trả lời được câu hỏi 2020

  (3) Phép phân xử không được đọc `doc_year` hay `periods` của A6.
      → kiểm cấu trúc trên chính mã nguồn

Nhóm test cuối khoá NĂM lỗi mà bước kiểm tay đã bắt. Cả năm đều làm bảng đúng
bị loại oan, và cả năm đều thuộc một kiểu: quy tắc đọc chữ mà không lường được
cách OCR thật sự in ra.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGUON = ROOT / "tools/audit_nam/03_phan_xu_ky.py"

_spec = importlib.util.spec_from_file_location("p0e_phan_xu_ky", NGUON)
px = importlib.util.module_from_spec(_spec)
sys.modules["p0e_phan_xu_ky"] = px
_spec.loader.exec_module(px)


def nam(tieu_de, dong2=(), nhan=(), nam_tep=2021):
    return px.nam_cua_cot(list(tieu_de), list(dong2), list(nhan), nam_tep)[0]


# ═════════════════════════════════════════════════════════════════════════════
# 1 · KHÔNG phải `doc_year == năm hỏi` trá hình
# ═════════════════════════════════════════════════════════════════════════════

def test_tieu_de_tuyet_doi_khong_phu_thuoc_nam_bao_cao():
    """Cột ghi rõ "Năm 2019 | Năm 2018" thì năm báo cáo không được ảnh hưởng gì.

    Nếu phép phân xử lén dùng năm báo cáo, đổi tham số này sẽ đổi kết quả.
    """
    td = ["CHỈ TIÊU", "Năm 2019 VND", "Năm 2018 VND"]
    assert nam(td, nam_tep=2019) == {2018, 2019}
    assert nam(td, nam_tep=2024) == {2018, 2019}
    assert nam(td, nam_tep=1999) == {2018, 2019}


def test_nhan_tuong_doi_cho_nam_KHAC_nam_bao_cao():
    """"Năm trước" trong báo cáo 2021 phải là 2020 — ngược dấu với vị từ đang đo."""
    v = nam(["", "Năm nayTriệu đồng", "Năm trướcTriệu đồng"], nam_tep=2021)
    assert v == {2020, 2021}
    assert 2020 in v, "năm liền trước phải được nhận, nếu không thì đây là doc_year trá hình"


def test_so_dau_nam_tro_ve_nam_lien_truoc():
    assert nam(["", "31/12/2024 VND", "01/01/2024 VND"], nam_tep=2024) == {2023, 2024}


# ═════════════════════════════════════════════════════════════════════════════
# 2 · chứng cứ dương: sinh được nhãn mà gold cũ bị cấm có
# ═════════════════════════════════════════════════════════════════════════════

def test_bao_cao_2021_tra_loi_duoc_cau_hoi_2020():
    """EIB/2021 thuyết minh 23 có cột "Năm trước" = 2020 — chính là q105.

    Gold cũ không thể chứa bảng này (quy tắc docs/82 cấm), gold audit thì có.
    """
    v = nam(["", "Năm nayTriệu đồng", "Năm trướcTriệu đồng"], nam_tep=2021)
    nam_hoi, _ = px.nam_duoc_hoi(
        "Lãi thuần từ hoạt động dịch vụ của Ngân hàng TMCP Xuất nhập khẩu "
        "Việt Nam năm 2020 là bao nhiêu triệu đồng?", [2020])
    assert set(nam_hoi) & v == {2020}


# ═════════════════════════════════════════════════════════════════════════════
# 3 · không đọc trường dẫn xuất của A6
# ═════════════════════════════════════════════════════════════════════════════

def test_ma_nguon_phan_xu_khong_dung_doc_year_hay_periods():
    """Kiểm cấu trúc: hai trường đang được đánh giá không được xuất hiện như NGUỒN.

    `doc_year` chỉ được phép có mặt trong phần chú thích giải thích vì sao không
    dùng nó; ở đây ta cấm mọi truy cập kiểu `["doc_year"]` / `.periods`.
    """
    import ast

    cay = ast.parse(NGUON.read_text(encoding="utf-8"))
    for nut in ast.walk(cay):                 # bỏ chú thích và mọi chuỗi văn bản
        if isinstance(nut, ast.Constant) and isinstance(nut.value, str):
            nut.value = ""
    ma = ast.unparse(cay)
    for cam in ("doc_year", "periods", "table_cards", "sources", "score", "rank"):
        assert cam not in ma, f"phan xu khong duoc doc {cam}"


# ═════════════════════════════════════════════════════════════════════════════
# 4 · quy về năm ở phía CÂU HỎI
# ═════════════════════════════════════════════════════════════════════════════

def test_dau_nam_quy_ve_nam_lien_truoc():
    ra, ly = px.nam_duoc_hoi("Chi phí trả trước của HBC đầu năm 2018 là bao nhiêu?", [2018])
    assert ra == [2017] and "dau nam" in ly


def test_cuoi_nam_giu_nguyen():
    assert px.nam_duoc_hoi("... cuối năm 2021 là bao nhiêu?", [2021])[0] == [2021]


def test_giai_doan_duoc_no_ra_het_khoang():
    ra, ly = px.nam_duoc_hoi("Trong giai đoạn 2018–2024 của HPG ...", [2018, 2024])
    assert ra == [2018, 2019, 2020, 2021, 2022, 2023, 2024] and "no ra" in ly


# ═════════════════════════════════════════════════════════════════════════════
# 5 · NĂM lỗi mà kiểm tay đã bắt — mỗi lỗi làm bảng đúng bị loại oan
# ═════════════════════════════════════════════════════════════════════════════

def test_ocr_dinh_don_vi_vao_nam_van_doc_duoc():
    """`\\b` sau chữ số bị chặn bởi `V` trong "2021VND"."""
    assert nam(["", "2021VND", "2020VND"], nam_tep=2021) == {2020, 2021}


def test_tieu_de_trai_qua_HAI_dong_phai_duoc_gop():
    """VPI/2025 `1906`: "Năm nay" ở dòng 1, "Năm trước" ở dòng 2."""
    assert nam(["", "Năm nay", "Đơn vị tính: VND"], ["Năm trước"], nam_tep=2025) \
        == {2024, 2025}


def test_bang_bien_dong_dat_ky_o_NHAN_DONG():
    """CTG/2019 `3df582ad`: cột là loại dự phòng, kỳ nằm ở nhãn dòng."""
    v = nam(["", "Dự phòng chung", "Dự phòng cụ thể", "Tổng cộng"],
            ["Số dư tại ngày 1 tháng 1 năm 2019", "6.768.218"],
            ["Số dư tại ngày 1 tháng 1 năm 2019", "Dự phòng trích lập trong năm",
             "Số dư tại ngày 31 tháng 12 năm 2019"], nam_tep=2019)
    assert 2019 in v, "cột 31/12/2019 ở nhãn dòng phải được nhận"


def test_trich_dan_hanh_chinh_khong_phai_ky():
    """ABB/2020 `448` (số giấy phép) và MML/2023 `950` (số thông tư)."""
    assert nam(["Tên công ty", "Giấy phép kinh doanh"],
               ["Công ty ABBA", "Giấy phép Kinh doanh số 0104 ngày 1 tháng 6 năm 2010"],
               nam_tep=2020) == set()
    assert nam(["", "Mẫu B 09 – DN/HN(Ban hành theo Thông tư số 202/2014/TT-BTC"
                    "ngày 22 tháng 12 năm 2014)"], nam_tep=2023) == set()


def test_cot_phat_sinh_trong_nam_la_ky_cua_bao_cao():
    """DNH/2025 `919`: "Số phải nộp trong năm" là số phát sinh 2025."""
    assert 2025 in nam(["", "Số đầu năm", "Số phải nộp trong năm"], nam_tep=2025)


def test_ocr_dinh_chu_van_nhan_duoc_so_du_dau_nam():
    """MBB/2019 `1523` in "Số dưđầu nămtriệu đồng" — không có dấu cách."""
    v = nam(["", "Số dưđầu nămtriệu đồng", "Phát sinh trong năm",
             "Số dưcuối nămtriệu đồng"], nam_tep=2019)
    assert v == {2018, 2019}


# ═════════════════════════════════════════════════════════════════════════════
# 6 · bất đối xứng có chủ định: nhãn dòng chứng minh CÓ, không chứng minh KHÔNG
# ═════════════════════════════════════════════════════════════════════════════

def test_nam_roi_trong_nhan_dong_khong_duoc_tinh_la_ky():
    """"Trái phiếu đáo hạn 2025" không biến bảng thành bảng của kỳ 2025."""
    assert nam(["Chỉ tiêu", "Giá trị"], [], ["Trái phiếu đáo hạn 2025"],
               nam_tep=2020) == set()
