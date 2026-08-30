"""Fail-closed structural gates for the five Recovery Wave 5 Risk-A families."""

from __future__ import annotations

from dataclasses import dataclass

from text2pandas.application.binding import BoundExecutionPlan
from text2pandas.domain.semantic import (
    Aggregate,
    AggregateFunction,
    Arithmetic,
    ArithmeticOperator,
    Axis,
    Dimension,
    FormulaCall,
    MetricRef,
    ObservationRowRole,
    QuestionAST,
    ResultKind,
    Unary,
)
from text2pandas.domain.semantic.ast import Expression


@dataclass(frozen=True, slots=True)
class FamilyCompletenessResult:
    family: str
    failures: tuple[str, ...]
    expected_members: tuple[str, ...] = ()
    bound_members: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures


def validate_family_completeness(
    bound: BoundExecutionPlan,
) -> FamilyCompletenessResult:
    """Validate only a recognized direct Risk-A family; other ASTs are deferred."""

    expression = _unwrap(bound.plan.ast.expression)
    if isinstance(expression, MetricRef):
        return _validate_lookup(bound, bound.plan.ast)
    if isinstance(expression, Arithmetic):
        if expression.operator is ArithmeticOperator.DIVIDE:
            return _validate_binary(bound, "direct_ratio", require_distinct=False)
        if expression.operator is ArithmeticOperator.SUBTRACT:
            return _validate_binary(bound, "two_period_difference", require_distinct=True)
        return FamilyCompletenessResult("out_of_scope", ())
    if isinstance(expression, Aggregate):
        if expression.function is AggregateFunction.SUM:
            return _validate_aggregate(bound, expression, "single_metric_sum")
        if expression.function is AggregateFunction.AVERAGE:
            return _validate_aggregate(bound, expression, "single_metric_average")
    return FamilyCompletenessResult("out_of_scope", ())


def _validate_lookup(
    bound: BoundExecutionPlan, ast: QuestionAST
) -> FamilyCompletenessResult:
    failures: list[str] = []
    if ast.output.result_kind is not ResultKind.SCALAR:
        failures.append("DIRECT_LOOKUP_OUTPUT_NOT_SCALAR")
    if len(bound.operands) != 1:
        failures.append("DIRECT_LOOKUP_CARDINALITY")
    _append_role_proof_failures(bound, failures)
    return FamilyCompletenessResult("direct_lookup", tuple(failures))


def _validate_binary(
    bound: BoundExecutionPlan,
    family: str,
    *,
    require_distinct: bool,
) -> FamilyCompletenessResult:
    failures: list[str] = []
    if len(bound.operands) != 2:
        failures.append("BINARY_OPERAND_CARDINALITY")
    operands = list(bound.operands.values())
    if len(operands) == 2:
        left, right = operands
        if left.request.entity != right.request.entity:
            failures.append("BINARY_ENTITY_MISMATCH")
        if left.candidate.basis != right.candidate.basis:
            failures.append("BINARY_BASIS_MISMATCH")
        if require_distinct:
            if left.request.metric_id != right.request.metric_id:
                failures.append("DIFFERENCE_METRIC_MISMATCH")
            if left.request.period == right.request.period:
                failures.append("DIFFERENCE_PERIOD_NOT_DISTINCT")
            if left.candidate.observation_uid == right.candidate.observation_uid:
                failures.append("DIFFERENCE_OBSERVATION_NOT_DISTINCT")
        else:
            if left.request.period != right.request.period:
                failures.append("RATIO_PERIOD_MISMATCH")
    _append_role_proof_failures(bound, failures)
    return FamilyCompletenessResult(family, tuple(failures))


def _validate_aggregate(
    bound: BoundExecutionPlan,
    expression: Aggregate,
    family: str,
) -> FamilyCompletenessResult:
    failures: list[str] = []
    expected = tuple(dict.fromkeys(expression.members))
    if not expected:
        failures.append("AGGREGATE_MEMBER_DOMAIN_EMPTY")
    bound_members: list[str] = []
    for operand in bound.operands.values():
        member = (
            operand.request.entity
            if expression.axis is Axis.ENTITY
            else operand.request.period
        )
        if member is None:
            failures.append("AGGREGATE_MEMBER_KEY_MISSING")
        else:
            bound_members.append(member)
    if len(bound_members) != len(set(bound_members)):
        failures.append("AGGREGATE_MEMBER_DUPLICATE")
    if set(bound_members) != set(expected):
        failures.append("AGGREGATE_MEMBER_DOMAIN_INCOMPLETE")
    metric_ids = {operand.request.metric_id for operand in bound.operands.values()}
    if len(metric_ids) != 1:
        failures.append("AGGREGATE_METRIC_MISMATCH")
    bases = {operand.candidate.basis for operand in bound.operands.values()}
    if len(bases) != 1:
        failures.append("AGGREGATE_BASIS_MISMATCH")
    periods = {operand.request.period for operand in bound.operands.values()}
    if expression.axis is Axis.ENTITY and len(periods) != 1:
        failures.append("AGGREGATE_PERIOD_MISMATCH")
    row_roles = {
        operand.candidate.row_role
        for operand in bound.operands.values()
        if operand.candidate.row_role is not ObservationRowRole.UNKNOWN
    }
    if ObservationRowRole.TOTAL in row_roles and ObservationRowRole.CHILD in row_roles:
        failures.append("AGGREGATE_TOTAL_CHILD_MIX")
    column_roles = {operand.candidate.column_role for operand in bound.operands.values()}
    if len(column_roles) != 1:
        failures.append("AGGREGATE_COLUMN_ROLE_MISMATCH")
    _append_role_proof_failures(bound, failures)
    return FamilyCompletenessResult(
        family,
        tuple(dict.fromkeys(failures)),
        expected_members=tuple(sorted(expected)),
        bound_members=tuple(sorted(bound_members)),
    )


def _append_role_proof_failures(
    bound: BoundExecutionPlan, failures: list[str]
) -> None:
    for request_id, operand in sorted(bound.operands.items()):
        if operand.request.observation_role is None:
            failures.append(f"OBSERVATION_ROLE_SPEC_MISSING:{request_id}")
        if (
            operand.candidate.unit.dimension is Dimension.MONEY
            and operand.candidate.scale_source in {None, "none", "assumed", "unknown"}
        ):
            failures.append(f"SCALE_SOURCE_UNSAFE:{request_id}")


def _unwrap(expression: Expression) -> Expression:
    while isinstance(expression, (FormulaCall, Unary)):
        expression = expression.expression
    return expression
