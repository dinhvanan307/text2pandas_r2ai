"""RC-03 · `tiny_money` đã được NỐI vào build, không chỉ tồn tại như một module.

Bản audit đếm được 2.836 ca `Q-OBS-TINY-MONEY` và chỉ *gắn cờ* chúng. Doc 17
gọi đây là "task data correctness ưu tiên cao nhất" vì gắn cờ không sửa được
gì: một mã Thông tư 200 (`110`) vẫn nằm trong `observations` dưới dạng
"110 đồng", và downstream vẫn cộng nó vào tổng.

Bốn hành vi được khoá ở đây, mỗi cái ứng với một cách hỏng đã đo được:

1. Giá trị giả (mã số · số hiệu thuyết minh · STT) **rời khỏi** `observations`
   và **có mặt** trong `dropped_cells` — mất khỏi bảng fact nhưng không mất
   khỏi kiểm toán.
2. Nhóm 740 ca mà luật cũ buộc tội oan (bảng khai `triệu đồng`, ô ghi `3`)
   **được giữ**, vì thước đo đã sửa: so ngưỡng SAU khi áp scale.
3. Ca không đủ bằng chứng **được giữ** nhưng mang cờ `tiny_money_unresolved`
   — DI-07 cấm đoán, và chính sách readiness đã khai cờ này ở `blocking_flags`.
4. Giá trị `0` **không** bị coi là tiny money. `0` là số liệu hợp lệ; DI-06 đã
   tách nó khỏi dấu gạch, và gộp lại ở đây sẽ xoá dữ liệu thật.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from data_pipeline.observation_builder import (
    _column_digit_profile, build_silver_tables)
from data_pipeline.storage import BRONZE_DDL, SILVER_DDL, connect, integrity_check
from data_pipeline.tiny_money import (
    FALSE_VALUE_CLASSES, classify_tiny_money, is_reference_header)

# ─────────────────────── S1 · dung sai OCR ở nhãn cột ───────────────────────


@pytest.mark.parametrize("header, expect", [
    ("Mã số", "metric_code"),
    ("Másố", "metric_code"),          # mất dấu cách
    ("M8 số", "metric_code"),         # `ã` → `8`
    ("Mã sơ", "metric_code"),         # mất dấu nặng
    ("MS", "metric_code"),
    ("Thuyết minh", "note_reference"),
    ("TM ›", "note_reference"),       # ký tự rác đuôi
    ("STT", "ordinal"),
    ("31/12/2018", None),
    ("Nguyên giá", None),
    ("", None),
    (None, None),
])
def test_reference_header_ocr_tolerance(header, expect):
    assert is_reference_header(header) == expect


def test_ocr_mixed_header_prefers_note_reference():
    """`Mã Thuyết số minh` là hai tiêu đề bị OCR trộn — nội dung là số hiệu mục."""
    assert is_reference_header("Mã Thuyết số minh") == "note_reference"


# ───────────────────── thước đo sửa TRƯỚC khi kết tội ─────────────────────


def test_scaled_value_above_threshold_is_legitimate():
    """740/2.836 ca: bảng khai `triệu đồng`, ô ghi `3` → 3.000.000 VND."""
    cls, why = classify_tiny_money(
        value_decimal_text="3", value_source="3", scale_exponent=6,
        unit_kind="money", scale_source="table_context",
        header_path_text="Năm nay", row_label="Chi phí khác")
    assert cls == "legitimate_small_money"
    assert "THÔ" in why          # lý do phải NÓI RA rằng luật cũ đo sai


def test_section_number_beats_everything():
    """`5.18` không phải 5,18 đồng dù cột được gán vai trò gì."""
    cls, _ = classify_tiny_money(
        value_decimal_text="5.18", value_source="5.18", scale_exponent=0,
        unit_kind="money", scale_source="none",
        header_path_text="Năm nay", row_label="Tiền và tương đương tiền")
    assert cls == "note_reference_false_value"


def test_no_signal_stays_unresolved():
    """Không tín hiệu nào đủ mạnh → KHÔNG đoán. Đây là hành vi đúng của DI-07."""
    cls, _ = classify_tiny_money(
        value_decimal_text="12", value_source="12", scale_exponent=0,
        unit_kind="money", scale_source="none",
        header_path_text="Năm nay", row_label="Khoản mục khác")
    assert cls == "parse_or_column_role_unresolved"


# ─────────────────────── S3 · hồ sơ chữ số cấp cột ───────────────────────


class _Cell:
    __slots__ = ("grid_row_idx", "grid_col_idx", "text_clean")

    def __init__(self, r, c, t):
        self.grid_row_idx, self.grid_col_idx, self.text_clean = r, c, t


class _PT:
    def __init__(self, cells):
        self.source_cells = cells


class _Row:
    def __init__(self, role):
        self.row_role = role


def test_digit_profile_peer_is_max_of_others():
    from data_pipeline.models import RowRole
    pt = _PT([
        _Cell(0, 0, "2024"), _Cell(0, 1, "Mã số"),      # dòng header — bỏ qua
        _Cell(1, 0, "Tiền"), _Cell(1, 1, "110"), _Cell(1, 2, "20.559.756.794"),
        _Cell(2, 0, "Nợ"), _Cell(2, 1, "300"), _Cell(2, 2, "1.234.567"),
    ])
    rows = {0: _Row(RowRole.HEADER), 1: _Row(RowRole.METRIC), 2: _Row(RowRole.METRIC)}
    prof = _column_digit_profile(pt, rows)
    # cột 1 có tối đa 3 chữ số; cột dài nhất KHÁC nó là cột 2 với 11.
    assert prof[1] == (3, 11)
    # cột 2 chính là cực đại, nên peer của nó là cực đại THỨ HAI.
    assert prof[2] == (11, 3)
    # `2024` ở dòng header không được tính, và cột 0 không có chữ số nào nên
    # nó vắng mặt hoàn toàn — không phải mang giá trị 0.
    assert 0 not in prof


# ─────────────────────── tích hợp: chạy trong build ───────────────────────

# Cột `M8 số` cố tình là bản OCR hỏng của `Mã số`: `structure.py` KHÔNG nhận ra
# nên nó lọt qua bộ lọc `non_value_column` và trở thành cột `value`. Đây đúng
# là đường đi của 472 ca đo được trên build thật.
_DOC = """===== PAGE 1 =====
CÔNG TY CỔ PHẦN MẪU
Đơn vị tính: VND

