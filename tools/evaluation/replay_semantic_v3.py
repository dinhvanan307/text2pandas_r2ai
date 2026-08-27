"""Replay every emitted Semantic V3 query from its materialized evidence CSVs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.application.usecases.semantic_v3_replay import (
    replay_semantic_v3_records,
)
from text2pandas.infrastructure.checksums import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True)
    parser.add_argument("--data-root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-9)
    args = parser.parse_args()
    records_path = Path(args.records).expanduser().resolve()
    records = [
        json.loads(line)
        for line in records_path.read_text(encoding="utf-8").splitlines()
        if line
    ]
    report = replay_semantic_v3_records(
        records, Path(args.data_root), tolerance=args.tolerance
    )
    report["input"] = {
        "path": str(records_path),
        "sha256": sha256_file(records_path),
    }
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(output)
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

