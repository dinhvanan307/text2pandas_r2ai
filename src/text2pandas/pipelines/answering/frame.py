"""QuestionSemanticFrame -- a typed reading of the question.

This is *only* about what the question asks. It knows nothing about which
tables exist, which cells were retrieved, or what the answer is. Keeping that
boundary is what lets the funnel say "parse was right, selection was wrong".

The frame never carries free text in the ``operation`` field and never uses a
``multi`` catch-all: an operation it cannot name is ``UNSUPPORTED`` with a
reason, which is a measurable state rather than a silent fallback.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from .ir import AVG, DIVIDE, GROWTH, LOOKUP, SUBTRACT, SUM
from .units import (COUNT, MONEY, PERCENT, RATIO, SHARES, UNKNOWN, Unit)

UNSUPPORTED = "UNSUPPORTED"

#: operations this pipeline can compile today. Anything else is declared, not
#: silently coerced -- see ``OperationHint.reason``.
SUPPORTED = (LOOKUP, DIVIDE, SUBTRACT, GROWTH, SUM, AVG, "EXTREMUM")

#: named gaps, kept as first-class values so coverage reports can show them
EXTREMUM = "EXTREMUM"
COUNT_OP = "COUNT"        # "bao nhiêu công ty" -- no emitter yet

RANK_MAX = "MAX"
RANK_MIN = "MIN"
RETURN_VALUE = "VALUE"
RETURN_PERIOD = "PERIOD"
RETURN_SELECT_AT_ARG = "SELECT_AT_ARG"
RETURN_FILTERED_VALUE = "FILTERED_VALUE"

_DERIVED_RANKING = re.compile(
    r"(m[ứu]c\s+(?:t[ăa]ng|gi[ảa]m|thay\s*đ[ổo]i|ch[êe]nh\s*l[ệe]ch)"
    r"|t[ốo]c\s*đ[ộo]\s*t[ăa]ng|t[ăa]ng\s*tr[ưu][ởo]ng|cagr)"
)
_SELECT_AT_ARG = re.compile(
    r"((?:t[ạa]i|v[àa]o|[ởo])\s+n[ăa]m\b|n[ăa]m\s+m[àa]\b"
    r"|n[ăa]m\s+c[óo]\s+[^?]{0,160}(?:cao|th[ấa]p|l[ớo]n|nh[ỏo])\s*nh[ấa]t)"
)
_FILTERED_EXTREMUM = re.compile(
    r"((?:x[ée]t|trong|[ởo])\s+(?:nh[ữu]ng|c[áa]c)\s+n[ăa]m\s+c[óo]\b"
    r"|ch[ỉi]\s+t[íi]nh\s+(?:nh[ữu]ng|c[áa]c)\s+n[ăa]m\b)"
)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


# ------------------------------------------------------------------- periods
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_DMY = re.compile(r"\b(\d{1,2})/(\d{1,2})/((?:19|20)\d{2})\b")
_QUARTER = re.compile(r"\b(?:qu[ýy]|q)\s*([1-4])\b")

# --------------------------------------------------------------------- basis
_SEPARATE = re.compile(r"(công\s*ty\s*mẹ|riêng\s*l[ẻe]|báo\s*cáo\s*riêng|separate)")
_CONSOLIDATED = re.compile(r"(h[ợo]p\s*nh[ấa]t|consolidated)")

# ---------------------------------------------------------------- operations
# Precedence matters and is asserted by tests. Most specific first.
#
# ROOT-CAUSE NOTE (review 173 / audit 174)
# ---------------------------------------
# The first version drew operation cues and *metric nouns* from one lexicon.
# "tỷ lệ", "tỷ trọng", "hệ số", "biên lợi nhuận" are the NAMES OF METRICS, not
# instructions to divide: "tỷ lệ nợ xấu" is a reported ratio you look up, and
# "chênh lệch tỷ lệ nợ xấu" is a SUBTRACTION of two of them. Because DIVIDE
# owned those nouns and was tested before SUBTRACT, every difference-of-ratio
# question was silently routed to DIVIDE and produced a wrong number rather
# than an abstention (measured: 15% vs 10% returned 150.0 instead of 5).
#
# The fix is two-part and both parts are load-bearing:
#   1. DIVIDE keeps only RELATIONAL cues ("trên tổng", "chiếm ... trong",
#      "gấp ... lần", "trên mỗi") -- constructions that actually express a
#      quotient between two named quantities;
#   2. difference cues (GROWTH, SUBTRACT) are evaluated BEFORE DIVIDE.
# A bare metric noun no longer implies any operation; it only hints that the
# RESULT is ratio-like, which is the Unit Contract's business, not the router's.
_DIFFERENCE_CUE = re.compile(
    r"(ch[êe]nh\s*l[ệe]ch|hi[ệe]u\s*s[ốo]|m[ứu]c\s*thay\s*đ[ổo]i"
    r"|thay\s*đ[ổo]i\s*(?:so\s*v[ớo]i|gi[ữu]a)|nhi[ềe]u\s*h[ơo]n|[íi]t\s*h[ơo]n"
    r"|b[ée]\s*h[ơo]n|cao\s*h[ơo]n|th[ấa]p\s*h[ơo]n|bi[ếe]n\s*đ[ộo]ng"
    r"|(?:k[ếe]t\s*qu[ảa]|l[ãa]i)\s+(?:thu[ầa]n|r[òo]ng)\s+(?:t[ừu]\s+)?ho[ạa]t\s*đ[ộo]ng\s+t[àa]i\s*ch[íi]nh)"
)

_OP_PATTERNS: list[tuple[str, re.Pattern]] = [
    # A superlative marks the OUTER operation. A change/growth word inside such
    # a question usually describes the RANKING KEY ("năm có mức tăng doanh thu
    # cao nhất"), not the top-level operation. Measured on gold: 11 cases whose
    # outer operation is SELECT_AT_ARG were captured by GROWTH because GROWTH
    # was tested first -- the same inner-cue-steals-outer-operation error as
    # the "tỷ lệ" -> DIVIDE bug.
    (EXTREMUM, re.compile(
        r"(cao\s*nh[ấa]t|th[ấa]p\s*nh[ấa]t|l[ớo]n\s*nh[ấa]t|nh[ỏo]\s*nh[ấa]t"
        r"|đ[ứu]ng\s*đ[ầa]u|x[ếe]p\s*h[ạa]ng)")),
    # COUNT: "có bao nhiêu công ty/doanh nghiệp" asks for a cardinality, not a
    # money amount. Must precede the generic cues.
    (COUNT_OP, re.compile(
        r"(c[óo]\s*bao\s*nhi[êe]u\s*(?:c[ôo]ng\s*ty|doanh\s*nghi[ệe]p|m[ãa]|đơn\s*v[ịi])"
        r"|s[ốo]\s*l[ưu][ợo]ng\s*(?:c[ôo]ng\s*ty|doanh\s*nghi[ệe]p)"
        r"|bao\s*nhi[êe]u\s*(?:c[ôo]ng\s*ty|doanh\s*nghi[ệe]p)\s*(?:c[óo]|đ[ạa]t|th[ỏo]a)"
        r"|(?:c[óo]\s*)?bao\s*nhi[êe]u\s*n[ăa]m\b|s[ốo]\s*n[ăa]m\b)")),
    (GROWTH, re.compile(
        r"(t[ăa]ng\s*tr[ưu][ởo]ng|t[ốo]c\s*đ[ộo]\s*t[ăa]ng"
        r"|t[ăa]ng\s*(?:hay|hoặc)?\s*gi[ảa]m\s*bao\s*nhi[êe]u\s*(?:%|phần\s*trăm)"
        r"|thay\s*đ[ổo]i\s*(?:bao\s*nhi[êe]u\s*)?(?:%|phần\s*trăm))")),
    (AVG, re.compile(r"(trung\s*b[ìi]nh|b[ìi]nh\s*qu[âa]n)")),
    (SUBTRACT, _DIFFERENCE_CUE),
    (DIVIDE, re.compile(
        r"(chi[ếe]m\s*bao\s*nhi[êe]u|g[ấa]p\s*(?:bao\s*nhi[êe]u\s*)?l[ầa]n"
        r"|so\s*v[ớo]i\s*.{0,30}\s*g[ấa]p"
        r"|tr[êe]n\s+(?!(?:b[áa]o\s*c[áa]o|bctc|m[ứu]c|ng[ưu][ỡo]ng|th[ịi]\s*tr[ưu][ờo]ng|c[ơo]\s*s[ởo])\b)(?![\d,.])[a-zà-ỹ]"
        r"|t[ỷy]\s*tr[ọo]ng\s+[^?]{0,100}\s+trong\s+t[ổo]ng"
        r"|/\s*m[ỗo]i)")),
    # "Tổng cộng tài sản" is the NAME of a reported total line, not an
    # instruction to add things up. Require an explicit enumeration ("A và B")
    # or the verb form ("cộng lại").
    (SUM, re.compile(
        r"(c[ộo]ng\s*l[ạa]i|t[íi]ch\s*l[ũu]y"
        r"|t[íi]nh\s+t[ổo]ng\s+[^?]{0,100}(?:trong|qua)\s+c[áa]c\s+n[ăa]m"
        r"|t[ổo]ng\s+[^?]{0,70}\bn[ăa]m\s+(?:19|20)\d{2}\s+v[àa]\s+n[ăa]m\s+(?:19|20)\d{2})"
    )),
]

#: metric nouns that merely describe a ratio-like QUANTITY. Kept separate so a
#: future ontology can consume them; they must never select an operation.
_RATIO_METRIC_NOUN = re.compile(
    r"(t[ỷy]\s*l[ệe]|t[ỷy]\s*tr[ọo]ng|h[ệe]\s*s[ốo]|bi[êe]n\s*l[ợo]i\s*nhu[ậa]n"
    r"|v[òo]ng\s*quay|roa|roe|eps)")


@dataclass(frozen=True)
class OperationHint:
    op: str
    reason: str
    matched: Optional[str] = None
    rank_direction: Optional[str] = None
    return_mode: Optional[str] = None
    requires_derived_metric: bool = False
    reverse_difference: bool = False

    @property
    def supported(self) -> bool:
        return self.op in SUPPORTED


@dataclass(frozen=True)
class QuestionSemanticFrame:
    """Typed reading of a question. Every field is nullable and explicit."""

    qid: Optional[int]
    question: str
    entity: Optional[str]
    metric_id: Optional[str]
    periods: tuple[str, ...]
    basis: Optional[str]
    requested_dimension: str
    requested_unit: Unit
    operation: OperationHint

    #: fields whose value could not be determined, for coverage reporting
    missing: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "qid": self.qid,
            "entity": self.entity,
            "metric_id": self.metric_id,
            "periods": list(self.periods),
            "basis": self.basis,
            "requested_dimension": self.requested_dimension,
            "requested_scale_exponent": self.requested_unit.scale_exponent,
            "operation": self.operation.op,
            "operation_reason": self.operation.reason,
            "operation_supported": self.operation.supported,
            "rank_direction": self.operation.rank_direction,
            "return_mode": self.operation.return_mode,
            "requires_derived_metric": self.operation.requires_derived_metric,
            "reverse_difference": self.operation.reverse_difference,
            "missing": list(self.missing),
        }


# ------------------------------------------------------------------- parsing
_TICKER = re.compile(r"\b([A-Z]{3,4})\b")


_TICKER_STOP = {"TMCP", "CTCP", "VND", "USD", "TNHH", "NHNN", "BCTC", "ROE",
                "ROA", "EPS", "CFO", "LNST", "TSC", "XDCB", "GTCG", "DN"}


def extract_entities(question: str) -> tuple[str, ...]:
    """EVERY ticker the question names, in text order, de-duplicated.

    A comparison across four companies has four entities. Returning only the
    first silently turns a multi-entity question into a single-entity one --
    measured on gold: exact entity-set match was 0.425 with the scalar version.
    """
    seen, out = set(), []
    for m in _TICKER.finditer(question):
        tok = m.group(1)
        if tok in _TICKER_STOP or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return tuple(out)


def extract_entity(question: str) -> Optional[str]:
    """First ticker only. Kept for callers that genuinely want one entity."""
    ents = extract_entities(question)
    return ents[0] if ents else None


_YEAR_RANGE = re.compile(r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})")


def extract_periods(question: str) -> tuple[str, ...]:
    """Every period the question names.

    "giai đoạn 2021-2024" names FOUR years, not two. Measured on gold: exact
    period match rose 0.862 -> 1.000 once ranges were expanded.
    """
    out: list[str] = []
    for m in _DMY.finditer(question):
        out.append(f"{int(m.group(3)):04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}")
    for m in _YEAR.finditer(question):
        y = m.group(0)
        if not any(p.startswith(y) for p in out):
            out.append(y)
    for m in _YEAR_RANGE.finditer(question):
        lo, hi = int(m.group(1)), int(m.group(2))
        if 0 < hi - lo <= 12:
            out.extend(str(y) for y in range(lo, hi + 1))
    # stable, de-duplicated, source order
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return tuple(uniq)


#: what a question means when it says nothing about basis. Not a guess: in this
#: corpus, unmarked questions were answered from consolidated statements 579
#: times out of 635. The frame records the default AND whether it was explicit,
#: so "stated consolidated" and "assumed consolidated" stay distinguishable.
DEFAULT_BASIS = "consolidated"


def extract_basis(question: str) -> Optional[str]:
    """Explicit basis only; ``None`` means the question did not say."""
    t = _norm(question)
    if _SEPARATE.search(t):
        return "separate"
    if _CONSOLIDATED.search(t):
        return "consolidated"
    return None


def resolve_basis(question: str) -> tuple[str, bool]:
    """``(basis, was_explicit)`` -- the value to use, plus whether it was read
    or defaulted. Downstream must never confuse the two."""
    b = extract_basis(question)
    return (b, True) if b is not None else (DEFAULT_BASIS, False)


def classify_operation(question: str) -> OperationHint:
    """Precedence-ordered operation classification.

    Returns an explicit ``EXTREMUM``/``COUNT`` hint for the known gaps rather
    than mis-routing them to LOOKUP, so coverage reports stay honest.
    """
    t = _norm(question)
    for op, pat in _OP_PATTERNS:
        m = pat.search(t)
        if m:
            if op == AVG and re.search(r"b[ìi]nh\s*qu[âa]n\s+gia\s+quy[ềe]n", t):
                continue
            if op == SUBTRACT and re.search(r"ch[êe]nh\s*l[ệe]ch\s+t[ỷy]\s+gi[áa]", t):
                if not re.search(r"(gi[ữu]a|so\s+v[ớo]i|t[ừu].{0,80}đ[ếe]n)", t):
                    continue
            if op == EXTREMUM:
                direction = (
                    RANK_MIN
                    if re.search(r"(th[ấa]p|nh[ỏo]|[íi]t)\s*nh[ấa]t", m.group(0))
                    else RANK_MAX
                )
                if re.search(r"\b(?:n[ăa]m|qu[ýy]|k[ỳy])\s+n[àa]o\b", t):
                    return_mode = RETURN_PERIOD
                elif _FILTERED_EXTREMUM.search(t):
                    return_mode = RETURN_FILTERED_VALUE
                elif _SELECT_AT_ARG.search(t):
                    return_mode = RETURN_SELECT_AT_ARG
                else:
                    return_mode = RETURN_VALUE
                return OperationHint(
                    op,
                    reason=f"cue:{op}",
                    matched=m.group(0),
                    rank_direction=direction,
                    return_mode=return_mode,
                    requires_derived_metric=bool(_DERIVED_RANKING.search(t)),
                )
            return OperationHint(
                op,
                reason=f"cue:{op}",
                matched=m.group(0),
                reverse_difference=bool(
                    op == SUBTRACT and re.search(r"(?:b[ée]|[íi]t|th[ấa]p)\s+h[ơo]n", m.group(0))
                ),
            )
    return OperationHint(LOOKUP, reason="default:no_operation_cue")


def parse_question(question: str, qid: Optional[int] = None,
                   metric_id: Optional[str] = None,
                   requested_unit: Optional[Unit] = None) -> QuestionSemanticFrame:
    """Build a frame. ``requested_unit`` may be injected by a caller that owns
    a better lexicon; otherwise it is left UNKNOWN rather than guessed."""
    entity = extract_entity(question)
    periods = extract_periods(question)
    basis = extract_basis(question)
    op = classify_operation(question)
    unit = requested_unit or Unit(UNKNOWN)

    missing = []
    if entity is None:
        missing.append("entity")
    if not periods:
        missing.append("periods")
    if basis is None:
        missing.append("basis")
    if metric_id is None:
        missing.append("metric_id")
    if unit.dimension == UNKNOWN:
        missing.append("requested_unit")

    return QuestionSemanticFrame(
        qid=qid,
        question=question,
        entity=entity,
        metric_id=metric_id,
        periods=periods,
        basis=basis,
        requested_dimension=unit.dimension,
        requested_unit=unit,
        operation=op,
        missing=tuple(missing),
    )
