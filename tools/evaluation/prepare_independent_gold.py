"""Prepare prediction-blind dual-annotation packets from the sealed question source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from text2pandas.application.usecases.independent_gold import (
    adjudication_templates,
    annotation_templates,
    canonical_jsonl,
    select_blinded_questions,
)

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", default="configs/evaluation/independent_gold_protocol_v1.yaml")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    protocol_path = (ROOT / args.protocol).resolve()
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    source = ROOT / protocol["question_source"]["path"]
    source_bytes = source.read_bytes()
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_sha != protocol["question_source"]["sha256"]:
        raise ValueError(f"question source checksum mismatch: {actual_sha}")
    questions = [json.loads(line) for line in source_bytes.decode().splitlines() if line]
    selection = select_blinded_questions(
        questions,
        seed=str(protocol["selection"]["seed"]),
        count=int(protocol["selection"]["records"]),
    )
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    assets = {
        "selection.jsonl": canonical_jsonl(selection),
        "annotator_a.jsonl": canonical_jsonl(annotation_templates(selection, annotator_slot="A")),
        "annotator_b.jsonl": canonical_jsonl(annotation_templates(selection, annotator_slot="B")),
        "adjudication.jsonl": canonical_jsonl(adjudication_templates(selection)),
    }
    for name, content in assets.items():
        (output / name).write_bytes(content)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.independent_gold_annotation_packet",
        "protocol_id": protocol["protocol_id"],
        "status": "OPEN_FOR_INDEPENDENT_REVIEW",
        "model_outputs_included": False,
        "records": len(selection),
        "assets": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "records": len(selection)}
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
