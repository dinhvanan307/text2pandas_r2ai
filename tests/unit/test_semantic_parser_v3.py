from __future__ import annotations

from dataclasses import replace

from text2pandas.application.parsing import (
    MetricHypothesis,
    MetricResolutionResult,
    OperationKind,
    QuestionAnnotations,
    QuestionMetricMention,
    ReturnMode,
    SemanticParser,
)
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Basis,
    Comparison,
    Dimension,
    Filter,
    FormulaCall,
    Literal,
    LogicalOperator,
    LogicalPredicate,
    MetricRef,
    PeriodSemantics,
    PredicateQuantifier,
    QuantifiedPredicate,
    Rank,
    RankDirection,
    RollingGrowth,
    SelectAtArg,
    Unary,
    UnaryOperator,
    UnitSpec,
)
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.semantic import LegacyVietnameseAnnotator


class StaticAnnotator:
    def __init__(self, annotations: QuestionAnnotations):
        self.annotations = annotations

    def annotate(self, question: str) -> QuestionAnnotations:
        return self.annotations


class MovementResolver:
    fingerprint = "movement-fixture"

    def resolve(
        self,
        question: str,
        annotations: QuestionAnnotations,
    ) -> MetricResolutionResult:
        normalized = normalize_phrase(question)
        surface = "chi phi trich lap du phong rui ro cho vay khach hang"
        start = normalized.index(surface)
        hypothesis = MetricHypothesis(
            mention=QuestionMetricMention(
                start,
                start + len(surface),
                surface,
                surface,
            ),
            source_metric_id="source_provision_charge",
            source_build_id="fixture-build",
            aliases=("Trích lập dự phòng rủi ro cho vay khách hàng",),
            metric_codes=(),
            row_paths=(
                "Chi phí dự phòng rủi ro › Trích lập dự phòng rủi ro cho vay khách hàng",
            ),
            statement_types=("note",),
            unit=UnitSpec(Dimension.MONEY),
            period_semantics=PeriodSemantics.FLOW,
            preferred_basis=Basis.SEPARATE,
            match_method="fixture",
            score=(1000, 1000, 9),
            supporting_observations=2,
        )
        return MetricResolutionResult(
            "RESOLVED",
            selected=(hypothesis,),
            hypotheses=(hypothesis,),
        )


class CountSignResolver:
    fingerprint = "count-sign-fixture"

    def resolve(
        self,
        question: str,
        annotations: QuestionAnnotations,
    ) -> MetricResolutionResult:
        normalized = normalize_phrase(question)
        surface = "luu chuyen tien rong tu hoat dong dau tu am"
        start = normalized.index(surface)
        hypothesis = MetricHypothesis(
            mention=QuestionMetricMention(
                start,
                start + len(surface),
                surface,
                surface,
            ),
            source_metric_id="source_investing_cash_flow",
            source_build_id="fixture-build",
            aliases=("Lưu chuyển tiền thuần từ hoạt động đầu tư",),
            metric_codes=("30",),
            row_paths=("Lưu chuyển tiền thuần từ hoạt động đầu tư",),
            statement_types=("cash_flow",),
            unit=UnitSpec(Dimension.MONEY),
            period_semantics=PeriodSemantics.FLOW,
            preferred_basis=Basis.CONSOLIDATED,
            match_method="fixture",
            score=(1000, 1000, 8),
            supporting_observations=3,
        )
        return MetricResolutionResult(
            "RESOLVED",
            selected=(hypothesis,),
            hypotheses=(hypothesis,),
        )


class FormulaOperandResolver:
    fingerprint = "formula-operand-fixture"

    def __init__(self) -> None:
        self.calls = 0

    def resolve(
        self,
        question: str,
        annotations: QuestionAnnotations,
    ) -> MetricResolutionResult:
        self.calls += 1
        normalized = normalize_phrase(question)
        surface = "loi nhuan thuan tu hoat dong kinh doanh"
        start = normalized.index(surface)
        hypothesis = MetricHypothesis(
            mention=QuestionMetricMention(start, start + len(surface), surface, surface),
            source_metric_id="source_operating_profit",
            source_build_id="fixture-build",
            aliases=("Lợi nhuận thuần từ hoạt động kinh doanh (30=20+21-22)",),
            metric_codes=("30",),
            row_paths=("Lợi nhuận thuần từ hoạt động kinh doanh (30=20+21-22)",),
            statement_types=("income_statement",),
            unit=UnitSpec(Dimension.MONEY),
            period_semantics=PeriodSemantics.FLOW,
            preferred_basis=Basis.CONSOLIDATED,
            match_method="fixture",
            score=(1000, 1000, 8),
            supporting_observations=3,
        )
        return MetricResolutionResult(
            "RESOLVED",
            selected=(hypothesis,),
            hypotheses=(hypothesis,),
        )


def _annotations(**changes: object) -> QuestionAnnotations:
    base = QuestionAnnotations(
        entities=("VCB",),
        periods=("2024",),
        basis=Basis.CONSOLIDATED,
        requested_unit=UnitSpec(Dimension.MONEY, 9, "VND"),
        operation=OperationKind.LOOKUP,
        mode="single",
    )
    return replace(base, **changes)


