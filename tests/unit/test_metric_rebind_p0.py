from __future__ import annotations

import pandas as pd

from text2pandas.application.selection import SelectorSpec
from text2pandas.domain.semantic import Basis
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.semantic import load_metric_selector_policy
from text2pandas.pipelines.answering import CandidateCell, Unit, answer_question
from text2pandas.pipelines.answering.binding import Selector, bind_ranked
from text2pandas.pipelines.answering.ir import OperandSlot, OperationIR
from text2pandas.pipelines.answering.metric_selector import MetricAwareSelector
from text2pandas.pipelines.answering.units import MONEY, PERCENT


def _candidate(
    row: str,
    *,
    row_index: int,
    value: float,
    storage_exponent: int | None,
    table_rank: int,
) -> CandidateCell:
    return CandidateCell(
        df_var="df1",
        csv_path="data/t.csv",
        row_index=row_index,
        row_path=row,
        col_label="2024 Triệu đồng",
        value_raw=str(value),
        value=value,
        parsed_raw=value,
        storage_exponent=storage_exponent,
        unit=Unit(MONEY, 6),
        period="2024",
        table_uid=f"t{row_index}",
        document_id="doc",
        entity="AAA",
        basis="consolidated",
        statement_type="income_statement",
        period_role="current",
        table_rank=table_rank,
    )


def _frames(cells: list[CandidateCell]) -> dict[str, pd.DataFrame]:
    rows = [
        {
            "row_path": cell.row_path,
            "col_label": cell.col_label,
            "value_raw": cell.value_raw,
            "value": cell.value,
        }
        for cell in sorted(cells, key=lambda value: value.row_index)
    ]
    return {"df1": pd.DataFrame(rows)}


def test_bind_validate_rebind_uses_second_candidate_after_render_failure() -> None:
    ontology = load_ontology()
    spec = SelectorSpec.from_metric(
        ontology.metrics["gross_profit"],
        ontology_fingerprint=ontology.fingerprint,
        entity="AAA",
        period="2024",
        requested_period_role="current",
        requested_basis=Basis.CONSOLIDATED,
    )
    selector = MetricAwareSelector({"value": spec})
    bad = _candidate(
        "Lợi nhuận gộp",
        row_index=0,
        value=100.0,
        storage_exponent=None,
        table_rank=0,
    )
    good = _candidate(
        "Lợi nhuận gộp",
        row_index=1,
        value=100.0,
        storage_exponent=0,
        table_rank=1,
    )

    result = answer_question(
        "Lợi nhuận gộp của AAA năm 2024 là bao nhiêu triệu đồng?",
        [bad, good],
        _frames([bad, good]),
        metric_id="gross_profit",
        requested_unit=Unit(MONEY, 6),
        selector=selector,
        resolved_entity="AAA",
        max_bind_attempts=3,
    )

    assert result.ok, result.reason
    assert result.operands[0].cell is good
    assert result.answer == 100.0
    assert [entry["stage"] for entry in result.trace].count("REBIND") == 1
    assert next(entry for entry in result.trace if entry["stage"] == "REBIND") == {
        "stage": "REBIND",
        "from_attempt": 1,
        "next_attempt": 2,
        "trigger_stage": "RENDER",
        "trigger_reason": "UNIT_CONTRACT_ABSTAIN:value:MISSING_STORAGE_SCALE",
    }


def test_ranked_binding_is_capped_at_three() -> None:
    cells = [
        _candidate(
            "Lợi nhuận gộp",
            row_index=index,
            value=100.0,
            storage_exponent=0,
            table_rank=index,
        )
        for index in range(5)
    ]
    ir = OperationIR(
        "LOOKUP",
        (OperandSlot("value", metric_id="gross_profit", period="2024", entity="AAA"),),
        Unit(MONEY, 6),
    )
    ontology = load_ontology()
    spec = SelectorSpec.from_metric(
        ontology.metrics["gross_profit"],
        ontology_fingerprint=ontology.fingerprint,
        entity="AAA",
        period="2024",
        requested_period_role="current",
        requested_basis=Basis.CONSOLIDATED,
    )

    policy = load_metric_selector_policy()
    bindings = bind_ranked(
        ir,
        cells,
        selector=MetricAwareSelector(
            {"value": spec}, ambiguity_margin=policy.ambiguity_margin
        ),
        max_bindings=policy.max_rebind_candidates,
    )

    assert len(bindings) == 3
    assert policy.max_rebind_candidates == 3


class _RoleSelector(Selector):
    def __init__(
        self, numerator: CandidateCell, denominators: list[CandidateCell]
    ) -> None:
        self.numerator = numerator
        self.denominators = denominators

    def rank(self, slot: OperandSlot, pool: list[CandidateCell]) -> list[CandidateCell]:
        _ = pool
        return [self.numerator] if slot.role == "numerator" else self.denominators


def test_zero_divisor_does_not_trigger_rebind() -> None:
    numerator = _candidate(
        "A", row_index=0, value=10.0, storage_exponent=0, table_rank=0
    )
    zero = _candidate("B", row_index=1, value=0.0, storage_exponent=0, table_rank=0)
    nonzero = _candidate("B", row_index=2, value=2.0, storage_exponent=0, table_rank=1)
    selector = _RoleSelector(numerator, [zero, nonzero])

    result = answer_question(
        "A trên B của AAA năm 2024 là bao nhiêu phần trăm?",
        [numerator, zero, nonzero],
        _frames([numerator, zero, nonzero]),
        requested_unit=Unit(PERCENT),
        selector=selector,
        resolved_entity="AAA",
        max_bind_attempts=3,
    )

    assert result.status == "ABSTAIN"
    assert result.stage_failed == "POLICY"
    assert result.reason == "ZERO_DENOMINATOR"
    assert all(entry["stage"] != "REBIND" for entry in result.trace)
