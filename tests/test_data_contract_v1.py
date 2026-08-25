"""Data Contract v1 — bộ kiểm bảo vệ hợp đồng đóng băng 08/08/2026.

Bộ test này KHÔNG kiểm chất lượng dữ liệu. Nó kiểm rằng **hình dạng** của dữ
liệu không đổi. Đó là toàn bộ ý nghĩa của Contract Freeze: chất lượng còn được
cải thiện tiếp, hình dạng thì không.

Test nào ở đây đỏ nghĩa là một thay đổi BREAKING đã lọt vào — downstream sẽ
phải xây lại. Không được sửa test cho xanh; phải sửa code hoặc bump major.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.models import ColumnInfo, ColumnRole, RowInfo, RowRole
from text2pandas.pipelines.a6.readiness import apply_policy, load_policy
from text2pandas.pipelines.a6.storage import (
    SCHEMA_VERSION, SILVER_DDL, stamp_schema_version)

# Trường [F3]: cố ý NULL ở v1.0, được điền ở các minor về sau. Chúng phải TỒN
# TẠI từ ngày đóng băng, nếu không mọi cải tiến ngữ nghĩa là breaking change.
F3_FIELDS = {
    "rows": ["parent_row_uid", "hierarchy_level", "hierarchy_source",
             "hierarchy_confidence", "structural_role", "accounting_role"],
    "columns": ["parent_column_uid", "column_group_source",
                "column_group_confidence"],
    "table_features": ["table_group_uid", "table_group_role",
                       "table_group_confidence", "section_source_line",
                       "section_rule", "section_confidence"],
}

# Trường danh tính vật lý. Đổi bất kỳ cái nào là major version.
IDENTITY_FIELDS = {
    "observations": ["observation_uid", "source_cell_uid", "table_uid",
                     "row_uid", "column_uid", "grid_row_idx", "grid_col_idx"],
    "rows": ["table_uid", "grid_row_idx", "row_uid"],
    "columns": ["table_uid", "grid_col_idx", "column_uid"],
}


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.executescript(SILVER_DDL)
    yield con
    con.close()


def _cols(con, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


# ── hình dạng schema ────────────────────────────────────────────────────────

@pytest.mark.parametrize("table,fields", F3_FIELDS.items())
def test_f3_fields_exist(db, table, fields):
    """Chỗ chứa phải có sẵn từ ngày đóng băng, dù còn rỗng.

    Đây là điều khoản trung tâm của Contract Freeze: ta không đóng băng những
    gì đã biết, mà đóng băng CHỖ ĐỂ CHỨA những gì sẽ biết.
    """
    have = _cols(db, table)
    missing = [f for f in fields if f not in have]
    assert not missing, f"{table} thiếu trường [F3]: {missing}"


@pytest.mark.parametrize("table,fields", IDENTITY_FIELDS.items())
def test_identity_fields_exist(db, table, fields):
    have = _cols(db, table)
    assert not [f for f in fields if f not in have]


def test_f3_nullable(db):
    """[F3] phải cho phép NULL — v1.0 chưa có gì để điền."""
    for table, fields in F3_FIELDS.items():
        notnull = {r[1]: r[3] for r in db.execute(f"PRAGMA table_info({table})")}
        for f in fields:
            assert notnull[f] == 0, f"{table}.{f} là NOT NULL — v1.0 không điền được"


def test_uid_fields_not_null(db):
    """Ngược lại, danh tính vật lý KHÔNG được phép rỗng."""
    for table, field in (("rows", "row_uid"), ("columns", "column_uid"),
                         ("observations", "row_uid"), ("observations", "column_uid")):
        notnull = {r[1]: r[3] for r in db.execute(f"PRAGMA table_info({table})")}
        assert notnull[field] == 1, f"{table}.{field} phải NOT NULL"


# ── tính ổn định của UID ────────────────────────────────────────────────────

def test_row_uid_độc_lập_với_ngữ_nghĩa():
    """`row_uid` chỉ phụ thuộc toạ độ vật lý.

    Đây là điều kiện để v1.2 điền `parent_row_uid` và đổi `row_path` mà vẫn là
    ENRICHMENT: downstream so được build cũ với build mới theo cùng một dòng.
    """
    a = RowInfo("T1", 7, RowRole.METRIC, "Tiền mặt", "Tiền mặt", ["s", "Tiền mặt"], 0)
    b = RowInfo("T1", 7, RowRole.TOTAL, "KHÁC HẲN", "KHÁC HẲN",
                ["s", "A", "B", "KHÁC HẲN"], 3)
    b.parent_row_uid, b.hierarchy_source = "abc123", "taxonomy"
    assert a.row_uid == b.row_uid


def test_uid_đổi_khi_toạ_độ_đổi():
    a = RowInfo("T1", 7, RowRole.METRIC, "x", "x", [], 0)
    assert a.row_uid != RowInfo("T1", 8, RowRole.METRIC, "x", "x", [], 0).row_uid
    assert a.row_uid != RowInfo("T2", 7, RowRole.METRIC, "x", "x", [], 0).row_uid


def test_column_uid_độc_lập_với_ngữ_nghĩa():
    a = ColumnInfo("T1", 3, ColumnRole.VALUE, ["31/12/2023"])
    b = ColumnInfo("T1", 3, ColumnRole.NOTE_REFERENCE, ["hoàn toàn khác"])
    assert a.column_uid == b.column_uid


# ── phiên bản ───────────────────────────────────────────────────────────────

def test_schema_version_được_ghi(db):
    stamp_schema_version(db)
    got = dict(db.execute("SELECT key, value FROM build_meta"))
    assert got["schema_version"] == SCHEMA_VERSION


def test_schema_version_là_1_0():
    """Đổi số này ngoài quy trình bump version là lỗi quy trình, không phải lỗi code."""
    assert SCHEMA_VERSION == "1.0"


# ── readiness là CHÍNH SÁCH, không phải dữ liệu ─────────────────────────────

def _obs(con, uid, flags=(), **over):
    cols = _cols(con, "observations")
    d = dict.fromkeys(cols)
    d.update(observation_uid=uid, table_uid="T", source_cell_uid="S" + uid,
             grid_row_idx=1, grid_col_idx=1, row_path_json="[]", row_path_text="",
             col_path_json="[]", col_path_text="", metric_label_source="Tiền mặt",
             metric_label_clean="Tiền mặt", value_source="100", value_clean="100",
             value_decimal_text="100", value_kind="money", parse_status="ok",
             parse_rule="N-OK", is_negative=0, unit_kind="money",
             unit_kind_source="cell", currency_source="cell", scale_source="cell",
             period_end="2023-12-31", period_type="instant", period_role="closing",
             period_source="column_path", is_restated=0, dimensions_json="{}",
             quality_flags_json=json.dumps(sorted(flags)), row_uid="R", column_uid="C")
    d.update(over)
    con.execute("INSERT INTO observations VALUES(" + ",".join("?" * len(cols)) + ")",
                [d[c] for c in cols])


def test_readiness_không_phải_cột_trong_bảng(db):
    """Ba cờ readiness KHÔNG được nằm trong Data Core.

    Tài liệu 07 §2.1 xếp chúng vào phần đóng băng. Đó là lỗi kiến trúc: chúng
    là NGƯỠNG của người tiêu thụ. Nướng vào bảng nghĩa là mỗi lần nới ngưỡng
    phải rebuild 2,5 triệu observation.
    """
    for t in ("observations", "table_features", "rows", "columns"):
        have = _cols(db, t)
        for f in ("retrieval_ready", "execution_ready", "review_required"):
            assert f not in have, f"{f} không được là cột của {t} — nó là chính sách"


def test_readiness_view_sinh_được(db):
    apply_policy(db, load_policy())
    views = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='view'")}
    assert {"v_retrieval_ready", "v_execution_ready"} <= views


# Cập nhật theo chính sách readiness v2.1 (RC-02).
#
# v2.0 hạ `period_from_table` và `generic_row_label` từ CHẶN xuống CẢNH BÁO
# phẳng, kèm một dòng `allowed_if` bằng văn xuôi mà không ai thi hành.
# v2.1 biến "kèm điều kiện" thành điều kiện THẬT:
#
#   generic_row_label  → warning  khi `row_path_text` phân biệt được
#                      → blocking khi row_path rỗng hoặc trùng chính nhãn
#
# Fixture ở đây có `row_path_text=""`, tức đúng ca KHÔNG phân biệt được —
# nên `nhan_chung` chuyển từ 1 sang 0. Đây không phải siết lại vô cớ: một
# nhãn `Cộng` mà không có đường dẫn dòng thì không định danh được fact nào.
@pytest.mark.parametrize("uid,flags,over,ready", [
    ("sach",       (),                              {},                     1),
    ("bac_bac",    ("scale_rejected_implausible",), {},                     0),
    ("ky_suy",     ("period_from_table",),          {},                     1),
    ("nhan_chung", ("generic_row_label",),          {},                     0),
    # Cùng cờ, KHÁC bằng chứng → khác kết quả. Đây là thứ v2.0 không làm được.
    ("nhan_chung_co_path", ("generic_row_label",),
     {"row_path_text": "Tài sản ngắn hạn > Tiền mặt"},                       1),
    ("thieu_ky",   (),                              {"period_end": None},   0),
    ("nhan_rong",  (),                              {"metric_label_clean": ""}, 0),
    ("don_vi_ko",  (),                              {"unit_kind": "unknown"},   0),
    # Mới ở v2.0 — đây là chính lỗ hổng A-04.
    ("vai_tro_ko", ("column_role_unknown",),        {},                     0),
    ("tien_be",    ("tiny_money_unresolved",),      {},                     0),
])
def test_execution_ready(db, uid, flags, over, ready):
    _obs(db, uid, flags, **over)
    apply_policy(db, load_policy())
    got = db.execute(
        "SELECT execution_ready FROM v_execution_ready WHERE observation_uid=?",
        (uid,)).fetchone()[0]
    assert got == ready


def test_cờ_khớp_nguyên_vẹn_không_khớp_tiền_tố(db):
    """`generic_row_label` không được khớp bởi một cờ khác chứa nó làm tiền tố."""
    _obs(db, "khac", ("generic_row_label_something_else",))
    apply_policy(db, load_policy())
    got = db.execute(
        "SELECT execution_ready FROM v_execution_ready WHERE observation_uid=?",
        ("khac",)).fetchone()[0]
    assert got == 1


def test_nới_ngưỡng_không_cần_rebuild(db):
    """Bằng chứng cho quyết định kiến trúc: đổi chính sách, dữ liệu không đụng.

    Cùng một hàng dữ liệu, hai chính sách khác nhau, hai kết quả khác nhau —
    và không có một câu INSERT/UPDATE nào vào `observations` giữa hai lần đo.
    """
    _obs(db, "x", ("column_role_unknown",))
    apply_policy(db, load_policy())
    truoc = db.execute("SELECT execution_ready FROM v_execution_ready").fetchone()[0]

    # Nới đúng như `planned_relaxations` mô tả: hạ `column_role_unknown` từ
    # chặn xuống cảnh báo sau khi có Structure Gold.
    #
    # Phải gỡ ở CẢ HAI chỗ — danh sách chặn và danh sách hạ confidence. Bản
    # đầu chỉ gỡ một chỗ và test này đỏ, phơi ra đúng cái khớp nối mà RC-02
    # sinh ra để xoá: `confidence` từng là hằng số trong Python nên chính sách
    # không với tới. Giờ cả hai đều nằm trong YAML.
    long_ = load_policy()
    er = long_.raw["execution_ready"]
    er["blocking_flags"] = [b for b in er["blocking_flags"]
                            if b["flag"] != "column_role_unknown"]
    conf = long_.raw["confidence"]
    conf["low_if_flags"] = [f for f in conf["low_if_flags"]
                            if f != "column_role_unknown"]
    apply_policy(db, long_)
    sau = db.execute("SELECT execution_ready FROM v_execution_ready").fetchone()[0]

    assert (truoc, sau) == (0, 1)


def test_chính_sách_khai_báo_lịch_nới_ngưỡng():
    """Ngưỡng chặt phải kèm kế hoạch gỡ, nếu không nó là nợ chứ không phải quyết định."""
    pol = load_policy()
    plans = pol.raw.get("planned_relaxations") or []
    assert plans, "chính sách phải khai báo lịch nới ngưỡng"
    hoan = {p["flag"] for p in plans if "flag" in p}
    blocking = {f for f, _ in pol.blocking}
    assert hoan <= blocking, f"khai gỡ cờ không nằm trong danh sách chặn: {hoan - blocking}"
    for p in plans:
        assert p.get("condition") and p.get("action"), \
            "mỗi kế hoạch nới phải nói RÕ điều kiện và hành động"
