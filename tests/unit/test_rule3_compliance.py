from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from text2pandas.application.usecases.rule3_compliance import (
    build_rule3_compliance_candidate,
    rewrite_legacy_arg_period_query,
    simplify_zero_multiplier_query,
)
from text2pandas.application.usecases.submission import (
    SubmissionBuildError,
    write_deterministic_submission_zip,
)
from text2pandas.infrastructure.sandbox.query import execute_query, validate_query


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, *, source_value: str = "20") -> tuple[Path, Path, Path, Path]:
    baseline = root / "baseline.zip"
    records = [
        {
            "id": 1,
            "question": "Năm nào lớn nhất?",
            "answer": 2021.0,
            "relevant_docs": ["ABC_financial_statements_2020_consolidated"],
            "relevant_tables": ["ABC_financial_statements_2020_consolidated|1"],
            "evidence": [{"variable": "df1", "csv_path": "data/q1.csv"}],
            "pandas_query": (
                "float(2021 + 0 * float(df1[df1['observation_uid'] == 'u20']"
                "['value'].values[0]) + 0 * float(df1[df1['observation_uid'] == 'u21']"
                "['value'].values[0]))"
            ),
        },
        {
            "id": 2,
            "question": "Chưa giải được",
            "answer": 0.0,
            "relevant_docs": [],
            "relevant_tables": [],
            "evidence": [],
            "pandas_query": "",
        },
    ]
    csv_payload = b"observation_uid,value\nu20,10\nu21,20\n"
    write_deterministic_submission_zip(
        baseline,
        json_name="submission.json",
        json_bytes=json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8"),
        csv_payloads={"data/q1.csv": csv_payload},
    )

    corpus = root / "corpus"
    source_dir = (
        corpus
        / "ABC"
        / "2021"
        / "ABC_financial_statements_2021_consolidated"
    )
    source_dir.mkdir(parents=True)
    (source_dir / "ABC_financial_statements_2021_consolidated_extracted.txt").write_text(
        "<table><tr><td>2020</td><td>10</td></tr>"
        "<tr><td>2021</td><td>20</td></tr></table>\n",
        encoding="utf-8",
    )

    database = root / "silver.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY,
            directory_doc_id TEXT NOT NULL,
            line_start_1based INTEGER NOT NULL
        );
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY,
            table_uid TEXT NOT NULL,
            value_decimal_text TEXT,
            value_source_raw TEXT,
            directory_doc_id TEXT NOT NULL
        );
        INSERT INTO tables VALUES (
            'table-1', 'ABC_financial_statements_2021_consolidated', 1
        );
        INSERT INTO observations VALUES (
            'u20', 'table-1', '10', '10', 'ABC_financial_statements_2021_consolidated'
        );
        """
    )
    connection.execute(
        "INSERT INTO observations VALUES (?, ?, ?, ?, ?)",
        (
            "u21",
            "table-1",
            source_value,
            "20",
            "ABC_financial_statements_2021_consolidated",
        ),
    )
    connection.commit()
    connection.close()

    ledger = root / "repair.json"
    ledger.write_text(
        json.dumps(
            {
                "baseline": {
                    "zip_path": str(baseline),
                    "zip_sha256": _sha256(baseline),
                },
                "a6_database": {
                    "database_path": str(database),
                    "database_sha256": _sha256(database),
                },
                "repairs": [
                    {"qid": 1, "direction": "max", "years": [2020, 2021]}
                ],
                "simplifications": [],
            }
        ),
        encoding="utf-8",
    )
    return baseline, database, corpus, ledger


def test_rule3_candidate_is_data_driven_traceable_and_deterministic(tmp_path: Path) -> None:
    baseline, database, corpus, ledger = _fixture(tmp_path)
    first = build_rule3_compliance_candidate(
        baseline_zip=baseline,
        a6_database=database,
        corpus_root=corpus,
        repair_ledger=ledger,
        output_zip=tmp_path / "first.zip",
    )
    second = build_rule3_compliance_candidate(
        baseline_zip=baseline,
        a6_database=database,
        corpus_root=corpus,
        repair_ledger=ledger,
        output_zip=tmp_path / "second.zip",
    )

    assert first.repaired_qids == (1,)
    assert first.csv_rows_verified == 2
    assert first.a6_uid_rows_verified == 2
    assert first.source_locators_verified == 1
    assert first.retrieval_rebound_qids == (1,)
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    with zipfile.ZipFile(first.zip_path) as archive:
        records = json.loads(archive.read("submission.json"))
        query = records[0]["pandas_query"]
        frame = pd.read_csv(io.BytesIO(archive.read("data/q1.csv")))
        validate_query(query, {"df1"})
        assert execute_query(query, {"df1": frame}) == 2021.0
        frame.loc[frame["observation_uid"] == "u20", "value"] = 30
        assert execute_query(query, {"df1": frame}) == 2020.0
        assert records[0]["answer"] == 2021.0
        assert records[0]["relevant_tables"] == [
            "ABC_financial_statements_2021_consolidated|1"
        ]


def test_rule3_candidate_fails_closed_on_a6_value_mismatch(tmp_path: Path) -> None:
    baseline, database, corpus, ledger = _fixture(tmp_path, source_value="19")

    with pytest.raises(SubmissionBuildError, match="differs from active A6"):
        build_rule3_compliance_candidate(
            baseline_zip=baseline,
            a6_database=database,
            corpus_root=corpus,
            repair_ledger=ledger,
            output_zip=tmp_path / "blocked.zip",
        )


def test_rewrite_rejects_non_zero_multiplier_query() -> None:
    with pytest.raises(SubmissionBuildError, match="unrecognized"):
        rewrite_legacy_arg_period_query(
            "float(2021 + float(df1['value'].values[0]))",
            [2020, 2021],
            direction="max",
        )


def test_simplifier_removes_discarded_data_and_encoded_boolean_flags() -> None:
    query = (
        "float(((0 + 0 * df1['value'].values[0] > 0) and "
        "(df1['value'].values[1] > 3)) + "
        "((1 + 0 * df1['value'].values[0] > 0) and "
        "(df1['value'].values[2] > 3)))"
    )
    simplified = simplify_zero_multiplier_query(query)

    assert "0 *" not in simplified
    assert "values[0]" not in simplified
    assert execute_query(
        simplified,
        {"df1": pd.DataFrame({"value": [100, 100, 4]})},
    ) == 1.0
