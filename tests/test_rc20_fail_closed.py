"""RC-20 và RC-17 phải FAIL-CLOSED.

Kiểm toán độc lập (Doc 56) tìm thấy bốn chỗ hệ acceptance im lặng cho qua:

* P0-02 · `summary` và `gates[]` nói hai điều khác nhau trong CÙNG một tệp,
  và `_exit_code()` chỉ đọc `gates[]`;
* P0-03 · `readiness` không nằm trong `REQUIRED_INPUTS`, nên thiếu nó RC-20
  vẫn exit 0;
* P0-04 · taxonomy parse ra 0 mã mà verdict vẫn PASS;
* P2-01 · mười ca replay cùng mang tên `replay::None`.

Cả bốn chỉ lộ ra ở ĐƯỜNG THÀNH CÔNG. Nhóm test này ép từng đường hỏng.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _gr():
    spec = importlib.util.spec_from_file_location("gr", ROOT / "tools" / "gate_report.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _rep(gates_status: dict) -> dict:
    return {"summary": {k: "BLOCKED" for k in gates_status},
            "gates": [{"gate": g, "status": s, "metrics": []}
                      for g, s in gates_status.items()],
            "release_label": "silver-v1.0.0-rc1"}


# ── B1 · summary phải bám gates[] ─────────────────────────────────────────

def test_summary_lech_gates_phai_duoc_dong_bo():
    gr = _gr()
    rep = _rep({"SG": "BLOCKED", "C0": "PASS", "C1": "PASS",
                "C2": "BLOCKED", "C3": "BLOCKED", "C4": "PASS", "C5": "PASS"})
    assert rep["summary"]["C0"] == "BLOCKED"          # trạng thái lỗi ban đầu
    gr._resync_summary(rep)
    st = {g["gate"]: g["status"] for g in rep["gates"]}
    assert rep["summary"] == st, "summary vẫn lệch gates[]"
    assert rep["summary_resynced_after_c0_resolution"] is True


def test_nhan_phat_hanh_dung_von_tu_vung_va_khong_con_rc1():
    gr = _gr()
    rep = _rep({"SG": "BLOCKED", "C0": "PASS", "C1": "PASS", "C2": "BLOCKED",
                "C3": "BLOCKED", "C4": "PASS", "C5": "PASS"})
    gr._resync_summary(rep)
    assert rep["release_label"] == "silver-v1.0.0-rc2"


def test_cong_FAIL_thi_nhan_phai_la_blocked():
    gr = _gr()
    rep = _rep({"SG": "BLOCKED", "C0": "PASS", "C1": "FAIL", "C2": "BLOCKED",
                "C3": "BLOCKED", "C4": "PASS", "C5": "PASS"})
    gr._resync_summary(rep)
    assert rep["release_label"] == "blocked"


def test_cong_BLOCKED_ngoai_allowlist_thi_blocked():
    gr = _gr()
    rep = _rep({"SG": "BLOCKED", "C0": "PASS", "C1": "BLOCKED", "C2": "BLOCKED",
                "C3": "BLOCKED", "C4": "PASS", "C5": "PASS"})
    gr._resync_summary(rep)
    assert rep["release_label"] == "blocked", "C1 BLOCKED không nằm trong allowlist"


# ── B2 · readiness là input BẮT BUỘC ──────────────────────────────────────

def test_readiness_nam_trong_required_inputs():
    assert "readiness" in _gr().REQUIRED_INPUTS


@pytest.mark.parametrize("data,mong_doi", [
    ({"verdict": "PASS"}, "PASS"),
    ({"verdict": "FAIL"}, "FAIL"),
    ({"summary": {"verdict": "FAIL"}}, "FAIL"),
    ({}, None),
])
def test_verdict_cua_readiness_duoc_doc_that(data, mong_doi):
    assert _gr()._verdict_of("readiness", data) == mong_doi


# ── B3 · taxonomy rỗng là FAIL, không phải PASS ───────────────────────────

def _readiness_tool(db: Path, tax: Path, out: Path):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "readiness_report.py"),
         "--db", str(db), "--taxonomy", str(tax), "--report", str(out)],
        capture_output=True, text=True, cwd=ROOT, timeout=600)


def _db():
    for p in (ROOT / "artifacts/rc2/buildA3/silver/7aa8b4c22984bf5f/silver.sqlite",
              ROOT / "artifacts/rc2/release_finalv2/silver.db"):
        if p.is_file():
            return p
    return None


def test_taxonomy_rong_phai_FAIL(tmp_path):
    db = _db()
    if db is None:
        pytest.skip("MISSING ARTIFACT: không có DB để chạy readiness")
    tax = tmp_path / "tax.yaml"
    tax.write_text('taxonomy_version: "1.0"\ndefects: {}\n', encoding="utf-8")
    out = tmp_path / "r.json"
    r = _readiness_tool(db, tax, out)
    assert r.returncode != 0, "taxonomy rỗng mà readiness vẫn exit 0"
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["verdict"] == "FAIL"
    assert d["taxonomy_n_codes"] == 0
    assert d["taxonomy_error"], "phải nói RÕ vì sao taxonomy không dùng được"


def test_taxonomy_that_phai_co_ma_va_PASS(tmp_path):
    db = _db()
    if db is None:
        pytest.skip("MISSING ARTIFACT: không có DB để chạy readiness")
    out = tmp_path / "r.json"
    r = _readiness_tool(db, ROOT / "configs" / "defect_taxonomy_v1.yaml", out)
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["taxonomy_n_codes"] > 0, "bảng nối readiness_reasons không đọc được"
    assert d["taxonomy_error"] is None
    assert r.returncode == 0 and d["verdict"] == "PASS"


def test_reason_tro_toi_defect_khong_ton_tai_phai_FAIL(tmp_path):
    """Bảng nối có mã nhưng trỏ sai thì cũng không dùng được."""
    from importlib.util import module_from_spec, spec_from_file_location
    spec = spec_from_file_location("rr", ROOT / "tools" / "readiness_report.py")
    rr = module_from_spec(spec); spec.loader.exec_module(rr)
    tax = tmp_path / "tax.yaml"
    tax.write_text('defects:\n  D-01:\n    name: x\n'
                   'readiness_reasons:\n  abc: D-99\n', encoding="utf-8")
    codes, err = rr._taxonomy(tax)
    assert err and "D-99" in err


# ── B4 · danh tính từng ca replay ─────────────────────────────────────────

def _replay():
    p = ROOT / "artifacts/rc2/acceptance/replay/replay_report.json"
    if not p.is_file():
        pytest.skip("MISSING ARTIFACT: replay_report.json")
    return json.loads(p.read_text(encoding="utf-8"))


def _c5(rep):
    from text2pandas.pipelines.a6.gates import _gate_c5
    g = _gate_c5(rep)
    return g, {m.name: m.status for m in g.metrics}


def test_replay_that_giu_duoc_danh_tinh_tung_ca():
    g, m = _c5(_replay())
    ten = [x.name for x in g.metrics if x.name.startswith("replay::")]
    assert "replay::None" not in ten, "mất case_id — không truy vết được ca nào"
    assert len(set(ten)) == len(ten) == 10


def test_replay_trung_ID_phai_FAIL():
    rep = _replay()
    rep["cases"][3]["case_id"] = rep["cases"][2]["case_id"]
    g, m = _c5(rep)
    assert str(m["replay_case_duplicate_id"]) != "PASS"
    assert str(g.status) != "PASS"


def test_replay_thieu_ID_phai_FAIL():
    rep = _replay()
    for k in ("case_id", "case", "name"):
        rep["cases"][5].pop(k, None)
    g, m = _c5(rep)
    assert str(m["replay_case_missing_id"]) != "PASS"
    assert str(g.status) != "PASS"


def test_replay_thieu_ca_phai_FAIL():
    rep = _replay()
    rep["cases"] = rep["cases"][:8]
    g, m = _c5(rep)
    assert str(m["replay_case_id_count"]) != "PASS"
    assert str(g.status) != "PASS"
