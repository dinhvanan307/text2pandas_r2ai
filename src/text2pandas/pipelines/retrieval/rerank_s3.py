"""S3 feature reranker with a versioned, auditable linear model.

The reranker only reorders S2's bounded candidate list.  It never creates a
candidate and therefore cannot hide a retrieval miss.  Model files contain the
feature contract and a SHA-bound training manifest; unknown features fail
closed instead of being silently ignored.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from text2pandas.pipelines.retrieval.evalkit.stages import RankedItem, StageOutput
from text2pandas.pipelines.retrieval.question_intent import Intent

MODEL_SCHEMA = "linear-reranker-v1"
FEATURES = (
    "s2_score",
    "bm25",
    "rank_prior",
    "period_hit",
    "unit_hit",
    "stmt_hit",
    "basis_hit",
    "clean_ratio",
    "primary_statement",
    "note_statement",
    "cash_flow_statement",
    "screen_primary",
    "related_primary",
)
PRIMARY_STATEMENTS = frozenset({"balance_sheet", "income_statement"})


@dataclass(frozen=True, slots=True)
class LinearRerankerModel:
    model_id: str
    weights: tuple[float, ...]
    training_manifest_sha256: str
    schema: str = MODEL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MODEL_SCHEMA:
            raise ValueError(f"unsupported reranker schema: {self.schema!r}")
        if len(self.weights) != len(FEATURES):
            raise ValueError(
                f"reranker needs {len(FEATURES)} weights, got {len(self.weights)}"
            )
        if not self.model_id or not self.training_manifest_sha256:
            raise ValueError("reranker model_id and training manifest SHA are required")
        if any(not math.isfinite(w) for w in self.weights):
            raise ValueError("reranker weights must be finite")

    @classmethod
    def load(cls, path: str | Path) -> "LinearRerankerModel":
        p = Path(path)
        doc = json.loads(p.read_text(encoding="utf-8"))
        names = tuple(doc.get("features") or ())
        if names != FEATURES:
            raise ValueError(
                "reranker feature contract mismatch; refusing positional weight drift"
            )
        weights = doc.get("weights")
        if not isinstance(weights, dict) or set(weights) != set(FEATURES):
            raise ValueError("reranker model must define every feature exactly once")
        return cls(
            model_id=str(doc["model_id"]),
            weights=tuple(float(weights[name]) for name in FEATURES),
            training_manifest_sha256=str(doc["training_manifest_sha256"]),
            schema=str(doc.get("schema", "")),
        )

    @property
    def sha256(self) -> str:
        payload = {
            "schema": self.schema,
            "model_id": self.model_id,
            "features": FEATURES,
            "weights": self.weights,
            "training_manifest_sha256": self.training_manifest_sha256,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def feature_rows(upstream: StageOutput, intent: Intent) -> list[tuple[RankedItem, tuple[float, ...]]]:
    """Extract bounded features without querying labels or external state."""
    items = list(upstream.ranked)
    max_score = max((abs(it.score) for it in items), default=0.0) or 1.0
    max_bm25 = max((abs(it.scored.bm25) for it in items if it.scored), default=0.0) or 1.0
    out: list[tuple[RankedItem, tuple[float, ...]]] = []
    for rank, item in enumerate(items, 1):
        s = item.scored
        cand = item.cand
        statement = cand.statement_type if cand else None
        primary = statement in PRIMARY_STATEMENTS
        values = (
            item.score / max_score,
            (s.bm25 / max_bm25) if s else 0.0,
            1.0 / rank,
            float(bool(s and s.period_hit)),
            float(bool(s and s.unit_hit)),
            float(bool(s and s.stmt_hit)),
            float(bool(s and s.basis_hit)),
            cand.clean_ratio if cand else 0.0,
            float(primary),
            float(statement == "note"),
            float(statement == "cash_flow"),
            float(intent.mode == "screen" and primary),
            float(intent.mode == "related" and primary),
        )
        out.append((item, values))
    return out


class LinearFeatureReranker:
    """Deterministic learned S3; ties preserve S2 order then table UID."""

    name = "s3_linear_features"

    def __init__(self, model: LinearRerankerModel, top_k: int = 10):
        if top_k < 1:
            raise ValueError("top_k must be positive")
        self.model = model
        self.top_k = top_k

    def rerank(self, conn, question: str, intent: Intent,
               upstream: StageOutput) -> StageOutput:
        scored = []
        for original_rank, (item, values) in enumerate(feature_rows(upstream, intent)):
            score = sum(w * x for w, x in zip(self.model.weights, values, strict=True))
            scored.append((score, original_rank, item))
        scored.sort(key=lambda row: (-row[0], row[1], row[2].table_uid))
        keep = tuple(
            RankedItem(
                table_uid=item.table_uid,
                score=score,
                reasons=(*item.reasons, "s3_linear"),
                cand=item.cand,
                scored=item.scored,
            )
            for score, _, item in scored[:self.top_k]
        )
        return StageOutput(
            stage=self.name,
            uids=frozenset(it.table_uid for it in keep),
            ranked=keep,
            truncated_at=self.top_k,
            trace={
                "model": self.model.model_id,
                "model_sha256": self.model.sha256,
                "training_manifest_sha256": self.model.training_manifest_sha256,
                "passthrough": False,
                "n_in": len(upstream.ranked),
                "n_out": len(keep),
            },
        )
