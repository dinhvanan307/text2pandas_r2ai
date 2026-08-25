"""Semantic contract v2 — per-operand specification.

STATUS: schema frozen, **not yet wired** into the live router. It exists so the
candidate generator can be written against a stable contract, and so gold
annotation has something concrete to annotate against. Wiring happens only
after the local semantic gold exists (review 173 §7, constraint 1).

Why the old contract was insufficient
-------------------------------------
``OperandSlot`` carried one ``metric_id`` copied identically into every slot,
so the router emitted:

    numerator.metric_id   = bad_debt
    denominator.metric_id = bad_debt      # <- wrong, silently

"nợ xấu / tổng dư nợ" needs two different metrics. The same applies to every
axis: a cross-company sum varies the ENTITY per slot, a year-over-year change
varies the PERIOD, a separate-vs-consolidated comparison varies the BASIS.
A scalar field on the frame cannot express any of them.

The fix is to make each operand carry its own selectors, and to say explicitly
which axis the operation varies over.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .units import Unit

# ------------------------------------------------------------------- axes
AXIS_PERIOD = "PERIOD"
AXIS_ENTITY = "ENTITY"
AXIS_METRIC = "METRIC"
AXIS_CATEGORY = "CATEGORY"
AXIS_NONE = "NONE"

AGGREGATION_AXES = (AXIS_PERIOD, AXIS_ENTITY, AXIS_METRIC, AXIS_CATEGORY, AXIS_NONE)

# --------------------------------------------------------------- comparators
OP_GT, OP_GE, OP_LT, OP_LE, OP_EQ, OP_NE = ">", ">=", "<", "<=", "==", "!="
COMPARATORS = (OP_GT, OP_GE, OP_LT, OP_LE, OP_EQ, OP_NE)


@dataclass(frozen=True)
class FilterSpec:
    """A qualifying predicate: "các năm có biên lợi nhuận ròng trên 10%".

    Measured on ``metric_id`` of the same entity/period as the operand it
    qualifies, unless overridden.
    """

    metric_id: str
    comparator: str
    threshold: float
    unit: Optional[Unit] = None
    #: e.g. "median-of-group" comparisons need the group, not a constant
    threshold_is_group_statistic: Optional[str] = None

    def __post_init__(self):
        if self.comparator not in COMPARATORS:
            raise ValueError(f"unknown comparator {self.comparator!r}")


@dataclass(frozen=True)
class EntitySelector:
    """Which company. ``ticker`` is preferred; ``name`` keeps the surface form
    so an ontology can resolve tickerless mentions later."""

    ticker: Optional[str] = None
    name: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.ticker is not None


@dataclass(frozen=True)
class PeriodSelector:
    """Which period, and which point of it.

    ``point`` distinguishes a flow over the year from a balance at an instant --
    "số đầu năm" is an opening balance, not an annual flow, and conflating them
    is a known unresolved risk (review 173 §5.6).
    """

    year: Optional[str] = None
    point: str = "PERIOD"          # PERIOD | OPENING | CLOSING
    quarter: Optional[int] = None


@dataclass(frozen=True)
class OperandSpec:
    """Everything needed to FIND one operand, independent of every other."""

    role: str
    metric_id: Optional[str] = None
    metric_expression: Optional[str] = None      # for derived ranking keys
    entity: Optional[EntitySelector] = None
    period: Optional[PeriodSelector] = None
    basis: Optional[str] = None                  # separate | consolidated
    quantity_dimension: Optional[str] = None
    aggregation_axis: str = AXIS_NONE
    filters: tuple[FilterSpec, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def is_specified(self) -> bool:
        """Enough information to query for a candidate at all."""
        return bool(self.metric_id or self.metric_expression)


@dataclass(frozen=True)
class RankSpec:
    """For EXTREMUM: what is ranked, over which axis, and which end."""

    key_metric_id: Optional[str] = None
    key_expression: Optional[str] = None
    axis: str = AXIS_PERIOD
    direction: str = "MAX"                       # MAX | MIN
    filters: tuple[FilterSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ReturnSpec:
    """What the answer IS -- separate from how it is scaled.

    ``result_kind`` uses the vocabulary in :mod:`result_kind`. ``select_metric``
    is what makes SELECT_AT_ARG expressible: rank by one metric, then return a
    DIFFERENT one at the winning position.
    """

    result_kind: str
    unit: Optional[Unit] = None
    select_metric_id: Optional[str] = None
    select_axis_value_only: bool = False          # True for ARG_* (return the label)


@dataclass(frozen=True)
class QuestionSemanticFrameV2:
    """Typed reading of a question, with per-operand specifications."""

    qid: Optional[int]
    question: str
    entity_set: tuple[EntitySelector, ...] = field(default_factory=tuple)
    basis: Optional[str] = None
    requested_periods: tuple[PeriodSelector, ...] = field(default_factory=tuple)
    operation_family: Optional[str] = None
    requested_result_kind: Optional[str] = None
    requested_unit: Optional[Unit] = None
    operand_specs: tuple[OperandSpec, ...] = field(default_factory=tuple)
    rank: Optional[RankSpec] = None
    returns: Optional[ReturnSpec] = None
    missing: tuple[str, ...] = field(default_factory=tuple)

    def spec(self, role: str) -> Optional[OperandSpec]:
        for s in self.operand_specs:
            if s.role == role:
                return s
        return None

    @property
    def varies_axis(self) -> Optional[str]:
        """The axis the operation actually varies over, if exactly one does.

        This is what a candidate generator needs: for a two-period difference it
        must vary PERIOD and hold metric/entity/basis fixed; for a two-metric
        ratio it must vary METRIC and hold the rest fixed.
        """
        axes = {s.aggregation_axis for s in self.operand_specs} - {AXIS_NONE}
        return axes.pop() if len(axes) == 1 else None

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "entity_set": [asdict(e) for e in self.entity_set],
            "basis": self.basis,
            "requested_periods": [asdict(p) for p in self.requested_periods],
            "operation_family": self.operation_family,
            "requested_result_kind": self.requested_result_kind,
            "operand_specs": [s.to_dict() for s in self.operand_specs],
            "rank": asdict(self.rank) if self.rank else None,
            "returns": asdict(self.returns) if self.returns else None,
            "missing": list(self.missing),
            "varies_axis": self.varies_axis,
        }


@dataclass(frozen=True)
class CandidateObservation:
    """What a candidate generator must return per slot.

    ``observation_uid`` is the dedup key: two rows describing the same physical
    fact must collapse, otherwise a DIVIDE can bind "the same number twice" and
    return a plausible 1.0.
    """

    observation_uid: str
    metric_id: Optional[str]
    entity: Optional[str]
    period: Optional[str]
    basis: Optional[str]
    source_table: str
    source_row: int
    value: Optional[float]
    unit: Optional[Unit]
    storage_exponent: Optional[int]
    provenance: dict = field(default_factory=dict)
    score_components: dict = field(default_factory=dict)

    @staticmethod
    def make_uid(source_table: str, source_row: int, column: str) -> str:
        """Deterministic identity of one physical cell."""
        return f"{source_table}#{source_row}#{column}"
