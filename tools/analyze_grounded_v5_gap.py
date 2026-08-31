"""Profile semantic shapes left unanswered by the scorer-safe seed fusion."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.infrastructure.retrieval.grounded_query import GroundedQueryExpander
from text2pandas.infrastructure.semantic.legacy_annotator import LegacyVietnameseAnnotator
from text2pandas.pipelines.retrieval.alias_store import load_aliases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    baseline = _submission(args.baseline)
    secondary = _submission(args.secondary)
    questions = {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line)
            for line in args.questions.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    annotator = LegacyVietnameseAnnotator(load_aliases("a6"))
    expander = GroundedQueryExpander(load_ontology())
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, object]]] = defaultdict(list)
    unanswered: list[int] = []
    for qid, question in sorted(questions.items()):
        if _is_executable(baseline[qid]) or _is_executable(secondary[qid]):
            continue
        unanswered.append(qid)
        annotation = annotator.annotate(question)
        expansion = expander.analyze(question)
        roles = "+".join(sorted(formula.role for formula in expansion.formulas)) or "none"
        formula_ids = "+".join(formula.formula_id for formula in expansion.formulas) or "none"
        shape = f"{annotation.operation.value}|f={len(expansion.formulas)}|r={roles}"
        counters["operation"][annotation.operation.value] += 1
        counters["formula_count"][str(len(expansion.formulas))] += 1
        counters["formula_roles"][roles] += 1
        counters["formula_ids"][formula_ids] += 1
        counters["concept_count"][str(len(expansion.concepts))] += 1
        counters["shape"][shape] += 1
        if len(examples[shape]) < 5:
            examples[shape].append(
                {
                    "qid": qid,
                    "question": question,
                    "metrics": list(expansion.metric_ids),
                    "formulas": [
                        formula.to_planner_dict() for formula in expansion.formulas
                    ],
                }
            )
    payload = {
        "n_questions": len(questions),
        "n_seed_executable": len(questions) - len(unanswered),
        "n_unanswered": len(unanswered),
        "unanswered_qids": unanswered,
        "counters": {
            name: dict(counter.most_common()) for name, counter in counters.items()
        },
        "examples": dict(examples),
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


def _submission(path: Path) -> dict[int, dict[str, object]]:
    with zipfile.ZipFile(path) as archive:
        roots = [name for name in archive.namelist() if "/" not in name and name.endswith(".json")]
        if len(roots) != 1:
            raise ValueError(f"expected one root JSON in {path}")
        rows = json.loads(archive.read(roots[0]).decode("utf-8"))
    return {int(row["id"]): row for row in rows}


def _is_executable(row: Mapping[str, object]) -> bool:
    evidence = row.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        return False
    if not evidence or not str(row.get("pandas_query") or ""):
        return False
    value = row.get("answer")
    if value is None or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(str(value)))
    except (TypeError, ValueError, OverflowError):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
