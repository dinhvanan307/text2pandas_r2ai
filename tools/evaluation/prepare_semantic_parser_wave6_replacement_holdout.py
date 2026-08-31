#!/usr/bin/env python3
"""Prepare an immutable unlabeled replacement holdout after exposure of the old split."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.semantic_parser_holdout import (
    build_replacement_holdout,
)
from text2pandas.application.usecases.semantic_parser_review import (
    semantic_parser_adjudication_templates,
    semantic_parser_annotation_templates,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.source_identity import git_source_identity

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scope-config", type=Path, required=True)
    args = parser.parse_args()

    protocol_path = args.protocol.expanduser().resolve()
    protocol = _json(protocol_path)
    if protocol.get("kind") != "text2pandas.semantic_parser_wave6_replacement_holdout_protocol":
        parser.error("unexpected replacement holdout protocol kind")
    output = args.output.expanduser().resolve()
    scope_config = args.scope_config.expanduser().resolve()
    if output.exists() or scope_config.exists():
        parser.error("replacement holdout outputs are immutable and must not already exist")
    source_identity = git_source_identity(ROOT)
    if source_identity.get("git_dirty") is not False:
        parser.error("holdout preparation requires a clean committed source tree")

    sources = _mapping(protocol.get("sources"), "sources")
    inventory_path = _verified_path(sources, "inventory")
    questions_path = _verified_path(sources, "questions")
    legacy_ledger_path = _verified_path(sources, "legacy_contamination_ledger")
    exposed_review_path = _verified_path(sources, "exposed_user_review")

    inventory = _jsonl(inventory_path)
    questions = {
        _positive_int(row.get("id"), "question id"): str(row.get("question") or "")
        for row in _jsonl(questions_path)
    }
    legacy_ledger = _json(legacy_ledger_path)
    exposed_review = _json(exposed_review_path)
    excluded_qids = {
        _positive_int(row.get("qid"), "ledger qid")
        for row in _objects(legacy_ledger.get("ledger"), "ledger")
    } | {
        _positive_int(row.get("qid"), "review qid")
        for row in _objects(exposed_review.get("records"), "review records")
    }
    quotas = {
        str(family): _positive_int(count, f"family quota:{family}")
        for family, count in _mapping(protocol.get("family_quota"), "family quota").items()
    }
    holdout = build_replacement_holdout(
        inventory,
        questions,
        excluded_qids,
        family_quota=quotas,
        seed=str(protocol.get("seed") or ""),
    )
    expected_records = int(protocol.get("records") or 0)
    if len(holdout.records) != expected_records:
        parser.error(
            f"replacement holdout count mismatch: expected={expected_records} "
            f"actual={len(holdout.records)}"
        )

    scope = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_replacement_holdout_scope",
        "status": "UNLABELED_SEALED_PENDING_CODE_FREEZE",
        "seed": protocol["seed"],
        "records": list(holdout.records),
        "counts": {
            "records": len(holdout.records),
            "family_quota": quotas,
            "eligible_records": holdout.eligible_records,
            "eligible_by_family": holdout.eligible_by_family,
            "excluded_qids": len(excluded_qids),
        },
        "selection": {
            "algorithm": "lowest_sha256(seed\\0family\\0risk_tier\\0qid\\0question_sha256)",
            "prediction_fields_read": False,
            "answer_fields_read": False,
        },
        "review_contract": {
            "minimum_independent_annotators": 2,
            "require_distinct_adjudicator": True,
            "source_evidence_required": True,
            "labels_visible_to_implementer_before_freeze": False,
        },
        "source": {
            "git": source_identity,
            **sources,
        },
    }
    output.mkdir(parents=True)
    scope_config.parent.mkdir(parents=True, exist_ok=True)
    scope_bytes = _pretty_json(scope)
    (output / "scope.json").write_bytes(scope_bytes)
    scope_config.write_bytes(scope_bytes)
    (output / "annotator_a.jsonl").write_bytes(
        canonical_jsonl(semantic_parser_annotation_templates(holdout.records, annotator_slot="A"))
    )
    (output / "annotator_b.jsonl").write_bytes(
        canonical_jsonl(semantic_parser_annotation_templates(holdout.records, annotator_slot="B"))
    )
    (output / "adjudication.jsonl").write_bytes(
        canonical_jsonl(semantic_parser_adjudication_templates(holdout.records))
    )
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_replacement_holdout_manifest",
        "status": "UNLABELED_SEALED_PENDING_CODE_FREEZE",
        "source": source_identity,
        "outputs": {
            path.name: {"sha256": sha256_file(path)}
            for path in sorted(output.iterdir())
            if path.is_file()
        },
        "scope_config": {
            "path": str(scope_config.relative_to(ROOT)),
            "sha256": sha256_file(scope_config),
        },
    }
    (output / "manifest.json").write_bytes(_pretty_json(manifest))
    print(json.dumps(scope["counts"], ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


def _verified_path(sources: dict[str, Any], key: str) -> Path:
    contract = _mapping(sources.get(key), key)
    path = ROOT / str(contract.get("path") or "")
    if not path.is_file():
        raise FileNotFoundError(f"missing source {key}: {path}")
    if sha256_file(path) != contract.get("sha256"):
        raise ValueError(f"source checksum mismatch: {key}")
    return path


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def _objects(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise TypeError(f"{label} must be a list of objects")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TypeError(f"{label} must be a positive integer")
    return value


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(payload, str(path))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        _mapping(json.loads(line), f"{path}:{line_number}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if line.strip()
    ]


def _pretty_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(main())
