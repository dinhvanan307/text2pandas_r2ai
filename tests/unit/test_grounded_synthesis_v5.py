from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from text2pandas.application.usecases.grounded_synthesis import (
    Comparator,
    GroundedFact,
    GroundedOperation,
    GroundedPlan,
    GroundedPlanError,
    GroundedProgram,
    ProgramNode,
    ProgramOperation,
    execute_grounded,
    execute_grounded_plan,
)
from text2pandas.domain.semantic import Basis, Dimension
from text2pandas.infrastructure.sandbox.query import execute_query


def _fact(
    uid: str,
    value: str,
    *,
    entity: str = "AAA",
    period: str = "2024-12-31",
    dimension: Dimension = Dimension.MONEY,
    scale: int | None = 0,
) -> GroundedFact:
    return GroundedFact(
        observation_uid=uid,
        table_uid=f"table-{uid}",
        document_id=f"{entity}_financial_statements_2024_consolidated",
        entity=entity,
        period=period,
        basis=Basis.CONSOLIDATED,
        row_path=uid,
        column_path=period,
        section_text="",
        value=Decimal(value),
        dimension=dimension,
        scale_exponent=scale,
    )


def _frame(facts: tuple[GroundedFact, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_uid": [fact.observation_uid for fact in facts],
            "value": [float(fact.value) for fact in facts],
        }
    )


def test_flat_plan_scales_money_and_replays_exactly() -> None:
    fact = _fact("revenue", "125", scale=6)
    plan = GroundedPlan(
        operation=GroundedOperation.LOOKUP,
        operand_uids=(fact.observation_uid,),
        output_dimension=Dimension.MONEY,
        output_scale_exponent=6,
    )

    execution = execute_grounded_plan(plan, (fact,))

    assert execution.answer == 125.0
    assert execute_query(execution.pandas_query, {"df1": _frame((fact,))}) == 125.0


@pytest.mark.parametrize(
    ("scale", "expected"),
    ((11, 1.25), (12, 0.125)),
)
def test_flat_plan_supports_competition_hundred_and_thousand_billion_units(
    scale: int, expected: float
) -> None:
    fact = _fact("revenue", "125000000000", scale=0)
    plan = GroundedPlan(
        operation=GroundedOperation.LOOKUP,
        operand_uids=(fact.observation_uid,),
        output_dimension=Dimension.MONEY,
        output_scale_exponent=scale,
    )

    execution = execute_grounded_plan(plan, (fact,))

    assert execution.answer == expected
    assert execute_query(execution.pandas_query, {"df1": _frame((fact,))}) == expected


def test_flat_plan_treats_missing_share_scale_as_absolute_units() -> None:
    fact = _fact(
        "outstanding-shares",
        "361481878",
        dimension=Dimension.SHARES,
        scale=None,
    )
    plan = GroundedPlan(
        operation=GroundedOperation.LOOKUP,
        operand_uids=(fact.observation_uid,),
        output_dimension=Dimension.SHARES,
        output_scale_exponent=0,
    )

    execution = execute_grounded_plan(plan, (fact,))

    assert execution.answer == 361481878.0
    assert execute_query(execution.pandas_query, {"df1": _frame((fact,))}) == 361481878.0