def test_formula_match_does_not_skip_unreviewed_operand_resolution() -> None:
    resolver = FormulaOperandResolver()
    parser = SemanticParser(
        load_ontology(),
        StaticAnnotator(
            _annotations(
                operation=OperationKind.EXTREMUM,
                return_mode=ReturnMode.SELECT_AT_ARG,
                rank_direction=RankDirection.ASCENDING,
                requested_unit=UnitSpec(Dimension.PERCENT),
            )
        ),
        resolver,
    )

    result = parser.parse(
        "Doanh nghiệp có lợi nhuận thuần từ hoạt động kinh doanh thấp nhất "
        "có biên lợi nhuận ròng là bao nhiêu phần trăm?"
    )

    assert resolver.calls == 1
    assert tuple(binding.metric_codes for binding in result.source_bindings) == (("30",),)


def _parse(question: str, annotations: QuestionAnnotations):
    return SemanticParser(load_ontology(), StaticAnnotator(annotations)).parse(question)


def test_direct_metric_compiles_to_canonical_metric_ref() -> None:
    result = _parse("Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?", _annotations())

    assert result.ok
    assert isinstance(result.ast.expression, MetricRef)
    assert result.ast.expression.metric_id == "total_assets"
    assert result.ast.expression.entities == ("VCB",)


def test_reviewed_net_revenue_owns_longer_reported_statement_alias() -> None:
    result = _parse(
        "Doanh thu thuần về bán hàng và cung cấp dịch vụ của VCB năm 2024?",
        _annotations(),
    )

    assert result.ok
    assert isinstance(result.ast.expression, MetricRef)
    assert result.ast.expression.metric_id == "net_revenue"


def test_count_sign_survives_source_resolver_absorbing_polarity_token() -> None:
    question = (
        "SAB có số năm lưu chuyển tiền ròng từ hoạt động đầu tư âm "
        "là bao nhiêu trong các năm 2022, 2023 và 2024?"
    )
    annotations = _annotations(
        entities=("SAB",),
        periods=("2022", "2023", "2024"),
        requested_unit=UnitSpec(Dimension.COUNT),
        operation=OperationKind.COUNT,
    )

    result = SemanticParser(
        load_ontology(),
        StaticAnnotator(annotations),
        CountSignResolver(),
    ).parse(question)

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.function is AggregateFunction.COUNT
    assert isinstance(result.ast.expression.expression, Filter)
    assert isinstance(result.ast.expression.expression.predicate, Comparison)


def test_difference_across_entities_is_one_generic_arithmetic_tree() -> None:
    annotations = _annotations(
        entities=("VCB", "BID"),
        operation=OperationKind.SUBTRACT,
        mode="compare",
    )
    result = _parse("Chênh lệch tổng tài sản VCB và BID năm 2024?", annotations)

    assert result.ok
    assert isinstance(result.ast.expression, Arithmetic)
    assert result.ast.expression.operator == ArithmeticOperator.SUBTRACT
    assert result.ast.expression.left.entities == ("VCB",)
    assert result.ast.expression.right.entities == ("BID",)


