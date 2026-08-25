"""A0 bước 1 · chọn mẫu PHÂN TẦNG cho gold ĐÁP ÁN.

VÌ SAO CẦN
----------
`docs/95` chứng minh gold v2 dự báo được LB của TABLES với sai số 3,4%. Tầng
ĐÁP ÁN **không có** dụng cụ tương đương: mọi thay đổi chỉ đo được bằng cách
tiêu một lượt nộp (public ~10/ngày, private 5 TỔNG). Đó là ràng buộc chặn mọi
phương án nâng EXECUTION, không phải một tiện nghi.

NGUYÊN TẮC CHỌN MẪU
-------------------
1. Phân tầng theo `lop` của `data/curated/dev-legacy/so_hoc/phan_loai.jsonl` — vì hỏng theo
   LỚP chứ không theo câu: 100% `difference`/`max_min`/`percentage_change`/
   `count`/`sum` đang nộp query một-ô-đơn.
2. **Sàn 8 câu/lớp.** Cấp phát thuần theo tỷ lệ cho `sum` (5 câu) đúng 1 câu —
   một lớp đo bằng 1 câu là không đo được. Sàn đổi độ chính xác toàn cục lấy
   độ phân giải theo lớp; ở đây độ phân giải theo lớp mới là thứ cần.
3. Seed cố định + ghi lệnh vào chính tệp ra. Mẫu không tái hiện được thì mọi
   số đo sau nó vô giá trị.
4. **KHÔNG** dùng bất kỳ tín hiệu nào của bài nộp (confidence, thứ hạng S2,
   trạng thái engine) để chọn mẫu. Chọn mẫu theo kết quả là tự dựng một tập
   dễ rồi đo trên nó.

Chạy:
    python tools/gold_dap_an/01_chon_mau.py --n 150 --seed 20260819
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHAN_LOAI = ROOT / "data/curated/dev-legacy/so_hoc/phan_loai.jsonl"
RA = ROOT / "data/curated/dev-legacy/gold_dap_an/mau_v1.jsonl"

SAN = 8  # sàn tối thiểu mỗi lớp


def _doc_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def cap_phat(dem: dict[str, int], n: int, san: int = SAN) -> dict[str, int]:
    """Cấp phát theo tỷ lệ NHƯNG bảo đảm sàn, không vượt cỡ lớp.

    Thuật toán: đặt sàn trước, chia phần dư theo tỷ lệ số câu CÒN LẠI, rồi
    trả phần lẻ theo largest-remainder để tổng khớp `n` chính xác.
    """
    lop = sorted(dem, key=lambda k: (-dem[k], k))
    out = {k: min(san, dem[k]) for k in lop}
    con = n - sum(out.values())
    if con <= 0:
        return out
    du = {k: dem[k] - out[k] for k in lop}
    tong_du = sum(du.values())
    if tong_du == 0:
        return out
    tho = {k: con * du[k] / tong_du for k in lop}
    for k in lop:
        out[k] += int(tho[k])
    # largest-remainder cho phần lẻ
    le = sorted(lop, key=lambda k: (-(tho[k] - int(tho[k])), k))
    i = 0
    while sum(out.values()) < n and i < len(le) * 4:
        k = le[i % len(le)]
        if out[k] < dem[k]:
            out[k] += 1
        i += 1
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20260819)
    ap.add_argument("--san", type=int, default=SAN)
    a = ap.parse_args(argv)

    hoi = _doc_jsonl(PHAN_LOAI)
    theo_lop: dict[str, list[dict]] = collections.defaultdict(list)
    for r in hoi:
        theo_lop[r["lop"]].append(r)
    dem = {k: len(v) for k, v in theo_lop.items()}
    quota = cap_phat(dem, a.n, a.san)

    rng = random.Random(a.seed)
    chon: list[dict] = []
    for lop in sorted(theo_lop):
        pool = sorted(theo_lop[lop], key=lambda r: r["id"])
        lay = rng.sample(pool, quota[lop])
        for r in sorted(lay, key=lambda r: r["id"]):
            chon.append({
                "qid": r["id"],
                "question": r["question"],
                "lop": r["lop"],
                "don_vi_hoi": r["don_vi_hoi"],
                "tang": lop,
            })
    chon.sort(key=lambda r: r["qid"])

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        sha = "?"
    meta = {
        "_meta": True,
        "dataset": str(PHAN_LOAI.relative_to(ROOT)),
        "n_yeu_cau": a.n,
        "n_thuc_te": len(chon),
        "seed": a.seed,
        "san": a.san,
        "quota": quota,
        "co_lop": dem,
        "git": sha,
        "lenh": f"python tools/gold_dap_an/01_chon_mau.py --n {a.n} --seed {a.seed} --san {a.san}",
        "tao_luc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    RA.parent.mkdir(parents=True, exist_ok=True)
    with RA.open("w", encoding="utf-8") as f:
        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        for r in chon:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{'lớp':20}{'cỡ':>6}{'chọn':>7}{'tỷ lệ':>9}")
    for lop in sorted(dem, key=lambda k: -dem[k]):
        print(f"{lop:20}{dem[lop]:>6}{quota[lop]:>7}{100*quota[lop]/dem[lop]:>8.1f}%")
    print(f"{'TỔNG':20}{sum(dem.values()):>6}{len(chon):>7}")
    print(f"-> {RA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
