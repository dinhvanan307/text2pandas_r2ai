"""Active dataset snapshots and lightweight lineage verification."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from text2pandas.infrastructure.paths import ProjectPathError, ProjectPaths


A6_RUNTIME_SCHEMA: dict[str, frozenset[str]] = {
    "documents": frozenset({"document_uid", "directory_doc_id", "ticker", "doc_year", "basis"}),
    "tables": frozenset(
        {"table_uid", "directory_doc_id", "locator", "evidence_ref", "line_start_1based"}
    ),
    "observations": frozenset(
        {
            "observation_uid",
            "table_uid",
            "directory_doc_id",
            "row_path_text",
            "col_path_text",
            "metric_code",
            "value_decimal_text",
            "unit_kind",
            "scale_exponent",
            "period_end",
            "period_role",
            "is_restated",
        }
    ),
}

RETRIEVAL_RUNTIME_SCHEMA: dict[str, frozenset[str]] = {
    "table_cards": frozenset(
        {
            "table_uid",
            "doc_id",
            "locator",
            "evidence_ref",
            "ticker",
            "doc_year",
            "metric_codes",
            "periods",
            "retrieval_ready",
        }
    ),
    "table_cards_fts": frozenset(
        {"table_uid", "ticker", "section_text", "context_clean", "row_labels", "col_labels"}
    ),
}


@dataclass(frozen=True, slots=True)
class ActiveSnapshots:
    """Dataset identities selected by ``configs/datasets/active_snapshot.yaml``."""

    raw_dataset_id: str
    raw_snapshot_id: str
    raw_path: Path
    a6_build_id: str
    a6_path: Path
    retrieval_source_a6_build_id: str
    retrieval_index_id: str
    retrieval_path: Path

    @classmethod
    def load(cls, paths: ProjectPaths) -> ActiveSnapshots:
        config = _mapping(
            yaml.safe_load(paths.active_snapshot_config.read_text(encoding="utf-8")),
            "root",
        )
        raw = _mapping(config.get("raw"), "raw")
        a6 = _mapping(config.get("a6"), "a6")
        retrieval = _mapping(config.get("retrieval"), "retrieval")

        active = cls(
            raw_dataset_id=_text(raw, "dataset_id"),
            raw_snapshot_id=_text(raw, "snapshot_id"),
            raw_path=_under_data_root(paths, _text(raw, "path")),
            a6_build_id=_text(a6, "build_id"),
            a6_path=_under_data_root(paths, _text(a6, "path")),
            retrieval_source_a6_build_id=_text(retrieval, "source_a6_build_id"),
            retrieval_index_id=_text(retrieval, "index_id"),
            retrieval_path=_under_data_root(paths, _text(retrieval, "path")),
        )
        if active.raw_path != paths.raw_btc:
            raise ProjectPathError(f"active raw path is not canonical: {active.raw_path}")
        if active.a6_path != paths.a6_snapshot(active.a6_build_id):
            raise ProjectPathError(f"active A6 path is not canonical: {active.a6_path}")
        expected_retrieval = paths.retrieval_snapshot(
            active.retrieval_source_a6_build_id,
            active.retrieval_index_id,
        )
        if active.retrieval_path != expected_retrieval:
            raise ProjectPathError(
                f"active retrieval path is not canonical: {active.retrieval_path}"
            )
        if active.retrieval_source_a6_build_id != active.a6_build_id:
            raise ProjectPathError(
                "active retrieval index does not reference the active A6 build"
            )
        return active


@dataclass(frozen=True, slots=True)
class VerificationItem:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class VerificationReport:
    items: tuple[VerificationItem, ...]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items)


def verify_active_snapshots(
    paths: ProjectPaths,
    scope: str = "all",
) -> VerificationReport:
    """Verify active snapshot identity, lineage, counts, and SQLite contracts.

    This deliberately avoids hashing multi-gigabyte databases. Payload digests are
    frozen in manifests and provenance; this gate verifies that the selected local
    materialization has the declared identity and schema.
    """

    if scope not in {"raw", "a6", "retrieval", "all"}:
        raise ValueError(f"unknown verification scope: {scope}")
    active = ActiveSnapshots.load(paths)
    items: list[VerificationItem] = []
    if scope in {"raw", "all"}:
        _verify_raw(active, items)
    if scope in {"a6", "all"}:
        _verify_a6(active, items)
    if scope in {"retrieval", "all"}:
        _verify_retrieval(active, items)
    return VerificationReport(tuple(items))


def _verify_raw(active: ActiveSnapshots, items: list[VerificationItem]) -> None:
    manifest = _json_manifest(active.raw_path, items, "raw")
    if manifest is None:
        return
    _expect(items, "raw.dataset_id", manifest.get("dataset_id"), active.raw_dataset_id)
    _expect(items, "raw.snapshot_id", manifest.get("snapshot_id"), active.raw_snapshot_id)

    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    statements = active.raw_path / "financial_statements"
    questions = active.raw_path / "questions" / "questions.jsonl"
    companies = active.raw_path / "metadata" / "companies.csv"
    _count(
        items,
        "raw.financial_statement_txt",
        statements.rglob("*.txt"),
        counts.get("financial_statement_txt"),
    )
    _count_jsonl(items, "raw.question", questions, counts.get("question"))
    _count(
        items,
        "raw.ticker",
        (entry for entry in statements.iterdir() if entry.is_dir()) if statements.is_dir() else (),
        counts.get("ticker"),
    )
    _exists(items, "raw.companies", companies)


def _verify_a6(active: ActiveSnapshots, items: list[VerificationItem]) -> None:
    manifest = _json_manifest(active.a6_path, items, "a6")
    if manifest is None:
        return
    declared = manifest.get("build_id", manifest.get("source_build_id"))
    _expect(items, "a6.build_id", declared, active.a6_build_id)
    database = active.a6_path / "silver.db"
    _exists(items, "a6.silver.db", database)
    if not database.is_file():
        return
    with _readonly_sqlite(database) as connection:
        items.extend(verify_sqlite_contract(connection, A6_RUNTIME_SCHEMA, "a6.runtime"))
        meta = dict(connection.execute("SELECT key, value FROM build_meta"))
        _expect(items, "a6.build_meta.build_id", meta.get("build_id"), active.a6_build_id)
        expected = _nested(manifest, "dataframes", "table_cards")
        expected = expected.get("rows") if isinstance(expected, dict) else None
        actual = connection.execute("SELECT COUNT(*) FROM table_cards").fetchone()[0]
        _expect(items, "a6.table_cards", actual, expected)


def _verify_retrieval(active: ActiveSnapshots, items: list[VerificationItem]) -> None:
    manifest = _json_manifest(active.retrieval_path, items, "retrieval")
    if manifest is None:
        return
    _expect(items, "retrieval.index_id", manifest.get("index_id"), active.retrieval_index_id)
    _expect(
        items,
        "retrieval.source_a6_build_id",
        manifest.get("source_a6_build_id"),
        active.a6_build_id,
    )
    database = active.retrieval_path / str(manifest.get("database", "retrieval.db"))
    _exists(items, "retrieval.db", database)
    if not database.is_file():
        return
    expected_bytes = manifest.get("database_bytes")
    _expect(items, "retrieval.database_bytes", database.stat().st_size, expected_bytes)
    with _readonly_sqlite(database) as connection:
        items.extend(
            verify_sqlite_contract(connection, RETRIEVAL_RUNTIME_SCHEMA, "retrieval.runtime")
        )
        meta = dict(connection.execute("SELECT key, value FROM build_meta"))
        _expect(
            items,
            "retrieval.build_meta.build_id",
            meta.get("build_id"),
            active.a6_build_id,
        )
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        required = set(manifest.get("indexes_added", []))
        missing = sorted(required - indexes)
        items.append(
            VerificationItem(
                "retrieval.indexes",
                not missing,
                "present=" + ",".join(sorted(required))
                if not missing
                else "missing=" + ",".join(missing),
            )
        )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ProjectPathError(f"active snapshot {label} must be a mapping")
    return value


def _text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectPathError(f"active snapshot field {key!r} must be non-empty text")
    return value.strip()


def _under_data_root(paths: ProjectPaths, relative: str) -> Path:
    candidate = (paths.data_root / relative).resolve(strict=False)
    try:
        candidate.relative_to(paths.data_root)
    except ValueError as error:
        raise ProjectPathError(f"snapshot path escapes data root: {relative}") from error
    return candidate


def _json_manifest(
    root: Path,
    items: list[VerificationItem],
    label: str,
) -> dict[str, Any] | None:
    path = root / "manifest.json"
    if not path.is_file():
        items.append(VerificationItem(f"{label}.manifest", False, f"missing {path}"))
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        items.append(VerificationItem(f"{label}.manifest", False, str(error)))
        return None
    if not isinstance(value, dict):
        items.append(VerificationItem(f"{label}.manifest", False, "root is not an object"))
        return None
    items.append(VerificationItem(f"{label}.manifest", True, str(path)))
    return value


def _exists(items: list[VerificationItem], name: str, path: Path) -> None:
    items.append(VerificationItem(name, path.is_file(), str(path)))


def _expect(items: list[VerificationItem], name: str, actual: Any, expected: Any) -> None:
    items.append(
        VerificationItem(name, actual == expected, f"actual={actual!r}, expected={expected!r}")
    )


def _count(items: list[VerificationItem], name: str, values: Any, expected: Any) -> None:
    _expect(items, name, sum(1 for _ in values), expected)


def _count_jsonl(items: list[VerificationItem], name: str, path: Path, expected: Any) -> None:
    if not path.is_file():
        items.append(VerificationItem(name, False, f"missing {path}"))
        return
    with path.open(encoding="utf-8") as handle:
        actual = sum(1 for line in handle if line.strip())
    _expect(items, name, actual, expected)


def _nested(mapping: Mapping[str, Any], parent: str, key: str) -> Any:
    child = mapping.get(parent)
    return child.get(key) if isinstance(child, dict) else None


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def verify_sqlite_contract(
    connection: sqlite3.Connection,
    required: Mapping[str, frozenset[str]],
    label: str,
) -> tuple[VerificationItem, ...]:
    """Verify tables and columns consumed by the production runtime."""

    available = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }
    items: list[VerificationItem] = []
    for table, expected_columns in required.items():
        if table not in available:
            items.append(VerificationItem(f"{label}.{table}", False, "missing table"))
            continue
        actual_columns = {
            row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        missing = sorted(expected_columns - actual_columns)
        items.append(
            VerificationItem(
                f"{label}.{table}",
                not missing,
                f"columns={len(actual_columns)}" if not missing else f"missing columns={missing}",
            )
        )
    return tuple(items)
