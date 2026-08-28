"""Read-only identity of the source tree used for a generated run."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_source_identity(repo_root: Path) -> dict[str, object]:
    """Return commit and runtime-relevant dirty state without mutation.

    Match the release environment gate: every tracked change is dirty, while
    an untracked file is dirty only when it lives in a source/config path that
    can affect execution.  Untracked reports must not invalidate an otherwise
    commit-addressable run.
    """

    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()

    try:
        tracked = run("status", "--porcelain", "--untracked-files=no")
        untracked_source = run(
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "src",
            "tools",
            "configs",
            "Makefile",
            "pyproject.toml",
        )
        return {
            "git_commit": run("rev-parse", "HEAD"),
            "git_dirty": bool(tracked or untracked_source),
        }
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}
