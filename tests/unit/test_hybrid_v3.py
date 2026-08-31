from __future__ import annotations

import json
from pathlib import Path

import pytest

from text2pandas.application.usecases.hybrid_v3 import (
    HybridDecisionKind,
    HybridPolicy,
    HybridRoutePolicy,
    build_hybrid_candidate,
    decide_hybrid_record,
    hybrid_publication_eligibility,
    validate_source_manifest,
)


def _policy(*, replace: bool = False, refs: str = "semantic_evidence") -> HybridPolicy:
    route = HybridRoutePolicy(
        recover_legacy_abstention=True,
        replace_legacy_value=replace,
        minimum_binding_margin=1.0,
    )
    return HybridPolicy(
        policy_id="fixture",
        status="EXPERIMENTAL",
        production_eligible=False,
        relevant_refs_mode=refs,
        maximum_relevant_tables=10,
        default_route=HybridRoutePolicy(),
        routes={"metric_ref": route},
    )


def _legacy(*, answer: float | None) -> dict[str, object]:
    return {
        "qid": 1,
        "question": "Doanh thu VNM năm 2024?",
        "status": "OK" if answer is not None else "ABSTAIN",
        "answer": answer,
        "relevant_docs": ["VNM_financial_statements_2024_consolidated"],
        "relevant_tables": ["VNM_financial_statements_2024_consolidated|2"],
        "evidence": (
            [{"variable": "df1", "csv_path": "data/legacy-table.csv"}]
            if answer is not None
            else []
        ),
        "pandas_query": "float(df1['value'].values[0])" if answer is not None else "",
        "confidence": 0.5,
        "reason": None if answer is not None else "UNSUPPORTED",
    }


def _semantic(*, answer: object = "20", margin: float | None = 2.0) -> dict[str, object]:
    return {
        "qid": 1,
        "question": "Doanh thu VNM năm 2024?",
        "status": "OK",
        "answer": answer,
        "ast": {"expression": {"type": "metric_ref"}},
        "binding_margin": margin,
        "pandas_query": (
            "float(df1[df1['observation_uid'] == 'obs-1']['value'].values[0])"
        ),
        "evidence": [
            {
                "variable": "df1",
                "table_uid": "semantic-table",
                "observation_uids": ["obs-1"],
            }
        ],
        "reason": None,
        "stage_failed": None,
    }


def test_safe_policy_recovers_abstention_but_blocks_value_change() -> None:
    recovered = decide_hybrid_record(_legacy(answer=None), _semantic(), _policy())
    changed = decide_hybrid_record(_legacy(answer=10), _semantic(), _policy())

    assert recovered.kind is HybridDecisionKind.PROMOTE_V3
    assert changed.kind is HybridDecisionKind.KEEP_LEGACY_VALUE_CHANGE_BLOCKED


def test_lookup_experiment_allows_high_margin_value_change() -> None:
    promoted = decide_hybrid_record(_legacy(answer=10), _semantic(), _policy(replace=True))
    blocked = decide_hybrid_record(
        _legacy(answer=10), _semantic(margin=0.5), _policy(replace=True)
    )
    missing_margin = decide_hybrid_record(
        _legacy(answer=10), _semantic(margin=None), _policy(replace=True)
    )

    assert promoted.kind is HybridDecisionKind.PROMOTE_V3
    assert promoted.value_changed
    assert blocked.kind is HybridDecisionKind.KEEP_LEGACY_MARGIN_LOW
    assert missing_margin.kind is HybridDecisionKind.KEEP_LEGACY_MARGIN_LOW


def test_publication_requires_policy_and_locked_semantic_gate() -> None:
    experimental = _policy()
    production = HybridPolicy(
        policy_id="production-fixture",
        status="APPROVED",
        production_eligible=True,
        relevant_refs_mode="semantic_evidence",
        maximum_relevant_tables=10,
        default_route=HybridRoutePolicy(),
        routes=experimental.routes,
    )

    assert hybrid_publication_eligibility(experimental, "PROMOTABLE") == (
        False,
        ("POLICY_NOT_PRODUCTION_ELIGIBLE",),
    )
    assert hybrid_publication_eligibility(production, "BLOCKED") == (
        False,
        ("SEMANTIC_SOURCE_NOT_PROMOTABLE:BLOCKED",),
    )
    assert hybrid_publication_eligibility(production, "PROMOTABLE") == (True, ())


