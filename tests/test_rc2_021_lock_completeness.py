"""RC2-021 · `requirements.lock` phải phủ HẾT thứ mã nguồn thật sự import.

Defect gốc, có thật và đã làm hỏng một lần chạy:

  `html_parser` import `lxml` không điều kiện. `pyproject.toml` chỉ *nhắc*
  `lxml` trong một comment (`parsing = []   # lxml, ...`) chứ không **khai
  báo** nó. `pip-compile` vì thế không đưa `lxml` vào `requirements.lock`, và
  `pip install --no-deps` — đúng ngữ nghĩa: lock là con đường DUY NHẤT để một
  gói vào venv đóng băng — tạo ra một venv thiếu `lxml`.

  `dp-env-check` vẫn báo `lock_matches_installed = True`, vì phép so đó chỉ
  hỏi "pin có khớp bản đang cài không", KHÔNG BAO GIỜ hỏi "mã nguồn import
  những gì". Ba lớp kiểm tra xanh, `make dp-test` chết bằng ModuleNotFoundError.

Bộ test này khoá chiều ngược lại. Nó phải ĐỎ nếu ai đó thêm một import bên
thứ ba mà quên khai báo — kể cả khi máy họ tình cờ đã cài sẵn gói đó.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "check_imports_mod", ROOT / "tools" / "check_imports.py")
ci = importlib.util.module_from_spec(_SPEC)
sys.modules["check_imports_mod"] = ci
_SPEC.loader.exec_module(ci)


# ── 1. hồi quy trực tiếp trên repo thật ───────────────────────────────────

def test_lock_co_lxml_vi_html_parser_import_no_khong_dieu_kien():
    """Đây là con số cụ thể đã làm chết `make dp-test`. Nếu ai gỡ `lxml` khỏi
    `pyproject.toml`/lock, test này phải đỏ TRƯỚC khi build chạy."""
    pins = ci._lock_pins(ROOT / "requirements.lock")
    assert "lxml" in pins, (
        "requirements.lock KHÔNG có lxml — nhưng src/ import nó không điều kiện")


def test_repo_that_khong_con_import_nao_ngoai_lock():
    """Điều kiện thoát của RC2-021, đo trên chính cây nguồn đang có."""
    rep = ci.check(ROOT, ["src", "@contract"])
    assert rep["unpinned_required"] == [], rep["unpinned_required"]
    assert rep["unpinned_optional"] == [], rep["unpinned_optional"]
    assert rep["verdict"] == "PASS"


def test_cong_cu_tren_duong_chay_duoc_lay_TU_HOP_DONG_khong_go_tay():
    """`@contract` phải đọc Makefile + execution_sequence, không phải danh
    sách cứng — nếu không, nó lệch ngay lần đầu ai thêm một bước."""
    tools = {p.name for p in ci.contract_tools(ROOT)}
    for must in ("env_check.py", "build_runner.py", "run_tests.py",
                 "no_loss_check.py", "replay_report.py", "gate_report.py"):
        assert must in tools, f"{must} không được `@contract` nhặt ra"


# ── 2. AST, không regex ───────────────────────────────────────────────────

def test_import_trong_docstring_hoac_chuoi_KHONG_duoc_tinh(tmp_path):
    f = tmp_path / "m.py"
    f.write_text('"""Ví dụ: import lxml rồi from bs4 import x."""\n'
                 'S = "import requests"\n', encoding="utf-8")
    assert ci._scan_one(f) == {}


def test_import_trong_than_ham_VAN_duoc_tinh(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def g():\n    from lxml import etree\n    return etree\n",
                 encoding="utf-8")
    got = ci._scan_one(f)
    assert "lxml" in got and got["lxml"]["required"] is True


def test_import_tuong_doi_la_noi_bo_khong_phai_ben_thu_ba(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("from . import sibling\nfrom .pkg import thing\n", encoding="utf-8")
    assert ci._scan_one(f) == {}


# ── 3. loại trừ đúng chỗ ──────────────────────────────────────────────────

def test_stdlib_bi_loai(tmp_path):
    (tmp_path / "m.py").write_text("import json, sqlite3, hashlib\n", encoding="utf-8")
    assert ci._scan_paths([tmp_path / "m.py"], ROOT) == {}


def test_module_cua_chinh_repo_bi_loai_khong_bao_dong_gia():
    """`release.py` có `from make_preview import ...`, và `make_preview.py`
    nằm ở `tools/`. Coi nó là gói bên thứ ba là báo động giả — và báo động giả
    là thứ giết một công cụ kiểm tra nhanh nhất."""
    first = ci._first_party(ROOT)
    assert "make_preview" in first
    assert "data_pipeline" in first


# ── 4. ánh xạ module → tên phân phối ──────────────────────────────────────

@pytest.mark.parametrize("mod,dist", [
    ("yaml", "pyyaml"), ("bs4", "beautifulsoup4"), ("sklearn", "scikit-learn"),
    ("dateutil", "python-dateutil"),
])
def test_ten_module_khac_ten_phan_phoi(mod, dist):
    assert ci.module_to_dist(mod) == dist


# ── 5. phán quyết và exit code ────────────────────────────────────────────

def _repo(tmp_path: Path, code: str, lock: str) -> Path:
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "mod.py").write_text(code, encoding="utf-8")
    (tmp_path / "requirements.lock").write_text(lock, encoding="utf-8")
    return tmp_path


def test_import_tran_khong_co_trong_lock_thi_FAIL_va_la_BAT_BUOC(tmp_path):
    r = _repo(tmp_path, "import lxml.etree\n", "pandas==2.3.3\n")
    rep = ci.check(r, ["src"])
    assert rep["verdict"] == "FAIL"
    assert rep["unpinned_required"] == ["lxml"]


def test_import_co_try_except_VAN_FAIL_chu_khong_im_lang(tmp_path):
    """Có `try/except ImportError` nghĩa là build không chết — nhưng nó rụng
    tính năng trong im lặng, và một release im lặng thiếu tính năng còn khó
    phát hiện hơn một build chết. Vẫn phải khai báo hoặc allowlist tường minh.
    """
    r = _repo(tmp_path, "try:\n    import lxml\nexcept ImportError:\n    lxml = None\n",
              "pandas==2.3.3\n")
    rep = ci.check(r, ["src"])
    assert rep["verdict"] == "FAIL"
    assert rep["unpinned_required"] == []
    assert rep["unpinned_optional"] == ["lxml"]


def test_allowlist_phai_tuong_minh_moi_bo_qua_duoc(tmp_path):
    r = _repo(tmp_path, "import lxml\n", "pandas==2.3.3\n")
    assert ci.check(r, ["src"])["verdict"] == "FAIL"
    assert ci.check(r, ["src"], allow=("lxml",))["verdict"] == "PASS"


def test_co_trong_lock_thi_PASS(tmp_path):
    r = _repo(tmp_path, "import lxml\nimport yaml\n",
              "lxml==6.1.1\nPyYAML==6.0.3\n")
    rep = ci.check(r, ["src"])
    assert rep["verdict"] == "PASS"
    assert {m["module"] for m in rep["modules"]} == {"lxml", "yaml"}


def test_exit_code_3_khi_thieu_pin(tmp_path, capsys):
    r = _repo(tmp_path, "import lxml\n", "pandas==2.3.3\n")
    assert ci.main(["--root", str(r), "--scan", "src"]) == 3


def test_exit_code_0_khi_du_pin(tmp_path):
    r = _repo(tmp_path, "import lxml\n", "lxml==6.1.1\n")
    assert ci.main(["--root", str(r), "--scan", "src"]) == 0
