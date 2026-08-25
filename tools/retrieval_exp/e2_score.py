"""E2-score · Chấm một hoặc nhiều `--tag` bằng GOLD_v2 VÀ PROXY_v2 cạnh nhau.

Quy tắc bắt buộc (yêu cầu của chủ dự án): không bao giờ chỉ in một metric.
Nếu gold và proxy lệch dấu, script IN RA cảnh báo thay vì chọn số đẹp hơn.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RE = ROOT / "artifacts/runs/retrieval/reaudit"
K, CAP = 3, 30


def nap_gold():
    B = json.loads((RE / "exp_gold_bundle.json").read_text(encoding="utf-8"))
    return {q: set(e["gold"]) for q, e in B.items()}, {q: e["mode"] for q, e in B.items()}


def nap_proxy():
    R = json.loads((RE / "e1_proxy_gap.json").read_text(encoding="utf-8"))
    return {str(r["qid"]): set(r["proxy"]) for r in R}


def cham(D, GS, qids=None):
    Ps = Rs = Fs = RR = ND = 0.0
    h1 = h10 = n = 0
    for q, e in D.items():
        if qids is not None and q not in qids:
            continue
        g = GS.get(q) or set()
        if not g:
            continue
        refs = e["refs"]; N = min(max(1, K * e["o"]), CAP)
        rr = refs[:N]; ln = len(rr); h = len(set(rr) & g)
        pos = [i + 1 for i, x in enumerate(refs) if x in g]
        dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(rr) if x in g)
        idcg = sum(1 / math.log2(i + 2) for i in range(min(len(g), ln)))
        Ps += h / ln; Rs += h / len(g); Fs += 5 * h / (4 * len(g) + ln)
        RR += 1 / pos[0] if pos else 0.0
        ND += dcg / idcg if idcg else 0.0
        h1 += 1 if 1 in pos else 0
        h10 += 1 if any(p <= 10 for p in pos) else 0
        n += 1
    if not n:
        return None
    P, R = Ps / n, Rs / n
    return dict(n=n, P=P, R=R, F2A=Fs / n,
                F2B=5 * P * R / (4 * P + R) if (4 * P + R) else 0.0,
                MRR=RR / n, NDCG=ND / n, hit1=h1 / n, hit10=h10 / n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tags", required=True, help="base,exp1,…  (tag đầu = mốc so sánh)")
    a = ap.parse_args(argv)
    tags = [t for t in a.tags.split(",") if t]
    G, MODE = nap_gold(); P = nap_proxy()
    Ds = {}
    for t in tags:
        f = RE / f"exp_refs_{t}.json"
        if not f.is_file():
            print(f"✗ thiếu {f.name}"); return 2
        Ds[t] = json.loads(f.read_text(encoding="utf-8"))

    for nguon, GS in (("GOLD_v2", G), ("PROXY_v2", P)):
        print(f"\n{'='*94}\n{nguon}  ·  k={K} cap={CAP}\n{'='*94}")
        print(f"  {'tag':<14s}{'n':>4s}{'P̄':>8s}{'R̄':>8s}{'F2(A)':>8s}{'F2(B)':>8s}"
              f"{'MRR':>8s}{'NDCG':>8s}{'hit@1':>8s}{'hit@10':>8s}{'ΔF2A':>9s}")
        goc = None
        for t in tags:
            m = cham(Ds[t]["refs"], GS)
            if goc is None:
                goc = m
            print(f"  {t:<14s}{m['n']:4d}{m['P']:8.4f}{m['R']:8.4f}{m['F2A']:8.4f}"
                  f"{m['F2B']:8.4f}{m['MRR']:8.4f}{m['NDCG']:8.4f}{m['hit1']:8.4f}"
                  f"{m['hit10']:8.4f}{m['F2A']-goc['F2A']:+9.4f}")

    # ── kiểm tra MÂU THUẪN dấu giữa gold và proxy ────────────────────────────
    print(f"\n{'='*94}\nĐỐI CHIẾU DẤU  gold vs proxy  (so với tag `{tags[0]}`)\n{'='*94}")
    g0, p0 = cham(Ds[tags[0]]["refs"], G), cham(Ds[tags[0]]["refs"], P)
    for t in tags[1:]:
        gm, pm = cham(Ds[t]["refs"], G), cham(Ds[t]["refs"], P)
        for key in ("F2A", "MRR", "hit1"):
            dg, dp = gm[key] - g0[key], pm[key] - p0[key]
            cb = "MÂU THUẪN" if dg * dp < 0 and abs(dg) > 1e-4 and abs(dp) > 1e-4 else "hợp"
            print(f"  {t:<14s}{key:<6s} gold {dg:+.4f} · proxy {dp:+.4f}   → {cb}")

    # ── theo mode, chỉ trên gold ─────────────────────────────────────────────
    print(f"\n{'='*94}\nGOLD_v2 · F2(A) THEO MODE\n{'='*94}")
    md = ("single", "screen", "compare", "related")
    print(f"  {'tag':<14s}" + "".join(f"{m:>12s}" for m in md))
    for t in tags:
        row = []
        for m in md:
            qs = {q for q, x in MODE.items() if x == m}
            r = cham(Ds[t]["refs"], G, qs)
            row.append(f"{r['F2A']:12.4f}" if r else f"{'-':>12s}")
        print(f"  {t:<14s}" + "".join(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
