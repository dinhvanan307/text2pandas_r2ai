"""Phiếu phân xử cho pool v6 — nhãn dòng ĐẦY ĐỦ, nhóm theo ô, KHÔNG rò thứ hạng.

Ba luật chống nhiễm (kế thừa `gold_tay.py`, docs/81 §7):
  1. nhãn dòng lấy TOÀN BỘ từ `table_cards_fts`, không cắt còn 3 dòng và không
     xếp theo số từ khoá trùng — docs/82 §1 đã chỉ ra 3 dòng ấy được chọn hộ
     bằng đúng heuristic term-overlap mà hệ thống dùng để xếp hạng.
  2. thứ tự hiển thị = (mã, năm, phạm vi, loại, uid). Không lộ thứ hạng S2.
  3. KHÔNG in `sources`, không in điểm, không in nhãn proxy.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "curated" / "dev-legacy"

def main(argv):
    p = argparse.ArgumentParser(prog="gold_sheet_v6")
    p.add_argument("--db", required=True)
    p.add_argument("--pool", default=str(DEV / "gold_tay_pool_v6.jsonl"))
    p.add_argument("--qid", type=int, action="append", required=True)
    p.add_argument("--rows", type=int, default=28)
    a = p.parse_args(argv)
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    P = {r["id"]: r for r in (json.loads(l) for l in open(a.pool, encoding="utf-8"))}
    for qid in a.qid:
        r = P[qid]
        print("=" * 100)
        print(f"### q{qid}  [{r['mode']}]  scope={r['explicit_scope']}  cells={r['cells']}  needs={r['needs']}")
        print(f"    {r['question']}")
        full = {}
        uids = [c["table_uid"] for c in r["candidates"]]
        for i in range(0, len(uids), 400):
            lot = uids[i:i + 400]
            ph = ",".join("?" * len(lot))
            for u, rl in conn.execute(
                    f"SELECT table_uid, row_labels FROM table_cards_fts WHERE table_uid IN ({ph})", lot):
                full[u] = str(rl or "")
        cs = sorted(r["candidates"], key=lambda c: (c.get("ticker") or "", c.get("doc_year") or 0,
                                                    c.get("basis") or "", c.get("statement_type") or "",
                                                    c["table_uid"]))
        cell = None
        for c in cs:
            k = (c.get("ticker"), c.get("doc_year"))
            if k != cell:
                cell = k
                print(f"  ── {k[0]} · {k[1]} " + "─" * 60)
            bs = {"consolidated": "HN", "separate": "RIENG", "aggregated": "GOP"}.get(c.get("basis"), "??")
            print(f"  {c['table_uid']} {bs:<5} {str(c.get('statement_type'))[:16]:<16} "
                  f"obs={c.get('ready_obs')}/{c.get('n_obs')} per={str(c.get('periods'))[:24]}")
            if c.get("section_text"):
                print(f"     § {str(c['section_text'])[:110]}")
            rows = full.get(c["table_uid"], "")
            print(f"     rows: {rows[:a.rows * 34]}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
