"""Đóng gói P0I = P0G2 (relevant_tables/docs NGUYÊN XI) + đáp án A6-first.

Cổng cứng: lệch một phần tử hợp đồng Retrieval là dừng, không nộp.
Đáp án SỐ HỌC của P0-g được giữ (chúng là nhiều bước, tra-một-ô không thay được).
"""
from __future__ import annotations
import json, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NEN = ROOT / "data/submissions/submission_P0G2.zip"
RA = ROOT / "data/submissions/submission_P0I.zip"
A6R = ROOT / "data/dev/answer_a6/records_a6.jsonl"
DATA_A6 = ROOT / "data/dev/answer_a6/data"
DATA_V3 = ROOT / "data/dev/answer_v3/data"
SOHOC = ROOT / "data/dev/so_hoc/records_sohoc.jsonl"

moi = {r["qid"]: r for r in (json.loads(l) for l in A6R.open(encoding="utf-8") if l.strip())}
zin = zipfile.ZipFile(NEN)
sub = json.loads(zin.read("submission.json"))
goc = {r["id"]: r for r in json.loads(zin.read("submission.json"))}

giu_sohoc = set()
if SOHOC.is_file():
    for l in SOHOC.open(encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r.get("trang_thai") == "OK":
                giu_sohoc.add(r.get("qid") or r.get("id"))

doi = giu = bo = 0
n_a6 = n_fb = 0
for r in sub:
    qid = r["id"]
    if qid in giu_sohoc:
        bo += 1; continue
    m = moi.get(qid)
    if not m or not m.get("evidence") or m.get("answer") is None:
        giu += 1; continue
    n_a6 += m["nguon"] == "PRIMARY_A6"; n_fb += m["nguon"] != "PRIMARY_A6"
    if m["answer"] == goc[qid].get("answer") and m["pandas_query"] == goc[qid].get("pandas_query"):
        giu += 1; continue
    r["answer"] = m["answer"]; r["pandas_query"] = m["pandas_query"]; r["evidence"] = m["evidence"]
    doi += 1

for r in sub:                       # ── CỔNG CỨNG hợp đồng Retrieval ──
    g = goc[r["id"]]
    for f in ("relevant_tables", "relevant_docs", "question"):
        if json.dumps(r.get(f), ensure_ascii=False) != json.dumps(g.get(f), ensure_ascii=False):
            raise SystemExit(f"q{r['id']}: {f} ĐÃ ĐỔI — Retrieval đang FREEZE, dừng")

with zipfile.ZipFile(RA, "w", zipfile.ZIP_DEFLATED) as zo:
    zo.writestr("submission.json", json.dumps(sub, ensure_ascii=False, indent=1))
    can = {e["csv_path"] for r in sub for e in (r.get("evidence") or []) if e.get("csv_path")}
    co_nen = set(zin.namelist())
    a = b = d = thieu = 0
    for path in sorted(can):
        name = path.split("/", 1)[1]
        # THỨ TỰ ƯU TIÊN CÓ CHỦ ĐÍCH: gói nền TRƯỚC.
        # Các câu SỐ HỌC của P0-g giữ nguyên câu lệnh cũ, và câu lệnh ấy được
        # viết dựa trên CSV trong gói nền (nhãn cột riêng của engine số học).
        # Lấy bản v3/A6 cùng tên sẽ làm 15 câu vỡ ngầm — đã đo, không phải giả định.
        if path in co_nen:
            zo.writestr(path, zin.read(path)); d += 1
        elif (DATA_A6 / name).is_file():
            zo.write(DATA_A6 / name, path); a += 1
        elif (DATA_V3 / name).is_file():
            zo.write(DATA_V3 / name, path); b += 1
        else:
            thieu += 1; print(f"  ⚠ THIẾU CSV: {path}")
print(f"P0I: {doi} đổi · {giu} giữ · {bo} giữ SỐ HỌC P0-g | nguồn: A6 {n_a6} · fallback {n_fb}")
print(f"     CSV: {a} từ A6 · {b} từ v3 · {d} từ gói nền · {thieu} THIẾU")
print(f"  -> {RA.name} · {RA.stat().st_size:,} bytes")
