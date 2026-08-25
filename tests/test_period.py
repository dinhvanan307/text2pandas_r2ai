"""Period resolution tests.

REGRESSION ORIGIN: the first adapter read the year only from ``col_label``.
Most of this corpus writes periods *relatively* ("Năm nay" / "Năm trước") and
keeps the absolute year in the FILENAME, so that reader returned None for the
majority of cells and starved every multi-period operation. The failure looked
like "operands unavailable" -- a measurement artifact, not a data fact.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from text2pandas.pipelines.answering.period import (  # noqa: E402
    ABSOLUTE, CURRENT, PRIOR, UNRESOLVED, anchor_year_from_path, resolve_period,
)

F2021 = "data/a6_ABB_financial_statements_2021_separate_line316.csv"
F2018 = "data/a6_VJC_financial_statements_2018_separate_line229.csv"


@pytest.mark.parametrize("path,expected", [
    (F2021, "2021"),
    (F2018, "2018"),
    ("data/ACB_financial_statements_2023_consolidated_line2297.csv", "2023"),
    ("", None),
    ("data/no_year_here.csv", None),
])
def test_anchor_year_from_path(path, expected):
    assert anchor_year_from_path(path) == expected


def test_line_number_is_not_mistaken_for_a_year():
    """'line2015' must not be read as the year 2015."""
    assert anchor_year_from_path(
        "data/ACB_financial_statements_2025_separate_line2015.csv") == "2025"


@pytest.mark.parametrize("label,expected,kind", [
    ("2018VND › LƯU CHUYỂN TIỀN", "2018", ABSOLUTE),
    ("31.12.2023Triệu VND", "2023", ABSOLUTE),
])
def test_absolute_year_in_header_wins(label, expected, kind):
    p = resolve_period(label, F2021)
    assert (p.year, p.kind) == (expected, kind)


@pytest.mark.parametrize("label,expected", [
    ("Năm nay Triệu đồng", "2021"),
    ("Năm nayTriệu đồng", "2021"),
    ("Kỳ này", "2021"),
    ("Số cuối năm", "2021"),
    ("Cuối kỳ", "2021"),
])
def test_current_period_resolves_to_anchor(label, expected):
    p = resolve_period(label, F2021)
    assert p.year == expected and p.kind == CURRENT


@pytest.mark.parametrize("label,expected", [
    ("Năm trước Triệu đồng", "2020"),
    ("Năm trướcTriệu đồng", "2020"),
    ("Kỳ trước", "2020"),
    ("Số đầu năm", "2020"),
    ("Đầu kỳ", "2020"),
])
def test_prior_period_resolves_to_anchor_minus_one(label, expected):
    p = resolve_period(label, F2021)
    assert p.year == expected and p.kind == PRIOR


def test_relative_label_without_anchor_is_unresolved_not_guessed():
    p = resolve_period("Năm nay", "")
    assert p.year is None and p.kind == UNRESOLVED


def test_unrecognised_label_is_unresolved():
    p = resolve_period("Thuyết minh", F2021)
    assert p.year is None and p.kind == UNRESOLVED


def test_one_file_yields_two_distinct_periods():
    """This is what makes any year-over-year operation possible at all."""
    a = resolve_period("Năm nay Triệu đồng", F2021).year
    b = resolve_period("Năm trước Triệu đồng", F2021).year
    assert a == "2021" and b == "2020" and a != b


def test_resolution_records_its_provenance():
    p = resolve_period("Năm trước", F2018)
    assert p.anchor_year == "2018"
    assert p.source == "filename+col_label"
