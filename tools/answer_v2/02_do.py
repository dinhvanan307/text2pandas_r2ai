"""P0-f · đo tầng đáp án MỚI so với gói P0E — cùng câu, cùng gold, khác nguồn bảng."""
from __future__ import annotations
import json, os, re, sqlite3, zipfile, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
conn = sqlite3.connect(f"file:{os.path.expanduser('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db')}?mode=ro", uri=True)
U2R = {u: (e or "").replace("|line:", "|") for u, e in
       conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}

GOLD_TAY = {r["id"]: {U2R[u] for u in r["gold_table_uids"] if u in U2R}
            for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/gold_v1.jsonl").open(encoding="utf-8") if l.strip())
            if r.get("gold_table_uids")}
GA = {r["id"]: {U2R[b["table_uid"]] for b in r["gold"] if b["table_uid"] in U2R}
      for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/audit/gold_audit_nam.jsonl").open(encoding="utf-8") if l.strip())
      if r.get("gold")}

CU = {r["id"]: r for r in json.loads(zipfile.ZipFile(ROOT / "artifacts/submissions/legacy/submission_P0E.zip").read("submission.json"))}
MOI = {r["qid"]: r for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/answer_v2/records.jsonl").open(encoding="utf-8") if l.strip())}
V3 = {r["qid"]: r for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/answer_v2/records_v3.jsonl").open(encoding="utf-8") if l.strip())}

_CSV = re.compile(r"data/(.+)_line(\d+)\.csv$")


def nguon(rec) -> str | None:
    ev = rec.get("evidence") or []
    if not ev:
        return None
    m = _CSV.match(ev[0].get("csv_path", ""))
    return f"{m.group(1)}|{m.group(2)}" if m else None


def trung(gold: dict, lay) -> tuple[int, int]:
    t = n = 0
    for q, g in gold.items():
        src = lay(q)
        if src is None:
            continue
        n += 1
        t += src in g
    return t, n


print("═" * 70)
print("A · BẢNG NGUỒN của đáp án có nằm trong GOLD không")
print("═" * 70)
print(f"{'tập gold':<28}{'P0E':>14}{'P0F':>14}{'P0G':>14}")
for ten, G in (("gold tay (89 câu)", GOLD_TAY), ("gold audit P0-e (30 câu)", GA)):
    a, na = trung(G, lambda q: nguon(CU.get(q, {})))
    b, nb = trung(G, lambda q: nguon(MOI.get(q, {})))
    c, nc = trung(G, lambda q: nguon(V3.get(q, {})))
    print(f"{ten:<28}{a}/{na}={a/na if na else 0:.3f}  {b}/{nb}={b/nb if nb else 0:.3f}  {c}/{nc}={c/nc if nc else 0:.3f}")

print()
print("═" * 70)
print("B · Tính nhất quán nội tại của gói")
print("═" * 70)
for ten, lay in (("gói P0E", lambda q: nguon(CU.get(q, {}))),
                 ("đáp án mới", lambda q: nguon(MOI.get(q, {})))):
    top1 = trong = co = 0
    for q, r in CU.items():
        src = lay(q)
        if src is None:
            continue
        co += 1
        tb = r.get("relevant_tables") or []
        top1 += bool(tb) and src == tb[0]
        trong += src in tb
    print(f"  {ten:<12} evidence == relevant_tables[0]: {top1}/{co} = {top1/co:.3f}"
          f"   ·  nằm trong danh sách: {trong}/{co} = {trong/co:.3f}")

print()
print("═" * 70)
print("C · Chất lượng khớp ô")
print("═" * 70)
for ten, D in (("gói P0E", None), ("đáp án mới", MOI)):
    if D is None:
        print("  gói P0E     : không còn `notes`/`confidence` trong zip — không đo được")
        continue
    fb = sum(1 for r in D.values() if any("không khớp được nhãn" in n for n in (r.get("notes") or [])))
    z = sum(1 for r in D.values() if r.get("answer") in (0, 0.0))
    c = [r.get("confidence") or 0.0 for r in D.values()]
    import statistics as S
    print(f"  đáp án mới  : rơi vào ô dự phòng {fb}/1012 = {fb/1012:.3f}"
          f" · answer=0 {z} · confidence trung vị {S.median(c):.2f}")
