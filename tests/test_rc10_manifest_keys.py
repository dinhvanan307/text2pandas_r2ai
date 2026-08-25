"""RC-10 · manifest phải khai đủ — và nói KHÔNG BIẾT khi không biết.

`manifest_contract` liệt kê 17 khoá bắt buộc; RC1 thiếu **bảy**:

    acceptance_status · source_commit · source_hash · config_hash
    readiness_policy_version · defect_taxonomy_version · allowed_blocked_gates

`source_commit` là mục đáng nói nhất. RC1 không phải ghi SAI nó — RC1 **chưa
bao giờ có** trường đó. Điều tra ban đầu ở RC-01 nhầm
`manifest.revision = 0450088ab22ec946…` là git commit đã mất; đo lại thì đó là
revision DATASET trên HuggingFace (`cli.py:33-34`), nên `git cat-file` thất
bại là đúng thiết kế chứ không phải một phát hiện.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.a6.release import (  # noqa: E402
    ALLOWED_BLOCKED_GATES, _source_commit, _taxonomy_version)

CONTRACT = ROOT / "configs" / "rc2_contracts_v1.yaml"
RELEASE_PY = ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "release.py"


@pytest.fixture(scope="module")
def contract():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["manifest_contract"]


# A6 · hai bài dưới đây TỪNG đọc mã nguồn: cắt thân `_md_manifest` ra rồi tìm
# chuỗi `"ten_khoa"` trong đó. Chúng đỏ ngay khi năm khoá định danh được gom
# vào `_identity_from_build_meta()` — dù manifest sinh ra vẫn đủ khoá. Đó là
# dấu hiệu bài test đang kiểm CÁCH VIẾT chứ không kiểm HÀNH VI: một khoá nằm
# trong mã mà không bao giờ được ghi ra vẫn qua được bản cũ.
#
# Bản này dựng manifest THẬT rồi soi khoá trong KẾT QUẢ. Chặt hơn theo cả hai
# chiều, và không vỡ khi ai đó tái cấu trúc.

def _manifest_that(tmp: Path) -> dict:
    """Gọi `_md_manifest` trên một release tối thiểu nhưng thật."""
    import sqlite3

    from text2pandas.pipelines.a6.release import ReleaseReport, _md_manifest

    out = tmp / "rel"
    out.mkdir(parents=True, exist_ok=True)
    (out / "README.md").write_text("x", encoding="utf-8")
    c = sqlite3.connect(out / "silver.db")
    c.execute("CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT)")
    c.executemany("INSERT INTO build_meta VALUES (?,?)", [
        ("build_id", "b" * 16), ("source_hash", "s" * 16),
        ("config_hash", "c" * 16), ("source_commit", "d" * 40),
        ("readiness_policy_version", "9.9")])
    c.commit(); c.close()
    rep = ReleaseReport(out_dir=out, profile="test", build_id="b" * 16,
                        counts={"t": 0}, files={},
                        quality={"gates": {}})
    return _md_manifest(rep, out, {"corpus_id": "sha256:x", "corpus_hash": "sha256:x"})


def test_moi_khoa_BAT_BUOC_deu_duoc_sinh(contract, tmp_path):
    m = _manifest_that(tmp_path)
    missing = [k for k in contract["required_keys"] if k not in m]
    assert not missing, f"manifest thiếu khoá bắt buộc: {missing}"


def test_bay_khoa_RC1_thieu_nay_da_co(contract, tmp_path):
    m = _manifest_that(tmp_path)
    still = [k for k in contract["rc1_missing_keys"] if k not in m]
    assert not still, f"vẫn thiếu: {still}"


def test_khoa_dinh_danh_khong_duoc_RONG(contract, tmp_path):
    """RC2-050 · đủ khoá mà rỗng giá trị thì cũng như thiếu."""
    m = _manifest_that(tmp_path)
    rong = [k for k in ("build_id", "source_hash", "config_hash",
                        "source_commit", "readiness_policy_version")
            if m.get(k) in (None, "")]
    assert not rong, f"trường định danh rỗng: {rong}"


def test_readiness_policy_version_lay_tu_build_meta(tmp_path):
    """Vân tay của lỗi gói 5ade9ae9d5f68b6a, kiểm ở tầng manifest hoàn chỉnh."""
    assert _manifest_that(tmp_path)["readiness_policy_version"] == "9.9"


def test_allowed_blocked_gates_khop_hop_dong(contract):
    assert list(ALLOWED_BLOCKED_GATES) == contract["allowed_blocked_gates"]


# ── source_commit · ba trạng thái ──────────────────────────────────────────

def test_source_commit_KHONG_BAO_GIO_tra_chuoi_rong():
    """Chuỗi rỗng bị đọc thành "đã ghi". Mỗi trạng thái phải tự nói nó là gì."""
    v = _source_commit()
    assert v and v.strip()
    assert v.startswith("unavailable:") or len(v.split("-")[0]) == 40


def test_cay_ban_phai_duoc_danh_dau():
    """Gói dựng từ cây bẩn KHÔNG tương ứng commit nào.

    Ghi sha của commit gần nhất rồi im lặng là mời người sau tin rằng gói tái
    lập được từ commit đó.
    """
    src = RELEASE_PY.read_text(encoding="utf-8")
    assert '"-dirty"' in src or "-dirty" in src
    assert "status" in src[src.index("def _source_commit"):
                           src.index("def _md_manifest")]


def test_taxonomy_version_doc_duoc_hoac_noi_ro_khong_doc_duoc():
    v = _taxonomy_version()
    assert v.startswith("unavailable:") or v[0].isdigit()


# ── revision KHÔNG được nhầm là commit nữa ─────────────────────────────────

def test_revision_khai_ro_no_la_revision_DATASET():
    """Chống hồi quy cho một hiểu nhầm đã tốn cả một vòng điều tra."""
    src = RELEASE_PY.read_text(encoding="utf-8")
    body = src[src.index("def _md_manifest"):src.index("def _md_dictionary")]
    assert '"revision_kind"' in body
    assert "huggingface_dataset_revision" in body


def test_acceptance_status_khong_duoc_lac_quan():
    """`acceptance_status` không được lạc quan hơn cổng đã chạy.

    C3 · Doc 56 P0-05 · bản trước suy trạng thái ngay tại chỗ ghi manifest, và
    test này kiểm bằng cách GREP đoạn mã đó. Hai vấn đề: grep source vỡ ngay
    khi biểu thức được tách thành hàm, và quan trọng hơn — phép suy tại chỗ
    đóng gói chính là thứ đã tạo ra mâu thuẫn `not_accepted` trong manifest
    đối lại `retrieval-baseline-ready` trong tài liệu bàn giao.

    Nay trạng thái lấy từ RC-20 thật, nên test đo HÀNH VI thay vì đo văn bản.
    """
    import sys
    sys.path.insert(0, str(RELEASE_PY.parents[2]))
    from text2pandas.pipelines.a6.release import ReleaseReport, _acceptance_status

    r = ReleaseReport(out_dir=None, profile="slim")
    assert _acceptance_status(r) == "not_accepted_no_gate_report", (
        "không có cổng mà vẫn dám nói gì đó tích cực")

    r.gate_summary_from_rc20 = {"release_label": "blocked", "exit_code": "0"}
    assert _acceptance_status(r) == "not_accepted"

    r.gate_summary_from_rc20 = {"release_label": "silver-v1.0.0-rc2",
                                "exit_code": "3"}
    assert _acceptance_status(r) == "not_accepted", (
        "gate_report nói đẹp nhưng command exit 3 — không phải cổng đã đạt")

    r.gate_summary_from_rc20 = {"release_label": "silver-v1.0.0-rc2",
                                "exit_code": "0"}
    assert _acceptance_status(r) == "retrieval_baseline_ready"
