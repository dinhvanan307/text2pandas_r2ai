"""Beam-search global assignment under explicit semantic constraints."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from text2pandas.application.planning import ConstraintKind, ExecutionPlan
from text2pandas.application.retrieval import CandidateBatch, ObservationCandidate
from text2pandas.domain.semantic import Dimension

from .contracts import BindingResult, BoundExecutionPlan, BoundOperand


@dataclass(slots=True)
class _State:
    score: float = 0.0
    assignments: dict[str, ObservationCandidate] = field(default_factory=dict)


class JointBinder:
    def __init__(self, *, beam_width: int = 64):
        if beam_width < 2:
            raise ValueError("beam_width must be at least 2 to expose an assignment margin")
        self.beam_width = beam_width

    def bind(
        self,
        plan: ExecutionPlan,
        batches: dict[str, CandidateBatch],
    ) -> BindingResult:
        missing_batches = [request.request_id for request in plan.requests if request.request_id not in batches]
        if missing_batches:
            return _abstain(f"MISSING_CANDIDATE_BATCH:{','.join(sorted(missing_batches))}")
        empty = [request.request_id for request in plan.requests if not batches[request.request_id].candidates]
        if empty:
            return _abstain(f"NO_CANDIDATES:{','.join(sorted(empty))}")

        ordered = sorted(
            plan.requests,
            key=lambda request: (len(batches[request.request_id].candidates), request.request_id),
        )
        states = [_State()]
        expanded = 0
        rejected = 0
        for request in ordered:
            next_states: list[_State] = []
            for state in states:
                for candidate in batches[request.request_id].candidates:
                    expanded += 1
                    if not _compatible_request(request.expected_unit.dimension, candidate.unit.dimension):
                        rejected += 1
                        continue
                    assignments = {**state.assignments, request.request_id: candidate}
                    if not _constraints_hold(plan, assignments):
                        rejected += 1
                        continue
                    next_states.append(_State(state.score + candidate.score, assignments))
            if not next_states:
                return _abstain(
                    "NO_COHERENT_ASSIGNMENT",
                    trace=({"expanded": expanded, "rejected": rejected},),
                )
            next_states.sort(key=_state_sort_key)
            states = next_states[: self.beam_width]

        states.sort(key=_state_sort_key)
        winner = states[0]
        margin = winner.score - states[1].score if len(states) > 1 else None
        tied = [state for state in states[1:] if state.score == winner.score]
        if any(not _semantically_equivalent(winner, contender) for contender in tied):
            return _abstain(
                "AMBIGUOUS_BINDING",
                trace=(
                    {
                        "expanded": expanded,
                        "rejected": rejected,
                        "tied_assignments": len(tied) + 1,
                        "total_score": winner.score,
                        "score_margin": 0.0,
                    },
                ),
            )
        requests = plan.requests_by_id
        bound = {
            request_id: BoundOperand(requests[request_id], candidate)
            for request_id, candidate in winner.assignments.items()
        }
        return BindingResult(
            "OK",
            BoundExecutionPlan(plan, MappingProxyType(bound), winner.score, margin),
            trace=(
                {
                    "expanded": expanded,
                    "rejected": rejected,
                    "surviving_assignments": len(states),
                    "total_score": winner.score,
                    "score_margin": margin,
                },
            ),
        )


def _constraints_hold(
    plan: ExecutionPlan, assignments: dict[str, ObservationCandidate]
) -> bool:
    for constraint in plan.constraints:
        selected = [assignments[value] for value in constraint.request_ids if value in assignments]
        if len(selected) < 2:
            continue
        if constraint.kind == ConstraintKind.SAME_DOCUMENT:
            if len({candidate.document_id for candidate in selected}) != 1:
                return False
        elif constraint.kind == ConstraintKind.SAME_PERIOD:
            periods = {candidate.period for candidate in selected}
            if None in periods or len(periods) != 1:
                return False
        elif constraint.kind == ConstraintKind.SAME_BASIS:
            if len({candidate.basis for candidate in selected}) != 1:
                return False
        elif constraint.kind == ConstraintKind.SAME_CURRENCY:
            currencies = {candidate.unit.currency or "__unknown__" for candidate in selected}
            if len(currencies) != 1:
                return False
        elif constraint.kind == ConstraintKind.SAME_DIMENSION:
            if len({candidate.unit.dimension for candidate in selected}) != 1:
                return False
        elif constraint.kind == ConstraintKind.DISTINCT_OBSERVATIONS and len(
            {candidate.observation_uid for candidate in selected}
        ) != len(selected):
            return False
    return True


def _compatible_request(expected: Dimension, actual: Dimension) -> bool:
    if expected == Dimension.UNKNOWN:
        return actual != Dimension.UNKNOWN
    if expected == actual:
        return True
    return {expected, actual} == {Dimension.PERCENT, Dimension.RATIO}


def _state_sort_key(state: _State) -> tuple[float, tuple[tuple[str, str], ...]]:
    stable = tuple(sorted((key, value.observation_uid) for key, value in state.assignments.items()))
    return -state.score, stable


def _semantically_equivalent(left: _State, right: _State) -> bool:
    if set(left.assignments) != set(right.assignments):
        return False
    for request_id, left_candidate in left.assignments.items():
        right_candidate = right.assignments[request_id]
        if (
            left_candidate.value != right_candidate.value
            or left_candidate.unit != right_candidate.unit
            or left_candidate.basis != right_candidate.basis
            or left_candidate.entity != right_candidate.entity
            or left_candidate.period != right_candidate.period
            or left_candidate.is_restated != right_candidate.is_restated
        ):
            return False
    return True


def _abstain(reason: str, *, trace: tuple[dict[str, object], ...] = ()) -> BindingResult:
    return BindingResult("ABSTAIN", reason=reason, trace=trace)
