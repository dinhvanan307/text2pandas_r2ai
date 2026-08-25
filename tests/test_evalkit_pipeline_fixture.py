"""Test tích hợp S1→S2→S3 trên SQLite TỔNG HỢP, không cần `work.db` 4,24 GB.

VÌ SAO CẦN FIXTURE NÀY
----------------------
Trước đây mọi kiểm chứng tầng retrieval đều phải chạy trên `work.db` 4,24 GB
trên máy build. Hệ quả: không ai chạy được test trong CI, và ba lỗi im lặng
(`bm25` chia lô, xoá alias không biên từ, `basis` chết ở cấu hình mặc định) chỉ
lộ ra khi đọc mã bằng mắt.

Fixture dựng đúng lược đồ tối thiểu mà `filter_s1.SQL` và `rank_s2` cần —
`documents`, `table_cards`, `table_cards_fts` (6 cột, khớp `len(WEIGHTS)`) — với
vài chục dòng dữ liệu đủ để kiểm HÀNH VI, không kiểm số.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from retrieval.evalkit.goldset import ProxyGoldV2, free_ticker_histogram  # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator, IdentityReranker)
from retrieval.question_intent import parse_intent  # noqa: E402
from retrieval.rank_s2 import assert_fts_arity, rank  # noqa: E402

ALIAS = {"VNM": ["Công ty CP Sữa Việt Nam"], "HPG": ["Công ty CP Tập đoàn Hòa Phát"]}

DOCS = [
    # directory_doc_id, ticker, doc_year, basis
    ("VNM_financial_statements_2023_consolidated", "VNM", 2023, "consolidated"),
    ("VNM_financial_statements_2023_separate", "VNM", 2023, "separate"),
    ("VNM_financial_statements_2024_consolidated", "VNM", 2024, "consolidated"),
    ("HPG_financial_statements_2023_consolidated", "HPG", 2023, "consolidated"),
]
# table_uid, doc_id, statement_type, n_obs, ready_obs, periods, units, codes,
# section_text, context_clean, row_labels, col_labels
CARDS = [
    ("t1", DOCS[0][0], "income_statement", 10, 9, "2023-12-31,2022-12-31",
     "money", "10,11", "BÁO CÁO KẾT QUẢ", "", "Doanh thu thuần bán hàng", "2023VND"),
    ("t2", DOCS[0][0], "note", 8, 4, "2023-12-31", "money", "",
     "THUYẾT MINH 25", "", "Doanh thu thuần nhắc lại", "2023VND"),
    ("t3", DOCS[1][0], "income_statement", 10, 10, "2023-12-31",
     "money", "10", "BÁO CÁO RIÊNG", "", "Doanh thu thuần bán hàng", "2023VND"),
    ("t4", DOCS[2][0], "balance_sheet", 6, 0, "2024-12-31,2023-12-31",
     "money", "", "CÂN ĐỐI", "", "Hàng tồn kho", "2024VND"),
    ("t5", DOCS[3][0], "income_statement", 12, 12, "2023-12-31",
     "money", "10", "KQKD HÒA PHÁT", "", "Doanh thu thuần bán hàng", "2023VND"),
]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (directory_doc_id TEXT PRIMARY KEY, "
              "ticker TEXT, doc_year INT, basis TEXT)")
    c.executemany("INSERT INTO documents VALUES (?,?,?,?)", DOCS)
    c.execute("CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, doc_id TEXT, "
              "ticker TEXT, doc_year INT, statement_type TEXT, n_observations INT, "
              "execution_ready_obs INT, periods TEXT, units TEXT, metric_codes TEXT, "
              "retrieval_ready INT DEFAULT 1, evidence_ref TEXT)")
    c.execute("CREATE VIRTUAL TABLE table_cards_fts USING fts5("
              "table_uid UNINDEXED, ticker, section_text, context_clean, "
              "row_labels, col_labels)")
    for i, (uid, doc, stmt, nobs, ready, per, un, codes, sec, ctx, rows_, cols) \
            in enumerate(CARDS):
        tk = doc.split("_")[0]
        yr = int(doc.split("_")[3])
        c.execute("INSERT INTO table_cards VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                  (uid, doc, tk, yr, stmt, nobs, ready, per, un, codes,
                   f"{doc}|line:{100+i}"))
        c.execute("INSERT INTO table_cards_fts VALUES (?,?,?,?,?,?)",
                  (uid, tk, sec, ctx, rows_, cols))
    return c


# ── lược đồ FTS phải khớp WEIGHTS ────────────────────────────────────────────

def test_fts_arity_khop_weights(conn):
    assert assert_fts_arity(conn) == 6


def test_fts_arity_bat_duoc_lech_cot(conn):
    conn.execute("CREATE VIRTUAL TABLE tc2 USING fts5(a, b)")
    with pytest.raises(ValueError, match="áp theo VỊ TRÍ"):
        assert_fts_arity(conn, (1.0, 2.0, 3.0))


# ── S1 · lọc cứng ────────────────────────────────────────────────────────────

def test_s1_soft_giu_ca_hai_basis(conn):
    """`basis_mode=soft` phải giữ CẢ hợp nhất và riêng lẻ — đó là toàn bộ lý do
    nó tồn tại (candidate recall 97,42% → 99,68%)."""
    it = parse_intent("Doanh thu thuần của VNM năm 2023 là bao nhiêu?", ALIAS)
    out = HardFilterGenerator(basis_mode="soft").generate(conn, "x", it)
    assert {"t1", "t2", "t3"} <= out.uids       # t3 là bản `separate`
    assert "t5" not in out.uids                 # khác ticker


def test_s1_hard_loai_basis_khac(conn):
    it = parse_intent("Doanh thu thuần của VNM năm 2023 là bao nhiêu?", ALIAS)
    out = HardFilterGenerator(basis_mode="hard").generate(conn, "x", it)
    assert "t3" not in out.uids                 # separate bị loại → mất hẳn
    assert "t1" in out.uids


def test_s1_year_slack_mo_nam_sau(conn):
    """Báo cáo năm N+1 chứa cột năm N — không được lọc cứng `doc_year = năm hỏi`."""
    it = parse_intent("Hàng tồn kho của VNM năm 2023?", ALIAS)
    out = HardFilterGenerator(basis_mode="soft", year_slack=1).generate(conn, "x", it)
    assert "t4" in out.uids                     # doc_year=2024, kỳ có 2023-12-31


def test_s1_tap_rong_khi_khong_phan_giai_duoc(conn):
    it = parse_intent("Doanh thu của một công ty nào đó?", ALIAS)
    out = HardFilterGenerator().generate(conn, "x", it)
    assert out.n == 0 and out.uids == frozenset()


def test_s1_khai_mach_de_dang_hoat_dong(conn):
    """`retrieval_ready` PHẢI được khai là NOOP — 146.246/146.246 bảng đạt."""
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    out = HardFilterGenerator(basis_mode="soft").generate(conn, "x", it)
    cl = out.trace["active_clauses"]
    assert "ticker" in cl and "doc_year" in cl
    assert "retrieval_ready:NOOP" in cl
    assert "basis" not in cl                    # soft ⇒ basis KHÔNG ở WHERE


# ── S2 · xếp hạng ────────────────────────────────────────────────────────────

def test_s2_tra_ve_thu_tu_va_cat_top_k(conn):
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    o1 = HardFilterGenerator().generate(conn, "q", it)
    o2 = Bm25StructuralRanker(ALIAS, top_k=2).rank(
        conn, "Doanh thu thuần của VNM năm 2023?", it, o1)
    assert len(o2.ranked) == 2 and o2.truncated_at == 2
    sc = [r.score for r in o2.ranked]
    assert sc == sorted(sc, reverse=True)


def test_s2_bang_income_statement_thang_bang_note(conn):
    """Cùng cụm ở nhãn dòng, nhưng bảng KQKD sạch hơn và có mã chỉ tiêu."""
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    o1 = HardFilterGenerator().generate(conn, "q", it)
    o2 = Bm25StructuralRanker(ALIAS, top_k=10).rank(
        conn, "Doanh thu thuần của VNM năm 2023?", it, o1)
    order = [r.table_uid for r in o2.ranked]
    assert order.index("t1") < order.index("t2")


def test_s2_chia_lo_cho_cung_ket_qua(conn, monkeypatch):
    """Chia lô KHÔNG được đổi điểm: `bm25()` chấm từng dòng, độc lập tập ứng viên."""
    import retrieval.rank_s2 as m
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    cands = [r.cand for r in HardFilterGenerator().generate(conn, "q", it).ranked]
    from retrieval.query_terms import build_match, content_terms
    match = build_match(content_terms("Doanh thu thuần của VNM năm 2023?",
                                      drop=("VNM",)))
    goc = {s.cand.table_uid: s.score for s in rank(conn, cands, match, top_k=99)}
    monkeypatch.setattr(m, "_CHUNK", 1)          # ép mỗi ứng viên một lô
    lo = {s.cand.table_uid: s.score for s in rank(conn, cands, match, top_k=99)}
    assert goc == pytest.approx(lo)


def test_s2_bonus_cau_hinh_duoc(conn):
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    cands = [r.cand for r in HardFilterGenerator().generate(conn, "q", it).ranked]
    from retrieval.query_terms import build_match, content_terms
    match = build_match(content_terms("Doanh thu thuần của VNM năm 2023?", drop=("VNM",)))
    a = rank(conn, cands, match, period_ends=("2023-12-31",), top_k=99)
    b = rank(conn, cands, match, period_ends=("2023-12-31",), top_k=99,
             bonuses={"period": 5.0})
    assert [s.cand.table_uid for s in a] != [s.cand.table_uid for s in b] \
        or a[0].score != b[0].score


# ── S3 · reranker mặc định là identity ───────────────────────────────────────

def test_s3_identity_khong_doi_thu_tu(conn):
    it = parse_intent("Doanh thu thuần của VNM năm 2023?", ALIAS)
    o1 = HardFilterGenerator().generate(conn, "q", it)
    o2 = Bm25StructuralRanker(ALIAS, top_k=10).rank(conn, "Doanh thu thuần VNM 2023?", it, o1)
    o3 = IdentityReranker(top_k=2).rerank(conn, "q", it, o2)
    assert [r.table_uid for r in o3.ranked] == [r.table_uid for r in o2.ranked[:2]]
    assert o3.trace["passthrough"] is True


# ── gold · ProxyGoldV2 không còn lọc mã trong MATCH ──────────────────────────

def test_proxy_v2_ma_la_vi_tu_sql_khong_nam_trong_match(conn):
    """Gold vẫn chỉ chứa bảng của mã đã phân giải — ràng buộc mã ĐÚNG ngữ nghĩa."""
    g = ProxyGoldV2(alias=ALIAS).gold_for(
        conn, 1, "Doanh thu thuần của Công ty CP Sữa Việt Nam năm 2023?",
        frozenset({"VNM"}), (2023,), None)
    assert g.tables and all(u in {"t1", "t2", "t3"} for u in g.tables)
    assert "t5" not in g.tables
    assert g.tier in ("T1_row_ngram", "T2_row_2gram")
    assert g.strict is True


def test_proxy_v2_KHONG_return_som_khi_cum_dau_khop_ma_khac(conn):
    """BUG ĐÃ SỬA · vòng lặp phải THỬ HẾT, không dừng ở cụm đầu tiên thất bại.

    "Hàng tồn kho" chỉ có ở VNM (t4). Câu hỏi về HPG chứa CẢ cụm đó VÀ cụm
    "Doanh thu thuần" (có ở t5 của HPG). Bản đầu gặp "Hàng tồn kho" trước, thấy
    `keep` rỗng và `return` ngay → mất gold. Bản này phải đi tiếp và tìm ra t5.

    Đây chính là lỗi làm coverage tụt 92% → 56,7% trên 1.012 câu thật.
    """
    g = ProxyGoldV2(alias=ALIAS).gold_for(
        conn, 9, "Hàng tồn kho và Doanh thu thuần của HPG năm 2023?",
        frozenset({"HPG"}), (2023,), None)
    assert g.tables == frozenset({"t5"}), f"return sớm đã quay lại: {g.reason}"


def test_proxy_v2_bao_entity_suspect_CHI_KHI_da_can_moi_cum(conn):
    """Cụm tồn tại ở mã KHÁC và đã cạn mọi tier → nghi vấn phân giải thực thể.

    Tín hiệu lấy từ `COUNT(*) GROUP BY ticker` KHÔNG LIMIT, nên không thiên lệch
    theo rowid. Thước đo cũ chỉ trả gold rỗng và câu biến mất khỏi tập đo.
    """
    g = ProxyGoldV2(alias=ALIAS).gold_for(
        conn, 2, "Hàng tồn kho ghi nhận năm 2023?", frozenset({"HPG"}),
        (2023,), None)
    assert not g.tables
    assert g.trace.get("entity_suspect") is True
    assert "VNM" in (g.trace.get("free_top") or {})
    assert g.n_free_hits > 0


def test_proxy_v2_scope_tuong_minh_thu_hep(conn):
    g = ProxyGoldV2(alias=ALIAS).gold_for(
        conn, 3, "Doanh thu thuần báo cáo riêng của VNM năm 2023?",
        frozenset({"VNM"}), (2023,), "công ty mẹ")
    assert g.tables == frozenset({"t3"})


def test_free_ticker_histogram_khong_gioi_han_ma(conn):
    h = free_ticker_histogram(conn, 'row_labels : "Doanh thu"', ())
    assert set(h) >= {"VNM", "HPG"}
    assert h["VNM"] >= 2


def test_gold_tier_noi_dan_theo_thu_tu(conn):
    """Cụm không khớp `row_labels` nhưng khớp `section_text` → phải rơi về T4."""
    g = ProxyGoldV2(alias=ALIAS).gold_for(
        conn, 7, "Chỉ tiêu ở THUYẾT MINH 25 của VNM năm 2023?",
        frozenset({"VNM"}), (2023,), None)
    assert g.tables, g.reason
    assert g.tier == "T4_anycol_2gram"
    assert g.strict is False       # tier nới ⇒ KHÔNG dùng để chốt quyết định


def test_max_tier_cat_dung_thang(conn):
    """`max_tier=T2` phải KHÔNG bao giờ trả về gold ở T3/T4."""
    g = ProxyGoldV2(alias=ALIAS, max_tier="T2_row_2gram").gold_for(
        conn, 8, "Chỉ tiêu ở THUYẾT MINH 25 của VNM năm 2023?",
        frozenset({"VNM"}), (2023,), None)
    assert g.tier in ("", "T1_row_ngram", "T2_row_2gram")
