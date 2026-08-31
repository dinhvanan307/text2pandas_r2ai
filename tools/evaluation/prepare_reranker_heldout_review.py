"""Prepare A/B/C prediction-blind templates for the sealed reranker cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.reranker_gold import reranker_review_templates
from text2pandas.infrastructure.checksums import sha256_file

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selection", type=Path, default=ROOT / "configs/evaluation/reranker_heldout_v1.json"
    )
    parser.add_argument(
        "--questions", type=Path, default=ROOT / "data/gold/retrieval/heldout_v1_questions.jsonl"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    selection_path = args.selection.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    questions = [
        json.loads(line)
        for line in questions_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = list(map(int, selection.get("heldout_qids") or []))
    actual = sorted(int(row["id"]) for row in questions)
    if sorted(expected) != actual:
        raise ValueError("question packet does not match sealed heldout QIDs")
    if selection.get("packet_sha256") != hashlib.sha256(
        questions_path.read_bytes()
    ).hexdigest():
        raise ValueError("question packet checksum mismatch")
    output.mkdir(parents=True)
    assets = {
        "annotator_a.jsonl": canonical_jsonl(
            reranker_review_templates(questions, reviewer_slot="A")
        ),
        "annotator_b.jsonl": canonical_jsonl(
            reranker_review_templates(questions, reviewer_slot="B")
        ),
        "adjudication.jsonl": canonical_jsonl(
            reranker_review_templates(questions, reviewer_slot="C")
        ),
    }
    for name, content in assets.items():
        (output / name).write_bytes(content)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.reranker_heldout_review_packet",
        "status": "OPEN_FOR_INDEPENDENT_REVIEW",
        "model_outputs_included": False,
        "records": len(questions),
        "selection_manifest_sha256": sha256_file(selection_path),
        "question_packet_sha256": sha256_file(questions_path),
        "assets": {
            name: {
                "records": len(questions),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for name, content in assets.items()
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
