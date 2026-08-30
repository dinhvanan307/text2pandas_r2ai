"""Resolve physical A6 observations into one governed logical financial fact.

A6 intentionally preserves every physical observation.  The same economic fact
can therefore occur in a primary statement, a note, a comparative column and a
restated report.  Selecting the first lexical hit is not a valid deduplication
strategy: it erases the metadata needed to decide which observation represents
the question's requested fact.

This module performs resolution after high-recall retrieval.  It is independent
of QIDs and numeric gold labels; decisions are based on the metric contract,
period/basis semantics and source quality only.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from text2pandas.application.usecases.grounded_synthesis import GroundedFact
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import Basis, PeriodSemantics


@dataclass(frozen=True, slots=True)
class LogicalMetricContract:
    metric_id: str
    aliases: tuple[str, ...] = ()
    statement_types: tuple[str, ...] = ()
    period_semantics: PeriodSemantics = PeriodSemantics.UNKNOWN
    preferred_basis: Basis = Basis.UNSPECIFIED
    forbidden_prefixes: tuple[str, ...] = ()
    forbidden_contains: tuple[str, ...] = ()
    query_surfaces: tuple[str, ...] = ()
    required_context_phrases: tuple[str, ...] = ()
    metric_codes: tuple[str, ...] = ()


_CORE_METRIC_CODES: dict[str, frozenset[str]] = {
    "net_revenue": frozenset({"10"}),
    "cogs": frozenset({"11"}),
    "gross_profit": frozenset({"20"}),
    "profit_before_tax": frozenset({"50"}),
    "profit_after_tax": frozenset({"60"}),
    "interest_expense": frozenset({"23"}),
    "cash_flow_from_operations": frozenset({"20"}),
    "current_assets": frozenset({"100"}),
    # B01 code 140 is the net balance-sheet inventory used by financial
    # ratios.  Code 141 is gross inventory before the code-149 provision and
    # must not compete as the same canonical metric.
    "inventory": frozenset({"140"}),
    "total_assets": frozenset({"270"}),
    "total_liabilities": frozenset({"300"}),
    "current_liabilities": frozenset({"310"}),
    "equity": frozenset({"400", "410"}),
    "short_term_borrowings": frozenset({"320"}),
}

_CLOSING_RE = re.compile(
    r"(?:cuoi (?:nam|ky)|so du cuoi|den ngay|tai ngay|31\s*/\s*12|31\s+thang\s+12)"
)
_OPENING_RE = re.compile(
    r"(?:dau (?:nam|ky)|so du dau|(?<!\d)0?1\s*/\s*0?1(?!\d))"
)
_RESTATED_RE = re.compile(r"(?:trinh bay lai|dieu chinh|restated)")
_OPENING_DATE_RE = re.compile(
    r"\b0?1(?:\s+|\s*/\s*)0?1(?:\s+|\s*/\s*)((?:19|20)\d{2})(?!\d)"
)
_MOVEMENT_COLUMN_CUES = (
    "phat sinh trong nam",
    "so phai nop",
    "da nop",
    "tang trong nam",
    "giam trong nam",
    "bien dong trong nam",
    "trong ky",
)
_MOVEMENT_CONTEXT_CUES = (
    "trich lap",
    "hoan nhap",
    "tang trong nam",
    "giam trong nam",
)
_OPENING_COLUMN_CUES = (
    "so dau nam",
    "so du dau nam",
    "dau ky",
    "tai ngay dau nam",
    "01 01",
    "01/01",
    "nam truoc",
)
_CLOSING_COLUMN_CUES = (
    "so cuoi nam",
    "so du cuoi nam",
    "cuoi ky",
    "tai ngay cuoi nam",
    "31 12",
    "31/12",
    "tai ngay",
)
_NON_PRIMARY_TOTAL_CONTEXT = (
    "phan tich tai san va cong no theo ky han",
    "theo ky han lai suat",
    "rui ro thanh khoan",
    "rui ro lai suat",
    "rui ro tien te",
    "rui ro ngoai hoi",
    "tai san dam bao",
    "gia tri hop ly",
    "truong hop doanh thu duoc phan bo",
)
_ASSET_ROLL_FORWARD_CONTEXT = (
    "tai san co dinh",
    "bat dong san dau tu",
)
_UNRELATED_BANKING_BALANCE_CONTEXT = (
    "chi phi hoat dong",
    "thong tin theo bo phan",
)
_SEGMENT_REPORT_CONTEXT = (
    "bao cao bo phan",
    "thong tin theo bo phan",
    "thong tin bo phan",
    "ket qua theo bo phan",
)
_PRIMARY_STATEMENT_CONTEXT = (
    "bang can doi ke toan",
    "bao cao tinh hinh tai chinh",
    "bao cao ket qua hoat dong kinh doanh",
    "bao cao luu chuyen tien te",
    "b01 dn",
    "b01-dn",
    "b02 dn",
    "b02-dn",
    "b03 dn",
    "b03-dn",
    "b02 tctd",
    "b02/tctd",
    "b03 tctd",
    "b03/tctd",
)
_EXPENSE_BY_NATURE_LEAVES = (
    "chi phi dich vu mua ngoai",
    "chi phi nhan vien",
    "chi phi nguyen lieu vat lieu",
    "chi phi khau hao",
)
_EXPENSE_BY_NATURE_CONTEXT = (
    "chi phi san xuat kinh doanh theo yeu to",
    "chi phi kinh doanh theo yeu to",
)
_FUNCTIONAL_EXPENSE_CONTEXT = (
    "chi phi ban hang",
    "chi phi quan ly doanh nghiep",
)
_SECURITY_PORTFOLIO_CONTEXT = (
    "chung khoan kinh doanh",
    "san sang de ban",
    "giu den ngay dao han",
)
_FIXED_ASSET_CLASS_CUES = (
    "nha cua",
    "vat kien truc",
    "may moc",
    "thiet bi",
    "phuong tien van tai",
    "thiet bi van phong",
    "tai san co dinh khac",
)
_TOTAL_REQUEST_RE = re.compile(r"\btong\s+(?!cong\s+ty|cong\b|tap\s+doan|ngan\s+hang)")
_GENERIC_SURFACE_TOKENS = frozenset(
    {
        "bao",
        "nhieu",
        "tong",
        "cong",
        "gia",
        "tri",
        "tien",
        "so",
        "du",
        "no",
        "cua",
        "tai",
        "nam",
        "trong",
        "den",
        "vao",
        "la",
        "phai",
        "nop",
        "cuoi",
        "dau",
        "ky",
        "co",
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
        "vnd",
        "usd",
        "bang",
        "chi",
        "phi",
        "cac",
        "khoan",
        "muc",
        "goc",
        # Relational grammar belongs to the expression, not to either source
        # metric.  Treating these words as physical-source qualifiers makes a
        # perfectly grounded ratio/margin look semantically incomplete.
        "bien",
        "vong",
        "quay",
        "va",
        "nhung",
        "ma",
        "neu",
        "khi",
        "tu",
        "thay",
        "doi",
        "chenh",
        "lech",
        "binh",
        "quan",
        "trung",
        "truong",
        "tren",
        "voi",
        "ty",
        "ti",
        "le",
        "phan",
        "tram",
    }
)
# Only governed physical-source language may become a hard row qualifier.
# Arbitrary neighbouring words in a natural-language question include entity
# names and semantic operators (CAGR, rank, subtract, threshold, ...); requiring
# those words to appear in an accounting row creates systematic false
# negatives.  This vocabulary captures source distinctions that the physical
# report can actually express.  Metric aliases themselves are removed later.
_PHYSICAL_SURFACE_QUALIFIER_TOKENS = frozenset(
    {
        "ngan",
        "dai",
        "han",
        "con",
        "lai",
        "nguyen",
        "hao",
        "mon",
        "luy",
        "ke",
        "nha",
        "vat",
        "kien",
        "truc",
        "may",
        "moc",
        "thiet",
        "bi",
        "phuong",
        "tien",
        "van",
        "tai",
        "phong",
        "hang",
        "hoa",
        "kho",
        "von",
        "me",
        "rieng",
        "hop",
        "nhat",
        "vay",
        "thue",
    }
)
_SOURCE_ALIAS_GLUE_TOKENS = frozenset(
    {
        "cac",
        "khoan",
        "tong",
        "cong",
        "gia",
        "tri",
        "so",
        "du",
        "cua",
        "tai",
        "trong",
        "den",
        "vao",
        "la",
        "va",
        "cho",
        "bang",
        "muc",
        "tieu",
    }
)


class LogicalFactResolver:
    """Collapse observation duplicates only after semantic source resolution."""

    def __init__(
        self,
        question: str,
        *,
        requested_periods: Sequence[str] = (),
        requested_basis: Basis = Basis.UNSPECIFIED,
        contracts: Sequence[LogicalMetricContract] = (),
    ) -> None:
        self.question = normalize_phrase(question)
        self.requested_years = frozenset(
            value[:4] for value in requested_periods if len(value) >= 4
        )
        self.requested_basis = requested_basis
        self.contracts = {contract.metric_id: contract for contract in contracts}
        self.explicit_closing = bool(_CLOSING_RE.search(self.question))
        self.explicit_opening = bool(_OPENING_RE.search(self.question))
        self.requests_restated = bool(_RESTATED_RE.search(self.question))

    def resolve(
        self,
        facts: Sequence[GroundedFact],
        *,
        limit: int,
    ) -> tuple[GroundedFact, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        groups: dict[
            tuple[str, int | None, Basis, str, str],
            list[GroundedFact],
        ] = defaultdict(list)
        for fact in facts:
            metric = fact.retrieval_metric or normalize_phrase(fact.row_path.rsplit("›", 1)[-1])
            groups[
                (
                    fact.entity,
                    fact.period_year,
                    fact.basis,
                    metric,
                    _logical_component_key(fact, metric),
                )
            ].append(fact)

        resolved_groups: list[tuple[GroundedFact, str]] = []
        for group_key, candidates in groups.items():
            ranked = [self._score(fact) for fact in candidates]
            ranked.sort(key=lambda item: (-item.score, item.observation_uid))
            safe_ranked = [
                fact for fact in ranked if not has_hard_logical_fact_conflict(fact)
            ]
            eligible = safe_ranked or ranked
            top = eligible[0]
            second_score = eligible[1].score if len(eligible) > 1 else None
            corroboration = self._corroboration(top, ranked)
            margin = None if second_score is None else top.score - second_score
            reasons = (*top.score_reasons, f"corroboration:{corroboration}")
            resolved_groups.append(
                (
                    replace(
                        top,
                        resolution_margin=margin,
                        corroboration_count=corroboration,
                        score_reasons=reasons,
                    ),
                    group_key[-1],
                )
            )

        by_scope: dict[
            tuple[str, int | None, Basis, str],
            list[tuple[GroundedFact, str]],
        ] = defaultdict(list)
        for fact, component in resolved_groups:
            by_scope[
                (
                    fact.entity,
                    fact.period_year,
                    fact.basis,
                    fact.retrieval_metric or "",
                )
            ].append((fact, component))
        winners: list[GroundedFact] = []
        for values in by_scope.values():
            safe_totals = [
                fact
                for fact, component in values
                if not component and not has_hard_logical_fact_conflict(fact)
            ]
            if safe_totals:
                winners.extend(safe_totals)
                continue
            safe_components = [
                fact
                for fact, component in values
                if component and not has_hard_logical_fact_conflict(fact)
            ]
            winners.extend(safe_components or [fact for fact, _component in values])

        winners.sort(key=lambda item: (-item.score, item.observation_uid))
        return self._diversify(winners, limit)

    def _score(self, fact: GroundedFact) -> GroundedFact:
        metric = fact.retrieval_metric or ""
        contract = self.contracts.get(metric, LogicalMetricContract(metric))
        adjustment = 0.0
        reasons: list[str] = []

        leaf = normalize_phrase(fact.row_path.rsplit("›", 1)[-1])
        column = normalize_phrase(fact.column_path)
        context = normalize_phrase(f"{fact.row_path} {fact.column_path} {fact.section_text}")
        aliases = tuple(normalize_phrase(value) for value in contract.aliases if value)
        surfaces = tuple(normalize_phrase(value) for value in contract.query_surfaces if value)
        exact_row = any(leaf == alias for alias in aliases)
        prefix_row = any(
            leaf.startswith(alias + " ") or alias.startswith(leaf + " ")
            for alias in aliases
            if leaf and alias
        )
        contained_row = any(
            f" {alias} " in f" {leaf} " or f" {leaf} " in f" {alias} "
            for alias in aliases
            if len(leaf) > 2 and len(alias) > 2
        )
        expected_codes = frozenset(contract.metric_codes) or _CORE_METRIC_CODES.get(
            metric, frozenset()
        )
        code_match = bool(
            expected_codes
            and (
                fact.metric_code in expected_codes
                or _row_declares_metric_code(fact.row_path, expected_codes)
            )
        )

        source_context_complete = False
        if metric.startswith("source_") and aliases:
            context_tokens = _metric_identity_tokens(context)
            alias_token_sets = tuple(
                _metric_identity_tokens(alias) - _SOURCE_ALIAS_GLUE_TOKENS for alias in aliases
            )
            source_context_complete = any(
                tokens and tokens <= context_tokens for tokens in alias_token_sets
            )
            if not source_context_complete:
                closest = max(
                    alias_token_sets,
                    key=lambda tokens: len(tokens & context_tokens),
                )
                missing_alias = closest - context_tokens
                adjustment -= 500.0
                reasons.append(
                    "metric:missing_source_alias_tokens:" + ",".join(sorted(missing_alias))
                )

        row_context = normalize_phrase(fact.row_path)
        alias_requests_short_term = any("ngan han" in alias for alias in aliases)
        alias_requests_long_term = any("dai han" in alias for alias in aliases)
        if alias_requests_short_term and "dai han" in row_context:
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:long_term_for_short_term")
        if alias_requests_long_term and "ngan han" in row_context:
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:short_term_for_long_term")

        if code_match:
            adjustment += 130.0
            reasons.append("metric:governed_code")
        if exact_row:
            adjustment += 120.0
            reasons.append("metric:exact_row")
        elif prefix_row:
            adjustment += 75.0
            reasons.append("metric:prefix_row")
        elif contained_row:
            adjustment += 35.0
            reasons.append("metric:contained_row")
        elif source_context_complete:
            adjustment += 90.0
            reasons.append("metric:source_context_complete")
        elif aliases:
            # A column may name a balance category while the physical row is
            # merely "I" or another subtotal.  That is not the requested row.
            adjustment -= 120.0
            reasons.append("metric:column_or_context_only")

        if any(_prefix(leaf, value) for value in contract.forbidden_prefixes):
            adjustment -= 220.0
            reasons.append("metric:forbidden_prefix")
        if any(value and value in leaf for value in contract.forbidden_contains):
            adjustment -= 220.0
            reasons.append("metric:forbidden_qualifier")

        surface_qualifiers = _surface_qualifiers(surfaces, aliases)
        if surface_qualifiers:
            context_tokens = _semantic_tokens(context)
            missing_qualifiers = surface_qualifiers - context_tokens
            if (
                missing_qualifiers <= {"ngan", "han"}
                and "chi phi phai tra" in context
                and (fact.period_role or "") in {"closing", "current"}
            ):
                missing_qualifiers = set()
                reasons.append("metric:implied_short_term_accrual")
            if (
                missing_qualifiers <= {"con", "lai"}
                and metric == "tangible_fixed_assets"
                and fact.metric_code == "221"
                and (fact.period_role or "") in {"closing", "current"}
            ):
                missing_qualifiers = set()
                reasons.append("metric:implied_fixed_asset_carrying_amount")
            if missing_qualifiers:
                adjustment -= 180.0
                reasons.append(
                    "metric:missing_query_qualifier:" + ",".join(sorted(missing_qualifiers))
                )
            else:
                adjustment += 90.0
                reasons.append("metric:query_qualifier_match")

        required_context = tuple(
            normalize_phrase(value) for value in contract.required_context_phrases if value
        )
        missing_context = tuple(value for value in required_context if value not in context)
        if missing_context:
            adjustment -= 300.0
            reasons.append("metric:missing_required_context:" + ",".join(missing_context))
        elif required_context:
            adjustment += 160.0
            reasons.append("metric:required_context_match")

        if contract.statement_types:
            if fact.statement_type in contract.statement_types:
                adjustment += 45.0
                reasons.append("source:expected_statement")
            elif fact.statement_type in {"note", "personnel", "subsidiary"}:
                adjustment -= 35.0
                reasons.append("source:non_primary_statement")
            else:
                adjustment -= 8.0
                reasons.append("source:unclassified_statement")

        if metric in _CORE_METRIC_CODES and any(
            cue in context for cue in _NON_PRIMARY_TOTAL_CONTEXT
        ):
            adjustment -= 180.0
            reasons.append("source:analytical_note_collision")

        if metric in {"common_loan_loss_provision", "total_loan_loss_provision"}:
            loan_provision_context = any(
                cue in context
                for cue in (
                    "du phong rui ro cho vay",
                    "du phong cho vay",
                    "cho vay khach hang",
                )
            )
            if not loan_provision_context:
                adjustment -= 500.0
                reasons.append(
                    "source:semantic_context_conflict:non_loan_provision_context"
                )

        if metric.startswith("source_") and any(
            cue in context for cue in _PRIMARY_STATEMENT_CONTEXT
        ):
            adjustment += 90.0
            reasons.append("source:primary_statement_context")

        if metric.startswith("reported_") and fact.statement_type in {
            "balance_sheet",
            "income_statement",
            "cash_flow",
        }:
            adjustment += 90.0
            reasons.append("source:reported_primary_statement")

        if metric == "tangible_fixed_assets" and "gia tri con lai" in self.question:
            if "gia tri con lai" in context:
                adjustment += 500.0
                reasons.append("source:explicit_fixed_asset_carrying_context")
            elif fact.metric_code == "221":
                adjustment += 20.0
                reasons.append("source:implied_fixed_asset_carrying_context")
            if "trong do" in context and "trong do" not in self.question:
                adjustment -= 500.0
                reasons.append(
                    "source:semantic_context_conflict:fixed_asset_disclosed_component"
                )

        if (
            metric.startswith(("source_", "reported_"))
            and "bo phan" not in self.question
            and any(cue in context for cue in _SEGMENT_REPORT_CONTEXT)
        ):
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:unrequested_segment")

        if (
            metric.startswith(("source_", "reported_"))
            and "khong kiem soat" in context
            and "khong kiem soat" not in self.question
        ):
            adjustment -= 500.0
            reasons.append(
                "source:semantic_context_conflict:unrequested_non_controlling_interest"
            )

        query_requests_movement = any(
            cue in self.question for cue in _MOVEMENT_CONTEXT_CUES
        )
        physical_has_movement = any(
            cue in context for cue in (*_MOVEMENT_CONTEXT_CUES, *_MOVEMENT_COLUMN_CUES)
        )
        physical_is_balance = _has_opening_context(context) or any(
            cue in context for cue in _CLOSING_COLUMN_CUES
        )
        if (
            metric.startswith(("source_", "reported_"))
            and query_requests_movement
            and physical_is_balance
            and not physical_has_movement
        ):
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:balance_for_movement")

        query_charge_first = _ordered_phrases(
            self.question, "trich lap", "hoan nhap"
        )
        if query_charge_first and metric.startswith(("source_", "reported_")):
            if _ordered_phrases(context, "trich lap", "hoan nhap") and "trong nam" in context:
                adjustment += 280.0
                reasons.append("source:movement_presentation_order_match")
            elif _ordered_phrases(context, "hoan nhap", "trich lap"):
                adjustment -= 100.0
                reasons.append("source:movement_presentation_order_mismatch")
        if (
            metric == "reported_afs_provision_charge"
            and query_charge_first
            and not (
                _ordered_phrases(context, "trich lap", "hoan nhap")
                and "trong nam" in context
            )
        ):
            adjustment -= 500.0
            reasons.append(
                "source:semantic_context_conflict:afs_charge_without_roll_forward"
            )

        requests_total = bool(_TOTAL_REQUEST_RE.search(self.question))
        physical_total = any(
            cue in context for cue in ("tong cong", "cong vnd", "tong vnd")
        )
        if metric.startswith(("source_", "reported_")) and requests_total:
            if physical_total:
                adjustment += 220.0
                reasons.append("source:requested_physical_total")
            else:
                adjustment -= 100.0
                reasons.append("source:missing_physical_total")

        column_tokens = _semantic_tokens(column)
        requests_fixed_asset_class = any(
            cue in self.question for cue in _FIXED_ASSET_CLASS_CUES
        )
        requests_fixed_asset_carrying_total = (
            metric == "tangible_fixed_assets"
            and "gia tri con lai" in self.question
            and "gia tri con lai" in context
            and not requests_fixed_asset_class
        )
        if requests_fixed_asset_carrying_total:
            if "tong" in column_tokens or "cong" in column_tokens:
                adjustment += 240.0
                reasons.append("source:fixed_asset_aggregate_column")
            else:
                adjustment -= 120.0
                reasons.append("source:fixed_asset_component_column")

        requests_component = any(
            cue in self.question for cue in ("du phong chung", "du phong cu the")
        )
        if not requests_component and (
            metric.startswith(("source_", "reported_")) or "provision" in metric
        ):
            if "tong" in column_tokens or "cong" in column_tokens:
                adjustment += 100.0
                reasons.append("source:aggregate_column")
            elif (
                "chung" in column_tokens
                or {"cu", "the"} <= column_tokens
                or "specific" in column_tokens
            ):
                adjustment -= 100.0
                reasons.append("source:component_column")

        if metric.startswith("source_") and leaf in _EXPENSE_BY_NATURE_LEAVES:
            if any(cue in context for cue in _EXPENSE_BY_NATURE_CONTEXT):
                adjustment += 220.0
                reasons.append("source:expense_by_nature_total_context")
            elif any(
                cue in context and cue not in self.question for cue in _FUNCTIONAL_EXPENSE_CONTEXT
            ):
                adjustment -= 500.0
                reasons.append("source:semantic_context_conflict:functional_expense_component")

        if (
            metric.startswith("source_")
            and leaf == "lai vay"
            and not self.explicit_opening
            and not self.explicit_closing
        ):
            if "chi phi phai tra" in context:
                adjustment -= 500.0
                reasons.append("source:semantic_context_conflict:payable_balance_for_flow")
            elif "chi phi hoat dong tai chinh" in context:
                adjustment += 180.0
                reasons.append("source:finance_expense_flow_context")

        if (
            metric.startswith("source_")
            and leaf == "chung khoan no"
            and not any(cue in self.question for cue in _SECURITY_PORTFOLIO_CONTEXT)
            and any(cue in context for cue in _SECURITY_PORTFOLIO_CONTEXT)
        ):
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:portfolio_component_for_total")

        if metric.startswith("source_") and self.explicit_opening:
            physical_opening_years = frozenset(_OPENING_DATE_RE.findall(context))
            if physical_opening_years and not (physical_opening_years & self.requested_years):
                adjustment -= 500.0
                reasons.append("period:physical_opening_boundary_mismatch")
            if not physical_opening_years and not _has_opening_context(context):
                adjustment -= 500.0
                reasons.append("period:opening_without_physical_evidence")
        if (
            metric.startswith("source_")
            and self.explicit_closing
            and fact.metric_code is None
            and (
                contract.period_semantics is PeriodSemantics.POINT_IN_TIME
                or (fact.period_role or "") in {"opening", "closing", "prior"}
                or "so du" in context
            )
            and not any(cue in context for cue in _CLOSING_COLUMN_CUES)
            and not any(year in context for year in self.requested_years)
        ):
            adjustment -= 500.0
            reasons.append("period:closing_without_physical_evidence")

        if (
            metric.startswith("source_")
            and "khau hao" in self.question
            and any("khau hao trong nam" in alias for alias in aliases)
            and not any(cue in context for cue in _ASSET_ROLL_FORWARD_CONTEXT)
        ):
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:asset_roll_forward_required")
        if (
            metric.startswith("source_")
            and any("tien gui tai ngan hang nha nuoc" in alias for alias in aliases)
            and any(cue in context for cue in _UNRELATED_BANKING_BALANCE_CONTEXT)
        ):
            adjustment -= 500.0
            reasons.append("source:semantic_context_conflict:banking_balance_in_unrelated_note")

        period_semantics = contract.period_semantics
        role_adjustment, role_reason = self._period_role_adjustment(
            fact.period_role or "", column, context, period_semantics
        )
        adjustment += role_adjustment
        if role_reason:
            reasons.append(role_reason)

        if fact.period_year is not None and fact.document_year is not None:
            if fact.document_year == fact.period_year:
                adjustment += 35.0
                reasons.append("period:current_document")
            elif fact.document_year == fact.period_year + 1 and (fact.period_role or "") in {
                "prior",
                "opening",
            }:
                adjustment += 8.0
                reasons.append("period:comparative_document")
            else:
                adjustment -= 20.0
                reasons.append("period:document_mismatch")

        if fact.is_restated == self.requests_restated:
            adjustment += 4.0
            reasons.append("period:restatement_match")
        elif fact.is_restated:
            adjustment -= 15.0
            reasons.append("period:unexpected_restatement")

        if self.requested_basis is not Basis.UNSPECIFIED:
            if fact.basis is self.requested_basis:
                adjustment += 35.0
                reasons.append("basis:explicit_match")
            else:
                adjustment -= 100.0
                reasons.append("basis:explicit_mismatch")
        elif (
            contract.preferred_basis is not Basis.UNSPECIFIED
            and fact.basis is contract.preferred_basis
        ):
            adjustment += 10.0
            reasons.append("basis:preferred_match")

        if fact.collision_class is None:
            adjustment += 4.0
            reasons.append("quality:no_collision")
        else:
            adjustment -= 8.0
            reasons.append(f"quality:collision:{fact.collision_class}")
        if fact.source_confidence is not None:
            adjustment += 12.0 * (fact.source_confidence - 0.5)
            reasons.append(f"quality:confidence:{fact.source_confidence:.2f}")

        if not math.isfinite(adjustment):  # defensive domain invariant
            raise ValueError("logical fact adjustment must be finite")
        return replace(
            fact,
            score=fact.score + adjustment,
            score_reasons=tuple(reasons),
        )

    def _period_role_adjustment(
        self,
        role: str,
        column: str,
        context: str,
        semantics: PeriodSemantics,
    ) -> tuple[float, str | None]:
        movement_column = any(cue in column for cue in _MOVEMENT_COLUMN_CUES)
        movement_context = any(cue in context for cue in _MOVEMENT_CONTEXT_CUES)
        if self.explicit_closing:
            if _has_opening_context(context):
                return -240.0, "period:opening_fact_for_closing"
            if movement_column or movement_context:
                return -220.0, "period:movement_column_for_closing"
            if role == "closing" or any(cue in column for cue in _CLOSING_COLUMN_CUES):
                return 80.0, "period:closing_match"
            if role == "current":
                return 15.0, "period:current_closing_fallback"
            return -55.0, "period:closing_mismatch"
        if self.explicit_opening:
            if any(cue in context for cue in _CLOSING_COLUMN_CUES):
                return -240.0, "period:closing_fact_for_opening"
            if movement_column:
                return -220.0, "period:movement_column_for_opening"
            if role == "opening" or _has_opening_context(column):
                return 80.0, "period:opening_match"
            if role == "prior":
                return 20.0, "period:prior_opening_fallback"
            return -55.0, "period:opening_mismatch"
        if semantics is PeriodSemantics.POINT_IN_TIME:
            if role == "closing":
                return 50.0, "period:point_in_time_closing"
            if role == "current":
                return 12.0, "period:point_in_time_current"
            if movement_column:
                return -100.0, "period:movement_column_for_balance"
        elif semantics is PeriodSemantics.FLOW:
            if role == "current":
                return 50.0, "period:flow_current"
            if role == "prior":
                return 15.0, "period:flow_prior"
            if role in {"opening", "closing"}:
                return -20.0, "period:flow_role_mismatch"
        return 0.0, None

    @staticmethod
    def _corroboration(
        selected: GroundedFact,
        candidates: Sequence[GroundedFact],
    ) -> int:
        try:
            selected_value = selected.canonical_value()
        except ValueError:
            return 1
        sources = {
            (fact.document_id, fact.table_uid)
            for fact in candidates
            if _same_canonical_value(fact, selected_value)
        }
        return max(1, len(sources))

    def _diversify(
        self, facts: Sequence[GroundedFact], limit: int
    ) -> tuple[GroundedFact, ...]:
        if len(facts) <= limit:
            return tuple(facts)

        # A global score cut silently starves one low-prior entity/period of a
        # secondary operand in complex formulas.  Preserve every fact bound to
        # a governed query contract first; lexical fallback facts may use only
        # the remaining capacity.
        governed = [
            fact for fact in facts if (fact.retrieval_metric or "") in self.contracts
        ]
        if self.requested_basis is Basis.UNSPECIFIED:
            coverage: dict[tuple[str, Basis], set[tuple[str, int | None, str]]] = (
                defaultdict(set)
            )
            scores: dict[tuple[str, Basis], float] = defaultdict(float)
            for fact in governed:
                if not fact.entity or fact.basis is Basis.UNSPECIFIED:
                    continue
                key = (fact.entity, fact.basis)
                coverage[key].add(
                    (
                        fact.retrieval_metric or "",
                        fact.period_year,
                        _logical_component_key(fact, fact.retrieval_metric or ""),
                    )
                )
                scores[key] += fact.score
            chosen_basis: dict[str, Basis] = {}
            for entity in {key[0] for key in coverage}:
                choices = [key for key in coverage if key[0] == entity]
                chosen_basis[entity] = max(
                    choices,
                    key=lambda key: (
                        len(coverage[key]),
                        key[1] is Basis.CONSOLIDATED,
                        scores[key],
                        key[1].value,
                    ),
                )[1]
            governed = [
                fact
                for fact in governed
                if fact.entity not in chosen_basis
                or fact.basis is chosen_basis[fact.entity]
            ]
        fallback = [
            fact for fact in facts if (fact.retrieval_metric or "") not in self.contracts
        ]
        if len(governed) <= limit:
            retained = [*governed, *fallback[: limit - len(governed)]]
            retained.sort(key=lambda item: (-item.score, item.observation_uid))
            return tuple(retained)

        # Governed facts form a metric x entity x period coverage matrix.  A
        # scope-only quota still lets the highest-scoring metric consume every
        # slot in every scope, which makes otherwise valid formulas fail later
        # with missing operands.  Allocate the constrained budget using
        # max-min fairness across both axes, then use score only as the
        # deterministic tie-breaker.  Source-component facts remain distinct
        # candidates because each component can be a required operand.
        remaining = list(governed)
        metric_counts: dict[str, int] = defaultdict(int)
        scope_counts: dict[tuple[str, int | None], int] = defaultdict(int)
        selected: list[GroundedFact] = []
        while remaining and len(selected) < limit:
            minimum_metric_count = min(
                metric_counts[fact.retrieval_metric or ""] for fact in remaining
            )
            metric_candidates = [
                fact
                for fact in remaining
                if metric_counts[fact.retrieval_metric or ""] == minimum_metric_count
            ]
            minimum_scope_count = min(
                scope_counts[(fact.entity, fact.period_year)]
                for fact in metric_candidates
            )
            scope_candidates = [
                fact
                for fact in metric_candidates
                if scope_counts[(fact.entity, fact.period_year)] == minimum_scope_count
            ]
            chosen = min(
                scope_candidates,
                key=lambda fact: (-fact.score, fact.observation_uid),
            )
            selected.append(chosen)
            metric_counts[chosen.retrieval_metric or ""] += 1
            scope_counts[(chosen.entity, chosen.period_year)] += 1
            remaining.remove(chosen)
        selected.sort(key=lambda item: (-item.score, item.observation_uid))
        return tuple(selected)


def _prefix(value: str, prefix: str) -> bool:
    return value == prefix or value.startswith(prefix + " ")


def _same_canonical_value(fact: GroundedFact, expected: object) -> bool:
    try:
        return fact.canonical_value() == expected
    except ValueError:
        return False


def _logical_component_key(fact: GroundedFact, metric: str) -> str:
    if not metric.startswith("source_"):
        return ""
    leaf = normalize_phrase(fact.row_path.rsplit("›", 1)[-1])
    if "du phong chung" in leaf:
        return "provision_common"
    if "du phong cu the" in leaf:
        return "provision_specific"
    return ""


def contracts_from_query_concepts(
    concepts: Sequence[object],
) -> tuple[LogicalMetricContract, ...]:
    """Project query-layer concepts without coupling resolution to infrastructure."""

    output: list[LogicalMetricContract] = []
    for concept in concepts:
        raw = _concept_mapping(concept)
        metric_id = str(raw.get("metric_id") or "")
        if not metric_id:
            continue
        try:
            semantics = PeriodSemantics(
                str(raw.get("period_semantics") or PeriodSemantics.UNKNOWN.value)
            )
        except ValueError:
            semantics = PeriodSemantics.UNKNOWN
        try:
            basis = Basis(str(raw.get("preferred_basis") or Basis.UNSPECIFIED.value))
        except ValueError:
            basis = Basis.UNSPECIFIED
        output.append(
            LogicalMetricContract(
                metric_id=metric_id,
                aliases=_strings(raw.get("aliases")),
                statement_types=_strings(raw.get("statement_types")),
                metric_codes=_strings(raw.get("metric_codes")),
                period_semantics=semantics,
                preferred_basis=basis,
                forbidden_prefixes=_strings(raw.get("forbidden_prefixes")),
                forbidden_contains=_strings(raw.get("forbidden_contains")),
                query_surfaces=_strings(raw.get("query_surfaces")),
                required_context_phrases=_strings(raw.get("required_context_phrases")),
            )
        )
    return tuple(output)


_HARD_CONFLICT_REASON_PREFIXES = (
    "metric:forbidden_",
    "metric:missing_query_qualifier",
    "metric:missing_required_context",
    "metric:missing_source_alias_tokens",
    "source:analytical_note_collision",
    "source:semantic_context_conflict",
    "period:opening_fact_for_closing",
    "period:closing_fact_for_opening",
    "period:movement_column_",
    "period:physical_opening_boundary_mismatch",
    "period:opening_without_physical_evidence",
    "period:closing_without_physical_evidence",
    "basis:explicit_mismatch",
)


def has_hard_logical_fact_conflict(fact: GroundedFact) -> bool:
    """Return whether source resolution recorded a non-overridable conflict."""

    if fact.collision_class is not None:
        reasons = set(fact.score_reasons)
        governed_recoverable_collision = (
            fact.collision_class in {"missing_label_or_split", "missing_dimension"}
            and fact.source_confidence is not None
            and fact.source_confidence >= 0.85
            and "metric:governed_code" in reasons
            and bool({"metric:exact_row", "metric:prefix_row"} & reasons)
        )
        structurally_recovered_parent = (
            fact.collision_class == "missing_row_parent"
            and fact.source_confidence is not None
            and fact.source_confidence >= 0.65
            and "source:movement_presentation_order_match" in reasons
        )
        if not (governed_recoverable_collision or structurally_recovered_parent):
            return True
    if fact.source_confidence is not None and fact.source_confidence < 0.6:
        return True
    return any(reason.startswith(_HARD_CONFLICT_REASON_PREFIXES) for reason in fact.score_reasons)


def is_high_trust_logical_fact(fact: GroundedFact) -> bool:
    """Return whether a resolved fact is safe to replace an executable seed.

    Recovery and replacement have different risk.  This gate is deliberately
    stricter than retrieval: it requires structural identity, source quality
    and either a decisive conflict margin or independent corroboration.
    """

    if not fact.retrieval_metric or has_hard_logical_fact_conflict(fact):
        return False
    reasons = set(fact.score_reasons)
    governed_code = "metric:governed_code" in reasons
    exact_row = "metric:exact_row" in reasons
    margin = fact.resolution_margin
    corroborated = fact.corroboration_count >= 2
    if governed_code:
        if (
            exact_row
            and fact.source_confidence is not None
            and fact.source_confidence >= 0.85
        ):
            return True
        return corroborated or margin is None or margin >= 20.0
    if fact.retrieval_metric in _CORE_METRIC_CODES and exact_row:
        return margin is None or margin >= 30.0
    query_qualified = "metric:query_qualifier_match" in reasons
    if fact.retrieval_metric.startswith("reported_") and (exact_row or query_qualified):
        return corroborated and margin is not None and margin >= 50.0
    return False


def _concept_mapping(concept: object) -> Mapping[str, object]:
    if isinstance(concept, Mapping):
        return concept
    return {
        "metric_id": getattr(concept, "metric_id", ""),
        "aliases": getattr(concept, "aliases", ()),
        "statement_types": getattr(concept, "statement_types", ()),
        "metric_codes": getattr(concept, "metric_codes", ()),
        "period_semantics": getattr(concept, "period_semantics", PeriodSemantics.UNKNOWN),
        "preferred_basis": getattr(concept, "preferred_basis", Basis.UNSPECIFIED),
        "forbidden_prefixes": getattr(concept, "forbidden_prefixes", ()),
        "forbidden_contains": getattr(concept, "forbidden_contains", ()),
        "query_surfaces": getattr(concept, "query_surfaces", ()),
        "required_context_phrases": getattr(concept, "required_context_phrases", ()),
    }


def _row_declares_metric_code(
    row_path: str,
    expected_codes: frozenset[str],
) -> bool:
    """Recognize statement codes embedded in formulas when A6 metadata is null."""

    return any(
        re.search(rf"(?<!\d){re.escape(code)}(?!\d)", row_path) is not None
        for code in expected_codes
    )


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _surface_qualifiers(surfaces: Sequence[str], aliases: Sequence[str]) -> set[str]:
    alias_tokens = {token for alias in aliases for token in alias.split()}
    local_surfaces: list[str] = []
    for surface in surfaces:
        # Query surfaces may still contain both sides of a coordinated or
        # relational expression.  Qualifiers from the other operand must not
        # become requirements on this metric's physical source.
        clauses = tuple(
            value.strip()
            for value in re.split(r"\b(?:va|tren|so voi|chia cho)\b", surface)
            if value.strip()
        )
        matching_clauses = tuple(
            clause
            for clause in clauses
            if any(
                set(alias.split()) <= _semantic_tokens(clause)
                for alias in aliases
                if alias
            )
        )
        local_surfaces.extend(matching_clauses or (surface,))
    return {
        token
        for surface in local_surfaces
        for token in _semantic_tokens(surface)
        if (
            token not in alias_tokens
            and token not in _GENERIC_SURFACE_TOKENS
            and token in _PHYSICAL_SURFACE_QUALIFIER_TOKENS
            and not token.isdigit()
        )
    }


def _semantic_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_phrase(value)))


def _metric_identity_tokens(value: str) -> set[str]:
    tokens = _semantic_tokens(value)
    if {"du", "phong"} <= tokens and (
        {"giam", "gia"} <= tokens
        or {"rui", "ro"} <= tokens
        or "chung" in tokens
        or "cu" in tokens
        and "the" in tokens
    ):
        tokens -= {"giam", "gia", "rui", "ro"}
        tokens.add("impairment")
    return tokens


def _ordered_phrases(value: str, first: str, second: str) -> bool:
    first_index = value.find(first)
    second_index = value.find(second)
    return first_index >= 0 and second_index > first_index


def _has_opening_context(value: str) -> bool:
    """Match opening labels without treating ``31/12`` as ``1/1``."""

    return bool(_OPENING_DATE_RE.search(value)) or any(
        cue in value for cue in _OPENING_COLUMN_CUES
    )
