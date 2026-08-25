from __future__ import annotations

from pathlib import Path

import pytest
import sqlite3

from text2pandas.infrastructure.paths import ProjectPathError, ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots, verify_sqlite_contract


def _config(root: Path, content: str) -> ProjectPaths:
    (root / "src").mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    target = root / "configs" / "datasets"
    target.mkdir(parents=True)
    (target / "active_snapshot.yaml").write_text(content, encoding="utf-8")
    return ProjectPaths.from_repo_root(root, environ={})


def test_load_active_snapshots_resolves_canonical_lineage(tmp_path: Path) -> None:
    paths = _config(
        tmp_path,
        """
raw:
  dataset_id: btc
  snapshot_id: raw-1
  path: raw/btc
a6:
  build_id: a6-1
  path: processed/a6/a6-1
retrieval:
  source_a6_build_id: a6-1
  index_id: idx-1
  path: indexes/retrieval/a6-1/idx-1
""",
    )

    active = ActiveSnapshots.load(paths)

    assert active.raw_path == paths.raw_btc
    assert active.a6_path == paths.a6_snapshot("a6-1")
    assert active.retrieval_path == paths.retrieval_snapshot("a6-1", "idx-1")


def test_load_active_snapshots_rejects_cross_build_retrieval(tmp_path: Path) -> None:
    paths = _config(
        tmp_path,
        """
raw: {dataset_id: btc, snapshot_id: raw-1, path: raw/btc}
a6: {build_id: a6-1, path: processed/a6/a6-1}
retrieval:
  source_a6_build_id: a6-2
  index_id: idx-1
  path: indexes/retrieval/a6-2/idx-1
""",
    )

    with pytest.raises(ProjectPathError, match="does not reference"):
        ActiveSnapshots.load(paths)


def test_load_active_snapshots_rejects_path_escape(tmp_path: Path) -> None:
    paths = _config(
        tmp_path,
        """
raw: {dataset_id: btc, snapshot_id: raw-1, path: ../raw/btc}
a6: {build_id: a6-1, path: processed/a6/a6-1}
retrieval:
  source_a6_build_id: a6-1
  index_id: idx-1
  path: indexes/retrieval/a6-1/idx-1
""",
    )

    with pytest.raises(ProjectPathError, match="escapes data root"):
        ActiveSnapshots.load(paths)


def test_verify_sqlite_contract_reports_missing_table_and_columns() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE observations (observation_uid TEXT)")

    report = verify_sqlite_contract(
        connection,
        {
            "observations": frozenset({"observation_uid", "table_uid"}),
            "tables": frozenset({"table_uid"}),
        },
        "runtime",
    )

    assert [(item.name, item.ok) for item in report] == [
        ("runtime.observations", False),
        ("runtime.tables", False),
    ]
    assert "table_uid" in report[0].detail
    assert report[1].detail == "missing table"
