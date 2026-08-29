"""Evaluate a submission ZIP against governed local development gold."""

from __future__ import annotations

import argparse
import io
import json
import math
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd

from text2pandas.application.usecases.competition_evaluation import (
    AnswerGold,
    Prediction,
    ReplayResult,
    RetrievalGold,
    compare_scores,
    normalize_doc_ref,
    normalize_table_ref,
    score_competition,
)
from text2pandas.application.usecases.submission import validate_zip
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.sandbox.query import execute_query

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
CORPUS = ROOT / "data/raw/btc/financial_statements"
RETRIEVAL_GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"
ANSWER_GOLD = (
    ROOT / "data/curated/dev-legacy/answer_gold/answer_gold_wave1_final.jsonl"
)
A6_DB = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _submission(path: Path) -> tuple[list[dict[str, Any]], str]:
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and "/" not in name.strip("/")
        ]
        if len(names) != 1:
            raise ValueError(f"submission must contain one root JSON: {names}")
        return json.loads(archive.read(names[0])), names[0]


def _predictions(rows: list[dict[str, Any]]) -> list[Prediction]:
    output: list[Prediction] = []
    for row in rows:
        raw_answer = row.get("answer")
        try:
            answer = float(str(raw_answer))
        except (TypeError, ValueError, OverflowError):
            answer = None
        if answer is not None and not math.isfinite(answer):
            answer = None
        output.append(
            Prediction(
                qid=int(row["id"]),
                relevant_tables=tuple(
                    normalize_table_ref(value)
                    for value in row.get("relevant_tables") or []
                ),
                relevant_docs=tuple(
                    normalize_doc_ref(value) for value in row.get("relevant_docs") or []
                ),
                answer=answer,
            )
        )
    return output


def _retrieval_gold(path: Path, database: Path) -> list[RetrievalGold]:
    source = [
        row
        for row in _rows(path)
        if row.get("gold_table_uids") and row.get("uncertain") is not True
    ]
    uids = sorted(
        {str(uid) for row in source for uid in row.get("gold_table_uids") or []}
    )
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    mapping: dict[str, str] = {}
    for start in range(0, len(uids), 500):
        chunk = uids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        mapping.update(
            connection.execute(
                f"SELECT table_uid, evidence_ref FROM tables "
                f"WHERE table_uid IN ({placeholders})",
                chunk,
            ).fetchall()
        )
    connection.close()
    missing = sorted(set(uids) - set(mapping))
    if missing:
        raise ValueError(f"retrieval gold UIDs absent from active A6: {missing[:5]}")
    output: list[RetrievalGold] = []
    for row in source:
        tables = frozenset(
            normalize_table_ref(mapping[str(uid)])
            for uid in row.get("gold_table_uids") or []
        )
        docs = frozenset(value.rpartition("|")[0] for value in tables)
        output.append(RetrievalGold(int(row["id"]), tables, docs))
    return output


def _answer_gold(path: Path) -> list[AnswerGold]:
    return [
        AnswerGold(int(row["qid"]), float(row["normalized_answer_gold"]))
        for row in _rows(path)
        if row.get("trang_thai") == "OK" and row.get("normalized_answer_gold") is not None
    ]


def _replay(path: Path, qids: set[int]) -> list[ReplayResult]:
    records, json_name = _submission(path)
    _ = json_name
    selected = {int(row["id"]): row for row in records if int(row["id"]) in qids}
    output: list[ReplayResult] = []
    cache: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(path) as archive:
        for qid in sorted(qids):
            row = selected.get(qid)
            if row is None:
                output.append(ReplayResult(qid, "MISSING_PREDICTION", None))
                continue
            evidence = row.get("evidence") or []
            query = str(row.get("pandas_query") or "")
            if not evidence or not query:
                output.append(ReplayResult(qid, "NO_EXECUTABLE_QUERY", None))
                continue
            frames: dict[str, object] = {}
            try:
                for item in evidence:
                    csv_path = str(item["csv_path"])
                    if csv_path not in cache:
                        cache[csv_path] = pd.read_csv(io.BytesIO(archive.read(csv_path)))
                    frames[str(item["variable"])] = cache[csv_path]
                value = execute_query(query, frames)
                output.append(ReplayResult(qid, "OK", value))
            except Exception as error:  # noqa: BLE001
                output.append(
                    ReplayResult(qid, f"ERROR:{type(error).__name__}", None)
                )
    return output


def _evaluate(
    path: Path,
    retrieval: list[RetrievalGold],
    answers: list[AnswerGold],
    questions: dict[int, str],
    tolerance: float,
) -> dict[str, Any]:
    validation = validate_zip(path, questions, corpus_root=CORPUS)
    records, json_name = _submission(path)
    score = score_competition(
        _predictions(records),
        retrieval,
        answers,
        _replay(path, {row.qid for row in answers}),
        tolerance=tolerance,
    )
    return {
        "artifact": {
            "path": str(path),
            "sha256": sha256_file(path),
            "json_member": json_name,
        },
        "validation": {
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        **score,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--retrieval-gold", type=Path, default=RETRIEVAL_GOLD)
    parser.add_argument("--answer-gold", type=Path, default=ANSWER_GOLD)
    parser.add_argument("--a6-db", type=Path, default=A6_DB)
    parser.add_argument("--tolerance", type=float, default=0.005)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    questions = {
        int(row["id"]): str(row["question"]) for row in _rows(QUESTIONS)
    }
    retrieval = _retrieval_gold(
        args.retrieval_gold.expanduser().resolve(), args.a6_db.expanduser().resolve()
    )
    answers = _answer_gold(args.answer_gold.expanduser().resolve())
    candidate = _evaluate(
        args.candidate.expanduser().resolve(),
        retrieval,
        answers,
        questions,
        args.tolerance,
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "kind": "text2pandas.competition_proxy_evaluation",
        "classification": "LOCAL_DEVELOPMENT_PROXY_NOT_OFFICIAL",
        "official_score_guarantee": False,
        "metric_semantics": "BTC_PUBLISHED_MACRO_PER_QUERY",
        "tolerance": {
            "kind": "relative_with_absolute_floor",
            "value": args.tolerance,
            "official_threshold_known": False,
        },
        "gold": {
            "retrieval": {
                "path": str(args.retrieval_gold),
                "sha256": sha256_file(args.retrieval_gold),
                "records": len(retrieval),
                "development_used": True,
            },
            "answer": {
                "path": str(args.answer_gold),
                "sha256": sha256_file(args.answer_gold),
                "records": len(answers),
                "development_used": True,
            },
        },
        "candidate": candidate,
    }
    exit_code = 0 if not candidate["validation"]["errors"] else 2
    if args.baseline:
        baseline = _evaluate(
            args.baseline.expanduser().resolve(),
            retrieval,
            answers,
            questions,
            args.tolerance,
        )
        report["baseline"] = baseline
        report["comparison"] = compare_scores(candidate, baseline)
        if not report["comparison"]["all_ten_metrics_non_regressing"]:
            exit_code = 3
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(candidate["metrics"], ensure_ascii=False, indent=2))
    if "comparison" in report:
        print(json.dumps(report["comparison"], ensure_ascii=False, indent=2))
    print(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
