"""Composable question AST for retrieval, binding and execution.

The tree describes *what* must be computed.  It never contains physical table,
row or dataframe identifiers; those belong to the bound execution plan.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from .types import (
    AggregateFunction,
    ArithmeticOperator,
    Axis,
    Basis,
    ComparisonOperator,
    LogicalOperator,
    OutputSpec,
    PeriodSemantics,
    PredicateQuantifier,
    RankDirection,
    UnaryOperator,
    UnitSpec,
)


@dataclass(frozen=True, slots=True)
class MetricRef:
    metric_id: str
    entities: tuple[str, ...] = ()
    periods: tuple[str, ...] = ()
    basis: Basis = Basis.UNSPECIFIED
    statement_types: tuple[str, ...] = ()
    expected_unit: UnitSpec | None = None
    period_semantics: PeriodSemantics = PeriodSemantics.UNKNOWN
    qualifiers: tuple[str, ...] = ()
    # Closed grammatical selectors such as "từ Công ty TNHH X của Tập đoàn Y".
    # Every phrase is a hard evidence requirement, unlike soft qualifiers.
    required_context_phrases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Literal:
    value: float
    unit: UnitSpec


@dataclass(frozen=True, slots=True)
class Arithmetic:
    operator: ArithmeticOperator
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class Unary:
    operator: UnaryOperator
    expression: Expression


@dataclass(frozen=True, slots=True)
class FormulaCall:
    formula_id: str
    variant_id: str
    expression: Expression
    same_entity: bool = True
    same_period: bool = True


@dataclass(frozen=True, slots=True)
class Aggregate:
    function: AggregateFunction
    axis: Axis
    expression: Expression
    members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Comparison:
    operator: ComparisonOperator
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class Exists:
    expression: Expression
    negated: bool = False


@dataclass(frozen=True, slots=True)
class LogicalPredicate:
    operator: LogicalOperator
    predicates: tuple[Predicate, ...]


@dataclass(frozen=True, slots=True)
class QuantifiedPredicate:
    """Reduce predicate decisions over one axis while preserving the other."""

    axis: Axis
    quantifier: PredicateQuantifier
    predicate: Predicate


@dataclass(frozen=True, slots=True)
class Filter:
    axis: Axis
    members: tuple[str, ...]
    predicate: Predicate
    expression: Expression


@dataclass(frozen=True, slots=True)
class Rank:
    axis: Axis
    members: tuple[str, ...]
    by: Expression
    direction: RankDirection
    limit: int = 1


@dataclass(frozen=True, slots=True)
class SelectAtArg:
    rank: Rank
    expression: Expression


Expression: TypeAlias = (
    MetricRef
    | Literal
    | Arithmetic
    | Unary
    | FormulaCall
    | Aggregate
    | Filter
    | Rank
    | SelectAtArg
)
Predicate: TypeAlias = Comparison | Exists | LogicalPredicate | QuantifiedPredicate


@dataclass(frozen=True, slots=True)
class QuestionAST:
    expression: Expression
    output: OutputSpec
    question: str
    qid: int | None = None
    schema_version: int = 3
    diagnostics: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "qid": self.qid,
            "question": self.question,
            "expression": expression_to_dict(self.expression),
            "output": self.output.to_dict(),
            "diagnostics": list(self.diagnostics),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> QuestionAST:
        version = int(raw.get("schema_version", 0))
        if version != 3:
            raise ValueError(f"unsupported semantic schema version: {version}")
        return cls(
            expression=expression_from_dict(_mapping(raw["expression"])),
            output=OutputSpec.from_dict(_mapping(raw["output"])),
            question=str(raw["question"]),
            qid=None if raw.get("qid") is None else int(raw["qid"]),
            schema_version=version,
            diagnostics=tuple(str(value) for value in raw.get("diagnostics", ())),
        )


def expression_to_dict(expression: Expression) -> dict[str, Any]:
    if isinstance(expression, MetricRef):
        return {
            "type": "metric_ref",
            "metric_id": expression.metric_id,
            "entities": list(expression.entities),
            "periods": list(expression.periods),
            "basis": expression.basis.value,
            "statement_types": list(expression.statement_types),
            "expected_unit": expression.expected_unit.to_dict() if expression.expected_unit else None,
            "period_semantics": expression.period_semantics.value,
            "qualifiers": list(expression.qualifiers),
            "required_context_phrases": list(expression.required_context_phrases),
        }
    if isinstance(expression, Literal):
        return {"type": "literal", "value": expression.value, "unit": expression.unit.to_dict()}
    if isinstance(expression, Arithmetic):
        return {
            "type": "arithmetic",
            "operator": expression.operator.value,
            "left": expression_to_dict(expression.left),
            "right": expression_to_dict(expression.right),
        }
    if isinstance(expression, Unary):
        return {
            "type": "unary",
            "operator": expression.operator.value,
            "expression": expression_to_dict(expression.expression),
        }
    if isinstance(expression, FormulaCall):
        return {
            "type": "formula_call",
            "formula_id": expression.formula_id,
            "variant_id": expression.variant_id,
            "expression": expression_to_dict(expression.expression),
            "same_entity": expression.same_entity,
            "same_period": expression.same_period,
        }
    if isinstance(expression, Aggregate):
        return {
            "type": "aggregate",
            "function": expression.function.value,
            "axis": expression.axis.value,
            "members": list(expression.members),
            "expression": expression_to_dict(expression.expression),
        }
    if isinstance(expression, Filter):
        return {
            "type": "filter",
            "axis": expression.axis.value,
            "members": list(expression.members),
            "predicate": predicate_to_dict(expression.predicate),
            "expression": expression_to_dict(expression.expression),
        }
    if isinstance(expression, Rank):
        return {
            "type": "rank",
            "axis": expression.axis.value,
            "members": list(expression.members),
            "by": expression_to_dict(expression.by),
            "direction": expression.direction.value,
            "limit": expression.limit,
        }
    if isinstance(expression, SelectAtArg):
        return {
            "type": "select_at_arg",
            "rank": expression_to_dict(expression.rank),
            "expression": expression_to_dict(expression.expression),
        }
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def predicate_to_dict(predicate: Predicate) -> dict[str, Any]:
    if isinstance(predicate, Comparison):
        return {
            "type": "comparison",
            "operator": predicate.operator.value,
            "left": expression_to_dict(predicate.left),
            "right": expression_to_dict(predicate.right),
        }
    if isinstance(predicate, Exists):
        return {
            "type": "exists",
            "expression": expression_to_dict(predicate.expression),
            "negated": predicate.negated,
        }
    if isinstance(predicate, LogicalPredicate):
        return {
            "type": "logical",
            "operator": predicate.operator.value,
            "predicates": [predicate_to_dict(value) for value in predicate.predicates],
        }
    if isinstance(predicate, QuantifiedPredicate):
        return {
            "type": "quantified",
            "axis": predicate.axis.value,
            "quantifier": predicate.quantifier.value,
            "predicate": predicate_to_dict(predicate.predicate),
        }
    raise TypeError(f"unsupported predicate: {type(predicate).__name__}")


def expression_from_dict(raw: Mapping[str, Any]) -> Expression:
    kind = str(raw.get("type"))
    if kind == "metric_ref":
        unit = raw.get("expected_unit")
        return MetricRef(
            metric_id=str(raw["metric_id"]),
            entities=tuple(str(value) for value in raw.get("entities", ())),
            periods=tuple(str(value) for value in raw.get("periods", ())),
            basis=Basis(str(raw.get("basis", Basis.UNSPECIFIED.value))),
            statement_types=tuple(str(value) for value in raw.get("statement_types", ())),
            expected_unit=UnitSpec.from_dict(_mapping(unit)) if unit is not None else None,
            period_semantics=PeriodSemantics(
                str(raw.get("period_semantics", PeriodSemantics.UNKNOWN.value))
            ),
            qualifiers=tuple(str(value) for value in raw.get("qualifiers", ())),
            required_context_phrases=tuple(
                str(value) for value in raw.get("required_context_phrases", ())
            ),
        )
    if kind == "literal":
        return Literal(float(raw["value"]), UnitSpec.from_dict(_mapping(raw["unit"])))
    if kind == "arithmetic":
        return Arithmetic(
            ArithmeticOperator(str(raw["operator"])),
            expression_from_dict(_mapping(raw["left"])),
            expression_from_dict(_mapping(raw["right"])),
        )
    if kind == "unary":
        return Unary(
            UnaryOperator(str(raw["operator"])),
            expression_from_dict(_mapping(raw["expression"])),
        )
    if kind == "formula_call":
        return FormulaCall(
            str(raw["formula_id"]),
            str(raw.get("variant_id", "default")),
            expression_from_dict(_mapping(raw["expression"])),
            bool(raw.get("same_entity", True)),
            bool(raw.get("same_period", True)),
        )
    if kind == "aggregate":
        return Aggregate(
            AggregateFunction(str(raw["function"])),
            Axis(str(raw["axis"])),
            expression_from_dict(_mapping(raw["expression"])),
            tuple(str(value) for value in raw.get("members", ())),
        )
    if kind == "filter":
        return Filter(
            Axis(str(raw["axis"])),
            tuple(str(value) for value in raw.get("members", ())),
            predicate_from_dict(_mapping(raw["predicate"])),
            expression_from_dict(_mapping(raw["expression"])),
        )
    if kind == "rank":
        return Rank(
            Axis(str(raw["axis"])),
            tuple(str(value) for value in raw.get("members", ())),
            expression_from_dict(_mapping(raw["by"])),
            RankDirection(str(raw["direction"])),
            int(raw.get("limit", 1)),
        )
    if kind == "select_at_arg":
        rank = expression_from_dict(_mapping(raw["rank"]))
        if not isinstance(rank, Rank):
            raise TypeError("select_at_arg.rank must be a rank expression")
        return SelectAtArg(rank, expression_from_dict(_mapping(raw["expression"])))
    raise ValueError(f"unknown expression type: {kind!r}")


def predicate_from_dict(raw: Mapping[str, Any]) -> Predicate:
    kind = str(raw.get("type"))
    if kind == "comparison":
        return Comparison(
            ComparisonOperator(str(raw["operator"])),
            expression_from_dict(_mapping(raw["left"])),
            expression_from_dict(_mapping(raw["right"])),
        )
    if kind == "exists":
        return Exists(expression_from_dict(_mapping(raw["expression"])), bool(raw.get("negated")))
    if kind == "logical":
        return LogicalPredicate(
            LogicalOperator(str(raw["operator"])),
            tuple(predicate_from_dict(_mapping(value)) for value in raw.get("predicates", ())),
        )
    if kind == "quantified":
        return QuantifiedPredicate(
            Axis(str(raw["axis"])),
            PredicateQuantifier(str(raw["quantifier"])),
            predicate_from_dict(_mapping(raw["predicate"])),
        )
    raise ValueError(f"unknown predicate type: {kind!r}")


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected mapping, got {type(value).__name__}")
    return value
