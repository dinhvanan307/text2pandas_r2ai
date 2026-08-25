"""B0-06 · C0-final phải phủ bản dựng ĐÃ finalize, và RC2-020 group_uid tất định.

C0-core chỉ so 5 bảng lõi TRƯỚC `quality`. Nó không thể phát hiện bất định ở
`collision_*`, `quality_issues`, `observation_readiness` — và thực tế đã bỏ lọt
một lỗi thật (RC2-020).
"""
from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "rebuild_check.py"


def _mk(d: Path, *, finalized=True, stages=None, val="1", bid="B1") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(d / "silver.sqlite")
    con.executescript("""
    CREATE TABLE table_features(table_uid TEXT, parse_status TEXT);
    CREATE TABLE rows(row_uid TEXT, label_clean TEXT);
    CREATE TABLE columns(column_uid TEXT, role TEXT);
    CREATE TABLE observations(observation_uid TEXT, value_decimal_text TEXT);
    CREATE TABLE dropped_cells(source_cell_uid TEXT, reason TEXT);
    CREATE TABLE quality_issues(issue_uid TEXT, rule_id TEXT);
    CREATE TABLE build_meta(key TEXT, value TEXT);
    """)
    con.execute("INSERT INTO table_features VALUES('T1','ok')")
    con.execute("INSERT INTO observations VALUES('o1',?)", (val,))
    con.execute("INSERT INTO quality_issues VALUES('i1','Q-X')")
    con.execute("INSERT INTO build_meta VALUES('build_id',?)", (bid,))
    con.commit()
    con.close()
    (d / "completion_marker.json").write_text(json.dumps({
        "stages_completed": stages or ["snapshot", "catalog", "silver", "quality"],
        "finalized": finalized, "build_id": bid}), encoding="utf-8")
    return d


def _run(a: Path, b: Path, mode: str, rep: Path) -> int:
    return subprocess.run(
        [sys.executable, str(TOOL), "--build-a", str(a), "--build-b", str(b),
         "--mode", mode, "--report", str(rep)],
        capture_output=True, text=True).returncode


def test_c0_final_PASS_khi_hai_ban_giong_nhau(tmp_path):
    a, b = _mk(tmp_path / "A"), _mk(tmp_path / "B")
    assert _run(a, b, "final", tmp_path / "r.json") == 0


def test_c0_final_BAT_khac_biet_o_quality_issues(tmp_path):
    """Đúng loại khác biệt mà C0-core bỏ lọt."""
    a, b = _mk(tmp_path / "A"), _mk(tmp_path / "B")
    con = sqlite3.connect(b / "silver.sqlite")
    con.execute("INSERT INTO quality_issues VALUES('i2','Q-Y')")
    con.commit()
    con.close()
    assert _run(a, b, "final", tmp_path / "r.json") == 3
    # cùng dữ liệu đó, C0-core KHÔNG bắt được
    assert _run(a, b, "core", tmp_path / "r2.json") == 0


def test_thieu_completion_marker_thi_KHONG_ket_luan(tmp_path):
    a, b = _mk(tmp_path / "A"), _mk(tmp_path / "B")
    (b / "completion_marker.json").unlink()
    assert _run(a, b, "final", tmp_path / "r.json") == 2


def test_ban_chua_finalize_thi_KHONG_ket_luan(tmp_path):
    a = _mk(tmp_path / "A")
    b = _mk(tmp_path / "B", finalized=False, stages=["snapshot", "catalog", "silver"])
    assert _run(a, b, "final", tmp_path / "r.json") == 2


def test_hai_ban_chay_khac_chuoi_stage_thi_KHONG_ket_luan(tmp_path):
    a = _mk(tmp_path / "A", stages=["snapshot", "catalog", "silver", "quality"])
    b = _mk(tmp_path / "B", stages=["snapshot", "catalog", "silver"])
    assert _run(a, b, "final", tmp_path / "r.json") == 2


