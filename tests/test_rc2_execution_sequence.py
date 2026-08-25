"""B0-08 · thứ tự thực thi phải là artifact máy đọc được, không phải văn xuôi.

Trước đây thứ tự nằm rải ở runbook 37, `status/NEXT_EXECUTION_SEQUENCE.md` và
doc 43 — ba nơi đã lệch nhau thật: bản trong gói còn ghi
`release → package → verify → differential/replay/gate`, tức đóng gói TRƯỚC khi
có báo cáo acceptance.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "configs" / "execution_sequence_v1.yaml"


@pytest.fixture(scope="module")
def seq():
    return yaml.safe_load(SPEC.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(seq):
    return {s["id"]: s for s in seq["steps"]}


def _ancestors(steps, sid, seen=None):
    seen = seen if seen is not None else set()
    for p in steps[sid].get("must_follow") or []:
        if p not in seen:
            seen.add(p)
            _ancestors(steps, p, seen)
    return seen


def test_moi_must_follow_deu_tro_toi_buoc_co_that(steps):
    for sid, s in steps.items():
        for p in s.get("must_follow") or []:
            assert p in steps, f"{sid}.must_follow trỏ tới bước không tồn tại: {p}"


def test_khong_co_chu_trinh(steps):
    for sid in steps:
        assert sid not in _ancestors(steps, sid), f"chu trình quanh {sid}"


def test_SEQ01_package_phai_sau_RC20(steps):
    """Bất biến quan trọng nhất của B0-08."""
    assert "rc20_gate" in _ancestors(steps, "package"), \
        "đóng gói trước RC-20 → báo cáo acceptance nằm ngoài manifest/checksum"


def test_SEQ02_c0_final_sau_ca_hai_build(steps):
    anc = _ancestors(steps, "c0_final")
    assert {"build_a", "build_b"} <= anc


def test_SEQ03_cleanup_la_buoc_cuoi(steps):
    assert "verify" in _ancestors(steps, "cleanup")
    for sid, s in steps.items():
        if sid != "cleanup":
            assert "cleanup" not in (s.get("must_follow") or []), \
                f"{sid} chạy SAU cleanup — dọn trước khi xong là mất bản dựng"


def test_SEQ04_rc20_doc_du_nam_cong(steps):
    need = {"c0_final", "c1_no_loss", "readiness_c4", "differential",
            "unresolved", "replay"}
    assert need <= set(steps["rc20_gate"]["must_follow"])


def test_c0_final_khong_duoc_dung_mode_core(steps):
    assert "--mode final" in steps["c0_final"]["command"]
    assert any("core" in c for c in steps["c0_final"]["exit_criteria"])


def test_env_check_doi_lock_matches_installed(steps):
    crit = " ".join(steps["env_check"]["exit_criteria"])
    assert "lock_matches_installed = true" in crit
    assert "untracked_in_source_paths = []" in crit


def test_replay_doi_10_10_khong_skip(steps):
    crit = " ".join(steps["replay"]["exit_criteria"])
    assert "10/10" in crit and "0 skip" in crit and "0 error" in crit


def test_moi_buoc_co_du_truong_bat_buoc(steps):
    for sid, s in steps.items():
        for k in ("id", "phase", "command", "exit_criteria", "must_follow",
                  "artifacts_consumed", "artifacts_produced"):
            assert k in s, f"bước {sid} thiếu trường {k}"


def test_nam_bat_bien_duoc_khai(seq):
    """SEQ-05 vào v1.1: bốn bất biến cũ chỉ kiểm cạnh ĐƯỢC KHAI, nên chúng
    không thấy quan hệ thật "bước X đọc artifact do bước Y sinh" — và RC2-031
    đã lọt qua đúng khoảng trống đó."""
    ids = {i["id"] for i in seq["invariants"]}
    assert ids == {"SEQ-01", "SEQ-02", "SEQ-03", "SEQ-04", "SEQ-05"}
    for i in seq["invariants"]:
        assert i.get("rationale"), f"{i['id']} thiếu rationale"


def test_runbook_khong_con_thu_tu_cu():
    """Runbook không được còn câu bảo dọn trước C0."""
    rb = ROOT / "to_read" / "37_RC2_BUILD_RUNBOOK.md"
    if not rb.is_file():
        pytest.skip("MISSING ARTIFACT: runbook 37")
    txt = rb.read_text(encoding="utf-8")
    i_clean, i_c0 = txt.find("rm -f"), txt.find("dp-rebuild-check")
    assert i_c0 != -1
    assert i_clean == -1 or i_clean > i_c0
