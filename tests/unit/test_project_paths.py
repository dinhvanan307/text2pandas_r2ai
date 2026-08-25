from pathlib import Path

import pytest

from text2pandas.infrastructure.paths import ProjectPathError, ProjectPaths


def test_default_roots_are_repository_local(tmp_path: Path) -> None:
    paths = ProjectPaths.from_repo_root(tmp_path, environ={})

    assert paths.repo_root == tmp_path
    assert paths.data_root == tmp_path / "data"
    assert paths.artifact_root == tmp_path / "artifacts"
    assert paths.raw_btc == tmp_path / "data/raw/btc"


def test_roots_can_be_overridden(tmp_path: Path) -> None:
    paths = ProjectPaths.from_repo_root(
        tmp_path,
        environ={"T2P_DATA_ROOT": "runtime/data", "T2P_ARTIFACT_ROOT": "/tmp/t2p-artifacts"},
    )

    assert paths.data_root == tmp_path / "runtime/data"
    assert paths.artifact_root == Path("/tmp/t2p-artifacts").resolve(strict=False)


def test_discover_walks_up_to_repository_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "src/text2pandas/domain"
    nested.mkdir(parents=True)

    paths = ProjectPaths.discover(nested, environ={})

    assert paths.repo_root == tmp_path


@pytest.mark.parametrize("unsafe_id", ["../escape", "a/b", "", "with space"])
def test_snapshot_identifiers_reject_path_traversal(tmp_path: Path, unsafe_id: str) -> None:
    paths = ProjectPaths.from_repo_root(tmp_path, environ={})

    with pytest.raises(ProjectPathError):
        paths.a6_snapshot(unsafe_id)
