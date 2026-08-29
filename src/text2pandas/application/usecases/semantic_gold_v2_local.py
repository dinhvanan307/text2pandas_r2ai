"""Local-only synthetic Semantic Gold v2 generation and evaluation.

This use case exists to validate the Phase 1.5 plumbing without pretending
that automated labels are independent or human reviewed.  It imports only
public, pre-binding semantic functions.  It never reads retrieval candidates,
answers, evidence, or a production gold registry.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from text2pandas.application.usecases.semantic_gold_v2 import (
    SEMANTIC_COMPONENT_FIELDS,
    canonical_semantic_frame,
    validate_annotation_record,
)
from text2pandas.pipelines.answering.adapters import requested_unit_of
from text2pandas.pipelines.answering.count_engine import classify_count_predicate
from text2pandas.pipelines.answering.entity_average import is_typed_entity_average
from text2pandas.pipelines.answering.entity_count import classify_entity_count
from text2pandas.pipelines.answering.entity_difference import (
    is_typed_entity_difference,
)
from text2pandas.pipelines.answering.entity_sum import is_typed_entity_sum
from text2pandas.pipelines.answering.formula_engine import match_formula
from text2pandas.pipelines.answering.frame import (
    COUNT_OP,
    EXTREMUM,
    RANK_MIN,
    RETURN_FILTERED_VALUE,
    RETURN_PERIOD,
    RETURN_SELECT_AT_ARG,
    classify_operation,
    parse_question,
)
from text2pandas.pipelines.answering.router import route
from text2pandas.pipelines.retrieval.metric_hint import (
    metric_codes_hint,
    statement_hint,
)
from text2pandas.pipelines.retrieval.question_intent import Intent, parse_intent

LOCAL_SYNTHETIC = "LOCAL_SYNTHETIC"
LOCAL_PROVENANCE: dict[str, object] = {
    "gold_mode": LOCAL_SYNTHETIC,
    "annotation_source": "AUTOMATED",
    "independent_review": False,
    "human_adjudication": False,
    "official_submission_ready": False,
}

METRIC_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("Entity Reference Accuracy", "entities"),
    ("Metric Phrase Exact Match", "metrics"),
    ("Metric Concept Accuracy", "metrics"),
    ("Period Exact Match", "periods"),
    ("Period Role Accuracy", "periods"),
    ("Basis Accuracy", "basis"),
    ("Unit Accuracy", "unit"),
    ("Operation Accuracy", "operation_tree"),
    ("Result Kind Accuracy", "output"),
    ("Operand Count Accuracy", "operands"),
    ("Operand Role Accuracy", "operands"),
    ("Operand Metric Accuracy", "operands"),
    ("Operand Role+Metric Accuracy", "operands"),
    ("Full Semantic Frame Exact", "full_frame"),
)

_ROLE_BY_OPERATION: dict[str, tuple[str, ...]] = {
    "LOOKUP": ("VALUE",),
    "DIVIDE": ("NUMERATOR", "DENOMINATOR"),
    "SUBTRACT": ("MINUEND", "SUBTRAHEND"),
    "GROWTH": ("NEW", "OLD"),
}
_VARIADIC_ROLE: dict[str, str] = {
    "SUM": "SUMMAND",
    "AVERAGE": "SUMMAND",
    "MINIMUM": "VALUE",
    "MAXIMUM": "VALUE",
    "ARGMIN": "RANK_KEY",
    "ARGMAX": "RANK_KEY",
    "COUNT": "FILTER_OPERAND",
}
_OPERATION_NAME = {"AVG": "AVERAGE", COUNT_OP: "COUNT"}


@dataclass(frozen=True, slots=True)
class LocalObservation:
    annotation: dict[str, object]
    prediction_source: dict[str, str]
    route_status: str
    route_reason: str | None


class LocalSchemaValidationError(ValueError):
    """A generated record violates the tracked Semantic Gold v2 JSON Schema."""


def validate_json_schema_instance(
    instance: object, schema: Mapping[str, object]
) -> None:
    """Validate the exact JSON-Schema subset used by Semantic Gold v2.

    Supported Draft 2020-12 keywords are deliberately explicit: local ``$ref``,
    ``type``, ``const``, ``enum``, object/array/string/number constraints,
    ``anyOf``, ``allOf`` and ``if``/``then``/``else``.  An unknown validation
    keyword fails closed so schema growth cannot silently bypass this gate.
    """

    errors: list[str] = []
    _validate_schema_node(instance, schema, schema, "$", errors)
    if errors:
        raise LocalSchemaValidationError(errors[0])


def _validate_schema_node(
    instance: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    known = {
        "$schema",
        "$id",
        "$defs",
        "$ref",
        "title",
        "type",
        "const",
        "enum",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "uniqueItems",
        "pattern",
        "minLength",
        "minimum",
        "maximum",
        "anyOf",
        "allOf",
        "if",
        "then",
        "else",
    }
    unknown = set(schema) - known
    if unknown:
        errors.append(f"{path}: unsupported schema keywords {sorted(unknown)}")
        return
    reference = schema.get("$ref")
    if reference is not None:
        target = _resolve_local_ref(root, str(reference))
        _validate_schema_node(instance, target, root, path, errors)
        return

    raw_any = schema.get("anyOf")
    if raw_any is not None:
        branches = _schema_rows(raw_any, f"{path}.anyOf")
        if not any(_schema_matches(instance, branch, root, path) for branch in branches):
            errors.append(f"{path}: value does not match anyOf")
            return
    raw_all = schema.get("allOf")
    if raw_all is not None:
        for branch in _schema_rows(raw_all, f"{path}.allOf"):
            _validate_schema_node(instance, branch, root, path, errors)
            if errors:
                return
    raw_if = schema.get("if")
    if raw_if is not None:
        condition = _mapping(raw_if, f"{path}.if")
        branch_name = "then" if _schema_matches(instance, condition, root, path) else "else"
        raw_branch = schema.get(branch_name)
        if raw_branch is not None:
            _validate_schema_node(
                instance,
                _mapping(raw_branch, f"{path}.{branch_name}"),
                root,
                path,
                errors,
            )
            if errors:
                return

    raw_type = schema.get("type")
    if raw_type is not None:
        allowed_types = (
            [str(value) for value in _sequence(raw_type, f"{path}.type")]
            if not isinstance(raw_type, str)
            else [raw_type]
        )
        if not any(_json_type(instance, expected) for expected in allowed_types):
            errors.append(f"{path}: expected type {allowed_types}, found {type(instance).__name__}")
            return
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
        return
    raw_enum = schema.get("enum")
    if raw_enum is not None and instance not in _sequence(raw_enum, f"{path}.enum"):
        errors.append(f"{path}: value {instance!r} is not in enum")
        return

    if isinstance(instance, Mapping):
        required = {
            str(value)
            for value in _sequence(schema.get("required", []), f"{path}.required")
        }
        missing = required - set(instance)
        if missing:
            errors.append(f"{path}: missing required properties {sorted(missing)}")
            return
        properties = _mapping(schema.get("properties", {}), f"{path}.properties")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            key_text = str(key)
            if key_text in properties:
                child_schema = _mapping(properties[key_text], f"{path}.{key_text} schema")
            elif additional is False:
                errors.append(f"{path}: additional property {key_text!r} is forbidden")
                return
            elif isinstance(additional, Mapping):
                child_schema = additional
            else:
                continue
            _validate_schema_node(value, child_schema, root, f"{path}.{key_text}", errors)
            if errors:
                return
    if isinstance(instance, Sequence) and not isinstance(instance, (str, bytes)):
        raw_items = schema.get("items")
        if raw_items is not None:
            item_schema = _mapping(raw_items, f"{path}.items")
            for index, item in enumerate(instance):
                _validate_schema_node(item, item_schema, root, f"{path}[{index}]", errors)
                if errors:
                    return
        if schema.get("uniqueItems") is True:
            encoded = [repr(_canonical_schema_value(value)) for value in instance]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: array values are not unique")
                return
    if isinstance(instance, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(instance) < minimum_length:
            errors.append(f"{path}: string is shorter than minLength={minimum_length}")
            return
        pattern = schema.get("pattern")
        if pattern is not None and re.search(str(pattern), instance) is None:
            errors.append(f"{path}: string does not match pattern {pattern!r}")
            return
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, (int, float)) and instance < minimum:
            errors.append(f"{path}: number is below minimum={minimum}")
            return
        if isinstance(maximum, (int, float)) and instance > maximum:
            errors.append(f"{path}: number is above maximum={maximum}")


def _schema_matches(
    instance: object,
    schema: Mapping[str, object],
    root: Mapping[str, object],
    path: str,
) -> bool:
    errors: list[str] = []
    _validate_schema_node(instance, schema, root, path, errors)
    return not errors


def _resolve_local_ref(
    root: Mapping[str, object], reference: str
) -> Mapping[str, object]:
    if not reference.startswith("#/"):
        raise LocalSchemaValidationError(f"only local JSON Schema refs are allowed: {reference}")
    current: object = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        current = _mapping(current, f"schema ref:{reference}").get(part)
        if current is None:
            raise LocalSchemaValidationError(f"unresolved JSON Schema ref: {reference}")
    return _mapping(current, f"schema ref:{reference}")


def _schema_rows(value: object, label: str) -> list[Mapping[str, object]]:
    return [_mapping(row, label) for row in _sequence(value, label)]


def _json_type(value: object, expected: str) -> bool:
    checks = {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "object": isinstance(value, Mapping),
        "array": isinstance(value, Sequence) and not isinstance(value, (str, bytes)),
    }
    if expected not in checks:
        raise LocalSchemaValidationError(f"unsupported JSON Schema type: {expected}")
    return checks[expected]


def _canonical_schema_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _canonical_schema_value(child))
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(_canonical_schema_value(child) for child in value)
    return value


def validate_local_provenance(provenance: Mapping[str, object]) -> None:
    """Require the five governance declarations verbatim and fail closed."""

    if dict(provenance) != LOCAL_PROVENANCE:
        raise ValueError(
            "LOCAL_SYNTHETIC provenance must exactly declare automated, "
            "non-independent, non-human, non-official origin"
        )


def metric_concept_ids(vocabulary: Mapping[str, object]) -> frozenset[str]:
    raw_concepts = vocabulary.get("concepts")
    if not isinstance(raw_concepts, Sequence) or isinstance(raw_concepts, str):
        raise TypeError("metric vocabulary concepts must be a list")
    ids: set[str] = set()
    for raw in raw_concepts:
        concept = _mapping(raw, "metric concept")
        concept_id = _text(concept.get("id"), "metric concept id")
        if concept_id in ids:
            raise ValueError(f"duplicate metric concept id: {concept_id}")
        ids.add(concept_id)
    return frozenset(ids)


def build_local_synthetic_annotation(
    selected: Mapping[str, object],
    *,
    aliases: Mapping[str, str | Sequence[str]],
    metric_vocabulary: Mapping[str, object],
    contract_hashes: Mapping[str, str],
) -> LocalObservation:
    """Create one deterministic automated reference annotation.

    Metric labels are admitted only when an exact NFC substring matches a
    frozen ontology inclusion example.  Unmatched fields remain UNRESOLVED.
    Other fields are observations from the active public pre-binding parser.
    """

    return _observe(
        selected,
        aliases=aliases,
        metric_vocabulary=metric_vocabulary,
        contract_hashes=contract_hashes,
        include_ontology_metric_labels=True,
    )


def export_canonical_v2_prediction(
    selected: Mapping[str, object],
    *,
    aliases: Mapping[str, str | Sequence[str]],
    metric_vocabulary: Mapping[str, object],
    contract_hashes: Mapping[str, str],
    implementation_fingerprint: str,
) -> dict[str, object]:
    """Export the honest Canonical V2 public pre-bind semantic observation.

    Canonical V2 does not expose a metric phrase/concept contract before
    binding.  The exporter therefore emits MISSING_OUTPUT for that field; it
    does not convert VAS hints or ontology matches into parser predictions.
    """

    observed = _observe(
        selected,
        aliases=aliases,
        metric_vocabulary=metric_vocabulary,
        contract_hashes=contract_hashes,
        include_ontology_metric_labels=False,
    )
    annotation = observed.annotation
    semantic = {
        field: deepcopy(annotation[field]) for field in SEMANTIC_COMPONENT_FIELDS
    }
    semantic.update(
        {
            "record_status": annotation["record_status"],
            "field_status": deepcopy(annotation["field_status"]),
        }
    )
    missing_fields = sorted(
        field
        for field, status in _mapping(
            annotation["field_status"], "prediction field status"
        ).items()
        if status not in {"RESOLVED", "NOT_APPLICABLE"}
    )
    return {
        "schema_version": 1,
        "qid": annotation["qid"],
        "question_sha256": annotation["question_sha256"],
        "cohort": annotation["cohort"],
        "primary_stratum": annotation.get("primary_stratum"),
        "prediction_status": (
            "COMPLETE" if not missing_fields else "PARTIAL_MISSING_OUTPUT"
        ),
        "prediction_source": observed.prediction_source,
        "route_status": observed.route_status,
        "route_reason": observed.route_reason,
        "vas_metric_code_hints": sorted(metric_codes_hint(str(annotation["question"]))),
        "statement_hint": statement_hint(str(annotation["question"])),
        "missing_fields": missing_fields,
        "implementation_fingerprint": implementation_fingerprint,
        "semantic": semantic,
        "canonical_frame": canonical_semantic_frame(annotation),
    }


def evaluate_local_predictions(
    annotations: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
    """Evaluate local synthetic references with the strict Phase 1.5 rules."""

    gold_by_qid = {_qid(row): row for row in annotations}
    prediction_by_qid = {_qid(row): row for row in predictions}
    if len(gold_by_qid) != len(annotations):
        raise ValueError("duplicate QID in local synthetic annotations")
    if len(prediction_by_qid) != len(predictions):
        raise ValueError("duplicate QID in parser predictions")
    if set(gold_by_qid) != set(prediction_by_qid):
        raise ValueError("annotation/prediction QID sets differ")

    cohorts = {
        "HEADLINE_CORE": sorted(
            qid
            for qid, row in gold_by_qid.items()
            if row.get("cohort") == "HEADLINE_CORE"
        ),
        "DIAGNOSTIC_SUPPLEMENT": sorted(
            qid
            for qid, row in gold_by_qid.items()
            if row.get("cohort") == "DIAGNOSTIC_SUPPLEMENT"
        ),
    }
    views = {
        cohort: _evaluate_qids(qids, gold_by_qid, prediction_by_qid)
        for cohort, qids in cohorts.items()
    }
    failures = _failure_rows(gold_by_qid, prediction_by_qid)
    status_distribution = Counter(str(row["record_status"]) for row in annotations)
    prediction_distribution = Counter(
        str(row["prediction_status"]) for row in predictions
    )
    field_status_distribution = {
        field: dict(
            sorted(
                Counter(
                    str(_mapping(row["field_status"], "field status")[field])
                    for row in annotations
                ).items()
            )
        )
        for field in SEMANTIC_COMPONENT_FIELDS
    }
    diagnostic_breakdown = _diagnostic_breakdown(
        cohorts["DIAGNOSTIC_SUPPLEMENT"], gold_by_qid, prediction_by_qid
    )
    boundary_counts = Counter(str(row["boundary"]) for row in failures)
    metrics: dict[str, object] = {
        "schema_version": 1,
        **LOCAL_PROVENANCE,
        "metric_scope": (
            "LOCAL_SYNTHETIC pipeline validation; not human-validated accuracy"
        ),
        "strict_scoring_rule": (
            "record_status=RESOLVED only; applicable missing prediction is wrong"
        ),
        "status_distribution": dict(sorted(status_distribution.items())),
        "field_status_distribution": field_status_distribution,
        "prediction_status_distribution": dict(
            sorted(prediction_distribution.items())
        ),
        "views": views,
        "diagnostic_strata": diagnostic_breakdown,
        "failure_summary": {
            "failed_qids": len(failures),
            "primary_failure_counts": dict(
                sorted(Counter(str(row["primary_failure"]) for row in failures).items())
            ),
            "boundary_counts": dict(sorted(boundary_counts.items())),
        },
        "resolver_and_downstream_accuracy": {
            "status": "NOT_MEASURABLE",
            "reason": (
                "no independent resolver/binding/answer/evidence reference exists "
                "in LOCAL_SYNTHETIC mode"
            ),
        },
    }
    return metrics, tuple(failures)


def _observe(
    selected: Mapping[str, object],
    *,
    aliases: Mapping[str, str | Sequence[str]],
    metric_vocabulary: Mapping[str, object],
    contract_hashes: Mapping[str, str],
    include_ontology_metric_labels: bool,
) -> LocalObservation:
    question = unicodedata.normalize("NFC", _text(selected.get("question"), "question"))
    qid = _qid(selected)
    intent = parse_intent(question, aliases)
    requested_unit = requested_unit_of(question)
    resolved_entity = intent.targets[0] if len(intent.targets) == 1 else None
    frame = parse_question(
        question,
        qid=qid,
        requested_unit=requested_unit,
        resolved_entity=resolved_entity,
    )

    entities, ticker_to_ref, entity_status = _entity_rows(question, intent, aliases)
    if include_ontology_metric_labels:
        metrics = _metric_rows(question, metric_vocabulary)
        metric_status = "RESOLVED" if metrics else "UNRESOLVED"
        metric_source = "frozen_ontology_exact_inclusion_example"
    else:
        metrics = []
        metric_status = "UNRESOLVED"
        metric_source = (
            "MISSING_OUTPUT:canonical_v2_has_no_public_prebind_metric_phrase_or_concept"
        )
    periods, period_to_ref = _period_rows(frame.periods, frame.operation.op)
    period_status = "RESOLVED" if periods else "UNRESOLVED"
    basis = _basis(frame.basis)
    unit, unit_status = _unit(requested_unit)

    node, route_status, route_reason, route_source = _operation(
        question, intent, frame
    )
    operation_status = "RESOLVED" if node != "OTHER" else "UNRESOLVED"
    operands = _operands(
        node,
        frame.operation.reverse_difference,
        entities,
        ticker_to_ref,
        metrics,
        periods,
        period_to_ref,
        intent,
    )
    operand_status = _operand_status(node, operands, entities, metrics, periods)
    operation_tree = {
        "node": node,
        "operands": [str(row["operand_ref"]) for row in operands],
        "children": [],
    }
    output = {"shape": _output_shape(node, intent, frame.operation.return_mode)}
    output_status = "RESOLVED" if node != "OTHER" else "UNRESOLVED"
    field_status: dict[str, str] = {
        "entities": entity_status,
        "metrics": metric_status,
        "periods": period_status,
        "basis": "RESOLVED",
        "unit": unit_status,
        "operation_tree": operation_status,
        "output": output_status,
        "operands": operand_status,
    }
    record_status = (
        "RESOLVED"
        if all(value in {"RESOLVED", "NOT_APPLICABLE"} for value in field_status.values())
        else "UNRESOLVED"
    )
    hashes = _contract_hashes(contract_hashes)
    annotation: dict[str, object] = {
        "schema_version": 2,
        "qid": qid,
        "question": question,
        "question_sha256": _text(selected.get("question_sha256"), "question sha256"),
        "cohort": _text(selected.get("cohort"), "cohort"),
        "selection_digest": _text(
            selected.get("selection_digest"), "selection digest"
        ),
        "primary_stratum": selected.get("primary_stratum"),
        "secondary_tags": sorted(
            str(value) for value in _sequence(selected.get("secondary_tags", []), "tags")
        ),
        # The schema predates local mode and restricts this technical slot to
        # A/B/C.  Slot A is used only as a schema-compatible container; the
        # false attestations and explicit reviewer ID prevent human claims.
        "reviewer_slot": "A",
        "reviewer_id": "LOCAL_SYNTHETIC_AUTOMATION",
        "attestations": {
            "independent_of_model_development": False,
            "blind_to_model_outputs": False,
            "source_evidence_reviewed": False,
            **hashes,
        },
        "record_status": record_status,
        "entities": entities,
        "metrics": metrics,
        "periods": periods,
        "basis": basis,
        "unit": unit,
        "operation_tree": operation_tree,
        "output": output,
        "operands": operands,
        "field_status": field_status,
        "source_evidence": [],
        "ambiguity_alternatives": [],
        "adjudication": None,
        "notes": (
            "gold_mode=LOCAL_SYNTHETIC; annotation_source=AUTOMATED; "
            "independent_review=false; human_adjudication=false; "
            "official_submission_ready=false"
        ),
    }
    validate_annotation_record(annotation, require_complete=True)
    prediction_source = {
        "entities": f"parse_intent:{intent.resolved_by}",
        "metrics": metric_source,
        "periods": "parse_question.periods",
        "basis": "parse_question.basis_explicit_only",
        "unit": "requested_unit_of",
        "operation_tree": route_source,
        "output": f"operation_result_kind:{route_source}",
        "operands": f"public_prebind_route_roles:{route_source}",
    }
    return LocalObservation(annotation, prediction_source, route_status, route_reason)


def _entity_rows(
    question: str,
    intent: Intent,
    aliases: Mapping[str, str | Sequence[str]],
) -> tuple[list[dict[str, object]], dict[str, str], str]:
    located: list[tuple[int, int, str]] = []
    for ticker in intent.targets:
        span = _entity_span(question, ticker, aliases.get(ticker, ()))
        if span is not None:
            located.append((*span, ticker))
    located.sort(key=lambda value: (value[0], value[1], value[2]))
    rows: list[dict[str, object]] = []
    ticker_to_ref: dict[str, str] = {}
    for index, (start, end, ticker) in enumerate(located, 1):
        ref = f"e{index}"
        ticker_to_ref[ticker] = ref
        rows.append(
            {
                "entity_ref": ref,
                "mention": {
                    "text": question[start:end],
                    "start": start,
                    "end": end,
                },
                "canonical_ref": ticker,
                "resolution_status": "RESOLVED",
                "semantic_role": (
                    "COMPARAND" if len(intent.targets) > 1 else "REPORTING_ENTITY"
                ),
            }
        )
    status = (
        "RESOLVED"
        if intent.targets and len(ticker_to_ref) == len(intent.targets)
        else "UNRESOLVED"
    )
    return rows, ticker_to_ref, status


def _entity_span(
    question: str,
    ticker: str,
    raw_aliases: str | Sequence[str],
) -> tuple[int, int] | None:
    ticker_match = re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker)}(?![A-Za-z0-9])", question)
    if ticker_match:
        return ticker_match.span()
    aliases = [raw_aliases] if isinstance(raw_aliases, str) else list(raw_aliases)
    for alias in sorted((str(value) for value in aliases), key=lambda x: (-len(x), x)):
        span = _casefold_span(question, alias)
        if span is not None:
            return span
    return None


def _metric_rows(
    question: str, vocabulary: Mapping[str, object]
) -> list[dict[str, object]]:
    raw_concepts = _sequence(vocabulary.get("concepts"), "metric concepts")
    candidates: list[tuple[int, int, str]] = []
    for raw in raw_concepts:
        concept = _mapping(raw, "metric concept")
        concept_id = _text(concept.get("id"), "metric concept id")
        for raw_example in _sequence(
            concept.get("inclusion_examples_vi", []), "metric examples"
        ):
            example = str(raw_example)
            for start, end in _all_casefold_spans(question, example):
                candidates.append((start, end, concept_id))
    # A span claimed by multiple concepts is ambiguous and therefore omitted;
    # choosing alphabetically would fabricate certainty.  Maximal,
    # non-overlapping exact matches then avoid REVENUE inside NET_REVENUE.
    concepts_by_span: dict[tuple[int, int], set[str]] = {}
    for start, end, concept_id in candidates:
        concepts_by_span.setdefault((start, end), set()).add(concept_id)
    unambiguous = [
        (start, end, next(iter(concepts)))
        for (start, end), concepts in concepts_by_span.items()
        if len(concepts) == 1
    ]
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(
        unambiguous, key=lambda item: (-(item[1] - item[0]), item[0], item[2])
    ):
        start, end, _concept = candidate
        if any(start < chosen_end and chosen_start < end for chosen_start, chosen_end, _ in selected):
            continue
        selected.append(candidate)
    selected.sort(key=lambda item: (item[0], item[1], item[2]))
    rows: list[dict[str, object]] = []
    for index, (start, end, concept_id) in enumerate(selected, 1):
        rows.append(
            {
                "metric_ref": f"m{index}",
                "phrase": {
                    "text": question[start:end],
                    "start": start,
                    "end": end,
                },
                "concept_id": concept_id,
                "concept_status": "RESOLVED",
                "reported_or_derived": "UNKNOWN",
                "definition_version": "semantic-metric-concepts-v1",
                "variant": None,
            }
        )
    return rows


def _period_rows(
    raw_periods: Sequence[str], operation: str
) -> tuple[list[dict[str, object]], dict[str, str]]:
    normalized = sorted({str(value)[:4] for value in raw_periods if str(value)[:4].isdigit()})
    rows: list[dict[str, object]] = []
    period_to_ref: dict[str, str] = {}
    newest = normalized[-1] if normalized else None
    for index, period in enumerate(normalized, 1):
        role = "VALUE"
        if operation == "GROWTH":
            role = "CURRENT" if period == newest else "PREVIOUS"
        elif operation == "SUBTRACT" and len(normalized) >= 2:
            role = "CURRENT" if period == newest else "PREVIOUS"
        elif operation == EXTREMUM:
            role = "RANK_DOMAIN"
        elif operation == COUNT_OP:
            role = "FILTER_DOMAIN"
        ref = f"p{index}"
        period_to_ref[period] = ref
        rows.append(
            {
                "period_ref": ref,
                "year": int(period),
                "quarter": None,
                "point": "PERIOD",
                "role": role,
                "explicit": True,
            }
        )
    return rows, period_to_ref


def _basis(explicit_basis: str | None) -> dict[str, object]:
    if explicit_basis is None:
        return {"value": "UNSPECIFIED", "explicit": False}
    return {"value": explicit_basis.upper(), "explicit": True}


def _unit(unit: Any) -> tuple[dict[str, object], str]:
    dimension = str(unit.dimension)
    scale = unit.scale_exponent if dimension == "MONEY" else None
    if dimension == "MONEY" and scale not in {0, 3, 6, 9, 12}:
        return (
            {
                "dimension": "UNKNOWN",
                "scale_exponent": None,
                "currency": None,
                "explicit": False,
            },
            "UNRESOLVED",
        )
    return (
        {
            "dimension": dimension,
            "scale_exponent": scale,
            "currency": unit.currency,
            "explicit": dimension != "UNKNOWN",
        },
        "RESOLVED" if dimension != "UNKNOWN" else "UNRESOLVED",
    )


def _operation(
    question: str, intent: Intent, frame: Any
) -> tuple[str, str, str | None, str]:
    requested_unit = frame.requested_unit
    entity_count, entity_count_reason = classify_entity_count(
        question, intent.targets, intent.years, mode=intent.mode
    )
    if entity_count is not None:
        return "COUNT", "OK", None, "typed_entity_count"
    if entity_count_reason is not None:
        return "COUNT", "ABSTAIN", entity_count_reason, "typed_entity_count"
    if is_typed_entity_difference(
        question,
        intent.targets,
        intent.years,
        requested_unit,
        mode=intent.mode,
    ):
        return "SUBTRACT", "OK", None, "typed_entity_difference"
    if is_typed_entity_average(
        question, intent.targets, intent.years, requested_unit
    ):
        return "AVERAGE", "OK", None, "typed_entity_average"
    if is_typed_entity_sum(question, intent.targets, intent.years, requested_unit):
        return "SUM", "OK", None, "typed_entity_sum"
    count_predicate, count_reason = classify_count_predicate(question)
    if count_predicate is not None:
        return "COUNT", "OK", None, "typed_period_count"
    if count_reason is not None:
        return "COUNT", "ABSTAIN", count_reason, "typed_period_count"
    formula = match_formula(question)
    if formula is not None:
        node = _schema_operation(frame.operation)
        return node, "OK", None, f"reviewed_formula:{formula.formula_id}"
    routed = route(frame)
    node = _schema_operation(frame.operation)
    return (
        node,
        routed.status,
        routed.reason,
        "generic_frame_ir" if routed.ok else "generic_operation_hint",
    )


def _schema_operation(operation: Any) -> str:
    if operation.op == EXTREMUM:
        if operation.return_mode == RETURN_FILTERED_VALUE:
            return "OTHER"
        if operation.return_mode == RETURN_SELECT_AT_ARG:
            return "SELECT_AT_ARG"
        if operation.return_mode == RETURN_PERIOD:
            return "ARGMIN" if operation.rank_direction == RANK_MIN else "ARGMAX"
        return "MINIMUM" if operation.rank_direction == RANK_MIN else "MAXIMUM"
    return _OPERATION_NAME.get(str(operation.op), str(operation.op))


def _operands(
    node: str,
    reverse_difference: bool,
    entities: Sequence[Mapping[str, object]],
    ticker_to_ref: Mapping[str, str],
    metrics: Sequence[Mapping[str, object]],
    periods: Sequence[Mapping[str, object]],
    period_to_ref: Mapping[str, str],
    intent: Intent,
) -> list[dict[str, object]]:
    entity_refs = [str(row["entity_ref"]) for row in entities]
    metric_refs = [str(row["metric_ref"]) for row in metrics]
    period_refs = [str(row["period_ref"]) for row in periods]
    newest_first = list(reversed(period_refs))
    specs: list[tuple[str, str | None, str | None, str | None]] = []

    if node in {"SUM", "AVERAGE", "COUNT"} and len(intent.targets) > 1:
        role = _VARIADIC_ROLE[node]
        period_ref = period_refs[0] if len(period_refs) == 1 else None
        for ticker in intent.targets:
            specs.append(
                (
                    role,
                    ticker_to_ref.get(ticker),
                    metric_refs[0] if len(metric_refs) == 1 else None,
                    period_ref,
                )
            )
    elif node == "SUBTRACT" and len(intent.targets) == 2 and len(period_refs) == 1:
        ordered = list(intent.targets)
        if reverse_difference:
            ordered.reverse()
        for role, ticker in zip(_ROLE_BY_OPERATION[node], ordered, strict=True):
            specs.append(
                (
                    role,
                    ticker_to_ref.get(ticker),
                    metric_refs[0] if len(metric_refs) == 1 else None,
                    period_refs[0],
                )
            )
    elif node in _ROLE_BY_OPERATION:
        roles = _ROLE_BY_OPERATION[node]
        for index, role in enumerate(roles):
            metric_ref: str | None = None
            if node == "DIVIDE":
                metric_ref = metric_refs[index] if index < len(metric_refs) else None
            elif len(metric_refs) == 1:
                metric_ref = metric_refs[0]
            elif index < len(metric_refs):
                metric_ref = metric_refs[index]
            period_ref = period_refs[0] if period_refs else None
            if node in {"GROWTH", "SUBTRACT"} and len(newest_first) >= 2:
                period_ref = newest_first[index]
                if node == "SUBTRACT" and reverse_difference:
                    period_ref = newest_first[1 - index]
            specs.append(
                (
                    role,
                    entity_refs[0] if len(entity_refs) == 1 else None,
                    metric_ref,
                    period_ref,
                )
            )
    elif node in _VARIADIC_ROLE:
        role = _VARIADIC_ROLE[node]
        axis_refs = period_refs if len(period_refs) >= 2 else entity_refs
        for axis_ref in axis_refs:
            is_period_axis = axis_ref in period_to_ref.values()
            specs.append(
                (
                    role,
                    entity_refs[0] if is_period_axis and len(entity_refs) == 1 else (
                        axis_ref if not is_period_axis else None
                    ),
                    metric_refs[0] if len(metric_refs) == 1 else None,
                    axis_ref if is_period_axis else (
                        period_refs[0] if len(period_refs) == 1 else None
                    ),
                )
            )
    elif node == "SELECT_AT_ARG" and len(metric_refs) >= 2:
        specs = [
            (
                "RANK_KEY",
                entity_refs[0] if len(entity_refs) == 1 else None,
                metric_refs[0],
                period_refs[0] if len(period_refs) == 1 else None,
            ),
            (
                "PROJECTED_VALUE",
                entity_refs[0] if len(entity_refs) == 1 else None,
                metric_refs[1],
                period_refs[0] if len(period_refs) == 1 else None,
            ),
        ]

    rows: list[dict[str, object]] = []
    for index, (role, entity_ref, metric_ref, period_ref) in enumerate(specs, 1):
        rows.append(
            {
                "operand_ref": f"o{index}",
                "role": role,
                "metric_ref": metric_ref,
                "entity_ref": entity_ref,
                "period_ref": period_ref,
                "basis": None,
                "unit": None,
            }
        )
    return rows


def _operand_status(
    node: str,
    operands: Sequence[Mapping[str, object]],
    entities: Sequence[Mapping[str, object]],
    metrics: Sequence[Mapping[str, object]],
    periods: Sequence[Mapping[str, object]],
) -> str:
    if not operands or node == "OTHER":
        return "UNRESOLVED"
    for operand in operands:
        if metrics and operand.get("metric_ref") is None:
            return "UNRESOLVED"
        if not metrics:
            return "UNRESOLVED"
        if entities and operand.get("entity_ref") is None:
            return "UNRESOLVED"
        if periods and operand.get("period_ref") is None:
            return "UNRESOLVED"
    return "RESOLVED"


def _output_shape(node: str, intent: Intent, return_mode: str | None) -> str:
    if node == "COUNT":
        return "COUNT"
    if node in {"ARGMIN", "ARGMAX"} or return_mode == RETURN_PERIOD:
        return "PERIOD"
    if node in {"MINIMUM", "MAXIMUM"} and intent.mode == "screen":
        return "ENTITY"
    return "SCALAR" if node != "OTHER" else "OTHER"


def _evaluate_qids(
    qids: Sequence[int],
    gold_by_qid: Mapping[int, Mapping[str, object]],
    prediction_by_qid: Mapping[int, Mapping[str, object]],
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for metric_name, field in METRIC_DEFINITIONS:
        correct = scored = skipped = 0
        for qid in qids:
            gold = gold_by_qid[qid]
            if gold.get("record_status") != "RESOLVED":
                skipped += 1
                continue
            if field != "full_frame" and _field_status(gold, field) == "NOT_APPLICABLE":
                skipped += 1
                continue
            scored += 1
            prediction = _prediction_semantic(prediction_by_qid[qid])
            if _metric_value(metric_name, gold) == _metric_value(metric_name, prediction):
                correct += 1
        rows.append(_metric_row(metric_name, correct, scored, skipped))
    return {
        "records": len(qids),
        "resolved_records": sum(
            gold_by_qid[qid].get("record_status") == "RESOLVED" for qid in qids
        ),
        "metrics": rows,
    }


def _metric_row(name: str, correct: int, scored: int, skipped: int) -> dict[str, object]:
    accuracy: float | str = "NOT_MEASURABLE"
    interval: list[float] | str = "NOT_MEASURABLE"
    if scored:
        accuracy = correct / scored
        interval = list(_wilson(correct, scored))
    return {
        "metric": name,
        "correct": correct,
        "scored": scored,
        "skipped": skipped,
        "accuracy": accuracy,
        "wilson_95": interval,
    }


def _metric_value(name: str, record: Mapping[str, object]) -> object:
    if name == "Entity Reference Accuracy":
        return [
            (row.get("canonical_ref"), row.get("semantic_role"))
            for row in _rows(record.get("entities"), "entities")
        ]
    if name == "Metric Phrase Exact Match":
        return [
            (
                _mapping(row.get("phrase"), "metric phrase").get("start"),
                _mapping(row.get("phrase"), "metric phrase").get("end"),
                _mapping(row.get("phrase"), "metric phrase").get("text"),
            )
            for row in _rows(record.get("metrics"), "metrics")
        ]
    if name == "Metric Concept Accuracy":
        return [row.get("concept_id") for row in _rows(record.get("metrics"), "metrics")]
    if name == "Period Exact Match":
        return [
            (row.get("year"), row.get("quarter"), row.get("point"))
            for row in _rows(record.get("periods"), "periods")
        ]
    if name == "Period Role Accuracy":
        return [row.get("role") for row in _rows(record.get("periods"), "periods")]
    if name == "Basis Accuracy":
        return record.get("basis")
    if name == "Unit Accuracy":
        return record.get("unit")
    if name == "Operation Accuracy":
        return record.get("operation_tree")
    if name == "Result Kind Accuracy":
        return record.get("output")
    if name == "Operand Count Accuracy":
        return len(_rows(record.get("operands"), "operands"))
    if name == "Operand Role Accuracy":
        return [row.get("role") for row in _rows(record.get("operands"), "operands")]
    if name == "Operand Metric Accuracy":
        return _operand_concepts(record)
    if name == "Operand Role+Metric Accuracy":
        roles = [row.get("role") for row in _rows(record.get("operands"), "operands")]
        return list(zip(roles, _operand_concepts(record), strict=True))
    if name == "Full Semantic Frame Exact":
        return {
            field: deepcopy(record.get(field))
            for field in SEMANTIC_COMPONENT_FIELDS
            if _field_status(record, field) != "NOT_APPLICABLE"
        }
    raise ValueError(f"unknown metric: {name}")


def _operand_concepts(record: Mapping[str, object]) -> list[object]:
    concepts = {
        str(row.get("metric_ref")): row.get("concept_id")
        for row in _rows(record.get("metrics"), "metrics")
    }
    return [
        concepts.get(str(row.get("metric_ref")))
        if row.get("metric_ref") is not None
        else None
        for row in _rows(record.get("operands"), "operands")
    ]


def _failure_rows(
    gold_by_qid: Mapping[int, Mapping[str, object]],
    prediction_by_qid: Mapping[int, Mapping[str, object]],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for qid in sorted(gold_by_qid):
        gold = gold_by_qid[qid]
        if gold.get("record_status") != "RESOLVED":
            continue
        prediction_row = prediction_by_qid[qid]
        prediction = _prediction_semantic(prediction_row)
        failed_metrics = [
            name
            for name, _field in METRIC_DEFINITIONS
            if _metric_value(name, gold) != _metric_value(name, prediction)
        ]
        if not failed_metrics:
            continue
        categories = _failure_categories(failed_metrics, prediction_row)
        primary = categories[0]
        failed_fields = sorted(
            {
                field
                for name, field in METRIC_DEFINITIONS
                if name in failed_metrics and field != "full_frame"
            }
        )
        failures.append(
            {
                "schema_version": 1,
                "qid": qid,
                "cohort": gold.get("cohort"),
                "primary_stratum": gold.get("primary_stratum"),
                "primary_failure": primary,
                "secondary_failures": categories[1:],
                "failed_fields": failed_fields,
                "failed_metrics": failed_metrics,
                "gold_value": {
                    field: deepcopy(gold.get(field)) for field in failed_fields
                },
                "prediction_value": {
                    field: deepcopy(prediction.get(field)) for field in failed_fields
                },
                "prediction_source": _mapping(
                    prediction_row.get("prediction_source"), "prediction source"
                ),
                "category_tags": sorted(
                    str(value)
                    for value in _sequence(gold.get("secondary_tags", []), "tags")
                ),
                "boundary": _failure_boundary(categories),
            }
        )
    return failures


def _failure_categories(
    failed_metrics: Sequence[str], prediction: Mapping[str, object]
) -> list[str]:
    categories: set[str] = set()
    missing = set(
        str(value)
        for value in _sequence(prediction.get("missing_fields", []), "missing fields")
    )
    if missing:
        categories.add("MISSING_OUTPUT")
    mapping = {
        "Entity Reference Accuracy": "ENTITY_REFERENCE",
        "Metric Phrase Exact Match": "METRIC_PHRASE",
        "Metric Concept Accuracy": "METRIC_CONCEPT",
        "Period Exact Match": "PERIOD",
        "Period Role Accuracy": "PERIOD_ROLE",
        "Basis Accuracy": "BASIS",
        "Unit Accuracy": "UNIT",
        "Operation Accuracy": "OPERATION",
        "Result Kind Accuracy": "RESULT_KIND",
        "Operand Count Accuracy": "OPERAND_COUNT",
        "Operand Role Accuracy": "OPERAND_ROLE",
        "Operand Metric Accuracy": "OPERAND_METRIC",
        "Operand Role+Metric Accuracy": "OPERAND_METRIC",
        "Full Semantic Frame Exact": "COMPOSITION",
    }
    categories.update(mapping[name] for name in failed_metrics)
    precedence = (
        "MISSING_OUTPUT",
        "ENTITY_REFERENCE",
        "OPERATION",
        "COMPOSITION",
        "OPERAND_COUNT",
        "OPERAND_ROLE",
        "OPERAND_METRIC",
        "METRIC_PHRASE",
        "METRIC_CONCEPT",
        "PERIOD",
        "PERIOD_ROLE",
        "BASIS",
        "UNIT",
        "RESULT_KIND",
    )
    return [category for category in precedence if category in categories]


def _failure_boundary(categories: Sequence[str]) -> str:
    if any(
        category in {"OPERATION", "OPERAND_COUNT", "OPERAND_ROLE"}
        for category in categories
    ):
        return "PARSER_OR_SEMANTIC_COMPILER"
    return "PARSER"


def _diagnostic_breakdown(
    qids: Sequence[int],
    gold_by_qid: Mapping[int, Mapping[str, object]],
    prediction_by_qid: Mapping[int, Mapping[str, object]],
) -> dict[str, object]:
    strata: dict[str, list[int]] = {}
    for qid in qids:
        stratum = str(gold_by_qid[qid].get("primary_stratum") or "UNSTRATIFIED")
        strata.setdefault(stratum, []).append(qid)
    result: dict[str, object] = {}
    for stratum, selected in sorted(strata.items()):
        evaluated = _evaluate_qids(selected, gold_by_qid, prediction_by_qid)
        full_frame = next(
            row
            for row in _sequence(evaluated["metrics"], "evaluated metrics")
            if _mapping(row, "metric row").get("metric") == "Full Semantic Frame Exact"
        )
        result[stratum] = {
            "records": len(selected),
            "resolved_records": evaluated["resolved_records"],
            "full_frame_exact": full_frame,
        }
    return result


def _prediction_semantic(prediction: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(prediction.get("semantic"), "prediction semantic")


def _field_status(record: Mapping[str, object], field: str) -> str:
    statuses = _mapping(record.get("field_status"), "field status")
    return str(statuses.get(field, "UNRESOLVED"))


def _wilson(correct: int, total: int) -> tuple[float, float]:
    if total <= 0:
        raise ValueError("Wilson interval requires a positive denominator")
    z = 1.959963984540054
    proportion = correct / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return (center - margin, center + margin)


def _contract_hashes(values: Mapping[str, str]) -> dict[str, str]:
    required = {
        "guideline_version",
        "guideline_sha256",
        "metric_vocabulary_sha256",
        "operation_vocabulary_sha256",
    }
    if set(values) != required:
        raise ValueError("local annotation contract hashes are incomplete")
    return {key: _text(values[key], key) for key in sorted(values)}


def _casefold_span(text: str, phrase: str) -> tuple[int, int] | None:
    folded_text = text.casefold()
    folded_phrase = phrase.casefold()
    start = folded_text.find(folded_phrase)
    return None if start < 0 else (start, start + len(phrase))


def _all_casefold_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    if not phrase:
        return []
    folded_text = text.casefold()
    folded_phrase = phrase.casefold()
    spans: list[tuple[int, int]] = []
    offset = 0
    while True:
        start = folded_text.find(folded_phrase, offset)
        if start < 0:
            return spans
        end = start + len(phrase)
        left_ok = start == 0 or not folded_text[start - 1].isalnum()
        right_ok = end == len(folded_text) or not folded_text[end].isalnum()
        if left_ok and right_ok:
            spans.append((start, end))
        offset = start + 1


def _qid(row: Mapping[str, object]) -> int:
    raw = row.get("qid", row.get("id"))
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise TypeError(f"invalid qid: {raw!r}")
    qid = int(raw)
    if qid < 1:
        raise ValueError("qid must be positive")
    return qid


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    return value


def _rows(value: object, label: str) -> list[Mapping[str, object]]:
    return [_mapping(row, label) for row in _sequence(value, label)]
