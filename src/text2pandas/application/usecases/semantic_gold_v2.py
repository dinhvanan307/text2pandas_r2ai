"""Pure contracts for prediction-blind Semantic Gold v2 packet preparation.

This module selects questions and creates blank reviewer templates. It never
imports a parser, retrieval component, candidate, answer, or model output.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from text2pandas.application.usecases.independent_gold import (
    canonical_jsonl,
    question_sha256,
)

FORBIDDEN_PREDICTION_FIELDS = frozenset(
    {
        "a6_output",
        "a6_selection",
        "answer",
        "answer_output",
        "abstention",
        "ast_prediction",
        "binder_output",
        "candidate_scores",
        "evidence",
        "known_parser_score",
        "model_answer",
        "model_ast",
        "model_output",
        "pandas_query",
        "parser_output",
        "parser_prediction",
        "predicted_answer",
        "predicted_semantic",
        "prediction",
        "retrieval_score",
        "retrieval_scores",
        "retrieval_candidates",
        "retrieval_output",
        "score",
        "selector_output",
        "trace",
        "v3_ast",
    }
)

RECORD_STATUSES = frozenset({"RESOLVED", "AMBIGUOUS", "UNRESOLVED"})
FIELD_STATUSES = frozenset((*RECORD_STATUSES, "NOT_APPLICABLE"))
OPERATIONS = frozenset(
    {
        "LOOKUP",
        "ADD",
        "SUBTRACT",
        "DIVIDE",
        "GROWTH",
        "PERCENT_CHANGE",
        "SUM",
        "AVERAGE",
        "COUNT",
        "MINIMUM",
        "MAXIMUM",
        "ARGMIN",
        "ARGMAX",
        "SELECT_AT_ARG",
        "FILTER",
        "MEDIAN",
        "OTHER",
    }
)
OPERAND_ROLES = frozenset(
    {
        "VALUE",
        "LEFT",
        "RIGHT",
        "MINUEND",
        "SUBTRAHEND",
        "NUMERATOR",
        "DENOMINATOR",
        "NEW",
        "OLD",
        "SUMMAND",
        "RANK_KEY",
        "PROJECTED_VALUE",
        "FILTER_OPERAND",
        "FILTER_THRESHOLD",
    }
)
BASIS_VALUES = frozenset({"CONSOLIDATED", "SEPARATE", "UNSPECIFIED"})
UNIT_DIMENSIONS = frozenset(
    {"MONEY", "PERCENT", "PERCENT_POINT", "RATIO", "COUNT", "SHARES", "UNKNOWN"}
)
UNIT_SCALE_EXPONENTS = frozenset({0, 3, 6, 9, 12, None})
OUTPUT_SHAPES = frozenset(
    {"SCALAR", "ENTITY", "PERIOD", "COUNT", "TABLE", "SET", "BOOLEAN", "OTHER"}
)
SEMANTIC_COMPONENT_FIELDS = (
    "entities",
    "metrics",
    "periods",
    "basis",
    "unit",
    "operation_tree",
    "output",
    "operands",
)
_ENUM_KEYS = frozenset(
    {
        "concept_status",
        "dimension",
        "node",
        "point",
        "record_status",
        "reported_or_derived",
        "resolution_status",
        "role",
        "semantic_role",
        "shape",
        "status",
        "value",
    }
)


@dataclass(frozen=True, slots=True)
class ProxyStratum:
    stratum_id: str
    quota: int
    patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticSelection:
    core: tuple[dict[str, object], ...]
    diagnostic: tuple[dict[str, object], ...]
    reserve: tuple[dict[str, object], ...]
    coverage: dict[str, object]

    @property
    def active(self) -> tuple[dict[str, object], ...]:
        return tuple(sorted((*self.core, *self.diagnostic), key=_row_qid))


def fold_question(value: str) -> str:
    """Normalize question text for sampling proxies, not semantic labels."""

    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9%/]+", " ", plain.replace("đ", "d")).strip()


def build_contamination_ledger(
    sources: Mapping[str, Sequence[Mapping[str, object]]],
    reasons: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """Build deterministic, auditable QID/source/reason contamination entries."""

    if set(sources) != set(reasons):
        raise ValueError("every contamination source must have exactly one reason")
    entries: set[tuple[int, str, str]] = set()
    for source, rows in sorted(sources.items()):
        default_reason = _required_text(reasons[source], f"reason:{source}")
        for row in rows:
            qid = record_qid(row)
            entry_source = _required_text(row.get("source", source), f"source:{qid}")
            entry_reason = _required_text(row.get("reason", default_reason), f"reason:{qid}")
            entries.add((qid, entry_source, entry_reason))
    return tuple(
        {"qid": qid, "source": source, "reason": reason}
        for qid, source, reason in sorted(entries)
    )


def record_qid(row: Mapping[str, object]) -> int:
    for field in ("qid", "question_id", "id"):
        value = row.get(field)
        if value is not None:
            return _positive_int(value, f"{field} qid")
    raise ValueError("contamination record has no qid/question_id/id")


def select_semantic_questions(
    questions: Iterable[Mapping[str, object]],
    *,
    contaminated_qids: frozenset[int],
    sampling: Mapping[str, object],
) -> SemanticSelection:
    """Select core, diagnostic and reserve cohorts without reading predictions."""

    raw_questions = list(questions)
    reject_prediction_fields(raw_questions, "question_source")
    reject_prediction_fields(sampling, "sampling_contract")
    source = _validated_questions(raw_questions)
    source_qids = {_row_qid(row) for row in source}
    unknown_contamination = contaminated_qids - source_qids
    if unknown_contamination:
        raise ValueError(
            f"contamination QIDs absent from question source: "
            f"{sorted(unknown_contamination)}"
        )
    eligible = [row for row in source if _row_qid(row) not in contaminated_qids]
    core_config = _mapping(sampling.get("headline_core"), "headline_core")
    diagnostic_config = _mapping(
        sampling.get("diagnostic_supplement"), "diagnostic_supplement"
    )
    reserve_config = _mapping(sampling.get("reserve"), "reserve")
    strata = _proxy_strata(diagnostic_config)

    core_count = _positive_int(core_config.get("records"), "headline core count")
    diagnostic_count = _positive_int(
        diagnostic_config.get("records"), "diagnostic count"
    )
    reserve_count = _positive_int(reserve_config.get("records"), "reserve count")
    total_needed = core_count + diagnostic_count + reserve_count
    if total_needed > len(eligible):
        raise ValueError(
            f"selection requires {total_needed} eligible records, found {len(eligible)}"
        )

    core_seed = _required_text(core_config.get("seed"), "headline core seed")
    core_ranked = _ranked(eligible, core_seed)
    core_qids = {_row_qid(row) for row in core_ranked[:core_count]}
    core = tuple(
        _selection_row(
            row,
            cohort="HEADLINE_CORE",
            seed=core_seed,
            primary_stratum=None,
            strata=strata,
        )
        for row in core_ranked[:core_count]
    )

    remaining = [row for row in eligible if _row_qid(row) not in core_qids]
    diagnostic_seed = _required_text(
        diagnostic_config.get("seed"), "diagnostic seed"
    )
    diagnostic_rows: list[dict[str, object]] = []
    diagnostic_qids: set[int] = set()
    stratum_coverage: dict[str, dict[str, int]] = {}
    primary_by_qid = {
        _row_qid(row): _primary_stratum(str(row["question"]), strata)
        for row in remaining
    }
    for stratum in strata:
        candidates = [
            row
            for row in remaining
            if _row_qid(row) not in diagnostic_qids
            and primary_by_qid[_row_qid(row)] == stratum.stratum_id
        ]
        ranked = _ranked(candidates, f"{diagnostic_seed}:{stratum.stratum_id}")
        chosen = ranked[: stratum.quota]
        for row in chosen:
            diagnostic_qids.add(_row_qid(row))
            diagnostic_rows.append(
                _selection_row(
                    row,
                    cohort="DIAGNOSTIC_SUPPLEMENT",
                    seed=f"{diagnostic_seed}:{stratum.stratum_id}",
                    primary_stratum=stratum.stratum_id,
                    strata=strata,
                )
            )
        stratum_coverage[stratum.stratum_id] = {
            "available_proxy": len(candidates),
            "target": stratum.quota,
            "selected": len(chosen),
        }

    if len(diagnostic_rows) != diagnostic_count:
        raise ValueError(
            "diagnostic primary quotas must fill the exact diagnostic record target"
        )

    diagnostic = tuple(sorted(diagnostic_rows, key=_row_qid))
    used = core_qids | diagnostic_qids
    reserve_seed = _required_text(reserve_config.get("seed"), "reserve seed")
    reserve_candidates = [row for row in eligible if _row_qid(row) not in used]
    reserve_ranked = _ranked(reserve_candidates, reserve_seed)[:reserve_count]
    reserve = tuple(
        _selection_row(
            row,
            cohort="RESERVE",
            seed=reserve_seed,
            primary_stratum=None,
            strata=strata,
        )
        for row in reserve_ranked
    )

    all_qids = [
        _row_qid(row) for row in (*core, *diagnostic, *reserve)
    ]
    if len(all_qids) != len(set(all_qids)):
        raise AssertionError("semantic selection cohorts overlap")
    if contaminated_qids & set(all_qids):
        raise AssertionError("contaminated QID leaked into semantic selection")

    coverage: dict[str, object] = {
        "schema_version": 1,
        "source_records": len(source),
        "contaminated_records": len(contaminated_qids),
        "eligible_records": len(eligible),
        "headline_core_records": len(core),
        "diagnostic_records": len(diagnostic),
        "reserve_records": len(reserve),
        "strata": stratum_coverage,
        "selection_uses_predictions": False,
        "model_outputs_included": False,
        "authority": {
            "algorithm": "SHA256(seed + NUL + qid + NUL + question)",
            "sort": ["selection_digest", "qid"],
            "seeds": {
                "headline_core": core_seed,
                "diagnostic_supplement": diagnostic_seed,
                "reserve": reserve_seed,
            },
            "source_universe_sha256": _rows_sha256(source),
            "eligible_universe_sha256": _rows_sha256(eligible),
            "excluded_qids": sorted(contaminated_qids),
            "excluded_qids_sha256": _canonical_value_sha256(
                sorted(contaminated_qids)
            ),
            "selected": {
                "headline_core": _selected_digests(core),
                "diagnostic_supplement": _selected_digests(diagnostic),
                "reserve": _selected_digests(reserve),
            },
        },
    }
    return SemanticSelection(core, diagnostic, reserve, coverage)


def validate_phase1_5_sampling_contract(sampling: Mapping[str, object]) -> None:
    """Fail closed when the tracked WP2 sampling design drifts from the plan."""

    reject_prediction_fields(sampling, "sampling_contract")
    core = _mapping(sampling.get("headline_core"), "headline_core")
    diagnostic = _mapping(
        sampling.get("diagnostic_supplement"), "diagnostic_supplement"
    )
    reserve = _mapping(sampling.get("reserve"), "reserve")
    expected_counts = (
        (core, "headline core", 100),
        (diagnostic, "diagnostic", 20),
        (reserve, "reserve", 30),
    )
    for config, label, expected in expected_counts:
        actual = _positive_int(config.get("records"), f"{label} records")
        if actual != expected:
            raise ValueError(f"{label} records must equal {expected}, found {actual}")
    expected_methods = {
        "headline core": (core, "sha256_hash_order_equal_probability"),
        "diagnostic": (diagnostic, "question_text_proxy_stratified"),
        "reserve": (reserve, "sha256_hash_order_equal_probability"),
    }
    for method_label, (method_config, expected_method) in expected_methods.items():
        actual_method = _required_text(
            method_config.get("method"), f"{method_label} method"
        )
        if actual_method != expected_method:
            raise ValueError(
                f"{method_label} method must equal {expected_method}, "
                f"found {actual_method}"
            )
    expected_quotas = {
        "DIVIDE_EXPLICIT_RATIO": 4,
        "SUBTRACT_DIRECTIONAL": 3,
        "GROWTH_PERCENT_CHANGE": 2,
        "ARG_SELECT_PROJECT": 3,
        "NESTED_COMPOSED": 3,
        "MULTI_ENTITY_DIRECTIONAL": 2,
        "COUNT": 1,
        "BASIS_SENSITIVE": 1,
        "UNIT_SCALE_SENSITIVE": 1,
    }
    actual_quotas = {item.stratum_id: item.quota for item in _proxy_strata(diagnostic)}
    if actual_quotas != expected_quotas:
        raise ValueError(
            f"diagnostic primary quotas differ from Phase 1.5 plan: {actual_quotas}"
        )
    if sum(actual_quotas.values()) != 20:
        raise ValueError("diagnostic primary quotas must sum to 20")


def annotation_templates(
    selected: Sequence[Mapping[str, object]],
    *,
    reviewer_slot: str,
    contract_hashes: Mapping[str, str],
) -> tuple[dict[str, object], ...]:
    """Create blank, prediction-free A/B/C semantic annotation templates."""

    if reviewer_slot not in {"A", "B", "C"}:
        raise ValueError("reviewer_slot must be A, B or C")
    required_hashes = {
        "guideline_version",
        "guideline_sha256",
        "metric_vocabulary_sha256",
        "operation_vocabulary_sha256",
    }
    if set(contract_hashes) != required_hashes:
        raise ValueError("contract hashes are incomplete or contain unknown keys")
    rows: list[dict[str, object]] = []
    for selected_row in sorted(selected, key=_row_qid):
        row = {
            "schema_version": 2,
            "qid": _row_qid(selected_row),
            "question": str(selected_row["question"]),
            "question_sha256": str(selected_row["question_sha256"]),
            "cohort": str(selected_row["cohort"]),
            "selection_digest": str(selected_row["selection_digest"]),
            "primary_stratum": selected_row.get("primary_stratum"),
            "secondary_tags": _string_list(
                selected_row.get("secondary_tags", []), "secondary_tags"
            ),
            "reviewer_slot": reviewer_slot,
            "reviewer_id": None,
            "attestations": {
                "independent_of_model_development": None,
                "blind_to_model_outputs": None,
                "source_evidence_reviewed": None,
                **dict(contract_hashes),
            },
            "record_status": None,
            "entities": [],
            "metrics": [],
            "periods": [],
            "basis": None,
            "unit": None,
            "operation_tree": None,
            "output": None,
            "operands": [],
            "field_status": {},
            "source_evidence": [],
            "ambiguity_alternatives": [],
            "adjudication": None,
            "notes": None,
        }
        reject_prediction_fields(row, f"template:{reviewer_slot}:{row['qid']}")
        rows.append(row)
    return tuple(rows)


def validate_reviewer_governance(
    reviewers: Mapping[str, object],
    attestations: Mapping[str, Mapping[str, object]],
) -> None:
    """Validate the A/B/C identity and attestation contract without assigning it."""

    slots = ("A", "B", "C")
    identities = [
        _required_text(reviewers.get(slot), f"reviewer {slot}") for slot in slots
    ]
    if any(identity == "UNASSIGNED" for identity in identities):
        raise ValueError("reviewer roster is not assigned")
    if len(set(identities)) != len(identities):
        raise ValueError("reviewer A, reviewer B and adjudicator C must be distinct")
    required_true = {
        "independent_of_model_development",
        "blind_to_model_outputs",
        "source_evidence_reviewed",
    }
    required_text = {
        "guideline_version",
        "guideline_sha256",
        "metric_vocabulary_sha256",
        "operation_vocabulary_sha256",
    }
    if set(attestations) != set(slots):
        raise ValueError("attestations must be present for reviewer A, B and C")
    observed_bindings: set[tuple[str, str, str, str]] = set()
    for slot in slots:
        attestation = attestations[slot]
        missing = (required_true | required_text) - set(attestation)
        if missing:
            raise ValueError(f"reviewer {slot} missing attestations: {sorted(missing)}")
        for field in required_true:
            if attestation[field] is not True:
                raise ValueError(f"reviewer {slot} attestation {field} must be true")
        _required_text(attestation["guideline_version"], "guideline version")
        for field in required_text - {"guideline_version"}:
            value = _required_text(attestation[field], f"reviewer {slot} {field}")
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"reviewer {slot} {field} must be a SHA-256")
        observed_bindings.add(
            (
                str(attestation["guideline_version"]),
                str(attestation["guideline_sha256"]),
                str(attestation["metric_vocabulary_sha256"]),
                str(attestation["operation_vocabulary_sha256"]),
            )
        )
    if len(observed_bindings) != 1:
        raise ValueError("reviewer guideline/vocabulary contract bindings differ")


def validate_annotation_record(
    record: Mapping[str, object], *, require_complete: bool = False
) -> None:
    """Validate semantic relations that JSON Schema cannot express."""

    reject_prediction_fields(record, f"annotation:{record.get('qid')}")
    if "full_frame" in record:
        raise ValueError("annotators must not supply a manual full_frame")
    question = _required_text(record.get("question"), "question")
    if unicodedata.normalize("NFC", question) != question:
        raise ValueError("question must be Unicode NFC")
    expected_question_hash = question_sha256(question)
    if record.get("question_sha256") != expected_question_hash:
        raise ValueError("question_sha256 does not match question")
    status = record.get("record_status")
    if status is not None and status not in RECORD_STATUSES:
        raise ValueError(f"invalid record status: {status}")
    if require_complete and status is None:
        raise ValueError("completed annotation requires record_status")

    raw_field_status = _mapping(record.get("field_status"), "field_status")
    unknown_fields = set(raw_field_status) - set(SEMANTIC_COMPONENT_FIELDS)
    if unknown_fields:
        raise ValueError(f"unknown field_status keys: {sorted(unknown_fields)}")
    for field, field_value in raw_field_status.items():
        if field_value not in FIELD_STATUSES:
            raise ValueError(f"invalid field status for {field}: {field_value}")
        if field_value == "NOT_APPLICABLE" and not _empty_component(record.get(field)):
            raise ValueError(f"NOT_APPLICABLE field must be empty: {field}")
    if require_complete:
        missing_status = set(SEMANTIC_COMPONENT_FIELDS) - set(raw_field_status)
        if missing_status:
            raise ValueError(f"completed annotation missing field status: {sorted(missing_status)}")

    entities = _mapping_rows(record.get("entities"), "entities")
    metrics = _mapping_rows(record.get("metrics"), "metrics")
    periods = _mapping_rows(record.get("periods"), "periods")
    operands = _mapping_rows(record.get("operands"), "operands")
    _validate_spanned_rows(entities, "mention", "entity_ref", question, "entity")
    _validate_spanned_rows(metrics, "phrase", "metric_ref", question, "metric")

    entity_refs = _unique_refs(entities, "entity_ref", "entity")
    metric_refs = _unique_refs(metrics, "metric_ref", "metric")
    period_refs = _unique_refs(periods, "period_ref", "period")
    operand_refs = _unique_refs(operands, "operand_ref", "operand")
    for metric in metrics:
        concept_status = metric.get("concept_status")
        if concept_status not in RECORD_STATUSES:
            raise ValueError(f"invalid metric concept status: {concept_status}")
        concept_id = metric.get("concept_id")
        if concept_status == "RESOLVED" and not str(concept_id or "").strip():
            raise ValueError("resolved metric requires concept_id")
    for operand in operands:
        role = str(operand.get("role", "")).upper()
        if role not in OPERAND_ROLES:
            raise ValueError(f"invalid operand role: {operand.get('role')}")
        _validate_optional_ref(operand.get("entity_ref"), entity_refs, "entity")
        _validate_optional_ref(operand.get("metric_ref"), metric_refs, "metric")
        _validate_optional_ref(operand.get("period_ref"), period_refs, "period")
        _validate_basis(operand.get("basis"), allow_none=True)
        _validate_unit(operand.get("unit"), allow_none=True)

    _validate_basis(record.get("basis"), allow_none=not require_complete)
    _validate_unit(record.get("unit"), allow_none=not require_complete)
    output = record.get("output")
    if output is None:
        if require_complete and raw_field_status.get("output") != "NOT_APPLICABLE":
            raise ValueError("completed applicable output is missing")
    else:
        output_map = _mapping(output, "output")
        shape = str(output_map.get("shape", "")).upper()
        if shape not in OUTPUT_SHAPES:
            raise ValueError(f"invalid output shape: {output_map.get('shape')}")

    operation_tree = record.get("operation_tree")
    tree_refs: list[str] = []
    if operation_tree is not None:
        _validate_operation_tree(operation_tree, operand_refs, tree_refs)
    elif require_complete and raw_field_status.get("operation_tree") != "NOT_APPLICABLE":
        raise ValueError("completed applicable operation_tree is missing")
    if operation_tree is not None and set(tree_refs) != operand_refs:
        missing = sorted(operand_refs - set(tree_refs))
        extra = sorted(set(tree_refs) - operand_refs)
        raise ValueError(f"operation tree/operand mismatch: missing={missing}, extra={extra}")


def canonical_semantic_frame(record: Mapping[str, object]) -> dict[str, object]:
    """Derive one deterministic full frame from annotated components."""

    validate_annotation_record(record)
    field_status = _mapping(record.get("field_status"), "field_status")
    components: dict[str, object] = {}
    for field in SEMANTIC_COMPONENT_FIELDS:
        if field_status.get(field) == "NOT_APPLICABLE":
            continue
        if field not in record:
            raise ValueError(f"missing applicable semantic component: {field}")
        value = record[field]
        if field in {"entities", "metrics", "periods"}:
            ref_field = {
                "entities": "entity_ref",
                "metrics": "metric_ref",
                "periods": "period_ref",
            }[field]
            rows = _mapping_rows(value, field)
            value = sorted(rows, key=lambda row: str(row.get(ref_field, "")))
        components[field] = _canonicalize_component(value)
    applicable_status = {
        str(field): str(value).upper()
        for field, value in sorted(field_status.items())
        if value != "NOT_APPLICABLE"
    }
    return {
        "schema_version": 2,
        "record_status": _canonicalize_component(record.get("record_status"), "record_status"),
        "field_status": applicable_status,
        "components": components,
    }


def assert_full_frame_matches_components(
    record: Mapping[str, object], supplied_full_frame: Mapping[str, object]
) -> None:
    """Reject a manually supplied frame that differs from derived components."""

    derived = canonical_semantic_frame(record)
    supplied = _canonicalize_component(supplied_full_frame)
    if supplied != derived:
        raise ValueError("full-frame/component mismatch")


def reject_prediction_fields(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = FORBIDDEN_PREDICTION_FIELDS & {str(key) for key in value}
        if forbidden:
            raise ValueError(
                f"prediction field leaked into blinded semantic packet: "
                f"{label}:{sorted(forbidden)}"
            )
        for child in value.values():
            reject_prediction_fields(child, label)
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for child in value:
            reject_prediction_fields(child, label)


def canonical_packet_jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return canonical_jsonl(rows)


def _validate_spanned_rows(
    rows: Sequence[Mapping[str, object]],
    span_field: str,
    ref_field: str,
    question: str,
    label: str,
) -> None:
    ordering: list[tuple[int, int, str]] = []
    for row in rows:
        span = _mapping(row.get(span_field), f"{label} span")
        text = _required_text(span.get("text"), f"{label} span text")
        if unicodedata.normalize("NFC", text) != text:
            raise ValueError(f"{label} span text must be Unicode NFC")
        start = _nonnegative_int(span.get("start"), f"{label} span start")
        end = _nonnegative_int(span.get("end"), f"{label} span end")
        if end <= start:
            raise ValueError(f"{label} span end must be greater than start")
        if end > len(question):
            raise ValueError(f"{label} span exceeds question length")
        if unicodedata.normalize("NFC", question[start:end]) != text:
            raise ValueError(f"{label} span does not match question occurrence")
        ordering.append((start, end, _required_text(row.get(ref_field), ref_field)))
    if ordering != sorted(ordering):
        raise ValueError(f"unstable {label} span ordering")


def _unique_refs(
    rows: Sequence[Mapping[str, object]], ref_field: str, label: str
) -> set[str]:
    refs = [_required_text(row.get(ref_field), f"{label} ref") for row in rows]
    if len(refs) != len(set(refs)):
        raise ValueError(f"duplicate {label} ref")
    return set(refs)


def _validate_optional_ref(value: object, valid: set[str], label: str) -> None:
    if value is None:
        return
    ref = _required_text(value, f"operand {label} ref")
    if ref not in valid:
        raise ValueError(f"invalid operand {label} reference: {ref}")


def _validate_basis(value: object, *, allow_none: bool) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError("basis is required")
    basis = _mapping(value, "basis")
    basis_value = str(basis.get("value", "")).upper()
    if basis_value not in BASIS_VALUES:
        raise ValueError(f"invalid basis: {basis.get('value')}")
    explicit = basis.get("explicit")
    if not isinstance(explicit, bool):
        raise TypeError("basis explicit must be boolean")
    if not explicit and basis_value != "UNSPECIFIED":
        raise ValueError("implicit basis must be UNSPECIFIED")
    if explicit and basis_value == "UNSPECIFIED":
        raise ValueError("explicit basis cannot be UNSPECIFIED")


def _validate_unit(value: object, *, allow_none: bool) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError("unit is required")
    unit = _mapping(value, "unit")
    dimension = str(unit.get("dimension", "")).upper()
    if dimension not in UNIT_DIMENSIONS:
        raise ValueError(f"invalid unit dimension: {unit.get('dimension')}")
    scale = unit.get("scale_exponent")
    if scale not in UNIT_SCALE_EXPONENTS:
        raise ValueError(f"invalid unit scale exponent: {scale}")
    if dimension != "MONEY" and scale is not None:
        raise ValueError("non-money unit scale_exponent must be null")
    if dimension == "MONEY" and scale is None:
        raise ValueError("money unit requires scale_exponent")
    explicit = unit.get("explicit")
    if not isinstance(explicit, bool):
        raise TypeError("unit explicit must be boolean")


def _validate_operation_tree(
    value: object, operand_refs: set[str], observed_refs: list[str]
) -> None:
    tree = _mapping(value, "operation_tree")
    node = str(tree.get("node", "")).upper()
    if node not in OPERATIONS:
        raise ValueError(f"invalid operation: {tree.get('node')}")
    raw_operands = tree.get("operands", [])
    if not isinstance(raw_operands, Sequence) or isinstance(raw_operands, (str, bytes)):
        raise TypeError("operation_tree operands must be a list")
    for raw_ref in raw_operands:
        ref = _required_text(raw_ref, "operation operand ref")
        if ref not in operand_refs:
            raise ValueError(f"invalid operation operand reference: {ref}")
        observed_refs.append(ref)
    raw_children = tree.get("children", [])
    if not isinstance(raw_children, Sequence) or isinstance(raw_children, (str, bytes)):
        raise TypeError("operation_tree children must be a list")
    for child in raw_children:
        _validate_operation_tree(child, operand_refs, observed_refs)


def _mapping_rows(value: object, label: str) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a list")
    return [_mapping(row, f"{label} row") for row in value]


def _empty_component(value: object) -> bool:
    return value is None or value == [] or value == {}


def _canonicalize_component(value: object, key: str | None = None) -> object:
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        return normalized.upper() if key in _ENUM_KEYS else normalized
    if isinstance(value, Mapping):
        return {
            str(child_key): _canonicalize_component(child, str(child_key))
            for child_key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonicalize_component(child) for child in value]
    return value


def _selected_digests(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {"qid": _row_qid(row), "selection_digest": str(row["selection_digest"])}
        for row in rows
    ]


def _rows_sha256(rows: Sequence[Mapping[str, object]]) -> str:
    ordered = sorted(rows, key=_row_qid)
    return hashlib.sha256(canonical_packet_jsonl(ordered)).hexdigest()


def _canonical_value_sha256(value: object) -> str:
    content = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _validated_questions(
    questions: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    seen: set[int] = set()
    for raw in questions:
        qid = record_qid(raw)
        question = _required_text(raw.get("question"), f"question text:{qid}")
        if qid in seen:
            raise ValueError(f"duplicate source qid: {qid}")
        seen.add(qid)
        output.append({"qid": qid, "question": question})
    if not output:
        raise ValueError("question source is empty")
    return output


def _proxy_strata(config: Mapping[str, object]) -> tuple[ProxyStratum, ...]:
    raw_strata = config.get("strata")
    if not isinstance(raw_strata, Sequence) or isinstance(raw_strata, (str, bytes)):
        raise TypeError("diagnostic strata must be a list")
    output: list[ProxyStratum] = []
    seen: set[str] = set()
    for raw in raw_strata:
        value = _mapping(raw, "diagnostic stratum")
        stratum_id = _required_text(value.get("id"), "diagnostic stratum id")
        if stratum_id in seen:
            raise ValueError(f"duplicate diagnostic stratum: {stratum_id}")
        seen.add(stratum_id)
        raw_patterns = value.get("patterns_any")
        if not isinstance(raw_patterns, Sequence) or isinstance(
            raw_patterns, (str, bytes)
        ):
            raise TypeError(f"patterns_any must be a list: {stratum_id}")
        patterns = tuple(_required_text(item, f"pattern:{stratum_id}") for item in raw_patterns)
        for pattern in patterns:
            re.compile(pattern)
        output.append(
            ProxyStratum(
                stratum_id=stratum_id,
                quota=_positive_int(value.get("quota"), f"quota:{stratum_id}"),
                patterns=patterns,
            )
        )
    return tuple(output)


def _selection_row(
    row: Mapping[str, object],
    *,
    cohort: str,
    seed: str,
    primary_stratum: str | None,
    strata: Sequence[ProxyStratum],
) -> dict[str, object]:
    qid = _row_qid(row)
    question = str(row["question"])
    return {
        "schema_version": 2,
        "qid": qid,
        "question": question,
        "question_sha256": question_sha256(question),
        "cohort": cohort,
        "selection_digest": _selection_digest(seed, qid, question),
        "primary_stratum": primary_stratum,
        "secondary_tags": sorted(
            stratum.stratum_id
            for stratum in strata
            if _matches_proxy(question, stratum)
        ),
        "proxy_tags_are_gold": False,
    }


def _matches_proxy(question: str, stratum: ProxyStratum) -> bool:
    folded = fold_question(question)
    return any(re.search(pattern, folded) is not None for pattern in stratum.patterns)


def _primary_stratum(
    question: str, strata: Sequence[ProxyStratum]
) -> str | None:
    return next(
        (stratum.stratum_id for stratum in strata if _matches_proxy(question, stratum)),
        None,
    )


def _ranked(
    rows: Sequence[Mapping[str, object]], seed: str
) -> list[Mapping[str, object]]:
    return sorted(
        rows,
        key=lambda row: (
            _selection_digest(seed, _row_qid(row), str(row["question"])),
            _row_qid(row),
        ),
    )


def _selection_digest(seed: str, qid: int, question: str) -> str:
    return hashlib.sha256(f"{seed}\0{qid}\0{question}".encode("utf-8")).hexdigest()


def _row_qid(row: Mapping[str, object]) -> int:
    return _positive_int(row.get("qid"), "selected qid")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a list")
    return [str(item) for item in value]


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value)
    else:
        raise TypeError(f"{label} must be an integer")
    if result <= 0:
        raise ValueError(f"{label} must be positive")
    return result


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.strip().isdigit():
        result = int(value)
    else:
        raise TypeError(f"{label} must be an integer")
    if result < 0:
        raise ValueError(f"{label} must be non-negative")
    return result
