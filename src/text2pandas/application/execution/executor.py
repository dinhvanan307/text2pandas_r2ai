"""Generic visitor over a jointly bound semantic expression."""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise
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
    RollingAverage,
    RollingGrowth,
    SelectAtArg,
    Unary,
    iter_metric_refs,
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
            selection_signatures = self._selection_signatures(
                bound.plan.ast.expression,
                "$.expression",
                bound,
            )
            output = bound.plan.ast.output
            if isinstance(value, MemberValue):
                if len(value.members) != 1:
                    raise ExecutionError("NON_SCALAR_MEMBER_RESULT")
                answer = value.members[0]
                return ExecutionResult(
                    "OK",
                    answer=answer,
                    unit=output.unit,
                    trace=(
                        {
                            "stage": "TYPED_EXECUTE",
                            "member": answer,
                            "selection_signatures": list(selection_signatures),
                        },
                    ),
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
                        "selection_signatures": list(selection_signatures),
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
        if isinstance(expression, RollingAverage):
            if expression.window != 2:
                raise ExecutionError("ROLLING_AVERAGE_WINDOW_UNSUPPORTED")
            child = _numeric(
                self._evaluate(expression.expression, f"{path}.expression", bound)
            )
            return _rolling_average(child)
        if isinstance(expression, RollingGrowth):
            child = _numeric(
                self._evaluate(expression.expression, f"{path}.expression", bound)
            )
            return _rolling_growth(child)
        if isinstance(expression, FormulaCall):
            return self._evaluate(expression.expression, f"{path}.expression", bound)
        if isinstance(expression, Aggregate):
            child = _numeric(self._evaluate(expression.expression, f"{path}.expression", bound))
            return _aggregate(expression.function, child)
        if isinstance(expression, Rank):
            child = _numeric(self._evaluate(expression.by, f"{path}.by", bound))
            return _rank(expression, child)
        if isinstance(expression, SelectAtArg):
            rank_values = _numeric(
                self._evaluate(expression.rank.by, f"{path}.rank.by", bound)
            )
            ranked = _rank(expression.rank, rank_values)
            selected_values = _numeric(
                self._evaluate(expression.expression, f"{path}.expression", bound)
            )
            _validate_projected_domain(expression, selected_values)
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

    def _selection_signatures(
        self,
        expression: Expression,
        path: str,
        bound: BoundExecutionPlan,
    ) -> tuple[dict[str, object], ...]:
        signatures: list[dict[str, object]] = []
        for select_path, select in _iter_select_at_arg(expression, path):
            rank_values = _numeric(
                self._evaluate(select.rank.by, f"{select_path}.rank.by", bound)
            )
            ranked = _rank(select.rank, rank_values)
            selected_values = _numeric(
                self._evaluate(select.expression, f"{select_path}.expression", bound)
            )
            _validate_projected_domain(select, selected_values)
            bound_rank_keys = _series_members(rank_values, select.rank.axis)
            projected_keys = _series_members(selected_values, select.rank.axis)
            expected_rank_keys = (
                bound_rank_keys
                if isinstance(select.rank.by, Filter)
                else tuple(sorted(select.rank.members))
            )
            signatures.append(
                {
                    "path": select_path,
                    "axis": select.rank.axis.value,
                    "source_domain_keys": list(select.rank.members),
                    "expected_keys": list(expected_rank_keys),
                    "bound_rank_keys": list(bound_rank_keys),
                    "projected_keys": list(projected_keys),
                    "selected_key": ranked.members[0],
                    "rank_metric_ids": sorted(
                        {ref.metric_id for ref in iter_metric_refs(select.rank.by)}
                    ),
                    "projected_metric_ids": sorted(
                        {ref.metric_id for ref in iter_metric_refs(select.expression)}
                    ),
                }
            )
        return tuple(signatures)

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


def _rolling_average(series: SeriesValue) -> SeriesValue:
    grouped: dict[str, list[tuple[int, Scope, QuantityValue]]] = {}
    for scope, value in series.values.items():
        if scope.entity is None or scope.period is None:
            raise ExecutionError("ROLLING_AVERAGE_REQUIRES_ENTITY_PERIOD_SCOPE")
        try:
            period = int(scope.period[:4])
        except ValueError as error:
            raise ExecutionError("ROLLING_AVERAGE_PERIOD_INVALID") from error
        grouped.setdefault(scope.entity, []).append((period, scope, value))
    output: dict[Scope, QuantityValue] = {}
    for values in grouped.values():
        ordered = sorted(values)
        if len(ordered) < 2:
            raise ExecutionError("ROLLING_AVERAGE_REQUIRES_TWO_PERIODS")
        for previous, current in pairwise(ordered):
            combined = arithmetic_quantity(
                ArithmeticOperator.ADD,
                previous[2],
                current[2],
            )
            output[current[1]] = QuantityValue(combined.value / Decimal(2), combined.unit)
    return _series(output)


def _rolling_growth(series: SeriesValue) -> SeriesValue:
    grouped: dict[str, list[tuple[int, Scope, QuantityValue]]] = {}
    for scope, value in series.values.items():
        if scope.entity is None or scope.period is None:
            raise ExecutionError("ROLLING_GROWTH_REQUIRES_ENTITY_PERIOD_SCOPE")
        try:
            period = int(scope.period[:4])
        except ValueError as error:
            raise ExecutionError("ROLLING_GROWTH_PERIOD_INVALID") from error
        grouped.setdefault(scope.entity, []).append((period, scope, value))
    output: dict[Scope, QuantityValue] = {}
    for values in grouped.values():
        ordered = sorted(values)
        if len(ordered) < 2:
            raise ExecutionError("ROLLING_GROWTH_REQUIRES_TWO_PERIODS")
        for previous, current in pairwise(ordered):
            output[current[1]] = arithmetic_quantity(
                ArithmeticOperator.GROWTH,
                current[2],
                previous[2],
            )
    return _series(output)


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
    projected = _align_on_shared_axis(left, right)
    if projected is not None:
        return projected
    if len(left.values) == len(right.values) == 1:
        return [(Scope(), next(iter(left.values.values())), next(iter(right.values.values())))]
    raise ExecutionError(f"SERIES_SCOPE_MISMATCH:{sorted(left.values)}:{sorted(right.values)}")


def _align_on_shared_axis(
    left: SeriesValue, right: SeriesValue
) -> list[tuple[Scope, QuantityValue, QuantityValue]] | None:
    """Pair two temporal/entity slices while retaining their shared axis.

    A vectorized change such as ``value(entity, 2020) - value(entity, 2019)``
    has different full scopes but one unambiguous entity key.  The resulting
    series is entity-scoped.  The symmetric period-scoped case is supported as
    well; non-unique projections continue to fail closed.
    """

    for attribute in ("entity", "period"):
        left_by_key = _unique_scope_values(left, attribute)
        right_by_key = _unique_scope_values(right, attribute)
        if left_by_key is None or right_by_key is None or set(left_by_key) != set(right_by_key):
            continue
        output: list[tuple[Scope, QuantityValue, QuantityValue]] = []
        for key in sorted(left_by_key):
            left_scope, left_value = left_by_key[key]
            right_scope, right_value = right_by_key[key]
            scope = (
                Scope(entity=key)
                if attribute == "entity"
                else Scope(period=key)
            )
            other_left = left_scope.period if attribute == "entity" else left_scope.entity
            other_right = right_scope.period if attribute == "entity" else right_scope.entity
            if other_left == other_right:
                scope = left_scope
            output.append((scope, left_value, right_value))
        return output
    return None


def _unique_scope_values(
    values: SeriesValue, attribute: str
) -> dict[str, tuple[Scope, QuantityValue]] | None:
    output: dict[str, tuple[Scope, QuantityValue]] = {}
    for scope, value in values.values.items():
        key = getattr(scope, attribute)
        if key is None or key in output:
            return None
        output[key] = (scope, value)
    return output


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
    bound_members = tuple(member for _, member in ranked)
    if len(bound_members) != len(set(bound_members)):
        raise ExecutionError("RANK_DOMAIN_DUPLICATE_KEY")
    if (
        expression.members
        and not isinstance(expression.by, Filter)
        and set(bound_members) != set(expression.members)
    ):
        raise ExecutionError("RANK_DOMAIN_INCOMPLETE")
    if expression.direction.value == "descending":
        ranked.sort(key=lambda item: (-item[0], item[1]))
    else:
        ranked.sort(key=lambda item: (item[0], item[1]))
    if expression.limit == 1 and len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise ExecutionError("RANK_KEY_TIE")
    return MemberValue(expression.axis, tuple(member for _, member in ranked[: expression.limit]))


def _validate_projected_domain(
    expression: SelectAtArg, selected_values: SeriesValue
) -> None:
    projected = _series_members(selected_values, expression.rank.axis)
    if expression.rank.members and set(projected) != set(expression.rank.members):
        raise ExecutionError("PROJECTED_DOMAIN_MISMATCH")


def _series_members(series: SeriesValue, axis: Axis) -> tuple[str, ...]:
    members: list[str] = []
    for scope in series.values:
        member = scope.member(axis)
        if member is None:
            raise ExecutionError(f"RANK_SCOPE_MISSING:{axis}")
        members.append(member)
    return tuple(sorted(members))


def _iter_select_at_arg(
    expression: Expression, path: str
) -> list[tuple[str, SelectAtArg]]:
    if isinstance(expression, (MetricRef, Literal)):
        return []
    if isinstance(expression, Arithmetic):
        return [
            *_iter_select_at_arg(expression.left, f"{path}.left"),
            *_iter_select_at_arg(expression.right, f"{path}.right"),
        ]
    if isinstance(expression, (Unary, RollingAverage, RollingGrowth, FormulaCall, Aggregate)):
        return _iter_select_at_arg(expression.expression, f"{path}.expression")
    if isinstance(expression, Rank):
        return _iter_select_at_arg(expression.by, f"{path}.by")
    if isinstance(expression, SelectAtArg):
        return [
            (path, expression),
            *_iter_select_at_arg(expression.rank.by, f"{path}.rank.by"),
            *_iter_select_at_arg(expression.expression, f"{path}.expression"),
        ]
    if isinstance(expression, Filter):
        return [
            *_iter_select_at_arg(expression.expression, f"{path}.expression"),
            *_iter_predicate_select_at_arg(expression.predicate, f"{path}.predicate"),
        ]
    raise ExecutionError(f"UNSUPPORTED_EXPRESSION:{type(expression).__name__}")


def _iter_predicate_select_at_arg(
    predicate: Predicate, path: str
) -> list[tuple[str, SelectAtArg]]:
    if isinstance(predicate, Comparison):
        return [
            *_iter_select_at_arg(predicate.left, f"{path}.left"),
            *_iter_select_at_arg(predicate.right, f"{path}.right"),
        ]
    if isinstance(predicate, Exists):
        return _iter_select_at_arg(predicate.expression, f"{path}.expression")
    if isinstance(predicate, LogicalPredicate):
        return [
            item
            for index, child in enumerate(predicate.predicates)
            for item in _iter_predicate_select_at_arg(
                child, f"{path}.predicates[{index}]"
            )
        ]
    if isinstance(predicate, QuantifiedPredicate):
        return _iter_predicate_select_at_arg(
            predicate.predicate, f"{path}.predicate"
        )
    raise ExecutionError(f"UNSUPPORTED_PREDICATE:{type(predicate).__name__}")


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
