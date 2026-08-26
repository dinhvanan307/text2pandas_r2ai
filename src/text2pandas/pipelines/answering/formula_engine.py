"""Fail-closed execution of reviewed, per-metric financial formulas."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .binding import CandidateCell
from .frame import classify_operation
from .ir import DIVIDE, LOOKUP
from .pipeline import execute
from .render import cell_expr
from .units import MONEY, PERCENT, RATIO, Unit, query_factor

_REPO_ROOT = Path(__file__).resolve().parents[4]
_FORMULAS = _REPO_ROOT / "configs" / "answer_v2" / "formulas_v1.yaml"
_METRICS = _REPO_ROOT / "configs" / "answer_v2" / "metrics_v1.yaml"
_AGGREGATE_PREFIXES = ("tong cong ", "tong ", "cong ")


@dataclass(frozen=True, slots=True)
class MetricSpec:
    metric_id: str
    aliases: tuple[str, ...]
    statement_types: tuple[str, ...]
    period_semantics: str
    forbidden_aliases: tuple[str, ...]
    forbidden_contains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FormulaSpec:
    formula_id: str
    aliases: tuple[str, ...]
    leaves: tuple[str, ...]
    output_dimension: str
    max_abs_percent: float
    expression: dict


@dataclass(slots=True)
class FormulaAnswer:
    formula_id: str
    status: str
    qid: int | None = None
    stage_failed: str | None = None
    reason: str | None = None
    query: str | None = None
    answer: float | None = None
    evidence: list[dict[str, str]] = field(default_factory=list)
    trace: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "OK"

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "status": self.status,
            "stage_failed": self.stage_failed,
            "reason": self.reason,
            "formula_id": self.formula_id,
            "pandas_query": self.query,
            "answer": self.answer,
            "evidence": self.evidence,
            "trace": self.trace,
        }


@lru_cache(maxsize=1)
def load_registry() -> tuple[dict[str, FormulaSpec], dict[str, MetricSpec]]:
    formula_document = yaml.safe_load(_FORMULAS.read_text(encoding="utf-8"))
    metric_document = yaml.safe_load(_METRICS.read_text(encoding="utf-8"))
    formulas: dict[str, FormulaSpec] = {}
    for raw in formula_document.get("formulas", []):
        output = raw.get("output") or {}
        dimension = PERCENT if output.get("kind") == "percentage" else RATIO
        spec = FormulaSpec(
            formula_id=str(raw["formula_id"]),
            aliases=tuple(_normalize(value) for value in raw.get("aliases", [])),
            leaves=tuple(str(value) for value in raw.get("leaves", [])),
            output_dimension=dimension,
            max_abs_percent=float(output.get("max_abs", 10_000.0)),
            expression=dict(raw["expression"]),
        )
        formulas[spec.formula_id] = spec
    metrics: dict[str, MetricSpec] = {}
    for raw in metric_document.get("metrics", []):
        spec = MetricSpec(
            metric_id=str(raw["metric_id"]),
            aliases=tuple(_normalize(value) for value in raw.get("aliases", [])),
            statement_types=tuple(str(value) for value in raw.get("statement_types", [])),
            period_semantics=str(raw.get("period_semantics", "")),
            forbidden_aliases=tuple(
                _normalize(value) for value in raw.get("forbidden_aliases", [])
            ),
            forbidden_contains=tuple(
                _normalize(value) for value in raw.get("forbidden_contains", [])
            ),
        )
        metrics[spec.metric_id] = spec
    missing = {leaf for formula in formulas.values() for leaf in formula.leaves} - set(metrics)
    if missing:
        raise ValueError(f"formula registry references unknown metrics: {sorted(missing)}")
    return formulas, metrics


def match_formula(question: str) -> FormulaSpec | None:
    normalized = _normalize(question)
    formulas, _ = load_registry()
    matches = [
        (len(alias), formula.formula_id, formula)
        for formula in formulas.values()
        for alias in formula.aliases
        if alias and alias in normalized
    ]
    return max(matches, default=(0, "", None))[2]


def answer_formula_question(
    question: str,
    pool: Sequence[CandidateCell],
    frames: Mapping[str, object],
    *,
    entity: str,
    years: Sequence[int],
    basis: str | None,
    requested_unit: Unit,
    qid: int | None = None,
) -> FormulaAnswer | None:
    """Execute one reviewed formula, or return ``None`` when none is matched."""

    formula = match_formula(question)
    if formula is None:
        return None
    result = FormulaAnswer(formula.formula_id, "OK", qid=qid)
    result.trace.append({"stage": "FORMULA_MATCH", "status": "OK", "formula": formula.formula_id})
    operation = classify_operation(question).op
    if operation not in (LOOKUP, DIVIDE):
        return _fail(result, "ROUTE", f"FORMULA_OUTER_OPERATION_NOT_SUPPORTED:{operation}")
    if len(years) != 1:
        return _fail(result, "ROUTE", "FORMULA_REQUIRES_ONE_PERIOD")
    if requested_unit.dimension != formula.output_dimension:
        return _fail(
            result,
            "ROUTE",
            f"FORMULA_OUTPUT_DIMENSION_MISMATCH:{formula.output_dimension}:{requested_unit.dimension}",
        )

    _, metrics = load_registry()
    ranked_by_metric: dict[str, list[tuple[tuple[float, ...], CandidateCell]]] = {}
    for metric_id in formula.leaves:
        candidates = _rank_metric_candidates(
            metrics[metric_id],
            pool,
            entity=entity,
            year=years[0],
            basis=basis,
        )
        if not candidates:
            return _fail(result, "BIND", f"FORMULA_METRIC_NOT_IN_POOL:{metric_id}")
        ranked_by_metric[metric_id] = candidates
    bound = _bind_coherent_operands(ranked_by_metric)
    if bound is None:
        return _fail(result, "BIND", "FORMULA_OPERANDS_NOT_COHERENT")
    physical = {(cell.csv_path, cell.row_index) for cell in bound.values()}
    if len(physical) != len(bound):
        return _fail(result, "BIND", "FORMULA_DUPLICATE_OPERAND_CELLS")
    result.trace.append(
        {
            "stage": "BIND",
            "status": "OK",
            "operands": {
                metric: {
                    "table_uid": cell.table_uid,
                    "row_path": cell.row_path,
                    "col_label": cell.col_label,
                    "value": cell.value,
                    "unit": cell.unit.describe(),
                    "period": cell.period,
                }
                for metric, cell in bound.items()
            },
        }
    )

    expressions: dict[str, str] = {}
    values: dict[str, float] = {}
    for metric_id, cell in bound.items():
        factor = query_factor(cell.unit, Unit(MONEY, 0, cell.unit.currency), cell.storage_exponent)
        if not factor.ok or factor.factor is None:
            return _fail(result, "RENDER", f"FORMULA_UNIT_ABSTAIN:{metric_id}:{factor.reason}")
        expressions[metric_id] = cell_expr(_operand(cell), factor.factor)
        values[metric_id] = float(cell.value) * factor.factor
    try:
        expected = _evaluate(formula.expression, values)
        query = _render(formula.expression, expressions)
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        return _fail(result, "RENDER", f"FORMULA_EXPRESSION_ERROR:{type(error).__name__}")
    if not math.isfinite(expected):
        return _fail(result, "POLICY", "FORMULA_NON_FINITE")

    used_frames = {cell.df_var: frames[cell.df_var] for cell in bound.values()}
    answer, error = execute(query, used_frames)
    if error or answer is None:
        return _fail(result, "EXECUTE", error or "FORMULA_EXECUTION_FAILED")
    tolerance = 1e-9 * max(1.0, abs(expected))
    if abs(answer - expected) > tolerance:
        return _fail(result, "VALIDATE", "FORMULA_RENDER_VALUE_MISMATCH")
    if formula.output_dimension == PERCENT and abs(answer) > formula.max_abs_percent:
        return _fail(result, "VALIDATE", "FORMULA_PERCENT_OUT_OF_RANGE")

    result.query = query
    result.answer = answer
    seen: set[str] = set()
    for metric_id in formula.leaves:
        cell = bound[metric_id]
        if cell.df_var not in seen:
            seen.add(cell.df_var)
            result.evidence.append({"variable": cell.df_var, "csv_path": cell.csv_path})
    result.trace.extend(
        [
            {"stage": "RENDER", "status": "OK", "query": query},
            {"stage": "EXECUTE", "status": "OK", "answer": answer},
            {"stage": "VALIDATE", "status": "PASS"},
        ]
    )
    return result


def _fail(result: FormulaAnswer, stage: str, reason: str) -> FormulaAnswer:
    result.status = "ABSTAIN"
    result.stage_failed = stage
    result.reason = reason
    result.trace.append({"stage": stage, "status": "ABSTAIN", "reason": reason})
    return result


def _rank_metric_candidates(
    spec: MetricSpec,
    pool: Sequence[CandidateCell],
    *,
    entity: str,
    year: int,
    basis: str | None,
) -> list[tuple[tuple[float, ...], CandidateCell]]:
    ranked: list[tuple[tuple[float, ...], CandidateCell]] = []
    for cell in pool:
        if cell.entity != entity or not cell.period or cell.period[:4] != str(year):
            continue
        if basis and cell.basis != basis:
            continue
        if (
            cell.statement_type
            and spec.statement_types
            and cell.statement_type not in spec.statement_types
        ):
            continue
        if cell.unit.dimension != MONEY:
            continue
        match = _metric_match(spec, cell.row_path.rsplit("›", 1)[-1])
        if match is None:
            continue
        direct, alias_length = match
        ranked.append(
            (
                (
                    float(direct),
                    float(alias_length),
                    _period_role_score(spec, cell),
                    _section_relevance(spec, cell),
                    1.0 if not cell.is_restated else 0.0,
                    -float(cell.row_path.count("›")),
                    -float(cell.table_rank),
                    -float(cell.row_index),
                ),
                cell,
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _period_role_score(spec: MetricSpec, cell: CandidateCell) -> float:
    role = (cell.period_role or "").casefold()
    column = _normalize(cell.col_label)
    if spec.period_semantics == "point_in_time":
        if role == "closing" or any(
            cue in column for cue in ("so cuoi nam", "cuoi nam", "31 12", "tai ngay")
        ):
            return 3.0
        if role in {"opening", "prior"}:
            return 2.0
        # A generic `current` column in a movement table is not a balance.
        return 0.0 if role == "current" else 1.0
    if role == "current":
        return 3.0
    if role == "prior":
        return 2.0
    return 1.0


def _section_relevance(spec: MetricSpec, cell: CandidateCell) -> float:
    section_tokens = set(_normalize(cell.section_text).split())
    if not section_tokens:
        return 0.0
    return max(
        (
            len(section_tokens.intersection(alias.split())) / max(1, len(alias.split()))
            for alias in spec.aliases
        ),
        default=0.0,
    )


def _bind_coherent_operands(
    ranked_by_metric: Mapping[str, Sequence[tuple[tuple[float, ...], CandidateCell]]],
) -> dict[str, CandidateCell] | None:
    """Choose all leaves from one report and one currency.

    Period, entity and accounting basis alone are not sufficient: annual
    reports repeat prior-year values in notes and dimensional breakdowns. A
    cross-report formula can therefore be executable while being semantically
    false. Formula operands must share the same source document; test fixtures
    without document metadata are treated as one explicit unknown group.
    """

    document_sets = [
        {cell.document_id or "__unknown__" for _, cell in ranked}
        for ranked in ranked_by_metric.values()
    ]
    common_documents = set.intersection(*document_sets) if document_sets else set()
    groups: list[tuple[tuple[float, ...], str, dict[str, CandidateCell]]] = []
    for document_id in sorted(common_documents):
        selected: dict[str, CandidateCell] = {}
        scores: list[tuple[float, ...]] = []
        for metric_id, ranked in ranked_by_metric.items():
            score, cell = next(
                item for item in ranked if (item[1].document_id or "__unknown__") == document_id
            )
            selected[metric_id] = cell
            scores.append(score)
        currencies = {cell.unit.currency for cell in selected.values()}
        if len(currencies) != 1:
            continue
        physical = {(cell.csv_path, cell.row_index) for cell in selected.values()}
        if len(physical) != len(selected):
            continue
        aggregate = tuple(sum(score[index] for score in scores) for index in range(len(scores[0])))
        groups.append((aggregate, document_id, selected))
    if not groups:
        return None
    groups.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return groups[0][2]


def _metric_match(spec: MetricSpec, label: str) -> tuple[int, int] | None:
    normalized = _normalize(label)
    if not normalized or any(normalized.startswith(value) for value in spec.forbidden_aliases):
        return None
    if any(value in normalized for value in spec.forbidden_contains):
        return None
    direct = [alias for alias in spec.aliases if _prefix_match(normalized, alias)]
    if direct:
        return 1, max(map(len, direct))
    stripped = normalized
    for prefix in _AGGREGATE_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :]
            break
    if stripped == normalized or any(
        stripped.startswith(value) for value in spec.forbidden_aliases
    ):
        return None
    aliases = [alias for alias in spec.aliases if _prefix_match(stripped, alias)]
    return (0, max(map(len, aliases))) if aliases else None


def _prefix_match(value: str, alias: str) -> bool:
    return value == alias or value.startswith(alias + " ")


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", (value or "").casefold())
    plain = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", plain.replace("đ", "d")).strip()


@dataclass(frozen=True, slots=True)
class _RenderedOperand:
    role: str
    cell: CandidateCell


def _operand(cell: CandidateCell) -> _RenderedOperand:
    return _RenderedOperand("formula_leaf", cell)


def _render(node: dict, expressions: Mapping[str, str]) -> str:
    kind = node.get("node")
    if kind == "FactRef":
        return expressions[str(node["metric_id"])]
    if kind == "Literal":
        return repr(float(node["value"]))
    if kind == "Abs":
        return f"abs({_render(node['child'], expressions)})"
    operators = {"Add": "+", "Subtract": "-", "Multiply": "*", "Divide": "/"}
    if kind in operators:
        left_key, right_key = ("num", "den") if kind == "Divide" else ("left", "right")
        return (
            f"({_render(node[left_key], expressions)} {operators[kind]} "
            f"{_render(node[right_key], expressions)})"
        )
    raise ValueError(f"unsupported formula node: {kind!r}")


def _evaluate(node: dict, values: Mapping[str, float]) -> float:
    kind = node.get("node")
    if kind == "FactRef":
        return values[str(node["metric_id"])]
    if kind == "Literal":
        return float(node["value"])
    if kind == "Abs":
        return abs(_evaluate(node["child"], values))
    if kind == "Divide":
        denominator = _evaluate(node["den"], values)
        if denominator == 0:
            raise ZeroDivisionError
        return _evaluate(node["num"], values) / denominator
    if kind == "Add":
        return _evaluate(node["left"], values) + _evaluate(node["right"], values)
    if kind == "Subtract":
        return _evaluate(node["left"], values) - _evaluate(node["right"], values)
    if kind == "Multiply":
        return _evaluate(node["left"], values) * _evaluate(node["right"], values)
    raise ValueError(f"unsupported formula node: {kind!r}")
