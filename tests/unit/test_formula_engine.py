from __future__ import annotations

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell
from text2pandas.pipelines.answering.formula_engine import (
    _rank_metric_candidates,
    answer_formula_question,
    load_registry,
    match_formula,
)
from text2pandas.pipelines.answering.units import MONEY, PERCENT, RATIO, UNKNOWN, Unit


def _cell(
    label: str,
    value: float,
    row: int,
    *,
    metric_code: str | None = None,
    document_id: str | None = None,
    statement_type: str | None = None,
    period_role: str | None = None,
    col_label: str = "2024 Triệu đồng",
    section_text: str = "",
) -> CandidateCell:
    return CandidateCell(
        df_var="df1",
        csv_path="data/table.csv",
        row_index=row,
        row_path=label,
        col_label=col_label,
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
        statement_type=statement_type,
        metric_code=metric_code,
        period_role=period_role,
        section_text=section_text,
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

    assert len(formulas) == 27
    assert "quick_ratio" in formulas
    assert "roe" not in formulas
    assert set(formulas["quick_ratio"].leaves) <= set(metrics)


def test_ambiguous_metric_requires_its_reviewed_financial_context() -> None:
    _, metrics = load_registry()
    investment = _cell(
        "Chứng khoán đầu tư sẵn sàng để bán › Dự phòng chung",
        -20,
        0,
        statement_type="note",
        section_text="Chứng khoán đầu tư sẵn sàng để bán",
    )
    lending = _cell(
        "Dự phòng rủi ro cho vay khách hàng › Dự phòng chung",
        -100,
        1,
        statement_type="note",
        section_text="Dự phòng rủi ro cho vay khách hàng",
    )

    ranked = _rank_metric_candidates(
        metrics["common_loan_loss_provision"],
        [investment, lending],
        entity="HPG",
        year=2024,
        basis="consolidated",
    )

    assert [cell for _, cell in ranked] == [lending]


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
            "Tỷ lệ vay ngắn hạn trên vốn chủ sở hữu năm 2024 là bao nhiêu phần trăm?",
            "Vay ngắn hạn",
            "Vốn chủ sở hữu",
            "short_term_borrowings_to_equity",
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


@pytest.mark.parametrize(
    ("question", "first_label", "second_label", "expected_formula", "expected"),
    [
        (
            "Tỷ trọng tài sản cố định vô hình trong tổng tài sản cố định là bao nhiêu %?",
            "Tài sản cố định vô hình",
            "Tài sản cố định hữu hình",
            "intangible_fixed_assets_share_of_component_total",
            25.0,
        ),
        (
            "Tỷ trọng khoản phải thu ngắn hạn khác trong tổng khoản phải thu khác là bao nhiêu %?",
            "Phải thu ngắn hạn khác",
            "Phải thu dài hạn khác",
            "short_term_other_receivables_share",
            25.0,
        ),
    ],
)
def test_reviewed_component_total_formulas_execute(
    question: str,
    first_label: str,
    second_label: str,
    expected_formula: str,
    expected: float,
) -> None:
    cells = [_cell(first_label, 25, 0), _cell(second_label, 75, 1)]

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
    assert result.answer == pytest.approx(expected)


@pytest.mark.parametrize(
    ("question", "first_label", "second_label", "unit", "expected_formula", "expected"),
    [
        (
            "Tính tỷ lệ chi phí trả trước ngắn hạn trên chi phí trả trước dài hạn năm 2024.",
            "Chi phí trả trước ngắn hạn",
            "Chi phí trả trước dài hạn",
            Unit(RATIO),
            "short_to_long_prepaid_expenses",
            0.25,
        ),
        (
            "Tính tỷ số nợ ngắn hạn trên vốn chủ sở hữu năm 2024.",
            "Nợ ngắn hạn",
            "Vốn chủ sở hữu",
            Unit(RATIO),
            "current_liabilities_to_equity_ratio",
            0.25,
        ),
        (
            "Tỷ trọng dự phòng chung trên tổng dự phòng rủi ro cho vay khách hàng là bao nhiêu phần trăm?",
            "Dự phòng chung",
            "Dự phòng rủi ro cho vay khách hàng",
            Unit(PERCENT),
            "common_loan_loss_provision_share",
            25.0,
        ),
    ],
)
def test_additional_reviewed_relational_formulas(
    question: str,
    first_label: str,
    second_label: str,
    unit: Unit,
    expected_formula: str,
    expected: float,
) -> None:
    cells = [_cell(first_label, 25, 0), _cell(second_label, 100, 1)]
    if expected_formula == "common_loan_loss_provision_share":
        cells[0] = _cell(
            first_label,
            25,
            0,
            section_text="Dự phòng rủi ro cho vay khách hàng",
        )

    result = answer_formula_question(
        question,
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=unit,
    )

    assert result is not None and result.ok, result.reason if result else None
    assert result.formula_id == expected_formula
    assert result.answer == pytest.approx(expected)


def test_reviewed_ratio_supplies_implicit_unit_when_question_omits_lan() -> None:
    cells = [
        _cell("Chi phí trả trước ngắn hạn", 20, 0),
        _cell("Chi phí trả trước dài hạn", 80, 1),
    ]

    result = answer_formula_question(
        "Tính tỷ lệ chi phí trả trước ngắn hạn trên chi phí trả trước dài hạn năm 2024.",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(UNKNOWN),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(0.25)


def test_short_term_borrowings_prefers_reported_aggregate_over_component() -> None:
    cells = [
        _cell("Trong đó: Chi phí lãi vay", 20, 0, statement_type="income_statement"),
        _cell("Vay ngắn hạn", 50, 1, statement_type="note", period_role="closing"),
        _cell(
            "Vay và trái phiếu phát hành ngắn hạn",
            100,
            2,
            statement_type="balance_sheet",
            period_role="closing",
        ),
    ]

    result = answer_formula_question(
        "Tỷ lệ chi phí lãi vay trên nợ vay ngắn hạn là bao nhiêu %?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(20.0)
    assert "Vay và trái phiếu phát hành ngắn hạn" in result.query


def test_exact_metric_label_outranks_prefix_component() -> None:
    cells = [
        _cell("Chi phí trả trước ngắn hạn", 20, 0),
        _cell("Chi phí trả trước dài hạn khác", 10, 1),
        _cell("Chi phí trả trước dài hạn", 80, 2),
    ]

    result = answer_formula_question(
        "Tỷ lệ chi phí trả trước ngắn hạn trên chi phí trả trước dài hạn",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(RATIO),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(0.25)
    assert "Chi phí trả trước dài hạn khác" not in result.query


@pytest.mark.parametrize(
    ("question", "numerator_label", "denominator_label", "formula_id", "numerator"),
    [
        (
            "Tỷ lệ chi phí lãi vay trên nợ vay ngắn hạn là bao nhiêu %?",
            "Chi phí lãi vay",
            "Vay ngắn hạn",
            "interest_expense_to_short_term_borrowings",
            -20,
        ),
        (
            "Tỷ lệ lãi vay trên nợ vay dài hạn là bao nhiêu %?",
            "Chi phí lãi vay",
            "Vay dài hạn",
            "interest_expense_to_long_term_borrowings",
            -20,
        ),
        (
            "Tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên lợi nhuận trước thuế là bao nhiêu %?",
            "Lưu chuyển tiền thuần từ hoạt động kinh doanh",
            "XI. Tổng lợi nhuận trước thuế",
            "cfo_to_profit_before_tax",
            20,
        ),
    ],
)
def test_reviewed_flow_over_balance_formulas_execute(
    question: str,
    numerator_label: str,
    denominator_label: str,
    formula_id: str,
    numerator: float,
) -> None:
    cells = [_cell(numerator_label, numerator, 0), _cell(denominator_label, 100, 1)]

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
    assert result.formula_id == formula_id
    assert result.answer == pytest.approx(20.0)


def test_point_in_time_metric_prefers_closing_balance_over_movement_column() -> None:
    cells = [
        _cell(
            "Trong đó: Chi phí lãi vay",
            20,
            0,
            statement_type="income_statement",
        ),
        _cell(
            "Vay ngắn hạn",
            -60,
            1,
            statement_type="note",
            period_role="current",
            col_label="Biến động trong năm › Thanh toán",
            section_text="Vay và trái phiếu phát hành ngắn hạn",
        ),
        _cell(
            "Vay ngắn hạn",
            100,
            2,
            statement_type="note",
            period_role="closing",
            col_label="31/12/2024",
            section_text="Vay và trái phiếu phát hành ngắn hạn",
        ),
    ]

    result = answer_formula_question(
        "Tỷ lệ chi phí lãi vay trên nợ vay ngắn hạn là bao nhiêu %?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(20.0)
    assert "31/12/2024" in result.query


def test_metric_statement_contract_rejects_cash_flow_proxy_for_interest_expense() -> None:
    cells = [
        _cell(
            "Chi phí lãi vay",
            20,
            0,
            statement_type="cash_flow",
        ),
        _cell("Vay ngắn hạn", 100, 1, statement_type="note"),
    ]

    result = answer_formula_question(
        "Tỷ lệ chi phí lãi vay trên nợ vay ngắn hạn là bao nhiêu %?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None
    assert result.reason == "FORMULA_METRIC_NOT_IN_POOL:interest_expense"


def test_formula_specific_percent_bound_allows_reviewed_extreme_ratio() -> None:
    cells = [
        _cell("Lưu chuyển tiền thuần từ hoạt động kinh doanh", 300, 0),
        _cell("XI. Tổng lợi nhuận trước thuế", 1, 1),
    ]

    result = answer_formula_question(
        "Tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên lợi nhuận trước thuế là bao nhiêu %?",
        cells,
        _frames(cells),
        entity="HPG",
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(PERCENT),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(30_000.0)


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
