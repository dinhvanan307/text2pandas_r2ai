#!/usr/bin/env python3
"""Generate resumable question-only Wave 6 semantic drafts with local Ollama."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request

from text2pandas.application.usecases.independent_gold import canonical_jsonl
from text2pandas.application.usecases.semantic_parser_model_draft import (
    build_user_review_queue,
    compile_model_draft,
    generation_failure_draft,
    summarize_model_drafts,
)
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.source_identity import git_source_identity

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--qids", help="Optional comma-separated subset for controlled tests")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    return generate(args)


def generate(args: argparse.Namespace) -> int:
    protocol_path = args.protocol.expanduser().resolve()
    protocol = _json(protocol_path)
    _validate_protocol(protocol, protocol_path)
    scope_path = ROOT / str(_mapping(protocol["scope"], "scope")["path"])
    scope = _json(scope_path)
    rows = _scope_rows(scope, protocol, scope_path)
    prompt_path = ROOT / str(protocol["prompt"])
    schema_path = ROOT / str(protocol["response_schema"])
    prompt_template = prompt_path.read_text(encoding="utf-8").strip()
    response_schema = _json(schema_path)
    ontology = load_ontology()
    source = git_source_identity(ROOT)
    work_dir = args.work_dir.expanduser().resolve()
    state = _prepare_state(
        work_dir,
        protocol_path=protocol_path,
        protocol=protocol,
        scope_path=scope_path,
        prompt_path=prompt_path,
        schema_path=schema_path,
        ontology_fingerprint=ontology.fingerprint,
        source=source,
    )

    selected_qids: set[int] | None = None
    if args.qids:
        selected_qids = {int(value) for value in args.qids.split(",") if value.strip()}
        unknown = selected_qids - {int(row["qid"]) for row in rows}
        if unknown:
            raise ValueError(f"unknown selected QIDs: {sorted(unknown)}")
    targets = [row for row in rows if selected_qids is None or int(row["qid"]) in selected_qids]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("limit must be positive")
        targets = targets[: args.limit]

    model = _mapping(protocol["model"], "model")
    records_dir = work_dir / "records"
    attempts_dir = work_dir / "attempts"
    records_dir.mkdir(exist_ok=True)
    attempts_dir.mkdir(exist_ok=True)
    generated = 0
    cached = 0
    started = time.monotonic()
    for position, row in enumerate(targets, start=1):
        qid = int(row["qid"])
        record_path = records_dir / f"{qid:04d}.json"
        if record_path.exists():
            existing = _json(record_path)
            _validate_cached(existing, row, model)
            cached += 1
            print(f"[{position}/{len(targets)}] qid={qid} cached", flush=True)
            continue
        errors: list[str] = []
        final: dict[str, object] | None = None
        last_prompt_hash = ""
        last_response_hash = hashlib.sha256(b"").hexdigest()
        max_attempts = int(model["max_attempts"])
        for attempt in range(1, max_attempts + 1):
            prompt = _prompt(
                prompt_template,
                row,
                ontology_hints=_ontology_hints(str(row["question"]), ontology),
                validation_feedback=tuple(errors[-1:]),
            )
            last_prompt_hash = _sha256_text(prompt)
            try:
                event = _ollama_generate(
                    args.endpoint,
                    model=model,
                    prompt=prompt,
                    response_schema=response_schema,
                )
                raw_response = str(event["response"])
                last_response_hash = _sha256_text(raw_response)
                _write_json(
                    attempts_dir / f"{qid:04d}-attempt-{attempt}.json",
                    {
                        "qid": qid,
                        "attempt": attempt,
                        "prompt_sha256": last_prompt_hash,
                        "response_sha256": last_response_hash,
                        "ollama": event,
                    },
                )
                response = json.loads(raw_response)
                if not isinstance(response, Mapping):
                    raise TypeError("model response must be an object")
                generation = _generation_metadata(
                    model,
                    attempt=attempt,
                    prompt_sha256=last_prompt_hash,
                    response_sha256=last_response_hash,
                )
                final = compile_model_draft(row, response, generation)
                break
            except Exception as error:  # bounded transport, JSON and semantic retry
                detail = f"{type(error).__name__}: {error}"
                errors.append(detail)
                _write_json(
                    attempts_dir / f"{qid:04d}-attempt-{attempt}-error.json",
                    {"qid": qid, "attempt": attempt, "error": detail[:8000]},
                )
        if final is None:
            generation = _generation_metadata(
                model,
                attempt=max_attempts,
                prompt_sha256=last_prompt_hash,
                response_sha256=last_response_hash,
            )
            final = generation_failure_draft(
                row,
                generation,
                errors[-1] if errors else "unknown generation failure",
            )
        _write_json(record_path, final)
        generated += 1
        all_records = _records(records_dir)
        _materialize_outputs(work_dir, all_records)
        _update_state(state, work_dir, all_records)
        elapsed = time.monotonic() - started
        print(
            f"[{position}/{len(targets)}] qid={qid} "
            f"status={final['structural_status']} elapsed={elapsed:.1f}s",
            flush=True,
        )

    all_records = _records(records_dir)
    _materialize_outputs(work_dir, all_records)
    _update_state(state, work_dir, all_records, completed=True)
    summary = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_model_draft_generation",
        "status": "MODEL_DRAFT_PENDING_HUMAN_REVIEW",
        "targeted_this_invocation": len(targets),
        "generated_this_invocation": generated,
        "cached_this_invocation": cached,
        "source": source,
        "model": dict(model),
        "measurement": summarize_model_drafts(all_records),
        "outputs": {
            "model_draft.jsonl": {
                "sha256": sha256_file(work_dir / "model_draft.jsonl"),
                "records": len(all_records),
            },
            "user_review_queue.jsonl": {
                "sha256": sha256_file(work_dir / "user_review_queue.jsonl"),
                "records": len(all_records),
            },
        },
        "completed_at_utc": _utc_now(),
    }
    _write_json(work_dir / "generation_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


def _validate_protocol(protocol: Mapping[str, Any], protocol_path: Path) -> None:
    if protocol.get("kind") != "text2pandas.semantic_parser_wave6_model_draft_protocol":
        raise ValueError("unexpected model draft protocol kind")
    governance = _mapping(protocol.get("governance"), "governance")
    expected = {
        "question_only": True,
        "parser_predictions_allowed": False,
        "retrieval_outputs_allowed": False,
        "answers_allowed": False,
        "independent_human_gold": False,
        "runtime_use_allowed": False,
        "human_review_required": True,
    }
    if governance != expected:
        raise ValueError("model draft governance contract mismatch")
    for key in ("prompt", "response_schema"):
        path = ROOT / str(protocol[key])
        if not path.is_file():
            raise FileNotFoundError(f"missing {key}: {path}")
    model = _mapping(protocol.get("model"), "model")
    if model.get("model_id") != "qwen2.5:14b":
        raise ValueError("Wave 6 model draft protocol requires qwen2.5:14b")
    if not protocol_path.is_relative_to(ROOT):
        raise ValueError("protocol must live inside repository")


def _scope_rows(
    scope: Mapping[str, Any], protocol: Mapping[str, Any], scope_path: Path
) -> list[dict[str, Any]]:
    scope_contract = _mapping(protocol["scope"], "scope")
    if sha256_file(scope_path) != scope_contract["sha256"]:
        raise ValueError("scope checksum mismatch")
    rows = scope.get("records")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TypeError("scope records must be a list of objects")
    if len(rows) != int(scope_contract["records"]):
        raise ValueError("scope record count mismatch")
    qids = [int(row["qid"]) for row in rows]
    if len(qids) != len(set(qids)):
        raise ValueError("scope contains duplicate QIDs")
    return sorted(rows, key=lambda row: int(row["qid"]))


def _prepare_state(
    work_dir: Path,
    *,
    protocol_path: Path,
    protocol: Mapping[str, Any],
    scope_path: Path,
    prompt_path: Path,
    schema_path: Path,
    ontology_fingerprint: str,
    source: Mapping[str, object],
) -> dict[str, Any]:
    expected = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_parser_wave6_model_draft_state",
        "status": "IN_PROGRESS",
        "protocol_path": str(protocol_path.relative_to(ROOT)),
        "protocol_sha256": sha256_file(protocol_path),
        "scope_path": str(scope_path.relative_to(ROOT)),
        "scope_sha256": sha256_file(scope_path),
        "prompt_sha256": sha256_file(prompt_path),
        "response_schema_sha256": sha256_file(schema_path),
        "ontology_fingerprint": ontology_fingerprint,
        "model_id": _mapping(protocol["model"], "model")["model_id"],
        "model_digest": _mapping(protocol["model"], "model")["model_digest"],
        "source": dict(source),
    }
    state_path = work_dir / "generation_state.json"
    if state_path.exists():
        existing = _json(state_path)
        for key, value in expected.items():
            if key == "status":
                continue
            if existing.get(key) != value:
                raise ValueError(f"generation state mismatch for {key}; use a new work-dir")
        return existing
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        raise ValueError("new model draft generation requires a clean committed source tree")
    work_dir.mkdir(parents=True, exist_ok=False)
    expected.update(
        {
            "started_at_utc": _utc_now(),
            "completed_qids": [],
            "status_counts": {},
        }
    )
    _write_json(state_path, expected)
    return expected


def _prompt(
    template: str,
    row: Mapping[str, Any],
    *,
    ontology_hints: list[dict[str, object]],
    validation_feedback: tuple[str, ...],
) -> str:
    feedback = ""
    if validation_feedback:
        feedback = (
            "\n\nPREVIOUS ATTEMPT FAILED VALIDATION. Correct only these errors:\n- "
            + "\n- ".join(validation_feedback)
        )
    payload = {
        "qid": row["qid"],
        "question": row["question"],
        "question_sha256": row["question_sha256"],
        "ontology_hints": ontology_hints,
    }
    return template + "\n\nINPUT:\n" + json.dumps(payload, ensure_ascii=False) + feedback


def _ontology_hints(question: str, ontology: Any) -> list[dict[str, object]]:
    normalized = normalize_phrase(question)
    candidates: list[tuple[int, str, dict[str, object]]] = []
    for metric in ontology.metrics.values():
        for alias in metric.aliases:
            if alias and alias in normalized:
                candidates.append(
                    (
                        len(alias),
                        metric.metric_id,
                        {
                            "kind": "metric",
                            "id": metric.metric_id,
                            "matched_alias": alias,
                            "dimension": metric.unit.dimension.value,
                            "period_semantics": metric.period_semantics.value,
                        },
                    )
                )
    for formula in ontology.formulas.values():
        for alias in formula.aliases:
            if alias and alias in normalized:
                candidates.append(
                    (
                        len(alias),
                        formula.formula_id,
                        {
                            "kind": "formula",
                            "id": formula.formula_id,
                            "matched_alias": alias,
                            "dimension": formula.output_unit.dimension.value,
                            "leaf_metric_ids": list(formula.leaves),
                        },
                    )
                )
    output: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for _, identifier, value in sorted(candidates, key=lambda item: (-item[0], item[1])):
        key = (str(value["kind"]), identifier)
        if key not in seen:
            seen.add(key)
            output.append(value)
        if len(output) >= 24:
            break
    return output


def _ollama_generate(
    endpoint: str,
    *,
    model: Mapping[str, Any],
    prompt: str,
    response_schema: Mapping[str, Any],
) -> dict[str, Any]:
    payload = {
        "model": model["model_id"],
        "prompt": prompt,
        "stream": False,
        "format": response_schema,
        "options": {
            "temperature": model["temperature"],
            "top_p": model["top_p"],
            "seed": model["seed"],
            "num_ctx": model["num_ctx"],
            "num_predict": model["num_predict"],
        },
        "keep_alive": model["keep_alive"],
    }
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=900) as response:
            event = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Ollama generation request failed: {error}") from error
    if not isinstance(event, dict) or not isinstance(event.get("response"), str):
        raise RuntimeError("Ollama response lacks response text")
    return event


def _generation_metadata(
    model: Mapping[str, Any],
    *,
    attempt: int,
    prompt_sha256: str,
    response_sha256: str,
) -> dict[str, object]:
    return {
        "annotation_source": "LLM",
        "model_id": model["model_id"],
        "model_digest": model["model_digest"],
        "attempt_count": attempt,
        "prompt_sha256": prompt_sha256,
        "response_sha256": response_sha256,
        "human_review": False,
        "independent_gold": False,
    }


def _validate_cached(
    record: Mapping[str, Any], row: Mapping[str, Any], model: Mapping[str, Any]
) -> None:
    if record.get("qid") != row.get("qid"):
        raise ValueError("cached record QID mismatch")
    if record.get("question_sha256") != row.get("question_sha256"):
        raise ValueError(f"cached question checksum mismatch: {row.get('qid')}")
    generation = _mapping(record.get("generation"), "generation")
    if generation.get("model_id") != model["model_id"]:
        raise ValueError(f"cached model mismatch: {row.get('qid')}")
    if record.get("independent_human_gold") is not False:
        raise ValueError(f"cached draft has invalid gold claim: {row.get('qid')}")


def _records(records_dir: Path) -> list[dict[str, Any]]:
    records = [_json(path) for path in sorted(records_dir.glob("*.json"))]
    qids = [int(record["qid"]) for record in records]
    if len(qids) != len(set(qids)):
        raise ValueError("duplicate generated QIDs")
    return records


def _materialize_outputs(work_dir: Path, records: list[dict[str, Any]]) -> None:
    _write_atomic(work_dir / "model_draft.jsonl", canonical_jsonl(records))
    _write_atomic(
        work_dir / "user_review_queue.jsonl",
        canonical_jsonl(build_user_review_queue(records)),
    )


def _update_state(
    state: dict[str, Any],
    work_dir: Path,
    records: list[dict[str, Any]],
    *,
    completed: bool = False,
) -> None:
    state["status"] = "GENERATION_COMPLETE" if completed else "IN_PROGRESS"
    state["completed_qids"] = sorted(int(record["qid"]) for record in records)
    state["status_counts"] = dict(
        sorted(Counter(str(record["structural_status"]) for record in records).items())
    )
    state["updated_at_utc"] = _utc_now()
    _write_json(work_dir / "generation_state.json", state)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return dict(value)


def _write_json(path: Path, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _write_atomic(path, payload)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
