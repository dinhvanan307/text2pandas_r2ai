#!/usr/bin/env python3
"""Build a coverage-only differential for the frozen Wave 5 shadow checkpoints."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


EXPECTED_BASELINE_SHA256 = "2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76"
STAGES = (
    "s1-contract",
    "s2-selector",
    "s3-binding",
    "s4-direct",
    "s5-difference-sum",
    "s6-average",
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not all(isinstance(item, dict) for item in records):
        raise TypeError(f"expected JSON objects: {path}")
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index(records: list[dict[str, Any]], path: Path) -> dict[int, dict[str, Any]]:
    indexed = {int(item["qid"]): item for item in records}
    if len(indexed) != 1012 or set(indexed) != set(range(1, 1013)):
        raise ValueError(f"stage must contain QID 1..1012 exactly once: {path}")
    return indexed


def _counts(records: list[dict[str, Any]]) -> dict[str, object]:
    return {
        "records": len(records),
        "statuses": dict(sorted(Counter(str(item["status"]) for item in records).items())),
        "reasons": dict(
            sorted(Counter(str(item.get("reason") or "OK") for item in records).items())
        ),
    }


def _fingerprint(record: dict[str, Any]) -> str:
    selected = {
        "status": record.get("status"),
        "reason": record.get("reason"),
        "answer": record.get("answer"),
        "pandas_query": record.get("pandas_query"),
        "plan_fingerprint": record.get("plan_fingerprint"),
        "selected_parse_candidate_id": record.get("selected_parse_candidate_id"),
        "evidence": record.get("evidence"),
    }
    canonical = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _transition(
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
    qids: set[int],
) -> dict[str, object]:
    status_changed = [qid for qid in qids if before[qid]["status"] != after[qid]["status"]]
    output_changed = [qid for qid in qids if _fingerprint(before[qid]) != _fingerprint(after[qid])]
    ok_gained = [
        qid for qid in qids if before[qid]["status"] != "OK" and after[qid]["status"] == "OK"
    ]
    ok_lost = [
        qid for qid in qids if before[qid]["status"] == "OK" and after[qid]["status"] != "OK"
    ]
    return {
        "status_changed": len(status_changed),
        "output_fingerprint_changed": len(output_changed),
        "ok_gained": len(ok_gained),
        "ok_lost": len(ok_lost),
        "status_changed_qids": sorted(status_changed),
        "ok_gained_qids": sorted(ok_gained),
        "ok_lost_qids": sorted(ok_lost),
    }


def _completed_review(record: dict[str, Any], *, adjudication: bool) -> bool:
    identity = record.get("adjudicator_id" if adjudication else "annotator_id")
    decision = (
        record.get("decision" if adjudication else "evidence_binding", {}).get("status")
        if not adjudication
        else record.get("decision")
    )
    return bool(
        identity
        and decision
        and record.get("independent_of_model_development") is True
        and record.get("source_evidence_reviewed") is True
    )


def build_report(args: argparse.Namespace) -> dict[str, object]:
    baseline = args.baseline.resolve()
    baseline_sha = _sha256(baseline)
    if baseline_sha != EXPECTED_BASELINE_SHA256:
        raise ValueError(f"baseline SHA mismatch: {baseline_sha}")

    scope = _json(args.scope.resolve())
    protected = _json(args.protected.resolve())
    scope_records = scope["records"]
    family_by_qid = {int(item["qid"]): str(item["family"]) for item in scope_records}
    risk_a = set(family_by_qid)
    sets = protected["sets"]
    p_answer = {int(value) for value in sets["p_answer"]}
    out_of_scope = {int(value) for value in sets["p_out_of_scope_unresolved"]}
    if len(risk_a) != 60 or len(p_answer) != 798 or len(out_of_scope) != 154:
        raise ValueError("protected cohort cardinality mismatch")

    review_dir = args.review_dir.resolve()
    reviewer_a = _jsonl(review_dir / "reviewer_a.jsonl")
    reviewer_b = _jsonl(review_dir / "reviewer_b.jsonl")
    adjudication = _jsonl(review_dir / "adjudication.jsonl")
    review_counts = {
        "reviewer_a_completed": sum(
            _completed_review(item, adjudication=False) for item in reviewer_a
        ),
        "reviewer_b_completed": sum(
            _completed_review(item, adjudication=False) for item in reviewer_b
        ),
        "adjudication_completed": sum(
            _completed_review(item, adjudication=True) for item in adjudication
        ),
    }

    stage_paths = dict(args.stage)
    if tuple(stage_paths) != STAGES:
        raise ValueError(f"stages must be supplied in order: {STAGES}")
    stages: dict[str, object] = {}
    stage_indexes: dict[str, dict[int, dict[str, Any]]] = {}
    previous_name: str | None = None
    all_qids = set(range(1, 1013))
    for name in STAGES:
        run_dir = Path(stage_paths[name]).resolve()
        records_path = run_dir / "records.jsonl"
        manifest_path = run_dir / "manifest.json"
        records = _jsonl(records_path)
        indexed = _index(records, records_path)
        stage_indexes[name] = indexed
        manifest = _json(manifest_path)
        by_family = {
            family: _counts(
                [indexed[qid] for qid in sorted(risk_a) if family_by_qid[qid] == family]
            )
            for family in sorted(set(family_by_qid.values()))
        }
        entry: dict[str, object] = {
            "run_dir": str(run_dir),
            "records_sha256": _sha256(records_path),
            "manifest_sha256": _sha256(manifest_path),
            "overall": _counts(records),
            "replay_mismatches": manifest["metrics"]["replay_mismatches"],
            "cohorts": {
                "p_answer_798": _counts([indexed[qid] for qid in sorted(p_answer)]),
                "risk_a60": _counts([indexed[qid] for qid in sorted(risk_a)]),
                "out_of_scope_154": _counts([indexed[qid] for qid in sorted(out_of_scope)]),
            },
            "risk_a60_by_family": by_family,
            "exactness": "NOT_MEASURED_NO_SEALED_REVIEW",
        }
        if previous_name is not None:
            entry["transition_from_previous"] = _transition(
                stage_indexes[previous_name], indexed, all_qids
            )
        stages[name] = entry
        previous_name = name

    s1 = stage_indexes["s1-contract"]
    s6 = stage_indexes["s6-average"]
    return {
        "schema_version": 1,
        "kind": "text2pandas.recovery_wave5_shadow_differential",
        "measurement_scope": "COVERAGE_REPLAY_ONLY_NOT_ACCURACY",
        "baseline": {
            "path": str(baseline),
            "sha256": baseline_sha,
            "identity_pass": True,
            "answer_records_preserved_by_shadow": "798/798",
            "retrieval_records_preserved_by_shadow": "1012/1012",
            "note": "shadow runs are separate artifacts and do not mutate submission 3842",
        },
        "review": {
            **review_counts,
            "required_per_slot": 60,
            "holdout_exactness": "NOT_MEASURED",
            "promotion": "BLOCKED_AWAITING_INDEPENDENT_A_B_C_REVIEW",
        },
        "stages": stages,
        "s1_to_s6": {
            "all_1012": _transition(s1, s6, all_qids),
            "p_answer_798": _transition(s1, s6, p_answer),
            "risk_a60": _transition(s1, s6, risk_a),
            "out_of_scope_154": _transition(s1, s6, out_of_scope),
        },
        "promotion": {
            "status": "BLOCKED",
            "candidate_built": False,
            "submission_zip": None,
            "reason": "independent review and one-shot holdout are unavailable",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--protected", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument(
        "--stage",
        action="append",
        nargs=2,
        metavar=("NAME", "RUN_DIR"),
        required=True,
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
