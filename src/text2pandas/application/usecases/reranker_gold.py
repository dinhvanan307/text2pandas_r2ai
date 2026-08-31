"""Prediction-blind review contracts for the sealed reranker held-out cohort."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RerankerGoldRelease:
    records: tuple[dict[str, Any], ...]
    disagreement_records: int


def reranker_review_templates(
    questions: Sequence[Mapping[str, object]], *, reviewer_slot: str
) -> tuple[dict[str, object], ...]:
    if reviewer_slot not in {"A", "B", "C"}:
        raise ValueError("reviewer_slot must be A, B or C")
    identity_field = "adjudicator_id" if reviewer_slot == "C" else "annotator_id"
    return tuple(
        {
            "schema_version": 1,
            "id": _qid(row),
            "question": str(row.get("question") or ""),
            "question_sha256": _question_sha(str(row.get("question") or "")),
            "reviewer_slot": reviewer_slot,
            identity_field: None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "gold_table_uids": None,
            **(
                {"reviewed_disagreement": None}
                if reviewer_slot == "C"
                else {}
            ),
            "notes": None,
        }
        for row in sorted(questions, key=_qid)
    )


def seal_reranker_gold(
    pass_a: Sequence[Mapping[str, object]],
    pass_b: Sequence[Mapping[str, object]],
    adjudication: Sequence[Mapping[str, object]],
    *,
    expected_qids: Sequence[int],
    expected_question_sha256: Mapping[int, str] | None = None,
) -> RerankerGoldRelease:
    expected = tuple(sorted(int(value) for value in expected_qids))
    a = _index(pass_a, expected, "A")
    b = _index(pass_b, expected, "B")
    c = _index(adjudication, expected, "C")
    reviewer_a = _single_reviewer(a, "annotator_id", "A")
    reviewer_b = _single_reviewer(b, "annotator_id", "B")
    adjudicator = _single_reviewer(c, "adjudicator_id", "C")
    if len({reviewer_a, reviewer_b, adjudicator}) != 3:
        raise ValueError("reviewer identities must be globally distinct")
    output: list[dict[str, Any]] = []
    disagreements = 0
    for qid in expected:
        row_a, row_b, row_c = a[qid], b[qid], c[qid]
        identities = (
            _identity(row_a, "annotator_id", f"A:{qid}"),
            _identity(row_b, "annotator_id", f"B:{qid}"),
            _identity(row_c, "adjudicator_id", f"C:{qid}"),
        )
        for label, row in (("A", row_a), ("B", row_b), ("C", row_c)):
            if row.get("independent_of_model_development") is not True:
                raise ValueError(f"missing independence attestation: {label}:{qid}")
            if row.get("source_evidence_reviewed") is not True:
                raise ValueError(f"source evidence was not reviewed: {label}:{qid}")
        hashes = {str(row.get("question_sha256") or "") for row in (row_a, row_b, row_c)}
        if "" in hashes or len(hashes) != 1:
            raise ValueError(f"question checksum disagreement: {qid}")
        question_hash = next(iter(hashes))
        if any(
            _question_sha(str(row.get("question") or "")) != question_hash
            for row in (row_a, row_b, row_c)
        ):
            raise ValueError(f"question text checksum mismatch: {qid}")
        if (
            expected_question_sha256 is not None
            and expected_question_sha256.get(qid) != question_hash
        ):
            raise ValueError(f"question differs from sealed packet: {qid}")
        gold_a = _table_uids(row_a, qid)
        gold_b = _table_uids(row_b, qid)
        gold_c = _table_uids(row_c, qid)
        disagreed = len({gold_a, gold_b, gold_c}) > 1
        if disagreed and row_c.get("reviewed_disagreement") is not True:
            raise ValueError(f"unreviewed evidence disagreement: {qid}")
        disagreements += disagreed
        output.append(
            {
                "id": qid,
                "gold_table_uids": list(gold_c),
                "annotators": [identities[0], identities[1]],
                "adjudicator": identities[2],
                "question_sha256": next(iter(hashes)),
                "source_evidence_reviewed": True,
                "disagreement": disagreed,
            }
        )
    return RerankerGoldRelease(tuple(output), disagreements)


def _index(
    rows: Sequence[Mapping[str, object]], expected: tuple[int, ...], slot: str
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = _qid(row)
        if qid in output:
            raise ValueError(f"duplicate review qid: {qid}")
        if row.get("reviewer_slot") != slot:
            raise ValueError(f"wrong reviewer slot: {qid}:{row.get('reviewer_slot')}")
        output[qid] = row
    if tuple(sorted(output)) != expected:
        raise ValueError(f"review qids do not match sealed selection: {slot}")
    return output


def _table_uids(row: Mapping[str, object], qid: int) -> tuple[str, ...]:
    raw = row.get("gold_table_uids")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"gold_table_uids must be a non-empty list: {qid}")
    values = tuple(dict.fromkeys(str(value).strip() for value in raw if str(value).strip()))
    if not values:
        raise ValueError(f"gold_table_uids must contain non-empty IDs: {qid}")
    return values


def _identity(row: Mapping[str, object], field: str, label: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise ValueError(f"missing reviewer identity: {label}")
    return value


def _single_reviewer(
    rows: Mapping[int, Mapping[str, object]], field: str, slot: str
) -> str:
    identities = {_identity(row, field, f"{slot}:{qid}") for qid, row in rows.items()}
    if len(identities) != 1:
        raise ValueError(f"reviewer identity must be stable for slot {slot}")
    return next(iter(identities))


def _qid(row: Mapping[str, object]) -> int:
    value = row.get("id", row.get("qid"))
    if isinstance(value, bool):
        raise TypeError("qid must be an integer")
    try:
        qid = int(str(value))
    except (TypeError, ValueError) as error:
        raise TypeError("qid must be an integer") from error
    if qid < 1:
        raise ValueError("qid must be positive")
    return qid


def _question_sha(question: str) -> str:
    return hashlib.sha256(question.encode("utf-8")).hexdigest()
