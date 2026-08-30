from dataclasses import replace
from decimal import Decimal

import pytest

from text2pandas.application.usecases.grounded_ast_compiler import (
    GroundedAstCompilationUnsupported,
    GroundedAstCompiler,
)
from text2pandas.application.usecases.grounded_synthesis import (
    GroundedFact,
    execute_grounded,
)
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
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
    RollingAverage,
    RollingGrowth,
    SelectAtArg,
    UnitSpec,
)


def _fact(
    metric: str,
    entity: str,
    year: int,
    value: str,
    *,
    scale: int = 0,
) -> GroundedFact:
    return GroundedFact(
        observation_uid=f"{metric}-{entity}-{year}",
        table_uid=f"table-{entity}-{year}",
        document_id=f"{entity}_financial_statements_{year}_consolidated",
        entity=entity,
        period=f"{year}-12-31",
        basis=Basis.CONSOLIDATED,
        row_path=metric,
        column_path=str(year),
        section_text="",
        value=Decimal(value),
        dimension=Dimension.MONEY,
        scale_exponent=scale,
        statement_type="income_statement",
        retrieval_metric=metric,
        score=100.0,
    )


def _ast(expression: object, unit: UnitSpec) -> QuestionAST:
    return QuestionAST(
        expression=expression,  # type: ignore[arg-type]
        output=OutputSpec(ResultKind.SCALAR, unit),
        question="synthetic",
    )


def _metric(
    metric: str,
    *,
    entities: tuple[str, ...],
    periods: tuple[str, ...],
) -> MetricRef:
    return MetricRef(metric, entities=entities, periods=periods)


def test_compiler_executes_direct_lookup_with_requested_scale() -> None:
    facts = (_fact("net_revenue", "AAA", 2024, "123", scale=6),)
    ast = _ast(
        _metric("net_revenue", entities=("AAA",), periods=("2024",)),
        UnitSpec(Dimension.MONEY, 6),
    )

    execution = execute_grounded(GroundedAstCompiler().compile(ast, facts), facts)

    assert execution.answer == 123.0


def test_compiler_rejects_fact_with_hard_logical_conflict() -> None:
    fact = replace(
        _fact("source_metric", "AAA", 2024, "123", scale=6),
        score_reasons=("metric:missing_source_alias_tokens:du,phong",),
    )
    ast = _ast(
        _metric("source_metric", entities=("AAA",), periods=("2024",)),
        UnitSpec(Dimension.MONEY, 6),
    )

    with pytest.raises(
        GroundedAstCompilationUnsupported,
        match="semantic AST has no facts",
    ):
        GroundedAstCompiler().compile(ast, (fact,))


def test_compiler_allows_qualified_roll_forward_with_misclassified_statement() -> None:
    fact = replace(
        _fact("source_provision_charge", "AAA", 2024, "123", scale=6),
        statement_type="equity_change",
        score_reasons=("metric:source_context_complete",),
    )
    reference = MetricRef(
        "source_provision_charge",
        entities=("AAA",),
        periods=("2024",),
        statement_types=("note",),
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(
            _ast(reference, UnitSpec(Dimension.MONEY, 6)),
            (fact,),
        ),
        (fact,),
    )

    assert execution.answer == 123.0


@pytest.mark.parametrize(
    ("operator", "unit", "expected"),
    [
        (ArithmeticOperator.SUBTRACT, UnitSpec(Dimension.MONEY, 0), 25.0),
        (ArithmeticOperator.GROWTH, UnitSpec(Dimension.PERCENT), 25.0),
    ],
)
def test_compiler_executes_two_period_arithmetic(
    operator: ArithmeticOperator,
    unit: UnitSpec,
    expected: float,
) -> None:
    facts = (
        _fact("net_revenue", "AAA", 2023, "100"),
        _fact("net_revenue", "AAA", 2024, "125"),
    )
    expression = Arithmetic(
        operator,
        _metric("net_revenue", entities=("AAA",), periods=("2024",)),
        _metric("net_revenue", entities=("AAA",), periods=("2023",)),
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(_ast(expression, unit), facts), facts
    )

    assert execution.answer == expected


