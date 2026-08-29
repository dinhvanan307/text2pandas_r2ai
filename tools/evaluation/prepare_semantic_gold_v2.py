"""Prepare an immutable, prediction-blind Semantic Gold v2 review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from text2pandas.application.usecases.semantic_gold_v2 import (
    annotation_templates,
    build_contamination_ledger,
    canonical_packet_jsonl,
    select_semantic_questions,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "artifacts"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--protocol",
        default="configs/evaluation/semantic_gold_v2_protocol.yaml",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    protocol_path = _repo_path(args.protocol)
    protocol = _yaml_mapping(protocol_path)
    if _as_int(protocol.get("schema_version", 0), "protocol schema version") != 2:
        raise ValueError("semantic gold protocol schema_version must equal 2")
    target_parser = _mapping(protocol.get("target_parser"), "target_parser")
    _validate_active_snapshot(target_parser)

    question_config = _mapping(protocol.get("question_source"), "question_source")
    question_path = _repo_path(_required_text(question_config.get("path"), "question path"))
    question_bytes = question_path.read_bytes()
    _verify_sha(
        question_bytes,
        _required_text(question_config.get("sha256"), "question source sha256"),
        "question source",
    )
    questions = _jsonl(question_path)
    expected_records = _as_int(question_config["records"], "question records")
    if len(questions) != expected_records:
        raise ValueError(
            f"question source record mismatch: {len(questions)} != {expected_records}"
        )

    contracts = _mapping(protocol.get("contracts"), "contracts")
    contract_paths = {
        name: _repo_path(_required_text(path, f"contract path:{name}"))
        for name, path in contracts.items()
    }
    contract_hashes = {
        name: _sha256(path.read_bytes()) for name, path in contract_paths.items()
    }
    sampling = _yaml_mapping(contract_paths["sampling"])

    contamination_configs = protocol.get("contamination_sources")
    if not isinstance(contamination_configs, Sequence) or isinstance(
        contamination_configs, (str, bytes)
    ):
        raise TypeError("contamination_sources must be a list")
    contamination_sources: dict[str, list[dict[str, object]]] = {}
    contamination_reasons: dict[str, str] = {}
    for raw in contamination_configs:
        item = _mapping(raw, "contamination source")
        relative = _required_text(item.get("path"), "contamination source path")
        reason = _required_text(item.get("reason"), f"contamination reason:{relative}")
        path = _repo_path(relative)
        contamination_sources[relative] = _jsonl(path)
        contamination_reasons[relative] = reason
    ledger_rows = build_contamination_ledger(contamination_sources)
    contaminated_qids = frozenset(
        _as_int(row["qid"], "contamination qid") for row in ledger_rows
    )

    selection = select_semantic_questions(
        questions,
        contaminated_qids=contaminated_qids,
        sampling=sampling,
    )
    active_selection = selection.active

    annotation_hashes = {
        "guideline_sha256": contract_hashes["guideline"],
        "metric_vocabulary_sha256": contract_hashes["metric_vocabulary"],
        "operation_vocabulary_sha256": contract_hashes["operation_vocabulary"],
    }
    protected = _protected_surface(protocol)
    _validate_protected_target(target_parser, protected)
    protected_bytes = _canonical_json(protected)
    contamination_document = {
        "schema_version": 1,
        "records": len(ledger_rows),
        "sources": [
            {
                "path": path,
                "reason": contamination_reasons[path],
                "records": len(contamination_sources[path]),
                "sha256": _sha256(_repo_path(path).read_bytes()),
            }
            for path in sorted(contamination_sources)
        ],
        "ledger": list(ledger_rows),
    }
    coverage_document = {
        **selection.coverage,
        "headline_core_qids": [
            _as_int(row["qid"], "headline qid") for row in selection.core
        ],
        "diagnostic_qids": [
            _as_int(row["qid"], "diagnostic qid") for row in selection.diagnostic
        ],
        "reserve_qids": [
            _as_int(row["qid"], "reserve qid") for row in selection.reserve
        ],
    }

    assets: dict[str, tuple[bytes, int | None]] = {
        "selection_core.jsonl": (
            canonical_packet_jsonl(selection.core),
            len(selection.core),
        ),
        "selection_diagnostic.jsonl": (
            canonical_packet_jsonl(selection.diagnostic),
            len(selection.diagnostic),
        ),
        "selection_reserve.jsonl": (
            canonical_packet_jsonl(selection.reserve),
            len(selection.reserve),
        ),
        "annotator_a.jsonl": (
            canonical_packet_jsonl(
                annotation_templates(
                    active_selection,
                    reviewer_slot="A",
                    contract_hashes=annotation_hashes,
                )
            ),
            len(active_selection),
        ),
        "annotator_b.jsonl": (
            canonical_packet_jsonl(
                annotation_templates(
                    active_selection,
                    reviewer_slot="B",
                    contract_hashes=annotation_hashes,
                )
            ),
            len(active_selection),
        ),
        "adjudication.jsonl": (
            canonical_packet_jsonl(
                annotation_templates(
                    active_selection,
                    reviewer_slot="C",
                    contract_hashes=annotation_hashes,
                )
            ),
            len(active_selection),
        ),
        "access_log.jsonl": (b"", 0),
        "contamination_ledger.json": (_canonical_json(contamination_document), None),
        "coverage_matrix.json": (_canonical_json(coverage_document), None),
        "protected_surface.json": (protected_bytes, None),
    }
    current_commit = _git_head()
    implementation = _preparation_implementation()
    implementation_bytes = _canonical_json(implementation)
    manifest: dict[str, Any] = {
        "schema_version": 2,
        "kind": "text2pandas.semantic_gold_v2_annotation_packet",
        "protocol_id": _required_text(protocol.get("protocol_id"), "protocol id"),
        "status": "OPEN_FOR_INDEPENDENT_REVIEW",
        "model_outputs_included": False,
        "question_source": {
            "path": str(question_config["path"]),
            "sha256": _sha256(question_bytes),
            "records": len(questions),
        },
        "target_parser": dict(target_parser),
        "preparation_source_commit": current_commit,
        "preparation_implementation_sha256": _sha256(implementation_bytes),
        "contracts": {
            name: {"path": str(contracts[name]), "sha256": contract_hashes[name]}
            for name in sorted(contract_paths)
        },
        "selection": {
            "headline_core_records": len(selection.core),
            "diagnostic_records": len(selection.diagnostic),
            "active_records": len(active_selection),
            "reserve_records": len(selection.reserve),
            "contaminated_records": len(contaminated_qids),
            "selection_uses_predictions": False,
        },
        "review": {
            "annotator_a": "UNASSIGNED",
            "annotator_b": "UNASSIGNED",
            "adjudicator_c": "UNASSIGNED",
            "minimum_independent_annotators": 2,
            "require_distinct_adjudicator": True,
        },
        "protected_surface_sha256": _sha256(protected_bytes),
        "assets": {
            name: {
                "sha256": _sha256(content),
                **({"records": records} if records is not None else {}),
            }
            for name, (content, records) in sorted(assets.items())
        },
        "blockers": [
            "INDEPENDENT_ANNOTATOR_A_UNASSIGNED",
            "INDEPENDENT_ANNOTATOR_B_UNASSIGNED",
            "DISTINCT_ADJUDICATOR_C_UNASSIGNED",
            "SEMANTIC_METRICS_NOT_MEASURED_UNTIL_GOLD_IS_SEALED",
        ],
    }

    output = Path(args.output).expanduser().resolve()
    try:
        output.relative_to(ARTIFACT_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"packet output must be under {ARTIFACT_ROOT}") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False, exist_ok=False)
    for name, (content, _records) in assets.items():
        (output / name).write_bytes(content)
    (output / "manifest.json").write_bytes(_canonical_json(manifest))
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _protected_surface(protocol: Mapping[str, object]) -> dict[str, object]:
    raw_paths = protocol.get("protected_surface")
    if not isinstance(raw_paths, Sequence) or isinstance(raw_paths, (str, bytes)):
        raise TypeError("protected_surface must be a list")
    assets = []
    for raw in raw_paths:
        relative = _required_text(raw, "protected surface path")
        path = _repo_path(relative)
        assets.append(
            {"path": relative, "sha256": _sha256(path.read_bytes())}
        )
    return {
        "schema_version": 1,
        "policy": "must_match_after_phase1.5_measurement",
        "assets": sorted(assets, key=lambda item: str(item["path"])),
    }


def _preparation_implementation() -> dict[str, object]:
    relative_paths = (
        "src/text2pandas/application/usecases/semantic_gold_v2.py",
        "tools/evaluation/prepare_semantic_gold_v2.py",
    )
    return {
        "schema_version": 1,
        "assets": [
            {"path": relative, "sha256": _sha256(_repo_path(relative).read_bytes())}
            for relative in relative_paths
        ],
    }


def _validate_active_snapshot(target: Mapping[str, object]) -> None:
    active = _yaml_mapping(ROOT / "configs/datasets/active_snapshot.yaml")
    raw = _mapping(active.get("raw"), "active raw snapshot")
    a6 = _mapping(active.get("a6"), "active A6 snapshot")
    retrieval = _mapping(active.get("retrieval"), "active retrieval snapshot")
    expected = {
        "raw_snapshot_id": str(raw.get("snapshot_id")),
        "a6_build_id": str(a6.get("build_id")),
        "retrieval_index_id": str(retrieval.get("index_id")),
    }
    for field, actual in expected.items():
        configured = _required_text(target.get(field), f"target parser {field}")
        if configured != actual:
            raise ValueError(
                f"active snapshot mismatch for {field}: {actual} != {configured}"
            )


def _validate_protected_target(
    target: Mapping[str, object], protected: Mapping[str, object]
) -> None:
    commit = _required_text(target.get("source_commit"), "target parser source commit")
    raw_assets = protected.get("assets")
    if not isinstance(raw_assets, Sequence) or isinstance(raw_assets, (str, bytes)):
        raise TypeError("protected assets must be a list")
    paths = [str(_mapping(item, "protected asset")["path"]) for item in raw_assets]
    subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "diff", "--quiet", commit, "--", *paths],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            "protected production surface differs from target parser commit"
        )


def _jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"JSONL row must be an object: {path}:{line_number}")
        rows.append(value)
    return rows


def _yaml_mapping(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"YAML root must be a mapping: {path}")
    return value


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    raise TypeError(f"{label} must be an integer")


def _repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(f"path escapes repository: {value}") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _verify_sha(content: bytes, expected: str, label: str) -> None:
    actual = _sha256(content)
    if actual != expected:
        raise ValueError(f"{label} checksum mismatch: {actual} != {expected}")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
