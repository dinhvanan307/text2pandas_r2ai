"""Write a machine-readable completeness audit for an independent-gold packet."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.independent_gold_audit import (
    audit_independent_gold_packet,
)
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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = args.packet.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    paths = {
        "selection": packet / "selection.jsonl",
        "annotator_a": packet / "annotator_a.jsonl",
        "annotator_b": packet / "annotator_b.jsonl",
        "adjudication": packet / "adjudication.jsonl",
    }
    for label, path in paths.items():
        if not path.is_file():
            parser.error(f"missing packet asset {label}: {path}")
    audit = audit_independent_gold_packet(
        _rows(paths["selection"]),
        _rows(paths["annotator_a"]),
        _rows(paths["annotator_b"]),
        _rows(paths["adjudication"]),
    )
    report = {
        **audit.to_dict(),
        "packet": str(packet),
        "inputs": {
            label: {"path": str(path), "sha256": sha256_file(path)}
            for label, path in paths.items()
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if audit.sealable else 3


if __name__ == "__main__":
    raise SystemExit(main())
