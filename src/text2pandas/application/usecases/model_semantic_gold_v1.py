"""Pure contracts for single-model semantic gold generation and evaluation.

This module is deliberately prediction-blind. It contains no parser, retrieval,
resolver, answer, query, or execution imports.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RELEASE_ID = "MODEL_SEMANTIC_GOLD_V1"
SCHEMA_VERSION = 3
PROMPT_VERSION = "model-semantic-gold-prompt-v1"

SEMANTIC_FIELDS = (
    "entities",
    "metrics",
    "periods",
    "basis",
    "unit",
    "operation_tree",
    "output",
    "operands",
)

FORBIDDEN_INPUT_FIELDS = frozenset(
    {
        "answer",
        "answer_output",
        "ast_prediction",
        "binder_output",
        "candidate_scores",
        "execution_result",
        "execution_trace",
        "model_answer",
        "numeric_answer",
        "pandas_query",
        "parser_output",
        "parser_prediction",
        "parser_trace",
        "predicted_answer",
        "predicted_semantic",
        "prediction",
        "resolver_output",
        "resolver_result",
        "retrieval_candidates",
        "retrieval_output",
        "retrieval_rank",
        "retrieval_result",
        "retrieval_score",
        "retrieval_scores",
        "selected_cell",
        "selected_row",
        "selected_table",
        "selector_output",
        "trace",
        "v3_ast",
        "vas_hints",
    }
)

_ENUM_KEYS = frozenset(
    {
        "comparator",
        "concept_status",
        "dimension",
        "entity_type",
        "kind",
        "node",
        "point",
        "record_status",
        "reported_or_derived",
        "resolution_status",
        "role",
        "semantic_role",
        "shape",
        "source_kind",
        "status",
        "status_reason",
        "value",
    }
)


class ModelGoldValidationError(ValueError):
    """Raised when a model-gold record violates a frozen semantic contract."""


@dataclass(frozen=True, slots=True)
class EvaluationMetric:
    passed: int
    total: int

    @property
    def accuracy(self) -> float | None:
        return self.passed / self.total if self.total else None


@dataclass(frozen=True, slots=True)
class SemanticEvaluation:
    metrics: Mapping[str, EvaluationMetric]
    evaluated_qids: tuple[int, ...]
    missing_prediction_qids: tuple[int, ...]
    extra_prediction_qids: tuple[int, ...]


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(canonical_json_bytes(dict(row)) for row in rows)


def json_schema_errors(value: object, schema: Mapping[str, object]) -> list[str]:
    """Validate the JSON-Schema subset used by the two frozen model contracts."""

    errors: list[str] = []

    def resolve_ref(reference: str) -> Mapping[str, object]:
        if not reference.startswith("#/"):
            raise ModelGoldValidationError(f"only local JSON Schema refs are supported: {reference}")
        current: object = schema
        for raw_part in reference[2:].split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            if not isinstance(current, Mapping) or part not in current:
                raise ModelGoldValidationError(f"unresolvable JSON Schema ref: {reference}")
            current = current[part]
        if not isinstance(current, Mapping):
            raise ModelGoldValidationError(f"JSON Schema ref is not an object: {reference}")
        return current

    def walk(instance: object, contract: Mapping[str, object], path: str) -> None:
        reference = contract.get("$ref")
        if isinstance(reference, str):
            walk(instance, resolve_ref(reference), path)
            return
        alternatives = contract.get("anyOf")
        if isinstance(alternatives, Sequence) and not isinstance(alternatives, (str, bytes)):
            branch_errors: list[list[str]] = []
            for alternative in alternatives:
                if not isinstance(alternative, Mapping):
                    continue
                before = len(errors)
                walk(instance, alternative, path)
                branch_errors.append(errors[before:])
                del errors[before:]
            if branch_errors and not any(not branch for branch in branch_errors):
                errors.append(f"{path}: does not match any allowed schema")
            return
        if "const" in contract and instance != contract["const"]:
            errors.append(f"{path}: must equal {contract['const']!r}")
        enum = contract.get("enum")
        if isinstance(enum, Sequence) and not isinstance(enum, (str, bytes)) and instance not in enum:
            errors.append(f"{path}: value {instance!r} is outside enum")
        raw_types = contract.get("type")
        if raw_types is not None:
            types: list[object] = (
                [raw_types]
                if isinstance(raw_types, str)
                else list(_required_sequence(raw_types, f"{path}.schema.type"))
            )
            if not any(_json_type_matches(instance, str(expected)) for expected in types):
                errors.append(f"{path}: expected JSON type {types}, found {type(instance).__name__}")
                return
        if isinstance(instance, Mapping):
            required = contract.get("required", [])
            if isinstance(required, Sequence) and not isinstance(required, (str, bytes)):
                for key in required:
                    if str(key) not in instance:
                        errors.append(f"{path}: missing required property {key}")
            properties = contract.get("properties", {})
            if isinstance(properties, Mapping):
                if contract.get("additionalProperties") is False:
                    extras = sorted(str(key) for key in instance if key not in properties)
                    if extras:
                        errors.append(f"{path}: additional properties {extras}")
                for raw_key, child_contract in properties.items():
                    key = str(raw_key)
                    if key in instance and isinstance(child_contract, Mapping):
                        walk(instance[key], child_contract, f"{path}/{key}")
        elif isinstance(instance, Sequence) and not isinstance(instance, (str, bytes, bytearray)):
            item_contract = contract.get("items")
            if isinstance(item_contract, Mapping):
                for index, child in enumerate(instance):
                    walk(child, item_contract, f"{path}/{index}")
            if contract.get("uniqueItems") is True:
                rendered = [
                    json.dumps(child, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    for child in instance
                ]
                if len(rendered) != len(set(rendered)):
                    errors.append(f"{path}: array items must be unique")
        elif isinstance(instance, str):
            minimum_length = contract.get("minLength")
            if isinstance(minimum_length, int) and len(instance) < minimum_length:
                errors.append(f"{path}: string is shorter than {minimum_length}")
            pattern = contract.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, instance) is None:
                errors.append(f"{path}: string does not match {pattern}")
        if isinstance(instance, (int, float)) and not isinstance(instance, bool):
            minimum = contract.get("minimum")
            maximum = contract.get("maximum")
            if isinstance(minimum, (int, float)) and instance < minimum:
                errors.append(f"{path}: value is below minimum {minimum}")
            if isinstance(maximum, (int, float)) and instance > maximum:
                errors.append(f"{path}: value is above maximum {maximum}")

    walk(value, schema, "$")
    return errors


def _json_type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    raise ModelGoldValidationError(f"unsupported JSON Schema type: {expected}")


def reject_forbidden_fields(value: object, *, location: str) -> None:
    """Fail closed when prediction/runtime-shaped fields occur at any depth."""

    violations: list[str] = []

    def walk(item: object, path: str) -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                key = str(raw_key)
                child_path = f"{path}.{key}"
                if key.casefold() in FORBIDDEN_INPUT_FIELDS:
                    violations.append(child_path)
                walk(child, child_path)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value, location)
    if violations:
        raise ModelGoldValidationError(
            "forbidden prediction/runtime fields: " + ", ".join(sorted(violations))
        )


def derive_record_status(field_status: Mapping[str, object]) -> str:
    statuses = [_required_text(field_status.get(name), f"field_status.{name}") for name in SEMANTIC_FIELDS]
    if any(status == "UNRESOLVED" for status in statuses):
        return "UNRESOLVED"
    if any(status == "AMBIGUOUS" for status in statuses):
        return "AMBIGUOUS"
    return "RESOLVED"


def derive_status_reason(record: Mapping[str, object], *, generation_failure: bool = False) -> str | None:
    field_status = _required_mapping(record.get("field_status"), "field_status")
    status = derive_record_status(field_status)
    if status == "RESOLVED":
        return None
    if status == "AMBIGUOUS":
        return "QUESTION_AMBIGUITY"
    if generation_failure:
        return "GENERATION_FAILURE"
    evidence = _required_sequence(record.get("source_evidence"), "source_evidence")
    if any(
        isinstance(item, Mapping) and item.get("status") == "NOT_LOCATED"
        for item in evidence
    ):
        return "MISSING_EVIDENCE"
    if field_status.get("metrics") == "UNRESOLVED":
        return "MISSING_VOCABULARY"
    return "SCHEMA_LIMITATION"


def compile_model_response(
    selection: Mapping[str, object],
    response: Mapping[str, object],
    generation: Mapping[str, object],
) -> dict[str, object]:
    """Compile a constrained model response into the final annotation schema."""

    reject_forbidden_fields(response, location="model_response")
    question = unicodedata.normalize(
        "NFC", _required_text(selection.get("question"), "selection.question")
    )
    entities = [
        _compile_entity(question, _required_mapping(item, "entity"))
        for item in _required_sequence(response.get("entities"), "entities")
    ]
    metrics = [
        _compile_metric(question, _required_mapping(item, "metric"))
        for item in _required_sequence(response.get("metrics"), "metrics")
    ]
    periods = [
        _compile_period(question, _required_mapping(item, "period"))
        for item in _required_sequence(response.get("periods"), "periods")
    ]
    draft: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "release_id": RELEASE_ID,
        "qid": _positive_int(selection.get("qid"), "selection.qid"),
        "question": question,
        "question_sha256": _required_text(
            selection.get("question_sha256"), "selection.question_sha256"
        ),
        "cohort": _required_text(selection.get("cohort"), "selection.cohort"),
        "selection_digest": _required_text(
            selection.get("selection_digest"), "selection.selection_digest"
        ),
        "primary_stratum": selection.get("primary_stratum"),
        "secondary_tags": list(
            _required_sequence(selection.get("secondary_tags"), "selection.secondary_tags")
        ),
        "generation": dict(generation),
        "entities": entities,
        "metrics": metrics,
        "periods": periods,
        "basis": _copy_json_value(response.get("basis")),
        "unit": _copy_json_value(response.get("unit")),
        "operation_tree": _copy_json_value(response.get("operation_tree")),
        "output": _copy_json_value(response.get("output")),
        "operands": _copy_json_value(response.get("operands")),
        "field_status": _copy_json_value(response.get("field_status")),
        "source_evidence": _copy_json_value(response.get("source_evidence")),
        "ambiguity_alternatives": _copy_json_value(
            response.get("ambiguity_alternatives")
        ),
        "notes": response.get("notes"),
    }
    status = derive_record_status(
        _required_mapping(draft["field_status"], "field_status")
    )
    draft["record_status"] = status
    draft["status_reason"] = derive_status_reason(draft)
    return draft


def generation_failure_record(
    selection: Mapping[str, object],
    generation: Mapping[str, object],
    error: str,
) -> dict[str, object]:
    """Create an explicit, non-dropped record after all retries are exhausted."""

    question = unicodedata.normalize(
        "NFC", _required_text(selection.get("question"), "selection.question")
    )
    statuses = {name: "UNRESOLVED" for name in SEMANTIC_FIELDS}
    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "release_id": RELEASE_ID,
        "qid": _positive_int(selection.get("qid"), "selection.qid"),
        "question": question,
        "question_sha256": _required_text(
            selection.get("question_sha256"), "selection.question_sha256"
        ),
        "cohort": _required_text(selection.get("cohort"), "selection.cohort"),
        "selection_digest": _required_text(
            selection.get("selection_digest"), "selection.selection_digest"
        ),
        "primary_stratum": selection.get("primary_stratum"),
        "secondary_tags": list(
            _required_sequence(selection.get("secondary_tags"), "selection.secondary_tags")
        ),
        "generation": dict(generation),
        "record_status": "UNRESOLVED",
        "status_reason": "GENERATION_FAILURE",
        "entities": [],
        "metrics": [],
        "periods": [],
        "basis": {"value": "UNSPECIFIED", "explicit": False},
        "unit": {
            "dimension": "UNKNOWN",
            "scale_exponent": None,
            "currency": None,
            "explicit": False,
        },
        "operation_tree": None,
        "output": None,
        "operands": [],
        "field_status": statuses,
        "source_evidence": [
            {"source_path": None, "context_label": None, "status": "NOT_APPLICABLE"}
        ],
        "ambiguity_alternatives": [],
        "notes": f"Generation failed after bounded retries: {error}"[:2000],
    }
    return record


def validate_model_gold_record(
    record: Mapping[str, object],
    selection: Mapping[str, object],
    *,
    metric_concept_ids: frozenset[str],
    operation_specs: Mapping[str, object],
) -> None:
    """Run semantic validation beyond JSON Schema and report all violations."""

    errors: list[str] = []
    try:
        reject_forbidden_fields(record, location="record")
    except ModelGoldValidationError as exc:
        errors.append(str(exc))

    question = str(record.get("question", ""))
    if question != unicodedata.normalize("NFC", question):
        errors.append("question is not NFC")
    expected_question = unicodedata.normalize(
        "NFC", str(selection.get("question", ""))
    )
    for field in ("qid", "question_sha256", "cohort", "selection_digest"):
        if record.get(field) != selection.get(field):
            errors.append(f"{field} does not match frozen selection")
    if question != expected_question:
        errors.append("question does not match frozen selection")
    if record.get("question_sha256") != sha256_text(question):
        errors.append("question_sha256 does not match question bytes")
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if record.get("release_id") != RELEASE_ID:
        errors.append(f"release_id must be {RELEASE_ID}")

    try:
        field_status = _required_mapping(record.get("field_status"), "field_status")
        derived_status = derive_record_status(field_status)
        if record.get("record_status") != derived_status:
            errors.append("record_status is not deterministically derived")
        expected_reason = derive_status_reason(
            record, generation_failure=record.get("status_reason") == "GENERATION_FAILURE"
        )
        if record.get("status_reason") != expected_reason:
            errors.append(
                f"status_reason mismatch: expected {expected_reason!r}, "
                f"found {record.get('status_reason')!r}"
            )
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))
        field_status = {}

    entities = _mapping_items(record.get("entities"), "entities", errors)
    metrics = _mapping_items(record.get("metrics"), "metrics", errors)
    periods = _mapping_items(record.get("periods"), "periods", errors)
    operands = _mapping_items(record.get("operands"), "operands", errors)

    entity_refs = _unique_refs(entities, "entity_ref", "entities", errors)
    metric_refs = _unique_refs(metrics, "metric_ref", "metrics", errors)
    period_refs = _unique_refs(periods, "period_ref", "periods", errors)
    operand_refs = _unique_refs(operands, "operand_ref", "operands", errors)

    for index, entity in enumerate(entities):
        _validate_span(question, entity.get("mention"), f"entities[{index}].mention", errors)
    for index, metric in enumerate(metrics):
        _validate_span(question, metric.get("phrase"), f"metrics[{index}].phrase", errors)
        concept = metric.get("concept_id")
        status = metric.get("concept_status")
        if status == "RESOLVED" and concept not in metric_concept_ids:
            errors.append(f"metrics[{index}].concept_id is outside frozen vocabulary")
        if concept == "OTHER_REPORTED_METRIC" and not str(metric.get("variant") or "").strip():
            errors.append(f"metrics[{index}] OTHER_REPORTED_METRIC requires variant")
        if status == "UNRESOLVED" and concept is not None:
            errors.append(f"metrics[{index}] unresolved concept_id must be null")
    for index, period in enumerate(periods):
        mention = period.get("mention")
        if mention is not None:
            _validate_span(question, mention, f"periods[{index}].mention", errors)
        if all(period.get(name) is None for name in ("year", "quarter", "date")):
            errors.append(f"periods[{index}] has no year, quarter, or date")

    _validate_unit(record.get("unit"), "unit", errors)
    for index, operand in enumerate(operands):
        _validate_ref(operand.get("entity_ref"), entity_refs, f"operands[{index}].entity_ref", errors)
        _validate_ref(operand.get("metric_ref"), metric_refs, f"operands[{index}].metric_ref", errors)
        _validate_ref(operand.get("period_ref"), period_refs, f"operands[{index}].period_ref", errors)
        if operand.get("unit") is not None:
            _validate_unit(operand.get("unit"), f"operands[{index}].unit", errors)
        literal = operand.get("literal")
        if operand.get("role") == "FILTER_THRESHOLD" and literal is None:
            errors.append(f"operands[{index}] FILTER_THRESHOLD requires literal")
        if literal is not None and operand.get("role") != "FILTER_THRESHOLD":
            errors.append(f"operands[{index}] literal is only valid for FILTER_THRESHOLD")

    generation_failure = record.get("status_reason") == "GENERATION_FAILURE"
    if not generation_failure:
        _validate_component_statuses(
            field_status, entities, metrics, periods, operands, record, errors
        )
        operation = record.get("operation_tree")
        if isinstance(operation, Mapping):
            if operation.get("node") == "OTHER" and field_status.get("operation_tree") != "UNRESOLVED":
                errors.append("OTHER operation requires UNRESOLVED operation_tree status")
            _validate_operation_tree(
                operation,
                operand_refs=operand_refs,
                operands={str(item.get("operand_ref")): item for item in operands},
                operation_specs=operation_specs,
                errors=errors,
            )
        elif field_status.get("operation_tree") == "RESOLVED":
            errors.append("resolved operation_tree cannot be null")

    alternatives = _mapping_items(
        record.get("ambiguity_alternatives"), "ambiguity_alternatives", errors
    )
    _unique_refs(alternatives, "alternative_id", "ambiguity_alternatives", errors)
    if record.get("record_status") == "AMBIGUOUS" and len(alternatives) < 2:
        errors.append("ambiguous record requires at least two alternatives")
    if record.get("record_status") == "UNRESOLVED" and not str(record.get("notes") or "").strip():
        errors.append("unresolved record requires non-empty notes")

    if errors:
        qid = record.get("qid", "unknown")
        raise ModelGoldValidationError(
            f"semantic validation failed for qid={qid}: " + "; ".join(errors)
        )


def canonicalize_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return the deterministic semantic-only evaluation frame."""

    entities = sorted(
        _json_list(record.get("entities")), key=lambda item: _span_sort_key(item, "mention", "entity_ref")
    )
    metrics = sorted(
        _json_list(record.get("metrics")), key=lambda item: _span_sort_key(item, "phrase", "metric_ref")
    )
    periods = sorted(
        _json_list(record.get("periods")), key=lambda item: _period_sort_key(item)
    )
    alternatives = sorted(
        _json_list(record.get("ambiguity_alternatives")),
        key=lambda item: str(item.get("alternative_id", "")),
    )
    frame: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "qid": record.get("qid"),
        "question_sha256": record.get("question_sha256"),
        "record_status": record.get("record_status"),
        "status_reason": record.get("status_reason"),
        "field_status": _copy_json_value(record.get("field_status")),
        "entities": entities,
        "metrics": metrics,
        "periods": periods,
        "basis": _copy_json_value(record.get("basis")),
        "unit": _copy_json_value(record.get("unit")),
        "operation_tree": _copy_json_value(record.get("operation_tree")),
        "output": _copy_json_value(record.get("output")),
        "operands": _copy_json_value(record.get("operands")),
        "ambiguity_alternatives": alternatives,
    }
    normalized = _normalize_json(frame)
    if not isinstance(normalized, dict):
        raise TypeError("canonical frame must be an object")
    return normalized


