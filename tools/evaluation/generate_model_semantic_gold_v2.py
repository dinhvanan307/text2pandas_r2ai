#!/usr/bin/env python3
"""Generate, validate, canonicalize, and seal MODEL_SEMANTIC_GOLD_V1.

The only semantic input sent to the model is the frozen question plus frozen
contracts. This tool intentionally has no imports from parser, retrieval,
resolver, answer, query, or execution packages.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from text2pandas.application.usecases.model_semantic_gold_v1 import (  # noqa: E402
    PROMPT_VERSION,
    RELEASE_ID,
    ModelGoldValidationError,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    canonicalize_record,
    compile_model_response,
    evaluate_canonical_predictions,
    generation_failure_record,
    json_schema_errors,
    reject_forbidden_fields,
    sha256_bytes,
    validate_model_gold_record,
)

COHORT_FILES = (
    ("HEADLINE_CORE", "selection_core.jsonl"),
    ("DIAGNOSTIC_SUPPLEMENT", "selection_diagnostic.jsonl"),
    ("RESERVE", "selection_reserve.jsonl"),
)
CONTRACT_RELEASE_NAMES = {
    "schema": "schema.json",
    "model_response_schema": "model_response_schema.json",
    "metric_vocabulary": "metric_vocabulary.yaml",
    "operation_vocabulary": "operation_vocabulary.yaml",
    "evaluation": "evaluation.yaml",
    "guideline": "guideline.md",
    "prompt": "prompt.txt",
}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected YAML object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"expected JSON object: {path}:{line_number}")
            rows.append(value)
    return rows


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _write_json(path: Path, value: object) -> None:
    _write_atomic(path, canonical_json_bytes(value))


def _sha256_file(path: Path) -> str:
    digest = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a repository-relative path")
    path = (ROOT / raw).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root: {raw}") from exc
    return path


def _protocol(path: Path) -> dict[str, Any]:
    protocol = _read_yaml(path)
    if protocol.get("release_id") != RELEASE_ID:
        raise ValueError(f"protocol release_id must be {RELEASE_ID}")
    expected_provenance = {
        "gold_mode": "MODEL_GOLD",
        "annotation_source": "LLM",
        "human_review": False,
        "cross_model_review": False,
        "official_human_gold": False,
    }
    if protocol.get("provenance") != expected_provenance:
        raise ValueError("protocol provenance is not the frozen single-model contract")
    registry = _read_yaml(ROOT / "configs/models.yaml").get("semantic_gold_generator")
    if not isinstance(registry, Mapping):
        raise ValueError("configs/models.yaml lacks semantic_gold_generator evidence")
    model = protocol.get("model")
    if not isinstance(model, Mapping):
        raise TypeError("protocol.model must be an object")
    for protocol_key, registry_key in (
        ("model_id", "served_model"),
        ("upstream_model_id", "name"),
        ("parameters_b", "params_b"),
        ("manifest_sha256", "local_manifest_sha256"),
        ("model_layer_sha256", "model_layer_sha256"),
        ("quantization", "quantization"),
    ):
        if model.get(protocol_key) != registry.get(registry_key):
            raise ValueError(
                f"model registry mismatch: protocol.{protocol_key} != "
                f"configs/models.yaml.{registry_key}"
            )
    return protocol


def _contract_paths(protocol: Mapping[str, Any]) -> dict[str, Path]:
    raw = protocol.get("contracts")
    if not isinstance(raw, Mapping):
        raise TypeError("protocol.contracts must be an object")
    paths = {
        name: _repo_path(raw.get(name), f"contracts.{name}")
        for name in CONTRACT_RELEASE_NAMES
    }
    paths["protocol"] = Path(protocol["_path"])
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing {name} contract: {path}")
    return paths


def _load_selection(protocol: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = protocol.get("target_set")
    if not isinstance(target, Mapping):
        raise TypeError("protocol.target_set must be an object")
    packet = _repo_path(target.get("packet"), "target_set.packet")
    manifest = _read_json(packet / "manifest.json")
    if manifest.get("kind") != "text2pandas.semantic_gold_v2_annotation_packet":
        raise ValueError("target packet has an unexpected kind")
    if manifest.get("model_outputs_included") is not False:
        raise ValueError("target packet is not prediction-blind")
    assets = manifest.get("assets")
    if not isinstance(assets, Mapping):
        raise TypeError("packet manifest assets must be an object")
    rows: list[dict[str, Any]] = []
    cohort_counts: dict[str, int] = {}
    for cohort, file_name in COHORT_FILES:
        path = packet / file_name
        asset = assets.get(file_name)
        if not isinstance(asset, Mapping):
            raise ValueError(f"packet manifest lacks {file_name}")
        if _sha256_file(path) != asset.get("sha256"):
            raise ValueError(f"packet asset checksum mismatch: {file_name}")
        cohort_rows = _read_jsonl(path)
        if len(cohort_rows) != asset.get("records"):
            raise ValueError(f"packet asset record count mismatch: {file_name}")
        for row in cohort_rows:
            if row.get("cohort") != cohort:
                raise ValueError(f"cohort mismatch in {file_name}: qid={row.get('qid')}")
            reject_forbidden_fields(row, location=f"selection:{row.get('qid')}")
        cohort_counts[cohort] = len(cohort_rows)
        rows.extend(cohort_rows)
    expected = target.get("expected_records")
    if len(rows) != expected:
        raise ValueError(f"expected {expected} selected records, found {len(rows)}")
    qids = [int(row["qid"]) for row in rows]
    if len(qids) != len(set(qids)):
        raise ValueError("duplicate QID across frozen cohorts")
    question_source = manifest.get("question_source")
    if not isinstance(question_source, Mapping):
        raise TypeError("packet question_source must be an object")
    source_path = _repo_path(question_source.get("path"), "packet.question_source.path")
    if _sha256_file(source_path) != question_source.get("sha256"):
        raise ValueError("frozen question source checksum mismatch")
    info = {
        "packet_path": str(packet.relative_to(ROOT)),
        "packet_manifest_sha256": _sha256_file(packet / "manifest.json"),
        "question_source": dict(question_source),
        "cohort_counts": cohort_counts,
        "asset_sha256": {
            name: str(assets[name]["sha256"]) for _, name in COHORT_FILES
        },
        "selection_sha256": sha256_bytes(
            canonical_jsonl_bytes(sorted(rows, key=lambda item: int(item["qid"])))
        ),
    }
    return sorted(rows, key=lambda item: int(item["qid"])), info


def _load_contracts(protocol: Mapping[str, Any]) -> dict[str, Any]:
    paths = _contract_paths(protocol)
    schema = _read_json(paths["schema"])
    response_schema = _read_json(paths["model_response_schema"])
    metric_overlay = _read_yaml(paths["metric_vocabulary"])
    operation_vocab = _read_yaml(paths["operation_vocabulary"])
    evaluation = _read_yaml(paths["evaluation"])
    extends = metric_overlay.get("extends")
    if not isinstance(extends, Mapping):
        raise TypeError("metric vocabulary must extend a frozen base vocabulary")
    metric_base_path = _repo_path(extends.get("path"), "metric_vocabulary.extends.path")
    metric_base = _read_yaml(metric_base_path)
    concept_rows = metric_base.get("concepts")
    if not isinstance(concept_rows, Sequence):
        raise TypeError("base metric vocabulary concepts must be a list")
    concept_ids = frozenset(
        str(item["id"]) for item in concept_rows if isinstance(item, Mapping)
    )
    operations = operation_vocab.get("operations")
    if not isinstance(operations, Mapping):
        raise TypeError("operation vocabulary operations must be an object")
    hashes = {name: _sha256_file(path) for name, path in paths.items()}
    hashes["metric_base"] = _sha256_file(metric_base_path)
    return {
        "paths": paths,
        "schema": schema,
        "response_schema": response_schema,
        "metric_overlay": metric_overlay,
        "metric_base": metric_base,
        "metric_base_path": metric_base_path,
        "operation_vocab": operation_vocab,
        "evaluation": evaluation,
        "concept_ids": concept_ids,
        "operations": operations,
        "hashes": hashes,
    }


def _prompt(
    selection: Mapping[str, Any],
    contracts: Mapping[str, Any],
    feedback: Sequence[str],
) -> str:
    paths = contracts["paths"]
    template = paths["prompt"].read_text(encoding="utf-8").strip()
    guideline = paths["guideline"].read_text(encoding="utf-8").strip()
    annotation_schema = json.dumps(
        contracts["schema"], ensure_ascii=False, separators=(",", ":")
    )
    response_schema = json.dumps(
        contracts["response_schema"], ensure_ascii=False, separators=(",", ":")
    )
    metric_vocab = yaml.safe_dump(
        contracts["metric_base"], allow_unicode=True, sort_keys=False
    ).strip()
    operation_vocab = yaml.safe_dump(
        contracts["operation_vocab"], allow_unicode=True, sort_keys=False
    ).strip()
    retry = ""
    if feedback:
        retry = (
            "\n\nPREVIOUS ATTEMPT VALIDATION ERRORS (correct these contract errors only):\n- "
            + "\n- ".join(feedback[:12])
        )
    return (
        f"{template}\n\n"
        f"FROZEN FINAL ANNOTATION SCHEMA:\n{annotation_schema}\n\n"
        f"FROZEN MODEL RESPONSE SCHEMA (your JSON must match this exactly):\n"
        f"{response_schema}\n\n"
        f"FROZEN METRIC VOCABULARY:\n{metric_vocab}\n\n"
        f"FROZEN OPERATION VOCABULARY:\n{operation_vocab}\n\n"
        f"FROZEN GUIDELINE:\n{guideline}\n\n"
        "FROZEN SOURCE EVIDENCE:\n"
        "No parser-selected or retriever-selected source evidence is included in this "
        "prediction-blind packet. Use NOT_APPLICABLE evidence and interpret only the "
        "question. If question meaning itself is insufficient, mark the affected field "
        "AMBIGUOUS or UNRESOLVED.\n\n"
        "QUESTION:\n"
        + json.dumps(
            {
                "qid": selection["qid"],
                "question": selection["question"],
                "question_sha256": selection["question_sha256"],
                "cohort": selection["cohort"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + retry
    )


def _ollama_generate(
    endpoint: str,
    *,
    model: str,
    prompt: str,
    response_schema: Mapping[str, Any],
    options: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": response_schema,
        "options": dict(options),
        "keep_alive": "30m",
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            value = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Ollama generation request failed: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("response"), str):
        raise RuntimeError("Ollama response lacks text field")
    return value


def _generation_metadata(
    protocol: Mapping[str, Any],
    *,
    prompt_hash: str,
    response_hash: str,
    attempt: int,
) -> dict[str, object]:
    model = protocol["model"]
    provenance = protocol["provenance"]
    return {
        "gold_mode": provenance["gold_mode"],
        "annotation_source": provenance["annotation_source"],
        "human_review": provenance["human_review"],
        "cross_model_review": provenance["cross_model_review"],
        "model_id": model["model_id"],
        "model_digest": f"sha256:{model['manifest_sha256']}",
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_hash,
        "response_sha256": response_hash,
        "attempt_count": attempt,
    }


def _validate_compiled(
    record: Mapping[str, Any],
    selection: Mapping[str, Any],
    contracts: Mapping[str, Any],
) -> None:
    schema_errors = json_schema_errors(record, contracts["schema"])
    if schema_errors:
        raise ModelGoldValidationError("; ".join(schema_errors))
    validate_model_gold_record(
        record,
        selection,
        metric_concept_ids=contracts["concept_ids"],
        operation_specs=contracts["operations"],
    )


def _prepare_state(
    work_dir: Path,
    protocol_path: Path,
    protocol: Mapping[str, Any],
    selection_info: Mapping[str, Any],
    contracts: Mapping[str, Any],
) -> dict[str, Any]:
    state_path = work_dir / "generation_state.json"
    expected = {
        "kind": "text2pandas.model_semantic_gold_v1_generation_state",
        "release_id": RELEASE_ID,
        "protocol_path": str(protocol_path.relative_to(ROOT)),
        "protocol_sha256": _sha256_file(protocol_path),
        "selection_sha256": selection_info["selection_sha256"],
        "contract_sha256": contracts["hashes"],
        "model_id": protocol["model"]["model_id"],
        "model_manifest_sha256": protocol["model"]["manifest_sha256"],
    }
    if state_path.exists():
        existing = _read_json(state_path)
        for key, value in expected.items():
            if existing.get(key) != value:
                raise ValueError(f"work-dir state mismatch for {key}; use a new run-id")
        return existing
    work_dir.mkdir(parents=True, exist_ok=False)
    expected["started_at"] = _utc_now()
    _write_json(state_path, expected)
    return expected


def generate(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol).resolve()
    protocol = _protocol(protocol_path)
    protocol["_path"] = str(protocol_path)
    selection, selection_info = _load_selection(protocol)
    contracts = _load_contracts(protocol)
    work_dir = Path(args.work_dir).resolve()
    _prepare_state(work_dir, protocol_path, protocol, selection_info, contracts)

    selected_qids: set[int] | None = None
    if args.qids:
        selected_qids = {int(value) for value in args.qids.split(",") if value.strip()}
        unknown = selected_qids - {int(row["qid"]) for row in selection}
        if unknown:
            raise ValueError(f"unknown selected QIDs: {sorted(unknown)}")
    targets = [
        row for row in selection if selected_qids is None or int(row["qid"]) in selected_qids
    ]
    if args.limit is not None:
        targets = targets[: args.limit]
    model = protocol["model"]
    options = {
        "temperature": model["temperature"],
        "top_p": model["top_p"],
        "seed": model["seed"],
        "num_ctx": model["num_ctx"],
        "num_predict": model["num_predict"],
    }
    records_dir = work_dir / "records"
    attempts_dir = work_dir / "attempts"
    records_dir.mkdir(exist_ok=True)
    attempts_dir.mkdir(exist_ok=True)
    completed = 0
    skipped = 0
    started = time.monotonic()
    for position, row in enumerate(targets, start=1):
        qid = int(row["qid"])
        record_path = records_dir / f"{qid:04d}.json"
        if record_path.exists():
            existing = _read_json(record_path)
            _validate_compiled(existing, row, contracts)
            skipped += 1
            print(f"[{position}/{len(targets)}] qid={qid} cached", flush=True)
            continue
        feedback: list[str] = []
        final_record: dict[str, Any] | None = None
        last_raw = ""
        for attempt in range(1, int(model["max_attempts"]) + 1):
            prompt = _prompt(row, contracts, feedback)
            prompt_hash = sha256_bytes(prompt.encode("utf-8"))
            raw_event: dict[str, Any]
            try:
                event = _ollama_generate(
                    args.endpoint,
                    model=str(model["model_id"]),
                    prompt=prompt,
                    response_schema=contracts["response_schema"],
                    options=options,
                )
                last_raw = str(event["response"])
                response_hash = sha256_bytes(last_raw.encode("utf-8"))
                raw_event = {
                    "qid": qid,
                    "attempt": attempt,
                    "prompt_sha256": prompt_hash,
                    "response_sha256": response_hash,
                    "ollama": event,
                }
                _write_json(attempts_dir / f"{qid:04d}-attempt-{attempt}.json", raw_event)
                response_value = json.loads(last_raw)
                response_errors = json_schema_errors(
                    response_value, contracts["response_schema"]
                )
                if response_errors:
                    raise ModelGoldValidationError("; ".join(response_errors))
                if not isinstance(response_value, Mapping):
                    raise TypeError("model response must be an object")
                generation = _generation_metadata(
                    protocol,
                    prompt_hash=prompt_hash,
                    response_hash=response_hash,
                    attempt=attempt,
                )
                candidate_record = compile_model_response(row, response_value, generation)
                _validate_compiled(candidate_record, row, contracts)
                final_record = candidate_record
                break
            except Exception as exc:  # bounded retry captures transport + contract errors
                feedback = [f"{type(exc).__name__}: {exc}"]
                _write_json(
                    attempts_dir / f"{qid:04d}-attempt-{attempt}-error.json",
                    {
                        "qid": qid,
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:8000],
                    },
                )
        if final_record is None:
            final_prompt = _prompt(row, contracts, feedback)
            generation = _generation_metadata(
                protocol,
                prompt_hash=sha256_bytes(final_prompt.encode("utf-8")),
                response_hash=sha256_bytes(last_raw.encode("utf-8")),
                attempt=int(model["max_attempts"]),
            )
            final_record = generation_failure_record(row, generation, feedback[0])
            _validate_compiled(final_record, row, contracts)
        _write_json(record_path, final_record)
        completed += 1
        status = final_record["record_status"]
        elapsed = time.monotonic() - started
        print(
            f"[{position}/{len(targets)}] qid={qid} status={status} "
            f"elapsed={elapsed:.1f}s",
            flush=True,
        )
    all_records = [_read_json(path) for path in sorted(records_dir.glob("*.json"))]
    _write_atomic(work_dir / "gold.generated.jsonl", canonical_jsonl_bytes(all_records))
    summary = {
        "kind": "text2pandas.model_semantic_gold_v1_generation",
        "release_id": RELEASE_ID,
        "completed_at": _utc_now(),
        "targeted_this_invocation": len(targets),
        "generated_this_invocation": completed,
        "cached_this_invocation": skipped,
        "records_present": len(all_records),
        "status_counts": dict(sorted(Counter(row["record_status"] for row in all_records).items())),
        "selection": selection_info,
        "contract_sha256": contracts["hashes"],
        "model": dict(model),
    }
    _write_json(work_dir / "generation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


def _validate_work(
    protocol: Mapping[str, Any],
    work_dir: Path,
    selection: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records_dir = work_dir / "records"
    records = [_read_json(path) for path in sorted(records_dir.glob("*.json"))]
    expected = {int(row["qid"]): row for row in selection}
    actual = {int(row["qid"]): row for row in records}
    duplicates = len(actual) != len(records)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    failures: dict[str, str] = {}
    if duplicates:
        failures["duplicate_qids"] = "duplicate QID in generated records"
    if missing:
        failures["missing_qids"] = str(missing)
    if extra:
        failures["extra_qids"] = str(extra)
    for qid in sorted(set(expected) & set(actual)):
        try:
            _validate_compiled(actual[qid], expected[qid], contracts)
        except Exception as exc:
            failures[str(qid)] = str(exc)
    passed = not failures and len(records) == protocol["target_set"]["expected_records"]
    report = {
        "kind": "text2pandas.model_semantic_gold_v1_validation",
        "release_id": RELEASE_ID,
        "passed": passed,
        "expected_records": protocol["target_set"]["expected_records"],
        "validated_records": len(records),
        "failed_records": len(failures),
        "missing_qids": missing,
        "extra_qids": extra,
        "failures": failures,
        "status_counts": dict(sorted(Counter(row.get("record_status") for row in records).items())),
        "forbidden_fields": "PASS" if passed else "SEE_FAILURES",
        "schema_validation": "PASS" if passed else "FAIL",
        "semantic_validation": "PASS" if passed else "FAIL",
    }
    _write_json(work_dir / "validation_report.json", report)
    if not passed:
        raise ModelGoldValidationError(json.dumps(report, ensure_ascii=False))
    ordered = [actual[qid] for qid in sorted(expected)]
    _write_atomic(work_dir / "gold.validated.jsonl", canonical_jsonl_bytes(ordered))
    return ordered, report


def validate(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol).resolve()
    protocol = _protocol(protocol_path)
    protocol["_path"] = str(protocol_path)
    selection, _ = _load_selection(protocol)
    contracts = _load_contracts(protocol)
    _, report = _validate_work(protocol, Path(args.work_dir).resolve(), selection, contracts)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _canonicalize_work(
    work_dir: Path, records: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    frames = [canonicalize_record(record) for record in records]
    first = canonical_jsonl_bytes(frames)
    second = canonical_jsonl_bytes([canonicalize_record(record) for record in records])
    if first != second:
        raise ModelGoldValidationError("canonicalization is not byte-identical")
    _write_atomic(work_dir / "canonical_frames.jsonl", first)
    report = {
        "kind": "text2pandas.model_semantic_gold_v1_canonicalization",
        "release_id": RELEASE_ID,
        "passed": True,
        "records": len(frames),
        "byte_identical_replay": True,
        "canonical_sha256": sha256_bytes(first),
    }
    _write_json(work_dir / "canonicalization_report.json", report)
    return frames, report


def canonicalize(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol).resolve()
    protocol = _protocol(protocol_path)
    protocol["_path"] = str(protocol_path)
    selection, _ = _load_selection(protocol)
    contracts = _load_contracts(protocol)
    work_dir = Path(args.work_dir).resolve()
    records, _ = _validate_work(protocol, work_dir, selection, contracts)
    _, report = _canonicalize_work(work_dir, records)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


def _coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_cohort: dict[str, Counter[str]] = {}
    operations: Counter[str] = Counter()
    tags: Counter[str] = Counter()

    def collect_ops(raw: object) -> None:
        if not isinstance(raw, Mapping):
            return
        operations[str(raw.get("node"))] += 1
        children = raw.get("children", [])
        if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
            for child in children:
                collect_ops(child)

    for record in records:
        cohort = str(record["cohort"])
        by_cohort.setdefault(cohort, Counter())[str(record["record_status"])] += 1
        for tag in record.get("secondary_tags", []):
            tags[str(tag)] += 1
        collect_ops(record.get("operation_tree"))
    return {
        "release_id": RELEASE_ID,
        "total_records": len(records),
        "by_cohort_and_status": {
            cohort: dict(sorted(counts.items())) for cohort, counts in sorted(by_cohort.items())
        },
        "status_counts": dict(sorted(Counter(str(row["record_status"]) for row in records).items())),
        "status_reason_counts": dict(sorted(Counter(str(row["status_reason"]) for row in records).items())),
        "operation_node_counts": dict(sorted(operations.items())),
        "selection_tag_counts": dict(sorted(tags.items())),
        "not_measured": [
            "retrieval_accuracy",
            "binding_accuracy",
            "numeric_answer_accuracy",
            "execution_accuracy",
        ],
    }


def _git_identity() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    return commit, dirty


def seal(args: argparse.Namespace) -> int:
    protocol_path = Path(args.protocol).resolve()
    protocol = _protocol(protocol_path)
    protocol["_path"] = str(protocol_path)
    selection, selection_info = _load_selection(protocol)
    contracts = _load_contracts(protocol)
    work_dir = Path(args.work_dir).resolve()
    records, validation_report = _validate_work(
        protocol, work_dir, selection, contracts
    )
    frames, canonical_report = _canonicalize_work(work_dir, records)
    compatibility = evaluate_canonical_predictions(frames, frames)
    compatibility_report = {
        "contract_id": contracts["evaluation"]["contract_id"],
        "self_replay_passed": all(
            metric.accuracy == 1.0 for metric in compatibility.metrics.values()
        ),
        "metrics": {
            name: {
                "passed": metric.passed,
                "total": metric.total,
                "accuracy": metric.accuracy,
            }
            for name, metric in compatibility.metrics.items()
        },
        "explicitly_not_measured": contracts["evaluation"]["explicitly_not_measured"],
    }
    if not compatibility_report["self_replay_passed"]:
        raise ModelGoldValidationError("evaluator compatibility self-replay failed")

    release_path = Path(args.release).resolve()
    configured_release = _repo_path(protocol["release"]["output"], "release.output")
    if release_path != configured_release:
        raise ValueError(f"release path must equal frozen contract: {configured_release}")
    if release_path.exists():
        raise FileExistsError(f"sealed release already exists: {release_path}")
    release_path.parent.mkdir(parents=True, exist_ok=True)
    temp = release_path.parent / f".{release_path.name}.tmp-{uuid.uuid4().hex}"
    temp.mkdir()
    try:
        gold_bytes = canonical_jsonl_bytes(records)
        canonical_bytes = canonical_jsonl_bytes(frames)
        _write_atomic(temp / "gold.jsonl", gold_bytes)
        _write_atomic(temp / "canonical_frames.jsonl", canonical_bytes)
        coverage = _coverage(records)
        _write_json(temp / "coverage_matrix.json", coverage)
        _write_json(temp / "evaluator_compatibility.json", compatibility_report)
        contracts_dir = temp / "contracts"
        contracts_dir.mkdir()
        for name, release_name in CONTRACT_RELEASE_NAMES.items():
            shutil.copy2(contracts["paths"][name], contracts_dir / release_name)
        shutil.copy2(protocol_path, contracts_dir / "protocol.yaml")
        shutil.copy2(
            contracts["metric_base_path"], contracts_dir / "metric_vocabulary_base.yaml"
        )
        commit, dirty = _git_identity()
        generation_summary = _read_json(work_dir / "generation_summary.json")
        model = dict(protocol["model"])
        manifest = {
            "schema_version": 1,
            "kind": "text2pandas.model_semantic_gold_release",
            "release_id": RELEASE_ID,
            "status": protocol["release"]["status"],
            "gold_mode": "MODEL_GOLD",
            "annotation_source": "LLM",
            "human_review": False,
            "cross_model_review": False,
            "official_human_gold": False,
            "model": model,
            "model_identity": {
                "served_model": model["model_id"],
                "upstream_model": model["upstream_model_id"],
                "manifest_sha256": model["manifest_sha256"],
                "model_layer_sha256": model["model_layer_sha256"],
                "quantization": model["quantization"],
            },
            "prompt_version": PROMPT_VERSION,
            "prompt_template_sha256": contracts["hashes"]["prompt"],
            "semantic_schema": {
                "id": contracts["schema"].get("$id"),
                "version": 3,
                "title": contracts["schema"].get("title"),
            },
            "contract_sha256": contracts["hashes"],
            "question_source": selection_info["question_source"],
            "question_count": len(records),
            "selection": selection_info,
            "gold_sha256": sha256_bytes(gold_bytes),
            "canonical_frames_sha256": sha256_bytes(canonical_bytes),
            "tool_commit": commit,
            "tool_worktree_dirty_at_seal": dirty,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "ollama_endpoint": args.endpoint,
            },
            "generation_started_at": _read_json(work_dir / "generation_state.json")["started_at"],
            "generation_completed_at": generation_summary["completed_at"],
            "sealed_at": _utc_now(),
            "resolved_count": coverage["status_counts"].get("RESOLVED", 0),
            "ambiguous_count": coverage["status_counts"].get("AMBIGUOUS", 0),
            "unresolved_count": coverage["status_counts"].get("UNRESOLVED", 0),
            "validation": validation_report,
            "canonicalization": canonical_report,
            "evaluator_compatibility": {
                "self_replay_passed": compatibility_report["self_replay_passed"],
                "metric_count": len(compatibility_report["metrics"]),
            },
            "limitations": [
                "Model-generated development gold; not human-reviewed gold.",
                "No independent evidence binding, numeric answer, query, or execution truth.",
                "No retrieval, binding, numeric-answer, or execution accuracy is measured.",
            ],
        }
        _write_json(temp / "manifest.json", manifest)
        checksum_lines = []
        for path in sorted(item for item in temp.rglob("*") if item.is_file()):
            relative = path.relative_to(temp).as_posix()
            checksum_lines.append(f"{_sha256_file(path)}  {relative}\n")
        _write_atomic(temp / "checksums.sha256", "".join(checksum_lines).encode("utf-8"))
        os.replace(temp, release_path)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="generate_model_semantic_gold_v2")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--protocol", required=True)
    generate_parser.add_argument("--work-dir", required=True)
    generate_parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    generate_parser.add_argument("--limit", type=int)
    generate_parser.add_argument("--qids")
    generate_parser.set_defaults(handler=generate)

    for name, handler in (("validate", validate), ("canonicalize", canonicalize)):
        command = subparsers.add_parser(name)
        command.add_argument("--protocol", required=True)
        command.add_argument("--work-dir", required=True)
        command.set_defaults(handler=handler)

    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("--protocol", required=True)
    seal_parser.add_argument("--work-dir", required=True)
    seal_parser.add_argument("--release", required=True)
    seal_parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    seal_parser.set_defaults(handler=seal)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
