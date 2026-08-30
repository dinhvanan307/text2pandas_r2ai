from pathlib import Path

import pytest

from tools import package_submission_handoff


def _materialize_run(root: Path, run_kind: str, run_id: str) -> None:
    stage = root / "artifacts/runs" / run_kind / run_id
    stage.mkdir(parents=True)
    (stage / "manifest.json").write_text("{}\n", encoding="utf-8")
    stage.with_suffix(".zip").write_bytes(b"zip")


def test_resolve_candidate_stage_supports_grounded_v5(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "grounded-v5-release-r1"
    _materialize_run(tmp_path, "grounded-v5", run_id)
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    stage, source_zip = package_submission_handoff._resolve_candidate_stage(run_id)

    assert stage == tmp_path / "artifacts/runs/grounded-v5" / run_id
    assert source_zip == stage.with_suffix(".zip")


def test_resolve_candidate_stage_supports_recovery_wave2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "recovery-wave2-release-r1"
    _materialize_run(tmp_path, "recovery-wave2", run_id)
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    stage, source_zip = package_submission_handoff._resolve_candidate_stage(run_id)

    assert stage == tmp_path / "artifacts/runs/recovery-wave2" / run_id
    assert source_zip == stage.with_suffix(".zip")


def test_resolve_candidate_stage_supports_recovery_wave3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "recovery-wave3-release-r1"
    _materialize_run(tmp_path, "recovery-wave3", run_id)
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    stage, source_zip = package_submission_handoff._resolve_candidate_stage(run_id)

    assert stage == tmp_path / "artifacts/runs/recovery-wave3" / run_id
    assert source_zip == stage.with_suffix(".zip")


def test_resolve_candidate_stage_supports_recovery_wave4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "recovery-wave4-release-r1"
    _materialize_run(tmp_path, "recovery-wave4", run_id)
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    stage, source_zip = package_submission_handoff._resolve_candidate_stage(run_id)

    assert stage == tmp_path / "artifacts/runs/recovery-wave4" / run_id
    assert source_zip == stage.with_suffix(".zip")


def test_resolve_candidate_stage_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="path-safe"):
        package_submission_handoff._resolve_candidate_stage("../release")


def test_resolve_candidate_stage_fails_on_ambiguous_run_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "duplicate-r1"
    _materialize_run(tmp_path, "answer", run_id)
    _materialize_run(tmp_path, "grounded-v5", run_id)
    monkeypatch.setattr(package_submission_handoff, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="ambiguous"):
        package_submission_handoff._resolve_candidate_stage(run_id)
