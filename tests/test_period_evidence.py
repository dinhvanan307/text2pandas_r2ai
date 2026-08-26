"""Khoá hành vi rơi bậc bằng chứng của kỳ báo cáo (FEATURE_SPEC §4.1).

Test này tồn tại vì hai lỗi đã thực sự xảy ra trên corpus thật:

1. Bảng thuyết minh dùng cột cho CHIỀU (`Nguyên giá`, `Hao mòn luỹ kế`) không
   giải được kỳ, kéo độ phủ xuống 59,24% và làm G4 FAIL.
2. `publish` vẫn chạy dù G4 FAIL — build a94013318c97ad30 được phát hành với
   cổng chưa đạt.

Cả hai đều là lỗi ngữ nghĩa im lặng: dữ liệu trông đúng, chỉ sai kỳ. Không có
test thì lần regression sau chỉ lộ ra qua điểm tụt trên leaderboard.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.models import EvidenceSource, PeriodRole, PeriodType
from text2pandas.pipelines.a6.observation_builder import build_silver_tables
from text2pandas.pipelines.a6.period_resolver import resolve_period, resolve_table_period
from text2pandas.pipelines.a6.quality import run_quality
from text2pandas.pipelines.a6.storage import BRONZE_DDL, SILVER_DDL, connect, integrity_check

# ─────────────────────── giải kỳ cấp bảng ───────────────────────


@pytest.mark.parametrize(
    "context, doc_year, period_end, rule",
    [
        ("Tăng giảm tài sản cố định hữu hình tại ngày 31 tháng 12 năm 2018",
         2018, "2018-12-31", "PT-CONTEXT-DMY-WORDS"),
        ("Thuyết minh cho năm tài chính kết thúc ngày 31/12/2020",
         2020, "2020-12-31", "PT-CONTEXT-DMY"),
        # 01/01 giữ nguyên ngữ nghĩa kế toán như P-OPENING-0101.
        ("Số dư tại ngày 01 tháng 01 năm 2019", 2019, "2018-12-31",
         "PT-CONTEXT-DMY-WORDS"),
        ("BÁO CÁO TÀI CHÍNH NĂM 2017", 2017, "2017-12-31", "PT-CONTEXT-YEAR"),
        # Số hiệu thông tư KHÔNG được nhầm thành kỳ.
        ("Ban hành theo Thông tư 200/2014/TT-BTC", 2019, None, "PT-UNRESOLVED"),
        ("", 2019, None, "PT-NO-CONTEXT"),
    ],
)
def test_table_period(context, doc_year, period_end, rule):
    res = resolve_table_period(context, doc_year)
    assert res.period_end == period_end
    assert res.rule == rule
    if period_end:
        assert res.source is EvidenceSource.TABLE_CONTEXT


def test_table_period_duration_has_start():
    res = resolve_table_period(
        "Chi phí bán hàng cho năm tài chính kết thúc ngày 31/12/2020", 2020)
    assert res.period_type is PeriodType.DURATION
    assert res.period_start == "2020-01-01"


def test_table_period_opening_role():
    res = resolve_table_period("Số dư tại ngày 01/01/2019", 2019)
    assert res.period_role is PeriodRole.OPENING
    assert res.period_end == "2018-12-31"


def test_column_resolution_unchanged():
    """Bậc `column` không được đổi hành vi khi thêm bậc `table`."""
    assert resolve_period("31/12/2018", 2018).period_end == "2018-12-31"
    assert resolve_period("01/01/2018", 2018).period_end == "2017-12-31"
    assert resolve_period("Quý 4/2023", 2023).period_end == "2023-12-31"
    assert resolve_period("Nguyên giá", 2018).period_end is None


# ─────────────────── tích hợp: rơi bậc trong build ───────────────────

_DOC = """===== PAGE 1 =====
CÔNG TY CỔ PHẦN MẪU
Đơn vị tính: VND

BẢNG CÂN ĐỐI KẾ TOÁN
<table><tr><td>Chỉ tiêu</td><td>Mã số</td><td>31/12/2018</td><td>01/01/2018</td></tr>\
<tr><td>A. TÀI SẢN NGẮN HẠN</td><td>100</td><td>20.559.756.794.837</td>\
<td>18.673.827.995.634</td></tr></table>

