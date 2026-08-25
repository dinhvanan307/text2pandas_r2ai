"""P0-g · KHOÁ engine số học — hồi quy và đối kháng.

VÌ SAO MỖI TEST TỒN TẠI
-----------------------
Mỗi ca dưới đây là một lỗi ĐÃ XẢY RA trong lúc dựng engine, bắt được bằng cách
đọc tay toán hạng chứ không bằng chỉ số tổng. Kiểm tay 8 câu `OK` đầu tiên cho
6 câu lấy nhầm dòng; siết ngưỡng khớp từ 0.60 lên 0.85 rồi kiểm lại 11 câu thì
còn 2 sai. Danh sách:

    q593/q731  `answer != eval(pandas_query)` — cặp (row_path, col_label) không
               duy nhất, `.values[0]` lấy ô khác ô engine đã chọn
    q844       "tỷ trọng ... TRUNG BÌNH ... bao nhiêu %" bị gộp thành số tiền
    q954       chi phí lãi vay DPM dương, HSG âm — cộng hai quy ước dấu
    q705       tử ở bản RIÊNG, mẫu ở bản HỢP NHẤT của cùng công ty/năm
    q822       câu hỏi "công ty mẹ" nhưng lấy bảng hợp nhất
    q749       "chứng khoán ĐẦU TƯ" khớp phải dòng "chứng khoán KINH DOANH"

Bất biến bị khoá: `answer == eval(pandas_query)`, đơn vị chuẩn hoá về VND trước
khi tính, thiếu toán hạng thì `UNCERTAIN` chứ không đoán.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools/so_hoc"))

_spec = importlib.util.spec_from_file_location("p0g_engine", ROOT / "tools/so_hoc/02_engine.py")
E = importlib.util.module_from_spec(_spec)
sys.modules["p0g_engine"] = E
_spec.loader.exec_module(E)


class O:
    """Đứng thay `LongCell` — cùng bốn thuộc tính mà engine dùng."""

    __slots__ = ("row_label", "row_path", "col_label", "value")

    def __init__(self, row, col, val):
        self.row_label = self.row_path = row
        self.col_label = col
        self.value = Decimal(str(val))


def bang(loc, nam, o, mu=None):
    return E.Bang(loc, nam, loc.split("_")[0], o, mu)


CTY = "HPG_financial_statements_2022_consolidated|100"
RIENG = "HPG_financial_statements_2022_separate|100"


# ═════════════════════════════════════════════════════════════════════════════
# 1 · KỲ lấy từ CỘT, không lấy từ `doc_year`
# ═════════════════════════════════════════════════════════════════════════════

def test_ky_lay_tu_cot_khong_lay_tu_nam_tep():
    assert E.nam_cua_cot("Năm trướcTriệu đồng", 2021) == {2020}
    assert E.nam_cua_cot("Năm 2019 VND", 2024) == {2019}      # năm tệp vô can
    assert E.nam_cua_cot("01/01/2024 VND", 2024) == {2023}    # số dư ĐẦU năm


def test_cot_khong_lo_ky_thi_khong_dung_lam_toan_hang():
    """Yêu cầu 8: không xác định được kỳ thì bỏ, không đoán theo `doc_year`."""
    b = bang(CTY, 2022, [O("Doanh thu thuần", "Tổng cộng", 100)])
    assert E.tim_toan_hang("A", ["doanh", "thu", "thuan"], 2022, "HPG", [b]) is None


# ═════════════════════════════════════════════════════════════════════════════
# 2 · CỘT PHI GIÁ TRỊ không bao giờ thành toán hạng
# ═════════════════════════════════════════════════════════════════════════════

def test_cot_ma_so_khong_duoc_lam_toan_hang():
    b = bang(CTY, 2022, [O("Doanh thu thuần", "Mã số", 10),
                         O("Doanh thu thuần", "Năm 2022 VND", 5_000)])
    th = E.tim_toan_hang("A", ["doanh", "thu", "thuan"], 2022, "HPG", [b])
    assert th is not None and th.col_label == "Năm 2022 VND" and th.vnd == 5_000


# ═════════════════════════════════════════════════════════════════════════════
# 3 · ĐƠN VỊ chuẩn hoá về VND TRƯỚC khi tính
# ═════════════════════════════════════════════════════════════════════════════

def test_hai_bang_khac_don_vi_van_tru_dung():
    """A ghi bằng triệu đồng, B ghi bằng đồng. Không quy đổi thì lệch 10^6."""
    a = bang("AAA_financial_statements_2022_consolidated|1", 2022,
             [O("Chi phí lãi vay", "Năm 2022 Triệu VND", 100)])
    b = bang("BBB_financial_statements_2022_consolidated|1", 2022,
             [O("Chi phí lãi vay", "Năm 2022 VND", 40_000_000)])
    kq = E.tinh_difference("Chênh lệch chi phí lãi vay năm 2022 giữa AAA và BBB "
                           "là bao nhiêu triệu đồng?", [a, b], ["AAA", "BBB"],
                           [2022], "trieu")
    assert kq.trang_thai == "OK"
    assert abs(kq.answer - 60.0) < 1e-9        # (100e6 − 40e6) VND = 60 triệu


def test_mu_don_vi_doc_tu_chu_in_trong_bang():
    assert E.mu_don_vi("Triệu VND") == 6
    assert E.mu_don_vi("Năm 2022 VND") == 0
    assert E.mu_don_vi("Số cuối năm") is None      # không khai


# ═════════════════════════════════════════════════════════════════════════════
# 4 · CHIA 0
# ═════════════════════════════════════════════════════════════════════════════

def test_mau_so_bang_0_thi_UNCERTAIN_chu_khong_no():
    b = bang(CTY, 2022, [O("Lợi nhuận gộp", "Năm 2022 VND", 500),
                         O("Doanh thu thuần", "Năm 2022 VND", 0)])
    kq = E.tinh_ratio("Tỷ lệ lợi nhuận gộp trên doanh thu thuần của HPG năm 2022 "
                      "là bao nhiêu %?", [b], "HPG", 2022, "%")
    assert kq.trang_thai == "UNCERTAIN" and "0" in kq.ghi_chu[0]


def test_ky_goc_bang_0_thi_khong_tinh_tang_truong():
    b = bang(CTY, 2022, [O("Doanh thu thuần", "Năm 2021 VND", 0),
                         O("Doanh thu thuần", "Năm 2022 VND", 900)])
    kq = E.tinh_percentage_change("Tăng trưởng doanh thu thuần của HPG từ năm 2021 "
                                  "đến năm 2022 là bao nhiêu %?", [b], "HPG",
                                  [2021, 2022], "%")
    assert kq.trang_thai == "UNCERTAIN"


# ═════════════════════════════════════════════════════════════════════════════
# 5 · ÂM / DƯƠNG
# ═════════════════════════════════════════════════════════════════════════════

def test_tang_truong_am_giu_dung_dau():
    b = bang(CTY, 2022, [O("Doanh thu thuần", "Năm 2021 VND", 1_000),
                         O("Doanh thu thuần", "Năm 2022 VND", 800)])
    kq = E.tinh_percentage_change("Tăng trưởng doanh thu thuần của HPG từ năm 2021 "
                                  "đến năm 2022 là bao nhiêu %?", [b], "HPG",
                                  [2021, 2022], "%")
    assert kq.trang_thai == "OK" and abs(kq.answer + 20.0) < 1e-9


def test_goc_am_van_ra_dau_dung_nho_mau_so_la_tri_tuyet_doi():
    """A = −100 -> B = −50 là TĂNG 50%. Chia cho A (không lấy |A|) sẽ ra −50%."""
    b = bang(CTY, 2022, [O("Lợi nhuận sau thuế", "Năm 2021 VND", -100),
                         O("Lợi nhuận sau thuế", "Năm 2022 VND", -50)])
    kq = E.tinh_percentage_change("Tăng trưởng lợi nhuận sau thuế của HPG từ năm "
                                  "2021 đến năm 2022 là bao nhiêu %?", [b], "HPG",
                                  [2021, 2022], "%")
    assert kq.trang_thai == "OK" and abs(kq.answer - 50.0) < 1e-9


def test_gop_ma_lan_dau_am_duong_thi_UNCERTAIN():
    """q954: chi phí lãi vay dương ở hai công ty, âm ở công ty thứ ba."""
    a = bang("AAA_financial_statements_2018_consolidated|1", 2018,
             [O("Chi phí lãi vay", "Năm 2018 VND", 60)])
    b = bang("BBB_financial_statements_2018_consolidated|1", 2018,
             [O("Chi phí lãi vay", "Năm 2018 VND", -800)])
    kq = E.tinh_gop("Giá trị trung bình chi phí lãi vay của AAA và BBB tại năm 2018 "
                    "theo đơn vị tỷ đồng.", [a, b], ["AAA", "BBB"], [2018], "ty",
                    "average")
    assert kq.trang_thai == "UNCERTAIN" and "dấu" in kq.ghi_chu[0]


# ═════════════════════════════════════════════════════════════════════════════
# 6 · `%` so với số thập phân
# ═════════════════════════════════════════════════════════════════════════════

def test_don_vi_phan_tram_nhan_100_con_don_vi_lan_thi_khong():
    o = [O("Tài sản ngắn hạn", "Năm 2022 VND", 300),
         O("Nợ ngắn hạn", "Năm 2022 VND", 200)]
    cau = "Tỷ lệ tài sản ngắn hạn trên nợ ngắn hạn của HPG năm 2022 là bao nhiêu"
    pc = E.tinh_ratio(cau + " %?", [bang(CTY, 2022, o)], "HPG", 2022, "%")
    lan = E.tinh_ratio(cau + " lần?", [bang(CTY, 2022, o)], "HPG", 2022, "lan")
    assert abs(pc.answer - 150.0) < 1e-9
    assert abs(lan.answer - 1.5) < 1e-9


def test_gop_ma_don_vi_hoi_la_phan_tram_thi_UNCERTAIN():
    """q844: "tỷ trọng vốn chủ sở hữu TRUNG BÌNH ... bao nhiêu %" — cộng số tiền
    rồi chia n cho ra 7,4e12. Đó là câu tỷ lệ bị phân loại nhầm."""
    b = bang(CTY, 2022, [O("Vốn chủ sở hữu", "Năm 2021 VND", 100),
                         O("Vốn chủ sở hữu", "Năm 2022 VND", 200)])
    kq = E.tinh_gop("Tỷ trọng vốn chủ sở hữu trung bình của HPG trong các năm 2021 "
                    "và 2022 là bao nhiêu %?", [b], ["HPG"], [2021, 2022], "%",
                    "average")
    assert kq.trang_thai == "UNCERTAIN"


# ═════════════════════════════════════════════════════════════════════════════
# 7 · HAI NĂM · HAI MÃ
# ═════════════════════════════════════════════════════════════════════════════

def test_chenh_lech_hai_nam_lay_nam_lon_tru_nam_nho():
    b = bang(CTY, 2022, [O("Hàng tồn kho", "Năm 2021 VND", 100),
                         O("Hàng tồn kho", "Năm 2022 VND", 175)])
    kq = E.tinh_difference("Chênh lệch hàng tồn kho của HPG giữa năm 2022 và năm "
                           "2021 là bao nhiêu đồng?", [b], ["HPG"], [2021, 2022],
                           "dong")
    assert kq.trang_thai == "OK" and abs(kq.answer - 75.0) < 1e-9


def test_thu_tu_hai_ma_theo_vi_tri_trong_cau():
    """`chênh lệch A và B` = A − B. Đảo thứ tự là đổi dấu.

    Mã suy từ TÊN phải định vị bằng vị trí của cái tên, không xếp cuối.
    """
    class CI:
        by_ticker = {"VIB": "Ngân hàng TMCP Quốc tế Việt Nam",
                     "SHB": "Ngân hàng TMCP Sài Gòn - Hà Nội"}

        def lookup(self, q):
            return ["VIB", "SHB"]

    q = ("Chênh lệch tiền mặt giữa Ngân hàng TMCP Quốc tế Việt Nam và "
         "Ngân hàng TMCP Sài Gòn - Hà Nội (SHB) là bao nhiêu?")
    assert E.phan_giai_ma(q, CI(), {"VIB", "SHB"}) == ["VIB", "SHB"]


def test_ma_viet_tuong_minh_khong_duoc_nuot_ma_suy_tu_ten():
    """Lỗi RC-2 của `parse_question`: `if literal: ... else: name` làm mất một vế."""
    class CI:
        by_ticker = {"VIB": "Ngân hàng TMCP Quốc tế Việt Nam"}

        def lookup(self, q):
            return ["VIB"]

    q = "Chênh lệch giữa Ngân hàng TMCP Quốc tế Việt Nam và ACB là bao nhiêu?"
    assert set(E.phan_giai_ma(q, CI(), {"VIB", "ACB"})) == {"VIB", "ACB"}


# ═════════════════════════════════════════════════════════════════════════════
# 8 · THIẾU TOÁN HẠNG · LẪN PHẠM VI
# ═════════════════════════════════════════════════════════════════════════════

def test_thieu_mot_ve_thi_UNCERTAIN_chu_khong_bia():
    b = bang(CTY, 2022, [O("Lợi nhuận gộp", "Năm 2022 VND", 500)])
    kq = E.tinh_ratio("Tỷ lệ lợi nhuận gộp trên doanh thu thuần của HPG năm 2022 "
                      "là bao nhiêu %?", [b], "HPG", 2022, "%")
    assert kq.trang_thai == "UNCERTAIN" and kq.answer is None


def test_thieu_mot_ky_thi_khong_gop():
    b = bang(CTY, 2022, [O("Hàng tồn kho", "Năm 2022 VND", 100)])
    kq = E.tinh_gop("Tính tổng hàng tồn kho của HPG cho các năm 2021 và 2022, tính "
                    "bằng tỷ đồng.", [b], ["HPG"], [2021, 2022], "ty", "sum")
    assert kq.trang_thai == "UNCERTAIN" and "2021" in kq.ghi_chu[0]


def test_lan_ban_rieng_va_ban_hop_nhat_thi_UNCERTAIN():
    """q705: tử ở bản riêng, mẫu ở bản hợp nhất — tỷ lệ không có nghĩa kế toán."""
    a = bang(RIENG, 2022, [O("Vay ngắn hạn", "Năm 2022 VND", 400)])
    b = bang(CTY, 2022, [O("Vốn chủ sở hữu", "Năm 2022 VND", 1_700)])
    kq = E.tinh_ratio("Tỷ lệ vay ngắn hạn trên vốn chủ sở hữu của HPG cuối năm 2022 "
                      "là bao nhiêu %?", [a, b], None, 2022, "%")
    assert kq.trang_thai == "UNCERTAIN" and "hợp nhất" in kq.ghi_chu[0]


def test_cau_neu_cong_ty_me_thi_bo_qua_ban_hop_nhat():
    hn = bang(CTY, 2022, [O("Hàng tồn kho", "Năm 2022 VND", 999)])
    assert E.tim_toan_hang("A", ["hang", "ton", "kho"], 2022, "HPG", [hn],
                           "separate") is None


# ═════════════════════════════════════════════════════════════════════════════
# 9 · bất biến `answer == eval(pandas_query)`
# ═════════════════════════════════════════════════════════════════════════════

def test_query_sinh_ra_chay_lai_dung_bang_answer():
    b = bang(CTY, 2022, [O("Lợi nhuận gộp", "Năm 2022 Triệu VND", 500),
                         O("Doanh thu thuần", "Năm 2022 Triệu VND", 2_000)])
    kq = E.tinh_ratio("Tỷ lệ lợi nhuận gộp trên doanh thu thuần của HPG năm 2022 "
                      "là bao nhiêu %?", [b], "HPG", 2022, "%")
    assert kq.trang_thai == "OK"

    class Cot:
        def __init__(self, v):
            self.values = [v]

    class DF:
        def __init__(self, o):
            self.o = o

        def __getitem__(self, k):
            if isinstance(k, list):
                return DF([x for x, giu in zip(self.o, k) if giu])
            if k == "row_path":
                return [x.row_path for x in self.o]
            if k == "col_label":
                return [x.col_label for x in self.o]
            if k == "value":
                return Cot(float(self.o[0].value))
            raise KeyError(k)

    # mô phỏng `df[(df['a'] == x) & (df['b'] == y)]['value'].values[0]`
    class Cot2(list):
        def __eq__(self, other):
            return Cot2(x == other for x in self)   # phải trả Cot2 để `&` dùng được

        def __and__(self, other):
            return Cot2(a and b for a, b in zip(self, other))

        __hash__ = None

    class DF2(DF):
        def __getitem__(self, k):
            if isinstance(k, str) and k in ("row_path", "col_label"):
                return Cot2(super().__getitem__(k))
            return super().__getitem__(k)

    env = {"df1": DF2(b.rows)}
    gt = eval(kq.pandas_query, {"float": float, "abs": abs}, env)
    assert abs(gt - kq.answer) < 1e-9
