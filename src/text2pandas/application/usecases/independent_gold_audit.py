"""Completeness audit for prediction-blind independent-gold review packets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from text2pandas.application.usecases.independent_gold import GOLD_FIELDS


@dataclass(frozen=True, slots=True)
class IndependentGoldAudit:
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


def audit_independent_gold_packet(
    selection: Sequence[Mapping[str, object]],
    pass_a: Sequence[Mapping[str, object]],
    pass_b: Sequence[Mapping[str, object]],
    adjudication: Sequence[Mapping[str, object]],
) -> IndependentGoldAudit:
    expected = tuple(sorted(_qid(row) for row in selection))
    blockers: list[str] = []
    if len(expected) != len(set(expected)):
        blockers.append("SELECTION_DUPLICATE_QIDS")
    indexes = {
        "A": _index(pass_a, blockers),
        "B": _index(pass_b, blockers),
        "ADJUDICATION": _index(adjudication, blockers),
    }
    for label, index in indexes.items():
        if tuple(sorted(index)) != expected:
            blockers.append(f"{label}_QID_SET_MISMATCH")

    a_complete = sum(_annotation_complete(indexes["A"].get(qid), "annotator_id") for qid in expected)
    b_complete = sum(_annotation_complete(indexes["B"].get(qid), "annotator_id") for qid in expected)
    c_complete = sum(
        _annotation_complete(indexes["ADJUDICATION"].get(qid), "adjudicator_id")
        and isinstance(indexes["ADJUDICATION"][qid].get("reviewed_disagreement_fields"), list)
        for qid in expected
    )
    for label, complete in (
        ("ANNOTATOR_A", a_complete),
        ("ANNOTATOR_B", b_complete),
        ("ADJUDICATION", c_complete),
    ):
        if complete != len(expected):
            blockers.append(f"{label}_INCOMPLETE:{len(expected) - complete}")

    identities = tuple(
        sorted(
            {
                identity
                for index, field in (
                    (indexes["A"], "annotator_id"),
                    (indexes["B"], "annotator_id"),
                    (indexes["ADJUDICATION"], "adjudicator_id"),
                )
                for row in index.values()
                if (identity := str(row.get(field) or "").strip())
            }
        )
    )
    if len(identities) < 3:
        blockers.append(f"DISTINCT_REVIEWER_IDENTITIES_REQUIRED:{len(identities)}:3")
    return IndependentGoldAudit(
        expected_records=len(expected),
        annotator_a_complete=a_complete,
        annotator_b_complete=b_complete,
        adjudication_complete=c_complete,
        reviewer_ids=identities,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _annotation_complete(row: Mapping[str, object] | None, identity_field: str) -> bool:
    if row is None or not str(row.get(identity_field) or "").strip():
        return False
    if row.get("independent_of_model_development") is not True:
        return False
    if row.get("source_evidence_reviewed") is not True:
        return False
    return all(isinstance(row.get(field), Mapping) for field in GOLD_FIELDS)


def _index(
    rows: Sequence[Mapping[str, object]], blockers: list[str]
) -> dict[int, Mapping[str, object]]:
    output: dict[int, Mapping[str, object]] = {}
    for row in rows:
        qid = _qid(row)
        if qid in output:
            blockers.append(f"DUPLICATE_REVIEW_QID:{qid}")
        output[qid] = row
    return output


def _qid(row: Mapping[str, object]) -> int:
    value = row.get("qid")
    if isinstance(value, bool):
        raise TypeError("qid must be an integer")
    try:
        qid = int(str(value))
    except (TypeError, ValueError) as error:
        raise TypeError("qid must be an integer") from error
    if qid < 1:
        raise ValueError("qid must be positive")
    return qid
