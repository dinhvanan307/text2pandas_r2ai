from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig, _build_reranker
from text2pandas.pipelines.retrieval.evalkit.stages import RankedItem, StageOutput
from text2pandas.pipelines.retrieval.filter_s1 import Candidate
from text2pandas.pipelines.retrieval.question_intent import Intent
from text2pandas.pipelines.retrieval.rank_s2 import Scored
from text2pandas.pipelines.retrieval.rerank_s3 import (
    FEATURES,
    LinearFeatureReranker,
    LinearRerankerModel,
)


def _intent(mode: str = "screen") -> Intent:
    return Intent(
        tickers=frozenset({"AAA"}), years=(2024,), mode=mode,
        explicit_scope="hợp nhất", resolved_by="fixture",
    )


def _item(uid: str, rank_score: float, statement: str) -> RankedItem:
    cand = Candidate(uid, "doc", "AAA", 2024, "consolidated", statement,
                     10, 10, "2024-12-31", "money", None)
    scored = Scored(cand, rank_score, True, True, False, rank_score,
                    ("bm25", "period", "unit"), True)
    return RankedItem(uid, rank_score, scored.reasons, cand, scored)


def test_linear_reranker_reorders_and_preserves_candidates() -> None:
    upstream = StageOutput(
        "s2", frozenset({"note", "primary"}),
        (_item("note", 1.0, "note"), _item("primary", 0.8, "balance_sheet")),
        50,
    )
    weights = dict.fromkeys(FEATURES, 0.0)
    weights["screen_primary"] = 2.0
    model = LinearRerankerModel("fixture", tuple(weights[n] for n in FEATURES), "a" * 64)
    out = LinearFeatureReranker(model, top_k=2).rerank(None, "q", _intent(), upstream)
    assert [x.table_uid for x in out.ranked] == ["primary", "note"]
    assert out.uids == upstream.uids
    assert out.trace["passthrough"] is False


def test_model_feature_contract_fails_closed(tmp_path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps({
        "schema": "linear-reranker-v1", "model_id": "bad",
        "features": list(reversed(FEATURES)),
        "weights": dict.fromkeys(FEATURES, 0.0),
        "training_manifest_sha256": "a" * 64,
    }))
    with pytest.raises(ValueError, match="feature contract"):
        LinearRerankerModel.load(path)


def test_runner_binds_model_bytes_to_config_sha(tmp_path) -> None:
    path = tmp_path / "model.json"
    path.write_text(json.dumps({
        "schema": "linear-reranker-v1", "model_id": "ok",
        "features": list(FEATURES), "weights": dict.fromkeys(FEATURES, 0.0),
        "training_manifest_sha256": "a" * 64,
    }))
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    cfg = EvalConfig(reranker="linear", reranker_model_path=path.name,
                     reranker_model_sha256=actual)
    assert isinstance(_build_reranker(tmp_path, cfg), LinearFeatureReranker)
    with pytest.raises(ValueError, match="checksum mismatch"):
        _build_reranker(tmp_path, replace(cfg, reranker_model_sha256="0" * 64))


def test_heldout_manifest_and_packet_are_reproducible() -> None:
    from tools.evaluation.freeze_reranker_heldout import build

    manifest, packet = build()
    assert manifest["status"] == "SEALED_UNLABELED"
    assert manifest["n_heldout"] == 120
    assert len(set(manifest["heldout_qids"])) == 120
    assert hashlib.sha256(packet.encode()).hexdigest() == manifest["packet_sha256"]
