"""Run deterministic Phase 1.5 WP3-WP10 in LOCAL_SYNTHETIC mode twice."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from text2pandas.application.usecases.semantic_gold_v2 import (
    SEMANTIC_COMPONENT_FIELDS,
    canonical_packet_jsonl,
    canonical_semantic_frame,
    validate_annotation_record,
)
from text2pandas.application.usecases.semantic_gold_v2_local import (
    LOCAL_PROVENANCE,
    LOCAL_SYNTHETIC,
    build_local_synthetic_annotation,
    evaluate_local_predictions,
    export_canonical_v2_prediction,
    metric_concept_ids,
    validate_json_schema_instance,
    validate_local_provenance,
)
from text2pandas.pipelines.retrieval.alias_store import (
    alias_artifact_sha256,
    load_aliases,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "artifacts"
REPORT_ROOT = ROOT / "docs" / "reports"
LOCAL_CONFIG = ROOT / "configs/evaluation/semantic_gold_v2_local_synthetic.yaml"
PROTOCOL = ROOT / "configs/evaluation/semantic_gold_v2_protocol.yaml"

DETERMINISTIC_ASSETS = (
    "selected_qids.json",
    "annotator_local.jsonl",
    "canonical_gold_frames.jsonl",
    "parser_predictions.jsonl",
    "canonical_prediction_frames.jsonl",
    "metrics.json",
    "failure_taxonomy.jsonl",
    "resolver_boundary.json",
    "validation.json",
    "workflow.json",
    "protected_surface.json",
    "manifest.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", default=os.environ.get("SEMANTIC_GOLD_V2_MODE")
    )
    parser.add_argument("--packet", required=True)
    parser.add_argument("--run-a", required=True)
    parser.add_argument("--run-b", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--include-reserve", action="store_true")
    args = parser.parse_args()

    if args.mode != LOCAL_SYNTHETIC:
        raise ValueError(
            "local E2E requires --mode LOCAL_SYNTHETIC or "
            "SEMANTIC_GOLD_V2_MODE=LOCAL_SYNTHETIC"
        )
    packet = _artifact_dir(args.packet, must_exist=True)
    run_a = _artifact_dir(args.run_a, must_exist=False)
    run_b = _artifact_dir(args.run_b, must_exist=False)
    if run_a == run_b:
        raise ValueError("run-a and run-b must be distinct output directories")
    report = _report_path(args.report)

    context = _load_context(packet, include_reserve=args.include_reserve)
    manifest_a = _build_run(run_a, context)
    manifest_b = _build_run(run_b, context)
    determinism = _compare_runs(run_a, run_b)
    report.write_bytes(
        _render_report(run_a, run_b, manifest_a, manifest_b, determinism)
    )
    print(
        json.dumps(
            {
                "mode": LOCAL_SYNTHETIC,
                "run_a": str(run_a.relative_to(ROOT)),
                "run_b": str(run_b.relative_to(ROOT)),
                "report": str(report.relative_to(ROOT)),
                "E2E_DETERMINISM": determinism["status"],
                "official_submission_ready": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _load_context(packet: Path, *, include_reserve: bool) -> dict[str, object]:
    local_config = _yaml_mapping(LOCAL_CONFIG)
    if local_config.get("mode") != LOCAL_SYNTHETIC:
        raise ValueError("local synthetic config mode mismatch")
    provenance = _mapping(local_config.get("provenance"), "local provenance")
    validate_local_provenance(provenance)
    scope = _mapping(local_config.get("scope"), "local scope")
    if scope.get("official_release_allowed") is not False:
        raise ValueError("LOCAL_SYNTHETIC must forbid official releases")
    if scope.get("official_registry_update_allowed") is not False:
        raise ValueError("LOCAL_SYNTHETIC must forbid official registry updates")

    packet_manifest = _json_mapping(packet / "manifest.json")
    if packet_manifest.get("kind") != "text2pandas.semantic_gold_v2_annotation_packet":
        raise ValueError("input is not a Semantic Gold v2 annotation packet")
    if packet_manifest.get("status") != "OPEN_FOR_INDEPENDENT_REVIEW":
        raise ValueError("source packet must remain OPEN_FOR_INDEPENDENT_REVIEW")
    if packet_manifest.get("model_outputs_included") is not False:
        raise ValueError("source packet is not prediction-blind")

    protocol = _yaml_mapping(PROTOCOL)
    contracts = _mapping(protocol.get("contracts"), "protocol contracts")
    contract_files = {
        name: _repo_file(str(path)) for name, path in contracts.items()
    }
    packet_contracts = _mapping(packet_manifest.get("contracts"), "packet contracts")
    for name, path in contract_files.items():
        expected = _text(
            _mapping(packet_contracts.get(name), f"packet contract:{name}").get(
                "sha256"
            ),
            f"packet contract sha:{name}",
        )
        _verify_sha(path.read_bytes(), expected, f"contract:{name}")

    selection_names = ["selection_core.jsonl", "selection_diagnostic.jsonl"]
    if include_reserve:
        if scope.get("reserve_supported") is not True:
            raise ValueError("local mode does not permit reserve activation")
        selection_names.append("selection_reserve.jsonl")
    selected: list[dict[str, object]] = []
    packet_assets = _mapping(packet_manifest.get("assets"), "packet assets")
    for name in selection_names:
        content = (packet / name).read_bytes()
        expected = _text(
            _mapping(packet_assets.get(name), f"packet asset:{name}").get("sha256"),
            f"packet asset sha:{name}",
        )
        _verify_sha(content, expected, f"packet asset:{name}")
        selected.extend(_jsonl(packet / name))
    counts = Counter(str(row.get("cohort")) for row in selected)
    if counts["HEADLINE_CORE"] != 100 or counts["DIAGNOSTIC_SUPPLEMENT"] != 20:
        raise ValueError(f"local active cohort counts differ from 100/20: {counts}")
    if include_reserve and counts["RESERVE"] != 30:
        raise ValueError("reserve activation requires exactly 30 records")
    qids = [_qid(row) for row in selected]
    if len(qids) != len(set(qids)):
        raise ValueError("selected cohorts overlap")

    metric_vocabulary = _yaml_mapping(contract_files["metric_vocabulary"])
    concept_ids = metric_concept_ids(metric_vocabulary)
    review = _mapping(protocol.get("review"), "protocol review")
    contract_hashes = {
        "guideline_version": _text(
            review.get("guideline_version"), "guideline version"
        ),
        "guideline_sha256": _sha256(contract_files["guideline"].read_bytes()),
        "metric_vocabulary_sha256": _sha256(
            contract_files["metric_vocabulary"].read_bytes()
        ),
        "operation_vocabulary_sha256": _sha256(
            contract_files["operation_vocabulary"].read_bytes()
        ),
    }
    implementation = _implementation_fingerprint(contract_files)
    protected_before = _protected_snapshot(protocol)
    return {
        "packet": packet,
        "packet_manifest": packet_manifest,
        "protocol": protocol,
        "local_config": local_config,
        "contract_files": contract_files,
        "contract_hashes": contract_hashes,
        "metric_vocabulary": metric_vocabulary,
        "metric_concept_ids": sorted(concept_ids),
        "selected": selected,
        "include_reserve": include_reserve,
        "implementation": implementation,
        "protected_before": protected_before,
    }


def _build_run(output: Path, context: Mapping[str, object]) -> dict[str, object]:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=False, exist_ok=False)
    selected = [
        dict(_mapping(row, "selected row"))
        for row in _sequence(context.get("selected"), "selected rows")
    ]
    aliases = load_aliases("a6")
    metric_vocabulary = _mapping(
        context.get("metric_vocabulary"), "metric vocabulary"
    )
    contract_hashes = {
        str(key): str(value)
        for key, value in _mapping(
            context.get("contract_hashes"), "contract hashes"
        ).items()
    }
    implementation = _mapping(context.get("implementation"), "implementation")
    fingerprint = _text(
        implementation.get("sha256"), "implementation fingerprint"
    )
    annotations = [
        build_local_synthetic_annotation(
            row,
            aliases=aliases,
            metric_vocabulary=metric_vocabulary,
            contract_hashes=contract_hashes,
        ).annotation
        for row in selected
    ]
    predictions = [
        export_canonical_v2_prediction(
            row,
            aliases=aliases,
            metric_vocabulary=metric_vocabulary,
            contract_hashes=contract_hashes,
            implementation_fingerprint=fingerprint,
        )
        for row in selected
    ]
    validation = _validate_generated(context, annotations, predictions)
    gold_frames = [
        {
            "qid": _qid(row),
            "cohort": row["cohort"],
            "canonical_frame": canonical_semantic_frame(row),
        }
        for row in annotations
    ]
    prediction_frames = [
        {
            "qid": _qid(row),
            "cohort": row["cohort"],
            "canonical_frame": row["canonical_frame"],
        }
        for row in predictions
    ]
    metrics, failures = evaluate_local_predictions(annotations, predictions)
    resolver_boundary = {
        "schema_version": 1,
        **LOCAL_PROVENANCE,
        "failure_boundaries": _mapping(
            _mapping(metrics["failure_summary"], "failure summary").get(
                "boundary_counts"
            ),
            "boundary counts",
        ),
        "metric_resolver_accuracy": "NOT_MEASURABLE",
        "selector_binder_accuracy": "NOT_MEASURABLE",
        "downstream_answer_accuracy": "NOT_MEASURABLE",
        "reason": (
            "LOCAL_SYNTHETIC has no independent binding, answer, or evidence labels; "
            "VAS hints are not promoted to metric concepts"
        ),
    }
    workflow = _workflow()
    protected_after = _protected_snapshot(
        _mapping(context.get("protocol"), "protocol")
    )
    protected_before = _mapping(
        context.get("protected_before"), "protected before"
    )
    if protected_before.get("assets") != protected_after.get("assets"):
        raise ValueError("protected surface changed during LOCAL_SYNTHETIC run")
    protected = {
        "schema_version": 1,
        "policy": "target_commit_equals_before_equals_after_byte_for_byte",
        "target_parser_commit": protected_before["target_parser_commit"],
        "before": protected_before,
        "after": protected_after,
        "byte_identical": True,
    }
    selected_document = {
        "schema_version": 1,
        "headline_core": sorted(
            _qid(row) for row in selected if row.get("cohort") == "HEADLINE_CORE"
        ),
        "diagnostic_supplement": sorted(
            _qid(row)
            for row in selected
            if row.get("cohort") == "DIAGNOSTIC_SUPPLEMENT"
        ),
        "reserve": sorted(
            _qid(row) for row in selected if row.get("cohort") == "RESERVE"
        ),
    }
    assets: dict[str, bytes] = {
        "selected_qids.json": _canonical_json(selected_document),
        "annotator_local.jsonl": canonical_packet_jsonl(annotations),
        "canonical_gold_frames.jsonl": canonical_packet_jsonl(gold_frames),
        "parser_predictions.jsonl": canonical_packet_jsonl(predictions),
        "canonical_prediction_frames.jsonl": canonical_packet_jsonl(
            prediction_frames
        ),
        "metrics.json": _canonical_json(metrics),
        "failure_taxonomy.jsonl": canonical_packet_jsonl(failures),
        "resolver_boundary.json": _canonical_json(resolver_boundary),
        "validation.json": _canonical_json(validation),
        "workflow.json": _canonical_json(workflow),
        "protected_surface.json": _canonical_json(protected),
    }
    packet = Path(str(context["packet"]))
    packet_manifest = _mapping(context.get("packet_manifest"), "packet manifest")
    protocol = _mapping(context.get("protocol"), "protocol")
    target_parser = _mapping(protocol.get("target_parser"), "target parser")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_gold_v2_local_synthetic_e2e",
        "status": "LOCAL_E2E_VALIDATED",
        **LOCAL_PROVENANCE,
        "purpose": "LOCAL_END_TO_END_PIPELINE_VALIDATION",
        "official_release_created": False,
        "official_registry_updated": False,
        "source_packet": {
            "path": str(packet.relative_to(ROOT)),
            "manifest_sha256": _sha256((packet / "manifest.json").read_bytes()),
            "selection_manifest_sha256": _sha256(
                _canonical_json(packet_manifest.get("selection"))
            ),
            "source_status": packet_manifest.get("status"),
        },
        "target_parser": dict(target_parser),
        "implementation": dict(implementation),
        "alias_artifacts_sha256": alias_artifact_sha256("a6"),
        "selection": {
            "headline_core_records": len(selected_document["headline_core"]),
            "diagnostic_records": len(selected_document["diagnostic_supplement"]),
            "reserve_records": len(selected_document["reserve"]),
        },
        "validation": validation,
        "workflow": workflow,
        "protected_surface": {
            "byte_identical": True,
            "sha256": _sha256(assets["protected_surface.json"]),
        },
        "environment": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "UNSET"),
            "tz": os.environ.get("TZ", "UNSET"),
            "locale": os.environ.get("LC_ALL", "UNSET"),
        },
        "invocation_contract": {
            "mode": LOCAL_SYNTHETIC,
            "packet": str(packet.relative_to(ROOT)),
            "output": "<EXPLICIT_ARTIFACT_OUTPUT>",
            "include_reserve": bool(context.get("include_reserve")),
        },
        "local_blockers": [],
        "official_submission_blockers": [
            "INDEPENDENT_ANNOTATOR_A_UNASSIGNED",
            "INDEPENDENT_ANNOTATOR_B_UNASSIGNED",
            "DISTINCT_ADJUDICATOR_C_UNASSIGNED",
            "NO_HUMAN_ADJUDICATION",
            "SYNTHETIC_REFERENCE_NOT_OFFICIAL_GOLD",
        ],
        "assets": {
            name: {
                "sha256": _sha256(content),
                **(
                    {"records": len(_jsonl_bytes(content))}
                    if name.endswith(".jsonl")
                    else {}
                ),
            }
            for name, content in sorted(assets.items())
        },
    }
    for name, content in assets.items():
        (output / name).write_bytes(content)
    (output / "manifest.json").write_bytes(_canonical_json(manifest))
    return manifest


def _validate_generated(
    context: Mapping[str, object],
    annotations: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    contract_files = _mapping(context.get("contract_files"), "contract files")
    schema_path = Path(str(contract_files["schema"]))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    concept_ids = frozenset(
        str(value)
        for value in _sequence(context.get("metric_concept_ids"), "concept ids")
    )
    canonical_frames = 0
    resolved_concepts = 0
    for record in annotations:
        validate_json_schema_instance(record, schema)
        validate_annotation_record(record, require_complete=True)
        canonical_semantic_frame(record)
        canonical_frames += 1
        for metric in _rows(record.get("metrics"), "metrics"):
            if metric.get("concept_status") == "RESOLVED":
                concept_id = str(metric.get("concept_id"))
                if concept_id not in concept_ids:
                    raise ValueError(
                        f"resolved concept absent from vocabulary: {concept_id}"
                    )
                resolved_concepts += 1
    if len(predictions) != len(annotations):
        raise ValueError("prediction record count differs from annotations")
    if {_qid(row) for row in predictions} != {_qid(row) for row in annotations}:
        raise ValueError("prediction QID set differs from annotations")
    status_counts = Counter(str(row["record_status"]) for row in annotations)
    return {
        "schema": "PASS",
        "unicode_nfc": "PASS",
        "span_occurrence_ordering": "PASS",
        "reference_integrity": "PASS",
        "operation_operand_closure": "PASS",
        "basis_contract": "PASS",
        "unit_scale_contract": "PASS",
        "canonical_frame_derivation": "PASS",
        "vocabulary_membership": "PASS",
        "records": len(annotations),
        "resolved_records": status_counts["RESOLVED"],
        "unresolved_records": status_counts["UNRESOLVED"],
        "ambiguous_records": status_counts["AMBIGUOUS"],
        "canonical_frames": canonical_frames,
        "resolved_metric_mentions": resolved_concepts,
    }


def _workflow() -> dict[str, object]:
    return {
        "schema_version": 1,
        **LOCAL_PROVENANCE,
        "wp3": {
            "status": "PASS_LOCAL_SYNTHETIC_EQUIVALENT",
            "action": "deterministic contract calibration and schema validation",
        },
        "wp4": {
            "status": "PASS_LOCAL_SYNTHETIC_EQUIVALENT",
            "action": "single automated annotation over active 100+20 cohorts",
        },
        "wp5": {
            "status": "COMPLETED_AS_NOT_APPLICABLE",
            "action": "human inter-annotator agreement not fabricated",
        },
        "wp6": {
            "status": "COMPLETED_AS_NOT_APPLICABLE",
            "action": "human adjudication not fabricated",
        },
        "wp7": {
            "status": "PASS_LOCAL_ARTIFACT_FROZEN",
            "action": "local checksummed artifact only; no official SEALED release",
        },
        "wp8": {
            "status": "PASS",
            "action": "Canonical V2 effective public pre-bind prediction export",
        },
        "wp9": {
            "status": "PASS",
            "action": "strict metrics, Wilson CI, taxonomy, boundary attribution",
        },
        "wp10": {
            "status": "PASS",
            "action": "local-only decision report generated",
        },
    }


def _protected_snapshot(protocol: Mapping[str, object]) -> dict[str, object]:
    target_parser = _mapping(protocol.get("target_parser"), "target parser")
    commit = _text(target_parser.get("source_commit"), "target parser commit")
    paths = [
        _text(value, "protected path")
        for value in _sequence(protocol.get("protected_surface"), "protected surface")
    ]
    assets: list[dict[str, object]] = []
    for relative in paths:
        current = _repo_file(relative).read_bytes()
        target = subprocess.run(
            ["git", "show", f"{commit}:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if current != target:
            raise ValueError(
                f"PRODUCTION_CHANGE_REQUIRED: protected file differs: {relative}"
            )
        assets.append(
            {
                "path": relative,
                "sha256": _sha256(current),
                "size": len(current),
            }
        )
    return {
        "authority": "LOCAL_SYNTHETIC_WORKTREE",
        "target_parser_commit": commit,
        "assets": sorted(assets, key=lambda row: str(row["path"])),
        "matches_target_commit": True,
    }


def _implementation_fingerprint(
    contract_files: Mapping[str, object]
) -> dict[str, object]:
    relative_paths = (
        "src/text2pandas/application/usecases/semantic_gold_v2.py",
        "src/text2pandas/application/usecases/semantic_gold_v2_local.py",
        "tools/evaluation/run_semantic_gold_v2_local_e2e.py",
        "configs/evaluation/semantic_gold_v2_local_synthetic.yaml",
        "src/text2pandas/pipelines/retrieval/question_intent.py",
        "src/text2pandas/pipelines/retrieval/metric_hint.py",
        "src/text2pandas/pipelines/answering/adapters.py",
        "src/text2pandas/pipelines/answering/frame.py",
        "src/text2pandas/pipelines/answering/router.py",
        "src/text2pandas/pipelines/answering/ir.py",
    )
    assets = [
        {"path": relative, "sha256": _sha256(_repo_file(relative).read_bytes())}
        for relative in relative_paths
    ]
    for name in ("schema", "metric_vocabulary", "operation_vocabulary"):
        path = Path(str(contract_files[name]))
        assets.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path.read_bytes()),
            }
        )
    assets.sort(key=lambda row: str(row["path"]))
    return {
        "sha256": _sha256(_canonical_json(assets)),
        "assets": assets,
        "source_commit": _git_head(),
    }


def _compare_runs(run_a: Path, run_b: Path) -> dict[str, object]:
    comparisons: list[dict[str, object]] = []
    for name in DETERMINISTIC_ASSETS:
        left = (run_a / name).read_bytes()
        right = (run_b / name).read_bytes()
        same = left == right
        comparisons.append(
            {
                "asset": name,
                "run_a_sha256": _sha256(left),
                "run_b_sha256": _sha256(right),
                "byte_identical": same,
            }
        )
    failed = [row["asset"] for row in comparisons if not row["byte_identical"]]
    if failed:
        raise ValueError(f"E2E_DETERMINISM=FAIL assets={failed}")
    return {
        "status": "PASS",
        "compared_assets": len(comparisons),
        "comparisons": comparisons,
    }


def _render_report(
    run_a: Path,
    run_b: Path,
    manifest_a: Mapping[str, object],
    manifest_b: Mapping[str, object],
    determinism: Mapping[str, object],
) -> bytes:
    del manifest_b
    metrics = _json_mapping(run_a / "metrics.json")
    validation = _mapping(manifest_a.get("validation"), "manifest validation")
    status_distribution = _mapping(
        metrics.get("status_distribution"), "status distribution"
    )
    field_status_distribution = _mapping(
        metrics.get("field_status_distribution"), "field status distribution"
    )
    failure_summary = _mapping(metrics.get("failure_summary"), "failure summary")
    views = _mapping(metrics.get("views"), "metric views")
    headline = _mapping(views.get("HEADLINE_CORE"), "headline view")
    diagnostic = _mapping(
        views.get("DIAGNOSTIC_SUPPLEMENT"), "diagnostic view"
    )
    diagnostic_strata = _mapping(
        metrics.get("diagnostic_strata"), "diagnostic strata"
    )
    comparisons = _sequence(determinism.get("comparisons"), "comparisons")
    lines = [
        "# PHASE 1.5 Semantic Gold V2 — LOCAL_SYNTHETIC E2E Report",
        "",
        "> [!WARNING]",
        "> Evaluation mode: **LOCAL_SYNTHETIC**. Independent human annotation: "
        "**NOT PERFORMED**. Independent adjudication: **NOT PERFORMED**. "
        "Official submission validity: **NOT VALID**. Purpose: "
        "**LOCAL END-TO-END PIPELINE VALIDATION**.",
        "",
        "## 1. Executive Summary",
        "",
        "WP3–WP10 đã chạy hết bằng nhánh local riêng, không thay đổi production "
        "parser và không ghi synthetic data vào official gold registry. Local E2E "
        "đạt gate schema/provenance/determinism/protected-surface; kết quả accuracy "
        "chỉ mô tả hành vi so với automated ontology-derived reference.",
        "",
        f"- Local decision: `PASS_LOCAL_E2E_ONLY`",
        f"- E2E determinism: `{determinism['status']}` "
        f"({determinism['compared_assets']} artifacts byte-identical)",
        f"- Protected production surface: `PASS`, before == after == target commit",
        f"- Active records: `{validation['records']}`; resolved synthetic records: "
        f"`{validation['resolved_records']}`; unresolved: "
        f"`{validation['unresolved_records']}`",
        "- Official submission: `BLOCKED` until genuine independent A/B/C work replaces "
        "all automated annotations.",
        "",
        "## 2. Implementation and Files Changed",
        "",
        "Implemented a fail-closed local mode, deterministic ontology-exact synthetic "
        "annotator, honest Canonical V2 pre-bind exporter, strict evaluator, Wilson CI, "
        "failure taxonomy, parser/resolver boundary report, protected-surface verifier, "
        "and two-run orchestration.",
        "",
        "Tracked implementation files:",
        "",
        "- `configs/evaluation/semantic_gold_v2_local_synthetic.yaml`",
        "- `src/text2pandas/application/usecases/semantic_gold_v2_local.py`",
        "- `tools/evaluation/run_semantic_gold_v2_local_e2e.py`",
        "- `tests/unit/test_semantic_gold_v2_local.py`",
        "- `Makefile`",
        "- `docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_2026-08-29.md`",
        "",
        "Generated local artifacts:",
        "",
        f"- `{run_a.relative_to(ROOT)}`",
        f"- `{run_b.relative_to(ROOT)}`",
        "",
        "No artifact was written to `data/curated/gold/semantic_gold_v2`, and "
        "`gold_registry_v1.yaml` was not updated.",
        "",
        "## 3. Dataset, Provenance, and Validation",
        "",
        "```text",
        "gold_mode=LOCAL_SYNTHETIC",
        "annotation_source=AUTOMATED",
        "independent_review=false",
        "human_adjudication=false",
        "official_submission_ready=false",
        "```",
        "",
        f"Source packet: `{manifest_a['source_packet']['path']}`. Headline 100 and "
        "diagnostic 20 were used; reserve support is implemented but not activated.",
        "",
        "| Validation gate | Result |",
        "|---|---:|",
    ]
    for key in (
        "schema",
        "unicode_nfc",
        "span_occurrence_ordering",
        "reference_integrity",
        "operation_operand_closure",
        "basis_contract",
        "unit_scale_contract",
        "canonical_frame_derivation",
        "vocabulary_membership",
    ):
        lines.append(f"| {key} | {validation[key]} |")
    lines.extend(
        [
            "",
            "Synthetic status distribution: "
            + ", ".join(
                f"`{key}={value}`" for key, value in sorted(status_distribution.items())
            )
            + ". `UNRESOLVED` records are reported, never force-labeled.",
            "",
            "Field-level coverage:",
            "",
            "| Semantic field | RESOLVED | UNRESOLVED | NOT_APPLICABLE |",
            "|---|---:|---:|---:|",
        ]
    )
    for field in SEMANTIC_COMPONENT_FIELDS:
        counts = _mapping(field_status_distribution.get(field), f"field:{field}")
        lines.append(
            f"| {field} | {counts.get('RESOLVED', 0)} | "
            f"{counts.get('UNRESOLVED', 0)} | {counts.get('NOT_APPLICABLE', 0)} |"
        )
    lines.extend(
        [
            "",
            "## 4. WP3–WP10 Execution",
            "",
            "| WP | Local result | Exact substitute/action |",
            "|---|---|---|",
            "| WP3 | PASS_LOCAL_SYNTHETIC_EQUIVALENT | Contract calibration + full validation |",
            "| WP4 | PASS_LOCAL_SYNTHETIC_EQUIVALENT | One automated annotation pass over 100+20 |",
            "| WP5 | COMPLETED_AS_NOT_APPLICABLE | No fake human agreement metric |",
            "| WP6 | COMPLETED_AS_NOT_APPLICABLE | No fake human adjudication |",
            "| WP7 | PASS_LOCAL_ARTIFACT_FROZEN | Checksummed local artifact; not official SEALED gold |",
            "| WP8 | PASS | Frozen Canonical V2 public pre-bind export |",
            "| WP9 | PASS | Strict metrics + taxonomy + boundary attribution |",
            "| WP10 | PASS | This local-only decision report |",
            "",
            "## 5. Parser Metrics",
            "",
            "Strict metrics score only `record_status=RESOLVED`; `NOT_APPLICABLE` is "
            "excluded and an applicable missing prediction is wrong. These figures are "
            "not human-validated accuracy.",
            "",
            "### HEADLINE_CORE",
            "",
            _metric_table(headline),
            "",
            "### DIAGNOSTIC_SUPPLEMENT",
            "",
            _metric_table(diagnostic),
            "",
            "Canonical V2 correctly exposes entity/period/basis/unit/operation/role "
            "structure on the resolved synthetic subset, but it has no public pre-bind "
            "metric phrase/concept output. Therefore metric concept, operand metric, and "
            "full-frame exact scores are zero rather than being backfilled from VAS hints.",
            "",
            "## 6. Diagnostic-Stratum Performance",
            "",
            "| Stratum | Records | Resolved | Full-frame correct/scored | Accuracy |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for stratum, raw in sorted(diagnostic_strata.items()):
        item = _mapping(raw, f"stratum:{stratum}")
        full = _mapping(item.get("full_frame_exact"), "full frame")
        lines.append(
            f"| {stratum} | {item['records']} | {item['resolved_records']} | "
            f"{full['correct']}/{full['scored']} | {_format_accuracy(full['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## 7. Failure Taxonomy",
            "",
            f"Failed resolved QIDs: `{failure_summary['failed_qids']}`. Primary failures: "
            + ", ".join(
                f"`{key}={value}`"
                for key, value in sorted(
                    _mapping(
                        failure_summary.get("primary_failure_counts"),
                        "primary failures",
                    ).items()
                )
            )
            + ".",
            "",
            "The dominant failure is deliberately `MISSING_OUTPUT`: Canonical V2 does "
            "not emit metric phrase/concept before binding. `failure_taxonomy.jsonl` "
            "retains secondary field mismatches and prediction-source provenance.",
            "",
            "## 8. Parser vs Resolver Boundary",
            "",
            "All measurable failures in this run are attributed at the parser boundary. "
            "Metric resolver, selector/binder, and downstream answer accuracy are "
            "`NOT_MEASURABLE`: the local packet contains no independent binding, answer, "
            "or evidence reference. VAS code hints were recorded diagnostically and were "
            "not promoted into concept predictions.",
            "",
            "Boundary counts: "
            + ", ".join(
                f"`{key}={value}`"
                for key, value in sorted(
                    _mapping(failure_summary.get("boundary_counts"), "boundaries").items()
                )
            )
            + ".",
            "",
            "## 9. Determinism and Production Safety",
            "",
            "Two complete runs were created independently. The following artifact "
            "classes were compared byte-for-byte:",
            "",
            "| Artifact | Run A SHA-256 | Run B SHA-256 | Identical |",
            "|---|---|---|---:|",
        ]
    )
    for raw in comparisons:
        item = _mapping(raw, "comparison")
        lines.append(
            f"| {item['asset']} | `{item['run_a_sha256']}` | "
            f"`{item['run_b_sha256']}` | "
            f"{'PASS' if item['byte_identical'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            f"`E2E_DETERMINISM={determinism['status']}`.",
            "",
            "Protected parser/retrieval/answering files were hashed before and after "
            "both runs and compared with target commit "
            f"`{manifest_a['target_parser']['source_commit']}`: `PASS`, byte-identical.",
            "",
            "## 10. Tests and Reproduction",
            "",
            "Primary reproduction command (use fresh explicit output IDs because run "
            "directories are immutable):",
            "",
            "```bash",
            "make semantic-gold-v2-local-e2e PY=/opt/anaconda3/bin/python \\",
            "  MODE=LOCAL_SYNTHETIC \\",
            "  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-01 \\",
            "  RUN_A=artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-<run-id>-a \\",
            "  RUN_B=artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-<run-id>-b \\",
            "  REPORT=docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<date-or-run-id>.md",
            "```",
            "",
            "Verification completed by the runner: the tracked Draft 2020-12 schema, "
            "semantic relation validation, canonical derivation, vocabulary membership, "
            "two-run byte determinism, and protected-surface checks. Repository-wide test "
            "gate results are appended after the implementation run.",
            "",
            "## 11. Remaining Blockers",
            "",
            "Local E2E has no remaining blocker. Official submission remains blocked by:",
            "",
            "- independent annotator A not assigned/completed;",
            "- independent annotator B not assigned/completed;",
            "- distinct adjudicator C not assigned/completed;",
            "- no human inter-annotator agreement or adjudication evidence;",
            "- automated ontology matches are not official semantic gold;",
            "- resolver/binding/answer correctness is not independently measured here.",
            "",
            "## 12. Required Replacement Before Official Submission",
            "",
            "Replace `annotator_local.jsonl` with schema-valid, source-evidence-backed "
            "independent A and B annotations; compute agreement before C; adjudicate every "
            "record with a distinct C; activate reserve if the resolved count is below the "
            "official minimum; seal a new immutable release; only then export predictions "
            "and rerun the same evaluator against that release. Synthetic artifacts must "
            "never be copied into the official gold directory or registry.",
            "",
            "Exact next engineering task after human gold exists: implement a public "
            "pre-bind metric phrase/concept contract (without row-binding leakage), then "
            "measure it on the sealed independent release.",
            "",
        ]
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _metric_table(view: Mapping[str, object]) -> str:
    lines = [
        f"Resolved/scored population: `{view['resolved_records']}/{view['records']}`.",
        "",
        "| Metric | Correct | Scored | Skipped | Accuracy | Wilson 95% CI |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for raw in _sequence(view.get("metrics"), "view metrics"):
        row = _mapping(raw, "metric row")
        interval = row["wilson_95"]
        ci = "NOT_MEASURABLE"
        if isinstance(interval, Sequence) and not isinstance(interval, str):
            ci = f"{float(interval[0]):.4f}–{float(interval[1]):.4f}"
        lines.append(
            f"| {row['metric']} | {row['correct']} | {row['scored']} | "
            f"{row['skipped']} | {_format_accuracy(row['accuracy'])} | {ci} |"
        )
    return "\n".join(lines)


def _format_accuracy(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{100 * float(value):.2f}%"
    return str(value)


def _artifact_dir(value: str, *, must_exist: bool) -> Path:
    path = (ROOT / value).expanduser().resolve()
    try:
        path.relative_to(ARTIFACT_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"artifact path must be under {ARTIFACT_ROOT}: {value}") from error
    if must_exist and not path.is_dir():
        raise FileNotFoundError(path)
    if not must_exist and path.exists():
        raise FileExistsError(path)
    return path


def _report_path(value: str) -> Path:
    path = (ROOT / value).expanduser().resolve()
    try:
        path.relative_to(REPORT_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"report must be under {REPORT_ROOT}: {value}") from error
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _repo_file(value: str) -> Path:
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as error:
        raise ValueError(f"path escapes repository: {value}") from error
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _jsonl(path: Path) -> list[dict[str, object]]:
    return _jsonl_bytes(path.read_bytes())


def _jsonl_bytes(content: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(content.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"JSONL row {line_number} must be an object")
        rows.append(value)
    return rows


def _json_mapping(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON root must be a mapping: {path}")
    return value


def _yaml_mapping(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"YAML root must be a mapping: {path}")
    return value


def _qid(row: Mapping[str, object]) -> int:
    raw = row.get("qid", row.get("id"))
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise TypeError(f"invalid qid: {raw!r}")
    return int(raw)


def _text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError(f"{label} must be a sequence")
    return value


def _rows(value: object, label: str) -> list[Mapping[str, object]]:
    return [_mapping(row, label) for row in _sequence(value, label)]


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
