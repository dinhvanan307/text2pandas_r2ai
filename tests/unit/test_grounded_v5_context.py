from dataclasses import replace
from decimal import Decimal

from text2pandas.application.parsing.contracts import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
)
from text2pandas.application.usecases.grounded_synthesis import (
    GroundedFact,
    GroundedProgram,
    ProgramNode,
    ProgramOperation,
    execute_grounded,
)
from text2pandas.application.usecases.grounded_v5 import (
    _coherent_basis_candidates,
    _expand_period_range_annotations,
    _is_trusted_recovery,
    _is_trusted_replacement,
)
from text2pandas.domain.semantic import Basis, Dimension, RankDirection, UnitSpec


def _basis_fact(
    uid: str,
    *,
    metric: str,
    year: int,
    basis: Basis,
    score: float,
    metric_code: str | None = None,
    row_path: str | None = None,
) -> GroundedFact:
    return GroundedFact(
        observation_uid=uid,
        table_uid=f"table-{uid}",
        document_id=f"AAA-{year}-{basis.value}",
        entity="AAA",
        period=f"{year}-12-31",
        basis=basis,
        row_path=row_path or metric,
        column_path=str(year),
        section_text="",
        value=Decimal(1),
        dimension=Dimension.MONEY,
        scale_exponent=0,
        metric_code=metric_code,
        retrieval_metric=metric,
        score=score,
    )


def test_minimum_lease_payment_is_parsed_as_metric_not_extremum() -> None:
    annotation = QuestionAnnotations(
        entities=("IJC",),
        periods=("2015",),
        basis=Basis.SEPARATE,
        requested_unit=UnitSpec(Dimension.MONEY, 9, "VND"),
        operation=OperationKind.EXTREMUM,
        mode="legacy",
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.VALUE,
    )

    repaired = _expand_period_range_annotations(
        "Tổng số tiền thuê tối thiểu trong tương lai của công ty mẹ IJC "
        "đến ngày 31/12/2015 là bao nhiêu tỷ đồng?",
        annotation,
    )

    assert repaired.operation is OperationKind.LOOKUP
    assert repaired.rank_direction is None
    assert repaired.return_mode is ReturnMode.VALUE


def test_inventory_days_period_range_includes_prior_year_for_average_balance() -> None:
    annotation = QuestionAnnotations(
        entities=("HPG", "HSG"),
        periods=("2022", "2024"),
        basis=Basis.UNSPECIFIED,
        requested_unit=UnitSpec(Dimension.PERCENT_POINT, None, None),
        operation=OperationKind.AVERAGE,
        mode="legacy",
        return_mode=ReturnMode.VALUE,
    )

    repaired = _expand_period_range_annotations(
        "Các công ty có số ngày tồn kho năm 2022 cao hơn trung vị; mức thay "
        "đổi biên lợi nhuận gộp từ 2022 đến 2024 đạt bình quân bao nhiêu?",
        annotation,
    )

    assert repaired.periods == ("2021", "2022", "2023", "2024")


def test_coherent_basis_candidates_prefer_complete_consolidated_bundle() -> None:
    facts = (
        _basis_fact(
            "ca-consolidated",
            metric="current_assets",
            year=2022,
            basis=Basis.CONSOLIDATED,
            score=90,
        ),
        _basis_fact(
            "ca-separate",
            metric="current_assets",
            year=2022,
            basis=Basis.SEPARATE,
            score=200,
        ),
        _basis_fact(
            "cl-consolidated",
            metric="current_liabilities",
            year=2022,
            basis=Basis.CONSOLIDATED,
            score=90,
        ),
        _basis_fact(
            "cl-separate",
            metric="current_liabilities",
            year=2022,
            basis=Basis.SEPARATE,
            score=80,
        ),
    )

    selected = _coherent_basis_candidates(
        facts,
        required_metric_ids=("current_assets", "current_liabilities"),
        requested_basis=Basis.UNSPECIFIED,
    )

    assert {fact.basis for fact in selected} == {Basis.CONSOLIDATED}


def test_coherent_basis_candidates_use_lexical_score_for_direct_retrieval() -> None:
    facts = (
        _basis_fact(
            "direct-consolidated",
            metric="reported_service_purchase",
            year=2024,
            basis=Basis.CONSOLIDATED,
            score=90,
        ),
        _basis_fact(
            "direct-separate",
            metric="reported_service_purchase",
            year=2024,
            basis=Basis.SEPARATE,
            score=200,
        ),
    )

    selected = _coherent_basis_candidates(
        facts,
        required_metric_ids=(),
        requested_basis=Basis.UNSPECIFIED,
    )

    assert [fact.observation_uid for fact in selected] == ["direct-separate"]


