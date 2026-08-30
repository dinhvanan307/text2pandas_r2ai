"""Build an immutable semantic/failure inventory for baseline abstentions."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from text2pandas.domain.metrics import normalize_phrase
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander
from text2pandas.infrastructure.semantic.legacy_annotator import LegacyVietnameseAnnotator
from text2pandas.infrastructure.source_identity import git_source_identity
from text2pandas.pipelines.retrieval.alias_store import load_aliases

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "artifacts/official/submission-3828/submission.zip"
DEFAULT_RECORDS = ROOT / (
    "artifacts/runs/grounded-v5/grounded-v6-downloaded-replace-trusted-20260830-r1/records.jsonl"
)
DEFAULT_QUESTIONS = ROOT / "data/raw/btc/questions/questions.jsonl"


def classify_case(
    *,
    operation: str,
    formula_count: int,
    concept_count: int,
    candidate_facts: int,
    question: str,
) -> tuple[str, str]:
    """Return preliminary repair class and risk tier without claiming correctness."""

    simple_classes = {
        "lookup": "direct_lookup",
        "sum": "single_metric_sum",
        "average": "single_metric_average",
        "subtract": "two_period_difference",
        "divide": "direct_ratio",
    }
    repair_class = simple_classes.get(operation, "complex_composition")
    if operation == "extremum" and formula_count == 0 and concept_count == 1:
        repair_class = "simple_extremum"
    normalized = normalize_phrase(question)
    complex_cues = (
        "trung vi",
        "cagr",
        "dong thoi",
        "trong so cac cong ty co",
        "tai nam co",
        "vao nam co",
    )
    if candidate_facts == 0 or concept_count == 0:
        return repair_class, "D"
    if (
        repair_class in set(simple_classes.values())
        and formula_count <= 1
        and not any(cue in normalized for cue in complex_cues)
    ):
        return repair_class, "A"
    if repair_class == "simple_extremum":
        return repair_class, "B"
    return repair_class, "C"


def _rows(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _submission(path: Path) -> dict[int, dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        roots = [name for name in archive.namelist() if "/" not in name and name.endswith(".json")]
        if len(roots) != 1:
            raise ValueError(f"expected one root JSON in {path}")
        payload = json.loads(archive.read(roots[0]).decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError("submission root must be a list")
    return {int(row["id"]): row for row in payload}


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-abstentions", type=int, default=277)
    parser.add_argument(
        "--kind",
        default="text2pandas.recovery_wave2_inventory",
        help="Versioned inventory kind recorded in summary and manifest",
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output.exists():
        parser.error(f"immutable output already exists: {output}")
    source = git_source_identity(ROOT)
    if source.get("git_dirty") is not False or not source.get("git_commit"):
        parser.error("inventory generation requires a clean committed source tree")

    baseline_path = args.baseline.expanduser().resolve()
    records_path = args.records.expanduser().resolve()
    questions_path = args.questions.expanduser().resolve()
    baseline = _submission(baseline_path)
    source_records = {int(row["qid"]): row for row in _rows(records_path)}
    questions = {int(row["id"]): str(row["question"]) for row in _rows(questions_path)}
    if set(baseline) != set(questions):
        raise ValueError("baseline and question scope differ")
    if set(source_records) != set(questions):
        raise ValueError("source records and question scope differ")

    annotator = LegacyVietnameseAnnotator(load_aliases("a6"))
    expander = GroundedQueryExpander(load_ontology())
    inventory: list[dict[str, object]] = []
    for qid, question in sorted(questions.items()):
        if _is_executable(baseline[qid]):
            continue
        annotation = annotator.annotate(question)
        expansion = expander.analyze(question)
        source_attempt = source_records[qid].get("grounded_v5")
        grounded = source_attempt if isinstance(source_attempt, Mapping) else {}
        candidate_facts = int(grounded.get("candidate_facts") or 0)
        repair_class, risk_tier = classify_case(
            operation=annotation.operation.value,
            formula_count=len(expansion.formulas),
            concept_count=len(expansion.concepts),
            candidate_facts=candidate_facts,
            question=question,
        )
        inventory.append(
            {
                "qid": qid,
                "question": question,
                "semantic": {
                    "operation": annotation.operation.value,
                    "entities": list(annotation.entities),
                    "periods": list(annotation.periods),
                    "basis": annotation.basis.value,
                    "requested_dimension": annotation.requested_unit.dimension.value,
                    "requested_scale_exponent": annotation.requested_unit.scale_exponent,
                    "metric_ids": list(expansion.metric_ids),
                    "formula_count": len(expansion.formulas),
                    "formula_roles": sorted(formula.role for formula in expansion.formulas),
                    "concept_count": len(expansion.concepts),
                },
                "source_attempt": {
                    "status": grounded.get("status") or "NO_GROUNDED_V5",
                    "reason": grounded.get("reason"),
                    "candidate_facts": candidate_facts,
                    "required_metric_ids": grounded.get("required_metric_ids") or [],
                },
                "triage": {
                    "repair_class": repair_class,
                    "risk_tier": risk_tier,
                    "correctness": "NOT_MEASURED",
                },
            }
        )

    if len(inventory) != args.expected_abstentions:
        raise ValueError(
            f"expected {args.expected_abstentions} baseline abstentions, found {len(inventory)}"
        )
    operation_counts = Counter(str(row["semantic"]["operation"]) for row in inventory)  # type: ignore[index]
    risk_counts = Counter(str(row["triage"]["risk_tier"]) for row in inventory)  # type: ignore[index]
    repair_counts = Counter(str(row["triage"]["repair_class"]) for row in inventory)  # type: ignore[index]
    output.mkdir(parents=True)
    inventory_path = output / "inventory.jsonl"
    inventory_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in inventory),
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "kind": args.kind,
        "records": len(inventory),
        "operation_counts": dict(sorted(operation_counts.items())),
        "risk_tier_counts": dict(sorted(risk_counts.items())),
        "repair_class_counts": dict(sorted(repair_counts.items())),
        "correctness": "NOT_MEASURED",
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        **summary,
        "source": {
            **source,
            "baseline": {"path": str(baseline_path), "sha256": sha256_file(baseline_path)},
            "records": {"path": str(records_path), "sha256": sha256_file(records_path)},
            "questions": {"path": str(questions_path), "sha256": sha256_file(questions_path)},
        },
        "outputs": {
            "inventory": {"path": "inventory.jsonl", "sha256": sha256_file(inventory_path)},
            "summary": {"path": "summary.json", "sha256": sha256_file(output / "summary.json")},
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
