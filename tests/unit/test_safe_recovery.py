from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from text2pandas.application.usecases.safe_recovery import (
    build_source_adjudicated_candidate,
)
from text2pandas.application.usecases.submission import (
    replay_zip,
    write_deterministic_submission_zip,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    baseline = root / "submission.zip"
    records = [
        {
            "id": 1,
            "question": "Protected answer",
            "answer": 5.0,
            "relevant_docs": [],
            "relevant_tables": [],
            "evidence": [{"variable": "df1", "csv_path": "data/base.csv"}],
            "pandas_query": "float(df1['value'].values[0])",
        },
        {
            "id": 2,
            "question": "Reviewed abstention",
            "answer": 0.0,
            "relevant_docs": [],
            "relevant_tables": [],
            "evidence": [],
            "pandas_query": "",
        },
    ]
    write_deterministic_submission_zip(
        baseline,
        json_name="submission.json",
        json_bytes=json.dumps(records, ensure_ascii=False, indent=1).encode(),
        csv_payloads={"data/base.csv": b"value\n5\n"},
    )
    source_records = root / "records.jsonl"
    source_records.write_text(
        json.dumps(
            {
                "qid": 2,
                "grounded_v5": {
                    "status": "PROMOTED_RECOVERY",
                    "answer": 7.0,
                    "pandas_query": (
                        "float(df1[df1['observation_uid'] == 'fact-2']"
                        "['value'].values[0])"
                    ),
                    "selected_facts": [
                        {
                            "uid": "fact-2",
                            "raw_value": "7",
                            "canonical_value": "7",
                            "table_uid": "table-2",
                            "document_id": "DOC_2022",
                            "entity": "DOC",
                            "period": "2022-12-31",
                            "dimension": "money",
                            "scale_exponent": 0,
                            "row": "Metric",
                            "column": "2022",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = root / "review.json"
    ledger.write_text(
        json.dumps(
            {
                "baseline": {
                    "zip_path": baseline.name,
                    "zip_sha256": _sha256(baseline),
                },
                "source_run": {
                    "records_path": source_records.name,
                    "records_sha256": _sha256(source_records),
                },
                "reviews": [
                    {
                        "qid": 2,
                        "cohort": "trusted",
                        "source_status": "PROMOTED_RECOVERY",
                        "decision": "PASS_SOURCE_PROVEN",
                        "expected_answer": 7.0,
                        "checks": {
                            "metric": True,
                            "entity": True,
                            "period": True,
                            "basis": True,
                            "operation": True,
                            "unit": True,
                            "source": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return baseline, source_records, ledger


def test_safe_recovery_is_deterministic_and_preserves_baseline_layers(tmp_path: Path) -> None:
    baseline, source_records, ledger = _fixture(tmp_path)
    first = build_source_adjudicated_candidate(
        baseline_zip=baseline,
        source_records=source_records,
        review_ledger=ledger,
        output_zip=tmp_path / "first.zip",
        cohort="trusted",
    )
    second = build_source_adjudicated_candidate(
        baseline_zip=baseline,
        source_records=source_records,
        review_ledger=ledger,
        output_zip=tmp_path / "second.zip",
        cohort="trusted",
    )

    assert first.accepted_qids == (2,)
    assert first.protected_answer_query_evidence == 1
    assert first.protected_retrieval == 2
    assert first.protected_csv_payloads == 1
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    with zipfile.ZipFile(first.zip_path) as archive:
        candidate = {
            row["id"]: row
            for row in json.loads(archive.read("submission.json").decode("utf-8"))
        }
        assert archive.read("data/base.csv") == b"value\n5\n"
        assert candidate[1]["answer"] == 5.0
        assert candidate[1]["evidence"] == [
            {"variable": "df1", "csv_path": "data/base.csv"}
        ]
        assert candidate[2]["answer"] == 7.0
        assert candidate[2]["relevant_docs"] == []
        assert candidate[2]["relevant_tables"] == []
    assert replay_zip(first.zip_path, tmp_path / "replay", profile="competition") == {
        "total": 2,
        "executed": 2,
        "matched": 2,
        "no_evidence": 0,
        "error": 0,
    }