def test_source_manifest_is_bound_to_run_id_and_records_digest() -> None:
    manifest = {
        "run_id": "semantic-1",
        "outputs": {"records_jsonl": {"sha256": "abc123"}},
    }

    validate_source_manifest(
        manifest,
        expected_run_id="semantic-1",
        records_sha256="abc123",
        source_label="semantic",
    )

    with pytest.raises(ValueError, match="records sha256 does not match"):
        validate_source_manifest(
            manifest,
            expected_run_id="semantic-1",
            records_sha256="changed",
            source_label="semantic",
        )


def test_builder_renames_v3_evidence_and_separates_scorer_refs(tmp_path: Path) -> None:
    legacy_stage = tmp_path / "legacy"
    semantic_stage = tmp_path / "semantic"
    (legacy_stage / "data").mkdir(parents=True)
    (semantic_stage / "data").mkdir(parents=True)
    (legacy_stage / "records.jsonl").write_text(
        json.dumps(_legacy(answer=None)) + "\n", encoding="utf-8"
    )
    (semantic_stage / "records.jsonl").write_text(
        json.dumps(_semantic()) + "\n", encoding="utf-8"
    )
    (semantic_stage / "data" / "semantic-table.csv").write_text(
        "observation_uid,value\nobs-1,20\n", encoding="utf-8"
    )

    report = build_hybrid_candidate(
        legacy_records_path=legacy_stage / "records.jsonl",
        semantic_records_path=semantic_stage / "records.jsonl",
        legacy_data_dir=legacy_stage / "data",
        semantic_data_dir=semantic_stage / "data",
        output_dir=tmp_path / "hybrid",
        policy=_policy(refs="semantic_plus_legacy"),
        table_locators={
            "semantic-table": "VNM_financial_statements_2024_consolidated|3"
        },
    )

    assert report.n_promoted == 1
    assert report.n_recovered == 1
    result = report.results[0]
    assert result.answer == 20
    assert result.evidence == [
        {"variable": "df1", "csv_path": "data/v3_semantic-table.csv"}
    ]
    assert result.relevant_tables == [
        "VNM_financial_statements_2024_consolidated|3",
        "VNM_financial_statements_2024_consolidated|2",
    ]
    assert (tmp_path / "hybrid/data/v3_semantic-table.csv").is_file()
    attribution = json.loads(report.attribution_path.read_text(encoding="utf-8"))
    assert attribution["decision"] == "PROMOTE_V3"


def test_builder_accepts_historical_legacy_record_without_question(tmp_path: Path) -> None:
    legacy_stage = tmp_path / "legacy"
    semantic_stage = tmp_path / "semantic"
    (legacy_stage / "data").mkdir(parents=True)
    (semantic_stage / "data").mkdir(parents=True)
    legacy = _legacy(answer=None)
    legacy.pop("question")
    (legacy_stage / "records.jsonl").write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    (semantic_stage / "records.jsonl").write_text(
        json.dumps(_semantic()) + "\n", encoding="utf-8"
    )
    (semantic_stage / "data" / "semantic-table.csv").write_text(
        "observation_uid,value\nobs-1,20\n", encoding="utf-8"
    )

    report = build_hybrid_candidate(
        legacy_records_path=legacy_stage / "records.jsonl",
        semantic_records_path=semantic_stage / "records.jsonl",
        legacy_data_dir=legacy_stage / "data",
        semantic_data_dir=semantic_stage / "data",
        output_dir=tmp_path / "hybrid",
        policy=_policy(),
        table_locators={
            "semantic-table": "VNM_financial_statements_2024_consolidated|3"
        },
    )

    record = json.loads(report.records_path.read_text(encoding="utf-8"))
    assert record["question"] == "Doanh thu VNM năm 2024?"
