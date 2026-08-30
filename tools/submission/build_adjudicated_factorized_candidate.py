#!/usr/bin/env python3
"""Build the allowlisted A17 answer patch on the sealed 3811 x 3770 layers.

The tool is intentionally release-specific and fail-closed:

* only QIDs declared by the checksum-bound adjudication manifest may change;
* manual corrections are materialized from exact A6 observation UIDs;
* V3 fills must match an exact record in one sealed shadow package;
* all patch evidence is rematerialized from the active A6 database under a
  namespaced path, so it cannot overwrite a baseline evidence CSV;
* answer fields outside the allowlist remain exactly equal to submission 3811;
* retrieval fields remain exactly equal to submission 3770.

P0, MODEL_GOLD, answer generation and full Semantic V3 promotion are not run.
"""

from __future__ import annotations

import argparse
import csv
import importlib
import io
import json
import math
import sqlite3
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from text2pandas.application.usecases.submission import replay_zip, validate_zip

_factorized = importlib.import_module(
    "tools.submission.build_factorized_hybrid"
    if __package__
    else "build_factorized_hybrid"
)
CompositionError = _factorized.CompositionError
InputBundle = _factorized.InputBundle
_answer_csv_payloads = _factorized._answer_csv_payloads
_archive_metrics = _factorized._archive_metrics
_read_bundle = _factorized._read_bundle
_required_csvs = _factorized._required_csvs
_sha256_bytes = _factorized._sha256_bytes
_sha256_file = _factorized._sha256_file
_validate_retrieval_record = _factorized._validate_retrieval_record
_write_zip = _factorized._write_zip

JsonObject = dict[str, Any]
_ANSWER_FIELDS = ("answer", "evidence", "pandas_query")
_RETRIEVAL_FIELDS = ("relevant_tables", "relevant_docs")
_SOURCE_KINDS = frozenset(("A6_MANUAL", "SEMANTIC_V3_PACKAGE"))
_DECISIONS = frozenset(("CORRECT", "FILL"))


class PatchError(CompositionError):
    """Raised when an adjudication or source-integrity gate fails."""


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _question_sha256(question: str) -> str:
    return _sha256_bytes(question.encode("utf-8"))


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PatchError(f"{label} must be a 64-character SHA-256")
    try:
        int(value, 16)
    except ValueError as error:
        raise PatchError(f"{label} is not hexadecimal") from error
    return value


