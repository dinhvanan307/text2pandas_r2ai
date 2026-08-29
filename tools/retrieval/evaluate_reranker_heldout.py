"""Run the one-shot paired A/B after an independent held-out label release exists."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from text2pandas.application.usecases.reranker_evaluation import (
    RerankOutcome,
    evaluate_reranker_ab,
)
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.evalkit.runner import (
    EvalConfig,
    _build_reranker,
    resolve_evaluation_dataset,
)
from text2pandas.pipelines.retrieval.evalkit.stages import (
    Bm25StructuralRanker,
    HardFilterGenerator,
)
from text2pandas.pipelines.retrieval.question_intent import parse_intent

SELECTION = ROOT / "configs/evaluation/reranker_heldout_v1.json"
LABELS = ROOT / "data/gold/retrieval/heldout_v1_gold.jsonl"
LABEL_MANIFEST = ROOT / "data/gold/retrieval/heldout_v1_gold_manifest.json"
MODEL = ROOT / "configs/retrieval/models/linear_reranker_v1.json"
OUT = ROOT / "artifacts/reports/reranker_linear_v1_heldout_ab.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_release(
    selection_path: Path,
    labels_path: Path,
    label_manifest_path: Path,
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    if not labels_path.is_file() or not label_manifest_path.is_file():
        raise FileNotFoundError(
            "independent held-out labels are absent; model promotion remains BLOCKED"
        )
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    release = json.loads(label_manifest_path.read_text(encoding="utf-8"))
    if release.get("status") != "SEALED" or release.get("independent") is not True:
        raise ValueError("held-out label release must be SEALED and independent")
    if release.get("selection_manifest_sha256") != _sha(selection_path):
        raise ValueError("held-out selection manifest checksum mismatch")
    if release.get("labels_sha256") != _sha(labels_path):
        raise ValueError("held-out labels checksum mismatch")
    rows = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    by_qid = {int(row["id"]): row for row in rows}
    expected = set(map(int, selection["heldout_qids"]))
    if set(by_qid) != expected or len(rows) != len(expected):
        raise ValueError("held-out labels must cover the sealed QIDs exactly once")
    for qid, row in by_qid.items():
        if not row.get("gold_table_uids"):
            raise ValueError(f"held-out qid {qid} has no evidence gold")
        if len(set(row.get("annotators") or ())) < 2 or not row.get("adjudicator"):
            raise ValueError(f"held-out qid {qid} lacks independent dual annotation")
    return by_qid, release


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=SELECTION)
    parser.add_argument("--labels", type=Path, default=LABELS)
    parser.add_argument("--label-manifest", type=Path, default=LABEL_MANIFEST)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        gold, release = _load_release(
            args.selection.expanduser().resolve(),
            args.labels.expanduser().resolve(),
            args.label_manifest.expanduser().resolve(),
        )
    except FileNotFoundError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2
    questions = {
        int(row["id"]): row["question"]
        for row in (json.loads(line) for line in
                    (ROOT / "data/raw/btc/questions/questions.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip())
    }
    dataset = resolve_evaluation_dataset(ROOT)
    conn = sqlite3.connect(f"file:{dataset.database}?mode=ro", uri=True)
    alias = load_aliases(brands=True)
    cfg = EvalConfig(
        reranker="linear",
        reranker_model_path=str(MODEL.relative_to(ROOT)),
        reranker_model_sha256=_sha(MODEL),
    )
    s1 = HardFilterGenerator(cfg.basis_mode, cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank,
                              use_hints=cfg.use_hints, basis_mode=cfg.basis_mode,
                              norm=cfg.norm)
    s3 = _build_reranker(ROOT, cfg)
    outcomes = []
    for qid in sorted(gold):
        question = questions[qid]
        intent = parse_intent(question, alias)
        o2 = s2.rank(conn, question, intent, s1.generate(conn, question, intent))
        o3 = s3.rerank(conn, question, intent, o2)
        wanted = frozenset(gold[qid]["gold_table_uids"])
        base = tuple(i for i, item in enumerate(o2.ranked[:10], 1)
                     if item.table_uid in wanted)
        cand = tuple(i for i, item in enumerate(o3.ranked, 1)
                     if item.table_uid in wanted)
        outcomes.append(RerankOutcome(qid, intent.mode, len(wanted),
                                      min(10, len(o2.ranked)), base, cand))
    conn.close()
    report = evaluate_reranker_ab(outcomes)
    report.update({
        "protocol_id": "reranker-heldout-v1",
        "label_release_id": release.get("release_id"),
        "selection_manifest_sha256": _sha(args.selection.expanduser().resolve()),
        "labels_sha256": _sha(args.labels.expanduser().resolve()),
        "model_sha256": _sha(MODEL),
        "retrieval_dataset_sha": dataset.sha,
    })
    output = args.output.expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"immutable output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
