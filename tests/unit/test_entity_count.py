from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell, Selector
from text2pandas.pipelines.answering.entity_count import answer_entity_count
from text2pandas.pipelines.answering.units import MONEY, SHARES, Unit


def _cell(entity: str, value: float, label: str = "Thuế thu nhập doanh nghiệp"):
    number = ord(entity[-1]) - ord("A") + 1
    return CandidateCell(
        df_var=f"df{number}",
        csv_path=f"data/{entity}.csv",
        row_index=0,
        row_path=label,
        col_label="Năm 2024 Tỷ đồng",
        value_raw=str(value),
        value=value,
        parsed_raw=value,
        storage_exponent=0,
        unit=Unit(MONEY, 9, "VND"),
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


def test_entity_count_executes_money_threshold() -> None:
    cells = [_cell("AAA", 60), _cell("BBB", 10), _cell("CCC", 70)]

    result = answer_entity_count(
        "Tổng số công ty AAA, BBB và CCC có thuế thu nhập doanh nghiệp "
        "lớn hơn 50 tỷ đồng năm 2024?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB", "CCC"],
        years=[2024],
        basis="consolidated",
        selector=Selector(),
        mode="screen",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(2.0)
    assert len(result.evidence) == 3


def test_entity_count_executes_positive_predicate() -> None:
    cells = [_cell("AAA", 1), _cell("BBB", -1)]

    result = answer_entity_count(
        "Có bao nhiêu công ty AAA và BBB có lưu chuyển tiền thuần dương năm 2024?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        selector=Selector(),
        mode="screen",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(1.0)


def test_entity_count_scales_reviewed_outstanding_shares() -> None:
    cells = [
        replace(
            _cell("AAA", 500_000_000, "Cổ phiếu phổ thông đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
        replace(
            _cell("BBB", 300_000_000, "Số lượng cổ phiếu đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
    ]

    result = answer_entity_count(
        "Có bao nhiêu công ty AAA và BBB có số lượng cổ phiếu phổ thông đang "
        "lưu hành vượt 400 triệu cổ phiếu năm 2024?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        selector=Selector(),
        mode="screen",
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(1.0)


def test_compound_multi_metric_entity_count_is_not_routed() -> None:
    result = answer_entity_count(
        "Có bao nhiêu công ty AAA và BBB đồng thời có vốn lưu động ròng âm "
        "và lưu chuyển tiền thuần dương năm 2024?",
        [],
        {},
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        selector=Selector(),
        mode="screen",
    )

    assert result is None