10. TÀI SẢN CỐ ĐỊNH HỮU HÌNH
Tăng giảm tài sản cố định hữu hình tại ngày 31 tháng 12 năm 2018
<table><tr><td>Khoản mục</td><td>Nguyên giá</td><td>Hao mòn luỹ kế</td></tr>\
<tr><td>Nhà cửa, vật kiến trúc</td><td>5.123.456.789</td><td>1.234.567.890</td></tr></table>
"""


@pytest.fixture
def silver(tmp_path: Path) -> sqlite3.Connection:
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
         "ABC_2018/rep.txt", len(_DOC), len(lines), 1, 2, "x", "c", "ok", "ok"))
    for ordinal, (i, line) in enumerate(
            ((i, l) for i, l in enumerate(lines, 1) if l.startswith("<table")), 1):
        bronze.execute(
            "INSERT INTO tables VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"T{ordinal}", "D1", i, i, i - 1, ordinal, ordinal, 1, 0, 0, line,
             hashlib.sha256(line.encode()).hexdigest(), "ok"))
    bronze.commit()

    conn = connect(tmp_path / "silver.sqlite", SILVER_DDL, fresh=True)
    build_silver_tables(bronze, conn, tmp_path / "corpus")
    return conn


def _cols(conn, table_uid):
    return conn.execute(
        "SELECT header_path_text, period_end, period_source, flags_json"
        " FROM columns WHERE table_uid=? AND column_role='value'"
        " ORDER BY grid_col_idx", (table_uid,)).fetchall()


def test_explicit_columns_keep_own_period(silver):
    """Bảng cân đối: mỗi cột giữ kỳ RIÊNG, không bị kỳ cấp bảng ghi đè."""
    got = _cols(silver, "T1")
    assert [(h, p, s) for h, p, s, _ in got] == [
        ("31/12/2018", "2018-12-31", "column_path"),
        ("01/01/2018", "2017-12-31", "column_path"),
    ]


def test_dimension_columns_inherit_table_period(silver):
    """Cột CHIỀU nhận kỳ cấp bảng và phải mang cờ ghi rõ đó là suy diễn."""
    got = _cols(silver, "T2")
    assert len(got) == 2
    for header, period_end, source, flags in got:
        assert period_end == "2018-12-31", header
        assert source == "table_context", header
        assert "period_from_table" in flags, header


def test_provenance_reaches_observations(silver):
    """Suy diễn phải theo xuống tận observation — nếu không thì mất dấu vết."""
    rows = silver.execute(
        "SELECT period_source, quality_flags_json FROM observations"
        " WHERE table_uid='T2'").fetchall()
    assert rows
    assert all(src == "table_context" and "period_from_table" in flags
               for src, flags in rows)


def test_no_observation_lost_integrity(silver):
    assert integrity_check(silver) == []


def test_quality_reports_two_period_measures(silver):
    names = [c["name"] for c in run_quality(silver)["gates"]["G4 Semantics"]]
    assert any("TƯỜNG MINH" in n for n in names)
    assert any("suy diễn" in n for n in names)


def test_quality_blocks_explicit_column_unit_scale_mismatch(silver):
    """Không để retrieval nhận một observation sai 10^3/10^6/10^9 lần."""
    silver.execute(
        "UPDATE observations SET col_path_text=?, scale_exponent=0,"
        " quality_flags_json='[]' WHERE observation_uid="
        " (SELECT observation_uid FROM observations LIMIT 1)",
        ("31/12/2024Triệu VNDPhải thu",),
    )
    report = run_quality(silver)

    assert report["by_rule"]["Q-OBS-EXPLICIT-UNIT-SCALE-MISMATCH"] == 1
    check = next(c for c in report["gates"]["G4 Semantics"]
                 if "observation mang bậc khác" in c["name"])
    assert check["pass"] is False and check["value"] == 1


def test_quality_allows_traced_implausible_scale_rejection(silver):
    """Reconciliation được phép bác lời khai, nhưng bắt buộc để lại reason."""
    silver.execute(
        "UPDATE observations SET col_path_text=?, scale_exponent=0,"
        " quality_flags_json='[\"scale_rejected_implausible\"]'"
        " WHERE observation_uid=(SELECT observation_uid FROM observations LIMIT 1)",
        ("31/12/2024Triệu VNDPhải thu",),
    )
    report = run_quality(silver)

    assert report["by_rule"].get("Q-OBS-EXPLICIT-UNIT-SCALE-MISMATCH", 0) == 0


# ──────────── lỗi đo được từ diagnose_silver.py trên build 4941cb2a ────────────

from text2pandas.pipelines.a6.models import ColumnRole  # noqa: E402
from text2pandas.pipelines.a6.structure import (  # noqa: E402
    _classify_column,
    _global_header_segments,
)

_NUM = ["1.000", "2.000", "3.000"]
_TXT = ["Alpha", "Beta", "Gamma"]


@pytest.mark.parametrize("header, period_end", [
    # OCR nối đơn vị vào năm — `\b` không có ranh giới giữa `1` và `V`.
    ("2021VND", "2021-12-31"),
    ("2019VND", "2019-12-31"),
    ("31/12/2018VND", "2018-12-31"),
    ("Tổng cộng VND", None),
])
def test_year_glued_to_unit(header, period_end):
    assert resolve_period(header, 2021).period_end == period_end


@pytest.mark.parametrize("header", [
    "Trong năm", "Tăng trong năm", "Giảm trong năm",
    "Số phải nộp trong năm", "Biến động trong năm", "Trong năm › Tăng",
])
def test_duration_columns_get_full_year(header):
    res = resolve_period(header, 2020)
    assert (res.period_start, res.period_end) == ("2020-01-01", "2020-12-31")
    assert res.period_type is PeriodType.DURATION
    assert res.rule == "P-RELATIVE-DURATION"


@pytest.mark.parametrize("header", [
    "Năm phát sinh",            # CHIỀU: lỗ phát sinh năm nào, không phải kỳ của giá trị
    "Có thể chuyển lỗ đến năm",
    "Nguyên giá",
])
def test_duration_rule_does_not_overreach(header):
    assert resolve_period(header, 2020).period_end is None


def test_global_header_does_not_poison_roles():
    """Tiêu đề `colspan` toàn bảng chứa 'Thuyết minh' từng giết cả bảng."""
    paths = [["BẢN THUYẾT MINH BÁO CÁO TÀI CHÍNH", h]
             for h in ("Bên liên quan", "Mối quan hệ", "Số cuối năm", "Số đầu năm")]
    seg = frozenset(_global_header_segments(paths))
    roles = [_classify_column(i, p, _TXT if i < 2 else _NUM, seg)
             for i, p in enumerate(paths)]
    assert ColumnRole.NOTE_REFERENCE not in roles
    assert roles[2] is ColumnRole.VALUE and roles[3] is ColumnRole.VALUE


def test_real_note_column_still_detected():
    paths = [["Chỉ tiêu"], ["Thuyết minh"], ["31/12/2018"]]
    seg = frozenset(_global_header_segments(paths))
    roles = [_classify_column(i, p, _TXT if i == 0 else _NUM, seg)
             for i, p in enumerate(paths)]
    assert roles[1] is ColumnRole.NOTE_REFERENCE


def test_partial_span_header_is_not_global():
    """`Số cuối năm` phủ 2/5 cột là nhãn THẬT — không được loại."""
    paths = [["Chỉ tiêu"],
             ["Số cuối năm", "Giá gốc"], ["Số cuối năm", "Dự phòng"],
             ["Số đầu năm", "Giá gốc"], ["Số đầu năm", "Dự phòng"]]
    assert _global_header_segments(paths) == set()


@pytest.mark.parametrize("header, role", [
    ("STT", ColumnRole.ORDINAL),
    ("TT", ColumnRole.ORDINAL),
    ("Số TT", ColumnRole.ORDINAL),
    ("Mã số", ColumnRole.METRIC_CODE),
    ("31/12/2018", ColumnRole.VALUE),
])
def test_ordinal_column_not_a_value(header, role):
    assert _classify_column(1, [header], _NUM) is role


# ───── hai con số dính liền — 3.633 ô vượt 10^16 VND trên build 4941cb2a ─────

from text2pandas.pipelines.a6.models import ParseStatus, ValueKind  # noqa: E402
from text2pandas.pipelines.a6.number_parser import SepConvention, parse_number  # noqa: E402

_DOT, _COMMA = SepConvention.DOT, SepConvention.COMMA


@pytest.mark.parametrize("raw, conv, rule", [
    # ACV 2020: 97.158.150.939 và 396.219.749.004 dính liền → 9,7×10^22 VND.
    ("97.158.150.939396.219.749.004", _DOT, "N-MALFORMED-GROUPS"),
    ("10.384.277.519.096418.310.786", _DOT, "N-MALFORMED-GROUPS"),
    ("1,234,5678,901", _COMMA, "N-MALFORMED-GROUPS"),
    # Cùng lỗi nhưng còn dấu cách giữa hai số.
    ("97.158.150.939 396.219.749.004", _DOT, "N-MULTI-NUMBER"),
])
def test_glued_numbers_are_ambiguous_not_giant(raw, conv, rule):
    """DI-07: không đoán. Thà mất một ô còn hơn tạo ra 9,7×10^22 VND."""
    res = parse_number(raw, conv, ValueKind.MONEY)
    assert res.value_decimal is None
    assert res.status is ParseStatus.AMBIGUOUS
    assert res.parse_rule == rule


@pytest.mark.parametrize("raw, conv, want", [
    ("1.234.567", _DOT, "1234567"),
    ("20.559.756.794.837", _DOT, "20559756794837"),
    ("1,234,567", _COMMA, "1234567"),
    ("1.234.567,89", _DOT, "1234567.89"),
    ("1,234,567.89", _COMMA, "1234567.89"),
    ("1 234 567", _DOT, "1234567"),      # quy ước phân cách bằng dấu cách
    ("(1.234.567)", _DOT, "-1234567"),
    ("1.216", _DOT, "1216"),
    ("12,5", _DOT, "12.5"),
])
def test_valid_numbers_untouched(raw, conv, want):
    """Cổng chặt không được làm hỏng số hợp lệ — đây là nửa còn lại của bài toán."""
    assert str(parse_number(raw, conv, ValueKind.MONEY).value_decimal) == want


def test_reference_column_demoted_by_digit_length():
    """Cột `Thuyết minh` không nhãn: 4,5,6,7 giữa các cột tiền 13 chữ số."""
    from text2pandas.pipelines.a6.html_parser import parse_table
    from text2pandas.pipelines.a6.structure import interpret_structure
    html = ("<table><tr><td>Chỉ tiêu</td><td>Mã số</td><td></td>"
            "<td>31/12/2018</td><td>01/01/2018</td></tr>"
            "<tr><td>Tiền</td><td>110</td><td>4</td>"
            "<td>1.363.588.545.921</td><td>952.854.945.921</td></tr>"
            "<tr><td>Đầu tư</td><td>120</td><td>5</td>"
            "<td>1.500.000.000</td><td>410.713.600.000</td></tr>"
            "<tr><td>Phải thu</td><td>130</td><td>6</td>"
            "<td>1.264.199.536.491</td><td>472.098.151.669</td></tr>"
            "<tr><td>Hàng tồn</td><td>140</td><td>7</td>"
            "<td>472.098.151.669</td><td>38.745.566.482</td></tr></table>")
    st = interpret_structure(parse_table("T", html, 120_000),
                             "BẢNG CÂN ĐỐI KẾ TOÁN", "§")
    roles = [c.column_role for c in st.columns]
    assert roles[2] is ColumnRole.NOTE_REFERENCE
    assert roles[3] is ColumnRole.VALUE and roles[4] is ColumnRole.VALUE


def test_small_number_table_not_demoted():
    """Bảng đếm nhân sự toàn số nhỏ KHÔNG được coi là cột tham chiếu."""
    from text2pandas.pipelines.a6.html_parser import parse_table
    from text2pandas.pipelines.a6.structure import interpret_structure
    html = ("<table><tr><td>Bộ phận</td><td>2018</td><td>2017</td></tr>"
            "<tr><td>Quản lý</td><td>12</td><td>10</td></tr>"
            "<tr><td>Sản xuất</td><td>85</td><td>80</td></tr>"
            "<tr><td>Bán hàng</td><td>30</td><td>28</td></tr></table>")
    st = interpret_structure(parse_table("T", html, 120_000),
                             "Số lượng nhân viên", "§")
    assert ColumnRole.NOTE_REFERENCE not in [c.column_role for c in st.columns]


@pytest.mark.parametrize("raw, ok", [
    # Hai số dính qua ĐÚNG một dấu phân cách — hình dạng hợp lệ, chỉ độ lớn tố cáo.
    ("97.158.150.939.396.219.749.004", False),
    ("1.234.567.890.123.456.789.012", False),
    # Trần 10^16 để dư 5 lần so với tổng tài sản lớn nhất corpus (~2×10^15).
    ("2.000.000.000.000.000", True),
    ("20.559.756.794.837", True),
])
def test_money_magnitude_ceiling(raw, ok):
    res = parse_number(raw, _DOT, ValueKind.MONEY)
    assert (res.value_decimal is not None) is ok, res.parse_rule
    if not ok:
        assert res.parse_rule == "N-IMPLAUSIBLE-MAGNITUDE"


def test_ceiling_does_not_apply_to_share_count():
    """Trần chỉ áp cho TIỀN. Số cổ phiếu, số lượng có thang khác."""
    res = parse_number("97.158.150.939.396.219.749.004", _DOT, ValueKind.SHARE_COUNT)
    assert res.value_decimal is not None


# ── `CÔNG TY CỔ PHẦN` trong tên pháp nhân KHÔNG phải lời khai đơn vị ──

from text2pandas.pipelines.a6.unit_resolver import resolve_unit  # noqa: E402


@pytest.mark.parametrize("context, scale", [
    ("CÔNG TY CỔ PHẦN SỮA VIỆT NAM Đơn vị tính: VND", 0),
    ("CÔNG TY CP TASCO Đơn vị tính: triệu đồng", 6),
    ("CTCP FPT Đơn vị tính: VND", 0),
    ("Đơn vị tính: nghìn đồng", 3),
])
def test_legal_form_does_not_steal_money_scale(context, scale):
    """Tên pháp nhân lặp ở đầu mỗi trang, tức nằm trong ngữ cảnh của hầu hết bảng.

    Khớp `cổ phần` ở đó làm đơn vị thành SHARES và **xoá mất bậc 10 của tiền** —
    giá trị khai "triệu đồng" bị đọc như đồng, sai 10^6, không cổng nào bắt được.
    """
    res = resolve_unit("", "31/12/2018", "", "", context)
    assert res.unit_kind.value == "money", res.unit_kind
    assert res.scale_exponent == scale


def test_real_share_column_still_detected():
    """Nửa còn lại: cột thật về cổ phiếu vẫn phải ra SHARES."""
    res = resolve_unit("", "Số lượng cổ phiếu", "", "", "CÔNG TY CỔ PHẦN X")
    assert res.unit_kind.value == "shares"


# ── 95% ô tiền mất bậc đơn vị: loại đơn vị bị suy từ VĂN XUÔI ──
#
# Đo trên build 832abca1a2111ba2, trong 2.406.208 ô có value_kind='money':
#   days 1.251.583 (52,0%) · shares 659.904 (27,4%) · percent 277.041 (11,5%)
#   rate 83.172 (3,5%)     · money chỉ 120.306 (5,0%)
# Loại phi tiền tệ thoát sớm không mang scale_exponent → giá trị khai
# "triệu đồng" bị đọc như đồng, sai 10^6, và cổng cũ vẫn báo 97,88%.

_REAL_CTX = ("CÔNG TY CỔ PHẦN SỮA VIỆT NAM  BẢN THUYẾT MINH BÁO CÁO TÀI CHÍNH "
             "HỢP NHẤT  Cho năm tài chính kết thúc ngày 31 tháng 12 năm 2018  "
             "Đơn vị tính: VND")


@pytest.mark.parametrize("context, scale", [
    (_REAL_CTX, 0),
    (_REAL_CTX.replace("Đơn vị tính: VND", "Đơn vị tính: triệu đồng"), 6),
    (_REAL_CTX.replace("Đơn vị tính: VND", "Đơn vị tính: nghìn đồng"), 3),
])
def test_prose_context_never_sets_unit_kind(context, scale):
    """Văn xuôi có 'ngày', 'cổ phần' — nhưng đó không phải lời khai đơn vị."""
    res = resolve_unit("", "31/12/2018", "", "", context)
    assert res.unit_kind.value == "money", res.unit_kind
    assert res.scale_exponent == scale
    # `Đơn vị tính: VND` khai bậc 10^0 TƯỜNG MINH, không phải thiếu bằng chứng.
    assert res.scale_source.value not in ("assumed", "none")


@pytest.mark.parametrize("header, kind", [
    ("Tỷ lệ (%)", "percent"),
    ("Số lượng cổ phiếu", "shares"),
    ("Số ngày", "days"),
    ("Lãi suất", "rate"),
    ("31/12/2018", "money"),
])
def test_label_layers_still_set_unit_kind(header, kind):
    """Nửa còn lại: nhãn cột là nơi HỢP LỆ để khai loại đơn vị."""
    assert resolve_unit("", header, "", "", _REAL_CTX).unit_kind.value == kind


# ══════ Lỗi do SILVER_RELEASE_AUDIT.md phát hiện trên build d576dd73 ══════

@pytest.mark.parametrize("context, scale", [
    # P0-01. Nguyên nhân thật: `tỷ\b` khớp "tỷ lệ" / "tỷ giá" / "tỷ suất" —
    # ba cụm có mặt ở gần như mọi báo cáo. Bảng ghi rõ `Đơn vị: VND` vẫn nhận
    # scale 9, và 1.135.279.409.795 VND thành 1,14×10^21.
    ("CÔNG TY CỔ PHẦN AAA  Đơn vị: VND  Tỷ lệ sở hữu 51%  tỷ giá 23.000", 0),
    ("Đơn vị: VND  tỷ suất lợi nhuận trên vốn", 0),
    ("Đơn vị tính: triệu đồng", 6),
    ("Đơn vị tính: triệu", 6),          # trong cụm khai báo, từ trần vẫn hợp lệ
    ("Đơn vị tính: tỷ đồng", 9),
    ("Đơn vị tính: nghìn tỷ đồng", 12),
])
def test_scale_word_must_attach_to_currency(context, scale):
    res = resolve_unit("", "31/12/2015", "", "", context)
    assert res.unit_kind.value == "money", res.unit_kind
    assert res.scale_exponent == scale, res.scale_source


@pytest.mark.parametrize("header, period_end", [
    # P1-01. Bản đầu ghép chuỗi thẳng nên sinh 2014-00-28, 2016-58-28,
    # 2025-31-12 — 818 observation mang ngày không tồn tại.
    ("12/31/2025", "2025-12-31"),          # MM/DD/YYYY, phân biệt được vì 31 > 12
    ("31/12/2018", "2018-12-31"),          # DD/MM/YYYY, mặc định
    ("31/02/2018", None),                  # 31 tháng 2 không tồn tại
    ("Quyết định 15/2006/QĐ-BTC", None),
    ("Thông tư 200/2014/TT-BTC", None),
    ("hợp đồng 58/2016", None),
])
def test_period_never_emits_invalid_calendar_date(header, period_end):
    import datetime
    res = resolve_period(header, 2018)
    assert res.period_end == period_end, res.rule
    for field in (res.period_end, res.period_start, res.as_of_date):
        if field:
            datetime.date.fromisoformat(field)      # ném nếu không phải ngày thật


def test_inferred_money_is_not_assumed():
    """`Đơn vị tính: VND` là BẰNG CHỨNG, không phải mặc định.

    Suy `unit_kind = money` từ tiền tệ đã tìm được là suy diễn có căn cứ. Gọi
    nó `assumed` làm cờ bùng từ 59.331 lên 2.267.258 ô (88%), và vì `confidence`
    dùng cờ đó để hạ xuống `low`, cả cột `confidence` mất khả năng phân biệt.
    """
    res = resolve_unit("", "31/12/2018", "", "", "Đơn vị tính: VND")
    assert res.unit_kind.value == "money"
    assert res.scale_exponent == 0
    assert res.assumed is False
    assert "unit_assumed" not in res.flags


def test_no_evidence_at_all_stays_unknown():
    """Nửa còn lại: không bằng chứng nào thì KHÔNG được tự nhận là tiền."""
    res = resolve_unit("", "c3", "", "", "Bảng phụ lục")
    assert res.unit_kind.value == "unknown"
    assert res.scale_exponent is None


@pytest.mark.parametrize("context, period_end, rule", [
    ("tại ngày 31 tháng 02 năm 2018", None, "PT-INVALID-DATE"),
    ("theo Thông tư 200/2014/TT-BTC", None, "PT-UNRESOLVED"),
    ("tại ngày 31 tháng 12 năm 2018", "2018-12-31", "PT-CONTEXT-DMY-WORDS"),
])
def test_table_period_validates_calendar_too(context, period_end, rule):
    """Bậc `table` cũng phải validate lịch — sửa bậc `column` thôi thì vẫn rò."""
    res = resolve_table_period(context, 2018)
    assert (res.period_end, res.rule) == (period_end, rule)


@pytest.mark.parametrize("context, scale", [
    # Thuyết minh vay mô tả hợp đồng bằng câu văn. `500 tỷ đồng` ở đó là HẠN
    # MỨC HỢP ĐỒNG, không phải đơn vị của bảng. Đo được 71.809 ô nhận scale
    # 10^6/10^9 từ ngữ cảnh trong khi chữ số thô đã 11–15 chữ số — giá trị vốn
    # là VND đầy đủ, nhân thêm cho ra 1,7×10^20 VND.
    ("(vi) Vay ngắn hạn theo hợp đồng hạn mức 500 tỷ đồng, lãi suất 7%/năm", 0),
    ("Trái phiếu phát hành mệnh giá 100 triệu đồng mỗi trái phiếu", 0),
    # Lời khai thật vẫn phải thắng — 9.099 khai báo nằm NGOÀI bảng.
    ("Đơn vị tính: triệu đồng", 6),
    ("Đơn vị tính: triệu đồng. Vay theo hạn mức 500 tỷ đồng", 6),
])
def test_scale_never_inferred_from_prose(context, scale):
    res = resolve_unit("", "31/12/2015", "", "", context)
    assert res.unit_kind.value == "money"
    assert res.scale_exponent == scale, res.scale_source


def test_column_label_scale_beats_prose():
    """Nhãn cột là lời khai; câu văn thì không. Nhãn phải thắng."""
    assert resolve_unit("", "Triệu VND", "", "",
                        "Vay 500 tỷ đồng").scale_exponent == 6


# ── Ngày BAN HÀNH văn bản pháp quy không phải kỳ của bảng ────────────────────
# Che số hiệu mà chừa ngày ký lại thì bậc suy diễn cấp bảng đọc trúng ngày ký:
# ngữ cảnh "…kết thúc ngày 31/12/2019 theo Thông tư 200/2014/TT-BTC ngày
# 22/12/2014" ra 2014-12-22, vì luật lấy ngày CUỐI CÙNG trong ngữ cảnh.
@pytest.mark.parametrize("context, doc_year, period_end, rule", [
    # Chỉ có trích dẫn: không kỳ nào cả, và phải nói rõ vì sao không.
    ("Ban hành theo Thông tư số 200/2014/TT-BTC ngày 22 tháng 12 năm 2014 "
     "của Bộ Tài chính", 2019, None, "PT-UNRESOLVED"),
    ("Theo Thông tư 200/2014/TT-BTC ngày 22/12/2014 của Bộ Tài chính",
     2019, None, "PT-UNRESOLVED"),
    ("Quyết định số 15/2006/QĐ-BTC ngày 20/03/2006", 2019, None,
     "PT-UNRESOLVED"),
    # Có CẢ ngày chốt thật LẪN trích dẫn: ngày chốt phải thắng, dù đứng TRƯỚC.
    ("Thuyết minh cho năm tài chính kết thúc ngày 31/12/2019 theo Thông tư "
     "200/2014/TT-BTC ngày 22/12/2014", 2019, "2019-12-31", "PT-CONTEXT-DMY"),
    ("Tăng giảm tại ngày 31 tháng 12 năm 2018 lập theo Thông tư "
     "200/2014/TT-BTC", 2018, "2018-12-31", "PT-CONTEXT-DMY-WORDS"),
])
def test_table_period_ignores_issuance_date(context, doc_year, period_end, rule):
    res = resolve_table_period(context, doc_year)
    assert (res.period_end, res.rule) == (period_end, rule)


@pytest.mark.parametrize("context, doc_year, period_end, rule", [
    # Ngày lịch hợp lệ nhưng cách năm tài liệu quá xa — không phải kỳ của bảng.
    ("Bảng so sánh tại ngày 31/12/2010", 2019, None, "PT-YEAR-OUT-OF-WINDOW"),
    # Trong cửa sổ: năm tài liệu, năm liền trước, và hai năm trước đều nhận.
    ("Số dư tại ngày 31/12/2019", 2019, "2019-12-31", "PT-CONTEXT-DMY"),
    ("Số dư tại ngày 31/12/2018", 2019, "2018-12-31", "PT-CONTEXT-DMY"),
    ("Số dư tại ngày 31/12/2017", 2019, "2017-12-31", "PT-CONTEXT-DMY"),
    # Không biết năm tài liệu thì không có cửa sổ để áp — không được chặn bừa.
    ("Số dư tại ngày 31/12/2010", None, "2010-12-31", "PT-CONTEXT-DMY"),
])
def test_table_period_year_window(context, doc_year, period_end, rule):
    res = resolve_table_period(context, doc_year)
    assert (res.period_end, res.rule) == (period_end, rule)


def test_year_window_applies_to_table_tier_only():
    """Nhãn cột là bằng chứng MẠNH — bảng tổng hợp 5 năm phải giữ được cột 2015.

    Áp cửa sổ năm cho cả hai bậc là sửa quá tay: nó sẽ xoá kỳ của những cột
    ĐỌC ĐƯỢC chỉ vì chúng xa năm thư mục.
    """
    assert resolve_period("31/12/2015", 2019).period_end == "2015-12-31"
    assert resolve_table_period("tại ngày 31/12/2015", 2019).period_end is None


# ── Bậc đơn vị là LỜI KHAI; chữ số in trong ô là BẰNG CHỨNG ──────────────────
from decimal import Decimal                                    # noqa: E402
from text2pandas.pipelines.a6.models import EvidenceSource as _E          # noqa: E402
from text2pandas.pipelines.a6.unit_resolver import reconcile_scale        # noqa: E402


@pytest.mark.parametrize("value, scale, src, expect", [
    # 14 chữ số thô đã là VND đầy đủ; ×10^9 ra 6,9×10^22 — bất khả.
    (Decimal("69361062377286"), 9, _E.SECTION_CONTEXT, (0, _E.NONE, True)),
    (Decimal("5341160000000"), 6, _E.SECTION_CONTEXT, (0, _E.NONE, True)),
    # Bảng lập bằng triệu in 7 chữ số -> 5,3×10^12. Hợp lệ, luật KHÔNG kích hoạt.
    (Decimal("5341160"), 6, _E.TABLE_CONTEXT, (6, _E.TABLE_CONTEXT, False)),
    (Decimal("1234"), 9, _E.COLUMN_PATH, (9, _E.COLUMN_PATH, False)),
    # Ngay tại ngưỡng: 9.999.999 × 10^9 = 10^16 -> vẫn nhận.
    (Decimal("9999999"), 9, _E.COLUMN_PATH, (9, _E.COLUMN_PATH, False)),
    (Decimal("10000001"), 9, _E.COLUMN_PATH, (0, _E.NONE, True)),
    # Bậc 0 không có gì để bác.
    (Decimal("69361062377286"), 0, _E.CELL, (0, _E.CELL, False)),
])
def test_reconcile_scale(value, scale, src, expect):
    got = reconcile_scale(value, True, scale, src)
    assert (got[0], got[1], got[2] is not None) == expect


def test_reconcile_scale_leaves_parse_errors_alone():
    """Chữ số thô ĐÃ vượt trần là lỗi TÁCH SỐ. Bác bậc ở đây sẽ che mất nó."""
    got = reconcile_scale(Decimal("1e20"), True, 9, _E.CELL)
    assert got == (9, _E.CELL, None)


def test_reconcile_scale_money_only():
    """Cổ phiếu, ngày, phần trăm không chịu trần tiền tệ."""
    assert reconcile_scale(Decimal("69361062377286"), False, 9, _E.CELL)[2] is None
