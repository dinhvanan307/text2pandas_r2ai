"""Grounded program plans selected by an LLM and executed deterministically.

The model is never allowed to provide a numeric answer.  It may only select
immutable A6 observation identifiers and a closed operation.  This module then
validates units/cardinality, computes the result and emits the restricted
Pandas expression used by the competition submission.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from enum import StrEnum
from itertools import pairwise
from typing import Protocol

from text2pandas.domain.semantic import Basis, Dimension


class GroundedOperation(StrEnum):
    LOOKUP = "lookup"
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    DIFFERENCE = "difference"
    GROWTH = "growth"
    RATIO = "ratio"
    COUNT = "count"
    ARGMAX_PERIOD = "argmax_period"
    ARGMIN_PERIOD = "argmin_period"
    SELECT_AT_ARG = "select_at_arg"


class Comparator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NE = "ne"


@dataclass(frozen=True, slots=True)
class GroundedFact:
    observation_uid: str
    table_uid: str
    document_id: str
    entity: str
    period: str | None
    basis: Basis
    row_path: str
    column_path: str
    section_text: str
    value: Decimal
    dimension: Dimension
    scale_exponent: int | None
    metric_code: str | None = None
    statement_type: str | None = None
    retrieval_metric: str | None = None
    score: float = 0.0
    document_year: int | None = None
    period_role: str | None = None
    is_restated: bool = False
    currency: str | None = None
    grid_row: int | None = None
    grid_column: int | None = None
    row_uid: str | None = None
    column_uid: str | None = None
    collision_class: str | None = None
    source_confidence: float | None = None
    resolution_margin: float | None = None
    corroboration_count: int = 1
    score_reasons: tuple[str, ...] = ()

    @property
    def period_year(self) -> int | None:
        if self.period is None or len(self.period) < 4:
            return None
        try:
            return int(self.period[:4])
        except ValueError:
            return None

    def canonical_value(self) -> Decimal:
        if self.dimension is Dimension.MONEY:
            if self.scale_exponent is None:
                raise GroundedPlanError(
                    f"scale is unknown for {self.dimension.value} fact {self.observation_uid}"
                )
            return self.value * (Decimal(10) ** self.scale_exponent)
        if self.dimension is Dimension.SHARES:
            # A6 stores an absolute share count as ``shares`` with no monetary
            # scale metadata.  Missing means units (10^0), while an explicit
            # exponent still supports disclosures in thousand/million shares.
            return self.value * (Decimal(10) ** (self.scale_exponent or 0))
        return self.value

    def to_prompt_dict(self) -> dict[str, object]:
        try:
            canonical: str | None = str(self.canonical_value())
        except GroundedPlanError:
            canonical = None
        return {
            "uid": self.observation_uid,
            "table_uid": self.table_uid,
            "document_id": self.document_id,
            "entity": self.entity,
            "period": self.period,
            "basis": self.basis.value,
            "row": self.row_path,
            "column": self.column_path,
            "section": self.section_text,
            "raw_value": str(self.value),
            "canonical_value": canonical,
            "dimension": self.dimension.value,
            "scale_exponent": self.scale_exponent,
            "metric_code": self.metric_code,
            "statement_type": self.statement_type,
            "retrieval_metric": self.retrieval_metric,
            "document_year": self.document_year,
            "period_role": self.period_role,
            "is_restated": self.is_restated,
            "currency": self.currency,
            "collision_class": self.collision_class,
            "source_confidence": self.source_confidence,
            "resolution_margin": self.resolution_margin,
            "corroboration_count": self.corroboration_count,
            "score_reasons": list(self.score_reasons),
        }

    def to_planner_dict(self) -> dict[str, object]:
        """Compact metadata-only view; numeric values stay outside the model."""

        return {
            "uid": self.observation_uid,
            "entity": self.entity,
            "period": self.period,
            "basis": self.basis.value,
            "row": self.row_path[-240:],
            "column": self.column_path[-140:],
            "section": self.section_text[:120],
            "dimension": self.dimension.value,
            "scale_exponent": self.scale_exponent,
            "metric_code": self.metric_code,
            "statement_type": self.statement_type,
            "retrieval_metric": self.retrieval_metric,
            "document_year": self.document_year,
            "period_role": self.period_role,
            "is_restated": self.is_restated,
            "currency": self.currency,
            "collision_class": self.collision_class,
            "source_confidence": self.source_confidence,
            "resolution_margin": self.resolution_margin,
            "corroboration_count": self.corroboration_count,
        }


@dataclass(frozen=True, slots=True)
class GroundedPlan:
    operation: GroundedOperation
    operand_uids: tuple[str, ...]
    output_dimension: Dimension
    output_scale_exponent: int | None = None
    absolute_difference: bool = False
    comparator: Comparator | None = None
    threshold: Decimal | None = None
    selector_uids: tuple[str, ...] = ()
    value_uids: tuple[str, ...] = ()
    join_axis: str | None = None
    direction: str | None = None
    confidence: float | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> GroundedPlan:
        try:
            operation = GroundedOperation(str(raw["operation"]))
            output_dimension = Dimension(str(raw["output_dimension"]))
        except (KeyError, ValueError) as error:
            raise GroundedPlanError(f"invalid operation/output dimension: {error}") from error
        operand_uids = _string_tuple(raw.get("operand_uids"), "operand_uids")
        selector_uids = _string_tuple(raw.get("selector_uids"), "selector_uids")
        value_uids = _string_tuple(raw.get("value_uids"), "value_uids")
        comparator_raw = raw.get("comparator")
        try:
            comparator = None if comparator_raw in (None, "") else Comparator(str(comparator_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid comparator: {comparator_raw!r}") from error
        threshold_raw = raw.get("threshold")
        try:
            threshold = None if threshold_raw in (None, "") else Decimal(str(threshold_raw))
        except InvalidOperation as error:
            raise GroundedPlanError(f"invalid threshold: {threshold_raw!r}") from error
        scale_raw = raw.get("output_scale_exponent")
        try:
            scale = None if scale_raw in (None, "") else int(str(scale_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid output scale: {scale_raw!r}") from error
        if scale is not None and scale not in {0, 3, 6, 9, 11, 12}:
            raise GroundedPlanError(f"output scale must be one of 0/3/6/9/11/12, received {scale}")
        confidence_raw = raw.get("confidence")
        try:
            confidence = None if confidence_raw in (None, "") else float(str(confidence_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid confidence: {confidence_raw!r}") from error
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise GroundedPlanError("confidence must be finite and in [0, 1]")
        return cls(
            operation=operation,
            operand_uids=operand_uids,
            output_dimension=output_dimension,
            output_scale_exponent=scale,
            absolute_difference=bool(raw.get("absolute_difference", False)),
            comparator=comparator,
            threshold=threshold,
            selector_uids=selector_uids,
            value_uids=value_uids,
            join_axis=_optional_string(raw.get("join_axis")),
            direction=_optional_string(raw.get("direction")),
            confidence=confidence,
        )


class GroundedPlanGenerator(Protocol):
    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedPlan | GroundedProgram: ...


@dataclass(frozen=True, slots=True)
class GroundedExecution:
    answer: float
    pandas_query: str
    facts: tuple[GroundedFact, ...]
    plan: GroundedPlan


class GroundedPlanError(ValueError):
    """The generated plan is ungrounded, ambiguous or dimensionally invalid."""


class ProgramOperation(StrEnum):
    FACTS = "facts"
    LITERAL = "literal"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    GROWTH = "growth"
    GROWTH_BY_ENTITY = "growth_by_entity"
    ROLLING_GROWTH = "rolling_growth"
    ROLLING_GROWTH_BY_ENTITY = "rolling_growth_by_entity"
    ROLLING_AVERAGE = "rolling_average"
    CHANGE_BY_ENTITY = "change_by_entity"
    EARLIEST_BY_ENTITY = "earliest_by_entity"
    LATEST_BY_ENTITY = "latest_by_entity"
    ROLLING_AVERAGE_BY_ENTITY = "rolling_average_by_entity"
    ROLLING_CHANGE_BY_ENTITY = "rolling_change_by_entity"
    ALL_BY_ENTITY = "all_by_entity"
    ANY_BY_ENTITY = "any_by_entity"
    AVERAGE_BY_ENTITY = "average_by_entity"
    SUM_BY_ENTITY = "sum_by_entity"
    SUM_BY_SCOPE = "sum_by_scope"
    CAGR_BY_ENTITY = "cagr_by_entity"
    DROP_FIRST_BY_ENTITY = "drop_first_by_entity"
    ROLLING_CHANGE = "rolling_change"
    TOP_K_MASK = "top_k_mask"
    BOTTOM_K_MASK = "bottom_k_mask"
    SHIFT_KEY = "shift_key"
    KEY_TO_NUMBER = "key_to_number"
    FIRST_TRUE_KEY = "first_true_key"
    LAST_TRUE_KEY = "last_true_key"
    TO_PERCENT = "to_percent"
    ABSOLUTE = "absolute"
    SUM = "sum"
    AVERAGE = "average"
    MEDIAN = "median"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    COMPARE = "compare"
    IS_NONZERO = "is_nonzero"
    IS_ZERO = "is_zero"
    LOGICAL_AND = "logical_and"
    LOGICAL_OR = "logical_or"
    FILTER = "filter"
    ARGMAX_KEY = "argmax_key"
    ARGMIN_KEY = "argmin_key"
    SELECT_AT_KEY = "select_at_key"
    COUNT_TRUE = "count_true"


@dataclass(frozen=True, slots=True)
class ProgramNode:
    node_id: str
    operation: ProgramOperation
    input_ids: tuple[str, ...] = ()
    fact_uids: tuple[str, ...] = ()
    axis: str | None = None
    literal: Decimal | None = None
    comparator: Comparator | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> ProgramNode:
        node_id = _optional_string(raw.get("id"))
        if node_id is None or not node_id.replace("_", "").isalnum():
            raise GroundedPlanError(f"invalid program node id: {node_id!r}")
        try:
            operation = ProgramOperation(str(raw["operation"]))
        except (KeyError, ValueError) as error:
            raise GroundedPlanError(f"invalid program operation: {error}") from error
        literal_raw = raw.get("literal")
        try:
            literal = None if literal_raw is None else Decimal(str(literal_raw))
        except InvalidOperation as error:
            raise GroundedPlanError(f"invalid program literal: {literal_raw!r}") from error
        if literal is not None and not literal.is_finite():
            raise GroundedPlanError("program literal must be finite")
        comparator_raw = raw.get("comparator")
        try:
            comparator = None if comparator_raw in (None, "") else Comparator(str(comparator_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid program comparator: {comparator_raw!r}") from error
        input_ids = _string_tuple(raw.get("input_ids"), "input_ids")
        fact_uids = _string_tuple(raw.get("fact_uids"), "fact_uids")
        # Small structured models sometimes copy fact_uids into input_ids even
        # though a source node has no graph dependencies.  Treat that as a
        # syntax-level repair; the executor still validates every fact UID
        # against the retrieved candidate boundary.
        if operation in {ProgramOperation.FACTS, ProgramOperation.LITERAL}:
            input_ids = ()
        return cls(
            node_id=node_id,
            operation=operation,
            input_ids=input_ids,
            fact_uids=fact_uids,
            axis=_optional_string(raw.get("axis")),
            literal=literal,
            comparator=comparator,
        )


@dataclass(frozen=True, slots=True)
class GroundedProgram:
    nodes: tuple[ProgramNode, ...]
    output_node_id: str
    output_dimension: Dimension
    output_scale_exponent: int | None = None
    confidence: float | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> GroundedProgram:
        nodes_raw = raw.get("nodes")
        if not isinstance(nodes_raw, Sequence) or isinstance(nodes_raw, (str, bytes)):
            raise GroundedPlanError("program nodes must be a list")
        nodes = tuple(
            ProgramNode.from_mapping(item) for item in nodes_raw if isinstance(item, Mapping)
        )
        if len(nodes) != len(nodes_raw) or not nodes:
            raise GroundedPlanError("every program node must be an object")
        node_ids = [node.node_id for node in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise GroundedPlanError("program node ids must be unique")
        known_ids = set(node_ids)
        generated_literals: list[ProgramNode] = []

        def repair_input_id(value: str) -> str:
            if value in known_ids:
                return value
            literal_match = re.fullmatch(r"literal\(([-+]?\d+(?:\.\d+)?)\)", value)
            if literal_match is not None:
                literal = Decimal(literal_match.group(1))
                candidate_id = f"literal_auto_{len(generated_literals)}"
                while candidate_id in known_ids:
                    candidate_id += "_"
                generated_literals.append(
                    ProgramNode(
                        node_id=candidate_id,
                        operation=ProgramOperation.LITERAL,
                        literal=literal,
                    )
                )
                known_ids.add(candidate_id)
                return candidate_id
            ranked = sorted(
                (
                    (SequenceMatcher(None, value, candidate).ratio(), candidate)
                    for candidate in known_ids
                ),
                reverse=True,
            )
            if (
                ranked
                and ranked[0][0] >= 0.94
                and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.03)
            ):
                return ranked[0][1]
            return value

        nodes = tuple(
            replace(node, input_ids=tuple(repair_input_id(value) for value in node.input_ids))
            for node in nodes
        )
        nodes = (*nodes, *generated_literals)
        repaired_literals: list[ProgramNode] = []
        for node in nodes:
            missing_inputs = [value for value in node.input_ids if value not in known_ids]
            if len(missing_inputs) == 1 and node.literal is not None:
                repaired_literals.append(
                    ProgramNode(
                        node_id=missing_inputs[0],
                        operation=ProgramOperation.LITERAL,
                        literal=node.literal,
                    )
                )
                known_ids.add(missing_inputs[0])
        nodes = (*nodes, *repaired_literals)
        node_ids = [node.node_id for node in nodes]
        output_node_id = _optional_string(raw.get("output_node_id"))
        if output_node_id not in set(node_ids):
            raise GroundedPlanError("program output_node_id is missing from nodes")
        try:
            output_dimension = Dimension(str(raw["output_dimension"]))
        except (KeyError, ValueError) as error:
            raise GroundedPlanError(f"invalid program output dimension: {error}") from error
        scale_raw = raw.get("output_scale_exponent")
        try:
            scale = None if scale_raw is None else int(str(scale_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid program output scale: {scale_raw!r}") from error
        if output_dimension not in {Dimension.MONEY, Dimension.SHARES}:
            scale = None
        if scale is not None and scale not in {0, 3, 6, 9, 11, 12}:
            raise GroundedPlanError("program output scale must be one of 0/3/6/9/11/12")
        confidence_raw = raw.get("confidence")
        try:
            confidence = None if confidence_raw is None else float(str(confidence_raw))
        except ValueError as error:
            raise GroundedPlanError(f"invalid program confidence: {confidence_raw!r}") from error
        if confidence is not None and (not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise GroundedPlanError("program confidence must be finite and in [0, 1]")
        return cls(nodes, output_node_id or "", output_dimension, scale, confidence)


@dataclass(frozen=True, slots=True)
class _Scalar:
    value: Decimal
    expression: str
    dimension: Dimension
    fact_uids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Boolean:
    value: bool
    expression: str
    fact_uids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Series:
    values: tuple[tuple[str, _Scalar | _Boolean], ...]

    def mapping(self) -> dict[str, _Scalar | _Boolean]:
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class _Key:
    value: str
    grounding_expression: str
    fact_uids: tuple[str, ...] = ()


_ProgramValue = _Scalar | _Boolean | _Series | _Key


def _merge_fact_uids(
    *values: _Scalar | _Boolean | _Key | tuple[str, ...],
) -> tuple[str, ...]:
    merged: list[str] = []
    for value in values:
        uids = value if isinstance(value, tuple) else value.fact_uids
        merged.extend(uids)
    return tuple(dict.fromkeys(merged))


def execute_grounded_program(
    program: GroundedProgram,
    candidates: Sequence[GroundedFact],
    *,
    dataframe_variable: str = "df1",
) -> GroundedExecution:
    """Type-check and execute a compositional grounded DAG."""

    facts_by_uid = {fact.observation_uid: fact for fact in candidates}
    nodes_by_id = {node.node_id: node for node in program.nodes}
    values: dict[str, _ProgramValue] = {}
    used_uids: list[str] = []
    visiting: set[str] = set()

    def evaluate(node_id: str) -> _ProgramValue:
        if node_id in values:
            return values[node_id]
        if node_id in visiting:
            raise GroundedPlanError(f"program contains a cycle at {node_id}")
        node = nodes_by_id.get(node_id)
        if node is None:
            raise GroundedPlanError(f"program references unknown node: {node_id}")
        visiting.add(node_id)
        inputs = tuple(evaluate(value) for value in node.input_ids)
        value = _execute_program_node(
            node,
            inputs,
            facts_by_uid,
            used_uids,
            dataframe_variable,
        )
        visiting.remove(node_id)
        values[node_id] = value
        return value

    output = evaluate(program.output_node_id)
    if not isinstance(output, _Scalar):
        raise GroundedPlanError("program output must resolve to a numeric scalar")
    adapter = GroundedPlan(
        operation=GroundedOperation.LOOKUP,
        operand_uids=(used_uids[0],) if used_uids else (),
        output_dimension=program.output_dimension,
        output_scale_exponent=program.output_scale_exponent,
        confidence=program.confidence,
    )
    converted, expression = _convert_output(
        output.value,
        output.expression,
        output.dimension,
        adapter,
    )
    answer = float(converted)
    if not math.isfinite(answer):
        raise GroundedPlanError("program result is not finite")
    selected = tuple(facts_by_uid[uid] for uid in output.fact_uids)
    if not selected:
        raise GroundedPlanError("program is not grounded in any A6 observation")
    return GroundedExecution(answer, f"float({expression})", selected, adapter)


def execute_grounded(
    plan: GroundedPlan | GroundedProgram,
    candidates: Sequence[GroundedFact],
    *,
    dataframe_variable: str = "df1",
) -> GroundedExecution:
    if isinstance(plan, GroundedProgram):
        return execute_grounded_program(plan, candidates, dataframe_variable=dataframe_variable)
    return execute_grounded_plan(plan, candidates, dataframe_variable=dataframe_variable)


def _execute_program_node(
    node: ProgramNode,
    inputs: tuple[_ProgramValue, ...],
    facts_by_uid: Mapping[str, GroundedFact],
    used_uids: list[str],
    variable: str,
) -> _ProgramValue:
    operation = node.operation
    if operation is ProgramOperation.FACTS:
        if (
            inputs
            or not node.fact_uids
            or node.axis
            not in {
                "entity",
                "period",
                "entity_period",
                "entity_period_observation",
            }
        ):
            raise GroundedPlanError(
                f"facts node {node.node_id} requires fact_uids, an axis and no inputs"
            )
        points: list[tuple[str, _Scalar | _Boolean]] = []
        retrieval_metrics: set[str] = set()
        for uid in node.fact_uids:
            fact = facts_by_uid.get(uid)
            if fact is None:
                raise GroundedPlanError(f"program fact is outside candidate context: {uid}")
            used_uids.append(uid)
            if fact.retrieval_metric:
                retrieval_metrics.add(fact.retrieval_metric)
            value, expression, dimension = _fact_value(fact, variable)
            if node.axis == "entity":
                key = fact.entity
            elif node.axis == "period":
                key = str(fact.period_year) if fact.period_year is not None else ""
            elif node.axis == "entity_period":
                year = str(fact.period_year) if fact.period_year is not None else ""
                key = f"{fact.entity}|{year}"
            else:
                year = str(fact.period_year) if fact.period_year is not None else ""
                key = f"{fact.entity}|{year}|{fact.observation_uid}"
            if not key:
                raise GroundedPlanError(f"fact {uid} has no {node.axis} key")
            points.append((key, _Scalar(value, expression, dimension, (uid,))))
        if len(retrieval_metrics) > 1:
            raise GroundedPlanError(
                f"facts node {node.node_id} mixes retrieval metrics: {sorted(retrieval_metrics)}"
            )
        if len({key for key, _value in points}) != len(points):
            raise GroundedPlanError(f"facts node {node.node_id} has duplicate axis keys")
        return _Series(tuple(points))
    if operation is ProgramOperation.LITERAL:
        if inputs or node.literal is None:
            raise GroundedPlanError(f"literal node {node.node_id} requires one literal")
        return _Scalar(node.literal, str(node.literal), Dimension.UNKNOWN)
    if operation in {
        ProgramOperation.ADD,
        ProgramOperation.SUBTRACT,
        ProgramOperation.MULTIPLY,
        ProgramOperation.DIVIDE,
        ProgramOperation.GROWTH,
    }:
        if len(inputs) != 2:
            raise GroundedPlanError(f"{operation.value} node requires two inputs")
        return _program_binary(operation, inputs[0], inputs[1])
    if operation in {
        ProgramOperation.GROWTH_BY_ENTITY,
        ProgramOperation.ROLLING_GROWTH,
        ProgramOperation.ROLLING_GROWTH_BY_ENTITY,
        ProgramOperation.ROLLING_AVERAGE,
        ProgramOperation.ROLLING_CHANGE,
        ProgramOperation.CHANGE_BY_ENTITY,
        ProgramOperation.EARLIEST_BY_ENTITY,
        ProgramOperation.LATEST_BY_ENTITY,
        ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
        ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
        ProgramOperation.AVERAGE_BY_ENTITY,
        ProgramOperation.SUM_BY_ENTITY,
        ProgramOperation.CAGR_BY_ENTITY,
        ProgramOperation.DROP_FIRST_BY_ENTITY,
    }:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError(f"{operation.value} requires one numeric series")
        return _program_temporal_growth(operation, inputs[0])
    if operation is ProgramOperation.SUM_BY_SCOPE:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError("sum_by_scope requires one numeric series")
        if node.axis not in {"entity", "period", "entity_period"}:
            raise GroundedPlanError(
                "sum_by_scope requires entity, period or entity_period target axis"
            )
        return _program_sum_by_scope(inputs[0], node.axis)
    if operation in {ProgramOperation.ALL_BY_ENTITY, ProgramOperation.ANY_BY_ENTITY}:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError(f"{operation.value} requires one boolean series")
        return _program_boolean_by_entity(operation, inputs[0])
    if operation in {ProgramOperation.TOP_K_MASK, ProgramOperation.BOTTOM_K_MASK}:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError(f"{operation.value} requires one numeric series")
        return _program_top_k_mask(operation, inputs[0], node.literal)
    if operation is ProgramOperation.SHIFT_KEY:
        if len(inputs) != 1 or not isinstance(inputs[0], _Key):
            raise GroundedPlanError("shift_key requires one key input")
        return _program_shift_key(inputs[0], node.literal)
    if operation is ProgramOperation.KEY_TO_NUMBER:
        if len(inputs) != 1 or not isinstance(inputs[0], _Key):
            raise GroundedPlanError("key_to_number requires one key input")
        try:
            numeric_key = Decimal(inputs[0].value)
        except InvalidOperation as error:
            raise GroundedPlanError("key_to_number requires a numeric period key") from error
        return _Scalar(
            numeric_key,
            f"({inputs[0].value} + {inputs[0].grounding_expression})",
            Dimension.PERIOD,
            inputs[0].fact_uids,
        )
    if operation in {ProgramOperation.FIRST_TRUE_KEY, ProgramOperation.LAST_TRUE_KEY}:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError(f"{operation.value} requires one boolean series")
        return _program_true_key(operation, inputs[0])
    if operation is ProgramOperation.ABSOLUTE:
        if len(inputs) != 1:
            raise GroundedPlanError("absolute node requires one input")
        return _program_unary_numeric(
            inputs[0],
            lambda item: _Scalar(
                abs(item.value),
                f"abs({item.expression})",
                item.dimension,
                item.fact_uids,
            ),
        )
    if operation is ProgramOperation.TO_PERCENT:
        if len(inputs) != 1:
            raise GroundedPlanError("to_percent requires one input")
        return _program_unary_numeric(
            inputs[0],
            lambda item: _Scalar(
                item.value * Decimal(100),
                f"({item.expression} * 100)",
                Dimension.PERCENT,
                item.fact_uids,
            ),
        )
    if operation in {
        ProgramOperation.SUM,
        ProgramOperation.AVERAGE,
        ProgramOperation.MEDIAN,
        ProgramOperation.MINIMUM,
        ProgramOperation.MAXIMUM,
    }:
        if len(inputs) != 1:
            raise GroundedPlanError(f"{operation.value} node requires one series input")
        return _program_aggregate(operation, inputs[0])
    if operation is ProgramOperation.COMPARE:
        if len(inputs) != 2 or node.comparator is None:
            raise GroundedPlanError("compare node requires two inputs and comparator")
        return _program_compare(node.comparator, inputs[0], inputs[1])
    if operation in {ProgramOperation.IS_NONZERO, ProgramOperation.IS_ZERO}:
        if len(inputs) != 1:
            raise GroundedPlanError(f"{operation.value} requires one numeric input")
        return _program_numeric_presence(operation, inputs[0])
    if operation in {ProgramOperation.LOGICAL_AND, ProgramOperation.LOGICAL_OR}:
        if len(inputs) != 2:
            raise GroundedPlanError(f"{operation.value} node requires two inputs")
        return _program_logical(operation, inputs[0], inputs[1])
    if operation is ProgramOperation.FILTER:
        if (
            len(inputs) != 2
            or not isinstance(inputs[0], _Series)
            or not isinstance(inputs[1], _Series)
        ):
            raise GroundedPlanError("filter node requires value and boolean series")
        predicates = inputs[1].mapping()
        decision_uids = _merge_fact_uids(
            *(item for _key, item in _boolean_series(inputs[1]))
        )
        filtered_points: list[tuple[str, _Scalar | _Boolean]] = []
        for key, point_value in inputs[0].values:
            predicate = predicates.get(key)
            if not isinstance(predicate, _Boolean):
                raise GroundedPlanError(f"filter predicate missing key {key}")
            if predicate.value:
                filtered_points.append(
                    (
                        key,
                        replace(
                            point_value,
                            fact_uids=_merge_fact_uids(point_value, decision_uids),
                        ),
                    )
                )
        if not filtered_points:
            raise GroundedPlanError("filter removes every candidate")
        return _Series(tuple(filtered_points))
    if operation in {ProgramOperation.ARGMAX_KEY, ProgramOperation.ARGMIN_KEY}:
        if len(inputs) != 1 or not isinstance(inputs[0], _Series):
            raise GroundedPlanError(f"{operation.value} node requires one series")
        numeric = _numeric_series(inputs[0])
        if not numeric:
            raise GroundedPlanError(f"{operation.value} cannot rank an empty series")
        chosen = (
            max(numeric, key=lambda item: (item[1].value, item[0]))
            if operation is ProgramOperation.ARGMAX_KEY
            else min(numeric, key=lambda item: (item[1].value, item[0]))
        )
        grounding = " + ".join(f"0 * ({item.expression})" for _key, item in numeric)
        return _Key(
            chosen[0],
            grounding,
            _merge_fact_uids(*(item for _key, item in numeric)),
        )
    if operation is ProgramOperation.SELECT_AT_KEY:
        if (
            len(inputs) != 2
            or not isinstance(inputs[0], _Series)
            or not isinstance(inputs[1], _Key)
        ):
            raise GroundedPlanError("select_at_key requires a series and key")
        chosen_value = inputs[0].mapping().get(inputs[1].value)
        if not isinstance(chosen_value, _Scalar):
            raise GroundedPlanError(f"select_at_key misses key {inputs[1].value}")
        return _Scalar(
            chosen_value.value,
            f"({chosen_value.expression} + {inputs[1].grounding_expression})",
            chosen_value.dimension,
            _merge_fact_uids(chosen_value, inputs[1]),
        )
    if operation is ProgramOperation.COUNT_TRUE:
        if not inputs:
            raise GroundedPlanError("count_true node requires boolean inputs")
        boolean_points: list[tuple[str, _Boolean]] = []
        for index, item in enumerate(inputs):
            if isinstance(item, _Series):
                boolean_points.extend(_boolean_series(item))
            elif isinstance(item, _Boolean):
                boolean_points.append((str(index), item))
            else:
                raise GroundedPlanError("count_true node requires boolean inputs")
        keys = [key for key, _item in boolean_points]
        if len(keys) != len(set(keys)):
            raise GroundedPlanError("count_true inputs contain duplicate keys")
        expression = "(" + " + ".join(f"({item.expression})" for _key, item in boolean_points) + ")"
        return _Scalar(
            Decimal(sum(item.value for _key, item in boolean_points)),
            expression,
            Dimension.COUNT,
            _merge_fact_uids(*(item for _key, item in boolean_points)),
        )
    raise GroundedPlanError(f"unsupported program node operation: {operation.value}")


def _program_binary(
    operation: ProgramOperation,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _ProgramValue:
    if isinstance(left, _Series) or isinstance(right, _Series):
        return _series_binary(operation, left, right)
    if not isinstance(left, _Scalar) or not isinstance(right, _Scalar):
        raise GroundedPlanError(f"{operation.value} inputs must be numeric")
    return _scalar_binary(operation, left, right)


def _program_temporal_growth(operation: ProgramOperation, series: _Series) -> _Series:
    numeric = _numeric_series(series)
    if operation in {
        ProgramOperation.ROLLING_GROWTH,
        ProgramOperation.ROLLING_AVERAGE,
        ProgramOperation.ROLLING_CHANGE,
    }:
        try:
            rolling_ordered = sorted(numeric, key=lambda item: int(item[0]))
        except ValueError as error:
            raise GroundedPlanError(f"{operation.value} requires period-axis keys") from error
        if len(rolling_ordered) < 2:
            raise GroundedPlanError(f"{operation.value} requires at least two periods")
        return _Series(
            tuple(
                (
                    current_key,
                    _scalar_binary(
                        ProgramOperation.GROWTH,
                        previous,
                        current,
                    )
                    if operation is ProgramOperation.ROLLING_GROWTH
                    else _Scalar(
                        (previous.value + current.value) / Decimal(2),
                        f"(({previous.expression} + {current.expression}) / 2)",
                        _compatible_numeric_dimension(
                            previous.dimension,
                            current.dimension,
                            ProgramOperation.ADD,
                        ),
                        _merge_fact_uids(previous, current),
                    )
                    if operation is ProgramOperation.ROLLING_AVERAGE
                    else _scalar_binary(
                        ProgramOperation.SUBTRACT,
                        current,
                        previous,
                    ),
                )
                for (_previous_key, previous), (current_key, current) in pairwise(rolling_ordered)
            )
        )
    grouped: dict[str, list[tuple[int, _Scalar]]] = {}
    for key, value in numeric:
        try:
            entity, year_raw = key.rsplit("|", 1)
            year = int(year_raw)
        except ValueError as error:
            raise GroundedPlanError("growth_by_entity requires entity_period-axis keys") from error
        grouped.setdefault(entity, []).append((year, value))
    output: list[tuple[str, _Scalar | _Boolean]] = []
    for entity, values in sorted(grouped.items()):
        entity_ordered = sorted(values, key=lambda item: item[0])
        if operation is ProgramOperation.DROP_FIRST_BY_ENTITY:
            if len(entity_ordered) < 2:
                raise GroundedPlanError(
                    f"drop_first_by_entity requires at least two periods for {entity}"
                )
            output.extend((f"{entity}|{year}", value) for year, value in entity_ordered[1:])
            continue
        if operation in {
            ProgramOperation.ROLLING_GROWTH_BY_ENTITY,
            ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
            ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
        }:
            if len(entity_ordered) < 2:
                raise GroundedPlanError(
                    f"{operation.value} requires at least two periods for {entity}"
                )
            for (previous_year, previous), (current_year, current) in pairwise(entity_ordered):
                del previous_year
                if operation is ProgramOperation.ROLLING_GROWTH_BY_ENTITY:
                    point = _scalar_binary(ProgramOperation.GROWTH, previous, current)
                elif operation is ProgramOperation.ROLLING_AVERAGE_BY_ENTITY:
                    point = _Scalar(
                        (previous.value + current.value) / Decimal(2),
                        f"(({previous.expression} + {current.expression}) / 2)",
                        _compatible_numeric_dimension(
                            previous.dimension,
                            current.dimension,
                            ProgramOperation.ADD,
                        ),
                        _merge_fact_uids(previous, current),
                    )
                else:
                    point = _scalar_binary(ProgramOperation.SUBTRACT, current, previous)
                output.append((f"{entity}|{current_year}", point))
            continue
        if operation in {
            ProgramOperation.AVERAGE_BY_ENTITY,
            ProgramOperation.SUM_BY_ENTITY,
        }:
            values_only = [value for _year, value in entity_ordered]
            total = sum((value.value for value in values_only), Decimal(0))
            if operation is ProgramOperation.AVERAGE_BY_ENTITY:
                result = total / Decimal(len(values_only))
                expression = (
                    "((" + " + ".join(value.expression for value in values_only) + ") / "
                    f"{len(values_only)})"
                )
            else:
                result = total
                expression = "(" + " + ".join(value.expression for value in values_only) + ")"
            output.append(
                (
                    entity,
                    _Scalar(
                        result,
                        expression,
                        values_only[0].dimension,
                        _merge_fact_uids(*values_only),
                    ),
                )
            )
            continue
        if operation is ProgramOperation.CAGR_BY_ENTITY:
            if len(entity_ordered) < 2:
                raise GroundedPlanError(
                    f"cagr_by_entity requires at least two periods for {entity}"
                )
            first = entity_ordered[0][1]
            last = entity_ordered[-1][1]
            if first.value == 0 or first.value * last.value < 0:
                raise GroundedPlanError(
                    f"cagr_by_entity has an invalid start/end value for {entity}"
                )
            intervals = entity_ordered[-1][0] - entity_ordered[0][0]
            if intervals <= 0:
                raise GroundedPlanError(f"cagr_by_entity has no positive interval for {entity}")
            cagr = (float(last.value / first.value) ** (1.0 / intervals) - 1.0) * 100.0
            output.append(
                (
                    entity,
                    _Scalar(
                        Decimal(str(cagr)),
                        f"((pow((({last.expression}) / ({first.expression})), "
                        f"(1 / {intervals})) - 1) * 100)",
                        Dimension.PERCENT,
                        _merge_fact_uids(first, last),
                    ),
                )
            )
            continue
        if (
            operation
            in {
                ProgramOperation.GROWTH_BY_ENTITY,
                ProgramOperation.CHANGE_BY_ENTITY,
            }
            and len(entity_ordered) < 2
        ):
            raise GroundedPlanError(f"{operation.value} requires at least two periods for {entity}")
        if operation is ProgramOperation.EARLIEST_BY_ENTITY:
            output.append((entity, entity_ordered[0][1]))
            continue
        if operation is ProgramOperation.LATEST_BY_ENTITY:
            output.append((entity, entity_ordered[-1][1]))
            continue
        binary_operation = (
            ProgramOperation.GROWTH
            if operation is ProgramOperation.GROWTH_BY_ENTITY
            else ProgramOperation.SUBTRACT
        )
        output.append(
            (
                entity,
                _scalar_binary(
                    ProgramOperation.SUBTRACT,
                    entity_ordered[-1][1],
                    entity_ordered[0][1],
                )
                if binary_operation is ProgramOperation.SUBTRACT
                else _scalar_binary(
                    binary_operation,
                    entity_ordered[0][1],
                    entity_ordered[-1][1],
                ),
            )
        )
    return _Series(tuple(output))


def _program_sum_by_scope(series: _Series, target_axis: str) -> _Series:
    """Reduce physical component observations to one logical scope value."""

    grouped: dict[str, list[_Scalar]] = {}
    for observation_key, value in _numeric_series(series):
        parts = observation_key.split("|", 2)
        if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
            raise GroundedPlanError("sum_by_scope requires entity_period_observation-axis keys")
        entity, period, _observation_uid = parts
        if target_axis == "entity":
            key = entity
        elif target_axis == "period":
            key = period
        else:
            key = f"{entity}|{period}"
        grouped.setdefault(key, []).append(value)

    output: list[tuple[str, _Scalar | _Boolean]] = []
    for key, values in sorted(grouped.items()):
        total = values[0]
        for value in values[1:]:
            total = _scalar_binary(ProgramOperation.ADD, total, value)
        output.append((key, total))
    return _Series(tuple(output))


def _program_boolean_by_entity(operation: ProgramOperation, series: _Series) -> _Series:
    grouped: dict[str, list[_Boolean]] = {}
    for key, value in _boolean_series(series):
        try:
            entity, _year = key.rsplit("|", 1)
        except ValueError as error:
            raise GroundedPlanError(
                f"{operation.value} requires entity_period-axis keys"
            ) from error
        grouped.setdefault(entity, []).append(value)
    output: list[tuple[str, _Scalar | _Boolean]] = []
    for entity, values in sorted(grouped.items()):
        if not values:
            raise GroundedPlanError(f"{operation.value} has no values for {entity}")
        if operation is ProgramOperation.ALL_BY_ENTITY:
            result = all(value.value for value in values)
            expression = "(" + " and ".join(f"({value.expression})" for value in values) + ")"
        else:
            result = any(value.value for value in values)
            expression = "(" + " or ".join(f"({value.expression})" for value in values) + ")"
        output.append(
            (entity, _Boolean(result, expression, _merge_fact_uids(*values)))
        )
    return _Series(tuple(output))


def _program_top_k_mask(
    operation: ProgramOperation,
    series: _Series,
    literal: Decimal | None,
) -> _Series:
    if literal is None or literal != literal.to_integral() or literal <= 0:
        raise GroundedPlanError(f"{operation.value} requires a positive integer literal")
    numeric = _numeric_series(series)
    k = int(literal)
    if k > len(numeric):
        raise GroundedPlanError(f"{operation.value} requests {k} keys from {len(numeric)} values")
    reverse = operation is ProgramOperation.TOP_K_MASK
    ordered = sorted(
        numeric,
        key=lambda item: (item[1].value, item[0]),
        reverse=reverse,
    )
    selected = {key for key, _value in ordered[:k]}
    grounding = " + ".join(f"0 * ({value.expression})" for _key, value in numeric)
    ranking_uids = _merge_fact_uids(*(value for _key, value in numeric))
    return _Series(
        tuple(
            (
                key,
                _Boolean(
                    key in selected,
                    f"(({1 if key in selected else 0} + {grounding}) > 0)",
                    ranking_uids,
                ),
            )
            for key, _value in numeric
        )
    )


def _program_shift_key(key: _Key, literal: Decimal | None) -> _Key:
    if literal is None or literal != literal.to_integral():
        raise GroundedPlanError("shift_key requires an integer literal")
    try:
        shifted = str(int(key.value) + int(literal))
    except ValueError as error:
        raise GroundedPlanError("shift_key requires a numeric period key") from error
    return _Key(shifted, key.grounding_expression, key.fact_uids)


def _program_true_key(operation: ProgramOperation, series: _Series) -> _Key:
    boolean = _boolean_series(series)
    selected = [item for item in boolean if item[1].value]
    if not selected:
        raise GroundedPlanError(f"{operation.value} has no true key")
    try:
        chosen = (
            min(selected, key=lambda item: int(item[0]))
            if operation is ProgramOperation.FIRST_TRUE_KEY
            else max(selected, key=lambda item: int(item[0]))
        )
    except ValueError as error:
        raise GroundedPlanError(f"{operation.value} requires numeric period keys") from error
    grounding = " + ".join(f"0 * ({item.expression})" for _key, item in boolean)
    return _Key(
        chosen[0],
        grounding,
        _merge_fact_uids(*(item for _key, item in boolean)),
    )


def _series_binary(
    operation: ProgramOperation,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _Series:
    left_series = left.mapping() if isinstance(left, _Series) else None
    right_series = right.mapping() if isinstance(right, _Series) else None
    if left_series is not None and right_series is not None:
        common_keys = set(left_series) & set(right_series)
        if not common_keys:
            raise GroundedPlanError(f"{operation.value} series keys do not align")
        assert isinstance(left, _Series)
        keys = [key for key, _value in left.values if key in common_keys]
    elif left_series is not None:
        assert isinstance(left, _Series)
        keys = [key for key, _value in left.values]
    elif right_series is not None:
        assert isinstance(right, _Series)
        keys = [key for key, _value in right.values]
    else:  # pragma: no cover - caller guarantees at least one series
        raise GroundedPlanError("series operation has no series")
    output: list[tuple[str, _Scalar | _Boolean]] = []
    for key in keys:
        left_value = left_series[key] if left_series is not None else left
        right_value = right_series[key] if right_series is not None else right
        if not isinstance(left_value, _Scalar) or not isinstance(right_value, _Scalar):
            raise GroundedPlanError(f"{operation.value} series inputs must be numeric")
        output.append((key, _scalar_binary(operation, left_value, right_value)))
    return _Series(tuple(output))


def _scalar_binary(
    operation: ProgramOperation,
    left: _Scalar,
    right: _Scalar,
) -> _Scalar:
    if operation in {ProgramOperation.ADD, ProgramOperation.SUBTRACT, ProgramOperation.GROWTH}:
        dimension = _compatible_numeric_dimension(left.dimension, right.dimension, operation)
    elif operation is ProgramOperation.DIVIDE:
        if right.value == 0:
            raise GroundedPlanError("program division denominator is zero")
        dimension = Dimension.RATIO if left.dimension == right.dimension else left.dimension
    else:
        if left.dimension is not Dimension.UNKNOWN and right.dimension is not Dimension.UNKNOWN:
            raise GroundedPlanError("multiplication requires one dimensionless input")
        dimension = right.dimension if left.dimension is Dimension.UNKNOWN else left.dimension
    operators = {
        ProgramOperation.ADD: "+",
        ProgramOperation.SUBTRACT: "-",
        ProgramOperation.MULTIPLY: "*",
        ProgramOperation.DIVIDE: "/",
    }
    if operation is ProgramOperation.GROWTH:
        if left.value == 0:
            raise GroundedPlanError("program growth denominator is zero")
        value = (right.value - left.value) / abs(left.value) * Decimal(100)
        expression = f"(({right.expression} - {left.expression}) / abs({left.expression}) * 100)"
        return _Scalar(
            value,
            expression,
            Dimension.PERCENT,
            _merge_fact_uids(left, right),
        )
    if operation is ProgramOperation.ADD:
        value = left.value + right.value
    elif operation is ProgramOperation.SUBTRACT:
        value = left.value - right.value
    elif operation is ProgramOperation.MULTIPLY:
        value = left.value * right.value
    else:
        value = left.value / right.value
    return _Scalar(
        value,
        f"({left.expression} {operators[operation]} {right.expression})",
        dimension,
        _merge_fact_uids(left, right),
    )


def _compatible_numeric_dimension(
    left: Dimension,
    right: Dimension,
    operation: ProgramOperation,
) -> Dimension:
    if left is Dimension.UNKNOWN:
        return right
    if right is Dimension.UNKNOWN:
        return left
    if left != right:
        raise GroundedPlanError(
            f"{operation.value} dimension mismatch: {left.value} vs {right.value}"
        )
    return left


def _program_unary_numeric(
    value: _ProgramValue, transform: Callable[[_Scalar], _Scalar]
) -> _ProgramValue:
    if isinstance(value, _Scalar):
        return transform(value)
    if isinstance(value, _Series):
        output: list[tuple[str, _Scalar | _Boolean]] = []
        for key, item in value.values:
            if not isinstance(item, _Scalar):
                raise GroundedPlanError("numeric unary operation received booleans")
            output.append((key, transform(item)))
        return _Series(tuple(output))
    raise GroundedPlanError("numeric unary operation received a non-numeric input")


def _program_aggregate(operation: ProgramOperation, value: _ProgramValue) -> _Scalar:
    if not isinstance(value, _Series):
        raise GroundedPlanError(f"{operation.value} requires a series")
    numeric = _numeric_series(value)
    if not numeric:
        raise GroundedPlanError(f"{operation.value} cannot aggregate an empty series")
    dimensions = {item.dimension for _key, item in numeric}
    if len(dimensions) != 1:
        raise GroundedPlanError(f"{operation.value} series has mixed dimensions")
    values = [item.value for _key, item in numeric]
    expressions = [item.expression for _key, item in numeric]
    dimension = numeric[0][1].dimension
    fact_uids = _merge_fact_uids(*(item for _key, item in numeric))
    if operation is ProgramOperation.SUM:
        return _Scalar(
            sum(values, Decimal(0)),
            "(" + " + ".join(expressions) + ")",
            dimension,
            fact_uids,
        )
    if operation is ProgramOperation.AVERAGE:
        return _Scalar(
            sum(values, Decimal(0)) / len(values),
            "((" + " + ".join(expressions) + f") / {len(values)})",
            dimension,
            fact_uids,
        )
    ordered = sorted(zip(values, expressions, strict=True), key=lambda item: item[0])
    if operation is ProgramOperation.MINIMUM:
        expression = expressions[0] if len(expressions) == 1 else f"min({', '.join(expressions)})"
        return _Scalar(ordered[0][0], expression, dimension, fact_uids)
    if operation is ProgramOperation.MAXIMUM:
        expression = expressions[0] if len(expressions) == 1 else f"max({', '.join(expressions)})"
        return _Scalar(ordered[-1][0], expression, dimension, fact_uids)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return _Scalar(ordered[middle][0], ordered[middle][1], dimension, fact_uids)
    return _Scalar(
        (ordered[middle - 1][0] + ordered[middle][0]) / 2,
        f"(({ordered[middle - 1][1]} + {ordered[middle][1]}) / 2)",
        dimension,
        fact_uids,
    )


def _program_compare(
    comparator: Comparator,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _ProgramValue:
    if isinstance(left, _Series) or isinstance(right, _Series):
        left_series = left.mapping() if isinstance(left, _Series) else None
        right_series = right.mapping() if isinstance(right, _Series) else None
        if left_series is not None and right_series is not None:
            if set(left_series) != set(right_series):
                raise GroundedPlanError("compare series keys do not align")
            assert isinstance(left, _Series)
            keys = [key for key, _value in left.values]
        elif left_series is not None:
            assert isinstance(left, _Series)
            keys = [key for key, _value in left.values]
        elif right_series is not None:
            assert isinstance(right, _Series)
            keys = [key for key, _value in right.values]
        else:  # pragma: no cover
            raise GroundedPlanError("compare has no series")
        output: list[tuple[str, _Scalar | _Boolean]] = []
        for key in keys:
            lhs = left_series[key] if left_series is not None else left
            rhs = right_series[key] if right_series is not None else right
            output.append((key, _compare_scalars(comparator, lhs, rhs)))
        return _Series(tuple(output))
    return _compare_scalars(comparator, left, right)


def _compare_scalars(
    comparator: Comparator,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _Boolean:
    if not isinstance(left, _Scalar) or not isinstance(right, _Scalar):
        raise GroundedPlanError("compare inputs must be numeric")
    _compatible_numeric_dimension(left.dimension, right.dimension, ProgramOperation.COMPARE)
    operators = {
        Comparator.GT: ">",
        Comparator.GTE: ">=",
        Comparator.LT: "<",
        Comparator.LTE: "<=",
        Comparator.EQ: "==",
        Comparator.NE: "!=",
    }
    comparisons = {
        Comparator.GT: left.value > right.value,
        Comparator.GTE: left.value >= right.value,
        Comparator.LT: left.value < right.value,
        Comparator.LTE: left.value <= right.value,
        Comparator.EQ: left.value == right.value,
        Comparator.NE: left.value != right.value,
    }
    return _Boolean(
        comparisons[comparator],
        f"({left.expression} {operators[comparator]} {right.expression})",
        _merge_fact_uids(left, right),
    )


def _program_numeric_presence(operation: ProgramOperation, value: _ProgramValue) -> _ProgramValue:
    def predicate(item: _Scalar) -> _Boolean:
        is_present = item.value != 0
        if operation is ProgramOperation.IS_ZERO:
            is_present = not is_present
        operator = "==" if operation is ProgramOperation.IS_ZERO else "!="
        return _Boolean(
            is_present,
            f"({item.expression} {operator} 0)",
            item.fact_uids,
        )

    if isinstance(value, _Scalar):
        return predicate(value)
    if isinstance(value, _Series):
        return _Series(tuple((key, predicate(item)) for key, item in _numeric_series(value)))
    raise GroundedPlanError(f"{operation.value} requires a numeric input")


def _program_logical(
    operation: ProgramOperation,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _ProgramValue:
    if isinstance(left, _Series) and isinstance(right, _Series):
        left_values = left.mapping()
        right_values = right.mapping()
        if set(left_values) != set(right_values):
            raise GroundedPlanError(f"{operation.value} series keys do not align")
        output: list[tuple[str, _Scalar | _Boolean]] = []
        for key, raw_left in left.values:
            raw_right = right_values[key]
            output.append((key, _logical_scalars(operation, raw_left, raw_right)))
        return _Series(tuple(output))
    return _logical_scalars(operation, left, right)


def _logical_scalars(
    operation: ProgramOperation,
    left: _ProgramValue,
    right: _ProgramValue,
) -> _Boolean:
    if not isinstance(left, _Boolean) or not isinstance(right, _Boolean):
        raise GroundedPlanError(f"{operation.value} inputs must be boolean")
    if operation is ProgramOperation.LOGICAL_AND:
        return _Boolean(
            left.value and right.value,
            f"({left.expression} and {right.expression})",
            _merge_fact_uids(left, right),
        )
    return _Boolean(
        left.value or right.value,
        f"({left.expression} or {right.expression})",
        _merge_fact_uids(left, right),
    )


def _numeric_series(value: _Series) -> list[tuple[str, _Scalar]]:
    output: list[tuple[str, _Scalar]] = []
    for key, item in value.values:
        if not isinstance(item, _Scalar):
            raise GroundedPlanError("expected a numeric series")
        output.append((key, item))
    return output


def _boolean_series(value: _Series) -> list[tuple[str, _Boolean]]:
    output: list[tuple[str, _Boolean]] = []
    for key, item in value.values:
        if not isinstance(item, _Boolean):
            raise GroundedPlanError("expected a boolean series")
        output.append((key, item))
    return output


def execute_grounded_plan(
    plan: GroundedPlan,
    candidates: Sequence[GroundedFact],
    *,
    dataframe_variable: str = "df1",
) -> GroundedExecution:
    facts_by_uid = {fact.observation_uid: fact for fact in candidates}
    requested_uids = tuple(
        dict.fromkeys((*plan.operand_uids, *plan.selector_uids, *plan.value_uids))
    )
    if not requested_uids:
        raise GroundedPlanError("plan selects no observations")
    missing = [uid for uid in requested_uids if uid not in facts_by_uid]
    if missing:
        raise GroundedPlanError(f"plan references facts outside candidate context: {missing[:5]}")
    selected = tuple(facts_by_uid[uid] for uid in requested_uids)
    operands = tuple(facts_by_uid[uid] for uid in plan.operand_uids)

    operation = plan.operation
    if operation is GroundedOperation.LOOKUP:
        _require_count(operands, exact=1, operation=operation)
        value, expression, dimension = _fact_value(operands[0], dataframe_variable)
    elif operation in {
        GroundedOperation.SUM,
        GroundedOperation.AVERAGE,
        GroundedOperation.MEDIAN,
        GroundedOperation.MINIMUM,
        GroundedOperation.MAXIMUM,
    }:
        _require_count(operands, minimum=1, operation=operation)
        value, expression, dimension = _aggregate(operation, operands, dataframe_variable)
    elif operation is GroundedOperation.DIFFERENCE:
        _require_count(operands, exact=2, operation=operation)
        left, left_expression, dimension = _fact_value(operands[0], dataframe_variable)
        right, right_expression, right_dimension = _fact_value(operands[1], dataframe_variable)
        _require_same_dimension(dimension, right_dimension, operation)
        value = left - right
        expression = f"({left_expression} - {right_expression})"
        if plan.absolute_difference:
            value = abs(value)
            expression = f"abs({expression})"
    elif operation is GroundedOperation.GROWTH:
        _require_count(operands, exact=2, operation=operation)
        old, old_expression, dimension = _fact_value(operands[0], dataframe_variable)
        new, new_expression, new_dimension = _fact_value(operands[1], dataframe_variable)
        _require_same_dimension(dimension, new_dimension, operation)
        if old == 0:
            raise GroundedPlanError("growth denominator is zero")
        value = (new - old) / abs(old) * Decimal(100)
        expression = f"(({new_expression} - {old_expression}) / abs({old_expression}) * 100)"
        dimension = Dimension.PERCENT
    elif operation is GroundedOperation.RATIO:
        _require_count(operands, exact=2, operation=operation)
        numerator, numerator_expression, dimension = _fact_value(operands[0], dataframe_variable)
        denominator, denominator_expression, denominator_dimension = _fact_value(
            operands[1], dataframe_variable
        )
        _require_same_dimension(dimension, denominator_dimension, operation)
        if denominator == 0:
            raise GroundedPlanError("ratio denominator is zero")
        value = numerator / denominator
        expression = f"({numerator_expression} / {denominator_expression})"
        dimension = Dimension.RATIO
    elif operation is GroundedOperation.COUNT:
        _require_count(operands, minimum=1, operation=operation)
        if plan.comparator is None or plan.threshold is None:
            raise GroundedPlanError("count requires comparator and threshold")
        value, expression, dimension = _count(plan, operands, dataframe_variable)
    elif operation in {GroundedOperation.ARGMAX_PERIOD, GroundedOperation.ARGMIN_PERIOD}:
        _require_count(operands, minimum=2, operation=operation)
        value, expression, dimension = _arg_period(operation, operands, dataframe_variable)
    elif operation is GroundedOperation.SELECT_AT_ARG:
        value, expression, dimension = _select_at_arg(plan, facts_by_uid, dataframe_variable)
    else:  # pragma: no cover - exhaustive StrEnum guard
        raise GroundedPlanError(f"unsupported operation: {operation}")

    value, expression = _convert_output(value, expression, dimension, plan)
    try:
        answer = float(value)
    except (ValueError, OverflowError) as error:
        raise GroundedPlanError("plan result is not a float") from error
    if not math.isfinite(answer):
        raise GroundedPlanError("plan result is not finite")
    return GroundedExecution(answer, f"float({expression})", selected, plan)


def _aggregate(
    operation: GroundedOperation,
    facts: tuple[GroundedFact, ...],
    variable: str,
) -> tuple[Decimal, str, Dimension]:
    resolved = tuple(_fact_value(fact, variable) for fact in facts)
    dimensions = {item[2] for item in resolved}
    if len(dimensions) != 1:
        raise GroundedPlanError(
            f"{operation.value} operands have mixed dimensions: "
            f"{sorted(value.value for value in dimensions)}"
        )
    values = [item[0] for item in resolved]
    expressions = [item[1] for item in resolved]
    dimension = resolved[0][2]
    if operation is GroundedOperation.SUM:
        return sum(values, Decimal(0)), "(" + " + ".join(expressions) + ")", dimension
    if operation is GroundedOperation.AVERAGE:
        return (
            sum(values, Decimal(0)) / len(values),
            "((" + " + ".join(expressions) + f") / {len(values)})",
            dimension,
        )
    if operation is GroundedOperation.MINIMUM:
        expression = expressions[0] if len(expressions) == 1 else f"min({', '.join(expressions)})"
        return min(values), expression, dimension
    if operation is GroundedOperation.MAXIMUM:
        expression = expressions[0] if len(expressions) == 1 else f"max({', '.join(expressions)})"
        return max(values), expression, dimension
    ordered = sorted(zip(values, expressions, strict=True), key=lambda item: item[0])
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle][0], ordered[middle][1], dimension
    value = (ordered[middle - 1][0] + ordered[middle][0]) / 2
    expression = f"(({ordered[middle - 1][1]} + {ordered[middle][1]}) / 2)"
    return value, expression, dimension


def _count(
    plan: GroundedPlan,
    facts: tuple[GroundedFact, ...],
    variable: str,
) -> tuple[Decimal, str, Dimension]:
    assert plan.comparator is not None
    assert plan.threshold is not None
    operators = {
        Comparator.GT: ">",
        Comparator.GTE: ">=",
        Comparator.LT: "<",
        Comparator.LTE: "<=",
        Comparator.EQ: "==",
    }
    values: list[bool] = []
    expressions: list[str] = []
    for fact in facts:
        value, expression, _dimension = _fact_value(fact, variable)
        threshold = plan.threshold
        if plan.comparator is Comparator.GT:
            matched = value > threshold
        elif plan.comparator is Comparator.GTE:
            matched = value >= threshold
        elif plan.comparator is Comparator.LT:
            matched = value < threshold
        elif plan.comparator is Comparator.LTE:
            matched = value <= threshold
        else:
            matched = value == threshold
        values.append(matched)
        expressions.append(f"({expression} {operators[plan.comparator]} {threshold})")
    return Decimal(sum(values)), "(" + " + ".join(expressions) + ")", Dimension.COUNT


def _arg_period(
    operation: GroundedOperation,
    facts: tuple[GroundedFact, ...],
    variable: str,
) -> tuple[Decimal, str, Dimension]:
    resolved = [(fact, *_fact_value(fact, variable)) for fact in facts]
    dimensions = {item[3] for item in resolved}
    if len(dimensions) != 1:
        raise GroundedPlanError("arg-period operands have mixed dimensions")
    if any(item[0].period_year is None for item in resolved):
        raise GroundedPlanError("arg-period requires a resolved year for every operand")
    key = lambda item: (item[1], -(item[0].period_year or 0))
    selected = (
        max(resolved, key=key)
        if operation is GroundedOperation.ARGMAX_PERIOD
        else min(resolved, key=key)
    )
    assert selected[0].period_year is not None
    grounding = " + ".join(f"0 * ({item[2]})" for item in resolved)
    return (
        Decimal(selected[0].period_year),
        f"({selected[0].period_year} + {grounding})",
        Dimension.PERIOD,
    )


def _select_at_arg(
    plan: GroundedPlan,
    facts_by_uid: Mapping[str, GroundedFact],
    variable: str,
) -> tuple[Decimal, str, Dimension]:
    selectors = tuple(facts_by_uid[uid] for uid in plan.selector_uids)
    values = tuple(facts_by_uid[uid] for uid in plan.value_uids)
    _require_count(selectors, minimum=2, operation=GroundedOperation.SELECT_AT_ARG)
    _require_count(values, minimum=1, operation=GroundedOperation.SELECT_AT_ARG)
    if plan.join_axis not in {"entity", "period"}:
        raise GroundedPlanError("select_at_arg join_axis must be entity or period")
    if plan.direction not in {"max", "min"}:
        raise GroundedPlanError("select_at_arg direction must be max or min")
    selector_values = [(fact, *_fact_value(fact, variable)) for fact in selectors]
    dimensions = {item[3] for item in selector_values}
    if len(dimensions) != 1:
        raise GroundedPlanError("selector facts have mixed dimensions")
    selected = (
        max(selector_values, key=lambda item: item[1])
        if plan.direction == "max"
        else min(selector_values, key=lambda item: item[1])
    )
    key = selected[0].entity if plan.join_axis == "entity" else selected[0].period
    matching = [
        fact
        for fact in values
        if (fact.entity if plan.join_axis == "entity" else fact.period) == key
    ]
    if len(matching) != 1:
        raise GroundedPlanError(
            f"select_at_arg value cardinality for {plan.join_axis}={key!r}: {len(matching)}"
        )
    value, expression, dimension = _fact_value(matching[0], variable)
    selector_grounding = " + ".join(f"0 * ({item[2]})" for item in selector_values)
    return value, f"({expression} + {selector_grounding})", dimension


def _fact_value(fact: GroundedFact, variable: str) -> tuple[Decimal, str, Dimension]:
    value = fact.canonical_value()
    raw = (
        f"float({variable}[{variable}['observation_uid'] == "
        f"'{fact.observation_uid}']['value'].values[0])"
    )
    expression = raw
    if fact.dimension in {Dimension.MONEY, Dimension.SHARES}:
        if fact.dimension is Dimension.MONEY:
            assert fact.scale_exponent is not None
        exponent = fact.scale_exponent or 0
        if exponent > 0:
            expression = f"({raw} * {10**exponent})"
        elif exponent < 0:
            expression = f"({raw} / {10 ** (-exponent)})"
    return value, expression, fact.dimension


def _convert_output(
    value: Decimal,
    expression: str,
    source_dimension: Dimension,
    plan: GroundedPlan,
) -> tuple[Decimal, str]:
    target = plan.output_dimension
    if target is Dimension.PERCENT and source_dimension is Dimension.RATIO:
        return value * 100, f"({expression} * 100)"
    if target is Dimension.RATIO and source_dimension is Dimension.PERCENT:
        return value / 100, f"({expression} / 100)"
    compatible = source_dimension == target or {
        source_dimension,
        target,
    } <= {Dimension.PERCENT, Dimension.PERCENT_POINT}
    if not compatible:
        raise GroundedPlanError(
            f"output dimension mismatch: source={source_dimension.value}, target={target.value}"
        )
    if target in {Dimension.MONEY, Dimension.SHARES}:
        if plan.output_scale_exponent is None:
            raise GroundedPlanError(f"{target.value} output requires scale_exponent")
        scale = Decimal(10) ** plan.output_scale_exponent
        if scale != 1:
            divisor = 10**plan.output_scale_exponent
            return value / scale, f"({expression} / {divisor})"
    return value, expression


def _require_count(
    facts: Sequence[GroundedFact],
    *,
    operation: GroundedOperation,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    if exact is not None and len(facts) != exact:
        raise GroundedPlanError(
            f"{operation.value} requires exactly {exact} operands, received {len(facts)}"
        )
    if minimum is not None and len(facts) < minimum:
        raise GroundedPlanError(
            f"{operation.value} requires at least {minimum} operands, received {len(facts)}"
        )


def _require_same_dimension(
    left: Dimension,
    right: Dimension,
    operation: GroundedOperation,
) -> None:
    if left != right:
        raise GroundedPlanError(
            f"{operation.value} dimension mismatch: {left.value} vs {right.value}"
        )


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GroundedPlanError(f"{field_name} must be a list")
    output = tuple(str(item) for item in value)
    if len(output) != len(set(output)):
        raise GroundedPlanError(f"{field_name} contains duplicates")
    return output


def _optional_string(value: object) -> str | None:
    return None if value in (None, "") else str(value)
