from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from text2pandas.application.binding import JointBinder
from text2pandas.application.execution import TypedExecutor
from text2pandas.application.parsing import OperationKind, QuestionAnnotations, SemanticParser
from text2pandas.application.planning import compile_execution_plan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.application.verification import ProgramVerifier, VerificationPolicy
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology


class _Annotator:
    def annotate(self, question: str) -> QuestionAnnotations:
        return QuestionAnnotations(
            entities=("VCB",),
            periods=("2024",),
            basis=Basis.CONSOLIDATED,
            requested_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
            operation=OperationKind.LOOKUP,
            mode="single",
        )


def _bound_candidate(**changes: object):
    ontology = load_ontology()
    parsed = SemanticParser(ontology, _Annotator()).parse("Tổng tài sản VCB năm 2024?")
    assert parsed.ast is not None
    plan = compile_execution_plan(parsed.ast, ontology)
    request = plan.requests[0]
    candidate = ObservationCandidate(
        observation_uid="obs-1",
        table_uid="table-1",
        document_id="VCB-2024",
        entity="VCB",
        basis=Basis.CONSOLIDATED,
        statement_type="balance_sheet",
        metric_id="total_assets",
        row_path="Tổng cộng tài sản",
        column_path="Cuối năm 2024",
        period="2024-12-31",
        period_role="closing",
        value=Decimal(1000),
        value_raw="1.000",
        unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        is_restated=False,
        score=30.0,
        score_reasons=("fixture",),
        grid_row=1,
        grid_column=1,
        row_uid="row-1",
        column_uid="column-1",
    )
    candidate = replace(candidate, **changes)
    binding = JointBinder().bind(
        plan,
        {request.request_id: CandidateBatch(request.request_id, (candidate,), {})},
    )
    assert binding.bound_plan is not None
    return binding.bound_plan


def test_verifier_accepts_consistent_ready_program() -> None:
    bound = _bound_candidate()
    typed = TypedExecutor().execute(bound)

    verified = ProgramVerifier().verify(bound, typed, 1000.0)

    assert verified.ok
    assert verified.score == 1.0


def test_verifier_rejects_scope_and_differential_mismatch() -> None:
    bound = _bound_candidate(entity="BID")
    typed = TypedExecutor().execute(bound)

    verified = ProgramVerifier().verify(bound, typed, 999.0)

    assert not verified.ok
    assert any(reason.startswith("ENTITY_SCOPE_MISMATCH:") for reason in verified.reasons)
    assert "TYPED_PANDAS_MISMATCH" in verified.reasons


def test_recoverable_collision_is_locked_by_default_and_policy_gated() -> None:
    bound = _bound_candidate(
        readiness="recoverable",
        collision_class="missing_row_parent",
        source_confidence=0.8,
    )
    typed = TypedExecutor().execute(bound)

    locked = ProgramVerifier().verify(bound, typed, 1000.0)
    enabled = ProgramVerifier(
        VerificationPolicy(allow_recoverable_collisions=True)
    ).verify(bound, typed, 1000.0)

    assert not locked.ok
    assert enabled.ok
    assert enabled.score < 1.0


def test_recoverable_collision_still_rejects_low_confidence() -> None:
    bound = _bound_candidate(
        readiness="recoverable",
        collision_class="missing_row_parent",
        source_confidence=0.5,
    )
    typed = TypedExecutor().execute(bound)

    verified = ProgramVerifier(
        VerificationPolicy(allow_recoverable_collisions=True)
    ).verify(bound, typed, 1000.0)

    assert not verified.ok
    assert any(reason.startswith("RECOVERABLE_CONFIDENCE_LOW:") for reason in verified.reasons)
