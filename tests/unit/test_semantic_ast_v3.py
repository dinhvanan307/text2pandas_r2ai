from __future__ import annotations

from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Basis,
    Dimension,
    MetricBindingHint,
    MetricRef,
    OutputSpec,
    QuestionAST,
    Rank,
    RankDirection,
    ResultKind,
    SelectAtArg,
    UnitSpec,
    validate_question_ast,
)


def _money() -> UnitSpec:
    return UnitSpec(Dimension.MONEY, 9, "VND")


def test_question_ast_round_trips_nested_select_at_arg() -> None:
    entities = ("VCB", "BID", "CTG")
    ast = QuestionAST(
        question="Doanh nghiệp có tổng tài sản lớn nhất có lợi nhuận sau thuế bao nhiêu?",
        expression=SelectAtArg(
            rank=Rank(
                axis=Axis.ENTITY,
                members=entities,
                by=MetricRef("total_assets", entities=entities, periods=("2024",)),
                direction=RankDirection.DESCENDING,
            ),
            expression=MetricRef(
                "profit_after_tax",
                entities=entities,
                periods=("2024",),
                basis=Basis.CONSOLIDATED,
            ),
        ),
        output=OutputSpec(ResultKind.SCALAR, _money()),
        qid=101,
    )

    restored = QuestionAST.from_dict(ast.to_dict())

    assert restored == ast
    assert validate_question_ast(restored) == ()


def test_source_binding_round_trips_and_old_payload_remains_compatible() -> None:
    binding = MetricBindingHint(
        source_metric_id="source:penalty",
        source_build_id="a6-build",
        labels=("Chi phí phạt",),
        row_paths=("Chi phí khác › Chi phí phạt",),
        question_surface="chi phi phat",
    )
    ast = QuestionAST(
        question="Chi phí phạt?",
        expression=MetricRef(
            "source:penalty",
            entities=("SCR",),
            periods=("2017",),
            expected_unit=_money(),
            source_binding=binding,
        ),
        output=OutputSpec(ResultKind.SCALAR, _money()),
    )

    assert QuestionAST.from_dict(ast.to_dict()) == ast
    old_payload = ast.to_dict()
    old_payload["expression"].pop("source_binding")
    restored_old = QuestionAST.from_dict(old_payload)
    assert isinstance(restored_old.expression, MetricRef)
    assert restored_old.expression.source_binding is None


def test_ast_expresses_cross_entity_derived_average_without_new_engine() -> None:
    entities = ("VCB", "BID", "CTG")
    roe = Arithmetic(
        ArithmeticOperator.DIVIDE,
        MetricRef("profit_after_tax", entities=entities, periods=("2024",)),
        MetricRef("equity", entities=entities, periods=("2024",)),
    )
    ast = QuestionAST(
        question="ROE bình quân của VCB, BID và CTG năm 2024 là bao nhiêu?",
        expression=Aggregate(AggregateFunction.AVERAGE, Axis.ENTITY, roe, entities),
        output=OutputSpec(ResultKind.SCALAR, UnitSpec(Dimension.PERCENT)),
    )

    assert validate_question_ast(ast) == ()


def test_validator_rejects_invalid_rank_and_period() -> None:
    ast = QuestionAST(
        question="x",
        expression=Rank(
            Axis.PERIOD,
            ("2024",),
            MetricRef("revenue", periods=("24",)),
            RankDirection.DESCENDING,
            limit=2,
        ),
        output=OutputSpec(ResultKind.PERIOD, UnitSpec(Dimension.PERIOD)),
    )

    codes = {issue.code for issue in validate_question_ast(ast)}

    assert codes == {"INVALID_PERIOD", "RANK_ARITY", "RANK_LIMIT"}
