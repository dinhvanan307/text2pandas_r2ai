"""Expand semantic metric references into independently retrievable operands."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import product

from text2pandas.domain.metrics import MetricOntology
from text2pandas.domain.semantic import (
    Aggregate,
    Arithmetic,
    Comparison,
    Exists,
    Filter,
    FormulaCall,
    Literal,
    LogicalPredicate,
    MetricRef,
    QuantifiedPredicate,
    QuestionAST,
    Rank,
    RollingAverage,
    RollingGrowth,
    SelectAtArg,
    Unary,
)
from text2pandas.domain.semantic.ast import Expression, Predicate

from .contracts import BindingConstraint, ConstraintKind, ExecutionPlan, OperandRequest
from .observation_roles import infer_observation_role_spec


class PlanningError(ValueError):
    pass


@dataclass(slots=True)
class _RequestAccumulator:
    metric_id: str
    entity: str | None
    period: str | None
    ref: MetricRef
    consumers: list[str] = field(default_factory=list)


def compile_execution_plan(
    ast: QuestionAST,
    ontology: MetricOntology,
    *,
    infer_observation_roles: bool = False,
) -> ExecutionPlan:
    requests: dict[tuple[object, ...], _RequestAccumulator] = {}
    formula_scopes: list[tuple[str, bool, set[tuple[object, ...]]]] = []
    _collect(ast.expression, "$.expression", requests, formula_scopes)
    if not requests:
        raise PlanningError("semantic expression contains no metric operands")

    materialized: dict[tuple[object, ...], OperandRequest] = {}
    for key, item in sorted(requests.items(), key=lambda value: repr(value[0])):
        metric = ontology.metrics.get(item.metric_id)
        source_binding = item.ref.source_binding
        if metric is None and source_binding is None:
            raise PlanningError(f"unknown ontology metric: {item.metric_id}")
        if source_binding is not None:
            if source_binding.source_metric_id != item.metric_id:
                raise PlanningError(
                    "source binding metric mismatch: "
                    f"{item.metric_id}!={source_binding.source_metric_id}"
                )
            if not source_binding.source_build_id or not source_binding.labels:
                raise PlanningError(f"incomplete source binding hint: {item.metric_id}")
        if metric is not None:
            preferred_basis = metric.preferred_basis
            statement_types = item.ref.statement_types or metric.statement_types
            expected_unit = item.ref.expected_unit or metric.unit
            period_semantics = (
                item.ref.period_semantics
                if item.ref.period_semantics.value != "unknown"
                else metric.period_semantics
            )
        else:
            assert source_binding is not None
            if item.ref.expected_unit is None:
                raise PlanningError(f"source metric has no expected unit: {item.metric_id}")
            preferred_basis = source_binding.preferred_basis
            statement_types = item.ref.statement_types
            expected_unit = item.ref.expected_unit
            period_semantics = item.ref.period_semantics
        request_id = _request_id(key)
        observation_role = item.ref.observation_role
        if observation_role is None and infer_observation_roles:
            observation_role = infer_observation_role_spec(
                item.ref,
                question=ast.question,
                entity=item.entity,
            )
        materialized[key] = OperandRequest(
            request_id=request_id,
            metric_id=item.metric_id,
            entity=item.entity,
            period=item.period,
            basis=item.ref.basis,
            preferred_basis=preferred_basis,
            statement_types=statement_types,
            expected_unit=expected_unit,
            period_semantics=period_semantics,
            qualifiers=item.ref.qualifiers,
            consumers=tuple(sorted(item.consumers)),
            required_context_phrases=item.ref.required_context_phrases,
            source_binding=source_binding,
            observation_role=observation_role,
        )

    constraints: list[BindingConstraint] = []
    by_consumer: dict[str, list[str]] = defaultdict(list)
    for request in materialized.values():
        for consumer in request.consumers:
            by_consumer[consumer].append(request.request_id)
    for consumer, request_ids in sorted(by_consumer.items()):
        unique = tuple(sorted(set(request_ids)))
        if len(unique) < 2:
            continue
        reason = f"semantic_series:{consumer}"
        constraints.extend(
            (
                BindingConstraint(ConstraintKind.SAME_BASIS, unique, reason),
                BindingConstraint(ConstraintKind.SAME_CURRENCY, unique, reason),
                BindingConstraint(ConstraintKind.SAME_DIMENSION, unique, reason),
            )
        )
    for formula_id, same_period, keys in formula_scopes:
        by_scope: dict[tuple[str | None, str | None], list[str]] = defaultdict(list)
        for key in keys:
            request = materialized[key]
            by_scope[(request.entity, request.period)].append(request.request_id)
        for scope, request_ids in sorted(by_scope.items(), key=lambda value: repr(value[0])):
            unique = tuple(sorted(set(request_ids)))
            if len(unique) < 2:
                continue
            reason = f"reviewed_formula:{formula_id}:scope={scope[0]}:{scope[1]}"
            constraints.extend(
                (
                    BindingConstraint(ConstraintKind.SAME_DOCUMENT, unique, reason),
                    BindingConstraint(ConstraintKind.SAME_CURRENCY, unique, reason),
                    BindingConstraint(ConstraintKind.DISTINCT_OBSERVATIONS, unique, reason),
                )
            )
            if same_period:
                constraints.append(BindingConstraint(ConstraintKind.SAME_PERIOD, unique, reason))
    return ExecutionPlan(
        ast=ast,
        requests=tuple(sorted(materialized.values(), key=lambda value: value.request_id)),
        constraints=tuple(dict.fromkeys(constraints)),
        ontology_fingerprint=ontology.fingerprint,
    )


def _collect(
    expression: Expression,
    path: str,
    requests: dict[tuple[object, ...], _RequestAccumulator],
    formula_scopes: list[tuple[str, bool, set[tuple[object, ...]]]],
) -> set[tuple[object, ...]]:
    if isinstance(expression, MetricRef):
        entities: tuple[str | None, ...] = expression.entities or (None,)
        periods: tuple[str | None, ...] = expression.periods or (None,)
        keys: set[tuple[object, ...]] = set()
        for entity, period in product(entities, periods):
            key: tuple[object, ...] = (
                expression.metric_id,
                entity,
                period,
                expression.basis.value,
                expression.statement_types,
                expression.qualifiers,
                expression.required_context_phrases,
                repr(expression.observation_role.to_dict())
                if expression.observation_role is not None
                else None,
            )
            if expression.source_binding is not None:
                key = (*key, repr(expression.source_binding.to_dict()))
            item = requests.setdefault(
                key,
                _RequestAccumulator(expression.metric_id, entity, period, expression),
            )
            item.consumers.append(path)
            keys.add(key)
        return keys
    if isinstance(expression, Literal):
        return set()
    if isinstance(expression, Arithmetic):
        return _collect(expression.left, f"{path}.left", requests, formula_scopes) | _collect(
            expression.right, f"{path}.right", requests, formula_scopes
        )
    if isinstance(expression, Unary):
        return _collect(expression.expression, f"{path}.expression", requests, formula_scopes)
    if isinstance(expression, RollingAverage):
        return _collect(expression.expression, f"{path}.expression", requests, formula_scopes)
    if isinstance(expression, RollingGrowth):
        return _collect(expression.expression, f"{path}.expression", requests, formula_scopes)
    if isinstance(expression, FormulaCall):
        keys = _collect(expression.expression, f"{path}.expression", requests, formula_scopes)
        formula_scopes.append((expression.formula_id, expression.same_period, keys))
        return keys
    if isinstance(expression, Aggregate):
        return _collect(expression.expression, f"{path}.expression", requests, formula_scopes)
    if isinstance(expression, Filter):
        return _collect(
            expression.expression, f"{path}.expression", requests, formula_scopes
        ) | _collect_predicate(expression.predicate, f"{path}.predicate", requests, formula_scopes)
    if isinstance(expression, Rank):
        return _collect(expression.by, f"{path}.by", requests, formula_scopes)
    if isinstance(expression, SelectAtArg):
        return _collect(expression.rank, f"{path}.rank", requests, formula_scopes) | _collect(
            expression.expression, f"{path}.expression", requests, formula_scopes
        )
    raise TypeError(f"unsupported expression: {type(expression).__name__}")


def _collect_predicate(
    predicate: Predicate,
    path: str,
    requests: dict[tuple[object, ...], _RequestAccumulator],
    formula_scopes: list[tuple[str, bool, set[tuple[object, ...]]]],
) -> set[tuple[object, ...]]:
    if isinstance(predicate, Comparison):
        return _collect(predicate.left, f"{path}.left", requests, formula_scopes) | _collect(
            predicate.right, f"{path}.right", requests, formula_scopes
        )
    if isinstance(predicate, Exists):
        return _collect(predicate.expression, f"{path}.expression", requests, formula_scopes)
    if isinstance(predicate, LogicalPredicate):
        keys: set[tuple[object, ...]] = set()
        for index, child in enumerate(predicate.predicates):
            keys |= _collect_predicate(
                child, f"{path}.predicates[{index}]", requests, formula_scopes
            )
        return keys
    if isinstance(predicate, QuantifiedPredicate):
        return _collect_predicate(
            predicate.predicate, f"{path}.predicate", requests, formula_scopes
        )
    raise TypeError(f"unsupported predicate: {type(predicate).__name__}")


def _request_id(key: tuple[object, ...]) -> str:
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:20]
    return f"operand:{digest}"
