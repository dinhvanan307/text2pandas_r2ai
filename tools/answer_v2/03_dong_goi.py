"""P0-f · đóng gói P0F = P0E (relevant_tables/docs GIỮ NGUYÊN) + đáp án mới.

Một biến duy nhất thay đổi: `answer` / `pandas_query` / `evidence` / CSV.
"""
from __future__ import annotations
import json, os, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CU = ROOT / "data/submissions/submission_P0E.zip"
V3 = len(sys.argv) > 1 and sys.argv[1] == "v3"
RA = ROOT / ("data/submissions/submission_P0G.zip" if V3 else "data/submissions/submission_P0F.zip")
REC = ROOT / ("data/dev/answer_v2/records_v3.jsonl" if V3 else "data/dev/answer_v2/records.jsonl")
DATA = ROOT / ("data/dev/answer_v2/data_v3" if V3 else "data/dev/answer_v2/data")

moi = {r["qid"]: r for r in (json.loads(l) for l in REC.open(encoding="utf-8") if l.strip())}
sub = json.loads(zipfile.ZipFile(CU).read("submission.json"))

can_csv, doi, giu = set(), 0, 0
for r in sub:
    m = moi.get(r["id"])
    if not m or not m.get("evidence"):
        giu += 1
        r["answer"] = 0.0 if not m else (m.get("answer") or 0.0)
        r["pandas_query"] = ""
        r["evidence"] = []
        continue
    r["answer"] = m["answer"] if m["answer"] is not None else 0.0
    r["pandas_query"] = m["pandas_query"]
    r["evidence"] = m["evidence"]
    can_csv.add(m["csv_name"])
    doi += 1

RA.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(RA, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("submission.json", json.dumps(sub, ensure_ascii=False, indent=1))
    n = 0
    for name in sorted(can_csv):
        p = DATA / name
        if p.is_file():
            z.write(p, f"data/{name}")
            n += 1
print(f"P0F: {doi} câu đổi đáp án · {giu} câu không có evidence · {n}/{len(can_csv)} csv đóng gói")
print(f"-> {RA.relative_to(ROOT)} · {RA.stat().st_size:,} bytes")
