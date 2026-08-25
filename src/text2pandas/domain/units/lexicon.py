"""Deterministic unit lexicon: parse raw numeric strings and unit tokens.

Pure functions, no I/O, no QID knowledge. Covered by tests in
``tests/test_unitlex.py``.

Design rules learned the hard way (see 170 measurement closure):
  * every detector has BOTH positive and negative tests;
  * word boundaries are mandatory -- "cong TY me" must not match "ty dong",
    "TMCP" must not match "CP" (co phieu);
  * a question's *requested output unit* is extracted from the interrogative
    frame ("... la bao nhieu X ?"), not from anywhere in the sentence;
  * anything not confidently recognised returns UNKNOWN, never a guess.
"""
from __future__ import annotations
import math
import re
import unicodedata

# ---------------------------------------------------------------- dimensions
MONEY = "MONEY"
PERCENT = "PERCENT"
#: a DIFFERENCE of two percentages ("điểm phần trăm"). Must be recognised
#: BEFORE plain percent, otherwise "tăng 2,5 điểm phần trăm" is read as
#: "tăng 2,5%" -- a different quantity.
PERCENT_POINT = "PERCENT_POINT"
RATIO = "RATIO"
COUNT = "COUNT"
SHARES = "SHARES"
UNKNOWN = "UNKNOWN"

DIMENSIONS = (MONEY, PERCENT, PERCENT_POINT, RATIO, COUNT, SHARES, UNKNOWN)


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "").lower()


# ------------------------------------------------------------- raw numbers
_VN_NUM = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d+)?$")
_EN_NUM = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN_INT = re.compile(r"^-?\d+$")
_PLAIN_DEC = re.compile(r"^-?\d+[.,]\d+$")


def parse_raw_number(s):
    """Parse a raw cell string into a float. Returns ``(value, status)``.

    status in {OK, EMPTY, NOT_A_NUMBER}. Handles VN grouping (1.234.567,89),
    EN grouping (1,234,567.89), plain integers/decimals, parentheses-negative
    and a trailing percent sign.
    """
    if s is None:
        return None, "EMPTY"
    t = str(s).strip()
    if t == "" or t in {"-", "--", "—", "N/A", "n/a", "nan", "None"}:
        return None, "EMPTY"
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1].strip()
    if t.startswith("-"):
        neg, t = True, t[1:].strip()
    if t.endswith("%"):
        t = t[:-1].strip()
    if t == "":
        return None, "EMPTY"
    if _VN_NUM.match(t):
        v = float(t.replace(".", "").replace(",", "."))
    elif _EN_NUM.match(t):
        v = float(t.replace(",", ""))
    elif _PLAIN_INT.match(t):
        v = float(t)
    elif _PLAIN_DEC.match(t):
        v = float(t.replace(",", "."))
    else:
        return None, "NOT_A_NUMBER"
    return (-v if neg else v), "OK"


# --------------------------------------------------------------- unit tokens
# Boundary policy. Real CSV headers are glued without separators
# ("Năm nayTriệu đồng", "2018VND › ..."), so we must NOT require a left word
# boundary. Safety therefore comes from the tokens themselves:
#   * the 10^9 scale is only ever spelled "tỷ" (with diacritic) or "ty đồng" --
#     never bare ascii "ty", which would swallow "công ty";
#   * "cp" is not accepted as an abbreviation of "cổ phiếu" -- it would swallow
#     "TMCP" (Thương mại Cổ phần, a bank-name fragment, not a unit).
_RB = r"(?![a-zà-ỹ0-9])"           # right boundary, diacritics included
_LETTER = r"[a-zà-ỹ]"

_MONEY_SCALE = [
    # most specific first
    (re.compile(r"ngh[ìi]n\s*t[ỷy]" + _RB), 12),
    (re.compile(r"t[ỷy]\s*(?:đồng|vnd)" + _RB), 9),
    (re.compile(r"tri[ệe]u\s*(?:đồng|vnd)" + _RB), 6),
    (re.compile(r"ngh[ìi]n\s*(?:đồng|vnd)" + _RB), 3),
    (re.compile(r"tri[ệe]u" + _RB), 6),
    (re.compile(r"ngh[ìi]n" + _RB), 3),
    # bare "đồng" only when it is not the adverb/verb "đồng thời|ý|bộ|nhất|loạt"
    (re.compile(r"(?:đồng|vnd)" + _RB + r"(?!\s*(?:thời|ý|bộ|nhất|loạt|thu[ậa]n))"), 0),
]
# "tỷ" alone: only the diacritic form, and not part of tỷ lệ/trọng/giá/suất
_TY_ALONE = re.compile(r"tỷ" + _RB + r"(?!\s*(?:l[ệe]|tr[ọo]ng|gi[áa]|su[ấa]t|ph[ầa]n))")

