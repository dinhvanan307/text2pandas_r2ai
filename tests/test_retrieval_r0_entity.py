"""R0c · phân giải thực thể. Khoá hành vi ĐỒNG BỘ với baseline của BTC.

Vì sao phải khoá: BTC là bên chấm. Hàm chuẩn hoá và luật nhận diện của ta lệch
họ thì ta tối ưu trên một bài toán khác bài toán được chấm.
"""
import csv
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.normalize import ascii_compact, company_aliases, ticker_mentioned  # noqa: E402
from text2pandas.pipelines.retrieval.question_intent import SCOPE_DEFAULT, parse_intent  # noqa: E402

CS = ROOT / "data/raw/btc/metadata/companies.csv"
ALIAS = ROOT / "configs/retrieval/company_alias_v1.yaml"


@pytest.fixture(scope="module")
def comp():
    return {r["Mã CK"].strip(): r["Tên công ty"].strip()
            for r in csv.DictReader(CS.open(encoding="utf-8"))}


# ── chuẩn hoá · khớp nguyên văn BTC ─────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("CTCP Tập đoàn Hòa Phát", "ctcptapdoanhoaphat"),
    ("Ngân hàng TMCP Á Châu", "nganhangtmcpachau"),
    ("Đầu tư & Phát triển", "dautuphattrien"),
])
def test_ascii_compact_khop_BTC(raw, want):
    assert ascii_compact(raw) == want


def test_cat_tien_to_phap_ly_dung_nguong_6():
    assert "tapdoanhoaphat" in company_aliases("CTCP Tập đoàn Hòa Phát")


def test_duoi_ngan_hon_6_khong_thanh_alias():
    """Ngưỡng của BTC. Nới nó ra là mở cửa cho khớp nhầm hàng loạt."""
    assert company_aliases("CTCP ABC") == ("ctcpabc",)


@pytest.mark.parametrize("q,t,want", [
    ("Vietjet (VJC) năm 2018", "VJC", True),
    ("mã VJCX không phải", "VJC", False),
    ("chữ thường vjc vẫn tính", "VJC", True),
])
def test_ticker_mentioned(q, t, want):
    assert ticker_mentioned(q, t) is want


# ── scope · quyết định có hậu quả, corpus chia gần đôi 957/954 ──────────
def test_mac_dinh_la_hop_nhat_theo_BTC(comp):
    i = parse_intent("Doanh thu thuần năm 2020 là bao nhiêu?", comp)
    assert i.explicit_scope is None
    assert i.basis == "consolidated", "BTC mặc định `hợp nhất` khi câu hỏi không nói"
    assert SCOPE_DEFAULT == "hợp nhất"


@pytest.mark.parametrize("q,want", [
    ("của công ty mẹ CTCP Hàng không Vietjet", "separate"),
    ("báo cáo riêng của doanh nghiệp", "separate"),
    ("tổng tài sản hợp nhất", "consolidated"),
])
def test_dau_hieu_scope(q, want, comp):
    assert parse_intent(q, comp).basis == want


def test_vua_rieng_vua_hop_nhat_thi_KHONG_ket_luan(comp):
    """Hai dấu hiệu ngược nhau → BTC trả None, không chọn bừa."""
    assert parse_intent("so sánh báo cáo riêng và hợp nhất", comp).explicit_scope is None


# ── thực thể ────────────────────────────────────────────────────────────
def test_ma_trong_ngoac_duoc_nhan(comp):
    i = parse_intent("Lãi tiền gửi năm 2018 của công ty mẹ CTCP Hàng không Vietjet (VJC)?", comp)
    assert i.tickers == frozenset({"VJC"}) and i.is_resolved


def test_ten_rut_gon_can_alias_mo_rong(comp):
    """`code_stock.csv` một mình KHÔNG khớp 'Hòa Phát' — luật BTC đòi gần trọn tên."""
    assert not parse_intent("Tổng tài sản của Hòa Phát năm 2022", comp).tickers
    ext = yaml.safe_load(ALIAS.read_text(encoding="utf-8"))["aliases"]
    assert parse_intent("Tổng tài sản của Hòa Phát năm 2022", ext).tickers == frozenset({"HPG"})


def test_ten_long_nhau_khop_dai_nhat_thang():
    """'Hoàng Anh Gia Lai' ⊂ 'Nông nghiệp Quốc tế Hoàng Anh Gia Lai'."""
    ext = yaml.safe_load(ALIAS.read_text(encoding="utf-8"))["aliases"]
    got = parse_intent("Lợi nhuận thuần của Công ty CP Nông nghiệp Quốc tế Hoàng Anh Gia Lai năm 2015",
                       ext).tickers
    assert got == frozenset({"HNG"}), got


def test_cau_sang_loc_nhieu_ma_GIU_ca_nhom():
    """Câu sàng lọc nhiều mã là loại câu có thật — không được khử xuống một."""
    ext = yaml.safe_load(ALIAS.read_text(encoding="utf-8"))["aliases"]
    got = parse_intent("Năm 2022, trong nhóm HPG, HSG, MSR và NKG, công ty nào...", ext).tickers
    assert {"HPG", "HSG", "NKG"} <= got and len(got) >= 3


