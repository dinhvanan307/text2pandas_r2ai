"""SAFETY · ba cái bẫy trong chính chuỗi build, khoá bằng test chứ không bằng lời.

Runbook `to_read/37` mô tả cả ba. Mô tả trong tài liệu KHÔNG phải một biện pháp
bảo vệ: nó chỉ hoạt động khi người vận hành đọc đúng dòng đó vào đúng lúc.

  RC2-004  `cli release` mặc định ghi vào `silver_release/` = baseline RC1
  RC2-005  `DATA_PIPELINE_SCRATCH` không nối tiếp giữa các stage
  RC2-012  runbook bảo xoá `silver.sqlite` của A TRƯỚC khi C0 chạy
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

CLI = ROOT / "src" / "data_pipeline" / "cli.py"
REBUILD = ROOT / "tools" / "rebuild_check.py"


def _run(args, env=None, cwd=None):
    e = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    e.update(env or {})
    e.pop("DATA_PIPELINE_SCRATCH", None) if env is None else None
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, env=e, cwd=cwd or ROOT, timeout=120)


# ── RC2-004 · release không được có default phá huỷ ────────────────────────

def test_release_thieu_out_thi_FAIL(tmp_path):
    r = _run(["-m", "data_pipeline.cli", "release"])
    assert r.returncode != 0
    assert "--out" in (r.stderr + r.stdout)


def test_KHONG_con_default_ghi_vao_silver_release():
    """Chống hồi quy ở mức nguồn — dòng cũ không được quay lại."""
    src = CLI.read_text(encoding="utf-8")
    # Kiểm DÒNG MÃ, không kiểm chuỗi bất kỳ: chú thích giải thích lỗi cũ có
    # nhắc tới đường dẫn đó, và cấm cả chú thích thì mất luôn lời giải thích.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert 'else ROOT / "silver_release"' not in code, (
        "mặc định ghi đè baseline RC1 đã quay lại")
    assert 'r.add_argument("--out", required=True' in code


def test_argparse_khai_out_la_required():
    from data_pipeline import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["release"])
    assert e.value.code == 2


# ── RC2-005 · scratch không được ngầm định khi đã có rác ───────────────────

def test_scratch_mac_dinh_CO_RAC_thi_dung_han(tmp_path, monkeypatch):
    """Đọc nhầm scratch của build khác là lỗi im lặng tệ nhất của chuỗi build."""
    from data_pipeline import cli
    stale = tmp_path / "dp_work"
    stale.mkdir()
    (stale / "silver.sqlite").write_text("rác của build khác", encoding="utf-8")
    monkeypatch.setattr(cli, "_SCRATCH_EXPLICIT", False)
    monkeypatch.setattr(cli, "SCRATCH", stale)
    with pytest.raises(SystemExit) as e:
        cli.assert_scratch_explicit("publish")
    assert "DATA_PIPELINE_SCRATCH" in str(e.value)


def test_scratch_dat_TUONG_MINH_thi_khong_can_canh_bao(tmp_path, monkeypatch):
    from data_pipeline import cli
    monkeypatch.setattr(cli, "_SCRATCH_EXPLICIT", True)
    monkeypatch.setattr(cli, "SCRATCH", tmp_path)
    cli.assert_scratch_explicit("publish")      # không được ném


def test_quality_va_publish_deu_goi_cong_kiem():
    src = CLI.read_text(encoding="utf-8")
    for stage in ("quality", "publish"):
        i = src.index(f"def cmd_{stage}(args)")
        assert 'assert_scratch_explicit' in src[i:i + 400], stage


# ── RC2-012 · thứ tự A/B — C0 phải chạy TRƯỚC khi dọn ──────────────────────

def test_thieu_silver_sqlite_thi_noi_RO_la_sai_thu_tu(tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir(); b.mkdir()
    r = _run([str(REBUILD), "--build-a", str(a), "--build-b", str(b)])
    out = r.stderr + r.stdout
    assert "rebuild-check" in out and "dọn dẹp" in out, (
        "thông báo phải chỉ ra SAI THỨ TỰ, không chỉ 'không thấy tệp'")


def test_runbook_KHONG_con_bao_xoa_A_truoc_C0():
    """Runbook là một tài liệu vận hành — sai thứ tự ở đó là một lỗi thật."""
    cand = [ROOT / "docs" / "37_RC2_BUILD_RUNBOOK.md",
            ROOT / "to_read" / "37_RC2_BUILD_RUNBOOK.md"]
    rb = next((p for p in cand if p.exists()), None)
    if rb is None:
        pytest.skip("MISSING ARTIFACT: 37_RC2_BUILD_RUNBOOK.md không có "
                    "trong source package (nó nằm ở to_read/, ngoài phạm vi gói)")
    txt = rb.read_text(encoding="utf-8")
    i_clean = txt.find("rm -f")
    i_c0 = txt.find("dp-rebuild-check")
    assert i_c0 != -1
    assert i_clean == -1 or i_clean > i_c0, (
        "runbook vẫn bảo dọn `silver.sqlite` TRƯỚC khi C0 chạy")


# ── B0-01 · giao diện release explicit ────────────────────────────────────

def test_make_dp_release_khong_con_truyen_tham_so_CLI_khong_nhan():
    """B0-01: Makefile từng truyền `--db/--report-dir` mà `cli release` không
    nhận → exit 2. Lệnh release trong tài liệu bàn giao không chạy được."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    cli = (ROOT / "src" / "data_pipeline" / "cli.py").read_text(encoding="utf-8")
    i = mk.index("dp-release:")
    block = mk[i:mk.index("\n\n", i)]
    for flag in ("--db", "--out", "--report-dir", "--bronze", "--quality"):
        if flag in block:
            assert f'"{flag}"' in cli or f"'{flag}'" in cli, \
                f"Makefile truyền {flag} nhưng cli release không khai tham số này"


