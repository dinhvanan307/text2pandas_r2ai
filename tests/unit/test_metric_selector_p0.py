from __future__ import annotations

from dataclasses import replace

from text2pandas.application.selection import SelectorSpec
from text2pandas.domain.semantic import Basis
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.pipelines.answering.binding import CandidateCell
from text2pandas.pipelines.answering.ir import OperandSlot
from text2pandas.pipelines.answering.metric_selector import MetricAwareSelector
from text2pandas.pipelines.answering.units import MONEY, PERCENT, Unit


def _spec(
    metric_id: str,
    *,
    entity: str = "AAA",
    period: str = "2024",
    basis: Basis = Basis.CONSOLIDATED,
    period_role: str | None = None,
) -> SelectorSpec:
    ontology = load_ontology()
    return SelectorSpec.from_metric(
        ontology.metrics[metric_id],
        ontology_fingerprint=ontology.fingerprint,
        entity=entity,
        period=period,
        requested_period_role=period_role,
        requested_basis=basis,
    )


def _cell(
    row: str,
    *,
    value: float = 100.0,
    row_index: int = 0,
    entity: str = "AAA",
    period: str = "2024",
    basis: str = "consolidated",
    statement_type: str = "balance_sheet",
    period_role: str = "closing",
    unit: Unit | None = None,
    table_rank: int = 0,
    table_uid: str = "table",
    is_restated: bool = False,
    section_text: str = "",
    table_context: str = "",
    metric_code: str | None = None,
) -> CandidateCell:
    return CandidateCell(
        df_var="df1",
        csv_path="data/t.csv",
        row_index=row_index,
        row_path=row,
        col_label=f"{period} Triệu đồng",
        value_raw=str(value),
        value=value,
        parsed_raw=value,
        storage_exponent=0,
        unit=unit or Unit(MONEY, 6),
        period=period,
        table_uid=table_uid,
        document_id="doc",
        entity=entity,
        basis=basis,
        statement_type=statement_type,
        metric_code=metric_code,
        period_role=period_role,
        is_restated=is_restated,
        table_rank=table_rank,
        section_text=section_text,
        table_context=table_context,
    )


def test_parent_metric_rejects_forbidden_child_even_with_better_table_rank() -> None:
    selector = MetricAwareSelector({"value": _spec("total_liabilities")})
    slot = OperandSlot("value", metric_id="total_liabilities", period="2024", entity="AAA")
    parent = _cell("Nợ phải trả", table_rank=9, table_uid="parent")
    child = _cell("Nợ phải trả người bán", table_rank=0, table_uid="child")

    ranked = selector.rank(slot, [child, parent])

    assert ranked == [parent]
    assert "FORBIDDEN_PREFIX" in selector.inspect(slot, child).reasons


def test_selector_rejects_pat_allocation_inventory_provision_and_other_revenue() -> None:
    fixtures = (
        ("profit_after_tax", "Lợi nhuận sau thuế của cổ đông công ty mẹ"),
        ("inventory", "Dự phòng giảm giá hàng tồn kho"),
        ("net_revenue", "Doanh thu thuần khác"),
    )

    for metric_id, row in fixtures:
        spec = _spec(metric_id)
        statement = "income_statement" if metric_id != "inventory" else "balance_sheet"
        role = "current" if statement == "income_statement" else "closing"
        cell = _cell(row, statement_type=statement, period_role=role)
        selector = MetricAwareSelector({"value": spec})
        slot = OperandSlot("value", metric_id=metric_id, period="2024", entity="AAA")
        assert selector.rank(slot, [cell]) == []
        assert any(reason.startswith("FORBIDDEN") for reason in selector.inspect(slot, cell).reasons)


def test_hard_scope_dimension_and_statement_gates() -> None:
    selector = MetricAwareSelector({"value": _spec("gross_profit")})
    slot = OperandSlot("value", metric_id="gross_profit", period="2024", entity="AAA")
    valid = _cell(
        "Lợi nhuận gộp",
        statement_type="income_statement",
        period_role="current",
    )
    wrong_entity = replace(valid, entity="BBB")
    wrong_period = replace(valid, period="2023")
    wrong_basis = replace(valid, basis="separate")
    wrong_dimension = replace(valid, unit=Unit(PERCENT))
    wrong_statement = replace(valid, statement_type="balance_sheet", period_role="closing")

    assert selector.rank(slot, [valid]) == [valid]
    for candidate in (
        wrong_entity,
        wrong_period,
        wrong_basis,
        wrong_dimension,
        wrong_statement,
    ):
        assert selector.rank(slot, [candidate]) == []


def test_required_context_and_explicit_period_role_are_hard_constraints() -> None:
    selector = MetricAwareSelector(
        {"value": _spec("common_loan_loss_provision", period_role="closing")}
    )
    slot = OperandSlot(
        "value",
        metric_id="common_loan_loss_provision",
        period="2024",
        entity="AAA",
    )
    missing_context = _cell("Dự phòng chung")
    opening = _cell(
        "Dự phòng rủi ro cho vay khách hàng › Dự phòng chung",
        period_role="opening",
        statement_type="note",
        table_context="Dự phòng rủi ro cho vay khách hàng",
    )
    valid = replace(opening, period_role="closing")

    assert selector.rank(slot, [missing_context, opening, valid]) == [valid]


def test_metric_correctness_precedes_table_prior_and_nonrestated_breaks_safe_tie() -> None:
    selector = MetricAwareSelector({"value": _spec("gross_profit")})
    slot = OperandSlot("value", metric_id="gross_profit", period="2024", entity="AAA")
    prefix = _cell(
        "Lợi nhuận gộp bộ phận",
        statement_type="income_statement",
        period_role="current",
        table_rank=0,
        table_uid="prefix",
    )
    exact_restated = _cell(
        "Lợi nhuận gộp",
        statement_type="income_statement",
        period_role="current",
        table_rank=5,
        table_uid="restated",
        is_restated=True,
    )
    exact_current = replace(
        exact_restated,
        table_uid="current",
        row_index=1,
        is_restated=False,
    )

    ranked = selector.rank(slot, [prefix, exact_restated, exact_current])

    assert ranked[0] is exact_current
    assert ranked[1] is exact_restated
    assert ranked[2] is prefix


def test_candidate_order_does_not_change_selection() -> None:
    selector = MetricAwareSelector({"value": _spec("gross_profit")})
    slot = OperandSlot("value", metric_id="gross_profit", period="2024", entity="AAA")
    left = _cell(
        "Lợi nhuận gộp",
        statement_type="income_statement",
        period_role="current",
        table_uid="a",
    )
    right = replace(left, table_uid="b", row_index=1)

    assert selector.rank(slot, [right, left])[0] is left
    assert selector.rank(slot, [left, right])[0] is left


def test_semantic_tie_with_different_values_abstains_instead_of_uid_tiebreak() -> None:
    selector = MetricAwareSelector({"value": _spec("gross_profit")})
    slot = OperandSlot("value", metric_id="gross_profit", period="2024", entity="AAA")
    left = _cell(
        "Lợi nhuận gộp",
        value=100.0,
        statement_type="income_statement",
        period_role="current",
        table_uid="a",
    )
    right = replace(left, value=200.0, parsed_raw=200.0, table_uid="b", row_index=1)

    assert selector.rank(slot, [left, right]) == []
    assert selector.failure_reason(slot, [left, right]) == "AMBIGUOUS_BINDING"
