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
from text2pandas.domain.semantic import (
    Aggregate,
    Basis,
    Dimension,
    FormulaCall,
    MetricBindingHint,
    MetricRef,
    OutputSpec,
    QuestionAST,
    ResultKind,
    UnitSpec,
)
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
    basis: Basis = Basis.CONSOLIDATED,
    period: str | None = "2024-12-31",
):
    return ObservationCandidate(
        observation_uid=uid,
        table_uid=f"table:{uid}",
        document_id=document,
        entity=request.entity or "?",
        basis=basis,
        statement_type="income_statement",
        metric_id=request.metric_id,
        row_path=request.metric_id,
        column_path="2024",
        period=period,
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
        constraint
        for constraint in plan.constraints
        if constraint.kind == ConstraintKind.SAME_DOCUMENT
    ]
    assert len(same_document) == 2
    assert all(len(constraint.request_ids) == 2 for constraint in same_document)
    same_period = [
        constraint
        for constraint in plan.constraints
        if constraint.kind == ConstraintKind.SAME_PERIOD
    ]
    assert len(same_period) == 2
    assert all(len(constraint.request_ids) == 2 for constraint in same_period)
    assert any(constraint.kind == ConstraintKind.SAME_BASIS for constraint in plan.constraints)
    assert any(constraint.kind == ConstraintKind.SAME_DIMENSION for constraint in plan.constraints)
    assert len(plan.fingerprint) == 64


def test_planner_preserves_source_binding_without_promoting_ontology() -> None:
    binding = MetricBindingHint(
        source_metric_id="source:penalty",
        source_build_id="a6-build",
        labels=("Chi phí phạt",),
        row_paths=("Chi phí khác › Chi phí phạt",),
        preferred_basis=Basis.SEPARATE,
    )
    ast = QuestionAST(
        question="Chi phí phạt?",
        expression=MetricRef(
            "source:penalty",
            entities=("SCR",),
            periods=("2017",),
            basis=Basis.SEPARATE,
            statement_types=("note",),
            expected_unit=UnitSpec(Dimension.MONEY),
            source_binding=binding,
        ),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.MONEY)),
    )

    plan = compile_execution_plan(ast, load_ontology())

    assert len(plan.requests) == 1
    assert plan.requests[0].metric_id == "source:penalty"
    assert plan.requests[0].source_binding == binding
    assert "source:penalty" not in load_ontology().metrics


def test_planner_honors_formula_that_explicitly_allows_cross_period_operands() -> None:
    plan = _formula_plan()
    assert isinstance(plan.ast.expression, Aggregate)
    assert isinstance(plan.ast.expression.expression, FormulaCall)
    relaxed_formula = replace(plan.ast.expression.expression, same_period=False)
    relaxed_ast = replace(
        plan.ast,
        expression=replace(plan.ast.expression, expression=relaxed_formula),
    )

    relaxed = compile_execution_plan(relaxed_ast, load_ontology())

    assert not any(
        constraint.kind == ConstraintKind.SAME_PERIOD for constraint in relaxed.constraints
    )


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


def test_joint_binder_enforces_reviewed_formula_same_period() -> None:
    plan = _formula_plan()
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
                _candidate(
                    left,
                    "left-wrong-period",
                    "doc-shared",
                    10.0,
                    period="2024-06-30",
                ),
                _candidate(left, "left-closing", "doc-shared", 9.0),
            ),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (_candidate(right, "right-closing", "doc-shared", 10.0),),
            {},
        ),
    }

    result = JointBinder().bind(scoped_plan, batches)

    assert result.ok
    selected = {
        operand.candidate.observation_uid for operand in result.bound_plan.operands.values()
    }
    assert selected == {"left-closing", "right-closing"}
    assert result.bound_plan.total_score == 19.0


def test_joint_binder_rejects_unknown_period_for_same_period_formula() -> None:
    plan = _formula_plan()
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
            (_candidate(left, "left-unknown", "doc-shared", 10.0, period=None),),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (_candidate(right, "right-unknown", "doc-shared", 10.0, period=None),),
            {},
        ),
    }

    result = JointBinder().bind(scoped_plan, batches)

    assert not result.ok
    assert result.reason == "NO_COHERENT_ASSIGNMENT"


def test_joint_binder_fails_closed_when_any_operand_has_no_candidates() -> None:
    plan = _formula_plan()
    batches = {
        request.request_id: CandidateBatch(request.request_id, (), {}) for request in plan.requests
    }

    result = JointBinder().bind(plan, batches)

    assert not result.ok
    assert result.reason.startswith("CANDIDATE_EMPTY:")


def test_joint_binder_prefers_coherent_basis_over_incompatible_local_top1s() -> None:
    ontology = load_ontology()
    annotations = QuestionAnnotations(
        entities=("VCB", "BID"),
        periods=("2024",),
        basis=Basis.UNSPECIFIED,
        requested_unit=UnitSpec(Dimension.MONEY, 9, "VND"),
        operation=OperationKind.AVERAGE,
        mode="screen",
    )
    parsed = SemanticParser(ontology, StaticAnnotator(annotations)).parse(
        "Tổng tài sản bình quân của VCB và BID năm 2024?"
    )
    assert parsed.ok
    plan = compile_execution_plan(parsed.ast, ontology)
    left, right = plan.requests
    batches = {
        left.request_id: CandidateBatch(
            left.request_id,
            (
                _candidate(left, "left-local", "doc-left", 10.0, basis=Basis.CONSOLIDATED),
                _candidate(left, "left-coherent", "doc-left-2", 8.5, basis=Basis.SEPARATE),
            ),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (
                _candidate(right, "right-local", "doc-right", 10.0, basis=Basis.SEPARATE),
                _candidate(
                    right,
                    "right-coherent",
                    "doc-right-2",
                    9.0,
                    basis=Basis.CONSOLIDATED,
                ),
            ),
            {},
        ),
    }

    result = JointBinder().bind(plan, batches)

    assert result.ok
    assert len({operand.candidate.basis for operand in result.bound_plan.operands.values()}) == 1
    assert result.bound_plan.total_score == 19.0


def test_joint_binder_abstains_on_equal_score_semantically_different_assignments() -> None:
    plan = _formula_plan()
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
                _candidate(left, "left-a", "doc-a", 10.0),
                _candidate(left, "left-b", "doc-b", 10.0),
            ),
            {},
        ),
        right.request_id: CandidateBatch(
            right.request_id,
            (
                _candidate(right, "right-a", "doc-a", 10.0),
                replace(
                    _candidate(right, "right-b", "doc-b", 10.0),
                    value=Decimal(200),
                ),
            ),
            {},
        ),
    }

    result = JointBinder().bind(scoped_plan, batches)

    assert not result.ok
    assert result.reason == "BINDING_TIE"
    assert result.trace[0]["tied_assignments"] == 2
