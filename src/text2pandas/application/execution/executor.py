"""Generic visitor over a jointly bound semantic expression."""

from __future__ import annotations

from decimal import Decimal
from statistics import median
from types import MappingProxyType

from text2pandas.application.binding import BoundExecutionPlan
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Comparison,
    ComparisonOperator,
    Exists,
    Filter,
    FormulaCall,
    Literal,
    LogicalOperator,
    LogicalPredicate,
    MetricRef,
    PredicateQuantifier,
    QuantifiedPredicate,
    Rank,
    SelectAtArg,
    Unary,
)
from text2pandas.domain.semantic.ast import Expression, Predicate

from .contracts import ExecutionResult, MemberValue, QuantityValue, Scope, SeriesValue
from .quantities import (
    QuantityError,
    arithmetic_quantity,
    comparable,
    convert_quantity,
    unary_quantity,
)


class ExecutionError(ValueError):
    pass


class TypedExecutor:
    def execute(self, bound: BoundExecutionPlan) -> ExecutionResult:
        try:
            value = self._evaluate(bound.plan.ast.expression, "$.expression", bound)
            output = bound.plan.ast.output
            if isinstance(value, MemberValue):
                if len(value.members) != 1:
                    raise ExecutionError("NON_SCALAR_MEMBER_RESULT")
                answer = value.members[0]
                return ExecutionResult(
                    "OK",
                    answer=answer,
                    unit=output.unit,
                    trace=({"stage": "TYPED_EXECUTE", "member": answer},),
                )
            if len(value.values) != 1:
                raise ExecutionError(f"NON_SCALAR_NUMERIC_RESULT:{len(value.values)}")
            quantity = next(iter(value.values.values()))
            converted = convert_quantity(quantity, output.unit)
            return ExecutionResult(
                "OK",
                answer=converted.value,
                unit=converted.unit,
                trace=(
                    {
                        "stage": "TYPED_EXECUTE",
                        "answer": str(converted.value),
                        "unit": converted.unit.to_dict(),
                    },
                ),
            )
        except (ExecutionError, QuantityError, ArithmeticError) as error:
            return ExecutionResult("ABSTAIN", reason=str(error))

    def _evaluate(
        self, expression: Expression, path: str, bound: BoundExecutionPlan
    ) -> SeriesValue | MemberValue:
        if isinstance(expression, MetricRef):
            metric_values: dict[Scope, QuantityValue] = {}
            for operand in bound.operands.values():
                request = operand.request
                if path not in request.consumers:
                    continue
                candidate = operand.candidate
                metric_values[Scope(request.entity, request.period)] = QuantityValue(
                    candidate.value, candidate.unit
                )
            if not metric_values:
                raise ExecutionError(f"UNBOUND_METRIC_PATH:{path}:{expression.metric_id}")
            return SeriesValue(MappingProxyType(metric_values))
        if isinstance(expression, Literal):
            return _series(
                {Scope(): QuantityValue(Decimal(str(expression.value)), expression.unit)}
            )
        if isinstance(expression, Arithmetic):
            left = _numeric(self._evaluate(expression.left, f"{path}.left", bound))
            right = _numeric(self._evaluate(expression.right, f"{path}.right", bound))
            return _combine_series(left, right, expression.operator)
        if isinstance(expression, Unary):
            child = _numeric(self._evaluate(expression.expression, f"{path}.expression", bound))
            return _series(
                {
                    scope: unary_quantity(expression.operator, value)
                    for scope, value in child.values.items()
                }
            )
        if isinstance(expression, FormulaCall):
            return self._evaluate(expression.expression, f"{path}.expression", bound)
        if isinstance(expression, Aggregate):
            child = _numeric(self._evaluate(expression.expression, f"{path}.expression", bound))
            return _aggregate(expression.function, child)
        if isinstance(expression, Rank):
            child = _numeric(self._evaluate(expression.by, f"{path}.by", bound))
            return _rank(expression, child)
        if isinstance(expression, SelectAtArg):
            ranked = self._evaluate(expression.rank, f"{path}.rank", bound)
            if not isinstance(ranked, MemberValue) or len(ranked.members) != 1:
                raise ExecutionError("SELECT_AT_ARG_RANK_NOT_SCALAR")
            selected_values = _numeric(
                self._evaluate(expression.expression, f"{path}.expression", bound)
            )
            selected = {
                scope: value
                for scope, value in selected_values.values.items()
                if scope.member(ranked.axis) == ranked.members[0]
            }
            if len(selected) != 1:
                raise ExecutionError(f"SELECT_AT_ARG_VALUE_CARDINALITY:{len(selected)}")
            return _series({Scope(): next(iter(selected.values()))})
        if isinstance(expression, Filter):
            decisions = self._predicate(expression.predicate, f"{path}.predicate", bound)
            filtered_values = _numeric(
                self._evaluate(expression.expression, f"{path}.expression", bound)
            )
            selected = {
                scope: value
                for scope, value in filtered_values.values.items()
                if _decision_for_scope(decisions, scope, expression.axis)
            }
            return _series(selected)
        raise ExecutionError(f"UNSUPPORTED_EXPRESSION:{type(expression).__name__}")

    def _predicate(
        self, predicate: Predicate, path: str, bound: BoundExecutionPlan
    ) -> dict[Scope, bool]:
        if isinstance(predicate, Comparison):
            left = _numeric(self._evaluate(predicate.left, f"{path}.left", bound))
            right = _numeric(self._evaluate(predicate.right, f"{path}.right", bound))
            pairs = _align(left, right)
            return {
                scope: _compare(predicate.operator, comparable(a).value, comparable(b).value)
                for scope, a, b in pairs
            }
        if isinstance(predicate, Exists):
            value = _numeric(self._evaluate(predicate.expression, f"{path}.expression", bound))
            return {scope: not predicate.negated for scope in value.values}
        if isinstance(predicate, LogicalPredicate):
            children = [
                self._predicate(value, f"{path}.predicates[{index}]", bound)
                for index, value in enumerate(predicate.predicates)
            ]
            scopes = set().union(*(set(child) for child in children))
            return {
                scope: (
                    all(child.get(scope, False) for child in children)
                    if predicate.operator == LogicalOperator.AND
                    else any(child.get(scope, False) for child in children)
                )
                for scope in scopes
            }
        if isinstance(predicate, QuantifiedPredicate):
            child = self._predicate(predicate.predicate, f"{path}.predicate", bound)
            grouped: dict[Scope, list[bool]] = {}
            for scope, decision in child.items():
                grouped.setdefault(scope.without(predicate.axis), []).append(decision)
            reducer = all if predicate.quantifier == PredicateQuantifier.ALL else any
            return {scope: reducer(values) for scope, values in grouped.items()}
        raise ExecutionError(f"UNSUPPORTED_PREDICATE:{type(predicate).__name__}")


