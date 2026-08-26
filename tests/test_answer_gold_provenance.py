"""Integrity gates for the two-stage adjudicated answer-gold workflow."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLD_DIR = ROOT / "data/curated/dev-legacy/answer_gold"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_pre_recheck_validation_report_matches_source_artifact() -> None:
    source = GOLD_DIR / "answer_gold_wave1.jsonl"
    report = _json(GOLD_DIR / "validation_report.json")
    rows = _jsonl(source)
    assert report["EXIT_GATE"] == "PASS"
    assert report["sha256_gold"] == _sha256(source)
    assert report["n"] == len(rows) == 40
    assert report["trang_thai"] == dict(Counter(row["trang_thai"] for row in rows))


def test_post_recheck_report_matches_final_gold() -> None:
    source = GOLD_DIR / "answer_gold_wave1_final.jsonl"
    report = _json(GOLD_DIR / "blind_recheck_report.json")
    rows = _jsonl(source)
    assert report["GATE_BAT_DONG"] == "PASS"
    assert report["sha256_final"] == _sha256(source)
    assert report["n_gold"] == len(rows) == 40
    assert report["trang_thai_cuoi"] == dict(
        Counter(row["trang_thai"] for row in rows)
    )


def test_final_gold_is_conservative_and_has_unique_ids() -> None:
    rows = _jsonl(GOLD_DIR / "answer_gold_wave1_final.jsonl")
    assert len({int(row["qid"]) for row in rows}) == len(rows)
    assert all(row["trang_thai"] in {"OK", "GOLD_UNCERTAIN", "DATA_MISSING"}
               for row in rows)
    assert sum(row["trang_thai"] == "OK" for row in rows) == 31
