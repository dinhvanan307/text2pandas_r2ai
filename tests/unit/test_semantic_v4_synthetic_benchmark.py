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
