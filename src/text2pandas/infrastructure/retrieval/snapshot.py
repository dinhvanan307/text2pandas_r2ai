"""Build immutable retrieval snapshots from a certified A6 release database."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from text2pandas.infrastructure.checksums import sha256_file


SNAPSHOT_SCHEMA_VERSION = "1.0"
INDEX_SPEC_VERSION = "1.0"
INDEX_SPECS: tuple[tuple[str, str], ...] = (
    ("ix_tc_ticker_year", "table_cards(ticker, doc_year)"),
    ("ix_tc_stmt_ticker", "table_cards(statement_type, ticker)"),
    ("ix_doc_tky", "documents(ticker, doc_year, basis)"),
    ("ix_obs_tab_period", "observations(table_uid, period_end)"),
)
REQUIRED_SOURCE_COLUMNS: dict[str, frozenset[str]] = {
    "build_meta": frozenset({"key", "value"}),
    "table_cards": frozenset({"ticker", "doc_year", "statement_type"}),
    "documents": frozenset({"ticker", "doc_year", "basis"}),
    "observations": frozenset({"table_uid", "period_end"}),
    "table_cards_fts": frozenset({"table_uid"}),
}
COUNT_TABLES = ("documents", "tables", "table_cards", "observations", "rows")


@dataclass(frozen=True, slots=True)
class RetrievalSnapshotResult:
    build_id: str
    index_id: str
    root: Path
    database: Path
    manifest: Path


def retrieval_index_id() -> str:
    payload = {
        "index_spec_version": INDEX_SPEC_VERSION,
        "indexes": [{"name": name, "sql_target": target} for name, target in INDEX_SPECS],
        "analyze": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_retrieval_snapshot(
    source_db: Path,
    output_root: Path,
    *,
    expected_build_id: str | None = None,
) -> RetrievalSnapshotResult:
    """Copy, index, verify, and atomically publish one retrieval snapshot.

    ``output_root`` is immutable: an existing path is always rejected. A
    sibling staging directory prevents consumers from observing a partial DB.
    """

    source_db = source_db.resolve(strict=True)
    output_root = output_root.resolve(strict=False)
    if output_root.exists():
        raise FileExistsError(f"immutable retrieval snapshot already exists: {output_root}")

    build_id = _validate_source(source_db, expected_build_id)
    index_id = retrieval_index_id()
    if output_root.name != index_id or output_root.parent.name != build_id:
        raise ValueError(
            "output path must end with "
            f"<source_build_id>/<index_id>: {build_id}/{index_id}"
        )

    staging = output_root.parent / f".{output_root.name}.staging-{os.getpid()}"
    if staging.exists():
        raise FileExistsError(f"staging path already exists: {staging}")
    staging.mkdir(parents=True)
    database = staging / "retrieval.db"
    try:
        shutil.copy2(source_db, database)
        _materialize_indexes(database)
        counts = _verify_database(database, build_id)
        manifest = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "index_spec_version": INDEX_SPEC_VERSION,
            "index_id": index_id,
            "source_a6_build_id": build_id,
            "source_a6_db": str(source_db),
            "source_a6_db_bytes": source_db.stat().st_size,
            "source_a6_db_sha256": sha256_file(source_db),
            "database": database.name,
            "database_bytes": database.stat().st_size,
            "database_sha256": sha256_file(database),
            "config_fingerprint": index_id,
            "indexes_added": [name for name, _ in INDEX_SPECS],
            "row_counts": counts,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(output_root)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise

    return RetrievalSnapshotResult(
        build_id,
        index_id,
        output_root,
        output_root / "retrieval.db",
        output_root / "manifest.json",
    )


def _validate_source(source_db: Path, expected_build_id: str | None) -> str:
    with sqlite3.connect(f"file:{source_db}?mode=ro", uri=True) as connection:
        _require_columns(connection, REQUIRED_SOURCE_COLUMNS)
        meta = dict(connection.execute("SELECT key, value FROM build_meta"))
        build_id = str(meta.get("build_id") or "").strip()
    if not build_id:
        raise ValueError("source A6 database has no build_meta.build_id")
    if expected_build_id is not None and build_id != expected_build_id:
        raise ValueError(
            f"source build_id is {build_id!r}, expected {expected_build_id!r}"
        )
    return build_id


def _materialize_indexes(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        for name, target in INDEX_SPECS:
            connection.execute(f'CREATE INDEX "{name}" ON {target}')
        connection.execute("ANALYZE")
        connection.commit()


def _verify_database(database: Path, build_id: str) -> dict[str, int]:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity != ("ok",):
            raise ValueError(f"retrieval database quick_check failed: {integrity!r}")
        _require_columns(connection, REQUIRED_SOURCE_COLUMNS)
        meta = dict(connection.execute("SELECT key, value FROM build_meta"))
        if meta.get("build_id") != build_id:
            raise ValueError("retrieval database lost source build identity")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        missing = [name for name, _ in INDEX_SPECS if name not in indexes]
        if missing:
            raise ValueError(f"retrieval database is missing indexes: {missing}")
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in COUNT_TABLES
        }


def _require_columns(
    connection: sqlite3.Connection,
    required: dict[str, frozenset[str]],
) -> None:
    available = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    for table, columns in required.items():
        if table not in available:
            raise ValueError(f"source A6 database is missing {table}")
        actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
        missing = sorted(columns - actual)
        if missing:
            raise ValueError(f"source A6 table {table} is missing columns: {missing}")
