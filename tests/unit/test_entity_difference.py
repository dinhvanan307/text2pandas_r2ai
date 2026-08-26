from __future__ import annotations

import pandas as pd
import pytest
from dataclasses import replace

from text2pandas.pipelines.answering.binding import CandidateCell, Selector
from text2pandas.pipelines.answering.entity_difference import answer_entity_difference
from text2pandas.pipelines.answering.units import MONEY, SHARES, Unit


def _cell(entity: str, value: float, label: str = "Doanh thu thuần") -> CandidateCell:
    index = 1 if entity == "BBB" else 0
    return CandidateCell(
        df_var=f"df{index + 1}",
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


def test_two_entity_same_metric_difference_executes_in_requested_unit() -> None:
    cells = [_cell("AAA", 5_000), _cell("BBB", 2_000)]

    result = answer_entity_difference(
        "Chênh lệch doanh thu thuần giữa AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
        mode="compare",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(3.0)
    assert not result.query.startswith("abs(")
    assert len(result.evidence) == 2


def test_two_entity_difference_preserves_first_minus_second_direction() -> None:
    cells = [_cell("AAA", 2_000), _cell("BBB", 5_000)]

    result = answer_entity_difference(
        "Chênh lệch doanh thu thuần của AAA so với BBB năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
        mode="compare",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(-3.0)


def test_two_entity_difference_abstains_on_metric_drift() -> None:
    cells = [_cell("AAA", 5_000), _cell("BBB", 2_000, "Lợi nhuận sau thuế")]

    result = answer_entity_difference(
        "Chênh lệch doanh thu thuần giữa AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
        mode="compare",
    )

    assert result is not None
    assert result.reason == "ENTITY_DIFFERENCE_METRIC_DRIFT"


def test_multi_period_entity_difference_is_not_routed() -> None:
    result = answer_entity_difference(
        "Chênh lệch doanh thu giữa AAA và BBB năm 2023 và 2024 là bao nhiêu?",
        [],
        {},
        entities=["AAA", "BBB"],
        years=[2023, 2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
        mode="compare",
    )

    assert result is None


def test_reviewed_outstanding_share_aliases_convert_to_million_shares() -> None:
    cells = [
        replace(
            _cell("AAA", 800_000_000, "Cổ phiếu phổ thông đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
        replace(
            _cell("BBB", 500_000_000, "Số lượng cổ phiếu đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
    ]

    result = answer_entity_difference(
        "Chênh lệch số lượng cổ phiếu phổ thông đang lưu hành giữa AAA và BBB "
        "năm 2024 là bao nhiêu triệu cổ phiếu?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(SHARES, 6),
        selector=Selector(),
        mode="compare",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(300.0)
