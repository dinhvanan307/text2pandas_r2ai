#!/usr/bin/env python3
"""Prepare the immutable prediction-blind Semantic Parser Wave 6 review packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.semantic_parser_review import (
    COMPOSITION_FRAME_FIELDS,
    FORBIDDEN_MODEL_FIELDS,
    audit_semantic_parser_review_packet,
    semantic_parser_adjudication_templates,
    semantic_parser_annotation_templates,
)
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.source_identity import git_source_identity

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope-config", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = git_source_identity(ROOT)
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        parser.error("review preparation requires a clean committed source tree")
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    scope_path = args.scope_config.expanduser().resolve()
    protocol_path = args.protocol.expanduser().resolve()
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    records = scope.get("records")
    if not isinstance(records, list):
        parser.error("scope records must be a list")
    _validate_scope(records, scope)
    _validate_protocol(protocol, scope_path)

    reviewer_a = semantic_parser_annotation_templates(records, annotator_slot="A")
    reviewer_b = semantic_parser_annotation_templates(records, annotator_slot="B")
    adjudication = semantic_parser_adjudication_templates(records)
    audit = audit_semantic_parser_review_packet(records, reviewer_a, reviewer_b, adjudication)

    output.mkdir(parents=True)
    outputs = {
        "scope.json": (
            json.dumps(scope, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "protocol.json": (
            json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
        "annotator_a.jsonl": canonical_jsonl(reviewer_a),
        "annotator_b.jsonl": canonical_jsonl(reviewer_b),
        "adjudication.jsonl": canonical_jsonl(adjudication),
        "audit.json": (
            json.dumps(audit.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
    }
    for name, payload in outputs.items():
        (output / name).write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_review_packet",
        "status": audit.to_dict()["status"],
        "prediction_blind": True,
        "records": len(records),
        "splits": scope["counts"]["splits"],
        "source": {
            **source,
            "scope_config": {"path": str(scope_path), "sha256": sha256_file(scope_path)},
            "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
        },
        "contract": {
            "composition_frame_fields": list(COMPOSITION_FRAME_FIELDS),
            "forbidden_model_fields": sorted(FORBIDDEN_MODEL_FIELDS),
            "minimum_independent_annotators": 2,
            "require_distinct_adjudicator": True,
        },
        "completion": audit.to_dict()["completion"],
        "blockers": list(audit.blockers),
        "outputs": {name: {"sha256": sha256_file(output / name)} for name in sorted(outputs)},
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


def _validate_scope(records: list[object], scope: dict[str, object]) -> None:
    if len(records) != 60:
        raise ValueError(f"semantic parser review scope must contain 60 records: {len(records)}")
    if not all(isinstance(row, dict) for row in records):
        raise TypeError("semantic parser review scope rows must be objects")
    qids = [int(str(row["qid"])) for row in records if isinstance(row, dict)]
    if len(set(qids)) != 60:
        raise ValueError("semantic parser review scope must contain 60 unique QIDs")
    splits = scope.get("counts")
    if not isinstance(splits, dict) or splits.get("splits") != {
        "development": 40,
        "holdout": 20,
    }:
        raise ValueError("semantic parser review scope must preserve the sealed 40/20 split")


def _validate_protocol(protocol: dict[str, object], scope_path: Path) -> None:
    if protocol.get("prediction_blind") is not True:
        raise ValueError("semantic parser review protocol must be prediction-blind")
    if protocol.get("scope_config") != str(scope_path.relative_to(ROOT)):
        raise ValueError("semantic parser review protocol scope path mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
