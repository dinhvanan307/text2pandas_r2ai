"""P1 · Paired bootstrap + sign test cho Δ giữa hai tag, trên gold_v2.

docs/119 §5.5: point estimate không thay được khoảng tin cậy.
Bootstrap THEO CÂU (paired), 10.000 lần lặp, seed khoá cứng.
"""
from __future__ import annotations
import argparse, json, math, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RE = ROOT / "artifacts/runs/retrieval/reaudit"
K, CAP = 3, 30
SEED = 20260821
B = 10000


def per_qid(D, G):
    out = {}
    for q, e in D.items():
        g = G.get(q)
        if not g:
            continue
        refs = e["refs"]; N = min(max(1, K * e["o"]), CAP)
        rr = refs[:N]; n = len(rr); h = len(set(rr) & g)
        pos = [i + 1 for i, x in enumerate(refs) if x in g]
        dcg = sum(1 / math.log2(i + 2) for i, x in enumerate(rr) if x in g)
        idcg = sum(1 / math.log2(i + 2) for i in range(min(len(g), n)))
        out[q] = {"F2A": 5 * h / (4 * len(g) + n), "recall": h / len(g),
                  "precision": h / n, "MRR": 1 / pos[0] if pos else 0.0,
                  "hit1": 1.0 if 1 in pos else 0.0,
                  "hit10": 1.0 if any(p <= 10 for p in pos) else 0.0,
                  "NDCG": dcg / idcg if idcg else 0.0}
    return out


def boot(dl, b=B, seed=SEED):
    n = len(dl); rng = random.Random(seed); xs = []
    for _ in range(b):
        xs.append(sum(dl[rng.randrange(n)] for _ in range(n)) / n)
    xs.sort()
    return xs[int(0.025 * b)], xs[int(0.975 * b) - 1]


def sign_test(dl):
    pos = sum(1 for d in dl if d > 1e-12)
    neg = sum(1 for d in dl if d < -1e-12)
    m = pos + neg
    if not m:
        return pos, neg, len(dl) - m, 1.0
    # nhị thức hai phía, p=0.5
    k = min(pos, neg)
    c = sum(math.comb(m, i) for i in range(k + 1))
    return pos, neg, len(dl) - m, min(1.0, 2 * c / 2 ** m)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="base")
    ap.add_argument("--b", default="pri060_bsis")
    ap.add_argument("--subset", default="", help="tệp JSON danh sách qid (chuỗi)")
    ap.add_argument("--label", default="dev_95")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    BD = json.loads((RE / "exp_gold_bundle.json").read_text(encoding="utf-8"))
    G = {q: set(e["gold"]) for q, e in BD.items()}
    MODE = {q: e["mode"] for q, e in BD.items()}
    DA = json.loads((RE / f"exp_refs_{a.a}.json").read_text(encoding="utf-8"))["refs"]
    DB = json.loads((RE / f"exp_refs_{a.b}.json").read_text(encoding="utf-8"))["refs"]
    PA, PB = per_qid(DA, G), per_qid(DB, G)
    qs = sorted(set(PA) & set(PB), key=int)
    if a.subset:
        keep = set(json.loads(Path(a.subset).read_text(encoding="utf-8")))
        qs = [q for q in qs if q in keep or int(q) in keep]

    res = {"label": a.label, "a": a.a, "b": a.b, "n": len(qs),
           "bootstrap": {"B": B, "seed": SEED, "method": "paired, resample QID"},
           "metrics": {}}
    print(f"{a.label}: {a.a} → {a.b} · n={len(qs)} · bootstrap B={B} seed={SEED}")
    print(f"  {'metric':<9s}{'A':>9s}{'B':>9s}{'Δ':>10s}{'CI95 thấp':>11s}{'CI95 cao':>10s}"
          f"{'+':>4s}{'0':>4s}{'−':>4s}{'p_sign':>9s}")
    for m in ("F2A", "recall", "precision", "MRR", "hit1", "hit10", "NDCG"):
        dl = [PB[q][m] - PA[q][m] for q in qs]
        va = sum(PA[q][m] for q in qs) / len(qs)
        vb = sum(PB[q][m] for q in qs) / len(qs)
        lo, hi = boot(dl)
        p, n_, z, pv = sign_test(dl)
        res["metrics"][m] = {"A": va, "B": vb, "delta": vb - va, "ci95": [lo, hi],
                             "n_pos": p, "n_zero": z, "n_neg": n_, "p_sign": pv}
        print(f"  {m:<9s}{va:9.4f}{vb:9.4f}{vb-va:+10.4f}{lo:+11.4f}{hi:+10.4f}"
              f"{p:4d}{z:4d}{n_:4d}{pv:9.4f}")
    res["per_mode"] = {}
    for md in ("single", "screen", "compare", "related"):
        sub = [q for q in qs if MODE[q] == md]
        if not sub:
            continue
        dl = [PB[q]["F2A"] - PA[q]["F2A"] for q in sub]
        lo, hi = boot(dl)
        res["per_mode"][md] = {"n": len(sub),
                               "A": sum(PA[q]["F2A"] for q in sub) / len(sub),
                               "B": sum(PB[q]["F2A"] for q in sub) / len(sub),
                               "delta": sum(dl) / len(dl), "ci95": [lo, hi]}
    print(f"\n  {'mode':<9s}{'n':>4s}{'ΔF2A':>10s}{'CI95':>24s}")
    for md, v in res["per_mode"].items():
        print(f"  {md:<9s}{v['n']:4d}{v['delta']:+10.4f}   [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}]")
    res["per_qid_delta"] = {q: {m: PB[q][m] - PA[q][m] for m in
                                ("F2A", "recall", "MRR", "hit1")} for q in qs}
    out = Path(a.out) if a.out else RE / f"e2_stats_{a.label}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {out.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
