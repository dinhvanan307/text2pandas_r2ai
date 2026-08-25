"""P1-04 · RC-04 chỉ được có MỘT con số, và nó phải có nguồn.

Số 26.515 từng nằm trong `RC_STATUS.json`, runbook 37, doc 40 và doc 41, trong
khi nguồn canonical `hard_risk_inventory.json` ghi `gained_total = 26.517`
(= 25.090 + 1.427). Chọn số bằng cảm tính là cách một sai lệch sống sót qua
bốn tài liệu.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = 26517
# Hai tài liệu này BÀN VỀ chính sự lệch đó, nên được phép chứa số cũ.
DISCUSSES_THE_DISCREPANCY = {
    "42_RC2_PREBUILD_SOURCE_AND_EVIDENCE_AUDIT.md",
    "43_RESPONSE_TO_AUDIT_42.md",
    "44_RC2_REMEDIATION_AND_CLOSURE_PLAN.md",
}
WRONG = re.compile(r"26[.,]?515")


def _docs():
    for d in ("to_read", "docs", "reports"):
        yield from (ROOT / d).glob("*.md") if (ROOT / d).is_dir() else ()
    yield from (ROOT / "docs").glob("*.json") if (ROOT / "docs").is_dir() else ()


def test_khong_tai_lieu_nao_con_so_cu():
    bad = []
    for p in _docs():
        if p.name in DISCUSSES_THE_DISCREPANCY:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if WRONG.search(line):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert not bad, f"còn số RC-04 cũ (26.515) ở: {bad}"


def test_arithmetic_cua_nguon_canonical():
    """25.090 + 1.427 = 26.517. Nếu tổng không khớp thành phần thì nguồn sai,
    và mọi tài liệu chép theo nó cũng sai."""
    assert 25090 + 1427 == CANONICAL


@pytest.mark.parametrize("doc", ["to_read/37_RC2_BUILD_RUNBOOK.md"])
def test_tai_lieu_chinh_dung_so_moi(doc):
    p = ROOT / doc
    if not p.is_file():
        pytest.skip(f"MISSING ARTIFACT: {doc}")
    s = p.read_text(encoding="utf-8")
    assert "26.517" in s
    assert not WRONG.search(s)
