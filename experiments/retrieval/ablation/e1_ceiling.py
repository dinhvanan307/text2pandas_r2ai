"""E1 · Trần đánh giá (evaluation ceiling) trên gold_v2, đọc từ exp_gold_bundle.json.

KHÔNG chạy retriever. KHÔNG sửa gold. Chỉ tính lại điểm với ba giả định xếp hạng:
  (1) HIEN_TAI   – thứ hạng thật của S2
  (2) TRAN_TOP300– xếp hoàn hảo nhưng chỉ với các bảng gold ĐÃ nằm trong top-300
  (3) TRAN_TUYET – xếp hoàn hảo, giả định mọi bảng gold đều truy hồi được
Chênh (1)→(2) = phần ranking có thể lấy lại. Chênh (2)→(3) = phần recall/candidate.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def diem(B, k, cap, che_do=None):
    Ps, Rs, F_hien, F_t300, F_tuyet = [], [], [], [], []
    P3, R3, Pt, Rt = [], [], [], []
    rrs, mrr = [], []
    for qid, e in B.items():
        if che_do and e["mode"] != che_do:
            continue
        g = set(e["gold"]); refs = e["refs"]
        N = min(max(1, k * e["o"]), cap)
        rr = refs[:N]; n = len(rr)
        h = len(set(rr) & g)
        h300 = min(n, len(g & set(refs)))          # trần: gold trong top-300
        htu = min(n, len(g))                        # trần tuyệt đối
        Ps.append(h / n); Rs.append(h / len(g))
        P3.append(h300 / n); R3.append(h300 / len(g))
        Pt.append(htu / n); Rt.append(htu / len(g))
        F_hien.append(5 * h / (4 * len(g) + n))
        F_t300.append(5 * h300 / (4 * len(g) + n))
        F_tuyet.append(5 * htu / (4 * len(g) + n))
        pos = [i + 1 for i, r in enumerate(refs) if r in g]
        mrr.append(1 / pos[0] if pos else 0.0)
        rrs.append(n)
    m = lambda x: sum(x) / len(x) if x else 0.0
    return dict(n=len(Ps), P=m(Ps), R=m(Rs), F2=m(F_hien),
                P300=m(P3), R300=m(R3), F2_300=m(F_t300),
                Ptu=m(Pt), Rtu=m(Rt), F2_tuyet=m(F_tuyet), MRR=m(mrr), Nbar=m(rrs))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", default="artifacts/runs/retrieval/reaudit/exp_gold_bundle.json")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--cap", type=int, default=30)
    ap.add_argument("--out", default="artifacts/runs/retrieval/reaudit/e1_ceiling.json")
    a = ap.parse_args(argv)
    B = json.loads(Path(a.bundle).read_text(encoding="utf-8"))
    tong = diem(B, a.k, a.cap)
    print(f"GOLD v2 · {tong['n']} câu · k={a.k} cap={a.cap} · N̄={tong['Nbar']:.1f}")
    print(f"  {'kịch bản':<26s} {'P̄':>8s} {'R̄':>8s} {'F2(A)':>8s}")
    print(f"  {'-'*26} {'-'*8} {'-'*8} {'-'*8}")
    print(f"  {'1 HIỆN TẠI':<26s} {tong['P']:8.4f} {tong['R']:8.4f} {tong['F2']:8.4f}")
    print(f"  {'2 TRẦN (gold∈top300)':<26s} {tong['P300']:8.4f} {tong['R300']:8.4f} {tong['F2_300']:8.4f}")
    print(f"  {'3 TRẦN TUYỆT ĐỐI':<26s} {tong['Ptu']:8.4f} {tong['Rtu']:8.4f} {tong['F2_tuyet']:8.4f}")
    d12 = tong['F2_300'] - tong['F2']; d23 = tong['F2_tuyet'] - tong['F2_300']
    tot = tong['F2_tuyet'] - tong['F2']
    print(f"\n  khoảng trống do XẾP HẠNG (1→2) : {d12:+.4f}  ({d12/tot*100:4.1f}% tổng)")
    print(f"  khoảng trống do TRUY HỒI  (2→3) : {d23:+.4f}  ({d23/tot*100:4.1f}% tổng)")
    print(f"\n  {'mode':<9s} {'n':>3s} {'F2 nay':>8s} {'F2 trần300':>11s} {'F2 tuyệt':>9s} {'Δrank':>8s}")
    theo = {}
    for md in ("single", "screen", "compare", "related"):
        d = diem(B, a.k, a.cap, md)
        if not d["n"]:
            continue
        theo[md] = d
        print(f"  {md:<9s} {d['n']:3d} {d['F2']:8.4f} {d['F2_300']:11.4f} "
              f"{d['F2_tuyet']:9.4f} {d['F2_300']-d['F2']:+8.4f}")
    Path(a.out).write_text(json.dumps(
        {"k": a.k, "cap": a.cap, "tong": tong, "theo_mode": theo},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