def test_compiler_executes_ratio_over_opening_closing_average_balance() -> None:
    facts = (
        _fact("net_revenue", "AAA", 2024, "120"),
        _fact("total_assets", "AAA", 2023, "100"),
        _fact("total_assets", "AAA", 2024, "140"),
    )
    expression = Arithmetic(
        ArithmeticOperator.DIVIDE,
        _metric("net_revenue", entities=("AAA",), periods=("2024",)),
        RollingAverage(
            _metric("total_assets", entities=("AAA",), periods=("2023", "2024"))
        ),
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(
            _ast(expression, UnitSpec(Dimension.RATIO)),
            facts,
        ),
        facts,
    )

    assert execution.answer == 1.0


def test_compiler_ranks_consecutive_period_growth_not_revenue_level() -> None:
    periods = ("2020", "2021", "2022")
    facts = (
        _fact("net_revenue", "HPG", 2020, "100"),
        _fact("net_revenue", "HPG", 2021, "150"),
        _fact("net_revenue", "HPG", 2022, "180"),
    )
    expression = Aggregate(
        AggregateFunction.MAXIMUM,
        Axis.PERIOD,
        RollingGrowth(_metric("net_revenue", entities=("HPG",), periods=periods)),
        periods[1:],
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(
            _ast(expression, UnitSpec(Dimension.PERCENT)),
            facts,
        ),
        facts,
    )

    assert execution.answer == 50.0


def test_compiler_converts_ratio_change_to_percentage_points() -> None:
    facts = (
        _fact("gross_profit", "AAA", 2023, "10"),
        _fact("gross_profit", "AAA", 2024, "30"),
        _fact("net_revenue", "AAA", 2023, "100"),
        _fact("net_revenue", "AAA", 2024, "150"),
    )
    current_margin = Arithmetic(
        ArithmeticOperator.DIVIDE,
        _metric("gross_profit", entities=("AAA",), periods=("2024",)),
        _metric("net_revenue", entities=("AAA",), periods=("2024",)),
    )
    prior_margin = Arithmetic(
        ArithmeticOperator.DIVIDE,
        _metric("gross_profit", entities=("AAA",), periods=("2023",)),
        _metric("net_revenue", entities=("AAA",), periods=("2023",)),
    )
    expression = Arithmetic(
        ArithmeticOperator.SUBTRACT,
        current_margin,
        prior_margin,
    )

    program = GroundedAstCompiler().compile(
        _ast(expression, UnitSpec(Dimension.PERCENT_POINT)),
        facts,
    )
    execution = execute_grounded(program, facts)

    assert program.nodes[-1].operation.value == "to_percent"
    assert execution.answer == 10.0


def test_compiler_aggregates_one_metric_over_entity_axis() -> None:
    facts = (
        _fact("profit_after_tax", "AAA", 2024, "10"),
        _fact("profit_after_tax", "BBB", 2024, "30"),
    )
    expression = Aggregate(
        AggregateFunction.AVERAGE,
        Axis.ENTITY,
        _metric(
            "profit_after_tax",
            entities=("AAA", "BBB"),
            periods=("2024",),
        ),
        ("AAA", "BBB"),
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(_ast(expression, UnitSpec(Dimension.MONEY, 0)), facts),
        facts,
    )

    assert execution.answer == 20.0


def test_compiler_sums_physical_components_before_entity_aggregate() -> None:
    aaa_common = replace(
        _fact("source_provision", "AAA", 2024, "-10"),
        observation_uid="source-provision-AAA-2024-common",
        row_path="AFS › Dự phòng chung",
    )
    aaa_specific = replace(
        _fact("source_provision", "AAA", 2024, "-20"),
        observation_uid="source-provision-AAA-2024-specific",
        row_path="AFS › Dự phòng cụ thể",
    )
    bbb_total = _fact("source_provision", "BBB", 2024, "-40")
    facts = (aaa_common, aaa_specific, bbb_total)
    expression = Aggregate(
        AggregateFunction.SUM,
        Axis.ENTITY,
        _metric(
            "source_provision",
            entities=("AAA", "BBB"),
            periods=("2024",),
        ),
        ("AAA", "BBB"),
    )

    program = GroundedAstCompiler().compile(_ast(expression, UnitSpec(Dimension.MONEY, 0)), facts)
    execution = execute_grounded(program, facts)

    assert any(node.operation.value == "sum_by_scope" for node in program.nodes)
    assert execution.answer == -70.0