def _load_manifest(path: Path) -> JsonObject:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PatchError(f"cannot read patch manifest {path}: {error}") from error
    if not isinstance(decoded, dict):
        raise PatchError("patch manifest root must be an object")
    if decoded.get("schema_version") != "1.0":
        raise PatchError("unsupported patch manifest schema_version")

    identities = decoded.get("identities")
    policy = decoded.get("policy")
    patches = decoded.get("patches")
    if not isinstance(identities, dict) or not isinstance(policy, dict):
        raise PatchError("manifest identities and policy must be objects")
    if not isinstance(patches, list) or not patches:
        raise PatchError("manifest patches must be a non-empty list")

    for key in (
        "answer_zip_sha256",
        "retrieval_zip_sha256",
        "semantic_v3_zip_sha256",
        "a6_silver_db_sha256",
        "retrieval_db_sha256",
    ):
        _require_sha256(identities.get(key), f"identities.{key}")

    expected_corrections = policy.get("expected_corrections")
    expected_fills = policy.get("expected_fills")
    if isinstance(expected_corrections, bool) or not isinstance(expected_corrections, int):
        raise PatchError("policy.expected_corrections must be an integer")
    if isinstance(expected_fills, bool) or not isinstance(expected_fills, int):
        raise PatchError("policy.expected_fills must be an integer")
    for key in (
        "expected_records",
        "expected_baseline_emitted",
        "expected_output_emitted",
        "table_cap",
    ):
        value = policy.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PatchError(f"policy.{key} must be a positive integer")
    if policy["expected_output_emitted"] != (
        policy["expected_baseline_emitted"] + expected_fills
    ):
        raise PatchError(
            "policy.expected_output_emitted must equal "
            "expected_baseline_emitted + expected_fills"
        )
    if policy.get("p0_enabled") is not False:
        raise PatchError("P0 must remain disabled")
    if policy.get("model_gold_used") is not False:
        raise PatchError("MODEL_GOLD must remain unused")
    if policy.get("semantic_v3_promoted") is not False:
        raise PatchError("full Semantic V3 promotion is forbidden")
    if policy.get("fail_closed") is not True:
        raise PatchError("manifest must be fail-closed")

    seen: set[int] = set()
    decisions: Counter[str] = Counter()
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            raise PatchError(f"patch {index} must be an object")
        qid = patch.get("qid")
        if isinstance(qid, bool) or not isinstance(qid, int):
            raise PatchError(f"patch {index} has invalid qid")
        if qid in seen:
            raise PatchError(f"duplicate patch QID {qid}")
        seen.add(qid)
        decision = patch.get("decision")
        if decision not in _DECISIONS:
            raise PatchError(f"QID {qid}: invalid decision {decision!r}")
        decisions[str(decision)] += 1
        _require_sha256(patch.get("question_sha256"), f"QID {qid} question_sha256")
        answer = patch.get("expected_answer")
        if isinstance(answer, bool) or not isinstance(answer, (int, float)):
            raise PatchError(f"QID {qid}: expected_answer must be numeric")
        if not math.isfinite(float(answer)):
            raise PatchError(f"QID {qid}: expected_answer must be finite")
        if not isinstance(patch.get("rationale"), str) or not patch["rationale"].strip():
            raise PatchError(f"QID {qid}: rationale is required")
        source = patch.get("source")
        if not isinstance(source, dict) or source.get("kind") not in _SOURCE_KINDS:
            raise PatchError(f"QID {qid}: invalid source")
        if source["kind"] == "SEMANTIC_V3_PACKAGE":
            _require_sha256(source.get("record_sha256"), f"QID {qid} record_sha256")
        else:
            _validate_manual_source(qid, source)

    if decisions["CORRECT"] != expected_corrections:
        raise PatchError(
            f"manifest correction count is {decisions['CORRECT']}, "
            f"expected {expected_corrections}"
        )
    if decisions["FILL"] != expected_fills:
        raise PatchError(
            f"manifest fill count is {decisions['FILL']}, expected {expected_fills}"
        )
    if len(patches) != expected_corrections + expected_fills:
        raise PatchError("manifest patch count differs from correction + fill counts")
    return decoded


def _validate_manual_source(qid: int, source: JsonObject) -> None:
    evidence = source.get("evidence")
    query = source.get("pandas_query")
    if not isinstance(evidence, list) or not evidence:
        raise PatchError(f"QID {qid}: manual source evidence must be non-empty")
    if not isinstance(query, str) or not query:
        raise PatchError(f"QID {qid}: manual source pandas_query is required")
    variables: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise PatchError(f"QID {qid}: manual evidence item must be an object")
        variable = item.get("variable")
        table_uid = item.get("table_uid")
        observation_uids = item.get("observation_uids")
        if not isinstance(variable, str) or not variable.isidentifier():
            raise PatchError(f"QID {qid}: invalid manual evidence variable")
        if variable in variables:
            raise PatchError(f"QID {qid}: duplicate manual evidence variable {variable}")
        variables.add(variable)
        if not isinstance(table_uid, str) or len(table_uid) != 16:
            raise PatchError(f"QID {qid}: invalid table_uid")
        if (
            not isinstance(observation_uids, list)
            or not observation_uids
            or not all(isinstance(value, str) and len(value) == 16 for value in observation_uids)
            or len(observation_uids) != len(set(observation_uids))
        ):
            raise PatchError(f"QID {qid}: invalid observation_uids")


