"""The transitional namespaces must resolve to canonical module objects."""
from __future__ import annotations

import importlib
import warnings

import pytest


@pytest.mark.parametrize(
    ("legacy", "canonical"),
    [
        ("data_pipeline.number_parser", "text2pandas.pipelines.a6.number_parser"),
        ("retrieval.question_intent", "text2pandas.pipelines.retrieval.question_intent"),
        ("retrieval.evalkit.runner", "text2pandas.pipelines.retrieval.evalkit.runner"),
        ("text2pandas.answer_pipeline.units", "text2pandas.pipelines.answering.units"),
    ],
)
def test_legacy_module_is_canonical_module(legacy: str, canonical: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old_module = importlib.import_module(legacy)
    assert old_module is importlib.import_module(canonical)