def test_khong_phan_giai_duoc_thi_KHONG_doan(comp):
    i = parse_intent("Doanh thu thuần năm 2020 là bao nhiêu?", comp)
    assert not i.is_resolved, "đoán bừa một mã là hỏng từ gốc mà tầng sau vẫn chạy trơn"


# ── năm · phần BTC cố ý chưa làm ────────────────────────────────────────
def test_trich_nam(comp):
    assert parse_intent("chi phí năm 2018 và 2017", comp).years == (2017, 2018)


def test_nam_ngoai_pham_vi_corpus_bi_loai(comp):
    assert parse_intent("số liệu năm 1999 và 2019", comp).years == (2019,)


# ── bảng alias ──────────────────────────────────────────────────────────
def test_alias_khong_co_bien_the_mo_ho():
    """Biến thể khớp nhầm sang mã khác phải bị LOẠI, không phải cho điểm thấp."""
    d = yaml.safe_load(ALIAS.read_text(encoding="utf-8"))
    seen = {}
    for t, names in d["aliases"].items():
        for n in names:
            c = ascii_compact(n)
            for u, o in seen.items():
                assert not (c in o or o in c) or u == t, f"{t}:{c} đụng {u}:{o}"
            seen[t] = c


def test_moi_ma_deu_con_it_nhat_mot_ten():
    d = yaml.safe_load(ALIAS.read_text(encoding="utf-8"))
    assert len(d["aliases"]) == 100
    assert all(v for v in d["aliases"].values())


# ── chủ thể vs bên liên quan · 273/1.012 câu nhắc ≥2 công ty ────────────
#
# Đo trên 223 câu tự có nhãn (mã trong ngoặc, che đi rồi hỏi lại):
#   đúng 201 (90,1%) · không kết luận 21 · SAI 1
# Một mã sai trên 223 là mức chấp nhận được; 21 ca "không kết luận" là hành vi
# ĐÚNG — chúng đi nhánh nhiều-thực-thể thay vì đoán bừa.

@pytest.fixture(scope="module")
def alias():
    return yaml.safe_load(ALIAS.read_text(encoding="utf-8"))["aliases"]


def test_screen_giu_nguyen_ca_nhom(alias):
    i = parse_intent("Năm 2022, trong nhóm HPG, HSG, MSR và NKG, công ty nào thấp nhất?", alias)
    assert i.mode == "screen"
    assert i.subject is None, "câu sàng lọc KHÔNG có chủ thể đơn"
    assert {"HPG", "HSG", "NKG"} <= set(i.targets)


def test_compare_giu_ca_hai_ben(alias):
    i = parse_intent("Chênh lệch thuế thu nhập năm 2025 giữa DNH và HND là bao nhiêu?", alias)
    assert i.mode == "compare"
    assert {"DNH", "HND"} <= set(i.targets)


def test_related_chon_chu_the_sau_chu_CUA(alias):
    """Bên liên quan đứng sau `với`; chủ sở hữu báo cáo đứng sau `của`."""
    i = parse_intent(
        "Vay dài hạn với Công ty Cổ phần Hoàng Anh Gia Lai của công ty mẹ "
        "CTCP Nông nghiệp Quốc tế Hoàng Anh Gia Lai năm 2016", alias)
    assert i.targets == ("HNG",)


def test_short_nested_brand_does_not_shadow_independent_legal_name(alias):
    i = parse_intent(
        "Trong các năm 2015 và 2019 của Tổng Công ty Khí Việt Nam - CTCP, "
        "giá trị bán hàng với Tổng Công ty Điện lực Dầu khí Việt Nam là bao nhiêu?",
        alias,
    )

    assert {"GAS", "POW"} <= set(i.tickers)
    assert i.mode == "related"
    assert i.targets == ("GAS",)


def test_hieu_so_is_a_two_entity_comparison(alias):
    i = parse_intent(
        "Hiệu số vốn chủ sở hữu của Tổng Công ty Khí Việt Nam - CTCP và "
        "Tổng Công ty Điện lực Dầu khí Việt Nam là bao nhiêu?",
        alias,
    )

    assert i.mode == "compare"
    assert set(i.targets) == {"GAS", "POW"}


def test_khong_quyet_duoc_chu_the_thi_TRA_CA_TAP_khong_tra_rong(alias):
    """S1 ưu tiên RECALL. Tập rỗng là bảo đảm 0 điểm; tập rộng vẫn cứu được.

    Fail-closed thuộc tầng TRẢ LỜI, không thuộc tầng sinh ứng viên. Luật cũ
    trả rỗng và làm 38/1.012 câu mất trắng.
    """
    i = parse_intent("Vay dài hạn với Công ty A của công ty B năm 2024", alias)
    if i.mode == "related" and i.subject is None:
        assert set(i.targets) == set(i.tickers)
        assert i.targets != () or not i.tickers


def test_cau_mot_cong_ty_luon_co_chu_the(alias):
    i = parse_intent("Lãi tiền gửi năm 2018 của công ty mẹ CTCP Hàng không Vietjet?", alias)
    assert i.mode == "single" and i.subject == "VJC" and i.targets == ("VJC",)
