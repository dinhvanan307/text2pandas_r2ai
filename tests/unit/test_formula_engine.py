from __future__ import annotations

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell
from text2pandas.pipelines.answering.formula_engine import (
    answer_formula_question,
    load_registry,
    match_formula,
)
from text2pandas.pipelines.answering.units import MONEY, PERCENT, RATIO, Unit


def _cell(
    label: str,
    value: float,
    row: int,
    *,
    metric_code: str | None = None,
    document_id: str | None = None,
) -> CandidateCell:
    return CandidateCell(
        df_var="df1",
        csv_path="data/table.csv",
        row_index=row,
        row_path=label,
        col_label="2024 Triệu đồng",
        value_raw=str(value),
        value=value,
        parsed_raw=value,
        storage_exponent=0,
        unit=Unit(MONEY, 6, "VND"),
        period="2024-12-31",
        table_uid="table-1",
        document_id=document_id,
        entity="HPG",
        basis="consolidated",
        metric_code=metric_code,
    )


def _frames(cells: list[CandidateCell]) -> dict[str, pd.DataFrame]:
    return {
        "df1": pd.DataFrame(
            [
                {
                    "row_path": cell.row_path,
                    "col_label": cell.col_label,
                    "value": cell.value,
                }
                for cell in cells
            ]
        )
    }


def test_registry_only_loads_reviewed_formulas() -> None:
    formulas, metrics = load_registry()

    assert len(formulas) == 18
    assert "quick_ratio" in formulas
    assert "roe" not in formulas
    assert set(formulas["quick_ratio"].leaves) <= set(metrics)


def test_current_ratio_binds_two_distinct_metrics_and_executes() -> None:
    cells = [_cell("Tài sản ngắn hạn", 200, 0), _cell("Nợ ngắn hạn", 100, 1)]

    result = answer_formula_question(
        "Hệ số thanh toán hiện hành của HPG năm 2024 là bao nhiêu lần?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(RATIO),
        qid=1,
    )

    assert result is not None and result.ok, result.reason if result else None
    assert result.formula_id == "current_ratio"
    assert result.answer == pytest.approx(2.0)
    assert "Tài sản ngắn hạn" in result.query and "Nợ ngắn hạn" in result.query
    assert result.evidence == [{"variable": "df1", "csv_path": "data/table.csv"}]


