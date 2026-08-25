"""RC-05 · chỉ mục toàn văn phải tìm được chữ `đ`.

Audit A-06. `unicode61 remove_diacritics 2` của SQLite gập được MỌI dấu tiếng
Việt trừ đúng một ký tự: `đ` (U+0111). Nó không phải `d` + dấu phụ mà là một
code point riêng, nên NFD không tách được và bộ lọc combining mark không chạm
tới.

Đo trên RC1 (146.246 thẻ):

    đồng         104.792 có dấu →     997 không dấu   mất 99,0%
    đầu tư        63.407          →     289           mất 99,5%
    tương đương   10.496          →      12           mất 99,9%
    tiền          65.190          →  65.190           mất  0,0%
    chi phí       47.112          →  47.112           mất  0,0%

Lỗi nằm ở đúng một ký tự — và 96,4% thẻ chứa nó ở ít nhất một trường được
đánh chỉ mục.

Bộ kiểm này đi qua ĐÚNG đường mà `release.py` dùng: cùng DDL, cùng hàm SQL
`norm_search`. Kiểm bằng cách tự viết chuỗi đã chuẩn hoá vào bảng thì không
chứng minh được gì về đường dựng thật.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_pipeline.release_schema import (  # noqa: E402
    FTS_CONTENT, FTS_TOKENIZER, RELEASE_FTS_DDL)
from data_pipeline.text_normalize import (  # noqa: E402
    NORMALIZE_VERSION, fts_match_expr, normalize_search_text)

# Văn bản thật, lấy từ nhãn phổ biến nhất của corpus.
CARDS = [
    ("T1", "VCB", "5 TIỀN VÀ TƯƠNG ĐƯƠNG TIỀN",
     "Tiền mặt tại quỹ | Tiền gửi ngân hàng | Các khoản tương đương tiền",
     "Tiền mặt | Tương đương tiền", "31/12/2023 | 31/12/2022 | Đồng Việt Nam"),
    ("T2", "VNM", "9 ĐẦU TƯ TÀI CHÍNH DÀI HẠN",
     "Đầu tư vào công ty liên kết | Đầu tư nắm giữ đến ngày đáo hạn",
     "Đầu tư dài hạn", "Năm nay | Năm trước"),
    ("T3", "HPG", "12 CHI PHÍ TRẢ TRƯỚC",
     "Chi phí trả trước ngắn hạn | Chi phí lãi vay",
     "Chi phí", "31/12/2023"),
]


@pytest.fixture
def fts():
    """Dựng chỉ mục ĐÚNG NHƯ `release.py`: cùng DDL, cùng UDF `norm_search`."""
    con = sqlite3.connect(":memory:")
    con.executescript(RELEASE_FTS_DDL)
    con.create_function("norm_search", 1,
                        lambda s: normalize_search_text(s or ""),
                        deterministic=True)
    con.executemany(
        "INSERT INTO table_cards_fts VALUES(?,?,norm_search(?),norm_search(?),"
        "norm_search(?),norm_search(?))", CARDS)
    con.commit()
    yield con
    con.close()


def _hits(con, expr):
    return {r[0] for r in con.execute(
        "SELECT table_uid FROM table_cards_fts WHERE table_cards_fts MATCH ?",
        (expr,))}


# ── lỗi RC1, nay phải hết ───────────────────────────────────────────────────

@pytest.mark.parametrize("plain, want", [
    ("dong", {"T1"}),            # `đồng` — 99,0% thẻ bị mất ở RC1
    ("dau tu", {"T2"}),          # `đầu tư` — 99,5%
    ("tuong duong", {"T1"}),     # `tương đương` — 99,9%
    ("dao han", {"T2"}),         # `đáo hạn` — `đ` ở giữa cụm
    ("dai han", {"T2"}),
])
def test_go_khong_dau_tim_duoc_chu_d_gach(fts, plain, want):
    assert _hits(fts, fts_match_expr(plain)) == want


@pytest.mark.parametrize("accented, plain", [
    ("Tiền và tương đương tiền", "tien va tuong duong tien"),
    ("ĐẦU TƯ DÀI HẠN", "dau tu dai han"),
    ("Chi phí trả trước", "chi phi tra truoc"),
])
def test_co_dau_va_khong_dau_cho_CUNG_ket_qua(fts, accented, plain):
    """Đây là lời hứa mà tài liệu RC1 đã ghi nhưng gói không giữ được."""
    assert _hits(fts, fts_match_expr(accented)) == _hits(fts, fts_match_expr(plain))
    assert _hits(fts, fts_match_expr(accented)), "cả hai cùng rỗng thì không chứng minh gì"


def test_chu_khong_co_d_gach_van_hoat_dong_nhu_cu(fts):
    """Chống hồi quy: sửa `đ` không được làm hỏng các dấu vốn đã đúng."""
    assert _hits(fts, fts_match_expr("tien mat")) == {"T1"}
    assert _hits(fts, fts_match_expr("chi phi")) == {"T3"}
    assert _hits(fts, fts_match_expr("ngan hang")) == {"T1"}


# ── hỏng thì phải hỏng TO ───────────────────────────────────────────────────

def test_truy_van_KHONG_chuan_hoa_tra_ve_RONG_chu_khong_tra_ve_it(fts):
    """Quyết định thiết kế của RC-05, khoá lại bằng test.

    Nội dung ở dạng chuẩn nên `MATCH '"đồng"'` viết thẳng khớp KHÔNG CÁI GÌ.
    Nghe như một nhược điểm, nhưng đó là điểm mạnh: RC1 trả về 997 thẻ thay vì
    104.792 — một con số trông hợp lý nên không ai nghi ngờ suốt cả vòng đời
    gói. Rỗng thì người ta nhận ra ngay trong năm phút.
    """
    assert _hits(fts, '"đồng"') == set()
    assert _hits(fts, fts_match_expr("đồng")) == {"T1"}


# ── an toàn cú pháp ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    'chi phí NOT tính', 'tiền OR mặt', 'a AND b', 'dấu " lẻ',
    'NEAR(x y)', "*", "^tiền",
])
def test_toan_tu_FTS5_lan_trong_cau_hoi_khong_lam_no_truy_van(fts, raw):
    """Người dùng gõ `NOT` như một từ tiếng Anh, không phải như một phép loại trừ.

    Hợp đồng: biểu thức RỖNG nghĩa là "không có gì để tìm" — nơi gọi phải bỏ
    hẳn truy vấn. Đưa chuỗi rỗng vào `MATCH` là lỗi cú pháp của FTS5, và đó là
    lỗi ĐÚNG: một câu hỏi toàn dấu câu không nên âm thầm trả về cả corpus.
    """
    expr = fts_match_expr(raw)
    if not expr:
        return
    fts.execute("SELECT table_uid FROM table_cards_fts WHERE table_cards_fts"
                " MATCH ?", (expr,)).fetchall()          # không được ném lỗi


def test_chuoi_rong_khong_sinh_bieu_thuc_rac():
    assert fts_match_expr("") == ""
    assert fts_match_expr("   ") == ""
    assert fts_match_expr("!!!") == ""
    assert fts_match_expr("*") == ""
    assert fts_match_expr("— – | ·") == ""


def test_phrase_giu_duoc_thu_tu_tu(fts):
    """Truy vấn cụm phải bám thứ tự — đây là thứ phương án `*_norm` song song
    KHÔNG giữ được, vì hai từ nằm ở hai cột khác nhau thì không kề nhau."""
    assert _hits(fts, fts_match_expr("tuong duong tien", phrase=True)) == {"T1"}
    assert _hits(fts, fts_match_expr("tien duong tuong", phrase=True)) == set()


# ── hợp đồng phải ĐỌC ĐƯỢC BẰNG MÁY ────────────────────────────────────────

def test_hang_so_hop_dong_khong_troi_di():
    assert FTS_CONTENT == "normalized"
    assert FTS_TOKENIZER == "unicode61 remove_diacritics 2"
    assert NORMALIZE_VERSION == "1.0"


def test_DDL_khai_ro_noi_dung_la_dang_chuan():
    """Người mở gói đọc DDL trước khi đọc tài liệu. DDL phải tự nói được."""
    assert FTS_TOKENIZER in RELEASE_FTS_DDL
    assert "DẠNG CHUẨN" in RELEASE_FTS_DDL


def test_release_py_KHONG_con_duong_nap_van_ban_tho():
    """Chống hồi quy ở mức nguồn: `INSERT INTO table_cards_fts` phải đi qua
    `norm_search`. Bỏ sót một cột là mở lại đúng lỗ hổng của RC1."""
    src = (Path(__file__).resolve().parents[1]
           / "src" / "data_pipeline" / "release.py").read_text(encoding="utf-8")
    i = src.index("INSERT INTO table_cards_fts")
    block = src[i:src.index("FROM table_cards", i)]
    assert block.count("norm_search(") == 4, (
        "cả 4 trường văn bản phải qua norm_search")
