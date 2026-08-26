from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell, Selector
from text2pandas.pipelines.answering.entity_average import answer_entity_average
from text2pandas.pipelines.answering.units import MONEY, PERCENT, SHARES, Unit


def _cell(
    entity: str,
    value: float,
    label: str = "Thuế và các khoản phải nộp Nhà nước",
) -> CandidateCell:
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


def test_entity_average_executes_in_requested_money_unit() -> None:
    cells = [_cell("AAA", 3_000), _cell("BBB", 6_000), _cell("CCC", 9_000)]

    result = answer_entity_average(
        "Giá trị trung bình thuế và các khoản phải nộp Nhà nước của AAA, BBB "
        "và CCC năm 2024 là bao nhiêu tỷ đồng?",
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
    assert "/ 3" in result.query


def test_entity_average_executes_absolute_share_counts() -> None:
    cells = [
        replace(
            _cell("AAA", 300_000_000, "Cổ phiếu phổ thông đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
        replace(
            _cell("BBB", 500_000_000, "Số lượng cổ phiếu phổ thông đang lưu hành"),
            unit=Unit(SHARES, 0),
        ),
    ]

    result = answer_entity_average(
        "Trung bình số lượng cổ phiếu phổ thông đang lưu hành của AAA và BBB "
        "năm 2024 là bao nhiêu triệu cổ phiếu?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(SHARES, 6),
        selector=Selector(),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(400.0)


def test_entity_average_abstains_when_reviewed_metric_is_unbound() -> None:
    cells = [_cell("AAA", 3_000), _cell("BBB", 6_000, "Doanh thu thuần")]

    result = answer_entity_average(
        "Giá trị trung bình thuế và các khoản phải nộp Nhà nước của AAA và BBB "
        "năm 2024 là bao nhiêu tỷ đồng?",
        cells,
        _frames(cells),
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=Unit(MONEY, 9, "VND"),
        selector=Selector(),
    )

    assert result is not None
    assert result.reason == "ENTITY_AVERAGE_UNBOUND:BBB"


@pytest.mark.parametrize(
    "question, unit",
    [
        (
            "Chênh lệch thu nhập bình quân giữa AAA và BBB năm 2024 là bao nhiêu tỷ đồng?",
            Unit(MONEY, 9, "VND"),
        ),
        (
            "Tỷ lệ lợi nhuận trung bình của AAA và BBB năm 2024 là bao nhiêu phần trăm?",
            Unit(PERCENT),
        ),
        (
            (
                "Trong các công ty AAA và BBB có doanh thu dương, chi phí trung bình "
                "năm 2024 là bao nhiêu tỷ đồng?"
            ),
            Unit(MONEY, 9, "VND"),
        ),
        (
            (
                "Giá trị trung bình chi phí lãi vay của AAA và BBB năm 2024 "
                "là bao nhiêu tỷ đồng?"
            ),
            Unit(MONEY, 9, "VND"),
        ),
    ],
)
def test_entity_average_rejects_ambiguous_or_derived_contracts(
    question: str,
    unit: Unit,
) -> None:
    result = answer_entity_average(
        question,
        [],
        {},
        entities=["AAA", "BBB"],
        years=[2024],
        basis="consolidated",
        requested_unit=unit,
        selector=Selector(),
    )

    assert result is None