def evaluate_canonical_predictions(
    gold_rows: Sequence[Mapping[str, object]],
    prediction_rows: Sequence[Mapping[str, object]],
) -> SemanticEvaluation:
    """Evaluate frozen canonical predictions with the 14 requested metrics."""

    gold = _index_by_qid(gold_rows, "gold")
    predictions = _index_by_qid(prediction_rows, "prediction")
    common = tuple(sorted(set(gold) & set(predictions)))
    missing = tuple(sorted(set(gold) - set(predictions)))
    extra = tuple(sorted(set(predictions) - set(gold)))
    names = (
        "entity_reference_accuracy",
        "metric_phrase_exact_match",
        "metric_concept_accuracy",
        "period_exact_match",
        "period_role_accuracy",
        "basis_accuracy",
        "unit_accuracy",
        "operation_accuracy",
        "result_kind_accuracy",
        "operand_count_accuracy",
        "operand_role_accuracy",
        "operand_metric_accuracy",
        "operand_role_metric_accuracy",
        "full_semantic_frame_exact",
    )
    passed = Counter({name: 0 for name in names})
    for qid in common:
        gold_row = gold[qid]
        predicted = predictions[qid]
        comparisons = _metric_comparisons(gold_row, predicted)
        for name, success in comparisons.items():
            passed[name] += int(success)
    metrics = {
        name: EvaluationMetric(passed=passed[name], total=len(gold)) for name in names
    }
    return SemanticEvaluation(metrics, common, missing, extra)


