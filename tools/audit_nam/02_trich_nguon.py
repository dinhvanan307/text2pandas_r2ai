"""P0-e buoc 2 · trich BANG THO tu van ban OCR goc.

VI SAO DOC TU NGUON, KHONG DOC `table_cards`
--------------------------------------------
Hai dac trung dang duoc danh gia deu la truong DAN XUAT cua A6:
`doc_year` va `periods`. Neu phan xu bang chinh chung thi lai vong tron mot
lan nua — dung cai loi da lam hong docs/86 §4.

Nen buoc nay chi dung:
  * `evidence_ref` (doc_id | so dong) — dia chi, khong phai bang chung
  * chinh tep `*_extracted.txt` cua BTC — nguon su that

Ket qua ghi ra `data/dev/audit/bang_tho.jsonl`, moi dong mot bang:
  table_uid · doc_id · tieu_de_cot (dong <tr> dau) · nhan_dong (td dau moi <tr>)
KHONG ghi `doc_year`, KHONG ghi `periods`.
"""
from __future__ import annotations
import json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OCR  = ROOT / "data/external/vifinqa/financial_statements"
RA   = ROOT / "data/dev/audit/bang_tho.jsonl"
DB   = Path(os.path.expanduser("~/fast/artifacts/retrieval/work.db"))

_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)


def duong_dan(doc_id: str) -> Path:
    tk, nam = doc_id.split("_")[0], doc_id.split("_")[-2]
    return OCR / tk / nam / doc_id / f"{doc_id}_extracted.txt"


def doc_bang(doc_id: str, dong: int, cache: dict) -> str | None:
    p = duong_dan(doc_id)
    if not p.is_file():
        return None
    if doc_id not in cache:
        cache[doc_id] = p.read_text(encoding="utf-8", errors="replace").splitlines()
    lines = cache[doc_id]
    if not (1 <= dong <= len(lines)):
        return None
    s = "\n".join(lines[dong - 1: dong + 40])
    i = s.find("<table")
    if i < 0:
        return None
    j = s.find("</table>", i)
    return s[i: j + 8] if j > 0 else s[i:]


def bocj(x: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()


def main(argv):
    ids = json.loads((ROOT / "data/dev/audit/mau_audit_nam.json").read_text())
    qs = {q for v in ids.values() for q in v}
    pool = {r["id"]: r for r in (json.loads(l) for l in
            (ROOT / "data/dev/gold_tay_pool_v5.jsonl").open(encoding="utf-8") if l.strip())}
    uids = sorted({c["table_uid"] for q in qs for c in pool[q]["candidates"]})
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    uids = uids[tu - 1: den]

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ref = {}
    for i in range(0, len(uids), 800):
        lot = uids[i:i + 800]
        for u, e in conn.execute(
                "SELECT table_uid,evidence_ref FROM table_cards WHERE table_uid IN (%s)"
                % ",".join("?" * len(lot)), lot):
            ref[u] = e

    cu = {}
    if RA.is_file():
        for l in RA.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l); cu[r["table_uid"]] = r
    cache, moi, hong = {}, 0, 0
    for u in uids:
        if u in cu:
            continue
        e = ref.get(u)
        if not e or "|line:" not in e:
            hong += 1; continue
        doc, dong = e.split("|line:")
        raw = doc_bang(doc, int(dong), cache)
        if not raw:
            hong += 1; continue
        trs = _TR.findall(raw)
        tds0 = [bocj(x) for x in _TD.findall(trs[0])] if trs else []
        nhan = [bocj(_TD.findall(t)[0]) if _TD.findall(t) else "" for t in trs[1:]]
        cu[u] = {"table_uid": u, "doc_id": doc, "dong": int(dong),
                 "tieu_de_cot": tds0,
                 "dong_dau_2": [bocj(x) for x in _TD.findall(trs[1])] if len(trs) > 1 else [],
                 "nhan_dong": [x for x in nhan if x][:60],
                 "so_dong": len(trs)}
        moi += 1
    RA.parent.mkdir(parents=True, exist_ok=True)
    with RA.open("w", encoding="utf-8") as f:
        for k in sorted(cu):
            f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    print(f"trich {moi} bang moi · tong {len(cu)} · khong doc duoc {hong}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
