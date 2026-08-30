"""Compile the canonical semantic AST into the grounded execution DAG.

The AST already models arithmetic, aggregation, filters and rank/select.  This
adapter makes it the common planning boundary for V5/V6 instead of encoding the
same semantics in an expanding list of question templates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.usecases.grounded_resolution import (
    has_hard_logical_fact_conflict,
)
from text2pandas.application.usecases.grounded_synthesis import (
    Comparator,
    GroundedFact,
    GroundedPlanError,
    GroundedProgram,
    ProgramNode,
    ProgramOperation,
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
    ComparisonOperator,
    Dimension,
    Exists,
    Filter,
    FormulaCall,
    Literal,
    LogicalOperator,
    LogicalPredicate,
    MetricRef,
    PredicateQuantifier,
    QuantifiedPredicate,
    QuestionAST,
    Rank,
    RankDirection,
    ResultKind,
    SelectAtArg,
    Unary,
    UnaryOperator,
)
from text2pandas.domain.semantic.ast import Expression, Predicate


class GroundedAstCompilationUnsupported(GroundedPlanError):
    """The canonical AST cannot be represented by the closed grounded DAG."""


@dataclass(frozen=True, slots=True)
class _Compiled:
    node_id: str
    keys: tuple[str, ...] | None
    axis: str | None
    kind: str = "numeric"
    dimension: Dimension = Dimension.UNKNOWN


class GroundedAstCompiler:
    """Stateless, re-entrant facade for one semantic compilation."""

    def __init__(self, confidence: float = 0.97) -> None:
        self.confidence = confidence

    def compile(self, ast: QuestionAST, facts: Sequence[GroundedFact]) -> GroundedProgram:
        return _GroundedAstCompilation(tuple(facts), confidence=self.confidence).compile(ast)


@dataclass(slots=True)
class _GroundedAstCompilation:
    facts: tuple[GroundedFact, ...]
    confidence: float = 0.97
    _nodes: list[ProgramNode] = field(init=False, repr=False, default_factory=list)

    def compile(self, ast: QuestionAST) -> GroundedProgram:
        if ast.output.result_kind not in {ResultKind.SCALAR, ResultKind.PERIOD}:
            raise GroundedAstCompilationUnsupported(
                f"grounded AST output must be scalar or period, got {ast.output.result_kind.value}"
            )
        self._nodes = []
        compiled = self._expression(ast.expression)
        if ast.output.result_kind is ResultKind.PERIOD:
            if compiled.kind != "key" or compiled.axis != "period":
                raise GroundedAstCompilationUnsupported(
                    "period AST output must be a ranked period key"
                )
            output_id = self._append(
                "period_key",
                ProgramOperation.KEY_TO_NUMBER,
                input_ids=(compiled.node_id,),
            )
        elif compiled.kind != "numeric":
            raise GroundedAstCompilationUnsupported(
                f"grounded AST output is {compiled.kind}, not numeric"
            )
        else:
            output_id = compiled.node_id
        if ast.output.result_kind is ResultKind.SCALAR and compiled.keys is not None:
            if len(compiled.keys) != 1:
                raise GroundedAstCompilationUnsupported(
                    f"semantic AST leaves a non-scalar series of {len(compiled.keys)} values"
                )
            output_id = self._append(
                "scalarize", ProgramOperation.SUM, input_ids=(output_id,)
            )
        if (
            ast.output.unit.dimension in {Dimension.PERCENT, Dimension.PERCENT_POINT}
            and compiled.dimension is Dimension.RATIO
        ):
            output_id = self._append(
                "to_percent",
                ProgramOperation.TO_PERCENT,
                input_ids=(output_id,),
            )
        unit = ast.output.unit
        if unit.dimension in {Dimension.MONEY, Dimension.SHARES} and unit.scale_exponent is None:
            raise GroundedAstCompilationUnsupported(
                f"{unit.dimension.value} AST output has no requested scale"
            )
        return GroundedProgram(
            nodes=tuple(self._nodes),
            output_node_id=output_id,
            output_dimension=unit.dimension,
            output_scale_exponent=unit.scale_exponent,
            confidence=self.confidence,
        )

    def _expression(self, expression: Expression) -> _Compiled:
        if isinstance(expression, MetricRef):
            selected_facts = self._select_facts(expression)
            axis = _fact_axis(selected_facts)
            fact_keys = tuple(_fact_key(fact, axis) for fact in selected_facts)
            has_components = len(fact_keys) != len(set(fact_keys))
            node_id = self._append(
                f"facts_{expression.metric_id}",
                ProgramOperation.FACTS,
                fact_uids=tuple(fact.observation_uid for fact in selected_facts),
                axis=("entity_period_observation" if has_components else axis),
            )
            if has_components:
                node_id = self._append(
                    f"components_{expression.metric_id}",
                    ProgramOperation.SUM_BY_SCOPE,
                    input_ids=(node_id,),
                    axis=axis,
                )
                fact_keys = tuple(dict.fromkeys(fact_keys))
            dimensions = {fact.dimension for fact in selected_facts}
            dimension = dimensions.pop() if len(dimensions) == 1 else Dimension.UNKNOWN
            return _Compiled(node_id, fact_keys, axis, dimension=dimension)
        if isinstance(expression, Literal):
            node_id = self._append(
                "literal", ProgramOperation.LITERAL, literal=Decimal(str(expression.value))
            )
            return _Compiled(node_id, None, None, dimension=expression.unit.dimension)
        if isinstance(expression, FormulaCall):
            return self._expression(expression.expression)
        if isinstance(expression, Arithmetic):
            left = self._expression(expression.left)
            right = self._expression(expression.right)
            left, right, aligned_keys, aligned_axis = self._align_numeric(left, right)
            binary_operation = {
                ArithmeticOperator.ADD: ProgramOperation.ADD,
                ArithmeticOperator.SUBTRACT: ProgramOperation.SUBTRACT,
                ArithmeticOperator.MULTIPLY: ProgramOperation.MULTIPLY,
                ArithmeticOperator.DIVIDE: ProgramOperation.DIVIDE,
                ArithmeticOperator.GROWTH: ProgramOperation.GROWTH,
            }[expression.operator]
            inputs: tuple[str, ...] = (left.node_id, right.node_id)
            # Semantic AST stores growth as (current, prior); the grounded DAG
            # operation accepts (prior, current) to make rolling use natural.
            if expression.operator is ArithmeticOperator.GROWTH:
                inputs = tuple(reversed(inputs))
            node_id = self._append(binary_operation.value, binary_operation, input_ids=inputs)
            return _Compiled(
                node_id,
                aligned_keys,
                aligned_axis,
                dimension=_arithmetic_dimension(
                    expression.operator,
                    left.dimension,
                    right.dimension,
                ),
            )
        if isinstance(expression, Unary):
            child = self._numeric(self._expression(expression.expression))
            if expression.operator is not UnaryOperator.ABSOLUTE:
                raise GroundedAstCompilationUnsupported(
                    f"unsupported unary operation: {expression.operator.value}"
                )
            node_id = self._append(
                ProgramOperation.ABSOLUTE.value,
                ProgramOperation.ABSOLUTE,
                input_ids=(child.node_id,),
            )
            return _Compiled(
                node_id,
                child.keys,
                child.axis,
                dimension=child.dimension,
            )
        if isinstance(expression, Aggregate):
            if expression.function is AggregateFunction.COUNT and isinstance(
                expression.expression, Filter
            ):
                predicate = self._predicate(expression.expression.predicate)
                self._require_axis(
                    predicate,
                    expression.axis,
                    expression.members,
                    operation="count",
                )
                node_id = self._append(
                    "count_true",
                    ProgramOperation.COUNT_TRUE,
                    input_ids=(predicate.node_id,),
                )
                return _Compiled(node_id, None, None, dimension=Dimension.COUNT)
            child = self._numeric(self._expression(expression.expression))
            self._require_axis(
                child,
                expression.axis,
                expression.members,
                operation=expression.function.value,
            )
            aggregate_operation = {
                AggregateFunction.SUM: ProgramOperation.SUM,
                AggregateFunction.AVERAGE: ProgramOperation.AVERAGE,
                AggregateFunction.MINIMUM: ProgramOperation.MINIMUM,
                AggregateFunction.MAXIMUM: ProgramOperation.MAXIMUM,
                AggregateFunction.MEDIAN: ProgramOperation.MEDIAN,
            }.get(expression.function)
            if aggregate_operation is None:
                raise GroundedAstCompilationUnsupported(
                    f"unsupported aggregate: {expression.function.value}"
                )
            node_id = self._append(
                aggregate_operation.value,
                aggregate_operation,
                input_ids=(child.node_id,),
            )
            return _Compiled(node_id, None, None, dimension=child.dimension)
        if isinstance(expression, Filter):
            value = self._numeric(self._expression(expression.expression))
            predicate = self._predicate(expression.predicate)
            self._require_axis(
                value,
                expression.axis,
                expression.members,
                operation="filter",
            )
            if (
                value.keys is None
                or predicate.keys is None
                or set(value.keys) != set(predicate.keys)
            ):
                raise GroundedAstCompilationUnsupported(
                    "filter value and predicate axes do not align"
                )
            node_id = self._append(
                "filter",
                ProgramOperation.FILTER,
                input_ids=(value.node_id, predicate.node_id),
            )
            return _Compiled(
                node_id,
                value.keys,
                value.axis,
                dimension=value.dimension,
            )
        if isinstance(expression, Rank):
            ranked = self._numeric(self._expression(expression.by))
            if ranked.keys is None:
                raise GroundedAstCompilationUnsupported("rank requires a series")
            self._require_axis(
                ranked,
                expression.axis,
                expression.members,
                operation="rank",
            )
            operation = (
                ProgramOperation.ARGMAX_KEY
                if expression.direction is RankDirection.DESCENDING
                else ProgramOperation.ARGMIN_KEY
            )
            if expression.limit != 1:
                raise GroundedAstCompilationUnsupported("rank limit must equal one")
            node_id = self._append(operation.value, operation, input_ids=(ranked.node_id,))
            return _Compiled(
                node_id,
                ranked.keys,
                ranked.axis,
                "key",
                ranked.dimension,
            )
        if isinstance(expression, SelectAtArg):
            selected_value = self._numeric(self._expression(expression.expression))
            ranked_key = self._expression(expression.rank)
            if (
                selected_value.keys is None
                or ranked_key.kind != "key"
                or selected_value.axis != ranked_key.axis
                or set(selected_value.keys) != set(ranked_key.keys or ())
            ):
                raise GroundedAstCompilationUnsupported(
                    "select-at-arg value and rank axes do not align"
                )
            node_id = self._append(
                "select_at_key",
                ProgramOperation.SELECT_AT_KEY,
                input_ids=(selected_value.node_id, ranked_key.node_id),
            )
            return _Compiled(
                node_id,
                None,
                None,
                dimension=selected_value.dimension,
            )
        raise GroundedAstCompilationUnsupported(
            f"unsupported semantic expression: {type(expression).__name__}"
        )

    def _predicate(self, predicate: Predicate) -> _Compiled:
        if isinstance(predicate, Comparison):
            left = self._numeric(self._expression(predicate.left))
            right = self._numeric(self._expression(predicate.right))
            left, right, aligned_keys, aligned_axis = self._align_numeric(left, right)
            if (
                left.keys is not None
                and right.keys is not None
                and (set(left.keys) != set(right.keys))
            ):
                raise GroundedAstCompilationUnsupported(
                    "comparison series axes do not align exactly"
                )
            comparator = {
                ComparisonOperator.GT: Comparator.GT,
                ComparisonOperator.GE: Comparator.GTE,
                ComparisonOperator.LT: Comparator.LT,
                ComparisonOperator.LE: Comparator.LTE,
                ComparisonOperator.EQ: Comparator.EQ,
                ComparisonOperator.NE: Comparator.NE,
            }.get(predicate.operator)
            if comparator is None:
                raise GroundedAstCompilationUnsupported(
                    f"unsupported comparator: {predicate.operator.value}"
                )
            node_id = self._append(
                "compare",
                ProgramOperation.COMPARE,
                input_ids=(left.node_id, right.node_id),
                comparator=comparator,
            )
            return _Compiled(node_id, aligned_keys, aligned_axis, "boolean")
        if isinstance(predicate, Exists):
            value = self._numeric(self._expression(predicate.expression))
            operation = (
                ProgramOperation.IS_ZERO if predicate.negated else ProgramOperation.IS_NONZERO
            )
            node_id = self._append(operation.value, operation, input_ids=(value.node_id,))
            return _Compiled(node_id, value.keys, value.axis, "boolean")
        if isinstance(predicate, LogicalPredicate):
            children = [self._predicate(value) for value in predicate.predicates]
            if len(children) < 2:
                raise GroundedAstCompilationUnsupported(
                    "logical predicate requires at least two children"
                )
            operation = (
                ProgramOperation.LOGICAL_AND
                if predicate.operator is LogicalOperator.AND
                else ProgramOperation.LOGICAL_OR
            )
            current = children[0]
            for child in children[1:]:
                if current.keys != child.keys:
                    raise GroundedAstCompilationUnsupported("logical predicate axes do not align")
                node_id = self._append(
                    operation.value,
                    operation,
                    input_ids=(current.node_id, child.node_id),
                )
                current = _Compiled(node_id, current.keys, current.axis, "boolean")
            return current
        if isinstance(predicate, QuantifiedPredicate):
            child = self._predicate(predicate.predicate)
            if (
                predicate.axis is not Axis.PERIOD
                or child.keys is None
                or child.axis != "entity_period"
            ):
                raise GroundedAstCompilationUnsupported(
                    "only period quantification over a keyed predicate is supported"
                )
            operation = (
                ProgramOperation.ALL_BY_ENTITY
                if predicate.quantifier is PredicateQuantifier.ALL
                else ProgramOperation.ANY_BY_ENTITY
            )
            node_id = self._append(operation.value, operation, input_ids=(child.node_id,))
            entities = tuple(dict.fromkeys(key.rsplit("|", 1)[0] for key in child.keys))
            return _Compiled(node_id, entities, "entity", "boolean")
        raise GroundedAstCompilationUnsupported(
            f"unsupported semantic predicate: {type(predicate).__name__}"
        )

    def _select_facts(self, reference: MetricRef) -> tuple[GroundedFact, ...]:
        years = {value[:4] for value in reference.periods}
        required_context = tuple(
            normalize_phrase(value) for value in reference.required_context_phrases
        )
        selected = []
        for fact in self.facts:
            if has_hard_logical_fact_conflict(fact):
                continue
            if fact.retrieval_metric != reference.metric_id:
                continue
            if reference.entities and fact.entity not in reference.entities:
                continue
            if years and str(fact.period_year or "") not in years:
                continue
            if reference.basis is not Basis.UNSPECIFIED and fact.basis is not reference.basis:
                continue
            if (
                reference.statement_types
                and fact.statement_type is not None
                and fact.statement_type not in reference.statement_types
                and not {
                    "metric:query_qualifier_match",
                    "metric:source_context_complete",
                    "metric:required_context_match",
                }
                & set(fact.score_reasons)
            ):
                continue
            context = normalize_phrase(f"{fact.row_path} {fact.section_text} {fact.column_path}")
            if any(value not in context for value in required_context):
                continue
            selected.append(fact)
        if not selected:
            raise GroundedAstCompilationUnsupported(
                f"semantic AST has no facts for {reference.metric_id}"
            )
        selected.sort(
            key=lambda fact: (
                fact.entity,
                fact.period_year or 0,
                -fact.score,
                fact.observation_uid,
            )
        )
        return tuple(selected)

    def _align_numeric(
        self, left: _Compiled, right: _Compiled
    ) -> tuple[_Compiled, _Compiled, tuple[str, ...] | None, str | None]:
        left = self._numeric(left)
        right = self._numeric(right)
        if left.keys is None and right.keys is None:
            return left, right, None, None
        if left.keys is None:
            return left, right, right.keys, right.axis
        if right.keys is None:
            return left, right, left.keys, left.axis
        common = tuple(key for key in left.keys if key in set(right.keys))
        if common:
            axis = left.axis if left.axis == right.axis else None
            if axis is None:
                raise GroundedAstCompilationUnsupported(
                    "semantic numeric axes have incompatible key types"
                )
            return left, right, common, axis
        if len(left.keys) == len(right.keys) == 1:
            return self._scalarize(left), self._scalarize(right), None, None
        raise GroundedAstCompilationUnsupported("semantic numeric axes do not align")

    def _scalarize(self, value: _Compiled) -> _Compiled:
        if value.keys is None:
            return value
        if len(value.keys) != 1:
            raise GroundedAstCompilationUnsupported(
                "cannot scalarize a multi-value semantic series"
            )
        node_id = self._append("scalar", ProgramOperation.SUM, input_ids=(value.node_id,))
        return _Compiled(node_id, None, None, value.kind, value.dimension)

    @staticmethod
    def _require_axis(
        value: _Compiled,
        axis: Axis,
        members: Sequence[str],
        *,
        operation: str,
    ) -> None:
        expected_axis = axis.value
        if value.keys is None or value.axis != expected_axis:
            raise GroundedAstCompilationUnsupported(
                f"{operation} requires a {expected_axis}-axis series"
            )
        if members and set(value.keys) != set(members):
            raise GroundedAstCompilationUnsupported(
                f"{operation} series does not cover its declared members"
            )

    @staticmethod
    def _numeric(value: _Compiled) -> _Compiled:
        if value.kind != "numeric":
            raise GroundedAstCompilationUnsupported(
                f"expected numeric semantic node, got {value.kind}"
            )
        return value

    def _append(
        self,
        stem: str,
        operation: ProgramOperation,
        *,
        input_ids: tuple[str, ...] = (),
        fact_uids: tuple[str, ...] = (),
        axis: str | None = None,
        literal: Decimal | None = None,
        comparator: Comparator | None = None,
    ) -> str:
        base = "".join(character if character.isalnum() else "_" for character in stem)
        base = base.strip("_") or "node"
        node_id = base
        known = {node.node_id for node in self._nodes}
        index = 2
        while node_id in known:
            node_id = f"{base}_{index}"
            index += 1
        self._nodes.append(
            ProgramNode(
                node_id=node_id,
                operation=operation,
                input_ids=input_ids,
                fact_uids=fact_uids,
                axis=axis,
                literal=literal,
                comparator=comparator,
            )
        )
        return node_id


@dataclass(slots=True)
class GroundedAstGenerator:
    parser: SemanticParser
    compiler: GroundedAstCompiler = field(default_factory=GroundedAstCompiler)

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        ast = hints.get("semantic_ast")
        if not isinstance(ast, QuestionAST):
            parsed = self.parser.parse(question)
            if not parsed.ok or parsed.ast is None:
                raise GroundedAstCompilationUnsupported(
                    f"semantic AST parse failed: {parsed.reason or 'unknown'}"
                )
            ast = parsed.ast
        return self.compiler.compile(ast, facts)


def _fact_axis(facts: Sequence[GroundedFact]) -> str:
    entities = {fact.entity for fact in facts}
    periods = {fact.period_year for fact in facts}
    if len(entities) > 1 and len(periods) > 1:
        return "entity_period"
    if len(entities) > 1:
        return "entity"
    if len(periods) > 1:
        return "period"
    return "entity_period"


def _fact_key(fact: GroundedFact, axis: str) -> str:
    if axis == "entity":
        return fact.entity
    if axis == "period":
        return str(fact.period_year or "")
    return f"{fact.entity}|{fact.period_year or ''}"


def _arithmetic_dimension(
    operator: ArithmeticOperator,
    left: Dimension,
    right: Dimension,
) -> Dimension:
    """Infer dimensions before applying final output-unit conversion."""

    if operator is ArithmeticOperator.DIVIDE:
        return Dimension.RATIO
    if operator is ArithmeticOperator.GROWTH:
        # The closed DAG defines GROWTH as ((current-prior)/abs(prior))*100.
        return Dimension.PERCENT
    if operator in {ArithmeticOperator.ADD, ArithmeticOperator.SUBTRACT}:
        return left if left is right else Dimension.UNKNOWN
    if operator is ArithmeticOperator.MULTIPLY:
        if left is Dimension.RATIO:
            return right
        if right is Dimension.RATIO:
            return left
    return Dimension.UNKNOWN
