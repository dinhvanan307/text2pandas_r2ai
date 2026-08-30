from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.submission.build_adjudicated_factorized_candidate import (
    PatchError,
    _compose_records,
    _fetch_observations,
    _load_manifest,
    _materialized_csv,
    _materialized_csv_path,
)
from tools.submission.build_factorized_hybrid import InputBundle

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "configs/evaluation/adjudicated_answer_patch_a17_v1.json"


def _record(
    qid: int,
    *,
    answer: float,
    emitted: bool,
    tables: list[str],
) -> dict[str, object]:
    return {
        "id": qid,
        "question": f"Question {qid}",
        "answer": answer,
        "relevant_docs": list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables)),
        "relevant_tables": tables,
        "evidence": (
            [{"variable": "df1", "csv_path": f"data/base_{qid}.csv"}]
            if emitted
            else []
        ),
        "pandas_query": "float(df1['value'].values[0])" if emitted else "",
    }


def _bundle(path: str, records: list[dict[str, object]]) -> InputBundle:
    return InputBundle(
        path=Path(path),
        records=tuple(records),
        by_qid={int(record["id"]): record for record in records},
        zip_sha256="0" * 64,
        submission_json_sha256="1" * 64,
        members=frozenset(("submission.json",)),
    )


def test_release_manifest_locks_exact_a17_policy() -> None:
    manifest = _load_manifest(MANIFEST)

    assert manifest["patch_id"] == "adjudicated-answer-patch-a17-v1"
    assert len(manifest["patches"]) == 17
    assert sum(item["decision"] == "CORRECT" for item in manifest["patches"]) == 4
    assert sum(item["decision"] == "FILL" for item in manifest["patches"]) == 13
    assert manifest["policy"]["p0_enabled"] is False
    assert manifest["policy"]["model_gold_used"] is False
    assert manifest["policy"]["semantic_v3_promoted"] is False


def test_manifest_rejects_incoherent_emitted_counts(tmp_path: Path) -> None:
    payload = MANIFEST.read_text(encoding="utf-8").replace(
        '"expected_output_emitted": 638',
        '"expected_output_emitted": 639',
    )
    path = tmp_path / "bad_manifest.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(PatchError, match="expected_baseline_emitted \\+ expected_fills"):
        _load_manifest(path)


def test_composition_changes_only_allowlist_and_uses_retrieval_owner() -> None:
    answer = _bundle(
        "answer.zip",
        [
            _record(1, answer=10.0, emitted=True, tables=["BASE|1"]),
            _record(2, answer=0.0, emitted=False, tables=["BASE|2"]),
            _record(3, answer=30.0, emitted=True, tables=["BASE|3"]),
        ],
    )
    retrieval = _bundle(
        "retrieval.zip",
        [
            _record(1, answer=-1.0, emitted=False, tables=["RET|11"]),
            _record(2, answer=-1.0, emitted=False, tables=["RET|12"]),
            _record(3, answer=-1.0, emitted=False, tables=["RET|13"]),
        ],
    )
    replacements = {
        1: {
            "answer": 11.0,
            "evidence": [{"variable": "df1", "csv_path": "data/a17_1.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        },
        2: {
            "answer": 22.0,
            "evidence": [{"variable": "df1", "csv_path": "data/a17_2.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        },
    }
    patches = {
        1: {"decision": "CORRECT"},
        2: {"decision": "FILL"},
    }

    output, report = _compose_records(
        answer,
        retrieval,
        replacements,
        patches,
        expected_count=3,
        table_cap=10,
    )

    assert [record["answer"] for record in output] == [11.0, 22.0, 30.0]
    assert [record["relevant_tables"] for record in output] == [
        ["RET|11"],
        ["RET|12"],
        ["RET|13"],
    ]
    assert output[2]["evidence"] == answer.records[2]["evidence"]
    assert output[2]["pandas_query"] == answer.records[2]["pandas_query"]
    assert report["changed_answer_qids"] == [1, 2]
    assert report["unchanged_answer_qids"] == 1
    assert report["corrections"] == 1
    assert report["fills"] == 1


def test_composition_rejects_fill_over_emitted_baseline() -> None:
    answer = _bundle(
        "answer.zip",
        [_record(1, answer=10.0, emitted=True, tables=["BASE|1"])],
    )
    retrieval = _bundle(
        "retrieval.zip",
        [_record(1, answer=0.0, emitted=False, tables=["RET|1"])],
    )
    replacement = {
        1: {
            "answer": 11.0,
            "evidence": [{"variable": "df1", "csv_path": "data/a17.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        }
    }

    with pytest.raises(PatchError, match="FILL patch targets an emitted baseline"):
        _compose_records(
            answer,
            retrieval,
            replacement,
            {1: {"decision": "FILL"}},
            expected_count=1,
            table_cap=10,
        )


def test_namespaced_evidence_path_is_stable_and_subset_sensitive() -> None:
    first = _materialized_csv_path("a" * 16, ["1" * 16])
    again = _materialized_csv_path("a" * 16, ["1" * 16])
    second = _materialized_csv_path("a" * 16, ["2" * 16])

    assert first == again
    assert first != second
    assert first.startswith("data/a17_")
    assert first.endswith(".csv")


def test_a6_materialization_preserves_uid_order_and_decimal_text() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY,
            locator TEXT NOT NULL
        );
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY,
            table_uid TEXT NOT NULL,
            value_decimal_text TEXT,
            directory_doc_id TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            row_path_text TEXT,
            col_path_text TEXT
        );
        INSERT INTO tables VALUES ('aaaaaaaaaaaaaaaa', 'line:7');
        INSERT INTO observations VALUES (
            '1111111111111111', 'aaaaaaaaaaaaaaaa', '10.250',
            'DOC', 'DOC|line:7', 'Revenue', '2025'
        );
        """
    )

    expanded = _fetch_observations(
        connection,
        qid=7,
        table_uid="aaaaaaaaaaaaaaaa",
        observation_uids=["1111111111111111"],
    )
    payload = _materialized_csv(expanded)

    assert expanded[0]["value_decimal_text"] == "10.250"
    assert payload == b"observation_uid,value\r\n1111111111111111,10.250\r\n"


def test_a6_materialization_rejects_wrong_table_binding() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE tables (
            table_uid TEXT PRIMARY KEY,
            locator TEXT NOT NULL
        );
        CREATE TABLE observations (
            observation_uid TEXT PRIMARY KEY,
            table_uid TEXT NOT NULL,
            value_decimal_text TEXT,
            directory_doc_id TEXT NOT NULL,
            evidence_ref TEXT NOT NULL,
            row_path_text TEXT,
            col_path_text TEXT
        );
        INSERT INTO tables VALUES ('bbbbbbbbbbbbbbbb', 'line:9');
        INSERT INTO observations VALUES (
            '2222222222222222', 'bbbbbbbbbbbbbbbb', '5',
            'DOC', 'DOC|line:9', 'Profit', '2025'
        );
        """
    )

    with pytest.raises(PatchError, match="belongs to bbbbbbbbbbbbbbbb"):
        _fetch_observations(
            connection,
            qid=9,
            table_uid="aaaaaaaaaaaaaaaa",
            observation_uids=["2222222222222222"],
        )
