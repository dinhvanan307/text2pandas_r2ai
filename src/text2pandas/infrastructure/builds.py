"""Safety primitives for generated build artifacts.

Active data snapshots are immutable inputs. Builders write to a versioned run
directory; promotion is a separate operation after verification.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots


class BuildSafetyError(RuntimeError):
    """Raised when a build could overwrite an existing or active artifact."""


def build_output_path(
    paths: ProjectPaths,
    pipeline: str,
    run_id: str,
    filename: str,
) -> Path:
    """Return an immutable run output path without creating it."""

    if Path(filename).name != filename:
        raise BuildSafetyError(f"build filename must not contain directories: {filename!r}")
    return paths.run_dir(pipeline, run_id) / filename


def assert_not_active_snapshot(path: Path, active: ActiveSnapshots) -> None:
    """Reject a destination inside any selected immutable snapshot."""

    target = path.resolve(strict=False)
    for root in (active.raw_path, active.a6_path, active.retrieval_path):
        resolved_root = root.resolve(strict=False)
        if target == resolved_root or resolved_root in target.parents:
            raise BuildSafetyError(
                f"refusing to write inside active snapshot {resolved_root}: {target}"
            )


def publish_new_file(src: Path, dst: Path) -> None:
    """Copy to a new destination and fail closed if that destination exists."""

    if not src.is_file():
        raise BuildSafetyError(f"build output does not exist: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with src.open("rb") as source, dst.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable build output already exists: {dst}") from error
    except Exception:
        dst.unlink(missing_ok=True)
        raise