# "điểm phần trăm" / "điểm %" -- checked before _PERCENT, longest match wins
_PERCENT_POINT = re.compile(r"đi[ểe]m\s*(?:ph[ầa]n\s*tr[ăa]m" + _RB + r"|%)")
_PERCENT = re.compile(r"(%|phần\s*trăm" + _RB + r")")
_RATIO = re.compile(r"(?:l[ầa]n|h[ệe]\s*s[ốo]|t[ỷy]\s*l[ệe]|t[ỷy]\s*tr[ọo]ng|t[ỷy]\s*su[ấa]t)" + _RB)
_SHARES = re.compile(r"(?:c[ổo]\s*phi[ếe]u|shares?)" + _RB)
_COUNT = re.compile(r"(?:s[ốo]\s*l[ưu][ợo]ng|s[ốo]\s*ng[ưu][ờo]i|nh[âa]n\s*vi[êe]n)" + _RB)


def scan_unit(text: str):
    """Return ``(dimension, scale_exponent|None, matched_token|None)``.

    ``scale_exponent`` is only meaningful for MONEY (power of ten over VND).
    Precedence: PERCENT > MONEY > SHARES > RATIO > COUNT > UNKNOWN.

    MONEY outranks SHARES on purpose: a column headed
    "Cổ phiếu phổ thông tính theo mệnh giá Triệu đồng" carries *money*, the
    share wording is only the row subject.
    """
    t = _norm(text)
    if not t:
        return UNKNOWN, None, None
    m = _PERCENT_POINT.search(t)
    if m:
        return PERCENT_POINT, None, m.group(0)
    m = _PERCENT.search(t)
    if m:
        return PERCENT, None, m.group(0)
    for pat, exp in _MONEY_SCALE:
        m = pat.search(t)
        if m:
            return MONEY, exp, m.group(0)
    m = _TY_ALONE.search(t)
    if m:
        return MONEY, 9, m.group(0)
    m = _SHARES.search(t)
    if m:
        return SHARES, None, m.group(0)
    m = _RATIO.search(t)
    if m:
        return RATIO, None, m.group(0)
    m = _COUNT.search(t)
    if m:
        return COUNT, None, m.group(0)
    return UNKNOWN, None, None


# ------------------------------------------------- question requested output
# The requested unit lives in the interrogative frame, not anywhere in the
# sentence. Capturing a bounded tail after these anchors avoids matching the
# unit words that belong to the *subject* of the question.
_ASK_ANCHORS = [
    re.compile(r"(?:l[àa]|b[ằa]ng|đ[ạa]t|chi[ếe]m)?\s*bao\s*nhi[êe]u\b(?P<tail>[^?]{0,40})"),
    re.compile(r"\bt[íi]nh\s+(?:b[ằa]ng|theo)\b(?P<tail>[^?]{0,40})"),
    re.compile(r"\bđơn\s*v[ịi]\s*(?:t[íi]nh)?\s*[:l[àa]]?(?P<tail>[^?]{0,40})"),
]


def scan_question_unit(question: str):
    """Requested output ``(dimension, scale_exponent, token)`` of a question.

    Falls back to a whole-sentence scan restricted to PERCENT only, because a
    percent sign anywhere unambiguously marks a percent answer, while money
    words routinely appear inside the *subject* ("vốn điều lệ", "công ty").
    """
    t = _norm(question)
    if not t:
        return UNKNOWN, None, None
    for pat in _ASK_ANCHORS:
        m = pat.search(t)
        if not m:
            continue
        dim, exp, tok = scan_unit(m.group("tail"))
        if dim != UNKNOWN:
            return dim, exp, tok
    m = _PERCENT_POINT.search(t)
    if m:
        return PERCENT_POINT, None, m.group(0)
    m = _PERCENT.search(t)
    if m:
        return PERCENT, None, m.group(0)
    return UNKNOWN, None, None


# ------------------------------------------------------------ storage scale
def storage_ratio(value, value_raw):
    """``ratio = stored numeric / parsed raw text``. Returns (ratio, status).

    status in {OK, RAW_EMPTY, RAW_UNPARSEABLE, VALUE_UNPARSEABLE, ZERO_RAW}.
    """
    raw, st = parse_raw_number(value_raw)
    if st == "EMPTY":
        return None, "RAW_EMPTY"
    if st != "OK":
        return None, "RAW_UNPARSEABLE"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None, "VALUE_UNPARSEABLE"
    if raw == 0:
        return None, "ZERO_RAW"
    return v / raw, "OK"


def snap_power_of_ten(ratio, tol_rel: float = 1e-6):
    """Snap a positive ratio to ``10**k`` when within relative tolerance."""
    if ratio is None or ratio <= 0:
        return None
    k = round(math.log10(ratio))
    if abs(ratio - 10.0 ** k) <= tol_rel * max(1.0, abs(ratio)):
        return int(k)
    return None
