"""So GHÉP CẶP hai checkpoint BẤT KỲ theo đường dẫn tệp — không qua `cfg_sha`.

VÌ SAO CẦN MỘT CÔNG CỤ RIÊNG
----------------------------
`evalkit ab` tra checkpoint bằng `tag → _load_cfg(tag).checkpoint_name`, tức là
nó tính `cfg_sha` BẰNG CODE ĐANG CHẠY. Đúng cho mọi phép so bình thường, nhưng
KHÔNG dùng được cho đúng phép so mà P0-1 cần:

    trước = checkpoint sinh bởi code CŨ  (SCHEMA_VERSION = evalkit-1)
    sau   = checkpoint sinh bởi code MỚI (SCHEMA_VERSION = evalkit-2)

Hai bên có `cfg_sha` khác nhau *vì code khác nhau* — đó chính là điều cần đo.
Chạy `ab` từ cây code nào cũng chỉ thấy được một trong hai. Nên ở đây nhận
ĐƯỜNG DẪN TỆP, và cố ý KHÔNG gọi `guard_single_config` chéo hai bên.

BA ĐIỀU KIỆN ĐỂ CON SỐ NÀY CÓ NGHĨA — kiểm tự động, không tin lời
  1. mỗi tệp chỉ chứa MỘT `cfg_sha`            (guard trong từng bên)
  2. hai bên khác nhau ĐÚNG một biến           (người gọi bảo đảm; in ra để đọc)
  3. gold GIỐNG NHAU từng câu                  (kiểm `n_gold` + `gold_how`)

Điều 3 là điều dễ mất nhất: nếu bản sửa cũng đổi cách dựng gold thì "cải thiện"
có thể chỉ là gold dễ hơn. Script DỪNG nếu gold lệch quá ngưỡng, và in ra vài ca
lệch đầu tiên để soi.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.evalkit.metrics import (f2_at_k, f2_at_policy,  # noqa: E402
                                       gold_size_stats, hit_rate_at_policy,
                                       metric_block)
from text2pandas.pipelines.retrieval.evalkit.report import (guard_single_config, load_rows,  # noqa: E402
                                      policy_n_map, to_outcomes)

KS = (1, 3, 5, 10, 20, 50)


def _boc(p: Path) -> tuple[dict[int, dict], str]:
    rows = load_rows(p)
    sha = guard_single_config(rows)
    return {r["id"]: r for r in rows}, sha


def _kiem_gold(a: dict[int, dict], b: dict[int, dict], ids: list[int],
               nguong: int = 0) -> list[str]:
    """Gold phải KHÔNG đổi giữa hai arm. Trả về danh sách ca lệch."""
    lech = []
    for i in ids:
        ra, rb = a[i], b[i]
        if (ra.get("n_gold"), ra.get("gold_ok"), ra.get("gold_how")) != \
           (rb.get("n_gold"), rb.get("gold_ok"), rb.get("gold_how")):
            lech.append(f"q{i}: A(n={ra.get('n_gold')},{ra.get('gold_how')}) "
                        f"≠ B(n={rb.get('n_gold')},{rb.get('gold_how')})")
    return lech


def _khoi(rows: list[dict], nhan: str) -> dict:
    oc = to_outcomes(rows)
    nmap = policy_n_map(rows)
    mb = metric_block(oc, KS, n_total=len(rows))
    g1 = [r for r in oc if r.measurable and r.n_gold == 1]
    return {
        "nhan": nhan,
        "n": len(rows), "n_do": mb.n_measured, "coverage": mb.coverage,
        "cand_hit": mb.candidate_hit_rate, "mrr": mb.mrr,
        "per_k": mb.per_k,
        "f2_policy": f2_at_policy(oc, nmap),
        "hit_policy": hit_rate_at_policy(oc, nmap),
        "f2_1_g1": f2_at_k(g1, 1) if g1 else 0.0,
        "n_g1": len(g1),
        "gold": gold_size_stats(oc),
    }


def _bang(A: dict, B: dict) -> str:
    def dong(ten: str, va: float, vb: float, nho_hon_tot: bool = False) -> str:
        d = vb - va
        dau = "→" if abs(d) < 5e-5 else ("▲" if (d > 0) != nho_hon_tot else "▼")
        return f"  {ten:<24s} {va:8.4f}  {vb:8.4f}   {d:+8.4f}  {dau}"

    L = [f"  {'chỉ số':<24s} {A['nhan']:>8s}  {B['nhan']:>8s}   {'Δ':>8s}",
         f"  {'-' * 24} {'-' * 8}  {'-' * 8}   {'-' * 8}",
         dong("candidate hit rate", A["cand_hit"], B["cand_hit"]),
         dong("MRR", A["mrr"], B["mrr"])]
    for k in KS:
        L.append(dong(f"hit@{k}", A["per_k"][k]["hit_rate"], B["per_k"][k]["hit_rate"]))
    for k in (1, 10):
        L.append(dong(f"Recall@{k}", A["per_k"][k]["recall"], B["per_k"][k]["recall"]))
        L.append(dong(f"nDCG@{k}", A["per_k"][k]["ndcg"], B["per_k"][k]["ndcg"]))
    L += [dong("F2@N* (so tương đối)", A["f2_policy"], B["f2_policy"]),
          dong("hit@N*", A["hit_policy"], B["hit_policy"]),
          dong(f"F2@1 |gold|=1 (n={A['n_g1']})", A["f2_1_g1"], B["f2_1_g1"])]
    return "\n".join(L)


def _doi_hang(a: dict[int, dict], b: dict[int, dict], ids: list[int],
              k: int = 10) -> tuple[list, list]:
    """Câu VÀO / RỚT khỏi top-k. Đây là thứ đọc được, khác với delta trung bình."""
    def hang(r: dict) -> int:
        h = r.get("hits_at_rank") or ()
        return min(h) if h else 10 ** 6
    vao, rot = [], []
    for i in ids:
        if not a[i].get("gold_ok"):
            continue
        ra, rb = hang(a[i]), hang(b[i])
        if ra > k >= rb:
            vao.append((i, ra, rb))
        elif rb > k >= ra:
            rot.append((i, ra, rb))
    return vao, rot


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="p0_before_after")
    ap.add_argument("--truoc", required=True, help="checkpoint arm A (.jsonl)")
    ap.add_argument("--sau", required=True, help="checkpoint arm B (.jsonl)")
    ap.add_argument("--nhan-truoc", default="TRƯỚC")
    ap.add_argument("--nhan-sau", default="SAU")
    ap.add_argument("--gold-lech-toi-da", type=int, default=0,
                    help="số ca gold được phép lệch; >0 phải có lý do ghi rõ")
    ap.add_argument("--out", default="")
    ns = ap.parse_args(argv)

    a, sha_a = _boc(Path(ns.truoc))
    b, sha_b = _boc(Path(ns.sau))
    ids = sorted(set(a) & set(b))
    if not ids:
        print("✗ hai checkpoint không có câu nào chung")
        return 2

    print(f"\nA · {ns.nhan_truoc:<12s} {Path(ns.truoc).name}  cfg_sha={sha_a}  {len(a)} câu")
    print(f"B · {ns.nhan_sau:<12s} {Path(ns.sau).name}  cfg_sha={sha_b}  {len(b)} câu")
    print(f"ghép cặp theo id: {len(ids)} câu"
          f"  (A riêng {len(set(a) - set(b))} · B riêng {len(set(b) - set(a))})")
    if sha_a == sha_b:
        print("⚠ HAI BÊN CÙNG cfg_sha — nếu đây là phép so trước/sau theo CODE thì")
        print("  `SCHEMA_VERSION` chưa được bump, và số liệu KHÔNG phản ánh bản sửa.")

    lech = _kiem_gold(a, b, ids)
    print(f"\ngold giống nhau: {len(ids) - len(lech)}/{len(ids)} câu")
    if lech:
        for s in lech[:6]:
            print(f"  ! {s}")
        if len(lech) > ns.gold_lech_toi_da:
            print(f"\n✗ DỪNG · {len(lech)} câu lệch gold > ngưỡng {ns.gold_lech_toi_da}.")
            print("  Khi gold đổi thì delta KHÔNG quy được cho bản sửa. Sửa nguyên")
            print("  nhân (hoặc nêu lý do rồi nới --gold-lech-toi-da) trước khi đọc số.")
            return 3

    A = _khoi([a[i] for i in ids], ns.nhan_truoc)
    B = _khoi([b[i] for i in ids], ns.nhan_sau)
    print(f"\nđo được (gold tin cậy): A {A['n_do']}/{A['n']} ({A['coverage']:.1%})"
          f"  ·  B {B['n_do']}/{B['n']} ({B['coverage']:.1%})")
    print(f"|gold| median A {A['gold'].get('median')} · B {B['gold'].get('median')}"
          f"   |gold|=1: A {A['gold'].get('n_exactly_one')} · B {B['gold'].get('n_exactly_one')}")
    print()
    print(_bang(A, B))

    vao, rot = _doi_hang(a, b, ids, 10)
    print(f"\nvào top-10 nhờ {ns.nhan_sau}: {len(vao)} câu"
          f"  ·  rớt khỏi top-10: {len(rot)} câu   (thực thu {len(vao) - len(rot):+d})")
    for lbl, v in (("+", vao), ("−", rot)):
        for i, ra, rb in v[:8]:
            f = lambda x: "-" if x > 10 ** 5 else str(x)  # noqa: E731
            print(f"  {lbl} q{i:<5d} hạng {f(ra)} → {f(rb)}")

    hows = Counter(a[i].get("gold_how") for i in ids)
    print("\ngold_how (chung cho cả hai arm): "
          + " · ".join(f"{k}={v}" for k, v in hows.most_common(6)))

    if ns.out:
        Path(ns.out).write_text(json.dumps(
            {"a": A, "b": B, "paired": len(ids), "sha_a": sha_a, "sha_b": sha_b,
             "vao_top10": vao[:80], "rot_top10": rot[:80],
             "gold_lech": lech[:40]},
            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"\n→ {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
