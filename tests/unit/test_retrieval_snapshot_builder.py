from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.retrieval.snapshot import (
    INDEX_SPECS,
    build_retrieval_snapshot,
    retrieval_index_id,
)


def _source(path: Path, build_id: str = "a6-test") -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE build_meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE documents (
                document_uid TEXT, ticker TEXT, doc_year INTEGER, basis TEXT
            );
            CREATE TABLE tables (table_uid TEXT);
            CREATE TABLE rows (row_uid TEXT);
            CREATE TABLE table_cards (
                table_uid TEXT, ticker TEXT, doc_year INTEGER, statement_type TEXT
            );
            CREATE TABLE observations (
                observation_uid TEXT, table_uid TEXT, period_end TEXT
            );
            CREATE TABLE table_cards_fts (table_uid TEXT);
            INSERT INTO documents VALUES ('d1', 'AAA', 2024, 'consolidated');
            INSERT INTO tables VALUES ('t1');
            INSERT INTO rows VALUES ('r1');
            INSERT INTO table_cards VALUES ('t1', 'AAA', 2024, 'balance_sheet');
            INSERT INTO observations VALUES ('o1', 't1', '2024-12-31');
            INSERT INTO table_cards_fts VALUES ('t1');
            """
        )
        connection.execute("INSERT INTO build_meta VALUES ('build_id', ?)", (build_id,))


def test_builder_publishes_verified_immutable_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "silver.db"
    _source(source)
    index_id = retrieval_index_id()
    output = tmp_path / "a6-test" / index_id

    result = build_retrieval_snapshot(source, output, expected_build_id="a6-test")

    manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
    assert result.index_id == index_id
    assert manifest["source_a6_build_id"] == "a6-test"
    assert manifest["source_a6_db_sha256"] == sha256_file(source)
    assert manifest["database_sha256"] == sha256_file(result.database)
    assert manifest["row_counts"] == {
        "documents": 1,
        "observations": 1,
        "rows": 1,
        "table_cards": 1,
        "tables": 1,
    }
    with sqlite3.connect(result.database) as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert {name for name, _ in INDEX_SPECS} <= indexes

    with pytest.raises(FileExistsError, match="immutable"):
        build_retrieval_snapshot(source, output, expected_build_id="a6-test")


def test_builder_rejects_cross_build_output_path(tmp_path: Path) -> None:
    source = tmp_path / "silver.db"
    _source(source)
    wrong = tmp_path / "another-build" / retrieval_index_id()

    with pytest.raises(ValueError, match="output path"):
        build_retrieval_snapshot(source, wrong)


def test_builder_rejects_declared_build_id_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "silver.db"
    _source(source)
    output = tmp_path / "a6-test" / retrieval_index_id()

    with pytest.raises(ValueError, match="expected"):
        build_retrieval_snapshot(source, output, expected_build_id="other")
