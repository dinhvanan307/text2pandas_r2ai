"""E1b · Đo độ lệch PROXY ↔ GOLD TAY trên toàn bộ 95 câu gold_v2.

Dùng CÙNG một thứ hạng (refs top-300 đã cache trong exp_gold_bundle.json), chấm
hai lần: một lần bằng gold_v2 (người/AI phân xử), một lần bằng ProxyGoldV2.
Không chạy lại S1/S2 ⇒ mọi chênh lệch là do ĐỊNH NGHĨA GOLD, không do retriever.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from text2pandas.pipelines.retrieval.alias_store import load_aliases            # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg               # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.goldset import ProxyGoldV2         # noqa: E402
from text2pandas.pipelines.retrieval.question_intent import parse_intent        # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db")
    ap.add_argument("--bundle", default="artifacts/runs/retrieval/reaudit/exp_gold_bundle.json")
    ap.add_argument("--out", default="artifacts/runs/retrieval/reaudit/e1_proxy_gap.json")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    B = json.loads(Path(a.bundle).read_text(encoding="utf-8"))
    cfg = _load_cfg("base", {})
    db = Path(a.db) if str(a.db).startswith("/") else ROOT / a.db
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=cfg.brands)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit, max_trusted=cfg.gold_max_trusted,
                        alias=alias, max_tier=cfg.gold_max_tier)
    u2r = {u: str(ev).replace("|line:", "|") for u, ev in conn.execute(
        "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}

    ds = sorted(B, key=int)
    if a.limit:
        ds = ds[:a.limit]
    ra = []
    for qid in ds:
        e = B[qid]
        it = parse_intent(e["question"], alias)
        gp = proxy.gold_for(conn, int(qid), e["question"],
                            frozenset(it.targets) or it.tickers, it.years,
                            it.explicit_scope)
        px = {u2r[u] for u in (gp.tables if gp.ok else frozenset()) if u in u2r}
        ra.append({"qid": int(qid), "mode": e["mode"], "o": e["o"],
                   "gold": e["gold"], "proxy": sorted(px),
                   "refs": e["refs"], "proxy_ok": bool(gp.ok),
                   "proxy_reason": None if gp.ok else str(getattr(gp, "reason", ""))})
    Path(a.out).write_text(json.dumps(ra, ensure_ascii=False), encoding="utf-8")
    print(f"qids={len(ra)} · proxy_ok={sum(1 for r in ra if r['proxy_ok'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
