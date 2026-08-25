#!/usr/bin/env python3
"""RC-12/RC-13 · `make dp-build` — preflight, log, rồi mới build.

Preflight tồn tại vì kiểu hỏng đắt nhất là build chết giữa chừng và để lại một
DB cụt trông hệt build hợp lệ. Bốn cổng chặn trước khi động vào dữ liệu:

    OUTPUT chưa tồn tại  ·  đủ đĩa  ·  ghi được  ·  ghi log invocation

Build B (RC-13) dùng CHÍNH tool này với `--output` khác; tính độc lập đến từ
process mới + thư mục mới + không đọc cache của A.
"""
from __future__ import annotations

import argparse, hashlib, json, os, platform, shutil, subprocess, sqlite3, sys, time
from pathlib import Path

MIN_FREE_GB = 40.0


def _sh(*c, strip: bool = True):
    """`strip=False` khi khoảng trắng đầu dòng CÓ NGHĨA — `git status
    --porcelain` dùng hai ký tự đầu làm trường trạng thái."""
    try:
        r = subprocess.run(c, capture_output=True, text=True, timeout=20)
        if r.returncode != 0:
            return None
        return r.stdout.strip() if strip else r.stdout.rstrip("\n")
    except Exception:
        return None


def _dirty_report() -> dict:
    """RC2-034 · "Cây có bẩn không" phải hỏi bằng CÙNG một phép với `env_check`.

    Bản trước ghi `bool(git status --porcelain)` — BẤT KỲ dòng nào cũng thành
    `source_tree_dirty: true`, kể cả một tệp `.md` trong `docs/`. Nhưng
    `source_hash` chỉ băm `src/text2pandas/pipelines/a6/*.py` và `config_hash` chỉ băm
    `configs/*.yaml`; sửa một tài liệu KHÔNG thể ảnh hưởng tới bản dựng.

    Hậu quả đo được trên chính bản dựng `4c86c9e43915694a`: nó ghi
    `source_tree_dirty: true` trong khi cây nguồn sinh ra nó khớp CHÍNH XÁC
    commit `22c26b2` — nguyên nhân là một tệp `docs/*.md` bị sửa sau commit.
    Người review đọc `build_invocation.json` sẽ mất niềm tin vào một bản dựng
    hoàn toàn sạch, vì một dòng tài liệu.

    `env_check._classify_dirty` đã giải đúng bài này rồi. Gọi lại nó, không
    viết bản thứ hai — hai phép đo cho cùng một câu hỏi là cách một sai lệch
    sống sót.
    """
    porcelain = _sh("git", "status", "--porcelain", strip=False)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_env_check_for_build", Path(__file__).with_name("env_check.py"))
        ec = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ec)
        d = ec._classify_dirty(porcelain)
    except Exception as exc:                                 # pragma: no cover
        return {"source_tree_dirty": bool(porcelain),
                "dirty_classification_error": repr(exc)}
    return {
        # CHỈ tệp đã tracked bị sửa mới làm bản dựng không quy được về commit.
        "source_tree_dirty": bool(d["tracked"]),
        "dirty_tracked_files": d["tracked"][:20],
        # Tệp lạ trong src/tools/configs KHÔNG vào `source_hash` nhưng vẫn có
        # thể được nạp lúc build — nguy hiểm hơn, nên tách riêng và ghi rõ.
        "untracked_in_source_paths": d["untracked_source"][:20],
        "untracked_elsewhere_count": len(d["untracked_other"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--allow-low-disk", action="store_true")
    ap.add_argument("--finalize", action="store_true",
                    help="chạy tiếp `quality` + `publish` trong CÙNG output. BẮT "
                         "BUỘC cho cả A và B nếu định dùng C0-final làm "
                         "acceptance (B0-06), và bắt buộc để có manifest BẢN DỰNG.")
    a = ap.parse_args()

    cfg, inp, out = Path(a.config), Path(a.input), Path(a.output)
    fails = []
    if out.exists():
        fails.append(f"OUTPUT đã tồn tại: {out} — build phải bắt đầu từ thư mục MỚI")
    if not cfg.is_file():
        fails.append(f"không thấy config: {cfg}")
    if not inp.is_dir():
        fails.append(f"không thấy input: {inp}")
    free = shutil.disk_usage(Path.cwd()).free / 1e9
    if free < MIN_FREE_GB and not a.allow_low_disk:
        fails.append(f"đĩa trống {free:.1f} GB < {MIN_FREE_GB} GB "
                     f"(2× build DB + release + zip + reports + 20%)")
    if fails:
        print("✗ PREFLIGHT KHÔNG ĐẠT:", file=sys.stderr)
        for f in fails:
            print(f"  · {f}", file=sys.stderr)
        return 2

    out.mkdir(parents=True)
    sys.path.insert(0, str(Path.cwd() / "src"))
    try:
        from text2pandas.pipelines.a6.storage import source_fingerprint
        fp = source_fingerprint()
    except Exception as exc:
        fp = {"source_fingerprint_error": repr(exc)}

    inv = {
        "invocation": " ".join(sys.argv),
        "cwd": str(Path.cwd()),
        "config": str(cfg), "input": str(inp), "output": str(out),
        "config_sha256": hashlib.sha256(cfg.read_bytes()).hexdigest(),
        "started_at_monotonic": time.monotonic(),
        "environment": {
            "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
            "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
            "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED"),
            "TZ": os.environ.get("TZ"), "LC_ALL": os.environ.get("LC_ALL"),
            "SOURCE_DATE_EPOCH": os.environ.get("SOURCE_DATE_EPOCH"),
        },
        "source_commit": _sh("git", "rev-parse", "HEAD"),
        **_dirty_report(),
        **fp,
        "disk_free_gb_before": round(free, 1),
    }
    (out / "build_invocation.json").write_text(
        json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ✓ preflight đạt · log → {out/'build_invocation.json'}")

    # RC2-017 · TRUYỀN `--config` và `--input` xuống thật.
    #
    # Bản trước chỉ kiểm chúng ở preflight rồi ghi vào `build_invocation.json`,
    # còn stage con thì suy đường dẫn từ `ROOT`. Một `INPUT=` trỏ sang corpus
    # khác vẫn cho preflight xanh và build vẫn quét corpus mặc định — tham số
    # không có tác dụng, và không có thông báo nào sai để người ta nghi ngờ.
    #
    # `bronze`/`silver_dir` cũng vào OUTPUT: hai build song song mà dùng chung
    # `artifacts/runs/a6/bronze/` sẽ giẫm lên nhau, và C0 sẽ so hai bản đã nhiễm nhau.
    env = {**os.environ,
           "DATA_PIPELINE_SCRATCH": str(out),
           "DATA_PIPELINE_CONFIG": str(Path(a.config).resolve()),
           "DATA_PIPELINE_CORPUS": str(Path(a.input).resolve()),
           "DATA_PIPELINE_BRONZE": str(out / "bronze" / "catalog_v2.sqlite"),
           "DATA_PIPELINE_SILVER_DIR": str(out / "silver"),
           "PYTHONPATH": "src", "PYTHONHASHSEED": "0", "TZ": "UTC",
           "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
    (out / "bronze").mkdir(parents=True, exist_ok=True)
    log = (out / "build.log").open("w", encoding="utf-8")
    rc = 0
    # B0-06 · A và B phải chạy CÙNG chuỗi stage. Nếu chỉ A được `quality`, thì
    # C0 so hai bản KHÁC PHA: bản A đã finalize, bản B chưa. Khi đó C0 xanh
    # cũng không chứng minh được final candidate tất định.
    stages = ["snapshot", "catalog", "silver"]
    if a.finalize:
        # `publish` KHÔNG phải bước tuỳ chọn — nó là bước sinh ra manifest BẢN
        # DỰNG (`build_id`, `counts`, `silver_sha256`, `blocked_gates`).
        #
        # Thiếu nó, thư mục OUTPUT chỉ có `manifest.json` do `snapshot` ghi —
        # tức manifest CORPUS. Hai tài liệu khác nhau, cùng một tên tệp. Khi đó
        # `release --db <OUT>/silver.sqlite` đọc nhầm manifest corpus và
        # `rep.build_id = src_manifest.get("build_id", "unknown")` cho ra
        # `build_id = "unknown"` — IM LẶNG, không lỗi, không cảnh báo.
        stages += ["quality", "publish"]
    for stage in stages:
        print(f"  ── {stage} ──", flush=True)
        log.write(f"\n===== {stage} =====\n"); log.flush()
        p = subprocess.run([sys.executable, "-m", "text2pandas.pipelines.a6.cli", stage],
                           env=env, stdout=log, stderr=subprocess.STDOUT)
        if p.returncode:
            rc = p.returncode
            print(f"  ✗ {stage} thất bại (exit {rc}) — xem {out/'build.log'}", file=sys.stderr)
            break
    log.close()

    if rc:
        # Build hỏng KHÔNG được để lại thứ trông giống candidate hợp lệ.
        (out / "BUILD_FAILED").write_text(
            f"stage thất bại, exit={rc}. Thư mục này KHÔNG phải candidate hợp lệ.\n",
            encoding="utf-8")
        return rc
    # B0-06 · completion marker — bằng chứng máy đọc được rằng bản dựng này đã
    # chạy ĐÚNG những stage nào. `rebuild_check --mode final` từ chối so hai bản
    # nếu thiếu marker hoặc hai marker khai khác chuỗi stage.
    bid = None
    for cand in (out / "silver" , out):
        for db in sorted(Path(cand).glob("**/silver.sqlite")):
            try:
                c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                r = c.execute("SELECT value FROM build_meta WHERE key='build_id'").fetchone()
                c.close()
                if r:
                    bid = r[0]
                    break
            except sqlite3.Error:
                continue
        if bid:
            break
    (out / "completion_marker.json").write_text(json.dumps({
        "_schema": "B0-06 · chuoi stage DA CHAY that cua ban dung nay.",
        "stages_completed": stages,
        "finalized": bool(a.finalize),
        "build_id": bid,
        "output": str(out),
        "config": str(Path(a.config).resolve()),
        "input": str(Path(a.input).resolve()),
        "note": ("finalized=false nghia la ban dung NAY chua qua `quality`. "
                 "C0-final khong duoc dung ban nhu vay lam acceptance."),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  ✓ build xong → {out}   (stages: {', '.join(stages)})")
    if not a.finalize:
        print("  ⚠ CHƯA finalize — dùng --finalize nếu bản dựng này sẽ đi vào C0-final",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
