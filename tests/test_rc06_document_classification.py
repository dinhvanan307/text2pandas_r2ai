"""RC-06 · phân loại tài liệu phi bảng biểu — trong CHÍNH GÓI PHÁT HÀNH.

Review 28 đòi năm thứ, và bản 1 mới làm được một:

    1. numeric-content summary
    2. coverage audit — có câu hỏi nào phụ thuộc tám tài liệu này không
    3. `unclassified no-table document = 0`
    4. điều kiện GENERIC từ raw markup, không hard-code tám tên tệp
    5. DQ phân biệt PASS/KNOWN với lỗi thật

Điểm mấu chốt của mục 4: bản 1 phân loại bằng `n_tables > 0` — tức là suy ra
một khẳng định về VĂN BẢN GỐC ("không có markup bảng") từ KẾT QUẢ PHÂN TÍCH.
Cùng lớp lỗi đã làm hỏng `execution_ready` ở RC-02: một đại lượng dẫn xuất bị
đem dùng như bằng chứng gốc.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.release_schema import (  # noqa: E402
    RELEASE_DDL, RELEASE_DOC_CLASS_DDL)

COLS = ("document_uid, directory_doc_id, ticker, doc_year, basis, rel_path,"
        " n_bytes, n_lines, n_pages, n_tables, sha256,"
        " n_table_markup, n_numeric_tokens, n_grouped_numbers")

# (uid, n_tables, n_table_markup, n_grouped_numbers)
DOCS = [
    ("T",  62,  62, 4210),   # bảng bình thường
    ("N",   0,   0,   14),   # công văn giải trình — ngoài phạm vi
    ("F",   0,   9,  300),   # CÓ markup mà 0 bảng — LỖI PARSER
    ("U",   0,  -1,   -1),   # Bronze cũ hơn RC-06 — KHÔNG BIẾT
    ("Z",   0,   0,    0),   # không bảng, không số
]


@pytest.fixture
def rel():
    con = sqlite3.connect(":memory:")
    con.executescript(RELEASE_DDL)
    con.executescript(RELEASE_DOC_CLASS_DDL)
    con.executemany(
        f"INSERT INTO documents ({COLS}) VALUES ({','.join('?' * 14)})",
        [(u, f"doc_{u}", "AAA", 2023, "consolidated", f"AAA/{u}.txt",
          1000, 100, 3, nt, f"h{u}", nm, 500, ng)
         for u, nt, nm, ng in DOCS])
    con.commit()
    yield con
    con.close()


def _col(con, name):
    return dict(con.execute(
        f"SELECT document_uid, {name} FROM v_document_classification"))


# ── 4 · điều kiện generic từ RAW MARKUP ────────────────────────────────────

def test_phan_loai_BA_trang_thai_khong_phai_hai(rel):
    assert _col(rel, "document_kind") == {
        "T": "tabular", "N": "non_tabular", "F": "tabular_parse_failed",
        "U": "unknown", "Z": "non_tabular"}


def test_markup_co_ma_bang_khong_ra_la_LOI_chu_khong_phai_ngoai_pham_vi(rel):
    """`F` là ca bản 1 KHÔNG THỂ nhìn thấy — nó bị gán `no_table_markup`."""
    assert _col(rel, "table_exclusion_reason")["F"] == \
        "markup_present_but_no_table_parsed"
    assert _col(rel, "retrieval_route")["F"] == "blocked_defect"


def test_chua_do_van_ban_goc_thi_noi_KHONG_BIET(rel):
    """§15 · thiếu bằng chứng thì phải nói thiếu, không được đoán.

    Gộp `U` vào `non_tabular` là khẳng định "tệp này vốn không có bảng" mà
    chưa hề mở tệp ra xem.
    """
    assert _col(rel, "document_kind")["U"] == "unknown"
    assert _col(rel, "table_exclusion_reason")["U"] == "raw_markup_not_measured"
    assert _col(rel, "numeric_content")["U"] == "unknown"


def test_khong_hard_code_ten_tep(rel):
    """Điều kiện phải là HÀM của hai con số, không phải danh sách tên."""
    src = (Path(__file__).resolve().parents[1] / "src" / "text2pandas" / "pipelines" / "a6"
           / "release_schema.py").read_text(encoding="utf-8")
    i = src.index("RELEASE_DOC_CLASS_DDL")
    block = src[i:src.index('"""', src.index('"""', i) + 3)]
    assert "PRT" not in block, "phân loại không được biết tên tệp cụ thể"
    assert "explanatory" not in block


# ── 1 · numeric-content summary ────────────────────────────────────────────

def test_tom_tat_noi_dung_so_theo_MAT_DO(rel):
    assert _col(rel, "numeric_content") == {
        "T": "dense", "N": "sparse", "F": "dense", "U": "unknown", "Z": "none"}


def test_ba_so_tho_ĐI_THEO_GOI(rel):
    """Người nhận phải tự đếm được, không phải tin một dòng markdown."""
    have = {d[0] for d in rel.execute("SELECT * FROM documents LIMIT 0").description}
    for c in ("n_table_markup", "n_numeric_tokens", "n_grouped_numbers"):
        assert c in have


# ── 3 · unclassified = 0 ───────────────────────────────────────────────────

def test_moi_tai_lieu_khong_co_bang_deu_noi_duoc_LY_DO(rel):
    n = rel.execute(
        "SELECT COUNT(*) FROM v_document_classification"
        " WHERE document_kind <> 'tabular'"
        "   AND table_exclusion_reason IS NULL").fetchone()[0]
    assert n == 0


def test_tabular_KHONG_mang_ly_do_loai_tru(rel):
    assert _col(rel, "table_exclusion_reason")["T"] is None
    assert _col(rel, "retrieval_route")["T"] == "table"


# ── VIEW, không phải bảng ──────────────────────────────────────────────────

def test_la_VIEW_de_khong_co_nguon_su_that_thu_hai(rel):
    kind = rel.execute(
        "SELECT type FROM sqlite_master WHERE name='v_document_classification'"
    ).fetchone()
    assert kind == ("view",)


def test_sua_n_tables_thi_phan_loai_doi_theo_NGAY(rel):
    rel.execute("UPDATE documents SET n_tables=3 WHERE document_uid='F'")
    assert _col(rel, "document_kind")["F"] == "tabular"
