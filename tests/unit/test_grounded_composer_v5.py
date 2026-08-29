from decimal import Decimal

import pandas as pd

from text2pandas.application.usecases.grounded_composer import (
    DeterministicProgramComposer,
    JsonlCachedGroundedGenerator,
)
from text2pandas.application.usecases.grounded_synthesis import (
    GroundedFact,
    GroundedProgram,
    execute_grounded,
)
from text2pandas.domain.semantic import Basis, Dimension
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander
from text2pandas.infrastructure.sandbox.query import execute_query

QUESTION = (
    "Trong giai đoạn 2019–2021 của HPG, xét các năm có biên lợi nhuận gộp "
    "thấp hơn trung vị của cả giai đoạn, ROE tại năm có tỷ số dòng tiền hoạt "
    "động trên doanh thu thuần cao nhất là bao nhiêu phần trăm?"
)


def _fact(metric: str, year: int, value: str) -> GroundedFact:
    uid = f"{metric}-{year}"
    return GroundedFact(
        observation_uid=uid,
        table_uid=f"table-{year}",
        document_id=f"HPG_financial_statements_{year}_consolidated",
        entity="HPG",
        period=f"{year}-12-31",
        basis=Basis.CONSOLIDATED,
        row_path=metric,
        column_path=str(year),
        section_text="",
        value=Decimal(value),
        dimension=Dimension.MONEY,
        scale_exponent=0,
        retrieval_metric=metric,
    )


def _entity_fact(metric: str, entity: str, year: int, value: str) -> GroundedFact:
    fact = _fact(metric, year, value)
    return GroundedFact(
        observation_uid=f"{metric}-{entity}-{year}",
        table_uid=f"table-{entity}-{year}",
        document_id=f"{entity}_financial_statements_{year}_consolidated",
        entity=entity,
        period=fact.period,
        basis=fact.basis,
        row_path=fact.row_path,
        column_path=fact.column_path,
        section_text=fact.section_text,
        value=fact.value,
        dimension=fact.dimension,
        scale_exponent=fact.scale_exponent,
        retrieval_metric=metric,
    )


def _frame(facts: tuple[GroundedFact, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "observation_uid": [fact.observation_uid for fact in facts],
            "value": [float(fact.value) for fact in facts],
        }
    )


def _lexical_fact(
    uid: str,
    row: str,
    value: str,
    *,
    score: float,
    year: int = 2024,
) -> GroundedFact:
    return GroundedFact(
        observation_uid=uid,
        table_uid=f"table-{uid}",
        document_id=f"AAA_financial_statements_{year}_consolidated",
        entity="AAA",
        period=f"{year}-12-31",
        basis=Basis.CONSOLIDATED,
        row_path=row,
        column_path=str(year),
        section_text="",
        value=Decimal(value),
        dimension=Dimension.MONEY,
        scale_exponent=0,
        retrieval_metric=None,
        score=score,
    )


