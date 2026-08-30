from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "configs/evaluation/submission_ledger_v1.json"


def test_submission_ledger_enforces_complete_identity_mapping() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    required = tuple(payload["policy"]["complete_entry_requires"])
    entries = payload["submissions"]

    assert payload["policy"]["append_before_reading_score"] is True
    assert len({entry["submission_id"] for entry in entries}) == len(entries)
    for entry in entries:
        assert all(field in entry for field in required)
        if entry["status"] == "COMPLETE":
            assert all(entry[field] not in (None, "") for field in required)
        elif entry["status"] == "INCOMPLETE_LEGACY_RECORD":
            assert entry["status"] == "INCOMPLETE_LEGACY_RECORD"
            assert entry["metrics"]["classification"].endswith("_UNATTRIBUTED")
        else:
            assert entry["status"] == "INCOMPLETE_SOURCE_ATTRIBUTION"
            assert entry["zip_path"]
            assert len(entry["zip_sha256"]) == 64
            assert entry["git_commit"] is None
            assert entry["config_sha256"] is None
            assert entry["receipt_path"] is None
            assert entry["metrics"]["classification"].endswith("_PARTIALLY_ATTRIBUTED")


def test_submission_3821_has_a_user_confirmed_artifact_identity() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    entry = next(row for row in payload["submissions"] if row["submission_id"] == 3821)
    provenance_path = ROOT / "provenance/submissions/submission_3821.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    assert entry["zip_sha256"] == provenance["artifact"]["sha256"]
    assert provenance["attribution"]["artifact_confirmation"] == (
        "USER_CONFIRMED_EXACT_ARTIFACT"
    )
    assert provenance["coverage"] == {
        "executable": 712,
        "records": 1012,
        "unresolved": 300,
    }
    assert provenance["replay"] == {
        "emitted_errors": 0,
        "executed": 712,
        "matched": 712,
        "unresolved": 300,
    }


def test_local_candidate_cannot_masquerade_as_official_submission() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    candidates = payload["local_candidates"]

    assert candidates
    for candidate in candidates:
        assert candidate["status"] == "NOT_SUBMITTED"
        assert "submission_id" not in candidate
        assert len(candidate["zip_sha256"]) == 64
