"""Canonical metric and formula ontology contracts."""

from .ontology import (
    FormulaDefinition,
    MetricDefinition,
    MetricOntology,
    OntologyIssue,
    OntologyValidationError,
    expression_metric_ids,
    iter_phrase_spans,
    normalize_phrase,
)

# P0 terminology: the validated MetricDefinition is the MetricSpec SSOT.
# Keep one runtime type and one ontology; callers may use either name.
MetricSpec = MetricDefinition

__all__ = [
    "FormulaDefinition",
    "MetricDefinition",
    "MetricOntology",
    "MetricSpec",
    "OntologyIssue",
    "OntologyValidationError",
    "expression_metric_ids",
    "iter_phrase_spans",
    "normalize_phrase",
]
