"""Compare a Semantic V3 metric resolver candidate with the sealed clean B0."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from text2pandas.pipelines.answering.frame import classify_operation
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.question_intent import parse_intent

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / "artifacts/runs/semantic-v3"
DEFAULT_BASELINE = RUN_ROOT / "metric-unresolved-b0-clean-20260828"
DEFAULT_CANDIDATE = RUN_ROOT / "metric-unresolved-candidate-v1-20260828"
DEFAULT_WARM = (
    RUN_ROOT / "metric-unresolved-candidate-v1-warm-a-20260828",
    RUN_ROOT / "metric-unresolved-candidate-v1-warm-b-20260828",
)
DEFAULT_OUTPUT = DEFAULT_CANDIDATE / "evaluation"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_record(record: dict[str, Any]) -> str:
    copied = json.loads(json.dumps(record))
    for evidence in copied.get("evidence", ()):
        evidence.pop("csv_path", None)
    return json.dumps(copied, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stages(record: dict[str, Any]) -> set[str]:
    return {
        str(value["stage"])
        for value in record.get("trace", ())
        if isinstance(value, dict) and value.get("stage")
    }


def _candidate_available(record: dict[str, Any]) -> bool:
    return any(
        value.get("stage") == "RETRIEVE_OPERANDS"
        and any(
            int(request.get("candidates", 0)) > 0 for request in value.get("requests", {}).values()
        )
        for value in record.get("trace", ())
        if isinstance(value, dict)
    )


def _binder_reached(record: dict[str, Any]) -> bool:
    return any(
        isinstance(value, dict) and "surviving_assignments" in value
        for value in record.get("trace", ())
    )


def _source_bindings(value: object) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    if isinstance(value, dict):
        binding = value.get("source_binding")
        if isinstance(binding, dict):
            output.append(binding)
        for child in value.values():
            output.extend(_source_bindings(child))
    elif isinstance(value, list):
        for child in value:
            output.extend(_source_bindings(child))
    return output


def _v2_snapshot(questions: list[dict[str, Any]]) -> list[dict[str, object]]:
    aliases = load_aliases("a6")
    output: list[dict[str, object]] = []
    for item in questions:
        question = str(item["question"])
        operation = classify_operation(question)
        intent = parse_intent(question, aliases)
        output.append(
            {
                "qid": int(item["id"]),
                "operation": operation.op,
                "return_mode": operation.return_mode,
                "rank_direction": operation.rank_direction,
                "entities": list(intent.targets),
                "years": list(intent.years),
                "basis": intent.explicit_scope,
            }
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--warm-run", type=Path, action="append")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    warm_runs = tuple(args.warm_run or DEFAULT_WARM)
    if args.output_dir.exists():
        raise FileExistsError(f"immutable evaluation output exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    baseline_rows = _jsonl(args.baseline / "records.jsonl")
    candidate_rows = _jsonl(args.candidate / "records.jsonl")
    baseline = {int(value["qid"]): value for value in baseline_rows}
    candidate = {int(value["qid"]): value for value in candidate_rows}
    if baseline.keys() != candidate.keys() or len(candidate) != 1012:
        raise ValueError("baseline/candidate corpus identity mismatch")

    cohort_rows = _jsonl(args.baseline / "baseline/cohort_h198.jsonl")
    cohort = {int(value["qid"]): value for value in cohort_rows}
    h198 = tuple(sorted(cohort))
    old_ok = tuple(sorted(qid for qid, value in baseline.items() if value["status"] == "OK"))
    new_ok = tuple(
        qid for qid in h198 if baseline[qid]["status"] != "OK" and candidate[qid]["status"] == "OK"
    )
    regressions = tuple(qid for qid in old_ok if candidate[qid]["status"] != "OK")
    semantic_drift = tuple(
        qid
        for qid in old_ok
        if _canonical_record(baseline[qid]) != _canonical_record(candidate[qid])
    )

    transition_counts: Counter[tuple[str, str]] = Counter()
    for qid in h198:
        before = str(baseline[qid].get("reason") or baseline[qid]["status"])
        after = str(candidate[qid].get("reason") or candidate[qid]["status"])
        transition_counts[(before, after)] += 1
    transitions = [
        {"before": before, "after": after, "count": count}
        for (before, after), count in sorted(
            transition_counts.items(), key=lambda value: (-value[1], value[0])
        )
    ]

    funnel = {
        "cohort": len(h198),
        "metric_unresolved_terminal": sum(
            candidate[qid].get("reason") == "METRIC_UNRESOLVED" for qid in h198
        ),
        "ast_created": sum(candidate[qid].get("ast") is not None for qid in h198),
        "plan_created": sum("PLAN" in _stages(candidate[qid]) for qid in h198),
        "candidate_available": sum(_candidate_available(candidate[qid]) for qid in h198),
        "binder_reached": sum(_binder_reached(candidate[qid]) for qid in h198),
        "new_ok": len(new_ok),
    }
    tiers: dict[str, dict[str, object]] = {}
    for tier in ("T1", "T2", "T3", "NO_PHRASE"):
        qids = tuple(qid for qid in h198 if cohort[qid]["tier"] == tier)
        tiers[tier] = {
            "questions": len(qids),
            "left_metric_unresolved": sum(
                candidate[qid].get("reason") != "METRIC_UNRESOLVED" for qid in qids
            ),
            "ast_created": sum(candidate[qid].get("ast") is not None for qid in qids),
            "plan_created": sum("PLAN" in _stages(candidate[qid]) for qid in qids),
            "candidate_available": sum(_candidate_available(candidate[qid]) for qid in qids),
            "binder_reached": sum(_binder_reached(candidate[qid]) for qid in qids),
            "new_ok": sum(candidate[qid]["status"] == "OK" for qid in qids),
            "terminal_reasons": dict(
                Counter(str(candidate[qid].get("reason") or "OK") for qid in qids).most_common()
            ),
        }

    deterministic_runs: list[dict[str, object]] = []
    for run in warm_runs:
        rows = {int(value["qid"]): value for value in _jsonl(run / "records.jsonl")}
        mismatch = [
            qid
            for qid in sorted(candidate)
            if _canonical_record(candidate[qid]) != _canonical_record(rows[qid])
        ]
        deterministic_runs.append(
            {"run_id": run.name, "mismatches": len(mismatch), "mismatch_qids": mismatch}
        )

    manifests = [
        json.loads((run / "manifest.json").read_text(encoding="utf-8"))
        for run in (args.candidate, *warm_runs)
    ]
    cold_seconds = float(manifests[0]["metrics"]["seconds"])
    warm_seconds = [float(value["metrics"]["seconds"]) for value in manifests[1:]]
    runtime = {
        "baseline_seconds": json.loads(
            (args.baseline / "manifest.json").read_text(encoding="utf-8")
        )["metrics"]["seconds"],
        "cold_seconds": cold_seconds,
        "warm_seconds": warm_seconds,
        "warm_median_seconds": statistics.median(warm_seconds),
        "resolver_seconds": manifests[0]["metric_resolution"]["resolve_seconds"],
        "db_lookup_seconds": manifests[0]["metric_resolution"]["db_lookup_seconds"],
        "cache_hits": manifests[0]["metric_resolution"]["cache_hits"],
        "cache_misses": manifests[0]["metric_resolution"]["cache_misses"],
        "peak_rss_bytes": max(int(value["metrics"]["peak_rss_bytes"]) for value in manifests),
    }

    questions = _jsonl(ROOT / "data/raw/btc/questions/questions.jsonl")
    lexical_path = args.output_dir / "current_v2_lexical_snapshot.jsonl"
    _write_jsonl(lexical_path, _v2_snapshot(questions))
    baseline_lexical = args.baseline / "baseline/v2_lexical_snapshot.jsonl"

    candidate_replay = {
        qid
        for qid, value in candidate.items()
        if str(value.get("reason") or "").startswith("TYPED_PANDAS_MISMATCH")
    }
    baseline_replay = {
        qid
        for qid, value in baseline.items()
        if str(value.get("reason") or "").startswith("TYPED_PANDAS_MISMATCH")
    }
    unsafe_emissions = [
        qid
        for qid, value in candidate.items()
        if value["status"] == "OK"
        and (
            not value.get("evidence")
            or not any(
                item.get("stage") == "PANDAS_REPLAY" and item.get("status") == "MATCH"
                for item in value.get("trace", ())
                if isinstance(item, dict)
            )
        )
    ]
    safety = {
        "old_ok_questions": len(old_ok),
        "old_ok_regressions": len(regressions),
        "old_ok_regression_qids": list(regressions),
        "old_ok_semantic_drift": len(semantic_drift),
        "old_ok_semantic_drift_qids": list(semantic_drift),
        "v2_baseline_sha256": _sha256(baseline_lexical),
        "v2_current_sha256": _sha256(lexical_path),
        "v2_lexical_drift": _sha256(baseline_lexical) != _sha256(lexical_path),
        "unsafe_emissions": len(unsafe_emissions),
        "unsafe_emission_qids": unsafe_emissions,
        "new_replay_mismatches": len(candidate_replay - baseline_replay),
        "new_replay_mismatch_qids": sorted(candidate_replay - baseline_replay),
        "deterministic_runs": deterministic_runs,
    }

    baseline_reasons = Counter(str(value.get("reason") or "OK") for value in baseline.values())
    candidate_reasons = Counter(str(value.get("reason") or "OK") for value in candidate.values())
    summary = {
        "schema_version": "metric-unresolved-evaluation-v1",
        "baseline_run_id": args.baseline.name,
        "candidate_run_id": args.candidate.name,
        "questions": len(candidate),
        "baseline": {
            "ok": baseline_reasons["OK"],
            "abstain": len(baseline) - baseline_reasons["OK"],
            "metric_unresolved": baseline_reasons["METRIC_UNRESOLVED"],
        },
        "candidate": {
            "ok": candidate_reasons["OK"],
            "abstain": len(candidate) - candidate_reasons["OK"],
            "metric_unresolved": candidate_reasons["METRIC_UNRESOLVED"],
            "ambiguous": candidate_reasons["METRIC_HYPOTHESES_AMBIGUOUS"],
            "specificity_required": candidate_reasons["METRIC_SOURCE_SPECIFICITY_REQUIRED"],
            "question_mention_no_mapping": candidate_reasons["QUESTION_MENTION_NO_MAPPING"],
        },
        "frozen_h198_funnel": funnel,
        "tiers": tiers,
        "new_ok": len(new_ok),
        "regressions": len(regressions),
        "review_status": "NON-PROMOTABLE",
        "runtime": runtime,
        "safety": safety,
    }

    review_qids = set(new_ok)
    review_qids.update(qid for qid in h198 if cohort[qid]["tier"] == "T3")
    review_qids.update((100, 426, 502, 508, 870))
    review_queue = [
        {
            "qid": qid,
            "question": candidate[qid]["question"],
            "tier": cohort.get(qid, {}).get("tier", "BOUNDARY"),
            "baseline_reason": baseline[qid].get("reason"),
            "candidate_status": candidate[qid]["status"],
            "candidate_reason": candidate[qid].get("reason"),
            "answer": candidate[qid].get("answer"),
            "source_bindings": _source_bindings(candidate[qid].get("ast")),
            "review_status": "UNADJUDICATED",
        }
        for qid in sorted(review_qids)
    ]
    remaining = [
        {
            "qid": qid,
            "tier": cohort[qid]["tier"],
            "question": candidate[qid]["question"],
            "reason": candidate[qid].get("reason"),
            "ast_created": candidate[qid].get("ast") is not None,
            "plan_created": "PLAN" in _stages(candidate[qid]),
            "candidate_available": _candidate_available(candidate[qid]),
            "binder_reached": _binder_reached(candidate[qid]),
        }
        for qid in h198
        if candidate[qid]["status"] != "OK"
    ]

    _write_json(args.output_dir / "comparison_summary.json", summary)
    _write_json(args.output_dir / "transition_matrix.json", transitions)
    _write_json(args.output_dir / "runtime.json", runtime)
    _write_json(args.output_dir / "safety.json", safety)
    _write_jsonl(
        args.output_dir / "new_ok_qids.jsonl",
        ({"qid": qid, "tier": cohort[qid]["tier"]} for qid in new_ok),
    )
    _write_jsonl(args.output_dir / "remaining_h198.jsonl", remaining)
    _write_jsonl(args.output_dir / "review_queue.jsonl", review_queue)
    _write_jsonl(
        args.output_dir / "old_ok_drift.jsonl",
        ({"qid": qid} for qid in semantic_drift),
    )
    _write_json(
        args.output_dir / "checksums.json",
        {path.name: _sha256(path) for path in sorted(args.output_dir.iterdir()) if path.is_file()},
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
