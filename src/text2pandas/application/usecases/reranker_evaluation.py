"""Pure paired evaluation and policy decision for a held-out reranker release."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RerankOutcome:
    qid: int
    mode: str
    n_gold: int
    n_returned: int
    baseline_hits: tuple[int, ...]
    candidate_hits: tuple[int, ...]


def _f2(row: RerankOutcome, candidate: bool) -> float:
    hits = row.candidate_hits if candidate else row.baseline_hits
    h = len(hits)
    den = 4 * row.n_gold + row.n_returned
    return 5 * h / den if den else 0.0


def evaluate_reranker_ab(
    rows: list[RerankOutcome], *, bootstrap_samples: int = 10_000,
    seed: int = 20260827,
) -> dict:
    if not rows:
        raise ValueError("held-out evaluation needs at least one outcome")
    deltas = [_f2(row, True) - _f2(row, False) for row in rows]
    mean = sum(deltas) / len(deltas)
    rng = random.Random(seed)
    boots = sorted(
        sum(deltas[rng.randrange(len(deltas))] for _ in rows) / len(rows)
        for _ in range(bootstrap_samples)
    )
    lo = boots[int(0.025 * (len(boots) - 1))]
    hi = boots[int(0.975 * (len(boots) - 1))]

    def aggregate(candidate: bool, sample: list[RerankOutcome]) -> dict:
        fs = [_f2(row, candidate) for row in sample]
        hits = [row.candidate_hits if candidate else row.baseline_hits for row in sample]
        mrr = [(1.0 / min(pos)) if pos else 0.0 for pos in hits]
        return {
            "n": len(sample),
            "f2_at_10": sum(fs) / len(sample),
            "mrr_at_10": sum(mrr) / len(sample),
            "hit_at_10": sum(bool(pos) for pos in hits) / len(sample),
        }

    protected = {}
    for mode in ("single", "compare"):
        sample = [row for row in rows if row.mode == mode]
        if sample:
            a, b = aggregate(False, sample), aggregate(True, sample)
            protected[mode] = {"n": len(sample), "f2_delta": b["f2_at_10"] - a["f2_at_10"]}
    min_protected = min((x["f2_delta"] for x in protected.values()), default=0.0)
    baseline, candidate = aggregate(False, rows), aggregate(True, rows)
    gates = {
        "records_gte_100": len(rows) >= 100,
        "f2_delta_non_negative": mean >= 0.0,
        "f2_ci95_low_non_negative": lo >= 0.0,
        "protected_slice_delta_gte_minus_0_01": min_protected >= -0.01,
    }
    return {
        "status": "PASS" if all(gates.values()) else "FAIL",
        "n": len(rows),
        "baseline": baseline,
        "candidate": candidate,
        "paired_f2_delta": mean,
        "paired_f2_delta_ci95": [lo, hi],
        "protected_slices": protected,
        "minimum_protected_slice_delta": min_protected,
        "bootstrap": {"samples": bootstrap_samples, "seed": seed},
        "gates": gates,
    }
