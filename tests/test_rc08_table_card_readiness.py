"""RC-08 · Table Card — MỘT định nghĩa `retrieval_ready`, và năm trường thiếu.

Hai khiếm khuyết, hai loại khác nhau:

1. `retrieval_ready` được định nghĩa ĐỘC LẬP ở hai nơi:
       readiness.py::v_retrieval_ready   locator ≠ '' ∧ evidence_ref ≠ ''
       release.py::_build_cards          parse_status='ok' ∧ type ≠ 'toc'
   Đo trên RC1: cả hai cùng cho 146.246/146.246. Nên nói cho đúng — chúng
   **chưa mâu thuẫn**, chúng **độc lập**. Vẫn phải sửa, nhưng đây là khiếm
   khuyết bảo trì chứ không phải một lỗi dữ liệu đang xảy ra.

2. `table_cards` thiếu 5 trường của `table_readiness_contract`, nên tầng truy
   hồi phải JOIN 2,6 triệu observation để trả lời một câu hỏi cấp BẢNG.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.a6.readiness import retrieval_ready_expr  # noqa: E402
from text2pandas.pipelines.a6.release_schema import (  # noqa: E402
    RELEASE_CARD_DDL, RELEASE_DDL)

CONTRACT = ROOT / "configs" / "rc2_contracts_v1.yaml"


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.executescript(RELEASE_DDL)
    con.executescript(RELEASE_CARD_DDL)
    yield con
    con.close()


def _tbl(con, uid, **kw):
    cols = [d[1] for d in con.execute("PRAGMA table_info(tables)")]
    d = dict.fromkeys(cols)
    d.update(table_uid=uid, document_uid="D", directory_doc_id="AAA_2023",
             ticker="AAA", doc_year=2023, basis="consolidated",
             industry_class="corporate", statement_type="note", statement_rule="R",
             is_data_table=1, line_start_1based=10, page_no=1,
             locator="line:10", evidence_ref="AAA_2023|line:10",
             n_grid_rows=3, n_grid_cols=2, n_header_rows=1, n_source_cells=4,
             numeric_ratio=0.5, sep_convention="dot", section_text="s",
             context_clean="c", parse_status="ok", quality_flags_json="[]")
    d.update(kw)
    con.execute("INSERT INTO tables VALUES(" + ",".join("?" * len(cols)) + ")",
                [d[c] for c in cols])


# ── 1 · MỘT định nghĩa ─────────────────────────────────────────────────────

def test_dinh_nghia_giu_TRON_ca_hai_y(db):
    """Hai vế cũ nói về hai điều kiện KHÁC nhau, không phải hai phiên bản."""
    _tbl(db, "ok")
    _tbl(db, "khong_locator", locator="", evidence_ref="")
    _tbl(db, "parse_loi", parse_status="failed")
    _tbl(db, "muc_luc", statement_type="toc")
    db.commit()
    got = dict(db.execute(
        f"SELECT t.table_uid, {retrieval_ready_expr('t')} FROM tables t"))
    assert got == {"ok": 1, "khong_locator": 0, "parse_loi": 0, "muc_luc": 0}


def test_release_py_KHONG_con_tu_dinh_nghia(db):
    """Chống hồi quy ở mức nguồn — biểu thức cũ không được quay lại."""
    src = (ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "release.py").read_text(encoding="utf-8")
    assert 'pstatus == "ok" and stype != "toc"' not in src
    assert "retrieval_ready_expr" in src


def test_dinh_nghia_DOC_LAP_voi_execution(db):
    """`table_readiness_contract`: "ĐỘC LẬP với execution".

    Một bảng tìm được mà không ô nào đủ tin để tự động tính — hai trục khác
    nhau. Biểu thức không được nhắc tới readiness của observation.
    """
    e = retrieval_ready_expr("t")
    for forbidden in ("execution_ready", "execution_candidate", "confidence",
                      "observation_readiness"):
        assert forbidden not in e


# ── 2 · năm trường thiếu ───────────────────────────────────────────────────

def test_du_TAM_truong_cua_table_readiness_contract(db):
    con = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    want = con["table_readiness_contract"]["fields"]
    have = {d[1] for d in db.execute("PRAGMA table_info(table_cards)")}
    missing = [f for f in want if f not in have]
    assert not missing, f"thiếu {missing}"


def test_co_has_la_DAN_XUAT_cua_so_dem(db):
    """`has_*` phải nhất quán với `*_obs`, nếu không thì nó là nguồn thứ hai."""
    have = {d[1] for d in db.execute("PRAGMA table_info(table_cards)")}
    for c, n in (("has_observations", "n_observations"),
                 ("has_execution_candidate", "execution_candidate_obs"),
                 ("has_execution_ready", "execution_ready_obs")):
        assert c in have and n in have


def test_ly_do_khong_ready_dem_theo_TUNG_ma(db):
    """"40 ô không dùng được" không sửa được gì. "40 ô vì confidence_low" thì có."""
    db.execute(
        "INSERT INTO table_cards (table_uid, doc_id, locator, evidence_ref,"
        " ticker, statement_type, n_rows, n_cols, n_observations,"
        " retrieval_ready, execution_ready_obs, review_required_obs,"
        " quality_flags_json, hash_identity, hash_labels, hash_semantics,"
        " not_ready_reason_counts_json)"
        " VALUES('T','d','line:1','d|line:1','AAA','note',1,1,50,1,10,40,'[]',"
        "'a','b','c', '{\"confidence_low\":40}')")
    db.commit()
    blob = db.execute("SELECT not_ready_reason_counts_json FROM table_cards"
                      ).fetchone()[0]
    assert json.loads(blob) == {"confidence_low": 40}


def test_mac_dinh_cua_nam_truong_moi_la_AN_TOAN(db):
    """Thẻ dựng bởi mã cũ phải mặc định về 0/`{}`, không phải NULL.

    NULL ở đây nghĩa là "không biết", và tầng truy hồi lọc `has_* = 1` sẽ âm
    thầm bỏ qua nó — mất bảng mà không có lỗi nào.
    """
    db.execute(
        "INSERT INTO table_cards (table_uid, doc_id, locator, evidence_ref,"
        " ticker, statement_type, n_rows, n_cols, n_observations,"
        " retrieval_ready, execution_ready_obs, review_required_obs,"
        " quality_flags_json, hash_identity, hash_labels, hash_semantics)"
        " VALUES('T2','d','line:1','d|line:1','AAA','note',1,1,0,1,0,0,'[]',"
        "'a','b','c')")
    db.commit()
    r = db.execute("SELECT execution_candidate_obs, has_observations,"
                   " has_execution_candidate, has_execution_ready,"
                   " not_ready_reason_counts_json FROM table_cards"
                   " WHERE table_uid='T2'").fetchone()
    assert r == (0, 0, 0, 0, "{}")
