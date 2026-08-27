"""Governed contracts for independent answer, semantic and evidence gold."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

FORBIDDEN_MODEL_FIELDS = frozenset(
    {
        "candidate_scores",
        "model_answer",
        "model_ast",
        "model_output",
        "predicted_answer",
        "retrieval_scores",
    }
)
GOLD_FIELDS = ("answer", "semantic_parser", "evidence_binding")


@dataclass(frozen=True, slots=True)
class GoldReleaseValidation:
    records: tuple[dict[str, Any], ...]
    disagreements: int


def question_sha256(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()


def select_blinded_questions(
    questions: Iterable[Mapping[str, object]], *, seed: str, count: int
) -> tuple[dict[str, object], ...]:
    """Select questions by content hash without reading any model output."""

    rows: list[dict[str, object]] = []
    seen: set[int] = set()
    for item in questions:
        qid = int(item.get("id", item.get("qid", 0)))
        question = str(item.get("question", "")).strip()
        if qid <= 0 or not question:
            raise ValueError("every source question requires a positive id and text")
        if qid in seen:
            raise ValueError(f"duplicate source qid: {qid}")
        seen.add(qid)
        digest = hashlib.sha256(f"{seed}\0{qid}\0{question}".encode()).hexdigest()
        rows.append(
            {
                "qid": qid,
                "question": question,
                "question_sha256": question_sha256(question),
                "selection_digest": digest,
            }
        )
    if count <= 0 or count > len(rows):
        raise ValueError(f"selection count must be within 1..{len(rows)}")
    rows.sort(key=lambda row: (str(row["selection_digest"]), int(row["qid"])))
    return tuple(rows[:count])


def annotation_templates(
    selected: Sequence[Mapping[str, object]], *, annotator_slot: str
) -> tuple[dict[str, object], ...]:
    if annotator_slot not in {"A", "B"}:
        raise ValueError("annotator_slot must be A or B")
    return tuple(
        {
            "schema_version": 1,
            "qid": int(row["qid"]),
            "question": str(row["question"]),
            "question_sha256": str(row["question_sha256"]),
            "annotator_slot": annotator_slot,
            "annotator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "answer": None,
            "semantic_parser": None,
            "evidence_binding": None,
            "notes": None,
        }
        for row in sorted(selected, key=lambda value: int(value["qid"]))
    )


def adjudication_templates(
    selected: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "schema_version": 1,
            "qid": int(row["qid"]),
            "question_sha256": str(row["question_sha256"]),
            "adjudicator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "reviewed_disagreement_fields": [],
            "answer": None,
            "semantic_parser": None,
            "evidence_binding": None,
            "notes": None,
        }
        for row in sorted(selected, key=lambda value: int(value["qid"]))
    )


def validate_and_merge_release(
    pass_a: Sequence[Mapping[str, object]],
    pass_b: Sequence[Mapping[str, object]],
    adjudication: Sequence[Mapping[str, object]],
    *,
    expected_qids: Sequence[int],
) -> GoldReleaseValidation:
    """Validate dual annotation and distinct adjudication, then merge gold."""

    expected = tuple(sorted(int(value) for value in expected_qids))
    a = _index_rows(pass_a, expected, "A")
    b = _index_rows(pass_b, expected, "B")
    c = _index_rows(adjudication, expected, None)
    merged: list[dict[str, Any]] = []
    disagreement_count = 0
    for qid in expected:
        row_a, row_b, row_c = a[qid], b[qid], c[qid]
        _reject_model_fields(row_a, f"A:{qid}")
        _reject_model_fields(row_b, f"B:{qid}")
        _reject_model_fields(row_c, f"ADJUDICATION:{qid}")
        sha_values = {
            str(row_a.get("question_sha256", "")),
            str(row_b.get("question_sha256", "")),
            str(row_c.get("question_sha256", "")),
        }
        if "" in sha_values or len(sha_values) != 1:
            raise ValueError(f"question checksum disagreement: {qid}")
        annotator_a = _required_identity(row_a, "annotator_id", f"A:{qid}")
        annotator_b = _required_identity(row_b, "annotator_id", f"B:{qid}")
        adjudicator = _required_identity(row_c, "adjudicator_id", f"ADJUDICATION:{qid}")
        if len({annotator_a, annotator_b, adjudicator}) != 3:
            raise ValueError(f"review identities must be distinct: {qid}")
        for label, row in (("A", row_a), ("B", row_b), ("ADJUDICATION", row_c)):
            if row.get("independent_of_model_development") is not True:
                raise ValueError(f"missing independence attestation: {label}:{qid}")
            if row.get("source_evidence_reviewed") is not True:
                raise ValueError(f"source evidence was not reviewed: {label}:{qid}")
        disagreement_fields = tuple(
            field for field in GOLD_FIELDS if row_a.get(field) != row_b.get(field)
        )
        reviewed = {str(value) for value in row_c.get("reviewed_disagreement_fields", [])}
        if not set(disagreement_fields) <= reviewed:
            raise ValueError(f"unreviewed disagreement fields: {qid}:{disagreement_fields}")
        for field in GOLD_FIELDS:
            _validate_gold_value(field, row_c.get(field), qid)
        disagreement_count += bool(disagreement_fields)
        merged.append(
            {
                "schema_version": 1,
                "qid": qid,
                "question_sha256": next(iter(sha_values)),
                **{field: row_c[field] for field in GOLD_FIELDS},
                "provenance": {
                    "annotators": [annotator_a, annotator_b],
                    "adjudicator": adjudicator,
                    "disagreement_fields": list(disagreement_fields),
                    "source_evidence_reviewed": True,
                    "independence": "VERIFIED_BY_ATTESTATION",
                },
            }
        )
    return GoldReleaseValidation(tuple(merged), disagreement_count)


def canonical_jsonl(rows: Iterable[Mapping[str, object]]) -> bytes:
    return b"".join(
        (json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        for row in rows
    )


def _index_rows(
    rows: Sequence[Mapping[str, object]], expected: tuple[int, ...], slot: str | None
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = int(row.get("qid", 0))
        if qid in output:
            raise ValueError(f"duplicate annotation qid: {qid}")
        if slot is not None and row.get("annotator_slot") != slot:
            raise ValueError(f"wrong annotator slot: {qid}:{row.get('annotator_slot')}")
        output[qid] = row
    if tuple(sorted(output)) != expected:
        raise ValueError("annotation qids do not match the sealed selection")
    return output


def _required_identity(row: Mapping[str, object], field: str, label: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing reviewer identity: {label}")
    return value


def _reject_model_fields(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = FORBIDDEN_MODEL_FIELDS & {str(key) for key in value}
        if forbidden:
            raise ValueError(f"model output leaked into blinded gold: {label}:{sorted(forbidden)}")
        for child in value.values():
            _reject_model_fields(child, label)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _reject_model_fields(child, label)


def _validate_gold_value(field: str, value: object, qid: int) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"missing adjudicated {field}: {qid}")
    status = value.get("status")
    if status not in {"OK", "UNANSWERABLE"}:
        raise ValueError(f"invalid {field} status: {qid}:{status}")
    if status == "UNANSWERABLE":
        if not str(value.get("reason") or "").strip():
            raise ValueError(f"unanswerable {field} requires a reason: {qid}")
        return
    if field == "answer" and value.get("value") is None:
        raise ValueError(f"answer value is required: {qid}")
    if field == "semantic_parser" and not isinstance(value.get("ast"), Mapping):
        raise ValueError(f"semantic AST is required: {qid}")
    if field == "evidence_binding":
        operands = value.get("ordered_operands")
        if not isinstance(operands, list) or not operands:
            raise ValueError(f"ordered evidence operands are required: {qid}")
        for operand in operands:
            if not isinstance(operand, Mapping) or not str(
                operand.get("observation_uid") or ""
            ).strip():
                raise ValueError(f"evidence operand requires observation_uid: {qid}")
