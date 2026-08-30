"""CLI commands for immutable Semantic V4 shadow and candidate artifacts."""

from __future__ import annotations

import csv
import json
import os
import platform
import resource
import shutil
import sqlite3
import time
from argparse import Namespace
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from text2pandas.infrastructure.builds import BuildSafetyError, publish_new_file
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots

ROOT = Path(__file__).resolve().parents[4]
PROJECT_PATHS = ProjectPaths.from_repo_root(ROOT)
ACTIVE_SNAPSHOTS = ActiveSnapshots.load(PROJECT_PATHS)
QUESTIONS = PROJECT_PATHS.raw_btc / "questions/questions.jsonl"
CORPUS = PROJECT_PATHS.raw_btc / "financial_statements"
SUBMIT_DIR = PROJECT_PATHS.artifact_root / "submissions"
SCRATCH = Path(os.environ.get("TEXT2PANDAS_SCRATCH", "/tmp/text2pandas_work"))


def cmd_shadow_v4(args: Namespace) -> int:
    from text2pandas.application.parsing import SemanticParser
    from text2pandas.application.retrieval import HierarchicalOperandRetriever
    from text2pandas.application.usecases.run_manifest import write_manifest
    from text2pandas.application.usecases.semantic_v3_readiness import (
        PromotionMetrics,
        evaluate_promotion,
    )
    from text2pandas.application.usecases.semantic_v4 import (
        CONFIDENCE_STATUS,
        SEMANTIC_V4_VERSION,
        SemanticV4Engine,
    )
    from text2pandas.application.verification import ProgramVerifier
    from text2pandas.infrastructure.checksums import sha256_file
    from text2pandas.infrastructure.execution import PandasSandboxReplay
    from text2pandas.infrastructure.ontology import load_ontology
    from text2pandas.infrastructure.retrieval import (
        FACT_RETRIEVAL_POLICY_VERSION,
        SqliteOperandRetriever,
    )
    from text2pandas.infrastructure.semantic import (
        A6MetricMentionResolver,
        LegacyVietnameseAnnotator,
        load_promotion_policy,
        load_semantic_v4_policy,
    )
    from text2pandas.infrastructure.snapshots import verify_active_snapshots
    from text2pandas.infrastructure.source_identity import git_source_identity
    from text2pandas.pipelines.retrieval.alias_store import load_aliases

    policy = load_semantic_v4_policy(args.policy)
    verification_scope = "all" if args.canonical_table_priors else "a6"
    verification = verify_active_snapshots(PROJECT_PATHS, scope=verification_scope)
    if not verification.ok:
        detail = "; ".join(item.detail for item in verification.items if not item.ok)
        raise BuildSafetyError(f"active snapshot preflight failed: {detail}")
    stage = PROJECT_PATHS.run_dir("semantic-v4", args.run_id)
    try:
        stage.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable semantic-v4 run already exists: {stage}") from error
    records_path = stage / "records.jsonl"
    questions = _load_questions()[args.offset :]
    if args.limit:
        questions = questions[: args.limit]
    legacy = _load_optional_legacy(args.legacy_run_id)
    ontology = load_ontology()
    aliases = load_aliases("a6")
    connection = sqlite3.connect(
        f"file:{(ACTIVE_SNAPSHOTS.a6_path / 'silver.db').resolve()}?mode=ro&immutable=1",
        uri=True,
    )
    retrieval_connection: sqlite3.Connection | None = None
    table_retriever = None
    if args.canonical_table_priors:
        from text2pandas.pipelines.retrieval.submission_adapter import RetrievalToSubmission

        retrieval_connection = sqlite3.connect(
            f"file:{(ACTIVE_SNAPSHOTS.retrieval_path / 'retrieval.db').resolve()}"
            "?mode=ro&immutable=1",
            uri=True,
        )
        table_retriever = RetrievalToSubmission(aliases, top_k_rank=50, top_k_rerank=50)
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id=ACTIVE_SNAPSHOTS.a6_build_id,
        entity_aliases=aliases,
    )
    parser = SemanticParser(
        ontology,
        LegacyVietnameseAnnotator(aliases),
        resolver,
    )
    physical_retriever = SqliteOperandRetriever(
        connection,
        ontology,
        top_k=policy.operand_pool_k,
        source_build_id=ACTIVE_SNAPSHOTS.a6_build_id,
        include_recoverable_collisions=policy.include_recoverable_collisions,
    )
    retriever = HierarchicalOperandRetriever(physical_retriever, policy.hierarchy)
    engine = SemanticV4Engine(
        parser,
        retriever,
        PandasSandboxReplay(),
        verifier=ProgramVerifier(policy.verification),
        config=policy.engine,
    )
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    differentials: Counter[str] = Counter()
    evidence_values: dict[str, dict[str, object]] = {}
    confidence_values: list[float] = []
    replay_mismatches = 0
    started = time.time()
    try:
        with records_path.open("x", encoding="utf-8") as handle:
            for index, item in enumerate(questions, 1):
                qid = int(str(item["id"]))
                question = str(item["question"])
                if table_retriever is not None and retrieval_connection is not None:
                    upstream = table_retriever.refs_for(
                        retrieval_connection,
                        qid,
                        question,
                    )
                    physical_retriever.set_table_rank_priors(tuple(upstream.ranked_table_uids))
                else:
                    physical_retriever.set_table_rank_priors(())
                result = engine.answer(question, qid=qid)
                statuses[result.status] += 1
                reasons[result.reason or "OK"] += 1
                if result.confidence is not None:
                    confidence_values.append(result.confidence)
                replay_mismatches += sum(
                    count
                    for failure, count in result.failure_counts.items()
                    if "TYPED_PANDAS_MISMATCH" in failure
                )
                differential = _classify_differential(legacy.get(qid), result.to_dict())
                differentials[differential] += 1
                record = {
                    "question": question,
                    **result.to_dict(),
                    "differential": differential,
                }
                _bind_evidence_csv_paths(record, connection, stage, evidence_values)
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                if args.verbose and index % 25 == 0:
                    print(
                        f"  ... {index:,} câu · {statuses['OK']:,} V4 OK",
                        flush=True,
                    )
        _write_evidence_csvs(stage, evidence_values)
    finally:
        connection.close()
        if retrieval_connection is not None:
            retrieval_connection.close()
    seconds = round(time.time() - started, 3)
    peak_rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = int(peak_rss_raw if platform.system() == "Darwin" else peak_rss_raw * 1024)
    promotion = evaluate_promotion(
        PromotionMetrics(
            questions=len(questions),
            replay_mismatches=replay_mismatches,
        ),
        load_promotion_policy(),
    )
    manifest_path = stage / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "schema_version": "4.0",
            "kind": "text2pandas.semantic_v4_shadow_run",
            "run_id": args.run_id,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "source": git_source_identity(ROOT),
            "a6": {
                "build_id": ACTIVE_SNAPSHOTS.a6_build_id,
                "path": str(ACTIVE_SNAPSHOTS.a6_path.relative_to(ROOT)),
            },
            "semantic_schema_version": 4,
            "semantic_engine_version": SEMANTIC_V4_VERSION,
            "confidence_status": CONFIDENCE_STATUS,
            "ontology_fingerprint": ontology.fingerprint,
            "physical_retrieval_policy": FACT_RETRIEVAL_POLICY_VERSION,
            "runtime_policy": {
                "policy_id": policy.policy_id,
                "status": policy.status,
                "production_eligible": policy.production_eligible,
                "path": str(policy.config_path.relative_to(ROOT)),
                "sha256": policy.config_sha256,
            },
            "metric_resolution": resolver.metadata,
            "parameters": {
                "offset": args.offset,
                "limit": args.limit,
                "legacy_run_id": args.legacy_run_id,
                "canonical_table_priors": args.canonical_table_priors,
                "operand_pool_k": policy.operand_pool_k,
                "hierarchical_top_k": policy.hierarchy.top_k,
                "max_parse_candidates": policy.engine.max_parse_candidates,
                "max_binding_candidates": policy.engine.max_binding_candidates,
                "include_recoverable_collisions": policy.include_recoverable_collisions,
            },
            "metrics": {
                "questions": len(questions),
                "statuses": dict(statuses),
                "reasons": dict(reasons.most_common()),
                "differentials": dict(differentials),
                "confidence_mean": (
                    sum(confidence_values) / len(confidence_values) if confidence_values else None
                ),
                "replay_mismatches": replay_mismatches,
                "seconds": seconds,
                "peak_rss_bytes": peak_rss_bytes,
            },
            "promotion": promotion.to_dict(),
            "outputs": {
                "records_jsonl": {
                    "path": str(records_path.relative_to(ROOT)),
                    "sha256": sha256_file(records_path),
                    "records": len(questions),
                },
                "evidence_csvs": [
                    {
                        "path": str(path.relative_to(ROOT)),
                        "sha256": sha256_file(path),
                        "table_uid": path.stem,
                    }
                    for path in sorted((stage / "data").glob("*.csv"))
                ],
            },
        },
    )
    print("\n╔═══════════ SEMANTIC V4 SHADOW ═══════════╗")
    print(f"  câu hỏi          : {len(questions):,}")
    print(f"  V4 OK            : {statuses['OK']:,}")
    print(f"  V4 abstain       : {statuses['ABSTAIN']:,}")
    print(f"  replay mismatch  : {replay_mismatches:,}")
    print(f"  thời gian        : {seconds}s")
    print(f"  promotion        : {promotion.status}")
    for reason, count in reasons.most_common(8):
        print(f"    {reason:<52} {count:>5}")
    print(f"  records          : {records_path}")
    print(f"  manifest         : {manifest_path}")
    return 0


