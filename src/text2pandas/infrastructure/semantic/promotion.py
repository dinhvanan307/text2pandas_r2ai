"""Load the data-owned Semantic V3 promotion policy."""

from __future__ import annotations

from pathlib import Path

import yaml

from text2pandas.application.usecases.semantic_v3_readiness import PromotionPolicy

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT = _REPO_ROOT / "configs" / "semantic" / "promotion_policy_v3.yaml"


def load_promotion_policy(path: str | Path = _DEFAULT) -> PromotionPolicy:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 3:
        raise ValueError("semantic promotion policy schema_version must equal 3")
    if raw.get("missing_metric_policy") != "block":
        raise ValueError("semantic promotion policy must block missing metrics")
    return PromotionPolicy(
        policy_id=str(raw["policy_id"]),
        required_full_questions=int(raw["required_full_questions"]),
        minimum_answer_gold_records=int(raw["minimum_answer_gold_records"]),
        minimum_semantic_gold_records=int(raw["minimum_semantic_gold_records"]),
        minimum_evidence_gold_records=int(raw["minimum_evidence_gold_records"]),
        minimum_parser_ast_exact=float(raw["minimum_parser_ast_exact"]),
        minimum_candidate_recall=float(raw["minimum_candidate_recall"]),
        minimum_binding_exact=float(raw["minimum_binding_exact"]),
        minimum_answer_accuracy=float(raw["minimum_answer_accuracy"]),
        minimum_submission_replay_records=int(raw["minimum_submission_replay_records"]),
        maximum_replay_mismatches=int(raw["maximum_replay_mismatches"]),
        maximum_submission_errors=int(raw["maximum_submission_errors"]),
        require_sealed_evaluation_release=bool(raw["require_sealed_evaluation_release"]),
    )
