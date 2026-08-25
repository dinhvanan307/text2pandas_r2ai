#!/usr/bin/env python3
"""RC-24 · verify từ BẢN GIẢI NÉN SẠCH.

Hợp đồng MỘT kiểu tham số (review 28 §RC-24): `PACKAGE` luôn là tệp **zip**.
Verifier tự tạo thư mục tạm, giải nén, kiểm, rồi dọn. Không bao giờ verify
thẳng thư mục vừa build — làm vậy là kiểm một thứ khác với thứ sẽ gửi đi.

`--type source` cho gói source; `--type release` (mặc định) cho gói dữ liệu.

── RC2-049 · verify phải kiểm PHỦ, không chỉ kiểm DÒNG ──────────────────────

Bản trước chỉ duyệt những dòng CÓ trong `SHA256SUMS`. Một tệp nằm trong gói
mà không dòng nào trỏ tới thì đi qua verify không ai biết — verify vẫn in
PASS. Đó không phải giả thuyết: `release.py` loại trừ chỉ mục theo BASENAME
(`f.name == "SHA256SUMS"`), nên tám tệp `acceptance/*/SHA256SUMS` được gieo
vào release cũng bị loại, và gói RC2 đầu tiên ra đời với 8 tệp không có dòng
checksum nào — mà verify báo PASS hai lần.

Doc 52 §9 đòi `missing checksum = 0` và `unexpected file = 0`. Muốn KHẲNG
ĐỊNH được hai con số đó thì phải liệt kê từ ĐĨA, không phải từ chỉ mục:

    đĩa  ↔  SHA256SUMS  ↔  manifest.files

Ba chiều, mỗi tệp băm đúng MỘT lần rồi đối chiếu với cả hai chỉ mục.
`manifest.files` là chỉ mục thứ hai đầy đủ (mọi entry `digest_mode=sha256`),
nên một tệp chỉ nằm trong manifest VẪN được phủ — nhưng verify nói ra điều
đó thay vì im lặng.
"""
from __future__ import annotations

import argparse, atexit, hashlib, json, shutil, sqlite3, sys, tempfile, zipfile
from pathlib import Path

FORBIDDEN = ("__MACOSX", ".DS_Store", "Thumbs.db", ".AppleDouble")
SELF = "SHA256SUMS"
_CHUNK = 1 << 20


def _fail(errs, msg):
    errs.append(msg); print(f"  ✗ {msg}", file=sys.stderr)


def _sha256(p: Path) -> str:
    """Băm theo khối. `read_bytes()` trên `silver.db` 4.1 GB là 4.1 GB RAM."""
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(blk)
    return h.hexdigest()



