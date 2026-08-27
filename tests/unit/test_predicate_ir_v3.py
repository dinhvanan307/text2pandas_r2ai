from __future__ import annotations

from decimal import Decimal

import pandas as pd

from text2pandas.application.binding import JointBinder
from text2pandas.application.execution import TypedExecutor, compile_pandas
from text2pandas.application.planning import compile_execution_plan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Axis,
    Basis,
    Comparison,
    ComparisonOperator,
    Dimension,
    Filter,
    Literal,
    MetricRef,
    OutputSpec,
    PredicateQuantifier,
    QuantifiedPredicate,
    QuestionAST,
    Rank,
    RankDirection,
    ResultKind,
    SelectAtArg,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.sandbox.query import execute_query

MONEY = UnitSpec(Dimension.MONEY, 6, "VND")


def _candidate(request, value: int) -> ObservationCandidate:
    return ObservationCandidate(
        observation_uid=f"obs:{request.metric_id}:{request.entity}:{request.period}",
        table_uid=f"table:{request.entity}:{request.period}",
        document_id=f"doc:{request.entity}:{request.period}",
        entity=request.entity,
        basis=Basis.CONSOLIDATED,
        statement_type="fixture",
        metric_id=request.metric_id,
        row_path=request.metric_id,
        column_path=request.period or "",
        period=f"{request.period}-12-31" if request.period else None,
        period_role="current",
        value=Decimal(value),
        value_raw=str(value),
        unit=MONEY,
        is_restated=False,
        score=10.0,
        score_reasons=("fixture",),
        grid_row=1,
        grid_column=1,
    )


def _bind(ast: QuestionAST, values: dict[tuple[str, str, str], int]):
    plan = compile_execution_plan(ast, load_ontology())
    batches = {
        request.request_id: CandidateBatch(
            request.request_id,
            (_candidate(request, values[(request.metric_id, request.entity, request.period)]),),
            {},
        )
        for request in plan.requests
    }
    result = JointBinder().bind(plan, batches)
    assert result.ok
    return result.bound_plan


def _frames(bound, compiled):
    output = {}
    for evidence in compiled.program.evidence:
        rows = [
            operand.candidate
            for operand in bound.operands.values()
            if operand.candidate.table_uid == evidence.table_uid
        ]
        output[evidence.variable] = pd.DataFrame(
            {
                "observation_uid": [row.observation_uid for row in rows],
                "value": [float(row.value) for row in rows],
            }
        )
    return output


def test_quantified_multi_entity_filter_requires_positive_value_in_every_period() -> None:
    entities = ("AAA", "BBB", "CCC")
    periods = ("2022", "2023", "2024")
    cash_flow = MetricRef(
        "cash_flow_from_operations",
        entities,
        periods,
        Basis.CONSOLIDATED,
        expected_unit=MONEY,
    )
    revenue = MetricRef(
        "net_revenue", entities, ("2024",), Basis.CONSOLIDATED, expected_unit=MONEY
    )
    predicate = QuantifiedPredicate(
        Axis.PERIOD,
        PredicateQuantifier.ALL,
        Comparison(ComparisonOperator.GT, cash_flow, Literal(0, MONEY)),
    )
    expression = Aggregate(
        AggregateFunction.SUM,
        Axis.ENTITY,
        Filter(Axis.ENTITY, entities, predicate, revenue),
        entities,
    )
    ast = QuestionAST(
        expression,
        OutputSpec(ResultKind.SCALAR, MONEY),
        "Tổng doanh thu 2024 của công ty có CFO dương trong cả ba năm?",
    )
    assert QuestionAST.from_dict(ast.to_dict()) == ast
    values = {
        ("cash_flow_from_operations", entity, period): value
        for entity, series in {
            "AAA": (1, 2, 3),
            "BBB": (1, -1, 3),
            "CCC": (2, 2, 2),
        }.items()
        for period, value in zip(periods, series, strict=True)
    }
    values.update(
        {
            ("net_revenue", "AAA", "2024"): 10,
            ("net_revenue", "BBB", "2024"): 20,
            ("net_revenue", "CCC", "2024"): 30,
        }
    )
    bound = _bind(ast, values)

    typed = TypedExecutor().execute(bound)
    compiled = compile_pandas(bound)

    assert typed.ok and typed.answer == Decimal(40)
    assert compiled.ok
    assert execute_query(compiled.program.query, _frames(bound, compiled)) == 40.0


def test_median_filtered_cohort_can_feed_rank_then_select_at_arg() -> None:
    entities = ("AAA", "BBB", "CCC")
    assets = MetricRef(
        "total_assets", entities, ("2024",), Basis.CONSOLIDATED, expected_unit=MONEY
    )
    profit = MetricRef(
        "profit_after_tax", entities, ("2024",), Basis.CONSOLIDATED, expected_unit=MONEY
    )
    revenue = MetricRef(
        "net_revenue", entities, ("2024",), Basis.CONSOLIDATED, expected_unit=MONEY
    )
    above_median = Comparison(
        ComparisonOperator.GT,
        assets,
        Aggregate(AggregateFunction.MEDIAN, Axis.ENTITY, assets, entities),
    )
    expression = SelectAtArg(
        Rank(
            Axis.ENTITY,
            entities,
            Filter(Axis.ENTITY, entities, above_median, profit),
            RankDirection.DESCENDING,
        ),
        revenue,
    )
    ast = QuestionAST(
        expression,
        OutputSpec(ResultKind.SCALAR, MONEY),
        "Doanh thu của công ty có lợi nhuận cao nhất trong nhóm tài sản trên trung vị?",
    )
    values = {
        ("total_assets", "AAA", "2024"): 100,
        ("total_assets", "BBB", "2024"): 200,
        ("total_assets", "CCC", "2024"): 300,
        ("profit_after_tax", "AAA", "2024"): 40,
        ("profit_after_tax", "BBB", "2024"): 50,
        ("profit_after_tax", "CCC", "2024"): 30,
        ("net_revenue", "AAA", "2024"): 10,
        ("net_revenue", "BBB", "2024"): 20,
        ("net_revenue", "CCC", "2024"): 30,
    }
    bound = _bind(ast, values)

    typed = TypedExecutor().execute(bound)
    compiled = compile_pandas(bound)

    assert typed.ok and typed.answer == Decimal(30)
    assert compiled.ok
    assert execute_query(compiled.program.query, _frames(bound, compiled)) == 30.0
