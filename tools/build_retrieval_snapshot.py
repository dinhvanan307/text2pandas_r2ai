"""CLI for the immutable A6-derived retrieval snapshot builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.retrieval.snapshot import (
    build_retrieval_snapshot,
    retrieval_index_id,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--build-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    paths = ProjectPaths.discover()
    expected_build_id = args.build_id
    if args.output is None:
        if not expected_build_id:
            parser.error("--build-id is required when --output is omitted")
        output = paths.retrieval_snapshot(expected_build_id, retrieval_index_id())
    else:
        output = args.output
    result = build_retrieval_snapshot(
        args.source_db,
        output,
        expected_build_id=expected_build_id,
    )
    print(
        json.dumps(
            {
                "build_id": result.build_id,
                "index_id": result.index_id,
                "root": str(result.root),
                "database": str(result.database),
                "manifest": str(result.manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
