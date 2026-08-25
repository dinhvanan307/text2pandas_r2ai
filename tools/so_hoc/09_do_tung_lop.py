"""P0-g bước 9 · đo RIÊNG TỪNG LỚP, không gộp thành một điểm."""
from __future__ import annotations
import collections, json, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SH = ROOT / "data/dev/so_hoc"
PL = {r["id"]: r for r in (json.loads(l) for l in (SH / "phan_loai.jsonl").open(encoding="utf-8") if l.strip())}
RC = {r["qid"]: r for r in (json.loads(l) for l in (SH / "records_sohoc.jsonl").open(encoding="utf-8") if l.strip())}
G = {r["id"]: r for r in json.loads(zipfile.ZipFile(ROOT / "data/submissions/submission_P0G.zip").read("submission.json"))}
G2 = {r["id"]: r for r in json.loads(zipfile.ZipFile(ROOT / "data/submissions/submission_P0G2.zip").read("submission.json"))}

LOP = ("lookup", "ratio", "percentage_change", "difference", "sum", "average",
       "max_min", "argmax_year", "count", "multi_table")
print(f"{'lớp':<20}{'câu':>6}{'engine OK':>11}{'phủ':>8}{'đổi đáp án':>12}"
      f"{'lý do UNCERTAIN nhiều nhất':>34}")
tong_ok = 0
for lop in LOP:
    ds = [q for q, r in PL.items() if r["lop"] == lop]
    ok = [q for q in ds if RC[q]["trang_thai"] == "OK"]
    doi = sum(1 for q in ds if G[q]["answer"] != G2[q]["answer"])
    ly = collections.Counter((RC[q]["ghi_chu"] or [""])[0][:32] for q in ds
                             if RC[q]["trang_thai"] != "OK")
    top = ly.most_common(1)[0][0] if ly else ""
    tong_ok += len(ok)
    print(f"{lop:<20}{len(ds):>6}{len(ok):>11}{len(ok)/len(ds):>8.1%}{doi:>12}  {top:<32}")
print(f"{'TỔNG':<20}{len(PL):>6}{tong_ok:>11}{tong_ok/len(PL):>8.1%}")
print()
so_hoc_lop = {"ratio", "percentage_change", "difference", "sum", "average",
              "max_min", "argmax_year"}
ds = [q for q, r in PL.items() if r["lop"] in so_hoc_lop]
ok = [q for q in ds if RC[q]["trang_thai"] == "OK"]
print(f"riêng 7 lớp CẦN SỐ HỌC: {len(ok)}/{len(ds)} = {len(ok)/len(ds):.1%}")
pl = [q for q, r in PL.items() if r["don_vi_hoi"] in ("%", "lan")]
plok = [q for q in pl if RC[q]["trang_thai"] == "OK"]
print(f"riêng 302 câu `%` và `lần`: {len(plok)}/{len(pl)} = {len(plok)/len(pl):.1%}")
