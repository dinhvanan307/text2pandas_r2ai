"""Machine-readable lineage for canonical answering and submission runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from text2pandas.application.usecases.canonical_run import CanonicalPipelineReport
from text2pandas.application.usecases.submission import ValidationReport
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots, VerificationReport


def pipeline_manifest(
    paths: ProjectPaths,
    active: ActiveSnapshots,
    run_id: str,
    parameters: Mapping[str, object],
    report: CanonicalPipelineReport,
    preflight: VerificationReport,
    source_identity: Mapping[str, object],
    records_path: Path,
) -> dict[str, object]:
    """Describe the immutable inputs, code, parameters, and pipeline output."""

    return {
        "schema_version": "1.0",
        "kind": "text2pandas.answering_run",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETED_WITH_ABSTENTIONS" if report.n_abstained else "COMPLETED",
        "source": dict(source_identity),
        "snapshots": {
            "raw": {
                "dataset_id": active.raw_dataset_id,
                "snapshot_id": active.raw_snapshot_id,
                "path": _relative(active.raw_path, paths.repo_root),
            },
            "a6": {
                "build_id": active.a6_build_id,
                "path": _relative(active.a6_path, paths.repo_root),
            },
            "retrieval": {
                "index_id": active.retrieval_index_id,
                "source_a6_build_id": active.retrieval_source_a6_build_id,
                "path": _relative(active.retrieval_path, paths.repo_root),
            },
        },
        "preflight": [
            {
                "name": item.name,
                "status": "PASS" if item.ok else "FAIL",
                "detail": _portable_detail(item.detail, paths),
            }
            for item in preflight.items
        ],
        "parameters": dict(parameters),
        "metrics": {
            "questions": report.n_questions,
            "with_entity": report.n_with_entity,
            "with_year": report.n_with_year,
            "retrieved": report.n_retrieved,
            "answered": report.n_answered,
            "abstained": report.n_abstained,
            "seconds": report.seconds,
            "abstain_reasons": report.abstain_reasons,
        },
        "outputs": {
            "records_jsonl": {
                "path": _relative(records_path, paths.repo_root),
                "sha256": sha256_file(records_path),
                "records": report.n_questions,
            }
        },
    }


def submission_manifest(
    paths: ProjectPaths,
    run_id: str,
    pipeline_manifest_path: Path,
    zip_path: Path,
    published_path: Path | None,
    validation: ValidationReport,
    replay: Mapping[str, int],
) -> dict[str, object]:
    valid = (
        validation.ok
        and replay.get("error", 0) == 0
        and replay.get("matched", 0) == replay.get("executed", 0)
    )
    return {
        "schema_version": "1.0",
        "kind": "text2pandas.submission_run",
        "run_id": run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "VALIDATED" if valid else "FAILED_VALIDATION",
        "pipeline_manifest": {
            "path": _relative(pipeline_manifest_path, paths.repo_root),
            "sha256": sha256_file(pipeline_manifest_path),
        },
        "package": {
            "stage_path": _relative(zip_path, paths.repo_root),
            "published_path": (
                _relative(published_path, paths.repo_root) if published_path else None
            ),
            "sha256": sha256_file(zip_path),
            "bytes": zip_path.stat().st_size,
        },
        "validation": {
            "ok": validation.ok,
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": dict(replay),
    }


def write_manifest(path: Path, manifest: Mapping[str, object]) -> None:
    """Publish once so a run's claims cannot be silently rewritten."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(repo_root.resolve(strict=False)).as_posix()
    except ValueError:
        return str(path.resolve(strict=False))


def _portable_detail(detail: str, paths: ProjectPaths) -> str:
    replacements = (
        (paths.data_root.resolve(strict=False), "${DATA_ROOT}"),
        (paths.artifact_root.resolve(strict=False), "${ARTIFACT_ROOT}"),
        (paths.repo_root.resolve(strict=False), "${REPO_ROOT}"),
    )
    portable = detail
    for root, label in replacements:
        portable = portable.replace(str(root), label)
    return portable