def cmd_package_v4(args: Namespace) -> int:
    from text2pandas.application.usecases.answer import AnswerResult
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        publication_blockers,
        replay_zip,
        validate_zip,
    )
    from text2pandas.infrastructure.checksums import sha256_file

    stage = PROJECT_PATHS.run_dir("semantic-v4", args.run_id)
    records_path = stage / "records.jsonl"
    if not records_path.is_file():
        raise BuildSafetyError(f"missing Semantic V4 records: {records_path}")
    locators = _table_locators()
    results: list[AnswerResult] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        evidence = [
            {
                "variable": str(item["variable"]),
                "csv_path": f"data/{Path(str(item['csv_path'])).name}",
            }
            for item in record.get("evidence") or []
        ]
        table_uids = [str(value) for value in record.get("relevant_tables") or []]
        try:
            tables = [locators[value] for value in table_uids]
        except KeyError as error:
            raise BuildSafetyError(f"A6 table locator missing: {error.args[0]}") from error
        answer = _numeric_answer(record.get("answer"))
        results.append(
            AnswerResult(
                qid=int(record["qid"]),
                answer=answer,
                relevant_docs=list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables)),
                relevant_tables=tables,
                evidence=evidence if answer is not None else [],
                pandas_query=str(record.get("pandas_query") or "") if answer is not None else "",
                confidence=float(record.get("confidence") or 0.0),
                csv_name=Path(evidence[0]["csv_path"]).name
                if evidence and answer is not None
                else "",
                has_csv=bool(evidence and answer is not None),
                notes=[str(record["reason"])] if record.get("reason") else [],
            )
        )
    questions = {int(str(row["id"])): str(row["question"]) for row in _load_questions()}
    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    output = stage / f"package-{cfg.doc_id_variant}-{cfg.locator_base}"
    try:
        output.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable V4 package already exists: {output}") from error
    (output / "data").mkdir()
    for source in sorted((stage / "data").glob("*.csv")):
        shutil.copy2(source, output / "data" / source.name)
    zip_path = build_submission(results, questions, output, cfg)
    validation = validate_zip(zip_path, questions, corpus_root=CORPUS)
    replay = replay_zip(zip_path, SCRATCH / f"v4-replay-{args.run_id}")
    replay_mismatches = replay["executed"] - replay["matched"]
    release_blockers = publication_blockers(validation, replay, expected_records=len(questions))
    report = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_v4_submission_validation",
        "run_id": args.run_id,
        "zip": {"path": str(zip_path.relative_to(ROOT)), "sha256": sha256_file(zip_path)},
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
        "replay_mismatches": replay_mismatches,
        "publication_blockers": release_blockers,
    }
    report_path = stage / f"package-{cfg.doc_id_variant}-{cfg.locator_base}.report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("\n╔═══════════ SEMANTIC V4 SUBMISSION ═══════════╗")
    print(f"  records           : {validation.n_records:,} / {len(questions):,}")
    print(f"  validation errors : {len(validation.errors):,}")
    print(
        f"  replay            : {replay['executed']:,} executed · "
        f"{replay['matched']:,} matched · {replay['error']:,} errors · "
        f"{replay_mismatches:,} mismatches"
    )
    print(f"  zip               : {zip_path}")
    print(f"  report            : {report_path}")
    return int(bool(release_blockers))