def test_movement_qualifier_rebinds_point_in_time_metric_to_source_flow() -> None:
    annotations = _annotations(
        entities=("MBB", "CTG"),
        periods=("2023",),
        basis=Basis.SEPARATE,
        operation=OperationKind.SUBTRACT,
        mode="compare",
    )
    parser = SemanticParser(
        load_ontology(),
        StaticAnnotator(annotations),
        MovementResolver(),
    )

    result = parser.parse(
        "Chênh lệch chi phí trích lập dự phòng rủi ro cho vay khách hàng "
        "năm 2023 giữa MBB và CTG?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Arithmetic)
    assert result.ast.expression.left.metric_id == "source_provision_charge"
    assert result.ast.expression.right.metric_id == "source_provision_charge"
    assert result.ast.expression.left.period_semantics is PeriodSemantics.FLOW


def test_absolute_difference_compiles_to_typed_unary_expression() -> None:
    annotations = _annotations(
        entities=("VCB", "BID"),
        operation=OperationKind.SUBTRACT,
        absolute_difference=True,
        mode="compare",
    )
    result = _parse(
        "Chênh lệch tuyệt đối tổng tài sản VCB và BID năm 2024?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, Unary)
    assert result.ast.expression.operator == UnaryOperator.ABSOLUTE
    assert isinstance(result.ast.expression.expression, Arithmetic)
    assert result.ast.expression.expression.operator == ArithmeticOperator.SUBTRACT


def test_formula_can_be_aggregated_across_entity_axis() -> None:
    annotations = _annotations(
        entities=("VCB", "BID", "CTG"),
        operation=OperationKind.AVERAGE,
        requested_unit=UnitSpec(Dimension.PERCENT),
        mode="screen",
    )
    result = _parse("Biên lợi nhuận ròng bình quân của VCB, BID và CTG năm 2024?", annotations)

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.axis == Axis.ENTITY
    assert isinstance(result.ast.expression.expression, FormulaCall)
    assert isinstance(result.ast.expression.expression.expression, Arithmetic)


def test_select_at_arg_keeps_rank_and_return_metrics_separate() -> None:
    annotations = _annotations(
        entities=("VCB", "BID", "CTG"),
        operation=OperationKind.EXTREMUM,
        mode="screen",
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    question = "Công ty có tổng tài sản lớn nhất có lợi nhuận sau thuế bao nhiêu tỷ đồng?"
    result = _parse(question, annotations)

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert result.ast.expression.rank.by.metric_id == "total_assets"
    assert result.ast.expression.expression.metric_id == "profit_after_tax"


def test_filtered_extremum_compiles_reviewed_predicate_and_complete_period_domain() -> None:
    annotations = _annotations(
        entities=("ASM",),
        periods=("2016", "2018"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.FILTERED_VALUE,
    )
    result = _parse(
        "Trong giai đoạn 2016–2018 của ASM, trong các năm có tỷ lệ lợi nhuận "
        "sau thuế trên doanh thu thuần lớn hơn 10%, doanh thu thuần thấp nhất "
        "là bao nhiêu tỷ đồng?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.members == ("2016", "2017", "2018")
    assert isinstance(result.ast.expression.expression, Filter)
    assert result.ast.expression.expression.expression.metric_id == "net_revenue"
    assert result.ast.expression.expression.predicate.left.formula_id == "net_margin"
    assert result.ast.expression.expression.predicate.right.value == 10.0


def test_filtered_extremum_rejects_requested_dimension_that_needs_second_formula() -> None:
    annotations = _annotations(
        entities=("DCM",),
        periods=("2020", "2022"),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.RATIO),
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.FILTERED_VALUE,
    )
    result = _parse(
        "Trong giai đoạn 2020–2022 của DCM, xét các năm có tỷ lệ lợi nhuận sau "
        "thuế trên doanh thu thuần lớn hơn 10%, năm có doanh thu thuần thấp nhất "
        "có tỷ lệ lưu chuyển tiền thuần từ hoạt động kinh doanh trên nợ ngắn hạn "
        "là bao nhiêu lần?",
        annotations,
    )

    assert not result.ok
    assert result.reason == "FILTER_VALUE_UNIT_MISMATCH"


def test_filtered_extremum_accepts_tren_as_explicit_numeric_threshold() -> None:
    annotations = _annotations(
        entities=("CEO",),
        periods=("2022", "2024"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.FILTERED_VALUE,
    )
    result = _parse(
        "Với CEO trong giai đoạn 2022-2024, ở các năm có biên lợi nhuận ròng "
        "trên 10%, doanh thu thuần thấp nhất là bao nhiêu tỷ đồng?",
        annotations,
    )

    assert result.ok
    assert result.ast.expression.members == ("2022", "2023", "2024")


def test_unreviewed_divide_fails_closed() -> None:
    annotations = _annotations(operation=OperationKind.DIVIDE)
    result = _parse("Tổng tài sản trên vốn gì đó của VCB?", annotations)

    assert not result.ok
    assert result.reason == "UNREVIEWED_RELATIONAL_FORMULA"


def test_rank_member_compiles_explicit_ratio_operands_by_grammar() -> None:
    annotations = _annotations(
        periods=("2022", "2024"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.MEMBER,
    )
    result = _parse(
        "Năm nào VCB có tỷ lệ tổng tài sản trên nợ phải trả cao nhất?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, Rank)
    assert isinstance(result.ast.expression.by, Arithmetic)
    assert result.ast.expression.by.operator == ArithmeticOperator.DIVIDE
    assert result.ast.expression.by.left.metric_id == "total_assets"
    assert result.ast.expression.by.right.metric_id == "total_liabilities"


def test_rank_share_uses_operand_magnitudes() -> None:
    annotations = _annotations(
        periods=("2022", "2024"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.MEMBER,
    )
    result = _parse(
        "Năm nào VCB có tỷ trọng tổng tài sản trên nợ phải trả cao nhất?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, Rank)
    assert isinstance(result.ast.expression.by, Arithmetic)
    assert isinstance(result.ast.expression.by.left, Unary)
    assert isinstance(result.ast.expression.by.right, Unary)
    assert result.ast.expression.by.left.operator == UnaryOperator.ABSOLUTE
    assert result.ast.expression.by.right.operator == UnaryOperator.ABSOLUTE


def test_reported_metric_supports_lookup_but_not_unreviewed_derivation() -> None:
    lookup = _parse("Chi phí dịch vụ mua ngoài VCB năm 2024 là bao nhiêu tỷ đồng?", _annotations())
    derived = _parse(
        "Chi phí dịch vụ mua ngoài VCB tăng bao nhiêu từ 2023 đến 2024?",
        _annotations(periods=("2023", "2024"), operation=OperationKind.SUBTRACT),
    )

    assert lookup.ok
    assert not derived.ok
    assert derived.reason == "REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION"


def test_measured_vietnamese_annotator_drives_v3_without_legacy_semantic_ir() -> None:
    companies = {
        "VCB": "Ngân hàng TMCP Ngoại thương Việt Nam",
        "BID": "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam",
        "CTG": "Ngân hàng TMCP Công thương Việt Nam",
    }
    parser = SemanticParser(load_ontology(), LegacyVietnameseAnnotator(companies))

    result = parser.parse(
        "Trong nhóm VCB, BID và CTG năm 2024, công ty có tổng tài sản lớn nhất "
        "có lợi nhuận sau thuế bao nhiêu tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert result.ast.expression.rank.members == ("BID", "CTG", "VCB")


def test_total_over_named_companies_keeps_complete_entity_domain() -> None:
    companies = {
        "AAA": "CTCP Nhựa An Phát Xanh",
        "DCM": "CTCP - Tổng công ty Phân bón Dầu khí Cà Mau",
        "HPG": "CTCP Tập đoàn Hòa Phát",
        "MSR": "CTCP Masan High-Tech Materials",
    }
    parser = SemanticParser(load_ontology(), LegacyVietnameseAnnotator(companies))

    result = parser.parse(
        "Tổng lưu chuyển tiền thuần từ hoạt động kinh doanh năm 2015 "
        "của CTCP Masan High-Tech Materials công ty mẹ, CTCP Tập đoàn Hòa "
        "Phát công ty mẹ, CTCP Nhựa An Phát Xanh công ty mẹ và CTCP - "
        "Tổng công ty Phân bón Dầu khí Cà Mau công ty mẹ là bao nhiêu tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.axis == Axis.ENTITY
    assert result.ast.expression.members == ("AAA", "DCM", "HPG", "MSR")


def test_total_after_leading_period_compiles_multi_entity_sum() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "MPC": "CTCP Tập đoàn Thủy sản Minh Phú",
                "SAB": "Sabeco",
                "HAG": "Hoàng Anh Gia Lai",
            }
        ),
    )

    result = parser.parse(
        "Năm 2016, tổng chi phí tài chính của MPC công ty mẹ, SAB công ty mẹ "
        "và HAG công ty mẹ là bao nhiêu tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.axis == Axis.ENTITY
    assert result.ast.expression.members == ("HAG", "MPC", "SAB")


def test_average_over_named_companies_keeps_complete_entity_domain() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "HPG": "CTCP Tập đoàn Hòa Phát",
                "MSR": "CTCP Masan High-Tech Materials",
                "NKG": "CTCP Thép Nam Kim",
            }
        ),
    )

    result = parser.parse(
        "Giá trị trung bình tổng tài sản của CTCP Tập đoàn Hòa Phát, "
        "CTCP Masan High-Tech Materials và CTCP Thép Nam Kim năm 2024 "
        "là bao nhiêu tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.function == AggregateFunction.AVERAGE
    assert result.ast.expression.axis == Axis.ENTITY
    assert result.ast.expression.members == ("HPG", "MSR", "NKG")


def test_explicit_numeric_predicate_compiles_typed_entity_count() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "DNH": "CTCP Thủy điện Đa Nhim - Hàm Thuận - Đa Mi",
                "GEG": "CTCP Điện Gia Lai",
                "HDG": "CTCP Tập đoàn Hà Đô",
            }
        ),
    )

    result = parser.parse(
        "Có bao nhiêu trong số CTCP Tập đoàn Hà Đô, CTCP Điện Gia Lai và "
        "CTCP Thủy điện Đa Nhim - Hàm Thuận - Đa Mi có dòng tiền thuần từ "
        "hoạt động kinh doanh lớn hơn 1 nghìn tỷ đồng trong năm 2025?"
    )

    assert result.ok
    assert result.ast.output.unit.dimension == Dimension.COUNT
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.function == AggregateFunction.COUNT
    assert isinstance(result.ast.expression.expression, Filter)
    assert isinstance(result.ast.expression.expression.predicate, Comparison)
    literal = result.ast.expression.expression.predicate.right
    assert isinstance(literal, Literal)
    assert literal.unit.dimension == Dimension.MONEY
    assert literal.unit.scale_exponent == 12


def test_explicit_simultaneous_sign_predicates_compile_typed_count() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {"HPX": "HPX", "NVL": "NVL", "SCR": "SCR", "VIC": "VIC", "VRE": "VRE"}
        ),
    )

    result = parser.parse(
        "Năm 2024, có bao nhiêu doanh nghiệp trong nhóm mã cổ phiếu HPX, NVL, "
        "SCR, VIC và VRE đồng thời ghi nhận vốn lưu động ròng âm và lưu chuyển "
        "tiền thuần từ hoạt động kinh doanh dương?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.function == AggregateFunction.COUNT
    filtered = result.ast.expression.expression
    assert isinstance(filtered, Filter)
    assert isinstance(filtered.predicate, LogicalPredicate)
    assert len(filtered.predicate.predicates) == 2


def test_count_compiles_multiple_explicit_formula_thresholds_as_conjunction() -> None:
    companies = {
        value: value
        for value in ("DIG", "HPX", "KBC", "NVL", "SCR", "VIC", "VPI", "VRE")
    }
    parser = SemanticParser(load_ontology(), LegacyVietnameseAnnotator(companies))
    result = parser.parse(
        "Năm 2024, trong nhóm DIG, HPX, KBC, NVL, SCR, VIC, VPI và VRE, có "
        "bao nhiêu doanh nghiệp đồng thời có hệ số thanh toán nhanh trên 1 lần "
        "và hệ số nợ phải trả trên vốn chủ sở hữu dưới 1,5 lần?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.function == AggregateFunction.COUNT
    filtered = result.ast.expression.expression
    assert isinstance(filtered, Filter)
    assert isinstance(filtered.predicate, LogicalPredicate)
    assert len(filtered.predicate.predicates) == 2


def test_direct_binary_metric_preserves_explicit_counterparty_selector() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"VGC": "Tổng Công ty Viglacera - CTCP"}),
    )

    result = parser.parse(
        "Thay đổi số dư vay ngắn hạn từ Ngân hàng TMCP Quốc tế của Tổng Công "
        "ty Viglacera - CTCP từ cuối năm 2023 đến cuối năm 2024 là bao nhiêu "
        "triệu đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Arithmetic)
    assert isinstance(result.ast.expression.left, MetricRef)
    assert isinstance(result.ast.expression.right, MetricRef)
    assert result.ast.expression.left.required_context_phrases == (
        "ngan hang tmcp quoc te",
    )
    assert result.ast.expression.right.required_context_phrases == (
        "ngan hang tmcp quoc te",
    )


def test_direct_metric_preserves_named_counterparty_without_legal_prefix() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"BVH": "Tập đoàn Bảo Việt"}),
    )

    result = parser.parse(
        "Khoản vay ngắn hạn từ Bảo Việt Nhân thọ của công ty mẹ Tập đoàn "
        "Bảo Việt cuối năm 2024 là bao nhiêu triệu đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, MetricRef)
    assert result.ast.expression.required_context_phrases == (
        "bao viet nhan tho",
    )


def test_total_over_explicit_period_domain_compiles_period_sum() -> None:
    parser = SemanticParser(
        load_ontology(), LegacyVietnameseAnnotator({"NVB": "Ngân hàng TMCP Quốc Dân"})
    )

    result = parser.parse(
        "Tổng lưu chuyển tiền thuần từ hoạt động kinh doanh của công ty "
        "mẹ Ngân hàng TMCP Quốc Dân (NVB) trong các năm 2015, 2016, "
        "2019, 2024 và 2025 là bao nhiêu nghìn tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)
    assert result.ast.expression.axis == Axis.PERIOD
    assert result.ast.expression.members == ("2015", "2016", "2019", "2024", "2025")


def test_filtered_entity_total_is_not_flattened_to_unconditional_sum() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "GEX": "CTCP Tập đoàn GELEX",
                "HBC": "CTCP Tập đoàn Xây dựng Hòa Bình",
                "PC1": "CTCP Tập đoàn PC1",
            }
        ),
    )

    annotations = parser.annotator.annotate(
        "Tổng số phải trả sau 12 tháng của công ty có tỷ lệ quyền biểu quyết "
        "tại các đơn vị liên doanh, liên kết đạt từ 50% trở lên trong số "
        "GEX, HBC và PC1 năm 2024 là bao nhiêu nghìn tỷ đồng?"
    )

    assert annotations.operation == OperationKind.LOOKUP


