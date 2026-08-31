from __future__ import annotations

from decimal import Decimal

from text2pandas.application.binding import BoundExecutionPlan, BoundOperand
from text2pandas.application.planning import compile_execution_plan
from text2pandas.application.retrieval import ObservationCandidate
from text2pandas.application.verification import validate_family_completeness
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Basis,
    Dimension,
    MetricRef,
    ObservationColumnRole,
    ObservationRowRole,
    OutputSpec,
    QuestionAST,
    ResultKind,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology


def _candidate(request, uid: str) -> ObservationCandidate:
    return ObservationCandidate(
        observation_uid=uid,
        table_uid=f"table:{uid}",
        document_id=f"document:{request.entity}",
        entity=request.entity or "?",
        basis=Basis.CONSOLIDATED,
        statement_type="balance_sheet",
        metric_id=request.metric_id,
        row_path="Tổng cộng tài sản",
        column_path="Số cuối năm",
        period=f"{request.period}-12-31",
        period_role="closing",
        value=Decimal(100),
        value_raw="100",
        unit=UnitSpec(Dimension.MONEY, 6, "VND"),
        is_restated=False,
        score=10.0,
        score_reasons=("fixture",),
        grid_row=1,
        grid_column=1,
        row_uid=f"row:{uid}",
        column_uid=f"column:{uid}",
        scale_source="column_path",
        row_role=ObservationRowRole.TOTAL,
        column_role=ObservationColumnRole.CLOSING,
    )


def _bound(ast: QuestionAST, *, drop_last: bool = False, same_uid: bool = False):
    plan = compile_execution_plan(ast, load_ontology(), infer_observation_roles=True)
    requests = plan.requests[:-1] if drop_last else plan.requests
    operands = {
        request.request_id: BoundOperand(
            request,
            _candidate(request, "same" if same_uid else request.request_id),
        )
        for request in requests
    }
    return BoundExecutionPlan(plan, operands, 10.0, None)


def test_average_requires_the_complete_member_domain() -> None:
    metric = MetricRef(
        "total_assets",
        entities=("AAA", "BBB", "CCC"),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        expected_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
    )
    ast = QuestionAST(
        expression=Aggregate(
            AggregateFunction.AVERAGE,
            Axis.ENTITY,
            metric,
            ("AAA", "BBB", "CCC"),
        ),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.MONEY, 6, "VND")),
        question="Tài sản trung bình của AAA, BBB và CCC năm 2024?",
    )

    complete = validate_family_completeness(_bound(ast))
    incomplete = validate_family_completeness(_bound(ast, drop_last=True))

    assert complete.ok
    assert complete.family == "single_metric_average"
    assert complete.bound_members == ("AAA", "BBB", "CCC")
    assert "AGGREGATE_MEMBER_DOMAIN_INCOMPLETE" in incomplete.failures


def test_two_period_difference_requires_distinct_source_observations() -> None:
    left = MetricRef(
        "total_assets",
        entities=("AAA",),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        expected_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
    )
    right = MetricRef(
        "total_assets",
        entities=("AAA",),
        periods=("2023",),
        basis=Basis.CONSOLIDATED,
        expected_unit=UnitSpec(Dimension.MONEY, 6, "VND"),
    )
    ast = QuestionAST(
        expression=Arithmetic(ArithmeticOperator.SUBTRACT, left, right),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.MONEY, 6, "VND")),
        question="Tài sản AAA năm 2024 trừ năm 2023?",
    )

    result = validate_family_completeness(_bound(ast, same_uid=True))

    assert result.family == "two_period_difference"
    assert "DIFFERENCE_OBSERVATION_NOT_DISTINCT" in result.failures
