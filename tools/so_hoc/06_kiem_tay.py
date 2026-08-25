"""P0-g bước 6 · phiếu KIỂM TAY cho các câu engine trả `OK`.

Bất biến `answer == eval(query)` chỉ nói bài nộp KHÔNG TỰ MÂU THUẪN. Nó không
nói đáp án ĐÚNG. Chỉ đọc tay toán hạng mới biết.
"""
from __future__ import annotations
import collections, json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RA = ROOT / "data/dev/so_hoc"
FILE = RA / "mau_kiem_tay.json"

rec = {r["qid"]: r for r in (json.loads(l) for l in (RA / "records_sohoc.jsonl").open(encoding="utf-8") if l.strip())}
q = {r["id"]: r["question"] for r in (json.loads(l) for l in
     (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8") if l.strip())}

if FILE.is_file():
    khoa = json.loads(FILE.read_text())
else:
    by = collections.defaultdict(list)
    for r in rec.values():
        if r["trang_thai"] == "OK":
            by[r["lop"]].append(r["qid"])
    rng = random.Random("p0g-kiem-tay")
    khoa = []
    for lop in sorted(by):
        khoa += rng.sample(sorted(by[lop]), min(2, len(by[lop])))
    FILE.write_text(json.dumps(khoa), encoding="utf-8")
    print(f"đóng băng mẫu {len(khoa)} câu -> {FILE.relative_to(ROOT)}")

tu, den = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (1, 99)
for i, qid in enumerate(khoa[tu-1:den], tu):
    r = rec[qid]
    print(f"── [{i}] q{qid} · {r['lop']} · đơn vị hỏi `{r['don_vi_hoi']}`")
    print(f"   {q[qid][:150]}")
    print(f"   công thức : {r['cong_thuc']}")
    for o in r["operands"]:
        print(f"     {o[:150]}")
    print(f"   => answer  : {r['answer']}")
    if r["ghi_chu"]:
        print(f"   ghi chú   : {r['ghi_chu']}")
