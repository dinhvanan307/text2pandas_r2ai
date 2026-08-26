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