def test_compiler_selects_output_at_ranked_entity() -> None:
    facts = (
        _fact("net_revenue", "AAA", 2024, "100"),
        _fact("net_revenue", "BBB", 2024, "200"),
        _fact("profit_after_tax", "AAA", 2024, "20"),
        _fact("profit_after_tax", "BBB", 2024, "30"),
    )
    entities = ("AAA", "BBB")
    expression = SelectAtArg(
        Rank(
            Axis.ENTITY,
            entities,
            _metric("net_revenue", entities=entities, periods=("2024",)),
            RankDirection.DESCENDING,
        ),
        _metric("profit_after_tax", entities=entities, periods=("2024",)),
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(_ast(expression, UnitSpec(Dimension.MONEY, 0)), facts),
        facts,
    )

    assert execution.answer == 30.0


def test_compiler_returns_ranked_period_as_numeric_year() -> None:
    facts = (
        _fact("net_revenue", "AAA", 2022, "100"),
        _fact("net_revenue", "AAA", 2023, "150"),
        _fact("net_revenue", "AAA", 2024, "125"),
    )
    periods = ("2022", "2023", "2024")
    ast = QuestionAST(
        expression=Rank(
            Axis.PERIOD,
            periods,
            _metric("net_revenue", entities=("AAA",), periods=periods),
            RankDirection.DESCENDING,
        ),
        output=OutputSpec(ResultKind.PERIOD, UnitSpec(Dimension.PERIOD)),
        question="Năm nào có doanh thu cao nhất?",
    )

    execution = execute_grounded(GroundedAstCompiler().compile(ast, facts), facts)

    assert execution.answer == 2023.0


def test_compiler_counts_entities_matching_all_periods() -> None:
    facts = (
        _fact("net_revenue", "AAA", 2023, "10"),
        _fact("net_revenue", "AAA", 2024, "20"),
        _fact("net_revenue", "BBB", 2023, "10"),
        _fact("net_revenue", "BBB", 2024, "0"),
        _fact("profit_after_tax", "AAA", 2024, "1"),
        _fact("profit_after_tax", "BBB", 2024, "1"),
    )
    entities = ("AAA", "BBB")
    positive_every_year = QuantifiedPredicate(
        Axis.PERIOD,
        PredicateQuantifier.ALL,
        Comparison(
            ComparisonOperator.GT,
            _metric(
                "net_revenue",
                entities=entities,
                periods=("2023", "2024"),
            ),
            Literal(0, UnitSpec(Dimension.MONEY, 0)),
        ),
    )
    filtered = Filter(
        Axis.ENTITY,
        entities,
        positive_every_year,
        _metric("profit_after_tax", entities=entities, periods=("2024",)),
    )
    expression = Aggregate(
        AggregateFunction.COUNT,
        Axis.ENTITY,
        filtered,
        entities,
    )

    execution = execute_grounded(
        GroundedAstCompiler().compile(_ast(expression, UnitSpec(Dimension.COUNT)), facts),
        facts,
    )

    assert execution.answer == 1.0


def test_compiler_rejects_rank_with_unreduced_period_axis() -> None:
    entities = ("AAA", "BBB")
    facts = tuple(
        _fact("net_revenue", entity, year, value)
        for entity, values in (("AAA", ("10", "20")), ("BBB", ("30", "40")))
        for year, value in zip((2023, 2024), values, strict=True)
    )
    expression = SelectAtArg(
        Rank(
            Axis.ENTITY,
            entities,
            _metric(
                "net_revenue",
                entities=entities,
                periods=("2023", "2024"),
            ),
            RankDirection.DESCENDING,
        ),
        _metric(
            "net_revenue",
            entities=entities,
            periods=("2023", "2024"),
        ),
    )

    with pytest.raises(
        GroundedAstCompilationUnsupported,
        match="rank requires a entity-axis series",
    ):
        GroundedAstCompiler().compile(_ast(expression, UnitSpec(Dimension.MONEY, 0)), facts)
