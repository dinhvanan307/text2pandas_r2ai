from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from text2pandas.application.binding import JointBinder
from text2pandas.application.parsing import (
    OperationKind,
    QuestionAnnotations,
    SemanticParser,
)
from text2pandas.application.planning import ConstraintKind, compile_execution_plan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.semantic import Basis, Dimension, UnitSpec
from text2pandas.infrastructure.ontology import load_ontology


class StaticAnnotator:
    def __init__(self, annotations: QuestionAnnotations):
        self.annotations = annotations

    def annotate(self, question: str) -> QuestionAnnotations:
        return self.annotations


def _formula_plan():
    annotations = QuestionAnnotations(
        entities=("VCB", "BID"),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.PERCENT),
        operation=OperationKind.AVERAGE,
        mode="screen",
    )
    ontology = load_ontology()
    parsed = SemanticParser(ontology, StaticAnnotator(annotations)).parse(
        "Biên lợi nhuận ròng bình quân của VCB và BID năm 2024?"
    )
    assert parsed.ok
    return compile_execution_plan(parsed.ast, ontology)


def _candidate(
    request,
    uid: str,
    document: str,
    score: float,
    *,
    currency: str = "VND",
):
    return ObservationCandidate(
        observation_uid=uid,
        table_uid=f"table:{uid}",
        document_id=document,
        entity=request.entity or "?",
        basis=Basis.CONSOLIDATED,
        statement_type="income_statement",
        metric_id=request.metric_id,
        row_path=request.metric_id,
        column_path="2024",
        period=request.period,
        period_role="current",
        value=Decimal(100),
        value_raw="100",
        unit=UnitSpec(Dimension.MONEY, 6, currency),
        is_restated=False,
        score=score,
        score_reasons=("fixture",),
        grid_row=1,
        grid_column=1,
    )


def test_planner_expands_formula_per_entity_and_scopes_coherence() -> None:
    plan = _formula_plan()

    assert len(plan.requests) == 4
    same_document = [
        constraint for constraint in plan.constraints if constraint.kind == ConstraintKind.SAME_DOCUMENT
    ]
    assert len(same_document) == 2
    assert all(len(constraint.request_ids) == 2 for constraint in same_document)
    assert len(plan.fingerprint) == 64


def test_joint_binder_finds_coherent_assignment_greedy_selection_misses() -> None:
    plan = _formula_plan()
    # Restrict to one entity's reviewed formula to make the expected global
    # choice explicit: each local top-1 is in a different report.
    entity = plan.requests[0].entity
    scoped_requests = tuple(request for request in plan.requests if request.entity == entity)
    scoped_ids = {request.request_id for request in scoped_requests}
    scoped_plan = replace(
        plan,
        requests=scoped_requests,
        constraints=tuple(
            constraint
            for constraint in plan.constraints
            if set(constraint.request_ids).issubset(scoped_ids)
        ),
    )
    left, right = scoped_requests
    batches = {
        left.request_id: CandidateBatch(
            left.request_id,
            (
                _candidate(left, "left-local", "doc-left", 10.0),
                _candidate(left, "left-coherent", "doc-shared", 8.0),
            ),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (
                _candidate(right, "right-local", "doc-right", 10.0),
                _candidate(right, "right-coherent", "doc-shared", 8.0),
            ),
            {},
        ),
    }

    result = JointBinder().bind(scoped_plan, batches)

    assert result.ok
    selected = {value.candidate.document_id for value in result.bound_plan.operands.values()}
    assert selected == {"doc-shared"}
    assert result.bound_plan.total_score == 16.0


def test_joint_binder_fails_closed_when_any_operand_has_no_candidates() -> None:
    plan = _formula_plan()
    batches = {
        request.request_id: CandidateBatch(request.request_id, (), {}) for request in plan.requests
    }

    result = JointBinder().bind(plan, batches)

    assert not result.ok
    assert result.reason.startswith("NO_CANDIDATES:")