def test_release_bat_buoc_kiem_ba_artifact_cung_build():
    cli = (ROOT / "src" / "data_pipeline" / "cli.py").read_text(encoding="utf-8")
    assert "_release_inputs_same_build" in cli
    assert "thuộc build" in cli, "phải báo rõ khi --quality khác build với --db"


# ── P1-05 · bỏ hard-code kích thước corpus ────────────────────────────────

def test_KHONG_con_hard_code_1973_trong_control_flow():
    """`n_doc >= 1973` khiến corpus khác kích thước KHÔNG BAO GIỜ publish —
    im lặng, không báo lỗi."""
    import ast
    src = (ROOT / "src" / "data_pipeline" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Chỉ xét HẰNG SỐ trong mã thật; docstring/comment nhắc tới 1973 là tư liệu.
    bad = [n.lineno for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and n.value == 1973]
    assert not bad, f"còn hard-code 1973 ở dòng {bad}"
    assert "_expected_report_count" in src


# ── B0-06 · C0 phải phân biệt core và final ───────────────────────────────

def test_rebuild_check_co_che_do_final_phu_bang_finalize():
    rc = (ROOT / "tools" / "rebuild_check.py").read_text(encoding="utf-8")
    assert "CANONICAL_FINAL" in rc and "CANONICAL_CORE" in rc
    for t in ("quality_issues", "observation_readiness", "source_cells"):
        assert t in rc, f"C0-final phải phủ {t}"
    assert "--mode" in rc


# ── B0-02 / B0-03 · cổng phải chặn bằng exit code ─────────────────────────

def test_gate_report_KHONG_con_luon_tra_0():
    gr = (ROOT / "tools" / "gate_report.py").read_text(encoding="utf-8")
    assert "_exit_code" in gr
    for flag in ("--rebuild-check", "--no-loss", "--differential", "--unresolved"):
        assert flag in gr, f"RC-20 phải đọc {flag}"


def test_differential_KHONG_con_luon_tra_0():
    da = (ROOT / "tools" / "differential_audit.py").read_text(encoding="utf-8")
    assert "blocking_findings" in da and "reason_accounting" in da
    assert 'return 3 if rep["verdict"] == "FAIL" else 0' in da


def test_make_dp_release_PHAI_truyen_du_bronze_va_quality():
    """B0-01 phần còn thiếu: CLI đã có `--bronze/--quality`, nhưng Makefile —
    giao diện mà người review thật sự gõ — vẫn không truyền chúng.

    Không truyền = `--bronze` rơi về `BRONZE_OUT` toàn cục, tức release có thể
    ghép silver.sqlite của build này với catalog.sqlite của build khác. Phép
    kiểm `_release_inputs_same_build` vẫn xanh vì nó chỉ kiểm những gì được
    truyền vào. Một lớp bảo vệ chỉ tồn tại khi đường gọi thật sự đi qua nó.
    """
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    i = mk.index("dp-release:")
    block = mk[i:mk.index("\n\n", i)]
    for flag in ("--db", "--bronze", "--quality", "--out", "--report-dir"):
        assert flag in block, f"dp-release không truyền {flag}"
    for var in ("$(DB)", "$(BRONZE)", "$(QUALITY)", "$(OUTPUT)", "$(REPORT_DIR)"):
        assert var in block, f"dp-release không bắt buộc {var}"
