"""Compose an immutable Canonical V2/Semantic V3 candidate under an explicit policy.

This module is deliberately an artifact-level strangler.  It never changes the
default Canonical V2 composition root and it never treats V2 output as gold.
Every promoted question must already be an ``OK`` Semantic V3 result, which
means typed execution and clean pandas replay matched in the source shadow run.
"""

from __future__ import annotations

import csv
import json
import math
import shutil
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from text2pandas.application.usecases.answer import AnswerResult


class HybridDecisionKind(StrEnum):
    PROMOTE_V3 = "PROMOTE_V3"
    KEEP_LEGACY_V3_NOT_OK = "KEEP_LEGACY_V3_NOT_OK"
    KEEP_LEGACY_ROUTE_BLOCKED = "KEEP_LEGACY_ROUTE_BLOCKED"
    KEEP_LEGACY_MARGIN_LOW = "KEEP_LEGACY_MARGIN_LOW"
    KEEP_LEGACY_NON_NUMERIC = "KEEP_LEGACY_NON_NUMERIC"
    KEEP_LEGACY_VALUE_CHANGE_BLOCKED = "KEEP_LEGACY_VALUE_CHANGE_BLOCKED"
    KEEP_LEGACY_RECOVERY_BLOCKED = "KEEP_LEGACY_RECOVERY_BLOCKED"
    KEEP_LEGACY_INVALID_EVIDENCE = "KEEP_LEGACY_INVALID_EVIDENCE"


@dataclass(frozen=True, slots=True)
class HybridRoutePolicy:
    recover_legacy_abstention: bool = False
    replace_legacy_value: bool = False
    minimum_binding_margin: float | None = None


@dataclass(frozen=True, slots=True)
class HybridPolicy:
    policy_id: str
    status: str
    production_eligible: bool
    relevant_refs_mode: str
    maximum_relevant_tables: int
    default_route: HybridRoutePolicy
    routes: Mapping[str, HybridRoutePolicy] = field(default_factory=dict)

    def route(self, expression_type: str) -> HybridRoutePolicy | None:
        return self.routes.get(expression_type)


@dataclass(frozen=True, slots=True)
class HybridDecision:
    qid: int
    kind: HybridDecisionKind
    expression_type: str | None
    legacy_status: str
    semantic_status: str
    legacy_answer: float | None
    semantic_answer: float | None
    binding_margin: float | None
    value_changed: bool
    semantic_stage_failed: str | None = None
    semantic_reason: str | None = None

    @property
    def promoted(self) -> bool:
        return self.kind == HybridDecisionKind.PROMOTE_V3

    def to_dict(self) -> dict[str, object]:
        return {
            "qid": self.qid,
            "decision": self.kind.value,
            "expression_type": self.expression_type,
            "legacy_status": self.legacy_status,
            "semantic_status": self.semantic_status,
            "legacy_answer": self.legacy_answer,
            "semantic_answer": self.semantic_answer,
            "binding_margin": self.binding_margin,
            "value_changed": self.value_changed,
            "semantic_stage_failed": self.semantic_stage_failed,
            "semantic_reason": self.semantic_reason,
        }


@dataclass(slots=True)
class HybridBuildReport:
    policy_id: str
    n_questions: int
    n_promoted: int
    n_recovered: int
    n_value_changed: int
    decisions: dict[str, int]
    promoted_routes: dict[str, int]
    results: list[AnswerResult]
    records_path: Path
    attribution_path: Path


class HybridBuildError(ValueError):
    """Raised when immutable source runs cannot be composed safely."""


