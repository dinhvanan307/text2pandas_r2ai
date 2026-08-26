"""Compile lexical annotations and the ontology into a compositional AST."""

from __future__ import annotations

from dataclasses import dataclass

from text2pandas.domain.metrics import (
    FormulaDefinition,
    MetricDefinition,
    MetricOntology,
    normalize_phrase,
)
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Dimension,
    Literal,
    MetricRef,
    OutputSpec,
    QuestionAST,
    Rank,
    RankDirection,
    ResultKind,
    SelectAtArg,
    Unary,
    UnitSpec,
    validate_question_ast,
)
from text2pandas.domain.semantic.ast import Expression

from .contracts import (
    OperationKind,
    ParseResult,
    QuestionAnnotations,
    QuestionAnnotator,
    ReturnMode,
)


@dataclass(frozen=True, slots=True)
class MetricMention:
    start: int
    end: int
    alias: str
    metric: MetricDefinition


class SemanticParser:
    """Question -> validated `QuestionAST`, or a named abstention.

    The annotator owns Vietnamese lexical recognition.  This compiler owns
    scope, axes and operation composition; it never imports retrieval or
    execution implementations.
    """

    def __init__(self, ontology: MetricOntology, annotator: QuestionAnnotator):
        self.ontology = ontology
        self.annotator = annotator

    def parse(self, question: str, *, qid: int | None = None) -> ParseResult:
        annotations = self.annotator.annotate(question)
        normalized = normalize_phrase(question)
        formula = self.ontology.match_formula(normalized)
        mentions = self._metric_mentions(normalized)
        trace: list[dict[str, object]] = [
            {
                "stage": "ANNOTATE",
                "entities": list(annotations.entities),
                "periods": list(annotations.periods),
                "basis": annotations.basis.value,
                "operation": annotations.operation.value,
                "operation_evidence": annotations.operation_evidence,
            },
            {
                "stage": "ONTOLOGY_MATCH",
                "formula_id": formula.formula_id if formula else None,
                "metric_ids": [mention.metric.metric_id for mention in mentions],
                "ontology_fingerprint": self.ontology.fingerprint,
            },
        ]
        result = self._compile(question, annotations, formula, mentions, qid=qid)
        return ParseResult(result.status, result.ast, result.reason, tuple(trace) + result.trace)

    def _compile(
        self,
        question: str,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
        *,
        qid: int | None,
    ) -> ParseResult:
        if not annotations.entities and annotations.mode != "screen_open":
            return _abstain("ENTITY_UNRESOLVED")
        if annotations.operation == OperationKind.UNSUPPORTED:
            return _abstain("OPERATION_UNSUPPORTED")

        base = self._base_expression(annotations, formula, mentions)
        if base is None:
            return _abstain("METRIC_UNRESOLVED")
        expression_result = self._compose(base, annotations, mentions)
        if isinstance(expression_result, str):
            return _abstain(expression_result)
        expression, result_kind = expression_result
        output_unit = self._output_unit(annotations, formula, mentions, result_kind)
        ast = QuestionAST(
            expression=expression,
            output=OutputSpec(result_kind, output_unit),
            question=question,
            qid=qid,
        )
        issues = validate_question_ast(ast)
        if issues:
            reason = ",".join(sorted({issue.code for issue in issues}))
            return _abstain(f"AST_INVALID:{reason}")
        return ParseResult(
            "OK",
            ast=ast,
            trace=(
                {
                    "stage": "COMPILE",
                    "expression_type": type(expression).__name__,
                    "result_kind": result_kind.value,
                },
            ),
        )

    def _base_expression(
        self,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
    ) -> Expression | None:
        if formula is not None:
            return _scope_expression(formula.expression, annotations)
        if not mentions:
            return None
        return _metric_ref(mentions[-1].metric, annotations)

    def _compose(
        self,
        base: Expression,
        annotations: QuestionAnnotations,
        mentions: tuple[MetricMention, ...],
    ) -> tuple[Expression, ResultKind] | str:
        operation = annotations.operation
        if operation in (OperationKind.LOOKUP, OperationKind.DIVIDE):
            if operation == OperationKind.DIVIDE and not isinstance(base, Arithmetic):
                return "UNREVIEWED_RELATIONAL_FORMULA"
            return base, ResultKind.SCALAR

        axis, members = _operation_axis(annotations)
        if operation in (OperationKind.SUM, OperationKind.AVERAGE, OperationKind.COUNT):
            if axis is None or len(members) < 2:
                return "AGGREGATE_AXIS_UNRESOLVED"
            function = {
                OperationKind.SUM: AggregateFunction.SUM,
                OperationKind.AVERAGE: AggregateFunction.AVERAGE,
                OperationKind.COUNT: AggregateFunction.COUNT,
            }[operation]
            if function == AggregateFunction.COUNT:
                return "COUNT_PREDICATE_REQUIRED"
            return Aggregate(function, axis, base, members), ResultKind.SCALAR

        if operation in (OperationKind.SUBTRACT, OperationKind.GROWTH):
            scoped = _binary_scopes(annotations)
            if scoped is None:
                return "BINARY_OPERANDS_UNRESOLVED"
            left_scope, right_scope = scoped
            left = _rescope_expression(base, annotations, left_scope[0], left_scope[1])
            right = _rescope_expression(base, annotations, right_scope[0], right_scope[1])
            operator = (
                ArithmeticOperator.GROWTH
                if operation == OperationKind.GROWTH
                else ArithmeticOperator.SUBTRACT
            )
            return Arithmetic(operator, left, right), ResultKind.SCALAR

        if operation == OperationKind.EXTREMUM:
            if axis is None or len(members) < 2:
                return "RANK_AXIS_UNRESOLVED"
            direction = annotations.rank_direction or RankDirection.DESCENDING
            if annotations.return_mode == ReturnMode.FILTERED_VALUE:
                return "FILTER_PREDICATE_REQUIRED"
            if annotations.return_mode == ReturnMode.SELECT_AT_ARG:
                if len(mentions) < 2:
                    return "SELECT_AT_ARG_REQUIRES_TWO_METRICS"
                rank_expression = _metric_ref(mentions[0].metric, annotations)
                selected_expression = _metric_ref(mentions[-1].metric, annotations)
                return (
                    SelectAtArg(Rank(axis, members, rank_expression, direction), selected_expression),
                    ResultKind.SCALAR,
                )
            rank = Rank(axis, members, base, direction)
            if annotations.return_mode == ReturnMode.MEMBER:
                return rank, ResultKind.ENTITY if axis == Axis.ENTITY else ResultKind.PERIOD
            function = (
                AggregateFunction.MAXIMUM
                if direction == RankDirection.DESCENDING
                else AggregateFunction.MINIMUM
            )
            return Aggregate(function, axis, base, members), ResultKind.SCALAR
        return "NO_COMPOSITION_ROUTE"

    def _output_unit(
        self,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
        result_kind: ResultKind,
    ) -> UnitSpec:
        if result_kind == ResultKind.ENTITY:
            return UnitSpec(Dimension.ENTITY)
        if result_kind == ResultKind.PERIOD:
            return UnitSpec(Dimension.PERIOD)
        if annotations.requested_unit.is_known:
            return annotations.requested_unit
        if formula is not None:
            return formula.output_unit
        if mentions:
            return mentions[-1].metric.unit
        return UnitSpec(Dimension.UNKNOWN)

    def _metric_mentions(self, normalized: str) -> tuple[MetricMention, ...]:
        raw: list[MetricMention] = []
        for metric in self.ontology.metrics.values():
            for alias in metric.aliases:
                start = normalized.find(alias)
                while start >= 0:
                    raw.append(MetricMention(start, start + len(alias), alias, metric))
                    start = normalized.find(alias, start + 1)
        # Longest span owns nested aliases.  This is ontology resolution, not a
        # list of metric-specific exceptions.
        selected: list[MetricMention] = []
        for mention in sorted(raw, key=lambda value: (-len(value.alias), value.start, value.metric.metric_id)):
            if any(mention.start >= other.start and mention.end <= other.end for other in selected):
                continue
            selected.append(mention)
        return tuple(sorted(selected, key=lambda value: (value.start, value.end)))


