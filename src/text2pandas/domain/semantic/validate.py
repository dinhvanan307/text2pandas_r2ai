"""Structural and type-shape validation for unbound semantic ASTs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .ast import (
    Aggregate,
    Arithmetic,
    Comparison,
    Exists,
    Expression,
    Filter,
    FormulaCall,
    Literal,
    LogicalPredicate,
    MetricRef,
    Predicate,
    QuantifiedPredicate,
    QuestionAST,
    Rank,
    SelectAtArg,
    Unary,
)
from .types import AggregateFunction, Axis, Dimension, ResultKind

_PERIOD = re.compile(r"^(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01]))?$")


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    path: str
    code: str
    message: str


def validate_question_ast(ast: QuestionAST) -> tuple[SemanticIssue, ...]:
    issues: list[SemanticIssue] = []
    if ast.schema_version != 3:
        issues.append(_issue("$", "SCHEMA_VERSION", "schema_version must equal 3"))
    if not ast.question.strip():
        issues.append(_issue("$.question", "EMPTY_QUESTION", "question must not be empty"))
    _validate_expression(ast.expression, "$.expression", issues)

    if ast.output.result_kind == ResultKind.ENTITY and ast.output.unit.dimension != Dimension.ENTITY:
        issues.append(_issue("$.output", "ENTITY_OUTPUT_UNIT", "entity result requires entity unit"))
    if ast.output.result_kind == ResultKind.PERIOD and ast.output.unit.dimension != Dimension.PERIOD:
        issues.append(_issue("$.output", "PERIOD_OUTPUT_UNIT", "period result requires period unit"))
    if ast.output.result_kind == ResultKind.SCALAR and ast.output.unit.dimension in (
        Dimension.ENTITY,
        Dimension.PERIOD,
    ):
        issues.append(_issue("$.output", "SCALAR_OUTPUT_UNIT", "scalar result cannot use set unit"))
    return tuple(issues)


def _validate_expression(expression: Expression, path: str, issues: list[SemanticIssue]) -> None:
    if isinstance(expression, MetricRef):
        if not expression.metric_id.strip():
            issues.append(_issue(path, "EMPTY_METRIC_ID", "metric_id must not be empty"))
        if len(set(expression.entities)) != len(expression.entities):
            issues.append(_issue(path, "DUPLICATE_ENTITY", "entities must be unique"))
        if len(set(expression.periods)) != len(expression.periods):
            issues.append(_issue(path, "DUPLICATE_PERIOD", "periods must be unique"))
        for index, period in enumerate(expression.periods):
            if not _PERIOD.match(period):
                issues.append(
                    _issue(f"{path}.periods[{index}]", "INVALID_PERIOD", f"invalid period: {period}")
                )
        return
    if isinstance(expression, Literal):
        if not math.isfinite(expression.value):
            issues.append(_issue(path, "NON_FINITE_LITERAL", "literal must be finite"))
        if not expression.unit.is_known:
            issues.append(_issue(path, "UNKNOWN_LITERAL_UNIT", "literal unit must be known"))
        return
    if isinstance(expression, Arithmetic):
        _validate_expression(expression.left, f"{path}.left", issues)
        _validate_expression(expression.right, f"{path}.right", issues)
        return
    if isinstance(expression, Unary):
        _validate_expression(expression.expression, f"{path}.expression", issues)
        return
    if isinstance(expression, FormulaCall):
        if not expression.formula_id.strip():
            issues.append(_issue(path, "EMPTY_FORMULA_ID", "formula_id must not be empty"))
        _validate_expression(expression.expression, f"{path}.expression", issues)
        return
    if isinstance(expression, Aggregate):
        if len(expression.members) < 2:
            issues.append(_issue(path, "AGGREGATE_ARITY", "aggregate requires at least two members"))
        if len(set(expression.members)) != len(expression.members):
            issues.append(_issue(path, "DUPLICATE_MEMBER", "aggregate members must be unique"))
        if expression.function == AggregateFunction.COUNT and isinstance(expression.expression, Literal):
            issues.append(_issue(path, "COUNT_LITERAL", "count must operate on evidence, not a literal"))
        _validate_expression(expression.expression, f"{path}.expression", issues)
        return
    if isinstance(expression, Filter):
        if not expression.members:
            issues.append(_issue(path, "EMPTY_FILTER_DOMAIN", "filter requires a finite domain"))
        _validate_predicate(expression.predicate, f"{path}.predicate", issues)
        _validate_expression(expression.expression, f"{path}.expression", issues)
        return
    if isinstance(expression, Rank):
        if len(expression.members) < 2:
            issues.append(_issue(path, "RANK_ARITY", "rank requires at least two members"))
        if expression.limit < 1 or expression.limit > len(expression.members):
            issues.append(_issue(path, "RANK_LIMIT", "rank limit must fit its domain"))
        _validate_expression(expression.by, f"{path}.by", issues)
        return
    if isinstance(expression, SelectAtArg):
        _validate_expression(expression.rank, f"{path}.rank", issues)
        _validate_expression(expression.expression, f"{path}.expression", issues)
        if not _references_axis(expression.expression, expression.rank.axis):
            issues.append(
                _issue(
                    path,
                    "SELECT_EXPRESSION_AXIS",
                    "selected expression must reference the ranked axis",
                )
            )
        return
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def _validate_predicate(predicate: Predicate, path: str, issues: list[SemanticIssue]) -> None:
    if isinstance(predicate, Comparison):
        _validate_expression(predicate.left, f"{path}.left", issues)
        _validate_expression(predicate.right, f"{path}.right", issues)
        return
    if isinstance(predicate, Exists):
        _validate_expression(predicate.expression, f"{path}.expression", issues)
        return
    if isinstance(predicate, LogicalPredicate):
        if len(predicate.predicates) < 2:
            issues.append(_issue(path, "LOGICAL_ARITY", "logical predicate requires two clauses"))
        for index, value in enumerate(predicate.predicates):
            _validate_predicate(value, f"{path}.predicates[{index}]", issues)
        return
    if isinstance(predicate, QuantifiedPredicate):
        _validate_predicate(predicate.predicate, f"{path}.predicate", issues)
        return
    raise TypeError(f"unsupported predicate: {type(predicate).__name__}")


def _references_axis(expression: Expression, axis: Axis) -> bool:
    if isinstance(expression, MetricRef):
        return bool(expression.entities if axis == Axis.ENTITY else expression.periods)
    if isinstance(expression, Arithmetic):
        return _references_axis(expression.left, axis) or _references_axis(expression.right, axis)
    if isinstance(expression, Unary):
        return _references_axis(expression.expression, axis)
    if isinstance(expression, FormulaCall):
        return _references_axis(expression.expression, axis)
    if isinstance(expression, Aggregate):
        return expression.axis == axis or _references_axis(expression.expression, axis)
    if isinstance(expression, Filter):
        return expression.axis == axis or _references_axis(expression.expression, axis)
    if isinstance(expression, Rank):
        return expression.axis == axis or _references_axis(expression.by, axis)
    if isinstance(expression, SelectAtArg):
        return _references_axis(expression.rank, axis) or _references_axis(expression.expression, axis)
    return False


def _issue(path: str, code: str, message: str) -> SemanticIssue:
    return SemanticIssue(path, code, message)
