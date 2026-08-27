from __future__ import annotations

from dataclasses import replace

from text2pandas.application.parsing import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
    SemanticParser,
)
from text2pandas.domain.semantic import (
    Aggregate,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Basis,
    Dimension,
    Filter,
    FormulaCall,
    MetricRef,
    RankDirection,
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


def _parse(question: str, annotations: QuestionAnnotations):
    return SemanticParser(load_ontology(), StaticAnnotator(annotations)).parse(question)


def test_direct_metric_compiles_to_canonical_metric_ref() -> None:
    result = _parse("Tổng tài sản VCB năm 2024 là bao nhiêu tỷ đồng?", _annotations())

    assert result.ok
    assert isinstance(result.ast.expression, MetricRef)
    assert result.ast.expression.metric_id == "total_assets"
    assert result.ast.expression.entities == ("VCB",)


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
