"""Đo S1→S2→S3 trên GOLD GÁN TAY và đặt cạnh GOLD PROXY trên đúng những câu đó.

CÂU HỎI DUY NHẤT SCRIPT NÀY TRẢ LỜI
-----------------------------------
83 câu `F3_RANK_MISS` đo trên proxy KHÔNG phân biệt được hai nguyên nhân:

    (a) S2 xếp sai           → sửa được bằng trọng số / reranker
    (b) proxy sinh gold rác  → không có gì để sửa ở S2

Chạy CÙNG một retriever trên CÙNG những câu đó, một lần chấm bằng gold tay, một
lần bằng proxy. Chênh lệch giữa hai bảng chính là phần proxy đang bóp méo.

ĐỌC CHO ĐÚNG — ba giới hạn, khai trước khi đưa số
-------------------------------------------------
1. **Gold tay ở đây do AI gán, không phải người.** Nguồn bằng chứng là nhãn
   dòng + kỳ + phạm vi (hợp nhất/riêng) đọc từ chính A6, tức cùng loại bằng
   chứng người gán sẽ dùng — nhưng vẫn phải ghi `gold_source="ai_adjudicated"`
   và cần một lượt người soi trước khi dùng để chốt.
2. **Pool có trần.** Ứng viên gộp từ 4 nguồn (S2 top-K, LIKE nhãn dòng, proxy,
   mã chỉ tiêu) và cắt ở 10. Bảng đúng nằm ngoài cả 4 nguồn thì không vào gold
   ⇒ `Recall` trên gold tay là **cận trên**, không phải điểm thật.
3. **n nhỏ.** Mỗi con số phải in kèm mẫu số; đừng đọc chênh lệch vài phần trăm
   trên vài chục câu như một kết luận.

    python tools/gold_tay_eval.py --db …/work.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.evalkit.cli import _load_cfg               # noqa: E402
from retrieval.evalkit.goldset import ProxyGoldV2         # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator, IdentityReranker)
from retrieval.question_intent import parse_intent        # noqa: E402

DEV = ROOT / "data/curated/dev-legacy"
MAU = DEV / "gold_tay_sample_v2.jsonl"
NHAN = DEV / "gold_v1.jsonl"
KS = (1, 3, 5, 10)


def _f2(h: int, g: int, n: int) -> float:
    return 5 * h / (4 * g + n) if (4 * g + n) else 0.0


def _khoi(ket: list[dict], khoa: str) -> dict:
    """`khoa` = 'tay' hoặc 'proxy'. Trả về chỉ số trên đúng tập câu có gold đó."""
    d = [r for r in ket if r[khoa]]
    if not d:
        return {"n": 0}
    out = {"n": len(d)}
    for k in KS:
        hit = sum(1 for r in d if any(p <= k for p in r[f"pos_{khoa}"]))
        rec = sum(len([p for p in r[f"pos_{khoa}"] if p <= k]) / len(r[khoa])
                  for r in d) / len(d)
        f2 = sum(_f2(len([p for p in r[f"pos_{khoa}"] if p <= k]),
                     len(r[khoa]), min(k, r["n_ranked"])) for r in d) / len(d)
        out[k] = {"hit": hit / len(d), "recall": rec, "f2": f2}
    out["mrr"] = sum((1 / min(r[f"pos_{khoa}"])) if r[f"pos_{khoa}"] else 0.0
                     for r in d) / len(d)
    out["g_median"] = sorted(len(r[khoa]) for r in d)[len(d) // 2]
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gold_tay_eval")
    ap.add_argument("--db", default="data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db")
    ap.add_argument("--out", default="artifacts/runs/retrieval/evalkit/gold_tay_eval.json")
    ns = ap.parse_args(argv)

    mau = {r["id"]: r for r in
           (json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip())}
    nhan = [json.loads(l) for l in NHAN.open(encoding="utf-8") if l.strip()]
    cfg = _load_cfg("base", {})
    db = ROOT / ns.db if not str(ns.db).startswith("/") else Path(ns.db)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=cfg.brands)
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    s3 = IdentityReranker(top_k=cfg.top_k_rerank)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)

    ket, khong_chac = [], []
    for r in nhan:
        qid = r["id"]
        if r.get("uncertain"):
            khong_chac.append((qid, r.get("reason")))
            continue
        q = mau[qid]["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        g_tay = frozenset(r["gold_table_uids"])
        gp = proxy.gold_for(conn, qid, q, frozenset(it.targets) or it.tickers,
                            it.years, it.explicit_scope)
        g_px = gp.tables if gp.ok else frozenset()
        ket.append({
            "id": qid, "tang": mau[qid]["tang"], "n_ranked": len(o2.ranked),
            "tay": g_tay, "proxy": g_px,
            "pos_tay": list(o2.positions_of(g_tay)),
            "pos_proxy": list(o2.positions_of(g_px)) if g_px else [],
            "tay_trong_proxy": bool(g_tay & g_px),
        })

    print(f"\nGOLD TAY · {len(ket)} câu gán được · {len(khong_chac)} câu UNCERTAIN")
    print("  UNCERTAIN theo lý do: "
          + " · ".join(f"{k}={v}" for k, v in Counter(r for _, r in khong_chac).items()))
    print("  theo tầng: " + " · ".join(
        f"{k}={v}" for k, v in Counter(r["tang"] for r in ket).items()))

    a, b = _khoi(ket, "tay"), _khoi(ket, "proxy")
    print(f"\n  |gold| median — tay {a.get('g_median')} · proxy {b.get('g_median')}")
    print(f"  {'chỉ số':<16s} {'GOLD TAY':>10s} {'GOLD PROXY':>11s}   {'Δ':>8s}")
    print(f"  {'-'*16} {'-'*10} {'-'*11}   {'-'*8}")
    for k in KS:
        for ten in ("hit", "recall", "f2"):
            va, vb = a[k][ten], b[k][ten]
            print(f"  {ten}@{k:<13d} {va:10.4f} {vb:11.4f}   {vb-va:+8.4f}")
    print(f"  {'MRR':<16s} {a['mrr']:10.4f} {b['mrr']:11.4f}   {b['mrr']-a['mrr']:+8.4f}")

    tay_top1 = sum(1 for r in ket if 1 in r["pos_tay"])
    px_top1 = sum(1 for r in ket if 1 in r["pos_proxy"])
    tay_out = [r for r in ket if not any(p <= 10 for p in r["pos_tay"])]
    px_out = [r for r in ket if r["proxy"] and not any(p <= 10 for p in r["pos_proxy"])]
    chong = sum(1 for r in ket if r["tay_trong_proxy"])
    print(f"\n  bảng gold tay CÓ nằm trong gold proxy : {chong}/{len(ket)}")
    print(f"  hạng 1 đúng theo gold TAY             : {tay_top1}/{len(ket)}")
    print(f"  hạng 1 'đúng' theo gold PROXY         : {px_top1}/{len(ket)}")
    print(f"  rớt top-10 theo gold TAY              : {len(tay_out)}")
    print(f"  rớt top-10 theo gold PROXY            : {len(px_out)}")
    if tay_out:
        print("  câu S2 THẬT SỰ xếp hỏng (gold tay ngoài top-10):")
        for r in tay_out[:10]:
            print(f"      q{r['id']:<5d} [{r['tang']}] hạng tay="
                  f"{min(r['pos_tay']) if r['pos_tay'] else '-'} "
                  f"· hạng proxy={min(r['pos_proxy']) if r['pos_proxy'] else '-'}")

    Path(ns.out).write_text(json.dumps(
        {"n_tay": len(ket), "uncertain": khong_chac,
         "tay": {str(k): v for k, v in a.items()},
         "proxy": {str(k): v for k, v in b.items()},
         "chi_tiet": [{**r, "tay": sorted(r["tay"]), "proxy": sorted(r["proxy"])}
                      for r in ket]},
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n→ {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