def manifest_vs_build_meta(m: dict, bm: dict) -> list[str]:
    """A6 · so MỌI khoá có mặt ở CẢ `manifest.json` lẫn `build_meta`.

    Vì sao cần: gói `5ade9ae9d5f68b6a` đi ra với
    `manifest.readiness_policy_version = 2.1` trong khi
    `build_meta.readiness_policy_version = 2.2` — cùng tên khoá, hai giá trị,
    một gói. Không cổng nào bắt được vì không cổng nào so hai nguồn đó với
    nhau. Đây là cổng đó.

    So sau khi CHUẨN HOÁ, không so chuỗi thô: `build_meta` lưu mọi thứ dưới
    dạng TEXT, nên một mảng ở manifest là `list` còn ở `build_meta` là chuỗi
    JSON của chính mảng ấy. Coi đó là lệch thì cổng này sẽ đỏ ở mỗi lần chạy
    và người ta sẽ tắt nó đi — cách một cổng thật chết vì báo động giả.
    """
    def chuan(v):
        if isinstance(v, str):
            t = v.strip()
            if t[:1] in "[{":
                try:
                    return json.dumps(json.loads(t), sort_keys=True,
                                      ensure_ascii=False)
                except ValueError:
                    return t
            return t
        if isinstance(v, (list, dict)):
            return json.dumps(v, sort_keys=True, ensure_ascii=False)
        return str(v)

    lech = []
    for k in sorted(set(m) & set(bm)):
        a, b = chuan(m[k]), chuan(bm[k])
        if a != b:
            lech.append(f"{k}: manifest={a[:60]!r} build_meta={b[:60]!r}")
    return lech


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, help="đường dẫn tới tệp .zip")
    ap.add_argument("--type", choices=("release", "source"), default="release")
    ap.add_argument("--keep-on-fail", action="store_true")
    ap.add_argument("--report", help="ghi JSON machine-readable (Doc 52 §5.3)")
    ap.add_argument("--work-dir", default=None,
                    help="nơi giải nén tạm. Mặc định: cạnh gói, KHÔNG dùng "
                         "/var/folders — rác 7 GB ở đó không ai nhìn thấy")
    a = ap.parse_args()

    pkg = Path(a.package)
    errs: list[str] = []
    rep: dict = {"package": str(pkg), "type": a.type}
    if not pkg.is_file() or pkg.suffix != ".zip":
        print(f"✗ PACKAGE phải là tệp .zip: {pkg}", file=sys.stderr); return 2

    pkg_sha = hashlib.sha256(pkg.read_bytes()).hexdigest()
    rep["package_sha256"] = pkg_sha
    rep["package_bytes"] = pkg.stat().st_size
    print(f"  gói     : {pkg}")
    print(f"  sha256  : {pkg_sha}")

    with zipfile.ZipFile(pkg) as z:
        names = z.namelist()
        for n in names:
            if any(f in n for f in FORBIDDEN):
                _fail(errs, f"entry cấm: {n}")
            if n.startswith("/") or ".." in n:
                _fail(errs, f"path traversal / tuyệt đối: {n}")
        roots = {n.split("/")[0] for n in names}
        if len(roots) != 1:
            _fail(errs, f"phải có đúng MỘT root, thấy {roots}")
        if names != sorted(names):
            _fail(errs, "entry chưa sort — gói không tất định")
    rep["zip_entries"] = len(names)

    # RC2-055 · giải nén CẠNH GÓI, không vào /var/folders.
    #
    # Bản trước dùng `tempfile.mkdtemp()` và dọn trong `finally`. `finally`
    # KHÔNG chạy khi tiến trình bị kill — và một lần `timeout` cắt ngang đã bỏ
    # lại 7 GB trong `/private/var/folders`, nơi không ai nghĩ tới khi đi tìm
    # chỗ đĩa biến mất. Rác thì sẽ có; nó phải nằm trong tầm nhìn.
    base = Path(a.work_dir) if a.work_dir else pkg.resolve().parent / "_verify_tmp"
    base.mkdir(parents=True, exist_ok=True)
    # Dọn xác của những lần chạy trước TRƯỚC khi giải nén lần này.
    cu = [d for d in base.glob("dp_verify_*") if d.is_dir()]
    for d in cu:
        shutil.rmtree(d, ignore_errors=True)
    if cu:
        print(f"  ⊘ dọn {len(cu)} thư mục giải nén còn sót của lần chạy trước")
    tmp = Path(tempfile.mkdtemp(prefix="dp_verify_", dir=base))
    # Kill giữa chừng thì `finally` không chạy, nhưng `atexit` bắt được thoát
    # bình thường lẫn SystemExit. Cộng với bước dọn ở trên, rác không tích tụ.
    atexit.register(shutil.rmtree, tmp, True)
    try:
        with zipfile.ZipFile(pkg) as z:
            z.extractall(tmp)
        root = tmp / next(iter(roots))
        print(f"  giải nén: {root}")

        # ── liệt kê từ ĐĨA, băm mỗi tệp đúng một lần ──────────────────────
        on_disk = {f.relative_to(root).as_posix(): f
                   for f in sorted(root.rglob("*")) if f.is_file()}
        digest = {rel: _sha256(f) for rel, f in on_disk.items()}
        rep["files_on_disk"] = len(on_disk)
        print(f"  trên đĩa: {len(on_disk)} tệp")

        # ── chỉ mục 1 · SHA256SUMS ────────────────────────────────────────
        sums_map: dict[str, str] = {}
        sums = root / SELF
        if not sums.is_file():
            _fail(errs, "thiếu SHA256SUMS")
        else:
            for line in sums.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                want, _, rel = line.partition("  ")
                sums_map[rel.strip()] = want.strip()
            nbad = 0
            for rel, want in sums_map.items():
                if rel not in on_disk:
                    _fail(errs, f"SHA256SUMS trỏ tệp không có: {rel}"); nbad += 1
                elif digest[rel] != want:
                    _fail(errs, f"checksum sai: {rel}"); nbad += 1
            rep["sha256sums_lines"] = len(sums_map)
            rep["sha256sums_bad"] = nbad
            print(f"  checksum: {'OK' if nbad == 0 else f'{nbad} lỗi'} "
                  f"· {len(sums_map)} dòng")

        # ── chỉ mục 2 · manifest.files ────────────────────────────────────
        man_map: dict[str, str] = {}
        if a.type == "release":
            man = root / "manifest.json"
            if not man.is_file():
                _fail(errs, "thiếu manifest.json")
            else:
                m = json.loads(man.read_text(encoding="utf-8"))
                required = ["release_label", "acceptance_status", "build_id",
                            "source_commit", "source_hash", "config_hash",
                            "corpus_hash", "schema_version", "component_versions",
                            "readiness_policy_version", "defect_taxonomy_version",
                            "counts", "gate_summary", "blocking_failures",
                            "allowed_blocked_gates", "files"]
                for k in required:
                    if k not in m:
                        _fail(errs, f"manifest thiếu khoá bắt buộc: {k}")

                # RC2-050 · `k not in m` KHÔNG bắt được `k: null`. Manifest của
                # build này mang `source_hash: null`, `config_hash: null`,
                # `corpus_hash: null` — đủ khoá, rỗng giá trị — và đi qua kiểm
                # "khoá bắt buộc" không một tiếng động. Cùng lớp lỗi với
                # RC2-049: kiểm có tồn tại nhưng không kiểm gì.
                #
                # Không nâng thành lỗi: định danh nguồn CÓ trong gói, ở
                # `acceptance/rc20/gate_report.json` và
                # `acceptance/c0_final/rebuild_check.json`, và Doc 52 §9 không
                # đặt điều kiện này. Nhưng phải ĐẾM và IN RA.
                IDENTITY = ("build_id", "source_hash", "config_hash",
                            "corpus_hash", "source_commit", "schema_version")
                null_id = [k for k in IDENTITY if k not in m or m[k] in (None, "")]
                rep["manifest_null_identity_fields"] = null_id
                if null_id:
                    # C4 · Doc 56 P1-04 · trước đây chỉ CẢNH BÁO. Một gói
                    # portable mà không tự định danh được thì người nhận không
                    # có cách nào biết nó dựng từ đâu — và cảnh báo thì trôi
                    # qua trong log. Nay là LỖI.
                    _fail(errs, f"manifest có {len(null_id)} trường định danh "
                                f"rỗng: {', '.join(null_id)}")
                rep["build_id"] = m.get("build_id")
                rep["release_label"] = m.get("release_label")
                if m.get("blocking_failures"):
                    _fail(errs, f"blocking_failures không rỗng: {m['blocking_failures']}")

                mf = m.get("files")
                if mf is not None and not isinstance(mf, dict):
                    _fail(errs, "manifest.files không phải object")
                elif isinstance(mf, dict):
                    nbadm = 0
                    for rel, meta in mf.items():
                        want = (meta or {}).get("digest")
                        mode = (meta or {}).get("digest_mode")
                        man_map[rel] = want
                        if rel not in on_disk:
                            _fail(errs, f"manifest trỏ tệp không có: {rel}"); nbadm += 1
                        elif mode == "sha256" and want and digest[rel] != want:
                            _fail(errs, f"manifest digest sai: {rel}"); nbadm += 1
                    rep["manifest_files"] = len(man_map)
                    rep["manifest_bad"] = nbadm
                    print(f"  manifest: {'OK' if nbadm == 0 else f'{nbadm} lỗi'} "
                          f"· {len(man_map)} tệp")
                    if m.get("n_files") is not None and m["n_files"] != len(man_map):
                        _fail(errs, f"n_files lệch: manifest={m['n_files']} "
                                    f"files={len(man_map)}")

                db = root / "silver.db"
                if not db.is_file():
                    _fail(errs, "thiếu silver.db")
                else:
                    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        _fail(errs, "quick_check KHÔNG ok")
                    if c.execute("PRAGMA foreign_key_check").fetchall():
                        _fail(errs, "foreign_key_check có vi phạm")
                    # A6 · manifest và build_meta phải nói cùng một điều.
                    try:
                        _bm = dict(c.execute("SELECT key, value FROM build_meta"))
                    except sqlite3.Error:
                        _bm = {}
                        _fail(errs, "silver.db không đọc được build_meta")
                    _lech = manifest_vs_build_meta(m, _bm)
                    rep["manifest_build_meta_mismatch"] = _lech
                    print(f"  danh tính: manifest ↔ build_meta "
                          f"{'OK' if not _lech else f'{len(_lech)} LỆCH'}")
                    for x in _lech:
                        _fail(errs, f"manifest lệch build_meta · {x}")

                    for t, want in (m.get("counts") or {}).items():
                        try:
                            got = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                        except sqlite3.Error:
                            continue
                        if got != want:
                            _fail(errs, f"counts lệch: {t} manifest={want} db={got}")
                    c.close()
        else:
            for need in ("pyproject.toml", "requirements.lock", "HANDOFF.md"):
                if not (root / need).is_file():
                    _fail(errs, f"gói source thiếu {need}")
            for bad in ("*.sqlite", "*.db", "*.zip"):
                hit = list(root.rglob(bad))
                if hit:
                    _fail(errs, f"gói source chứa artifact cấm: {hit[0].name}")

        # ── PHỦ · Doc 52 §9 ───────────────────────────────────────────────
        covered = set(sums_map) | set(man_map)
        missing = sorted(set(on_disk) - covered - {SELF})
        rep["missing_checksum"] = len(missing)
        rep["missing_checksum_files"] = missing[:50]
        if missing:
            _fail(errs, f"missing checksum = {len(missing)} "
                        f"(vd: {', '.join(missing[:3])})")

        if man_map:
            unexpected = sorted(set(on_disk) - set(man_map) - {SELF, "manifest.json"})
            rep["unexpected_file"] = len(unexpected)
            rep["unexpected_files"] = unexpected[:50]
            if unexpected:
                _fail(errs, f"unexpected file = {len(unexpected)} "
                            f"(vd: {', '.join(unexpected[:3])})")
            only_man = sorted(set(man_map) - set(sums_map))
            rep["covered_by_manifest_only"] = len(only_man)
            rep["covered_by_manifest_only_files"] = only_man[:50]
            if only_man:
                # C4 · Doc 56 P1-05 · `SHA256SUMS` phải phủ 100%. Phủ nhờ chỉ
                # mục khác vẫn là phủ, nhưng đó không phải điều `SHA256SUMS`
                # hứa, và bản handoff trước đã mô tả sai con số vì chỉ nhìn
                # cảnh báo (8 ở gói cũ, thật ra 21 ở gói đang gửi).
                _fail(errs, f"SHA256SUMS thiếu {len(only_man)} tệp mà "
                            f"manifest có: {', '.join(only_man[:3])}"
                            + (" …" if len(only_man) > 3 else ""))
                for r in only_man[:10]:
                    print(f"      {r}")
        print(f"  phủ     : missing checksum = {rep['missing_checksum']}"
              f" · unexpected = {rep.get('unexpected_file', 'n/a')}")
    finally:
        if errs and a.keep_on_fail:
            print(f"  giữ lại để soi: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    rep["errors"] = errs
    rep["n_errors"] = len(errs)
    rep["verdict"] = "PASS" if not errs else "FAIL"
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(f"  → {'PASS' if not errs else f'FAIL ({len(errs)} lỗi)'}")
    return 0 if not errs else 3


if __name__ == "__main__":
    sys.exit(main())
