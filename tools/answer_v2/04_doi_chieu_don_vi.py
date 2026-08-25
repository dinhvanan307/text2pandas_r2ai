"""P0-f · đối chiếu `unit_exponent` của A6 với ĐƠN VỊ IN TRONG BẢNG.

Gói P0F làm nhóm câu tiền hỏng NHIỀU HƠN P0E (money ngoài dải 49 → 111). Giả
thuyết: bảng nguồn mới thường đúng bảng hơn, nhưng `unit_exponent` khai báo cho
chúng lại sai — phần lớn khai 0 (VND) trong khi bảng in "Triệu đồng".

Bước này chỉ ĐO, chưa sửa gì.
"""
from __future__ import annotations
import json, re, sqlite3, unicodedata, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR = ROOT / "data/raw/btc/financial_statements"
_TABLE = re.compile(r"<table.*?</table>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def fold(s):
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def khoi(doc_id, dong, cache):
    if doc_id not in cache:
        p = OCR / doc_id.split("_")[0] / doc_id.split("_")[-2] / doc_id / f"{doc_id}_extracted.txt"
        cache[doc_id] = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []
    L = cache[doc_id]
    if not (1 <= dong <= len(L)):
        return "", ""
    truoc = "\n".join(L[max(0, dong - 4): dong - 1])          # dòng "Đơn vị tính:" hay đứng trên bảng
    m = _TABLE.search("\n".join(L[dong - 1: dong + 40]))
    return (m.group(0) if m else ""), truoc


def doc_don_vi(html, truoc):
    """Số mũ 10 mà bảng dùng, đọc từ chữ in trong bảng. None = không khai."""
    trs = _TR.findall(html)
    dau = " | ".join(x for t in trs[:3] for x in _TD.findall(t))
    t = fold(re.sub(r"<[^>]+>", " ", dau + " " + truoc))
    for mau, mu in ((r"nghin\s*ty\s*(dong|vnd)", 12), (r"tram\s*ty\s*(dong|vnd)", 11),
                    (r"\bty\s*(dong|vnd)\b", 9), (r"trieu\s*(dong|vnd)\b", 6),
                    (r"nghin\s*(dong|vnd)\b", 3), (r"\b(vnd|dong)\b", 0)):
        if re.search(mau, t):
            return mu
    return None


def main():
    card = sqlite3.connect("file:artifacts/legacy/silver-pre-a6/card_index.sqlite?mode=ro", uri=True)
    UE = {f"{d}|{ln}": ue for d, ln, ue in
          card.execute("SELECT doc_id,line_no,unit_exponent FROM card_meta")}
    rec = [json.loads(l) for l in (ROOT / "data/curated/dev-legacy/answer_v2/records.jsonl").open(encoding="utf-8") if l.strip()]
    _CSV = re.compile(r"data/(.+)_line(\d+)\.csv$")
    cache = {}
    bang = collections.Counter()
    vd = collections.defaultdict(list)
    for r in rec:
        ev = r.get("evidence") or []
        if not ev:
            continue
        m = _CSV.match(ev[0]["csv_path"])
        d, ln = m.group(1), int(m.group(2))
        k = f"{d}|{ln}"
        a6 = UE.get(k)
        html, truoc = khoi(d, ln, cache)
        doc = doc_don_vi(html, truoc)
        bang[(a6, doc)] += 1
        if a6 != doc and len(vd[(a6, doc)]) < 2:
            vd[(a6, doc)].append((r["qid"], k))
    print(f"{'A6 khai':>9}{'bang in':>9}{'so cau':>9}")
    for (a, b), n in sorted(bang.items(), key=lambda x: -x[1]):
        cho = "  ✓" if a == b else "  ✗"
        print(f"{str(a):>9}{str(b):>9}{n:>9}{cho}")
    tong = sum(bang.values())
    khop = sum(n for (a, b), n in bang.items() if a == b)
    print(f"\nkhop {khop}/{tong} = {khop/tong:.3f} · LECH {tong-khop} ({(tong-khop)/tong:.1%})")
    print("\nvai vi du lech:")
    for (a, b), ds in list(vd.items())[:6]:
        print(f"  A6={a} bang in={b}: " + ", ".join(f"q{q}·{k}" for q, k in ds))


if __name__ == "__main__":
    main()