def _metric_ref(metric: MetricDefinition, annotations: QuestionAnnotations) -> MetricRef:
    return MetricRef(
        metric_id=metric.metric_id,
        entities=annotations.entities,
        periods=annotations.periods,
        basis=annotations.basis,
        statement_types=metric.statement_types,
        expected_unit=metric.unit,
        period_semantics=metric.period_semantics,
    )


def _scope_expression(expression: Expression, annotations: QuestionAnnotations) -> Expression:
    if isinstance(expression, MetricRef):
        metric = expression.metric_id
        return _metric_ref_from_id(metric, annotations)
    if isinstance(expression, Literal):
        return expression
    if isinstance(expression, Arithmetic):
        return Arithmetic(
            expression.operator,
            _scope_expression(expression.left, annotations),
            _scope_expression(expression.right, annotations),
        )
    if isinstance(expression, Unary):
        return Unary(expression.operator, _scope_expression(expression.expression, annotations))
    raise TypeError(f"formula template contains unsupported node: {type(expression).__name__}")


def _metric_ref_from_id(metric_id: str, annotations: QuestionAnnotations) -> MetricRef:
    # Formula templates already carry reviewed canonical IDs.  Statement/unit
    # enrichment happens in the planner from the same ontology.
    return MetricRef(
        metric_id,
        entities=annotations.entities,
        periods=annotations.periods,
        basis=annotations.basis,
    )


def _operation_axis(annotations: QuestionAnnotations) -> tuple[Axis | None, tuple[str, ...]]:
    if len(annotations.entities) >= 2:
        return Axis.ENTITY, annotations.entities
    if len(annotations.periods) >= 2:
        return Axis.PERIOD, annotations.periods
    return None, ()


def _binary_scopes(
    annotations: QuestionAnnotations,
) -> tuple[tuple[str | None, str | None], tuple[str | None, str | None]] | None:
    if len(annotations.entities) == 2 and len(annotations.periods) == 1:
        pair = [
            (annotations.entities[0], annotations.periods[0]),
            (annotations.entities[1], annotations.periods[0]),
        ]
    elif len(annotations.periods) >= 2 and len(annotations.entities) == 1:
        newest, oldest = max(annotations.periods), min(annotations.periods)
        pair = [(annotations.entities[0], newest), (annotations.entities[0], oldest)]
    else:
        return None
    if annotations.reverse_difference:
        pair.reverse()
    return pair[0], pair[1]


def _rescope_expression(
    expression: Expression,
    annotations: QuestionAnnotations,
    entity: str | None,
    period: str | None,
) -> Expression:
    scoped_annotations = QuestionAnnotations(
        entities=(entity,) if entity else (),
        periods=(period,) if period else (),
        basis=annotations.basis,
        requested_unit=annotations.requested_unit,
        operation=annotations.operation,
        mode=annotations.mode,
        rank_direction=annotations.rank_direction,
        return_mode=annotations.return_mode,
        reverse_difference=annotations.reverse_difference,
        operation_evidence=annotations.operation_evidence,
    )
    return _scope_expression(expression, scoped_annotations)


def _abstain(reason: str) -> ParseResult:
    return ParseResult("ABSTAIN", reason=reason)
