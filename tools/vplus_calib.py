"""V+ bước 3 · Bộ suy `g_BTC` + tiền đăng ký dự phóng.

ƯỚC LƯỢNG (đúng công thức plan `docs/92` §1.1 / `docs/93`):

    ĝ = P̄ · N̄ / R̄

Dẫn xuất và GIẢ ĐỊNH — phải đọc kèm, vì nó quyết định nhánh nào đáng tin:

    P̄ = mean(h_i / N_i)          R̄ = mean(h_i / g_i)
    Nếu N_i ≡ N̄ (hằng số) thì  P̄·N̄ = mean(h_i), nên
        ĝ = mean(h_i) / mean(h_i / g_i)
    tức **trung bình điều hoà có trọng số h_i** của g_i — KHÔNG phải trung bình
    cộng. Khi N_i biến thiên mạnh, `P̄·N̄ ≠ mean(h_i)` và ước lượng lệch thêm.

⇒ Nhánh Z (`k=1, cap=10`) có `N_i` gần như hằng (phần lớn câu N_i = 1) nên là
nhánh hiệu chuẩn. Nhánh X (`k=3, cap=30`, N_i từ 3 đến 30) chỉ làm NEO.

Bộ này chạy được ở hai chế độ:
  * `--offline`  đo trên gold v2 — nơi ta BIẾT g thật ⇒ đo được ĐỘ LỆCH của
                 chính ước lượng, trước khi tiêu một lượt nộp.
  * `--lb`       nhập (P, R, N̄) trả về từ bảng xếp hạng cho từng nhánh ⇒ suy g.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "curated" / "dev-legacy"
VP = ROOT / "artifacts" / "runs" / "retrieval" / "vplus"

X_K, X_CAP = 3, 30
Z_K, Z_CAP = 1, 10


def g_hat(P: float, R: float, Nbar: float) -> float:
    return P * Nbar / R if R else float("nan")


def offline(db: str):
    D = json.loads((VP / "refs_1012.json").read_text())
    nh = json.loads((VP / "cal1_nhanh.json").read_text())
    arm = {}
    for k in ("X", "Z"):
        for q in nh[k]["qids"]:
            arm[q] = k
    conn = sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True)
    u2r = {u: ev.replace("|line:", "|") for u, ev in conn.execute(
        "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
    G = {}
    for line in (DEV / "gold_v2.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("gold_table_uids"):
            G[r["id"]] = {u2r[u] for u in r["gold_table_uids"] if u in u2r}

    print("=" * 92)
    print("OFFLINE · kiểm ước lượng ĝ = P̄·N̄/R̄ trên gold v2 (nơi BIẾT g thật)")
    print("=" * 92)
    print("  nhánh | n  | N̄     | P̄      | R̄      |  ĝ    | ḡ thật | lệch   | ḡ điều hoà")
    ket = {}
    for k, kk, cap in (("X", X_K, X_CAP), ("Z", Z_K, Z_CAP)):
        qs = [q for q in sorted(G) if arm.get(q) == k]
        if not qs:
            continue
        Ps, Rs, Ns, hs, gs = [], [], [], [], []
        for q in qs:
            g = G[q]
            N = min(max(1, kk * D[str(q)]["o"]), cap)
            rr = D[str(q)]["refs"][:N]
            h = len(set(rr) & g)
            Ps.append(h / len(rr)); Rs.append(h / len(g))
            Ns.append(len(rr)); hs.append(h); gs.append(len(g))
        P = sum(Ps) / len(Ps); R = sum(Rs) / len(Rs); Nb = sum(Ns) / len(Ns)
        gh = g_hat(P, R, Nb)
        gtrue = sum(gs) / len(gs)
        # trung bình điều hoà có trọng số h — thứ ĝ THỰC SỰ ước lượng
        num = sum(hs); den = sum(h / g for h, g in zip(hs, gs))
        gharm = num / den if den else float("nan")
        ket[k] = {"n": len(qs), "N_tb": Nb, "P": P, "R": R, "g_hat": gh,
                  "g_thuc": gtrue, "g_dieu_hoa": gharm}
        print(f"    {k}   |{len(qs):>3} | {Nb:>5.3f} | {P:.4f} | {R:.4f} | {gh:>5.3f} | "
              f"{gtrue:>5.3f}  | {gh-gtrue:+.3f} | {gharm:>5.3f}")
    print("\n  Đọc bảng: cột `ĝ` so với `ḡ điều hoà` mới là phép so ĐÚNG — ĝ ước lượng")
    print("  trung bình ĐIỀU HOÀ có trọng số h, không phải trung bình cộng `ḡ thật`.")

    # phân bố N_i của nhánh Z — điều kiện để ước lượng chặt
    nz = {}
    for q in nh["Z"]["qids"]:
        N = min(max(1, Z_K * D[str(q)]["o"]), Z_CAP)
        nz[N] = nz.get(N, 0) + 1
    tot = sum(nz.values())
    print(f"\n  Phân bố N_i nhánh Z (toàn 468 câu): " +
          " · ".join(f"N={k}:{v} ({100*v/tot:.0f}%)" for k, v in sorted(nz.items())))
    print(f"  ⇒ {100*nz.get(1,0)/tot:.0f}% câu nhánh Z có N_i = 1 ⇒ giả định 'N_i hằng' chặt nhất ở đây.")
    (VP / "calib_offline.json").write_text(json.dumps(ket, ensure_ascii=False))
    return ket


def tu_lb(a):
    print("=" * 92)
    print("TỪ BẢNG XẾP HẠNG · suy g cho từng nhánh")
    print("=" * 92)
    for k, P, R, Nb in (("X", a.xp, a.xr, a.xn), ("Z", a.zp, a.zr, a.zn)):
        if P is None:
            continue
        print(f"  {k}: P={P:.4f} R={R:.4f} N̄={Nb:.3f}  ⇒  ĝ = {g_hat(P,R,Nb):.3f}")


def main(argv):
    ap = argparse.ArgumentParser(prog="vplus_calib")
    ap.add_argument("--db")
    ap.add_argument("--offline", action="store_true")
    for x in ("xp", "xr", "xn", "zp", "zr", "zn"):
        ap.add_argument(f"--{x}", type=float)
    a = ap.parse_args(argv)
    if a.offline:
        offline(a.db)
    if a.xp is not None or a.zp is not None:
        tu_lb(a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