def _compile_entity(question: str, item: Mapping[str, object]) -> dict[str, object]:
    output = dict(item)
    text = _required_text(output.pop("mention_text", None), "entity.mention_text")
    output["mention"] = _exact_span(question, text)
    return output


def _compile_metric(question: str, item: Mapping[str, object]) -> dict[str, object]:
    output = dict(item)
    text = _required_text(output.pop("phrase_text", None), "metric.phrase_text")
    output["phrase"] = _exact_span(question, text)
    return output


def _compile_period(question: str, item: Mapping[str, object]) -> dict[str, object]:
    output = dict(item)
    raw_text = output.pop("mention_text", None)
    output["mention"] = None if raw_text is None else _exact_span(question, _required_text(raw_text, "period.mention_text"))
    return output


def _exact_span(question: str, text: str) -> dict[str, object]:
    normalized = unicodedata.normalize("NFC", text)
    start = question.find(normalized)
    if start < 0:
        folded_question = question.casefold()
        folded_text = normalized.casefold()
        candidates: list[int] = []
        cursor = 0
        while True:
            candidate = folded_question.find(folded_text, cursor)
            if candidate < 0:
                break
            candidates.append(candidate)
            cursor = candidate + 1
        if len(candidates) != 1:
            raise ModelGoldValidationError(
                f"mention is not a unique exact/casefold question substring: {text!r}"
            )
        start = candidates[0]
        normalized = question[start : start + len(normalized)]
    return {"text": normalized, "start": start, "end": start + len(normalized)}


