"""Compile lexical annotations and the ontology into a compositional AST."""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from dataclasses import dataclass, replace

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
    Comparison,
    ComparisonOperator,
    Dimension,
    Filter,
    FormulaCall,
    Literal,
    LogicalOperator,
    LogicalPredicate,
    MetricBindingHint,
    MetricRef,
    OutputSpec,
    QuestionAST,
    Rank,
    RankDirection,
    ResultKind,
    SelectAtArg,
    Unary,
    UnaryOperator,
    UnitSpec,
    validate_question_ast,
)
from text2pandas.domain.semantic.ast import Expression, Predicate
from text2pandas.domain.units.lexicon import scan_unit

from .contracts import (
    MetricHypothesis,
    MetricMentionResolver,
    OperationKind,
    ParseCandidate,
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
    source_binding: MetricBindingHint | None = None
    resolution_score: tuple[int, int, int] = (0, 0, 0)


@dataclass(frozen=True, slots=True)
class FormulaMention:
    start: int
    end: int
    alias: str
    formula: FormulaDefinition


@dataclass(frozen=True, slots=True)
class _PreparedParse:
    annotations: QuestionAnnotations
    formula: FormulaDefinition | None
    exact_mentions: tuple[MetricMention, ...]
    mentions: tuple[MetricMention, ...]
    formula_mentions: tuple[FormulaMention, ...]
    source_hypotheses: tuple[MetricHypothesis, ...]
    unresolved_reason: str | None
    trace: tuple[dict[str, object], ...]


class SemanticParser:
    """Question -> validated `QuestionAST`, or a named abstention.

    The annotator owns Vietnamese lexical recognition.  This compiler owns
    scope, axes and operation composition; it never imports retrieval or
    execution implementations.
    """

    def __init__(
        self,
        ontology: MetricOntology,
        annotator: QuestionAnnotator,
        resolver: MetricMentionResolver | None = None,
    ):
        self.ontology = ontology
        self.annotator = annotator
        self.resolver = resolver

    def parse(self, question: str, *, qid: int | None = None) -> ParseResult:
        prepared = self._prepare(question)
        result = self._compile(
            question,
            prepared.annotations,
            prepared.formula,
            prepared.mentions,
            prepared.formula_mentions,
            unresolved_reason=prepared.unresolved_reason,
            qid=qid,
        )
        return ParseResult(
            result.status,
            result.ast,
            result.reason,
            prepared.trace + result.trace,
        )

    def parse_candidates(
        self,
        question: str,
        *,
        qid: int | None = None,
        max_candidates: int = 8,
    ) -> tuple[ParseCandidate, ...]:
        """Compile an N-best semantic set without changing canonical V3 parsing."""
        if max_candidates < 1:
            raise ValueError("max_candidates must be positive")
        prepared = self._prepare(question)
        primary_compiled = self._compile(
            question,
            prepared.annotations,
            prepared.formula,
            prepared.mentions,
            prepared.formula_mentions,
            unresolved_reason=prepared.unresolved_reason,
            qid=qid,
        )
        primary = ParseResult(
            primary_compiled.status,
            primary_compiled.ast,
            primary_compiled.reason,
            prepared.trace + primary_compiled.trace,
        )
        output = [
            ParseCandidate(
                _parse_candidate_id(primary),
                primary,
                "canonical_v3",
                1.0 if primary.ok else 0.0,
                _source_metric_ids(prepared.mentions),
            )
        ]
        seen = {_parse_candidate_key(primary)}
        if prepared.formula is not None or not prepared.source_hypotheses:
            return tuple(output)
        for rank, hypotheses in enumerate(
            _hypothesis_combinations(prepared.source_hypotheses, max_candidates * 3),
            start=1,
        ):
            source_mentions = tuple(_source_metric_mention(value) for value in hypotheses)
            source_mentions = tuple(
                value
                for value in source_mentions
                if not any(
                    value.start < exact.end and exact.start < value.end
                    for exact in prepared.exact_mentions
                )
            )
            mentions = tuple(
                sorted(
                    (*prepared.exact_mentions, *source_mentions),
                    key=lambda value: (value.start, value.end, value.metric.metric_id),
                )
            )
            if not mentions:
                continue
            compiled = self._compile(
                question,
                prepared.annotations,
                prepared.formula,
                mentions,
                prepared.formula_mentions,
                unresolved_reason=None,
                qid=qid,
            )
            trace = prepared.trace + (
                {
                    "stage": "V4_SEMANTIC_HYPOTHESIS",
                    "rank": rank,
                    "source_metric_ids": [value.source_metric_id for value in hypotheses],
                },
            ) + compiled.trace
            result = ParseResult(compiled.status, compiled.ast, compiled.reason, trace)
            key = _parse_candidate_key(result)
            if key in seen:
                continue
            seen.add(key)
            output.append(
                ParseCandidate(
                    _parse_candidate_id(result),
                    result,
                    "source_nbest",
                    max(0.25, 0.95 - 0.05 * (rank - 1)),
                    tuple(value.source_metric_id for value in hypotheses),
                )
            )
            if len(output) >= max_candidates:
                break
        return tuple(output)

    def _prepare(self, question: str) -> _PreparedParse:
        annotations = _expand_aggregate_period_range(question, self.annotator.annotate(question))
        normalized = normalize_phrase(question)
        formula = self.ontology.match_formula(normalized)
        exact_mentions = self._metric_mentions(normalized)
        mentions = exact_mentions
        formula_mentions = self._formula_mentions(normalized)
        role_fallback = _needs_source_role_fallback(normalized, annotations, formula, mentions)
        trace: list[dict[str, object]] = [
            {
                "stage": "ANNOTATE",
                "entities": list(annotations.entities),
                "periods": list(annotations.periods),
                "basis": annotations.basis.value,
                "operation": annotations.operation.value,
                "operation_evidence": annotations.operation_evidence,
                "absolute_difference": annotations.absolute_difference,
            },
            {
                "stage": "ONTOLOGY_MATCH",
                "formula_id": formula.formula_id if formula else None,
                "formula_mentions": [value.formula.formula_id for value in formula_mentions],
                "metric_ids": [mention.metric.metric_id for mention in mentions],
                "ontology_fingerprint": self.ontology.fingerprint,
            },
        ]
        unresolved_reason: str | None = None
        source_hypotheses: tuple[MetricHypothesis, ...] = ()
        if formula is None and self.resolver is not None and (not mentions or role_fallback):
            resolved = self.resolver.resolve(question, annotations)
            source_hypotheses = resolved.hypotheses
            trace.extend(resolved.trace)
            use_selected = resolved.status == "RESOLVED" or (
                role_fallback and bool(resolved.selected)
            )
            if use_selected:
                source_mentions = tuple(
                    _source_metric_mention(value) for value in resolved.selected
                )
                if mentions:
                    # Exact ontology mentions retain precedence. Source evidence
                    # may only fill a missing, non-overlapping semantic role.
                    source_mentions = tuple(
                        value
                        for value in source_mentions
                        if not any(
                            value.start < exact.end and exact.start < value.end
                            for exact in mentions
                        )
                    )
                    mentions = tuple(
                        sorted(
                            (*mentions, *source_mentions),
                            key=lambda value: (value.start, value.end),
                        )
                    )
                else:
                    mentions = source_mentions
            else:
                unresolved_reason = resolved.reason
            if role_fallback:
                annotations = replace(annotations, return_mode=ReturnMode.SELECT_AT_ARG)
                trace.append(
                    {
                        "stage": "V3_ROLE_GRAMMAR",
                        "rule": "entity_has_rank_metric",
                        "return_mode": ReturnMode.SELECT_AT_ARG.value,
                    }
                )
        return _PreparedParse(
            annotations,
            formula,
            exact_mentions,
            mentions,
            formula_mentions,
            source_hypotheses,
            unresolved_reason,
            tuple(trace),
        )

    def _compile(
        self,
        question: str,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
        formula_mentions: tuple[FormulaMention, ...],
        unresolved_reason: str | None,
        *,
        qid: int | None,
    ) -> ParseResult:
        if not annotations.entities and annotations.mode != "screen_open":
            return _abstain("ENTITY_UNRESOLVED")
        if annotations.operation == OperationKind.UNSUPPORTED:
            return _abstain("OPERATION_UNSUPPORTED")

        base = self._base_expression(normalize_phrase(question), annotations, formula, mentions)
        expression_result = self._compose(
            question,
            base,
            annotations,
            formula,
            mentions,
            formula_mentions,
            unresolved_reason=unresolved_reason,
        )
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
        normalized_question: str,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
    ) -> Expression | None:
        if formula is not None:
            return FormulaCall(
                formula.formula_id,
                formula.variant_id,
                _scope_expression(formula.expression, annotations),
                formula.same_entity,
                formula.same_period,
            )
        if not mentions:
            return None
        source_mentions = [value for value in mentions if value.source_binding is not None]
        # Compatibility: the reviewed/exact path retains its measured ordering.
        # Source fallback never uses mention order as a semantic decision.
        mention = (
            max(
                source_mentions,
                key=lambda value: (
                    value.resolution_score,
                    value.end - value.start,
                    -value.start,
                    value.metric.metric_id,
                ),
            )
            if source_mentions
            else mentions[-1]
        )
        reference = _metric_ref(mention.metric, annotations, source_binding=mention.source_binding)
        return MetricRef(
            reference.metric_id,
            reference.entities,
            reference.periods,
            reference.basis,
            reference.statement_types,
            reference.expected_unit,
            reference.period_semantics,
            reference.qualifiers,
            _required_context_phrases(normalized_question, mention.start, mention.end),
            reference.source_binding,
        )

    def _compose(
        self,
        question: str,
        base: Expression | None,
        annotations: QuestionAnnotations,
        formula: FormulaDefinition | None,
        mentions: tuple[MetricMention, ...],
        formula_mentions: tuple[FormulaMention, ...],
        *,
        unresolved_reason: str | None,
    ) -> tuple[Expression, ResultKind] | str:
        operation = annotations.operation
        axis, members = _operation_axis(annotations)
        if operation == OperationKind.LOOKUP and (
            len(annotations.entities) != 1 or len(annotations.periods) != 1
        ):
            return "LOOKUP_SCOPE_NON_SCALAR"
        # Validate the requested scope before ontology promotion policy.  A
        # derived operation with one missing side is a structural parse error,
        # irrespective of whether the surviving metric is reviewed.
        if operation in (OperationKind.SUM, OperationKind.AVERAGE, OperationKind.COUNT) and (
            axis is None or len(members) < 2
        ):
            return "AGGREGATE_AXIS_UNRESOLVED"
        if (
            operation in (OperationKind.SUBTRACT, OperationKind.GROWTH)
            and _binary_scopes(annotations) is None
        ):
            return "BINARY_OPERANDS_UNRESOLVED"
        count_role: tuple[Predicate, Expression] | str | None = None
        if operation == OperationKind.COUNT:
            count_role = _count_predicate_role(
                question,
                annotations,
                mentions,
                formula_mentions,
            )
            if isinstance(count_role, str):
                return count_role
        if (
            not isinstance(base, FormulaCall)
            and any(mention.metric.review_status != "reviewed" for mention in mentions)
            and operation
            not in (
                OperationKind.LOOKUP,
                OperationKind.COUNT,
                OperationKind.EXTREMUM,
            )
        ):
            return "REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION"
        if base is None and not (
            operation == OperationKind.EXTREMUM
            and annotations.return_mode == ReturnMode.SELECT_AT_ARG
        ):
            return unresolved_reason or "METRIC_UNRESOLVED"
        if base is None:
            roles = _select_at_arg_roles(
                question,
                annotations,
                mentions,
                formula_mentions,
            )
            if isinstance(roles, str):
                return roles
            rank_expression, selected_expression = roles
            direction = annotations.rank_direction or RankDirection.DESCENDING
            assert axis is not None
            return (
                SelectAtArg(
                    Rank(axis, members, rank_expression, direction),
                    selected_expression,
                ),
                ResultKind.SCALAR,
            )
        if operation in (OperationKind.LOOKUP, OperationKind.DIVIDE):
            if operation == OperationKind.DIVIDE and not isinstance(base, FormulaCall):
                return "UNREVIEWED_RELATIONAL_FORMULA"
            return base, ResultKind.SCALAR

        if operation in (OperationKind.SUM, OperationKind.AVERAGE, OperationKind.COUNT):
            assert axis is not None
            function = {
                OperationKind.SUM: AggregateFunction.SUM,
                OperationKind.AVERAGE: AggregateFunction.AVERAGE,
                OperationKind.COUNT: AggregateFunction.COUNT,
            }[operation]
            if function == AggregateFunction.COUNT:
                assert count_role is not None and not isinstance(count_role, str)
                predicate, projection = count_role
                return (
                    Aggregate(
                        function,
                        axis,
                        Filter(axis, members, predicate, projection),
                        members,
                    ),
                    ResultKind.SCALAR,
                )
            if axis == Axis.ENTITY:
                filtered_roles = _filtered_aggregate_roles(
                    question,
                    annotations,
                    mentions,
                    formula_mentions,
                )
                if isinstance(filtered_roles, str):
                    return filtered_roles
                if filtered_roles is not None:
                    cohort_predicate, cohort_value = filtered_roles
                    return (
                        Aggregate(
                            function,
                            axis,
                            Filter(axis, members, cohort_predicate, cohort_value),
                            members,
                        ),
                        ResultKind.SCALAR,
                    )
            return Aggregate(function, axis, base, members), ResultKind.SCALAR

        if operation in (OperationKind.SUBTRACT, OperationKind.GROWTH):
            scoped = _binary_scopes(annotations)
            assert scoped is not None
            left_scope, right_scope = scoped
            left = _rescope_expression(base, annotations, left_scope[0], left_scope[1])
            right = _rescope_expression(base, annotations, right_scope[0], right_scope[1])
            operator = (
                ArithmeticOperator.GROWTH
                if operation == OperationKind.GROWTH
                else ArithmeticOperator.SUBTRACT
            )
            expression: Expression = Arithmetic(operator, left, right)
            if operation == OperationKind.SUBTRACT and annotations.absolute_difference:
                expression = Unary(UnaryOperator.ABSOLUTE, expression)
            return expression, ResultKind.SCALAR

        if operation == OperationKind.EXTREMUM:
            if axis is None or len(members) < 2:
                return "RANK_AXIS_UNRESOLVED"
            direction = annotations.rank_direction or RankDirection.DESCENDING
            if annotations.return_mode == ReturnMode.FILTERED_VALUE:
                if formula is None:
                    return "FILTER_PREDICATE_REQUIRED"
                threshold_predicate = _threshold_predicate(question, formula, annotations)
                if threshold_predicate is None:
                    return "FILTER_PREDICATE_REQUIRED"
                if not mentions:
                    return "FILTER_VALUE_METRIC_UNRESOLVED"
                selected_mention = mentions[-1]
                selected_metric = selected_mention.metric
                if not _unit_dimensions_compatible(
                    selected_metric.unit.dimension, annotations.requested_unit.dimension
                ):
                    return "FILTER_VALUE_UNIT_MISMATCH"
                selected = _metric_ref(
                    selected_metric,
                    annotations,
                    source_binding=selected_mention.source_binding,
                )
                filtered_expression = Filter(axis, members, threshold_predicate, selected)
                function = (
                    AggregateFunction.MAXIMUM
                    if direction == RankDirection.DESCENDING
                    else AggregateFunction.MINIMUM
                )
                return Aggregate(function, axis, filtered_expression, members), ResultKind.SCALAR
            if annotations.return_mode == ReturnMode.SELECT_AT_ARG:
                roles = _select_at_arg_roles(
                    question,
                    annotations,
                    mentions,
                    formula_mentions,
                )
                if isinstance(roles, str):
                    return roles
                rank_expression, selected_expression = roles
                return (
                    SelectAtArg(
                        Rank(axis, members, rank_expression, direction), selected_expression
                    ),
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
        if annotations.operation == OperationKind.COUNT:
            return UnitSpec(Dimension.COUNT)
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
        for mention in sorted(
            raw, key=lambda value: (-len(value.alias), value.start, value.metric.metric_id)
        ):
            if any(mention.start >= other.start and mention.end <= other.end for other in selected):
                continue
            selected.append(mention)
        return tuple(sorted(selected, key=lambda value: (value.start, value.end)))

    def _formula_mentions(self, normalized: str) -> tuple[FormulaMention, ...]:
        raw: list[FormulaMention] = []
        for formula in self.ontology.formulas.values():
            for alias in formula.aliases:
                start = normalized.find(alias)
                while start >= 0:
                    raw.append(FormulaMention(start, start + len(alias), alias, formula))
                    start = normalized.find(alias, start + 1)
        selected: list[FormulaMention] = []
        for mention in sorted(
            raw,
            key=lambda value: (-len(value.alias), value.start, value.formula.formula_id),
        ):
            if any(mention.start >= other.start and mention.end <= other.end for other in selected):
                continue
            selected.append(mention)
        return tuple(sorted(selected, key=lambda value: (value.start, value.end)))


def _source_metric_mention(hypothesis: MetricHypothesis) -> MetricMention:
    binding = MetricBindingHint(
        source_metric_id=hypothesis.source_metric_id,
        source_build_id=hypothesis.source_build_id,
        labels=hypothesis.aliases,
        metric_codes=hypothesis.metric_codes,
        row_paths=hypothesis.row_paths,
        resolution_method=hypothesis.match_method,
        question_surface=hypothesis.mention.surface,
        question_start=hypothesis.mention.start,
        question_end=hypothesis.mention.end,
        preferred_basis=hypothesis.preferred_basis,
    )
    metric = MetricDefinition(
        metric_id=hypothesis.source_metric_id,
        aliases=tuple(normalize_phrase(value) for value in hypothesis.aliases),
        statement_types=hypothesis.statement_types,
        unit=hypothesis.unit,
        period_semantics=hypothesis.period_semantics,
        sign_policy="signed_as_reported",
        preferred_basis=hypothesis.preferred_basis,
        review_status="source",
        legal_aggregations=("lookup", "count", "minimum", "maximum"),
    )
    return MetricMention(
        hypothesis.mention.start,
        hypothesis.mention.end,
        hypothesis.mention.normalized_surface,
        metric,
        binding,
        hypothesis.score,
    )


def _hypothesis_combinations(
    hypotheses: tuple[MetricHypothesis, ...],
    limit: int,
) -> tuple[tuple[MetricHypothesis, ...], ...]:
    by_span: dict[tuple[int, int], list[MetricHypothesis]] = {}
    for hypothesis in hypotheses:
        span = (hypothesis.mention.start, hypothesis.mention.end)
        by_span.setdefault(span, []).append(hypothesis)
    groups = tuple(
        tuple(
            sorted(
                values,
                key=lambda value: (
                    tuple(-part for part in value.score),
                    -value.supporting_observations,
                    value.source_metric_id,
                ),
            )[:3]
        )
        for _, values in sorted(by_span.items())
    )
    output: list[tuple[MetricHypothesis, ...]] = []
    seen: set[tuple[tuple[int, int, str], ...]] = set()
    for size in range(len(groups), 0, -1):
        for selected_groups in itertools.combinations(groups, size):
            for values in itertools.product(*selected_groups):
                ordered = tuple(
                    sorted(values, key=lambda value: (value.mention.start, value.mention.end))
                )
                if any(
                    left.mention.start < right.mention.end
                    and right.mention.start < left.mention.end
                    for index, left in enumerate(ordered)
                    for right in ordered[index + 1 :]
                ):
                    continue
                key = tuple(
                    (
                        value.mention.start,
                        value.mention.end,
                        value.source_metric_id,
                    )
                    for value in ordered
                )
                if key in seen:
                    continue
                seen.add(key)
                output.append(ordered)
                if len(output) >= limit:
                    return tuple(output)
    return tuple(output)


def _source_metric_ids(mentions: tuple[MetricMention, ...]) -> tuple[str, ...]:
    return tuple(
        value.source_binding.source_metric_id
        for value in mentions
        if value.source_binding is not None
    )


def _parse_candidate_key(result: ParseResult) -> str:
    payload: object
    if result.ast is None:
        payload = {"status": result.status, "reason": result.reason}
    else:
        payload = {
            "expression": result.ast.to_dict()["expression"],
            "output": result.ast.output.to_dict(),
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_candidate_id(result: ParseResult) -> str:
    digest = hashlib.sha256(_parse_candidate_key(result).encode("utf-8")).hexdigest()[:16]
    return f"semantic-program:{digest}"


def _metric_ref(
    metric: MetricDefinition,
    annotations: QuestionAnnotations,
    *,
    source_binding: MetricBindingHint | None = None,
) -> MetricRef:
    return MetricRef(
        metric_id=metric.metric_id,
        entities=annotations.entities,
        periods=annotations.periods,
        basis=annotations.basis,
        statement_types=metric.statement_types,
        expected_unit=metric.unit,
        period_semantics=metric.period_semantics,
        source_binding=source_binding,
    )


def _scope_expression(expression: Expression, annotations: QuestionAnnotations) -> Expression:
    if isinstance(expression, MetricRef):
        return MetricRef(
            expression.metric_id,
            entities=annotations.entities,
            periods=annotations.periods,
            basis=annotations.basis,
            statement_types=expression.statement_types,
            expected_unit=expression.expected_unit,
            period_semantics=expression.period_semantics,
            qualifiers=expression.qualifiers,
            required_context_phrases=expression.required_context_phrases,
            source_binding=expression.source_binding,
        )
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
    if isinstance(expression, FormulaCall):
        return FormulaCall(
            expression.formula_id,
            expression.variant_id,
            _scope_expression(expression.expression, annotations),
            expression.same_entity,
            expression.same_period,
        )
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


def _unit_dimensions_compatible(source: Dimension, requested: Dimension) -> bool:
    if source == Dimension.UNKNOWN or requested == Dimension.UNKNOWN:
        return True
    if {source, requested} <= {Dimension.RATIO, Dimension.PERCENT}:
        return True
    return source == requested


@dataclass(frozen=True, slots=True)
class _ExpressionMention:
    start: int
    end: int
    identity: str
    expression: Expression
    dimension: Dimension


_SUPERLATIVE = re.compile(r"\b(?:cao nhat|thap nhat|lon nhat|nho nhat)\b")
_RANK_CLAUSE = re.compile(
    r"\b(?:tai nam co|trong nam co|o nam co|nam co|tai nam|cong ty co|doanh nghiep co|ngan hang co)\b"
)

_SOURCE_ROLE_FALLBACK_CLAUSE = re.compile(
    r"\bngan hang co\b[^?]{0,240}\b(?:cao nhat|thap nhat|lon nhat|nho nhat)\b"
)


def _needs_source_role_fallback(
    normalized_question: str,
    annotations: QuestionAnnotations,
    formula: FormulaDefinition | None,
    mentions: tuple[MetricMention, ...],
) -> bool:
    """Open a V3-only role fallback when exact parsing has one missing role.

    A single exact metric in an ``entity has <rank metric>`` clause is not
    sufficient for select-at-arg. The source resolver may supplement it, but
    never replace an exact mention or mutate the shared V2 lexical frame.
    """

    return (
        formula is None
        and annotations.operation == OperationKind.EXTREMUM
        and annotations.return_mode == ReturnMode.VALUE
        and len(mentions) == 1
        and _SOURCE_ROLE_FALLBACK_CLAUSE.search(normalized_question) is not None
    )


def _select_at_arg_roles(
    question: str,
    annotations: QuestionAnnotations,
    metric_mentions: tuple[MetricMention, ...],
    formula_mentions: tuple[FormulaMention, ...],
) -> tuple[Expression, Expression] | str:
    """Resolve ranking and selected expressions from their lexical spans.

    Vietnamese select-at-arg questions place the ranking expression inside a
    ``năm có ... cao/thấp nhất`` clause and the returned expression outside it.
    Role assignment by mention order is therefore invalid in both common word
    orders. This compiler uses clause boundaries and requested output types.
    """

    normalized = normalize_phrase(question)
    extremes = tuple(_SUPERLATIVE.finditer(normalized))
    if not extremes:
        return "SELECT_AT_ARG_SUPERLATIVE_UNRESOLVED"
    extreme = extremes[-1]
    clause_matches = tuple(_RANK_CLAUSE.finditer(normalized, 0, extreme.start()))
    if not clause_matches:
        return "SELECT_AT_ARG_RANK_CLAUSE_UNRESOLVED"
    clause_start = clause_matches[-1].start()
    candidates = _expression_mentions(normalized, annotations, metric_mentions, formula_mentions)
    ranked = [
        value
        for value in candidates
        if value.start >= clause_start and value.end <= extreme.start()
    ]
    if not ranked:
        return "SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED"
    rank = max(ranked, key=lambda value: (value.end, value.end - value.start))
    rank_clause = normalized[clause_start : extreme.start()]
    rank_surface = normalized[rank.start : rank.end]
    if re.search(r"\btren\b", rank_clause) and not re.search(r"\btren\b", rank_surface):
        return "SELECT_AT_ARG_RANK_FORMULA_UNRESOLVED"

    requested = annotations.requested_unit.dimension
    prefix = [
        value
        for value in candidates
        if value.end <= clause_start and _selected_dimension_compatible(value.dimension, requested)
    ]
    suffix = [
        value
        for value in candidates
        if value.start >= extreme.end()
        and _selected_dimension_compatible(value.dimension, requested)
    ]
    if suffix:
        selected = min(suffix, key=lambda value: (value.start, -(value.end - value.start)))
    elif prefix:
        selected = max(prefix, key=lambda value: (value.end, value.end - value.start))
    else:
        return "SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED"
    if rank.identity == selected.identity:
        return "SELECT_AT_ARG_ROLE_COLLISION"
    selected_clause = normalized[
        max(0, selected.start - 100) : min(clause_start, selected.end + 100)
    ]
    if re.search(r"\bchi phi\b[^,?]{0,80}\bva\s+chi phi\b", selected_clause):
        return "SELECT_AT_ARG_SELECTED_COMPOSITE_UNRESOLVED"
    return rank.expression, _apply_selected_output_unit(
        selected.expression, annotations.requested_unit
    )


def _selected_dimension_compatible(source: Dimension, requested: Dimension) -> bool:
    # A ratio-like result is necessarily derived unless the ontology explicitly
    # types it as ratio/percent. An UNKNOWN catalog metric must not stand in for
    # one operand of an unreviewed quotient merely because its runtime unit has
    # not yet been resolved.
    if requested in (Dimension.RATIO, Dimension.PERCENT, Dimension.PERCENT_POINT):
        return source in (Dimension.RATIO, Dimension.PERCENT, Dimension.PERCENT_POINT)
    return _unit_dimensions_compatible(source, requested)


def _apply_selected_output_unit(expression: Expression, requested: UnitSpec) -> Expression:
    if (
        isinstance(expression, MetricRef)
        and expression.expected_unit is not None
        and expression.expected_unit.dimension == Dimension.UNKNOWN
        and requested.is_known
    ):
        return MetricRef(
            expression.metric_id,
            expression.entities,
            expression.periods,
            expression.basis,
            expression.statement_types,
            requested,
            expression.period_semantics,
            expression.qualifiers,
            expression.required_context_phrases,
            expression.source_binding,
        )
    return expression


def _expression_mentions(
    normalized_question: str,
    annotations: QuestionAnnotations,
    metric_mentions: tuple[MetricMention, ...],
    formula_mentions: tuple[FormulaMention, ...],
) -> tuple[_ExpressionMention, ...]:
    output: list[_ExpressionMention] = []
    for formula_mention in formula_mentions:
        formula = formula_mention.formula
        output.append(
            _ExpressionMention(
                formula_mention.start,
                formula_mention.end,
                f"formula:{formula.formula_id}:{formula.variant_id}",
                FormulaCall(
                    formula.formula_id,
                    formula.variant_id,
                    _scope_expression(formula.expression, annotations),
                    formula.same_entity,
                    formula.same_period,
                ),
                formula.output_unit.dimension,
            )
        )
    for metric_mention in metric_mentions:
        if any(
            metric_mention.start >= formula_mention.start
            and metric_mention.end <= formula_mention.end
            for formula_mention in formula_mentions
        ):
            continue
        reference = _metric_ref(
            metric_mention.metric,
            annotations,
            source_binding=metric_mention.source_binding,
        )
        reference = MetricRef(
            reference.metric_id,
            reference.entities,
            reference.periods,
            reference.basis,
            reference.statement_types,
            reference.expected_unit,
            reference.period_semantics,
            _qualifier_tokens(normalized_question, metric_mention.start, metric_mention.end),
            _required_context_phrases(
                normalized_question, metric_mention.start, metric_mention.end
            ),
            reference.source_binding,
        )
        output.append(
            _ExpressionMention(
                metric_mention.start,
                metric_mention.end,
                f"metric:{metric_mention.metric.metric_id}",
                reference,
                metric_mention.metric.unit.dimension,
            )
        )
    return tuple(sorted(output, key=lambda value: (value.start, value.end)))


_QUALIFIER_STOPWORDS = frozenset(
    {
        "bao",
        "cao",
        "cac",
        "cho",
        "co",
        "cong",
        "cua",
        "do",
        "dong",
        "gia",
        "la",
        "lon",
        "nam",
        "nhat",
        "nhieu",
        "tai",
        "tap",
        "theo",
        "thi",
        "trong",
        "ty",
        "va",
        "vao",
        "voi",
    }
)


def _qualifier_tokens(
    normalized_question: str, mention_start: int, mention_end: int
) -> tuple[str, ...]:
    window = normalized_question[max(0, mention_start - 100) : mention_end + 140]
    tokens = re.findall(r"[a-z][a-z0-9]+", window)
    return tuple(
        dict.fromkeys(
            token
            for token in tokens
            if len(token) >= 3
            and token not in _QUALIFIER_STOPWORDS
            and not re.fullmatch(r"(?:19|20)\d{2}", token)
        )
    )


_COUNTERPARTY_RELATION = re.compile(
    r"\b(?:tu|cho)\s+(?:cong ty\s+)?(?P<name>"
    r"(?:ctcp|tnhh|ngan hang|cong ty)\s+[a-z0-9 -]{2,100}?)\s+"
    r"cua\s+(?:tap doan|tong cong ty|cong ty|ctcp|ngan hang)\b"
)


def _required_context_phrases(
    normalized_question: str, mention_start: int, mention_end: int
) -> tuple[str, ...]:
    """Extract an explicit nested-counterparty selector, never an inferred name."""
    phrases = []
    for match in _COUNTERPARTY_RELATION.finditer(normalized_question):
        if mention_end > match.start() or match.start() - mention_end > 80:
            continue
        phrase = " ".join(match.group("name").split())
        if len(phrase.split()) >= 2:
            phrases.append(phrase)
    return tuple(dict.fromkeys(phrases))


_PERCENT_THRESHOLD = re.compile(
    r"\b(?P<operator>lon hon|vuot|cao hon|tren|it nhat|khong duoi|nho hon|thap hon|duoi)\s*"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*%"
)

_COHORT_THRESHOLD = re.compile(
    r"\b(?:(?P<from>tu)\s+)?"
    r"(?P<operator>lon hon|vuot|cao hon|tren|it nhat|khong duoi|"
    r"nho hon|thap hon|duoi)?\s*"
    r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>%|lan)?"
    r"(?:\s*tro len)?\b"
)


def _count_predicate_role(
    question: str,
    annotations: QuestionAnnotations,
    metric_mentions: tuple[MetricMention, ...],
    formula_mentions: tuple[FormulaMention, ...],
) -> tuple[Predicate, Expression] | str:
    """Compile an explicit numeric predicate for a finite-domain count.

    COUNT is accepted only when the question provides an explicit comparison
    or sign and a uniquely resolved expression. This keeps the route closed:
    implicit notions such as "healthy" or "material" abstain.
    """

    normalized = normalize_phrase(question)
    candidates = _expression_mentions(normalized, annotations, metric_mentions, formula_mentions)
    threshold_matches = [
        match
        for match in _COHORT_THRESHOLD.finditer(normalized)
        if match.group("operator") or match.group("from") or "tro len" in match.group(0)
    ]
    if not threshold_matches:
        sign_role = _count_sign_predicate_role(normalized, candidates)
        if sign_role is not None:
            return sign_role
        single_sign_role = _single_count_sign_predicate_role(normalized, candidates)
        if single_sign_role is not None:
            return single_sign_role
    if len(threshold_matches) != 1:
        return "COUNT_PREDICATE_REQUIRED"
    threshold = threshold_matches[0]
    preceding = [value for value in candidates if value.end <= threshold.start()]
    if not preceding:
        return "COUNT_PREDICATE_EXPRESSION_UNRESOLVED"
    nearest_end = max(value.end for value in preceding)
    nearest = [value for value in preceding if value.end == nearest_end]
    identities = {value.identity for value in nearest}
    if len(identities) != 1:
        return "COUNT_PREDICATE_EXPRESSION_AMBIGUOUS"
    expression = max(nearest, key=lambda value: value.end - value.start)
    if threshold.start() - expression.end > 80:
        return "COUNT_PREDICATE_EXPRESSION_UNRESOLVED"

    operator = {
        "lon hon": ComparisonOperator.GT,
        "vuot": ComparisonOperator.GT,
        "cao hon": ComparisonOperator.GT,
        "tren": ComparisonOperator.GT,
        "it nhat": ComparisonOperator.GE,
        "khong duoi": ComparisonOperator.GE,
        "nho hon": ComparisonOperator.LT,
        "thap hon": ComparisonOperator.LT,
        "duoi": ComparisonOperator.LT,
        "": ComparisonOperator.GE,
    }[threshold.group("operator") or ""]
    value = float(threshold.group("value").replace(",", "."))
    unit_dimension, unit_scale, _ = scan_unit(normalized[threshold.start() : threshold.end() + 40])
    literal_dimension = {
        "MONEY": Dimension.MONEY,
        "PERCENT": Dimension.PERCENT,
        "PERCENT_POINT": Dimension.PERCENT_POINT,
        "RATIO": Dimension.RATIO,
        "COUNT": Dimension.COUNT,
        "SHARES": Dimension.SHARES,
        "UNKNOWN": expression.dimension,
    }[unit_dimension]
    literal_unit = UnitSpec(literal_dimension, unit_scale)
    if not _unit_dimensions_compatible(expression.dimension, literal_unit.dimension):
        return "COUNT_PREDICATE_UNIT_MISMATCH"
    return (
        Comparison(
            operator,
            expression.expression,
            Literal(value, literal_unit),
        ),
        expression.expression,
    )


def _single_count_sign_predicate_role(
    normalized_question: str,
    candidates: tuple[_ExpressionMention, ...],
) -> tuple[Predicate, Expression] | None:
    """Compile one explicit ``metric âm/dương`` predicate for COUNT."""

    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    clause = normalized_question[candidate.end : candidate.end + 80]
    signs = re.findall(r"\b(am|duong)\b", clause)
    if len(signs) != 1:
        return None
    operator = ComparisonOperator.LT if signs[0] == "am" else ComparisonOperator.GT
    predicate = Comparison(
        operator,
        candidate.expression,
        Literal(0, UnitSpec(candidate.dimension)),
    )
    return predicate, candidate.expression


def _count_sign_predicate_role(
    normalized_question: str,
    candidates: tuple[_ExpressionMention, ...],
) -> tuple[Predicate, Expression] | None:
    """Compile explicit simultaneous positive/negative predicates.

    The construction is deliberately narrow: every expression must be
    followed by exactly one sign word in its own clause and the question must
    say ``đồng thời``. Implicit polarity and inferred conjunction are rejected.
    """

    if "dong thoi" not in normalized_question or len(candidates) < 2:
        return None
    predicates: list[Comparison] = []
    used: list[_ExpressionMention] = []
    ordered = sorted(candidates, key=lambda value: (value.start, value.end))
    for index, candidate in enumerate(ordered):
        clause_end = (
            ordered[index + 1].start if index + 1 < len(ordered) else len(normalized_question)
        )
        clause = normalized_question[candidate.end : min(clause_end, candidate.end + 80)]
        signs = re.findall(r"\b(am|duong)\b", clause)
        if len(signs) != 1:
            continue
        operator = ComparisonOperator.LT if signs[0] == "am" else ComparisonOperator.GT
        predicates.append(
            Comparison(
                operator,
                candidate.expression,
                Literal(0, UnitSpec(candidate.dimension)),
            )
        )
        used.append(candidate)
    if len(predicates) < 2 or len({value.identity for value in used}) != len(used):
        return None
    return LogicalPredicate(LogicalOperator.AND, tuple(predicates)), used[0].expression


def _filtered_aggregate_roles(
    question: str,
    annotations: QuestionAnnotations,
    metric_mentions: tuple[MetricMention, ...],
    formula_mentions: tuple[FormulaMention, ...],
) -> tuple[Comparison, Expression] | str | None:
    """Compile an explicit numeric cohort predicate for SUM/AVERAGE.

    This route is intentionally closed: the predicate must contain a reviewed
    expression immediately before an explicit numeric threshold, and exactly
    one different output-compatible expression must remain. Ambiguous clauses
    abstain instead of falling back to the aggregate base metric.
    """

    normalized = normalize_phrase(question)
    if not re.search(r"\b(?:cac cong ty|cac doanh nghiep|trong so|trong nhom)\b", normalized):
        return None
    candidates = _expression_mentions(normalized, annotations, metric_mentions, formula_mentions)
    if len(candidates) < 2:
        return None
    threshold_matches = [
        match
        for match in _COHORT_THRESHOLD.finditer(normalized)
        if match.group("operator") or match.group("from") or "tro len" in match.group(0)
    ]
    if not threshold_matches:
        return None
    threshold = threshold_matches[0]
    preceding = [value for value in candidates if value.end <= threshold.start()]
    if not preceding:
        return "FILTER_PREDICATE_EXPRESSION_UNRESOLVED"
    predicate_expression = max(preceding, key=lambda value: (value.end, value.end - value.start))
    if threshold.start() - predicate_expression.end > 80:
        return "FILTER_PREDICATE_EXPRESSION_UNRESOLVED"

    operator_token = threshold.group("operator") or ""
    operator = {
        "lon hon": ComparisonOperator.GT,
        "vuot": ComparisonOperator.GT,
        "cao hon": ComparisonOperator.GT,
        "tren": ComparisonOperator.GT,
        "it nhat": ComparisonOperator.GE,
        "khong duoi": ComparisonOperator.GE,
        "nho hon": ComparisonOperator.LT,
        "thap hon": ComparisonOperator.LT,
        "duoi": ComparisonOperator.LT,
        "": ComparisonOperator.GE,
    }[operator_token]
    value = float(threshold.group("value").replace(",", "."))
    explicit_unit = threshold.group("unit")
    literal_dimension = (
        Dimension.PERCENT
        if explicit_unit == "%"
        else Dimension.RATIO
        if explicit_unit == "lan"
        else predicate_expression.dimension
    )
    if not _unit_dimensions_compatible(predicate_expression.dimension, literal_dimension):
        return "FILTER_PREDICATE_UNIT_MISMATCH"
    predicate = Comparison(
        operator,
        predicate_expression.expression,
        Literal(value, UnitSpec(literal_dimension)),
    )

    selected = [
        candidate
        for candidate in candidates
        if candidate.identity != predicate_expression.identity
        and _selected_dimension_compatible(
            candidate.dimension, annotations.requested_unit.dimension
        )
    ]
    if selected:
        best_specificity = max(
            _selection_specificity(candidate.dimension, annotations.requested_unit.dimension)
            for candidate in selected
        )
        selected = [
            candidate
            for candidate in selected
            if _selection_specificity(candidate.dimension, annotations.requested_unit.dimension)
            == best_specificity
        ]
    by_identity = {candidate.identity: candidate for candidate in selected}
    if not by_identity:
        return "FILTER_SELECTED_EXPRESSION_UNRESOLVED"
    if len(by_identity) > 1:
        return "FILTER_SELECTED_EXPRESSION_AMBIGUOUS"
    chosen = next(iter(by_identity.values()))
    return predicate, _apply_selected_output_unit(
        _without_qualifiers(chosen.expression), annotations.requested_unit
    )


def _without_qualifiers(expression: Expression) -> Expression:
    if not isinstance(expression, MetricRef) or not expression.qualifiers:
        return expression
    return MetricRef(
        expression.metric_id,
        expression.entities,
        expression.periods,
        expression.basis,
        expression.statement_types,
        expression.expected_unit,
        expression.period_semantics,
        (),
        expression.required_context_phrases,
        expression.source_binding,
    )


def _selection_specificity(source: Dimension, requested: Dimension) -> int:
    if source == requested:
        return 2
    if {source, requested} <= {Dimension.RATIO, Dimension.PERCENT}:
        return 2
    return 0 if source == Dimension.UNKNOWN else 1


def _threshold_predicate(
    question: str,
    formula: FormulaDefinition,
    annotations: QuestionAnnotations,
) -> Comparison | None:
    """Compile an explicit percentage threshold into a typed predicate.

    Only reviewed formula aliases and explicit numeric thresholds are accepted.
    This deliberately rejects implicit comparisons and domain-specific defaults.
    """

    match = _PERCENT_THRESHOLD.search(normalize_phrase(question))
    if match is None:
        return None
    operator = {
        "lon hon": ComparisonOperator.GT,
        "vuot": ComparisonOperator.GT,
        "cao hon": ComparisonOperator.GT,
        "tren": ComparisonOperator.GT,
        "it nhat": ComparisonOperator.GE,
        "khong duoi": ComparisonOperator.GE,
        "nho hon": ComparisonOperator.LT,
        "thap hon": ComparisonOperator.LT,
        "duoi": ComparisonOperator.LT,
    }[match.group("operator")]
    value = float(match.group("value").replace(",", "."))
    scoped_formula = FormulaCall(
        formula.formula_id,
        formula.variant_id,
        _scope_expression(formula.expression, annotations),
        formula.same_entity,
        formula.same_period,
    )
    return Comparison(operator, scoped_formula, Literal(value, UnitSpec(Dimension.PERCENT)))


def _expand_aggregate_period_range(
    question: str, annotations: QuestionAnnotations
) -> QuestionAnnotations:
    """Materialize inclusive year domains for aggregate/rank operations.

    The lexical recognizer intentionally extracts endpoints. Semantic operators
    over a stated ``giai doan`` require the complete finite domain instead.
    Binary change/difference operations keep endpoint semantics.
    """

    if annotations.operation not in {
        OperationKind.SUM,
        OperationKind.AVERAGE,
        OperationKind.COUNT,
        OperationKind.EXTREMUM,
    }:
        return annotations
    if len(annotations.periods) != 2 or "giai doan" not in normalize_phrase(question):
        return annotations
    try:
        start, end = sorted(int(value[:4]) for value in annotations.periods)
    except ValueError:
        return annotations
    if end - start < 2 or end - start > 50:
        return annotations
    return QuestionAnnotations(
        entities=annotations.entities,
        periods=tuple(str(year) for year in range(start, end + 1)),
        basis=annotations.basis,
        requested_unit=annotations.requested_unit,
        operation=annotations.operation,
        mode=annotations.mode,
        rank_direction=annotations.rank_direction,
        return_mode=annotations.return_mode,
        reverse_difference=annotations.reverse_difference,
        absolute_difference=annotations.absolute_difference,
        operation_evidence=annotations.operation_evidence,
    )


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
        absolute_difference=annotations.absolute_difference,
        operation_evidence=annotations.operation_evidence,
    )
    return _scope_expression(expression, scoped_annotations)


def _abstain(reason: str) -> ParseResult:
    return ParseResult("ABSTAIN", reason=reason)
