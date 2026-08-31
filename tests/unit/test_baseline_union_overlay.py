from __future__ import annotations

from pathlib import Path

import pandas as pd

from tools.submission.build_baseline_union_overlay import (
    _merge_overlay,
    _merge_union,
    _preservation_metrics,
)


def _record(qid: int, *, tables: list[str], emitted: bool) -> dict[str, object]:
    return {
        "id": qid,
        "question": f"Question {qid}",
        "answer": 7.0 if emitted else 0.0,
        "relevant_docs": list(dict.fromkeys(item.rsplit("|", 1)[0] for item in tables)),
        "relevant_tables": tables,
        "evidence": [{"variable": "df1", "csv_path": "data/value.csv"}]
        if emitted
        else [],
        "pandas_query": (
            "float(df1[(df1['row_path'] == 'Metric') & "
            "(df1['col_label'] == 'FY2025')]['value'].values[0])"
            if emitted
            else ""
        ),
    }


def test_union_fills_only_replayed_baseline_abstention(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    pd.DataFrame(
        {"row_path": ["Metric"], "col_label": ["FY2025"], "value": [7.0]}
    ).to_csv(data / "value.csv", index=False)
    baseline = {
        1: _record(1, tables=["DOC_A|1"], emitted=True),
        2: _record(2, tables=["DOC_B|2"], emitted=False),
    }
    current = {
        1: {**_record(1, tables=["DOC_NEW|3"], emitted=True), "qid": 1, "status": "OK"},
        2: {**_record(2, tables=["DOC_C|4"], emitted=True), "qid": 2, "status": "OK"},
    }

    union, added, rejected = _merge_union(baseline, current, tmp_path, tolerance=1e-6)

    assert added == [2]
    assert rejected == {}
    assert union[0] == baseline[1]
    assert union[1]["answer"] == 7.0
    assert union[1]["relevant_tables"] == ["DOC_B|2", "DOC_C|4"]


def test_overlay_preserves_over_cap_and_appends_under_cap() -> None:
    over_cap = [f"DOC_{index}|{index + 1}" for index in range(11)]
    union = [
        _record(1, tables=over_cap, emitted=True),
        _record(2, tables=["DOC_A|1", "DOC_B|2"], emitted=False),
    ]
    retrieval = {
        1: _record(1, tables=["DOC_NEW|99"], emitted=False),
        2: _record(2, tables=["DOC_B|2", "DOC_C|3", "DOC_D|4"], emitted=False),
    }

    final, metrics = _merge_overlay(union, retrieval, table_cap=3)

    assert final[0]["relevant_tables"] == over_cap
    assert final[1]["relevant_tables"] == ["DOC_A|1", "DOC_B|2", "DOC_C|3"]
    assert metrics["over_cap_baseline_qids"] == [1]


def test_preservation_gate_checks_baseline_answer_query_and_evidence() -> None:
    baseline = {1: _record(1, tables=["DOC_A|1"], emitted=True)}
    union = [_record(1, tables=["DOC_A|1"], emitted=True)]
    final = [_record(1, tables=["DOC_A|1", "DOC_B|2"], emitted=True)]

    metrics = _preservation_metrics(baseline, union, final)

    assert metrics == {
        "baseline_emitted": 1,
        "answer_unchanged": 1,
        "query_unchanged": 1,
        "evidence_unchanged": 1,
        "baseline_table_prefix_preserved": 1,
        "total_qids": 1,
    }
