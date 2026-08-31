"""Build source-sealed, additive-only recovery candidates."""

from __future__ import annotations

import io
import json
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pandas as pd

from text2pandas.application.usecases.safe_recovery import (
    _enforce_protected_layers,
    _facts_csv,
    _index_reviews,
    _index_submission_records,
    _is_executable,
    _load_submission,
    _verify_bound_artifact,
    _verify_review_checks,
)
from text2pandas.application.usecases.submission import (
    SubmissionBuildError,
    write_deterministic_submission_zip,
)
from text2pandas.infrastructure.sandbox.query import execute_query


@dataclass(frozen=True, slots=True)
class Wave2RecoveryBuild:
    zip_path: Path
    accepted_qids: tuple[int, ...]
    rejected_qids: tuple[int, ...]
    source_fact_count: int
    baseline_executable: int
    baseline_unresolved: int
    candidate_executable: int
    candidate_unresolved: int
    baseline_csv_members: int
    candidate_csv_members: int
    protected_answer_query_evidence: int
    protected_retrieval: int
    protected_csv_payloads: int


def build_wave2_recovery_candidate(
    *,
    baseline_zip: Path,
    a6_database: Path,
    review_ledger: Path,
    output_zip: Path,
) -> Wave2RecoveryBuild:
    """Fill Wave 2 reviewed abstentions using execution-ready A6 observations."""

    return build_recovery_candidate(
        baseline_zip=baseline_zip,
        a6_database=a6_database,
        review_ledger=review_ledger,
        output_zip=output_zip,
        evidence_prefix="wave2",
    )


