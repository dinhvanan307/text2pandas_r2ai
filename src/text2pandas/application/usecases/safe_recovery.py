"""Build a baseline-preserving candidate from source-adjudicated abstentions."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from text2pandas.application.usecases.submission import (
    SubmissionBuildError,
    write_deterministic_submission_zip,
)

RecoveryCohort = Literal["trusted", "trusted_and_shadow"]
_REQUIRED_CHECKS = {"metric", "entity", "period", "basis", "operation", "unit", "source"}
_CSV_FIELDS = (
    "observation_uid",
    "value",
    "table_uid",
    "document_id",
    "entity",
    "period",
    "dimension",
    "scale_exponent",
    "row_path",
    "column_path",
)


@dataclass(frozen=True, slots=True)
class SafeRecoveryBuild:
    zip_path: Path
    accepted_qids: tuple[int, ...]
    trusted_qids: tuple[int, ...]
    shadow_qids: tuple[int, ...]
    baseline_executable: int
    baseline_unresolved: int
    candidate_executable: int
    candidate_unresolved: int
    baseline_csv_members: int
    candidate_csv_members: int
    protected_answer_query_evidence: int
    protected_retrieval: int
    protected_csv_payloads: int


def build_source_adjudicated_candidate(
    *,
    baseline_zip: Path,
    source_records: Path,
    review_ledger: Path,
    output_zip: Path,
    cohort: RecoveryCohort,
) -> SafeRecoveryBuild:
    """Overlay only reviewed abstentions; every existing baseline layer is sealed."""

    if cohort not in {"trusted", "trusted_and_shadow"}:
        raise ValueError(f"unsupported recovery cohort: {cohort!r}")
    if output_zip.exists():
        raise FileExistsError(f"immutable candidate already exists: {output_zip}")

    ledger = _load_object(review_ledger)
    _verify_bound_artifact(
        baseline_zip,
        cast(Mapping[str, object], ledger.get("baseline")),
        label="baseline ZIP",
        path_key="zip_path",
        sha_key="zip_sha256",
    )
    _verify_bound_artifact(
        source_records,
        cast(Mapping[str, object], ledger.get("source_run")),
        label="source records",
        path_key="records_path",
        sha_key="records_sha256",
    )

    reviews = ledger.get("reviews")
    if not isinstance(reviews, list):
        raise SubmissionBuildError("review ledger must contain a reviews list")
    review_by_qid = _index_reviews(reviews)
    source_by_qid = _load_source_records(source_records)
    allowed_cohorts = {"trusted"} if cohort == "trusted" else {"trusted", "shadow"}
    accepted = {
        qid: review
        for qid, review in review_by_qid.items()
        if review.get("decision") == "PASS_SOURCE_PROVEN"
        and review.get("cohort") in allowed_cohorts
    }
    if not accepted:
        raise SubmissionBuildError("review ledger selected no source-proven recovery")

    json_name, baseline_records, baseline_csvs = _load_submission(baseline_zip)
    baseline_by_qid = _index_submission_records(baseline_records)
    baseline_executable_qids = {
        qid for qid, row in baseline_by_qid.items() if _is_executable(row)
    }
    baseline_unresolved_qids = set(baseline_by_qid) - baseline_executable_qids
    unknown = sorted(set(accepted) - baseline_unresolved_qids)
    if unknown:
        raise SubmissionBuildError(
            "source-adjudicated overlay may only fill baseline abstentions; "
            f"invalid QIDs={unknown[:5]}"
        )

    candidate_records = [dict(row) for row in baseline_records]
    candidate_by_qid = _index_submission_records(candidate_records)
    candidate_csvs = dict(baseline_csvs)
    for qid in sorted(accepted):
        review = accepted[qid]
        source = source_by_qid.get(qid)
        if source is None:
            raise SubmissionBuildError(f"source records are missing reviewed QID {qid}")
        grounded = source.get("grounded_v5")
        if not isinstance(grounded, Mapping):
            raise SubmissionBuildError(f"QID {qid} has no grounded_v5 candidate")
        if grounded.get("status") != review.get("source_status"):
            raise SubmissionBuildError(f"QID {qid} source status changed after review")
        _verify_review_checks(qid, review)
        answer = grounded.get("answer")
        expected_answer = review.get("expected_answer")
        if not _same_finite_number(answer, expected_answer):
            raise SubmissionBuildError(
                f"QID {qid} answer changed after review: {answer!r} != {expected_answer!r}"
            )
        query = grounded.get("pandas_query")
        facts = grounded.get("selected_facts")
        if not isinstance(query, str) or not query.strip():
            raise SubmissionBuildError(f"QID {qid} reviewed candidate has an empty query")
        if not isinstance(facts, list) or not facts:
            raise SubmissionBuildError(f"QID {qid} reviewed candidate has no selected facts")
        csv_name = f"data/safe_q{qid:04d}.csv"
        if csv_name in candidate_csvs:
            raise SubmissionBuildError(f"QID {qid} evidence member collides with baseline")
        candidate_csvs[csv_name] = _facts_csv(qid, facts)
        row = candidate_by_qid[qid]
        row["answer"] = float(cast(int | float, answer))
        row["evidence"] = [{"variable": "df1", "csv_path": csv_name}]
        row["pandas_query"] = query

    _enforce_protected_layers(
        baseline_by_qid=baseline_by_qid,
        candidate_by_qid=candidate_by_qid,
        baseline_csvs=baseline_csvs,
        candidate_csvs=candidate_csvs,
        accepted_qids=set(accepted),
    )
    json_bytes = json.dumps(
        candidate_records,
        ensure_ascii=False,
        indent=1,
    ).encode("utf-8")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    write_deterministic_submission_zip(
        output_zip,
        json_name=json_name,
        json_bytes=json_bytes,
        csv_payloads=candidate_csvs,
    )
    candidate_executable = len(baseline_executable_qids) + len(accepted)
    trusted = tuple(
        sorted(qid for qid, row in accepted.items() if row.get("cohort") == "trusted")
    )
    shadow = tuple(
        sorted(qid for qid, row in accepted.items() if row.get("cohort") == "shadow")
    )
    return SafeRecoveryBuild(
        zip_path=output_zip,
        accepted_qids=tuple(sorted(accepted)),
        trusted_qids=trusted,
        shadow_qids=shadow,
        baseline_executable=len(baseline_executable_qids),
        baseline_unresolved=len(baseline_unresolved_qids),
        candidate_executable=candidate_executable,
        candidate_unresolved=len(baseline_by_qid) - candidate_executable,
        baseline_csv_members=len(baseline_csvs),
        candidate_csv_members=len(candidate_csvs),
        protected_answer_query_evidence=len(baseline_executable_qids),
        protected_retrieval=len(baseline_by_qid),
        protected_csv_payloads=len(baseline_csvs),
    )


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SubmissionBuildError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_bound_artifact(
    path: Path,
    binding: Mapping[str, object],
    *,
    label: str,
    path_key: str,
    sha_key: str,
) -> None:
    if not isinstance(binding, Mapping):
        raise SubmissionBuildError(f"review ledger has no {label} binding")
    declared_path = binding.get(path_key)
    declared_sha = binding.get(sha_key)
    if not isinstance(declared_path, str) or Path(declared_path).name != path.name:
        raise SubmissionBuildError(f"{label} path does not match the review ledger")
    if not isinstance(declared_sha, str) or _sha256(path) != declared_sha:
        raise SubmissionBuildError(f"{label} SHA-256 does not match the review ledger")


def _index_reviews(reviews: Sequence[object]) -> dict[int, Mapping[str, object]]:
    indexed: dict[int, Mapping[str, object]] = {}
    for item in reviews:
        if not isinstance(item, Mapping) or not isinstance(item.get("qid"), int):
            raise SubmissionBuildError("each review must be an object with an integer qid")
        qid = cast(int, item["qid"])
        if qid in indexed:
            raise SubmissionBuildError(f"duplicate reviewed QID {qid}")
        indexed[qid] = item
    return indexed


def _load_source_records(path: Path) -> dict[int, Mapping[str, object]]:
    indexed: dict[int, Mapping[str, object]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, Mapping) or not isinstance(row.get("qid"), int):
            raise SubmissionBuildError(f"invalid source record at line {line_number}")
        qid = cast(int, row["qid"])
        if qid in indexed:
            raise SubmissionBuildError(f"duplicate source QID {qid}")
        indexed[qid] = row
    return indexed


def _load_submission(
    path: Path,
) -> tuple[str, list[dict[str, object]], dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        json_names = [name for name in archive.namelist() if name.lower().endswith(".json")]
        if len(json_names) != 1:
            raise SubmissionBuildError("baseline submission must contain exactly one JSON")
        payload = json.loads(archive.read(json_names[0]).decode("utf-8"))
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise SubmissionBuildError("baseline submission JSON must be a list of objects")
        csvs = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.lower().endswith(".csv")
        }
    return json_names[0], cast(list[dict[str, object]], payload), csvs


def _index_submission_records(
    records: Sequence[dict[str, object]],
) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for row in records:
        qid = row.get("id")
        if not isinstance(qid, int):
            raise SubmissionBuildError("submission record id must be an integer")
        if qid in indexed:
            raise SubmissionBuildError(f"duplicate submission QID {qid}")
        indexed[qid] = row
    return indexed


def _is_executable(row: Mapping[str, object]) -> bool:
    return bool(row.get("evidence")) and bool(str(row.get("pandas_query") or "").strip())


def _verify_review_checks(qid: int, review: Mapping[str, object]) -> None:
    checks = review.get("checks")
    if not isinstance(checks, Mapping):
        raise SubmissionBuildError(f"QID {qid} has no structured review checks")
    if set(checks) != _REQUIRED_CHECKS or any(checks[key] is not True for key in _REQUIRED_CHECKS):
        raise SubmissionBuildError(f"QID {qid} did not pass every promotion requirement")


def _same_finite_number(left: object, right: object) -> bool:
    if (
        not isinstance(left, (int, float))
        or isinstance(left, bool)
        or not isinstance(right, (int, float))
        or isinstance(right, bool)
    ):
        return False
    return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)


def _facts_csv(qid: int, facts: Sequence[object]) -> bytes:
    target = io.StringIO(newline="")
    writer = csv.writer(target, lineterminator="\n")
    writer.writerow(_CSV_FIELDS)
    seen_uids: set[str] = set()
    for item in facts:
        if not isinstance(item, Mapping):
            raise SubmissionBuildError(f"QID {qid} has a non-object selected fact")
        uid = item.get("uid")
        value = item.get("raw_value")
        if not isinstance(uid, str) or not uid or uid in seen_uids:
            raise SubmissionBuildError(f"QID {qid} has an invalid or duplicate fact UID")
        if value is None:
            raise SubmissionBuildError(f"QID {qid} fact {uid} has no raw value")
        seen_uids.add(uid)
        writer.writerow(
            (
                uid,
                str(value),
                str(item.get("table_uid") or ""),
                str(item.get("document_id") or ""),
                str(item.get("entity") or ""),
                str(item.get("period") or ""),
                str(item.get("dimension") or ""),
                "" if item.get("scale_exponent") is None else str(item["scale_exponent"]),
                str(item.get("row") or ""),
                str(item.get("column") or ""),
            )
        )
    return target.getvalue().encode("utf-8")


def _enforce_protected_layers(
    *,
    baseline_by_qid: Mapping[int, Mapping[str, object]],
    candidate_by_qid: Mapping[int, Mapping[str, object]],
    baseline_csvs: Mapping[str, bytes],
    candidate_csvs: Mapping[str, bytes],
    accepted_qids: set[int],
) -> None:
    if set(baseline_by_qid) != set(candidate_by_qid):
        raise SubmissionBuildError("candidate QID scope differs from baseline")
    changed: set[int] = set()
    for qid, baseline in baseline_by_qid.items():
        candidate = candidate_by_qid[qid]
        if baseline.get("relevant_tables") != candidate.get("relevant_tables") or baseline.get(
            "relevant_docs"
        ) != candidate.get("relevant_docs"):
            raise SubmissionBuildError(f"QID {qid} retrieval layer changed")
        baseline_tuple = (
            baseline.get("answer"),
            baseline.get("evidence"),
            baseline.get("pandas_query"),
        )
        candidate_tuple = (
            candidate.get("answer"),
            candidate.get("evidence"),
            candidate.get("pandas_query"),
        )
        if baseline_tuple != candidate_tuple:
            changed.add(qid)
        if qid not in accepted_qids and baseline != candidate:
            raise SubmissionBuildError(f"unreviewed QID {qid} changed")
    if changed != accepted_qids:
        raise SubmissionBuildError(
            f"answer-layer diff does not equal reviewed overlay: changed={sorted(changed)}"
        )
    for name, payload in baseline_csvs.items():
        if candidate_csvs.get(name) != payload:
            raise SubmissionBuildError(f"baseline CSV payload changed: {name}")