def decide_hybrid_record(
    legacy: Mapping[str, object],
    semantic: Mapping[str, object],
    policy: HybridPolicy,
) -> HybridDecision:
    qid = _required_int(legacy, "qid")
    legacy_status = str(legacy.get("status") or "ABSTAIN")
    semantic_status = str(semantic.get("status") or "ABSTAIN")
    legacy_answer = _numeric_answer(legacy.get("answer"))
    semantic_answer = _numeric_answer(semantic.get("answer"))
    expression_type = _expression_type(semantic)
    margin = _optional_float(semantic.get("binding_margin"))

    def decision(kind: HybridDecisionKind) -> HybridDecision:
        return HybridDecision(
            qid=qid,
            kind=kind,
            expression_type=expression_type,
            legacy_status=legacy_status,
            semantic_status=semantic_status,
            legacy_answer=legacy_answer,
            semantic_answer=semantic_answer,
            binding_margin=margin,
            value_changed=(
                legacy_answer is not None
                and semantic_answer is not None
                and not _answers_match(legacy_answer, semantic_answer)
            ),
            semantic_stage_failed=_optional_string(semantic.get("stage_failed")),
            semantic_reason=_optional_string(semantic.get("reason")),
        )

    if semantic_status != "OK":
        return decision(HybridDecisionKind.KEEP_LEGACY_V3_NOT_OK)
    route = policy.route(expression_type or "")
    if route is None:
        return decision(HybridDecisionKind.KEEP_LEGACY_ROUTE_BLOCKED)
    if semantic_answer is None:
        return decision(HybridDecisionKind.KEEP_LEGACY_NON_NUMERIC)
    if not semantic.get("pandas_query") or not semantic.get("evidence"):
        return decision(HybridDecisionKind.KEEP_LEGACY_INVALID_EVIDENCE)
    if (
        route.minimum_binding_margin is not None
        and margin is not None
        and margin < route.minimum_binding_margin
    ):
        return decision(HybridDecisionKind.KEEP_LEGACY_MARGIN_LOW)

    legacy_ok = legacy_status == "OK" and legacy_answer is not None
    if not legacy_ok and not route.recover_legacy_abstention:
        return decision(HybridDecisionKind.KEEP_LEGACY_RECOVERY_BLOCKED)
    if (
        legacy_ok
        and legacy_answer is not None
        and not _answers_match(legacy_answer, semantic_answer)
        and not route.replace_legacy_value
    ):
        return decision(HybridDecisionKind.KEEP_LEGACY_VALUE_CHANGE_BLOCKED)
    return decision(HybridDecisionKind.PROMOTE_V3)


