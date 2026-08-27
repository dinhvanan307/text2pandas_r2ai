"""Vietnamese lexical adapters for Semantic Query Engine v3."""

from .gold_registry import load_gold_registry
from .legacy_annotator import LegacyVietnameseAnnotator
from .promotion import load_promotion_policy

__all__ = ["LegacyVietnameseAnnotator", "load_gold_registry", "load_promotion_policy"]
