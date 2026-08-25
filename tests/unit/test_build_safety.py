from __future__ import annotations

from pathlib import Path

import pytest

from text2pandas.infrastructure.builds import (
    BuildSafetyError,
    assert_not_active_snapshot,
    build_output_path,
    publish_new_file,
)
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots


def _active(root: Path) -> tuple[ProjectPaths, ActiveSnapshots]:
    paths = ProjectPaths.from_repo_root(root, environ={})
    active = ActiveSnapshots(
        raw_dataset_id="btc",
        raw_snapshot_id="raw-1",
        raw_path=paths.raw_btc,
        a6_build_id="a6-1",
        a6_path=paths.a6_snapshot("a6-1"),
        retrieval_source_a6_build_id="a6-1",
        retrieval_index_id="idx-1",
        retrieval_path=paths.retrieval_snapshot("a6-1", "idx-1"),
    )
    return paths, active


def test_build_output_is_versioned_outside_data_root(tmp_path: Path) -> None:
    paths, active = _active(tmp_path)
    target = build_output_path(paths, "legacy-build", "run-001", "silver.sqlite")
    assert target == tmp_path / "artifacts" / "runs" / "legacy-build" / "run-001" / "silver.sqlite"
    assert_not_active_snapshot(target, active)


def test_active_snapshot_destinations_are_rejected(tmp_path: Path) -> None:
    _, active = _active(tmp_path)
    with pytest.raises(BuildSafetyError, match="active snapshot"):
        assert_not_active_snapshot(active.a6_path / "silver.db", active)


def test_publish_is_exclusive_and_preserves_existing_file(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "run" / "output.db"
    source.write_bytes(b"first")
    publish_new_file(source, destination)
    assert destination.read_bytes() == b"first"

    source.write_bytes(b"second")
    with pytest.raises(BuildSafetyError, match="already exists"):
        publish_new_file(source, destination)
    assert destination.read_bytes() == b"first"


def test_build_filename_cannot_escape_run_directory(tmp_path: Path) -> None:
    paths, _ = _active(tmp_path)
    with pytest.raises(BuildSafetyError, match="must not contain directories"):
        build_output_path(paths, "legacy-build", "run-001", "../silver.db")
