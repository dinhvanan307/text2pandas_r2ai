from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from text2pandas.pipelines.retrieval.evalkit.runner import (
    EvalConfig,
    checkpoint_path,
    resolve_evaluation_dataset,
)


def _snapshot(root: Path, build_id: str, index_id: str, digest: str) -> Path:
    target = root / "snapshot" / "retrieval.db"
    target.parent.mkdir(parents=True)
    with sqlite3.connect(target) as connection:
        connection.execute("CREATE TABLE build_meta (key TEXT, value TEXT)")
        connection.execute("INSERT INTO build_meta VALUES ('build_id', ?)", (build_id,))
    manifest = {
        "source_a6_build_id": build_id,
        "index_id": index_id,
        "database": "retrieval.db",
        "database_bytes": target.stat().st_size,
        "database_sha256": digest,
    }
    (target.parent / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return target


def test_checkpoint_identity_includes_retrieval_snapshot(tmp_path: Path) -> None:
    db = _snapshot(tmp_path, "a6-1", "idx-1", "a" * 64)
    cfg = EvalConfig(tag="manual")

    path_a, dataset_a, evaluation_a = checkpoint_path(tmp_path, cfg, db)
    manifest_path = db.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["index_id"] = "idx-2"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    path_b, dataset_b, evaluation_b = checkpoint_path(tmp_path, cfg, db)

    assert dataset_a.sha != dataset_b.sha
    assert evaluation_a != evaluation_b
    assert path_a != path_b
    assert path_a.name.startswith("ek_manual_")


def test_resolver_rejects_database_size_drift(tmp_path: Path) -> None:
    db = _snapshot(tmp_path, "a6-1", "idx-1", "b" * 64)
    manifest_path = db.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["database_bytes"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="size"):
        resolve_evaluation_dataset(tmp_path, db)


def test_resolver_requires_manifest(tmp_path: Path) -> None:
    db = tmp_path / "retrieval.db"
    sqlite3.connect(db).close()

    with pytest.raises(ValueError, match="manifest"):
        resolve_evaluation_dataset(tmp_path, db)
