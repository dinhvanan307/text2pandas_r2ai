from __future__ import annotations

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell, Selector
from text2pandas.pipelines.answering.entity_sum import answer_entity_sum
from text2pandas.pipelines.answering.units import MONEY, PERCENT, Unit


def _cell(entity: str, value: float, label: str = "Chi phí tài chính") -> CandidateCell:
    number = ord(entity[-1]) - ord("A") + 1
    return CandidateCell(
        df_var=f"df{number}",
        csv_path=f"data/{entity}.csv",
        row_index=0,
        row_path=label,
        col_label="Năm 2024 Triệu đồng",
        value_raw=str(value),
        value=value,
        parsed_raw=value,
        storage_exponent=0,
        unit=Unit(MONEY, 6, "VND"),
        period="2024-12-31",
        table_uid=f"table-{entity}",
        document_id=f"report-{entity}",
        entity=entity,
        basis="consolidated",
    )


def _frames(cells: list[CandidateCell]) -> dict[str, pd.DataFrame]:
    return {
        cell.df_var: pd.DataFrame(
            [{"row_path": cell.row_path, "col_label": cell.col_label, "value": cell.value}]
        )
        for cell in cells
    }


def test_entity_sum_executes_in_requested_money_unit() -> None:
    cells = [_cell("AAA", -1_000), _cell("BBB", 2_000), _cell("CCC", 3_000)]

    result = answer_entity_sum(
        "Tổng chi phí tài chính của AAA, BBB và CCC năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB", "CCC"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(6.0)
    assert len(result.evidence) == 3
    assert "abs(" in result.query


def test_entity_sum_abstains_when_reviewed_metric_is_unbound() -> None:
    cells = [_cell("AAA", 1_000), _cell("BBB", 2_000, "Chi phí lãi vay")]

    result = answer_entity_sum(
        "Tổng chi phí tài chính của AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
    )

    assert result is not None
    assert result.reason == "ENTITY_SUM_UNBOUND:BBB"


@pytest.mark.parametrize(
    ("question", "years", "unit"),
    [
        (
            "Chi phí tài chính của AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
            [2024],
            Unit(MONEY, 9, "VND"),
        ),
        (
            "Tổng chi phí tài chính của AAA và BBB năm 2023 và 2024 là bao nhiêu?",
            [2023, 2024],
            Unit(MONEY, 9, "VND"),
        ),
        (
            "Tỷ trọng chi phí tài chính của AAA và BBB là bao nhiêu phần trăm?",
            [2024],
            Unit(PERCENT),
        ),
        (
            "Tổng chi phí chưa review của AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
            [2024],
            Unit(MONEY, 9, "VND"),
        ),
    ],
)
def test_entity_sum_rejects_out_of_contract_questions(
    question: str,
    years: list[int],
    unit: Unit,
) -> None:
    result = answer_entity_sum(
        question,
        [],
        {},
        entities=["AAA", "BBB"],
        years=years,
        basis="consolidated",
        requested_unit=unit,
        selector=Selector(),
    )

    assert result is None
