"""Đo Retrieval trên GOLD V2 — đúng đặc tả metric của BTC.

Retrieval chạy bằng `src/retrieval/**` NGUYÊN TRẠNG (còn nguyên RC-1..RC-4).
Gold thì đã được gỡ khỏi bốn lỗi ấy. Đó là chủ ý: gold phải là SỰ THẬT, và
Retrieval phải bị trừ điểm cho lỗi của chính nó.

Hai phép gộp F2 (docs/93 §1.2) đều được in, vì BTC viết B mà bảng xếp hạng
hành xử như A:
    A = mean_i( 5·h_i / (4·g_i + N_i) )
    B = 5·P̄·R̄ / (4·P̄ + R̄)   với P̄ = mean(h_i/N_i), R̄ = mean(h_i/g_i)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from retrieval.alias_store import load_aliases                 # noqa: E402
from retrieval.evalkit.cli import _load_cfg                    # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,    # noqa: E402
                                      HardFilterGenerator)
from retrieval.question_intent import parse_intent             # noqa: E402

DEV = ROOT / "data" / "dev"
OUT = ROOT / "artifacts" / "retrieval" / "reaudit" / "refs_goldv2.json"
DEPTH = 300


def f2_ab(Ps, Rs, Fs):
    P = sum(Ps) / len(Ps)
    R = sum(Rs) / len(Rs)
    A = sum(Fs) / len(Fs)
    B = 5 * P * R / (4 * P + R) if (4 * P + R) else 0.0
    return P, R, A, B


def main(argv):
    ap = argparse.ArgumentParser(prog="eval_gold_v2")
    ap.add_argument("--db", required=True)
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--cap", type=int, default=30)
    a = ap.parse_args(argv)

    cfg = _load_cfg("base", {})
    alias = load_aliases(brands=cfg.brands)
    conn = sqlite3.connect(f"file:{os.path.abspath(a.db)}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    u2r = {u: ev.replace("|line:", "|") for u, ev in conn.execute(
        "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}

    S = {r["id"]: r for r in (json.loads(l) for l in
                              (DEV / "gold_tay_sample_v2.jsonl").open(encoding="utf-8") if l.strip())}
    G = {}
    for line in (DEV / "gold_v2.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("gold_table_uids"):
            G[r["id"]] = {"refs": {u2r[u] for u in r["gold_table_uids"] if u in u2r},
                          "che_do": r["che_do"], "leak": r.get("leakage_flag")}

    # ── chạy Retrieval THẬT (S0 chưa sửa) ────────────────────────────────
    if OUT.is_file():
        D = json.loads(OUT.read_text())
    else:
        D = {}
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=max(cfg.top_k_rank, DEPTH),
                              use_hints=cfg.use_hints, basis_mode=cfg.basis_mode,
                              stop_mode=cfg.stop_mode)
    t0 = time.time()
    for qid in sorted(G):
        if str(qid) in D:
            continue
        q = S[qid]["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        D[str(qid)] = {"o": max(1, len(it.targets)) * max(1, len(it.years)),
                       "n_s1": len(o1.uids),
                       "refs": [u2r[x.table_uid] for x in o2.ranked[:DEPTH] if x.table_uid in u2r]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(D))
    print(f"# Retrieval chạy trên {len(G)} câu · {time.time() - t0:.0f}s · S0 NGUYÊN TRẠNG\n")

    Q = sorted(G)
    mode = {qid: S[qid]["mode"] for qid in Q}

    def do(qs, k, cap):
        Ps, Rs, Fs, RR, NDCG = [], [], [], [], []
        for qid in qs:
            g = G[qid]["refs"]
            refs = D[str(qid)]["refs"]
            N = min(max(1, k * D[str(qid)]["o"]), cap)
            rr = refs[:N]
            h = len(set(rr) & g)
            Ps.append(h / len(rr)); Rs.append(h / len(g))
            Fs.append(5 * h / (4 * len(g) + len(rr)))
            pos = [i + 1 for i, x in enumerate(refs) if x in g]
            RR.append(1 / min(pos) if pos else 0.0)
            dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(rr) if x in g)
            idcg = sum(1 / math.log2(i + 2) for i in range(min(len(g), len(rr))))
            NDCG.append(dcg / idcg if idcg else 0.0)
        P, R, A, B = f2_ab(Ps, Rs, Fs)
        return P, R, A, B, sum(RR) / len(RR), sum(NDCG) / len(NDCG)

    print("=" * 96)
    print("1 · METRIC CHÍNH  ·  k=%d cap=%d  ·  n=%d câu · %d bảng gold"
          % (a.k, a.cap, len(Q), sum(len(G[q]["refs"]) for q in Q)))
    print("=" * 96)
    P, R, A, B, mrr, nd = do(Q, a.k, a.cap)
    print(f"  P̄ (macro)       = {P:.4f}   [MEASURED trên gold tay]")
    print(f"  R̄ (macro)       = {R:.4f}   [MEASURED]")
    print(f"  F2  phép gộp A  = {A:.4f}   [MEASURED · = trung bình F2 từng câu — bảng xếp hạng hành xử như thế này]")
    print(f"  F2  phép gộp B  = {B:.4f}   [MEASURED · = 5P̄R̄/(4P̄+R̄) — đúng nguyên văn BTC]")
    print(f"  MRR             = {mrr:.4f}   [MEASURED]")
    print(f"  NDCG@N          = {nd:.4f}   [MEASURED]")

    print("\n" + "=" * 96)
    print("2 · BREAKDOWN THEO MODE (single / screen / compare / related)")
    print("=" * 96)
    print("  mode      |  n | ḡ    |  P̄     |  R̄     | F2(A)  | F2(B)  |  MRR   | NDCG")
    for m in ("single", "screen", "compare", "related"):
        qs = [q for q in Q if mode[q] == m]
        if not qs:
            continue
        P, R, A, B, mrr, nd = do(qs, a.k, a.cap)
        gb = sum(len(G[q]["refs"]) for q in qs) / len(qs)
        print(f"  {m:<9} | {len(qs):>2} | {gb:>4.1f} | {P:.4f} | {R:.4f} | {A:.4f} | {B:.4f} | {mrr:.4f} | {nd:.4f}")

    print("\n" + "=" * 96)
    print("3 · RECALL@K và hit@K (trên tập ứng viên S2, độ sâu 300)")
    print("=" * 96)
    print("     K | hit@K (≥1 gold) | đủ gold |  micro-R | macro-R")
    for K in (1, 3, 5, 10, 20, 30, 60, 100, 300):
        hit = sum(1 for q in Q if set(D[str(q)]["refs"][:K]) & G[q]["refs"])
        full = sum(1 for q in Q if G[q]["refs"] <= set(D[str(q)]["refs"][:K]))
        num = sum(len(set(D[str(q)]["refs"][:K]) & G[q]["refs"]) for q in Q)
        den = sum(len(G[q]["refs"]) for q in Q)
        mac = sum(len(set(D[str(q)]["refs"][:K]) & G[q]["refs"]) / len(G[q]["refs"]) for q in Q) / len(Q)
        print(f"  {K:>4} |   {hit:>3}/{len(Q)}       |  {full:>3}/{len(Q)} |  {num/den:.4f}  | {mac:.4f}")

    print("\n" + "=" * 96)
    print("4 · TÁCH THEO CHẾ ĐỘ PHÂN XỬ (kiểm leakage theo từng nhãn)")
    print("=" * 96)
    print("  chế độ            |  n | cờ leakage          |  P̄     |  R̄     | F2(A)")
    for m in ("ke_thua_v1", "doc_bang_chung", "luat_khai_bao"):
        qs = [q for q in Q if G[q]["che_do"] == m]
        if not qs:
            continue
        P, R, A, B, _, _ = do(qs, a.k, a.cap)
        lk = sorted({G[q]["leak"] for q in qs})
        print(f"  {m:<17} | {len(qs):>2} | {','.join(lk)[:19]:<19} | {P:.4f} | {R:.4f} | {A:.4f}")

    print("\n" + "=" * 96)
    print("5 · QUÉT (k, cap) — hai phép gộp cho hai điểm tối ưu KHÁC NHAU")
    print("=" * 96)
    bA = bB = (0, None)
    for k in (1, 2, 3, 4, 5):
        row = []
        for cap in (10, 20, 30, 40):
            _, _, A, B, _, _ = do(Q, k, cap)
            if A > bA[0]:
                bA = (A, (k, cap))
            if B > bB[0]:
                bB = (B, (k, cap))
            row.append(f"{A:.4f}/{B:.4f}")
        print(f"  k={k} | " + " | ".join(row))
    print(f"  (ô = F2(A)/F2(B) theo cap 10,20,30,40)")
    print(f"  tối ưu A: k,cap={bA[1]} F2={bA[0]:.4f}   |   tối ưu B: k,cap={bB[1]} F2={bB[0]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
