from __future__ import annotations

from decimal import Decimal

import pytest

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.application.usecases.semantic_v4 import SemanticV4Config, SemanticV4Engine
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.execution import PandasSandboxReplay
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.semantic import LegacyVietnameseAnnotator


class _FactRetriever:
    def __init__(
        self,
        values: dict[tuple[str, str, str], Decimal],
    ) -> None:
        self.values = values

    def retrieve(self, request) -> CandidateBatch:
        key = (request.metric_id, request.entity or "", request.period or "")
        value = self.values.get(key)
        if value is None:
            return CandidateBatch(
                request.request_id,
                (),
                {"reason": "SYNTHETIC_FACT_MISSING", "key": list(key)},
            )
        unit = (
            UnitSpec(Dimension.MONEY, 6, "VND")
            if request.expected_unit.dimension == Dimension.MONEY
            else request.expected_unit
        )
        candidate = ObservationCandidate(
            observation_uid="obs:" + ":".join(key),
            table_uid=f"table:{key[1]}:{key[2]}",
            logical_table_uid=f"logical:{key[1]}:{key[2]}",
            document_id=f"{key[1]}-{key[2]}",
            entity=key[1],
            basis=Basis.CONSOLIDATED,
            statement_type=request.statement_types[0] if request.statement_types else None,
            metric_id=request.metric_id,
            row_path=request.metric_id,
            row_hierarchy=(request.metric_id,),
            column_path=key[2],
            column_hierarchy=(key[2],),
            period=f"{key[2]}-12-31",
            period_role="current",
            value=value,
            value_raw=str(value),
            unit=unit,
            is_restated=False,
            score=30.0,
            score_reasons=("synthetic_exact",),
            grid_row=1,
            grid_column=1,
            row_uid="row:" + request.metric_id,
            column_uid="column:" + key[2],
        )
        return CandidateBatch(request.request_id, (candidate,), {"synthetic": True})


def _answer(
    question: str,
    values: dict[tuple[str, str, str], Decimal],
):
    aliases = {
        "VCB": "Ngân hàng TMCP Ngoại thương Việt Nam",
        "BID": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
        "CTG": "Ngân hàng TMCP Công thương Việt Nam",
        "DCM": "CTCP Phân bón Dầu khí Cà Mau",
        "DPM": "Tổng CTCP Phân bón và Hóa chất Dầu khí",
        "PRT": "PRT",
    }
    engine = SemanticV4Engine(
        SemanticParser(
            load_ontology(),
            LegacyVietnameseAnnotator(aliases),
        ),
        _FactRetriever(values),
        PandasSandboxReplay(),
        config=SemanticV4Config(minimum_confidence=0.0),
    )
    return engine.answer(question)


@pytest.mark.parametrize(
    ("question", "values", "expected"),
    [
        (
            "Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?",
            {("total_assets", "VCB", "2024"): Decimal(1_250_000)},
            Decimal(1250),
        ),
        (
            "Biên lợi nhuận ròng VCB năm 2024 là bao nhiêu phần trăm?",
            {
                ("profit_after_tax", "VCB", "2024"): Decimal(20),
                ("net_revenue", "VCB", "2024"): Decimal(100),
            },
            Decimal(20),
        ),
        (
            (
                "Lợi nhuận sau thuế bình quân của VCB và BID năm 2024 "
                "là bao nhiêu tỷ đồng?"
            ),
            {
                ("profit_after_tax", "VCB", "2024"): Decimal(100),
                ("profit_after_tax", "BID", "2024"): Decimal(300),
            },
            Decimal("0.2"),
        ),
        (
            (
                "Lợi nhuận sau thuế của VCB tăng bao nhiêu phần trăm "
                "từ năm 2023 đến năm 2024?"
            ),
            {
                ("profit_after_tax", "VCB", "2023"): Decimal(100),
                ("profit_after_tax", "VCB", "2024"): Decimal(125),
            },
            Decimal(25),
        ),
        (
            (
                "Trong nhóm VCB, BID và CTG năm 2024, công ty có tổng tài sản "
                "lớn nhất có lợi nhuận sau thuế bao nhiêu tỷ đồng?"
            ),
            {
                ("total_assets", "VCB", "2024"): Decimal(1000),
                ("total_assets", "BID", "2024"): Decimal(2000),
                ("total_assets", "CTG", "2024"): Decimal(1500),
                ("profit_after_tax", "VCB", "2024"): Decimal(100),
                ("profit_after_tax", "BID", "2024"): Decimal(250),
                ("profit_after_tax", "CTG", "2024"): Decimal(180),
            },
            Decimal("0.25"),
        ),
        (
            (
                "Trong ba mã cổ phiếu DCM, DPM và PRT, với các công ty có lưu "
                "chuyển tiền thuần từ hoạt động kinh doanh dương trong cả năm "
                "2019 và 2020, bình quân tỷ lệ tăng trưởng doanh thu thuần từ "
                "năm 2019 đến 2020 là bao nhiêu %?"
            ),
            {
                ("cash_flow_from_operations", "DCM", "2019"): Decimal(10),
                ("cash_flow_from_operations", "DCM", "2020"): Decimal(12),
                ("cash_flow_from_operations", "DPM", "2019"): Decimal(8),
                ("cash_flow_from_operations", "DPM", "2020"): Decimal(-1),
                ("cash_flow_from_operations", "PRT", "2019"): Decimal(5),
                ("cash_flow_from_operations", "PRT", "2020"): Decimal(6),
                ("net_revenue", "DCM", "2019"): Decimal(100),
                ("net_revenue", "DCM", "2020"): Decimal(120),
                ("net_revenue", "DPM", "2019"): Decimal(100),
                ("net_revenue", "DPM", "2020"): Decimal(200),
                ("net_revenue", "PRT", "2019"): Decimal(200),
                ("net_revenue", "PRT", "2020"): Decimal(220),
            },
            Decimal(15),
        ),
        (
            (
                "Trong nhóm DCM, DPM và PRT, xét các công ty có tăng trưởng "
                "doanh thu thuần dương từ 2019 đến 2020, thay đổi biên lợi "
                "nhuận gộp bình quân là bao nhiêu điểm phần trăm?"
            ),
            {
                ("net_revenue", "DCM", "2019"): Decimal(100),
                ("net_revenue", "DCM", "2020"): Decimal(110),
                ("net_revenue", "DPM", "2019"): Decimal(100),
                ("net_revenue", "DPM", "2020"): Decimal(90),
                ("net_revenue", "PRT", "2019"): Decimal(200),
                ("net_revenue", "PRT", "2020"): Decimal(220),
                ("gross_profit", "DCM", "2019"): Decimal(20),
                ("gross_profit", "DCM", "2020"): Decimal(33),
                ("gross_profit", "DPM", "2019"): Decimal(20),
                ("gross_profit", "DPM", "2020"): Decimal(27),
                ("gross_profit", "PRT", "2019"): Decimal(50),
                ("gross_profit", "PRT", "2020"): Decimal(55),
            },
            Decimal(5),
        ),
    ],
)
def test_v4_synthetic_operation_families(
    question: str,
    values: dict[tuple[str, str, str], Decimal],
    expected: Decimal,
) -> None:
    result = _answer(question, values)

    assert result.ok, (result.stage_failed, result.reason, result.failure_counts)
    assert result.answer == expected
    assert result.evidence
    assert result.query
