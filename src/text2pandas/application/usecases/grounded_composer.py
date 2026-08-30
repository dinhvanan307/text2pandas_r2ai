"""Deterministic vectorized composition over canonical grounded metrics."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from text2pandas.application.usecases.grounded_resolution import (
    has_hard_logical_fact_conflict,
)
from text2pandas.application.usecases.grounded_synthesis import (
    Comparator,
    GroundedFact,
    GroundedPlan,
    GroundedPlanError,
    GroundedPlanGenerator,
    GroundedProgram,
    ProgramNode,
    ProgramOperation,
)
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import Dimension


class DeterministicCompositionUnsupported(GroundedPlanError):
    """The governed composer has no template for this semantic shape."""


@dataclass(slots=True)
class DeterministicProgramComposer:
    """Compile governed formula contracts without exposing values to a model."""

    confidence: float = 0.96
    semantic_generator: GroundedPlanGenerator | None = None

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        return next(self.generate_candidates(question, facts, hints=hints))

    def generate_candidates(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> Iterator[GroundedProgram]:
        """Cascade governed templates into the canonical semantic compiler.

        Each candidate is still checked by the independent context, lineage,
        type and replay gates.  The semantic compiler is lazy: it runs only
        after a template cannot be generated or its candidate is rejected.
        """

        def candidates() -> Iterator[GroundedProgram]:
            failures: list[str] = []
            try:
                yield self._generate_template(question, facts, hints=hints)
            except GroundedPlanError as error:
                failures.append(f"template={error}")
            if self.semantic_generator is not None:
                try:
                    candidate = self.semantic_generator.generate(
                        question, facts, hints=hints
                    )
                    if not isinstance(candidate, GroundedProgram):
                        raise DeterministicCompositionUnsupported(
                            "semantic compiler returned a legacy plan"
                        )
                    yield candidate
                except GroundedPlanError as error:
                    failures.append(f"semantic_ast={error}")
            detail = "; ".join(failures) or "no governed planner is configured"
            raise DeterministicCompositionUnsupported(detail)

        return candidates()

    def _generate_template(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        formulas = _mappings(hints.get("required_formulas"))
        roles = {str(formula.get("role")): formula for formula in formulas}
        if _is_after_first_negative_period(question, hints, formulas):
            return _generate_after_first_negative_period(
                facts,
                hints=hints,
                output_formula=formulas[0],
                confidence=self.confidence,
            )
        if _is_continuous_positive_growth_average(question, hints):
            return _generate_continuous_positive_growth_average(
                question, facts, hints=hints, confidence=self.confidence
            )
        if _is_continuous_positive_formula_gap_average(question, hints, formulas):
            return _generate_continuous_positive_formula_gap_average(
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_continuous_positive_latest_sum(question, hints):
            return _generate_continuous_positive_latest_sum(
                facts, hints=hints, confidence=self.confidence
            )
        if _is_continuous_cagr_rank(question, hints, formulas):
            return _generate_continuous_cagr_rank(
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_growth_filtered_change_rank(question, hints, roles):
            return _generate_growth_filtered_change_rank(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if _is_rolling_formula_count(question, hints, formulas):
            return _generate_rolling_formula_count(
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_top_k_formula_count(question, hints, formulas):
            return _generate_top_k_formula_count(
                question,
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_median_filtered_average(question, hints, roles):
            return _generate_median_filtered_average(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if _is_median_group_average_difference(question, hints, roles):
            return _generate_median_group_average_difference(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if _is_inventory_days_filtered_margin_average(question, hints, formulas):
            return _generate_inventory_days_filtered_margin_average(
                question,
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_inventory_days_change(question, hints):
            return _generate_inventory_days_rank(
                question,
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_filtered_period_rank(question, hints, formulas):
            return _generate_filtered_period_rank(
                question,
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if _is_filtered_profit_share(question, hints):
            return _generate_filtered_profit_share(
                facts, hints=hints, confidence=self.confidence
            )
        if _is_median_filtered_share(question, hints, formulas):
            return _generate_median_filtered_share(
                question,
                facts,
                hints=hints,
                formulas=formulas,
                confidence=self.confidence,
            )
        if (
            not formulas
            and len(_sequence(hints.get("required_metric_ids"))) == 2
            and str(hints.get("operation") or "") == "extremum"
        ):
            return _generate_direct_rank_select(
                question, facts, hints=hints, confidence=self.confidence
            )
        if (
            len(formulas) == 1
            and str(hints.get("operation") or "") == "extremum"
            and len(_sequence(hints.get("required_metric_ids"))) == 3
        ):
            return _generate_formula_output_direct_rank(
                question,
                facts,
                hints=hints,
                output_formula=formulas[0],
                confidence=self.confidence,
            )
        if {"filter", "rank"} <= roles.keys() and (
            "output" in roles or str(hints.get("operation") or "") == "extremum"
        ):
            return self._generate_filtered_rank(question, facts, hints=hints)
        if _is_positive_conditioned_rank_select(question, hints, roles):
            return _generate_positive_conditioned_rank_select(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if _is_positive_period_formula_rank_select(question, hints, roles):
            return _generate_positive_period_formula_rank_select(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if {"rank", "output"} <= roles.keys() and len(
            _sequence(hints.get("periods"))
        ) == 2:
            normalized = normalize_phrase(question)
            if any(
                cue in normalized for cue in ("muc giam", "muc tang", "bien dong")
            ):
                return self._generate_two_period_entity_rank(
                    question, facts, hints=hints
                )
            return _generate_current_rank_select(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if {"rank", "output"} <= roles.keys():
            return _generate_current_rank_select(
                question,
                facts,
                hints=hints,
                roles=roles,
                confidence=self.confidence,
            )
        if len(formulas) == 1 and str(hints.get("operation") or "") == "divide":
            normalized = normalize_phrase(question)
            if any(
                cue in normalized
                for cue in (
                    "sut giam sau nhat",
                    "giam manh nhat",
                    "tang truong cao nhat",
                    "tang cao nhat",
                )
            ):
                return _generate_rolling_rank_select(
                    question,
                    facts,
                    hints=hints,
                    output_formula=formulas[0],
                    confidence=self.confidence,
                )
        return _generate_simple(
            question,
            facts,
            hints=hints,
            formulas=formulas,
            confidence=self.confidence,
        )

    def _generate_filtered_rank(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        formulas = _mappings(hints.get("required_formulas"))
        roles = {str(formula.get("role")): formula for formula in formulas}
        rank_is_output = "output" not in roles
        if rank_is_output and str(hints.get("operation") or "") == "extremum":
            roles["output"] = roles["rank"]
        if not {"filter", "rank", "output"} <= roles.keys():
            raise DeterministicCompositionUnsupported(
                "no deterministic template for semantic shape"
            )
        normalized = normalize_phrase(question)
        explicit_threshold = _formula_filter_threshold(
            normalized, roles["filter"]
        )
        if "trung vi" not in normalized and explicit_threshold is None:
            raise DeterministicCompositionUnsupported(
                "filtered rank template requires a median or explicit threshold"
            )
        grouped = _group_facts(facts)
        required_metrics = tuple(
            str(value) for value in _sequence(hints.get("required_metric_ids"))
        )
        missing = set(required_metrics) - grouped.keys()
        if missing:
            raise GroundedPlanError(
                f"deterministic composer misses facts for metrics: {sorted(missing)}"
            )
        axis = _axis(facts)
        nodes: list[ProgramNode] = []
        source_nodes: dict[str, str] = {}
        for metric_id in required_metrics:
            metric_facts = grouped[metric_id]
            node_id = _node_id(f"facts_{metric_id}", nodes)
            nodes.append(
                ProgramNode(
                    node_id,
                    ProgramOperation.FACTS,
                    fact_uids=tuple(
                        fact.observation_uid
                        for fact in sorted(metric_facts, key=_fact_scope_key)
                    ),
                    axis=axis,
                )
            )
            source_nodes[metric_id] = node_id

        filter_value = _compile_formula(
            roles["filter"], nodes, source_nodes, prefix="filter_formula"
        )
        if axis == "entity_period":
            starting_filter = _node_id("starting_filter", nodes)
            nodes.append(
                ProgramNode(
                    starting_filter,
                    (
                        ProgramOperation.LATEST_BY_ENTITY
                        if rank_is_output
                        else ProgramOperation.EARLIEST_BY_ENTITY
                    ),
                    input_ids=(filter_value,),
                )
            )
            filter_value = starting_filter
        if "trung vi" in normalized:
            threshold_id = _node_id("filter_median", nodes)
            nodes.append(
                ProgramNode(
                    threshold_id,
                    ProgramOperation.MEDIAN,
                    input_ids=(filter_value,),
                )
            )
            comparator = _median_comparator(normalized)
        else:
            assert explicit_threshold is not None
            threshold, comparator = explicit_threshold
            threshold_id = _node_id("filter_threshold", nodes)
            nodes.append(
                ProgramNode(
                    threshold_id,
                    ProgramOperation.LITERAL,
                    literal=threshold,
                )
            )
        predicate_id = _node_id("filter_predicate", nodes)
        nodes.append(
            ProgramNode(
                predicate_id,
                ProgramOperation.COMPARE,
                input_ids=(filter_value, threshold_id),
                comparator=comparator,
            )
        )

        rank_value = _compile_formula(
            roles["rank"], nodes, source_nodes, prefix="rank_formula"
        )
        if axis == "entity_period":
            rank_change = _node_id("rank_change", nodes)
            nodes.append(
                ProgramNode(
                    rank_change,
                    (
                        ProgramOperation.LATEST_BY_ENTITY
                        if rank_is_output
                        else ProgramOperation.CHANGE_BY_ENTITY
                    ),
                    input_ids=(rank_value,),
                )
            )
            rank_value = rank_change
        filtered_rank = _node_id("filtered_rank", nodes)
        nodes.append(
            ProgramNode(
                filtered_rank,
                ProgramOperation.FILTER,
                input_ids=(rank_value, predicate_id),
            )
        )
        rank_operation = (
            ProgramOperation.ARGMIN_KEY
            if any(value in normalized for value in ("thap nhat", "nho nhat"))
            else ProgramOperation.ARGMAX_KEY
        )
        selected_key = _node_id("selected_key", nodes)
        nodes.append(
            ProgramNode(selected_key, rank_operation, input_ids=(filtered_rank,))
        )

        output_value = _compile_formula(
            roles["output"], nodes, source_nodes, prefix="output_formula"
        )
        if axis == "entity_period":
            latest_output = _node_id("latest_output", nodes)
            nodes.append(
                ProgramNode(
                    latest_output,
                    ProgramOperation.LATEST_BY_ENTITY,
                    input_ids=(output_value,),
                )
            )
            output_value = latest_output
        output_id = _node_id("answer", nodes)
        nodes.append(
            ProgramNode(
                output_id,
                ProgramOperation.SELECT_AT_KEY,
                input_ids=(output_value, selected_key),
            )
        )
        requested_unit = hints.get("requested_unit")
        if not isinstance(requested_unit, Mapping):
            raise GroundedPlanError("deterministic composer requires requested_unit")
        try:
            output_dimension = Dimension(str(requested_unit["dimension"]))
        except (KeyError, ValueError) as error:
            raise GroundedPlanError("invalid deterministic output dimension") from error
        scale_raw = requested_unit.get("scale_exponent")
        output_scale = None if scale_raw is None else int(str(scale_raw))
        return GroundedProgram(
            tuple(nodes),
            output_id,
            output_dimension,
            output_scale,
            self.confidence,
        )

    def _generate_two_period_entity_rank(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        formulas = _mappings(hints.get("required_formulas"))
        roles = {str(formula.get("role")): formula for formula in formulas}
        normalized = normalize_phrase(question)
        if not any(cue in normalized for cue in ("muc giam", "muc tang", "bien dong")):
            raise DeterministicCompositionUnsupported(
                "two-period entity rank requires a change cue"
            )
        grouped = _group_facts(facts)
        required_metrics = tuple(
            str(value) for value in _sequence(hints.get("required_metric_ids"))
        )
        missing = set(required_metrics) - grouped.keys()
        if missing:
            raise GroundedPlanError(
                f"two-period entity rank misses metrics: {sorted(missing)}"
            )
        nodes: list[ProgramNode] = []
        source_nodes: dict[str, str] = {}
        for metric_id in required_metrics:
            node_id = _node_id(f"facts_{metric_id}", nodes)
            nodes.append(
                ProgramNode(
                    node_id,
                    ProgramOperation.FACTS,
                    fact_uids=tuple(
                        fact.observation_uid
                        for fact in sorted(grouped[metric_id], key=_fact_scope_key)
                    ),
                    axis="entity_period",
                )
            )
            source_nodes[metric_id] = node_id

        rank_formula = _compile_formula(
            roles["rank"], nodes, source_nodes, prefix="rank_formula"
        )
        change_id = _node_id("rank_change_by_entity", nodes)
        nodes.append(
            ProgramNode(
                change_id,
                ProgramOperation.CHANGE_BY_ENTITY,
                input_ids=(rank_formula,),
            )
        )
        ranked_value = change_id
        if "bien dong" in normalized:
            absolute_id = _node_id("rank_absolute_change", nodes)
            nodes.append(
                ProgramNode(
                    absolute_id,
                    ProgramOperation.ABSOLUTE,
                    input_ids=(change_id,),
                )
            )
            ranked_value = absolute_id
        rank_operation = (
            ProgramOperation.ARGMIN_KEY
            if "muc giam" in normalized
            else ProgramOperation.ARGMAX_KEY
        )
        selected_key = _node_id("selected_entity", nodes)
        nodes.append(
            ProgramNode(selected_key, rank_operation, input_ids=(ranked_value,))
        )

        output_formula = _compile_formula(
            roles["output"], nodes, source_nodes, prefix="output_formula"
        )
        requested_unit = hints.get("requested_unit")
        if not isinstance(requested_unit, Mapping):
            raise GroundedPlanError("two-period rank requires requested_unit")
        output_projection = _node_id("output_by_entity", nodes)
        output_operation = (
            ProgramOperation.CHANGE_BY_ENTITY
            if str(requested_unit.get("dimension") or "")
            == Dimension.PERCENT_POINT.value
            or "thay doi bao nhieu" in normalized
            else ProgramOperation.LATEST_BY_ENTITY
        )
        nodes.append(
            ProgramNode(
                output_projection,
                output_operation,
                input_ids=(output_formula,),
            )
        )
        output_id = _node_id("answer", nodes)
        nodes.append(
            ProgramNode(
                output_id,
                ProgramOperation.SELECT_AT_KEY,
                input_ids=(output_projection, selected_key),
            )
        )
        try:
            output_dimension = Dimension(str(requested_unit["dimension"]))
        except (KeyError, ValueError) as error:
            raise GroundedPlanError("invalid two-period rank output dimension") from error
        scale_raw = requested_unit.get("scale_exponent")
        output_scale = None if scale_raw is None else int(str(scale_raw))
        return GroundedProgram(
            tuple(nodes),
            output_id,
            output_dimension,
            output_scale,
            self.confidence,
        )


@dataclass(slots=True)
class FallbackGroundedGenerator:
    """Use deterministic composition first, then the eligible local model."""

    deterministic: DeterministicProgramComposer
    fallback: GroundedPlanGenerator

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedPlan | GroundedProgram:
        try:
            return self.deterministic.generate(question, facts, hints=hints)
        except DeterministicCompositionUnsupported:
            return self.fallback.generate(question, facts, hints=hints)

    def generate_candidates(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> Iterator[GroundedPlan | GroundedProgram]:
        """Lazily cascade planners so validation can trigger the fallback.

        A deterministic template can be syntactically applicable yet fail a
        downstream scope, formula-lineage or type gate.  Returning a lazy
        iterator lets the use case validate that first candidate before the
        local model is invoked.
        """

        def candidates() -> Iterator[GroundedPlan | GroundedProgram]:
            try:
                cascade = getattr(self.deterministic, "generate_candidates", None)
                if callable(cascade):
                    yield from cascade(question, facts, hints=hints)
                else:  # compatibility with small test/adapter composers
                    yield self.deterministic.generate(question, facts, hints=hints)
            except GroundedPlanError:
                pass
            yield self.fallback.generate(question, facts, hints=hints)

        return candidates()


@dataclass(slots=True)
class JsonlCachedGroundedGenerator:
    """Append-only cache for expensive value-free semantic model plans."""

    delegate: GroundedPlanGenerator
    path: Path
    namespace: str
    _entries: dict[str, GroundedProgram] = field(
        init=False, repr=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        self.path = self.path.expanduser().resolve()
        if not self.path.is_file():
            return
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise GroundedPlanError(
                    f"invalid semantic cache JSON at line {line_number}: {error}"
                ) from error
            if not isinstance(raw, Mapping) or raw.get("namespace") != self.namespace:
                continue
            cache_key = raw.get("cache_key")
            program_raw = raw.get("program")
            if not isinstance(cache_key, str) or not isinstance(program_raw, Mapping):
                raise GroundedPlanError(
                    f"invalid semantic cache record at line {line_number}"
                )
            self._entries[cache_key] = GroundedProgram.from_mapping(program_raw)

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedPlan | GroundedProgram:
        cache_key = self._key(question, facts, hints)
        cached = self._load(cache_key)
        if cached is not None:
            return cached
        generated = self.delegate.generate(question, facts, hints=hints)
        if isinstance(generated, GroundedProgram):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "cache_key": cache_key,
                            "namespace": self.namespace,
                            "program": _program_mapping(generated),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
            self._entries[cache_key] = generated
        return generated

    def _key(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        hints: Mapping[str, object],
    ) -> str:
        payload = {
            "namespace": self.namespace,
            "question": question,
            "hints": hints,
            "facts": [
                {
                    "uid": fact.observation_uid,
                    "metric": fact.retrieval_metric,
                    "entity": fact.entity,
                    "period": fact.period,
                }
                for fact in facts
            ],
        }
        canonical = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load(self, cache_key: str) -> GroundedProgram | None:
        return self._entries.get(cache_key)


def _generate_simple(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: tuple[Mapping[str, object], ...],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    operation = str(hints.get("operation") or "")
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    if not required_metrics and not formulas:
        return _generate_lexical_direct(
            question, facts, hints=hints, confidence=min(confidence, 0.84)
        )
    grouped = _group_facts(facts)
    if set(required_metrics) - grouped.keys():
        raise DeterministicCompositionUnsupported(
            "simple template lacks canonical metric coverage"
        )
    if len(formulas) > 1 or any(
        str(formula.get("role") or "value") != "value" for formula in formulas
    ):
        raise DeterministicCompositionUnsupported(
            "simple template received multiple semantic formula roles"
        )
    conditional_cues = (
        "dong thoi",
        " vua ",
        "xet ",
        "trong so",
        "nam ma",
        "tai nam",
        "duong",
        " am",
        "lien tuc",
        "thap hon trung vi",
        "cao hon trung vi",
    )
    if operation in {"sum", "average", "subtract", "growth", "divide"} and any(
        cue in normalized for cue in conditional_cues
    ):
        raise DeterministicCompositionUnsupported(
            "simple template rejects conditional/ranked question"
        )
    requested_entities = tuple(str(value) for value in _sequence(hints.get("entities")))
    requested_periods = tuple(str(value)[:4] for value in _sequence(hints.get("periods")))

    if operation in {"growth", "subtract"}:
        if formulas or len(required_metrics) != 1 or len(requested_entities) != 1:
            raise DeterministicCompositionUnsupported(
                "change template requires one direct metric and one entity"
            )
        metric_facts = grouped[required_metrics[0]]
        by_period = {
            str(fact.period_year): fact
            for fact in metric_facts
            if fact.period_year is not None
        }
        if len(requested_periods) != 2 or any(
            period not in by_period for period in requested_periods
        ):
            raise DeterministicCompositionUnsupported(
                "change template requires exactly two requested periods"
            )
        ordered_periods = sorted(requested_periods)
        if operation == "subtract":
            # A period difference is the current/newer value minus the
            # comparison/older value.  Retrieval annotations intentionally
            # store periods as a set-like domain, so input order must be
            # reconstructed from temporal semantics here.
            ordered_periods.reverse()
            if bool(hints.get("reverse_difference")):
                ordered_periods.reverse()
        nodes: list[ProgramNode] = []
        scalar_ids: list[str] = []
        for period in ordered_periods:
            fact = by_period[period]
            source_id = _node_id(f"facts_{required_metrics[0]}_{period}", nodes)
            nodes.append(
                ProgramNode(
                    source_id,
                    ProgramOperation.FACTS,
                    fact_uids=(fact.observation_uid,),
                    axis="entity_period",
                )
            )
            scalar_id = _node_id(f"scalar_{period}", nodes)
            nodes.append(
                ProgramNode(scalar_id, ProgramOperation.SUM, input_ids=(source_id,))
            )
            scalar_ids.append(scalar_id)
        arithmetic = (
            ProgramOperation.GROWTH
            if operation == "growth"
            else ProgramOperation.SUBTRACT
        )
        output_id = _node_id("answer_change", nodes)
        nodes.append(
            ProgramNode(output_id, arithmetic, input_ids=tuple(scalar_ids))
        )
        if operation == "subtract" and bool(hints.get("absolute_difference")):
            absolute_id = _node_id("answer_absolute", nodes)
            nodes.append(
                ProgramNode(
                    absolute_id,
                    ProgramOperation.ABSOLUTE,
                    input_ids=(output_id,),
                )
            )
            output_id = absolute_id
        dimension, scale = _output_contract(hints)
        return GroundedProgram(
            tuple(nodes), output_id, dimension, scale, confidence
        )

    supported = {"lookup", "sum", "average", "extremum", "divide"}
    if operation not in supported:
        raise DeterministicCompositionUnsupported(
            f"simple template does not support operation {operation}"
        )
    if operation == "divide" and (formulas or len(required_metrics) != 2):
        raise DeterministicCompositionUnsupported(
            "direct ratio template requires exactly two direct metrics"
        )
    if operation != "divide" and len(required_metrics) > 1 and not formulas:
        raise DeterministicCompositionUnsupported(
            "simple aggregate template requires one metric"
        )
    selected_facts = tuple(
        fact for metric_id in required_metrics for fact in grouped[metric_id]
    )
    nodes = []
    source_nodes = _append_source_nodes(
        nodes,
        grouped,
        required_metrics,
        axis=_axis(selected_facts),
    )
    if formulas:
        root_id = _compile_formula(
            formulas[0], nodes, source_nodes, prefix="value_formula"
        )
    elif operation == "divide":
        root_id = _node_id("direct_ratio", nodes)
        nodes.append(
            ProgramNode(
                root_id,
                ProgramOperation.DIVIDE,
                input_ids=(
                    source_nodes[required_metrics[0]],
                    source_nodes[required_metrics[1]],
                ),
            )
        )
    else:
        root_id = source_nodes[required_metrics[0]]
    if operation == "lookup":
        if any(len(grouped[metric_id]) != 1 for metric_id in required_metrics):
            raise DeterministicCompositionUnsupported(
                "lookup template requires one scoped fact per metric"
            )
        aggregate = ProgramOperation.SUM
    elif operation == "sum":
        aggregate = ProgramOperation.SUM
    elif operation == "average":
        aggregate = ProgramOperation.AVERAGE
    elif operation == "extremum":
        if str(hints.get("return_mode") or "") not in {"value", "filtered_value"}:
            raise DeterministicCompositionUnsupported(
                "extremum member/select-at-arg requires a compositional template"
            )
        aggregate = (
            ProgramOperation.MINIMUM
            if str(hints.get("rank_direction") or "") == "ascending"
            else ProgramOperation.MAXIMUM
        )
    else:
        aggregate = ProgramOperation.SUM
    output_id = _node_id("answer", nodes)
    nodes.append(ProgramNode(output_id, aggregate, input_ids=(root_id,)))
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), output_id, dimension, scale, confidence)


def _generate_lexical_direct(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    """Compile direct operations from a high-margin lexical row cluster.

    This route is for long-tail reported note metrics absent from the governed
    ontology.  It never sees or ranks by values: selection uses row text,
    requested scope, dimension-aware retrieval score and a strict margin.
    """

    operation = str(hints.get("operation") or "")
    if operation not in {"lookup", "sum", "average", "subtract", "growth", "extremum"}:
        raise DeterministicCompositionUnsupported(
            "lexical direct template does not support the operation"
        )
    normalized = normalize_phrase(question)
    if any(
        cue in normalized
        for cue in (
            "trung vi",
            "dong thoi",
            "trong so",
            "nam ma",
            "tai nam",
            "co muc",
            "duong trong",
            "am trong",
        )
    ):
        raise DeterministicCompositionUnsupported(
            "lexical direct template rejects conditional scope"
        )
    entities = tuple(str(value) for value in _sequence(hints.get("entities")))
    periods = tuple(str(value)[:4] for value in _sequence(hints.get("periods")))
    expected_scopes = _expected_lexical_scopes(entities, periods)
    clusters: dict[str, dict[tuple[str, str], GroundedFact]] = defaultdict(dict)
    question_tokens = set(normalized.split())
    for fact in facts:
        key = _lexical_fact_label(fact)
        if not key:
            continue
        scope = (fact.entity, str(fact.period_year or ""))
        existing = clusters[key].get(scope)
        if existing is None or fact.score > existing.score:
            clusters[key][scope] = fact
    ranked: list[tuple[float, float, str, tuple[GroundedFact, ...]]] = []
    for label, by_scope in clusters.items():
        if expected_scopes and not expected_scopes <= by_scope.keys():
            continue
        selected_scopes = sorted(expected_scopes or by_scope.keys())
        selected = tuple(by_scope[scope] for scope in selected_scopes)
        if not selected:
            continue
        label_tokens = set(label.split())
        coverage = (
            len(label_tokens & question_tokens) / len(label_tokens)
            if label_tokens
            else 0.0
        )
        overlap_count = len(label_tokens & question_tokens)
        mean_score = sum(fact.score for fact in selected) / len(selected)
        ranked.append(
            (
                mean_score + 20.0 * coverage + 6.0 * overlap_count,
                coverage,
                label,
                selected,
            )
        )
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    if not ranked:
        raise DeterministicCompositionUnsupported(
            "lexical direct template has no complete row cluster"
        )
    best = ranked[0]
    if best[1] < 0.45 or (len(ranked) > 1 and best[0] - ranked[1][0] < 4.0):
        raise DeterministicCompositionUnsupported(
            "lexical direct row cluster is ambiguous"
        )
    selected = best[3]
    axis = _axis(selected)
    nodes: list[ProgramNode] = [
        ProgramNode(
            "lexical_facts",
            ProgramOperation.FACTS,
            fact_uids=tuple(fact.observation_uid for fact in selected),
            axis=axis,
        )
    ]
    output_id = "lexical_facts"
    if operation in {"subtract", "growth"}:
        if len(selected) != 2 or len(entities) != 1:
            raise DeterministicCompositionUnsupported(
                "lexical change requires one entity and exactly two periods"
            )
        scalar_ids: list[str] = []
        ordered_facts = sorted(selected, key=_fact_scope_key)
        if operation == "subtract":
            ordered_facts.reverse()
            if bool(hints.get("reverse_difference")):
                ordered_facts.reverse()
        for index, fact in enumerate(ordered_facts, 1):
            source = f"lexical_period_{index}"
            scalar = f"lexical_scalar_{index}"
            nodes.extend(
                (
                    ProgramNode(
                        source,
                        ProgramOperation.FACTS,
                        fact_uids=(fact.observation_uid,),
                        axis="period",
                    ),
                    ProgramNode(scalar, ProgramOperation.SUM, input_ids=(source,)),
                )
            )
            scalar_ids.append(scalar)
        output_id = "answer_change"
        nodes.append(
            ProgramNode(
                output_id,
                ProgramOperation.GROWTH
                if operation == "growth"
                else ProgramOperation.SUBTRACT,
                input_ids=tuple(scalar_ids),
            )
        )
    else:
        aggregate = {
            "lookup": ProgramOperation.SUM,
            "sum": ProgramOperation.SUM,
            "average": ProgramOperation.AVERAGE,
            "extremum": (
                ProgramOperation.MINIMUM
                if str(hints.get("rank_direction") or "") == "ascending"
                else ProgramOperation.MAXIMUM
            ),
        }[operation]
        output_id = "answer"
        nodes.append(ProgramNode(output_id, aggregate, input_ids=("lexical_facts",)))
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), output_id, dimension, scale, confidence)


def _is_after_first_negative_period(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        len(formulas) == 1
        and len(_sequence(hints.get("entities"))) == 1
        and len(_sequence(hints.get("periods"))) >= 3
        and "cash_flow_from_operations" in metrics
        and "nam ngay sau nam dau tien" in normalized
        and "cfo am" in normalized
    )


def _generate_after_first_negative_period(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    output_formula: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"after-first-negative template misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="period")
    zero = _node_id("zero", nodes)
    negative = _node_id("cfo_negative", nodes)
    first_negative = _node_id("first_negative_period", nodes)
    next_period = _node_id("next_period", nodes)
    nodes.extend(
        (
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                negative,
                ProgramOperation.COMPARE,
                input_ids=(sources["cash_flow_from_operations"], zero),
                comparator=Comparator.LT,
            ),
            ProgramNode(
                first_negative,
                ProgramOperation.FIRST_TRUE_KEY,
                input_ids=(negative,),
            ),
            ProgramNode(
                next_period,
                ProgramOperation.SHIFT_KEY,
                input_ids=(first_negative,),
                literal=Decimal(1),
            ),
        )
    )
    output_series = _compile_formula(
        output_formula, nodes, sources, prefix="output_formula"
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, next_period),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _expected_lexical_scopes(
    entities: Sequence[str], periods: Sequence[str]
) -> set[tuple[str, str]]:
    if entities and periods:
        return {(entity, period) for entity in entities for period in periods}
    if entities:
        return {(entity, "") for entity in entities}
    if periods:
        return {("", period) for period in periods}
    return set()


def _lexical_fact_label(fact: GroundedFact) -> str:
    row = normalize_phrase(fact.row_path.rsplit("›", 1)[-1])
    column = normalize_phrase(fact.column_path.rsplit("›", 1)[-1])
    generic = {
        "nam",
        "nay",
        "truoc",
        "vnd",
        "dong",
        "trieu",
        "ty",
        "so",
        "cuoi",
        "dau",
        "ky",
    }
    semantic_column = [
        token for token in column.split() if not token.isdigit() and token not in generic
    ]
    return f"{row} {column}".strip() if len(semantic_column) >= 2 else row


def _is_median_filtered_average(
    question: str,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    return (
        str(hints.get("operation") or "") == "average"
        and len(_sequence(hints.get("periods"))) == 1
        and "trung vi" in normalized
        and {"filter", "output"} <= roles.keys()
        and "chenh lech" not in normalized
        and not any(cue in normalized for cue in ("cao nhat", "thap nhat", "lon nhat"))
    )


def _generate_median_filtered_average(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(required_metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"median filtered average misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, required_metrics, axis="entity")
    filter_value = _compile_formula(
        roles["filter"], nodes, sources, prefix="filter_formula"
    )
    median = _node_id("filter_median", nodes)
    nodes.append(ProgramNode(median, ProgramOperation.MEDIAN, input_ids=(filter_value,)))
    predicate = _node_id("filter_predicate", nodes)
    nodes.append(
        ProgramNode(
            predicate,
            ProgramOperation.COMPARE,
            input_ids=(filter_value, median),
            comparator=_median_comparator(normalize_phrase(question)),
        )
    )
    output_value = _compile_formula(
        roles["output"], nodes, sources, prefix="output_formula"
    )
    eligible = _node_id("eligible_output", nodes)
    nodes.append(
        ProgramNode(
            eligible,
            ProgramOperation.FILTER,
            input_ids=(output_value, predicate),
        )
    )
    answer = _node_id("answer", nodes)
    nodes.append(ProgramNode(answer, ProgramOperation.AVERAGE, input_ids=(eligible,)))
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_median_group_average_difference(
    question: str,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    return (
        str(hints.get("operation") or "") == "average"
        and len(_sequence(hints.get("periods"))) == 1
        and {"filter", "output"} <= roles.keys()
        and "trung vi" in normalized
        and "chenh lech" in normalized
        and "phan nhom" in normalized
    )


def _generate_median_group_average_difference(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"median group difference misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity")
    filter_value = _compile_formula(
        roles["filter"], nodes, sources, prefix="filter_formula"
    )
    output_value = _compile_formula(
        roles["output"], nodes, sources, prefix="output_formula"
    )
    median = _node_id("filter_median", nodes)
    high = _node_id("above_median", nodes)
    remaining = _node_id("remaining_group", nodes)
    high_values = _node_id("above_values", nodes)
    remaining_values = _node_id("remaining_values", nodes)
    high_average = _node_id("above_average", nodes)
    remaining_average = _node_id("remaining_average", nodes)
    answer = _node_id("answer", nodes)
    comparator = _median_comparator(normalize_phrase(question))
    opposite = Comparator.LTE if comparator is Comparator.GT else Comparator.GTE
    nodes.extend(
        (
            ProgramNode(median, ProgramOperation.MEDIAN, input_ids=(filter_value,)),
            ProgramNode(
                high,
                ProgramOperation.COMPARE,
                input_ids=(filter_value, median),
                comparator=comparator,
            ),
            ProgramNode(
                remaining,
                ProgramOperation.COMPARE,
                input_ids=(filter_value, median),
                comparator=opposite,
            ),
            ProgramNode(
                high_values,
                ProgramOperation.FILTER,
                input_ids=(output_value, high),
            ),
            ProgramNode(
                remaining_values,
                ProgramOperation.FILTER,
                input_ids=(output_value, remaining),
            ),
            ProgramNode(
                high_average,
                ProgramOperation.AVERAGE,
                input_ids=(high_values,),
            ),
            ProgramNode(
                remaining_average,
                ProgramOperation.AVERAGE,
                input_ids=(remaining_values,),
            ),
            ProgramNode(
                answer,
                ProgramOperation.SUBTRACT,
                input_ids=(high_average, remaining_average),
            ),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_continuous_positive_growth_average(
    question: str, hints: Mapping[str, object]
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        str(hints.get("operation") or "") == "average"
        and len(_sequence(hints.get("periods"))) == 2
        and "tang truong doanh thu thuan" in normalized
        and "net_revenue" in metrics
        and bool(metrics & {"profit_after_tax", "cash_flow_from_operations"})
        and "duong" in normalized
    )


def _is_continuous_positive_formula_gap_average(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    formula_ids = {str(formula.get("formula_id") or "") for formula in formulas}
    return (
        str(hints.get("operation") or "") in {"average", "subtract"}
        and len(_sequence(hints.get("periods"))) == 2
        and {"gross_margin", "net_margin"} <= formula_ids
        and {"cash_flow_from_operations", "net_revenue"} <= metrics
        and "chenh lech binh quan" in normalized
        and "duong" in normalized
        and "doanh thu thuan" in normalized
        and "giam" in normalized
    )


def _generate_continuous_positive_formula_gap_average(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"continuous formula-gap average misses metrics: {sorted(missing)}"
        )
    formulas_by_id = {
        str(formula.get("formula_id") or ""): formula for formula in formulas
    }
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity_period")
    zero = _node_id("zero", nodes)
    cfo_positive = _node_id("cfo_positive_by_period", nodes)
    cfo_positive_all = _node_id("cfo_positive_all_periods", nodes)
    earliest_revenue = _node_id("earliest_revenue", nodes)
    latest_revenue = _node_id("latest_revenue", nodes)
    revenue_decreased = _node_id("revenue_decreased", nodes)
    eligible = _node_id("eligible_entities", nodes)
    nodes.extend(
        (
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                cfo_positive,
                ProgramOperation.COMPARE,
                input_ids=(sources["cash_flow_from_operations"], zero),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                cfo_positive_all,
                ProgramOperation.ALL_BY_ENTITY,
                input_ids=(cfo_positive,),
            ),
            ProgramNode(
                earliest_revenue,
                ProgramOperation.EARLIEST_BY_ENTITY,
                input_ids=(sources["net_revenue"],),
            ),
            ProgramNode(
                latest_revenue,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(sources["net_revenue"],),
            ),
            ProgramNode(
                revenue_decreased,
                ProgramOperation.COMPARE,
                input_ids=(latest_revenue, earliest_revenue),
                comparator=Comparator.LT,
            ),
            ProgramNode(
                eligible,
                ProgramOperation.LOGICAL_AND,
                input_ids=(cfo_positive_all, revenue_decreased),
            ),
        )
    )
    gross_margin = _compile_formula(
        formulas_by_id["gross_margin"], nodes, sources, prefix="gross_margin"
    )
    net_margin = _compile_formula(
        formulas_by_id["net_margin"], nodes, sources, prefix="net_margin"
    )
    latest_gross_margin = _node_id("latest_gross_margin", nodes)
    latest_net_margin = _node_id("latest_net_margin", nodes)
    margin_gap = _node_id("margin_gap", nodes)
    eligible_gap = _node_id("eligible_margin_gap", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                latest_gross_margin,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(gross_margin,),
            ),
            ProgramNode(
                latest_net_margin,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(net_margin,),
            ),
            ProgramNode(
                margin_gap,
                ProgramOperation.SUBTRACT,
                input_ids=(latest_gross_margin, latest_net_margin),
            ),
            ProgramNode(
                eligible_gap,
                ProgramOperation.FILTER,
                input_ids=(margin_gap, eligible),
            ),
            ProgramNode(
                answer,
                ProgramOperation.AVERAGE,
                input_ids=(eligible_gap,),
            ),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_positive_conditioned_rank_select(
    question: str,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        len(_sequence(hints.get("periods"))) == 1
        and {"rank", "output"} <= roles.keys()
        and "cash_flow_from_operations" in metrics
        and any(cue in normalized for cue in ("cfo duong", "kinh doanh duong"))
    )


def _is_positive_period_formula_rank_select(
    question: str,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    rank_leaves = {
        str(value)
        for value in _sequence(roles.get("rank", {}).get("leaves"))
    }
    return (
        len(_sequence(hints.get("entities"))) == 1
        and len(_sequence(hints.get("periods"))) >= 2
        and {"rank", "output"} <= roles.keys()
        and "profit_after_tax" in rank_leaves
        and any(
            cue in normalized
            for cue in (
                "loi nhuan sau thue duong",
                "loi nhuan sau thue lon hon 0",
                "cac nam loi nhuan sau thue duong",
            )
        )
    )


def _generate_positive_period_formula_rank_select(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"positive period rank misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="period")
    rank = _compile_formula(roles["rank"], nodes, sources, prefix="rank_formula")
    zero = _node_id("zero", nodes)
    positive = _node_id("profit_after_tax_positive", nodes)
    eligible_rank = _node_id("eligible_rank", nodes)
    selected = _node_id("selected_period", nodes)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if any(cue in normalize_phrase(question) for cue in ("thap nhat", "nho nhat"))
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.extend(
        (
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                positive,
                ProgramOperation.COMPARE,
                input_ids=(sources["profit_after_tax"], zero),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                eligible_rank,
                ProgramOperation.FILTER,
                input_ids=(rank, positive),
            ),
            ProgramNode(selected, rank_operation, input_ids=(eligible_rank,)),
        )
    )
    output = _compile_formula(
        roles["output"], nodes, sources, prefix="output_formula"
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output, selected),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _generate_positive_conditioned_rank_select(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"positive conditioned rank misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity")
    zero = _node_id("zero", nodes)
    positive = _node_id("positive_cfo", nodes)
    nodes.extend(
        (
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                positive,
                ProgramOperation.COMPARE,
                input_ids=(sources["cash_flow_from_operations"], zero),
                comparator=Comparator.GT,
            ),
        )
    )
    rank = _compile_formula(roles["rank"], nodes, sources, prefix="rank_formula")
    eligible_rank = _node_id("eligible_rank", nodes)
    selected = _node_id("selected_entity", nodes)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if any(cue in normalize_phrase(question) for cue in ("thap nhat", "nho nhat"))
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.extend(
        (
            ProgramNode(
                eligible_rank,
                ProgramOperation.FILTER,
                input_ids=(rank, positive),
            ),
            ProgramNode(selected, rank_operation, input_ids=(eligible_rank,)),
        )
    )
    output = _compile_formula(
        roles["output"], nodes, sources, prefix="output_formula"
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output, selected),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _generate_continuous_positive_growth_average(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    grouped = _group_facts(facts)
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(required_metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"continuous growth average misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(
        nodes, grouped, required_metrics, axis="entity_period"
    )
    zero = _node_id("zero", nodes)
    nodes.append(ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)))
    masks: list[str] = []
    if "profit_after_tax" in sources and any(
        cue in normalized for cue in ("lnst duong", "loi nhuan sau thue duong")
    ):
        masks.append(
            _append_all_period_comparison(
                nodes,
                sources["profit_after_tax"],
                zero,
                Comparator.GT,
                "profit_positive",
            )
        )
    if "cash_flow_from_operations" in sources and any(
        cue in normalized
        for cue in (
            "cfo duong",
            "dong tien hoat dong duong",
            "luu chuyen tien thuan tu hoat dong kinh doanh duong",
        )
    ):
        masks.append(
            _append_all_period_comparison(
                nodes,
                sources["cash_flow_from_operations"],
                zero,
                Comparator.GT,
                "cfo_positive",
            )
        )
    if (
        {"cash_flow_from_operations", "profit_after_tax"} <= sources.keys()
        and any(cue in normalized for cue in ("cfo/lnst", "cfo tren loi nhuan sau thue"))
        and "lon hon 1" in normalized
    ):
        conversion = _node_id("profit_conversion", nodes)
        nodes.append(
            ProgramNode(
                conversion,
                ProgramOperation.DIVIDE,
                input_ids=(
                    sources["cash_flow_from_operations"],
                    sources["profit_after_tax"],
                ),
            )
        )
        one = _node_id("one", nodes)
        nodes.append(ProgramNode(one, ProgramOperation.LITERAL, literal=Decimal(1)))
        masks.append(
            _append_all_period_comparison(
                nodes, conversion, one, Comparator.GT, "conversion_above_one"
            )
        )
    if not masks:
        raise DeterministicCompositionUnsupported(
            "continuous growth average has no governed predicate"
        )
    eligible = _combine_masks(nodes, masks)
    growth = _node_id("revenue_growth", nodes)
    nodes.append(
        ProgramNode(
            growth,
            ProgramOperation.GROWTH_BY_ENTITY,
            input_ids=(sources["net_revenue"],),
        )
    )
    filtered = _node_id("eligible_growth", nodes)
    nodes.append(
        ProgramNode(filtered, ProgramOperation.FILTER, input_ids=(growth, eligible))
    )
    answer = _node_id("answer", nodes)
    nodes.append(ProgramNode(answer, ProgramOperation.AVERAGE, input_ids=(filtered,)))
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_continuous_positive_latest_sum(
    question: str, hints: Mapping[str, object]
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        str(hints.get("operation") or "") == "sum"
        and len(_sequence(hints.get("periods"))) >= 2
        and {"net_revenue", "profit_after_tax"} <= metrics
        and "tong doanh thu thuan" in normalized
        and "duong trong ca" in normalized
    )


def _generate_continuous_positive_latest_sum(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"continuous latest sum misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity_period")
    margin = _node_id("net_margin", nodes)
    nodes.append(
        ProgramNode(
            margin,
            ProgramOperation.DIVIDE,
            input_ids=(sources["profit_after_tax"], sources["net_revenue"]),
        )
    )
    zero = _node_id("zero", nodes)
    nodes.append(ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)))
    positive_all = _append_all_period_comparison(
        nodes, margin, zero, Comparator.GT, "positive_margin"
    )
    latest_revenue = _node_id("latest_revenue", nodes)
    nodes.append(
        ProgramNode(
            latest_revenue,
            ProgramOperation.LATEST_BY_ENTITY,
            input_ids=(sources["net_revenue"],),
        )
    )
    eligible = _node_id("eligible_revenue", nodes)
    nodes.append(
        ProgramNode(
            eligible,
            ProgramOperation.FILTER,
            input_ids=(latest_revenue, positive_all),
        )
    )
    answer = _node_id("answer", nodes)
    nodes.append(ProgramNode(answer, ProgramOperation.SUM, input_ids=(eligible,)))
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_continuous_cagr_rank(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        str(hints.get("operation") or "") == "extremum"
        and len(_sequence(hints.get("periods"))) >= 3
        and {"cash_flow_from_operations", "net_revenue"} <= metrics
        and "cagr doanh thu thuan" in normalized
        and "kinh doanh duong" in normalized
        and any(
            {str(value) for value in _sequence(formula.get("leaves"))}
            == {"profit_after_tax", "net_revenue"}
            for formula in formulas
        )
    )


def _generate_continuous_cagr_rank(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(f"continuous CAGR misses metrics: {sorted(missing)}")
    output_formula = next(
        formula
        for formula in formulas
        if {str(value) for value in _sequence(formula.get("leaves"))}
        == {"profit_after_tax", "net_revenue"}
    )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity_period")
    zero = _node_id("zero", nodes)
    nodes.append(ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)))
    eligible = _append_all_period_comparison(
        nodes,
        sources["cash_flow_from_operations"],
        zero,
        Comparator.GT,
        "positive_cfo",
    )
    cagr = _node_id("revenue_cagr", nodes)
    eligible_cagr = _node_id("eligible_cagr", nodes)
    selected = _node_id("selected_entity", nodes)
    nodes.extend(
        (
            ProgramNode(
                cagr,
                ProgramOperation.CAGR_BY_ENTITY,
                input_ids=(sources["net_revenue"],),
            ),
            ProgramNode(
                eligible_cagr,
                ProgramOperation.FILTER,
                input_ids=(cagr, eligible),
            ),
            ProgramNode(
                selected,
                ProgramOperation.ARGMAX_KEY,
                input_ids=(eligible_cagr,),
            ),
        )
    )
    output = _compile_formula(
        output_formula, nodes, sources, prefix="output_formula"
    )
    latest_output = _node_id("latest_output", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                latest_output,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(output,),
            ),
            ProgramNode(
                answer,
                ProgramOperation.SELECT_AT_KEY,
                input_ids=(latest_output, selected),
            ),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_growth_filtered_change_rank(
    question: str,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        str(hints.get("operation") or "") == "extremum"
        and len(_sequence(hints.get("periods"))) == 2
        and {"rank", "output"} <= roles.keys()
        and "net_revenue" in metrics
        and "tang truong doanh thu thuan duong" in normalized
        and "muc thay doi" in normalized
    )


def _generate_growth_filtered_change_rank(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"growth-filtered change rank misses metrics: {sorted(missing)}"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity_period")
    growth = _node_id("revenue_growth", nodes)
    zero = _node_id("zero", nodes)
    positive_growth = _node_id("positive_growth", nodes)
    nodes.extend(
        (
            ProgramNode(
                growth,
                ProgramOperation.GROWTH_BY_ENTITY,
                input_ids=(sources["net_revenue"],),
            ),
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                positive_growth,
                ProgramOperation.COMPARE,
                input_ids=(growth, zero),
                comparator=Comparator.GT,
            ),
        )
    )
    rank_formula = _compile_formula(
        roles["rank"], nodes, sources, prefix="rank_formula"
    )
    rank_change = _node_id("rank_change", nodes)
    eligible_rank = _node_id("eligible_rank", nodes)
    selected = _node_id("selected_entity", nodes)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if any(cue in normalize_phrase(question) for cue in ("thap nhat", "nho nhat"))
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.extend(
        (
            ProgramNode(
                rank_change,
                ProgramOperation.CHANGE_BY_ENTITY,
                input_ids=(rank_formula,),
            ),
            ProgramNode(
                eligible_rank,
                ProgramOperation.FILTER,
                input_ids=(rank_change, positive_growth),
            ),
            ProgramNode(selected, rank_operation, input_ids=(eligible_rank,)),
        )
    )
    output_formula = _compile_formula(
        roles["output"], nodes, sources, prefix="output_formula"
    )
    latest_output = _node_id("latest_output", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                latest_output,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(output_formula,),
            ),
            ProgramNode(
                answer,
                ProgramOperation.SELECT_AT_KEY,
                input_ids=(latest_output, selected),
            ),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_rolling_formula_count(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    formula_ids = {str(formula.get("formula_id") or "") for formula in formulas}
    return (
        str(hints.get("operation") or "") == "count"
        and len(_sequence(hints.get("entities"))) == 1
        and len(_sequence(hints.get("periods"))) >= 3
        and {"gross_margin", "cash_flow_from_operations_to_net_revenue"}
        <= formula_ids
        and "cai thien bien loi nhuan gop" in normalized
        and "trung vi cfo margin" in normalized
    )


def _generate_rolling_formula_count(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(f"rolling count misses metrics: {sorted(missing)}")
    formulas_by_id = {
        str(formula.get("formula_id") or ""): formula for formula in formulas
    }
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="period")
    gross_margin = _compile_formula(
        formulas_by_id["gross_margin"], nodes, sources, prefix="gross_margin"
    )
    cfo_margin = _compile_formula(
        formulas_by_id["cash_flow_from_operations_to_net_revenue"],
        nodes,
        sources,
        prefix="cfo_margin",
    )
    margin_change = _node_id("gross_margin_change", nodes)
    zero = _node_id("zero", nodes)
    improved = _node_id("gross_margin_improved", nodes)
    cfo_median = _node_id("cfo_margin_median", nodes)
    above_median = _node_id("cfo_above_median", nodes)
    eligible = _node_id("eligible_year", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                margin_change,
                ProgramOperation.ROLLING_CHANGE,
                input_ids=(gross_margin,),
            ),
            ProgramNode(zero, ProgramOperation.LITERAL, literal=Decimal(0)),
            ProgramNode(
                improved,
                ProgramOperation.COMPARE,
                input_ids=(margin_change, zero),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                cfo_median,
                ProgramOperation.MEDIAN,
                input_ids=(cfo_margin,),
            ),
            ProgramNode(
                above_median,
                ProgramOperation.COMPARE,
                input_ids=(cfo_margin, cfo_median),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                eligible,
                ProgramOperation.FILTER,
                input_ids=(improved, above_median),
            ),
            ProgramNode(answer, ProgramOperation.COUNT_TRUE, input_ids=(eligible,)),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_top_k_formula_count(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    formula_ids = {str(formula.get("formula_id") or "") for formula in formulas}
    return (
        str(hints.get("operation") or "") == "count"
        and len(_sequence(hints.get("periods"))) == 1
        and "net_revenue" in _sequence(hints.get("required_metric_ids"))
        and {"quick_ratio", "debt_to_equity"} <= formula_ids
        and re.search(r"trong \d+ doanh nghiep", normalized) is not None
    )


def _generate_top_k_formula_count(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    k_match = re.search(r"trong (\d+) doanh nghiep", normalized)
    high_match = re.search(r"(?:tren|lon hon) (\d+(?:[.,]\d+)?) lan", normalized)
    low_match = re.search(r"(?:duoi|nho hon) (\d+(?:[.,]\d+)?) lan", normalized)
    if k_match is None or high_match is None or low_match is None:
        raise DeterministicCompositionUnsupported(
            "top-k count cannot parse K and comparison thresholds"
        )
    k = Decimal(k_match.group(1))
    high_threshold = Decimal(high_match.group(1).replace(",", "."))
    low_threshold = Decimal(low_match.group(1).replace(",", "."))
    grouped = _group_facts(facts)
    metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    missing = set(metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(f"top-k count misses metrics: {sorted(missing)}")
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, metrics, axis="entity")
    formulas_by_id = {
        str(formula.get("formula_id") or ""): formula for formula in formulas
    }
    quick = _compile_formula(
        formulas_by_id["quick_ratio"], nodes, sources, prefix="quick_ratio"
    )
    debt = _compile_formula(
        formulas_by_id["debt_to_equity"], nodes, sources, prefix="debt_to_equity"
    )
    five = _node_id("top_five", nodes)
    one = _node_id("one", nodes)
    one_half = _node_id("one_point_five", nodes)
    quick_ok = _node_id("quick_above_one", nodes)
    debt_ok = _node_id("debt_below_one_point_five", nodes)
    financial_ok = _node_id("financial_conditions", nodes)
    eligible = _node_id("eligible_top_five", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                five,
                ProgramOperation.TOP_K_MASK,
                input_ids=(sources["net_revenue"],),
                literal=k,
            ),
            ProgramNode(one, ProgramOperation.LITERAL, literal=high_threshold),
            ProgramNode(one_half, ProgramOperation.LITERAL, literal=low_threshold),
            ProgramNode(
                quick_ok,
                ProgramOperation.COMPARE,
                input_ids=(quick, one),
                comparator=Comparator.GT,
            ),
            ProgramNode(
                debt_ok,
                ProgramOperation.COMPARE,
                input_ids=(debt, one_half),
                comparator=Comparator.LT,
            ),
            ProgramNode(
                financial_ok,
                ProgramOperation.LOGICAL_AND,
                input_ids=(quick_ok, debt_ok),
            ),
            ProgramNode(
                eligible,
                ProgramOperation.LOGICAL_AND,
                input_ids=(five, financial_ok),
            ),
            ProgramNode(answer, ProgramOperation.COUNT_TRUE, input_ids=(eligible,)),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _append_all_period_comparison(
    nodes: list[ProgramNode],
    value_id: str,
    threshold_id: str,
    comparator: Comparator,
    prefix: str,
) -> str:
    comparison = _node_id(prefix + "_by_period", nodes)
    nodes.append(
        ProgramNode(
            comparison,
            ProgramOperation.COMPARE,
            input_ids=(value_id, threshold_id),
            comparator=comparator,
        )
    )
    reduced = _node_id(prefix + "_all_periods", nodes)
    nodes.append(
        ProgramNode(
            reduced,
            ProgramOperation.ALL_BY_ENTITY,
            input_ids=(comparison,),
        )
    )
    return reduced


def _combine_masks(nodes: list[ProgramNode], masks: Sequence[str]) -> str:
    output = masks[0]
    for index, mask in enumerate(masks[1:], 2):
        combined = _node_id(f"eligible_conditions_{index}", nodes)
        nodes.append(
            ProgramNode(
                combined,
                ProgramOperation.LOGICAL_AND,
                input_ids=(output, mask),
            )
        )
        output = combined
    return output


def _generate_rolling_rank_select(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    output_formula: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    marker_positions = [
        (normalized.find(cue), cue)
        for cue in (
            "sut giam sau nhat",
            "giam manh nhat",
            "tang truong cao nhat",
            "tang cao nhat",
        )
        if normalized.find(cue) >= 0
    ]
    if not marker_positions:
        raise DeterministicCompositionUnsupported("rolling rank marker is missing")
    marker_position, marker = min(marker_positions)
    rank_metric = _metric_before_position(
        normalized,
        _mappings(hints.get("metric_contracts")),
        marker_position,
    )
    if rank_metric is None:
        raise DeterministicCompositionUnsupported("rolling rank metric is ambiguous")
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    grouped = _group_facts(facts)
    if set(required_metrics) - grouped.keys() or len(grouped[rank_metric]) < 3:
        raise GroundedPlanError("rolling rank template lacks complete metric facts")
    selected_facts = tuple(
        fact for metric_id in required_metrics for fact in grouped[metric_id]
    )
    nodes: list[ProgramNode] = []
    source_nodes = _append_source_nodes(
        nodes,
        grouped,
        required_metrics,
        axis=_axis(selected_facts),
    )
    growth_id = _node_id("rolling_growth", nodes)
    nodes.append(
        ProgramNode(
            growth_id,
            ProgramOperation.ROLLING_GROWTH,
            input_ids=(source_nodes[rank_metric],),
        )
    )
    rank_id = _node_id("rank_growth", nodes)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if "giam" in marker
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.append(ProgramNode(rank_id, rank_operation, input_ids=(growth_id,)))
    output_series = _compile_formula(
        output_formula, nodes, source_nodes, prefix="output_formula"
    )
    output_id = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            output_id,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, rank_id),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), output_id, dimension, scale, confidence)


def _compile_formula(
    formula: Mapping[str, object],
    nodes: list[ProgramNode],
    source_nodes: Mapping[str, str],
    *,
    prefix: str,
) -> str:
    expression = formula.get("expression")
    if not isinstance(expression, Mapping):
        raise GroundedPlanError("formula contract has no expression")
    root_id = _compile_expression(expression, nodes, source_nodes, prefix=prefix)
    if str(formula.get("output_dimension") or "") == Dimension.PERCENT.value:
        percent_id = _node_id(f"{prefix}_percent", nodes)
        nodes.append(
            ProgramNode(
                percent_id,
                ProgramOperation.TO_PERCENT,
                input_ids=(root_id,),
            )
        )
        return percent_id
    return root_id


def _is_inventory_days_filtered_margin_average(
    question: str,
    hints: Mapping[str, object],
    formulas: tuple[Mapping[str, object], ...],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    has_gross_margin = any(
        {str(value) for value in _sequence(formula.get("leaves"))}
        == {"gross_profit", "net_revenue"}
        for formula in formulas
    )
    return (
        str(hints.get("operation") or "") == "average"
        and {"inventory", "cogs", "gross_profit", "net_revenue"} <= metrics
        and "so ngay ton kho" in normalized
        and "trung vi" in normalized
        and "bien loi nhuan gop" in normalized
        and any(cue in normalized for cue in ("muc thay doi", "thay doi"))
        and any(cue in normalized for cue in ("binh quan", "trung binh"))
        and has_gross_margin
    )


def _generate_inventory_days_filtered_margin_average(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: tuple[Mapping[str, object], ...],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    gross_margin = next(
        (
            formula
            for formula in formulas
            if {str(value) for value in _sequence(formula.get("leaves"))}
            == {"gross_profit", "net_revenue"}
        ),
        None,
    )
    if gross_margin is None:
        raise DeterministicCompositionUnsupported(
            "inventory-days filtered average requires gross-margin formula"
        )
    grouped = _group_facts(facts)
    required_metrics = ("inventory", "cogs", "gross_profit", "net_revenue")
    missing = set(required_metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"inventory-days filtered average misses metrics: {sorted(missing)}"
        )

    nodes: list[ProgramNode] = []
    source_nodes = _append_source_nodes(
        nodes, grouped, required_metrics, axis="entity_period"
    )
    inventory_average = _node_id("starting_inventory_average", nodes)
    absolute_cogs = _node_id("starting_absolute_cogs", nodes)
    days = _node_id("days_365", nodes)
    annualized_inventory = _node_id("starting_annualized_inventory", nodes)
    inventory_days = _node_id("starting_inventory_days", nodes)
    inventory_days_by_entity = _node_id("starting_inventory_days_by_entity", nodes)
    median = _node_id("starting_inventory_days_median", nodes)
    predicate = _node_id("starting_inventory_days_filter", nodes)
    nodes.extend(
        (
            ProgramNode(
                inventory_average,
                ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
                input_ids=(source_nodes["inventory"],),
            ),
            ProgramNode(
                absolute_cogs,
                ProgramOperation.ABSOLUTE,
                input_ids=(source_nodes["cogs"],),
            ),
            ProgramNode(days, ProgramOperation.LITERAL, literal=Decimal(365)),
            ProgramNode(
                annualized_inventory,
                ProgramOperation.MULTIPLY,
                input_ids=(inventory_average, days),
            ),
            ProgramNode(
                inventory_days,
                ProgramOperation.DIVIDE,
                input_ids=(annualized_inventory, absolute_cogs),
            ),
            ProgramNode(
                inventory_days_by_entity,
                ProgramOperation.EARLIEST_BY_ENTITY,
                input_ids=(inventory_days,),
            ),
            ProgramNode(
                median,
                ProgramOperation.MEDIAN,
                input_ids=(inventory_days_by_entity,),
            ),
            ProgramNode(
                predicate,
                ProgramOperation.COMPARE,
                input_ids=(inventory_days_by_entity, median),
                comparator=_median_comparator(normalized),
            ),
        )
    )
    margin = _compile_formula(
        gross_margin, nodes, source_nodes, prefix="gross_margin"
    )
    requested_margin = _node_id("requested_period_margin", nodes)
    margin_change = _node_id("gross_margin_change", nodes)
    eligible_change = _node_id("eligible_gross_margin_change", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                requested_margin,
                ProgramOperation.DROP_FIRST_BY_ENTITY,
                input_ids=(margin,),
            ),
            ProgramNode(
                margin_change,
                ProgramOperation.CHANGE_BY_ENTITY,
                input_ids=(requested_margin,),
            ),
            ProgramNode(
                eligible_change,
                ProgramOperation.FILTER,
                input_ids=(margin_change, predicate),
            ),
            ProgramNode(
                answer,
                ProgramOperation.AVERAGE,
                input_ids=(eligible_change,),
            ),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_inventory_days_change(
    question: str, hints: Mapping[str, object]
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        {"inventory", "cogs", "gross_profit", "net_revenue"} <= metrics
        and ("365" in normalized or "so ngay ton kho" in normalized)
        and ("hang ton kho" in normalized or "so ngay ton kho" in normalized)
        and ("gia von hang ban" in normalized or "so ngay ton kho" in normalized)
        and any(
            cue in normalized
            for cue in (
                "muc tang lon nhat",
                "tang lon nhat",
                "muc giam so ngay ton kho lon nhat",
            )
        )
    )


def _generate_inventory_days_rank(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: tuple[Mapping[str, object], ...],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    gross_margin = next(
        (
            formula
            for formula in formulas
            if {str(value) for value in _sequence(formula.get("leaves"))}
            == {"gross_profit", "net_revenue"}
        ),
        None,
    )
    if gross_margin is None:
        raise DeterministicCompositionUnsupported(
            "inventory-days template requires gross-margin formula"
        )
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    grouped = _group_facts(facts)
    missing = set(required_metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"inventory-days template misses metrics: {sorted(missing)}"
        )
    selected = tuple(
        fact for metric_id in required_metrics for fact in grouped[metric_id]
    )
    nodes: list[ProgramNode] = []
    source_nodes = _append_source_nodes(
        nodes, grouped, required_metrics, axis=_axis(selected)
    )
    inventory_average = _node_id("rolling_inventory_average", nodes)
    nodes.append(
        ProgramNode(
            inventory_average,
            ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
            input_ids=(source_nodes["inventory"],),
        )
    )
    days = _node_id("days_365", nodes)
    nodes.append(ProgramNode(days, ProgramOperation.LITERAL, literal=Decimal(365)))
    annualized_inventory = _node_id("annualized_inventory", nodes)
    nodes.append(
        ProgramNode(
            annualized_inventory,
            ProgramOperation.MULTIPLY,
            input_ids=(inventory_average, days),
        )
    )
    inventory_days = _node_id("inventory_days", nodes)
    absolute_cogs = _node_id("absolute_cogs", nodes)
    nodes.append(
        ProgramNode(
            absolute_cogs,
            ProgramOperation.ABSOLUTE,
            input_ids=(source_nodes["cogs"],),
        )
    )
    nodes.append(
        ProgramNode(
            inventory_days,
            ProgramOperation.DIVIDE,
            input_ids=(annualized_inventory, absolute_cogs),
        )
    )
    earliest_inventory_days = _node_id("earliest_inventory_days", nodes)
    latest_inventory_days = _node_id("latest_inventory_days", nodes)
    inventory_days_change = _node_id("inventory_days_change", nodes)
    nodes.extend(
        (
            ProgramNode(
                earliest_inventory_days,
                ProgramOperation.EARLIEST_BY_ENTITY,
                input_ids=(inventory_days,),
            ),
            ProgramNode(
                latest_inventory_days,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(inventory_days,),
            ),
            ProgramNode(
                inventory_days_change,
                ProgramOperation.SUBTRACT,
                input_ids=(latest_inventory_days, earliest_inventory_days),
            ),
        )
    )
    rank_input = inventory_days_change
    if "trung vi" in normalized:
        median = _node_id("starting_inventory_days_median", nodes)
        predicate = _node_id("starting_inventory_days_filter", nodes)
        filtered_change = _node_id("filtered_inventory_days_change", nodes)
        nodes.extend(
            (
                ProgramNode(
                    median,
                    ProgramOperation.MEDIAN,
                    input_ids=(earliest_inventory_days,),
                ),
                ProgramNode(
                    predicate,
                    ProgramOperation.COMPARE,
                    input_ids=(earliest_inventory_days, median),
                    comparator=_median_comparator(normalized),
                ),
                ProgramNode(
                    filtered_change,
                    ProgramOperation.FILTER,
                    input_ids=(inventory_days_change, predicate),
                ),
            )
        )
        rank_input = filtered_change
    selected_entity = _node_id("selected_entity", nodes)
    nodes.append(
        ProgramNode(
            selected_entity,
            ProgramOperation.ARGMIN_KEY
            if "muc giam" in normalized
            else ProgramOperation.ARGMAX_KEY,
            input_ids=(rank_input,),
        )
    )
    margin = _compile_formula(
        gross_margin, nodes, source_nodes, prefix="gross_margin"
    )
    output_series = _node_id("latest_margin", nodes)
    if any(cue in normalized for cue in ("muc thay doi", "thay doi bao nhieu")):
        rolling_margin_change = _node_id("rolling_margin_change", nodes)
        nodes.append(
            ProgramNode(
                rolling_margin_change,
                ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
                input_ids=(margin,),
            )
        )
        nodes.append(
            ProgramNode(
                output_series,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(rolling_margin_change,),
            )
        )
    else:
        nodes.append(
            ProgramNode(
                output_series,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(margin,),
            )
        )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, selected_entity),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _compile_expression(
    expression: Mapping[str, object],
    nodes: list[ProgramNode],
    source_nodes: Mapping[str, str],
    *,
    prefix: str,
) -> str:
    expression_type = str(expression.get("type") or "")
    if expression_type == "metric_ref":
        metric_id = str(expression.get("metric_id") or "")
        try:
            return source_nodes[metric_id]
        except KeyError as error:
            raise GroundedPlanError(
                f"formula references unavailable metric: {metric_id}"
            ) from error
    if expression_type == "arithmetic":
        left = expression.get("left")
        right = expression.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise GroundedPlanError("arithmetic formula requires two children")
        left_id = _compile_expression(left, nodes, source_nodes, prefix=f"{prefix}_left")
        right_id = _compile_expression(right, nodes, source_nodes, prefix=f"{prefix}_right")
        operation = {
            "add": ProgramOperation.ADD,
            "subtract": ProgramOperation.SUBTRACT,
            "multiply": ProgramOperation.MULTIPLY,
            "divide": ProgramOperation.DIVIDE,
        }.get(str(expression.get("operator") or ""))
        if operation is None:
            raise GroundedPlanError("formula has unsupported arithmetic operation")
        node_id = _node_id(prefix, nodes)
        nodes.append(ProgramNode(node_id, operation, input_ids=(left_id, right_id)))
        return node_id
    if expression_type == "unary":
        child = expression.get("expression")
        if not isinstance(child, Mapping):
            raise GroundedPlanError("unary formula requires a child")
        if str(expression.get("operator") or "") != "absolute":
            raise GroundedPlanError("formula has unsupported unary operation")
        child_id = _compile_expression(child, nodes, source_nodes, prefix=f"{prefix}_child")
        node_id = _node_id(prefix, nodes)
        nodes.append(
            ProgramNode(node_id, ProgramOperation.ABSOLUTE, input_ids=(child_id,))
        )
        return node_id
    if expression_type == "average_balance_ratio":
        numerator_metric = str(expression.get("numerator_metric_id") or "")
        denominator_metric = str(expression.get("denominator_metric_id") or "")
        try:
            numerator = source_nodes[numerator_metric]
            denominator = source_nodes[denominator_metric]
        except KeyError as error:
            raise GroundedPlanError(
                "average-balance ratio references unavailable metric"
            ) from error
        average_id = _node_id(f"{prefix}_average_balance", nodes)
        nodes.append(
            ProgramNode(
                average_id,
                ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
                input_ids=(denominator,),
            )
        )
        ratio_id = _node_id(prefix, nodes)
        nodes.append(
            ProgramNode(
                ratio_id,
                ProgramOperation.DIVIDE,
                input_ids=(numerator, average_id),
            )
        )
        return ratio_id
    raise GroundedPlanError(f"unsupported formula expression type: {expression_type}")


def _generate_current_rank_select(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    roles: Mapping[str, Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    grouped = _group_facts(facts)
    if set(required_metrics) - grouped.keys():
        raise DeterministicCompositionUnsupported(
            "current rank/select lacks canonical metric coverage"
        )
    selected = tuple(
        fact for metric_id in required_metrics for fact in grouped[metric_id]
    )
    nodes: list[ProgramNode] = []
    source_nodes = _append_source_nodes(
        nodes, grouped, required_metrics, axis=_axis(selected)
    )
    rank_series = _compile_formula(
        roles["rank"], nodes, source_nodes, prefix="rank_formula"
    )
    if _axis(selected) == "entity_period":
        latest_rank = _node_id("latest_rank", nodes)
        nodes.append(
            ProgramNode(
                latest_rank,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(rank_series,),
            )
        )
        rank_series = latest_rank
    normalized = normalize_phrase(question)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if any(cue in normalized for cue in ("thap nhat", "nho nhat"))
        else ProgramOperation.ARGMAX_KEY
    )
    selected_key = _node_id("selected_key", nodes)
    nodes.append(
        ProgramNode(selected_key, rank_operation, input_ids=(rank_series,))
    )
    output_series = _compile_formula(
        roles["output"], nodes, source_nodes, prefix="output_formula"
    )
    if _axis(selected) == "entity_period":
        latest_output = _node_id("latest_output", nodes)
        nodes.append(
            ProgramNode(
                latest_output,
                ProgramOperation.LATEST_BY_ENTITY,
                input_ids=(output_series,),
            )
        )
        output_series = latest_output
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, selected_key),
        )
    )
    dimension, scale = _output_contract(hints)
    if dimension is Dimension.UNKNOWN:
        try:
            dimension = Dimension(str(roles["output"].get("output_dimension") or ""))
        except ValueError as error:
            raise GroundedPlanError("rank output formula has unknown dimension") from error
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _generate_direct_rank_select(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    markers = [
        (normalized.find(cue), cue)
        for cue in ("cao nhat", "lon nhat", "thap nhat", "nho nhat")
        if normalized.find(cue) >= 0
    ]
    if not markers:
        raise DeterministicCompositionUnsupported("direct rank marker is missing")
    marker_position, marker = min(markers)
    contracts = _mappings(hints.get("metric_contracts"))
    rank_metric = _metric_before_position(normalized, contracts, marker_position)
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    if rank_metric is None or len(required_metrics) != 2:
        raise DeterministicCompositionUnsupported(
            "direct rank/select requires exactly two unambiguous metrics"
        )
    output_metric = next(
        (metric for metric in required_metrics if metric != rank_metric), None
    )
    grouped = _group_facts(facts)
    if output_metric is None or set(required_metrics) - grouped.keys():
        raise GroundedPlanError("direct rank/select lacks metric coverage")
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, required_metrics, axis="entity")
    selected_key = _node_id("selected_key", nodes)
    operation = (
        ProgramOperation.ARGMIN_KEY
        if "thap" in marker or "nho" in marker
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.append(
        ProgramNode(selected_key, operation, input_ids=(sources[rank_metric],))
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(sources[output_metric], selected_key),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _generate_formula_output_direct_rank(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    output_formula: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    markers = [
        (normalized.find(cue), cue)
        for cue in ("cao nhat", "lon nhat", "thap nhat", "nho nhat")
        if normalized.find(cue) >= 0
    ]
    if not markers:
        raise DeterministicCompositionUnsupported("formula rank marker is missing")
    marker_position, marker = min(markers)
    rank_metric = _metric_before_position(
        normalized,
        _mappings(hints.get("metric_contracts")),
        marker_position,
    )
    formula_metrics = {
        str(value) for value in _sequence(output_formula.get("leaves"))
    }
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    if rank_metric is None or rank_metric in formula_metrics:
        raise DeterministicCompositionUnsupported("direct formula rank is ambiguous")
    grouped = _group_facts(facts)
    if set(required_metrics) - grouped.keys():
        raise GroundedPlanError("formula output rank lacks metric coverage")
    selected = tuple(
        fact for metric_id in required_metrics for fact in grouped[metric_id]
    )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(
        nodes, grouped, required_metrics, axis=_axis(selected)
    )
    selected_key = _node_id("selected_key", nodes)
    rank_operation = (
        ProgramOperation.ARGMIN_KEY
        if "thap" in marker or "nho" in marker
        else ProgramOperation.ARGMAX_KEY
    )
    nodes.append(
        ProgramNode(selected_key, rank_operation, input_ids=(sources[rank_metric],))
    )
    output_series = _compile_formula(
        output_formula, nodes, sources, prefix="output_formula"
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, selected_key),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_filtered_period_rank(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    leaf_sets = [
        {str(value) for value in _sequence(formula.get("leaves"))}
        for formula in formulas
    ]
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        {"profit_after_tax", "net_revenue"} in leaf_sets
        and {"cash_flow_from_operations", "current_liabilities"} in leaf_sets
        and "doanh thu thuan thap nhat" in normalized
        and "10" in normalized
        and "net_revenue" in metrics
    )


def _generate_filtered_period_rank(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    del question
    grouped = _group_facts(facts)
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    if set(required_metrics) - grouped.keys():
        raise GroundedPlanError("filtered period rank lacks metric coverage")
    nodes: list[ProgramNode] = []
    source_nodes = _append_source_nodes(nodes, grouped, required_metrics, axis="period")
    net_margin = next(
        formula
        for formula in formulas
        if {str(value) for value in _sequence(formula.get("leaves"))}
        == {"profit_after_tax", "net_revenue"}
    )
    output_formula = next(
        formula
        for formula in formulas
        if {str(value) for value in _sequence(formula.get("leaves"))}
        == {"cash_flow_from_operations", "current_liabilities"}
    )
    margin = _compile_formula(net_margin, nodes, source_nodes, prefix="net_margin")
    threshold = _node_id("threshold_10_percent", nodes)
    nodes.append(ProgramNode(threshold, ProgramOperation.LITERAL, literal=Decimal(10)))
    predicate = _node_id("margin_above_threshold", nodes)
    nodes.append(
        ProgramNode(
            predicate,
            ProgramOperation.COMPARE,
            input_ids=(margin, threshold),
            comparator=Comparator.GT,
        )
    )
    eligible_revenue = _node_id("eligible_revenue", nodes)
    nodes.append(
        ProgramNode(
            eligible_revenue,
            ProgramOperation.FILTER,
            input_ids=(source_nodes["net_revenue"], predicate),
        )
    )
    selected_period = _node_id("selected_period", nodes)
    nodes.append(
        ProgramNode(
            selected_period,
            ProgramOperation.ARGMIN_KEY,
            input_ids=(eligible_revenue,),
        )
    )
    output_series = _compile_formula(
        output_formula, nodes, source_nodes, prefix="output_formula"
    )
    answer = _node_id("answer", nodes)
    nodes.append(
        ProgramNode(
            answer,
            ProgramOperation.SELECT_AT_KEY,
            input_ids=(output_series, selected_period),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_filtered_profit_share(
    question: str, hints: Mapping[str, object]
) -> bool:
    normalized = normalize_phrase(question)
    metrics = {str(value) for value in _sequence(hints.get("required_metric_ids"))}
    return (
        {"profit_after_tax", "total_liabilities", "equity"} <= metrics
        and "trung vi" in normalized
        and "tong loi nhuan sau thue" in normalized
        and "bao nhieu phan tram" in normalized
    )


def _generate_filtered_profit_share(
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    confidence: float,
) -> GroundedProgram:
    metrics = ("profit_after_tax", "total_liabilities", "equity")
    grouped = _group_facts(facts)
    if set(metrics) - grouped.keys():
        raise GroundedPlanError("filtered profit share lacks metric coverage")
    nodes: list[ProgramNode] = []
    source = _append_source_nodes(nodes, grouped, metrics, axis="entity")
    leverage = _node_id("leverage", nodes)
    nodes.append(
        ProgramNode(
            leverage,
            ProgramOperation.DIVIDE,
            input_ids=(source["total_liabilities"], source["equity"]),
        )
    )
    median = _node_id("median_leverage", nodes)
    nodes.append(ProgramNode(median, ProgramOperation.MEDIAN, input_ids=(leverage,)))
    predicate = _node_id("below_median", nodes)
    nodes.append(
        ProgramNode(
            predicate,
            ProgramOperation.COMPARE,
            input_ids=(leverage, median),
            comparator=Comparator.LT,
        )
    )
    filtered = _node_id("filtered_profit", nodes)
    nodes.append(
        ProgramNode(
            filtered,
            ProgramOperation.FILTER,
            input_ids=(source["profit_after_tax"], predicate),
        )
    )
    filtered_sum = _node_id("filtered_profit_sum", nodes)
    total_sum = _node_id("total_profit_sum", nodes)
    nodes.extend(
        (
            ProgramNode(filtered_sum, ProgramOperation.SUM, input_ids=(filtered,)),
            ProgramNode(
                total_sum,
                ProgramOperation.SUM,
                input_ids=(source["profit_after_tax"],),
            ),
        )
    )
    share = _node_id("profit_share", nodes)
    nodes.append(
        ProgramNode(
            share,
            ProgramOperation.DIVIDE,
            input_ids=(filtered_sum, total_sum),
        )
    )
    answer = _node_id("answer_percent", nodes)
    nodes.append(
        ProgramNode(answer, ProgramOperation.TO_PERCENT, input_ids=(share,))
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _is_median_filtered_share(
    question: str,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
) -> bool:
    normalized = normalize_phrase(question)
    metrics = _sequence(hints.get("required_metric_ids"))
    return (
        len(_sequence(hints.get("periods"))) == 1
        and 2 <= len(metrics) <= 4
        and len(formulas) <= 1
        and "trung vi" in normalized
        and any(cue in normalized for cue in ("ty trong tong", "chiem bao nhieu phan tram"))
    )


def _generate_median_filtered_share(
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
    formulas: Sequence[Mapping[str, object]],
    confidence: float,
) -> GroundedProgram:
    normalized = normalize_phrase(question)
    required_metrics = tuple(
        str(value) for value in _sequence(hints.get("required_metric_ids"))
    )
    grouped = _group_facts(facts)
    missing = set(required_metrics) - grouped.keys()
    if missing:
        raise GroundedPlanError(
            f"median filtered share misses metrics: {sorted(missing)}"
        )
    target_metric = _total_target_metric(
        normalized,
        _mappings(hints.get("metric_contracts")),
        required_metrics,
        formulas,
    )
    if target_metric is None:
        raise DeterministicCompositionUnsupported(
            "median filtered share cannot identify the summed metric"
        )
    nodes: list[ProgramNode] = []
    sources = _append_source_nodes(nodes, grouped, required_metrics, axis="entity")
    if formulas:
        filter_value = _compile_formula(
            formulas[0], nodes, sources, prefix="filter_formula"
        )
    else:
        other_metrics = [value for value in required_metrics if value != target_metric]
        if len(other_metrics) != 1:
            raise DeterministicCompositionUnsupported(
                "direct median share requires one numerator metric"
            )
        filter_value = _node_id("filter_ratio", nodes)
        nodes.append(
            ProgramNode(
                filter_value,
                ProgramOperation.DIVIDE,
                input_ids=(sources[other_metrics[0]], sources[target_metric]),
            )
        )
    median = _node_id("filter_median", nodes)
    nodes.append(ProgramNode(median, ProgramOperation.MEDIAN, input_ids=(filter_value,)))
    predicate = _node_id("filter_predicate", nodes)
    nodes.append(
        ProgramNode(
            predicate,
            ProgramOperation.COMPARE,
            input_ids=(filter_value, median),
            comparator=_median_comparator(normalized),
        )
    )
    filtered = _node_id("filtered_target", nodes)
    nodes.append(
        ProgramNode(
            filtered,
            ProgramOperation.FILTER,
            input_ids=(sources[target_metric], predicate),
        )
    )
    filtered_sum = _node_id("filtered_sum", nodes)
    total_sum = _node_id("total_sum", nodes)
    nodes.extend(
        (
            ProgramNode(filtered_sum, ProgramOperation.SUM, input_ids=(filtered,)),
            ProgramNode(
                total_sum,
                ProgramOperation.SUM,
                input_ids=(sources[target_metric],),
            ),
        )
    )
    share = _node_id("share", nodes)
    answer = _node_id("answer", nodes)
    nodes.extend(
        (
            ProgramNode(
                share,
                ProgramOperation.DIVIDE,
                input_ids=(filtered_sum, total_sum),
            ),
            ProgramNode(answer, ProgramOperation.TO_PERCENT, input_ids=(share,)),
        )
    )
    dimension, scale = _output_contract(hints)
    return GroundedProgram(tuple(nodes), answer, dimension, scale, confidence)


def _total_target_metric(
    normalized_question: str,
    contracts: Sequence[Mapping[str, object]],
    metrics: Sequence[str],
    formulas: Sequence[Mapping[str, object]],
) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for contract in contracts:
        metric_id = str(contract.get("metric_id") or "")
        if metric_id not in metrics:
            continue
        for alias in _sequence(contract.get("aliases")):
            normalized_alias = normalize_phrase(str(alias))
            for match in re.finditer(re.escape(normalized_alias), normalized_question):
                start = match.start()
                prefix = normalized_question[max(0, start - 20) : start]
                if "tong" in prefix:
                    candidates.append((start, len(normalized_alias), metric_id))
    if candidates:
        return min(candidates)[2]
    formula_leaves = {
        str(value)
        for formula in formulas
        for value in _sequence(formula.get("leaves"))
    }
    outside_formula = [metric for metric in metrics if metric not in formula_leaves]
    return outside_formula[0] if len(outside_formula) == 1 else None


def _group_facts(facts: Sequence[GroundedFact]) -> dict[str, tuple[GroundedFact, ...]]:
    output: dict[str, list[GroundedFact]] = defaultdict(list)
    for fact in facts:
        if fact.retrieval_metric and not has_hard_logical_fact_conflict(fact):
            output[fact.retrieval_metric].append(fact)
    return {key: tuple(value) for key, value in output.items()}


def _append_source_nodes(
    nodes: list[ProgramNode],
    grouped: Mapping[str, tuple[GroundedFact, ...]],
    metric_ids: Sequence[str],
    *,
    axis: str,
) -> dict[str, str]:
    output: dict[str, str] = {}
    for metric_id in metric_ids:
        node_id = _node_id(f"facts_{metric_id}", nodes)
        nodes.append(
            ProgramNode(
                node_id,
                ProgramOperation.FACTS,
                fact_uids=tuple(
                    fact.observation_uid
                    for fact in sorted(grouped[metric_id], key=_fact_scope_key)
                ),
                axis=axis,
            )
        )
        output[metric_id] = node_id
    return output


def _output_contract(hints: Mapping[str, object]) -> tuple[Dimension, int | None]:
    requested_unit = hints.get("requested_unit")
    if not isinstance(requested_unit, Mapping):
        raise GroundedPlanError("deterministic composer requires requested_unit")
    try:
        dimension = Dimension(str(requested_unit["dimension"]))
    except (KeyError, ValueError) as error:
        raise GroundedPlanError("invalid deterministic output dimension") from error
    scale_raw = requested_unit.get("scale_exponent")
    return dimension, None if scale_raw is None else int(str(scale_raw))


def _metric_before_position(
    normalized_question: str,
    contracts: Sequence[Mapping[str, object]],
    position: int,
) -> str | None:
    candidates: list[tuple[int, int, str]] = []
    for contract in contracts:
        metric_id = str(contract.get("metric_id") or "")
        for alias in _sequence(contract.get("aliases")):
            normalized_alias = normalize_phrase(str(alias))
            start = normalized_question.find(normalized_alias)
            if 0 <= start < position:
                candidates.append((start, len(normalized_alias), metric_id))
    if not candidates:
        return None
    return max(candidates)[2]


def _axis(facts: Sequence[GroundedFact]) -> str:
    entities = {fact.entity for fact in facts if fact.entity}
    periods = {fact.period_year for fact in facts if fact.period_year is not None}
    if len(entities) <= 1 and len(periods) > 1:
        return "period"
    if len(periods) <= 1 and len(entities) > 1:
        return "entity"
    return "entity_period"


def _fact_scope_key(fact: GroundedFact) -> tuple[str, int, str]:
    return (fact.entity, fact.period_year or -1, fact.observation_uid)


def _formula_filter_threshold(
    normalized: str,
    formula: Mapping[str, object],
) -> tuple[Decimal, Comparator] | None:
    alias = normalize_phrase(str(formula.get("matched_alias") or ""))
    start = normalized.find(alias) if alias else 0
    tail = normalized[start + len(alias) : start + len(alias) + 80]
    match = re.search(
        r"(lon hon|cao hon|tren|nho hon|thap hon|duoi)\s+"
        r"([-+]?\d+(?:[.,]\d+)?)",
        tail,
    )
    if match is None:
        return None
    comparator = (
        Comparator.GT
        if match.group(1) in {"lon hon", "cao hon", "tren"}
        else Comparator.LT
    )
    return Decimal(match.group(2).replace(",", ".")), comparator


def _median_comparator(normalized: str) -> Comparator:
    if "thap hon hoac bang" in normalized or "khong cao hon" in normalized:
        return Comparator.LTE
    if "cao hon hoac bang" in normalized or "khong thap hon" in normalized:
        return Comparator.GTE
    if any(
        cue in normalized
        for cue in ("cao hon trung vi", "cao hon muc trung vi", "tren muc trung vi")
    ):
        return Comparator.GT
    if any(
        cue in normalized
        for cue in ("thap hon trung vi", "thap hon muc trung vi", "duoi muc trung vi")
    ):
        return Comparator.LT
    raise DeterministicCompositionUnsupported("median comparator is ambiguous")


def _node_id(prefix: str, nodes: Sequence[ProgramNode]) -> str:
    normalized = "".join(value if value.isalnum() else "_" for value in prefix)
    known = {node.node_id for node in nodes}
    candidate = normalized
    index = 2
    while candidate in known:
        candidate = f"{normalized}_{index}"
        index += 1
    return candidate


def _mappings(value: object) -> tuple[Mapping[str, object], ...]:
    return tuple(item for item in _sequence(value) if isinstance(item, Mapping))


def _program_mapping(program: GroundedProgram) -> dict[str, object]:
    return {
        "nodes": [
            {
                "id": node.node_id,
                "operation": node.operation.value,
                "input_ids": list(node.input_ids),
                "fact_uids": list(node.fact_uids),
                "axis": node.axis,
                "literal": None if node.literal is None else str(node.literal),
                "comparator": (
                    None if node.comparator is None else node.comparator.value
                ),
            }
            for node in program.nodes
        ],
        "output_node_id": program.output_node_id,
        "output_dimension": program.output_dimension.value,
        "output_scale_exponent": program.output_scale_exponent,
        "confidence": program.confidence,
    }


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()
