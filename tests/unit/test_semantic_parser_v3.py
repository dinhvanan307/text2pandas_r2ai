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


def test_unreviewed_divide_fails_closed() -> None:
    annotations = _annotations(operation=OperationKind.DIVIDE)
    result = _parse("Tổng tài sản trên vốn gì đó của VCB?", annotations)

    assert not result.ok
    assert result.reason == "UNREVIEWED_RELATIONAL_FORMULA"


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
