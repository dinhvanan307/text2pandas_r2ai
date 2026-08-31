"""Prediction-blind review contracts for the Semantic Parser Wave 6 gate."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from text2pandas.application.usecases.independent_gold import question_sha256

STRUCTURAL_STATUSES = frozenset({"OK", "AMBIGUOUS", "UNRESOLVED"})
COMPLEXITY_CLASSES = frozenset(
    {"direct", "derived", "filtered", "aggregated", "ranked", "compositional"}
)
AMBIGUITY_STATUSES = frozenset({"NONE", "AMBIGUOUS", "UNRESOLVED"})
COMPOSITION_FRAME_FIELDS = (
    "entity_domain",
    "period_domain",
    "basis",
    "metric_mentions",
    "predicate_clauses",
    "logical_connectors",
    "temporal_transforms",
    "projection",
    "aggregate",
    "rank",
    "operation_order",
    "expected_ast",
    "output_dimension",
    "ambiguity",
)
FORBIDDEN_MODEL_FIELDS = frozenset(
    {
        "model_answer",
        "model_ast",
        "model_candidate",
        "model_candidates",
        "model_prediction",
        "candidate_scores",
        "parser_output",
        "primary_reason",
        "primary_status",
    }
)


@dataclass(frozen=True, slots=True)
class SemanticParserReviewAudit:
    expected_records: int
    annotator_a_complete: int
    annotator_b_complete: int
    adjudication_complete: int
    reviewer_ids: tuple[str, ...]
    blockers: tuple[str, ...]

    @property
    def sealable(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "kind": "text2pandas.semantic_parser_review_audit",
            "status": "READY_TO_SEAL" if self.sealable else "BLOCKED_PENDING_HUMAN_REVIEW",
            "sealable": self.sealable,
            "expected_records": self.expected_records,
            "completion": {
                "annotator_a": self.annotator_a_complete,
                "annotator_b": self.annotator_b_complete,
                "adjudication": self.adjudication_complete,
            },
            "reviewer_ids": list(self.reviewer_ids),
            "blockers": list(self.blockers),
        }


def semantic_parser_annotation_templates(
    scope: Sequence[Mapping[str, object]], *, annotator_slot: str
) -> tuple[dict[str, object], ...]:
    """Create A/B templates containing questions and no model predictions."""

    if annotator_slot not in {"A", "B"}:
        raise ValueError("annotator_slot must be A or B")
    return tuple(
        {
            **_scope_identity(row),
            "kind": "text2pandas.semantic_parser_review_annotation",
            "annotator_slot": annotator_slot,
            "annotator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "structural_status": None,
            "complexity_class": None,
            "composition_frame": _empty_composition_frame(),
            "notes": None,
        }
        for row in _sorted_scope(scope)
    )


def semantic_parser_adjudication_templates(
    scope: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Create C templates without exposing either model output or reviewer decisions."""

    return tuple(
        {
            **_scope_identity(row),
            "kind": "text2pandas.semantic_parser_review_adjudication",
            "adjudicator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "reviewed_disagreement_fields": [],
            "structural_status": None,
            "complexity_class": None,
            "composition_frame": _empty_composition_frame(),
            "notes": None,
        }
        for row in _sorted_scope(scope)
    )


