"""P0-f · kiểm tay ĐÁP ÁN. Hợp đồng kiểu chỉ là proxy; đây là phép đo thật."""
from __future__ import annotations
import json, os, random, re, sqlite3, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
conn = sqlite3.connect(f"file:{os.path.expanduser('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db')}?mode=ro", uri=True)
U2R = {u: (e or "").replace("|line:", "|") for u, e in
       conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
GOLD = {r["id"]: {U2R[u] for u in r["gold_table_uids"] if u in U2R}
        for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/gold_v1.jsonl").open(encoding="utf-8") if l.strip())
        if r.get("gold_table_uids")}
CU = {r["id"]: r for r in json.loads(zipfile.ZipFile(ROOT / "artifacts/submissions/legacy/submission_P0E.zip").read("submission.json"))}
MOI = {r["qid"]: r for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/answer_v2/records.jsonl").open(encoding="utf-8") if l.strip())}
_CSV = re.compile(r"data/(.+)_line(\d+)\.csv$")


def src(r):
    ev = (r or {}).get("evidence") or []
    if not ev:
        return None
    m = _CSV.match(ev[0]["csv_path"])
    return f"{m.group(1)}|{m.group(2)}" if m else None


ds = sorted(GOLD)
rng = random.Random("p0f-kiem-dap-an")
mau = rng.sample(ds, min(24, len(ds)))
tu, den = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1, 99)
for i, q in enumerate(mau[tu-1:den], tu):
    m = MOI.get(q, {}); c = CU.get(q, {})
    s = src(m)
    ql = c.get("question", "")
    print(f"── [{i}] q{q} · nguồn {'GOLD ✓' if s in GOLD[q] else 'ngoài gold'} · conf {m.get('confidence')}")
    print(f"   {ql[:150]}")
    print(f"   P0E: {c.get('answer')}")
    print(f"   P0F: {m.get('answer')}   ({s})")
    pq = m.get("pandas_query", "")
    r1 = re.search(r"row_path'\] == '(.*?)'\)", pq)
    c1 = re.search(r"col_label'\] == '(.*?)'\)", pq)
    print(f"   ô : row={r1.group(1)[:80] if r1 else '?'} | col={c1.group(1)[:60] if c1 else '?'}")
    if m.get("notes"):
        print(f"   note: {m['notes']}")
