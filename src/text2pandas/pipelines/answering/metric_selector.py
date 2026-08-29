"""Metric-aware selector for the guarded Canonical V2 P0 path."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from text2pandas.application.selection import SelectorSpec
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics

from .binding import CandidateCell, Selector
from .ir import OperandSlot
from .units import PERCENT, RATIO, UNKNOWN

_AGGREGATE_PREFIXES = ("tong cong ", "tong ", "cong ")


@dataclass(frozen=True, slots=True)
class CandidateSelectionTrace:
    accepted: bool
    reasons: tuple[str, ...]
    semantic_score: tuple[float, ...] = ()


class MetricAwareSelector(Selector):
    """Hard-gate semantics before applying any retrieval/table prior."""

    def __init__(
        self,
        specs_by_role: Mapping[str, SelectorSpec],
        *,
        ambiguity_margin: float = 0.05,
    ):
        if not specs_by_role:
            raise ValueError("MetricAwareSelector requires at least one SelectorSpec")
        if not 0.0 <= ambiguity_margin <= 1.0:
            raise ValueError("ambiguity_margin must be between 0 and 1")
        self.specs_by_role = dict(specs_by_role)
        self.ambiguity_margin = ambiguity_margin

    def spec_for(self, slot: OperandSlot) -> SelectorSpec | None:
        return self.specs_by_role.get(slot.role) or self.specs_by_role.get("*")

    def inspect(self, slot: OperandSlot, cell: CandidateCell) -> CandidateSelectionTrace:
        spec = self.spec_for(slot)
        if spec is None:
            return CandidateSelectionTrace(False, ("SELECTOR_SPEC_MISSING",))
        reasons: list[str] = []
        entity = slot.entity or spec.entity
        if entity and cell.entity != entity:
            reasons.append("ENTITY_MISMATCH")
        period = slot.period or spec.period
        if period and (not cell.period or cell.period[:4] != period[:4]):
            reasons.append("PERIOD_MISMATCH")
        expected_dimension = spec.expected_dimension.value.upper()
        if not _dimension_compatible(expected_dimension, cell.unit.dimension):
            reasons.append("DIMENSION_MISMATCH")
        leaf = _normalize(cell.row_path.rsplit("›", 1)[-1])
        context = _normalize(f"{cell.row_path} {cell.section_text} {cell.table_context}")
        if any(leaf.startswith(value) for value in spec.forbidden_prefixes):
            reasons.append("FORBIDDEN_PREFIX")
        if any(value in leaf for value in spec.forbidden_contains):
            reasons.append("FORBIDDEN_CONTAINS")
        if not cell.statement_type or cell.statement_type not in spec.allowed_statement_types:
            reasons.append("STATEMENT_TYPE_MISMATCH")
        requested_basis = (
            None if spec.requested_basis == Basis.UNSPECIFIED else spec.requested_basis.value
        )
        basis = slot.basis or requested_basis
        if basis and cell.basis != basis:
            reasons.append("BASIS_MISMATCH")
        if not _period_semantics_compatible(spec, cell):
            reasons.append("PERIOD_SEMANTICS_MISMATCH")
        if spec.required_context_any and not any(
            value in context for value in spec.required_context_any
        ):
            reasons.append("REQUIRED_CONTEXT_MISSING")
        metric_match = _metric_match(spec, leaf)
        code_match = bool(
            spec.metric_codes
            and cell.metric_code
            and cell.metric_code in spec.metric_codes
        )
        if metric_match == 0 and not code_match:
            reasons.append("METRIC_EVIDENCE_MISSING")
        if reasons:
            return CandidateSelectionTrace(False, tuple(reasons))
        required_context_score = 1.0 if spec.required_context_any else 0.0
        statement_score = 1.0
        period_role_score = _period_role_score(spec, cell)
        basis_score = 1.0 if cell.basis == spec.preferred_basis.value else 0.0
        section_score = _section_score(spec, cell)
        score = (
            float(metric_match),
            1.0 if code_match else 0.0,
            1.0,
            required_context_score,
            statement_score,
            period_role_score,
            basis_score,
            section_score,
            -float(cell.table_rank),
            1.0 if not cell.is_restated else 0.0,
            -float(cell.row_path.count("›")),
        )
        return CandidateSelectionTrace(True, (), score)

    def score(self, slot: OperandSlot, cell: CandidateCell) -> tuple:
        inspected = self.inspect(slot, cell)
        return inspected.semantic_score if inspected.accepted else ()

    def rank(self, slot: OperandSlot, pool: Sequence[CandidateCell]) -> list[CandidateCell]:
        accepted = self._accepted(slot, pool)
        accepted.sort(key=lambda value: value[1])
        accepted.sort(key=lambda value: value[0], reverse=True)
        if len(accepted) >= 2 and _ambiguous_top(
            accepted[0], accepted[1], self.ambiguity_margin
        ):
            return []
        return [value[2] for value in accepted]

    def failure_reason(
        self, slot: OperandSlot, pool: Sequence[CandidateCell]
    ) -> str | None:
        accepted = self._accepted(slot, pool)
        accepted.sort(key=lambda value: value[1])
        accepted.sort(key=lambda value: value[0], reverse=True)
        if len(accepted) >= 2 and _ambiguous_top(
            accepted[0], accepted[1], self.ambiguity_margin
        ):
            return "AMBIGUOUS_BINDING"
        return "METRIC_CANDIDATE_EMPTY" if not accepted else None

    def _accepted(
        self, slot: OperandSlot, pool: Sequence[CandidateCell]
    ) -> list[tuple[tuple[float, ...], str, CandidateCell]]:
        accepted: list[tuple[tuple[float, ...], str, CandidateCell]] = []
        for cell in pool:
            inspected = self.inspect(slot, cell)
            if inspected.accepted:
                accepted.append((inspected.semantic_score, _stable_uid(cell), cell))
        return accepted


def _metric_match(spec: SelectorSpec, leaf: str) -> int:
    direct = [alias for alias in spec.aliases if leaf == alias or leaf.startswith(f"{alias} ")]
    if direct:
        return 3 if leaf in direct else 2
    stripped = leaf
    for prefix in _AGGREGATE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    if stripped == leaf:
        return 0
    return 1 if any(
        stripped == alias or stripped.startswith(f"{alias} ") for alias in spec.aliases
    ) else 0


def _period_semantics_compatible(spec: SelectorSpec, cell: CandidateCell) -> bool:
    role = (cell.period_role or "").casefold()
    column = _normalize(cell.col_label)
    requested = (spec.requested_period_role or "").casefold()
    if requested in {"opening", "closing", "current", "prior"}:
        if role and role != requested:
            return False
    if spec.period_semantics == PeriodSemantics.POINT_IN_TIME:
        if role in {"opening", "closing", "prior"}:
            return True
        if role == "current" and cell.statement_type != "balance_sheet":
            return False
        return cell.statement_type == "balance_sheet" or any(
            cue in column for cue in ("dau nam", "cuoi nam", "31 12", "tai ngay")
        )
    if spec.period_semantics == PeriodSemantics.FLOW:
        if role in {"opening", "closing"}:
            return False
        return cell.statement_type in {"income_statement", "cash_flow", "note"}
    return False


def _period_role_score(spec: SelectorSpec, cell: CandidateCell) -> float:
    role = (cell.period_role or "").casefold()
    requested = (spec.requested_period_role or "").casefold()
    if requested and role == requested:
        return 3.0
    if spec.period_semantics == PeriodSemantics.POINT_IN_TIME:
        return 2.0 if role == "closing" else 1.0
    return 2.0 if role == "current" else 1.0


def _section_score(spec: SelectorSpec, cell: CandidateCell) -> float:
    tokens = set(_normalize(cell.section_text).split())
    if not tokens:
        return 0.0
    return max(
        (
            len(tokens.intersection(alias.split())) / max(1, len(alias.split()))
            for alias in spec.aliases
        ),
        default=0.0,
    )


def _dimension_compatible(expected: str, actual: str) -> bool:
    if expected == Dimension.UNKNOWN.value.upper() or actual == UNKNOWN:
        return False
    if expected == actual:
        return True
    return {expected, actual} == {PERCENT, RATIO}


def _ambiguous_top(
    first: tuple[tuple[float, ...], str, CandidateCell],
    second: tuple[tuple[float, ...], str, CandidateCell],
    ambiguity_margin: float,
) -> bool:
    # Table prior, restatement and row depth cannot break a tie in metric,
    # period and basis semantics when the physical observations disagree.
    if first[0][:7] != second[0][:7]:
        return False
    if abs(first[0][7] - second[0][7]) >= ambiguity_margin:
        return False
    left, right = first[2], second[2]
    return (
        left.value,
        left.period,
        left.basis,
        left.period_role,
    ) != (
        right.value,
        right.period,
        right.basis,
        right.period_role,
    )


def _stable_uid(cell: CandidateCell) -> str:
    return "|".join(
        (
            cell.table_uid or "",
            cell.csv_path,
            str(cell.row_index),
            cell.col_label,
        )
    )


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", (value or "").casefold())
    plain = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()
