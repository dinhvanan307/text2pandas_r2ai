"""P0-g bước 7 · P0G2 = P0G + 37 đáp án SỐ HỌC.

`relevant_tables` / `relevant_docs` GIỮ NGUYÊN. Chỉ `answer`/`pandas_query`/
`evidence` của 37 câu đổi. Định dạng bài nộp không đổi.
"""
from __future__ import annotations
import json, shutil, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CU = ROOT / "data/submissions/submission_P0G.zip"
RA = ROOT / "data/submissions/submission_P0G2.zip"
SH = ROOT / "data/dev/so_hoc"

sh = {r["qid"]: r for r in (json.loads(l) for l in (SH / "records_sohoc.jsonl").open(encoding="utf-8") if l.strip())
      if r["trang_thai"] == "OK"}
z0 = zipfile.ZipFile(CU)
sub = json.loads(z0.read("submission.json"))
cu_csv = {n for n in z0.namelist() if n.startswith("data/")}

doi, them, ngoai_ds = 0, set(), 0
for r in sub:
    m = sh.get(r["id"])
    if not m:
        continue
    r["answer"] = m["answer"]
    r["pandas_query"] = m["pandas_query"]
    r["evidence"] = m["evidence"]
    doi += 1
    for e in m["evidence"]:
        them.add(Path(e["csv_path"]).name)
    tb = set(r.get("relevant_tables") or [])
    for e in m["evidence"]:
        loc = Path(e["csv_path"]).stem.rsplit("_line", 1)
        if f"{loc[0]}|{loc[1]}" not in tb:
            ngoai_ds += 1
            break

with zipfile.ZipFile(RA, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("submission.json", json.dumps(sub, ensure_ascii=False, indent=1))
    for n in sorted(cu_csv):
        z.writestr(n, z0.read(n))
    n_them = 0
    for name in sorted(them):
        if f"data/{name}" in cu_csv:
            continue
        p = SH / "data" / name
        if p.is_file():
            z.write(p, f"data/{name}")
            n_them += 1
print(f"P0G2: {doi} câu dùng đáp án số học · thêm {n_them} CSV")
print(f"  trong đó {ngoai_ds} câu có evidence NGOÀI `relevant_tables` (đánh đổi có chủ ý)")
print(f"-> {RA.relative_to(ROOT)} · {RA.stat().st_size:,} bytes")
