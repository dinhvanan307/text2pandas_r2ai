#!/usr/bin/env python3
"""Build a fail-closed baseline union and retrieval-overlay submission.

The composer has two intentionally asymmetric rules:

1. every emitted baseline answer/query/evidence triple is immutable;
2. a current Canonical record may fill a baseline abstention only after its
   materialized query cleanly replays to the recorded answer.

The FINAL package then preserves every UNION table reference in order and
appends references from an already sealed retrieval-winner package.  The
normal cap is ten tables.  If the baseline already exceeds ten, all baseline
references are retained and no further table is appended.

This tool never reads P0 traces or MODEL_GOLD.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from text2pandas.application.usecases.submission import replay_zip, validate_zip
from text2pandas.infrastructure.sandbox.query import execute_query


JsonObject = dict[str, Any]
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_SUBMISSION_FIELDS = (
    "id",
    "question",
    "answer",
    "relevant_docs",
    "relevant_tables",
    "evidence",
    "pandas_query",
)


class CompositionError(RuntimeError):
    """Raised when an immutable input or preservation gate fails."""


@dataclass(frozen=True, slots=True)
class InputBundle:
    records: dict[int, JsonObject]
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
    if expected and actual != expected:
        raise CompositionError(
            f"SHA-256 mismatch for {path}: expected {expected}, got {actual}"
        )
    return actual


def _read_submission(path: Path) -> InputBundle:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if names.count("submission.json") != 1:
            raise CompositionError(f"{path} must contain one root submission.json")
        payload = archive.read("submission.json")
        decoded = json.loads(payload)
    if not isinstance(decoded, list):
        raise CompositionError(f"{path}: submission.json must contain a list")
    records: dict[int, JsonObject] = {}
    for item in decoded:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            raise CompositionError(f"{path}: malformed submission record")
        qid = int(item["id"])
        if qid in records:
            raise CompositionError(f"{path}: duplicate QID {qid}")
        records[qid] = item
    return InputBundle(records, _sha256_bytes(payload), frozenset(names))


def _read_current_records(path: Path) -> dict[int, JsonObject]:
    records: dict[int, JsonObject] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if not isinstance(item, dict) or not isinstance(item.get("qid"), int):
            raise CompositionError(f"{path}: malformed Canonical record")
        qid = int(item["qid"])
        if qid in records:
            raise CompositionError(f"{path}: duplicate QID {qid}")
        records[qid] = item
    return records


def _numeric(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        result = float(value)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _emitted(record: JsonObject) -> bool:
    return bool(
        _numeric(record.get("answer")) is not None
        and record.get("pandas_query")
        and record.get("evidence")
    )


def _close(left: object, right: object, tolerance: float) -> bool:
    actual = _numeric(left)
    expected = _numeric(right)
    return (
        actual is not None
        and expected is not None
        and abs(actual - expected) <= tolerance * max(1.0, abs(expected))
    )


def _ordered_union(*groups: object) -> list[str]:
    result: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        for value in group:
            if not isinstance(value, str):
                raise CompositionError("retrieval references must be strings")
            if value not in result:
                result.append(value)
    return result


def _docs_for_tables(tables: list[str]) -> list[str]:
    docs: list[str] = []
    for table in tables:
        if "|" not in table:
            raise CompositionError(f"malformed table reference: {table!r}")
        doc = table.rsplit("|", 1)[0]
        if doc not in docs:
            docs.append(doc)
    return docs


def _submission_record(record: JsonObject, qid: int) -> JsonObject:
    return {
        "id": qid,
        "question": record.get("question"),
        "answer": record.get("answer"),
        "relevant_docs": list(record.get("relevant_docs") or []),
        "relevant_tables": list(record.get("relevant_tables") or []),
        "evidence": list(record.get("evidence") or []),
        "pandas_query": record.get("pandas_query") or "",
    }


def _replay_current_record(
    record: JsonObject,
    data_root: Path,
    cache: dict[Path, pd.DataFrame],
    tolerance: float,
) -> tuple[bool, str | None]:
    if record.get("status") != "OK" or not _emitted(record):
        return False, "NOT_EMITTED_OK"
    frames: dict[str, object] = {}
    try:
        for evidence in record["evidence"]:
            csv_path = data_root / str(evidence["csv_path"])
            if not csv_path.is_file():
                return False, f"CSV_MISSING:{csv_path}"
            if csv_path not in cache:
                cache[csv_path] = pd.read_csv(csv_path)
            frames[str(evidence["variable"])] = cache[csv_path]
        actual = execute_query(str(record["pandas_query"]), frames)
    except Exception as error:  # noqa: BLE001 - surfaced as a release blocker
        return False, f"{type(error).__name__}:{error}"
    if not _close(actual, record.get("answer"), tolerance):
        return False, f"ANSWER_MISMATCH:{actual!r}!={record.get('answer')!r}"
    return True, None


def _merge_union(
    baseline: dict[int, JsonObject],
    current: dict[int, JsonObject],
    current_data_root: Path,
    *,
    tolerance: float,
) -> tuple[list[JsonObject], list[int], dict[int, str]]:
    if set(baseline) != set(current):
        raise CompositionError("baseline and Canonical records must contain identical QIDs")
    cache: dict[Path, pd.DataFrame] = {}
    added: list[int] = []
    rejected: dict[int, str] = {}
    result: list[JsonObject] = []
    for qid in sorted(baseline):
        before = _submission_record(baseline[qid], qid)
        candidate = current[qid]
        if _emitted(before):
            result.append(before)
            continue
        if not _emitted(candidate):
            result.append(before)
            continue
        replayed, failure = _replay_current_record(
            candidate, current_data_root, cache, tolerance
        )
        if not replayed:
            rejected[qid] = failure or "REPLAY_FAILED"
            result.append(before)
            continue
        if candidate.get("question") != before.get("question"):
            raise CompositionError(f"QID {qid}: Canonical question differs from baseline")
        tables = _ordered_union(
            before.get("relevant_tables"), candidate.get("relevant_tables")
        )
        merged = {
            "id": qid,
            "question": before["question"],
            "answer": candidate["answer"],
            "relevant_docs": _docs_for_tables(tables),
            "relevant_tables": tables,
            "evidence": list(candidate["evidence"]),
            "pandas_query": candidate["pandas_query"],
        }
        result.append(merged)
        added.append(qid)
    return result, added, rejected


def _merge_overlay(
    union: list[JsonObject],
    retrieval: dict[int, JsonObject],
    *,
    table_cap: int,
) -> tuple[list[JsonObject], dict[str, object]]:
    union_by_qid = {int(item["id"]): item for item in union}
    if set(union_by_qid) != set(retrieval):
        raise CompositionError("UNION and retrieval winner must contain identical QIDs")
    output: list[JsonObject] = []
    changed = 0
    table_additions = 0
    over_cap_preserved: list[int] = []
    for qid in sorted(union_by_qid):
        source = union_by_qid[qid]
        tables = _ordered_union(source.get("relevant_tables"))
        original = list(tables)
        if len(tables) > table_cap:
            over_cap_preserved.append(qid)
        if len(tables) < table_cap:
            for table in retrieval[qid].get("relevant_tables") or []:
                if table not in tables and len(tables) < table_cap:
                    tables.append(str(table))
                    table_additions += 1
        if tables != original:
            changed += 1
        item = dict(source)
        item["relevant_tables"] = tables
        item["relevant_docs"] = _docs_for_tables(tables)
        output.append(item)
    return output, {
        "changed_qids": changed,
        "table_additions": table_additions,
        "table_cap": table_cap,
        "over_cap_baseline_qids": over_cap_preserved,
        "max_tables": max(len(item["relevant_tables"]) for item in output),
        "mean_tables": sum(len(item["relevant_tables"]) for item in output)
        / len(output),
    }


def _required_csvs(records: list[JsonObject]) -> set[str]:
    required: set[str] = set()
    for record in records:
        evidence = record.get("evidence") or []
        for item in evidence:
            path = item.get("csv_path")
            if not isinstance(path, str):
                raise CompositionError(f"QID {record['id']}: malformed evidence path")
            required.add(path)
    return required


def _evidence_payloads(
    baseline_zip: Path,
    current_data_root: Path,
    current_qids: list[int],
    union_records: list[JsonObject],
) -> dict[str, bytes]:
    current_by_qid = {int(record["id"]): record for record in union_records}
    current_paths = {
        str(item["csv_path"])
        for qid in current_qids
        for item in current_by_qid[qid].get("evidence") or []
    }
    required = _required_csvs(union_records)
    payloads: dict[str, bytes] = {}
    with zipfile.ZipFile(baseline_zip) as archive:
        baseline_names = set(archive.namelist())
        for name in sorted(required):
            baseline_payload = archive.read(name) if name in baseline_names else None
            current_path = current_data_root / name
            current_payload = current_path.read_bytes() if current_path.is_file() else None
            if name in current_paths:
                if current_payload is None:
                    raise CompositionError(f"Canonical evidence is missing: {current_path}")
                if baseline_payload is not None and baseline_payload != current_payload:
                    raise CompositionError(
                        f"evidence filename collision with different bytes: {name}"
                    )
                payloads[name] = current_payload
            elif baseline_payload is not None:
                payloads[name] = baseline_payload
            elif current_payload is not None:
                payloads[name] = current_payload
            else:
                raise CompositionError(f"no evidence source for {name}")
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
    evidence_payloads: dict[str, bytes],
) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise CompositionError(f"immutable output already exists: {path}")
    json_payload = json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8")
    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        _write_member(archive, "submission.json", json_payload)
        for name in sorted(evidence_payloads):
            _write_member(archive, name, evidence_payloads[name])
    return _sha256_file(path), _sha256_bytes(json_payload)


def _preservation_metrics(
    baseline: dict[int, JsonObject],
    union: list[JsonObject],
    final: list[JsonObject],
) -> dict[str, object]:
    union_by_qid = {int(item["id"]): item for item in union}
    final_by_qid = {int(item["id"]): item for item in final}
    emitted = [qid for qid, item in baseline.items() if _emitted(item)]
    answer_equal = sum(
        baseline[qid].get("answer") == union_by_qid[qid].get("answer")
        == final_by_qid[qid].get("answer")
        for qid in emitted
    )
    query_equal = sum(
        baseline[qid].get("pandas_query") == union_by_qid[qid].get("pandas_query")
        == final_by_qid[qid].get("pandas_query")
        for qid in emitted
    )
    evidence_equal = sum(
        baseline[qid].get("evidence") == union_by_qid[qid].get("evidence")
        == final_by_qid[qid].get("evidence")
        for qid in emitted
    )
    table_prefix_preserved = sum(
        final_by_qid[qid]["relevant_tables"][: len(item.get("relevant_tables") or [])]
        == (item.get("relevant_tables") or [])
        for qid, item in baseline.items()
    )
    return {
        "baseline_emitted": len(emitted),
        "answer_unchanged": answer_equal,
        "query_unchanged": query_equal,
        "evidence_unchanged": evidence_equal,
        "baseline_table_prefix_preserved": table_prefix_preserved,
        "total_qids": len(baseline),
    }


def _answer_gold_metrics(
    gold_path: Path | None,
    baseline: dict[int, JsonObject],
    union: list[JsonObject],
    final: list[JsonObject],
    tolerance: float,
) -> dict[str, object]:
    if gold_path is None:
        return {"status": "NOT_MEASURED"}
    gold = [
        json.loads(line)
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    evaluable = [item for item in gold if item.get("trang_thai") == "OK"]
    union_by_qid = {int(item["id"]): item for item in union}
    final_by_qid = {int(item["id"]): item for item in final}

    def correct(records: dict[int, JsonObject]) -> list[int]:
        return [
            int(item["qid"])
            for item in evaluable
            if _emitted(records[int(item["qid"])])
            and _close(
                records[int(item["qid"])].get("answer"),
                item.get("normalized_answer_gold"),
                tolerance,
            )
        ]

    baseline_correct = correct(baseline)
    union_correct = correct(union_by_qid)
    final_correct = correct(final_by_qid)
    return {
        "status": "LOCAL_INDEPENDENT_GOLD_NOT_OFFICIAL",
        "gold_path": str(gold_path),
        "gold_sha256": _sha256_file(gold_path),
        "evaluable": len(evaluable),
        "baseline_correct": len(baseline_correct),
        "union_correct": len(union_correct),
        "final_correct": len(final_correct),
        "union_wins": sorted(set(union_correct) - set(baseline_correct)),
        "union_losses": sorted(set(baseline_correct) - set(union_correct)),
    }


def _validate_and_replay(
    zip_path: Path,
    questions: dict[int, str],
    corpus_root: Path,
) -> dict[str, object]:
    validation = validate_zip(zip_path, questions, corpus_root=corpus_root, strict=True)
    replay = replay_zip(zip_path, Path("/tmp/text2pandas_union_overlay_replay"))
    passed = (
        validation.ok
        and not validation.warnings
        and replay["error"] == 0
        and replay["matched"] == replay["executed"]
    )
    return {
        "pass": passed,
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-zip", type=Path, required=True)
    parser.add_argument("--current-records", type=Path, required=True)
    parser.add_argument("--current-data-root", type=Path, required=True)
    parser.add_argument("--retrieval-winner-zip", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--answer-gold", type=Path)
    parser.add_argument("--output-union", type=Path, required=True)
    parser.add_argument("--output-final", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--table-cap", type=int, default=10)
    parser.add_argument("--tolerance", type=float, default=1e-6)
    parser.add_argument("--expect-baseline-sha256")
    parser.add_argument("--expect-current-records-sha256")
    parser.add_argument("--expect-retrieval-winner-sha256")
    args = parser.parse_args()
    if args.table_cap < 1:
        parser.error("--table-cap must be positive")
    if not 0 <= args.tolerance < 1:
        parser.error("--tolerance must be in [0, 1)")
    for output in (args.output_union, args.output_final, args.report):
        if output.exists():
            parser.error(f"immutable output already exists: {output}")

    baseline_sha = _require_digest(args.baseline_zip, args.expect_baseline_sha256)
    current_sha = _require_digest(
        args.current_records, args.expect_current_records_sha256
    )
    retrieval_sha = _require_digest(
        args.retrieval_winner_zip, args.expect_retrieval_winner_sha256
    )
    baseline_bundle = _read_submission(args.baseline_zip)
    retrieval_bundle = _read_submission(args.retrieval_winner_zip)
    current = _read_current_records(args.current_records)
    if len(baseline_bundle.records) != 1012:
        raise CompositionError("baseline must contain exactly 1,012 records")

    union, added_qids, rejected = _merge_union(
        baseline_bundle.records,
        current,
        args.current_data_root,
        tolerance=args.tolerance,
    )
    final, overlay = _merge_overlay(
        union, retrieval_bundle.records, table_cap=args.table_cap
    )
    evidence_payloads = _evidence_payloads(
        args.baseline_zip, args.current_data_root, added_qids, union
    )
    union_sha, union_json_sha = _write_zip(args.output_union, union, evidence_payloads)
    final_sha, final_json_sha = _write_zip(args.output_final, final, evidence_payloads)

    questions = {
        qid: str(record.get("question") or "")
        for qid, record in baseline_bundle.records.items()
    }
    union_gate = _validate_and_replay(args.output_union, questions, args.corpus_root)
    final_gate = _validate_and_replay(args.output_final, questions, args.corpus_root)
    preservation = _preservation_metrics(baseline_bundle.records, union, final)
    hard_preservation_pass = all(
        preservation[key] == preservation["baseline_emitted"]
        for key in ("answer_unchanged", "query_unchanged", "evidence_unchanged")
    ) and preservation["baseline_table_prefix_preserved"] == preservation["total_qids"]
    package_pass = bool(union_gate["pass"] and final_gate["pass"] and hard_preservation_pass)

    report = {
        "schema_version": "1.0",
        "strategy": "BASELINE_UNION_PLUS_RETRIEVAL_WINNER_OVERLAY",
        "p0_enabled": False,
        "model_gold_used": False,
        "inputs": {
            "baseline_zip": {
                "path": str(args.baseline_zip),
                "sha256": baseline_sha,
                "submission_json_sha256": baseline_bundle.submission_json_sha256,
            },
            "current_records": {"path": str(args.current_records), "sha256": current_sha},
            "retrieval_winner_zip": {
                "path": str(args.retrieval_winner_zip),
                "sha256": retrieval_sha,
                "submission_json_sha256": retrieval_bundle.submission_json_sha256,
                "profile": {
                    "score_margin": 0.50,
                    "primary_boost": 0.60,
                    "normal_table_cap": args.table_cap,
                },
            },
        },
        "union": {
            "records": len(union),
            "baseline_emitted": sum(_emitted(item) for item in baseline_bundle.records.values()),
            "canonical_emitted": sum(_emitted(item) for item in current.values()),
            "added": len(added_qids),
            "added_qids": added_qids,
            "replay_rejected": rejected,
            "emitted": sum(_emitted(item) for item in union),
            "output": {
                "path": str(args.output_union),
                "sha256": union_sha,
                "submission_json_sha256": union_json_sha,
            },
            "gate": union_gate,
        },
        "overlay": overlay,
        "final": {
            "records": len(final),
            "emitted": sum(_emitted(item) for item in final),
            "output": {
                "path": str(args.output_final),
                "sha256": final_sha,
                "submission_json_sha256": final_json_sha,
            },
            "gate": final_gate,
        },
        "preservation": {**preservation, "pass": hard_preservation_pass},
        "local_answer_gold": _answer_gold_metrics(
            args.answer_gold,
            baseline_bundle.records,
            union,
            final,
            args.tolerance,
        ),
        "release_gate": {
            "pass": package_pass,
            "decision": "FINAL_READY" if package_pass else "BLOCKED",
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["release_gate"], ensure_ascii=False, indent=2))
    print(json.dumps(report["preservation"], ensure_ascii=False, indent=2))
    print(json.dumps(report["union"], ensure_ascii=False, indent=2))
    print(json.dumps(report["overlay"], ensure_ascii=False, indent=2))
    return 0 if package_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
