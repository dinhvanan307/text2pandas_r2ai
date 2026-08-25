"""Materialize small, auditable artifacts required by integration gates."""

from __future__ import annotations

import json
import re
from pathlib import Path

from text2pandas.infrastructure.checksums import sha256_file


class MaterializationError(ValueError):
    """Source provenance cannot support the requested materialized claim."""


_A6_EXPONENT = re.compile(r"a6\s*\(?10\^(?P<exponent>-?\d+)\)?", re.IGNORECASE)
_RAW_EVIDENCE = re.compile(
    r"raw\s+'(?P<token>[^']+)'\s+o\s+(?P<field>[a-z_]+)",
    re.IGNORECASE,
)


def resolved_unit_adjudications(records_path: Path, questions_path: Path) -> list[dict]:
    """Reconstruct the historical final ledger from resolved record provenance.

    The resolved record is the surviving source of truth after the old H0 work
    directory was relocated. Only explicit ``A6_DEFECT_FIXED`` records qualify;
    missing original scale or evidence is a hard failure, never an inference.
    """

    questions = {
        int(record["id"]): str(record["question"])
        for record in _read_jsonl(questions_path)
    }
    source_sha = sha256_file(records_path)
    output: list[dict] = []
    for record in _read_jsonl(records_path):
        provenance = record.get("provenance") or {}
        if provenance.get("unit_adjudication") != "A6_DEFECT_FIXED":
            continue
        reason = str(provenance.get("unit_adjudication_reason") or "")
        exponent_match = _A6_EXPONENT.search(reason)
        evidence_match = _RAW_EVIDENCE.search(reason)
        if not exponent_match or not evidence_match:
            raise MaterializationError(
                f"q{record.get('qid')}: resolved unit provenance is incomplete"
            )
        qid = int(record["qid"])
        final_exponent = provenance.get("scale_exponent")
        if final_exponent is None:
            raise MaterializationError(f"q{qid}: missing final scale exponent")
        output.append(
            {
                "qid": qid,
                "observation_uid": provenance.get("observation_uid"),
                "source_cell_uid": provenance.get("source_cell_uid"),
                "evidence_ref": provenance.get("evidence_ref"),
                "question": questions.get(qid, "")[:180],
                "a6_scale_exponent": int(exponent_match.group("exponent")),
                "a6_scale_source": "historical_resolver_provenance",
                "competing_scale_exponent": provenance.get("scale_bang_khai"),
                "raw_value": provenance.get("value_source_raw"),
                "raw_header": None,
                "raw_col_path": provenance.get("col_path"),
                "raw_row_path": provenance.get("row_path"),
                "raw_section": None,
                "final_status": "A6_DEFECT",
                "final_scale_exponent": int(final_exponent),
                "resolver_action": "OVERRIDE_SCALE",
                "decision_reason": reason,
                "evidence_found": [
                    {
                        "exponent": int(final_exponent),
                        "token": evidence_match.group("token"),
                        "field": evidence_match.group("field"),
                    }
                ],
                "materialized_from": {
                    "path": records_path.as_posix(),
                    "sha256": source_sha,
                    "status": "resolved_record_provenance",
                },
            }
        )
    if not output:
        raise MaterializationError("no explicit resolved unit adjudications found")
    return sorted(output, key=lambda item: item["qid"])


def write_jsonl(records: list[dict], output_path: Path, *, force: bool = False) -> None:
    if output_path.exists() and not force:
        raise FileExistsError(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    output_path.write_text(payload, encoding="utf-8")


def determinism_report(
    run_1: Path,
    run_2: Path,
    *,
    canonical: Path | None = None,
    input_hashes: dict[str, str] | None = None,
) -> dict:
    """Compare two independently built ZIPs and emit a checkable claim."""

    first = sha256_file(run_1)
    second = sha256_file(run_2)
    report = {
        "schema_version": 2,
        "deterministic_full_zip_sha256": first == second,
        "run_1": {"path": str(run_1), "zip_sha256": first, "bytes": run_1.stat().st_size},
        "run_2": {"path": str(run_2), "zip_sha256": second, "bytes": run_2.stat().st_size},
        "input_hashes": dict(sorted((input_hashes or {}).items())),
    }
    if canonical is not None:
        canonical_sha = sha256_file(canonical)
        report["canonical"] = {
            "path": str(canonical),
            "zip_sha256": canonical_sha,
            "matches_rebuild": canonical_sha == first,
        }
    return report


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