def _validate_span(
    question: str, raw_span: object, label: str, errors: list[str]
) -> None:
    if not isinstance(raw_span, Mapping):
        errors.append(f"{label} must be an object")
        return
    text = raw_span.get("text")
    start = raw_span.get("start")
    end = raw_span.get("end")
    if not isinstance(text, str) or not isinstance(start, int) or not isinstance(end, int):
        errors.append(f"{label} has invalid text/start/end")
        return
    if text != unicodedata.normalize("NFC", text):
        errors.append(f"{label}.text is not NFC")
    if start < 0 or end <= start or end > len(question) or question[start:end] != text:
        errors.append(f"{label} offsets do not slice the exact text")


def _validate_unit(raw: object, label: str, errors: list[str]) -> None:
    if not isinstance(raw, Mapping):
        errors.append(f"{label} must be an object")
        return
    dimension = raw.get("dimension")
    exponent = raw.get("scale_exponent")
    currency = raw.get("currency")
    if dimension not in {"MONEY", "SHARES"} and exponent not in {None, 0}:
        errors.append(f"{label} non-money/share scale must be null or 0")
    if dimension == "MONEY" and not isinstance(currency, str):
        errors.append(f"{label} MONEY requires currency")
    if dimension != "MONEY" and currency is not None:
        errors.append(f"{label} non-MONEY currency must be null")


