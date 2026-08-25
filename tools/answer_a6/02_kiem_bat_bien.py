"""Kiểm bất biến `answer == eval(pandas_query)` bằng pandas THẬT, trên CSV sẽ nộp."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RA = ROOT / "data/curated/dev-legacy/answer_a6"
rec = [json.loads(l) for l in (RA / "records_a6.jsonl").open(encoding="utf-8") if l.strip()]
tu, den = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) >= 3 else (0, 10**9)
kq_p = RA / "bat_bien.json"
kq = json.loads(kq_p.read_text()) if kq_p.is_file() and os.environ.get("RESET") != "1" else {}
cache = {}
xanh = do = bo = 0
for r in rec[tu:den]:
    qid = str(r["qid"])
    if qid in kq:
        continue
    if r["nguon"] != "PRIMARY_A6" or not r.get("pandas_query"):
        kq[qid] = {"trang_thai": "BO_QUA", "nguon": r["nguon"]}
        continue
    p = RA / "data" / r["csv_name"]
    if not p.is_file():
        kq[qid] = {"trang_thai": "THIEU_CSV"}; do += 1; continue
    if r["csv_name"] not in cache:
        if len(cache) > 120:
            cache.clear()
        cache[r["csv_name"]] = pd.read_csv(p)
    df1 = cache[r["csv_name"]]
    try:
        v = eval(r["pandas_query"], {"__builtins__": {}}, {"df1": df1, "float": float})
    except Exception as e:
        kq[qid] = {"trang_thai": "LOI", "chi_tiet": repr(e)[:110]}; do += 1; continue
    ok = abs(v - r["answer"]) <= max(1e-9, abs(r["answer"]) * 1e-9)
    kq[qid] = {"trang_thai": "XANH" if ok else "LECH", "eval": v, "answer": r["answer"]}
    xanh += ok; do += (not ok)
kq_p.write_text(json.dumps(kq, ensure_ascii=False))
import collections
c = collections.Counter(v["trang_thai"] for v in kq.values())
print(f"da kiem {len(kq)}/1012 · " + " · ".join(f"{k}={v}" for k, v in c.most_common()))