def test_dag_executes_compound_entity_count() -> None:
    facts = (
        _fact("ca-a", "100", entity="AAA"),
        _fact("ca-b", "50", entity="BBB"),
        _fact("cl-a", "120", entity="AAA"),
        _fact("cl-b", "40", entity="BBB"),
        _fact("ocf-a", "5", entity="AAA"),
        _fact("ocf-b", "-1", entity="BBB"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode("ca", ProgramOperation.FACTS, fact_uids=("ca-a", "ca-b"), axis="entity"),
            ProgramNode("cl", ProgramOperation.FACTS, fact_uids=("cl-a", "cl-b"), axis="entity"),
            ProgramNode("wc", ProgramOperation.SUBTRACT, input_ids=("ca", "cl")),
            ProgramNode("zero", ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                "wc_negative",
                ProgramOperation.COMPARE,
                input_ids=("wc", "zero"),
                comparator=Comparator.LT,
            ),
            ProgramNode("ocf", ProgramOperation.FACTS, fact_uids=("ocf-a", "ocf-b"), axis="entity"),
            ProgramNode(
                "ocf_positive",
                ProgramOperation.COMPARE,
                input_ids=("ocf", "zero"),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                "eligible",
                ProgramOperation.LOGICAL_AND,
                input_ids=("wc_negative", "ocf_positive"),
            ),
            ProgramNode("answer", ProgramOperation.COUNT_TRUE, input_ids=("eligible",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.COUNT,
        confidence=0.9,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == 1.0
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 1.0


def test_dag_executes_median_filter_argmax_and_select() -> None:
    facts = (
        _fact("margin-20", "10", period="2020-12-31", dimension=Dimension.PERCENT, scale=None),
        _fact("margin-21", "20", period="2021-12-31", dimension=Dimension.PERCENT, scale=None),
        _fact("margin-22", "30", period="2022-12-31", dimension=Dimension.PERCENT, scale=None),
        _fact("rank-20", "3", period="2020-12-31", dimension=Dimension.RATIO, scale=None),
        _fact("rank-21", "9", period="2021-12-31", dimension=Dimension.RATIO, scale=None),
        _fact("rank-22", "8", period="2022-12-31", dimension=Dimension.RATIO, scale=None),
        _fact("roe-20", "15", period="2020-12-31", dimension=Dimension.PERCENT, scale=None),
        _fact("roe-21", "25", period="2021-12-31", dimension=Dimension.PERCENT, scale=None),
        _fact("roe-22", "35", period="2022-12-31", dimension=Dimension.PERCENT, scale=None),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "margin",
                ProgramOperation.FACTS,
                fact_uids=("margin-20", "margin-21", "margin-22"),
                axis="period",
            ),
            ProgramNode("median", ProgramOperation.MEDIAN, input_ids=("margin",)),
            ProgramNode(
                "below",
                ProgramOperation.COMPARE,
                input_ids=("margin", "median"),
                comparator=Comparator.LT,
            ),
            ProgramNode(
                "rank",
                ProgramOperation.FACTS,
                fact_uids=("rank-20", "rank-21", "rank-22"),
                axis="period",
            ),
            ProgramNode("filtered", ProgramOperation.FILTER, input_ids=("rank", "below")),
            ProgramNode("best_year", ProgramOperation.ARGMAX_KEY, input_ids=("filtered",)),
            ProgramNode(
                "roe",
                ProgramOperation.FACTS,
                fact_uids=("roe-20", "roe-21", "roe-22"),
                axis="period",
            ),
            ProgramNode("answer", ProgramOperation.SELECT_AT_KEY, input_ids=("roe", "best_year")),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
        confidence=0.9,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == 15.0
    assert {fact.observation_uid for fact in execution.facts} == {
        "margin-20",
        "margin-21",
        "margin-22",
        "rank-20",
        "roe-20",
    }
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 15.0


def test_program_fails_closed_on_ungrounded_uid_and_dimension_mismatch() -> None:
    fact = _fact("money", "1")
    program = GroundedProgram(
        nodes=(
            ProgramNode("source", ProgramOperation.FACTS, fact_uids=("invented",), axis="entity"),
            ProgramNode("answer", ProgramOperation.SUM, input_ids=("source",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )
    with pytest.raises(GroundedPlanError, match="outside candidate context"):
        execute_grounded(program, (fact,))

    invalid_output = GroundedPlan(
        operation=GroundedOperation.LOOKUP,
        operand_uids=("money",),
        output_dimension=Dimension.PERCENT,
    )
    with pytest.raises(GroundedPlanError, match="output dimension mismatch"):
        execute_grounded(invalid_output, (fact,))


def test_program_parser_repairs_source_inputs_and_dangling_literal() -> None:
    program = GroundedProgram.from_mapping(
        {
            "nodes": [
                {
                    "id": "source",
                    "operation": "facts",
                    "input_ids": ["fact-a"],
                    "fact_uids": ["fact-a"],
                    "axis": "entity",
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": "positive",
                    "operation": "compare",
                    "input_ids": ["source", "zero"],
                    "fact_uids": [],
                    "axis": None,
                    "literal": 0,
                    "comparator": "gt",
                },
                {
                    "id": "answer",
                    "operation": "count_true",
                    "input_ids": ["positive"],
                    "fact_uids": [],
                    "axis": None,
                    "literal": None,
                    "comparator": None,
                },
            ],
            "output_node_id": "answer",
            "output_dimension": "count",
            "output_scale_exponent": 0,
            "confidence": 0.8,
        }
    )

    execution = execute_grounded(program, (_fact("fact-a", "1"),))

    assert program.nodes[0].input_ids == ()
    assert any(node.node_id == "zero" for node in program.nodes)
    assert execution.answer == 1.0


@pytest.mark.parametrize("operation", [ProgramOperation.MINIMUM, ProgramOperation.MAXIMUM])
def test_single_item_extremum_replays(operation: ProgramOperation) -> None:
    fact = _fact("only", "7")
    program = GroundedProgram(
        nodes=(
            ProgramNode("source", ProgramOperation.FACTS, fact_uids=("only",), axis="entity"),
            ProgramNode("answer", operation, input_ids=("source",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )

    execution = execute_grounded(program, (fact,))

    assert execute_query(execution.pandas_query, {"df1": _frame((fact,))}) == 7.0


def test_temporal_growth_vectorizes_by_entity_and_rolls_by_period() -> None:
    cohort_facts = (
        _fact("a-23", "100", entity="AAA", period="2023-12-31"),
        _fact("a-24", "120", entity="AAA", period="2024-12-31"),
        _fact("b-23", "100", entity="BBB", period="2023-12-31"),
        _fact("b-24", "80", entity="BBB", period="2024-12-31"),
    )
    cohort = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in cohort_facts),
                axis="entity_period",
            ),
            ProgramNode(
                "growth",
                ProgramOperation.GROWTH_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode("answer", ProgramOperation.AVERAGE, input_ids=("growth",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
    )
    assert execute_grounded(cohort, cohort_facts).answer == 0.0

    period_facts = (
        _fact("p-22", "100", period="2022-12-31"),
        _fact("p-23", "80", period="2023-12-31"),
        _fact("p-24", "120", period="2024-12-31"),
    )
    rolling = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in period_facts),
                axis="period",
            ),
            ProgramNode(
                "growth",
                ProgramOperation.ROLLING_GROWTH,
                input_ids=("source",),
            ),
            ProgramNode("answer", ProgramOperation.MINIMUM, input_ids=("growth",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
    )
    assert execute_grounded(rolling, period_facts).answer == -20.0


def test_temporal_projection_change_average_and_percent_replay() -> None:
    facts = (
        _fact("a-22", "100", entity="AAA", period="2022-12-31"),
        _fact("a-23", "120", entity="AAA", period="2023-12-31"),
        _fact("a-24", "90", entity="AAA", period="2024-12-31"),
        _fact("b-22", "40", entity="BBB", period="2022-12-31"),
        _fact("b-23", "50", entity="BBB", period="2023-12-31"),
        _fact("b-24", "80", entity="BBB", period="2024-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="entity_period",
            ),
            ProgramNode(
                "rolling_average",
                ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode(
                "rolling_change",
                ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
                input_ids=("rolling_average",),
            ),
            ProgramNode(
                "latest_change",
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=("rolling_change",),
            ),
            ProgramNode("best", ProgramOperation.ARGMAX_KEY, input_ids=("latest_change",)),
            ProgramNode(
                "latest_value",
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode(
                "selected",
                ProgramOperation.SELECT_AT_KEY,
                input_ids=("latest_value", "best"),
            ),
            ProgramNode("hundred", ProgramOperation.LITERAL, literal=Decimal(100)),
            ProgramNode(
                "ratio",
                ProgramOperation.DIVIDE,
                input_ids=("selected", "hundred"),
            ),
            ProgramNode("answer", ProgramOperation.TO_PERCENT, input_ids=("ratio",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == 80.0
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 80.0


def test_change_by_entity_uses_later_minus_earlier() -> None:
    facts = (
        _fact("a-23", "10", entity="AAA", period="2023-12-31"),
        _fact("a-24", "7", entity="AAA", period="2024-12-31"),
        _fact("b-23", "10", entity="BBB", period="2023-12-31"),
        _fact("b-24", "15", entity="BBB", period="2024-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="entity_period",
            ),
            ProgramNode(
                "change",
                ProgramOperation.CHANGE_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode("answer", ProgramOperation.MINIMUM, input_ids=("change",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == -3.0
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == -3.0


def test_drop_first_then_change_ignores_prior_year_added_for_rolling_balance() -> None:
    facts = (
        _fact("a-21", "5", entity="AAA", period="2021-12-31"),
        _fact("a-22", "10", entity="AAA", period="2022-12-31"),
        _fact("a-24", "40", entity="AAA", period="2024-12-31"),
        _fact("b-21", "50", entity="BBB", period="2021-12-31"),
        _fact("b-22", "20", entity="BBB", period="2022-12-31"),
        _fact("b-24", "10", entity="BBB", period="2024-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="entity_period",
            ),
            ProgramNode(
                "requested_periods",
                ProgramOperation.DROP_FIRST_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode(
                "change",
                ProgramOperation.CHANGE_BY_ENTITY,
                input_ids=("requested_periods",),
            ),
            ProgramNode("answer", ProgramOperation.AVERAGE, input_ids=("change",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == 10.0
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 10.0


def test_entity_reducers_filter_continuous_positive_cohort() -> None:
    facts = (
        _fact("a-23", "10", entity="AAA", period="2023-12-31"),
        _fact("a-24", "20", entity="AAA", period="2024-12-31"),
        _fact("b-23", "-1", entity="BBB", period="2023-12-31"),
        _fact("b-24", "30", entity="BBB", period="2024-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="entity_period",
            ),
            ProgramNode("zero", ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                "positive",
                ProgramOperation.COMPARE,
                input_ids=("source", "zero"),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                "continuous",
                ProgramOperation.ALL_BY_ENTITY,
                input_ids=("positive",),
            ),
            ProgramNode(
                "latest",
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode(
                "eligible",
                ProgramOperation.FILTER,
                input_ids=("latest", "continuous"),
            ),
            ProgramNode("answer", ProgramOperation.AVERAGE, input_ids=("eligible",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == 20.0
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 20.0


def test_top_k_mask_and_shifted_period_key_are_grounded() -> None:
    facts = (
        _fact("p-21", "5", period="2021-12-31"),
        _fact("p-22", "1", period="2022-12-31"),
        _fact("p-23", "9", period="2023-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="period",
            ),
            ProgramNode("first", ProgramOperation.ARGMIN_KEY, input_ids=("source",)),
            ProgramNode(
                "next",
                ProgramOperation.SHIFT_KEY,
                input_ids=("first",),
                literal=Decimal(1),
            ),
            ProgramNode(
                "answer",
                ProgramOperation.SELECT_AT_KEY,
                input_ids=("source", "next"),
            ),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
    )
    assert execute_grounded(program, facts).answer == 9.0

    cohort_facts = (
        _fact("a", "10", entity="AAA"),
        _fact("b", "30", entity="BBB"),
        _fact("c", "20", entity="CCC"),
    )
    top_two = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=("a", "b", "c"),
                axis="entity",
            ),
            ProgramNode(
                "mask",
                ProgramOperation.TOP_K_MASK,
                input_ids=("source",),
                literal=Decimal(2),
            ),
            ProgramNode("answer", ProgramOperation.COUNT_TRUE, input_ids=("mask",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.COUNT,
    )
    assert execute_grounded(top_two, cohort_facts).answer == 2.0


def test_cagr_by_entity_uses_actual_year_interval() -> None:
    facts = (
        _fact("a-22", "100", entity="AAA", period="2022-12-31"),
        _fact("a-24", "121", entity="AAA", period="2024-12-31"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "source",
                ProgramOperation.FACTS,
                fact_uids=("a-22", "a-24"),
                axis="entity_period",
            ),
            ProgramNode(
                "cagr",
                ProgramOperation.CAGR_BY_ENTITY,
                input_ids=("source",),
            ),
            ProgramNode("answer", ProgramOperation.AVERAGE, input_ids=("cagr",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
    )

    execution = execute_grounded(program, facts)

    assert execution.answer == pytest.approx(10.0)
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == pytest.approx(
        10.0
    )
