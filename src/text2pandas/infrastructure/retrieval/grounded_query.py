"""Expand named/derived metrics into independently retrievable leaf phrases."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from text2pandas.domain.metrics import MetricOntology, normalize_phrase


@dataclass(frozen=True, slots=True)
class GroundedQueryConcept:
    """One canonical metric and the governed aliases used to retrieve it."""

    metric_id: str
    aliases: tuple[str, ...]
    statement_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundedFormulaRequirement:
    """A value-free formula contract that the generated DAG must implement."""

    formula_id: str
    leaves: tuple[str, ...]
    expression: dict[str, object]
    output_dimension: str
    matched_alias: str = ""
    start: int = -1
    role: str = "value"

    def to_planner_dict(self) -> dict[str, object]:
        return {
            "formula_id": self.formula_id,
            "leaves": list(self.leaves),
            "expression": self.expression,
            "output_dimension": self.output_dimension,
            "matched_alias": self.matched_alias,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class GroundedQueryExpansion:
    """Typed retrieval contract derived from the question, without values."""

    phrases: tuple[str, ...]
    concepts: tuple[GroundedQueryConcept, ...]
    formulas: tuple[GroundedFormulaRequirement, ...]

    @property
    def metric_ids(self) -> tuple[str, ...]:
        return tuple(concept.metric_id for concept in self.concepts)


class GroundedQueryExpander:
    """Use the governed ontology to expose every operand of a question.

    Whole-question lexical retrieval systematically overweights the longest
    phrase and starves secondary metrics.  Formula expansion turns one complex
    question into a deterministic union of leaf-metric queries before the LLM
    sees any candidates.
    """

    def __init__(self, ontology: MetricOntology) -> None:
        self.ontology = ontology

    def expand(self, question: str) -> tuple[str, ...]:
        return self.analyze(question).phrases

    def analyze(self, question: str) -> GroundedQueryExpansion:
        normalized = normalize_phrase(question)
        metric_ids: list[str] = []
        formulas: list[GroundedFormulaRequirement] = []
        manual_concepts: list[GroundedQueryConcept] = []
        phrases: list[str] = [question]
        direct_matches: list[tuple[str, str]] = []
        for metric in self.ontology.metrics.values():
            direct_matches.extend(
                (metric.metric_id, alias)
                for alias in metric.aliases
                if alias and alias in normalized
            )
        # Ignore generic aliases embedded in a more specific matched phrase
        # (for example "doanh thu" inside "doanh thu thuan").
        for metric_id, alias in sorted(
            direct_matches,
            key=lambda value: (normalized.find(value[1]), -len(value[1]), value[0]),
        ):
            alias_start = normalized.find(alias)
            if metric_id.startswith("reported_") and "nganh" in normalized[
                max(0, alias_start - 60) : alias_start
            ]:
                continue
            alias_end = alias_start + len(alias)
            if metric_id.startswith("reported_") and any(
                not other_metric.startswith("reported_")
                and other_alias != alias
                and (
                    alias_start < normalized.find(other_alias) + len(other_alias)
                    and normalized.find(other_alias) < alias_end
                )
                for other_metric, other_alias in direct_matches
                if normalized.find(other_alias) >= 0
            ):
                continue
            if any(
                alias != other_alias and alias in other_alias
                for _other_metric, other_alias in direct_matches
            ):
                continue
            metric_ids.append(metric_id)
        formula_matches = [
            (
                ontology_formula,
                alias,
                normalized.find(alias),
                normalized.find(alias) + len(alias),
            )
            for ontology_formula in self.ontology.formulas.values()
            for alias in ontology_formula.aliases
            if alias and alias in normalized
        ]
        for ontology_formula, matched_alias, match_start, match_end in formula_matches:
            if any(
                ontology_formula.formula_id != other_formula.formula_id
                and len(other_alias) > len(matched_alias)
                and match_start < other_end
                and other_start < match_end
                for other_formula, other_alias, other_start, other_end in formula_matches
            ):
                continue
            if not any(
                formula.formula_id == ontology_formula.formula_id
                for formula in formulas
            ):
                metric_ids.extend(ontology_formula.leaves)
                formula_payload = ontology_formula.to_dict()
                expression = formula_payload["expression"]
                if not isinstance(expression, Mapping):  # pragma: no cover - domain contract
                    raise TypeError("formula expression must be a mapping")
                formulas.append(
                    GroundedFormulaRequirement(
                        formula_id=ontology_formula.formula_id,
                        leaves=ontology_formula.leaves,
                        expression=dict(expression),
                        output_dimension=ontology_formula.output_unit.dimension.value,
                        matched_alias=matched_alias,
                        start=normalized.find(matched_alias),
                    )
                )
        for cue, leaves in _DERIVED_ALIASES.items():
            if cue in normalized:
                metric_ids.extend(leaves)
        for cue, concept in _MANUAL_CONCEPTS.items():
            if cue in normalized:
                metric_ids.append(concept.metric_id)
                manual_concepts.append(concept)
                phrases.extend(concept.aliases)
        covered_ontology_metrics = {
            metric_id
            for concept in manual_concepts
            for manual_alias in concept.aliases
            for metric_id, metric in self.ontology.metrics.items()
            if metric_id != concept.metric_id
            and any(
                alias != manual_alias and alias in manual_alias
                for alias in metric.aliases
            )
        }
        if covered_ontology_metrics:
            metric_ids = [
                metric_id
                for metric_id in metric_ids
                if metric_id not in covered_ontology_metrics
            ]
        for cue, manual_formula in _MANUAL_FORMULAS.items():
            if cue in normalized:
                metric_ids.extend(manual_formula.leaves)
                formulas.append(
                    replace(
                        manual_formula,
                        matched_alias=cue,
                        start=normalized.find(cue),
                    )
                )
        for pattern, manual_formula in _MANUAL_FORMULA_PATTERNS:
            match = pattern.search(normalized)
            if match is None:
                continue
            metric_ids.extend(manual_formula.leaves)
            formulas.append(
                replace(
                    manual_formula,
                    matched_alias=match.group(0),
                    start=match.start(),
                )
            )
        for metric_id in dict.fromkeys(metric_ids):
            selected_metric = self.ontology.metrics.get(metric_id)
            if selected_metric is not None:
                phrases.extend(selected_metric.aliases)
        ontology_concepts = tuple(
            GroundedQueryConcept(
                metric_id,
                tuple(selected_metric.aliases),
                selected_metric.statement_types,
            )
            for metric_id in dict.fromkeys(metric_ids)
            if (selected_metric := self.ontology.metrics.get(metric_id)) is not None
        )
        concepts = tuple(
            {
                concept.metric_id: concept
                for concept in (*ontology_concepts, *manual_concepts)
            }.values()
        )
        unique_formulas = tuple(
            {formula.formula_id: formula for formula in formulas}.values()
        )
        return GroundedQueryExpansion(
            tuple(dict.fromkeys(value for value in phrases if value)),
            concepts,
            _assign_formula_roles(normalized, unique_formulas),
        )


# Named ratios intentionally omitted from the reviewed formula registry still
# occur in the generated benchmark.  These entries only expand retrieval; the
# model must build the formula and the deterministic type checker must accept
# it before any answer can be promoted.
_DERIVED_ALIASES: dict[str, tuple[str, ...]] = {
    "dong tien hoat dong": ("cash_flow_from_operations",),
    "cfo": ("cash_flow_from_operations",),
    "lnst": ("profit_after_tax",),
    "so ngay ton kho": ("inventory", "cogs"),
}

_MANUAL_CONCEPTS: dict[str, GroundedQueryConcept] = {
    "chi phi cho phan bo": GroundedQueryConcept(
        "reported_allocated_expenses",
        ("chi phi cho phan bo",),
        ("balance_sheet", "notes"),
    ),
    "loi nhuan thuan tu hoat dong kinh doanh truoc chi phi du phong rui ro tin dung": GroundedQueryConcept(
        "reported_operating_profit_before_credit_provision",
        (
            "loi nhuan thuan tu hoat dong kinh doanh truoc chi phi du phong rui ro tin dung",
        ),
        ("income_statement",),
    ),
    "trich lap/(hoan nhap) du phong chung khoan dau tu san sang de ban": GroundedQueryConcept(
        "reported_afs_provision_charge",
        (
            "trich lap/(hoan nhap) du phong chung khoan dau tu san sang de ban",
            "du phong chung khoan dau tu san sang de ban",
        ),
        ("notes", "note"),
    ),
}


def _ratio_requirement(
    formula_id: str,
    numerator: str,
    denominator: str,
    *,
    output_dimension: str,
) -> GroundedFormulaRequirement:
    return GroundedFormulaRequirement(
        formula_id=formula_id,
        leaves=(numerator, denominator),
        expression={
            "type": "arithmetic",
            "operator": "divide",
            "left": {"type": "metric_ref", "metric_id": numerator},
            "right": {"type": "metric_ref", "metric_id": denominator},
        },
        output_dimension=output_dimension,
    )


_ROE = _ratio_requirement(
    "roe_end_equity",
    "profit_after_tax",
    "equity",
    output_dimension="percent",
)
_ROA = _ratio_requirement(
    "roa_end_assets",
    "profit_after_tax",
    "total_assets",
    output_dimension="percent",
)
_CFO_TO_REVENUE = _ratio_requirement(
    "cash_flow_from_operations_to_net_revenue",
    "cash_flow_from_operations",
    "net_revenue",
    output_dimension="ratio",
)
_CFO_TO_CURRENT_LIABILITIES = _ratio_requirement(
    "cash_flow_from_operations_to_current_liabilities",
    "cash_flow_from_operations",
    "current_liabilities",
    output_dimension="ratio",
)
_CFO_TO_OPERATING_PROFIT = _ratio_requirement(
    "cash_flow_from_operations_to_operating_profit",
    "cash_flow_from_operations",
    "reported_5dafdc9a37317139",
    output_dimension="ratio",
)
_LONG_TERM_ASSETS_TO_ASSETS = _ratio_requirement(
    "long_term_assets_to_total_assets",
    "reported_d58548b4a183bb85",
    "total_assets",
    output_dimension="percent",
)
_DEBT_TO_EQUITY = _ratio_requirement(
    "total_liabilities_to_equity",
    "total_liabilities",
    "equity",
    output_dimension="ratio",
)
_ASSET_TURNOVER_AVERAGE = GroundedFormulaRequirement(
    formula_id="asset_turnover_average_assets",
    leaves=("net_revenue", "total_assets"),
    expression={
        "type": "average_balance_ratio",
        "numerator_metric_id": "net_revenue",
        "denominator_metric_id": "total_assets",
    },
    output_dimension="ratio",
)
_OPERATING_PROFIT_BEFORE_PROVISION_TO_ASSETS = _ratio_requirement(
    "operating_profit_before_credit_provision_to_assets",
    "reported_operating_profit_before_credit_provision",
    "total_assets",
    output_dimension="percent",
)
_CFO_TO_PROFIT_AFTER_TAX = _ratio_requirement(
    "cash_flow_from_operations_to_profit_after_tax",
    "cash_flow_from_operations",
    "profit_after_tax",
    output_dimension="ratio",
)
_CURRENT_RATIO = _ratio_requirement(
    "current_ratio",
    "current_assets",
    "current_liabilities",
    output_dimension="ratio",
)
_QUICK_RATIO = GroundedFormulaRequirement(
    formula_id="quick_ratio",
    leaves=("current_assets", "inventory", "current_liabilities"),
    expression={
        "type": "arithmetic",
        "operator": "divide",
        "left": {
            "type": "arithmetic",
            "operator": "subtract",
            "left": {"type": "metric_ref", "metric_id": "current_assets"},
            "right": {"type": "metric_ref", "metric_id": "inventory"},
        },
        "right": {"type": "metric_ref", "metric_id": "current_liabilities"},
    },
    output_dimension="ratio",
)
_INTEREST_COVERAGE = GroundedFormulaRequirement(
    formula_id="interest_coverage",
    leaves=("profit_before_tax", "interest_expense"),
    expression={
        "type": "arithmetic",
        "operator": "divide",
        "left": {
            "type": "arithmetic",
            "operator": "add",
            "left": {"type": "metric_ref", "metric_id": "profit_before_tax"},
            "right": {
                "type": "unary",
                "operator": "absolute",
                "expression": {
                    "type": "metric_ref",
                    "metric_id": "interest_expense",
                },
            },
        },
        "right": {
            "type": "unary",
            "operator": "absolute",
            "expression": {
                "type": "metric_ref",
                "metric_id": "interest_expense",
            },
        },
    },
    output_dimension="ratio",
)

_MANUAL_FORMULAS: dict[str, GroundedFormulaRequirement] = {
    "roe": _ROE,
    "ty suat sinh loi tren von chu so huu": _ROE,
    "roa": _ROA,
    "ty suat sinh loi tren tai san": _ROA,
    "ty so dong tien hoat dong tren doanh thu thuan": _CFO_TO_REVENUE,
    "dong tien thuan tu hoat dong kinh doanh tren doanh thu thuan": _CFO_TO_REVENUE,
    "dong tien tu hoat dong kinh doanh tren doanh thu thuan": _CFO_TO_REVENUE,
    "cfo tren doanh thu thuan": _CFO_TO_REVENUE,
    "ty so cfo tren doanh thu thuan": _CFO_TO_REVENUE,
    "cfo margin": _CFO_TO_REVENUE,
    "he so dong tien hoat dong tren no ngan han": _CFO_TO_CURRENT_LIABILITIES,
    "dong tien hoat dong tren no ngan han": _CFO_TO_CURRENT_LIABILITIES,
    "ty le luu chuyen tien thuan tu hoat dong kinh doanh tren loi nhuan thuan tu hoat dong kinh doanh": _CFO_TO_OPERATING_PROFIT,
    "luu chuyen tien thuan tu hoat dong kinh doanh tren loi nhuan thuan tu hoat dong kinh doanh": _CFO_TO_OPERATING_PROFIT,
    "ty trong tai san dai han tren tong tai san": _LONG_TERM_ASSETS_TO_ASSETS,
    "vong quay tong tai san": _ASSET_TURNOVER_AVERAGE,
    "loi nhuan thuan tu hoat dong kinh doanh truoc chi phi du phong rui ro tin dung": _OPERATING_PROFIT_BEFORE_PROVISION_TO_ASSETS,
    "cfo tren loi nhuan sau thue": _CFO_TO_PROFIT_AFTER_TAX,
    "luu chuyen tien thuan tu hoat dong kinh doanh tren loi nhuan sau thue": _CFO_TO_PROFIT_AFTER_TAX,
    "dong tien thuan tu hoat dong kinh doanh tren loi nhuan sau thue": _CFO_TO_PROFIT_AFTER_TAX,
    "ti so thanh toan hien hanh": _CURRENT_RATIO,
    "he so thanh toan hien hanh": _CURRENT_RATIO,
    "ti so thanh toan nhanh": _QUICK_RATIO,
    "he so kha nang thanh toan lai vay": _INTEREST_COVERAGE,
    "he so thanh toan lai vay": _INTEREST_COVERAGE,
}

_MANUAL_FORMULA_PATTERNS: tuple[
    tuple[re.Pattern[str], GroundedFormulaRequirement], ...
] = (
    (
        re.compile(
            r"(?:dong tien|luu chuyen tien)[^?]{0,80}"
            r"(?:\(cfo\)|cfo)[^?]{0,20}tren loi nhuan sau thue"
        ),
        _CFO_TO_PROFIT_AFTER_TAX,
    ),
)


def _assign_formula_roles(
    normalized_question: str,
    formulas: tuple[GroundedFormulaRequirement, ...],
) -> tuple[GroundedFormulaRequirement, ...]:
    if len(formulas) < 2:
        return formulas
    roles: dict[str, str] = {}
    threshold_markers = [
        match.start()
        for match in re.finditer(
            r"(?:lon hon|cao hon|tren|nho hon|thap hon|duoi)\s+"
            r"[-+]?\d+(?:[.,]\d+)?",
            normalized_question,
        )
    ]
    if threshold_markers:
        marker = min(threshold_markers)
        candidates = [formula for formula in formulas if 0 <= formula.start < marker]
        if candidates:
            selected = max(candidates, key=lambda value: value.start)
            roles[selected.formula_id] = "filter"
    median_index = normalized_question.find("trung vi")
    if median_index >= 0 and "filter" not in roles.values():
        candidates = [formula for formula in formulas if 0 <= formula.start < median_index]
        if candidates:
            selected = max(candidates, key=lambda value: value.start)
            roles[selected.formula_id] = "filter"
    rank_markers = [
        normalized_question.find(cue)
        for cue in (
            "cao nhat",
            "lon nhat",
            "thap nhat",
            "nho nhat",
            "manh nhat",
        )
        if normalized_question.find(cue) >= 0
    ]
    rank_markers.extend(
        match.start()
        for match in re.finditer(
            r"(?:lon hon|cao hon|nho hon|thap hon)(?!\s+(?:muc\s+)?trung vi)"
            r"(?!\s+[-+]?\d)",
            normalized_question,
        )
    )
    if rank_markers:
        marker = min(rank_markers)
        candidates = [formula for formula in formulas if 0 <= formula.start < marker]
        if candidates:
            selected = max(candidates, key=lambda value: value.start)
            roles[selected.formula_id] = "rank"
    remaining = [formula for formula in formulas if formula.formula_id not in roles]
    if len(remaining) == 1:
        roles[remaining[0].formula_id] = "output"
    return tuple(
        replace(formula, role=roles.get(formula.formula_id, formula.role))
        for formula in formulas
    )
