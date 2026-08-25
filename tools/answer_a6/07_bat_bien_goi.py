"""Bất biến `answer == eval(pandas_query)` trên CHÍNH gói nộp.

Bind ĐỦ mọi biến trong `evidence` (df1, df2, …) và cho phép các hàm dựng sẵn mà
engine số học dùng — nếu không, chính bộ kiểm sẽ báo đỏ giả (đã dính 2 ca).
"""
from __future__ import annotations
import io, json, sys, zipfile
import pandas as pd

Z = zipfile.ZipFile(sys.argv[1])
sub = json.loads(Z.read("submission.json"))
BUILTIN = {"float": float, "max": max, "min": min, "abs": abs, "sum": sum, "round": round, "len": len}
xanh = do = bo = 0
loi = []
cache = {}
for r in sub:
    ev = r.get("evidence") or []
    if not ev or not r.get("pandas_query") or r.get("answer") is None:
        bo += 1; continue
    env = dict(BUILTIN)
    thieu = False
    for e in ev:
        p = e.get("csv_path")
        if not p:
            thieu = True; break
        if p not in cache:
            if len(cache) > 150: cache.clear()
            try:
                cache[p] = pd.read_csv(io.BytesIO(Z.read(p)))
            except KeyError:
                thieu = True; break
        env[e["variable"]] = cache[p]
    if thieu:
        do += 1; loi.append((r["id"], "THIEU_CSV")); continue
    try:
        v = eval(r["pandas_query"], {"__builtins__": {}}, env)
        if abs(v - r["answer"]) <= max(1e-9, abs(r["answer"]) * 1e-9):
            xanh += 1
        else:
            do += 1; loi.append((r["id"], f"LECH {v} vs {r['answer']}"))
    except Exception as e:
        do += 1; loi.append((r["id"], repr(e)[:80]))
print(f"{sys.argv[1].split('/')[-1]}: xanh {xanh} · đỏ {do} · bỏ qua {bo}")
for q, m in loi[:8]:
    print(f"   q{q}: {m}")
