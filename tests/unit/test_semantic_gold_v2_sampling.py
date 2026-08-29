from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from text2pandas.application.usecases.semantic_gold_v2 import (
    build_contamination_ledger,
    select_semantic_questions,
    validate_phase1_5_sampling_contract,
)
from tools.evaluation.prepare_semantic_gold_v2 import _create_immutable_output

ROOT = Path(__file__).resolve().parents[2]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tracked_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, list[dict[str, object]]],
    dict[str, str],
]:
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
    reasons = {
        item["path"]: item["reason"] for item in protocol["contamination_sources"]
    }
    return protocol, sampling, sources, reasons


def test_tracked_phase1_5_sampling_contract_selects_untouched_cohorts() -> None:
    protocol, sampling, sources, reasons = _tracked_inputs()
    validate_phase1_5_sampling_contract(sampling)
    ledger = build_contamination_ledger(sources, reasons)
    contaminated = frozenset(int(row["qid"]) for row in ledger)

    selection = select_semantic_questions(
        _jsonl(ROOT / protocol["question_source"]["path"]),
        contaminated_qids=contaminated,
        sampling=sampling,
    )

    assert len(contaminated) > 221
    assert selection.coverage["eligible_records"] == 1012 - len(contaminated)
    assert len(selection.core) == 100
    assert len(selection.diagnostic) == 20
    assert len(selection.reserve) == 30
    selected_qids = {
        int(row["qid"])
        for row in (*selection.core, *selection.diagnostic, *selection.reserve)
    }
    assert len(selected_qids) == 150
    assert not (selected_qids & contaminated)
    assert selection.coverage["selection_uses_predictions"] is False
    assert selection.coverage["model_outputs_included"] is False
    assert "RANDOM_TOPUP" not in selection.coverage["strata"]
    assert all(
        value["selected"] == value["target"]
        for value in selection.coverage["strata"].values()
    )


def test_selection_authority_records_seeds_universes_exclusions_and_digests() -> None:
    protocol, sampling, sources, reasons = _tracked_inputs()
    ledger = build_contamination_ledger(sources, reasons)
    contaminated = frozenset(int(row["qid"]) for row in ledger)
    selection = select_semantic_questions(
        _jsonl(ROOT / protocol["question_source"]["path"]),
        contaminated_qids=contaminated,
        sampling=sampling,
    )

    authority = selection.coverage["authority"]
    assert authority["algorithm"] == "SHA256(seed + NUL + qid + NUL + question)"
    assert authority["seeds"] == {
        "headline_core": sampling["headline_core"]["seed"],
        "diagnostic_supplement": sampling["diagnostic_supplement"]["seed"],
        "reserve": sampling["reserve"]["seed"],
    }
    assert authority["excluded_qids"] == sorted(contaminated)
    assert len(authority["excluded_qids_sha256"]) == 64
    assert len(authority["source_universe_sha256"]) == 64
    assert len(authority["eligible_universe_sha256"]) == 64
    assert len(authority["selected"]["headline_core"]) == 100

    first = selection.core[0]
    expected = hashlib.sha256(
        f"{sampling['headline_core']['seed']}\0{first['qid']}\0{first['question']}".encode()
    ).hexdigest()
    assert first["selection_digest"] == expected


@pytest.mark.parametrize(
    ("cohort", "count", "match"),
    [
        ("headline_core", 99, "headline core records must equal 100"),
        ("diagnostic_supplement", 19, "diagnostic records must equal 20"),
        ("reserve", 29, "reserve records must equal 30"),
    ],
)
def test_phase1_5_contract_rejects_wrong_cohort_sizes(
    cohort: str, count: int, match: str
) -> None:
    _protocol, sampling, _sources, _reasons = _tracked_inputs()
    changed = deepcopy(sampling)
    changed[cohort]["records"] = count

    with pytest.raises(ValueError, match=match):
        validate_phase1_5_sampling_contract(changed)


def test_prediction_dependent_sampling_contract_is_rejected() -> None:
    _protocol, sampling, _sources, _reasons = _tracked_inputs()
    changed = deepcopy(sampling)
    changed["headline_core"]["prediction"] = "parser-output"

    with pytest.raises(ValueError, match="prediction field leaked"):
        validate_phase1_5_sampling_contract(changed)


def test_duplicate_question_qid_is_rejected() -> None:
    protocol, sampling, _sources, _reasons = _tracked_inputs()
    questions = _jsonl(ROOT / protocol["question_source"]["path"])
    questions.append(deepcopy(questions[0]))

    with pytest.raises(ValueError, match="duplicate source qid"):
        select_semantic_questions(
            questions, contaminated_qids=frozenset(), sampling=sampling
        )


def test_existing_packet_output_directory_is_rejected(tmp_path: Path) -> None:
    packet = tmp_path / "packet"
    _create_immutable_output(packet)

    with pytest.raises(FileExistsError):
        _create_immutable_output(packet)


def test_contamination_entries_always_include_qid_source_and_reason() -> None:
    _protocol, _sampling, sources, reasons = _tracked_inputs()
    ledger = build_contamination_ledger(sources, reasons)

    assert ledger
    assert all(set(row) == {"qid", "source", "reason"} for row in ledger)
    assert all(str(row["source"]).strip() for row in ledger)
    assert all(str(row["reason"]).strip() for row in ledger)
