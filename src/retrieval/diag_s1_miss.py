"""Vì sao S1 loại mất bảng gold — quy trách nhiệm cho ĐÚNG mệnh đề.

S1 có bốn mệnh đề lọc cứng. Câu hỏi duy nhất đáng hỏi khi mất recall là:
mệnh đề NÀO loại nó. Đoán thì sửa nhầm; ở đây kiểm từng mệnh đề trên chính
bảng gold bị mất.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval.pipeline import run                       # noqa: E402
from retrieval.proxy_gold import build_proxy_gold        # noqa: E402
from retrieval.question_intent import parse_intent       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    alias = yaml.safe_load((ROOT / "configs/retrieval/company_alias_v1.yaml")
                           .read_text(encoding="utf-8"))["aliases"]
    qs = {q["id"]: q for q in (json.loads(l) for l in
          (ROOT / "data/raw/btc/questions/questions.jsonl").open(encoding="utf-8"))}
    rows = [json.loads(l) for l in
            (ROOT / "artifacts/runs/retrieval/eval_retrieval.jsonl").open(encoding="utf-8") if l.strip()]
    mat = [r for r in rows if r["n_gold"] and r["n_gold"] <= 60
           and r["n_gold_cells"] < 400 and not r["in_s1"]]
    c = sqlite3.connect("file:" + str(ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db") + "?mode=ro", uri=True)
    c.execute("PRAGMA cache_size=-300000")
    thu = Counter()
    for r in mat:
        q = qs[r["id"]]
        it = parse_intent(q["question"], alias)
        tk = frozenset(it.targets) or it.tickers
        g = build_proxy_gold(c, q["id"], q["question"], tk, it.years, alias,
                             it.explicit_scope)
        res = run(c, q["question"], alias, top_k=1)
        lo, hi = (min(it.years), max(it.years) + 1) if it.years else (None, None)
        print(f"\nq{r['id']} [{it.mode}] targets={it.targets} years={it.years} "
              f"basis={it.basis} n_s1={res.n_s1}")
        print(f"   {q['question'][:110]}")
        for uid in sorted(g.tables)[:4]:
            row = c.execute(
                "SELECT t.doc_id, t.retrieval_ready, d.ticker, d.doc_year, d.basis "
                "FROM table_cards t LEFT JOIN documents d ON d.directory_doc_id=t.doc_id "
                "WHERE t.table_uid=?", (uid,)).fetchone()
            if row is None:
                print(f"   gold {uid[:28]}  KHÔNG CÓ trong table_cards"); thu["no_card"] += 1; continue
            doc, rr, tic, yr, bas = row
            ly = []
            if tic is None:
                ly.append("DOC_KHONG_KHOP(documents)")
            else:
                if tic not in it.targets:
                    ly.append(f"ticker({tic}∉targets)")
                if it.years and not (lo <= yr <= hi):
                    ly.append(f"doc_year({yr}∉[{lo},{hi}])")
                if it.basis and bas is not None and bas != it.basis:
                    ly.append(f"basis({bas}≠{it.basis})")
            if not rr:
                ly.append("retrieval_ready=0")
            if not ly:
                ly.append("KHÔNG RÕ — đáng lẽ phải qua")
            for x in ly:
                thu[x.split("(")[0]] += 1
            print(f"   gold {uid[:30]:30s} doc={doc[:40]:40s} → {' · '.join(ly)}")
    print("\n=== quy trách nhiệm (đếm theo bảng gold bị loại) ===")
    for k, v in thu.most_common():
        print(f"   {k:28s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
