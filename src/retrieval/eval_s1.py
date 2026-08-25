"""Đo S1 trên toàn bộ 1.012 câu hỏi thật."""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval.filter_s1 import filter_tables            # noqa: E402
from retrieval.question_intent import parse_intent       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "artifacts/retrieval/work.db"


def main() -> int:
    if not DB.is_file():
        print(f"✗ thiếu {DB} — chạy tools/build_retrieval_workdb.sh trước")
        return 2
    alias = yaml.safe_load((ROOT / "configs/retrieval/company_alias_v1.yaml")
                           .read_text(encoding="utf-8"))["aliases"]
    qs = [json.loads(l) for l in
          (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8")]
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c.execute("PRAGMA cache_size=-200000")

    sizes, rong, mode = [], 0, Counter()
    t0 = time.time()
    for q in qs:
        it = parse_intent(q["question"], alias)
        mode[it.mode] += 1
        cands = filter_tables(c, it.targets, it.years, it.basis)
        if not cands:
            rong += 1
        else:
            sizes.append(len(cands))
    dt = time.time() - t0

    P = print
    P(f"1.012 câu · {dt:.1f}s tổng · {1000*dt/len(qs):.1f} ms/câu")
    P(f"mode: {dict(mode)}")
    P(f"\ncâu KHÔNG ra ứng viên nào : {rong}  ({100*rong/len(qs):.1f}%)")
    if sizes:
        s = sorted(sizes)
        P(f"kích thước tập ứng viên   : trung vị {statistics.median(s):.0f}"
          f" · TB {statistics.mean(s):.0f} · p90 {s[int(.9*len(s))]}"
          f" · max {s[-1]} · min {s[0]}")
        P(f"thu hẹp so với 146.246    : {146246/statistics.mean(s):.0f}×")
        for lim in (10, 50, 100, 300, 1000):
            P(f"   ≤{lim:5d} bảng : {sum(1 for x in s if x <= lim):5d}"
              f"  ({100*sum(1 for x in s if x <= lim)/len(s):5.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