def build_hybrid_candidate(
    *,
    legacy_records_path: Path,
    semantic_records_path: Path,
    legacy_data_dir: Path,
    semantic_data_dir: Path,
    output_dir: Path,
    policy: HybridPolicy,
    table_locators: Mapping[str, str],
) -> HybridBuildReport:
    """Materialize a hybrid run and a complete per-QID attribution artifact."""
    legacy = _load_records(legacy_records_path)
    semantic = _load_records(semantic_records_path)
    if set(legacy) != set(semantic):
        missing_semantic = sorted(set(legacy) - set(semantic))
        missing_legacy = sorted(set(semantic) - set(legacy))
        raise HybridBuildError(
            "source QID sets differ: "
            f"missing_semantic={missing_semantic[:10]} "
            f"missing_legacy={missing_legacy[:10]}"
        )
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise HybridBuildError(f"immutable hybrid output already exists: {output_dir}") from error
    data_dir = output_dir / "data"
    data_dir.mkdir()
    records_path = output_dir / "records.jsonl"
    attribution_path = output_dir / "per_qid_attribution.jsonl"
    results: list[AnswerResult] = []
    decisions: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    recovered = 0
    changed = 0

    with records_path.open("x", encoding="utf-8") as records_handle, attribution_path.open(
        "x", encoding="utf-8"
    ) as attribution_handle:
        for qid in sorted(legacy):
            old = legacy[qid]
            new = semantic[qid]
            if str(old.get("question") or "") != str(new.get("question") or ""):
                raise HybridBuildError(f"question text differs for QID {qid}")
            decision = decide_hybrid_record(old, new, policy)
            decisions[decision.kind.value] += 1
            if decision.promoted:
                assert decision.semantic_answer is not None
                result = _semantic_result(
                    new,
                    old,
                    decision.semantic_answer,
                    semantic_data_dir,
                    data_dir,
                    table_locators,
                    policy,
                )
                routes[decision.expression_type or "UNKNOWN"] += 1
                recovered += int(decision.legacy_answer is None)
                changed += int(decision.value_changed)
            else:
                result = _legacy_result(old, legacy_data_dir, data_dir)
            results.append(result)
            attribution_handle.write(
                json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            )
            records_handle.write(
                json.dumps(
                    {
                        "qid": qid,
                        "question": str(old.get("question") or ""),
                        "status": "OK" if result.answer is not None else "ABSTAIN",
                        "answer": result.answer,
                        "relevant_docs": result.relevant_docs,
                        "relevant_tables": result.relevant_tables,
                        "evidence": result.evidence,
                        "pandas_query": result.pandas_query,
                        "confidence": result.confidence,
                        "reason": result.notes[0] if result.notes else None,
                        "answer_source": "semantic_v3" if decision.promoted else "canonical_v2",
                        "hybrid": decision.to_dict(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    return HybridBuildReport(
        policy_id=policy.policy_id,
        n_questions=len(results),
        n_promoted=decisions[HybridDecisionKind.PROMOTE_V3.value],
        n_recovered=recovered,
        n_value_changed=changed,
        decisions=dict(sorted(decisions.items())),
        promoted_routes=dict(sorted(routes.items())),
        results=results,
        records_path=records_path,
        attribution_path=attribution_path,
    )


def table_locator_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row["table_uid"]): str(row["evidence_ref"]).replace("|line:", "|")
            for row in csv.DictReader(handle)
        }


def _semantic_result(
    semantic: Mapping[str, object],
    legacy: Mapping[str, object],
    answer: float,
    source_data: Path,
    target_data: Path,
    locators: Mapping[str, str],
    policy: HybridPolicy,
) -> AnswerResult:
    evidence_items = semantic.get("evidence")
    if not isinstance(evidence_items, Sequence) or isinstance(evidence_items, (str, bytes)):
        raise HybridBuildError(f"Semantic V3 evidence is invalid for QID {semantic.get('qid')}")
    evidence: list[dict[str, str]] = []
    table_uids: list[str] = []
    for raw in evidence_items:
        if not isinstance(raw, Mapping):
            raise HybridBuildError(f"Semantic V3 evidence item is invalid: {raw!r}")
        table_uid = str(raw.get("table_uid") or "")
        variable = str(raw.get("variable") or "")
        if not table_uid or not variable:
            raise HybridBuildError(f"Semantic V3 evidence is incomplete: {raw!r}")
        source = source_data / f"{table_uid}.csv"
        target_name = f"v3_{table_uid}.csv"
        _copy_immutable(source, target_data / target_name)
        evidence.append({"variable": variable, "csv_path": f"data/{target_name}"})
        if table_uid not in table_uids:
            table_uids.append(table_uid)
    try:
        exact_refs = [locators[value] for value in table_uids]
    except KeyError as error:
        raise HybridBuildError(f"A6 table locator missing: {error.args[0]}") from error
    tables = _scorer_refs(exact_refs, legacy, policy)
    documents = list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables))
    margin = _optional_float(semantic.get("binding_margin"))
    positive_margin = None if margin is None else max(0.0, margin)
    confidence = (
        0.5 if positive_margin is None else positive_margin / (1.0 + positive_margin)
    )
    return AnswerResult(
        qid=_required_int(semantic, "qid"),
        answer=answer,
        relevant_docs=documents,
        relevant_tables=tables,
        evidence=evidence,
        pandas_query=str(semantic.get("pandas_query") or ""),
        confidence=confidence,
        csv_name=Path(evidence[0]["csv_path"]).name if evidence else "",
        has_csv=bool(evidence),
        notes=["PROMOTED_SEMANTIC_V3"],
    )


