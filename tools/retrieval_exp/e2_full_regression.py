"""P1 · Kiểm tra full-run 1.012 QID theo đúng checklist docs/119 §7.5."""
from __future__ import annotations
import json, sys, hashlib
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg          # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.runner import SCHEMA_VERSION  # noqa: E402
EK = ROOT / "artifacts/runs/retrieval/evalkit"


def load(tag):
    cfg = _load_cfg(tag, {})
    p = EK / cfg.checkpoint_name
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return cfg, p, rows


def main() -> int:
    A_cfg, A_p, A = load("base")
    B_cfg, B_p, B = load("s2_primary")
    chk = []
    def c(name, cond, got=None):
        chk.append({"check": name, "pass": bool(cond), "got": got})
        print(("PASS " if cond else "FAIL ") + name + (f"   {got}" if got is not None else ""))

    print(f"base       {A_p.name}  n={len(A)}")
    print(f"s2_primary {B_p.name}  n={len(B)}\n")
    for tag, rows, cfg in (("base", A, A_cfg), ("s2_primary", B, B_cfg)):
        ids = [r["id"] for r in rows]
        c(f"{tag}: đủ 1.012 dòng", len(rows) == 1012, len(rows))
        c(f"{tag}: id DUY NHẤT (không trùng)", len(set(ids)) == len(ids),
          f"{len(set(ids))} unique / {len(ids)}")
        c(f"{tag}: mọi dòng đúng cfg_sha", all(r["cfg_sha"] == cfg.sha for r in rows), cfg.sha)
        c(f"{tag}: mọi dòng đúng schema {SCHEMA_VERSION}",
          all(r["schema"] == SCHEMA_VERSION for r in rows),
          dict(Counter(r["schema"] for r in rows)))
        c(f"{tag}: không dòng nào lỗi",
          all(not r.get("error") for r in rows),
          sum(1 for r in rows if r.get("error")))
    c("hai lần chạy phủ CÙNG tập id", set(r["id"] for r in A) == set(r["id"] for r in B))
    c("checkpoint KHÔNG dùng chung tên tệp với evalkit-2", A_p.name != B_p.name
      and "489d4fed855debb5" not in A_p.name and "489d4fed855debb5" not in B_p.name,
      f"{A_p.name} | {B_p.name}")

    # ── latency ─────────────────────────────────────────────────────────────
    def pct(v, q):
        v = sorted(v); return v[min(len(v) - 1, int(q * len(v)))]
    lat = {}
    for tag, rows in (("base", A), ("s2_primary", B)):
        ms = [r.get("ms") or r.get("elapsed_ms") or 0 for r in rows]
        if any(ms):
            lat[tag] = {"p50": pct(ms, .50), "p95": pct(ms, .95), "p99": pct(ms, .99),
                        "max": max(ms), "mean": round(sum(ms) / len(ms), 1)}
    print("\nlatency (ms/câu):", json.dumps(lat))

    # ── bất biến top-N + per-mode ───────────────────────────────────────────
    Am = {r["id"]: r for r in A}; Bm = {r["id"]: r for r in B}
    modes = Counter(r.get("mode") for r in A)
    print("phân bố mode:", dict(modes))
    doi = {m: 0 for m in modes}
    tong_doi = 0
    khac_mode = []
    for i in Am:
        ra, rb = Am[i], Bm[i]
        if ra.get("mode") != rb.get("mode"):
            khac_mode.append(i)
        # Checkpoint KHÔNG lưu danh sách uid; nó lưu VỊ TRÍ của gold sau S2/S3
        # (`hits_at_rank`/`hits_at_final`) và kích thước từng tầng. Đổi thứ hạng
        # ⇒ đổi một trong các trường này. So đúng những gì có, không bịa ra
        # trường không tồn tại.
        a10 = (ra.get("hits_at_rank"), ra.get("hits_at_final"),
               ra.get("s1_n"), ra.get("s2_n"), ra.get("s3_n"), ra.get("bucket"))
        b10 = (rb.get("hits_at_rank"), rb.get("hits_at_final"),
               rb.get("s1_n"), rb.get("s2_n"), rb.get("s3_n"), rb.get("bucket"))
        if a10 != b10:
            doi[ra.get("mode")] = doi.get(ra.get("mode"), 0) + 1
            tong_doi += 1
    c("mode ổn định giữa hai lần chạy", not khac_mode, len(khac_mode))
    print("số câu ĐỔI top-K theo mode:", doi)
    c("single/compare BẤT BIẾN (bất biến cổng mode)",
      doi.get("single", 0) == 0 and doi.get("compare", 0) == 0,
      {k: doi.get(k, 0) for k in ("single", "compare")})
    c("screen CÓ thay đổi (nếu không thì knob chưa nối)", doi.get("screen", 0) > 0,
      doi.get("screen", 0))
    for tag, rows in (("base", A), ("s2_primary", B)):
        s3 = [r["s3_n"] for r in rows]; s2n = [r["s2_n"] for r in rows]
        c(f"{tag}: s3_n ≤ top_k_rerank({A_cfg.top_k_rerank})",
          max(s3) <= A_cfg.top_k_rerank, f"max={max(s3)} min={min(s3)}")
        c(f"{tag}: s2_n ≤ top_k_rank({A_cfg.top_k_rank})",
          max(s2n) <= A_cfg.top_k_rank, f"max={max(s2n)} min={min(s2n)}")
        c(f"{tag}: s1_n ≥ s2_n ≥ s3_n mọi câu",
          all(r["s1_n"] >= r["s2_n"] >= r["s3_n"] for r in rows))
    # bucket / phân bố lỗi
    from collections import Counter as _C
    bk = {t: dict(_C(r["bucket"] for r in rs)) for t, rs in (("base", A), ("s2_primary", B))}
    print("\nphân bố bucket:", json.dumps(bk, ensure_ascii=False))
    out_extra = {"bucket": bk}

    out = {"schema": SCHEMA_VERSION, "n": len(A),
           "checkpoints": {"base": {"file": A_p.name, "sha256": hashlib.sha256(A_p.read_bytes()).hexdigest(),
                                    "cfg_sha": A_cfg.sha, "primary_boost": A_cfg.primary_boost},
                           "s2_primary": {"file": B_p.name, "sha256": hashlib.sha256(B_p.read_bytes()).hexdigest(),
                                          "cfg_sha": B_cfg.sha, "primary_boost": B_cfg.primary_boost}},
           "latency_ms": lat, "mode_distribution": dict(modes),
           "n_doi_topk_theo_mode": doi, "n_doi_topk_tong": tong_doi,
           "bucket_distribution": out_extra["bucket"],
           "checks": chk, "n_pass": sum(1 for x in chk if x["pass"]),
           "n_fail": sum(1 for x in chk if not x["pass"])}
    (ROOT / "artifacts/runs/retrieval/reaudit/e2_full_regression_1012.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nTỔNG: {out['n_pass']} PASS / {out['n_fail']} FAIL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
