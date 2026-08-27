#!/usr/bin/env python3
"""Train S3 on legacy development gold without touching the sealed held-out.

This is deliberately dependency-free and deterministic.  It uses pairwise
logistic loss over bounded S2 features, selects an epoch on a deterministic
legacy dev split, and stamps both the immutable retrieval dataset and training
manifest into the model.  The output is a candidate model, never a promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.alias_store import load_aliases  # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.goldset import ManualGold  # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.runner import (  # noqa: E402
    EvalConfig,
    resolve_evaluation_dataset,
)
from text2pandas.pipelines.retrieval.evalkit.stages import (  # noqa: E402
    Bm25StructuralRanker,
    HardFilterGenerator,
)
from text2pandas.pipelines.retrieval.question_intent import parse_intent  # noqa: E402
from text2pandas.pipelines.retrieval.rerank_s3 import (  # noqa: E402
    FEATURES,
    MODEL_SCHEMA,
    feature_rows,
)

GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"
HELDOUT = ROOT / "configs/evaluation/reranker_heldout_v1.json"
MODEL_OUT = ROOT / "configs/retrieval/models/linear_reranker_v1.json"
REPORT_OUT = ROOT / "artifacts/reports/reranker_linear_v1_development.json"
SPLIT_SEED = "linear-reranker-v1-legacy-dev"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _split(qids: list[int]) -> tuple[set[int], set[int]]:
    ranked = sorted(qids, key=lambda q: hashlib.sha256(f"{SPLIT_SEED}:{q}".encode()).hexdigest())
    n_dev = max(1, round(len(ranked) * 0.20))
    return set(ranked[n_dev:]), set(ranked[:n_dev])


def _metric(cases: list[dict], weights: list[float], k: int = 10) -> dict:
    f2 = mrr = hit = 0.0
    for case in cases:
        ordered = sorted(
            case["items"],
            key=lambda row: (-sum(w * x for w, x in zip(weights, row[1], strict=True)),
                             row[2], row[0]),
        )
        positions = [i for i, row in enumerate(ordered[:k], 1) if row[0] in case["gold"]]
        h, g, n = len(positions), len(case["gold"]), min(k, len(ordered))
        f2 += (5 * h / (4 * g + n)) if g and n else 0.0
        mrr += (1.0 / positions[0]) if positions else 0.0
        hit += bool(positions)
    n = len(cases) or 1
    return {"n": len(cases), "f2_at_10": f2 / n, "mrr_at_10": mrr / n,
            "hit_at_10": hit / n}


def _pairs(cases: list[dict]) -> list[tuple[tuple[float, ...], float]]:
    pairs = []
    for case in cases:
        pos = [row for row in case["items"] if row[0] in case["gold"]]
        neg = [row for row in case["items"] if row[0] not in case["gold"]][:12]
        for p in pos:
            for n in neg:
                pairs.append((tuple(a - b for a, b in zip(p[1], n[1], strict=True)), 1.0))
    return pairs


def _train(train: list[dict], dev: list[dict], epochs: int = 300) -> tuple[list[float], dict]:
    prior = [0.0] * len(FEATURES)
    prior[FEATURES.index("s2_score")] = 2.0
    prior[FEATURES.index("bm25")] = 0.5
    prior[FEATURES.index("rank_prior")] = 0.5
    weights = prior.copy()
    pairs = _pairs(train)
    if not pairs:
        raise ValueError("no train pairs: gold is absent from S2 top-K")
    best = weights.copy()
    best_metric = _metric(dev, best)
    history = []
    l2 = 0.01
    for epoch in range(1, epochs + 1):
        grad = [0.0] * len(weights)
        for diff, _ in pairs:
            margin = sum(w * x for w, x in zip(weights, diff, strict=True))
            factor = -1.0 / (1.0 + math.exp(min(50.0, margin)))
            for i, x in enumerate(diff):
                grad[i] += factor * x
        scale = 1.0 / len(pairs)
        lr = 0.35 / math.sqrt(epoch)
        for i in range(len(weights)):
            g = grad[i] * scale + l2 * (weights[i] - prior[i])
            weights[i] -= lr * g
        if epoch % 10 == 0 or epoch == epochs:
            current = _metric(dev, weights)
            history.append({"epoch": epoch, **current})
            key = (current["f2_at_10"], current["mrr_at_10"], current["hit_at_10"])
            old = (best_metric["f2_at_10"], best_metric["mrr_at_10"],
                   best_metric["hit_at_10"])
            if key > old:
                best, best_metric = weights.copy(), current
    return best, {"n_pairs": len(pairs), "history": history, "selected": best_metric}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=300)
    args = ap.parse_args()

    heldout = json.loads(HELDOUT.read_text(encoding="utf-8"))
    if heldout.get("status") != "SEALED_UNLABELED":
        raise SystemExit("held-out protocol is not sealed")
    heldout_qids = set(map(int, heldout["heldout_qids"]))

    raw_questions = [json.loads(x) for x in
                     (ROOT / "data/raw/btc/questions/questions.jsonl").read_text(encoding="utf-8").splitlines()
                     if x.strip()]
    by_qid = {int(row["id"]): row["question"] for row in raw_questions}
    gold_rows = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    usable_qids = sorted(int(row["id"]) for row in gold_rows
                         if row.get("gold_table_uids") and not row.get("uncertain"))
    if set(usable_qids) & heldout_qids:
        raise SystemExit("training/held-out QID overlap")
    train_qids, dev_qids = _split(usable_qids)

    dataset = resolve_evaluation_dataset(ROOT)
    conn = sqlite3.connect(f"file:{dataset.database}?mode=ro", uri=True)
    alias = load_aliases(brands=True)
    manual = ManualGold(GOLD, conn)
    cfg = EvalConfig()
    s1 = HardFilterGenerator(cfg.basis_mode, cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank,
                              use_hints=cfg.use_hints, basis_mode=cfg.basis_mode,
                              norm=cfg.norm)
    cases = []
    for index, qid in enumerate(usable_qids, 1):
        question = by_qid[qid]
        intent = parse_intent(question, alias)
        gold = manual.gold_for(conn, qid, question, intent.tickers, intent.years,
                               intent.explicit_scope)
        upstream = s2.rank(conn, question, intent, s1.generate(conn, question, intent))
        items = [(item.table_uid, values, rank)
                 for rank, (item, values) in enumerate(feature_rows(upstream, intent))]
        cases.append({"qid": qid, "gold": gold.tables, "items": items})
        if index % 20 == 0:
            print(f"features {index}/{len(usable_qids)}")
    conn.close()

    train = [c for c in cases if c["qid"] in train_qids]
    dev = [c for c in cases if c["qid"] in dev_qids]
    baseline = [0.0] * len(FEATURES)
    baseline[FEATURES.index("s2_score")] = 1.0
    weights, fit = _train(train, dev, args.epochs)
    training_manifest = {
        "protocol": "legacy-development-only-v1",
        "gold_sha256": _sha(GOLD),
        "heldout_manifest_sha256": _sha(HELDOUT),
        "retrieval_dataset_sha": dataset.sha,
        "split_seed": SPLIT_SEED,
        "train_qids": sorted(train_qids),
        "dev_qids": sorted(dev_qids),
        "epochs": args.epochs,
        "features": FEATURES,
    }
    manifest_blob = json.dumps(training_manifest, sort_keys=True, separators=(",", ":"))
    manifest_sha = hashlib.sha256(manifest_blob.encode()).hexdigest()
    model = {
        "schema": MODEL_SCHEMA,
        "model_id": "linear-reranker-v1",
        "features": list(FEATURES),
        "weights": {name: round(weights[i], 12) for i, name in enumerate(FEATURES)},
        "training_manifest_sha256": manifest_sha,
    }
    rendered = json.dumps(model, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
    MODEL_OUT.write_text(rendered, encoding="utf-8")
    report = {
        "status": "DEVELOPMENT_ONLY_NOT_PROMOTED",
        "contamination_notice": "Legacy 95 gold was used by prior feature engineering; this is not untouched held-out evidence.",
        "model_sha256": hashlib.sha256(rendered.encode()).hexdigest(),
        "training_manifest": training_manifest,
        "fit": fit,
        "train": {"identity": _metric(train, baseline), "linear": _metric(train, weights)},
        "dev": {"identity": _metric(dev, baseline), "linear": _metric(dev, weights)},
        "heldout": {"status": "BLOCKED_AWAITING_INDEPENDENT_LABELS", "n": len(heldout_qids)},
    }
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    print(json.dumps(report["dev"], indent=2))
    print(f"model_sha256={report['model_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
