"""RC2-031 · SEQ-05 — thứ tự phải đúng với ĐỒ THỊ THẬT, không chỉ đồ thị khai.

Defect gốc, đo được trên bản dựng thật:

  `configs/execution_sequence_v1.yaml` v1.0 khai `replay (P8) → rc20_gate (P8)
  → release (P9)`. Nhưng `tools/replay_report.py` đọc
  `SELECT * FROM v_long_dataframe`, và view đó CHỈ tồn tại trong release DB —
  `src/text2pandas/pipelines/a6/release.py` sinh nó. Build DB `5ffc07216708d9fd` chỉ có
  `v_execution_ready` và `v_retrieval_ready`.

  Nghĩa là `replay` — một trong năm report BẮT BUỘC của `gate_report` — chỉ sinh
  ra được bởi `release`, chính là bước mà RC-20 đang gác. Thứ tự khai không chạy
  được.

Vì sao bốn test tô-pô cũ không bắt: chúng chỉ duyệt cạnh `must_follow` khai
trong YAML. Đồ thị *khai báo* phi chu trình; đồ thị *thật* thì không. Chúng kiểm
cái được viết ra, không kiểm cái thực sự xảy ra.

Bộ test này khoá khoảng trống đó bằng `artifacts_consumed` / `artifacts_produced`.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "configs" / "execution_sequence_v1.yaml"


@pytest.fixture(scope="module")
def steps():
    seq = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    return {s["id"]: s for s in seq["steps"]}


def _ancestors(steps, sid, seen=None):
    seen = seen if seen is not None else set()
    for p in steps[sid].get("must_follow") or []:
        if p not in seen:
            seen.add(p)
            _ancestors(steps, p, seen)
    return seen


# ── SEQ-05 · bất biến chính ───────────────────────────────────────────────

def test_SEQ05_moi_artifact_tieu_thu_deu_do_mot_buoc_TIEN_NHIEM_sinh(steps):
    """Đây là test đáng ra phải bắt được RC2-031 ngay từ khi B0-08 ra đời."""
    vi_pham = []
    for sid, s in steps.items():
        anc = _ancestors(steps, sid)
        sinh = {a for p in anc for a in (steps[p].get("artifacts_produced") or [])}
        for art in s.get("artifacts_consumed") or []:
            if art not in sinh:
                ai_sinh = [q for q, t in steps.items()
                           if art in (t.get("artifacts_produced") or [])]
                vi_pham.append(f"{sid} đọc `{art}` — sinh bởi {ai_sinh or 'KHÔNG AI'}"
                               f", không nằm trong tiền nhiệm {sorted(anc)}")
    assert not vi_pham, "\n".join(vi_pham)


def test_moi_artifact_tieu_thu_deu_co_nguoi_sinh(steps):
    """Một artifact không ai sinh ra là một bước không bao giờ chạy được."""
    sinh = {a for s in steps.values() for a in (s.get("artifacts_produced") or [])}
    mo_coi = {(sid, a) for sid, s in steps.items()
              for a in (s.get("artifacts_consumed") or []) if a not in sinh}
    assert not mo_coi, mo_coi


# ── hồi quy trực tiếp cho RC2-031 ─────────────────────────────────────────

def test_replay_phai_chay_SAU_release(steps):
    assert "release" in _ancestors(steps, "replay"), (
        "replay đọc `v_long_dataframe`, view chỉ có trong release DB")


def test_rc20_phai_chay_SAU_ca_replay_lan_release(steps):
    anc = _ancestors(steps, "rc20_gate")
    assert {"replay", "release"} <= anc


def test_SEQ01_van_nguyen_ven_dong_goi_sau_RC20(steps):
    """Sửa thứ tự KHÔNG được phá bất biến quan trọng nhất của B0-08."""
    assert "rc20_gate" in _ancestors(steps, "package")


def test_YAML_khop_voi_SQL_that_trong_replay_report():
    """Buộc lời khai trong YAML dính vào mã thật. Nếu ai đó đổi
    `replay_report.py` sang đọc bảng của build DB, test này phải đỏ để thứ tự
    được xem lại — chứ không để hai thứ trôi khỏi nhau trong im lặng."""
    src = (ROOT / "tools" / "replay_report.py").read_text(encoding="utf-8")
    assert "v_long_dataframe" in src
    seq = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    st = {s["id"]: s for s in seq["steps"]}
    assert "release_silver.db" in st["replay"]["artifacts_consumed"]
    assert "release_silver.db" in st["release"]["artifacts_produced"]


def test_rc20_tieu_thu_du_SAU_report_bat_buoc_cua_gate_report():
    """Danh sách bắt buộc lấy TỪ CHÍNH `gate_report.REQUIRED_INPUTS`, không gõ
    tay — gõ tay là cách hai nguồn sự thật bắt đầu trôi khỏi nhau."""
    spec = importlib.util.spec_from_file_location(
        "gate_report_mod", ROOT / "tools" / "gate_report.py")
    gr = importlib.util.module_from_spec(spec)
    sys.modules["gate_report_mod"] = gr
    spec.loader.exec_module(gr)
    seq = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    st = {s["id"]: s for s in seq["steps"]}
    tieu_thu = " ".join(st["rc20_gate"]["artifacts_consumed"])
    # B2 · readiness là report thứ SÁU. Danh sách này phải đi cùng
    # `REQUIRED_INPUTS`; lệch nhau là spec và mã nói hai điều khác nhau.
    khoa = {"rebuild_check": "rebuild_check", "no_loss": "no_loss",
            "differential": "differential", "replay": "replay",
            "unresolved": "unresolved", "readiness": "readiness"}
    assert set(gr.REQUIRED_INPUTS) == set(khoa), (
        f"REQUIRED_INPUTS đổi rồi: {gr.REQUIRED_INPUTS}")
    for name, frag in khoa.items():
        assert frag in tieu_thu, f"rc20_gate không khai tiêu thụ report `{name}`"


# ── RC2-030 · C0 không được tuyên bố phạm vi nó không đo được ─────────────

def _rc():
    spec = importlib.util.spec_from_file_location(
        "rebuild_check_mod", ROOT / "tools" / "rebuild_check.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["rebuild_check_mod"] = m
    spec.loader.exec_module(m)
    return m


def test_CANONICAL_FINAL_khong_chua_bang_chi_co_o_release():
    rc = _rc()
    assert set(rc.CANONICAL_FINAL) & set(rc.RELEASE_ONLY) == set()
    for t in ("documents", "pages", "tables", "table_cards"):
        assert t in rc.RELEASE_ONLY
        assert t not in rc.CANONICAL_FINAL, (
            f"`{t}` không tồn tại trong DB bản dựng — để nó trong CANONICAL_FINAL "
            "khiến C0 tuyên bố phạm vi nó không đo được")


def test_CANONICAL_FINAL_van_bao_phu_phan_finalize():
    """Thu hẹp phạm vi KHÔNG được làm mất những bảng mà C0-core bỏ sót — đó là
    lý do B0-06 sinh ra chế độ final."""
    rc = _rc()
    for t in ("source_cells", "grid_cells", "quality_issues",
              "observation_readiness", "collision_groups", "collision_obs"):
        assert t in rc.CANONICAL_FINAL
    assert set(rc.CANONICAL_CORE) <= set(rc.CANONICAL_FINAL)


@pytest.mark.parametrize("t", ["documents", "pages", "tables", "table_cards"])
def test_bang_release_only_that_su_vang_trong_DB_ban_dung(t):
    """Khẳng định trên DỮ LIỆU THẬT, không chỉ trên hằng số."""
    db = ROOT / "data" / "processed" / "a6" / "b927c3e8f90aed74" / "silver.sqlite"
    if not db.is_file():
        pytest.skip("MISSING ARTIFACT: DB bản dựng RC1 không có trong cây này")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    c.close()
    assert t not in names


# ── RC2-027 · dấu thời gian khai báo, không giả vờ là phép đo ─────────────

def test_hop_dong_replay_khong_con_truong_gia_vo_la_phep_do():
    d = yaml.safe_load(
        (ROOT / "configs" / "replay_expected_v1.yaml").read_text(encoding="utf-8"))
    assert "filled_at_utc" not in d, (
        "`filled_at_utc` đọc như một phép đo, và giá trị cũ nằm ở TƯƠNG LAI so "
        "với lúc sinh")
    assert d.get("frozen_at_declared"), "phải khai mốc đóng băng"
    assert d.get("frozen_at_note"), "phải nói rõ đây là hằng số khai báo"
