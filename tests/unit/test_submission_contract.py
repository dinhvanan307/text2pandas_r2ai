from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from text2pandas.application.usecases.answer import AnswerResult
from text2pandas.application.usecases.submission import (
    SubmissionConfig,
    build_submission,
    replay_zip,
    validate_zip,
)


DOC = "VNM_financial_statements_2023_consolidated"
QUESTION = "Doanh thu của VNM năm 2023 là bao nhiêu triệu đồng?"
QUERY = (
    "float(df1[(df1['row_path'] == 'Doanh thu') & "
    "(df1['col_label'] == '2023 VND')]['value'].values[0])"
)


def _corpus(root: Path) -> Path:
    corpus = root / "corpus"
    target = corpus / "VNM" / "2023" / DOC
    target.mkdir(parents=True)
    (target / f"{DOC}_extracted.txt").write_text(
        "page header\n<table>\n<tr><td>Doanh thu</td></tr>\n</table>\n",
        encoding="utf-8",
    )
    return corpus


def _result() -> AnswerResult:
    return AnswerResult(
        qid=1,
        answer=5.0,
        relevant_docs=[DOC],
        relevant_tables=[f"{DOC}|2"],
        evidence=[{"variable": "df1", "csv_path": "data/table.csv"}],
        pandas_query=QUERY,
        confidence=1.0,
        has_csv=True,
    )


def _build(root: Path, name: str) -> Path:
    output = root / name
    (output / "data").mkdir(parents=True)
    (output / "data" / "table.csv").write_text(
        "row_path,col_label,value\nDoanh thu,2023 VND,5.0\n",
        encoding="utf-8",
    )
    return build_submission([_result()], {1: QUESTION}, output, SubmissionConfig())


def test_submission_zip_is_deterministic_and_strictly_valid(tmp_path: Path) -> None:
    first = _build(tmp_path, "run-a")
    second = _build(tmp_path, "run-b")

    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
        second.read_bytes()
    ).digest()
    report = validate_zip(first, {1: QUESTION}, corpus_root=_corpus(tmp_path))
    assert report.ok, report.errors
    assert replay_zip(first, tmp_path / "unused") == {
        "total": 1,
        "executed": 1,
        "matched": 1,
        "no_evidence": 0,
        "error": 0,
    }


def test_validator_accepts_canonical_document_without_basis_suffix(tmp_path: Path) -> None:
    doc = "FTS_financial_statements_2024"
    corpus = tmp_path / "corpus"
    target = corpus / "FTS" / "2024" / doc
    target.mkdir(parents=True)
    (target / f"{doc}_extracted.txt").write_text(
        "page header\n<table>\n<tr><td>Doanh thu</td></tr>\n</table>\n",
        encoding="utf-8",
    )
    result = _result()
    result.relevant_docs = [doc]
    result.relevant_tables = [f"{doc}|2"]
    output = tmp_path / "no-basis"
    (output / "data").mkdir(parents=True)
    (output / "data" / "table.csv").write_text(
        "row_path,col_label,value\nDoanh thu,2023 VND,5.0\n",
        encoding="utf-8",
    )
    archive = build_submission([result], {1: QUESTION}, output, SubmissionConfig())

    report = validate_zip(archive, {1: QUESTION}, corpus_root=corpus)

    assert report.ok, report.errors


def test_validator_rejects_contract_and_grounding_defects(tmp_path: Path) -> None:
    record = {
        "id": 2,
        "question": "tampered",
        "answer": float("inf"),
        "relevant_docs": [DOC, DOC],
        "relevant_tables": [f"{DOC}|1"],
        "evidence": [
            {"variable": "df1", "csv_path": "data/table.csv", "unexpected": True}
        ],
        "pandas_query": "__import__('os').system('id')",
        "extra": True,
    }
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("submission.json", json.dumps([record]))
        target.writestr("data/table.csv", "value\n1\n")
        target.writestr("data/orphan.csv", "value\n2\n")
        target.writestr("notes.txt", "not part of the submission contract")

    report = validate_zip(archive, {1: QUESTION}, corpus_root=_corpus(tmp_path))

    joined = "\n".join(report.errors)
    assert "trường thừa" in joined
    assert "số hữu hạn" in joined
    assert "relevant_docs chứa phần tử trùng" in joined
    assert "relevant_docs phải suy ra đúng từ relevant_tables" in joined
    assert "locator không trỏ dòng mở table" in joined
    assert "allowlisted" in joined
    assert "evidence phải có đúng trường" in joined
    assert "member không được phép" in joined
    assert "thiếu 1 câu hỏi" in joined and "thừa 1 id" in joined
    assert "CSV không được evidence tham chiếu" in joined
