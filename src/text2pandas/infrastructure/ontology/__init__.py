"""Filesystem adapters for the canonical metric ontology."""

from .loader import OntologySourceError, load_ontology, normalize_phrase

__all__ = ["OntologySourceError", "load_ontology", "normalize_phrase"]