def build_recovery_candidate(
    *,
    baseline_zip: Path,
    a6_database: Path,
    review_ledger: Path,
    output_zip: Path,
    evidence_prefix: str,
) -> Wave2RecoveryBuild:
    """Fill reviewed abstentions while preserving every protected baseline layer."""

    if not evidence_prefix or not evidence_prefix.replace("_", "").isalnum():
        raise SubmissionBuildError("evidence prefix must be a non-empty path-safe token")

    if output_zip.exists():
        raise FileExistsError(f"immutable candidate already exists: {output_zip}")
    ledger = _load_ledger(review_ledger)
    _verify_bound_artifact(
        baseline_zip,
        cast(Mapping[str, object], ledger.get("baseline")),
        label="baseline ZIP",
        path_key="zip_path",
        sha_key="zip_sha256",
    )
    _verify_bound_artifact(
        a6_database,
        cast(Mapping[str, object], ledger.get("a6_database")),
        label="A6 database",
        path_key="database_path",
        sha_key="database_sha256",
    )
    raw_reviews = ledger.get("reviews")
    if not isinstance(raw_reviews, list):
        raise SubmissionBuildError("review ledger must contain a reviews list")
    reviews = _index_reviews(raw_reviews)
    accepted = {
        qid: review
        for qid, review in reviews.items()
        if review.get("decision") == "PASS_SOURCE_PROVEN"
    }
    rejected = tuple(
        sorted(
            qid for qid, review in reviews.items() if review.get("decision") != "PASS_SOURCE_PROVEN"
        )
    )
    if not accepted:
        raise SubmissionBuildError("review ledger selected no source-proven recovery")

    json_name, baseline_records, baseline_csvs = _load_submission(baseline_zip)
    baseline_by_qid = _index_submission_records(baseline_records)
    executable = {qid for qid, row in baseline_by_qid.items() if _is_executable(row)}
    unresolved = set(baseline_by_qid) - executable
    invalid = sorted(set(accepted) - unresolved)
    if invalid:
        raise SubmissionBuildError(
            f"recovery may only fill baseline abstentions; invalid QIDs={invalid[:10]}"
        )

    candidate_records = [dict(row) for row in baseline_records]
    candidate_by_qid = _index_submission_records(candidate_records)
    candidate_csvs = dict(baseline_csvs)
    connection = sqlite3.connect(f"file:{a6_database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    source_fact_count = 0
    try:
        for qid in sorted(accepted):
            review = accepted[qid]
            _verify_review_checks(qid, review)
            query = review.get("pandas_query")
            expected = review.get("expected_answer")
            fact_uids = review.get("fact_uids")
            if not isinstance(query, str) or not query.strip():
                raise SubmissionBuildError(f"QID {qid} has no reviewed pandas query")
            if not isinstance(fact_uids, list) or not fact_uids:
                raise SubmissionBuildError(f"QID {qid} has no reviewed fact UIDs")
            if not all(isinstance(uid, str) and uid for uid in fact_uids):
                raise SubmissionBuildError(f"QID {qid} has an invalid fact UID")
            if len(set(fact_uids)) != len(fact_uids):
                raise SubmissionBuildError(f"QID {qid} has duplicate fact UIDs")
            facts = [_load_ready_fact(connection, qid, uid) for uid in fact_uids]
            source_fact_count += len(facts)
            csv_name = f"data/{evidence_prefix}_q{qid:04d}.csv"
            if csv_name in candidate_csvs:
                raise SubmissionBuildError(f"QID {qid} evidence member collides with baseline")
            csv_payload = _facts_csv(qid, facts)
            frame = pd.read_csv(io.BytesIO(csv_payload))
            replayed = execute_query(query, {"df1": frame})
            if not _matches_reviewed_answer(replayed, expected):
                raise SubmissionBuildError(
                    f"QID {qid} reviewed answer does not match clean replay: "
                    f"{expected!r} != {replayed!r}"
                )
            candidate_csvs[csv_name] = csv_payload
            row = candidate_by_qid[qid]
            row["answer"] = replayed
            row["evidence"] = [{"variable": "df1", "csv_path": csv_name}]
            row["pandas_query"] = query
    finally:
        connection.close()

    _enforce_protected_layers(
        baseline_by_qid=baseline_by_qid,
        candidate_by_qid=candidate_by_qid,
        baseline_csvs=baseline_csvs,
        candidate_csvs=candidate_csvs,
        accepted_qids=set(accepted),
    )
    json_bytes = json.dumps(candidate_records, ensure_ascii=False, indent=1).encode("utf-8")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    write_deterministic_submission_zip(
        output_zip,
        json_name=json_name,
        json_bytes=json_bytes,
        csv_payloads=candidate_csvs,
    )
    return Wave2RecoveryBuild(
        zip_path=output_zip,
        accepted_qids=tuple(sorted(accepted)),
        rejected_qids=rejected,
        source_fact_count=source_fact_count,
        baseline_executable=len(executable),
        baseline_unresolved=len(unresolved),
        candidate_executable=len(executable) + len(accepted),
        candidate_unresolved=len(unresolved) - len(accepted),
        baseline_csv_members=len(baseline_csvs),
        candidate_csv_members=len(candidate_csvs),
        protected_answer_query_evidence=len(executable),
        protected_retrieval=len(baseline_by_qid),
        protected_csv_payloads=len(baseline_csvs),
    )


def _load_ledger(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SubmissionBuildError(f"expected JSON object: {path}")
    return payload


def _matches_reviewed_answer(replayed: float, expected: object) -> bool:
    if not isinstance(expected, (int, float)) or isinstance(expected, bool):
        return False
    return math.isfinite(float(expected)) and math.isclose(
        replayed,
        float(expected),
        rel_tol=1e-12,
        abs_tol=1e-12,
    )


def _load_ready_fact(connection: sqlite3.Connection, qid: int, uid: str) -> dict[str, object]:
    row = connection.execute(
        """
        SELECT o.observation_uid, o.value_decimal_text, o.table_uid,
               o.directory_doc_id, o.ticker, o.period_end, o.as_of_date,
               o.unit_kind, o.scale_exponent, o.row_path_text, o.col_path_text,
               o.metric_label_clean, r.execution_ready
        FROM observations o
        JOIN observation_readiness r USING (observation_uid)
        WHERE o.observation_uid = ?
        """,
        (uid,),
    ).fetchone()
    if row is None:
        raise SubmissionBuildError(f"QID {qid} reviewed fact does not exist: {uid}")
    if row["execution_ready"] != 1:
        raise SubmissionBuildError(f"QID {qid} reviewed fact is not execution-ready: {uid}")
    if row["value_decimal_text"] is None:
        raise SubmissionBuildError(f"QID {qid} reviewed fact has no decimal value: {uid}")
    return {
        "uid": row["observation_uid"],
        "raw_value": row["value_decimal_text"],
        "table_uid": row["table_uid"],
        "document_id": row["directory_doc_id"],
        "entity": row["ticker"],
        "period": row["period_end"] or row["as_of_date"] or "",
        "dimension": row["unit_kind"],
        "scale_exponent": row["scale_exponent"],
        "row": row["row_path_text"] or row["metric_label_clean"] or "",
        "column": row["col_path_text"] or "",
    }
