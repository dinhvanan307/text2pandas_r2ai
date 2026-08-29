"""Pure contracts for prediction-blind Semantic Gold v2 packet preparation.

This module selects questions and creates blank reviewer templates. It never
imports a parser, retrieval component, candidate, answer, or model output.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from text2pandas.application.usecases.independent_gold import (
    canonical_jsonl,
    question_sha256,
)

FORBIDDEN_PREDICTION_FIELDS = frozenset(
    {
        "answer",
        "candidate_scores",
        "evidence",
        "model_answer",
        "model_ast",
        "model_output",
        "pandas_query",
        "predicted_answer",
        "predicted_semantic",
        "prediction",
        "retrieval_scores",
        "trace",
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
) -> tuple[dict[str, object], ...]:
    """Build a deterministic QID ledger from explicit development-label sources."""

    by_qid: dict[int, set[str]] = {}
    for source, rows in sorted(sources.items()):
        for row in rows:
            qid = record_qid(row)
            by_qid.setdefault(qid, set()).add(source)
    return tuple(
        {"qid": qid, "sources": sorted(by_qid[qid])}
        for qid in sorted(by_qid)
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

    source = _validated_questions(questions)
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
    for stratum in strata:
        candidates = [
            row
            for row in remaining
            if _row_qid(row) not in diagnostic_qids
            and _matches_proxy(str(row["question"]), stratum)
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

    if len(diagnostic_rows) > diagnostic_count:
        raise ValueError("diagnostic stratum quotas exceed diagnostic record target")
    if len(diagnostic_rows) < diagnostic_count:
        topup_count = diagnostic_count - len(diagnostic_rows)
        topup_candidates = [
            row for row in remaining if _row_qid(row) not in diagnostic_qids
        ]
        topups = _ranked(topup_candidates, f"{diagnostic_seed}:RANDOM_TOPUP")[:topup_count]
        if len(topups) != topup_count:
            raise ValueError("not enough records for diagnostic random top-up")
        for row in topups:
            diagnostic_qids.add(_row_qid(row))
            diagnostic_rows.append(
                _selection_row(
                    row,
                    cohort="DIAGNOSTIC_SUPPLEMENT",
                    seed=f"{diagnostic_seed}:RANDOM_TOPUP",
                    primary_stratum="RANDOM_TOPUP",
                    strata=strata,
                )
            )
        stratum_coverage["RANDOM_TOPUP"] = {
            "available_proxy": len(topup_candidates),
            "target": topup_count,
            "selected": len(topups),
        }

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
    }
    return SemanticSelection(core, diagnostic, reserve, coverage)


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
