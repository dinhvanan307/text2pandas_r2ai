#!/usr/bin/env python3
"""Run an immutable parser-only baseline over the active question corpus."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import time

from text2pandas.application.parsing import SemanticParser
from text2pandas.application.usecases.run_manifest import write_manifest
from text2pandas.application.usecases.semantic_parser_baseline import (
    build_semantic_parser_record,
    summarize_semantic_parser_records,
)
from text2pandas.infrastructure.builds import BuildSafetyError
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.semantic import (
    A6MetricMentionResolver,
    LegacyVietnameseAnnotator,
)
from text2pandas.infrastructure.snapshots import ActiveSnapshots, verify_active_snapshots
from text2pandas.infrastructure.source_identity import git_source_identity
from text2pandas.pipelines.retrieval.alias_store import load_aliases


ROOT = Path(__file__).resolve().parents[2]
PATHS = ProjectPaths.from_repo_root(ROOT)
ACTIVE = ActiveSnapshots.load(PATHS)
QUESTIONS = PATHS.raw_btc / "questions/questions.jsonl"


def main() -> int:
    parser_args = argparse.ArgumentParser()
    parser_args.add_argument("--run-id", required=True)
    parser_args.add_argument("--max-candidates", type=int, default=8)
    args = parser_args.parse_args()
    if args.max_candidates < 1:
        raise ValueError("max-candidates must be positive")

    verification = verify_active_snapshots(PATHS, scope="a6")
    if not verification.ok:
        detail = "; ".join(item.detail for item in verification.items if not item.ok)
        raise BuildSafetyError(f"active snapshot preflight failed: {detail}")
    stage = PATHS.run_dir("semantic-parser", args.run_id)
    try:
        stage.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable semantic-parser run exists: {stage}") from error

    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(questions) != 1012:
        raise ValueError(f"active corpus must contain 1012 questions: {len(questions)}")
    ontology = load_ontology()
    aliases = load_aliases("a6")
    connection = sqlite3.connect(
        f"file:{(ACTIVE.a6_path / 'silver.db').resolve()}?mode=ro&immutable=1",
        uri=True,
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id=ACTIVE.a6_build_id,
        entity_aliases=aliases,
    )
    semantic_parser = SemanticParser(
        ontology,
        LegacyVietnameseAnnotator(aliases),
        resolver,
    )
    records_path = stage / "records.jsonl"
    records: list[dict[str, object]] = []
    started = time.time()
    try:
        with records_path.open("x", encoding="utf-8") as handle:
            for item in questions:
                record = build_semantic_parser_record(
                    semantic_parser,
                    str(item["question"]),
                    qid=int(str(item["id"])),
                    max_candidates=args.max_candidates,
                )
                records.append(record)
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    finally:
        connection.close()
    seconds = round(time.time() - started, 3)
    summary = summarize_semantic_parser_records(records)
    source = git_source_identity(ROOT)
    manifest_path = stage / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "schema_version": 1,
            "kind": "text2pandas.semantic_parser_baseline",
            "measurement_scope": "PREDICTED_STRUCTURE_ONLY_NOT_GOLD",
            "run_id": args.run_id,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "source": source,
            "inputs": {
                "questions": {
                    "path": str(QUESTIONS.relative_to(ROOT)),
                    "sha256": sha256_file(QUESTIONS),
                    "records": len(questions),
                },
                "a6": {
                    "build_id": ACTIVE.a6_build_id,
                    "path": str(ACTIVE.a6_path.relative_to(ROOT)),
                },
                "ontology_fingerprint": ontology.fingerprint,
                "resolver": resolver.metadata,
            },
            "parameters": {"max_candidates": args.max_candidates},
            "metrics": {**summary, "seconds": seconds},
            "outputs": {
                "records_jsonl": {
                    "path": str(records_path.relative_to(ROOT)),
                    "sha256": sha256_file(records_path),
                    "records": len(records),
                }
            },
        },
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"records={records_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