def _combine_series(
    left: SeriesValue, right: SeriesValue, operator: ArithmeticOperator
) -> SeriesValue:
    return _series(
        {scope: arithmetic_quantity(operator, a, b) for scope, a, b in _align(left, right)}
    )


def _align(
    left: SeriesValue, right: SeriesValue
) -> list[tuple[Scope, QuantityValue, QuantityValue]]:
    if set(left.values) == set(right.values):
        return [(scope, left.values[scope], right.values[scope]) for scope in sorted(left.values)]
    scalar = Scope()
    if set(left.values) == {scalar}:
        return [
            (scope, left.values[scalar], value) for scope, value in sorted(right.values.items())
        ]
    if set(right.values) == {scalar}:
        return [
            (scope, value, right.values[scalar]) for scope, value in sorted(left.values.items())
        ]
    if len(left.values) == len(right.values) == 1:
        return [(Scope(), next(iter(left.values.values())), next(iter(right.values.values())))]
    raise ExecutionError(f"SERIES_SCOPE_MISMATCH:{sorted(left.values)}:{sorted(right.values)}")


def _aggregate(function: AggregateFunction, series: SeriesValue) -> SeriesValue:
    values = list(series.values.values())
    if not values:
        raise ExecutionError("AGGREGATE_EMPTY")
    if function == AggregateFunction.COUNT:
        from text2pandas.domain.semantic import Dimension, UnitSpec

        return _series({Scope(): QuantityValue(Decimal(len(values)), UnitSpec(Dimension.COUNT))})
    comparable_values = [comparable(value) for value in values]
    dimensions = {value.unit.dimension for value in comparable_values}
    if len(dimensions) != 1:
        raise ExecutionError(f"AGGREGATE_DIMENSION_MISMATCH:{sorted(dimensions)}")
    if function in (AggregateFunction.SUM, AggregateFunction.AVERAGE):
        total = sum((value.value for value in comparable_values), start=Decimal(0))
        if function == AggregateFunction.AVERAGE:
            total /= len(comparable_values)
        return _series({Scope(): QuantityValue(total, comparable_values[0].unit)})
    if function == AggregateFunction.MEDIAN:
        median_value = median(value.value for value in comparable_values)
        return _series({Scope(): QuantityValue(median_value, comparable_values[0].unit)})
    chooser = max if function == AggregateFunction.MAXIMUM else min
    extreme_value = chooser(comparable_values, key=lambda value: value.value)
    return _series({Scope(): extreme_value})


def _rank(expression: Rank, series: SeriesValue) -> MemberValue:
    ranked: list[tuple[Decimal, str]] = []
    for scope, value in series.values.items():
        member = scope.member(expression.axis)
        if member is None:
            raise ExecutionError(f"RANK_SCOPE_MISSING:{expression.axis}")
        ranked.append((comparable(value).value, member))
    if expression.direction.value == "descending":
        ranked.sort(key=lambda item: (-item[0], item[1]))
    else:
        ranked.sort(key=lambda item: (item[0], item[1]))
    return MemberValue(expression.axis, tuple(member for _, member in ranked[: expression.limit]))


def _compare(operator: ComparisonOperator, left: Decimal, right: Decimal) -> bool:
    return {
        ComparisonOperator.EQ: left == right,
        ComparisonOperator.NE: left != right,
        ComparisonOperator.GT: left > right,
        ComparisonOperator.GE: left >= right,
        ComparisonOperator.LT: left < right,
        ComparisonOperator.LE: left <= right,
    }[operator]


def _numeric(value: SeriesValue | MemberValue) -> SeriesValue:
    if isinstance(value, MemberValue):
        raise ExecutionError("NUMERIC_VALUE_REQUIRED")
    return value


def _decision_for_scope(decisions: dict[Scope, bool], scope: Scope, axis: Axis) -> bool:
    if scope in decisions:
        return decisions[scope]
    projected = Scope(scope.entity, None) if axis == Axis.ENTITY else Scope(None, scope.period)
    return decisions.get(projected, False)


def _series(values: dict[Scope, QuantityValue]) -> SeriesValue:
    return SeriesValue(MappingProxyType(values))
