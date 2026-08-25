from __future__ import annotations

import json
from pathlib import Path

import pytest

from text2pandas.application.usecases.materialized_gates import (
    MaterializationError,
    determinism_report,
    resolved_unit_adjudications,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(item) + "\n" for item in records), encoding="utf-8")


def test_resolved_adjudication_is_derived_from_explicit_provenance(tmp_path: Path) -> None:
    records = tmp_path / "records.jsonl"
    questions = tmp_path / "questions.jsonl"
    _write_jsonl(questions, [{"id": 42, "question": "q42"}])
    _write_jsonl(
        records,
        [
            {
                "qid": 42,
                "provenance": {
                    "unit_adjudication": "A6_DEFECT_FIXED",
                    "unit_adjudication_reason": (
                        "raw 'triệu đồng' o col_path_text = 10^6 khop don vi muc bang, "
                        "KHAC A6 10^0"
                    ),
                    "observation_uid": "obs",
                    "source_cell_uid": "cell",
                    "scale_exponent": 6,
                    "scale_bang_khai": 6,
                    "col_path": "Năm nay Triệu đồng",
                },
            }
        ],
    )

    result = resolved_unit_adjudications(records, questions)

    assert result[0]["a6_scale_exponent"] == 0
    assert result[0]["final_scale_exponent"] == 6
    assert result[0]["evidence_found"][0]["field"] == "col_path_text"


def test_incomplete_resolved_provenance_fails_closed(tmp_path: Path) -> None:
    records = tmp_path / "records.jsonl"
    questions = tmp_path / "questions.jsonl"
    _write_jsonl(questions, [{"id": 1, "question": "q"}])
    _write_jsonl(
        records,
        [{"qid": 1, "provenance": {"unit_adjudication": "A6_DEFECT_FIXED"}}],
    )

    with pytest.raises(MaterializationError, match="incomplete"):
        resolved_unit_adjudications(records, questions)


def test_determinism_report_hashes_independent_outputs(tmp_path: Path) -> None:
    first = tmp_path / "one.zip"
    second = tmp_path / "two.zip"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")

    report = determinism_report(first, second)

    assert report["deterministic_full_zip_sha256"] is True
    assert report["run_1"]["path"] != report["run_2"]["path"]
