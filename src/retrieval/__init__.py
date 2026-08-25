"""Compatibility namespace for :mod:`text2pandas.pipelines.retrieval`."""
from __future__ import annotations

import warnings

from text2pandas.pipelines.retrieval import RETRIEVAL_VERSION, SILVER_BUILD_ID

warnings.warn(
    "retrieval is deprecated; use text2pandas.pipelines.retrieval",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["RETRIEVAL_VERSION", "SILVER_BUILD_ID"]
