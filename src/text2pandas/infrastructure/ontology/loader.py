"""Load the versioned ontology manifest and fail closed on source drift."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from text2pandas.domain.metrics import (
    FormulaDefinition,
    MetricDefinition,
    MetricOntology,
    normalize_phrase,
)
from text2pandas.domain.semantic import (
    Arithmetic,
    ArithmeticOperator,
    Basis,
    Dimension,
    Literal,
    MetricRef,
    PeriodSemantics,
    Unary,
    UnaryOperator,
    UnitSpec,
)
from text2pandas.domain.semantic.ast import Expression

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_MANIFEST = _REPO_ROOT / "configs" / "semantic" / "ontology_v3.yaml"


class OntologySourceError(ValueError):
    pass


@lru_cache(maxsize=4)
def load_ontology(manifest_path: str | Path = _DEFAULT_MANIFEST) -> MetricOntology:
    manifest_file = Path(manifest_path).resolve()
    manifest = _document(manifest_file)
    if int(manifest.get("schema_version", 0)) != 3:
        raise OntologySourceError("ontology manifest schema_version must equal 3")
    sources = _dict(manifest.get("sources"), "sources")
    metric_file, metric_digest = _verified_source(sources, "metrics", manifest_file)
    formula_file, formula_digest = _verified_source(sources, "formulas", manifest_file)
    metric_document = _document(metric_file)
    formula_document = _document(formula_file)

    metrics: dict[str, MetricDefinition] = {}
    for raw_value in metric_document.get("metrics", []):
        raw = _dict(raw_value, "metric")
        metric = _metric_definition(raw)
        if metric.metric_id in metrics:
            raise OntologySourceError(f"duplicate metric_id: {metric.metric_id}")
        metrics[metric.metric_id] = metric

    formulas: dict[str, FormulaDefinition] = {}
    for raw_value in formula_document.get("formulas", []):
        raw = _dict(raw_value, "formula")
        formula = _formula_definition(raw)
        if formula.formula_id in formulas:
            raise OntologySourceError(f"duplicate formula_id: {formula.formula_id}")
        formulas[formula.formula_id] = formula

    return MetricOntology(
        ontology_id=str(manifest["ontology_id"]),
        schema_version=3,
        metrics=metrics,
        formulas=formulas,
        source_digests={"metrics": metric_digest, "formulas": formula_digest},
    )


def _metric_definition(raw: dict[str, Any]) -> MetricDefinition:
    value_kind = str(raw.get("value_kind", "unknown"))
    dimension = {
        "money": Dimension.MONEY,
        "percent": Dimension.PERCENT,
        "ratio": Dimension.RATIO,
        "shares": Dimension.SHARES,
        "count": Dimension.COUNT,
    }.get(value_kind, Dimension.UNKNOWN)
    period = {
        "point_in_time": PeriodSemantics.POINT_IN_TIME,
        "flow": PeriodSemantics.FLOW,
        "instant": PeriodSemantics.INSTANT,
    }.get(str(raw.get("period_semantics", "")), PeriodSemantics.UNKNOWN)
    basis = {
        "consolidated": Basis.CONSOLIDATED,
        "separate": Basis.SEPARATE,
    }.get(str(raw.get("preferred_scope", "")), Basis.UNSPECIFIED)
    legal = ("sum", "average", "minimum", "maximum", "growth")
    return MetricDefinition(
        metric_id=str(raw["metric_id"]),
        aliases=_normalized_tuple(raw.get("aliases", ())),
        statement_types=tuple(str(value) for value in raw.get("statement_types", ())),
        unit=UnitSpec(dimension),
        period_semantics=period,
        sign_policy=str(raw.get("sign_policy", "signed_as_reported")),
        preferred_basis=basis,
        forbidden_prefixes=_normalized_tuple(raw.get("forbidden_aliases", ())),
        forbidden_contains=_normalized_tuple(raw.get("forbidden_contains", ())),
        legal_aggregations=legal,
    )


def _formula_definition(raw: dict[str, Any]) -> FormulaDefinition:
    output = _dict(raw.get("output"), f"formula {raw.get('formula_id')} output")
    output_kind = str(output.get("kind", "ratio"))
    output_unit = UnitSpec(Dimension.PERCENT if output_kind == "percentage" else Dimension.RATIO)
    expression = _formula_expression(_dict(raw.get("expression"), "formula expression"))
    if output_kind == "percentage":
        expression = _strip_legacy_percentage_multiplier(expression)
    return FormulaDefinition(
        formula_id=str(raw["formula_id"]),
        variant_id=str(raw.get("variant_id", "default")),
        aliases=_normalized_tuple(raw.get("aliases", ())),
        leaves=tuple(str(value) for value in raw.get("leaves", ())),
        expression=expression,
        output_unit=output_unit,
        period_contract=str(raw.get("period_semantics", "unknown")),
        same_entity=bool(raw.get("same_entity", True)),
        same_period=bool(raw.get("same_period", True)),
        zero_policy=str(raw.get("zero_policy", "unresolved")),
        max_abs=None if output.get("max_abs") is None else float(output["max_abs"]),
    )


def _strip_legacy_percentage_multiplier(expression: Expression) -> Expression:
    """V2 formulas encoded output formatting (`* 100`) inside arithmetic.

    V3 expressions carry units, so ratio-to-percent conversion belongs to the
    output contract.  Keeping both would multiply percentage answers twice.
    """
    if not isinstance(expression, Arithmetic) or expression.operator != ArithmeticOperator.MULTIPLY:
        return expression
    if isinstance(expression.right, Literal) and expression.right.value == 100.0:
        return expression.left
    if isinstance(expression.left, Literal) and expression.left.value == 100.0:
        return expression.right
    return expression


def _formula_expression(raw: dict[str, Any]) -> Expression:
    node = str(raw.get("node"))
    if node == "FactRef":
        return MetricRef(str(raw["metric_id"]))
    if node == "Literal":
        return Literal(float(raw["value"]), UnitSpec(Dimension.RATIO))
    if node == "Abs":
        return Unary(UnaryOperator.ABSOLUTE, _formula_expression(_dict(raw["child"], "Abs child")))
    binary = {
        "Add": (ArithmeticOperator.ADD, "left", "right"),
        "Subtract": (ArithmeticOperator.SUBTRACT, "left", "right"),
        "Multiply": (ArithmeticOperator.MULTIPLY, "left", "right"),
        "Divide": (ArithmeticOperator.DIVIDE, "num", "den"),
    }.get(node)
    if binary is None:
        raise OntologySourceError(f"unsupported formula node: {node!r}")
    operator, left_key, right_key = binary
    return Arithmetic(
        operator,
        _formula_expression(_dict(raw[left_key], f"{node}.{left_key}")),
        _formula_expression(_dict(raw[right_key], f"{node}.{right_key}")),
    )


def _verified_source(
    sources: dict[str, Any], name: str, manifest_file: Path
) -> tuple[Path, str]:
    raw = _dict(sources.get(name), f"sources.{name}")
    path_value = Path(str(raw["path"]))
    source = path_value if path_value.is_absolute() else _REPO_ROOT / path_value
    if not source.is_file():
        raise OntologySourceError(f"ontology source does not exist: {source}")
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = str(raw["sha256"])
    if actual != expected:
        raise OntologySourceError(
            f"ontology source drift for {name}: expected {expected}, actual {actual}; "
            f"update {manifest_file} only after ontology review"
        )
    return source, actual


def _document(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _dict(raw, str(path))


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OntologySourceError(f"{label} must be a mapping")
    return value


def _normalized_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise OntologySourceError("aliases must be a sequence")
    return tuple(normalize_phrase(str(value)) for value in values)
