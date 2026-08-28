from __future__ import annotations

import subprocess
from pathlib import Path

from text2pandas.infrastructure.source_identity import git_source_identity


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_source_identity_ignores_only_untracked_non_runtime_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src/app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs/report.md").write_text("baseline\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "src/app.py", "docs/report.md")
    _git(tmp_path, "commit", "-qm", "initial")

    (tmp_path / "docs/untracked-report.md").write_text("audit\n", encoding="utf-8")
    assert git_source_identity(tmp_path)["git_dirty"] is False

    (tmp_path / "src/untracked_hotfix.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert git_source_identity(tmp_path)["git_dirty"] is True

    (tmp_path / "src/untracked_hotfix.py").unlink()
    (tmp_path / "docs/report.md").write_text("changed\n", encoding="utf-8")
    assert git_source_identity(tmp_path)["git_dirty"] is True
