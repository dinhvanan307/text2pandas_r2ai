"""Validate completed reviews and create an immutable independent-gold release."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold import (
    canonical_jsonl,
    validate_and_merge_release,
)


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    packet = Path(args.packet).expanduser().resolve()
    selection = _rows(packet / "selection.jsonl")
    result = validate_and_merge_release(
        _rows(packet / "annotator_a.jsonl"),
        _rows(packet / "annotator_b.jsonl"),
        _rows(packet / "adjudication.jsonl"),
        expected_qids=[int(row["qid"]) for row in selection],
    )
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    gold = canonical_jsonl(result.records)
    (output / "gold.jsonl").write_bytes(gold)
    manifest = {
        "schema_version": 1,
        "kind": "text2pandas.independent_gold_release",
        "release_id": args.release_id,
        "status": "SEALED",
        "independence": "VERIFIED_BY_ATTESTATION",
        "records": len(result.records),
        "disagreement_records": result.disagreements,
        "assets": {
            "gold.jsonl": {
                "sha256": hashlib.sha256(gold).hexdigest(),
                "records": len(result.records),
            }
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
