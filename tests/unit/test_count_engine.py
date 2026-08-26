from __future__ import annotations

import pandas as pd
import pytest

from text2pandas.pipelines.answering.binding import CandidateCell, Selector
from text2pandas.pipelines.answering.count_engine import answer_count_periods
from text2pandas.pipelines.answering.units import MONEY, Unit


def _cells(values: dict[int, float], label: str = "Quỹ khen thưởng, phúc lợi"):
    cells = [
        CandidateCell(
            df_var="df1",
            csv_path="data/table.csv",
            row_index=index,
            row_path=label,
            col_label=f"Năm {year} Tỷ đồng",
            value_raw=str(value),
            value=value,
            parsed_raw=value,
            storage_exponent=0,
            unit=Unit(MONEY, 9, "VND"),
            period=f"{year}-12-31",
            table_uid="table-1",
            document_id=f"report-{year}",
            entity="HSG",
            basis="consolidated",
        )
        for index, (year, value) in enumerate(values.items())
    ]
    frame = pd.DataFrame(
        [
            {"row_path": cell.row_path, "col_label": cell.col_label, "value": cell.value}
            for cell in cells
        ]
    )
    return cells, {"df1": frame}


def test_count_periods_executes_reviewed_money_threshold() -> None:
    cells, frames = _cells({2019: 50, 2021: 30, 2024: 41, 2025: 0})

    result = answer_count_periods(
        "HSG có bao nhiêu năm ghi nhận quỹ khen thưởng nhiều hơn 40 tỷ đồng?",
        cells,
        frames,
        entity="HSG",
        years=[2019, 2021, 2024, 2025],
        basis="consolidated",
        selector=Selector(),
        qid=823,
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(2.0)
    assert result.query.count("> 40.0") == 4


def test_reviewed_count_metric_rejects_lexically_similar_wrong_leaf() -> None:
    correct, frames = _cells({2019: 4}, label="Trích lập từ lợi nhuận chưa phân phối")
    wrong = CandidateCell(
        **{
            **correct[0].__dict__,
            "row_index": 1,
            "row_path": "Quỹ khen thưởng › Trích lập dự phòng trong năm",
            "value": 100,
            "parsed_raw": 100,
        }
    )
    frames["df1"] = pd.concat(
        [
            frames["df1"],
            pd.DataFrame(
                [{"row_path": wrong.row_path, "col_label": wrong.col_label, "value": wrong.value}]
            ),
        ],
        ignore_index=True,
    )

    result = answer_count_periods(
        "Có bao nhiêu năm số tiền trích lập quỹ khen thưởng nhiều hơn 3 tỷ đồng?",
        [wrong, *correct],
        frames,
        entity="HSG",
        years=[2019],
        basis="consolidated",
        selector=Selector(),
    )

    assert result is not None and result.ok
    assert "Trích lập từ lợi nhuận chưa phân phối" in result.query
    assert "dự phòng" not in result.query


def test_count_periods_supports_negative_predicate() -> None:
    cells, frames = _cells(
        {2022: -1, 2023: 0, 2024: -2},
        label="Lưu chuyển tiền ròng từ hoạt động đầu tư",
    )

    result = answer_count_periods(
        "SAB có số năm lưu chuyển tiền ròng từ hoạt động đầu tư âm là bao nhiêu?",
        cells,
        frames,
        entity="HSG",
        years=[2022, 2023, 2024],
        basis="consolidated",
        selector=Selector(),
    )

    assert result is not None and result.ok
    assert result.answer == pytest.approx(2.0)


def test_count_existence_abstains_without_negative_evidence_contract() -> None:
    result = answer_count_periods(
        "Số năm tồn tại khoản mục doanh thu chưa thực hiện là bao nhiêu?",
        [],
        {},
        entity="VSF",
        years=[2018, 2019],
        basis="consolidated",
        selector=Selector(),
    )

    assert result is not None
    assert result.reason == "COUNT_EXISTENCE_REQUIRES_NEGATIVE_EVIDENCE"