def test_bare_hon_may_is_difference_and_fails_closed_with_missing_entity() -> None:
    parser = SemanticParser(
        load_ontology(), LegacyVietnameseAnnotator({"MBB": ["MBBank", "MB Bank"]})
    )

    result = parser.parse(
        "Cuối năm 2022, số dư dự phòng tài sản có khác của Eximbank hơn "
        "MBBank mấy triệu đồng?"
    )

    assert not result.ok
    assert result.reason == "BINARY_OPERANDS_UNRESOLVED"


def test_unresolved_filtered_multi_entity_lookup_fails_before_binding() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "GEX": "CTCP Tập đoàn GELEX",
                "HBC": "CTCP Tập đoàn Xây dựng Hòa Bình",
                "PC1": "CTCP Tập đoàn PC1",
            }
        ),
    )

    result = parser.parse(
        "Tổng tài sản của công ty có tỷ lệ quyền biểu quyết "
        "tại các đơn vị liên doanh, liên kết đạt từ 50% trở lên trong số "
        "GEX, HBC và PC1 năm 2024 là bao nhiêu nghìn tỷ đồng?"
    )

    assert not result.ok
    assert result.reason == "LOOKUP_SCOPE_NON_SCALAR"


def test_select_at_arg_uses_rank_clause_spans_not_global_mention_order() -> None:
    annotations = _annotations(
        entities=("HHS",),
        periods=("2015", "2016", "2017", "2020", "2021"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Trong các năm 2015, 2016, 2017, 2020 và 2021, giá gốc nguyên liệu, vật "
        "liệu cuối năm của HHS tại năm có tổng giá gốc hàng tồn kho cuối năm cao "
        "nhất là bao nhiêu tỷ đồng?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert result.ast.expression.rank.by.metric_id == "inventory"
    selected = result.ast.expression.expression
    assert selected.metric_id == "reported_477533b54944d591"
    assert selected.expected_unit == annotations.requested_unit


def test_select_at_arg_rejects_unreviewed_ratio_instead_of_using_one_operand() -> None:
    annotations = _annotations(
        entities=("ASM",),
        periods=("2022", "2024", "2025"),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.PERCENT),
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Trong các năm 2022, 2024 và 2025 của ASM, tỷ lệ giữa lưu chuyển tiền "
        "thuần từ hoạt động kinh doanh và doanh thu của năm có số dư vay ngắn "
        "hạn cuối năm cao nhất là bao nhiêu %?",
        annotations,
    )

    assert not result.ok
    assert result.reason == "SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED"


def test_unresolved_rank_formula_abstains_instead_of_ranking_output_operand() -> None:
    annotations = _annotations(
        entities=("HPG",),
        periods=("2017", "2023"),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.PERCENT),
        rank_direction=RankDirection.ASCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Trong giai đoạn 2017-2023, tại năm HPG có tỷ lệ CFO trên LNST thấp nhất, "
        "hàng tồn kho cuối năm chiếm bao nhiêu phần trăm tổng tài sản cuối năm đó?",
        annotations,
    )

    assert not result.ok
    assert result.reason == "SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED"


