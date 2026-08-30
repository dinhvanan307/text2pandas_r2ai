"""Expand named/derived metrics into independently retrievable leaf phrases."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace

from text2pandas.application.parsing import SemanticParser
from text2pandas.domain.metrics import MetricOntology, normalize_phrase
from text2pandas.domain.semantic import (
    Basis,
    MetricBindingHint,
    MetricRef,
    PeriodSemantics,
    QuestionAST,
    iter_metric_refs,
)


@dataclass(frozen=True, slots=True)
class GroundedQueryConcept:
    """One canonical metric and the governed aliases used to retrieve it."""

    metric_id: str
    aliases: tuple[str, ...]
    statement_types: tuple[str, ...] = ()
    period_semantics: PeriodSemantics = PeriodSemantics.UNKNOWN
    preferred_basis: Basis = Basis.UNSPECIFIED
    forbidden_prefixes: tuple[str, ...] = ()
    forbidden_contains: tuple[str, ...] = ()
    query_surfaces: tuple[str, ...] = ()
    required_context_phrases: tuple[str, ...] = ()
    metric_codes: tuple[str, ...] = ()


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
    semantic_ast: QuestionAST | None = None

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

    def __init__(
        self,
        ontology: MetricOntology,
        parser: SemanticParser | None = None,
    ) -> None:
        self.ontology = ontology
        self.parser = parser

    def expand(self, question: str) -> tuple[str, ...]:
        return self.analyze(question).phrases

    def analyze(self, question: str) -> GroundedQueryExpansion:
        normalized = normalize_phrase(question)
        semantic_ast: QuestionAST | None = None
        source_bindings: tuple[MetricBindingHint, ...] = ()
        if self.parser is not None:
            parsed = self.parser.parse(question)
            source_bindings = parsed.source_bindings
            if parsed.ok:
                semantic_ast = parsed.ast
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
        query_surfaces_by_metric: dict[str, tuple[str, ...]] = {
            metric_id: tuple(
                dict.fromkeys(
                    surface
                    for matched_metric, alias in direct_matches
                    if matched_metric == metric_id
                    and (surface := _query_metric_surface(normalized, alias))
                )
            )
            for metric_id in dict.fromkeys(metric_ids)
        }
        ontology_concepts = tuple(
            GroundedQueryConcept(
                metric_id,
                tuple(selected_metric.aliases),
                selected_metric.statement_types,
                selected_metric.period_semantics,
                selected_metric.preferred_basis,
                selected_metric.forbidden_prefixes,
                selected_metric.forbidden_contains,
                query_surfaces_by_metric.get(metric_id, ()),
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
        concepts = _enrich_concepts_with_source_bindings(concepts, source_bindings)
        if semantic_ast is not None:
            semantic_refs = tuple(iter_metric_refs(semantic_ast.expression))
            semantic_concepts = tuple(
                _concept_from_metric_ref(reference, self.ontology)
                for reference in semantic_refs
            )
            semantic_concepts = tuple(
                {
                    concept.metric_id: concept
                    for concept in semantic_concepts
                }.values()
            )
            if any(reference.source_binding is not None for reference in semantic_refs):
                # Source-resolved ASTs are scoped against A6.  Keeping a second
                # lexical metric interpretation would make retrieval and plan
                # validation disagree about the same noun phrase.
                concepts = semantic_concepts
            else:
                lexical_concepts = {concept.metric_id: concept for concept in concepts}
                merged_semantic_concepts = tuple(
                    replace(
                        concept,
                        aliases=tuple(
                            dict.fromkeys(
                                (
                                    *lexical_concepts.get(
                                        concept.metric_id, concept
                                    ).aliases,
                                    *concept.aliases,
                                )
                            )
                        ),
                        query_surfaces=tuple(
                            dict.fromkeys(
                                (
                                    *lexical_concepts.get(
                                        concept.metric_id, concept
                                    ).query_surfaces,
                                    *concept.query_surfaces,
                                )
                            )
                        ),
                        required_context_phrases=tuple(
                            dict.fromkeys(
                                (
                                    *lexical_concepts.get(
                                        concept.metric_id, concept
                                    ).required_context_phrases,
                                    *concept.required_context_phrases,
                                )
                            )
                        ),
                    )
                    for concept in semantic_concepts
                )
                concepts = tuple(
                    {
                        concept.metric_id: concept
                        for concept in (*concepts, *merged_semantic_concepts)
                    }.values()
                )
            for concept in semantic_concepts:
                phrases.extend(concept.aliases)
        unique_formulas = tuple(
            {formula.formula_id: formula for formula in formulas}.values()
        )
        if "von chu so huu binh quan" in normalized or (
            "roe" in normalized and "binh quan dau va cuoi ky" in normalized
        ):
            unique_formulas = tuple(
                replace(
                    _ROE_AVERAGE_EQUITY,
                    matched_alias=formula.matched_alias,
                    start=formula.start,
                    role=formula.role,
                )
                if formula.formula_id == _ROE.formula_id
                else formula
                for formula in unique_formulas
            )
        return GroundedQueryExpansion(
            tuple(dict.fromkeys(value for value in phrases if value)),
            concepts,
            _assign_formula_roles(normalized, unique_formulas),
            semantic_ast,
        )


def _concept_from_metric_ref(
    reference: MetricRef,
    ontology: MetricOntology,
) -> GroundedQueryConcept:
    source = reference.source_binding
    metric = ontology.metrics.get(reference.metric_id)
    aliases = (
        source.labels
        if source is not None
        else (() if metric is None else metric.aliases)
    )
    statement_types = (
        reference.statement_types
        or (() if metric is None else metric.statement_types)
    )
    semantics = reference.period_semantics
    if semantics is PeriodSemantics.UNKNOWN and metric is not None:
        semantics = metric.period_semantics
    preferred_basis = reference.basis
    if preferred_basis is Basis.UNSPECIFIED:
        if source is not None:
            preferred_basis = source.preferred_basis
        elif metric is not None:
            preferred_basis = metric.preferred_basis
    return GroundedQueryConcept(
        metric_id=reference.metric_id,
        aliases=tuple(dict.fromkeys(normalize_phrase(value) for value in aliases if value)),
        statement_types=statement_types,
        metric_codes=() if source is None else source.metric_codes,
        period_semantics=semantics,
        preferred_basis=preferred_basis,
        forbidden_prefixes=() if metric is None else metric.forbidden_prefixes,
        forbidden_contains=() if metric is None else metric.forbidden_contains,
        # A6 already resolved the source identity to physical labels/rows.
        # Its contiguous n-gram may include an adjacent entity name (for
        # example ``Sai Gon Thuong Tin, lai thuan ...``); that text is scope,
        # not a qualifier the physical accounting row must repeat.
        query_surfaces=(
            ()
            if source is None
            else tuple(dict.fromkeys(normalize_phrase(value) for value in aliases))
        ),
        required_context_phrases=reference.required_context_phrases,
    )


def _enrich_concepts_with_source_bindings(
    concepts: tuple[GroundedQueryConcept, ...],
    bindings: tuple[MetricBindingHint, ...],
) -> tuple[GroundedQueryConcept, ...]:
    """Carry A6 structural identity into lexical fallback contracts.

    A parser may understand every physical metric mention yet abstain on the
    surrounding composition.  The downstream deterministic compiler can still
    use those mentions, but retrieval must not discard their statement codes.
    Bindings are attached only to the best matching lexical concept so evidence
    for one operand cannot leak into another overlapping metric.
    """

    enriched = list(concepts)
    for binding in bindings:
        labels = tuple(normalize_phrase(value) for value in binding.labels if value)
        surface = normalize_phrase(binding.question_surface)
        ranked: list[tuple[tuple[int, int, int], int]] = []
        for index, concept in enumerate(enriched):
            aliases = tuple(normalize_phrase(value) for value in concept.aliases if value)
            exact = sum(alias == label for alias in aliases for label in labels)
            contained = max(
                (
                    min(len(alias), len(label))
                    for alias in aliases
                    for label in labels
                    if alias in label or label in alias
                ),
                default=0,
            )
            surface_match = max(
                (len(alias) for alias in aliases if alias and alias in surface),
                default=0,
            )
            if exact or contained or surface_match:
                ranked.append(((exact, contained, surface_match), index))
        if not ranked:
            continue
        _score, winner = max(ranked, key=lambda value: (value[0], -value[1]))
        concept = enriched[winner]
        enriched[winner] = replace(
            concept,
            aliases=tuple(dict.fromkeys((*concept.aliases, *labels))),
            metric_codes=tuple(
                dict.fromkeys((*concept.metric_codes, *binding.metric_codes))
            ),
        )
    return tuple(enriched)


_SURFACE_RIGHT_BOUNDARIES = frozenset(
    {
        "cua",
        "nam",
        "trong",
        "den",
        "tai",
        "vao",
        "la",
        "o",
        "giai",
        "giua",
        "bao",
        "cuoi",
        "dau",
        "cao",
        "thap",
        "lon",
        "nho",
        "nhat",
        "hon",
        "duong",
        "am",
        "tang",
        "giam",
        "ky",
    }
)
_SURFACE_LEFT_BOUNDARIES = frozenset(
    {
        "hay",
        "tinh",
        "xac",
        "dinh",
        "cho",
        "biet",
        "giua",
        "va",
        "nhung",
        "ma",
        "khi",
        "neu",
        "tu",
        "thay",
        "doi",
        "chenh",
        "lech",
        "binh",
        "quan",
        "trung",
        "tang",
        "truong",
        "bien",
        "co",
        "muc",
        "he",
        "vong",
        "quay",
        "le",
        "ty",
        "tren",
        "duoi",
        "theo",
        "nhan",
        "chia",
    }
)

_SURFACE_OUTPUT_BOUNDARIES = frozenset(
    {
        "so",
        "voi",
        "tinh",
        "don",
        "vi",
        "dong",
        "trieu",
        "ty",
        "nghin",
        "tram",
        "phan",
        "lan",
        "diem",
    }
)


def _query_metric_surface(question: str, alias: str) -> str:
    """Return the local noun phrase that qualified a matched ontology alias.

    Reported aliases are intentionally broad (for example ``hang hoa``).  The
    complete question may qualify that phrase as ``gia von hang hoa``.  Keeping
    this local surface lets fact resolution distinguish the accounting concept
    without creating a question-specific metric ID.
    """

    question_tokens = re.findall(r"[a-z0-9]+", question)
    alias_tokens = re.findall(r"[a-z0-9]+", alias)
    if not alias_tokens:
        return ""
    start = next(
        (
            index
            for index in range(len(question_tokens) - len(alias_tokens) + 1)
            if question_tokens[index : index + len(alias_tokens)] == alias_tokens
        ),
        -1,
    )
    if start < 0:
        return alias
    prefix = " ".join(question_tokens[:start])
    accounting_scope = re.search(
        r"\b(gia tri con lai|gia tri hao mon luy ke|nguyen gia) cua$",
        prefix,
    )
    if accounting_scope is not None:
        return f"{accounting_scope.group(1)} {alias}"
    left = start
    while (
        left > 0
        and start - left < 3
        and not question_tokens[left - 1].isdigit()
        and question_tokens[left - 1] not in _SURFACE_LEFT_BOUNDARIES
        and question_tokens[left - 1] not in _SURFACE_RIGHT_BOUNDARIES
    ):
        left -= 1
    # ``tổng`` is part of the accounting surface (and may distinguish a total
    # from a component), but it also starts a fresh operand after an entity
    # list.  Do not leak the final ticker from that list into the metric
    # qualifier, e.g. ``..., MSR và NKG, tổng doanh thu thuần``.
    if start > 0 and question_tokens[start - 1] == "tong":
        left = start - 1
    right = start + len(alias_tokens)
    while (
        right < len(question_tokens)
        and right - (start + len(alias_tokens)) < 2
        and question_tokens[right] not in _SURFACE_RIGHT_BOUNDARIES
        and question_tokens[right] not in _SURFACE_OUTPUT_BOUNDARIES
    ):
        right += 1
    return " ".join(question_tokens[left:right])


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
_ROE_AVERAGE_EQUITY = GroundedFormulaRequirement(
    formula_id="roe_average_equity",
    leaves=("profit_after_tax", "equity"),
    expression={
        "type": "average_balance_ratio",
        "numerator_metric_id": "profit_after_tax",
        "denominator_metric_id": "equity",
    },
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
