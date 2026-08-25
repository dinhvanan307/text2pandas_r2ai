#!/usr/bin/env python3
"""RC-11 · `make dp-test` — chạy full test và ghi report MÁY ĐỌC ĐƯỢC.

Không khoá acceptance vào một con số test cụ thể (review 28 §RC-11). Khoá vào:

    required suite có mặt  ·  collect không lỗi  ·  fail = 0
    không có skip vì thiếu dependency

Một suite bị đổi tên hoặc không collect được sẽ TRƯỢT, kể cả khi `fail = 0` —
đó là cách "test không chạy" nguỵ trang thành "test xanh".
"""
from __future__ import annotations

import argparse, json, platform, re, sqlite3, subprocess, sys, time
from pathlib import Path

# Mười nhóm test Plan 17 §RC-11 đòi. Khớp theo TÊN TỆP, không theo số ca.
REQUIRED_SUITES = {
    "header_boundary":       r"test_header_boundary",
    "physical_uid":          r"test_(rc2_readiness_and_safety|consumer_contract)",
    "tiny_money":            r"test_tiny_money_wiring",
    "readiness_policy":      r"test_(data_contract_v1|rc2_readiness_and_safety)",
    "fts_accent":            r"test_(rc2_batch1|fts)",
    "non_tabular":           r"test_rc2_batch1",
    "mojibake":              r"test_rc2_batch1",
    "manifest_counts":       r"test_(rc2_batch1|release_docs)",
    "legacy_consumer_schema": r"test_consumer_contract",
    "release_blocking":      r"test_release_gating",
}
_SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|xfailed|xpassed|error)")


def _sh(*cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--testpath", default="tests/")
    a = ap.parse_args()
    out = Path(a.report_dir); out.mkdir(parents=True, exist_ok=True)

    # C6 · Doc 56 P2-03 · xuất JUnit XML bên cạnh JSON.
    #
    # `test_report.json` là định dạng riêng của dự án; reviewer muốn một định
    # dạng máy đọc được phổ thông để tự dựng lại kết quả mà không phải học
    # schema của ta. JUnit là định dạng đó, và pytest sinh sẵn.
    junit = out / "junit.xml"
    cmd = [sys.executable, "-m", "pytest", a.testpath, "-q", "--tb=short", "-rs",
           f"--junit-xml={junit}"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dur = round(time.time() - t0, 2)
    stdout = proc.stdout + proc.stderr

    counts = {k: 0 for k in ("passed", "failed", "skipped", "xfailed", "xpassed", "error")}
    for n, kind in _SUMMARY.findall(stdout):
        counts[kind] = int(n)
    collected = sum(counts.values())

    # Suite nào không xuất hiện trong output => không được collect.
    files = set(re.findall(r"(tests/[\w/]+\.py)", stdout)) | {
        str(p) for p in Path("tests").rglob("test_*.py")}
    missing = [name for name, pat in REQUIRED_SUITES.items()
               if not any(re.search(pat, f) for f in files)]

    # Skip vì thiếu dependency là stop condition của Plan 17 §12.
    dep_skips = [ln for ln in stdout.splitlines()
                 if "SKIPPED" in ln and re.search(r"import|module|instal", ln, re.I)]

    rep = {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "duration_seconds": dur,
        "collected": collected,
        **counts,
        "collection_errors": counts["error"],
        "junit_xml": str(junit) if junit.is_file() else None,
        "required_suites": list(REQUIRED_SUITES),
        "missing_required_suites": missing,
        "dependency_related_skips": dep_skips,
        "environment": {
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": sys.version.split()[0],
            "python_executable": sys.executable,
            "sqlite": sqlite3.sqlite_version,
        },
        "source_commit": _sh("git", "rev-parse", "HEAD"),
        "source_tree_dirty": bool(_sh("git", "status", "--porcelain")),
    }
    try:
        sys.path.insert(0, str(Path.cwd() / "src"))
        from data_pipeline.storage import source_fingerprint
        rep.update(source_fingerprint())
    except Exception as exc:                                  # pragma: no cover
        rep["source_fingerprint_error"] = repr(exc)

    ok = (proc.returncode == 0 and counts["failed"] == 0
          and counts["error"] == 0 and not missing and not dep_skips)
    rep["verdict"] = "PASS" if ok else "FAIL"

    (out / "test_report.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "test_report.txt").write_text(stdout, encoding="utf-8")
    (out / "exit_code.txt").write_text(f"{proc.returncode}\n", encoding="utf-8")
    if not junit.is_file():
        # Không có thì NÓI RA. Một thư mục report thiếu tệp mà không ai báo là
        # cách `MISSING ARTIFACT` biến thành "chắc là ổn".
        (out / "MISSING_junit.xml.txt").write_text(
            "pytest khong sinh junit.xml — kiem plugin junitxml\n", encoding="utf-8")

    print(f"  collected {collected} · passed {counts['passed']} · failed {counts['failed']}"
          f" · skipped {counts['skipped']} · error {counts['error']} · {dur}s")
    if missing:
        print(f"  ✗ suite bắt buộc KHÔNG collect được: {missing}", file=sys.stderr)
    if dep_skips:
        print(f"  ✗ skip do thiếu dependency: {len(dep_skips)}", file=sys.stderr)
    print(f"  → {out/'test_report.json'}  verdict={rep['verdict']}")
    # Bảo toàn exit code của pytest khi nó khác 0; ngược lại dùng verdict.
    return proc.returncode if proc.returncode else (0 if ok else 3)


if __name__ == "__main__":
    sys.exit(main())
