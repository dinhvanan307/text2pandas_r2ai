"""Audit riêng: các ca đường HTML dùng một NHÃN DÒNG mà A6 không có (45/300)."""
from __future__ import annotations
import collections, json, os, re, sqlite3, unicodedata
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
c = sqlite3.connect('file:'+os.path.abspath(ROOT/'artifacts/retrieval/work.db')+'?mode=ro', uri=True)
ev2uid = {ev.replace("|line:", "|"): u for u, ev in c.execute(
    "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
HT = [json.loads(l) for l in (ROOT/"data/dev/answer_v3/records_v4.jsonl").open(encoding="utf-8")][:300]
RP = re.compile(r"row_path'\]\s*==\s*'([^']*)'")

def chuan(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(x for x in s if unicodedata.category(x) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s.replace("d", "d"))

loai = collections.Counter(); vd = collections.defaultdict(list)
for r in HT:
    nm = r.get("csv_name") or ""
    m = re.match(r"(.+)_line(\d+)\.csv$", nm)
    lab = RP.search(r.get("pandas_query") or "")
    if not m or not lab:
        loai["khong_map_duoc_bang"] += 1; continue
    uid = ev2uid.get(f"{m.group(1)}_extracted|{m.group(2)}") or ev2uid.get(f"{m.group(1)}|{m.group(2)}")
    if not uid:
        loai["bang_khong_co_trong_A6"] += 1; continue
    lab = lab.group(1)
    nhan = [(a or "", b or "") for a, b in c.execute(
        "SELECT metric_label_clean,row_path_text FROM observations WHERE table_uid=?", (uid,))]
    if not nhan:
        loai["bang_khong_co_observation"] += 1; continue
    tap = {chuan(a) for a, b in nhan} | {chuan(b) for a, b in nhan}
    k = chuan(lab)
    if k in tap:
        loai["KHOP"] += 1; continue
    con = [x for x in tap if x and (x in k or k in x)]
    if con:
        loai["A6 co nhan LIEN QUAN (HTML dan/cat chu)"] += 1
        if len(vd["lien_quan"]) < 5:
            vd["lien_quan"].append((r["qid"], lab[:52], sorted(con, key=len)[-1][:52]))
    else:
        loai["A6 KHONG co nhan tuong duong"] += 1
        if len(vd["khong"]) < 5:
            vd["khong"].append((r["qid"], lab[:60], len(tap)))
tot = sum(loai.values())
print(f"== 300 cau dau · nhan dong cua duong HTML co trong A6 khong? ==")
for k, v in loai.most_common():
    print(f"  {k:<46}{v:>4}  ({100*v/tot:.1f}%)")
print("\n-- HTML dan/cat chu, A6 co nhan lien quan --")
for q, a, b in vd["lien_quan"]:
    print(f"  q{q}\n     HTML: {a!r}\n     A6  : {b!r}")
print("\n-- A6 that su khong co --")
for q, a, n in vd["khong"]:
    print(f"  q{q} HTML={a!r} (bang co {n} nhan)")
