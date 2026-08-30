"""Seal answer, retrieval, inherited recovery, and mutation QID sets."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.source_identity import git_source_identity

ROOT = Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _submission(path: Path) -> dict[int, dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        roots = [name for name in archive.namelist() if "/" not in name and name.endswith(".json")]
        if len(roots) != 1:
            raise ValueError(f"expected one root JSON in {path}")
        payload = json.loads(archive.read(roots[0]).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("submission root must be a list")
    records = {int(row["id"]): row for row in payload}
    if len(records) != len(payload):
        raise ValueError("submission contains duplicate QIDs")
    return records


def _is_executable(row: Mapping[str, object]) -> bool:
    evidence = row.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        return False
    if not evidence or not str(row.get("pandas_query") or "").strip():
        return False
    answer = row.get("answer")
    try:
        return answer is not None and not isinstance(answer, bool) and math.isfinite(float(answer))
    except (TypeError, ValueError, OverflowError):
        return False


def partition_sets(
    baseline: Mapping[int, Mapping[str, object]],
    inventory_qids: set[int],
    inherited_qids: set[int],
    *,
    expected_records: int,
    expected_executable: int,
    expected_unresolved: int,
) -> dict[str, tuple[int, ...]]:
    """Validate the mutation boundary and return stable sorted QID sets."""

    all_qids = set(baseline)
    executable = {qid for qid, row in baseline.items() if _is_executable(row)}
    unresolved = all_qids - executable
    if len(all_qids) != expected_records:
        raise ValueError(f"expected {expected_records} records, found {len(all_qids)}")
    if len(executable) != expected_executable:
        raise ValueError(
            f"expected {expected_executable} executable records, found {len(executable)}"
        )
    if len(unresolved) != expected_unresolved:
        raise ValueError(
            f"expected {expected_unresolved} unresolved records, found {len(unresolved)}"
        )
    if inventory_qids != unresolved:
        missing = sorted(unresolved - inventory_qids)
        extra = sorted(inventory_qids - unresolved)
        raise ValueError(f"inventory differs from unresolved set: missing={missing} extra={extra}")
    if not inherited_qids.issubset(executable):
        raise ValueError(
            f"inherited recovery QIDs are not executable: {sorted(inherited_qids - executable)}"
        )
    if executable & inventory_qids:
        raise ValueError("protected answers overlap the mutation pool")
    return {
        "p_answer": tuple(sorted(executable)),
        "p_retrieval": tuple(sorted(all_qids)),
        "p_inherited_recovery": tuple(sorted(inherited_qids)),
        "mutation_pool": tuple(sorted(inventory_qids)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--inherited-ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-records", type=int, default=1012)
    parser.add_argument("--expected-executable", type=int, required=True)
    parser.add_argument("--expected-unresolved", type=int, required=True)
    parser.add_argument("--expected-inherited", type=int, required=True)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    source = git_source_identity(ROOT)
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        parser.error("protected-set generation requires a clean committed source tree")

    baseline_path = args.baseline.expanduser().resolve()
    inventory_path = args.inventory.expanduser().resolve()
    ledger_path = args.inherited_ledger.expanduser().resolve()
    baseline = _submission(baseline_path)
    inventory_qids = {int(row["qid"]) for row in _rows(inventory_path)}
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    reviews = ledger.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError("inherited ledger reviews must be a list")
    inherited_qids = {int(row["qid"]) for row in reviews}
    if len(inherited_qids) != args.expected_inherited:
        raise ValueError(
            f"expected {args.expected_inherited} inherited QIDs, found {len(inherited_qids)}"
        )
    sets = partition_sets(
        baseline,
        inventory_qids,
        inherited_qids,
        expected_records=args.expected_records,
        expected_executable=args.expected_executable,
        expected_unresolved=args.expected_unresolved,
    )

    output.mkdir(parents=True)
    protected_path = output / "protected_sets.json"
    payload = {
        "schema_version": 1,
        "kind": "text2pandas.recovery_protected_sets",
        "sets": {name: list(qids) for name, qids in sets.items()},
        "counts": {name: len(qids) for name, qids in sets.items()},
        "invariants": {
            "answer_mutation_overlap": 0,
            "inventory_equals_unresolved": True,
            "inherited_recovery_is_executable": True,
            "retrieval_scope_equals_baseline": True,
        },
    }
    protected_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        **payload,
        "source": {
            **source,
            "baseline": {"path": str(baseline_path), "sha256": sha256_file(baseline_path)},
            "inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
            "inherited_ledger": {"path": str(ledger_path), "sha256": sha256_file(ledger_path)},
        },
        "outputs": {
            "protected_sets": {
                "path": "protected_sets.json",
                "sha256": sha256_file(protected_path),
            }
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["counts"], indent=2, sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
