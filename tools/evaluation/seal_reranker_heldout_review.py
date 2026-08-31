"""Seal completed independent reranker evidence labels for one-shot A/B."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.reranker_gold import seal_reranker_gold
from text2pandas.infrastructure.checksums import sha256_file


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    packet = args.packet.expanduser().resolve()
    selection_path = args.selection.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    questions = _rows(questions_path)
    expected_question_sha256 = {
        int(str(row["id"])): hashlib.sha256(
            str(row["question"]).encode("utf-8")
        ).hexdigest()
        for row in questions
    }
    if sha256_file(questions_path) != selection.get("packet_sha256"):
        raise ValueError("question packet checksum mismatch")
    release = seal_reranker_gold(
        _rows(packet / "annotator_a.jsonl"),
        _rows(packet / "annotator_b.jsonl"),
        _rows(packet / "adjudication.jsonl"),
        expected_qids=list(map(int, selection.get("heldout_qids") or [])),
        expected_question_sha256=expected_question_sha256,
    )
    output.mkdir(parents=True)
    labels = canonical_jsonl(release.records)
    labels_path = output / "heldout_v1_gold.jsonl"
    labels_path.write_bytes(labels)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.reranker_heldout_gold_release",
        "release_id": args.release_id,
        "status": "SEALED",
        "independent": True,
        "records": len(release.records),
        "disagreement_records": release.disagreement_records,
        "selection_manifest_sha256": sha256_file(selection_path),
        "question_packet_sha256": sha256_file(questions_path),
        "labels_sha256": hashlib.sha256(labels).hexdigest(),
    }
    (output / "heldout_v1_gold_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
