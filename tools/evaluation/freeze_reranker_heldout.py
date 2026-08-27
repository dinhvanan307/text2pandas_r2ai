#!/usr/bin/env python3
"""Freeze an unlabeled retrieval held-out cohort before model development.

Selection uses only QID and question bytes.  Existing adjudication files are
used solely as an exclusion list, so no evidence label can leak into selection.
The generated packet intentionally contains no candidates or model outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"
LEGACY_GOLD = ROOT / "data/curated/dev-legacy/gold_v2.jsonl"
MANIFEST = ROOT / "configs/evaluation/reranker_heldout_v1.json"
PACKET = ROOT / "data/gold/retrieval/heldout_v1_questions.jsonl"
SEED = "text2pandas-reranker-heldout-v1-20260827"
N = 120


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> tuple[dict, str]:
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    legacy = [json.loads(line) for line in LEGACY_GOLD.read_text(encoding="utf-8").splitlines()
              if line.strip()]
    excluded = {int(row["id"]) for row in legacy}
    eligible = [row for row in questions if int(row["id"]) not in excluded]
    ranked = sorted(
        eligible,
        key=lambda row: hashlib.sha256(f"{SEED}:{int(row['id'])}".encode()).hexdigest(),
    )
    selected = sorted(ranked[:N], key=lambda row: int(row["id"]))
    packet = "".join(
        json.dumps({"id": int(row["id"]), "question": row["question"]},
                   ensure_ascii=False, sort_keys=True) + "\n"
        for row in selected
    )
    manifest = {
        "protocol_id": "reranker-heldout-v1",
        "status": "SEALED_UNLABELED",
        "selection_seed": SEED,
        "selection_algorithm": "lowest_sha256(seed:qid), excluding every legacy gold qid",
        "questions_sha256": sha(QUESTIONS),
        "legacy_gold_exclusion_sha256": sha(LEGACY_GOLD),
        "n_questions": len(questions),
        "n_excluded": len(excluded),
        "n_heldout": len(selected),
        "heldout_qids": [int(row["id"]) for row in selected],
        "packet_sha256": hashlib.sha256(packet.encode("utf-8")).hexdigest(),
        "label_policy": {
            "minimum_independent_annotators": 2,
            "adjudicator_independent_of_model_development": True,
            "candidate_outputs_hidden_during_first_pass": True,
            "model_selection_access": "forbidden_until_model_and_thresholds_are_frozen",
        },
    }
    return manifest, packet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    manifest, packet = build()
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.write:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        PACKET.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(rendered, encoding="utf-8")
        PACKET.write_text(packet, encoding="utf-8")
        print(f"wrote {MANIFEST.relative_to(ROOT)} and {PACKET.relative_to(ROOT)}")
        return 0
    if not MANIFEST.is_file() or not PACKET.is_file():
        raise SystemExit("held-out files missing; run once with --write")
    if MANIFEST.read_text(encoding="utf-8") != rendered:
        raise SystemExit("held-out manifest drift")
    if PACKET.read_text(encoding="utf-8") != packet:
        raise SystemExit("held-out packet drift")
    print(f"PASS heldout={manifest['n_heldout']} packet_sha={manifest['packet_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