def test_trusted_replacement_requires_composition_and_governed_metric_codes() -> None:
    facts = tuple(
        _basis_fact(
            f"revenue-{year}",
            metric="net_revenue",
            year=year,
            basis=Basis.CONSOLIDATED,
            score=100,
            metric_code="10",
        )
        for year in (2023, 2024)
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "revenue",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in facts),
                axis="period",
            ),
            ProgramNode(
                "growth",
                ProgramOperation.ROLLING_GROWTH,
                input_ids=("revenue",),
            ),
            ProgramNode(
                "answer",
                ProgramOperation.AVERAGE,
                input_ids=("growth",),
            ),
        ),
        output_node_id="answer",
        output_dimension=Dimension.PERCENT,
        output_scale_exponent=None,
        confidence=0.96,
    )
    execution = execute_grounded(program, facts)

    assert _is_trusted_replacement(program, execution)

    label_grounded_facts = tuple(
        _basis_fact(
            f"revenue-{year}",
            metric="net_revenue",
            year=year,
            basis=Basis.CONSOLIDATED,
            score=100,
            row_path="Doanh thu thuần về bán hàng và cung cấp dịch vụ",
        )
        for year in (2023, 2024)
    )
    label_execution = execute_grounded(program, label_grounded_facts)
    assert _is_trusted_replacement(program, label_execution)

    segmented_facts = (
        _basis_fact(
            "revenue-2023",
            metric="net_revenue",
            year=2023,
            basis=Basis.CONSOLIDATED,
            score=100,
            row_path="Bộ phận theo khu vực › Doanh thu thuần",
        ),
        label_grounded_facts[1],
    )
    segmented_execution = execute_grounded(program, segmented_facts)
    assert not _is_trusted_replacement(program, segmented_execution)


def test_trusted_replacement_accepts_high_margin_resolved_direct_fact() -> None:
    fact = replace(
        _basis_fact(
            "tax-payable",
            metric="reported_tax_payable",
            year=2024,
            basis=Basis.CONSOLIDATED,
            score=400,
            row_path="Thuế TNDN",
        ),
        source_confidence=0.65,
        resolution_margin=107.0,
        corroboration_count=3,
        score_reasons=(
            "metric:exact_row",
            "period:closing_match",
            "quality:no_collision",
        ),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "tax",
                ProgramOperation.FACTS,
                fact_uids=(fact.observation_uid,),
                axis="entity_period",
            ),
            ProgramNode("answer", ProgramOperation.SUM, input_ids=("tax",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
        confidence=0.96,
    )

    assert _is_trusted_replacement(program, execute_grounded(program, (fact,)))


def test_trusted_replacement_rejects_ambiguous_reported_direct_fact() -> None:
    fact = replace(
        _basis_fact(
            "service-expense",
            metric="reported_service_expense",
            year=2024,
            basis=Basis.CONSOLIDATED,
            score=400,
            row_path="Chi phí dịch vụ mua ngoài",
        ),
        source_confidence=0.9,
        resolution_margin=0.4,
        corroboration_count=2,
        score_reasons=("metric:exact_row", "quality:no_collision"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "expense",
                ProgramOperation.FACTS,
                fact_uids=(fact.observation_uid,),
                axis="entity_period",
            ),
            ProgramNode("answer", ProgramOperation.SUM, input_ids=("expense",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
        confidence=0.96,
    )

    assert not _is_trusted_replacement(program, execute_grounded(program, (fact,)))


def test_trusted_recovery_accepts_resolved_source_metric() -> None:
    fact = replace(
        _basis_fact(
            "source-expense",
            metric="source_expense",
            year=2024,
            basis=Basis.CONSOLIDATED,
            score=400,
            row_path="Chi phí hoạt động › Chi phí đặc thù",
        ),
        source_confidence=0.65,
        resolution_margin=80.0,
        score_reasons=("metric:source_context_complete", "quality:no_collision"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "expense",
                ProgramOperation.FACTS,
                fact_uids=(fact.observation_uid,),
                axis="entity_period",
            ),
            ProgramNode("answer", ProgramOperation.SUM, input_ids=("expense",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
        confidence=0.96,
    )

    assert _is_trusted_recovery(program, execute_grounded(program, (fact,)))


def test_trusted_recovery_rejects_unnamed_lexical_metric() -> None:
    fact = replace(
        _basis_fact(
            "lexical",
            metric="question text used as a metric",
            year=2024,
            basis=Basis.CONSOLIDATED,
            score=400,
        ),
        source_confidence=0.9,
        resolution_margin=100.0,
        score_reasons=("metric:exact_row", "quality:no_collision"),
    )
    program = GroundedProgram(
        nodes=(
            ProgramNode(
                "lexical",
                ProgramOperation.FACTS,
                fact_uids=(fact.observation_uid,),
                axis="entity_period",
            ),
            ProgramNode("answer", ProgramOperation.SUM, input_ids=("lexical",)),
        ),
        output_node_id="answer",
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
        confidence=0.96,
    )

    assert not _is_trusted_recovery(program, execute_grounded(program, (fact,)))
