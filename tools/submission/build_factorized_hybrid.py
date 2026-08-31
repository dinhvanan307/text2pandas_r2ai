#!/usr/bin/env python3
"""Compose the sealed 3811 answer layer with the sealed 3770 retrieval layer.

This release tool intentionally implements one fixed field-ownership contract:

* id/question/answer/evidence/pandas_query come from the answer ZIP;
* relevant_tables/relevant_docs come from the retrieval ZIP;
* every evidence CSV comes byte-for-byte from the answer ZIP.

It does not run answer generation, retrieval, P0, or MODEL_GOLD.  Every
identity, equality, validation, replay, and determinism prerequisite is
fail-closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from text2pandas.application.usecases.submission import replay_zip, validate_zip


JsonObject = dict[str, Any]
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_FIELD_ORDER = (
    "id",
    "question",
    "answer",
    "relevant_docs",
    "relevant_tables",
    "evidence",
    "pandas_query",
)
_FIELDS = frozenset(_FIELD_ORDER)
_EVIDENCE_FIELDS = frozenset(("variable", "csv_path"))


class CompositionError(RuntimeError):
    """Raised when a sealed input or a factorized ownership gate fails."""


@dataclass(frozen=True, slots=True)
class InputBundle:
    """One immutable submission input with preserved record order."""

    path: Path
    records: tuple[JsonObject, ...]
    by_qid: dict[int, JsonObject]
    zip_sha256: str
    submission_json_sha256: str
    members: frozenset[str]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_digest(path: Path, expected: str | None) -> str:
    actual = _sha256_file(path)
    if expected is not None and actual != expected:
        raise CompositionError(
            f"SHA-256 mismatch for {path}: expected {expected}, got {actual}"
        )
    return actual


def _read_bundle(path: Path, expected_sha256: str | None = None) -> InputBundle:
    zip_sha256 = _require_digest(path, expected_sha256)
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise CompositionError(f"{path}: duplicate archive member")
            json_members = [name for name in names if name.lower().endswith(".json")]
            if json_members != ["submission.json"]:
                raise CompositionError(
                    f"{path}: expected exactly one root submission.json"
                )
            payload = archive.read("submission.json")
    except (OSError, zipfile.BadZipFile, KeyError) as error:
        raise CompositionError(f"cannot read submission bundle {path}: {error}") from error

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CompositionError(f"{path}: invalid submission.json: {error}") from error
    if not isinstance(decoded, list):
        raise CompositionError(f"{path}: submission.json root must be a list")

    records: list[JsonObject] = []
    by_qid: dict[int, JsonObject] = {}
    for index, item in enumerate(decoded):
        if not isinstance(item, dict):
            raise CompositionError(f"{path}: record {index} must be an object")
        if set(item) != _FIELDS:
            raise CompositionError(
                f"{path}: record {index} fields differ from the submission contract"
            )
        qid = item.get("id")
        if isinstance(qid, bool) or not isinstance(qid, int):
            raise CompositionError(f"{path}: record {index} has invalid QID")
        if qid in by_qid:
            raise CompositionError(f"{path}: duplicate QID {qid}")
        records.append(item)
        by_qid[qid] = item

    return InputBundle(
        path=path,
        records=tuple(records),
        by_qid=by_qid,
        zip_sha256=zip_sha256,
        submission_json_sha256=_sha256_bytes(payload),
        members=frozenset(names),
    )


def _derived_docs(tables: list[str]) -> list[str]:
    docs: list[str] = []
    for table in tables:
        if "|" not in table:
            raise CompositionError(f"malformed table locator: {table!r}")
        doc = table.rsplit("|", 1)[0]
        if doc not in docs:
            docs.append(doc)
    return docs


def _validate_retrieval_record(record: JsonObject, table_cap: int) -> None:
    qid = record["id"]
    tables = record.get("relevant_tables")
    docs = record.get("relevant_docs")
    if not isinstance(tables, list) or not all(isinstance(item, str) for item in tables):
        raise CompositionError(f"QID {qid}: relevant_tables must be list[str]")
    if not isinstance(docs, list) or not all(isinstance(item, str) for item in docs):
        raise CompositionError(f"QID {qid}: relevant_docs must be list[str]")
    if len(tables) > table_cap:
        raise CompositionError(
            f"QID {qid}: retrieval source has {len(tables)} tables, cap is {table_cap}"
        )
    if len(tables) != len(set(tables)):
        raise CompositionError(f"QID {qid}: duplicate relevant_tables")
    if len(docs) != len(set(docs)):
        raise CompositionError(f"QID {qid}: duplicate relevant_docs")
    if docs != _derived_docs(tables):
        raise CompositionError(
            f"QID {qid}: relevant_docs are not exactly derived from relevant_tables"
        )


def _compose_records(
    answer: InputBundle,
    retrieval: InputBundle,
    *,
    expected_count: int | None,
    table_cap: int,
) -> tuple[list[JsonObject], dict[str, int]]:
    if expected_count is not None:
        if len(answer.records) != expected_count:
            raise CompositionError(
                f"answer source must contain {expected_count} records, "
                f"found {len(answer.records)}"
            )
        if len(retrieval.records) != expected_count:
            raise CompositionError(
                f"retrieval source must contain {expected_count} records, "
                f"found {len(retrieval.records)}"
            )
    if set(answer.by_qid) != set(retrieval.by_qid):
        missing = sorted(set(answer.by_qid) - set(retrieval.by_qid))[:5]
        extra = sorted(set(retrieval.by_qid) - set(answer.by_qid))[:5]
        raise CompositionError(
            f"answer/retrieval QID sets differ: missing={missing}, extra={extra}"
        )

    output: list[JsonObject] = []
    question_equal = 0
    changed_retrieval = 0
    for answer_record in answer.records:
        qid = int(answer_record["id"])
        retrieval_record = retrieval.by_qid[qid]
        if answer_record.get("question") != retrieval_record.get("question"):
            raise CompositionError(f"QID {qid}: source questions differ")
        question_equal += 1
        _validate_retrieval_record(retrieval_record, table_cap)
        if (
            answer_record.get("relevant_tables")
            != retrieval_record.get("relevant_tables")
            or answer_record.get("relevant_docs")
            != retrieval_record.get("relevant_docs")
        ):
            changed_retrieval += 1
        output.append(
            {
                "id": qid,
                "question": answer_record["question"],
                "answer": answer_record["answer"],
                "relevant_docs": list(retrieval_record["relevant_docs"]),
                "relevant_tables": list(retrieval_record["relevant_tables"]),
                "evidence": list(answer_record["evidence"]),
                "pandas_query": answer_record["pandas_query"],
            }
        )
    return output, {
        "records": len(output),
        "question_equal": question_equal,
        "retrieval_changed_qids": changed_retrieval,
    }


def _required_csvs(records: list[JsonObject]) -> set[str]:
    required: set[str] = set()
    for record in records:
        qid = record["id"]
        evidence = record.get("evidence")
        if not isinstance(evidence, list):
            raise CompositionError(f"QID {qid}: evidence must be a list")
        for item in evidence:
            if not isinstance(item, dict) or set(item) != _EVIDENCE_FIELDS:
                raise CompositionError(f"QID {qid}: malformed evidence item")
            path = item.get("csv_path")
            if not isinstance(path, str) or not path.startswith("data/") or not path.endswith(
                ".csv"
            ):
                raise CompositionError(f"QID {qid}: invalid evidence CSV path {path!r}")
            if Path(path).parts != ("data", Path(path).name) or "\\" in path:
                raise CompositionError(f"QID {qid}: unsafe evidence CSV path {path!r}")
            required.add(path)
    return required


def _answer_csv_payloads(
    answer: InputBundle, required: set[str]
) -> dict[str, bytes]:
    missing = sorted(required - answer.members)
    if missing:
        raise CompositionError(
            f"answer source is missing {len(missing)} evidence CSVs: {missing[:5]}"
        )
    payloads: dict[str, bytes] = {}
    with zipfile.ZipFile(answer.path) as archive:
        for name in sorted(required):
            payloads[name] = archive.read(name)
    return payloads


def _write_member(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    archive.writestr(info, payload)


def _write_zip(
    path: Path,
    records: list[JsonObject],
    csv_payloads: dict[str, bytes],
) -> tuple[str, str]:
    if path.exists():
        raise CompositionError(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    json_payload = json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8")
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        _write_member(archive, "submission.json", json_payload)
        for name in sorted(csv_payloads):
            _write_member(archive, name, csv_payloads[name])
    return _sha256_file(path), _sha256_bytes(json_payload)


def _emitted(record: JsonObject) -> bool:
    return bool(record.get("evidence") and record.get("pandas_query"))


def _layer_diff(
    output: list[JsonObject],
    answer: InputBundle,
    retrieval: InputBundle,
) -> dict[str, int]:
    answer_equal = {field: 0 for field in ("id", "question", "answer", "evidence", "pandas_query")}
    retrieval_equal = {field: 0 for field in ("relevant_tables", "relevant_docs")}
    max_tables = 0
    duplicate_ids = len(output) - len({record["id"] for record in output})
    duplicate_table_qids = 0
    duplicate_doc_qids = 0
    for index, record in enumerate(output):
        answer_record = answer.records[index]
        retrieval_record = retrieval.by_qid[int(record["id"])]
        for field in answer_equal:
            answer_equal[field] += record[field] == answer_record[field]
        for field in retrieval_equal:
            retrieval_equal[field] += record[field] == retrieval_record[field]
        tables = record["relevant_tables"]
        docs = record["relevant_docs"]
        max_tables = max(max_tables, len(tables))
        duplicate_table_qids += len(tables) != len(set(tables))
        duplicate_doc_qids += len(docs) != len(set(docs))
    return {
        "records": len(output),
        "id_order_equal_answer": answer_equal["id"],
        "question_equal_answer": answer_equal["question"],
        "answer_equal_answer": answer_equal["answer"],
        "evidence_equal_answer": answer_equal["evidence"],
        "pandas_query_equal_answer": answer_equal["pandas_query"],
        "relevant_tables_equal_retrieval": retrieval_equal["relevant_tables"],
        "relevant_docs_equal_retrieval": retrieval_equal["relevant_docs"],
        "emitted": sum(_emitted(record) for record in output),
        "max_tables": max_tables,
        "duplicate_ids": duplicate_ids,
        "duplicate_table_qids": duplicate_table_qids,
        "duplicate_doc_qids": duplicate_doc_qids,
    }


def _archive_metrics(path: Path, required_csvs: set[str]) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    csv_members = {name for name in names if name.lower().endswith(".csv")}
    return {
        "members": len(names),
        "root_submission_json": names.count("submission.json"),
        "csv_members": len(csv_members),
        "missing_csvs": len(required_csvs - csv_members),
        "orphan_csvs": len(csv_members - required_csvs),
    }


def _hard_gate(
    *,
    diff: dict[str, int],
    composition: dict[str, int],
    csv_count: int,
    archive: dict[str, int],
    validation_errors: list[str],
    validation_warnings: list[str],
    replay: dict[str, int],
    expected_count: int,
    expected_emitted: int,
    expected_csvs: int,
    expected_changed_qids: int,
    table_cap: int,
) -> bool:
    equality_keys = (
        "id_order_equal_answer",
        "question_equal_answer",
        "answer_equal_answer",
        "evidence_equal_answer",
        "pandas_query_equal_answer",
        "relevant_tables_equal_retrieval",
        "relevant_docs_equal_retrieval",
    )
    return bool(
        diff["records"] == expected_count
        and all(diff[key] == expected_count for key in equality_keys)
        and composition["question_equal"] == expected_count
        and composition["retrieval_changed_qids"] == expected_changed_qids
        and diff["emitted"] == expected_emitted
        and diff["max_tables"] <= table_cap
        and diff["duplicate_ids"] == 0
        and diff["duplicate_table_qids"] == 0
        and diff["duplicate_doc_qids"] == 0
        and csv_count == expected_csvs
        and archive["root_submission_json"] == 1
        and archive["csv_members"] == expected_csvs
        and archive["missing_csvs"] == 0
        and archive["orphan_csvs"] == 0
        and not validation_errors
        and not validation_warnings
        and replay["total"] == expected_count
        and replay["executed"] == expected_emitted
        and replay["matched"] == expected_emitted
        and replay["error"] == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the sealed 3811-answer x 3770-retrieval candidate"
    )
    parser.add_argument("--answer-zip", type=Path, required=True)
    parser.add_argument("--retrieval-zip", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expect-answer-sha256", required=True)
    parser.add_argument("--expect-retrieval-sha256", required=True)
    parser.add_argument("--expected-count", type=int, default=1012)
    parser.add_argument("--expected-emitted", type=int, default=625)
    parser.add_argument("--expected-evidence-csvs", type=int, default=1070)
    parser.add_argument("--expect-retrieval-changed-qids", type=int, default=176)
    parser.add_argument("--table-cap", type=int, default=10)
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("immutable output/report already exists")
    if min(
        args.expected_count,
        args.expected_emitted,
        args.expected_evidence_csvs,
        args.table_cap,
    ) < 1:
        parser.error("expected counts and table cap must be positive")
    if args.expect_retrieval_changed_qids < 0:
        parser.error("expected changed-QID count cannot be negative")

    answer = _read_bundle(args.answer_zip, args.expect_answer_sha256)
    retrieval = _read_bundle(args.retrieval_zip, args.expect_retrieval_sha256)
    records, composition = _compose_records(
        answer,
        retrieval,
        expected_count=args.expected_count,
        table_cap=args.table_cap,
    )
    required_csvs = _required_csvs(records)
    csv_payloads = _answer_csv_payloads(answer, required_csvs)
    output_sha256, output_json_sha256 = _write_zip(
        args.output, records, csv_payloads
    )

    questions = {int(record["id"]): str(record["question"]) for record in answer.records}
    diff = _layer_diff(records, answer, retrieval)
    archive = _archive_metrics(args.output, required_csvs)
    validation = validate_zip(
        args.output, questions, corpus_root=args.corpus_root, strict=True
    )
    replay = replay_zip(args.output, Path("/tmp/text2pandas_factorized_hybrid"))
    passed = _hard_gate(
        diff=diff,
        composition=composition,
        csv_count=len(csv_payloads),
        archive=archive,
        validation_errors=validation.errors,
        validation_warnings=validation.warnings,
        replay=replay,
        expected_count=args.expected_count,
        expected_emitted=args.expected_emitted,
        expected_csvs=args.expected_evidence_csvs,
        expected_changed_qids=args.expect_retrieval_changed_qids,
        table_cap=args.table_cap,
    )
    report: JsonObject = {
        "schema_version": "1.0",
        "strategy": "FACTORIZED_3811_ANSWER_3770_RETRIEVAL",
        "status": "PASS" if passed else "BLOCKED",
        "p0_enabled": False,
        "model_gold_used": False,
        "inputs": {
            "answer": {
                "path": str(args.answer_zip),
                "submission_id": 3811,
                "zip_sha256": answer.zip_sha256,
                "submission_json_sha256": answer.submission_json_sha256,
            },
            "retrieval": {
                "path": str(args.retrieval_zip),
                "submission_id": 3770,
                "zip_sha256": retrieval.zip_sha256,
                "submission_json_sha256": retrieval.submission_json_sha256,
            },
        },
        "field_ownership": {
            "answer_source": [
                "id",
                "question",
                "answer",
                "evidence",
                "pandas_query",
                "data/*.csv",
            ],
            "retrieval_source": ["relevant_tables", "relevant_docs"],
        },
        "expected": {
            "records": args.expected_count,
            "emitted": args.expected_emitted,
            "evidence_csvs": args.expected_evidence_csvs,
            "retrieval_changed_qids": args.expect_retrieval_changed_qids,
            "table_cap": args.table_cap,
        },
        "composition": composition,
        "layer_diff": diff,
        "evidence_csvs": {
            "required": len(required_csvs),
            "copied_from_answer_source": len(csv_payloads),
            "byte_identity_by_construction": len(csv_payloads),
        },
        "archive": archive,
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
        "output": {
            "path": str(args.output),
            "zip_sha256": output_sha256,
            "submission_json_sha256": output_json_sha256,
        },
        "release_gate": {
            "pass": passed,
            "decision": "BUILD_PASS" if passed else "BLOCKED",
        },
        "official_metrics": "NOT_MEASURED_UNTIL_UPLOAD",
        "upload_status": "NOT_UPLOADED",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["release_gate"], ensure_ascii=False, indent=2))
    print(json.dumps(diff, ensure_ascii=False, indent=2))
    print(json.dumps(report["validation"], ensure_ascii=False, indent=2))
    print(json.dumps(replay, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
