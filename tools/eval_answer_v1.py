"""Bộ đo OFFLINE cho tầng ĐÁP ÁN — dụng cụ còn thiếu của dự án.

VÌ SAO TỆP NÀY TỒN TẠI
----------------------
`docs/95` chứng minh gold v2 dự báo được LB của TABLES với sai số 3,4%: đó là
lý do tầng Retrieval lặp được mà không tiêu lượt nộp. Tầng ĐÁP ÁN **không có**
thứ tương đương. Hệ quả đo được: EXECUTION đi từ 0,0494 → 0,1087 mất hai lượt
nộp, và không ai biết thay đổi nào đóng góp bao nhiêu.

Ràng buộc làm điều đó đắt: public ~10 bài/ngày (C16 ⚠️), private **5 bài TỔNG**
(C17 ⚠️). Không dựng dụng cụ đo trước thì mọi phương án nâng EXECUTION đều là
đoán có kèm hoá đơn.

CÁI TỆP NÀY ĐO — VÀ CÁI NÓ KHÔNG ĐO
-----------------------------------
ĐO:  `answer` của bài nộp so với `dap_an_gold` (`gold_dap_an_v1.jsonl`),
     theo NGƯỠNG TƯƠNG ĐỐI tham số hoá.
KHÔNG ĐO: Answer Accuracy chính thức của BTC. Ngưỡng sai số của C09 **chưa
     công bố** (Q5 §7 của `COMPETITION_SPEC`). Vì vậy `--nguong` là tham số,
     mặc định 1%, và mọi báo cáo BẮT BUỘC in ngưỡng đã dùng.

BA CẢNH BÁO PHẢI ĐỌC TRƯỚC KHI TRÍCH SỐ
---------------------------------------
1. **Đây là mốc TƯƠNG ĐỐI, chưa phải mốc TUYỆT ĐỐI.** Gold v1 mới phủ 30% mẫu
   (45/150). Tập giải được thiên về câu có nhãn rõ ⇒ thiên lệch sống sót cùng
   chiều với thứ `docs/94` đã đo trên gold BẢNG (−0,0124 F2). Dùng để so A/B
   giữa hai bài nộp thì an toàn; dùng để tuyên bố "EXECUTION sẽ là X" thì không.
2. **Hệ số hiệu chuẩn phải đo, không được giả định.** Chạy `--hieu-chuan` trên
   các bài ĐÃ CÓ điểm LB (P0E 0,0494 · P0G2 0,1087) để suy tỷ lệ LB/offline,
   đúng cách `docs/95` làm cho TABLES.
3. **`answer` ≡ `eval(pandas_query)` là bất biến ĐÃ kiểm** (`docs/96` §4,
   120/120). Nên so `answer` là hợp lệ cho EXECUTION. Nếu bất biến ấy vỡ ở một
   bài nộp nào đó thì số của tệp này vô nghĩa cho bài ấy — kiểm lại trước.

Chạy:
    python tools/eval_answer_v1.py data/submissions/submission_P0G2.zip
    python tools/eval_answer_v1.py --hieu-chuan
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl"
SUB = ROOT / "data/submissions"

# Điểm neo LB đã biết (docs/95 §"Ba lượt nộp"). Dùng để hiệu chuẩn, KHÔNG dùng
# để tối ưu — tối ưu thẳng lên leaderboard là điều bị cấm trong ràng buộc dự án.
NEO_LB = {"submission_P0E.zip": 0.0494, "submission_P0G2.zip": 0.1087,
          "submission_CAL1Z.zip": 0.1087}


def doc_gold() -> list[dict]:
    rows = [json.loads(l) for l in GOLD.open(encoding="utf-8") if l.strip()]
    return [r for r in rows if not r.get("_meta")]


def doc_bai_nop(p: Path) -> dict[int, dict]:
    with zipfile.ZipFile(p) as z:
        ten = [n for n in z.namelist()
               if n.endswith(".json") and "/" not in n.strip("/")]
        if len(ten) != 1:                       # C15 · ZIP chỉ chứa 1 file .json
            raise SystemExit(f"{p.name}: cần đúng 1 .json cấp ngoài, thấy {ten}")
        return {r["id"]: r for r in json.loads(z.read(ten[0]))}


def khop(got, want, nguong: float) -> bool:
    """So theo sai số TƯƠNG ĐỐI. `want == 0` thì so tuyệt đối với chính ngưỡng."""
    try:
        g, w = float(got), float(want)
    except (TypeError, ValueError):
        return False
    if g != g or w != w:                        # NaN
        return False
    if w == 0:
        return abs(g) <= nguong
    return abs(g - w) / abs(w) <= nguong


def do_mot_bai(p: Path, gold: list[dict], nguong: float) -> dict:
    nop = doc_bai_nop(p)
    theo_lop: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    trat: list[dict] = []
    for g in gold:
        c = theo_lop[g["lop"]]
        c["n"] += 1
        r = nop.get(g["qid"])
        if r is None:
            c["thieu"] += 1
            continue
        if khop(r.get("answer"), g["dap_an_gold"], nguong):
            c["dung"] += 1
        else:
            c["sai"] += 1
            trat.append({"qid": g["qid"], "lop": g["lop"],
                         "gold": g["dap_an_gold"], "nop": r.get("answer"),
                         "don_vi": g["don_vi_hoi"]})
    n = sum(c.get("n", 0) for c in theo_lop.values())
    d = sum(c.get("dung", 0) for c in theo_lop.values())
    return {"bai": p.name, "n": n, "dung": d, "acc": d / n if n else 0.0,
            "theo_lop": {k: dict(v) for k, v in theo_lop.items()}, "trat": trat}


def in_bang(kq: dict, nguong: float) -> None:
    print(f"\n══ {kq['bai']} · ngưỡng tương đối {nguong:.1%} · gold n={kq['n']}")
    print(f"{'lớp':20}{'n':>4}{'đúng':>6}{'acc':>8}")
    for lop, c in sorted(kq["theo_lop"].items(), key=lambda x: -x[1]["n"]):
        n, d = c.get("n", 0), c.get("dung", 0)
        print(f"{lop:20}{n:>4}{d:>6}{(d / n if n else 0):>7.1%}")
    print(f"{'TỔNG':20}{kq['n']:>4}{kq['dung']:>6}{kq['acc']:>7.1%}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bai", nargs="*", help="đường dẫn .zip bài nộp")
    ap.add_argument("--nguong", type=float, default=0.01,
                    help="sai số TƯƠNG ĐỐI cho phép (C09 chưa công bố)")
    ap.add_argument("--hieu-chuan", action="store_true",
                    help="chạy trên các bài có điểm LB đã biết và suy hệ số")
    ap.add_argument("--trat", type=int, default=0, help="in N ca trật")
    a = ap.parse_args(argv)

    gold = doc_gold()
    if not gold:
        raise SystemExit("gold rỗng — chạy tools/gold_dap_an/02_phan_xu_o.py trước")

    bai = [Path(b) for b in a.bai] or [SUB / n for n in sorted(NEO_LB)]
    ket: list[dict] = []
    for p in bai:
        if not p.is_file():
            print(f"bỏ qua (không có): {p}")
            continue
        kq = do_mot_bai(p, gold, a.nguong)
        ket.append(kq)
        in_bang(kq, a.nguong)
        for t in kq["trat"][:a.trat]:
            print(f"   q{t['qid']:<5}{t['lop']:<18} gold={t['gold']!r} nộp={t['nop']!r}")

    if a.hieu_chuan or not a.bai:
        print("\n══ HIỆU CHUẨN offline ↔ leaderboard")
        print(f"{'bài':26}{'offline':>9}{'LB':>9}{'LB/offline':>12}")
        hs = []
        for k in ket:
            lb = NEO_LB.get(k["bai"])
            if lb is None:
                continue
            r = lb / k["acc"] if k["acc"] else float("nan")
            hs.append(r)
            print(f"{k['bai']:26}{k['acc']:>8.4f}{lb:>9.4f}{r:>12.3f}")
        if len(hs) >= 2:
            lo, hi = min(hs), max(hs)
            print(f"\ndao động hệ số: {lo:.3f}–{hi:.3f} "
                  f"({100*(hi-lo)/((hi+lo)/2):.1f}%)")
            print("Đọc: hệ số ỔN ĐỊNH ⇒ dụng cụ dùng được để dự báo. "
                  "Hệ số PHÂN KỲ ⇒ gold đang thiên lệch theo bài nộp, "
                  "KHÔNG được dùng làm mốc tuyệt đối.")
        else:
            print("chưa đủ 2 điểm neo để kết luận")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
