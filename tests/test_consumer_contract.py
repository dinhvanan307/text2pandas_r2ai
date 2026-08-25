"""Hợp đồng tiêu thụ — Table Card và long DataFrame (doc 12 §3.5, §7).

Bộ kiểm này đứng ở phía NGƯỜI NHẬN gói, không phía người dựng. Nó hỏi đúng
những câu mà Retrieval và Text-to-Pandas sẽ hỏi:

    có đủ cột hợp đồng không · locator join được không · bảng `n_header=0`
    có giữ được cột phân biệt không · `execution_ready` có thật sự chặn không

Test nào ở đây đỏ nghĩa là gói bàn giao không dùng được, dù Silver bên trong
có sạch đến đâu.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_pipeline.readiness import build_readiness, load_policy
from data_pipeline.text_normalize import fts_match_expr, normalize_search_text
from data_pipeline.release_schema import (
    RELEASE_CARD_DDL, RELEASE_DDL, RELEASE_FTS_DDL, RELEASE_LONG_DDL,
    RELEASE_SCHEMA_VERSION)

# Danh sách cột doc 12 §3.5 khoá cứng. Bỏ bớt một cột là thay đổi BREAKING.
CONTRACT_COLUMNS = [
    "doc_id", "table_uid", "table_locator", "statement_type",
    "row_uid", "row_label", "row_path", "metric_code",
    "column_uid", "col_label", "col_path", "period_end",
    "value_raw", "value", "unit", "scale",
    "source_cell_uid", "quality_flags",
    "retrieval_ready", "execution_ready",
]


@pytest.fixture
def rel():
    con = sqlite3.connect(":memory:")
    con.executescript(RELEASE_DDL)
    con.executescript(RELEASE_CARD_DDL)
    con.executescript(RELEASE_LONG_DDL)
    con.executescript(RELEASE_FTS_DDL)
    yield con
    con.close()


def _cols(con, name):
    return [d[0] for d in con.execute(f"SELECT * FROM {name} LIMIT 0").description]


# ── hình dạng hợp đồng ──────────────────────────────────────────────────────

def test_long_dataframe_du_cot_hop_dong(rel):
    have = _cols(rel, "v_long_dataframe")
    missing = [c for c in CONTRACT_COLUMNS if c not in have]
    assert not missing, f"thiếu cột hợp đồng doc 12 §3.5: {missing}"


def test_long_dataframe_mang_toa_do():
    """`row_idx`/`col_idx` không nằm trong hợp đồng nhưng BẮT BUỘC phải có.

    Long format không có thứ tự thì pandas không tái lập được trật tự báo cáo,
    và câu hỏi kiểu "khoản mục ngay trên Tổng cộng" không trả lời được.
    """
    con = sqlite3.connect(":memory:")
    con.executescript(RELEASE_DDL)
    con.executescript(RELEASE_CARD_DDL)
    con.executescript(RELEASE_LONG_DDL)
    have = _cols(con, "v_long_dataframe")
    for c in ("row_idx", "col_idx", "value_kind", "currency", "period_role"):
        assert c in have, f"{c} — thiếu nó là mất khả năng truy vấn cơ bản"
    con.close()


def test_table_cards_co_ba_nhom_hash(rel):
    have = _cols(rel, "table_cards")
    for h in ("hash_identity", "hash_labels", "hash_semantics"):
        assert h in have
    # Tách ba nhóm để downstream biết dựng lại PHẦN NÀO, không phải tất cả.
    assert "content_hash" not in have, "một hash gộp thì không nói được phần nào đổi"


def test_table_cards_co_evidence_ref(rel):
    """C20: `relevant_tables` là `"<doc_id>|<locator>"`."""
    assert "evidence_ref" in _cols(rel, "table_cards")


def test_release_schema_version():
    assert RELEASE_SCHEMA_VERSION == "1.2"


# ── hành vi ─────────────────────────────────────────────────────────────────

def _seed(con, *, col_path="31/12/2023", collision=None, label="Tiền mặt",
          period="2023-12-31", unit="money"):
    tcols = _cols(con, "tables")
    t = dict.fromkeys(tcols)
    t.update(table_uid="T", document_uid="D", directory_doc_id="AAA_2023",
             ticker="AAA", doc_year=2023, basis="consolidated",
             industry_class="corporate", statement_type="note",
             statement_rule="R", is_data_table=1, line_start_1based=10,
             page_no=1, locator="line:10", evidence_ref="AAA_2023|line:10",
             n_grid_rows=3, n_grid_cols=2, n_header_rows=1, n_source_cells=4,
             numeric_ratio=0.5, sep_convention="dot", section_text="5 TIỀN",
             context_clean="ctx", parse_status="ok", quality_flags_json="[]")
    con.execute("INSERT INTO tables VALUES(" + ",".join("?" * len(tcols)) + ")",
                [t[c] for c in tcols])
    cols = _cols(con, "observations")
    d = dict.fromkeys(cols)
    d.update(observation_uid="o1", table_uid="T", source_cell_uid="s1",
             grid_row_idx=1, grid_col_idx=1, directory_doc_id="AAA_2023",
             ticker="AAA", doc_year=2023, statement_type="note",
             evidence_ref="AAA_2023|line:10", row_path_text="5 TIỀN › " + label,
             col_path_text=col_path, metric_label_clean=label,
             value_source="1.000.000", value_source_raw="1.000.000",
             value_decimal_text="1000000", value_kind="money",
             parse_status="ok", parse_rule="N-OK", is_negative=0,
             unit_kind=unit, currency="VND", scale_exponent=0,
             scale_source="cell", period_end=period, period_type="instant",
             period_role="closing", period_source="column_path", is_restated=0,
             confidence="high", quality_flags_json="[]",
             row_uid="R1", column_uid="C1", collision_class=collision)
    con.execute("INSERT INTO observations VALUES(" + ",".join("?" * len(cols)) + ")",
                [d[c] for c in cols])
    con.commit()
    # RC-02 · `v_long_dataframe` KHÔNG còn tự tính `execution_ready` nữa; nó
    # đọc `observation_readiness`. Fixture vì thế phải chạy CHÍNH SÁCH THẬT,
    # chứ không viết tay vài dòng readiness — viết tay sẽ dựng lại đúng cái
    # định nghĩa thứ hai mà RC-02 vừa xoá đi.
    build_readiness(con, load_policy())
    con.commit()


def test_locator_join_100_phan_tram(rel):
    _seed(rel)
    n = rel.execute(
        "SELECT COUNT(*) FROM v_long_dataframe WHERE table_locator IS NOT NULL"
    ).fetchone()[0]
    assert n == rel.execute("SELECT COUNT(*) FROM v_long_dataframe").fetchone()[0]


def test_col_label_khong_rong_khi_khong_co_header(rel):
    """Bảng `n_header=0` cho `col_path_text` rỗng.

    Nếu để rỗng thì `df.groupby('col_label')` bỏ NaN **âm thầm** — mất dữ liệu
    trong mắt người dùng mà không có lỗi nào. Phải rơi về `col:<idx>`.
    """
    _seed(rel, col_path="")
    got = rel.execute("SELECT col_label FROM v_long_dataframe").fetchone()[0]
    assert got == "col:1"


@pytest.mark.parametrize("kw, ready", [
    ({}, 1),
    ({"collision": "missing_row_parent"}, 0),
    ({"period": None}, 0),
    ({"unit": "unknown"}, 0),
    ({"label": ""}, 0),
])
def test_execution_ready_that_su_chan(rel, kw, ready):
    """`execution_ready` phải là một CỔNG, không phải một nhãn trang trí."""
    _seed(rel, **kw)
    assert rel.execute(
        "SELECT execution_ready FROM v_long_dataframe").fetchone()[0] == ready


def test_fts_khop_tieng_viet_ca_co_dau_lan_khong_dau(rel):
    # Cột TƯỜNG MINH — chèn theo vị trí vỡ mỗi lần schema thêm cột append-only,
    # và cái vỡ đó không nói gì về hành vi đang kiểm (bài học RC-06).
    rel.execute(
        "INSERT INTO table_cards (table_uid, doc_id, locator, evidence_ref,"
        " ticker, doc_year, statement_type, section_text, n_rows, n_cols,"
        " n_observations, row_terms, col_terms, metric_codes, periods, units,"
        " table_search_text, retrieval_ready, execution_ready_obs,"
        " review_required_obs, quality_flags_json, hash_identity, hash_labels,"
        " hash_semantics) VALUES('T','AAA_2023','line:10',"
        "'AAA_2023|line:10','AAA',2023,'note','5 TIỀN',3,2,2,"
        "'Tiền mặt | Tiền gửi ngân hàng','31/12/2023','111','2023-12-31',"
        "'money','5 TIỀN | Tiền gửi ngân hàng',1,2,0,'[]','h1','h2','h3')")
    # RC-05 · nạp qua ĐÚNG đường của `release.py`: nội dung ở dạng chuẩn.
    # Bản cũ ghi thẳng văn bản thô rồi hỏi `tiền AND gửi` — không có chữ `đ`
    # nào nên nó xanh cả trước lẫn sau khi lỗi được sửa, tức nó không kiểm
    # được điều mà tên nó hứa.
    rel.create_function("norm_search", 1,
                        lambda s: normalize_search_text(s or ""),
                        deterministic=True)
    rel.execute("INSERT INTO table_cards_fts SELECT table_uid, ticker,"
                " norm_search(section_text), norm_search(table_search_text),"
                " norm_search(row_terms), norm_search(col_terms)"
                " FROM table_cards")
    rel.commit()
    for q in ("tiền gửi", "tien gui", "TIỀN GỬI"):
        got = rel.execute(
            "SELECT table_uid FROM table_cards_fts WHERE table_cards_fts MATCH ?",
            (fts_match_expr(q),)).fetchall()
        assert got, f"FTS không khớp {q!r}"


# ── RC-02 · chính sách readiness ĐI THEO GÓI ────────────────────────────────

def test_goi_phat_hanh_CO_bang_readiness():
    """RC1 không có bảng này. Toàn bộ máy chính sách chạy rồi bị bỏ lại.

    `build_meta` của RC1 ghi `readiness_policy_version = '1.0'` — một dòng
    metadata mô tả một bảng không tồn tại trong chính gói đó.
    """
    from data_pipeline.release_schema import SLIM_TABLES
    assert "observation_readiness" in SLIM_TABLES


def test_long_dataframe_PHOI_BAY_ly_do_chu_khong_chi_mot_bit(rel):
    """Một bit `execution_ready` nói được "không", không nói được "vì sao"."""
    have = _cols(rel, "v_long_dataframe")
    for c in ("execution_candidate", "confidence", "blocking_reasons",
              "warning_reasons", "non_candidate_reasons", "review_required"):
        assert c in have, f"thiếu {c} — người nhận không audit được quyết định"


def test_view_KHONG_tu_dinh_nghia_lai_execution_ready(rel):
    """Bản v1.2 cũ có MỘT ĐỊNH NGHĨA THỨ HAI ngay trong view.

    Cách duy nhất chứng minh nó đã biến mất: sửa bảng chính sách và xem view
    có đổi theo không. Nếu view còn tự tính, nó sẽ trơ ra.
    """
    _seed(rel)
    assert rel.execute("SELECT execution_ready FROM v_long_dataframe").fetchone()[0] == 1
    rel.execute("UPDATE observation_readiness SET execution_ready=0,"
                " blocking_reasons_json='[\"ly_do_gia_dinh\"]'")
    rel.commit()
    ready, blk = rel.execute(
        "SELECT execution_ready, blocking_reasons FROM v_long_dataframe").fetchone()
    assert ready == 0, "view vẫn tự tính lại — định nghĩa thứ hai chưa bị xoá"
    assert blk == '["ly_do_gia_dinh"]'


def test_hop_dong_nguon_TU_CHOI_silver_khong_co_readiness(tmp_path):
    """Dựng gói từ Silver thiếu readiness = phát hành một gói không có chính sách.

    Phải dừng ở cổng, không phải im lặng rơi về định nghĩa cũ.
    """
    from data_pipeline.release import check_source_contract
    p = tmp_path / "silver.db"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE observations(row_uid TEXT, column_uid TEXT);"
        "CREATE TABLE collision_obs(observation_uid TEXT, collision_class TEXT);"
        "CREATE TABLE dropped_cells(source_cell_uid TEXT, reason TEXT);"
        "CREATE TABLE build_meta(key TEXT, value TEXT);")
    con.commit()
    con.close()
    assert any("observation_readiness" in m for m in check_source_contract(p))
