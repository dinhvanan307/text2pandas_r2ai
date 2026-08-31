from __future__ import annotations

import json
from pathlib import Path

import yaml

from text2pandas.pipelines.retrieval.alias_store import (
    BRAND_A6,
    QUESTION_ATTESTED_V1,
    alias_artifact_sha256,
    load_aliases,
)
from text2pandas.pipelines.retrieval.question_intent import parse_intent

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"


def _questions() -> dict[int, str]:
    return {
        int(record["id"]): str(record["question"])
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for record in (json.loads(line),)
    }


def test_attested_brand_artifact_has_no_yaml_document_marker_suffix() -> None:
    raw = yaml.safe_load(BRAND_A6.read_text(encoding="utf-8"))["brands"]
    assert raw
    assert not [alias for aliases in raw.values() for alias in aliases if alias.endswith("...")]


def test_question_attested_aliases_have_qid_provenance() -> None:
    payload = yaml.safe_load(QUESTION_ATTESTED_V1.read_text(encoding="utf-8"))
    questions = _questions()
    for ticker, records in payload["aliases"].items():
        for record in records:
            assert record["qids"], (ticker, record)
            assert all(record["alias"].casefold() in questions[qid].casefold() for qid in record["qids"])


def test_known_retrieval_recovery_entities_resolve_completely() -> None:
    questions = _questions()
    aliases = load_aliases("a6")
    expected = {
        508: {"ACB", "OCB", "STB"},
        586: {"ACV"},
        782: {"VNM", "HNG"},
        783: {"EIB", "MBB"},
        792: {"EIB", "MBB"},
    }
    for qid, tickers in expected.items():
        assert set(parse_intent(questions[qid], aliases).targets) == tickers


def test_alias_fingerprint_is_branch_specific() -> None:
    fingerprints = {
        alias_artifact_sha256("full"),
        alias_artifact_sha256("a6"),
        alias_artifact_sha256("off"),
    }
    assert len(fingerprints) == 3
    assert all(len(value) == 64 for value in fingerprints)