def test_composer_executes_median_filter_rank_and_selected_ratio() -> None:
    values = {
        "gross_profit": ("30", "10", "20"),
        "net_revenue": ("100", "100", "100"),
        "cash_flow_from_operations": ("5", "8", "7"),
        "profit_after_tax": ("10", "20", "30"),
        "equity": ("100", "100", "100"),
    }
    facts = tuple(
        _fact(metric, year, value)
        for metric, metric_values in values.items()
        for year, value in zip((2019, 2020, 2021), metric_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(QUESTION)
    hints = {
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(QUESTION, facts, hints=hints)
    execution = execute_grounded(program, facts)
    frame = pd.DataFrame(
        {
            "observation_uid": [fact.observation_uid for fact in facts],
            "value": [float(fact.value) for fact in facts],
        }
    )

    assert execution.answer == 20.0
    assert execute_query(execution.pandas_query, {"df1": frame}) == 20.0


def test_composer_executes_simple_growth_without_model() -> None:
    facts = (
        _fact("net_revenue", 2023, "100"),
        _fact("net_revenue", 2024, "125"),
    )
    hints = {
        "operation": "growth",
        "entities": ["HPG"],
        "periods": ["2023", "2024"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": ["net_revenue"],
        "required_formulas": [],
        "absolute_difference": False,
    }

    program = DeterministicProgramComposer().generate(
        "Tốc độ tăng trưởng doanh thu thuần của HPG từ 2023 sang 2024?",
        facts,
        hints=hints,
    )
    execution = execute_grounded(program, facts)

    assert execution.answer == 25.0


def test_composer_executes_simple_direct_ratio_in_metric_order() -> None:
    facts = (
        _fact("cash_flow_from_operations", 2024, "20"),
        _fact("net_revenue", 2024, "100"),
    )
    hints = {
        "operation": "divide",
        "entities": ["HPG"],
        "periods": ["2024"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": ["cash_flow_from_operations", "net_revenue"],
        "required_formulas": [],
    }

    program = DeterministicProgramComposer().generate(
        "Dòng tiền hoạt động trên doanh thu thuần năm 2024 là bao nhiêu phần trăm?",
        facts,
        hints=hints,
    )
    execution = execute_grounded(program, facts)

    assert execution.answer == 20.0


class _CountingGenerator:
    def __init__(self, program: GroundedProgram) -> None:
        self.program = program
        self.calls = 0

    def generate(
        self,
        question: str,
        facts: tuple[GroundedFact, ...],
        *,
        hints: dict[str, object],
    ) -> GroundedProgram:
        del question, facts, hints
        self.calls += 1
        return self.program


class _StaticComposer:
    def __init__(self, program: GroundedProgram) -> None:
        self.program = program

    def generate(
        self,
        question: str,
        facts: tuple[GroundedFact, ...],
        *,
        hints: dict[str, object],
    ) -> GroundedProgram:
        del question, facts, hints
        return self.program


def test_semantic_program_cache_is_loaded_once_and_reused(tmp_path) -> None:
    facts = (_fact("net_revenue", 2024, "125"),)
    hints = {
        "operation": "lookup",
        "requested_unit": {"dimension": "money", "scale_exponent": 0},
        "required_metric_ids": ["net_revenue"],
    }
    program = DeterministicProgramComposer().generate(
        "Doanh thu thuần HPG năm 2024?", facts, hints=hints
    )
    delegate = _CountingGenerator(program)
    cache_path = tmp_path / "plans.jsonl"
    cache = JsonlCachedGroundedGenerator(delegate, cache_path, "test-v1")

    first = cache.generate("Doanh thu thuần HPG năm 2024?", facts, hints=hints)
    second = cache.generate("Doanh thu thuần HPG năm 2024?", facts, hints=hints)
    reloaded_delegate = _CountingGenerator(program)
    reloaded = JsonlCachedGroundedGenerator(
        reloaded_delegate, cache_path, "test-v1"
    ).generate("Doanh thu thuần HPG năm 2024?", facts, hints=hints)

    assert first == second == reloaded == program
    assert delegate.calls == 1
    assert reloaded_delegate.calls == 0


def test_fallback_candidate_cascade_is_lazy_until_validation_requests_next() -> None:
    from text2pandas.application.usecases.grounded_composer import (
        FallbackGroundedGenerator,
    )

    facts = (_fact("net_revenue", 2024, "125"),)
    valid = DeterministicProgramComposer().generate(
        "Doanh thu thuần HPG năm 2024?",
        facts,
        hints={
            "operation": "lookup",
            "entities": ["HPG"],
            "periods": ["2024"],
            "requested_unit": {"dimension": "money", "scale_exponent": 0},
            "required_metric_ids": ["net_revenue"],
            "required_formulas": [],
        },
    )
    invalid = GroundedProgram(
        valid.nodes,
        output_node_id=valid.nodes[0].node_id,
        output_dimension=Dimension.MONEY,
        output_scale_exponent=0,
        confidence=0.96,
    )
    fallback = _CountingGenerator(valid)
    cascade = FallbackGroundedGenerator(_StaticComposer(invalid), fallback)

    candidates = cascade.generate_candidates("question", facts, hints={})

    assert next(candidates) == invalid
    assert fallback.calls == 0
    assert next(candidates) == valid
    assert fallback.calls == 1


def test_composer_ranks_two_period_formula_change_then_selects_latest_ratio() -> None:
    question = (
        "Hệ số dòng tiền hoạt động trên nợ ngắn hạn năm 2023 của doanh nghiệp "
        "có mức giảm biên lợi nhuận gộp từ năm 2022 sang 2023 lớn hơn, trong "
        "2 doanh nghiệp DPM và DCM, là bao nhiêu lần?"
    )
    values = {
        "DPM": {
            "gross_profit": ("42", "12"),
            "net_revenue": ("100", "100"),
            "cash_flow_from_operations": ("50", "70"),
            "current_liabilities": ("100", "100"),
        },
        "DCM": {
            "gross_profit": ("36", "16"),
            "net_revenue": ("100", "100"),
            "cash_flow_from_operations": ("40", "60"),
            "current_liabilities": ("100", "100"),
        },
    }
    facts = tuple(
        _entity_fact(metric, entity, year, value)
        for entity, metrics in values.items()
        for metric, period_values in metrics.items()
        for year, value in zip((2022, 2023), period_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "periods": ["2022", "2023"],
        "requested_unit": {"dimension": "ratio", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)
    execution = execute_grounded(program, facts)

    assert {formula.role for formula in expansion.formulas} == {"rank", "output"}
    assert execution.answer == 0.7


def test_composer_filters_by_median_formula_then_averages_output_formula() -> None:
    question = (
        "Năm 2022, trong nhóm AAA, BBB và CCC, các công ty có hệ số thanh toán "
        "nhanh thấp hơn trung vị của nhóm có biên lợi nhuận ròng bình quân là "
        "bao nhiêu phần trăm?"
    )
    values = {
        "AAA": {
            "current_assets": "100",
            "inventory": "20",
            "current_liabilities": "100",
            "profit_after_tax": "10",
            "net_revenue": "100",
        },
        "BBB": {
            "current_assets": "100",
            "inventory": "10",
            "current_liabilities": "50",
            "profit_after_tax": "20",
            "net_revenue": "100",
        },
        "CCC": {
            "current_assets": "100",
            "inventory": "0",
            "current_liabilities": "25",
            "profit_after_tax": "30",
            "net_revenue": "100",
        },
    }
    facts = tuple(
        _entity_fact(metric, entity, 2022, value)
        for entity, metrics in values.items()
        for metric, value in metrics.items()
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "average",
        "entities": list(values),
        "periods": ["2022"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)
    execution = execute_grounded(program, facts)

    assert {formula.role for formula in expansion.formulas} == {"filter", "output"}
    assert execution.answer == 10.0


def test_composer_averages_growth_for_continuously_positive_cfo_cohort() -> None:
    question = (
        "Trong bốn mã AAA, BBB, với các công ty có lưu chuyển tiền thuần từ "
        "hoạt động kinh doanh dương trong cả năm 2020 và 2021, bình quân tỷ lệ "
        "tăng trưởng doanh thu thuần từ năm 2020 đến 2021 là bao nhiêu %?"
    )
    facts = tuple(
        _entity_fact(metric, entity, year, value)
        for entity, metrics in {
            "AAA": {
                "net_revenue": ("100", "120"),
                "cash_flow_from_operations": ("5", "6"),
            },
            "BBB": {
                "net_revenue": ("100", "80"),
                "cash_flow_from_operations": ("-1", "4"),
            },
        }.items()
        for metric, values in metrics.items()
        for year, value in zip((2020, 2021), values, strict=True)
    )
    hints = {
        "operation": "average",
        "periods": ["2020", "2021"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": ["net_revenue", "cash_flow_from_operations"],
        "required_formulas": [],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 20.0


def test_composer_sums_latest_revenue_for_continuous_positive_margin() -> None:
    question = (
        "Trong nhóm AAA và BBB có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần "
        "dương trong cả ba năm 2020–2022, tổng doanh thu thuần năm 2022 của các "
        "công ty đó là bao nhiêu tỷ đồng?"
    )
    facts = tuple(
        _entity_fact(metric, entity, year, value)
        for entity, metrics in {
            "AAA": {
                "net_revenue": ("100", "110", "120"),
                "profit_after_tax": ("1", "2", "3"),
            },
            "BBB": {
                "net_revenue": ("200", "210", "220"),
                "profit_after_tax": ("1", "-2", "3"),
            },
        }.items()
        for metric, values in metrics.items()
        for year, value in zip((2020, 2021, 2022), values, strict=True)
    )
    hints = {
        "operation": "sum",
        "periods": ["2020", "2021", "2022"],
        "requested_unit": {"dimension": "money", "scale_exponent": 0},
        "required_metric_ids": ["net_revenue", "profit_after_tax"],
        "required_formulas": [],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 120.0


def test_composer_computes_filtered_metric_share_above_median_ratio() -> None:
    question = (
        "Năm 2022, trong các doanh nghiệp AAA, BBB và CCC, tổng nợ ngắn hạn "
        "của các doanh nghiệp có tỷ lệ hàng tồn kho chia cho nợ ngắn hạn cao "
        "hơn mức trung vị của cả nhóm chiếm bao nhiêu phần trăm tổng nợ ngắn "
        "hạn của cả nhóm?"
    )
    facts = tuple(
        _entity_fact(metric, entity, 2022, value)
        for entity, metrics in {
            "AAA": {"current_liabilities": "100", "inventory": "10"},
            "BBB": {"current_liabilities": "200", "inventory": "100"},
            "CCC": {"current_liabilities": "300", "inventory": "270"},
        }.items()
        for metric, value in metrics.items()
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "sum",
        "periods": ["2022"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "metric_contracts": [
            {
                "metric_id": concept.metric_id,
                "aliases": list(concept.aliases),
            }
            for concept in expansion.concepts
        ],
        "required_formulas": [],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 50.0


def test_composer_uses_high_margin_lexical_cluster_for_unregistered_note_metric() -> None:
    facts = (
        _lexical_fact(
            "target",
            "Giá gốc khoản đầu tư tại CTCP Sài Gòn - Rạch Giá",
            "250",
            score=95,
        ),
        _lexical_fact("distractor", "Tỷ lệ sở hữu", "30", score=40),
    )
    hints = {
        "operation": "lookup",
        "entities": ["AAA"],
        "periods": ["2024"],
        "requested_unit": {"dimension": "money", "scale_exponent": 0},
        "required_metric_ids": [],
        "required_formulas": [],
    }

    program = DeterministicProgramComposer().generate(
        "Giá gốc khoản đầu tư tại CTCP Sài Gòn - Rạch Giá của AAA năm 2024?",
        facts,
        hints=hints,
    )

    assert execute_grounded(program, facts).answer == 250.0


def test_composer_selects_formula_at_period_after_first_negative_cfo() -> None:
    question = (
        "Trong giai đoạn 2019-2022, biên lợi nhuận gộp của năm ngay sau năm "
        "đầu tiên AAA ghi nhận CFO âm là bao nhiêu phần trăm?"
    )
    values = {
        "cash_flow_from_operations": ("5", "-1", "4", "3"),
        "gross_profit": ("10", "20", "30", "40"),
        "net_revenue": ("100", "100", "100", "100"),
    }
    facts = tuple(
        _entity_fact(metric, "AAA", year, value)
        for metric, metric_values in values.items()
        for year, value in zip((2019, 2020, 2021, 2022), metric_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "lookup",
        "entities": ["AAA"],
        "periods": ["2019", "2020", "2021", "2022"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 30.0


def test_composer_averages_latest_margin_gap_for_two_period_eligible_cohort() -> None:
    question = (
        "Trong nhóm AAA, BBB và CCC, các công ty duy trì dòng tiền hoạt động "
        "dương ở cả năm 2024 và 2025 nhưng doanh thu thuần năm 2025 giảm so "
        "với 2024 có chênh lệch bình quân giữa biên lợi nhuận gộp và biên lợi "
        "nhuận ròng năm 2025 là bao nhiêu điểm phần trăm?"
    )
    values = {
        "AAA": {
            "cash_flow_from_operations": ("5", "6"),
            "net_revenue": ("100", "90"),
            "gross_profit": ("40", "36"),
            "profit_after_tax": ("10", "9"),
        },
        "BBB": {
            "cash_flow_from_operations": ("5", "6"),
            "net_revenue": ("100", "110"),
            "gross_profit": ("40", "44"),
            "profit_after_tax": ("10", "11"),
        },
        "CCC": {
            "cash_flow_from_operations": ("-1", "6"),
            "net_revenue": ("100", "80"),
            "gross_profit": ("40", "32"),
            "profit_after_tax": ("10", "8"),
        },
    }
    facts = tuple(
        _entity_fact(metric, entity, year, value)
        for entity, metrics in values.items()
        for metric, period_values in metrics.items()
        for year, value in zip((2024, 2025), period_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "average",
        "entities": list(values),
        "periods": ["2024", "2025"],
        "requested_unit": {"dimension": "percent_point", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 30.0


def test_composer_counts_rolling_formula_conditions_on_common_periods() -> None:
    question = (
        "Trong giai đoạn 2021-2024 của AAA, có bao nhiêu năm sau năm đầu tiên "
        "vừa cải thiện biên lợi nhuận gộp so với năm trước, vừa có CFO margin "
        "cao hơn trung vị CFO margin của cả giai đoạn?"
    )
    values = {
        "gross_profit": ("10", "20", "15", "30"),
        "net_revenue": ("100", "100", "100", "100"),
        "cash_flow_from_operations": ("10", "20", "30", "40"),
    }
    facts = tuple(
        _entity_fact(metric, "AAA", year, value)
        for metric, period_values in values.items()
        for year, value in zip((2021, 2022, 2023, 2024), period_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "count",
        "entities": ["AAA"],
        "periods": ["2021", "2022", "2023", "2024"],
        "requested_unit": {"dimension": "count", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 1.0


def test_composer_filters_positive_period_before_formula_rank_and_select() -> None:
    question = (
        "Trong giai đoạn 2020-2022, ở năm AAA có tỷ lệ dòng tiền thuần từ "
        "hoạt động kinh doanh (CFO) trên lợi nhuận sau thuế thấp nhất trong "
        "các năm lợi nhuận sau thuế dương, hệ số thanh toán nhanh cuối năm đó "
        "là bao nhiêu lần?"
    )
    values = {
        "cash_flow_from_operations": ("-100", "20", "30"),
        "profit_after_tax": ("-10", "10", "10"),
        "current_assets": ("100", "100", "100"),
        "inventory": ("10", "10", "10"),
        "current_liabilities": ("30", "45", "30"),
    }
    facts = tuple(
        _entity_fact(metric, "AAA", year, value)
        for metric, period_values in values.items()
        for year, value in zip((2020, 2021, 2022), period_values, strict=True)
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "extremum",
        "entities": ["AAA"],
        "periods": ["2020", "2021", "2022"],
        "requested_unit": {"dimension": "ratio", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert {formula.role for formula in expansion.formulas} == {"rank", "output"}
    assert execute_grounded(program, facts).answer == 2.0


def test_composer_computes_profit_share_below_median_direct_leverage() -> None:
    question = (
        "Năm 2024, tổng lợi nhuận sau thuế của các doanh nghiệp có tỷ lệ nợ "
        "phải trả chia cho vốn chủ sở hữu thấp hơn mức trung vị của cả nhóm "
        "chiếm bao nhiêu phần trăm tổng lợi nhuận sau thuế của cả nhóm?"
    )
    values = {
        "AAA": {"profit_after_tax": "10", "total_liabilities": "10", "equity": "10"},
        "BBB": {"profit_after_tax": "20", "total_liabilities": "20", "equity": "10"},
        "CCC": {"profit_after_tax": "30", "total_liabilities": "30", "equity": "10"},
        "DDD": {"profit_after_tax": "40", "total_liabilities": "40", "equity": "10"},
    }
    facts = tuple(
        _entity_fact(metric, entity, 2024, value)
        for entity, metrics in values.items()
        for metric, value in metrics.items()
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "sum",
        "entities": list(values),
        "periods": ["2024"],
        "requested_unit": {"dimension": "percent", "scale_exponent": None},
        "required_metric_ids": list(expansion.metric_ids),
        "metric_contracts": [
            {"metric_id": concept.metric_id, "aliases": list(concept.aliases)}
            for concept in expansion.concepts
        ],
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)

    assert execute_grounded(program, facts).answer == 30.0


def test_composer_filters_inventory_days_then_averages_margin_change() -> None:
    question = (
        "Trong nhóm AAA, BBB, CCC và DDD, xét các công ty có số ngày tồn kho "
        "năm 2022 cao hơn trung vị của nhóm. Mức thay đổi biên lợi nhuận gộp "
        "của từng công ty từ năm 2022 đến năm 2024 đạt bình quân bao nhiêu "
        "điểm phần trăm?"
    )
    inventory = {
        "AAA": ("100", "100", "100", "100"),
        "BBB": ("200", "200", "200", "200"),
        "CCC": ("300", "300", "300", "300"),
        "DDD": ("400", "400", "400", "400"),
    }
    margins = {
        "AAA": ("5", "10", "12", "15"),
        "BBB": ("18", "20", "21", "22"),
        "CCC": ("15", "20", "25", "30"),
        "DDD": ("45", "40", "38", "35"),
    }
    facts = tuple(
        [
            _entity_fact("inventory", entity, year, value)
            for entity, values in inventory.items()
            for year, value in zip((2021, 2022, 2023, 2024), values, strict=True)
        ]
        + [
            _entity_fact("cogs", entity, year, "-365")
            for entity in inventory
            for year in (2021, 2022, 2023, 2024)
        ]
        + [
            _entity_fact("gross_profit", entity, year, value)
            for entity, values in margins.items()
            for year, value in zip((2021, 2022, 2023, 2024), values, strict=True)
        ]
        + [
            _entity_fact("net_revenue", entity, year, "100")
            for entity in inventory
            for year in (2021, 2022, 2023, 2024)
        ]
    )
    expansion = GroundedQueryExpander(load_ontology()).analyze(question)
    hints = {
        "operation": "average",
        "entities": list(inventory),
        "periods": ["2021", "2022", "2023", "2024"],
        "requested_unit": {
            "dimension": "percent_point",
            "scale_exponent": None,
        },
        "required_metric_ids": list(expansion.metric_ids),
        "required_formulas": [
            formula.to_planner_dict() for formula in expansion.formulas
        ],
    }

    program = DeterministicProgramComposer().generate(question, facts, hints=hints)
    execution = execute_grounded(program, facts)

    assert execution.answer == 2.5
    assert execute_query(execution.pandas_query, {"df1": _frame(facts)}) == 2.5
