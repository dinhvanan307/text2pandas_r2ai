from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from text2pandas.application.usecases.submission import (
    SubmissionBuildError,
    replay_zip,
    write_deterministic_submission_zip,
)
from text2pandas.application.usecases.wave2_recovery import (
    build_wave2_recovery_candidate,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, *, execution_ready: int = 1) -> tuple[Path, Path, Path]:
    baseline = root / "submission.zip"
    records = [
        {
            "id": 1,
            "question": "Protected answer",
            "answer": 5.0,
            "relevant_docs": ["DOC_BASE"],
            "relevant_tables": ["TABLE_BASE"],
            "evidence": [{"variable": "df1", "csv_path": "data/base.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        },
        {
            "id": 2,
            "question": "Reviewed abstention",
            "answer": 0.0,
            "relevant_docs": ["DOC_RETRIEVAL"],
            "relevant_tables": ["TABLE_RETRIEVAL"],
            "evidence": [],
            "pandas_query": "",
        },
    ]
    write_deterministic_submission_zip(
        baseline,
        json_name="submission.json",
        json_bytes=json.dumps(records, ensure_ascii=False, indent=1).encode(),
        csv_payloads={"data/base.csv": b"value\n5\n"},
    )

    database = root / "silver.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY,
            value_decimal_text TEXT,
            table_uid TEXT,
            directory_doc_id TEXT,
            ticker TEXT,
            period_end TEXT,
            as_of_date TEXT,
            unit_kind TEXT,
            scale_exponent INTEGER,
            row_path_text TEXT,
            col_path_text TEXT,
            metric_label_clean TEXT
        );
        CREATE TABLE observation_readiness (
            observation_uid TEXT PRIMARY KEY,
            execution_ready INTEGER NOT NULL
        );
        INSERT INTO observations VALUES (
            'fact-2', '7', 'table-2', 'DOC_2022', 'DOC', '2022-12-31',
            NULL, 'money', 0, 'Metric', '2022', 'Metric'
        );
        """
    )
    connection.execute(
        "INSERT INTO observation_readiness VALUES ('fact-2', ?)",
        (execution_ready,),
    )
    connection.commit()
    connection.close()

    ledger = root / "review.json"
    ledger.write_text(
        json.dumps(
            {
                "baseline": {
                    "zip_path": baseline.name,
                    "zip_sha256": _sha256(baseline),
                },
                "a6_database": {
                    "database_path": database.name,
                    "database_sha256": _sha256(database),
                },
                "reviews": [
                    {
                        "qid": 2,
                        "cohort": "pack_a",
                        "decision": "PASS_SOURCE_PROVEN",
                        "fact_uids": ["fact-2"],
                        "pandas_query": (
                            "float(df1[df1['observation_uid'] == 'fact-2']['value'].values[0])"
                        ),
                        "expected_answer": 7.0,
                        "checks": {
                            "metric": True,
                            "entity": True,
                            "period": True,
                            "basis": True,
                            "operation": True,
                            "unit": True,
                            "source": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return baseline, database, ledger


def test_wave2_is_deterministic_and_preserves_every_baseline_layer(tmp_path: Path) -> None:
    baseline, database, ledger = _fixture(tmp_path)
    first = build_wave2_recovery_candidate(
        baseline_zip=baseline,
        a6_database=database,
        review_ledger=ledger,
        output_zip=tmp_path / "first.zip",
    )
    second = build_wave2_recovery_candidate(
        baseline_zip=baseline,
        a6_database=database,
        review_ledger=ledger,
        output_zip=tmp_path / "second.zip",
    )

    assert first.accepted_qids == (2,)
    assert first.source_fact_count == 1
    assert first.protected_answer_query_evidence == 1
    assert first.protected_retrieval == 2
    assert first.protected_csv_payloads == 1
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    with zipfile.ZipFile(first.zip_path) as archive:
        candidate = {
            row["id"]: row for row in json.loads(archive.read("submission.json").decode("utf-8"))
        }
        assert archive.read("data/base.csv") == b"value\n5\n"
        assert candidate[1] == {
            **candidate[1],
            "answer": 5.0,
            "relevant_docs": ["DOC_BASE"],
            "relevant_tables": ["TABLE_BASE"],
            "evidence": [{"variable": "df1", "csv_path": "data/base.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        }
        assert candidate[2]["answer"] == 7.0
        assert candidate[2]["relevant_docs"] == ["DOC_RETRIEVAL"]
        assert candidate[2]["relevant_tables"] == ["TABLE_RETRIEVAL"]
    assert replay_zip(first.zip_path, tmp_path / "replay", profile="competition") == {
        "total": 2,
        "executed": 2,
        "matched": 2,
        "no_evidence": 0,
        "error": 0,
    }


def test_wave2_fails_closed_when_a_reviewed_fact_is_not_ready(tmp_path: Path) -> None:
    baseline, database, ledger = _fixture(tmp_path, execution_ready=0)
    with pytest.raises(SubmissionBuildError, match="not execution-ready"):
        build_wave2_recovery_candidate(
            baseline_zip=baseline,
            a6_database=database,
            review_ledger=ledger,
            output_zip=tmp_path / "blocked.zip",
        )
