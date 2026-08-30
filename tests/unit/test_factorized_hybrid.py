from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tools.submission.build_factorized_hybrid import (
    CompositionError,
    _answer_csv_payloads,
    _compose_records,
    _layer_diff,
    _read_bundle,
    _required_csvs,
    _write_zip,
)


CSV_PATH = "data/value.csv"
CSV_PAYLOAD = b"row_path,col_label,value\nMetric,FY2025,7.0\n"


def _record(
    qid: int,
    *,
    question: str | None = None,
    answer: float = 7.0,
    tables: list[str] | None = None,
    docs: list[str] | None = None,
    emitted: bool = True,
) -> dict[str, object]:
    selected_tables = tables if tables is not None else ["DOC_A|1"]
    selected_docs = (
        docs
        if docs is not None
        else list(dict.fromkeys(table.rsplit("|", 1)[0] for table in selected_tables))
    )
    return {
        "id": qid,
        "question": question or f"Question {qid}",
        "answer": answer,
        "relevant_docs": selected_docs,
        "relevant_tables": selected_tables,
        "evidence": [{"variable": "df1", "csv_path": CSV_PATH}] if emitted else [],
        "pandas_query": (
            "float(df1[(df1['row_path'] == 'Metric') & "
            "(df1['col_label'] == 'FY2025')]['value'].values[0])"
            if emitted
            else ""
        ),
    }


def _source_zip(
    path: Path,
    records: list[dict[str, object]],
    *,
    csvs: dict[str, bytes] | None = None,
) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "submission.json",
            json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8"),
        )
        for name, payload in sorted((csvs or {}).items()):
            archive.writestr(name, payload)
    return path


def _bundle(
    tmp_path: Path,
    name: str,
    records: list[dict[str, object]],
    *,
    include_csv: bool = True,
):
    csvs = {CSV_PATH: CSV_PAYLOAD} if include_csv else {}
    return _read_bundle(_source_zip(tmp_path / name, records, csvs=csvs))


def test_factorized_composition_uses_exact_field_owners_and_answer_order(
    tmp_path: Path,
) -> None:
    answer_records = [
        _record(2, answer=72.0, tables=["ANSWER_B|8"]),
        _record(1, answer=71.0, tables=["ANSWER_A|7"]),
    ]
    retrieval_records = [
        _record(1, answer=-1.0, tables=["RET_A|1", "RET_B|2"]),
        _record(2, answer=-2.0, tables=["RET_C|3", "RET_D|4"]),
    ]
    answer = _bundle(tmp_path, "answer.zip", answer_records)
    retrieval = _bundle(tmp_path, "retrieval.zip", retrieval_records)

    output, composition = _compose_records(
        answer, retrieval, expected_count=2, table_cap=10
    )
    diff = _layer_diff(output, answer, retrieval)

    assert [record["id"] for record in output] == [2, 1]
    assert output[0]["answer"] == 72.0
    assert output[0]["evidence"] == answer_records[0]["evidence"]
    assert output[0]["pandas_query"] == answer_records[0]["pandas_query"]
    assert output[0]["relevant_tables"] == ["RET_C|3", "RET_D|4"]
    assert output[0]["relevant_docs"] == ["RET_C", "RET_D"]
    assert composition == {
        "records": 2,
        "question_equal": 2,
        "retrieval_changed_qids": 2,
    }
    assert diff["answer_equal_answer"] == 2
    assert diff["evidence_equal_answer"] == 2
    assert diff["pandas_query_equal_answer"] == 2
    assert diff["relevant_tables_equal_retrieval"] == 2
    assert diff["relevant_docs_equal_retrieval"] == 2


def test_rejects_source_question_mismatch(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1, question="Original")])
    retrieval = _bundle(
        tmp_path, "retrieval.zip", [_record(1, question="Tampered")]
    )

    with pytest.raises(CompositionError, match="source questions differ"):
        _compose_records(answer, retrieval, expected_count=1, table_cap=10)


