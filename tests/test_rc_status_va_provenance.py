"""P1-01 · RC_STATUS không được gán PASS sớm.
P1-02 · mỗi claim phải tách thời gian CHẠY khỏi thời gian ĐÓNG GÓI.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "evstat", ROOT / "tools" / "evidence_status.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["evstat"] = ev
_spec.loader.exec_module(ev)


def _rc(**kw):
    d = {"id": "RC-XX", "status": "PASS", "acceptance_met": True,
         "evidence_paths": ["x.json"], "acceptance_scope": "unit",
         "evidence_scope": "unit"}
    d.update(kw)
    return {"rc": [d]}


# ── P1-01 ─────────────────────────────────────────────────────────────────

def test_PASS_ma_khong_co_evidence_la_vi_pham():
    assert ev.validate_rc_status(_rc(evidence_paths=[]))


def test_bang_chung_YEU_hon_acceptance_la_vi_pham():
    """RC đòi full-data mà bằng chứng chỉ là fixture — đúng ca RC-23/RC-24."""
    e = ev.validate_rc_status(_rc(acceptance_scope="full_data",
                                  evidence_scope="fixture"))
    assert e and "full_data" in e[0]


def test_bang_chung_MANH_hon_thi_duoc():
    assert not ev.validate_rc_status(_rc(acceptance_scope="unit",
                                         evidence_scope="full_data"))


def test_status_chua_xong_ma_acceptance_met_la_vi_pham():
    for st in ("IMPLEMENTED_NOT_RUN", "OPEN", "FIXED_NOT_RERUN", "FIXED_PARTIAL"):
        assert ev.validate_rc_status(_rc(status=st)), f"{st} phải bị chặn"


def test_du_lieu_hop_le_thi_khong_vi_pham():
    assert not ev.validate_rc_status(_rc())


def test_acceptance_met_false_thi_khong_bi_soi():
    assert not ev.validate_rc_status(_rc(acceptance_met=False, evidence_paths=[],
                                         status="OPEN"))


# ── P1-02 ─────────────────────────────────────────────────────────────────

def _claim(**kw):
    d = {"claim_id": "EV-01", "status": "PASS",
         "executed_on_host_role": "evidence_host",
         "executed_at_utc": "2026-08-11T03:22:56Z",
         "packaged_at_utc": "2026-08-11T03:48:13Z",
         "provenance_class": "machine_generated",
         "machine_readable_report": "validations/x.json"}
    d.update(kw)
    return {"claims": [d]}


def test_thieu_truong_thoi_gian_la_vi_pham():
    for k in ("executed_at_utc", "packaged_at_utc", "executed_on_host_role",
              "provenance_class"):
        assert ev.validate_evidence_manifest(_claim(**{k: None})), f"thiếu {k}"


def test_executed_at_SAU_packaged_at_la_vi_pham():
    """Nếu giờ chạy sau giờ đóng gói thì một trong hai là giờ bịa."""
    e = ev.validate_evidence_manifest(_claim(
        executed_at_utc="2026-08-11T09:00:00Z",
        packaged_at_utc="2026-08-11T03:48:13Z"))
    assert e and "SAU" in e[0]


def test_operator_copied_KHONG_duoc_PASS():
    """Bằng chứng do người vận hành dán lại là lời khai, không phải artifact."""
    e = ev.validate_evidence_manifest(_claim(provenance_class="operator_copied"))
    assert e and "operator_copied" in e[0]


def test_operator_copied_voi_nhan_khac_thi_duoc():
    assert not ev.validate_evidence_manifest(
        _claim(provenance_class="operator_copied", status="OPERATOR_REPORTED"))


def test_PASS_ma_khong_co_report_lan_log_la_vi_pham():
    assert ev.validate_evidence_manifest(
        _claim(machine_readable_report=None, stdout_stderr_path=None))


def test_NOT_RUN_khong_bi_doi_provenance():
    assert not ev.validate_evidence_manifest(
        {"claims": [{"claim_id": "EV-15", "status": "NOT_RUN"}]})


def test_claim_hop_le_thi_khong_vi_pham():
    assert not ev.validate_evidence_manifest(_claim())
