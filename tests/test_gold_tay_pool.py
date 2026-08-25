"""P0-a · khoá HỢP ĐỒNG của pool gold v3 và của bộ kiểm nhãn.

VÌ SAO PHẢI CÓ TEST CHO MỘT CÔNG CỤ NỘI BỘ
------------------------------------------
Gold tay là THƯỚC ĐO sẽ dùng để chốt mọi quyết định S2/S3 về sau. Một thước đo
hỏng không báo lỗi — nó chỉ cho ra những con số trông bình thường. Hai lần hỏng
đã xảy ra thật:

  · v1: phiếu thiếu `doc_year`/`basis` ⇒ câu "công ty mẹ … 2020" không gán được,
        vì bốn bảng nội dung y hệt nhau chỉ khác ở chỗ đó;
  · v2: phiếu in `uid[:8]` ⇒ 28/28 nhãn mang uid cụt, và nếu không có `check`
        thì `ManualGold` sẽ lặng lẽ coi mọi câu là "không có gold".

Nên ở đây khoá hai thứ: pool có ĐỦ và ĐÚNG hình dạng không, và bộ kiểm có bắt
được từng lớp lỗi không. Chạy trên fixture trong bộ nhớ — không cần `work.db`.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_tay import (POOL_MIN, S2_SHARE_MAX, _phu_thuoc_fts,  # noqa: E402
                      build_pool, kiem)
from retrieval.question_intent import parse_intent  # noqa: E402

ALIAS = {"VNM": ["Công ty Cổ phần Sữa Việt Nam"],
         "HPG": ["Công ty Cổ phần Tập đoàn Hòa Phát"],
         "MSN": ["Công ty Cổ phần Tập đoàn Masan Group"]}

_TK = ["VNM", "HPG", "MSN"]
_NAM = [2023, 2024]
_BASIS = ["consolidated", "separate"]
# Mỗi (mã, năm, phạm vi) có 4 bảng: KQKD, cân đối, một thuyết minh nhắc lại chỉ
# tiêu, một thuyết minh không liên quan. Đủ để phân biệt bốn trục mà `screen`
# đòi hỏi: khác mã, khác năm, hợp nhất vs riêng, cùng nội dung khác phạm vi.
# `row_labels` trong FTS được lưu ĐÃ BỎ DẤU + hạ chữ thường — fixture phải theo
# đúng thực tế đó, nếu không test sẽ xanh trong khi nguồn `like` chết ngoài đời.
_MAU_BANG = [
    ("income_statement", "doanh thu thuan ve ban hang va cung cap dich vu", "10"),
    ("balance_sheet", "hang ton kho | tai san ngan han", "140"),
    ("note", "doanh thu thuan nhac lai o thuyet minh", ""),
    ("note", "chi phi lai vay va cac khoan tuong tu", ""),
]


def _uid(i: int) -> str:
    return f"{i:016x}"


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (directory_doc_id TEXT PRIMARY KEY, "
              "ticker TEXT, doc_year INT, basis TEXT)")
    c.execute("CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, doc_id TEXT, "
              "ticker TEXT, doc_year INT, statement_type TEXT, n_observations INT, "
              "execution_ready_obs INT, periods TEXT, units TEXT, metric_codes TEXT, "
              "retrieval_ready INT DEFAULT 1, evidence_ref TEXT, section_text TEXT)")
    c.execute("CREATE VIRTUAL TABLE table_cards_fts USING fts5("
              "table_uid UNINDEXED, ticker, section_text, context_clean, "
              "row_labels, col_labels)")
    n = 0
    for tk in _TK:
        for yr in _NAM:
            for bs in _BASIS:
                doc = f"{tk}_financial_statements_{yr}_{bs}"
                c.execute("INSERT INTO documents VALUES (?,?,?,?)", (doc, tk, yr, bs))
                for stmt, rows_, code in _MAU_BANG:
                    n += 1
                    u = _uid(n)
                    c.execute(
                        "INSERT INTO table_cards VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
                        (u, doc, tk, yr, stmt, 20, 18, f"{yr}-12-31", "money",
                         code, f"{doc}|line:{100 + n}", f"MỤC {n}"))
                    c.execute("INSERT INTO table_cards_fts VALUES (?,?,?,?,?,?)",
                              (u, tk, f"MỤC {n}", "", rows_, f"{yr} VND"))
    return c


def _pool(conn, q: str, s2=(), proxy=()):
    it = parse_intent(q, ALIAS)
    uids = frozenset(
        u for (u,) in conn.execute(
            "SELECT t.table_uid FROM table_cards t "
            "JOIN documents d ON t.doc_id = d.directory_doc_id "
            "WHERE d.ticker IN ({}) ".format(",".join("?" * len(it.targets)))
            + ("AND d.doc_year BETWEEN ? AND ?" if it.years else ""),
            (*it.targets, *((min(it.years), max(it.years) + 1) if it.years else ()))))
    return build_pool(conn, 1, q, it, list(s2), list(proxy), uids, ALIAS), it


# ═════════════════════════════════════════════════════════════════════════════
# 1 · phiếu phải phân biệt được bốn trục
# ═════════════════════════════════════════════════════════════════════════════

def test_ung_vien_mang_du_truong_de_phan_biet(conn):
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?")
    assert p["candidates"], "pool rỗng"
    for c in p["candidates"]:
        for k in ("table_uid", "ticker", "doc_year", "basis", "statement_type",
                  "periods", "metric_codes", "row_labels", "evidence_ref"):
            assert k in c, f"ứng viên thiếu trường {k}"
        assert len(c["table_uid"]) == 16, "table_uid phải ĐẦY ĐỦ, không cắt ngắn"


def test_phan_biet_duoc_hop_nhat_va_rieng_cung_noi_dung(conn):
    """Hai bảng cùng chỉ tiêu, cùng mã, cùng năm — chỉ khác phạm vi. Nếu phiếu
    không mang `basis` thì câu "công ty mẹ" là không gán được, và đó chính là
    khuyết tật đã chặn v1."""
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?")
    bs = {c["basis"] for c in p["candidates"]}
    assert bs == {"consolidated", "separate"}


def test_phan_biet_duoc_cung_ma_khac_nam(conn):
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?")
    assert {c["doc_year"] for c in p["candidates"]} >= {2023, 2024}   # year_slack


# ═════════════════════════════════════════════════════════════════════════════
# 2 · sàn pool và trần S2
# ═════════════════════════════════════════════════════════════════════════════

def test_pool_dat_san_toi_thieu(conn):
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?")
    assert len(p["candidates"]) >= POOL_MIN


def test_s2_khong_duoc_chiem_qua_tran(conn):
    """Cả 48 bảng đều được S2 'đề cử'. Pool vẫn không được để S2 chi phối —
    đó là toàn bộ lý do `hit@10 = 1,0` của v2 không đọc được như recall."""
    het = [u for (u,) in conn.execute(
        "SELECT table_uid FROM table_cards ORDER BY table_uid")]
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het)
    chi_s2 = [c for c in p["candidates"] if c["sources"] == ["s2"]]
    assert len(chi_s2) / len(p["candidates"]) <= S2_SHARE_MAX + 1e-9


def test_phan_lon_ung_vien_den_tu_nguon_ngoai_fts(conn):
    het = [u for (u,) in conn.execute("SELECT table_uid FROM table_cards")]
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het, proxy=het[:6])
    ngoai = [c for c in p["candidates"] if not _phu_thuoc_fts(c["sources"])]
    assert len(ngoai) / len(p["candidates"]) >= 0.5


def test_bu_san_khong_bao_gio_bu_bang_s2(conn):
    """Khi hạn ngạch theo ô không lấp đủ sàn, phần bù phải đến từ tín hiệu độc
    lập. Bù bằng S2 là đưa thiên lệch quay lại qua cửa sau."""
    het = [u for (u,) in conn.execute("SELECT table_uid FROM table_cards")]
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het)
    doc_lap = [c for c in p["candidates"] if not _phu_thuoc_fts(c["sources"])]
    assert len(doc_lap) >= POOL_MIN


# ═════════════════════════════════════════════════════════════════════════════
# 3 · screen · pool theo ô (mã × năm)
# ═════════════════════════════════════════════════════════════════════════════

def test_screen_pool_phu_moi_o_ma_x_nam(conn):
    q = ("Trong nhóm VNM, HPG và MSN, doanh thu thuần năm 2023 và năm 2024 "
         "chênh lệch bao nhiêu phần trăm?")
    p, it = _pool(conn, q)
    assert it.mode == "screen", f"fixture không tạo được câu screen: {it.mode}"
    assert p["cells_missing"] == [], p["cells_missing"]
    co = {(c["ticker"], c["doc_year"]) for c in p["candidates"]}
    for t in ("VNM", "HPG", "MSN"):
        for y in (2023, 2024):
            assert (t, y) in co, f"thiếu ô {t}/{y}"


def test_screen_khong_bi_cat_o_10(conn):
    q = ("Trong nhóm VNM, HPG và MSN, doanh thu thuần năm 2023 và năm 2024 "
         "chênh lệch bao nhiêu phần trăm?")
    p, _ = _pool(conn, q)
    assert len(p["candidates"]) > 10
    assert len(p["candidates"]) >= len(p["cells"]) * 2


def test_screen_thieu_o_thi_KHAI_RA_chu_khong_im(conn):
    """Mã không có báo cáo năm đó ⇒ ô rỗng. Phải ghi vào `cells_missing` để
    `check` chặn, chứ không lặng lẽ cho ra một pool thiếu mã."""
    conn.execute("DELETE FROM documents WHERE ticker='MSN' AND doc_year=2024")
    conn.execute("DELETE FROM table_cards WHERE ticker='MSN' AND doc_year=2024")
    q = ("Trong nhóm VNM, HPG và MSN, doanh thu thuần năm 2023 và năm 2024 "
         "chênh lệch bao nhiêu phần trăm?")
    p, _ = _pool(conn, q)
    assert "MSN/2024" in p["cells_missing"]


# ═════════════════════════════════════════════════════════════════════════════
# 4 · thứ tự hiển thị KHÔNG rò rỉ thứ hạng
# ═════════════════════════════════════════════════════════════════════════════

def test_thu_tu_la_sieu_du_lieu_khong_phai_diem(conn):
    het = [u for (u,) in conn.execute(
        "SELECT table_uid FROM table_cards ORDER BY table_uid DESC")]
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het)
    khoa = [(c["ticker"], c["doc_year"], c["basis"], c["statement_type"],
             c["table_uid"]) for c in p["candidates"]]
    assert khoa == sorted(khoa), "ứng viên phải xếp theo (mã, năm, phạm vi, loại, uid)"


def test_thu_tu_khong_doi_khi_thu_tu_s2_dao_nguoc(conn):
    het = [u for (u,) in conn.execute(
        "SELECT table_uid FROM table_cards ORDER BY table_uid")]
    a, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het)
    b, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023?", s2=het[::-1])
    assert [c["table_uid"] for c in a["candidates"]] \
        == [c["table_uid"] for c in b["candidates"]], \
        "đảo thứ hạng S2 mà đổi thứ tự phiếu = phiếu đang rò rỉ thứ hạng"


# ═════════════════════════════════════════════════════════════════════════════
# 5 · `check` · chín lớp lỗi
# ═════════════════════════════════════════════════════════════════════════════

_POOL1 = {
    1: {"id": 1, "mode": "single", "targets": ["VNM"], "years": [2023],
        "explicit_scope": "công ty mẹ", "cells_missing": [],
        "candidates": [{"table_uid": "a" * 16}, {"table_uid": "b" * 16}]},
}
_META = {
    "a" * 16: {"ticker": "VNM", "doc_year": 2023, "basis": "separate"},
    "b" * 16: {"ticker": "VNM", "doc_year": 2023, "basis": "consolidated"},
    "c" * 16: {"ticker": "HPG", "doc_year": 2023, "basis": "separate"},
    "d" * 16: {"ticker": "VNM", "doc_year": 2019, "basis": "separate"},
    "e" * 16: {"ticker": None, "doc_year": 2023, "basis": "separate"},
}
_TIENTO = {u[:8]: [u] for u in _META}


def _co_loi(nhan, pool=None, meta=None):
    return kiem(nhan, pool or _POOL1, meta or _META, _TIENTO)


def test_check_sach_khi_nhan_dung():
    assert _co_loi([{"id": 1, "gold_table_uids": ["a" * 16]}]) == []


def test_check_bat_uid_cut():
    loi = _co_loi([{"id": 1, "gold_table_uids": ["aaaaaaaa"]}])
    assert any("CỤT" in e for e in loi)


def test_check_bat_uid_khong_ton_tai():
    loi = _co_loi([{"id": 1, "gold_table_uids": ["f" * 16]}])
    assert any("KHÔNG TỒN TẠI" in e for e in loi)


def test_check_bat_prefix_nhap_nhang():
    tt = {"aaaaaaaa": ["a" * 16, "a" * 8 + "z" * 8]}
    loi = kiem([{"id": 1, "gold_table_uids": ["aaaaaaaa"]}], _POOL1, _META, tt)
    assert any("2 bảng khớp" in e for e in loi)


def test_check_bat_nhan_trung_theo_id():
    loi = _co_loi([{"id": 1, "gold_table_uids": ["a" * 16]},
                   {"id": 1, "gold_table_uids": ["b" * 16]}])
    assert any("NHÃN TRÙNG" in e and "id" in e for e in loi)


def test_check_bat_uid_trung_trong_mot_nhan():
    loi = _co_loi([{"id": 1, "gold_table_uids": ["a" * 16, "a" * 16]}])
    assert any("hai lần" in e for e in loi)


def test_check_bat_thieu_ticker():
    pool = {1: {**_POOL1[1], "candidates": [{"table_uid": "e" * 16}]}}
    loi = _co_loi([{"id": 1, "gold_table_uids": ["e" * 16]}], pool=pool)
    assert any("KHÔNG có ticker" in e for e in loi)


def test_check_bat_ticker_lech():
    pool = {1: {**_POOL1[1], "candidates": [{"table_uid": "c" * 16}]}}
    loi = _co_loi([{"id": 1, "gold_table_uids": ["c" * 16]}], pool=pool)
    assert any("ticker LỆCH" in e for e in loi)


def test_check_bat_doc_year_lech():
    pool = {1: {**_POOL1[1], "candidates": [{"table_uid": "d" * 16}]}}
    loi = _co_loi([{"id": 1, "gold_table_uids": ["d" * 16]}], pool=pool)
    assert any("doc_year LỆCH" in e for e in loi)


def test_check_bat_basis_lech_khi_cau_neu_ro_pham_vi():
    loi = _co_loi([{"id": 1, "gold_table_uids": ["b" * 16]}])
    assert any("basis LỆCH" in e for e in loi)


def test_check_KHONG_bat_basis_khi_cau_im_lang():
    """Câu không nêu phạm vi thì mặc định `hợp nhất` là GIẢ ĐỊNH CỦA TA, không
    phải luật BTC. Biến giả định thành lỗi cứng là bịa ra một sự chắc chắn
    không có — nên chỉ chặn khi câu hỏi NÊU RÕ."""
    pool = {1: {**_POOL1[1], "explicit_scope": None}}
    assert _co_loi([{"id": 1, "gold_table_uids": ["b" * 16]}], pool=pool) == []


def test_check_bat_gold_ngoai_pool():
    meta = {**_META, "f" * 16: {"ticker": "VNM", "doc_year": 2023,
                                "basis": "separate"}}
    loi = kiem([{"id": 1, "gold_table_uids": ["f" * 16]}], _POOL1, meta,
               {u[:8]: [u] for u in meta})
    assert any("NGOÀI POOL" in e for e in loi)


def test_check_bat_screen_thieu_o():
    pool = {2: {"id": 2, "mode": "screen", "targets": ["VNM", "HPG"],
                "years": [2023], "explicit_scope": None,
                "cells_missing": ["HPG/2023"], "candidates": []}}
    loi = kiem([], pool, _META, _TIENTO)
    assert any("SCREEN thiếu ứng viên" in e for e in loi)


def test_check_bat_uncertain_thieu_ly_do():
    loi = _co_loi([{"id": 1, "uncertain": True}])
    assert any("thiếu `reason`" in e for e in loi)


def test_check_bat_nhan_rong():
    loi = _co_loi([{"id": 1, "gold_table_uids": []}])
    assert any("không có gold_table_uids" in e for e in loi)


def test_check_bat_chua_dung_pool():
    loi = _co_loi([{"id": 99, "gold_table_uids": ["a" * 16]}])
    assert any("chưa dựng pool" in e for e in loi)


def test_check_khong_tu_sua_du_lieu():
    """Bộ kiểm phải là hàm THUẦN: nhận vào, trả danh sách lỗi, không đụng gì.
    Một bộ kiểm 'tự sửa cho tiện' sẽ che đúng thứ nó sinh ra để phát hiện."""
    nhan = [{"id": 1, "gold_table_uids": ["aaaaaaaa"]}]
    truoc = [dict(r) for r in nhan]
    kiem(nhan, _POOL1, _META, _TIENTO)
    assert nhan == truoc


def test_nguon_like_khop_row_labels_da_bo_dau(conn):
    """`row_labels` lưu dạng bỏ dấu. Nếu cụm LIKE giữ dấu thì nguồn ĐỘC LẬP
    quan trọng nhất khớp 0 bảng — im lặng, không lỗi. Đo trên work.db thật:
    `%doanh thu thuần%` → 0 bảng; `%doanh thu thuan%` → 3.234 bảng."""
    p, _ = _pool(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?")
    co_like = [c for c in p["candidates"] if "like" in c["sources"]]
    assert co_like, "nguồn `like` không khớp gì — cụm LIKE chưa bỏ dấu?"
    for c in co_like:
        assert "doanh thu thuan" in " ".join(c["row_labels"])
