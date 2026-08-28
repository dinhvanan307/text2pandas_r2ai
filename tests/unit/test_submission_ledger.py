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
        else:
            assert entry["status"] == "INCOMPLETE_LEGACY_RECORD"
            assert entry["metrics"]["classification"].endswith("_UNATTRIBUTED")


def test_local_candidate_cannot_masquerade_as_official_submission() -> None:
    payload = json.loads(LEDGER.read_text(encoding="utf-8"))
    candidates = payload["local_candidates"]

    assert candidates
    for candidate in candidates:
        assert candidate["status"] == "NOT_SUBMITTED"
        assert "submission_id" not in candidate
        assert len(candidate["zip_sha256"]) == 64
