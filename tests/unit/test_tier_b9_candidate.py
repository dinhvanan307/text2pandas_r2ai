from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from text2pandas.infrastructure.sandbox.query import execute_query, validate_query
from tools.submission.build_adjudicated_factorized_candidate import _load_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "configs/evaluation/adjudicated_answer_patch_tier_b9_v1.json"
SAFE5_MANIFEST = (
    ROOT / "configs/evaluation/adjudicated_answer_patch_tier_b_safe5_v1.json"
)
A6_DB = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"
SAFE_3816 = (
    ROOT
    / "artifacts/submissions/submission_adjudicated-a17-3811-answer-3770.zip"
)
TIER_B9 = {452, 460, 546, 601, 647, 808, 883, 956, 967}


def test_tier_b9_manifest_is_fill_only_and_fail_closed() -> None:
    manifest = _load_manifest(MANIFEST)

    assert manifest["patch_id"] == "adjudicated-answer-patch-tier-b9-v1"
    assert {item["qid"] for item in manifest["patches"]} == TIER_B9
    assert all(item["decision"] == "FILL" for item in manifest["patches"])
    assert all(item["source"]["kind"] == "A6_MANUAL" for item in manifest["patches"])
    assert manifest["policy"] == {
        "expected_records": 1012,
        "expected_baseline_emitted": 638,
        "expected_output_emitted": 647,
        "expected_corrections": 0,
        "expected_fills": 9,
        "table_cap": 10,
        "p0_enabled": False,
        "model_gold_used": False,
        "semantic_v3_promoted": False,
        "fail_closed": True,
    }


def test_safe5_manifest_is_exact_direct_safe_subset() -> None:
    manifest = _load_manifest(SAFE5_MANIFEST)

    assert manifest["patch_id"] == "adjudicated-answer-patch-tier-b-safe5-v1"
    assert [item["qid"] for item in manifest["patches"]] == [452, 546, 601, 883, 956]
    assert manifest["policy"]["expected_baseline_emitted"] == 638
    assert manifest["policy"]["expected_output_emitted"] == 643
    assert manifest["policy"]["expected_corrections"] == 0
    assert manifest["policy"]["expected_fills"] == 5


@pytest.mark.skipif(not A6_DB.is_file(), reason="active A6 database is not materialized")
def test_tier_b9_queries_replay_from_exact_a6_observations() -> None:
    manifest = _load_manifest(MANIFEST)
    connection = sqlite3.connect(f"file:{A6_DB.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for patch in manifest["patches"]:
            frames: dict[str, pd.DataFrame] = {}
            for evidence in patch["source"]["evidence"]:
                observation_uids = evidence["observation_uids"]
                placeholders = ",".join("?" for _ in observation_uids)
                rows = connection.execute(
                    f"SELECT observation_uid, table_uid, value_decimal_text "
                    f"FROM observations WHERE observation_uid IN ({placeholders})",
                    observation_uids,
                ).fetchall()
                by_uid = {str(row["observation_uid"]): row for row in rows}
                assert set(by_uid) == set(observation_uids), patch["qid"]
                assert all(
                    str(by_uid[uid]["table_uid"]) == evidence["table_uid"]
                    for uid in observation_uids
                ), patch["qid"]
                frames[evidence["variable"]] = pd.DataFrame(
                    {
                        "observation_uid": observation_uids,
                        "value": [float(by_uid[uid]["value_decimal_text"]) for uid in observation_uids],
                    }
                )

            query = patch["source"]["pandas_query"]
            assert len(query) <= 10_000
            validate_query(query, set(frames))
            assert execute_query(query, frames) == pytest.approx(
                patch["expected_answer"], rel=1e-12, abs=1e-9
            )
    finally:
        connection.close()


@pytest.mark.skipif(not SAFE_3816.is_file(), reason="SAFE 3816 ZIP is not materialized")
def test_tier_b9_targets_only_safe_3816_abstentions() -> None:
    expected_sha = "f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628"
    assert hashlib.sha256(SAFE_3816.read_bytes()).hexdigest() == expected_sha

    with zipfile.ZipFile(SAFE_3816) as archive:
        records = json.loads(archive.read("submission.json"))
    selected = {int(record["id"]): record for record in records if int(record["id"]) in TIER_B9}

    assert set(selected) == TIER_B9
    assert all(not record["evidence"] for record in selected.values())
    assert all(not record["pandas_query"] for record in selected.values())


def test_tier_b9_sign_and_direction_contracts_are_explicit() -> None:
    manifest = _load_manifest(MANIFEST)
    patches = {item["qid"]: item for item in manifest["patches"]}

    assert "abs(" in patches[460]["source"]["pandas_query"]
    assert "abs(" in patches[647]["source"]["pandas_query"]
    assert "abs(" in patches[967]["source"]["pandas_query"]
    assert "abs(" not in patches[808]["source"]["pandas_query"]
    assert " and " in patches[452]["source"]["pandas_query"]
    assert " and " in patches[546]["source"]["pandas_query"]
