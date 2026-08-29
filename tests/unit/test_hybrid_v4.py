from __future__ import annotations

import json
from pathlib import Path

from text2pandas.application.usecases.hybrid_v3 import (
    HybridDecisionKind,
    build_hybrid_candidate,
    decide_hybrid_record,
)
from text2pandas.infrastructure.semantic import load_hybrid_policy

ROOT = Path(__file__).resolve().parents[2]


def _legacy() -> dict[str, object]:
    return {
        "qid": 1,
        "question": "Tổng tài sản VCB năm 2024?",
        "status": "ABSTAIN",
        "answer": None,
        "relevant_docs": [],
        "relevant_tables": [],
        "evidence": [],
        "pandas_query": "",
        "confidence": 0.0,
    }


def _semantic(*, confidence: float, consensus: int) -> dict[str, object]:
    return {
        "qid": 1,
        "question": "Tổng tài sản VCB năm 2024?",
        "status": "OK",
        "answer": "1000",
        "ast": {"expression": {"type": "metric_ref"}},
        "binding_margin": None,
        "confidence": confidence,
        "consensus_size": consensus,
        "pandas_query": "float(df1['value'].values[0])",
        "relevant_tables": ["exact-table", "candidate-table"],
        "evidence": [
            {
                "variable": "df1",
                "table_uid": "exact-table",
                "observation_uids": ["obs-1"],
            }
        ],
    }


def _policy():
    return load_hybrid_policy(
        ROOT / "configs/semantic/hybrid_candidate_v4_experimental.yaml"
    )


def test_v4_policy_requires_confidence_and_consensus() -> None:
    low_confidence = decide_hybrid_record(
        _legacy(),
        _semantic(confidence=0.5, consensus=1),
        _policy(),
    )
    low_consensus = decide_hybrid_record(
        _legacy(),
        _semantic(confidence=0.8, consensus=0),
        _policy(),
    )
    promoted = decide_hybrid_record(
        _legacy(),
        _semantic(confidence=0.8, consensus=1),
        _policy(),
    )

    assert low_confidence.kind is HybridDecisionKind.KEEP_LEGACY_CONFIDENCE_LOW
    assert low_consensus.kind is HybridDecisionKind.KEEP_LEGACY_CONSENSUS_LOW
    assert promoted.kind is HybridDecisionKind.PROMOTE_V3


def test_v4_hybrid_uses_semantic_output_tables_and_v4_attribution(tmp_path: Path) -> None:
    legacy_stage = tmp_path / "legacy"
    semantic_stage = tmp_path / "semantic"
    (legacy_stage / "data").mkdir(parents=True)
    (semantic_stage / "data").mkdir(parents=True)
    (legacy_stage / "records.jsonl").write_text(
        json.dumps(_legacy()) + "\n",
        encoding="utf-8",
    )
    (semantic_stage / "records.jsonl").write_text(
        json.dumps(_semantic(confidence=0.8, consensus=1)) + "\n",
        encoding="utf-8",
    )
    (semantic_stage / "data/exact-table.csv").write_text(
        "observation_uid,value\nobs-1,1000\n",
        encoding="utf-8",
    )

    report = build_hybrid_candidate(
        legacy_records_path=legacy_stage / "records.jsonl",
        semantic_records_path=semantic_stage / "records.jsonl",
        legacy_data_dir=legacy_stage / "data",
        semantic_data_dir=semantic_stage / "data",
        output_dir=tmp_path / "hybrid",
        policy=_policy(),
        table_locators={
            "exact-table": "VCB-2024|10",
            "candidate-table": "VCB-2024|20",
        },
        semantic_label="semantic_v4",
        evidence_prefix="v4",
    )

    assert report.results[0].relevant_tables == ["VCB-2024|10", "VCB-2024|20"]
    assert report.results[0].evidence == [
        {"variable": "df1", "csv_path": "data/v4_exact-table.csv"}
    ]
    record = json.loads(report.records_path.read_text(encoding="utf-8"))
    assert record["answer_source"] == "semantic_v4"
    assert record["hybrid"]["semantic_label"] == "semantic_v4"