def _validate_component_statuses(
    field_status: Mapping[str, object],
    entities: Sequence[Mapping[str, object]],
    metrics: Sequence[Mapping[str, object]],
    periods: Sequence[Mapping[str, object]],
    operands: Sequence[Mapping[str, object]],
    record: Mapping[str, object],
    errors: list[str],
) -> None:
    collections: Mapping[str, Sequence[Mapping[str, object]]] = {
        "entities": entities,
        "metrics": metrics,
        "periods": periods,
        "operands": operands,
    }
    for name, items in collections.items():
        status = field_status.get(name)
        if status == "RESOLVED" and not items:
            errors.append(f"field_status.{name}=RESOLVED requires at least one item")
        if status == "NOT_APPLICABLE" and items:
            errors.append(f"field_status.{name}=NOT_APPLICABLE requires an empty list")
    entity_states = {str(item.get("resolution_status")) for item in entities}
    metric_states = {str(item.get("concept_status")) for item in metrics}
    for name, states in (("entities", entity_states), ("metrics", metric_states)):
        status = field_status.get(name)
        if status == "RESOLVED" and ("AMBIGUOUS" in states or "UNRESOLVED" in states):
            errors.append(f"field_status.{name}=RESOLVED conflicts with item status")
        if "UNRESOLVED" in states and status != "UNRESOLVED":
            errors.append(f"field_status.{name} must be UNRESOLVED when an item is unresolved")
        if "AMBIGUOUS" in states and status not in {"AMBIGUOUS", "UNRESOLVED"}:
            errors.append(f"field_status.{name} must expose ambiguous item status")
    basis = record.get("basis")
    if field_status.get("basis") == "NOT_APPLICABLE" and (
        not isinstance(basis, Mapping)
        or basis.get("value") != "UNSPECIFIED"
        or basis.get("explicit") is not False
    ):
        errors.append(
            "field_status.basis=NOT_APPLICABLE requires UNSPECIFIED/explicit=false"
        )
    unit = record.get("unit")
    if field_status.get("unit") == "NOT_APPLICABLE" and (
        not isinstance(unit, Mapping)
        or unit.get("dimension") != "UNKNOWN"
        or unit.get("explicit") is not False
    ):
        errors.append(
            "field_status.unit=NOT_APPLICABLE requires UNKNOWN/explicit=false"
        )
    for name in ("operation_tree", "output"):
        value = record.get(name)
        if field_status.get(name) == "RESOLVED" and value is None:
            errors.append(f"field_status.{name}=RESOLVED requires a value")
        if field_status.get(name) == "NOT_APPLICABLE" and value is not None:
            errors.append(f"field_status.{name}=NOT_APPLICABLE requires null")
        if field_status.get(name) == "NOT_APPLICABLE":
            errors.append(f"field_status.{name} cannot be NOT_APPLICABLE for a question")
    if field_status.get("operands") == "NOT_APPLICABLE":
        errors.append("field_status.operands cannot be NOT_APPLICABLE for a question")


