"""RC-20 · cổng phát hành phải CHẶN được, không chỉ báo cáo.

Doc 52 §8 Bước 7: *"Một file JSON ghi FAIL nhưng command vẫn exit 0 không phải
release gate."* Bộ test này khoá hai thứ:

* **RC2-046** — ba metric C0 được khai BLOCKED kèm lý do nêu đích danh artifact
  còn thiếu (`rebuild_check`, `differential`). Ba artifact đó nay đã có, nhưng
  `evaluate_gates()` không nhận chúng, nên C0 vĩnh viễn BLOCKED — và vì C0
  không nằm trong `ALLOWED_BLOCKED`, RC-20 **không bao giờ** exit 0 được, kể cả
  khi mọi cổng khác xanh. Giải BLOCKED bằng đúng bằng chứng mà lý do BLOCKED
  nêu tên, và CHỈ khi verdict PASS + build_id khớp.
* **RC2-047** — mọi report phải mang `build_id`. Thiếu nó, phép kiểm
  "input build/hash mismatch = 0" của RC-20 im lặng bỏ qua, vì nó chỉ so khi
  cả hai bên cùng có giá trị.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# ── RC2-046 · C0 phải giải được bằng chính bằng chứng nó đòi ─────────────

def _gate_mod():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "gate_report_c0", ROOT / "tools" / "gate_report.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["gate_report_c0"] = m
    spec.loader.exec_module(m)
    return m


def _rep_c0(bid="B1"):
    return {"build_id": bid, "gates": [{"gate": "C0", "metrics": [
        {"name": "manifest_completeness", "status": "PASS", "blocking_reason": None},
        {"name": "uid_stability_two_clean_rebuilds", "status": "BLOCKED",
         "blocking_reason": "cần hai lần clean rebuild"},
        {"name": "output_checksum_determinism", "status": "BLOCKED",
         "blocking_reason": "cần hai lần build để so"},
        {"name": "unexplained_count_delta", "status": "BLOCKED",
         "blocking_reason": "cần differential audit"},
    ], "status": "BLOCKED"}]}


def _inputs(rc_verdict="PASS", rc_bid="B1", df_verdict="PASS", df_bid="B1"):
    return {"reports": {
        "rebuild_check": {"status": "OK", "verdict": rc_verdict,
                          "build_id": rc_bid, "path": "rc.json"},
        "differential": {"status": "OK", "verdict": df_verdict,
                         "build_id": df_bid, "path": "df.json"}}}


def test_C0_giai_duoc_khi_co_du_bang_chung():
    """Trước RC2-046, C0 vĩnh viễn BLOCKED dù `rebuild_check.json` đã PASS —
    và vì C0 không nằm trong ALLOWED_BLOCKED, RC-20 KHÔNG BAO GIỜ exit 0 được."""
    m = _gate_mod()
    rep = _rep_c0(); rep["inputs"] = _inputs()
    ket = m._resolve_c0(rep, None)
    assert rep["gates"][0]["status"] == "PASS", ket
    assert all(v.startswith("PASS ←") for k, v in ket.items())


def test_C0_KHONG_giai_khi_report_FAIL():
    m = _gate_mod()
    rep = _rep_c0(); rep["inputs"] = _inputs(rc_verdict="FAIL")
    m._resolve_c0(rep, None)
    assert rep["gates"][0]["status"] == "BLOCKED"


def test_C0_KHONG_giai_khi_build_id_LECH():
    """Một report PASS của bản dựng KHÁC không chứng minh gì cho bản này."""
    m = _gate_mod()
    rep = _rep_c0(); rep["inputs"] = _inputs(rc_bid="BUILD_KHAC")
    ket = m._resolve_c0(rep, None)
    assert rep["gates"][0]["status"] == "BLOCKED"
    assert "BUILD_KHAC" in ket["uid_stability_two_clean_rebuilds"]


def test_C0_KHONG_giai_khi_report_THIEU_build_id():
    """RC2-047 · report không mang build_id thì không xác thực được nó thuộc
    bản dựng nào — im lặng chấp nhận là mở lại đúng lỗ hổng vừa bịt."""
    m = _gate_mod()
    rep = _rep_c0(); rep["inputs"] = _inputs(rc_bid=None)
    ket = m._resolve_c0(rep, None)
    assert rep["gates"][0]["status"] == "BLOCKED"
    assert "KHÔNG mang build_id" in ket["uid_stability_two_clean_rebuilds"]


def test_C0_KHONG_giai_khi_thieu_report():
    m = _gate_mod()
    rep = _rep_c0()
    rep["inputs"] = {"reports": {"rebuild_check": {"status": "MISSING"},
                                 "differential": {"status": "MISSING"}}}
    m._resolve_c0(rep, None)
    assert rep["gates"][0]["status"] == "BLOCKED"


# ── RC2-047 · mọi report mang build_id ───────────────────────────────────

@pytest.mark.parametrize("tool", ["rebuild_check.py", "differential_audit.py",
                                  "replay_report.py"])
def test_report_mang_build_id(tool):
    src = (ROOT / "tools" / tool).read_text(encoding="utf-8")
    assert '"build_id"' in src, f"{tool} không ghi build_id vào report"