def test_viet_nam_company_name_does_not_create_select_at_arg_clause() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {"VCB": "Ngân hàng TMCP Ngoại thương Việt Nam"}
        ),
    )
    result = parser.parse(
        "Ngân hàng TMCP Ngoại thương Việt Nam có mức thuế TNDN hiện hành phải "
        "nộp trong năm lớn nhất là bao nhiêu tỷ đồng trong các năm 2015, 2017, "
        "2018, 2022 và 2023?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Aggregate)


def test_select_at_arg_rejects_unresolved_composite_selected_expense() -> None:
    annotations = _annotations(
        entities=("MPC",),
        periods=("2016", "2018", "2020", "2022", "2023"),
        operation=OperationKind.EXTREMUM,
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Chi phí vận chuyển và chi phí dịch vụ mua ngoài của MPC trong năm có "
        "số dư cuối năm xây dựng cơ bản dở dang cao nhất trong các năm 2016, "
        "2018, 2020, 2022 và 2023 là bao nhiêu tỷ đồng?",
        annotations,
    )

    assert not result.ok
    assert result.reason == "SELECT_AT_ARG_SELECTED_COMPOSITE_UNRESOLVED"


def test_filtered_multi_entity_sum_compiles_predicate_and_selected_metric_separately() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {
                "AAA": "CTCP Nhựa An Phát Xanh",
                "DCM": "CTCP Phân bón Dầu khí Cà Mau",
                "DPM": "Tổng CTCP Phân bón và Hóa chất Dầu khí",
                "GVR": "Tập đoàn Công nghiệp Cao su Việt Nam",
            }
        ),
    )

    result = parser.parse(
        "Năm 2016, trong bốn mã cổ phiếu AAA, DCM, DPM và GVR, tổng doanh thu "
        "thuần của các công ty có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần "
        "lớn hơn 10% là bao nhiêu nghìn tỷ đồng?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert aggregate.function == AggregateFunction.SUM
    assert isinstance(aggregate.expression, Filter)
    assert aggregate.expression.predicate.left.formula_id == "net_margin"
    assert aggregate.expression.predicate.operator.value == "gt"
    assert aggregate.expression.expression.metric_id == "net_revenue"
    assert aggregate.expression.expression.qualifiers == ()


def test_select_at_arg_preserves_explicit_nested_counterparty_selector() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"VGT": "Tập đoàn Dệt May Việt Nam"}),
    )

    result = parser.parse(
        "Trong các năm 2015 và 2017, giá trị mua hàng hóa và dịch vụ từ Công ty "
        "TNHH Coats Phong Phú của Tập đoàn Dệt May Việt Nam trong năm có vốn "
        "chủ sở hữu cuối năm cao nhất là bao nhiêu tỷ đồng?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert result.ast.expression.expression.required_context_phrases == (
        "tnhh coats phong phu",
    )