def cmd_hybrid_v4(args: Namespace) -> int:
    from text2pandas.application.usecases.hybrid_v3 import (
        HybridBuildError,
        build_hybrid_candidate,
        hybrid_publication_eligibility,
        table_locator_map,
        validate_source_manifest,
    )
    from text2pandas.application.usecases.run_manifest import write_manifest
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        publication_blockers,
        replay_zip,
        validate_zip,
    )
    from text2pandas.infrastructure.checksums import sha256_file
    from text2pandas.infrastructure.semantic import load_hybrid_policy
    from text2pandas.infrastructure.snapshots import verify_active_snapshots
    from text2pandas.infrastructure.source_identity import git_source_identity

    verification = verify_active_snapshots(PROJECT_PATHS, scope="all")
    if failures := [item for item in verification.items if not item.ok]:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in failures)
        raise BuildSafetyError(f"active snapshot preflight failed: {detail}")
    legacy_stage = PROJECT_PATHS.run_dir("answer", args.legacy_run_id)
    semantic_stage = PROJECT_PATHS.run_dir("semantic-v4", args.semantic_run_id)
    policy_path = Path(args.policy).expanduser().resolve()
    if not policy_path.is_file():
        raise BuildSafetyError(f"missing hybrid policy: {policy_path}")
    policy = load_hybrid_policy(policy_path)
    legacy_manifest_path = legacy_stage / "manifest.json"
    semantic_manifest_path = semantic_stage / "manifest.json"
    if not legacy_manifest_path.is_file() or not semantic_manifest_path.is_file():
        raise BuildSafetyError("hybrid source manifest is missing")
    legacy_manifest = json.loads(legacy_manifest_path.read_text(encoding="utf-8"))
    semantic_manifest = json.loads(semantic_manifest_path.read_text(encoding="utf-8"))
    legacy_records_sha256 = sha256_file(legacy_stage / "records.jsonl")
    semantic_records_sha256 = sha256_file(semantic_stage / "records.jsonl")
    try:
        validate_source_manifest(
            legacy_manifest,
            expected_run_id=args.legacy_run_id,
            records_sha256=legacy_records_sha256,
            source_label="legacy",
        )
        validate_source_manifest(
            semantic_manifest,
            expected_run_id=args.semantic_run_id,
            records_sha256=semantic_records_sha256,
            source_label="semantic_v4",
        )
    except HybridBuildError as error:
        raise BuildSafetyError(str(error)) from error
    semantic_promotion = semantic_manifest.get("promotion")
    semantic_promotion_status = (
        str(semantic_promotion.get("status"))
        if isinstance(semantic_promotion, dict) and semantic_promotion.get("status")
        else None
    )
    publication_eligible, policy_publication_blockers = hybrid_publication_eligibility(
        policy,
        semantic_promotion_status,
    )
    stage = PROJECT_PATHS.run_dir("answer", args.run_id)
    table_cards = ACTIVE_SNAPSHOTS.a6_path / "dataframe/csv/table_cards.csv"
    try:
        report = build_hybrid_candidate(
            legacy_records_path=legacy_stage / "records.jsonl",
            semantic_records_path=semantic_stage / "records.jsonl",
            legacy_data_dir=legacy_stage / "data",
            semantic_data_dir=semantic_stage / "data",
            output_dir=stage,
            policy=policy,
            table_locators=table_locator_map(table_cards),
            semantic_label="semantic_v4",
            evidence_prefix="v4",
        )
    except HybridBuildError as error:
        raise BuildSafetyError(str(error)) from error
    questions = {int(str(row["id"])): str(row["question"]) for row in _load_questions()}
    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    zip_path = build_submission(report.results, questions, stage, cfg)
    validation = validate_zip(zip_path, questions, corpus_root=CORPUS)
    replay = replay_zip(zip_path, SCRATCH / f"hybrid-v4-replay-{args.run_id}")
    replay_mismatches = replay["executed"] - replay["matched"]
    release_blockers = publication_blockers(validation, replay, expected_records=len(questions))
    package_ok = not release_blockers
    published = None
    if package_ok and publication_eligible:
        published = SUBMIT_DIR / f"submission_{args.run_id}.zip"
        publish_new_file(zip_path, published)
    manifest_path = stage / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "schema_version": "1.0",
            "kind": "text2pandas.semantic_v4_hybrid_candidate",
            "run_id": args.run_id,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "source": git_source_identity(ROOT),
            "inputs": {
                "legacy_run_id": args.legacy_run_id,
                "legacy_records_sha256": legacy_records_sha256,
                "legacy_manifest_sha256": sha256_file(legacy_manifest_path),
                "semantic_run_id": args.semantic_run_id,
                "semantic_records_sha256": semantic_records_sha256,
                "semantic_manifest_sha256": sha256_file(semantic_manifest_path),
                "policy": str(policy_path.relative_to(ROOT)),
                "policy_sha256": sha256_file(policy_path),
            },
            "policy": {
                "policy_id": policy.policy_id,
                "status": policy.status,
                "production_eligible": policy.production_eligible,
                "semantic_promotion_status": semantic_promotion_status,
                "publication_eligible": publication_eligible,
                "publication_blockers": list(policy_publication_blockers),
                "relevant_refs_mode": policy.relevant_refs_mode,
                "maximum_relevant_tables": policy.maximum_relevant_tables,
            },
            "metrics": {
                "questions": report.n_questions,
                "promoted": report.n_promoted,
                "recovered": report.n_recovered,
                "value_changed": report.n_value_changed,
                "decisions": report.decisions,
                "promoted_routes": report.promoted_routes,
            },
            "validation": {
                "records": validation.n_records,
                "errors": validation.errors,
                "warnings": validation.warnings,
            },
            "replay": replay,
            "replay_mismatches": replay_mismatches,
            "publication_blockers": release_blockers,
            "package": {
                "path": str(zip_path.relative_to(ROOT)),
                "sha256": sha256_file(zip_path),
                "published": None if published is None else str(published.relative_to(ROOT)),
            },
            "outputs": {
                "records_jsonl": {
                    "path": str(report.records_path.relative_to(ROOT)),
                    "sha256": sha256_file(report.records_path),
                    "records": report.n_questions,
                },
                "per_qid_attribution": str(report.attribution_path.relative_to(ROOT)),
            },
        },
    )
    print("\n╔═══════════ SEMANTIC V4 HYBRID ═══════════╗")
    print(f"  policy             : {policy.policy_id} ({policy.status})")
    print(f"  questions          : {report.n_questions:,}")
    print(f"  promoted V4        : {report.n_promoted:,}")
    print(f"  recovered abstain  : {report.n_recovered:,}")
    print(f"  changed values     : {report.n_value_changed:,}")
    print(f"  validation errors  : {len(validation.errors):,}")
    print(
        f"  replay             : {replay['executed']:,} executed · "
        f"{replay['matched']:,} matched · {replay['error']:,} errors"
    )
    print(f"  zip                : {zip_path}")
    if not publication_eligible:
        print(f"  publish            : BLOCKED — {', '.join(policy_publication_blockers)}")
    elif published:
        print(f"  publish            : {published}")
    return 0 if package_ok else 1


