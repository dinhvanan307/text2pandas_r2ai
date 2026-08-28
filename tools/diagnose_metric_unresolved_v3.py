"""Seal the clean Semantic V3 baseline and diagnose METRIC_UNRESOLVED.

This is a read-only audit tool.  It never mutates A6 and production code never
imports it.  The source-label matches are evidence candidates, not gold.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import sqlite3
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from text2pandas.domain.metrics import normalize_phrase
from text2pandas.infrastructure.semantic import LegacyVietnameseAnnotator
from text2pandas.pipelines.answering.frame import classify_operation
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.query_terms import content_terms
from text2pandas.pipelines.retrieval.question_intent import parse_intent

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = (
    ROOT / "artifacts/runs/semantic-v3/metric-unresolved-b0-clean-20260828/records.jsonl"
)
DEFAULT_MANIFEST = DEFAULT_RECORDS.with_name("manifest.json")
DEFAULT_A6 = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"
DEFAULT_EVAL = (
    ROOT / "artifacts/runs/retrieval/evalkit/ek_retrieval_recovery_v11_064d5c72466be010.jsonl"
)
DEFAULT_QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
DEFAULT_OUTPUT = DEFAULT_RECORDS.parent / "baseline"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _longest_common_run(left: list[str], right: list[str]) -> tuple[int, str]:
    best_length = 0
    best_surface = ""
    for left_index in range(len(left)):
        for right_index in range(len(right)):
            length = 0
            while (
                left_index + length < len(left)
                and right_index + length < len(right)
                and left[left_index + length] == right[right_index + length]
            ):
                length += 1
            surface = " ".join(left[left_index : left_index + length])
            if (length, surface) > (best_length, best_surface):
                best_length = length
                best_surface = surface
    return best_length, best_surface


def _source_hypotheses(
    connection: sqlite3.Connection,
    question: str,
    annotation: object,
    aliases: dict[str, list[str]],
) -> tuple[list[str], list[dict[str, object]]]:
    entities = tuple(str(value) for value in annotation.entities)
    periods = tuple(str(value) for value in annotation.periods)
    drop = tuple(value for entity in entities for value in aliases.get(entity, ())) + entities
    question_terms = [
        normalize_phrase(value) for value in content_terms(question, drop=drop, stop_mode="dau")
    ]
    clauses = [
        "r.execution_ready = 1",
        "o.value_decimal_text IS NOT NULL",
        "o.metric_label_clean IS NOT NULL",
    ]
    parameters: list[object] = []
    if entities:
        clauses.append(f"o.ticker IN ({','.join('?' for _ in entities)})")
        parameters.extend(entities)
    if periods:
        clauses.append(f"substr(o.period_end, 1, 4) IN ({','.join('?' for _ in periods)})")
        parameters.extend(periods)
    if annotation.basis.value != "unspecified":
        clauses.append("d.basis = ?")
        parameters.append(annotation.basis.value)
    rows = connection.execute(
        f"""
        SELECT o.metric_label_clean, o.row_path_text, o.metric_code,
               o.unit_kind, o.statement_type, d.basis, COUNT(*)
        FROM observations o
        JOIN observation_readiness r USING(observation_uid)
        JOIN tables t USING(table_uid)
        JOIN documents d USING(document_uid)
        WHERE {" AND ".join(clauses)}
        GROUP BY o.metric_label_clean, o.row_path_text, o.metric_code,
                 o.unit_kind, o.statement_type, d.basis
        """,
        tuple(parameters),
    )
    hypotheses: list[dict[str, object]] = []
    for label, row_path, metric_code, unit, statement_type, basis, support in rows:
        best = (0, 0, 0, "")
        for surface in (str(label or ""), str(row_path or "")):
            source_terms = normalize_phrase(surface).replace("›", " ").split()
            run, matched_surface = _longest_common_run(question_terms, source_terms)
            overlap = len(set(question_terms).intersection(source_terms))
            score = (run, overlap, -abs(len(source_terms) - len(question_terms)), matched_surface)
            best = max(best, score)
        if best[0] < 2:
            continue
        hypotheses.append(
            {
                "metric_label_clean": str(label),
                "row_path": str(row_path or label),
                "source_metric_code": None if metric_code in (None, "") else str(metric_code),
                "unit_kind": str(unit),
                "statement_type": str(statement_type),
                "basis": str(basis),
                "supporting_observations": int(support),
                "longest_run": best[0],
                "token_overlap": best[1],
                "metric_surface": best[3],
            }
        )
    hypotheses.sort(
        key=lambda value: (
            -int(value["longest_run"]),
            -int(value["token_overlap"]),
            str(value["metric_label_clean"]),
            str(value["row_path"]),
            str(value["source_metric_code"] or ""),
            str(value["basis"]),
        )
    )
    return question_terms, hypotheses[:20]


def _root_cause(
    annotation: object,
    tier: str,
    hypotheses: list[dict[str, object]],
) -> str:
    if not annotation.entities and annotation.mode != "screen_open":
        return "ENTITY_SCOPE_UNAVAILABLE"
    if tier == "NO_PHRASE":
        return "METRIC_SOURCE_SPECIFICITY_REQUIRED"
    if annotation.return_mode.value in {"select_at_arg", "filtered_value"}:
        return "OPERAND_ROLE_UNRESOLVED"
    if not hypotheses:
        return "QUESTION_MENTION_NOT_EXTRACTED"
    top = hypotheses[0]
    tied = [
        value
        for value in hypotheses
        if (value["longest_run"], value["token_overlap"])
        == (top["longest_run"], top["token_overlap"])
    ]
    identities = {
        (
            value["metric_label_clean"],
            value["source_metric_code"],
            value["unit_kind"],
        )
        for value in tied
    }
    if len(identities) > 1 or tier == "T3":
        return "METRIC_HYPOTHESES_AMBIGUOUS"
    return "QUESTION_MENTION_NO_MAPPING"


def _tier(eval_row: dict[str, Any] | None) -> str:
    if not eval_row or not eval_row.get("gold_ok"):
        return "NO_PHRASE"
    raw = str(eval_row.get("gold_tier", ""))
    if raw.startswith("T1"):
        return "T1"
    if raw.startswith("T2"):
        return "T2"
    return "T3"


def _dependency_versions() -> dict[str, str]:
    names = ("text2pandas", "pandas", "pyarrow", "PyYAML", "lxml", "pytest", "mypy", "ruff")
    versions: dict[str, str] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "NOT_INSTALLED"
    return versions


def _lexical_snapshot(
    questions: list[dict[str, Any]], aliases: dict[str, list[str]]
) -> list[dict[str, object]]:
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
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--a6", type=Path, default=DEFAULT_A6)
    parser.add_argument("--retrieval-eval", type=Path, default=DEFAULT_EVAL)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"immutable diagnostic output exists: {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    records = _jsonl(args.records)
    questions = _jsonl(args.questions)
    eval_by_qid = {int(row["id"]): row for row in _jsonl(args.retrieval_eval)}
    unresolved = [row for row in records if row.get("reason") == "METRIC_UNRESOLVED"]
    aliases = load_aliases("a6")
    annotator = LegacyVietnameseAnnotator(aliases)
    diagnostics: list[dict[str, object]] = []
    reason_counts: Counter[str] = Counter()
    tier_counts: Counter[str] = Counter()
    connection = sqlite3.connect(f"file:{args.a6.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        for row in unresolved:
            qid = int(row["qid"])
            question = str(row["question"])
            annotation = annotator.annotate(question)
            question_terms, hypotheses = _source_hypotheses(
                connection, question, annotation, aliases
            )
            tier = _tier(eval_by_qid.get(qid))
            reason = _root_cause(annotation, tier, hypotheses)
            reason_counts[reason] += 1
            tier_counts[tier] += 1
            diagnostics.append(
                {
                    "qid": qid,
                    "question": question,
                    "operation": annotation.operation.value,
                    "return_mode": annotation.return_mode.value,
                    "metric_surface": hypotheses[0]["metric_surface"] if hypotheses else None,
                    "metric_hypotheses": hypotheses,
                    "source_evidence": {
                        "a6_build_id": "c6887fb633374fad",
                        "proxy_tier": tier,
                        "proxy_phrase": eval_by_qid.get(qid, {}).get("gold_phrase"),
                        "question_terms": question_terms,
                    },
                    "root_cause": reason,
                    "terminal_reason": "METRIC_UNRESOLVED",
                }
            )
    finally:
        connection.close()

    diagnostics.sort(key=lambda value: int(value["qid"]))
    cohort = [
        {
            "qid": row["qid"],
            "tier": row["source_evidence"]["proxy_tier"],
            "root_cause": row["root_cause"],
        }
        for row in diagnostics
    ]
    _write_jsonl(args.output_dir / "diagnostic_records.jsonl", diagnostics)
    _write_jsonl(args.output_dir / "cohort_h198.jsonl", cohort)
    lexical = _lexical_snapshot(questions, aliases)
    _write_jsonl(args.output_dir / "v2_lexical_snapshot.jsonl", lexical)

    source_manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    metrics = source_manifest["metrics"]
    _write_json(args.output_dir / "baseline_metrics.json", metrics)
    _write_json(
        args.output_dir / "baseline_runtime.json",
        {
            "cold_seconds": metrics["seconds"],
            "warm_seconds": [],
            "resolver_seconds": 0.0,
            "note": "B0 resolver-disabled reference run",
        },
    )
    shutil.copy2(args.records, args.output_dir / "baseline_records.jsonl")
    seal = {
        "schema_version": "metric-unresolved-baseline-v1",
        "source_run_manifest": source_manifest,
        "environment": {
            "python": sys.version,
            "python_executable": sys.executable,
            "os": platform.platform(),
            "machine": platform.machine(),
            "dependencies": _dependency_versions(),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "timezone": os.environ.get("TZ"),
        },
        "checksums": {
            "questions_sha256": _sha256(args.questions),
            "ontology_manifest_sha256": _sha256(ROOT / "configs/semantic/ontology_v3.yaml"),
            "active_snapshot_sha256": _sha256(ROOT / "configs/datasets/active_snapshot.yaml"),
            "dependency_contract_sha256": _sha256(ROOT / "pyproject.toml"),
            "baseline_records_sha256": _sha256(args.records),
            "cohort_h198_sha256": _sha256(args.output_dir / "cohort_h198.jsonl"),
            "v2_lexical_snapshot_sha256": _sha256(args.output_dir / "v2_lexical_snapshot.jsonl"),
        },
    }
    _write_json(args.output_dir / "baseline_manifest.json", seal)
    _write_json(
        args.output_dir / "diagnostic_summary.json",
        {
            "records": len(diagnostics),
            "root_causes": dict(sorted(reason_counts.items())),
            "tiers": dict(sorted(tier_counts.items())),
            "limitations": [
                "A6 lexical hypotheses are source evidence, not semantic gold.",
                "Current parser does not retain unmapped mention spans; taxonomy is an audit classification.",
            ],
        },
    )
    print(json.dumps({"records": len(diagnostics), "reasons": reason_counts}, default=dict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