def test_select_at_arg_does_not_rank_one_operand_of_unreviewed_ratio() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"BSR": "BSR", "PLX": "PLX", "PVT": "PVT"}),
    )

    result = parser.parse(
        "Năm 2017, trong ba mã BSR, PLX và PVT, doanh nghiệp có tỷ lệ lưu chuyển "
        "tiền thuần từ hoạt động kinh doanh trên lợi nhuận thuần từ hoạt động "
        "kinh doanh thấp nhất có tỷ lệ lợi nhuận sau thuế trên doanh thu thuần "
        "là bao nhiêu %?"
    )

    assert not result.ok
    assert result.reason == "SELECT_AT_ARG_RANK_FORMULA_UNRESOLVED"


def test_select_at_arg_uses_shared_interest_coverage_formula_for_output() -> None:
    annotations = _annotations(
        entities=("BSR", "PLX", "PVT"),
        periods=("2019",),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.RATIO),
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Năm 2019, trong nhóm BSR, PLX và PVT, công ty có hệ số nợ phải trả "
        "trên vốn chủ sở hữu cao nhất có hệ số khả năng thanh toán lãi vay là "
        "bao nhiêu lần?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert isinstance(result.ast.expression.rank.by, FormulaCall)
    assert result.ast.expression.rank.by.formula_id == "debt_to_equity"
    assert isinstance(result.ast.expression.expression, FormulaCall)
    assert result.ast.expression.expression.formula_id == "interest_coverage"


