from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tools.evaluate_adjudicated_answers import evaluate


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_evaluator_separates_accuracy_coverage_and_replay(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    records = tmp_path / "records.jsonl"
    data_root = tmp_path / "run"
    (data_root / "data").mkdir(parents=True)
    pd.DataFrame([{"value": 10.0}]).to_csv(data_root / "data" / "t.csv", index=False)
    _jsonl(
        gold,
        [
            {"qid": 1, "trang_thai": "OK", "normalized_answer_gold": 10, "operation": "lookup"},
            {"qid": 2, "trang_thai": "OK", "normalized_answer_gold": 20, "operation": "ratio"},
            {"qid": 3, "trang_thai": "GOLD_UNCERTAIN", "normalized_answer_gold": 0},
        ],
    )
    _jsonl(
        records,
        [
            {
                "qid": 1,
                "status": "OK",
                "answer": 10.0,
                "evidence": [{"variable": "df1", "csv_path": "data/t.csv"}],
                "pandas_query": "float(df1[df1['value'] == 10.0]['value'].values[0])",
            },
            {
                "qid": 2,
                "status": "ABSTAIN",
                "answer": None,
                "evidence": [],
                "pandas_query": "",
                "reason": "UNBOUND",
            },
        ],
    )

    report = evaluate(records, gold, data_root, tolerance=0.005)

    assert report["population"]["gold_total"] == 3
    assert report["population"]["gold_evaluable"] == 2
    assert report["metrics"] == {
        "answer_accuracy": 0.5,
        "answer_correct": 1,
        "execution_accuracy": 0.5,
        "execution_correct": 1,
        "executable_coverage": 0.5,
        "executable": 1,
        "replay_consistency": 1.0,
        "replayed": 1,
    }
