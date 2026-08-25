"""Compatibility namespace for :mod:`text2pandas.pipelines.answering`."""
from __future__ import annotations

import warnings

from text2pandas.pipelines.answering import *  # noqa: F401,F403
from text2pandas.pipelines.answering import __all__

warnings.warn(
    "text2pandas.answer_pipeline is deprecated; use text2pandas.pipelines.answering",
    DeprecationWarning,
    stacklevel=2,
)
