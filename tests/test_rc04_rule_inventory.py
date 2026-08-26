"""RC-04 + RC-09 · sổ đăng ký rule phải khớp MÃ theo cả hai chiều.

Hợp đồng P3 liệt kê 14 rule — đó là 14 rule đã NỔ trên corpus RC1, tức một
**mẫu**, không phải bộ luật. `quality.py` phát ra **27**. 13 rule kia nổ 0 lần
trên RC1; nếu một trong số đó nổ trên RC2 thì nó là rule không có defect,
không có consequence, không ai kiểm.

Hai chiều, và chiều B mới là chiều đã để `value_unit_period_conflict` sống sót
ba pha:

    A · mã phát ra ∉ sổ  = 0     "rule đang chạy có được map không"
    B · sổ ∉ mã phát ra  = 0     "rule được map có thật sự chạy không"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

INVENTORY = ROOT / "configs" / "rule_inventory_v1.yaml"
QUALITY = ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "quality.py"
CONTRACTS = ROOT / "configs" / "rc2_contracts_v1.yaml"

_RULE_ID = re.compile(r'"(Q-[A-Z0-9-]+)"')

BLOCKING_LIKE = {"blocking", "blocking_until_classified", "non_candidate",
                 "build_failure"}


@pytest.fixture(scope="module")
def inv():
    return yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def emitted() -> set[str]:
    """Mã mà CODE có thể phát ra — đọc từ nguồn, không từ một danh sách chép tay."""
    src = "\n".join(p.read_text(encoding="utf-8")
                    for p in sorted((ROOT / "src" / "text2pandas" / "pipelines" / "a6").glob("*.py")))
    return set(_RULE_ID.findall(src))


# ── chiều A ────────────────────────────────────────────────────────────────

def test_A_moi_rule_CODE_phat_ra_deu_co_trong_so(inv, emitted):
    mapped = {r["id"] for r in inv["rules"]}
    missing = sorted(emitted - mapped)
    assert not missing, f"unmapped_active_rule = {len(missing)}: {missing}"


# ── chiều B · RC-09 ────────────────────────────────────────────────────────

def test_B_moi_rule_TRONG_SO_deu_duoc_code_phat_ra(inv, emitted):
    """Chiều không ai hỏi — và là chiều đã để một rule chết sống ba pha.

    `value_unit_period_conflict` được khai blocking trong policy suốt ba pha
    mà không một dòng mã nào phát ra nó. Nó chặn 0 ca, mãi mãi, và không có
    gì báo. Test này làm điều đó không lặp lại được.
    """
    mapped = {r["id"] for r in inv["rules"]}
    retired = set(inv.get("retired") or [])
    dead = sorted(mapped - emitted - retired)
    assert not dead, (
        f"{len(dead)} rule khai trong sổ mà KHÔNG mã nào phát ra: {dead}. "
        "Hoặc cài nó, hoặc cho nghỉ hưu kèm bằng chứng ở `retired_rules`.")


# ── hình dạng sổ ───────────────────────────────────────────────────────────

def test_moi_rule_co_defect_va_consequence(inv):
    for r in inv["rules"]:
        assert r.get("defect"), f"{r['id']} thiếu `defect`"
        assert r.get("consequence"), f"{r['id']} thiếu `consequence`"


def test_consequence_dung_TU_VUNG_cua_readiness_policy(inv):
    """Sổ và chính sách phải nói cùng một ngôn ngữ, nếu không thì không map được."""
    allowed = {"non_candidate", "blocking", "blocking_until_classified",
               "warning_conditional", "warning", "build_failure", "informational"}
    bad = [(r["id"], r["consequence"]) for r in inv["rules"]
           if r["consequence"] not in allowed]
    assert not bad, bad


def test_moi_rule_warning_phai_ghi_HE_QUA_downstream(inv):
    """Acceptance của hợp đồng P3. Warning không nói hệ quả thì nó là tiếng ồn."""
    missing = [r["id"] for r in inv["rules"]
               if r["consequence"] in ("warning", "warning_conditional")
               and not r.get("downstream")]
    assert not missing, missing


def test_co_cover_du_27_rule(inv, emitted):
    assert len(emitted) == 27, f"số mã trong code đổi: {len(emitted)}"
    assert len(inv["rules"]) == 27


# ── liên thông với hợp đồng đã đóng băng ───────────────────────────────────

def test_khong_mau_thuan_voi_inventory_14_rule_cua_P3(inv):
    """Sổ này MỞ RỘNG hợp đồng P3, không được nói ngược nó."""
    con = yaml.safe_load(CONTRACTS.read_text(encoding="utf-8"))
    frozen = {r["id"]: r for r in con["active_rule_inventory"]["rules"]}
    mine = {r["id"]: r for r in inv["rules"]}
    for rid, fr in frozen.items():
        assert rid in mine, f"{rid} có trong hợp đồng P3 mà mất khỏi sổ"
        assert mine[rid]["defect"] == fr["defect"], rid
        assert mine[rid]["consequence"] == fr["consequence"], rid
        assert mine[rid]["rc1_total"] == fr["total"], rid


def test_rule_chan_deu_map_ve_mot_co_cua_policy(inv):
    """Rule `blocking` mà không có cờ tương ứng thì chính sách không thi hành được."""
    pol = yaml.safe_load(
        (ROOT / "configs" / "readiness_policy_v1.yaml").read_text(encoding="utf-8"))
    er = pol["execution_ready"]
    flags = ({b["flag"] for b in er["blocking_flags"]}
             | {c["flag"] for c in er["conditional_flags"]}
             | {w["flag"] for w in er["warning_flags"]})
    for r in inv["rules"]:
        f = r.get("maps_to_flag")
        if f:
            assert f in flags, f"{r['id']} trỏ tới cờ {f!r} không có trong policy"