def test_select_at_arg_preserves_average_balance_asset_turnover_output() -> None:
    annotations = _annotations(
        entities=("ACV", "HHV", "VSC"),
        periods=("2024",),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.RATIO),
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Năm 2024, trong nhóm ACV, HHV và VSC, vòng quay tổng tài sản (tính "
        "theo tổng tài sản bình quân) của doanh nghiệp có tỷ trọng tài sản dài "
        "hạn trên tổng tài sản cao nhất là bao nhiêu vòng?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert isinstance(result.ast.expression.expression, FormulaCall)
    assert result.ast.expression.expression.formula_id == "asset_turnover_average_assets"


def test_period_select_at_arg_ranks_by_consecutive_growth_not_level() -> None:
    annotations = _annotations(
        entities=("HPG",),
        periods=("2020", "2021", "2022", "2023", "2024"),
        operation=OperationKind.EXTREMUM,
        requested_unit=UnitSpec(Dimension.PERCENT),
        rank_direction=RankDirection.DESCENDING,
        return_mode=ReturnMode.SELECT_AT_ARG,
    )
    result = _parse(
        "Ở năm có tốc độ tăng doanh thu thuần so với năm liền trước cao nhất, "
        "tỷ lệ lưu chuyển tiền thuần từ hoạt động kinh doanh trên doanh thu "
        "thuần của năm đó là bao nhiêu phần trăm?",
        annotations,
    )

    assert result.ok
    assert isinstance(result.ast.expression, SelectAtArg)
    assert isinstance(result.ast.expression.rank.by, RollingGrowth)
    assert isinstance(result.ast.expression.rank.by.expression, MetricRef)
    assert result.ast.expression.rank.by.expression.metric_id == "net_revenue"
    assert result.ast.expression.rank.members == ("2021", "2022", "2023", "2024")


def test_filtered_multi_entity_average_supports_distinct_reviewed_formulas() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {"AAA": "AAA", "DCM": "DCM", "GVR": "GVR", "PRT": "PRT"}
        ),
    )

    result = parser.parse(
        "Năm 2017, trong bốn mã cổ phiếu AAA, DCM, GVR và PRT, với các công ty "
        "có tỷ lệ tài sản ngắn hạn trên nợ ngắn hạn từ 1 lần trở lên, bình quân "
        "tỷ lệ hàng tồn kho trên nợ ngắn hạn là bao nhiêu lần?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert aggregate.function == AggregateFunction.AVERAGE
    assert isinstance(aggregate.expression, Filter)
    assert aggregate.expression.predicate.left.formula_id == "current_ratio"
    assert aggregate.expression.predicate.operator.value == "ge"
    assert aggregate.expression.expression.formula_id == "inventory_to_current_liabilities"


def test_temporal_cohort_average_requires_positive_metric_in_every_period() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"DCM": "DCM", "DPM": "DPM", "PRT": "PRT"}),
    )

    result = parser.parse(
        "Trong ba mã cổ phiếu DCM, DPM và PRT, với các công ty có lưu chuyển "
        "tiền thuần từ hoạt động kinh doanh dương trong cả năm 2019 và 2020, "
        "bình quân tỷ lệ tăng trưởng doanh thu thuần từ năm 2019 đến 2020 là "
        "bao nhiêu %?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert isinstance(aggregate.expression, Filter)
    predicate = aggregate.expression.predicate
    assert isinstance(predicate, QuantifiedPredicate)
    assert predicate.axis == Axis.PERIOD
    assert predicate.quantifier == PredicateQuantifier.ALL
    assert predicate.predicate.left.metric_id == "cash_flow_from_operations"
    assert predicate.predicate.left.periods == ("2019", "2020")
    projection = aggregate.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.GROWTH
    assert projection.left.entities == ("DCM", "DPM", "PRT")
    assert projection.left.periods == ("2020",)
    assert projection.right.periods == ("2019",)


def test_temporal_cohort_average_changes_formula_after_positive_growth_filter() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"DCM": "DCM", "DPM": "DPM", "PRT": "PRT"}),
    )

    result = parser.parse(
        "Trong nhóm DCM, DPM và PRT, xét các công ty có tăng trưởng doanh thu "
        "thuần dương từ 2019 đến 2020, thay đổi biên lợi nhuận gộp bình quân "
        "là bao nhiêu điểm phần trăm?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert isinstance(aggregate.expression, Filter)
    predicate = aggregate.expression.predicate
    assert isinstance(predicate, Comparison)
    assert isinstance(predicate.left, Arithmetic)
    assert predicate.left.operator == ArithmeticOperator.GROWTH
    assert predicate.left.left.periods == ("2020",)
    assert predicate.left.right.periods == ("2019",)
    projection = aggregate.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.SUBTRACT
    assert isinstance(projection.left, FormulaCall)
    assert projection.left.formula_id == "gross_margin"
    assert projection.left.expression.left.periods == ("2020",)
    assert projection.right.expression.left.periods == ("2019",)


def test_average_compiles_explicit_reported_ratio_before_outer_aggregate() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {"MSN": "MSN", "MPC": "MPC", "VNM": "VNM", "MML": "MML"}
        ),
    )

    result = parser.parse(
        "Tính tỷ trọng chi phí khấu hao trên tổng chi phí quản lý doanh nghiệp "
        "năm 2022 của MSN, MPC, VNM và MML, sau đó lấy trung bình của 4 tỷ trọng "
        "này theo đơn vị phần trăm."
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert aggregate.function == AggregateFunction.AVERAGE
    assert isinstance(aggregate.expression, Arithmetic)
    assert aggregate.expression.operator == ArithmeticOperator.DIVIDE
    assert isinstance(aggregate.expression.left, Unary)
    assert isinstance(aggregate.expression.right, Unary)


def test_known_money_expression_cannot_be_relabelled_as_percent_output() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"NLG": "NLG"}),
    )

    result = parser.parse(
        "Tỷ trọng vốn chủ sở hữu trung bình của NLG trong các năm 2015, 2018 và "
        "2024 là bao nhiêu %?"
    )

    assert not result.ok
    assert result.reason == "DIMENSION_MISMATCH:money:percent"


def test_entity_difference_can_wrap_an_explicit_ratio() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"AAA": "AAA", "BBB": "BBB"}),
    )

    result = parser.parse(
        "Chênh lệch tỷ trọng vay ngắn hạn trên tổng tài sản của AAA và BBB "
        "năm 2024 là bao nhiêu phần trăm?"
    )

    assert result.ok
    difference = result.ast.expression
    assert isinstance(difference, Arithmetic)
    assert difference.operator == ArithmeticOperator.SUBTRACT
    assert isinstance(difference.left, Arithmetic)
    assert difference.left.operator == ArithmeticOperator.DIVIDE
    assert isinstance(difference.right, Arithmetic)
    assert difference.right.operator == ArithmeticOperator.DIVIDE


def test_percentage_movement_between_periods_is_growth_not_subtraction() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"AAA": "AAA"}),
    )

    result = parser.parse(
        "Tỷ lệ biến động tổng tài sản của AAA giữa năm 2020 và năm 2024 "
        "là bao nhiêu phần trăm?"
    )

    assert result.ok
    assert isinstance(result.ast.expression, Arithmetic)
    assert result.ast.expression.operator == ArithmeticOperator.GROWTH


