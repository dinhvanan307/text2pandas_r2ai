from decimal import Decimal

from text2pandas.application.usecases.grounded_synthesis import GroundedFact, execute_grounded
from text2pandas.domain.semantic import Basis, Dimension
from text2pandas.infrastructure.llm.ollama import compile_semantic_program


def _fact(metric: str, entity: str, value: str) -> GroundedFact:
    return GroundedFact(
        observation_uid=f"{metric}-{entity}",
        table_uid=f"table-{entity}",
        document_id=f"{entity}_financial_statements_2024_consolidated",
        entity=entity,
        period="2024-12-31",
        basis=Basis.CONSOLIDATED,
        row_path=metric,
        column_path="2024",
        section_text="",
        value=Decimal(value),
        dimension=Dimension.MONEY,
        scale_exponent=0,
        retrieval_metric=metric,
    )


def test_semantic_program_binds_vectorized_metrics_to_fact_uids() -> None:
    facts = (
        _fact("current_assets", "AAA", "10"),
        _fact("current_assets", "BBB", "30"),
        _fact("current_liabilities", "AAA", "20"),
        _fact("current_liabilities", "BBB", "10"),
    )
    raw = {
        "nodes": [
            {
                "id": "assets",
                "operation": "metric",
                "input_ids": [],
                "metric_id": "current_assets",
                "literal": None,
                "comparator": None,
            },
            {
                "id": "liabilities",
                "operation": "metric",
                "input_ids": [],
                "metric_id": "current_liabilities",
                "literal": None,
                "comparator": None,
            },
            {
                "id": "working_capital",
                "operation": "subtract",
                "input_ids": ["assets", "liabilities"],
                "metric_id": None,
                "literal": None,
                "comparator": None,
            },
            {
                "id": "answer",
                "operation": "average",
                "input_ids": ["working_capital"],
                "metric_id": None,
                "literal": None,
                "comparator": None,
            },
        ],
        "output_node_id": "answer",
        "output_dimension": "money",
        "output_scale_exponent": 0,
        "confidence": 0.9,
    }

    program = compile_semantic_program(raw, facts)
    execution = execute_grounded(program, facts)

    assert execution.answer == 5.0
    assert {
        uid for node in program.nodes for uid in node.fact_uids
    } == {fact.observation_uid for fact in facts}


def test_semantic_compiler_canonicalizes_metric_alias_and_scalarizes_lookup() -> None:
    facts = (_fact("profit_after_tax", "AAA", "25"),)
    raw = {
        "nodes": [
            {
                "id": "metric_net_income",
                "operation": "metric",
                "input_ids": [],
                "metric_id": "net_income",
                "literal": None,
                "comparator": None,
            }
        ],
        "output_node_id": "metric_net_income",
        "output_dimension": "money",
        "output_scale_exponent": 0,
        "confidence": 0.9,
    }

    program = compile_semantic_program(raw, facts, hints={"operation": "lookup"})

    assert program.output_node_id.endswith("_scalar")
    assert execute_grounded(program, facts).answer == 25.0


def test_semantic_compiler_collapses_period_named_duplicate_metric_sources() -> None:
    facts = tuple(
        GroundedFact(
            observation_uid=f"revenue-{entity}-{year}",
            table_uid=f"table-{entity}-{year}",
            document_id=f"{entity}_financial_statements_{year}_consolidated",
            entity=entity,
            period=f"{year}-12-31",
            basis=Basis.CONSOLIDATED,
            row_path="net_revenue",
            column_path=str(year),
            section_text="",
            value=Decimal(value),
            dimension=Dimension.MONEY,
            scale_exponent=0,
            retrieval_metric="net_revenue",
        )
        for entity, values in {"AAA": ("100", "120"), "BBB": ("100", "80")}.items()
        for year, value in zip((2023, 2024), values, strict=True)
    )
    raw = {
        "nodes": [
            {
                "id": "revenue_2023",
                "operation": "metric",
                "input_ids": [],
                "metric_id": "net_revenue",
                "literal": None,
                "comparator": None,
            },
            {
                "id": "revenue_2024",
                "operation": "metric",
                "input_ids": [],
                "metric_id": "net_revenue",
                "literal": None,
                "comparator": None,
            },
            {
                "id": "growth",
                "operation": "growth_by_entity",
                "input_ids": ["revenue_2023", "revenue_2024"],
                "metric_id": None,
                "literal": None,
                "comparator": None,
            },
            {
                "id": "answer",
                "operation": "average",
                "input_ids": ["growth"],
                "metric_id": None,
                "literal": None,
                "comparator": None,
            },
        ],
        "output_node_id": "answer",
        "output_dimension": "percent",
        "output_scale_exponent": None,
        "confidence": 0.9,
    }

    program = compile_semantic_program(raw, facts)

    assert sum(node.operation.value == "facts" for node in program.nodes) == 1
    assert execute_grounded(program, facts).answer == 0.0