def _legacy_result(
    record: Mapping[str, object], source_data: Path, target_data: Path
) -> AnswerResult:
    raw_evidence = record.get("evidence") or []
    evidence: list[dict[str, str]] = []
    if not isinstance(raw_evidence, Sequence) or isinstance(raw_evidence, (str, bytes)):
        raise HybridBuildError(f"legacy evidence is invalid for QID {record.get('qid')}")
    for raw in raw_evidence:
        if not isinstance(raw, Mapping):
            raise HybridBuildError(f"legacy evidence item is invalid: {raw!r}")
        variable = str(raw.get("variable") or "")
        csv_path = str(raw.get("csv_path") or "")
        if not variable or not csv_path.startswith("data/"):
            raise HybridBuildError(f"legacy evidence is incomplete: {raw!r}")
        _copy_immutable(source_data / Path(csv_path).name, target_data / Path(csv_path).name)
        evidence.append({"variable": variable, "csv_path": csv_path})
    answer = _numeric_answer(record.get("answer"))
    return AnswerResult(
        qid=_required_int(record, "qid"),
        answer=answer,
        relevant_docs=_string_sequence(record.get("relevant_docs"), "relevant_docs"),
        relevant_tables=_string_sequence(record.get("relevant_tables"), "relevant_tables"),
        evidence=evidence,
        pandas_query=str(record.get("pandas_query") or ""),
        confidence=_optional_float(record.get("confidence")) or 0.0,
        csv_name=Path(evidence[0]["csv_path"]).name if evidence else "",
        has_csv=bool(evidence),
        notes=[str(record.get("reason"))] if record.get("reason") else [],
    )


def _scorer_refs(
    exact_refs: list[str], legacy: Mapping[str, object], policy: HybridPolicy
) -> list[str]:
    if policy.relevant_refs_mode == "semantic_evidence":
        values = exact_refs
    elif policy.relevant_refs_mode == "semantic_plus_legacy":
        values = exact_refs + _string_sequence(
            legacy.get("relevant_tables"), "relevant_tables"
        )
    else:
        raise HybridBuildError(f"unknown relevant_refs_mode: {policy.relevant_refs_mode}")
    return list(dict.fromkeys(values))[: policy.maximum_relevant_tables]


def _copy_immutable(source: Path, target: Path) -> None:
    if not source.is_file():
        raise HybridBuildError(f"referenced evidence CSV is missing: {source}")
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise HybridBuildError(f"evidence filename collision with different bytes: {target}")
        return
    shutil.copy2(source, target)


def _load_records(path: Path) -> dict[int, dict[str, object]]:
    if not path.is_file():
        raise HybridBuildError(f"source records are missing: {path}")
    output: dict[int, dict[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = json.loads(line)
        qid = _required_int(raw, "qid")
        if qid in output:
            raise HybridBuildError(f"duplicate QID {qid} in {path}:{line_number}")
        output[qid] = raw
    return output


def _expression_type(record: Mapping[str, object]) -> str | None:
    ast = record.get("ast")
    if not isinstance(ast, Mapping):
        return None
    expression = ast.get("expression")
    if not isinstance(expression, Mapping):
        return None
    value = expression.get("type")
    return None if value is None else str(value)


def _numeric_answer(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    converted = float(decimal)
    return converted if math.isfinite(converted) else None


def _answers_match(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        converted = float(str(value))
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _optional_string(value: object) -> str | None:
    return None if value in (None, "") else str(value)


def _required_int(record: Mapping[str, object], key: str) -> int:
    if key not in record:
        raise HybridBuildError(f"record is missing required integer field: {key}")
    try:
        return int(str(record[key]))
    except ValueError as error:
        raise HybridBuildError(f"record field {key} is not an integer: {record[key]!r}") from error


def _string_sequence(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise HybridBuildError(f"{field_name} must be a sequence")
    return [str(item) for item in value]