def audit_semantic_parser_review_packet(
    scope: Sequence[Mapping[str, object]],
    pass_a: Sequence[Mapping[str, object]],
    pass_b: Sequence[Mapping[str, object]],
    adjudication: Sequence[Mapping[str, object]],
) -> SemanticParserReviewAudit:
    """Fail closed on incompleteness, identity reuse, drift, or prediction leakage."""

    blockers: list[str] = []
    expected = _index(scope, "SCOPE", blockers)
    indexes = {
        "A": _index(pass_a, "A", blockers),
        "B": _index(pass_b, "B", blockers),
        "C": _index(adjudication, "C", blockers),
    }
    expected_qids = tuple(sorted(expected))
    if len(expected_qids) != len(scope):
        blockers.append("SCOPE_DUPLICATE_QIDS")
    for label, index in indexes.items():
        if tuple(sorted(index)) != expected_qids:
            blockers.append(f"{label}_QID_SET_MISMATCH")

    completion: dict[str, int] = {"A": 0, "B": 0, "C": 0}
    identities_by_slot: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    for label, index in indexes.items():
        identity_field = "adjudicator_id" if label == "C" else "annotator_id"
        for qid in expected_qids:
            row = index.get(qid)
            expected_row = expected[qid]
            if row is None:
                continue
            _audit_identity(row, expected_row, label, qid, blockers)
            leaked = sorted(_forbidden_fields(row))
            if leaked:
                blockers.append(f"{label}_MODEL_OUTPUT_LEAK:{qid}:{','.join(leaked)}")
            identity = str(row.get(identity_field) or "").strip()
            if identity:
                identities_by_slot[label].add(identity)
            if _review_complete(row, identity_field, adjudication=label == "C"):
                completion[label] += 1

    expected_count = len(expected_qids)
    for label, blocker_label in (
        ("A", "ANNOTATOR_A"),
        ("B", "ANNOTATOR_B"),
        ("C", "ADJUDICATION"),
    ):
        if completion[label] != expected_count:
            blockers.append(f"{blocker_label}_INCOMPLETE:{expected_count - completion[label]}")
        if len(identities_by_slot[label]) > 1:
            blockers.append(f"{label}_REVIEWER_ID_NOT_STABLE:{len(identities_by_slot[label])}")

    reviewer_ids = tuple(sorted(set().union(*identities_by_slot.values())))
    if any(len(values) != 1 for values in identities_by_slot.values()) or len(reviewer_ids) != 3:
        blockers.append(f"DISTINCT_REVIEWER_IDENTITIES_REQUIRED:{len(reviewer_ids)}:3")
    return SemanticParserReviewAudit(
        expected_records=expected_count,
        annotator_a_complete=completion["A"],
        annotator_b_complete=completion["B"],
        adjudication_complete=completion["C"],
        reviewer_ids=reviewer_ids,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _empty_composition_frame() -> dict[str, object]:
    return {
        "entity_domain": [],
        "period_domain": [],
        "basis": None,
        "metric_mentions": [],
        "predicate_clauses": [],
        "logical_connectors": [],
        "temporal_transforms": [],
        "projection": None,
        "aggregate": None,
        "rank": None,
        "operation_order": [],
        "expected_ast": None,
        "output_dimension": None,
        "ambiguity": {"status": None, "notes": None},
    }


def _scope_identity(row: Mapping[str, object]) -> dict[str, object]:
    question = str(row.get("question") or "")
    digest = str(row.get("question_sha256") or "")
    if not question or digest != question_sha256(question):
        raise ValueError(f"scope question checksum mismatch: {_qid(row)}")
    return {
        "schema_version": 1,
        "qid": _qid(row),
        "question": question,
        "question_sha256": digest,
        "family": str(row.get("family") or ""),
        "split": str(row.get("split") or ""),
    }


def _review_complete(row: Mapping[str, object], identity_field: str, *, adjudication: bool) -> bool:
    if not str(row.get(identity_field) or "").strip():
        return False
    if row.get("independent_of_model_development") is not True:
        return False
    if row.get("source_evidence_reviewed") is not True:
        return False
    if adjudication and not isinstance(row.get("reviewed_disagreement_fields"), list):
        return False
    status = row.get("structural_status")
    complexity = row.get("complexity_class")
    frame = row.get("composition_frame")
    if status not in STRUCTURAL_STATUSES or complexity not in COMPLEXITY_CLASSES:
        return False
    if not isinstance(frame, Mapping) or any(
        field not in frame for field in COMPOSITION_FRAME_FIELDS
    ):
        return False
    ambiguity = frame.get("ambiguity")
    if not isinstance(ambiguity, Mapping) or ambiguity.get("status") not in AMBIGUITY_STATUSES:
        return False
    for field in (
        "entity_domain",
        "period_domain",
        "metric_mentions",
        "predicate_clauses",
        "logical_connectors",
        "temporal_transforms",
        "operation_order",
    ):
        if not isinstance(frame.get(field), list):
            return False
    if status == "OK":
        if not isinstance(frame.get("expected_ast"), Mapping):
            return False
        if not str(frame.get("output_dimension") or "").strip():
            return False
        if ambiguity.get("status") != "NONE":
            return False
    elif ambiguity.get("status") == "NONE":
        return False
    return True


def _audit_identity(
    row: Mapping[str, object],
    expected: Mapping[str, object],
    label: str,
    qid: int,
    blockers: list[str],
) -> None:
    for field in ("question_sha256", "family", "split"):
        if row.get(field) != expected.get(field):
            blockers.append(f"{label}_{field.upper()}_MISMATCH:{qid}")
    question = row.get("question")
    if question is not None and str(question) != str(expected.get("question") or ""):
        blockers.append(f"{label}_QUESTION_MISMATCH:{qid}")


def _forbidden_fields(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold()
            if normalized in FORBIDDEN_MODEL_FIELDS or normalized.startswith("model_"):
                found.add(str(key))
            found.update(_forbidden_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_fields(child))
    return found


def _index(
    rows: Sequence[Mapping[str, object]], label: str, blockers: list[str]
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = _qid(row)
        if qid in output:
            blockers.append(f"{label}_DUPLICATE_QID:{qid}")
        output[qid] = row
    return output


def _sorted_scope(scope: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(scope, key=_qid)


def _qid(row: Mapping[str, object]) -> int:
    value = row.get("qid")
    if isinstance(value, bool):
        raise TypeError("qid must be a positive integer")
    try:
        qid = int(str(value))
    except (TypeError, ValueError) as error:
        raise TypeError("qid must be a positive integer") from error
    if qid < 1:
        raise ValueError("qid must be a positive integer")
    return qid