BẢNG CÂN ĐỐI KẾ TOÁN
<table><tr><td>Chỉ tiêu</td><td>M8 số</td><td>31/12/2018</td></tr>\
<tr><td>A. TÀI SẢN NGẮN HẠN</td><td>100</td><td>20.559.756.794.837</td></tr>\
<tr><td>B. TÀI SẢN DÀI HẠN</td><td>200</td><td>18.673.827.995.634</td></tr>\
<tr><td>C. KHOẢN MỤC BẰNG KHÔNG</td><td>300</td><td>0</td></tr></table>
"""


@pytest.fixture
def built(tmp_path: Path) -> tuple[sqlite3.Connection, object]:
    """Trả CẢ hai: connection và `BuildReport`.

    Không gắn report vào chính connection — `sqlite3.Connection` không nhận
    thuộc tính tuỳ ý, và đó đúng là lỗi đã vấp một lần ở fixture khác.
    """
    root = tmp_path / "corpus" / "ABC_2018"
    root.mkdir(parents=True)
    (root / "rep.txt").write_text(_DOC, encoding="utf-8")
    lines = _DOC.split("\n")

    bronze = connect(tmp_path / "bronze.sqlite", BRONZE_DDL, fresh=True)
    bronze.execute(
        "INSERT INTO documents (document_uid, literal_file_stem, directory_doc_id,"
        " ticker_path, year_path, basis_path, rel_path, n_bytes, n_lines,"
        " n_pages, n_tables, sha256, corpus_id, scan_status, discovery_status)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("D1", "rep", "ABC_2018", "ABC", 2018, "consolidated",
         "ABC_2018/rep.txt", len(_DOC), len(lines), 1, 1, "x", "c", "ok", "ok"))
    for ordinal, (i, line) in enumerate(
            ((i, l) for i, l in enumerate(lines, 1) if l.startswith("<table")), 1):
        bronze.execute(
            "INSERT INTO tables VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"T{ordinal}", "D1", i, i, i - 1, ordinal, ordinal, 1, 0, 0, line,
             hashlib.sha256(line.encode()).hexdigest(), "ok"))
    bronze.commit()

    conn = connect(tmp_path / "silver.sqlite", SILVER_DDL, fresh=True)
    rep = build_silver_tables(bronze, conn, tmp_path / "corpus")
    return conn, rep


@pytest.fixture
def silver(built) -> sqlite3.Connection:
    return built[0]


def _ocr_col_is_value(silver) -> bool:
    role = silver.execute(
        "SELECT column_role FROM columns WHERE header_path_text LIKE '%M8%'"
    ).fetchone()
    return bool(role) and role[0] == "value"


def test_ocr_metric_code_column_reaches_tiny_money(silver):
    """Tiền đề của test dưới: cột hỏng OCR PHẢI lọt qua bộ lọc vai trò cột.

    Nếu một ngày `structure.py` nhận ra `M8 số`, test này đỏ trước — và đó là
    tín hiệu đúng: khi ấy ca này thuộc `non_value_column`, không còn thuộc
    `tiny_money`, nên các assert phía dưới phải được viết lại chứ không phải
    được nới.
    """
    assert _ocr_col_is_value(silver), (
        "cột `M8 số` không còn là cột `value` — đường đi của test đã đổi")


def test_false_values_leave_observations(silver):
    """`100` và `200` là mã Thông tư 200, không được tồn tại như số liệu."""
    left = silver.execute(
        "SELECT value_source FROM observations"
        " WHERE value_source IN ('100','200')").fetchall()
    assert left == [], f"mã số vẫn nằm trong observations: {left}"


def test_false_values_land_in_dropped_cells_with_reason(silver):
    """Ra khỏi fact nhưng KHÔNG ra khỏi kiểm toán — DI-02."""
    rows = silver.execute(
        "SELECT reason, detail, text_clean FROM dropped_cells"
        " WHERE reason LIKE 'tiny_money_%' ORDER BY text_clean").fetchall()
    assert [r[2] for r in rows] == ["100", "200", "300"]
    for reason, detail, _ in rows:
        assert reason == "tiny_money_metric_code_false_value"
        assert detail and "M8" in detail          # lý do phải trỏ về BẰNG CHỨNG


def test_zero_is_not_tiny_money(silver):
    """`0` là số liệu hợp lệ. Gộp nó vào tiny money là xoá dữ liệu thật."""
    row = silver.execute(
        "SELECT quality_flags_json FROM observations WHERE value_source='0'"
    ).fetchone()
    assert row is not None, "observation cho giá trị 0 đã bị mất"
    assert "tiny_money" not in row[0]


def test_real_money_untouched(silver):
    """Số tiền thật không được đụng vào — đây là kiểm soát âm."""
    n = silver.execute(
        "SELECT COUNT(*) FROM observations"
        " WHERE value_source='20.559.756.794.837'").fetchone()[0]
    assert n == 1


def test_report_counts_are_consistent(built):
    rep = built[1]
    assert rep.n_tiny_money_flagged == sum(rep.by_tiny_money_class.values())
    assert rep.n_tiny_money_dropped == sum(
        v for k, v in rep.by_tiny_money_class.items() if k in FALSE_VALUE_CLASSES)
    # Ba mã số được đếm; ô `0` ở cột giá trị thì KHÔNG — nếu nó lọt vào,
    # con số này thành 4 và test đỏ.
    assert rep.n_tiny_money_flagged == 3
    assert rep.n_observations == 3          # ba ô giá trị thật, kể cả `0`


def test_no_loss_invariant_holds(silver):
    """Bất biến không-mất-mát vẫn đúng sau khi thêm một đường loại ô mới."""
    assert integrity_check(silver) == []


def test_unresolved_flag_is_declared_in_policy():
    """Cờ mà builder phát ra phải là cờ mà chính sách readiness thực sự chặn.

    Hai tệp này ở hai nơi khác nhau và không có gì buộc chúng khớp — đúng kiểu
    lệch đã xảy ra khi đổi tên `unit_assumed`.
    """
    import yaml
    pol = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "configs"
         / "readiness_policy_v1.yaml").read_text(encoding="utf-8"))
    flags = {f["flag"] for f in pol["execution_ready"]["blocking_flags"]}
    assert "tiny_money_unresolved" in flags


def test_drop_reasons_have_verdicts():
    """Mọi lý do `tiny_money_*` phải có phán xét trong `KNOWN_ISSUES`.

    Thiếu một entry thì bảng trong tài liệu phát hành in `⬜ chưa đánh giá` —
    đúng lỗi đã xảy ra với `non_value_column`, bucket lớn nhất (73%).
    """
    from data_pipeline.release_docs import _DROP_VERDICT
    from data_pipeline.tiny_money import FALSE_VALUE_CLASSES as F
    for cls in F:
        assert f"tiny_money_{cls}" in _DROP_VERDICT, cls


def test_build_id_reacts_to_tiny_money_version():
    """Đổi luật phân loại phải đổi `build_id` — nếu không, ID nói dối."""
    from data_pipeline.storage import make_build_id
    from data_pipeline.tiny_money import TINY_MONEY_VERSION
    counts = {"tables": 1, "observations": 2, "source_cells": 3, "dropped_cells": 4}
    base = {"semantic": "1.3", "tiny_money": TINY_MONEY_VERSION}
    a, _ = make_build_id(counts, base)
    b, _ = make_build_id(counts, {**base, "tiny_money": "9.9"})
    assert a != b


def test_dropped_cells_json_roundtrip(silver):
    """`detail` phải là chuỗi đọc được, không phải repr của object."""
    for (detail,) in silver.execute(
            "SELECT detail FROM dropped_cells WHERE reason LIKE 'tiny_money_%'"):
        assert isinstance(detail, str) and not detail.startswith("<")
        json.dumps(detail)          # phải serialize được cho registry RC-18


def test_out_rows_that_su_sinh_CSV():
    """P1-03 · khối xuất row-level từng là MÃ CHẾT vì hàm `return` trước nó.
    Unit test cũ không bắt được — chỉ chạy thật mới lộ."""
    from pathlib import Path as _P
    root = _P(__file__).resolve().parents[1]
    src = (root / "tools" / "reconcile_tiny_money.py").read_text(encoding="utf-8")
    i_ret = src.index('"reconcile_version": RECONCILE_VERSION,')
    assert "rep = {" in src[i_ret - 80:i_ret], (
        "dict kết quả phải gán vào `rep`, không được `return` ngay — nếu không "
        "khối xuất row-level là mã chết")
    assert 'rep["row_level_output"]' in src
    assert "return rep" in src
