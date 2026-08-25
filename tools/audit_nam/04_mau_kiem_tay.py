"""P0-e buoc 4 · rut mau KIEM TAY va DONG BANG no.

Bo phan xu o buoc 3 la mot BO QUY TAC, va bo quy tac cung sai duoc — no da sai
NAM lan, moi lan deu do doc tay bat duoc:

  1. bien phai cua regex nam: "2021VND" khong khop vi `\\b` bi chan boi `V`
  2. dung lai sau dong tieu de 1, bo mat "Nam truoc" o dong 2 (VPI/2025 `1906`)
  3. bang bien dong dat ky o NHAN DONG chu khong o tieu de (CTG/2019 `3df582ad`)
  4. nam trong trich dan hanh chinh bi tinh la ky (ABB/2020 `448`, MML/2023 `950`)
  5. cot "So phai nop trong nam" khong duoc nhan la ky phat sinh (DNH/2025 `919`)

Mau duoc GHI RA FILE va doc lai o cac lan chay sau, de no khong troi theo ket
qua cua chinh bo quy tac dang duoc kiem.
"""
import json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "data/curated/dev-legacy/audit"
FILE = AUD / "mau_kiem_tay_dong_bang.json"

R = [json.loads(l) for l in (AUD / "phan_xu_ky.jsonl").open(encoding="utf-8") if l.strip()]
THO = {r["table_uid"]: r for r in (json.loads(l) for l in
       (AUD / "bang_tho.jsonl").open(encoding="utf-8") if l.strip())}
BANG = {(r["id"], b["table_uid"]): (r, b) for r in R for b in r["bang"]}

if FILE.is_file():
    khoa = [tuple(x) for x in json.loads(FILE.read_text(encoding="utf-8"))]
else:
    nhom = {True: [], False: [], None: []}
    for r in R:
        for b in r["bang"]:
            nhom[b["chua_ky"]].append((r["id"], b["table_uid"]))
    rng = random.Random("p0e-kiem-tay-dong-bang")
    khoa = []
    for k, n in ((True, 25), (False, 21), (None, 20)):
        ds = sorted(nhom[k])
        khoa += rng.sample(ds, min(n, len(ds)))
    FILE.write_text(json.dumps(khoa, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"da dong bang mau {len(khoa)} muc -> {FILE.relative_to(ROOT)}")

tu, den = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1, 999)
for i, k in enumerate(khoa[tu-1:den], tu):
    r, b = BANG[tuple(k)]
    t = THO.get(b["table_uid"], {})
    print(f"── [{i}] q{r['id']} hoi {r['nam_hoi']} · may: {b['chua_ky']} · nam_cot {b.get('nam_cot')}")
    print(f"   {t.get('doc_id','?')} dong {t.get('dong','?')}")
    print(f"   td1: {' | '.join(t.get('tieu_de_cot',[])[:7])[:145]}")
    print(f"   td2: {' | '.join(t.get('dong_dau_2',[])[:7])[:145]}")
    print(f"   dong: {' / '.join(t.get('nhan_dong',[])[:5])[:145]}")
