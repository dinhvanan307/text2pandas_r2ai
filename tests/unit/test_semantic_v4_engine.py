from __future__ import annotations

from decimal import Decimal

from text2pandas.application.parsing import OperationKind, QuestionAnnotations, SemanticParser
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.application.usecases.semantic_v4 import SemanticV4Config, SemanticV4Engine
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.execution import PandasSandboxReplay
from text2pandas.infrastructure.ontology import load_ontology


class _FormulaAnnotator:
    def annotate(self, question: str) -> QuestionAnnotations:
        return QuestionAnnotations(
            entities=("VCB",),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            requested_unit=UnitSpec(Dimension.PERCENT),
            operation=OperationKind.DIVIDE,
            mode="single",
        )


class _FormulaRetriever:
    def __init__(self, *, ambiguous: bool = False, collision: bool = False) -> None:
        self.ambiguous = ambiguous
        self.collision = collision

    def retrieve(self, request) -> CandidateBatch:
        values = {"profit_after_tax": Decimal(20), "net_revenue": Decimal(100)}
        first = self._candidate(request, "a", values[request.metric_id], 10.0)
        candidates = [first]
        if self.ambiguous:
            second_value = Decimal(40) if request.metric_id == "profit_after_tax" else Decimal(100)
            candidates.append(self._candidate(request, "b", second_value, 10.0))
        return CandidateBatch(request.request_id, tuple(candidates), {"fixture": True})

    def _candidate(self, request, document: str, value: Decimal, score: float):
        return ObservationCandidate(
            observation_uid=f"obs:{document}:{request.metric_id}",
            table_uid=f"table:{document}",
            document_id=f"VCB-2024-{document}",
            entity="VCB",
            basis=Basis.CONSOLIDATED,
            statement_type="income_statement",
            metric_id=request.metric_id,
            row_path=request.metric_id,
            column_path="2024",
            period="2024-12-31",
            period_role="current",
            value=value,
            value_raw=str(value),
            unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            is_restated=False,
            score=score,
            score_reasons=("fixture",),
            grid_row=1,
            grid_column=1,
            row_uid=f"row:{document}:{request.metric_id}",
            column_uid=f"column:{document}",
            readiness="recoverable" if self.collision else "ready",
            collision_class="missing_row_parent" if self.collision else None,
            source_confidence=0.9 if self.collision else 1.0,
        )


def _engine(retriever: _FormulaRetriever) -> SemanticV4Engine:
    return SemanticV4Engine(
        SemanticParser(load_ontology(), _FormulaAnnotator()),
        retriever,
        PandasSandboxReplay(),
        config=SemanticV4Config(minimum_confidence=0.0),
    )


def test_v4_engine_executes_verified_program_and_emits_evidence_first_tables() -> None:
    result = _engine(_FormulaRetriever()).answer(
        "Biên lợi nhuận ròng VCB năm 2024?",
        qid=7,
    )

    assert result.ok
    assert result.answer == Decimal(20)
    assert result.relevant_tables[0] == "table:a"
    assert result.evidence[0]["observation_uids"] == [
        "obs:a:net_revenue",
        "obs:a:profit_after_tax",
    ]
    assert result.confidence is not None
    assert result.confidence_status == "UNCALIBRATED_NO_SEALED_GOLD"
    assert result.to_dict()["semantic_schema_version"] == 4


def test_v4_engine_abstains_when_equally_supported_programs_disagree() -> None:
    result = _engine(_FormulaRetriever(ambiguous=True)).answer(
        "Biên lợi nhuận ròng VCB năm 2024?"
    )

    assert not result.ok
    assert result.reason == "ANSWER_DISAGREEMENT"
    assert result.successful_candidates == 2
    assert result.candidate_tables == ("table:a", "table:b")


def test_v4_engine_strict_policy_rejects_any_verified_answer_disagreement() -> None:
    engine = SemanticV4Engine(
        SemanticParser(load_ontology(), _FormulaAnnotator()),
        _FormulaRetriever(ambiguous=True),
        PandasSandboxReplay(),
        config=SemanticV4Config(
            max_binding_candidates=3,
            minimum_confidence=0.0,
            require_answer_consensus=True,
        ),
    )

    result = engine.answer("Biên lợi nhuận ròng VCB năm 2024?")

    assert not result.ok
    assert result.reason == "SEMANTIC_CANDIDATE_DISAGREEMENT"
    assert result.successful_candidates == 2


def test_v4_engine_does_not_use_recoverable_collision_without_verifier_policy() -> None:
    result = _engine(_FormulaRetriever(collision=True)).answer(
        "Biên lợi nhuận ròng VCB năm 2024?"
    )

    assert not result.ok
    assert result.reason == "NO_VERIFIED_PROGRAM"
    assert any(key.startswith("VERIFY:EVIDENCE_NOT_EXECUTION_READY") for key in result.failure_counts)
