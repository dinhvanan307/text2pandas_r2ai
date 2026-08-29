"""Validated, immutable financial metric ontology.

The domain owns meaning; YAML and filesystem loading live in infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from text2pandas.domain.semantic import (
    Aggregate,
    Arithmetic,
    Basis,
    Dimension,
    Filter,
    FormulaCall,
    MetricRef,
    Rank,
    SelectAtArg,
    Unary,
    UnitSpec,
    expression_to_dict,
)
from text2pandas.domain.semantic.ast import Expression
from text2pandas.domain.semantic.types import PeriodSemantics


_REVIEWED_STATEMENT_TYPES = frozenset(
    {"balance_sheet", "income_statement", "cash_flow", "note"}
)


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    metric_id: str
    aliases: tuple[str, ...]
    statement_types: tuple[str, ...]
    unit: UnitSpec
    period_semantics: PeriodSemantics
    sign_policy: str
    preferred_basis: Basis
    review_status: str = "reviewed"
    forbidden_prefixes: tuple[str, ...] = ()
    forbidden_contains: tuple[str, ...] = ()
    required_context_any: tuple[str, ...] = ()
    legal_aggregations: tuple[str, ...] = ()

    @property
    def expected_dimension(self) -> Dimension:
        """Dimension required by a selector for this metric.

        ``MetricDefinition`` is the single source-of-truth MetricSpec.  The
        property gives P0 selection code the requested vocabulary without
        duplicating ontology records or policy data.
        """

        return self.unit.dimension

    @property
    def preferred_statement_types(self) -> tuple[str, ...]:
        return self.statement_types

    def to_dict(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "aliases": list(self.aliases),
            "statement_types": list(self.statement_types),
            "unit": self.unit.to_dict(),
            "period_semantics": self.period_semantics.value,
            "sign_policy": self.sign_policy,
            "preferred_basis": self.preferred_basis.value,
            "review_status": self.review_status,
            "forbidden_prefixes": list(self.forbidden_prefixes),
            "forbidden_contains": list(self.forbidden_contains),
            "required_context_any": list(self.required_context_any),
            "legal_aggregations": list(self.legal_aggregations),
        }


@dataclass(frozen=True, slots=True)
class FormulaDefinition:
    formula_id: str
    variant_id: str
    aliases: tuple[str, ...]
    leaves: tuple[str, ...]
    expression: Expression
    output_unit: UnitSpec
    period_contract: str
    same_entity: bool
    same_period: bool
    zero_policy: str
    max_abs: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "variant_id": self.variant_id,
            "aliases": list(self.aliases),
            "leaves": list(self.leaves),
            "expression": expression_to_dict(self.expression),
            "output_unit": self.output_unit.to_dict(),
            "period_contract": self.period_contract,
            "same_entity": self.same_entity,
            "same_period": self.same_period,
            "zero_policy": self.zero_policy,
            "max_abs": self.max_abs,
        }


@dataclass(frozen=True, slots=True)
class OntologyIssue:
    severity: str
    code: str
    subject: str
    message: str


class OntologyValidationError(ValueError):
    def __init__(self, issues: tuple[OntologyIssue, ...]):
        self.issues = issues
        detail = "; ".join(f"{issue.code}:{issue.subject}" for issue in issues)
        super().__init__(f"invalid metric ontology: {detail}")


@dataclass(frozen=True, slots=True)
class MetricOntology:
    ontology_id: str
    schema_version: int
    metrics: Mapping[str, MetricDefinition]
    formulas: Mapping[str, FormulaDefinition]
    source_digests: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "formulas", MappingProxyType(dict(self.formulas)))
        object.__setattr__(self, "source_digests", MappingProxyType(dict(self.source_digests)))
        issues = self.validate()
        errors = tuple(issue for issue in issues if issue.severity == "ERROR")
        if errors:
            raise OntologyValidationError(errors)

    def validate(self) -> tuple[OntologyIssue, ...]:
        issues: list[OntologyIssue] = []
        if self.schema_version != 3:
            issues.append(_error("SCHEMA_VERSION", self.ontology_id, "schema must equal 3"))
        for key, metric in self.metrics.items():
            if key != metric.metric_id:
                issues.append(_error("METRIC_KEY", key, "dictionary key differs from metric_id"))
            normalized_aliases = tuple(normalize_phrase(alias) for alias in metric.aliases)
            if not normalized_aliases or any(not alias for alias in normalized_aliases):
                issues.append(_error("METRIC_ALIASES", key, "metric requires aliases"))
            if len(set(normalized_aliases)) != len(normalized_aliases):
                issues.append(_error("METRIC_ALIAS_DUPLICATE", key, "aliases must be unique"))
            if metric.review_status == "reviewed":
                if metric.unit.dimension.value == "unknown":
                    issues.append(
                        _error("METRIC_DIMENSION", key, "reviewed metric requires a dimension")
                    )
                if metric.period_semantics == PeriodSemantics.UNKNOWN:
                    issues.append(
                        _error(
                            "METRIC_PERIOD_SEMANTICS",
                            key,
                            "reviewed metric requires period semantics",
                        )
                    )
                invalid_statement_types = sorted(
                    set(metric.statement_types) - _REVIEWED_STATEMENT_TYPES
                )
                if not metric.statement_types or invalid_statement_types:
                    issues.append(
                        _error(
                            "METRIC_STATEMENT_TYPES",
                            key,
                            f"invalid={invalid_statement_types}",
                        )
                    )
                forbidden_prefixes = tuple(
                    normalize_phrase(value) for value in metric.forbidden_prefixes
                )
                forbidden_contains = tuple(
                    normalize_phrase(value) for value in metric.forbidden_contains
                )
                if normalized_aliases and all(
                    any(alias.startswith(value) for value in forbidden_prefixes if value)
                    or any(value in alias for value in forbidden_contains if value)
                    for alias in normalized_aliases
                ):
                    issues.append(
                        _error(
                            "METRIC_ALIASES_FORBIDDEN",
                            key,
                            "forbidden rules reject every positive alias",
                        )
                    )
        metric_alias_owner: dict[str, str] = {}
        for metric in self.metrics.values():
            for alias in metric.aliases:
                normalized_alias = normalize_phrase(alias)
                owner = metric_alias_owner.setdefault(normalized_alias, metric.metric_id)
                if owner != metric.metric_id:
                    issues.append(
                        _error(
                            "METRIC_ALIAS_COLLISION",
                            normalized_alias,
                            f"owned by both {owner} and {metric.metric_id}",
                        )
                    )
        formula_alias_owner: dict[str, str] = {}
        for key, formula in self.formulas.items():
            if key != formula.formula_id:
                issues.append(_error("FORMULA_KEY", key, "dictionary key differs from formula_id"))
            actual = expression_metric_ids(formula.expression)
            declared = frozenset(formula.leaves)
            if actual != declared:
                issues.append(
                    _error(
                        "FORMULA_LEAVES",
                        key,
                        f"declared={sorted(declared)} expression={sorted(actual)}",
                    )
                )
            missing = declared - self.metrics.keys()
            if missing:
                issues.append(_error("FORMULA_UNKNOWN_METRIC", key, f"missing={sorted(missing)}"))
            if not formula.aliases:
                issues.append(_error("FORMULA_ALIASES", key, "formula requires aliases"))
            for alias in formula.aliases:
                owner = formula_alias_owner.setdefault(alias, formula.formula_id)
                if owner != formula.formula_id:
                    issues.append(
                        _error(
                            "FORMULA_ALIAS_COLLISION",
                            alias,
                            f"owned by both {owner} and {formula.formula_id}",
                        )
                    )
        return tuple(issues)

    @property
    def fingerprint(self) -> str:
        payload = {
            "ontology_id": self.ontology_id,
            "schema_version": self.schema_version,
            "metrics": [self.metrics[key].to_dict() for key in sorted(self.metrics)],
            "formulas": [self.formulas[key].to_dict() for key in sorted(self.formulas)],
            "source_digests": dict(sorted(self.source_digests.items())),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def match_metric(self, normalized_text: str) -> MetricDefinition | None:
        matches = [
            (len(alias), metric.metric_id, metric)
            for metric in self.metrics.values()
            for alias in metric.aliases
            if alias and alias in normalized_text
        ]
        return max(matches, default=(0, "", None))[2]

    def match_formula(self, normalized_text: str) -> FormulaDefinition | None:
        matches = [
            (len(alias), formula.formula_id, formula)
            for formula in self.formulas.values()
            for alias in formula.aliases
            if alias and alias in normalized_text
        ]
        return max(matches, default=(0, "", None))[2]


def expression_metric_ids(expression: Expression) -> frozenset[str]:
    if isinstance(expression, MetricRef):
        return frozenset({expression.metric_id})
    if isinstance(expression, Arithmetic):
        return expression_metric_ids(expression.left) | expression_metric_ids(expression.right)
    if isinstance(expression, Unary):
        return expression_metric_ids(expression.expression)
    if isinstance(expression, FormulaCall):
        return expression_metric_ids(expression.expression)
    if isinstance(expression, Aggregate):
        return expression_metric_ids(expression.expression)
    if isinstance(expression, Filter):
        return expression_metric_ids(expression.expression)
    if isinstance(expression, Rank):
        return expression_metric_ids(expression.by)
    if isinstance(expression, SelectAtArg):
        return expression_metric_ids(expression.rank) | expression_metric_ids(expression.expression)
    return frozenset()


def normalize_phrase(value: str) -> str:
    """Corpus-independent Vietnamese normalization for ontology matching."""
    decomposed = unicodedata.normalize("NFD", value.casefold())
    plain = "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    )
    return " ".join(plain.replace("đ", "d").split())


def _error(code: str, subject: str, message: str) -> OntologyIssue:
    return OntologyIssue("ERROR", code, subject, message)