def test_c0_final_phu_bang_bat_buoc():
    src = TOOL.read_text(encoding="utf-8")
    for t in ("source_cells", "grid_cells", "quality_issues",
              "observation_readiness", "collision_groups", "collision_obs"):
        assert t in src, f"C0-final thiếu bảng {t}"


# ── RC2-020 · group_uid không được mang thành phần ngẫu nhiên ─────────────

def test_collision_group_uid_KHONG_dung_randomblob():
    """`randomblob(N)` với N<1 trả MỘT BYTE NGẪU NHIÊN (không phải blob rỗng),
    nên `group_uid` đổi mỗi lần build — bất định im lặng."""
    src = (ROOT / "src" / "data_pipeline" / "collision.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        code = line.split("--")[0]
        assert "randomblob" not in code, \
            f"còn randomblob trong SQL sinh group_uid: {line.strip()}"


def test_randomblob_0_that_su_khong_tat_dinh():
    """Khoá lại sự thật kỹ thuật, để không ai 'tối ưu' nó quay lại."""
    con = sqlite3.connect(":memory:")
    vals = {con.execute("SELECT lower(hex(randomblob(0)))").fetchone()[0]
            for _ in range(30)}
    con.close()
    assert len(vals) > 1, "randomblob(0) hoá ra tất định — xem lại giả định"


# ── RC2-041 · C0 phải tìm được DB khi bản làm việc đã dọn ────────────────

def _rc_mod():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "rebuild_check_resolve", ROOT / "tools" / "rebuild_check.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["rebuild_check_resolve"] = m
    spec.loader.exec_module(m)
    return m


def test_uu_tien_ban_LAM_VIEC_khi_con(tmp_path):
    rc = _rc_mod()
    (tmp_path / "silver.sqlite").write_bytes(b"x")
    (tmp_path / "silver" / "abc123").mkdir(parents=True)
    (tmp_path / "silver" / "abc123" / "silver.sqlite").write_bytes(b"x")
    assert rc._resolve_db(tmp_path) == tmp_path / "silver.sqlite"


def test_roi_xuong_ban_DA_PUBLISH_khi_ban_lam_viec_da_don(tmp_path):
    """Bản làm việc bị dọn để lấy đĩa là chuyện có thật và đã xảy ra: C0 chạy
    lại để lấy bằng chứng thì không còn input. `publish` copy bằng
    `shutil.copy2`, và hai tệp đã được đo là đồng nhất từng byte — nên so trên
    bản đã publish là so đúng những byte đó."""
    rc = _rc_mod()
    (tmp_path / "silver" / "abc123").mkdir(parents=True)
    (tmp_path / "silver" / "abc123" / "silver.sqlite").write_bytes(b"x")
    assert rc._resolve_db(tmp_path) == tmp_path / "silver" / "abc123" / "silver.sqlite"


def test_NHIEU_ban_publish_thi_KHONG_tu_chon(tmp_path):
    """Hai bản dựng trong cùng một thư mục là trạng thái không xác định. Tự
    chọn một cái là đoán, và đoán trong một cổng acceptance thì tệ hơn là dừng."""
    rc = _rc_mod()
    for b in ("aaa", "bbb"):
        (tmp_path / "silver" / b).mkdir(parents=True)
        (tmp_path / "silver" / b / "silver.sqlite").write_bytes(b"x")
    assert rc._resolve_db(tmp_path) == tmp_path / "silver.sqlite"   # -> báo lỗi cũ


def test_report_ghi_RO_da_so_tren_tep_nao():
    """Doc 52 §8 Bước 1: report phải ghi rõ input identity."""
    src = (ROOT / "tools" / "rebuild_check.py").read_text(encoding="utf-8")
    assert '"input_identity"' in src
    for k in ("db_a_path", "db_b_path", "db_a_is_published_copy"):
        assert k in src
    assert '"byte_identity"' in src and "--db-sha256" in src