def _require_file_sha256(path: Path, expected: str, label: str) -> str:
    actual = _sha256_file(path)
    if actual != expected:
        raise PatchError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def _open_a6_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise PatchError(f"A6 database does not exist: {path}")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _fetch_observations(
    connection: sqlite3.Connection,
    qid: int,
    table_uid: str,
    observation_uids: list[str],
) -> list[JsonObject]:
    placeholders = ",".join("?" for _ in observation_uids)
    rows = connection.execute(
        f"SELECT o.observation_uid, o.table_uid, o.value_decimal_text, "
        f"o.directory_doc_id, o.evidence_ref, o.row_path_text, o.col_path_text, "
        f"t.locator FROM observations o JOIN tables t USING (table_uid) "
        f"WHERE o.observation_uid IN ({placeholders})",
        observation_uids,
    ).fetchall()
    by_uid = {str(row["observation_uid"]): row for row in rows}
    missing = [uid for uid in observation_uids if uid not in by_uid]
    if missing:
        raise PatchError(f"QID {qid}: A6 observations are missing: {missing}")
    expanded: list[JsonObject] = []
    for uid in observation_uids:
        row = by_uid[uid]
        actual_table = str(row["table_uid"])
        if actual_table != table_uid:
            raise PatchError(
                f"QID {qid}: observation {uid} belongs to {actual_table}, not {table_uid}"
            )
        value = row["value_decimal_text"]
        if value is None:
            raise PatchError(f"QID {qid}: observation {uid} has no decimal value")
        expanded.append(
            {
                "observation_uid": uid,
                "table_uid": table_uid,
                "value_decimal_text": str(value),
                "directory_doc_id": str(row["directory_doc_id"]),
                "evidence_ref": str(row["evidence_ref"]),
                "locator": str(row["locator"]),
                "row_path_text": str(row["row_path_text"] or ""),
                "col_path_text": str(row["col_path_text"] or ""),
            }
        )
    return expanded


def _decimal_equal(left: object, right: object) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError) as error:
        raise PatchError(f"cannot compare decimal values {left!r} and {right!r}") from error


def _materialized_csv_path(table_uid: str, observation_uids: list[str]) -> str:
    digest = _sha256_bytes("|".join(observation_uids).encode("ascii"))[:12]
    return f"data/a17_{table_uid}_{digest}.csv"