def _validate_operation_tree(
    root: Mapping[str, object],
    *,
    operand_refs: frozenset[str],
    operands: Mapping[str, Mapping[str, object]],
    operation_specs: Mapping[str, object],
    errors: list[str],
) -> None:
    node_refs: set[str] = set()
    used_operands: Counter[str] = Counter()

    def walk(node: Mapping[str, object], path: str) -> None:
        node_id = str(node.get("node_id", ""))
        if node_id in node_refs:
            errors.append(f"duplicate operation node_id: {node_id}")
        node_refs.add(node_id)
        operation = str(node.get("node", ""))
        raw_spec = operation_specs.get(operation)
        if not isinstance(raw_spec, Mapping):
            errors.append(f"{path}.node is outside frozen operation vocabulary")
            raw_spec = {}
        inputs = _mapping_items(node.get("inputs"), f"{path}.inputs", errors)
        children = _mapping_items(node.get("children"), f"{path}.children", errors)
        direct_children = {str(child.get("node_id", "")) for child in children}
        referenced_children: Counter[str] = Counter()
        roles: list[str] = []
        for index, item in enumerate(inputs):
            role = str(item.get("role", ""))
            roles.append(role)
            source_kind = item.get("source_kind")
            source_ref = str(item.get("source_ref", ""))
            if source_kind == "OPERAND":
                if source_ref not in operand_refs:
                    errors.append(f"{path}.inputs[{index}] has dangling operand ref")
                else:
                    used_operands[source_ref] += 1
                    operand_role = operands[source_ref].get("role")
                    if operand_role != role:
                        errors.append(
                            f"{path}.inputs[{index}] role differs from referenced operand"
                        )
            elif source_kind == "NODE":
                if source_ref not in direct_children:
                    errors.append(f"{path}.inputs[{index}] must reference a direct child")
                referenced_children[source_ref] += 1
            else:
                errors.append(f"{path}.inputs[{index}] has invalid source_kind")
        for child_ref in direct_children:
            if referenced_children[child_ref] != 1:
                errors.append(f"{path} child {child_ref} must be referenced exactly once")
        _validate_operation_roles(operation, roles, raw_spec, path, errors)
        if operation == "FILTER":
            threshold_inputs = [item for item in inputs if item.get("role") == "FILTER_THRESHOLD"]
            for item in threshold_inputs:
                ref = str(item.get("source_ref", ""))
                if item.get("source_kind") != "OPERAND" or not isinstance(
                    operands.get(ref, {}).get("literal"), Mapping
                ):
                    errors.append(f"{path} FILTER_THRESHOLD must reference a literal operand")
        for index, child in enumerate(children):
            walk(child, f"{path}.children[{index}]")

    walk(root, "operation_tree")
    for operand_ref in operand_refs:
        if used_operands[operand_ref] != 1:
            errors.append(f"operand {operand_ref} must be referenced exactly once")


