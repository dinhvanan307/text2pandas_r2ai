"""Centralized filesystem layout for source, data, and generated artifacts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ProjectPathError(ValueError):
    """Raised when the repository layout or a snapshot identifier is invalid."""


def _safe_id(value: str, label: str) -> str:
    if not _SAFE_ID.fullmatch(value):
        raise ProjectPathError(f"invalid {label}: {value!r}")
    return value


def _resolve_root(value: str | os.PathLike[str], repo_root: Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve(strict=False)


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Resolved project roots with version-safe dataset helpers."""

    repo_root: Path
    data_root: Path
    artifact_root: Path

    @classmethod
    def from_repo_root(
        cls,
        repo_root: str | os.PathLike[str],
        environ: Mapping[str, str] | None = None,
    ) -> "ProjectPaths":
        resolved_repo = Path(repo_root).expanduser().resolve(strict=False)
        values = os.environ if environ is None else environ
        data_value = values.get("T2P_DATA_ROOT", "data")
        artifact_value = values.get("T2P_ARTIFACT_ROOT", "artifacts")
        return cls(
            repo_root=resolved_repo,
            data_root=_resolve_root(data_value, resolved_repo),
            artifact_root=_resolve_root(artifact_value, resolved_repo),
        )

    @classmethod
    def discover(
        cls,
        start: str | os.PathLike[str] | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> "ProjectPaths":
        cursor = Path.cwd() if start is None else Path(start)
        cursor = cursor.expanduser().resolve(strict=False)
        if cursor.is_file():
            cursor = cursor.parent
        for candidate in (cursor, *cursor.parents):
            if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
                return cls.from_repo_root(candidate, environ=environ)
        raise ProjectPathError(f"cannot discover repository root from {cursor}")

    @property
    def raw_btc(self) -> Path:
        return self.data_root / "raw" / "btc"

    @property
    def active_snapshot_config(self) -> Path:
        return self.repo_root / "configs" / "datasets" / "active_snapshot.yaml"

    def a6_snapshot(self, build_id: str) -> Path:
        return self.data_root / "processed" / "a6" / _safe_id(build_id, "A6 build_id")

    def retrieval_snapshot(self, a6_build_id: str, index_id: str) -> Path:
        return (
            self.data_root
            / "indexes"
            / "retrieval"
            / _safe_id(a6_build_id, "A6 build_id")
            / _safe_id(index_id, "retrieval index_id")
        )

    def run_dir(self, pipeline: str, run_id: str) -> Path:
        return (
            self.artifact_root
            / "runs"
            / _safe_id(pipeline, "pipeline")
            / _safe_id(run_id, "run_id")
        )