def _materialized_csv(expanded: list[JsonObject]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(("observation_uid", "value"))
    for item in expanded:
        writer.writerow((item["observation_uid"], item["value_decimal_text"]))
    return stream.getvalue().encode("utf-8")


def _register_payload(payloads: dict[str, bytes], path: str, payload: bytes) -> None:
    previous = payloads.setdefault(path, payload)
    if previous != payload:
        raise PatchError(f"generated evidence path collision with unequal bytes: {path}")


def _source_csv_rows(archive: zipfile.ZipFile, path: str, qid: int) -> list[JsonObject]:
    try:
        payload = archive.read(path)
    except KeyError as error:
        raise PatchError(f"QID {qid}: V3 source CSV is missing: {path}") from error
    try:
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8")))
        if reader.fieldnames != ["observation_uid", "value"]:
            raise PatchError(
                f"QID {qid}: V3 source CSV {path} has unexpected columns {reader.fieldnames}"
            )
        rows = list(reader)
    except UnicodeDecodeError as error:
        raise PatchError(f"QID {qid}: V3 source CSV is not UTF-8: {path}") from error
    if not rows:
        raise PatchError(f"QID {qid}: V3 source CSV is empty: {path}")
    uids = [row.get("observation_uid") for row in rows]
    if not all(isinstance(uid, str) and len(uid) == 16 for uid in uids):
        raise PatchError(f"QID {qid}: V3 source CSV has invalid observation UID")
    if len(uids) != len(set(uids)):
        raise PatchError(f"QID {qid}: V3 source CSV has duplicate observation UID")
    return rows


def _build_replacements(
    manifest: JsonObject,
    answer: InputBundle,
    v3: InputBundle,
    v3_zip: Path,
    connection: sqlite3.Connection,
) -> tuple[dict[int, JsonObject], dict[str, bytes], list[JsonObject]]:
    replacements: dict[int, JsonObject] = {}
    payloads: dict[str, bytes] = {}
    expanded_sources: list[JsonObject] = []
    with zipfile.ZipFile(v3_zip) as archive:
        for patch in manifest["patches"]:
            qid = int(patch["qid"])
            baseline = answer.by_qid.get(qid)
            if baseline is None:
                raise PatchError(f"QID {qid}: missing from answer source")
            question = str(baseline["question"])
            actual_question_sha = _question_sha256(question)
            if actual_question_sha != patch["question_sha256"]:
                raise PatchError(
                    f"QID {qid}: question SHA drift: expected {patch['question_sha256']}, "
                    f"got {actual_question_sha}"
                )
            source = patch["source"]
            if source["kind"] == "SEMANTIC_V3_PACKAGE":
                replacement, generated, expanded = _replacement_from_v3(
                    qid=qid,
                    patch=patch,
                    source=source,
                    v3=v3,
                    archive=archive,
                    connection=connection,
                )
            else:
                replacement, generated, expanded = _replacement_from_manual(
                    qid=qid,
                    patch=patch,
                    source=source,
                    connection=connection,
                )
            if replacement["answer"] == baseline["answer"]:
                raise PatchError(f"QID {qid}: patch does not change the baseline answer")
            replacements[qid] = replacement
            for path, payload in generated.items():
                _register_payload(payloads, path, payload)
            expanded_sources.append(
                {
                    "qid": qid,
                    "decision": patch["decision"],
                    "question_sha256": patch["question_sha256"],
                    "expected_answer": patch["expected_answer"],
                    "rationale": patch["rationale"],
                    "source_kind": source["kind"],
                    **expanded,
                }
            )
    return replacements, payloads, expanded_sources


def _replacement_from_v3(
    *,
    qid: int,
    patch: JsonObject,
    source: JsonObject,
    v3: InputBundle,
    archive: zipfile.ZipFile,
    connection: sqlite3.Connection,
) -> tuple[JsonObject, dict[str, bytes], JsonObject]:
    record = v3.by_qid.get(qid)
    if record is None:
        raise PatchError(f"QID {qid}: missing from V3 source")
    record_sha = _canonical_json_sha256(record)
    if record_sha != source["record_sha256"]:
        raise PatchError(
            f"QID {qid}: V3 record SHA drift: expected {source['record_sha256']}, "
            f"got {record_sha}"
        )
    if _question_sha256(str(record["question"])) != patch["question_sha256"]:
        raise PatchError(f"QID {qid}: V3 source question differs from manifest")
    if record["answer"] != patch["expected_answer"]:
        raise PatchError(
            f"QID {qid}: V3 answer {record['answer']!r} differs from expected "
            f"{patch['expected_answer']!r}"
        )
    evidence = record.get("evidence")
    query = record.get("pandas_query")
    if not isinstance(evidence, list) or not evidence or not isinstance(query, str) or not query:
        raise PatchError(f"QID {qid}: V3 source is not emitted")

    output_evidence: list[JsonObject] = []
    generated: dict[str, bytes] = {}
    expanded_items: list[JsonObject] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise PatchError(f"QID {qid}: malformed V3 evidence item")
        variable = item.get("variable")
        source_path = item.get("csv_path")
        if not isinstance(variable, str) or not isinstance(source_path, str):
            raise PatchError(f"QID {qid}: malformed V3 evidence fields")
        source_name = Path(source_path).name
        table_uid = Path(source_name).stem
        if source_path != f"data/{table_uid}.csv" or len(table_uid) != 16:
            raise PatchError(f"QID {qid}: V3 evidence path is not a table UID: {source_path}")
        source_rows = _source_csv_rows(archive, source_path, qid)
        observation_uids = [str(row["observation_uid"]) for row in source_rows]
        expanded = _fetch_observations(connection, qid, table_uid, observation_uids)
        for source_row, a6_row in zip(source_rows, expanded, strict=True):
            if not _decimal_equal(source_row["value"], a6_row["value_decimal_text"]):
                raise PatchError(
                    f"QID {qid}: V3/A6 value drift for {a6_row['observation_uid']}"
                )
        output_path = _materialized_csv_path(table_uid, observation_uids)
        payload = _materialized_csv(expanded)
        _register_payload(generated, output_path, payload)
        output_evidence.append({"variable": variable, "csv_path": output_path})
        expanded_items.append(
            {
                "variable": variable,
                "source_csv_path": source_path,
                "source_csv_sha256": _sha256_bytes(archive.read(source_path)),
                "output_csv_path": output_path,
                "output_csv_sha256": _sha256_bytes(payload),
                "observations": expanded,
            }
        )
    return (
        {
            "answer": record["answer"],
            "evidence": output_evidence,
            "pandas_query": query,
        },
        generated,
        {
            "source_record_sha256": record_sha,
            "pandas_query_sha256": _sha256_bytes(query.encode("utf-8")),
            "evidence": expanded_items,
        },
    )


def _replacement_from_manual(
    *,
    qid: int,
    patch: JsonObject,
    source: JsonObject,
    connection: sqlite3.Connection,
) -> tuple[JsonObject, dict[str, bytes], JsonObject]:
    output_evidence: list[JsonObject] = []
    generated: dict[str, bytes] = {}
    expanded_items: list[JsonObject] = []
    for item in source["evidence"]:
        table_uid = str(item["table_uid"])
        observation_uids = [str(value) for value in item["observation_uids"]]
        expanded = _fetch_observations(connection, qid, table_uid, observation_uids)
        output_path = _materialized_csv_path(table_uid, observation_uids)
        payload = _materialized_csv(expanded)
        _register_payload(generated, output_path, payload)
        output_evidence.append({"variable": item["variable"], "csv_path": output_path})
        expanded_items.append(
            {
                "variable": item["variable"],
                "output_csv_path": output_path,
                "output_csv_sha256": _sha256_bytes(payload),
                "observations": expanded,
            }
        )
    query = str(source["pandas_query"])
    return (
        {
            "answer": patch["expected_answer"],
            "evidence": output_evidence,
            "pandas_query": query,
        },
        generated,
        {
            "operation": source.get("operation"),
            "pandas_query_sha256": _sha256_bytes(query.encode("utf-8")),
            "evidence": expanded_items,
        },
    )


def _emitted(record: JsonObject) -> bool:
    return bool(record.get("evidence") and record.get("pandas_query"))


def _compose_records(
    answer: InputBundle,
    retrieval: InputBundle,
    replacements: dict[int, JsonObject],
    patches_by_qid: dict[int, JsonObject],
    *,
    expected_count: int,
    table_cap: int,
) -> tuple[list[JsonObject], JsonObject]:
    if len(answer.records) != expected_count or len(retrieval.records) != expected_count:
        raise PatchError(
            f"input record count mismatch: answer={len(answer.records)}, "
            f"retrieval={len(retrieval.records)}, expected={expected_count}"
        )
    if set(answer.by_qid) != set(retrieval.by_qid):
        raise PatchError("answer and retrieval QID sets differ")
    if set(replacements) != set(patches_by_qid):
        raise PatchError("replacement QIDs differ from the manifest allowlist")

    output: list[JsonObject] = []
    corrections = 0
    fills = 0
    changed_answer_qids: list[int] = []
    retrieval_changed_qids = 0
    for baseline in answer.records:
        qid = int(baseline["id"])
        retrieval_record = retrieval.by_qid[qid]
        if baseline["question"] != retrieval_record["question"]:
            raise PatchError(f"QID {qid}: answer/retrieval question mismatch")
        _validate_retrieval_record(retrieval_record, table_cap)
        replacement = replacements.get(qid)
        if replacement is None:
            answer_fields = {field: baseline[field] for field in _ANSWER_FIELDS}
        else:
            patch = patches_by_qid[qid]
            baseline_emitted = _emitted(baseline)
            if patch["decision"] == "CORRECT":
                if not baseline_emitted:
                    raise PatchError(f"QID {qid}: CORRECT patch targets a baseline abstention")
                corrections += 1
            else:
                if baseline_emitted:
                    raise PatchError(f"QID {qid}: FILL patch targets an emitted baseline")
                fills += 1
            answer_fields = replacement
            if all(answer_fields[field] == baseline[field] for field in _ANSWER_FIELDS):
                raise PatchError(f"QID {qid}: allowlisted patch changes no answer field")
            changed_answer_qids.append(qid)
        if any(
            baseline[field] != retrieval_record[field] for field in _RETRIEVAL_FIELDS
        ):
            retrieval_changed_qids += 1
        output.append(
            {
                "id": qid,
                "question": baseline["question"],
                "answer": answer_fields["answer"],
                "relevant_docs": list(retrieval_record["relevant_docs"]),
                "relevant_tables": list(retrieval_record["relevant_tables"]),
                "evidence": list(answer_fields["evidence"]),
                "pandas_query": answer_fields["pandas_query"],
            }
        )
    return output, {
        "records": len(output),
        "corrections": corrections,
        "fills": fills,
        "changed_answer_qids": changed_answer_qids,
        "unchanged_answer_qids": len(output) - len(changed_answer_qids),
        "retrieval_changed_qids_vs_3811": retrieval_changed_qids,
    }


def _diff_layers(
    output: list[JsonObject],
    answer: InputBundle,
    retrieval: InputBundle,
    patch_qids: set[int],
) -> JsonObject:
    outside_equal = 0
    patched_equal_manifest = 0
    retrieval_equal = 0
    question_equal = 0
    max_tables = 0
    for index, record in enumerate(output):
        baseline = answer.records[index]
        qid = int(record["id"])
        retrieval_record = retrieval.by_qid[qid]
        question_equal += record["question"] == baseline["question"]
        if qid not in patch_qids:
            outside_equal += all(record[field] == baseline[field] for field in _ANSWER_FIELDS)
        else:
            patched_equal_manifest += qid in patch_qids
        retrieval_equal += all(
            record[field] == retrieval_record[field] for field in _RETRIEVAL_FIELDS
        )
        max_tables = max(max_tables, len(record["relevant_tables"]))
    return {
        "records": len(output),
        "question_equal_3811": question_equal,
        "answer_fields_equal_3811_outside_allowlist": outside_equal,
        "patched_qids_present": patched_equal_manifest,
        "retrieval_fields_equal_3770": retrieval_equal,
        "emitted": sum(_emitted(record) for record in output),
        "max_tables": max_tables,
        "duplicate_ids": len(output) - len({record["id"] for record in output}),
        "duplicate_table_qids": sum(
            len(record["relevant_tables"]) != len(set(record["relevant_tables"]))
            for record in output
        ),
        "duplicate_doc_qids": sum(
            len(record["relevant_docs"]) != len(set(record["relevant_docs"]))
            for record in output
        ),
    }


def _release_passes(
    *,
    policy: JsonObject,
    composition: JsonObject,
    diff: JsonObject,
    source_count: int,
    archive: JsonObject,
    validation_errors: list[str],
    validation_warnings: list[str],
    replay: JsonObject,
) -> bool:
    expected_records = int(policy["expected_records"])
    expected_patches = int(policy["expected_corrections"]) + int(policy["expected_fills"])
    expected_unchanged = expected_records - expected_patches
    return bool(
        composition["records"] == expected_records
        and composition["corrections"] == policy["expected_corrections"]
        and composition["fills"] == policy["expected_fills"]
        and len(composition["changed_answer_qids"]) == expected_patches
        and composition["unchanged_answer_qids"] == expected_unchanged
        and diff["records"] == expected_records
        and diff["question_equal_3811"] == expected_records
        and diff["answer_fields_equal_3811_outside_allowlist"] == expected_unchanged
        and diff["patched_qids_present"] == expected_patches
        and diff["retrieval_fields_equal_3770"] == expected_records
        and diff["emitted"] == policy["expected_output_emitted"]
        and diff["max_tables"] <= policy["table_cap"]
        and diff["duplicate_ids"] == 0
        and diff["duplicate_table_qids"] == 0
        and diff["duplicate_doc_qids"] == 0
        and source_count == expected_patches
        and archive["root_submission_json"] == 1
        and archive["missing_csvs"] == 0
        and archive["orphan_csvs"] == 0
        and not validation_errors
        and not validation_warnings
        and replay["total"] == expected_records
        and replay["executed"] == policy["expected_output_emitted"]
        and replay["matched"] == policy["expected_output_emitted"]
        and replay["error"] == 0
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the adjudicated A17 answer patch on 3811 x 3770"
    )
    parser.add_argument("--answer-zip", type=Path, required=True)
    parser.add_argument("--retrieval-zip", type=Path, required=True)
    parser.add_argument("--v3-zip", type=Path, required=True)
    parser.add_argument("--a6-db", type=Path, required=True)
    parser.add_argument("--retrieval-db", type=Path, required=True)
    parser.add_argument("--patch-manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists() or args.report.exists():
        parser.error("immutable output/report already exists")

    manifest = _load_manifest(args.patch_manifest)
    identities = manifest["identities"]
    policy = manifest["policy"]
    manifest_sha = _sha256_file(args.patch_manifest)

    answer = _read_bundle(args.answer_zip, identities["answer_zip_sha256"])
    retrieval = _read_bundle(args.retrieval_zip, identities["retrieval_zip_sha256"])
    v3 = _read_bundle(args.v3_zip, identities["semantic_v3_zip_sha256"])
    baseline_emitted = sum(_emitted(record) for record in answer.records)
    if baseline_emitted != policy["expected_baseline_emitted"]:
        raise PatchError(
            f"answer source emitted count is {baseline_emitted}, "
            f"expected {policy['expected_baseline_emitted']}"
        )
    a6_sha = _require_file_sha256(
        args.a6_db, identities["a6_silver_db_sha256"], "A6 silver database"
    )
    retrieval_db_sha = _require_file_sha256(
        args.retrieval_db, identities["retrieval_db_sha256"], "retrieval database"
    )

    patches_by_qid = {int(patch["qid"]): patch for patch in manifest["patches"]}
    connection = _open_a6_read_only(args.a6_db)
    try:
        replacements, patch_payloads, expanded_sources = _build_replacements(
            manifest, answer, v3, args.v3_zip, connection
        )
    finally:
        connection.close()

    records, composition = _compose_records(
        answer,
        retrieval,
        replacements,
        patches_by_qid,
        expected_count=int(policy["expected_records"]),
        table_cap=int(policy["table_cap"]),
    )
    required_csvs = _required_csvs(records)
    patch_paths = set(patch_payloads)
    if not patch_paths <= required_csvs:
        raise PatchError("generated patch evidence is not fully referenced")
    if patch_paths & answer.members:
        raise PatchError("namespaced patch evidence collides with the answer ZIP")
    baseline_payloads = _answer_csv_payloads(answer, required_csvs - patch_paths)
    csv_payloads = {**baseline_payloads, **patch_payloads}
    if set(csv_payloads) != required_csvs:
        raise PatchError("materialized CSV set differs from required evidence set")

    output_sha, output_json_sha = _write_zip(args.output, records, csv_payloads)
    questions = {int(record["id"]): str(record["question"]) for record in answer.records}
    validation = validate_zip(
        args.output,
        questions,
        corpus_root=args.corpus_root,
        strict=True,
    )
    replay = replay_zip(args.output, Path("/tmp/text2pandas_adjudicated_a17_replay"))
    archive = _archive_metrics(args.output, required_csvs)
    diff = _diff_layers(records, answer, retrieval, set(patches_by_qid))
    passed = _release_passes(
        policy=policy,
        composition=composition,
        diff=diff,
        source_count=len(expanded_sources),
        archive=archive,
        validation_errors=validation.errors,
        validation_warnings=validation.warnings,
        replay=replay,
    )

    report: JsonObject = {
        "schema_version": "1.0",
        "strategy": manifest["strategy"],
        "status": "PASS" if passed else "BLOCKED",
        "patch_id": manifest["patch_id"],
        "manifest": {
            "path": str(args.patch_manifest),
            "sha256": manifest_sha,
        },
        "identities": {
            **identities,
            "verified_a6_silver_db_sha256": a6_sha,
            "verified_retrieval_db_sha256": retrieval_db_sha,
        },
        "inputs": {
            "answer_zip": str(args.answer_zip),
            "retrieval_zip": str(args.retrieval_zip),
            "semantic_v3_zip": str(args.v3_zip),
            "a6_db": str(args.a6_db),
            "retrieval_db": str(args.retrieval_db),
        },
        "policy": policy,
        "composition": composition,
        "answer_source_emitted": baseline_emitted,
        "layer_diff": diff,
        "source_verification": {
            "verified_patches": len(expanded_sources),
            "manual": sum(
                item["source_kind"] == "A6_MANUAL" for item in expanded_sources
            ),
            "semantic_v3_package": sum(
                item["source_kind"] == "SEMANTIC_V3_PACKAGE"
                for item in expanded_sources
            ),
            "expanded": expanded_sources,
        },
        "evidence_csvs": {
            "required": len(required_csvs),
            "copied_from_3811": len(baseline_payloads),
            "materialized_a17": len(patch_payloads),
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
            "zip_sha256": output_sha,
            "submission_json_sha256": output_json_sha,
        },
        "release_gate": {
            "pass": passed,
            "decision": "BUILD_PASS" if passed else "BLOCKED",
        },
        "official_answer_accuracy": "NOT_MEASURED_UNTIL_UPLOAD",
        "official_execution_accuracy": "NOT_MEASURED_UNTIL_UPLOAD",
        "official_retrieval_metrics": "NOT_MEASURED_UNTIL_UPLOAD",
        "upload_status": "NOT_UPLOADED",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
