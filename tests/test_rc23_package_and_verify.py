"""RC-23/RC-24 · đóng gói tất định và verify từ bản giải nén SẠCH.

Nhóm này bị `required_suites.json` báo `MISSING_REQUIRED_SUITE` ở lần chạy
trước: hai công cụ tồn tại và smoke run dùng được, nhưng **không unit test
nào** chạm tới chúng. Một công cụ chỉ được smoke chứng minh là một công cụ
chưa có lưới an toàn khi ai đó sửa nó.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tools" / "package_release.py"
VERIFY = ROOT / "tools" / "verify_package.py"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _run(args, cwd=None):
    return subprocess.run([sys.executable, *[str(a) for a in args]],
                          capture_output=True, text=True, cwd=cwd or ROOT,
                          timeout=120)


@pytest.fixture
def rel(tmp_path):
    d = tmp_path / "release"
    (d / "logs").mkdir(parents=True)
    (d / "silver.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    (d / "manifest.json").write_text('{"package":"x"}', encoding="utf-8")
    (d / "README.md").write_text("readme", encoding="utf-8")
    (d / "logs" / "build.log").write_text("log", encoding="utf-8")
    return d


# ── RC-23 · tất định ───────────────────────────────────────────────────────

def test_dong_goi_HAI_LAN_cho_cung_sha256(rel, tmp_path):
    z1, z2 = tmp_path / "a.zip", tmp_path / "b.zip"
    assert _run([PACKAGE, "--dir", rel, "--out", z1]).returncode == 0
    assert _run([PACKAGE, "--dir", rel, "--out", z2]).returncode == 0
    assert _sha(z1) == _sha(z2), "zip không tất định"


def test_timestamp_trong_zip_la_CO_DINH(rel, tmp_path):
    """mtime của tệp nguồn KHÔNG được rò vào gói — nếu rò thì hash đổi mỗi lần."""
    z = tmp_path / "a.zip"
    _run([PACKAGE, "--dir", rel, "--out", z])
    with zipfile.ZipFile(z) as zf:
        dates = {i.date_time for i in zf.infolist()}
    assert dates == {(1980, 1, 1, 0, 0, 0)}, dates


def test_entry_da_SAP_XEP(rel, tmp_path):
    z = tmp_path / "a.zip"
    _run([PACKAGE, "--dir", rel, "--out", z])
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
    assert names == sorted(names)


def test_LOAI_rac_cua_macOS_va_NOI_RA(rel, tmp_path):
    """Hành vi thật là LOẠI, không phải TỪ CHỐI — và tôi đã mô tả sai ở doc 37.

    Loại là đúng: một `.DS_Store` do Finder sinh không đáng làm hỏng cả lần
    đóng gói. Nhưng loại IM LẶNG thì gói khác với thư mục người vận hành vừa
    xem mà không có dòng nào cho biết.
    """
    (rel / ".DS_Store").write_text("x", encoding="utf-8")
    z = tmp_path / "a.zip"
    r = _run([PACKAGE, "--dir", rel, "--out", z])
    assert r.returncode == 0
    assert "DS_Store" in (r.stdout + r.stderr), "loại mà không nói ra"
    with zipfile.ZipFile(z) as zf:
        assert not any(".DS_Store" in n for n in zf.namelist())


def test_TU_CHOI_symlink(rel, tmp_path):
    (rel / "link.db").symlink_to(rel / "silver.db")
    r = _run([PACKAGE, "--dir", rel, "--out", tmp_path / "a.zip"])
    assert r.returncode != 0


# ── RC-24 · verify từ bản giải nén sạch ────────────────────────────────────

def test_verify_NHAN_ZIP_khong_nhan_thu_muc(rel, tmp_path):
    """Verify thẳng thư mục vừa build là kiểm MỘT THỨ KHÁC với thứ sẽ gửi đi."""
    r = _run([VERIFY, "--package", rel, "--type", "release"])
    assert r.returncode != 0


def test_verify_bat_thieu_SHA256SUMS(rel, tmp_path):
    """Lỗi thật: trước RC-21 không bước nào sinh SHA256SUMS, nên MỌI gói fail."""
    z = tmp_path / "a.zip"
    _run([PACKAGE, "--dir", rel, "--out", z])
    r = _run([VERIFY, "--package", z, "--type", "release"])
    assert "SHA256SUMS" in (r.stdout + r.stderr)


def test_verify_bat_checksum_sai(rel, tmp_path):
    lines = []
    for f in sorted(rel.rglob("*")):
        if f.is_file():
            lines.append(f"{'0' * 64}  {f.relative_to(rel).as_posix()}")
    (rel / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    z = tmp_path / "a.zip"
    _run([PACKAGE, "--dir", rel, "--out", z])
    r = _run([VERIFY, "--package", z, "--type", "release"])
    assert r.returncode != 0, "checksum sai mà verify vẫn PASS"


# ── RC2-049 · verify phải kiểm PHỦ, không chỉ kiểm DÒNG ────────────────────
#
# Lỗi thật đã lọt: `release.py` loại chỉ mục theo BASENAME, nên tám tệp
# `acceptance/*/SHA256SUMS` gieo vào release không có dòng checksum nào —
# và verify in PASS hai lần. Nhóm test này khoá lại cả ba chiều
# đĩa ↔ SHA256SUMS ↔ manifest.files.

import json as _json
import sqlite3 as _sqlite3

_REQUIRED_MANIFEST_KEYS = {
    "release_label": "silver_v1_rc2_test", "acceptance_status": "PASS",
    "build_id": "0" * 16, "source_commit": "deadbeef", "source_hash": "1" * 16,
    "config_hash": "2" * 16, "corpus_hash": "3" * 16, "schema_version": "1.0",
    "component_versions": {}, "readiness_policy_version": "1.0",
    "defect_taxonomy_version": "1.0", "gate_summary": {},
    "blocking_failures": [], "allowed_blocked_gates": ["SG"],
}


def _reindex(rel: Path, drop_from_sums=(), drop_from_manifest=(),
             manifest_patch=None):
    """Ghi manifest.json rồi SHA256SUMS đúng thứ tự production.

    `manifest_patch` áp TRƯỚC khi ghi. Vá manifest rồi mới gọi `_reindex` là
    vá xong bị ghi đè — chính lỗi đã làm hai test RC2-050 đỏ ở lần chạy đầu.
    """
    files = {}
    for f in sorted(rel.rglob("*")):
        if not f.is_file():
            continue
        r = f.relative_to(rel).as_posix()
        if r in ("manifest.json", "SHA256SUMS") or r in drop_from_manifest:
            continue
        files[r] = {"bytes": f.stat().st_size, "digest": _sha(f),
                    "digest_mode": "sha256"}
    man = dict(_REQUIRED_MANIFEST_KEYS)
    man["files"] = files
    man["n_files"] = len(files)
    man["counts"] = {"t": 2}
    if manifest_patch:
        man.update(manifest_patch)
    (rel / "manifest.json").write_text(_json.dumps(man), encoding="utf-8")

    lines = []
    for f in sorted(rel.rglob("*")):
        if not f.is_file():
            continue
        r = f.relative_to(rel).as_posix()
        if r == "SHA256SUMS" or r in drop_from_sums:
            continue
        lines.append(f"{_sha(f)}  {r}")
    (rel / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def relfull(tmp_path):
    """Một release tối thiểu nhưng HỢP LỆ: db thật, hai chỉ mục đầy đủ."""
    d = tmp_path / "release"
    (d / "acceptance" / "c0").mkdir(parents=True)
    c = _sqlite3.connect(d / "silver.db")
    c.execute("CREATE TABLE t(x INTEGER)")
    c.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    # A6 · release THẬT luôn có `build_meta`; fixture thiếu nó thì nhóm test
    # này không đại diện cho thứ nó đang kiểm. Giá trị lấy ĐÚNG từ manifest
    # để hai nguồn nói cùng một điều — đó là trạng thái hợp lệ.
    c.execute("CREATE TABLE build_meta(key TEXT PRIMARY KEY, value TEXT)")
    c.executemany("INSERT INTO build_meta VALUES (?,?)",
                  [(k, str(_REQUIRED_MANIFEST_KEYS[k])) for k in
                   ("build_id", "source_hash", "config_hash", "schema_version",
                    "readiness_policy_version", "release_label")])
    c.commit(); c.close()
    (d / "README.md").write_text("readme", encoding="utf-8")
    (d / "acceptance" / "c0" / "exit_code.txt").write_text("0\n", encoding="utf-8")
    (d / "acceptance" / "c0" / "SHA256SUMS").write_text(
        "0" * 64 + "  exit_code.txt\n", encoding="utf-8")
    _reindex(d)
    return d


def _zip_and_verify(rel, tmp_path, name="p.zip", report=None):
    z = tmp_path / name
    assert _run([PACKAGE, "--dir", rel, "--out", z]).returncode == 0
    args = [VERIFY, "--package", z, "--type", "release"]
    if report:
        args += ["--report", report]
    return _run(args)


def test_release_hop_le_thi_PASS(relfull, tmp_path):
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_tep_KHONG_CO_trong_ca_hai_chi_muc_thi_FAIL(relfull, tmp_path):
    """Đây chính là lớp lỗi đã lọt: tệp trong gói, không chỉ mục nào phủ."""
    _reindex(relfull,
             drop_from_sums=("acceptance/c0/SHA256SUMS",),
             drop_from_manifest=("acceptance/c0/SHA256SUMS",))
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0, "tệp không được phủ mà verify vẫn PASS"
    assert "missing checksum" in (r.stdout + r.stderr)


def test_tep_chi_co_trong_MANIFEST_phai_FAIL(relfull, tmp_path):
    """C4 · Doc 56 P1-05 · NÂNG từ cảnh báo lên LỖI.

    Bản trước coi "manifest phủ là đủ" và chỉ in cảnh báo. Hệ quả đo được:
    handoff mô tả 8 tệp trong khi gói đang gửi có 21 — người viết báo cáo nhìn
    một dòng cảnh báo trôi trong log và chép sai. `SHA256SUMS` hứa phủ toàn
    bộ; phủ nhờ chỉ mục khác không phải điều nó hứa.
    """
    _reindex(relfull, drop_from_sums=("acceptance/c0/SHA256SUMS",))
    out = tmp_path / "rep.json"
    r = _zip_and_verify(relfull, tmp_path, report=str(out))
    assert r.returncode != 0, "SHA256SUMS thiếu tệp mà verify vẫn PASS"
    rep = _json.loads(out.read_text(encoding="utf-8"))
    assert rep["missing_checksum"] == 0        # manifest vẫn phủ
    assert rep["covered_by_manifest_only"] == 1
    assert rep["covered_by_manifest_only_files"] == ["acceptance/c0/SHA256SUMS"]


def test_tep_THUA_khong_co_trong_manifest_thi_FAIL(relfull, tmp_path):
    _reindex(relfull)
    (relfull / "la_mat.txt").write_text("x", encoding="utf-8")
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0, "tệp thừa mà verify vẫn PASS"
    assert "unexpected file" in (r.stdout + r.stderr)


def test_manifest_digest_SAI_thi_FAIL(relfull, tmp_path):
    m = _json.loads((relfull / "manifest.json").read_text(encoding="utf-8"))
    m["files"]["README.md"]["digest"] = "f" * 64
    (relfull / "manifest.json").write_text(_json.dumps(m), encoding="utf-8")
    lines = []
    for f in sorted(relfull.rglob("*")):
        if f.is_file() and f.name != "SHA256SUMS" or (
                f.is_file() and f.relative_to(relfull).as_posix() != "SHA256SUMS"):
            r_ = f.relative_to(relfull).as_posix()
            if r_ != "SHA256SUMS":
                lines.append(f"{_sha(f)}  {r_}")
    (relfull / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0
    assert "manifest digest sai" in (r.stdout + r.stderr)


def test_report_json_co_du_con_so_cua_Doc52_muc9(relfull, tmp_path):
    out = tmp_path / "rep.json"
    r = _zip_and_verify(relfull, tmp_path, report=str(out))
    assert r.returncode == 0
    rep = _json.loads(out.read_text(encoding="utf-8"))
    for k in ("package_sha256", "files_on_disk", "sha256sums_lines",
              "manifest_files", "missing_checksum", "unexpected_file",
              "covered_by_manifest_only", "verdict"):
        assert k in rep, f"report thiếu {k}"
    assert rep["verdict"] == "PASS"


# ── RC2-049 · package_coverage_check · kiểm PHỦ không cần giải nén ─────────

COVERAGE = ROOT / "tools" / "package_coverage_check.py"


def _cov(rel, tmp_path, name="c.zip"):
    z = tmp_path / name
    assert _run([PACKAGE, "--dir", rel, "--out", z]).returncode == 0
    out = tmp_path / (name + ".json")
    r = _run([COVERAGE, "--package", z, "--report", out])
    data = _json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
    return r, data


def test_coverage_gói_phu_du_thi_PASS(relfull, tmp_path):
    r, d = _cov(relfull, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert d["verdict"] == "PASS"
    assert d["missing_checksum"] == 0 and d["unexpected_file"] == 0


def test_coverage_bat_tep_khong_duoc_phu(relfull, tmp_path):
    _reindex(relfull,
             drop_from_sums=("acceptance/c0/SHA256SUMS",),
             drop_from_manifest=("acceptance/c0/SHA256SUMS",))
    r, d = _cov(relfull, tmp_path)
    assert r.returncode == 3
    assert d["missing_checksum"] == 1


def test_coverage_bat_tep_thua(relfull, tmp_path):
    _reindex(relfull)
    (relfull / "la_mat.txt").write_text("x", encoding="utf-8")
    r, d = _cov(relfull, tmp_path)
    assert r.returncode == 3
    assert d["unexpected_file"] == 1


def test_coverage_BAM_LAI_tep_chi_manifest_phu(relfull, tmp_path):
    """Phủ bằng manifest chỉ có giá trị nếu digest trong manifest ĐÚNG.

    Từ C4, thiếu dòng trong `SHA256SUMS` là LỖI. Nhưng công cụ vẫn phải băm
    lại và ĐẾM được — nếu không, con số trong báo cáo lại là con số đoán.
    """
    _reindex(relfull, drop_from_sums=("acceptance/c0/SHA256SUMS",))
    r, d = _cov(relfull, tmp_path)
    assert r.returncode != 0
    assert d["covered_by_manifest_only"] == 1
    assert d["manifest_only_reverified_ok"] == 1


def test_coverage_digest_manifest_SAI_thi_FAIL(relfull, tmp_path):
    """Tệp chỉ manifest phủ mà digest sai → không được coi là đã phủ."""
    _reindex(relfull, drop_from_sums=("acceptance/c0/SHA256SUMS",))
    m = _json.loads((relfull / "manifest.json").read_text(encoding="utf-8"))
    m["files"]["acceptance/c0/SHA256SUMS"]["digest"] = "f" * 64
    (relfull / "manifest.json").write_text(_json.dumps(m), encoding="utf-8")
    r, d = _cov(relfull, tmp_path)
    assert r.returncode == 3
    assert d["manifest_only_reverified_bad"]


def test_coverage_KHONG_tu_nhan_la_kiem_toan_ven(relfull, tmp_path):
    """Công cụ này không kiểm 16.5k băm — report phải nói ra phạm vi."""
    _r, d = _cov(relfull, tmp_path)
    assert d["scope"] == "coverage_only"
    assert d["checks_integrity"] is False


# ── RC2-050 · khoá CÓ MẶT nhưng RỖNG không phải là định danh ───────────────
#
# `if k not in m` cho `source_hash: null` đi qua. Manifest của build
# 7aa8b4c22984bf5f đúng là như vậy, và RC-24 bản trước PASS mà không nói gì.

def test_bat_truong_dinh_danh_RONG_trong_manifest(relfull, tmp_path):
    _reindex(relfull, manifest_patch={"source_hash": None, "config_hash": ""})
    out = tmp_path / "rep.json"
    r = _zip_and_verify(relfull, tmp_path, report=str(out))
    rep = _json.loads(out.read_text(encoding="utf-8"))
    assert set(rep["manifest_null_identity_fields"]) == {"source_hash", "config_hash"}
    assert r.returncode != 0, "identity rỗng phải là LỖI, không phải cảnh báo"


def test_dinh_danh_RONG_phai_lam_verify_FAIL(relfull, tmp_path):
    """C4 · Doc 56 P1-04 · NÂNG từ cảnh báo lên LỖI.

    Lý lẽ cũ — "định danh vẫn tìm được trong acceptance report" — đúng về mặt
    dữ kiện nhưng sai về mặt hợp đồng: một gói portable phải tự định danh
    trong manifest gốc của nó, không bắt người nhận đi tìm nơi khác.
    """
    _reindex(relfull, manifest_patch={"source_hash": None})
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0, "identity rỗng mà verify vẫn PASS"


def test_manifest_day_du_dinh_danh_thi_khong_canh_bao(relfull, tmp_path):
    out = tmp_path / "rep.json"
    r = _zip_and_verify(relfull, tmp_path, report=str(out))
    rep = _json.loads(out.read_text(encoding="utf-8"))
    assert rep["manifest_null_identity_fields"] == []
    assert "RC2-050" not in r.stdout


def test_coverage_cung_ghi_nhan_dinh_danh_rong(relfull, tmp_path):
    _reindex(relfull, manifest_patch={"corpus_hash": None})
    _r, d = _cov(relfull, tmp_path)
    assert d["manifest_null_identity_fields"] == ["corpus_hash"]


# ── RC2-051 · thứ tự entry phải là thứ tự CHUỖI, không phải thứ tự Path ────
#
# `sorted(Path)` so sánh tuple `parts`; `namelist()` là chuỗi. Hai thứ tự lệch
# nhau ngay khi một thư mục là tiền tố của tên anh em: `pkg/` và
# `pkg.egg-info/`. Bản trước sort theo Path rồi assert theo chuỗi, nên tự
# đâm vào assert của chính mình khi gói source thật.

def test_thu_muc_la_tien_to_cua_ten_anh_em_van_dong_goi_duoc(rel, tmp_path):
    (rel / "pkg").mkdir()
    (rel / "pkg" / "mod.py").write_text("x", encoding="utf-8")
    (rel / "pkg.egg-info").mkdir()
    (rel / "pkg.egg-info" / "PKG-INFO").write_text("y", encoding="utf-8")
    z = tmp_path / "a.zip"
    r = _run([PACKAGE, "--dir", rel, "--out", z])
    assert r.returncode == 0, r.stdout + r.stderr
    with zipfile.ZipFile(z) as zf:
        names = zf.namelist()
    assert names == sorted(names), "entry chưa sort — gói không tất định"
    assert f"{rel.name}/pkg.egg-info/PKG-INFO" in names
    assert names.index(f"{rel.name}/pkg.egg-info/PKG-INFO") \
        < names.index(f"{rel.name}/pkg/mod.py"), "'.' phải đứng trước '/'"


def test_va_cham_ten_van_TAT_DINH_qua_hai_lan_dong_goi(rel, tmp_path):
    (rel / "pkg").mkdir(); (rel / "pkg" / "mod.py").write_text("x", encoding="utf-8")
    (rel / "pkg.egg-info").mkdir()
    (rel / "pkg.egg-info" / "PKG-INFO").write_text("y", encoding="utf-8")
    z1, z2 = tmp_path / "a.zip", tmp_path / "b.zip"
    assert _run([PACKAGE, "--dir", rel, "--out", z1]).returncode == 0
    assert _run([PACKAGE, "--dir", rel, "--out", z2]).returncode == 0
    assert _sha(z1) == _sha(z2)


# ── RC2-055 · rác giải nén phải nằm trong tầm nhìn và tự dọn ──────────────
#
# Verify giải nén 7 GB. Bản trước dùng `/var/folders` và dọn trong `finally` —
# `finally` không chạy khi tiến trình bị kill, nên một lần `timeout` cắt ngang
# đã bỏ lại 7 GB ở nơi không ai nghĩ tới khi đi tìm chỗ đĩa biến mất. Đủ để
# chặn build kế tiếp bằng preflight dung lượng.

def _duong_giai_nen(stdout: str) -> str:
    """Rút ĐÚNG dòng `giải nén:` ra khỏi stdout.

    A5 · sửa gốc một bài test hỏng. Bản trước khẳng định `"/var/folders" not
    in r.stdout` — grep cả stdout thay vì đọc dòng cần đọc. Trên macOS,
    `tmp_path` của pytest CHÍNH NÓ nằm dưới `/private/var/folders/...`, nên
    dòng in đường dẫn GÓI đã đủ làm phép khẳng định đỏ, kể cả khi hành vi
    đúng hoàn toàn. Bài test vì thế phụ thuộc `TMPDIR` của shell đang chạy:
    xanh ở máy này, đỏ ở máy kia, mà không cái nào nói gì về mã.

    Bất biến THẬT của RC2-055 là "giải nén CẠNH GÓI", và nó chỉ kiểm được
    bằng cách so thư mục giải nén với thư mục chứa gói. Bản dưới đây kiểm
    đúng thứ đó, nên nó CHẶT HƠN bản cũ chứ không lỏng hơn: nó vẫn đỏ nếu mã
    quay lại dùng thư mục tạm hệ thống, và không còn đỏ vì lý do không liên
    quan.
    """
    for dong in stdout.splitlines():
        if dong.strip().startswith("giải nén:"):
            return dong.split("giải nén:", 1)[1].strip()
    raise AssertionError(f"stdout không có dòng `giải nén:`\n{stdout}")


def test_giai_nen_canh_goi_khong_vao_thu_muc_tam_he_thong(relfull, tmp_path):
    import os
    import tempfile

    z = tmp_path / "p.zip"
    assert _run([PACKAGE, "--dir", relfull, "--out", z]).returncode == 0
    r = _run([VERIFY, "--package", z, "--type", "release"])

    noi_giai_nen = Path(_duong_giai_nen(r.stdout)).resolve()
    canh_goi = z.resolve().parent

    assert canh_goi in noi_giai_nen.parents, (
        f"phải giải nén cạnh gói ({canh_goi}), thực tế {noi_giai_nen}")
    assert "_verify_tmp" in noi_giai_nen.parts, noi_giai_nen

    # Và không được nằm dưới thư mục tạm HỆ THỐNG — trừ khi chính gói nằm
    # đó, vì khi ấy "cạnh gói" và "dưới thư mục tạm" là một, và điều kiện
    # trên mới là điều kiện có nghĩa.
    he_thong = Path(tempfile.gettempdir()).resolve()
    if he_thong not in canh_goi.parents and he_thong != canh_goi:
        assert he_thong not in noi_giai_nen.parents, (
            f"vẫn giải nén vào thư mục tạm hệ thống: {noi_giai_nen}")
    assert os.path.exists(z)


def test_don_rac_cua_lan_chay_truoc(relfull, tmp_path):
    z = tmp_path / "p.zip"
    _run([PACKAGE, "--dir", relfull, "--out", z])
    rac = tmp_path / "_verify_tmp" / "dp_verify_xacchet"
    rac.mkdir(parents=True)
    (rac / "to.bin").write_bytes(b"x" * 1024)
    r = _run([VERIFY, "--package", z, "--type", "release"])
    assert not rac.exists(), "xác của lần chạy trước không được dọn"
    assert "dọn" in r.stdout


def test_khong_de_lai_gi_sau_khi_chay_xong(relfull, tmp_path):
    z = tmp_path / "p.zip"
    _run([PACKAGE, "--dir", relfull, "--out", z])
    _run([VERIFY, "--package", z, "--type", "release"])
    base = tmp_path / "_verify_tmp"
    con = list(base.glob("dp_verify_*")) if base.exists() else []
    assert not con, f"còn {len(con)} thư mục giải nén sau khi chạy xong"


# ── A6 · manifest và build_meta phải nói cùng một điều ────────────────────
#
# Lỗi thật: gói `5ade9ae9d5f68b6a` phát hành với
# `manifest.readiness_policy_version = 2.1` còn `build_meta` ghi `2.2`. Cùng
# tên khoá, hai giá trị, một gói. Không cổng nào bắt vì không cổng nào so hai
# nguồn với nhau.

def test_manifest_lech_build_meta_thi_FAIL(relfull, tmp_path):
    """Đúng hình dạng của lỗi đã lọt."""
    _reindex(relfull, manifest_patch={"readiness_policy_version": "9.9"})
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0, "manifest lệch build_meta mà verify vẫn PASS"
    assert "readiness_policy_version" in (r.stdout + r.stderr)


def test_db_KHONG_co_build_meta_thi_FAIL(relfull, tmp_path):
    """Release không có `build_meta` là release không có định danh."""
    c = _sqlite3.connect(relfull / "silver.db")
    c.execute("DROP TABLE build_meta"); c.commit(); c.close()
    _reindex(relfull)
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode != 0
    assert "build_meta" in (r.stdout + r.stderr)


def test_mang_luu_dang_chuoi_JSON_KHONG_bi_coi_la_lech(relfull, tmp_path):
    """`build_meta` lưu TEXT nên mảng ở đó là chuỗi JSON của mảng ở manifest.
    Báo động giả ở đây sẽ làm cổng bị tắt trong vòng một tuần."""
    c = _sqlite3.connect(relfull / "silver.db")
    c.execute("INSERT INTO build_meta VALUES ('blocked_gates', ?)",
              (_json.dumps(["G3 Structure"]),))
    c.commit(); c.close()
    _reindex(relfull, manifest_patch={"blocked_gates": ["G3 Structure"]})
    r = _zip_and_verify(relfull, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
