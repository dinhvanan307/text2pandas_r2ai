"""E1b-report · Phân tích độ lệch PROXY ↔ GOLD trên 95 câu (cùng một thứ hạng)."""
from __future__ import annotations
import argparse, json
from pathlib import Path


def cham(r, g, k, cap):
    N = min(max(1, k * r["o"]), cap)
    rr = r["refs"][:N]; n = len(rr)
    h = len(set(rr) & g)
    pos = [i + 1 for i, x in enumerate(r["refs"]) if x in g]
    return dict(P=h / n, R=h / len(g), F2=5 * h / (4 * len(g) + n),
                MRR=1 / pos[0] if pos else 0.0, hit1=1.0 if 1 in pos else 0.0,
                hit10=1.0 if any(p <= 10 for p in pos) else 0.0, g=len(g), N=n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", default="artifacts/retrieval/reaudit/e1_proxy_gap.json")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--cap", type=int, default=30)
    a = ap.parse_args(argv)
    R = json.loads(Path(a.inp).read_text(encoding="utf-8"))

    # ── 1. proxy như một BỘ NHÃN: so trực tiếp với gold ──────────────────────
    tp = fp = fn = 0
    per = []
    for r in R:
        G, P = set(r["gold"]), set(r["proxy"])
        tp += len(G & P); fp += len(P - G); fn += len(G - P)
        per.append((r["qid"], len(G), len(P), len(G & P)))
    print(f"PROXY NHƯ BỘ NHÃN (95 câu · gold {tp+fn} bảng · proxy {tp+fp} bảng)")
    print(f"  precision nhãn proxy = {tp/(tp+fp):.4f}   ({tp}/{tp+fp})")
    print(f"  recall    nhãn proxy = {tp/(tp+fn):.4f}   ({tp}/{tp+fn})")
    hoan = sum(1 for _, g, p, i in per if i == g == p)
    roi = sum(1 for _, g, p, i in per if i == 0)
    print(f"  câu proxy trùng KHỚP HOÀN TOÀN gold : {hoan}/95")
    print(f"  câu proxy KHÔNG giao gold một bảng  : {roi}/95")
    med = lambda x: sorted(x)[len(x) // 2]
    print(f"  |gold| median={med([g for _, g, _, _ in per])} · "
          f"|proxy| median={med([p for _, _, p, _ in per])}")

    # ── 2. cùng thứ hạng, chấm hai lần ───────────────────────────────────────
    A = [cham(r, set(r["gold"]), a.k, a.cap) for r in R]
    Bp = [cham(r, set(r["proxy"]), a.k, a.cap) for r in R if r["proxy"]]
    m = lambda L, key: sum(x[key] for x in L) / len(L)
    print(f"\nCÙNG THỨ HẠNG · chấm bằng GOLD (n={len(A)}) vs PROXY (n={len(Bp)})")
    print(f"  {'chỉ số':<10s} {'GOLD':>8s} {'PROXY':>8s} {'Δ (lạc quan)':>13s}")
    for key in ("hit1", "hit10", "MRR", "P", "R", "F2"):
        va, vb = m(A, key), m(Bp, key)
        print(f"  {key:<10s} {va:8.4f} {vb:8.4f} {vb-va:+13.4f}")

    # ── 3. đồng thuận mức CÂU: proxy có xếp đúng câu nào tốt/xấu không? ──────
    pair = [(cham(r, set(r["gold"]), a.k, a.cap)["F2"],
             cham(r, set(r["proxy"]), a.k, a.cap)["F2"]) for r in R if r["proxy"]]
    n = len(pair)
    rk = lambda v: {x: i for i, x in enumerate(sorted(range(n), key=lambda j: v[j]))}
    ga = [p[0] for p in pair]; pa = [p[1] for p in pair]
    ra_, rb = rk(ga), rk(pa)
    d2 = sum((ra_[i] - rb[i]) ** 2 for i in range(n))
    rho = 1 - 6 * d2 / (n * (n * n - 1))
    con = dis = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (ga[i] - ga[j]) * (pa[i] - pa[j])
            if s > 0: con += 1
            elif s < 0: dis += 1
    print(f"\nĐỒNG THUẬN MỨC CÂU (F2 gold vs F2 proxy, n={n})")
    print(f"  Spearman ρ = {rho:.4f}")
    print(f"  Kendall  τ = {(con-dis)/(con+dis):.4f}  (thuận {con} · nghịch {dis})")
    xau_gold_tot_proxy = [r["qid"] for r, (g, p) in zip([x for x in R if x["proxy"]], pair)
                          if g < 0.20 and p > 0.60]
    tot_gold_xau_proxy = [r["qid"] for r, (g, p) in zip([x for x in R if x["proxy"]], pair)
                          if g > 0.60 and p < 0.20]
    print(f"  câu GOLD kém (<.20) nhưng PROXY khen (>.60): {len(xau_gold_tot_proxy)} → {xau_gold_tot_proxy[:12]}")
    print(f"  câu GOLD tốt (>.60) nhưng PROXY chê (<.20): {len(tot_gold_xau_proxy)} → {tot_gold_xau_proxy[:12]}")

    print(f"\nTHEO MODE · Δ lạc quan của proxy (F2 proxy − F2 gold)")
    for md in ("single", "screen", "compare", "related"):
        idx = [i for i, r in enumerate(R) if r["mode"] == md and r["proxy"]]
        if not idx: continue
        pp = [pair[k] for k, r in enumerate([x for x in R if x["proxy"]]) if r["mode"] == md]
        print(f"  {md:<9s} n={len(pp):3d}  gold {sum(x[0] for x in pp)/len(pp):.4f} "
              f"· proxy {sum(x[1] for x in pp)/len(pp):.4f} "
              f"· Δ {sum(x[1]-x[0] for x in pp)/len(pp):+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
