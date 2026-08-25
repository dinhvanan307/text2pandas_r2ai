"""P3 · `freeze_input` phải ĐO ĐƯỢC, không phải một dòng tiêu chí không có dụng cụ.

`configs/execution_sequence_v1.yaml` đòi bước `freeze_input` thoả:

    corpus_content_hash ổn định giữa hai lần đọc
    uid_namespace_id đúng hằng số đóng băng (AMD-04)

Trước `tools/corpus_freeze_check.py`, không công cụ nào đo được hai điều đó
TRƯỚC build. `dp-env-check` chỉ băm (đường dẫn, kích thước) — nó bắt tệp
thêm/mất nhưng **không bắt được một tệp bị sửa mà giữ nguyên kích thước**, và
đúng loại thay đổi đó mới là thứ làm lệch mọi observation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "corpus_freeze_mod", ROOT / "tools" / "corpus_freeze_check.py")
cfc = importlib.util.module_from_spec(_SPEC)
sys.modules["corpus_freeze_mod"] = cfc
_SPEC.loader.exec_module(cfc)

NS = "sha256:ca033190f2e9e99f8384bf59749484b0668c573e0a84e02a055d173d99de0cb9"


def _tree(tmp: Path, docs: dict[str, bytes]) -> Path:
    root = tmp / "corpus"
    for name, data in docs.items():
        p = root / "financial_statements" / name[:3] / f"{name}_extracted.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def _baseline(tmp: Path, root: Path) -> Path:
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            files.append({"rel_path": p.relative_to(root).as_posix(),
                          "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    b = tmp / "baseline.json"
    b.write_text(json.dumps({"corpus_id": NS, "files": files}), encoding="utf-8")
    return b


def _cfg(tmp: Path, ns: str = NS) -> Path:
    c = tmp / "cfg.yaml"
    c.write_text(f'corpus:\n  uid_namespace_id: "{ns}"\n', encoding="utf-8")
    return c


def _run(tmp, root, base, cfg):
    out = tmp / "rep.json"
    rc = cfc.main(["--root", str(root), "--baseline", str(base),
                   "--config", str(cfg), "--out", str(out)])
    return rc, json.loads(out.read_text(encoding="utf-8"))


def test_corpus_khong_doi_thi_PASS(tmp_path):
    root = _tree(tmp_path, {"AAA": b"x\n", "BBB": b"yy\n"})
    rc, rep = _run(tmp_path, root, _baseline(tmp_path, root), _cfg(tmp_path))
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["measured"]["n_content_files"] == 2
    assert rep["measured"]["uid_namespace_id"] == NS


def test_sua_noi_dung_MA_GIU_NGUYEN_kich_thuoc_van_bi_bat(tmp_path):
    """Đây là ca mà `dp-env-check` không thể bắt: nó chỉ băm (path, size)."""
    root = _tree(tmp_path, {"AAA": b"x\n", "BBB": b"yy\n"})
    base = _baseline(tmp_path, root)
    (root / "financial_statements" / "AAA" / "AAA_extracted.txt").write_bytes(b"z\n")
    rc, rep = _run(tmp_path, root, base, _cfg(tmp_path))
    assert rc == 3 and rep["verdict"] == "FAIL"
    assert rep["diff_vs_baseline"]["n_changed"] == 1
    assert any("corpus_content_hash lech" in f for f in rep["findings"])


def test_them_tep_bao_cao_thi_FAIL(tmp_path):
    root = _tree(tmp_path, {"AAA": b"x\n"})
    base = _baseline(tmp_path, root)
    _tree(tmp_path, {"CCC": b"new\n"})
    rc, rep = _run(tmp_path, root, base, _cfg(tmp_path))
    assert rc == 3 and rep["diff_vs_baseline"]["n_added"] == 1


def test_mat_tep_bao_cao_thi_FAIL(tmp_path):
    root = _tree(tmp_path, {"AAA": b"x\n", "BBB": b"yy\n"})
    base = _baseline(tmp_path, root)
    (root / "financial_statements" / "BBB" / "BBB_extracted.txt").unlink()
    rc, rep = _run(tmp_path, root, base, _cfg(tmp_path))
    assert rc == 3 and rep["diff_vs_baseline"]["n_removed"] == 1


def test_doi_uid_namespace_trong_config_thi_FAIL(tmp_path):
    """Đổi hạt giống UID = đổi MỌI observation_uid. Không được im lặng."""
    root = _tree(tmp_path, {"AAA": b"x\n"})
    rc, rep = _run(tmp_path, root, _baseline(tmp_path, root),
                   _cfg(tmp_path, "sha256:deadbeef"))
    assert rc == 3
    assert any("uid_namespace_id" in f for f in rep["findings"])


def test_thieu_moc_thi_NOT_VERIFIED_chu_khong_phai_PASS(tmp_path):
    """Không có mốc = chưa đo được. Trả PASS ở đây là nói dối."""
    root = _tree(tmp_path, {"AAA": b"x\n"})
    rc, rep = _run(tmp_path, root, tmp_path / "khong-co.json", _cfg(tmp_path))
    assert rep["verdict"] == "NOT_VERIFIED" and rc == 3


def test_dung_CHINH_data_pipeline_manifest_khong_cai_lai_thuat_toan():
    src = (ROOT / "tools" / "corpus_freeze_check.py").read_text(encoding="utf-8")
    assert "from text2pandas.pipelines.a6.manifest import" in src
    assert "build_manifest" in src and "compute_corpus_id" in src


def test_corpus_that_neu_co_thi_phai_KHOP_moc_RC1():
    """Acceptance thật của bước freeze_input. Bỏ qua nếu corpus không có
    trong cây này (gói source không mang 380 MB corpus)."""
    root = ROOT / "data" / "raw" / "btc"
    base = ROOT / "data" / "bronze" / "manifest.json"
    if not root.is_dir() or not base.is_file():
        pytest.skip("MISSING ARTIFACT: corpus/manifest mốc không có trong cây này")
    assert cfc.main(["--root", str(root), "--baseline", str(base),
                     "--config", str(ROOT / "configs" / "vifinqa_silver_v1.yaml")]) == 0


# ── RC2-029 · trùng nội dung phải tách theo quần thể ──────────────────────

def test_trung_noi_dung_tach_bao_cao_khoi_cache(tmp_path):
    """`manifest.n_duplicate_files` đếm trên CẢ CÂY. Trên corpus thật nó là
    **1.977 tệp dư / 3 nhóm** — nhưng 1.975 trong số đó là một nhóm duy nhất
    gồm 1.976 tệp `.cache/huggingface/**` giống hệt nhau. Sự thật về corpus là
    **2 tệp dư / 2 nhóm**.

    Một con số trông như đã đo nhưng mô tả sai quần thể thì nguy hiểm hơn
    không đo gì: người đọc sẽ tin nó.
    """
    root = _tree(tmp_path, {"AAA": b"same\n", "BBB": b"same\n", "CCC": b"khac\n"})
    cache = root / "cache_like"
    cache.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (cache / f"lock{i}.metadata").write_bytes(b"")
    rc, rep = _run(tmp_path, root, _baseline(tmp_path, root), _cfg(tmp_path))
    assert rc == 0
    d = rep["duplicates"]
    assert d["content_reports"]["n_groups"] == 1
    assert d["content_reports"]["n_redundant_files"] == 1
    assert d["non_content"]["n_redundant_files"] == 4
    assert rep["measured"]["n_duplicate_files"] == 5