def _load_questions() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_optional_legacy(run_id: str | None) -> dict[int, dict[str, object]]:
    if not run_id:
        return {}
    path = PROJECT_PATHS.run_dir("answer", run_id) / "records.jsonl"
    if not path.is_file():
        raise BuildSafetyError(f"missing legacy records: {path}")
    return {
        int(record["qid"]): record
        for record in (
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        )
    }


def _classify_differential(
    legacy: dict[str, object] | None,
    semantic: dict[str, object],
) -> str:
    if legacy is None:
        return "V4_ONLY_MEASUREMENT"
    legacy_answer = _numeric_answer(legacy.get("answer"))
    semantic_answer = _numeric_answer(semantic.get("answer"))
    if legacy_answer is not None and semantic_answer is not None:
        matched = abs(legacy_answer - semantic_answer) <= 1e-9 * max(
            1.0,
            abs(legacy_answer),
        )
        return "BOTH_OK_MATCH" if matched else "BOTH_OK_VALUE_DIFFERENCE"
    if legacy_answer is not None:
        return "LEGACY_ONLY_OK"
    if semantic_answer is not None:
        return "V4_ONLY_OK"
    return "BOTH_ABSTAIN"


def _bind_evidence_csv_paths(
    record: dict[str, object],
    connection: sqlite3.Connection,
    stage: Path,
    evidence_values: dict[str, dict[str, object]],
) -> None:
    raw_evidence = record.get("evidence")
    if not isinstance(raw_evidence, list):
        return
    for raw in raw_evidence:
        if not isinstance(raw, dict):
            raise BuildSafetyError("Semantic V4 evidence item must be an object")
        table_uid = str(raw["table_uid"])
        uids = [str(value) for value in raw["observation_uids"]]
        placeholders = ",".join("?" for _ in uids)
        rows = connection.execute(
            f"SELECT observation_uid, value_decimal_text FROM observations "
            f"WHERE observation_uid IN ({placeholders})",
            uids,
        ).fetchall()
        if len(rows) != len(set(uids)):
            raise BuildSafetyError(f"A6 evidence observations missing: {table_uid}:{uids}")
        values = evidence_values.setdefault(table_uid, {})
        for observation_uid, value in rows:
            previous = values.setdefault(str(observation_uid), value)
            if previous != value:
                raise BuildSafetyError(f"A6 evidence value drift: {observation_uid}")
        raw["csv_path"] = str((stage / "data" / f"{table_uid}.csv").relative_to(ROOT))


def _write_evidence_csvs(
    stage: Path,
    evidence_values: dict[str, dict[str, object]],
) -> None:
    evidence_dir = stage / "data"
    evidence_dir.mkdir()
    for table_uid, values in sorted(evidence_values.items()):
        with (evidence_dir / f"{table_uid}.csv").open(
            "x",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(("observation_uid", "value"))
            writer.writerows(sorted(values.items()))


def _table_locators() -> dict[str, str]:
    table_cards = ACTIVE_SNAPSHOTS.a6_path / "dataframe/csv/table_cards.csv"
    with table_cards.open(encoding="utf-8", newline="") as handle:
        return {
            str(row["table_uid"]): str(row["evidence_ref"]).replace("|line:", "|")
            for row in csv.DictReader(handle)
        }


def _numeric_answer(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return float(decimal) if decimal.is_finite() else None
