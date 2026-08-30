"""Prepare the immutable prediction-blind Risk-A60 review packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.risk_a_review import (
    DEFAULT_FAMILY_SPLIT,
    REQUIRED_OBSERVATION_FIELDS,
    build_risk_a_review_scope,
    risk_a_adjudication_templates,
    risk_a_annotation_templates,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.source_identity import git_source_identity

ROOT = Path(__file__).resolve().parents[2]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope-config", type=Path, required=True)
    parser.add_argument("--seed", default="text2pandas-wave5-riska60-v1")
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    scope_config = args.scope_config.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    if scope_config.exists():
        parser.error(f"immutable scope config already exists: {scope_config}")
    source = git_source_identity(ROOT)
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        parser.error("review preparation requires a clean committed source tree")

    inventory_path = args.inventory.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    baseline_path = args.baseline.expanduser().resolve()
    questions = {
        int(row["id"]): str(row["question"])
        for row in _jsonl(questions_path)
    }
    scope = build_risk_a_review_scope(
        _jsonl(inventory_path), questions, seed=args.seed
    )
    scope_payload = {
        "schema_version": 1,
        "kind": "text2pandas.recovery_wave5_riska60_scope",
        "seed": args.seed,
        "records": list(scope.records),
        "counts": {
            "records": len(scope.records),
            "families": scope.family_counts,
            "splits": scope.split_counts,
        },
        "family_split": {
            family: {"development": counts[0], "holdout": counts[1]}
            for family, counts in DEFAULT_FAMILY_SPLIT.items()
        },
        "review_contract": {
            "minimum_independent_annotators": 2,
            "require_distinct_adjudicator": True,
            "blind_model_outputs": True,
            "required_observation_fields": list(REQUIRED_OBSERVATION_FIELDS),
            "holdout_access": "SEALED_UNTIL_CODE_AND_CONFIG_FREEZE",
        },
        "source": {
            **source,
            "baseline": {"path": str(baseline_path), "sha256": sha256_file(baseline_path)},
            "inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
            "questions": {"path": str(questions_path), "sha256": sha256_file(questions_path)},
        },
    }
    output.mkdir(parents=True)
    scope_path = output / "scope.json"
    reviewer_a_path = output / "reviewer_a.jsonl"
    reviewer_b_path = output / "reviewer_b.jsonl"
    adjudication_path = output / "adjudication.jsonl"
    scope_bytes = (
        json.dumps(scope_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    scope_path.write_bytes(scope_bytes)
    scope_config.parent.mkdir(parents=True, exist_ok=True)
    scope_config.write_bytes(scope_bytes)
    reviewer_a_path.write_bytes(risk_a_packet(scope.records, "A"))
    reviewer_b_path.write_bytes(risk_a_packet(scope.records, "B"))
    adjudication_path.write_bytes(
        canonical_jsonl(risk_a_adjudication_templates(scope.records))
    )
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.recovery_wave5_riska60_review_packet",
        "records": len(scope.records),
        "source": scope_payload["source"],
        "outputs": {
            path.name: {"sha256": sha256_file(path)}
            for path in (scope_path, reviewer_a_path, reviewer_b_path, adjudication_path)
        },
        "scope_config": {
            "path": str(scope_config),
            "sha256": sha256_file(scope_config),
        },
        "status": "AWAITING_INDEPENDENT_REVIEW",
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(scope_payload["counts"], ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


def risk_a_packet(records: tuple[dict[str, object], ...], slot: str) -> bytes:
    return canonical_jsonl(risk_a_annotation_templates(records, reviewer_slot=slot))


if __name__ == "__main__":
    raise SystemExit(main())
