"""Compatibility namespace for :mod:`text2pandas.pipelines.a6`.

Remove this shim after downstream consumers have migrated to the canonical
namespace.
"""
from __future__ import annotations

import warnings

warnings.warn(
    "data_pipeline is deprecated; use text2pandas.pipelines.a6",
    DeprecationWarning,
    stacklevel=2,
)
