"""Tài liệu bàn giao phải SINH TỪ DỮ LIỆU, và phải trung thực khi thiếu số.

Bộ kiểm này bảo vệ một tính chất dễ mất: tài liệu nói về hạn chế của dữ liệu
mà bản thân nó sai số liệu thì tệ hơn không có tài liệu — người đọc tin nó và
lập kế hoạch theo nó. Ba nguy cơ được khoá ở đây:

1. **Số gõ tay quay lại.** `SILVER_REPORT.md §5` từng liệt kê "200.195 ô",
   "116.857 ô" — đúng vào tháng viết ra, sai sau bản dựng kế tiếp.
2. **Thiếu bảng thì im lặng.** Một Silver cũ không có `dropped_cells` mà tài
   liệu vẫn in ra bảng trống trông y hệt "không có vấn đề nào".
3. **Cổng `BLOCKED` không được khai.** Doc 12 §7 số 12 đòi khai rõ; một cổng
   chưa đo mà không nói ra thì đọc như một cổng đã qua.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.release_docs import (  # noqa: E402
    DOC_FILES, _DROP_VERDICT, build_docs)
from text2pandas.pipelines.a6.release_schema import (  # noqa: E402
    RELEASE_CARD_DDL, RELEASE_DDL, RELEASE_FTS_DDL, RELEASE_LONG_DDL)


class _Rep:
    build_id = "b0b0b0b0b0b0b0b0"
    release_label = "silver-v1.0.0-rc1"
    blocked_gates = ["G3 Structure · độ chính xác role trên gold = BLOCKED"]


def _cols(con, t):
    return [d[0] for d in con.execute(f"SELECT * FROM {t} LIMIT 0").description]


def _ins(con, t, **kw):
    c = _cols(con, t)
    d = dict.fromkeys(c)
    d.update(kw)
    con.execute(f"INSERT OR IGNORE INTO {t} VALUES(" + ",".join("?" * len(c)) + ")",
                [d[x] for x in c])


def _make(tmp_path, *, n_obs=6, drops=(("parse_ambiguous", 3),),
          collisions=("missing_dimension",), with_dropped_table=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "silver.db"
    con = sqlite3.connect(p)
    for ddl in (RELEASE_DDL, RELEASE_CARD_DDL, RELEASE_LONG_DDL, RELEASE_FTS_DDL):
        con.executescript(ddl)
    if not with_dropped_table:
        con.execute("DROP TABLE dropped_cells")

    _ins(con, "documents", document_uid="D", directory_doc_id="AAA_2023",
         ticker="AAA", doc_year=2023, basis="consolidated", rel_path="a.txt",
         n_bytes=1, n_lines=1, n_pages=1, n_tables=1, sha256="x")
    _ins(con, "tables", table_uid="T", document_uid="D",
         directory_doc_id="AAA_2023", ticker="AAA", doc_year=2023,
         basis="consolidated", industry_class="corporate", statement_type="note",
         is_data_table=1, line_start_1based=10, page_no=1, locator="line:10",
         evidence_ref="AAA_2023|line:10", n_grid_rows=3, n_grid_cols=2,
         n_header_rows=1, n_source_cells=4, numeric_ratio=0.5,
         sep_convention="dot", parse_status="ok", quality_flags_json="[]")
    _ins(con, "columns", table_uid="T", grid_col_idx=1, column_role="value",
         period_type="instant", period_role="closing", period_source="column_path",
         is_restated=0, unit_kind="money", numeric_ratio=1.0, flags_json="[]")
    for i in range(n_obs):
        _ins(con, "rows", table_uid="T", grid_row_idx=i, row_role="data",
             label_clean="Tiền", row_path_json="[]", is_generic_label=0,
             flags_json="[]")
        _ins(con, "observations", observation_uid=f"o{i}", table_uid="T",
             source_cell_uid=f"s{i}", grid_row_idx=i, grid_col_idx=1,
             directory_doc_id="AAA_2023", ticker="AAA", doc_year=2023,
             statement_type="note", evidence_ref="AAA_2023|line:10",
             metric_label_clean="Tiền", value_source="1", value_decimal_text="1",
             value_kind="money", parse_status="ok", parse_rule="N-OK",
             is_negative=0, unit_kind="money", scale_source="cell",
             period_end="2023-12-31", period_type="instant",
             period_role="closing", period_source="column_path", is_restated=0,
             confidence="high", quality_flags_json="[]", row_uid=f"R{i}",
             column_uid="C1",
             collision_class=collisions[i % len(collisions)] if collisions and i == 0 else None)
    if with_dropped_table:
        for reason, n in drops:
            for j in range(n):
                _ins(con, "dropped_cells", source_cell_uid=f"{reason}{j}",
                     table_uid="T", grid_row_idx=1, grid_col_idx=2,
                     reason=reason, detail="d", text_clean="31/12/2019")
    con.commit()
    con.close()
    return p


@pytest.fixture
def docs(tmp_path):
    return build_docs(_make(tmp_path), _Rep())


# ── hình dạng ───────────────────────────────────────────────────────────────

def test_sinh_du_ba_tep(docs):
    assert set(docs) == set(DOC_FILES)
    for name, body in docs.items():
        assert body.startswith("# "), f"{name} phải mở bằng H1"
        assert body.endswith("\n")


def test_moi_tep_khai_build_id(docs):
    """Số không có `build_id` là số không so được giữa hai bản dựng."""
    for name, body in docs.items():
        assert _Rep.build_id in body, f"{name} không khai build_id"


# ── số phải đến từ DB ───────────────────────────────────────────────────────

def test_so_lieu_thay_doi_theo_du_lieu(tmp_path):
    """Khoá chống số gõ tay: đổi dữ liệu thì tài liệu PHẢI đổi theo."""
    a = build_docs(_make(tmp_path / "a", n_obs=6), _Rep())["DATA_OVERVIEW.md"]
    b = build_docs(_make(tmp_path / "b", n_obs=9), _Rep())["DATA_OVERVIEW.md"]
    assert "| **6** |" in a and "| **9** |" in b, \
        "số observation phải truy vấn từ DB, không gõ tay"


def test_so_o_bi_loai_theo_ly_do(tmp_path):
    d = build_docs(_make(tmp_path, drops=(("parse_ambiguous", 7),
                                          ("empty_or_dash", 2))),
                   _Rep())["KNOWN_ISSUES.md"]
    assert "`parse_ambiguous` | 7" in d
    assert "`empty_or_dash` | 2" in d


def test_ly_do_la_moi_khong_bi_nuot(tmp_path):
    """Một `reason` chưa có phán xét phải HIỆN RA, không bị bỏ qua.

    Nếu bỏ qua, một chế độ loại ô mới sẽ lặng lẽ không bao giờ được nhắc tới
    trong tài liệu — đúng loại im lặng mà tài liệu này sinh ra để chống.
    """
    d = build_docs(_make(tmp_path, drops=(("mot_ly_do_hoan_toan_moi", 5),)),
                   _Rep())["KNOWN_ISSUES.md"]
    assert "mot_ly_do_hoan_toan_moi" in d
    assert "chưa đánh giá" in d


def test_moi_ly_do_da_biet_deu_co_phan_xet():
    for reason, (verdict, why) in _DROP_VERDICT.items():
        assert verdict and why, f"{reason} thiếu phán xét hoặc giải thích"


# ── trung thực khi thiếu số ─────────────────────────────────────────────────

def test_thieu_bang_thi_noi_ro_khong_im_lang(tmp_path):
    """Silver cũ không có `dropped_cells`: tài liệu không được nổ, nhưng cũng
    không được in bảng trống trông như 'không có vấn đề nào'."""
    d = build_docs(_make(tmp_path, with_dropped_table=False),
                   _Rep())["KNOWN_ISSUES.md"]
    assert "không đo được" in d
    assert "không kiểm chứng được" in d


def test_db_rong_van_sinh_duoc(tmp_path):
    """Gói rỗng là một gói hỏng — nhưng tài liệu vẫn phải sinh ra để nói điều đó."""
    d = build_docs(_make(tmp_path, n_obs=0, drops=(), collisions=()), _Rep())
    assert len(d) == 3
    assert "không thể" in d["KNOWN_ISSUES.md"], \
        "phải cảnh báo rằng 0 đụng độ trên corpus thật là bất thường"


# ── khai rõ cổng BLOCKED ────────────────────────────────────────────────────

def test_blocked_gate_duoc_khai_ro(docs):
    k = docs["KNOWN_ISSUES.md"]
    assert "G3 Structure" in k
    assert "chưa từng được đo" in k
    assert "không** phải `production`" in k


def test_khong_co_blocked_thi_noi_thang(tmp_path):
    class Clean(_Rep):
        blocked_gates: list[str] = []
    d = build_docs(_make(tmp_path), Clean())["KNOWN_ISSUES.md"]
    assert "Không có cổng nào ở trạng thái `BLOCKED`" in d


# ── bất biến nội dung ───────────────────────────────────────────────────────

@pytest.mark.parametrize("phrase", [
    "execution_ready",          # cổng bắt buộc trước mọi phép tính
    "Decimal",                  # DI-05
    "row_uid",                  # danh tính vật lý
    "TỪ CHỐI",                  # im lặng tốt hơn số sai
])
def test_usage_guide_day_du_luat_cot_loi(docs, phrase):
    assert phrase in docs["USAGE_GUIDE.md"], f"thiếu luật cốt lõi: {phrase}"


def test_overview_khai_cai_KHONG_co(docs):
    """Người nhận cần biết cái gì không có, để không đi tìm."""
    o = docs["DATA_OVERVIEW.md"]
    for x in ("Structure Gold", "embedding", "nhãn vàng"):
        assert x in o


def test_bang_markdown_hop_le(docs):
    """Mỗi bảng phải có dòng phân cách ngay sau dòng tiêu đề, và số cột khớp.

    Bảng lệch cột render vỡ trên GitHub — tài liệu đúng nội dung mà không đọc
    được thì cũng như không có.
    """
    for name, body in docs.items():
        lines = body.split("\n")
        for i, ln in enumerate(lines):
            if not (ln.startswith("| ") and i + 1 < len(lines)):
                continue
            nxt = lines[i + 1]
            if not re.fullmatch(r"\|[\s:-]+\|", nxt.replace("|", "|")):
                continue
            n_head = ln.count("|") - 1
            n_sep = nxt.count("|") - 1
            assert n_head == n_sep, f"{name} dòng {i+1}: {n_head} cột vs {n_sep}"
            for j in range(i + 2, len(lines)):
                if not lines[j].startswith("| "):
                    break
                assert lines[j].count("|") - 1 == n_head, \
                    f"{name} dòng {j+1}: số cột lệch so với tiêu đề"
