"""Prediction-blind, deterministic review scope for Recovery Wave 5 Risk-A."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from text2pandas.application.usecases.independent_gold import question_sha256

Split = Literal["development", "holdout"]

DEFAULT_FAMILY_SPLIT: Mapping[str, tuple[int, int]] = {
    "direct_lookup": (5, 2),
    "direct_ratio": (6, 3),
    "two_period_difference": (7, 4),
    "single_metric_sum": (2, 1),
    "single_metric_average": (20, 10),
}

REQUIRED_OBSERVATION_FIELDS = (
    "metric_id",
    "source_metric_id",
    "source_metric_code",
    "observation_uid",
    "row_label",
    "row_path",
    "row_role",
    "column_path",
    "column_role",
    "entity",
    "basis",
    "period",
    "period_role",
    "sign_mode",
    "unit",
    "scale_exponent",
    "scale_source",
)


@dataclass(frozen=True, slots=True)
class RiskAReviewScope:
    records: tuple[dict[str, Any], ...]
    family_counts: Mapping[str, int]
    split_counts: Mapping[str, int]


def build_risk_a_review_scope(
    inventory: Sequence[Mapping[str, object]],
    questions: Mapping[int, str],
    *,
    seed: str,
    family_split: Mapping[str, tuple[int, int]] = DEFAULT_FAMILY_SPLIT,
) -> RiskAReviewScope:
    """Build the exact stratified dev/holdout split without reading predictions."""

    if not seed.strip():
        raise ValueError("review seed must be non-empty")
    eligible: dict[str, list[dict[str, Any]]] = {family: [] for family in family_split}
    seen: set[int] = set()
    for raw in inventory:
        qid = _positive_int(raw.get("qid"), "inventory qid")
        if qid in seen:
            raise ValueError(f"duplicate inventory qid: {qid}")
        seen.add(qid)
        triage = raw.get("triage")
        if not isinstance(triage, Mapping) or triage.get("risk_tier") != "A":
            continue
        family = str(triage.get("repair_class") or "")
        if family not in family_split:
            raise ValueError(f"unsupported Risk-A family: {qid}:{family}")
        question = questions.get(qid)
        if not question:
            raise ValueError(f"question text is missing: {qid}")
        question_digest = question_sha256(question)
        split_digest = hashlib.sha256(
            f"{seed}\0{family}\0{qid}\0{question_digest}".encode()
        ).hexdigest()
        eligible[family].append(
            {
                "qid": qid,
                "question": question,
                "question_sha256": question_digest,
                "family": family,
                "risk_tier": "A",
                "split_digest": split_digest,
            }
        )

    selected: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    for family, (development_count, holdout_count) in family_split.items():
        if development_count < 0 or holdout_count < 1:
            raise ValueError(f"invalid split quota for {family}")
        rows = sorted(
            eligible[family], key=lambda row: (row["split_digest"], row["qid"])
        )
        expected = development_count + holdout_count
        if len(rows) != expected:
            raise ValueError(
                f"Risk-A family count mismatch: {family}: expected={expected} actual={len(rows)}"
            )
        for index, row in enumerate(rows):
            split: Split = "development" if index < development_count else "holdout"
            selected.append({**row, "split": split})
            family_counts[family] += 1
            split_counts[split] += 1
    selected.sort(key=lambda row: row["qid"])
    return RiskAReviewScope(
        tuple(selected),
        dict(sorted(family_counts.items())),
        dict(sorted(split_counts.items())),
    )


def risk_a_annotation_templates(
    scope: Sequence[Mapping[str, object]], *, reviewer_slot: str
) -> tuple[dict[str, object], ...]:
    """Create role-complete A/B templates without model output fields."""

    if reviewer_slot not in {"A", "B"}:
        raise ValueError("reviewer_slot must be A or B")
    return tuple(
        {
            "schema_version": 1,
            "qid": _positive_int(row.get("qid"), "scope qid"),
            "question": str(row.get("question") or ""),
            "question_sha256": str(row.get("question_sha256") or ""),
            "family": str(row.get("family") or ""),
            "split": str(row.get("split") or ""),
            "annotator_slot": reviewer_slot,
            "annotator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "answer": None,
            "semantic_parser": None,
            "evidence_binding": {
                "status": None,
                "observations": [],
                "required_observation_fields": list(REQUIRED_OBSERVATION_FIELDS),
                "member_domain_complete": None,
                "operation_order": None,
                "source_tables": [],
                "source_documents": [],
            },
            "notes": None,
        }
        for row in sorted(scope, key=lambda value: _positive_int(value.get("qid"), "scope qid"))
    )


def risk_a_adjudication_templates(
    scope: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Create third-reviewer templates for field-level adjudication."""

    return tuple(
        {
            "schema_version": 1,
            "qid": _positive_int(row.get("qid"), "scope qid"),
            "question_sha256": str(row.get("question_sha256") or ""),
            "family": str(row.get("family") or ""),
            "split": str(row.get("split") or ""),
            "adjudicator_id": None,
            "independent_of_model_development": None,
            "source_evidence_reviewed": None,
            "reviewed_disagreement_fields": [],
            "decision": None,
            "answer": None,
            "semantic_parser": None,
            "evidence_binding": None,
            "notes": None,
        }
        for row in sorted(scope, key=lambda value: _positive_int(value.get("qid"), "scope qid"))
    )


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    raise TypeError(f"{label} must be a positive integer")
