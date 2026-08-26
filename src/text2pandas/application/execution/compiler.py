"""Compile a bound semantic AST to the restricted pandas expression grammar."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from text2pandas.application.binding import BoundExecutionPlan
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Dimension,
    Filter,
    FormulaCall,
    Literal,
    MetricRef,
    Rank,
    RankDirection,
    SelectAtArg,
    Unary,
    UnaryOperator,
    UnitSpec,
)
from text2pandas.domain.semantic.ast import Expression

from .contracts import Scope


@dataclass(frozen=True, slots=True)
class PandasEvidence:
    variable: str
    table_uid: str
    document_id: str
    observation_uids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PandasProgram:
    query: str
    evidence: tuple[PandasEvidence, ...]


@dataclass(frozen=True, slots=True)
class CompilationResult:
    status: str
    program: PandasProgram | None = None
    reason: str | None = None
    trace: tuple[dict[str, object], ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(frozen=True, slots=True)
class _RenderedQuantity:
    expression: str
    unit: UnitSpec


@dataclass(frozen=True, slots=True)
class _RenderedSeries:
    values: dict[Scope, _RenderedQuantity]


@dataclass(frozen=True, slots=True)
class _RenderedRank:
    axis: Axis
    values: _RenderedSeries
    direction: RankDirection
    limit: int


class CompilationError(ValueError):
    pass


def compile_pandas(bound: BoundExecutionPlan) -> CompilationResult:
    tables = sorted({operand.candidate.table_uid for operand in bound.operands.values()})
    variables = {table_uid: f"df{index + 1}" for index, table_uid in enumerate(tables)}
    try:
        rendered = _render(bound.plan.ast.expression, "$.expression", bound, variables)
        output = bound.plan.ast.output
        if isinstance(rendered, _RenderedRank):
            query = _render_rank_member(rendered)
        else:
            if len(rendered.values) != 1:
                raise CompilationError(f"NON_SCALAR_NUMERIC_RESULT:{len(rendered.values)}")
            value = next(iter(rendered.values.values()))
            query = _convert(value, output.unit).expression
        evidence = _evidence(bound, variables)
        return CompilationResult(
            "OK",
            PandasProgram(query, evidence),
            trace=(
                {
                    "stage": "PANDAS_COMPILE",
                    "query_length": len(query),
                    "evidence_tables": len(evidence),
                },
            ),
        )
    except CompilationError as error:
        return CompilationResult("ABSTAIN", reason=str(error))


def _render(
    expression: Expression,
    path: str,
    bound: BoundExecutionPlan,
    variables: dict[str, str],
) -> _RenderedSeries | _RenderedRank:
    if isinstance(expression, MetricRef):
        values: dict[Scope, _RenderedQuantity] = {}
        for operand in bound.operands.values():
            request = operand.request
            if path not in request.consumers:
                continue
            candidate = operand.candidate
            variable = variables[candidate.table_uid]
            cell = (
                f"float({variable}[{variable}['observation_uid'] == "
                f"{candidate.observation_uid!r}]['value'].values[0])"
            )
            values[Scope(request.entity, request.period)] = _RenderedQuantity(cell, candidate.unit)
        if not values:
            raise CompilationError(f"UNBOUND_METRIC_PATH:{path}:{expression.metric_id}")
        return _RenderedSeries(values)
    if isinstance(expression, Literal):
        return _RenderedSeries(
            {Scope(): _RenderedQuantity(_number(Decimal(str(expression.value))), expression.unit)}
        )
    if isinstance(expression, Arithmetic):
        left = _numeric(_render(expression.left, f"{path}.left", bound, variables))
        right = _numeric(_render(expression.right, f"{path}.right", bound, variables))
        return _RenderedSeries(
            {scope: _arithmetic(expression.operator, a, b) for scope, a, b in _align(left, right)}
        )
    if isinstance(expression, Unary):
        child = _numeric(_render(expression.expression, f"{path}.expression", bound, variables))
        if expression.operator == UnaryOperator.ABSOLUTE:
            return _RenderedSeries(
                {
                    scope: _RenderedQuantity(f"abs({value.expression})", value.unit)
                    for scope, value in child.values.items()
                }
            )
        if expression.operator == UnaryOperator.NEGATE:
            return _RenderedSeries(
                {
                    scope: _RenderedQuantity(f"(-{value.expression})", value.unit)
                    for scope, value in child.values.items()
                }
            )
        raise CompilationError(f"UNSUPPORTED_UNARY:{expression.operator}")
    if isinstance(expression, FormulaCall):
        return _render(expression.expression, f"{path}.expression", bound, variables)
    if isinstance(expression, Aggregate):
        child = _numeric(_render(expression.expression, f"{path}.expression", bound, variables))
        return _render_aggregate(expression.function, child)
    if isinstance(expression, Rank):
        child = _numeric(_render(expression.by, f"{path}.by", bound, variables))
        return _RenderedRank(expression.axis, child, expression.direction, expression.limit)
    if isinstance(expression, SelectAtArg):
        rank = _render(expression.rank, f"{path}.rank", bound, variables)
        if not isinstance(rank, _RenderedRank) or rank.limit != 1:
            raise CompilationError("SELECT_AT_ARG_RANK_NOT_SCALAR")
        selected = _numeric(_render(expression.expression, f"{path}.expression", bound, variables))
        return _render_select_at_arg(rank, selected)
    if isinstance(expression, Filter):
        raise CompilationError("FILTER_PANDAS_COMPILER_NOT_PROMOTED")
    raise CompilationError(f"UNSUPPORTED_EXPRESSION:{type(expression).__name__}")


def _arithmetic(
    operator: ArithmeticOperator, left: _RenderedQuantity, right: _RenderedQuantity
) -> _RenderedQuantity:
    if operator in (ArithmeticOperator.ADD, ArithmeticOperator.SUBTRACT):
        left, right = _common(left, right)
        symbol = "+" if operator == ArithmeticOperator.ADD else "-"
        unit = left.unit
        if operator == ArithmeticOperator.SUBTRACT and unit.dimension == Dimension.PERCENT:
            unit = UnitSpec(Dimension.PERCENT_POINT)
        return _RenderedQuantity(f"({left.expression} {symbol} {right.expression})", unit)
    if operator == ArithmeticOperator.GROWTH:
        left, right = _common(left, right)
        return _RenderedQuantity(
            f"(({left.expression} - {right.expression}) / abs({right.expression}))",
            UnitSpec(Dimension.RATIO),
        )
    if operator == ArithmeticOperator.DIVIDE:
        left, right = _common(left, right)
        return _RenderedQuantity(
            f"({left.expression} / {right.expression})", UnitSpec(Dimension.RATIO)
        )
    if operator == ArithmeticOperator.MULTIPLY:
        if left.unit.dimension == Dimension.RATIO:
            return _RenderedQuantity(f"({left.expression} * {right.expression})", right.unit)
        if right.unit.dimension == Dimension.RATIO:
            return _RenderedQuantity(f"({left.expression} * {right.expression})", left.unit)
        raise CompilationError(
            f"MULTIPLY_DIMENSION_UNSUPPORTED:{left.unit.dimension}:{right.unit.dimension}"
        )
    raise CompilationError(f"UNSUPPORTED_ARITHMETIC:{operator}")


def _render_aggregate(function: AggregateFunction, series: _RenderedSeries) -> _RenderedSeries:
    values = list(series.values.values())
    if not values:
        raise CompilationError("AGGREGATE_EMPTY")
    if function == AggregateFunction.COUNT:
        return _RenderedSeries(
            {Scope(): _RenderedQuantity(str(len(values)), UnitSpec(Dimension.COUNT))}
        )
    base = [_comparable(value) for value in values]
    dimensions = {value.unit.dimension for value in base}
    if len(dimensions) != 1:
        raise CompilationError(f"AGGREGATE_DIMENSION_MISMATCH:{sorted(dimensions)}")
    if function in (AggregateFunction.SUM, AggregateFunction.AVERAGE):
        body = "(" + " + ".join(value.expression for value in base) + ")"
        if function == AggregateFunction.AVERAGE:
            body = f"({body} / {len(base)})"
    else:
        name = "max" if function == AggregateFunction.MAXIMUM else "min"
        body = f"{name}({', '.join(value.expression for value in base)})"
    return _RenderedSeries({Scope(): _RenderedQuantity(body, base[0].unit)})


def _render_select_at_arg(rank: _RenderedRank, selected: _RenderedSeries) -> _RenderedSeries:
    ranked = _by_member(rank.values, rank.axis)
    output = _by_member(selected, rank.axis)
    if set(ranked) != set(output):
        raise CompilationError("SELECT_AT_ARG_MEMBER_MISMATCH")
    name = "max" if rank.direction == RankDirection.DESCENDING else "min"
    comparable_ranked = {member: _comparable(value) for member, value in ranked.items()}
    winner = f"{name}({', '.join(value.expression for value in comparable_ranked.values())})"
    members = sorted(ranked)
    body = output[members[-1]].expression
    for member in reversed(members[:-1]):
        body = (
            f"({output[member].expression} if "
            f"{comparable_ranked[member].expression} == {winner} else {body})"
        )
    return _RenderedSeries({Scope(): _RenderedQuantity(body, output[members[0]].unit)})


def _render_rank_member(rank: _RenderedRank) -> str:
    if rank.limit != 1:
        raise CompilationError("RANK_MEMBER_NOT_SCALAR")
    if rank.axis != Axis.PERIOD:
        raise CompilationError("ENTITY_RESULT_NOT_NUMERIC")
    ranked = _by_member(rank.values, rank.axis)
    comparable_ranked = {member: _comparable(value) for member, value in ranked.items()}
    name = "max" if rank.direction == RankDirection.DESCENDING else "min"
    winner = f"{name}({', '.join(value.expression for value in comparable_ranked.values())})"
    members = sorted(ranked)
    body = f"float({int(members[-1][:4])})"
    for member in reversed(members[:-1]):
        body = (
            f"(float({int(member[:4])}) if "
            f"{comparable_ranked[member].expression} == {winner} else {body})"
        )
    return body


def _align(
    left: _RenderedSeries, right: _RenderedSeries
) -> list[tuple[Scope, _RenderedQuantity, _RenderedQuantity]]:
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
    raise CompilationError(f"SERIES_SCOPE_MISMATCH:{sorted(left.values)}:{sorted(right.values)}")


def _common(
    left: _RenderedQuantity, right: _RenderedQuantity
) -> tuple[_RenderedQuantity, _RenderedQuantity]:
    if left.unit.dimension != right.unit.dimension:
        raise CompilationError(f"DIMENSION_MISMATCH:{left.unit.dimension}:{right.unit.dimension}")
    if left.unit.dimension in (Dimension.MONEY, Dimension.SHARES):
        currency = left.unit.currency or right.unit.currency
        target = UnitSpec(left.unit.dimension, 0, currency)
        return _convert(left, target), _convert(right, target)
    return left, right


def _comparable(value: _RenderedQuantity) -> _RenderedQuantity:
    if value.unit.dimension in (Dimension.MONEY, Dimension.SHARES):
        return _convert(value, UnitSpec(value.unit.dimension, 0, value.unit.currency))
    if value.unit.dimension == Dimension.PERCENT:
        return _convert(value, UnitSpec(Dimension.RATIO))
    return value


def _convert(value: _RenderedQuantity, target: UnitSpec) -> _RenderedQuantity:
    source = value.unit
    factor: Decimal
    if source.dimension == target.dimension:
        if source.dimension in (Dimension.MONEY, Dimension.SHARES):
            if source.scale_exponent is None or target.scale_exponent is None:
                raise CompilationError("SCALE_UNKNOWN")
            if source.currency and target.currency and source.currency != target.currency:
                raise CompilationError("CURRENCY_MISMATCH")
            factor = Decimal(10) ** (source.scale_exponent - target.scale_exponent)
        else:
            factor = Decimal(1)
    elif source.dimension == Dimension.RATIO and target.dimension == Dimension.PERCENT:
        factor = Decimal(100)
    elif source.dimension == Dimension.PERCENT and target.dimension == Dimension.RATIO:
        factor = Decimal("0.01")
    else:
        raise CompilationError(f"DIMENSION_MISMATCH:{source.dimension}:{target.dimension}")
    expression = value.expression if factor == 1 else f"({value.expression} * {_number(factor)})"
    return _RenderedQuantity(expression, target)


def _by_member(series: _RenderedSeries, axis: Axis) -> dict[str, _RenderedQuantity]:
    output: dict[str, _RenderedQuantity] = {}
    for scope, value in series.values.items():
        member = scope.member(axis)
        if member is None or member in output:
            raise CompilationError(f"MEMBER_CARDINALITY:{axis}:{member}")
        output[member] = value
    return output


def _numeric(value: _RenderedSeries | _RenderedRank) -> _RenderedSeries:
    if isinstance(value, _RenderedRank):
        raise CompilationError("NUMERIC_VALUE_REQUIRED")
    return value


def _evidence(bound: BoundExecutionPlan, variables: dict[str, str]) -> tuple[PandasEvidence, ...]:
    by_table: dict[str, list[str]] = {table_uid: [] for table_uid in variables}
    document: dict[str, str] = {}
    for operand in bound.operands.values():
        candidate = operand.candidate
        by_table[candidate.table_uid].append(candidate.observation_uid)
        document[candidate.table_uid] = candidate.document_id
    return tuple(
        PandasEvidence(
            variables[table_uid],
            table_uid,
            document[table_uid],
            tuple(sorted(set(by_table[table_uid]))),
        )
        for table_uid in sorted(by_table)
    )


def _number(value: Decimal) -> str:
    return format(value, "f")
