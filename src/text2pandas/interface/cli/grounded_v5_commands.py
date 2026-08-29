"""CLI wiring for the scorer-safe grounded V5 pipeline."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from text2pandas.application.usecases.grounded_composer import (
    DeterministicProgramComposer,
    FallbackGroundedGenerator,
    JsonlCachedGroundedGenerator,
)
from text2pandas.application.usecases.grounded_v5 import (
    GroundedV5BuildError,
    GroundedV5Config,
    build_grounded_v5_candidate,
)
from text2pandas.application.usecases.submission import (
    SubmissionConfig,
    build_submission,
    replay_zip,
    validate_zip,
)
from text2pandas.infrastructure.builds import BuildSafetyError
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.llm.ollama import OllamaSemanticProgramGenerator
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander
from text2pandas.infrastructure.semantic.legacy_annotator import (
    LegacyVietnameseAnnotator,
)
from text2pandas.infrastructure.snapshots import (
    ActiveSnapshots,
    verify_active_snapshots,
)
from text2pandas.infrastructure.source_identity import git_source_identity
from text2pandas.pipelines.retrieval.alias_store import load_aliases


def configure_grounded_v5_parser(parser: argparse.ArgumentParser, root: Path) -> None:
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--baseline-zip",
        type=Path,
        default=root
        / "artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/submission.zip",
    )
    parser.add_argument(
        "--secondary-zip",
        type=Path,
        default=root
        / "artifacts/handoffs/submission-v4-hybrid-20260829-r4-final/submission.zip",
    )
    parser.add_argument(
        "--semantic-records",
        type=Path,
        default=root
        / "artifacts/runs/semantic-v4/semantic-v4-full-20260829-r2/records.jsonl",
    )
    parser.add_argument(
        "--promotion-mode",
        choices=["recover_only", "replace_trusted", "replace_all", "shadow"],
        default="recover_only",
    )
    parser.add_argument("--minimum-confidence", type=float, default=0.7)
    parser.add_argument("--fact-limit", type=int, default=100)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--plan-cache",
        type=Path,
        default=root / "artifacts/cache/grounded-v5/qwen3-8b-semantic.jsonl",
        help="Append-only semantic plan cache used to resume long local-model runs",
    )
    parser.add_argument(
        "--deterministic-only",
        action="store_true",
        help="Disable local-model fallback and run only governed deterministic templates",
    )
    parser.add_argument(
        "--question-id",
        type=int,
        action="append",
        default=[],
        help="Restrict V5 inference to selected QIDs while still packaging all 1012 records",
    )


def cmd_grounded_v5(
    args: argparse.Namespace,
    *,
    root: Path,
    paths: ProjectPaths,
    active: ActiveSnapshots,
    questions_path: Path,
    corpus: Path,
    scratch: Path,
    verbose: bool,
) -> int:
    verification = verify_active_snapshots(paths, scope="all")
    failures = [item for item in verification.items if not item.ok]
    if failures:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in failures)
        raise BuildSafetyError(f"active snapshot preflight failed: {detail}")
    stage = paths.run_dir("grounded-v5", str(args.run_id))
    aliases = load_aliases("a6")
    deterministic = DeterministicProgramComposer()
    generator = (
        deterministic
        if args.deterministic_only
        else FallbackGroundedGenerator(
            deterministic,
            JsonlCachedGroundedGenerator(
                OllamaSemanticProgramGenerator(
                    model=str(args.model), endpoint=str(args.ollama_endpoint)
                ),
                Path(args.plan_cache),
                f"semantic-v5:{args.model}",
            ),
        )
    )
    selected = frozenset(int(value) for value in args.question_id)
    config = GroundedV5Config(
        run_id=str(args.run_id),
        promotion_mode=str(args.promotion_mode),  # type: ignore[arg-type]
        minimum_confidence=float(args.minimum_confidence),
        fact_limit=int(args.fact_limit),
        selected_qids=selected or None,
    )

    def progress(index: int, total: int, promoted: int, outcomes: Mapping[str, int]) -> None:
        if verbose and (index == 1 or index % 10 == 0 or index == total):
            rejected = sum(
                count for name, count in outcomes.items() if name.startswith("REJECTED:")
            )
            print(
                f"  ... {index}/{total} câu · promoted={promoted} · rejected={rejected}",
                flush=True,
            )

    try:
        report = build_grounded_v5_candidate(
            baseline_zip=Path(args.baseline_zip),
            secondary_zip=Path(args.secondary_zip) if args.secondary_zip else None,
            questions_path=questions_path,
            a6_db=active.a6_path / "silver.db",
            output_dir=stage,
            generator=generator,
            annotator=LegacyVietnameseAnnotator(aliases),
            config=config,
            semantic_records_path=(
                Path(args.semantic_records) if args.semantic_records else None
            ),
            query_expander=GroundedQueryExpander(load_ontology()),
            progress=progress,
        )
    except GroundedV5BuildError as error:
        raise BuildSafetyError(str(error)) from error
    questions = {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line)
            for line in questions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    package = build_submission(
        report.results,
        questions,
        stage,
        SubmissionConfig(doc_id_variant="stripped", locator_base=1),
    )
    validation = validate_zip(package, questions, corpus_root=corpus)
    replay = replay_zip(package, scratch / f"grounded-v5-{args.run_id}-replay")
    package_ok = (
        validation.ok
        and replay["error"] == 0
        and replay["matched"] == replay["executed"]
    )
    summary = {
        "n_questions": report.n_questions,
        "n_baseline_executable": report.n_baseline_executable,
        "n_seed_executable": report.n_seed_executable,
        "n_attempted": report.n_attempted,
        "n_generated": report.n_generated,
        "n_promoted": report.n_promoted,
        "n_recovered": report.n_recovered,
        "n_replaced": report.n_replaced,
        "n_final_executable": report.n_final_executable,
        "outcomes": report.outcomes,
    }
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.grounded_v5_candidate",
        "run_id": args.run_id,
        "status": "VALIDATED" if package_ok else "BLOCKED",
        "source": git_source_identity(root),
        "model": {
            "id": None if args.deterministic_only else args.model,
            "runtime": "deterministic" if args.deterministic_only else "ollama",
            "closed_answer_generation": False,
            "allowed_output": "observation_uids_and_closed_operation_only",
        },
        "policy": {
            "promotion_mode": args.promotion_mode,
            "minimum_confidence": args.minimum_confidence,
            "fact_limit": args.fact_limit,
            "preserve_baseline_scorer_refs": True,
            "selected_qids": sorted(selected),
            "deterministic_only": bool(args.deterministic_only),
            "plan_cache": str(Path(args.plan_cache).resolve()),
        },
        "inputs": {
            "baseline_zip": {
                "path": str(Path(args.baseline_zip).resolve()),
                "sha256": sha256_file(Path(args.baseline_zip).resolve()),
            },
            "secondary_zip": (
                None
                if not args.secondary_zip
                else {
                    "path": str(Path(args.secondary_zip).resolve()),
                    "sha256": sha256_file(Path(args.secondary_zip).resolve()),
                }
            ),
            "semantic_records": (
                None
                if not args.semantic_records
                else {
                    "path": str(Path(args.semantic_records).resolve()),
                    "sha256": sha256_file(Path(args.semantic_records).resolve()),
                }
            ),
            "a6_build_id": active.a6_build_id,
            "retrieval_index_id": active.retrieval_index_id,
        },
        "summary": summary,
        "package": {
            "path": str(package),
            "sha256": sha256_file(package),
            "bytes": package.stat().st_size,
        },
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
    }
    (stage / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("\n╔═══════════ GROUNDED V5 ═══════════╗")
    for name, value in summary.items():
        if name != "outcomes":
            print(f"  {name:<24} {value}")
    for name, value in report.outcomes.items():
        print(f"    {name:<42} {value:>5}")
    print(f"  validation errors       {len(validation.errors)}")
    print(
        f"  replay                  {replay['matched']}/{replay['executed']} "
        f"matched · {replay['error']} errors"
    )
    print(f"  ZIP                     {package}")
    print(f"  SHA-256                 {manifest['package']['sha256']}")
    if not package_ok:
        for validation_error in validation.errors[:10]:
            print(f"   ✗ {validation_error}")
    return 0 if package_ok else 1