def _validate_operation_roles(
    operation: str,
    roles: Sequence[str],
    spec: Mapping[str, object],
    path: str,
    errors: list[str],
) -> None:
    minimum = spec.get("min_arity")
    maximum = spec.get("max_arity")
    if isinstance(minimum, int) and len(roles) < minimum:
        errors.append(f"{path} {operation} arity is below {minimum}")
    if isinstance(maximum, int) and len(roles) > maximum:
        errors.append(f"{path} {operation} arity is above {maximum}")
    ordered = spec.get("ordered_roles")
    repeated = spec.get("repeated_role")
    if isinstance(ordered, Sequence) and not isinstance(ordered, (str, bytes)):
        expected = [str(value) for value in ordered]
        if list(roles) != expected:
            errors.append(f"{path} {operation} roles must be {expected}, found {list(roles)}")
    elif isinstance(repeated, str) and any(role != repeated for role in roles):
        errors.append(f"{path} {operation} roles must all be {repeated}")


def _metric_comparisons(
    gold: Mapping[str, object], prediction: Mapping[str, object]
) -> dict[str, bool]:
    gold_metrics = _json_list(gold.get("metrics"))
    pred_metrics = _json_list(prediction.get("metrics"))
    gold_periods = _json_list(gold.get("periods"))
    pred_periods = _json_list(prediction.get("periods"))
    gold_operands = _json_list(gold.get("operands"))
    pred_operands = _json_list(prediction.get("operands"))
    return {
        "entity_reference_accuracy": _entity_signature(gold) == _entity_signature(prediction),
        "metric_phrase_exact_match": [item.get("phrase") for item in gold_metrics]
        == [item.get("phrase") for item in pred_metrics],
        "metric_concept_accuracy": _metric_signature(gold_metrics)
        == _metric_signature(pred_metrics),
        "period_exact_match": _period_signature(gold_periods, include_role=False)
        == _period_signature(pred_periods, include_role=False),
        "period_role_accuracy": [item.get("role") for item in gold_periods]
        == [item.get("role") for item in pred_periods],
        "basis_accuracy": gold.get("basis") == prediction.get("basis"),
        "unit_accuracy": gold.get("unit") == prediction.get("unit"),
        "operation_accuracy": _operation_signature(gold.get("operation_tree"))
        == _operation_signature(prediction.get("operation_tree")),
        "result_kind_accuracy": gold.get("output") == prediction.get("output"),
        "operand_count_accuracy": len(gold_operands) == len(pred_operands),
        "operand_role_accuracy": [item.get("role") for item in gold_operands]
        == [item.get("role") for item in pred_operands],
        "operand_metric_accuracy": _operand_metric_signature(gold, gold_operands)
        == _operand_metric_signature(prediction, pred_operands),
        "operand_role_metric_accuracy": _operand_role_metric_signature(gold, gold_operands)
        == _operand_role_metric_signature(prediction, pred_operands),
        "full_semantic_frame_exact": dict(gold) == dict(prediction),
    }


