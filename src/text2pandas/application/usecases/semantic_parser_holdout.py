"""Deterministic unlabeled replacement holdout for Semantic Parser Wave 6."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from typing import Any

from text2pandas.application.usecases.independent_gold import question_sha256


@dataclass(frozen=True, slots=True)
class ReplacementHoldout:
    records: tuple[dict[str, object], ...]
    eligible_records: int
    eligible_by_family: Mapping[str, int]


def build_replacement_holdout(
    inventory: Sequence[Mapping[str, object]],
    questions: Mapping[int, str],
    excluded_qids: set[int],
    *,
    family_quota: Mapping[str, int],
    seed: str,
) -> ReplacementHoldout:
    """Select by QID/question/family only; never inspect predictions or answers."""

    if not seed.strip():
        raise ValueError("holdout seed must be non-empty")
    if not family_quota or any(count < 1 for count in family_quota.values()):
        raise ValueError("every holdout family quota must be positive")

    eligible: dict[str, list[dict[str, object]]] = {
        family: [] for family in family_quota
    }
    seen: set[int] = set()
    for raw in inventory:
        qid = _positive_int(raw.get("qid"), "inventory qid")
        if qid in seen:
            raise ValueError(f"duplicate inventory qid: {qid}")
        seen.add(qid)
        if qid in excluded_qids:
            continue
        triage = raw.get("triage")
        if not isinstance(triage, Mapping):
            raise TypeError(f"missing triage for QID {qid}")
        family = str(triage.get("repair_class") or "")
        if family not in family_quota:
            continue
        question = str(questions.get(qid) or "")
        if not question:
            raise ValueError(f"question is missing for QID {qid}")
        digest = question_sha256(question)
        risk_tier = str(triage.get("risk_tier") or "")
        selection_digest = hashlib.sha256(
            f"{seed}\0{family}\0{risk_tier}\0{qid}\0{digest}".encode("utf-8")
        ).hexdigest()
        eligible[family].append(
            {
                "qid": qid,
                "question": question,
                "question_sha256": digest,
                "family": family,
                "risk_tier": risk_tier,
                "split": "replacement_holdout",
                "selection_digest": selection_digest,
            }
        )

    selected: list[dict[str, object]] = []
    eligible_counts: Counter[str] = Counter()
    for family, quota in family_quota.items():
        rows = sorted(
            eligible[family],
            key=lambda row: (
                str(row["selection_digest"]),
                _positive_int(row.get("qid"), "selected qid"),
            ),
        )
        eligible_counts[family] = len(rows)
        if len(rows) < quota:
            raise ValueError(
                f"insufficient holdout candidates: {family}: required={quota} actual={len(rows)}"
            )
        selected.extend(rows[:quota])
    selected.sort(key=lambda row: _positive_int(row.get("qid"), "selected qid"))
    return ReplacementHoldout(
        records=tuple(selected),
        eligible_records=sum(eligible_counts.values()),
        eligible_by_family=dict(sorted(eligible_counts.items())),
    )


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TypeError(f"{label} must be a positive integer")
    return value
