"""Regression contract for entity-resolution defects found in `docs/82` §4.

Bộ test này chia làm hai loại, và sự phân biệt là chủ ý:

  · **Test cơ chế** — khẳng định một sự thật về code hiện tại (`ascii_compact`
    xoá khoảng trắng, `company_aliases` cắt tiền tố ở ngưỡng 6 ký tự…). Chúng
    xanh bây giờ và phải xanh mãi, vì chúng mô tả hợp đồng chứ không mô tả lỗi.

  · **Regression tests** — khóa hành vi đã sửa: word-boundary aliases, hợp nhất
    explicit ticker với company-name matches và `chênh lệch với` là comparison.

Alias dùng ở đây chép nguyên văn từ `configs/retrieval/company_alias_v1.yaml`
và `company_brand_v1.yaml` (chép chứ không nạp, để test chạy được ở mọi máy kể
cả khi chưa có tệp cấu hình).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.normalize import (ascii_compact,  # noqa: E402
                                 company_aliases, ticker_mentioned)
from text2pandas.pipelines.retrieval.question_intent import parse_intent  # noqa: E402
from text2pandas.pipelines.retrieval.subject import QuestionMode, classify, _plain  # noqa: E402

# Chép từ configs/retrieval/company_alias_v1.yaml (+ brand_v1 cho ABB).
ALIAS = {
    "ABB": ["Ngân hàng TMCP An Bình", "an binh", "ABBank"],
    "ASM": ["CTCP Tập đoàn Sao Mai", "sao mai"],
    "BID": ["Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
            "dau tu va phat trien viet nam", "dau tu va phat trien", "BIDV"],
    "DBC": ["dabaco", "Dabaco"],
    "DCM": ["phan bon dau khi ca mau", "Phân bón Dầu khí Cà Mau"],
    "DPM": ["phan bon va hoa chat dau khi"],
    "GAS": ["Tổng Công ty Khí Việt Nam - CTCP", "PV GAS", "Khí Việt Nam"],
    "GEG": ["CTCP Điện Gia Lai", "dien gia lai"],
    "GVR": ["cong nghiep cao su viet nam"],
    "MSN": ["CTCP Tập đoàn Masan"],
    "OGC": ["CTCP Tập đoàn Đại Dương", "dai duong"],
    "SHB": ["Ngân hàng TMCP Sài Gòn - Hà Nội", "sai gon ha noi"],
    "VIB": ["Ngân hàng TMCP Quốc tế Việt Nam", "quoc te viet nam", "VIB Bank"],
    "VNM": ["Vinamilk"],
    # TIX cố ý VẮNG MẶT — xem `test_tix_khong_ton_tai_trong_bang_alias`.
}

Q429 = ("Năm 2024, khi rà soát hiệu suất tài sản cố định của các doanh nghiệp "
        "thực phẩm (Tập đoàn Sao Mai; Tập đoàn DABACO; Masan; Tập đoàn Đại "
        "Dương; Vinamilk), trong nhóm có vòng quay tài sản cố định thấp hơn "
        "trung vị ngành, doanh nghiệp có bình quân tài sản cố định thuần lớn "
        "nhất đang tạo doanh thu bằng bao nhiêu lần bình quân tài sản cố định "
        "thuần?")
Q542 = ("Trong số CTCP Phân bón Dầu khí Cà Mau, Tổng CTCP Phân bón và Hóa chất "
        "Dầu khí, Tập đoàn Công nghiệp Cao su Việt Nam và CTCP Sản xuất Kinh "
        "doanh Xuất nhập khẩu Dịch vụ và Đầu tư Tân Bình, mức thay đổi trung "
        "bình từ năm 2021 đến năm 2022 của tỷ lệ lợi nhuận gộp trên doanh thu "
        "thuần tại các công ty có doanh thu thuần năm 2022 tăng so với năm "
        "2021 là bao nhiêu điểm phần trăm?")
Q791 = ("Cuối năm 2017, giá trị thuần của nguyên vật liệu của Tổng Công ty Khí "
        "Việt Nam cao hơn của CTCP Điện Gia Lai (GEG) bao nhiêu tỷ đồng?")
Q774 = ("Chênh lệch giữa số dư tiền mặt và vàng của công ty mẹ Ngân hàng TMCP "
        "Quốc tế Việt Nam và công ty mẹ Ngân hàng TMCP Sài Gòn - Hà Nội (SHB) "
        "vào cuối năm 2022 là bao nhiêu triệu đồng?")
Q790 = ("Cuối năm 2023, tỉ trọng dư nợ ngành công nghiệp chế biến, chế tạo "
        "trên BCTC riêng của VIB chênh lệch bao nhiêu phần trăm so với BIDV?")
Q767 = ("Giá trị tiền và các khoản tương đương tiền của công ty mẹ CTCP Tập "
        "đoàn Đức Long Gia Lai chênh lệch với công ty mẹ Tổng Công ty Cảng "
        "Hàng không Việt Nam đến ngày 31/12/2015 là bao nhiêu nghìn tỷ đồng?")


# ═════════════════════════════════════════════════════════════════════════════
# A · CƠ CHẾ — alias khớp bằng CHUỖI CON, không neo biên từ
# ═════════════════════════════════════════════════════════════════════════════

def test_alias_ngan_khop_chuoi_con_khong_neo_bien_tu():
    """Gốc của cả hai ca `→ ABB`.

    `ascii_compact` xoá mọi ký tự không alnum, rồi `parse_intent` kiểm tra
    `alias in compact`. Không có neo biên từ ở BẤT KỲ đâu trong chuỗi ấy, nên
    một alias 6 ký tự như `anbinh` khớp vào giữa `tanbinh` và `lanbinhquan`.
    Bỏ dấu mà vẫn giữ khoảng trắng CŨNG KHÔNG cứu được: `an binh` vẫn là chuỗi
    con của `tan binh`. Thứ duy nhất cứu được là neo biên từ.
    """
    assert company_aliases("an binh") == ("anbinh",)
    assert "anbinh" in ascii_compact("… Dịch vụ và Đầu tư Tân Bình, mức …")
    assert "anbinh" in ascii_compact("… bằng bao nhiêu lần bình quân tài sản …")
    # giữ khoảng trắng vẫn không đủ
    assert "an binh" in _plain("Đầu tư Tân Bình")
    # neo biên từ thì đủ
    import re
    assert not re.search(r"\ban binh\b", _plain("Đầu tư Tân Bình"))
    assert re.search(r"\ban binh\b", _plain("Ngân hàng An Bình"))


def test_q542_word_boundary_prevents_abb_from_swallowing_tan_binh():
    it = parse_intent(Q542, ALIAS)
    assert "ABB" not in it.tickers
    assert it.tickers == {"DCM", "DPM", "GVR"}
    assert it.resolved_by == "company_name"


def test_q429_word_boundary_prevents_abb_from_matching_binh_quan():
    it = parse_intent(Q429, ALIAS)
    assert "ABB" not in it.tickers


def test_q429_msn_khong_khop_vi_alias_qua_dai():
    """Nguyên nhân THỨ HAI của q429, độc lập với ABB.

    Alias duy nhất của MSN là tên pháp lý; `company_aliases` cắt được `ctcp`
    còn lại `tapdoanmasan`. Câu hỏi viết trần `Masan`, nên không có mẫu nào
    khớp. Đây là thiếu hụt PHỦ, không phải khớp nhầm — và hai lỗi này cộng dồn
    trên cùng một câu.
    """
    assert company_aliases("CTCP Tập đoàn Masan") == ("ctcptapdoanmasan",
                                                      "tapdoanmasan")
    assert "tapdoanmasan" not in ascii_compact(Q429)
    assert "MSN" not in parse_intent(Q429, ALIAS).tickers


def test_tix_khong_ton_tai_trong_bang_alias():
    """Và đó là ĐÚNG: TIX có 0 tài liệu trong A6 (kiểm bằng `work.db`).

    Bảng alias phủ đúng 100 mã của A6. Nên khuyết tật của q542 không phải
    "thiếu alias cho TIX" mà là "ABB được nhận thay chỗ trống" — nếu không có
    lỗi chuỗi con, câu này lẽ ra chỉ còn 3 mã và vẫn phân xử được.
    """
    assert "TIX" not in ALIAS


# ═════════════════════════════════════════════════════════════════════════════
# B · CƠ CHẾ — nhánh `explicit ticker` nuốt trọn nhánh `company_name`
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("q,ma_ten,ma_ticker", [
    (Q791, "GAS", "GEG"),
    (Q774, "VIB", "SHB"),
    (Q790, "BID", "VIB"),
])
def test_explicit_ticker_and_company_name_matches_are_merged(q, ma_ten, ma_ticker):
    """One explicit ticker must not erase the company named on the other side."""
    comp = ascii_compact(q)
    assert any(a in comp for n in ALIAS[ma_ten] for a in company_aliases(n)), \
        "alias không khớp — nếu vậy đây là lỗi bảng alias, không phải lỗi nhánh"
    assert ticker_mentioned(q, ma_ticker)
    it = parse_intent(q, ALIAS)
    assert it.resolved_by == "ticker_and_company_name"
    assert {ma_ten, ma_ticker} <= set(it.targets)


def test_bidv_khong_duoc_tinh_la_nhac_ma_bid():
    """Chi tiết dễ hiểu nhầm ở q790: `BIDV` KHÔNG kích hoạt `ticker_mentioned`
    cho `BID`, vì `V` đứng ngay sau làm hỏng neo `(?![A-Z0-9])`. Nó khớp qua
    alias TÊN `BIDV` — tức đúng nhánh bị nhánh ticker loại bỏ."""
    assert not ticker_mentioned(Q790, "BID")
    assert "bidv" in ascii_compact(Q790)


# ═════════════════════════════════════════════════════════════════════════════
# C · CƠ CHẾ — `chênh lệch với` không nằm trong bộ mẫu `compare`
# ═════════════════════════════════════════════════════════════════════════════

def test_chenh_lech_voi_is_a_comparison():
    p = _plain(Q767)
    assert "chenh lech voi" in p
    assert "chenh lech giua" not in p and " giua " not in f" {p} "
    assert classify(Q767, 2) == QuestionMode.COMPARE
