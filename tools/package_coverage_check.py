#!/usr/bin/env python3
"""RC2-049 · kiểm PHỦ checksum của một gói release — ĐỌC THẲNG TỪ ZIP.

Doc 52 §9 đòi ba con số: `missing checksum = 0`, `unexpected file = 0`,
`manifest/count mismatch = 0`. `verify_package.py` (RC-24) trả lời đủ ba,
nhưng nó giải nén 7 GB nên chỉ chạy được ở terminal của người vận hành.

Công cụ này trả lời ĐÚNG ba con số đó mà không giải nén: central directory
của zip đủ để liệt kê, và ba tệp cần đọc nội dung (`manifest.json`,
`SHA256SUMS`, cùng các tệp chưa có dòng checksum) đều nhỏ. Nó KHÔNG thay
`verify_package` — không kiểm sqlite, không kiểm counts, không kiểm băm của
16.5k tệp — nên nó là kiểm PHỦ, không phải kiểm TOÀN VẸN.

Exit: 0 phủ đủ · 3 thiếu phủ hoặc thừa tệp · 2 gói hỏng/thiếu chỉ mục.
"""
from __future__ import annotations

import argparse, hashlib, json, sys, zipfile
from pathlib import Path

SELF = "SHA256SUMS"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True)
    ap.add_argument("--report")
    a = ap.parse_args()

    pkg = Path(a.package)
    if not pkg.is_file() or pkg.suffix != ".zip":
        print(f"✗ PACKAGE phải là tệp .zip: {pkg}", file=sys.stderr); return 2

    rep: dict = {"package": str(pkg), "package_bytes": pkg.stat().st_size,
                 "scope": "coverage_only", "checks_integrity": False}
    with zipfile.ZipFile(pkg) as zf:
        names = zf.namelist()
        roots = {n.split("/")[0] for n in names}
        if len(roots) != 1:
            print(f"✗ phải có đúng MỘT root, thấy {roots}", file=sys.stderr); return 2
        root = next(iter(roots))
        rel = {n[len(root) + 1:] for n in names if not n.endswith("/")}
        rep["root"] = root
        rep["files_in_zip"] = len(rel)

        try:
            man = json.loads(zf.read(f"{root}/manifest.json"))
        except KeyError:
            print("✗ thiếu manifest.json", file=sys.stderr); return 2
        mf = man.get("files") or {}
        rep["build_id"] = man.get("build_id")
        rep["release_label"] = man.get("release_label")
        rep["manifest_files"] = len(mf)
        rep["manifest_n_files"] = man.get("n_files")
        # RC2-050 · khoá có mặt nhưng giá trị rỗng thì không phải là định danh.
        #
        # Hai loại gói, hai bộ trường. Gói RELEASE đi ra ngoài nhóm nên phải tự
        # định danh đầy đủ; gói BUNDLE bằng chứng đi kèm nó thì chỉ cần nói rõ
        # nó thuộc bản dựng nào. Áp một bộ cho cả hai là bắt bundle mang những
        # trường vốn không thuộc về nó.
        IDENTITY_RELEASE = ("build_id", "source_hash", "config_hash",
                            "corpus_hash", "source_commit", "schema_version")
        IDENTITY_BUNDLE = ("build_id",)
        la_release = "release_label" in man or "counts" in man
        rep["manifest_kind"] = "release" if la_release else "bundle"
        idf = IDENTITY_RELEASE if la_release else IDENTITY_BUNDLE
        rep["manifest_null_identity_fields"] = [
            k for k in idf if k not in man or man[k] in (None, "")]

        sums: dict[str, str] = {}
        try:
            for line in zf.read(f"{root}/{SELF}").decode("utf-8").splitlines():
                if line.strip():
                    w, _, r = line.partition("  ")
                    sums[r.strip()] = w.strip()
        except KeyError:
            print("✗ thiếu SHA256SUMS", file=sys.stderr); return 2
        rep["sha256sums_lines"] = len(sums)

        missing = sorted(rel - set(mf) - set(sums) - {SELF})
        unexpected = sorted(rel - set(mf) - {SELF, "manifest.json"})
        only_man = sorted(set(mf) - set(sums))
        dangling_man = sorted(set(mf) - rel)
        dangling_sums = sorted(set(sums) - rel)

        # Tệp chỉ được manifest phủ thì PHẢI băm lại — nếu không, "phủ đủ"
        # mới là một dòng trong JSON chứ chưa là một sự thật đã đo.
        recheck_ok, recheck_bad = 0, []
        for r in only_man:
            meta = mf[r]
            if meta.get("digest_mode") != "sha256":
                recheck_bad.append(f"{r} (digest_mode={meta.get('digest_mode')})")
                continue
            h = hashlib.sha256(zf.read(f"{root}/{r}")).hexdigest()
            if h == meta.get("digest"):
                recheck_ok += 1
            else:
                recheck_bad.append(f"{r} (digest lệch)")

    rep.update({
        "missing_checksum": len(missing), "missing_checksum_files": missing[:50],
        "unexpected_file": len(unexpected), "unexpected_files": unexpected[:50],
        "manifest_count_mismatch": int(
            man.get("n_files") is not None and man["n_files"] != len(mf)),
        "manifest_dangling": len(dangling_man),
        "sha256sums_dangling": len(dangling_sums),
        "covered_by_manifest_only": len(only_man),
        "covered_by_manifest_only_files": only_man,
        "manifest_only_reverified_ok": recheck_ok,
        "manifest_only_reverified_bad": recheck_bad,
    })

    print(f"  gói      : {pkg.name}")
    print(f"  build_id : {rep['build_id']}")
    print(f"  trong zip: {rep['files_in_zip']} · manifest {rep['manifest_files']}"
          f" · SHA256SUMS {rep['sha256sums_lines']}")
    print(f"  missing checksum        : {rep['missing_checksum']}")
    print(f"  unexpected file         : {rep['unexpected_file']}")
    print(f"  manifest/count mismatch : {rep['manifest_count_mismatch']}")
    print(f"  manifest trỏ hụt        : {rep['manifest_dangling']}")
    print(f"  SHA256SUMS trỏ hụt      : {rep['sha256sums_dangling']}")
    if only_man:
        print(f"  ⚠ RC2-048 · {len(only_man)} tệp chỉ manifest phủ, "
              f"băm lại từ zip: {recheck_ok}/{len(only_man)} khớp")
        for r in only_man[:12]:
            print(f"      {r}")
    for r in missing[:5]:
        print(f"  ✗ không có checksum: {r}", file=sys.stderr)
    for r in unexpected[:5]:
        print(f"  ✗ tệp thừa: {r}", file=sys.stderr)
    for r in recheck_bad[:5]:
        print(f"  ✗ băm lại không khớp: {r}", file=sys.stderr)

    # C4 · hai công cụ kiểm phải cùng một ngưỡng. Để `verify_package` FAIL còn
    # công cụ này PASS trên cùng một gói là tạo ra hai câu trả lời cho một câu
    # hỏi, và người vận hành sẽ tin câu dễ nghe hơn.
    bad = bool(missing or unexpected or recheck_bad or dangling_man
               or dangling_sums or rep["manifest_count_mismatch"]
               or only_man or rep["manifest_null_identity_fields"])
    if only_man:
        print(f"  ✗ SHA256SUMS thiếu {len(only_man)} tệp mà manifest có "
              f"(RC2-048)", file=sys.stderr)
    if rep["manifest_null_identity_fields"]:
        print(f"  ✗ manifest có trường định danh rỗng: "
              f"{', '.join(rep['manifest_null_identity_fields'])} (RC2-050)",
              file=sys.stderr)
    rep["verdict"] = "FAIL" if bad else "PASS"
    if a.report:
        Path(a.report).parent.mkdir(parents=True, exist_ok=True)
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(f"  → {rep['verdict']}")
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
