"""Read-only identity of the source tree used for a generated run."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_source_identity(repo_root: Path) -> dict[str, object]:
    """Return commit and dirty state without mutating the repository."""

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
        return {
            "git_commit": run("rev-parse", "HEAD"),
            "git_dirty": bool(run("status", "--porcelain")),
        }
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": None, "git_dirty": None}
