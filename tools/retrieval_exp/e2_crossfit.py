"""P0-C/P1 · (a) công suất của tập 25 UNCERTAIN, (b) cross-fitting KHAI BÁO TRƯỚC.

Chạy ĐÚNG theo `e2_eval_protocol_v1.json` §5. Không chạy lại retrieval:
mọi tag trong lưới đều đã có `exp_refs_*.json`.
"""
from __future__ import annotations
import json, math, random, statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RE = ROOT / "artifacts/retrieval/reaudit"
K, CAP = 3, 30
GRID = {0.00: "base", 0.15: "pri015", 0.30: "pri030_bsis",
        0.60: "pri060_bsis", 1.00: "pri100_bsis", 1.50: "pri150_bsis"}
REPEATS, CV_SEED = 200, 20260822


def f2_per_qid(D, G):
    out = {}
    for q, e in D.items():
        g = G.get(q)
        if not g:
            continue
        N = min(max(1, K * e["o"]), CAP); rr = e["refs"][:N]
        out[q] = 5 * len(set(rr) & g) / (4 * len(g) + len(rr))
    return out


def main() -> int:
    B = json.loads((RE / "exp_gold_bundle.json").read_text(encoding="utf-8"))
    G = {q: set(e["gold"]) for q, e in B.items()}
    MODE = {q: e["mode"] for q, e in B.items()}
    P = {b: f2_per_qid(json.loads((RE / f"exp_refs_{t}.json").read_text(encoding="utf-8"))["refs"], G)
         for b, t in GRID.items()}
    qs = sorted(P[0.0], key=int)

    # ── (a) CÔNG SUẤT của một tập cỡ nhỏ ────────────────────────────────────
    d = [P[0.60][q] - P[0.00][q] for q in qs]
    sd = st.pstdev(d)
    d_screen = [P[0.60][q] - P[0.00][q] for q in qs if MODE[q] in ("screen", "related")]
    sd_s = st.pstdev(d_screen)
    print("(a) CÔNG SUẤT")
    print(f"  Δ per-QID trên dev: mean {st.mean(d):+.4f} · SD {sd:.4f} (n={len(qs)})")
    print(f"  riêng screen+related: mean {st.mean(d_screen):+.4f} · SD {sd_s:.4f} (n={len(d_screen)})")
    pw = {}
    for n in (10, 20, 25, 32, 50, 95, 150, 300):
        half = 1.96 * sd / math.sqrt(n)
        # công suất phát hiện hiệu ứng đúng bằng mean quan sát được
        z = abs(st.mean(d)) / (sd / math.sqrt(n)) - 1.96
        power = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        pw[n] = {"ci_half_width": round(half, 4), "power_at_observed_effect": round(power, 3)}
        print(f"  n={n:<4d} nửa-khoảng CI95 = ±{half:.4f}   công suất ≈ {power:.2f}")
    n_needed = math.ceil((1.96 + 0.8416) ** 2 * sd ** 2 / st.mean(d) ** 2)
    print(f"  ⇒ cần n ≈ {n_needed} QID để đạt công suất 80% ở hiệu ứng quan sát được")

    # ── (b) CROSS-FITTING khai báo trước ────────────────────────────────────
    rng = random.Random(CV_SEED)
    picks, deltas, dev_delta = [], [], []
    for _ in range(REPEATS):
        sh = qs[:]; rng.shuffle(sh)
        h = len(sh) // 2
        for tr, te in ((sh[:h], sh[h:]), (sh[h:], sh[:h])):
            best = max(GRID, key=lambda b: sum(P[b][q] for q in tr) / len(tr))
            picks.append(best)
            deltas.append(sum(P[best][q] - P[0.0][q] for q in te) / len(te))
            dev_delta.append(sum(P[0.60][q] - P[0.0][q] for q in te) / len(te))
    from collections import Counter
    deltas.sort()
    lo, hi = deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas)) - 1]
    print(f"\n(b) CROSS-FITTING · {REPEATS} lần lặp × 2 fold = {len(deltas)} lần đo · seed {CV_SEED}")
    print(f"  boost được CHỌN trên nửa train: {dict(Counter(picks).most_common())}")
    print(f"  Δ F2(A) trên nửa TEST: mean {st.mean(deltas):+.4f} · median {st.median(deltas):+.4f}")
    print(f"  khoảng 95% của phân bố Δ test: [{lo:+.4f}, {hi:+.4f}]")
    print(f"  tỉ lệ fold có Δ > 0: {sum(1 for x in deltas if x>0)/len(deltas):.3f}")
    print(f"  (đối chiếu) nếu ÁP CỨNG 0,60 lên nửa test: mean {st.mean(dev_delta):+.4f}")
    print(f"  co ngót do chọn tham số: {st.mean(deltas)-st.mean(dev_delta):+.4f}")

    out = {"power_analysis": {"sd_per_qid_delta": sd, "mean_per_qid_delta": st.mean(d),
                              "sd_screen_related": sd_s, "n_can_de_power_80": n_needed,
                              "by_n": pw,
                              "ket_luan": ("Tập 25 UNCERTAIN cho nửa-khoảng CI95 ≈ "
                                           f"±{1.96*sd/math.sqrt(25):.4f}, rộng hơn chính hiệu ứng "
                                           f"({st.mean(d):+.4f}). KHÔNG đủ công suất để chấp nhận "
                                           "hay bác bỏ E2. Ngoài ra 25 QID này KHÔNG ngẫu nhiên — "
                                           "chúng là phần khó gán nhãn nhất (13 pool_miss, 3 a6_gap), "
                                           "nên còn lệch mẫu chứ không chỉ thiếu cỡ mẫu.")},
           "cross_fitting": {"repeats": REPEATS, "seed": CV_SEED, "folds": len(deltas),
                             "grid": list(GRID), "picked": dict(Counter(picks)),
                             "test_delta_mean": st.mean(deltas),
                             "test_delta_median": st.median(deltas),
                             "test_delta_p2.5": lo, "test_delta_p97.5": hi,
                             "frac_folds_positive": sum(1 for x in deltas if x > 0) / len(deltas),
                             "fixed_060_test_delta_mean": st.mean(dev_delta),
                             "shrinkage": st.mean(deltas) - st.mean(dev_delta),
                             "gioi_han": ("Việc chọn PRIMARY_KINDS (BS+IS, loại CF) vẫn nằm NGOÀI "
                                          "vòng CV — chỉ có `boost` được chọn lại trên train. "
                                          "Vì vậy con số này VẪN lạc quan hơn một held-out thật.")}}
    (RE / "e2_crossfit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
