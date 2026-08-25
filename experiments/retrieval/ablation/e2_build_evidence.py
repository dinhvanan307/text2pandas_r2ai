"""P0-B · Dựng `retrieval_e2_evidence_v1/` đúng cây thư mục docs/119 §8."""
from __future__ import annotations
import hashlib, json, os, shutil, sqlite3, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RE = ROOT / "artifacts/runs/retrieval/reaudit"
OUT = ROOT / "artifacts/runs/retrieval/bundles/retrieval_e2_evidence_v1"
sys.path.insert(0, str(ROOT / "src"))
K, CAP = 3, 30
TAGS = ["base", "pri015", "pri030", "pri060", "pri100",
        "pri030_bsis", "pri060_bsis", "pri100_bsis", "pri150_bsis"]


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def git(*a):
    try:
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                              text=True, timeout=20).stdout.strip()
    except Exception as e:
        return f"<không lấy được: {e}>"


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "src/text2pandas/pipelines/retrieval/evalkit").mkdir(parents=True)
    (OUT / "tests").mkdir(parents=True)
    (OUT / "experiments/retrieval/ablation").mkdir(parents=True)

    SRC = ["src/text2pandas/pipelines/retrieval/rank_s2.py", "src/text2pandas/pipelines/retrieval/pipeline.py",
           "src/text2pandas/pipelines/retrieval/evalkit/stages.py", "src/text2pandas/pipelines/retrieval/evalkit/runner.py",
           "src/text2pandas/pipelines/retrieval/evalkit/cli.py", "tests/test_s2_primary_prior.py",
           "configs/retrieval/eval_v1.yaml"]
    for f in SRC:
        d = OUT / f
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, d)
    for f in sorted((ROOT / "experiments/retrieval/ablation").glob("*.py")):
        shutil.copy2(f, OUT / "experiments/retrieval/ablation" / f.name)

    # ── source_identity ─────────────────────────────────────────────────────
    from text2pandas.pipelines.retrieval.evalkit.runner import SCHEMA_VERSION, EvalConfig
    from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg
    si = {"git_commit": git("rev-parse", "HEAD"),
          "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
          "git_dirty": bool(git("status", "--porcelain")),
          "python": sys.version.split()[0],
          "schema_version": SCHEMA_VERSION,
          "cfg_sha_base": _load_cfg("base", {}).sha,
          "cfg_sha_s2_primary": _load_cfg("s2_primary", {}).sha,
          "cfg_sha_s2_primary_nullmode": _load_cfg("s2_primary_nullmode", {}).sha,
          "default_primary_boost_production": EvalConfig().primary_boost,
          "file_sha256": {f: sha(ROOT / f) for f in SRC}}
    (OUT / "source_identity.json").write_text(
        json.dumps(si, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── gold_identity ───────────────────────────────────────────────────────
    G = {}
    for line in (ROOT / "data/curated/dev-legacy/gold_v2.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("gold_table_uids"):
            G[r["id"]] = r["gold_table_uids"]
    gi = {"gold_file": "data/curated/dev-legacy/gold_v2.jsonl",
          "gold_file_sha256": sha(ROOT / "data/curated/dev-legacy/gold_v2.jsonl"),
          "gold_v1_sha256": sha(ROOT / "data/curated/dev-legacy/gold_v1.jsonl"),
          "sample_file_sha256": sha(ROOT / "data/curated/dev-legacy/gold_tay_sample_v2.jsonl"),
          "n_rows_total": sum(1 for _ in (ROOT / "data/curated/dev-legacy/gold_v2.jsonl").open(encoding="utf-8")),
          "n_qid_co_gold": len(G), "n_bang_gold": sum(len(v) for v in G.values()),
          "qids": sorted(G),
          "qid_list_sha256": hashlib.sha256(
              json.dumps(sorted(G), separators=(",", ":")).encode()).hexdigest(),
          "ghi_chu": ("gold_v2 GIỮ NGUYÊN 89 QID đã gán của v1 và phân xử thêm 6 QID "
                      "trước đó bỏ trống; 25 QID vẫn chưa có gold đầy đủ. Cả hai tệp "
                      "đều 120 dòng — docs/119 §4.2.")}
    (OUT / "gold_identity.json").write_text(
        json.dumps(gi, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── cache_identity ──────────────────────────────────────────────────────
    db = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n_cards = conn.execute("SELECT COUNT(*) FROM table_cards").fetchone()[0]
    ci = {"work_db": str(db.relative_to(ROOT)), "work_db_bytes": db.stat().st_size,
          "work_db_n_table_cards": n_cards,
          "refs_cache": {f"exp_refs_{t}.json": {
              "sha256": sha(RE / f"exp_refs_{t}.json"),
              "meta": {k: v for k, v in json.loads(
                  (RE / f"exp_refs_{t}.json").read_text(encoding="utf-8")).items()
                  if k != "refs"}} for t in TAGS if (RE / f"exp_refs_{t}.json").is_file()},
          "bundle_gold": {"exp_gold_bundle.json": sha(RE / "exp_gold_bundle.json")},
          "canh_bao": ("Mỗi tệp `exp_refs_*.json` là ĐẦU RA của một lần chạy S1+S2 "
                       "ĐẦY ĐỦ, không phải một cache top-300 được rerank. Xem "
                       "e2_stage_boundary.json.")}
    (OUT / "cache_identity.json").write_text(
        json.dumps(ci, ensure_ascii=False, indent=1), encoding="utf-8")

    for f, dst in (("e1_ceiling.json", "ceiling_report.json"),
                   ("e1_proxy_gap.json", None),
                   ("e2_stage_boundary.json", "stage_boundary_report.json"),
                   ("e2_summary.json", "parameter_sweep_summary.json")):
        if (RE / f).is_file() and dst:
            shutil.copy2(RE / f, OUT / dst)
    print("→", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
