from __future__ import annotations

import pandas as pd

from text2pandas.application.usecases.semantic_v3_replay import (
    replay_semantic_v3_records,
)


def test_replay_audits_emitted_and_fail_closed_records(tmp_path) -> None:
    evidence = tmp_path / "evidence.csv"
    pd.DataFrame({"observation_uid": ["obs-1"], "value": [21.0]}).to_csv(
        evidence, index=False
    )
    records = [
        {
            "qid": 1,
            "status": "OK",
            "answer": "42",
            "pandas_query": "float(df1[df1['observation_uid'] == 'obs-1']['value'].values[0]) * 2",
            "evidence": [{"variable": "df1", "csv_path": "evidence.csv"}],
        },
        {
            "qid": 2,
            "status": "ABSTAIN",
            "answer": None,
            "pandas_query": None,
            "evidence": [],
        },
    ]

    report = replay_semantic_v3_records(records, tmp_path)

    assert report["records"] == 2
    assert report["emitted"] == report["matched"] == 1
    assert report["abstentions"] == 1
    assert report["replay_consistency"] == 1.0
    assert report["failures"] == []


def test_replay_reports_abstention_payload_leak(tmp_path) -> None:
    report = replay_semantic_v3_records(
        [
            {
                "qid": 1,
                "status": "ABSTAIN",
                "answer": "1",
                "pandas_query": None,
                "evidence": [],
            }
        ],
        tmp_path,
    )

    assert report["errors"] == 1
    assert report["failures"][0]["reason"] == "ABSTAIN_PAYLOAD_LEAK"
