"""SMOKE tích hợp · A6 → work.db → Retrieval → bảng đã chọn → định dạng nộp bài.

VÌ SAO CHẠY TRÊN FIXTURE CHỨ KHÔNG PHẢI `work.db`
-------------------------------------------------
`work.db` nặng 4,24 GB và chỉ có trên máy build. Một smoke test chỉ chạy được ở
đúng một chỗ thì trên thực tế là một smoke test **không ai chạy**. Fixture ở đây
dựng đúng những cột mà chuỗi S1→S2→S3→adapter đọc, nên nó khoá được HỢP ĐỒNG —
phần dễ vỡ và im lặng nhất — mà không cần dữ liệu thật.

Cái nó KHÔNG khoá, và phải nói rõ: chất lượng xếp hạng, và việc `evidence_ref`
trong A6 có trỏ đúng dòng mở `<table>` hay không. Điều thứ hai đã được kiểm
riêng trên corpus thật (400/400 khớp 1-based) — xem `docs/80`.

BỐN BẤT BIẾN ĐƯỢC KHOÁ
  1. `relevant_tables` đúng dạng `<doc_id>|<line_no>` — KHÔNG còn tiền tố `line:`
  2. `relevant_docs` SUY RA từ `relevant_tables`, không dựng riêng ⇒ không lệch
  3. `N` theo chính sách `clamp(n_mã × n_năm, 1, 10)`
  4. `evidence_ref` dạng lạ thì NỔ, không lặng lẽ nộp chuỗi rác
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.submission_adapter import (MAX_N,  # noqa: E402
                                          RetrievalToSubmission,
                                          to_submission_ref)

ALIAS = {"VNM": ["Công ty Cổ phần Sữa Việt Nam"], "HPG": ["Tập đoàn Hòa Phát"]}

# doc_id, ticker, year, basis
_DOCS = [
    ("VNM_financial_statements_2023_consolidated", "VNM", 2023, "consolidated"),
    ("VNM_financial_statements_2023_separate", "VNM", 2023, "separate"),
    ("HPG_financial_statements_2023_consolidated", "HPG", 2023, "consolidated"),
]
# uid, doc index, stmt, row_labels, line
_CARDS = [
    ("aaaa000000000001", 0, "income_statement",
     "Doanh thu thuần về bán hàng và cung cấp dịch vụ", 288),
    ("aaaa000000000002", 0, "note", "Doanh thu thuần nhắc lại ở thuyết minh", 954),
    ("aaaa000000000003", 1, "income_statement",
     "Doanh thu thuần về bán hàng và cung cấp dịch vụ", 301),
    ("aaaa000000000004", 2, "income_statement",
     "Doanh thu thuần về bán hàng và cung cấp dịch vụ", 275),
]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (directory_doc_id TEXT PRIMARY KEY, "
              "ticker TEXT, doc_year INT, basis TEXT)")
    c.executemany("INSERT INTO documents VALUES (?,?,?,?)", _DOCS)
    c.execute("CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, doc_id TEXT, "
              "ticker TEXT, doc_year INT, statement_type TEXT, n_observations INT, "
              "execution_ready_obs INT, periods TEXT, units TEXT, metric_codes TEXT, "
              "retrieval_ready INT DEFAULT 1, evidence_ref TEXT)")
    c.execute("CREATE VIRTUAL TABLE table_cards_fts USING fts5("
              "table_uid UNINDEXED, ticker, section_text, context_clean, "
              "row_labels, col_labels)")
    for uid, di, stmt, rows_, line in _CARDS:
        doc, tk, yr, _ = _DOCS[di]
        c.execute("INSERT INTO table_cards VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                  (uid, doc, tk, yr, stmt, 20, 20, "2023-12-31", "money", "10",
                   f"{doc}|line:{line}"))
        c.execute("INSERT INTO table_cards_fts VALUES (?,?,?,?,?,?)",
                  (uid, tk, "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH", "",
                   rows_, "2023 VND"))
    return c


# ── hợp đồng định danh ───────────────────────────────────────────────────────

def test_ref_bo_tien_to_line():
    assert to_submission_ref("DOC_X|line:1293") == "DOC_X|1293"


def test_ref_off_by_one_chinh_duoc_ma_khong_sua_code():
    """1-based hay 0-based CHƯA ĐÓNG với BTC — phải chỉnh được bằng tham số."""
    assert to_submission_ref("DOC_X|line:1293", off_by_one=-1) == "DOC_X|1292"


@pytest.mark.parametrize("xau", ["DOC_X|1293", "DOC_X", "DOC_X|line:abc", ""])
def test_ref_dang_la_thi_NO(xau):
    """Nộp một `relevant_tables` sai định dạng = mất trọn C20 của câu đó, mà
    không có ngoại lệ nào để lần ra. Nên phải nổ ngay tại chỗ đổi định dạng."""
    with pytest.raises(ValueError):
        to_submission_ref(xau)


# ── chuỗi đầy đủ ─────────────────────────────────────────────────────────────

def test_smoke_het_chuoi_mot_ma_mot_nam(conn):
    ad = RetrievalToSubmission(ALIAS)
    r = ad.refs_for(conn, 1, "Doanh thu thuần của Công ty Cổ phần Sữa Việt Nam "
                             "năm 2023 là bao nhiêu tỷ đồng?")
    assert r.n_policy == 1                      # 1 mã × 1 năm
    assert len(r.relevant_tables) == 1
    assert r.relevant_tables[0].startswith("VNM_financial_statements_2023_")
    assert "line:" not in r.relevant_tables[0]
    assert r.relevant_docs == [r.relevant_tables[0].rsplit("|", 1)[0]]
    assert r.n_candidates >= 2                  # S1 giữ cả hợp nhất lẫn riêng
    assert r.ranked_table_uids[:len(r.table_uids)] == r.table_uids


def test_relevant_docs_luon_suy_ra_tu_relevant_tables(conn):
    ad = RetrievalToSubmission(ALIAS, max_n=MAX_N)
    r = ad.refs_for(conn, 2, "Doanh thu thuần của VNM và HPG năm 2023 "
                             "là bao nhiêu tỷ đồng?")
    suy_ra = list(dict.fromkeys(t.rsplit("|", 1)[0] for t in r.relevant_tables))
    assert r.relevant_docs == suy_ra
    assert len(set(r.relevant_docs)) == len(r.relevant_docs)


def test_chinh_sach_N_theo_so_ma_va_so_nam(conn):
    ad = RetrievalToSubmission(ALIAS)
    r = ad.refs_for(conn, 3, "Doanh thu thuần của VNM và HPG năm 2023 "
                             "là bao nhiêu tỷ đồng?")
    assert r.n_policy == 2                      # 2 mã × 1 năm
    assert len(r.relevant_tables) <= 2


def test_khong_phan_giai_duoc_ma_thi_khong_nop_bua(conn):
    """S1 im lặng ⇒ nộp rỗng. Nộp bừa vài bảng để 'có còn hơn không' làm TỤT F2
    của chính câu đó (mẫu số `4g+N` tăng mà `h` vẫn 0)."""
    ad = RetrievalToSubmission(ALIAS)
    r = ad.refs_for(conn, 4, "Doanh thu của một công ty nào đó năm 2023?")
    assert r.relevant_tables == [] and r.relevant_docs == []


def test_item_nop_bai_du_khoa_va_answer_rong_van_hop_le(conn):
    ad = RetrievalToSubmission(ALIAS)
    q = "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?"
    item = ad.refs_for(conn, 5, q).as_item(q)
    assert set(item) == {"id", "question", "answer", "relevant_docs",
                         "relevant_tables"}
    assert item["answer"] == ""
    json.dumps(item, ensure_ascii=False)        # phải tuần tự hoá được


def test_thieu_evidence_ref_thi_NO(conn):
    """Xếp hạng được mà không nộp được là lỗi DỮ LIỆU — phải nổ, không nộp thiếu."""
    conn.execute("UPDATE table_cards SET evidence_ref = NULL")
    ad = RetrievalToSubmission(ALIAS)
    with pytest.raises(ValueError, match="evidence_ref"):
        ad.refs_for(conn, 6, "Doanh thu thuần của VNM năm 2023?")
