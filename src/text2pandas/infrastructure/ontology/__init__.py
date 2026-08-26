"""Filesystem adapters for the canonical metric ontology."""

from text2pandas.domain.metrics import normalize_phrase

from .loader import OntologySourceError, load_ontology

__all__ = ["OntologySourceError", "load_ontology", "normalize_phrase"]