def test_temporal_cohort_accepts_o_ca_nam_and_ty_le_thay_doi_growth() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"DCM": "DCM", "DPM": "DPM", "PRT": "PRT"}),
    )

    result = parser.parse(
        "Trong nhóm DCM, DPM và PRT, xét các công ty có lưu chuyển tiền thuần từ "
        "hoạt động kinh doanh dương ở cả năm 2019 và 2020, trung bình tỷ lệ thay "
        "đổi doanh thu thuần năm 2020 so với năm 2019 là bao nhiêu %?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert isinstance(aggregate.expression, Filter)
    assert isinstance(aggregate.expression.predicate, QuantifiedPredicate)
    assert aggregate.expression.predicate.quantifier == PredicateQuantifier.ALL
    projection = aggregate.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.GROWTH


def test_multi_predicate_cohort_precedes_temporal_projection_and_average() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"AAA": "AAA", "BBB": "BBB", "CCC": "CCC"}),
    )

    result = parser.parse(
        "Trong năm 2024, các công ty AAA, BBB và CCC có lợi nhuận sau thuế "
        "dương và hệ số chuyển đổi lợi nhuận (CFO/LNST) lớn hơn 1 đạt tốc độ "
        "tăng trưởng tổng tài sản bình quân là bao nhiêu phần trăm so với năm "
        "2023?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert isinstance(aggregate.expression, Filter)
    predicate = aggregate.expression.predicate
    assert isinstance(predicate, LogicalPredicate)
    assert predicate.operator == LogicalOperator.AND
    assert len(predicate.predicates) == 2
    projection = aggregate.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.GROWTH
    assert projection.left.periods == ("2024",)
    assert projection.right.periods == ("2023",)


def test_multi_predicate_route_requires_explicit_conjunction() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"AAA": "AAA", "BBB": "BBB", "CCC": "CCC"}),
    )

    result = parser.parse(
        "Trong năm 2024, các công ty AAA, BBB và CCC có lợi nhuận sau thuế "
        "dương, hệ số chuyển đổi lợi nhuận (CFO/LNST) lớn hơn 1 đạt tốc độ "
        "tăng trưởng tổng tài sản bình quân là bao nhiêu phần trăm so với năm "
        "2023?"
    )

    assert not result.ok


def test_explicit_ratio_same_metric_roles_fail_closed() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"MSR": "MSR", "GVR": "GVR", "AAA": "AAA"}),
    )

    result = parser.parse(
        "Trung bình tỷ trọng ngoại tệ USD trong tổng dư lượng ngoại tệ cuối năm "
        "2023 của MSR, GVR và AAA là bao nhiêu phần trăm?"
    )

    assert not result.ok
    assert result.reason == "EXPLICIT_RATIO_ROLE_COLLISION"


def test_period_comparison_filter_precedes_ratio_change_and_average() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"DCM": "DCM", "DPM": "DPM", "PRT": "PRT"}),
    )

    result = parser.parse(
        "Trong nhóm DCM, DPM và PRT, xét các công ty có doanh thu thuần năm 2020 "
        "cao hơn năm 2019, mức thay đổi trung bình của tỷ lệ lợi nhuận gộp trên "
        "doanh thu thuần từ năm 2019 đến năm 2020 là bao nhiêu điểm phần trăm?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert isinstance(aggregate.expression, Filter)
    assert isinstance(aggregate.expression.predicate, Comparison)
    assert aggregate.expression.predicate.left.periods == ("2020",)
    assert aggregate.expression.predicate.right.periods == ("2019",)
    projection = aggregate.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.SUBTRACT


def test_inner_multi_period_sign_filter_does_not_hide_trailing_sum() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator(
            {"HPG": "HPG", "HSG": "HSG", "MSR": "MSR", "NKG": "NKG"}
        ),
    )

    result = parser.parse(
        "Trong nhóm HPG, HSG, MSR và NKG, xét các công ty có tỷ lệ lợi nhuận "
        "sau thuế trên doanh thu thuần dương trong cả ba năm 2020, 2021 và 2022, "
        "tổng doanh thu thuần năm 2022 là bao nhiêu nghìn tỷ đồng?"
    )

    assert result.ok
    aggregate = result.ast.expression
    assert isinstance(aggregate, Aggregate)
    assert aggregate.function == AggregateFunction.SUM
    assert isinstance(aggregate.expression, Filter)
    assert isinstance(aggregate.expression.predicate, QuantifiedPredicate)
    assert aggregate.expression.predicate.quantifier == PredicateQuantifier.ALL
    projection = aggregate.expression.expression
    assert isinstance(projection, MetricRef)
    assert projection.metric_id == "net_revenue"
    assert projection.periods == ("2022",)


def test_filtered_accrual_ratio_preserves_nested_period_average() -> None:
    parser = SemanticParser(
        load_ontology(),
        LegacyVietnameseAnnotator({"DLG": "DLG", "HHV": "HHV", "VSC": "VSC"}),
    )

    result = parser.parse(
        "Trong nhóm DLG, HHV và VSC, xét các công ty có lợi nhuận sau thuế dương "
        "năm 2020, trung bình tỷ lệ của chênh lệch giữa lợi nhuận sau thuế và lưu "
        "chuyển tiền thuần từ hoạt động kinh doanh năm 2020 trên trung bình tổng "
        "tài sản cuối năm 2019 và cuối năm 2020 là bao nhiêu %?"
    )

    assert result.ok
    outer = result.ast.expression
    assert isinstance(outer, Aggregate)
    assert isinstance(outer.expression, Filter)
    assert isinstance(outer.expression.predicate, Comparison)
    projection = outer.expression.expression
    assert isinstance(projection, Arithmetic)
    assert projection.operator == ArithmeticOperator.DIVIDE
    assert isinstance(projection.left, Arithmetic)
    assert projection.left.operator == ArithmeticOperator.SUBTRACT
    assert isinstance(projection.right, Aggregate)
    assert projection.right.axis == Axis.PERIOD
    assert projection.right.members == ("2019", "2020")
