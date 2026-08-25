"""E2 · Chạy S1→S2 trên đúng 95 câu gold_v2 với MỘT tham số thay đổi, ghi refs top-300.

Mỗi lần chạy = một `--tag`. Không đụng gold, không đụng định nghĩa metric.
Chấm điểm nằm ở `e2_score.py` (gold_v2 + proxy_v2 cạnh nhau).
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from retrieval.alias_store import load_aliases                 # noqa: E402
from retrieval.evalkit.cli import _load_cfg                    # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,    # noqa: E402
                                      HardFilterGenerator)
from retrieval.question_intent import parse_intent             # noqa: E402

DEV = ROOT / "data/curated/dev-legacy"
OUTDIR = ROOT / "artifacts/runs/retrieval/reaudit"
DEPTH = 300


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"))
    ap.add_argument("--tag", required=True)
    ap.add_argument("--primary-boost", type=float, default=0.0)
    ap.add_argument("--primary-modes", default="screen,related")
    ap.add_argument("--primary-kinds", default="",
                    help="mặc định rỗng = PRIMARY_KINDS (BS+IS+CF)")
    ap.add_argument("--per-ticker-k", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    out = OUTDIR / f"exp_refs_{a.tag}.json"
    if out.is_file() and not a.force:
        print(f"đã có {out.name} — dùng --force để chạy lại"); return 0

    cfg = _load_cfg("base", {})
    alias = load_aliases(brands=cfg.brands)
    conn = sqlite3.connect(f"file:{os.path.abspath(a.db)}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    u2r = {u: ev.replace("|line:", "|") for u, ev in conn.execute(
        "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
    S = {r["id"]: r for r in (json.loads(l) for l in
         (DEV / "gold_tay_sample_v2.jsonl").open(encoding="utf-8") if l.strip())}
    qids = sorted(r["id"] for r in (json.loads(l) for l in
                  (DEV / "gold_v2.jsonl").open(encoding="utf-8") if l.strip())
                  if r.get("gold_table_uids"))

    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(
        alias, top_k=max(cfg.top_k_rank, DEPTH), use_hints=cfg.use_hints,
        basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode,
        primary_boost=a.primary_boost,
        primary_modes=tuple(x for x in a.primary_modes.split(",") if x),
        primary_kinds=(frozenset(x for x in a.primary_kinds.split(",") if x)
                       or None) if a.primary_kinds else None,
        per_ticker_k=a.per_ticker_k or None)

    D, t0 = {}, time.time()
    for qid in qids:
        q = S[qid]["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        D[str(qid)] = {"o": max(1, len(it.targets)) * max(1, len(it.years)),
                       "mode": it.mode, "n_s1": len(o1.uids),
                       "refs": [u2r[x.table_uid] for x in o2.ranked[:DEPTH]
                                if x.table_uid in u2r]}
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"tag": a.tag, "primary_boost": a.primary_boost,
                               "primary_modes": a.primary_modes,
                               "primary_kinds": a.primary_kinds,
                               "per_ticker_k": a.per_ticker_k, "refs": D}),
                   encoding="utf-8")
    print(f"{a.tag}: {len(D)} câu · {time.time()-t0:.1f}s → {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
