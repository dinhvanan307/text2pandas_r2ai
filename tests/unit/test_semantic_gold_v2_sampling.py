from __future__ import annotations

import json
from pathlib import Path

import yaml

from text2pandas.application.usecases.semantic_gold_v2 import (
    build_contamination_ledger,
    select_semantic_questions,
)

ROOT = Path(__file__).resolve().parents[2]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_tracked_phase1_5_sampling_contract_selects_untouched_cohorts() -> None:
    protocol = yaml.safe_load(
        (ROOT / "configs/evaluation/semantic_gold_v2_protocol.yaml").read_text(
            encoding="utf-8"
        )
    )
    sampling = yaml.safe_load(
        (ROOT / protocol["contracts"]["sampling"]).read_text(encoding="utf-8")
    )
    sources = {
        item["path"]: _jsonl(ROOT / item["path"])
        for item in protocol["contamination_sources"]
    }
    ledger = build_contamination_ledger(sources)
    contaminated = frozenset(int(row["qid"]) for row in ledger)

    selection = select_semantic_questions(
        _jsonl(ROOT / protocol["question_source"]["path"]),
        contaminated_qids=contaminated,
        sampling=sampling,
    )

    assert len(contaminated) == 221
    assert selection.coverage["eligible_records"] == 791
    assert len(selection.core) == 100
    assert len(selection.diagnostic) == 20
    assert len(selection.reserve) == 30
    selected_qids = {
        int(row["qid"])
        for row in (*selection.core, *selection.diagnostic, *selection.reserve)
    }
    assert not (selected_qids & contaminated)
    assert selection.coverage["selection_uses_predictions"] is False
    assert all(
        value["selected"] == value["target"]
        for name, value in selection.coverage["strata"].items()
        if name != "RANDOM_TOPUP"
    )
