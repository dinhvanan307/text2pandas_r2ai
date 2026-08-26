from __future__ import annotations

from decimal import Decimal

from text2pandas.application.parsing import OperationKind, QuestionAnnotations, SemanticParser
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.application.usecases.semantic_v3 import SemanticV3Engine, classify_differential
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.execution import PandasSandboxReplay
from text2pandas.infrastructure.ontology import load_ontology


class StaticAnnotator:
    def annotate(self, question):
        return QuestionAnnotations(
            entities=("VCB",),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            requested_unit=UnitSpec(Dimension.PERCENT),
            operation=OperationKind.DIVIDE,
            mode="single",
        )


class FormulaRetriever:
    def retrieve(self, request):
        values = {"profit_after_tax": Decimal(20), "net_revenue": Decimal(100)}
        candidate = ObservationCandidate(
            observation_uid=f"obs:{request.metric_id}",
            table_uid="table:income",
            document_id="VCB-2024",
            entity="VCB",
            basis=Basis.CONSOLIDATED,
            statement_type="income_statement",
            metric_id=request.metric_id,
            row_path=request.metric_id,
            column_path="2024",
            period="2024-12-31",
            period_role="current",
            value=values[request.metric_id],
            value_raw=str(values[request.metric_id]),
            unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            is_restated=False,
            score=10.0,
            score_reasons=("fixture",),
            grid_row=1,
            grid_column=1,
        )
        return CandidateBatch(request.request_id, (candidate,), {"fixture": True})


def test_engine_runs_parse_to_replay_and_derives_exact_evidence() -> None:
    parser = SemanticParser(load_ontology(), StaticAnnotator())
    engine = SemanticV3Engine(parser, FormulaRetriever(), PandasSandboxReplay())

    result = engine.answer("Biên lợi nhuận ròng VCB năm 2024?", qid=7)

    assert result.ok and result.answer == Decimal(20)
    assert result.relevant_tables == ("table:income",)
    assert result.relevant_documents == ("VCB-2024",)
    assert result.plan_fingerprint and result.ontology_fingerprint
    assert classify_differential({"status": "OK", "answer": 20.0}, result) == "BOTH_OK_MATCH"

