"""Đo tầng Retrieval trên 1.012 câu — KHÔNG sinh đáp án.

Chạy hai pha, vì máy build cắt tiến trình nền sau ~45 s: `collect` ghi tiếp
vào checkpoint và BỎ QUA câu đã đo, nên gọi lại nhiều lần là xong; `report`
chỉ đọc checkpoint. Tách như vậy còn cho phép đổi cách tính metric mà không
phải quét lại DB.

    python3 src/retrieval/eval_retrieval.py collect   (gọi tới khi hết câu)
    python3 src/retrieval/eval_retrieval.py report

BỐN CON SỐ, tách bạch, vì mỗi thứ hỏng đòi một cách sửa khác nhau:

  hit rate          dựng được proxy gold cho bao nhiêu câu (kích thước tập đo)
  candidate recall  S1 (LỌC CỨNG) có giữ bảng gold không — mất là mất hẳn
  Recall@K          S2 (XẾP HẠNG) có đẩy bảng gold lên top-K không
  Precision@K · F2@K · MRR

`candidate recall` đo trên `Result.s1_uids` — TẬP ỨNG VIÊN ĐẦY ĐỦ, không phải
`hits` đã cắt top-K. Đo trên `hits` là đo lại `Recall@50` dưới một cái tên
khác, và sẽ kết luận sai rằng "S1 ổn" trong khi thật ra mất ngay ở S1.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.pipeline import run                       # noqa: E402
from retrieval.proxy_gold import build_proxy_gold        # noqa: E402
from retrieval.question_intent import parse_intent       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MODE = os.environ.get("BASIS_MODE", "soft")
BRANDS = os.environ.get("BRANDS", "1") == "1"
HINTS = os.environ.get("HINTS", "code_single")
CK = ROOT / (f"artifacts/runs/retrieval/eval_{MODE}"
             f"{'_brand' if BRANDS else ''}"
             f"{'' if HINTS == 'none' else '_' + HINTS}.jsonl")
KS = (1, 3, 5, 10, 20, 50)
TOP_K = 50
GOLD_LIMIT = 400          # trùng LIMIT trong proxy_gold._phrase_match
GOLD_MAX_TRUSTED = 60     # gold to hơn mức này = cụm quá phổ thông → không tin
BUDGET_S = 35.0           # tự dừng trước khi máy build cắt tiến trình


def f2(p: float, r: float) -> float:
    return 0.0 if p + r == 0 else 5 * p * r / (4 * p + r)


def _questions() -> list[dict]:
    p = ROOT / "data/raw/btc/questions/questions.jsonl"
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def _done() -> set[int]:
    if not CK.is_file():
        return set()
    out = set()
    for l in CK.open(encoding="utf-8"):
        l = l.strip()
        if l:
            try:
                out.add(json.loads(l)["id"])
            except (ValueError, KeyError):
                pass
    return out


def collect() -> int:
    db = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"
    if not db.is_file():
        print("✗ thiếu work.db — chạy tools/build_retrieval_workdb.sh")
        return 2
    alias = load_aliases(brands=BRANDS)
    qs = _questions()
    xong = _done()
    con_lai = [q for q in qs if q["id"] not in xong]
    if not con_lai:
        print(f"đã đo đủ {len(xong)}/{len(qs)} câu — chạy `report`")
        return 0
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.execute("PRAGMA cache_size=-300000")
    ck = CK.open("a", encoding="utf-8")
    t0 = time.time()
    n = 0
    for q in con_lai:
        tq = time.time()
        it = parse_intent(q["question"], alias)
        tk = frozenset(it.targets) or it.tickers
        g = build_proxy_gold(c, q["id"], q["question"], tk, it.years, alias,
                             it.explicit_scope)
        r = run(c, q["question"], alias, top_k=TOP_K, basis_mode=MODE,
                use_hints=HINTS)
        ranked = [h.cand.table_uid for h in r.hits]
        # `hits_at`: mọi vị trí 1-based trong bảng xếp hạng có bảng gold.
        # Đủ để dựng lại Recall@K, Precision@K, MRR mà không cần quét lại DB.
        row = {
            "id": q["id"], "mode": it.mode, "n_targets": len(it.targets),
            "n_s1": r.n_s1, "n_ranked": len(ranked),
            "n_gold": len(g.tables), "n_gold_cells": g.n_cells,
            "gold_how": g.how, "phrase": g.note,
            "in_s1": bool(g.tables & r.s1_uids) if g.tables else None,
            "hits_at": [j + 1 for j, u in enumerate(ranked) if u in g.tables],
            "ms": round(1000 * (time.time() - tq)),
        }
        ck.write(json.dumps(row, ensure_ascii=False) + "\n")
        ck.flush()
        n += 1
        if time.time() - t0 > BUDGET_S:
            break
    ck.close()
    da = len(xong) + n
    print(f"đo thêm {n} câu · tổng {da}/{len(qs)} · {time.time()-t0:.0f}s"
          + ("" if da >= len(qs) else "  → gọi lại `collect`"))
    return 0


def report() -> int:
    if not CK.is_file():
        print("✗ chưa có checkpoint — chạy `collect`")
        return 2
    rows = [json.loads(l) for l in CK.open(encoding="utf-8") if l.strip()]
    rows = list({r["id"]: r for r in rows}.values())
    tong = len(_questions())

    n_s1_empty = sum(1 for r in rows if r["n_s1"] == 0)
    # Gold quá lớn hoặc chạm trần LIMIT = cụm quá phổ thông ("tổng cộng"):
    # không phải bằng chứng về chất lượng truy hồi. Khai ra, và loại khỏi tập đo.
    do_duoc = [r for r in rows if r["n_gold"]
               and r["n_gold"] <= GOLD_MAX_TRUSTED
               and r["n_gold_cells"] < GOLD_LIMIT]
    n_gold = len(do_duoc)
    P = print
    P(f"đã đo                          : {len(rows)}/{tong} câu")
    P(f"S1 trả về TẬP RỖNG             : {n_s1_empty}  ← không ứng viên nào")
    P(f"proxy gold dựng được           : {sum(1 for r in rows if r['n_gold'])}")
    P(f"proxy gold TIN CẬY (tập đo)    : {n_gold}  ({100*n_gold/max(len(rows),1):.1f}% số câu đã đo)")
    if not n_gold:
        return 1
    gs = sorted(r["n_gold"] for r in do_duoc)
    P(f"   gold/câu  median={gs[len(gs)//2]}  p90={gs[int(.9*len(gs))]}  max={gs[-1]}")

    s1_hit = sum(1 for r in do_duoc if r["in_s1"])
    mat_s1 = [r for r in do_duoc if not r["in_s1"]]
    mat_s2 = [r for r in do_duoc if r["in_s1"]
              and not any(h <= 10 for h in r["hits_at"])]
    mrr = sum(1.0 / min(r["hits_at"]) for r in do_duoc if r["hits_at"])
    P("")
    P(f"CANDIDATE RECALL (S1 giữ gold)  : {s1_hit}/{n_gold}  ({100*s1_hit/n_gold:.2f}%)")
    P(f"MẤT Ở S1 (lọc cứng, mất hẳn)    : {len(mat_s1)}")
    P(f"MẤT Ở S2 (có ứng viên, rớt top10): {len(mat_s2)}")
    P(f"MRR                             : {mrr/n_gold:.4f}")
    P("")
    P(f"{'K':>4s} {'Recall@K':>10s} {'Precision@K':>12s} {'F2@K':>8s}")
    for k in KS:
        rc = sum(1 for r in do_duoc if any(h <= k for h in r["hits_at"]))
        pr = sum(sum(1 for h in r["hits_at"] if h <= k) / k for r in do_duoc)
        r_, p_ = rc / n_gold, pr / n_gold
        P(f"{k:>4d} {r_:>10.4f} {p_:>12.4f} {f2(p_, r_):>8.4f}")

    by: dict[str, list] = {}
    for r in do_duoc:
        by.setdefault(r["mode"], []).append(r)
    P("")
    P(f"{'mode':12s} {'n':>5s} {'cand recall':>12s} {'recall@10':>11s} {'recall@1':>10s}")
    for m in sorted(by):
        v = by[m]
        c1 = sum(1 for r in v if r["in_s1"])
        c10 = sum(1 for r in v if any(h <= 10 for h in r["hits_at"]))
        cc1 = sum(1 for r in v if any(h == 1 for h in r["hits_at"]))
        P(f"{m:12s} {len(v):5d} {100*c1/len(v):11.1f}% "
          f"{100*c10/len(v):10.1f}% {100*cc1/len(v):9.1f}%")

    mode_all = Counter(r["mode"] for r in rows)
    P("")
    P("phủ của tập đo theo mode (đo được / tổng đã chạy):")
    for m in sorted(mode_all):
        P(f"   {m:12s} {len(by.get(m, [])):4d}/{mode_all[m]:<4d}")
    P("")
    P(f"15 câu MẤT Ở S1 — ưu tiên cao nhất, mất ở đây thì xếp hạng vô nghĩa:")
    for r in mat_s1[:15]:
        P(f"  q{r['id']:<5d} {r['mode']:11s} n_s1={r['n_s1']:<5d} "
          f"gold={r['n_gold']:<3d} phrase={r['phrase']!r}")
    P("")
    P("15 câu MẤT Ở S2:")
    for r in mat_s2[:15]:
        P(f"  q{r['id']:<5d} {r['mode']:11s} n_s1={r['n_s1']:<5d} "
          f"gold={r['n_gold']:<3d} hits_at={r['hits_at'][:3]} phrase={r['phrase']!r}")
    P("")
    P(f"chi tiết từng câu → {CK.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    raise SystemExit(collect() if cmd == "collect" else report())
