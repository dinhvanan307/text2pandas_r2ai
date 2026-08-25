"""Positive AND negative tests for the unit lexicon.

Rule adopted after the 75.1% false-claim post-mortem: no detector ships
without a negative test.
"""
import pytest

from text2pandas.domain.units.lexicon import (
    MONEY, PERCENT, RATIO, COUNT, SHARES, UNKNOWN,
    parse_raw_number, scan_unit, scan_question_unit,
    storage_ratio, snap_power_of_ten,
)


# ----------------------------------------------------------- parse_raw_number
@pytest.mark.parametrize("raw,expected", [
    ("1.855.837", 1855837.0),
    ("3.045.280.003.467", 3045280003467.0),
    ("1,234,567.89", 1234567.89),
    ("1.234.567,89", 1234567.89),
    ("0", 0.0),
    ("42", 42.0),
    ("12,5", 12.5),
    ("12.5", 12.5),
    ("(1.234)", -1234.0),
    ("-1.234", -1234.0),
    ("15%", 15.0),
])
def test_parse_raw_ok(raw, expected):
    v, st = parse_raw_number(raw)
    assert st == "OK"
    assert v == pytest.approx(expected)


@pytest.mark.parametrize("raw,status", [
    (None, "EMPTY"),
    ("", "EMPTY"),
    ("   ", "EMPTY"),
    ("-", "EMPTY"),
    ("N/A", "EMPTY"),
    ("31/12/2024", "NOT_A_NUMBER"),
    ("2018VND", "NOT_A_NUMBER"),
    ("Triệu đồng", "NOT_A_NUMBER"),
])
def test_parse_raw_rejects(raw, status):
    v, st = parse_raw_number(raw)
    assert v is None and st == status


# ------------------------------------------------------------------ scan_unit
@pytest.mark.parametrize("text,dim,exp", [
    ("Năm nayTriệu đồng", MONEY, 6),
    ("Số cuối nămTriệu đồng", MONEY, 6),
    ("2018VND › LƯU CHUYỂN TIỀN", MONEY, 0),
    ("Tỷ đồng", MONEY, 9),
    ("Nghìn đồng", MONEY, 3),
    ("Nghìn tỷ", MONEY, 12),
    ("%", PERCENT, None),
    ("Tỷ lệ phần trăm", PERCENT, None),
    ("Cổ phiếu phổ thông", SHARES, None),
    ("Số lượng", COUNT, None),
    ("Hệ số", RATIO, None),
])
def test_scan_unit_positive(text, dim, exp):
    d, e, _tok = scan_unit(text)
    assert (d, e) == (dim, exp)


@pytest.mark.parametrize("text", [
    "",
    "Số cuối năm",
    "Chỉ tiêu",
    "Thuyết minh",
])
def test_scan_unit_unknown(text):
    d, e, _ = scan_unit(text)
    assert d == UNKNOWN and e is None


def test_scan_unit_money_outranks_shares():
    """A share-capital column measured in money is MONEY, not SHARES."""
    d, e, _ = scan_unit("Cổ phiếu phổ thôngtính theo mệnh giáTriệu đồng")
    assert (d, e) == (MONEY, 6)


# ------------------------------------------------- negative regressions (bugs)
def test_cong_ty_is_not_ty_dong():
    """REGRESSION: 'công ty mẹ' must not be read as 'tỷ đồng'."""
    d, e, _ = scan_question_unit("Tổng quỹ lương năm 2022 của công ty mẹ EIB là bao nhiêu triệu đồng?")
    assert (d, e) == (MONEY, 6)


def test_tmcp_is_not_co_phieu():
    """REGRESSION: 'TMCP' must not be read as 'cổ phiếu' (CP)."""
    d, e, _ = scan_question_unit(
        "Số dư phải thu của Ngân hàng TMCP Nam Á (NAB) đến ngày 31/12/2024 là bao nhiêu triệu đồng?")
    assert (d, e) == (MONEY, 6)


def test_ty_le_is_not_ty_dong():
    """REGRESSION: 'tỷ lệ' is a RATIO word, not the 10^9 money scale."""
    d, _e, _ = scan_unit("Tỷ lệ nợ xấu")
    assert d == RATIO


def test_von_dieu_le_question_is_money_million():
    d, e, _ = scan_question_unit("Vốn điều lệ của công ty mẹ EIB cuối năm 2023 là bao nhiêu triệu đồng?")
    assert (d, e) == (MONEY, 6)


@pytest.mark.parametrize("q,dim,exp", [
    ("Doanh thu thuần năm 2023 là bao nhiêu tỷ đồng?", MONEY, 9),
    ("Lợi nhuận sau thuế năm 2022 là bao nhiêu triệu đồng?", MONEY, 6),
    ("Tỷ lệ nợ xấu cuối năm 2023 là bao nhiêu %?", PERCENT, None),
    ("Số lượng cổ phiếu đang lưu hành là bao nhiêu cổ phiếu?", SHARES, None),
])
def test_scan_question_unit(q, dim, exp):
    d, e, _ = scan_question_unit(q)
    assert (d, e) == (dim, exp)


def test_question_without_unit_is_unknown():
    d, e, _ = scan_question_unit("Công ty nào có lợi nhuận cao nhất?")
    assert d == UNKNOWN and e is None


# -------------------------------------------------------------- storage scale
@pytest.mark.parametrize("value,raw,exp", [
    ("1855837", "1.855.837", 0),
    ("1855837000000", "1.855.837", 6),
    ("1855837000", "1.855.837", 3),
    ("-208253201298", "-208.253.201.298", 0),
])
def test_storage_ratio_powers(value, raw, exp):
    r, st = storage_ratio(value, raw)
    assert st == "OK"
    assert snap_power_of_ten(r) == exp


@pytest.mark.parametrize("value,raw,status", [
    ("100", "0", "ZERO_RAW"),
    ("100", "", "RAW_EMPTY"),
    ("100", "31/12/2024", "RAW_UNPARSEABLE"),
    ("abc", "1.000", "VALUE_UNPARSEABLE"),
    ("100", None, "RAW_EMPTY"),
])
def test_storage_ratio_rejects(value, raw, status):
    r, st = storage_ratio(value, raw)
    assert r is None and st == status


def test_snap_rejects_non_power_of_ten():
    assert snap_power_of_ten(3.0) is None
    assert snap_power_of_ten(0.0) is None
    assert snap_power_of_ten(None) is None
    assert snap_power_of_ten(-10.0) is None