def _entity_signature(row: Mapping[str, object]) -> list[tuple[object, ...]]:
    return [
        (
            item.get("mention"),
            item.get("canonical_ref"),
            item.get("entity_type"),
            item.get("semantic_role"),
        )
        for item in _json_list(row.get("entities"))
    ]


def _metric_signature(items: Sequence[Mapping[str, object]]) -> list[tuple[object, object, object]]:
    return [
        (item.get("concept_id"), item.get("variant"), item.get("reported_or_derived"))
        for item in items
    ]


def _period_signature(
    items: Sequence[Mapping[str, object]], *, include_role: bool
) -> list[tuple[object, ...]]:
    fields: tuple[str, ...] = (
        "mention",
        "year",
        "quarter",
        "date",
        "point",
        "explicit",
    )
    if include_role:
        fields = (*fields, "role")
    return [tuple(item.get(field) for field in fields) for item in items]


def _operation_signature(raw: object) -> object:
    if not isinstance(raw, Mapping):
        return None
    children = _json_list(raw.get("children"))
    return {
        "node": raw.get("node"),
        "inputs": [
            {
                "role": item.get("role"),
                "source_kind": item.get("source_kind"),
            }
            for item in _json_list(raw.get("inputs"))
        ],
        "children": [_operation_signature(child) for child in children],
    }


def _operand_metric_signature(
    row: Mapping[str, object], operands: Sequence[Mapping[str, object]]
) -> list[object]:
    metrics = {
        str(item.get("metric_ref")): (item.get("concept_id"), item.get("variant"))
        for item in _json_list(row.get("metrics"))
    }
    return [metrics.get(str(item.get("metric_ref"))) for item in operands]


def _operand_role_metric_signature(
    row: Mapping[str, object], operands: Sequence[Mapping[str, object]]
) -> list[tuple[object, object]]:
    metric_signature = _operand_metric_signature(row, operands)
    return [
        (operand.get("role"), metric)
        for operand, metric in zip(operands, metric_signature, strict=True)
    ]


def _index_by_qid(
    rows: Sequence[Mapping[str, object]], label: str
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = _positive_int(row.get("qid"), f"{label}.qid")
        if qid in output:
            raise ModelGoldValidationError(f"duplicate {label} qid: {qid}")
        output[qid] = row
    return output


def _mapping_items(
    value: object, label: str, errors: list[str]
) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        errors.append(f"{label} must be a list")
        return []
    output: list[Mapping[str, object]] = []
    for index, item in enumerate(value):
        if isinstance(item, Mapping):
            output.append(item)
        else:
            errors.append(f"{label}[{index}] must be an object")
    return output


def _unique_refs(
    items: Sequence[Mapping[str, object]],
    field: str,
    label: str,
    errors: list[str],
) -> frozenset[str]:
    refs = [str(item.get(field, "")) for item in items]
    if "" in refs:
        errors.append(f"{label} has missing {field}")
    duplicates = sorted(ref for ref, count in Counter(refs).items() if count > 1)
    if duplicates:
        errors.append(f"{label} has duplicate {field}: {duplicates}")
    return frozenset(refs) - {""}


def _validate_ref(
    raw_ref: object, allowed: frozenset[str], label: str, errors: list[str]
) -> None:
    if raw_ref is not None and str(raw_ref) not in allowed:
        errors.append(f"{label} is dangling: {raw_ref!r}")


def _normalize_json(value: object, key: str | None = None) -> object:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value.strip())
        return normalized.upper() if key in _ENUM_KEYS else normalized
    if isinstance(value, Mapping):
        return {
            str(raw_key): _normalize_json(child, str(raw_key))
            for raw_key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_json(child) for child in value]
    return value


def _copy_json_value(value: object) -> object:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _json_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _span_sort_key(item: Mapping[str, object], span_key: str, ref_key: str) -> tuple[int, int, str]:
    span = item.get(span_key)
    if isinstance(span, Mapping):
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int):
            return start, end, str(item.get(ref_key, ""))
    return 10**9, 10**9, str(item.get(ref_key, ""))


def _period_sort_key(item: Mapping[str, object]) -> tuple[int, int, str]:
    mention = item.get("mention")
    if isinstance(mention, Mapping) and isinstance(mention.get("start"), int):
        return int(mention["start"]), int(mention.get("end", 0)), str(item.get("period_ref", ""))
    return 10**9, 10**9, str(item.get("period_ref", ""))


def _required_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _required_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{label} must be a list")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be a positive integer")
    if isinstance(value, int) and value > 0:
        return value
    raise TypeError(f"{label} must be a positive integer")
