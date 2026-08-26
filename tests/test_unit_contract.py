"""Unit Contract tests: x1, x1e3, x1e6, percent, ratio, count, zero, null,
dimension mismatch, unknown scale. Every abstention path is asserted."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402

from text2pandas.pipelines.answering.units import (  # noqa: E402
    COUNT, MONEY, PERCENT, RATIO, SHARES, UNKNOWN,
    ConversionStatus, Quantity, Reason, Unit,
    compatible, conversion_factor, convert, query_factor,
)


# --------------------------------------------------------------- money scales
@pytest.mark.parametrize("src_exp,dst_exp,factor", [
    (0, 0, 1.0),
    (6, 6, 1.0),
    (6, 0, 1e6),
    (0, 6, 1e-6),
    (3, 0, 1e3),
    (0, 3, 1e-3),
    (9, 6, 1e3),
    (6, 9, 1e-3),
    (12, 9, 1e3),
])
def test_money_scale_factors(src_exp, dst_exp, factor):
    r = conversion_factor(Unit(MONEY, src_exp), Unit(MONEY, dst_exp))
    assert r.ok
    assert r.factor == pytest.approx(factor)


def test_money_missing_source_scale_abstains():
    r = conversion_factor(Unit(MONEY, None), Unit(MONEY, 6))
    assert not r.ok and r.reason == Reason.MISSING_SOURCE_SCALE


def test_money_missing_target_scale_abstains():
    r = conversion_factor(Unit(MONEY, 6), Unit(MONEY, None))
    assert not r.ok and r.reason == Reason.MISSING_TARGET_SCALE


def test_currency_mismatch_abstains():
    r = conversion_factor(Unit(MONEY, 0, "VND"), Unit(MONEY, 0, "USD"))
    assert not r.ok and r.reason == Reason.CURRENCY_MISMATCH


# --------------------------------------------- non-scaled/scaled dimensions
@pytest.mark.parametrize("dim", [PERCENT, RATIO, COUNT])
def test_identity_dimensions(dim):
    r = conversion_factor(Unit(dim), Unit(dim))
    assert r.ok and r.factor == 1.0


def test_share_quantities_require_and_convert_declared_scale():
    converted = conversion_factor(Unit(SHARES, 0), Unit(SHARES, 6))
    missing = conversion_factor(Unit(SHARES), Unit(SHARES, 6))

    assert converted.ok and converted.factor == pytest.approx(1e-6)
    assert missing.reason == Reason.MISSING_SOURCE_SCALE


def test_percent_ratio_is_the_only_declared_cross_pair():
    assert conversion_factor(Unit(RATIO), Unit(PERCENT)).factor == 100.0
    assert conversion_factor(Unit(PERCENT), Unit(RATIO)).factor == 0.01


@pytest.mark.parametrize("a,b", [
    (MONEY, PERCENT), (MONEY, COUNT), (MONEY, SHARES), (MONEY, RATIO),
    (COUNT, SHARES), (SHARES, PERCENT), (COUNT, PERCENT),
])
def test_dimension_mismatch_abstains(a, b):
    r = conversion_factor(Unit(a, 0 if a == MONEY else None),
                          Unit(b, 0 if b == MONEY else None))
    assert not r.ok and r.reason == Reason.DIMENSION_MISMATCH
    assert not compatible(Unit(a, 0 if a == MONEY else None),
                          Unit(b, 0 if b == MONEY else None))


@pytest.mark.parametrize("src,dst,reason", [
    (Unit(UNKNOWN), Unit(MONEY, 0), Reason.UNKNOWN_SOURCE_DIMENSION),
    (Unit(MONEY, 0), Unit(UNKNOWN), Reason.UNKNOWN_TARGET_DIMENSION),
])
def test_unknown_dimension_abstains(src, dst, reason):
    r = conversion_factor(src, dst)
    assert not r.ok and r.reason == reason


# ------------------------------------------------------------------- convert
def test_convert_value():
    q = Quantity(1_855_837.0, Unit(MONEY, 6))
    r = convert(q, Unit(MONEY, 9))
    assert r.ok
    assert r.quantity.value == pytest.approx(1855.837)
    assert r.quantity.unit == Unit(MONEY, 9)


def test_convert_zero_is_fine():
    r = convert(Quantity(0.0, Unit(MONEY, 6)), Unit(MONEY, 0))
    assert r.ok and r.quantity.value == 0.0


def test_convert_null_abstains():
    r = convert(Quantity(None, Unit(MONEY, 6)), Unit(MONEY, 0))
    assert not r.ok and r.reason == Reason.NON_FINITE_VALUE


def test_convert_nan_abstains():
    r = convert(Quantity(float("nan"), Unit(MONEY, 6)), Unit(MONEY, 0))
    assert not r.ok and r.reason == Reason.NON_FINITE_VALUE


def test_convert_inf_abstains():
    r = convert(Quantity(float("inf"), Unit(MONEY, 6)), Unit(MONEY, 0))
    assert not r.ok and r.reason == Reason.NON_FINITE_VALUE


# --------------------------------------------------------------- query factor
@pytest.mark.parametrize("col_exp,q_exp,storage_exp,expected", [
    # header "Triệu đồng", value stored un-normalised, question in millions
    # -> factor 1.0. This is the family the /1e6 patch was written for.
    (6, 6, 0, 1.0),
    # same header, value already normalised to VND by ingest -> /1e6 is right
    (6, 6, 6, 1e-6),
    # header VND, question in billions, no ingest scaling -> /1e9
    (0, 9, 0, 1e-9),
    # header "Triệu đồng", question in billions, un-normalised -> /1e3
    (6, 9, 0, 1e-3),
    # header nghìn đồng, question in đồng, un-normalised -> x1e3
    (3, 0, 0, 1e3),
])
def test_query_factor_matrix(col_exp, q_exp, storage_exp, expected):
    r = query_factor(Unit(MONEY, col_exp), Unit(MONEY, q_exp), storage_exp)
    assert r.ok
    assert r.factor == pytest.approx(expected)


def test_query_factor_unknown_storage_abstains():
    """The exact ambiguity behind the spurious /1e6 family: refuse to guess."""
    r = query_factor(Unit(MONEY, 6), Unit(MONEY, 6), None)
    assert not r.ok and r.reason == Reason.MISSING_STORAGE_SCALE


def test_query_factor_dimension_mismatch_abstains():
    r = query_factor(Unit(MONEY, 6), Unit(PERCENT), 0)
    assert not r.ok and r.reason == Reason.DIMENSION_MISMATCH


def _executable_source(path: Path) -> str:
    """Source with comments and docstrings stripped, so structural guards test
    the *code* rather than the prose that explains the code."""
    import ast
    import io
    import tokenize

    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.ENCODING):
                continue
            out.append(tok)
    src = tokenize.untokenize(out).decode("utf-8", "replace") if isinstance(
        tokenize.untokenize(out), bytes) else tokenize.untokenize(out)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            ds = ast.get_docstring(node, clean=False)
            if ds:
                docstrings.add(ds)
    for ds in docstrings:
        src = src.replace(ds, "")
    return src


PKG = ROOT / "src" / "text2pandas" / "pipelines" / "answering"


# Guard scope, corrected after review 171 §7.3: banning every "1e6" in the
# package is too broad. An ontology constant (MILLION = 10**6) is legitimate;
# a conversion baked into the emitter is not. So the guards target the emitter
# and the *origin* of factors, not the literal.
EMITTERS = ("render.py", "pipeline.py", "binding.py", "router.py")


def test_emitter_contains_no_scale_literal():
    """No conversion constant may be written into the query builder."""
    offenders = []
    for name in EMITTERS:
        p = PKG / name
        if not p.exists():
            continue
        code = _executable_source(p)
        for bad in ("1000000", "1_000_000", "1e6", "1E6", "1e9", "1e3"):
            if bad in code:
                offenders.append((name, bad))
    assert offenders == [], f"scale literal in emitter: {offenders}"


def test_emitter_never_computes_a_power_of_ten_itself():
    """Every factor the renderer applies must come back from the contract."""
    code = _executable_source(PKG / "render.py")
    assert "10 **" not in code and "10**" not in code, \
        "render.py must take factors from UnitContract, not derive them"
    assert "query_factor" in code and "conversion_factor" in code, \
        "render.py must obtain its factors from the contract API"


def test_ontology_scale_constants_are_allowed_in_the_contract_module():
    """The contract itself may define what 'million' means -- that is ontology,
    not a patch. This test documents the distinction so the guard above is not
    later widened back into a blanket ban."""
    code = _executable_source(PKG / "units.py")
    assert "10.0 **" in code or "10 **" in code, \
        "the contract is the one place allowed to turn an exponent into a factor"


def test_no_qid_whitelist_in_the_package():
    """Structural guard against test-set-specific patches."""
    known_u1_7 = ("42", "52", "238", "284", "317", "321", "322")
    for p in sorted(PKG.glob("*.py")):
        code = _executable_source(p)
        assert "qid in {" not in code and "qid in (" not in code and "qid in [" not in code, p.name
        joined = "".join(ch for ch in code if ch.isdigit() or ch == ",")
        assert ",".join(known_u1_7) not in joined, p.name


# ------------------------------------------------- percent vs percentage point
# 23 questions in the corpus ask explicitly for "điểm phần trăm". A percentage
# and a difference of percentages are different quantities; conflating them is
# the same class of error as conflating triệu with tỷ.
from text2pandas.pipelines.answering.units import PERCENT_POINT  # noqa: E402
from text2pandas.pipelines.answering.ir import (  # noqa: E402
    SUBTRACT as _SUB, DIVIDE as _DIV, GROWTH as _GROW, AVG as _AVG,
    result_dimension as _rd,
)


@pytest.mark.parametrize("other", [PERCENT, RATIO, MONEY, COUNT, SHARES])
def test_percent_point_never_auto_converts(other):
    src = Unit(PERCENT_POINT)
    dst = Unit(other, 0 if other == MONEY else None)
    assert not conversion_factor(src, dst).ok
    assert not conversion_factor(dst, src).ok


def test_percent_point_identity_is_allowed():
    r = conversion_factor(Unit(PERCENT_POINT), Unit(PERCENT_POINT))
    assert r.ok and r.factor == 1.0


def test_difference_of_two_percentages_is_percentage_points():
    """REGRESSION: SUBTRACT(PERCENT, PERCENT) must not stay PERCENT."""
    assert _rd(_SUB, [PERCENT, PERCENT]) == PERCENT_POINT


def test_difference_of_two_money_amounts_stays_money():
    assert _rd(_SUB, [MONEY, MONEY]) == MONEY


def test_ratio_and_growth_still_yield_ratio():
    assert _rd(_DIV, [MONEY, MONEY]) == RATIO
    assert _rd(_GROW, [MONEY, MONEY]) == RATIO


def test_average_of_percentages_is_still_percent():
    """Averaging percentages does not create percentage points."""
    assert _rd(_AVG, [PERCENT, PERCENT]) == PERCENT


def test_basis_point_is_declared_out_of_scope():
    """No corpus question asks for bps; the contract must not invent a unit
    it cannot validate. Adding BASIS_POINT requires corpus evidence first."""
    from text2pandas.pipelines.answering.units import DIMENSIONS
    assert "BASIS_POINT" not in DIMENSIONS
