"""RC2-022 · `publish` là bước BẮT BUỘC, và release phải từ chối manifest corpus.

Defect: `snapshot` ghi manifest **corpus** vào gốc OUTPUT; `publish` ghi manifest
**bản dựng** vào `<silver_dir>/<build_id>/`. Hai tài liệu khác nhau, **cùng một
tên tệp** `manifest.json`.

`dp-build --finalize` trước đây dừng ở stage `quality`, nên OUTPUT chỉ có
manifest corpus. Gọi `release --db <OUT>/silver.sqlite` khi đó:

    src_manifest = json.load(<OUT>/manifest.json)      # manifest CORPUS
    rep.build_id = src_manifest.get("build_id", "unknown")   # -> "unknown"

Gói phát hành mang `build_id: "unknown"`, `source_hash: null`,
`component_versions: {}` — và **không có một dòng lỗi nào**. Đó là kiểu hỏng
đắt nhất: sai im lặng ở artifact cuối cùng, sau khi mọi cổng đã xanh.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from text2pandas.pipelines.a6 import cli  # noqa: E402


# ── 1. `--finalize` phải chạy tới publish ─────────────────────────────────

def test_finalize_chay_ca_quality_va_publish():
    src = (ROOT / "tools" / "build_runner.py").read_text(encoding="utf-8")
    assert 'stages += ["quality", "publish"]' in src, (
        "--finalize dừng ở `quality` thì OUTPUT không có manifest bản dựng")


def test_stage_publish_ton_tai_trong_cli():
    """Nếu `publish` không phải subcommand thì build_runner gọi nó sẽ chết."""
    src = (ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "cli.py").read_text(encoding="utf-8")
    assert '"publish": cmd_publish' in src


# ── 2. hợp đồng thứ tự phải khai bước này ─────────────────────────────────

def test_execution_sequence_co_buoc_publish():
    seq = yaml.safe_load(
        (ROOT / "configs" / "execution_sequence_v1.yaml").read_text(encoding="utf-8"))
    steps = {s["id"]: s for s in seq["steps"]}
    assert "publish" in steps, "thứ tự thực thi không khai bước publish"
    assert {"build_a", "build_b"} <= set(steps["publish"]["must_follow"])
    assert "publish" in steps["release"]["must_follow"], (
        "release có thể chạy trước publish → đọc phải manifest corpus")


# ── 3. phân biệt manifest corpus và manifest bản dựng ─────────────────────

def _corpus_manifest(p: Path):
    p.write_text(json.dumps({
        "corpus_id": "sha256:ca0331", "dataset": "AIGuruTinix/ViFinQA",
        "n_files": 5931, "n_reports": 1973,
        "files": [{"rel_path": "a.txt", "bytes": 1, "sha256": "aa"}],
    }), encoding="utf-8")


def _build_manifest(p: Path, bid: str = "abc123"):
    p.write_text(json.dumps({
        "build_id": bid, "corpus_id": "sha256:ca0331", "revision": "045008",
        "counts": {"observations": 1}, "silver_sha256": "ff",
        "blocked_gates": [],
    }), encoding="utf-8")


def test_manifest_corpus_bi_TU_CHOI_va_noi_ro_ly_do(tmp_path):
    m = tmp_path / "manifest.json"
    _corpus_manifest(m)
    ok, why = cli._is_build_manifest(m, "abc123")
    assert ok is False
    assert "CORPUS" in why and "publish" in why, why


def test_manifest_thieu_thi_TU_CHOI(tmp_path):
    ok, why = cli._is_build_manifest(tmp_path / "khong-co.json", "abc123")
    assert ok is False and "khong thay" in why


def test_manifest_khac_build_id_thi_TU_CHOI(tmp_path):
    m = tmp_path / "manifest.json"
    _build_manifest(m, "KHAC")
    ok, why = cli._is_build_manifest(m, "abc123")
    assert ok is False and "KHAC" in why and "abc123" in why


def test_manifest_ban_dung_dung_build_id_thi_CHAP_NHAN(tmp_path):
    m = tmp_path / "manifest.json"
    _build_manifest(m, "abc123")
    assert cli._is_build_manifest(m, "abc123") == (True, "")


def test_khong_kiem_duoc_build_id_thi_van_doi_manifest_ban_dung(tmp_path):
    """`--db` không đọc được build_id (DB hỏng) → vẫn phải có manifest bản dựng.
    Không suy diễn ngược thành "chắc là khớp"."""
    m = tmp_path / "manifest.json"
    _corpus_manifest(m)
    assert cli._is_build_manifest(m, None)[0] is False


# ── 4. đường gọi thật: _do_release phải dừng, không phát hành ─────────────

def _db(p: Path, bid: str = "abc123") -> Path:
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT INTO build_meta VALUES('build_id',?)", (bid,))
    c.commit(); c.close()
    return p


def test_do_release_tra_2_khi_canh_DB_la_manifest_corpus(tmp_path, capsys):
    out = tmp_path / "build"; out.mkdir()
    db = _db(out / "silver.sqlite")
    _corpus_manifest(out / "manifest.json")
    bronze = out / "catalog.sqlite"; bronze.write_bytes(b"x")
    args = SimpleNamespace(db=str(db), bronze=str(bronze), quality=None,
                           out=str(tmp_path / "rel"), profile="slim",
                           per_table="primary")
    assert cli._do_release(args, out) == 2
    err = capsys.readouterr().err
    assert "CORPUS" in err and "publish" in err
    assert not (tmp_path / "rel").exists(), "đã dừng thì KHÔNG được tạo thư mục phát hành"


def test_release_khong_duoc_de_build_id_unknown_di_qua():
    """`build_release` có mặc định `"unknown"`; nó chỉ an toàn khi có chốt chặn
    đứng TRƯỚC. Test này khoá cả hai vế lại với nhau."""
    rel = (ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "release.py").read_text(encoding="utf-8")
    assert 'src_manifest.get("build_id", "unknown")' in rel
    cl = (ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "cli.py").read_text(encoding="utf-8")
    i_guard = cl.index("_is_build_manifest(manifest")
    assert i_guard < cl.index("build_release(src_silver=db"), \
        "chốt chặn phải đứng TRƯỚC lời gọi build_release"


def test_make_dp_build_truyen_duoc_finalize():
    """Không có đường truyền `--finalize` qua `make` thì bước duy nhất sinh
    manifest bản dựng chỉ chạy được khi gọi thẳng `build_runner.py` — tức
    giao diện hợp đồng không dựng nổi một candidate hợp lệ."""
    mk = (ROOT / "Makefile").read_text(encoding="utf-8")
    i = mk.index("dp-build:")
    block = mk[i:mk.index("\n\n", i)]
    assert "--finalize" in block and "$(FINALIZE)" in block


# ── RC2-034 · "cây có bẩn không" phải là MỘT phép đo ──────────────────────

def test_build_runner_dung_cung_phep_phan_loai_dirty_voi_env_check():
    """Bản đầu ghi `bool(git status --porcelain)`, nên MỘT tệp `docs/*.md` bị
    sửa sau commit cũng bật `source_tree_dirty: true`.

    Đo được trên bản dựng thật `4c86c9e43915694a`: nó ghi dirty=true trong khi
    cây nguồn sinh ra nó khớp CHÍNH XÁC commit `22c26b2` — `source_hash` chỉ băm
    `src/text2pandas/pipelines/a6/*.py`, `config_hash` chỉ băm `configs/*.yaml`, nên một
    tài liệu không thể ảnh hưởng tới bản dựng. Người review đọc
    `build_invocation.json` sẽ mất niềm tin vào một bản dựng hoàn toàn sạch, vì
    một dòng tài liệu.
    """
    src = (ROOT / "tools" / "build_runner.py").read_text(encoding="utf-8")
    assert "bool(_sh(\"git\", \"status\", \"--porcelain\"))" not in src, (
        "vẫn dùng phép thô — bất kỳ dòng nào cũng thành dirty")
    assert "_classify_dirty" in src, "phải gọi lại bộ phân loại của env_check"
    assert "untracked_in_source_paths" in src


def test_build_runner_khong_viet_lai_bo_phan_loai_thu_hai():
    """Hai phép đo cho cùng một câu hỏi là cách một sai lệch sống sót."""
    src = (ROOT / "tools" / "build_runner.py").read_text(encoding="utf-8")
    assert "env_check.py" in src, "phải nạp env_check, không tự cài lại"
    assert "SOURCE_PATHS = (" not in src, "đang cài lại bảng đường dẫn nguồn"
