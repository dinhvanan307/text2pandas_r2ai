"""P0-e buoc 1 · chon mau >=40 cau, phan tang T1/T2/screen, tat dinh.

Mau lay tu chinh 120 cau gold tay de con so sanh duoc voi gold cu, nhung
KHONG loc theo "co ung vien lech nam hay khong" — loc nhu vay se thoi phong
chinh hien tuong dang do.
"""
import json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAU  = ROOT / "data/curated/dev-legacy/gold_tay_sample_v2.jsonl"
RA   = ROOT / "data/curated/dev-legacy/audit/mau_audit_nam.json"
MOI_TANG = 15

rows = [json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip()]
theo = {}
for r in rows:
    theo.setdefault(r["tang"], []).append(r["id"])

chon = {}
for tang in sorted(theo):
    ids = sorted(theo[tang])
    rng = random.Random(f"p0e-{tang}")          # tat dinh, doc lap giua cac tang
    chon[tang] = sorted(rng.sample(ids, MOI_TANG))

RA.parent.mkdir(parents=True, exist_ok=True)
RA.write_text(json.dumps(chon, ensure_ascii=False, indent=2), encoding="utf-8")
tong = sum(len(v) for v in chon.values())
for t, v in sorted(chon.items()):
    print(f"{t:8s} {len(v):3d} cau : {v}")
print(f"tong {tong} cau -> {RA.relative_to(ROOT)}")