def test_rejects_input_sha_mismatch(tmp_path: Path) -> None:
    source = _source_zip(
        tmp_path / "source.zip", [_record(1)], csvs={CSV_PATH: CSV_PAYLOAD}
    )

    with pytest.raises(CompositionError, match="SHA-256 mismatch"):
        _read_bundle(source, "0" * 64)


def test_rejects_qid_set_mismatch(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)])
    retrieval = _bundle(tmp_path, "retrieval.zip", [_record(2)])

    with pytest.raises(CompositionError, match="QID sets differ"):
        _compose_records(answer, retrieval, expected_count=1, table_cap=10)


def test_rejects_duplicate_qid(tmp_path: Path) -> None:
    source = _source_zip(
        tmp_path / "duplicate.zip",
        [_record(1), _record(1)],
        csvs={CSV_PATH: CSV_PAYLOAD},
    )

    with pytest.raises(CompositionError, match="duplicate QID 1"):
        _read_bundle(source)


def test_rejects_missing_answer_evidence_csv(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)], include_csv=False)
    required = _required_csvs(list(answer.records))

    with pytest.raises(CompositionError, match="missing 1 evidence CSVs"):
        _answer_csv_payloads(answer, required)


def test_rejects_extra_submission_field(tmp_path: Path) -> None:
    record = {**_record(1), "unexpected": True}
    source = _source_zip(
        tmp_path / "extra-field.zip", [record], csvs={CSV_PATH: CSV_PAYLOAD}
    )

    with pytest.raises(CompositionError, match="fields differ"):
        _read_bundle(source)


def test_rejects_retrieval_over_table_cap(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)])
    tables = [f"DOC_{index}|{index + 1}" for index in range(11)]
    retrieval = _bundle(
        tmp_path, "retrieval.zip", [_record(1, tables=tables)]
    )

    with pytest.raises(CompositionError, match="cap is 10"):
        _compose_records(answer, retrieval, expected_count=1, table_cap=10)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (_record(1, tables=["DOC_A|1", "DOC_A|1"]), "duplicate relevant_tables"),
        (
            _record(
                1,
                tables=["DOC_A|1", "DOC_B|2"],
                docs=["DOC_A", "DOC_A"],
            ),
            "duplicate relevant_docs",
        ),
    ],
)
def test_rejects_duplicate_retrieval_references(
    tmp_path: Path, record: dict[str, object], message: str
) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)])
    retrieval = _bundle(tmp_path, "retrieval.zip", [record])

    with pytest.raises(CompositionError, match=message):
        _compose_records(answer, retrieval, expected_count=1, table_cap=10)


def test_rejects_docs_not_derived_from_retrieval_tables(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)])
    retrieval = _bundle(
        tmp_path,
        "retrieval.zip",
        [_record(1, tables=["DOC_A|1", "DOC_B|2"], docs=["DOC_B", "DOC_A"])],
    )

    with pytest.raises(CompositionError, match="not exactly derived"):
        _compose_records(answer, retrieval, expected_count=1, table_cap=10)


def test_two_independent_writes_are_byte_identical(tmp_path: Path) -> None:
    answer = _bundle(tmp_path, "answer.zip", [_record(1)])
    retrieval = _bundle(
        tmp_path, "retrieval.zip", [_record(1, tables=["RET_B|2", "RET_A|1"])]
    )
    records, _ = _compose_records(
        answer, retrieval, expected_count=1, table_cap=10
    )
    payloads = _answer_csv_payloads(answer, _required_csvs(records))

    first_sha, first_json_sha = _write_zip(tmp_path / "first.zip", records, payloads)
    second_sha, second_json_sha = _write_zip(
        tmp_path / "second.zip", records, payloads
    )

    assert first_sha == second_sha
    assert first_json_sha == second_json_sha
    assert hashlib.sha256((tmp_path / "first.zip").read_bytes()).digest() == (
        hashlib.sha256((tmp_path / "second.zip").read_bytes()).digest()
    )


def test_writer_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    output = tmp_path / "sealed.zip"
    output.write_bytes(b"sealed")

    with pytest.raises(CompositionError, match="immutable output already exists"):
        _write_zip(output, [_record(1)], {CSV_PATH: CSV_PAYLOAD})
