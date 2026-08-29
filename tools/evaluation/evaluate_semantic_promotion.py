"""Evaluate one V3 run against a sealed gold release and locked policy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.promotion_evaluation import evaluate_semantic_gold
from text2pandas.application.usecases.semantic_v3_readiness import (
    PromotionMetrics,
    evaluate_promotion,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.semantic import load_promotion_policy


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _optional_report(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--gold-release", type=Path, required=True)
    parser.add_argument("--submission-handoff", type=Path, required=True)
    parser.add_argument("--reranker-report", type=Path)
    parser.add_argument("--policy", default="configs/semantic/promotion_policy_v3.yaml")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.005)
    args = parser.parse_args()
    records_path = args.records.expanduser().resolve()
    release = args.gold_release.expanduser().resolve()
    manifest_path = release / "manifest.json"
    gold_path = release / "gold.jsonl"
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "SEALED":
        raise ValueError("independent gold release is not SEALED")
    declared = str(((manifest.get("assets") or {}).get("gold.jsonl") or {}).get("sha256") or "")
    if declared != sha256_file(gold_path):
        raise ValueError("sealed gold checksum mismatch")

    evaluation = evaluate_semantic_gold(
        _rows(records_path),
        _rows(gold_path),
        tolerance=args.tolerance,
    )
    submission = _optional_report(args.submission_handoff.expanduser().resolve())
    replay = submission.get("replay") if isinstance(submission.get("replay"), dict) else {}
    validation = (
        submission.get("validation")
        if isinstance(submission.get("validation"), dict)
        else {}
    )
    reranker = _optional_report(
        args.reranker_report.expanduser().resolve() if args.reranker_report else None
    )
    reranker_metrics = (
        reranker.get("metrics") if isinstance(reranker.get("metrics"), dict) else {}
    )
    release_id = str(manifest.get("release_id") or "")
    metrics = PromotionMetrics(
        questions=len(_rows(records_path)),
        evaluation_release_id=release_id or None,
        evaluation_release_sealed=True,
        answer_gold_records=evaluation.records,
        semantic_gold_records=evaluation.records,
        evidence_gold_records=evaluation.records,
        parser_ast_exact=evaluation.parser_ast_exact,
        candidate_recall=evaluation.candidate_recall,
        binding_exact=evaluation.binding_exact,
        answer_accuracy=evaluation.answer_accuracy,
        reranker_heldout_records=_optional_int(reranker_metrics.get("heldout_records")),
        reranker_f2_delta=_optional_float(reranker_metrics.get("f2_delta")),
        reranker_f2_delta_ci95_low=_optional_float(
            reranker_metrics.get("f2_delta_ci95_low")
        ),
        reranker_protected_slice_delta=_optional_float(
            reranker_metrics.get("protected_slice_min_delta")
        ),
        submission_replay_records=_optional_int(replay.get("total")),
        replay_mismatches=_optional_int(replay.get("mismatches")),
        submission_errors=(
            len(validation.get("errors") or [])
            if isinstance(validation.get("errors") or [], list)
            else None
        ),
    )
    decision = evaluate_promotion(metrics, load_promotion_policy(args.policy))
    report = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_v3_promotion_evaluation",
        "release": {
            "release_id": release_id,
            "manifest_sha256": sha256_file(manifest_path),
            "gold_sha256": declared,
        },
        "records": {"path": str(records_path), "sha256": sha256_file(records_path)},
        "evaluation": evaluation.to_dict(),
        "promotion": decision.to_dict(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    print(output)
    return 0 if decision.promotable else 3


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
