"""Vietnamese lexical adapters for Semantic Query Engine v3."""

from .legacy_annotator import LegacyVietnameseAnnotator
from .promotion import load_promotion_policy

__all__ = ["LegacyVietnameseAnnotator", "load_promotion_policy"]
