"""S4-P0 · đóng gói P0H = P0G2 (relevant_tables/docs GIỮ NGUYÊN XI) + đáp án v4.

Một biến duy nhất đổi: `answer` / `pandas_query` / `evidence` / CSV.
Hợp đồng Retrieval đã FREEZE ⇒ `relevant_tables`/`relevant_docs` không được chạm.
Có cổng cứng: lệch một phần tử là dừng.

Đáp án SỐ HỌC của P0-g (37 câu) được GIỮ, vì chúng thắng đáp án tra-cứu-một-ô
ở chính bất biến `answer == eval(pandas_query)` chạy bằng pandas thật.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEN = ROOT / "data/submissions/submission_P0G2.zip"
RA = ROOT / "data/submissions/submission_P0H.zip"
REC = ROOT / "data/dev/answer_v3/records_v4.jsonl"
DATA = ROOT / "data/dev/answer_v3/data"
SOHOC = ROOT / "data/dev/so_hoc/records_sohoc.jsonl"

moi = {r["qid"]: r for r in (json.loads(l) for l in REC.open(encoding="utf-8") if l.strip())}
zin = zipfile.ZipFile(NEN)
sub = json.loads(zin.read("submission.json"))
goc = {r["id"]: r for r in json.loads(zin.read("submission.json"))}

# Câu nào đang dùng đáp án số học của P0-g thì GIỮ NGUYÊN.
giu_sohoc = set()
if SOHOC.is_file():
    for l in SOHOC.open(encoding="utf-8"):
        if not l.strip():
            continue
        r = json.loads(l)
        qid = r.get("qid") or r.get("id")
        if r.get("trang_thai") == "OK":
            giu_sohoc.add(qid)

doi = giu = bo_qua = 0
can_csv = set()
for r in sub:
    qid = r["id"]
    if qid in giu_sohoc:
        bo_qua += 1
        continue
    m = moi.get(qid)
    if not m or not m.get("evidence"):
        giu += 1
        continue                      # giữ nguyên đáp án cũ, KHÔNG xoá
    if (m["answer"] == goc[qid].get("answer")
            and m["pandas_query"] == goc[qid].get("pandas_query")):
        giu += 1
        can_csv.add(m["csv_name"])
        continue
    r["answer"] = m["answer"] if m["answer"] is not None else 0.0
    r["pandas_query"] = m["pandas_query"]
    r["evidence"] = m["evidence"]
    can_csv.add(m["csv_name"])
    doi += 1

# ── CỔNG CỨNG: hợp đồng Retrieval không được đổi ─────────────────────────
for r in sub:
    g = goc[r["id"]]
    for f in ("relevant_tables", "relevant_docs", "question"):
        if json.dumps(r.get(f), ensure_ascii=False) != json.dumps(g.get(f), ensure_ascii=False):
            raise SystemExit(f"q{r['id']}: {f} ĐÃ ĐỔI — hợp đồng Retrieval đang FREEZE, dừng")

# ── gom CSV: của v3 nếu câu dùng đáp án mới, còn lại lấy từ gói nền ───────
with zipfile.ZipFile(RA, "w", zipfile.ZIP_DEFLATED) as zo:
    zo.writestr("submission.json", json.dumps(sub, ensure_ascii=False, indent=1))
    can = {e["csv_path"] for r in sub for e in (r.get("evidence") or []) if e.get("csv_path")}
    co_nen = set(zin.namelist())
    n_v3 = n_nen = thieu = 0
    for path in sorted(can):
        name = path.split("/", 1)[1]
        p = DATA / name
        if p.is_file():
            zo.write(p, path)
            n_v3 += 1
        elif path in co_nen:
            zo.writestr(path, zin.read(path))
            n_nen += 1
        else:
            thieu += 1
            print(f"  ⚠ THIẾU CSV: {path}")

print(f"P0H: {doi} câu đổi đáp án · {giu} giữ nguyên · {bo_qua} giữ đáp án SỐ HỌC P0-g")
print(f"     CSV: {n_v3} từ v3 · {n_nen} từ gói nền · {thieu} THIẾU")
print(f"  -> {RA.relative_to(ROOT)} · {RA.stat().st_size:,} bytes")