def test_quick_ratio_and_net_margin_support_nested_expression_nodes() -> None:
    quick_cells = [
        _cell("Tài sản ngắn hạn", 200, 0),
        _cell("Hàng tồn kho", 50, 1),
        _cell("Nợ ngắn hạn", 100, 2),
    ]
    margin_cells = [_cell("Lợi nhuận sau thuế", 20, 0), _cell("Doanh thu thuần", 100, 1)]

    quick = answer_formula_question(
        "Hệ số thanh toán nhanh HPG năm 2024 là bao nhiêu lần?",
        quick_cells,
        _frames(quick_cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(RATIO),
    )
    margin = answer_formula_question(
        "Biên lợi nhuận ròng HPG năm 2024 là bao nhiêu phần trăm?",
        margin_cells,
        _frames(margin_cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert quick is not None and quick.answer == pytest.approx(1.5)
    assert margin is not None and margin.answer == pytest.approx(20.0)


@pytest.mark.parametrize(
    ("question", "expense_label", "expected_formula"),
    [
        (
            "Tỷ lệ chi phí quản lý doanh nghiệp trên doanh thu thuần là bao nhiêu %?",
            "Chi phí quản lý doanh nghiệp",
            "admin_expense_intensity",
        ),
        (
            "Tỷ lệ chi phí bán hàng trên doanh thu thuần là bao nhiêu %?",
            "Chi phí bán hàng",
            "selling_expense_intensity",
        ),
        (
            "Tỷ lệ giá vốn hàng bán trên doanh thu thuần là bao nhiêu %?",
            "Giá vốn hàng bán",
            "cogs_intensity",
        ),
    ],
)
def test_reviewed_expense_intensities_execute_with_absolute_numerator(
    question: str,
    expense_label: str,
    expected_formula: str,
) -> None:
    cells = [_cell(expense_label, -25, 0), _cell("Doanh thu thuần", 100, 1)]

    result = answer_formula_question(
        question,
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.formula_id == expected_formula
    assert result.answer == pytest.approx(25.0)
    assert "abs(" in result.query


@pytest.mark.parametrize(
    ("question", "numerator_label", "denominator_label", "expected_formula"),
    [
        (
            "Lợi nhuận sau thuế trên tổng tài sản cuối năm 2024 là bao nhiêu phần trăm?",
            "Lợi nhuận sau thuế",
            "Tổng tài sản",
            "return_on_ending_assets",
        ),
        (
            "Tỷ lệ nợ ngắn hạn trên vốn chủ sở hữu năm 2024 là bao nhiêu phần trăm?",
            "Nợ ngắn hạn",
            "Vốn chủ sở hữu",
            "current_liabilities_to_equity",
        ),
        (
            "Tỷ lệ chi phí tài chính trên doanh thu thuần năm 2024 là bao nhiêu phần trăm?",
            "Chi phí tài chính",
            "Doanh thu thuần",
            "financial_expense_intensity",
        ),
        (
            "Tỷ lệ doanh thu hoạt động tài chính trên chi phí tài chính năm 2024 là bao nhiêu phần trăm?",
            "Doanh thu hoạt động tài chính",
            "Chi phí tài chính",
            "financial_income_to_financial_expense",
        ),
        (
            "Tỷ trọng tài sản cố định hữu hình trong tổng tài sản cố định năm 2024 là bao nhiêu phần trăm?",
            "Tài sản cố định hữu hình",
            "Tài sản cố định",
            "tangible_fixed_assets_share_of_total_fixed_assets",
        ),
        (
            "Tỷ trọng tài sản cố định vô hình trên tổng tài sản năm 2024 là bao nhiêu phần trăm?",
            "Tài sản cố định vô hình",
            "Tổng tài sản",
            "intangible_fixed_assets_to_assets",
        ),
        (
            "Tỷ trọng tài sản cố định hữu hình trên tổng tài sản năm 2024 là bao nhiêu phần trăm?",
            "Tài sản cố định hữu hình",
            "Tổng tài sản",
            "tangible_fixed_assets_to_assets",
        ),
    ],
)
def test_reviewed_unambiguous_relational_formulas_execute(
    question: str,
    numerator_label: str,
    denominator_label: str,
    expected_formula: str,
) -> None:
    cells = [_cell(numerator_label, 20, 0), _cell(denominator_label, 100, 1)]

    result = answer_formula_question(
        question,
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.formula_id == expected_formula
    assert result.answer == pytest.approx(20.0)


def test_total_fixed_assets_metric_rejects_component_rows() -> None:
    cells = [
        _cell("Tài sản cố định hữu hình", 20, 0),
        _cell("Tài sản cố định vô hình", 80, 1),
    ]

    result = answer_formula_question(
        "Tỷ trọng tài sản cố định hữu hình trong tổng tài sản cố định là bao nhiêu %?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None
    assert result.reason == "FORMULA_METRIC_NOT_IN_POOL:total_fixed_assets"


def test_formula_engine_fails_closed_on_scope_period_and_forbidden_child_metric() -> None:
    cells = [_cell("Tổng tài sản", 200, 0), _cell("Nợ phải trả người bán", 100, 1)]

    multiple_periods = answer_formula_question(
        "Hệ số nợ trên tổng tài sản HPG năm 2023 và 2024 là bao nhiêu phần trăm?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2023, 2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )
    forbidden = answer_formula_question(
        "Hệ số nợ trên tổng tài sản HPG năm 2024 là bao nhiêu phần trăm?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert multiple_periods is not None
    assert multiple_periods.reason == "FORMULA_REQUIRES_ONE_PERIOD"
    assert forbidden is not None
    assert forbidden.reason == "FORMULA_METRIC_NOT_IN_POOL:total_liabilities"


def test_unreviewed_formula_does_not_match() -> None:
    assert match_formula("ROE của HPG năm 2024 là bao nhiêu?") is None


def test_formula_operands_must_come_from_one_report() -> None:
    cells = [
        _cell("Nợ phải trả", 100, 0, document_id="report-a"),
        _cell("Tổng tài sản", 200, 1, document_id="report-b"),
    ]

    result = answer_formula_question(
        "Tỷ lệ nợ trên tổng tài sản HPG năm 2024 là bao nhiêu phần trăm?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None
    assert result.reason == "FORMULA_OPERANDS_NOT_COHERENT"


def test_bank_total_assets_alias_prefers_balance_sheet_wording() -> None:
    cells = [
        _cell("Tổng nợ phải trả", 80, 0, document_id="report-a"),
        _cell("Tổng tài sản", 10, 1, document_id="report-a"),
        _cell("TỔNG TÀI SẢN CÓ", 100, 2, document_id="report-a"),
    ]

    result = answer_formula_question(
        "Tỷ lệ nợ trên tổng tài sản HPG năm 2024 là bao nhiêu phần trăm?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(80.0)
    assert "TỔNG TÀI SẢN CÓ" in result.query
