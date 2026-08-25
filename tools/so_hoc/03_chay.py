"""P0-g bước 3 · chạy engine số học cho 1.012 câu.

`UNCERTAIN` -> LÙI VỀ đáp án tra-cứu-một-ô của P0-f (records_v3). Bài nộp bắt
buộc có một `answer` kiểu số, nên `UNCERTAIN` không thể xuất ra bài nộp; nó được
ghi vào artifact của ta. Không câu nào bị làm cho tệ đi.
"""
from __future__ import annotations
import importlib, json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/so_hoc"))
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

E = importlib.import_module("02_engine")
from text2pandas.application.usecases.answer import write_long_csv          # noqa: E402
from text2pandas.domain.rules.question import CompanyIndex, parse_question  # noqa: E402

OCR = ROOT / "data/external/vifinqa/financial_statements"
RA = ROOT / "data/dev/so_hoc"
DATA = RA / "data"
GHI = RA / "records_sohoc.jsonl"
_TABLE = re.compile(r"<table.*?</table>", re.S)
TOI_DA_BANG = 24


def html_tho(doc_id, dong, cache):
    if doc_id not in cache:
        p = OCR / doc_id.split("_")[0] / doc_id.split("_")[-2] / doc_id / f"{doc_id}_extracted.txt"
        cache[doc_id] = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []
    L = cache[doc_id]
    if not (1 <= dong <= len(L)):
        return ""
    m = _TABLE.search("\n".join(L[dong - 1: dong + 40]))
    return m.group(0) if m else ""


def main(argv):
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    # Dùng truy hồi THEO Ô (bước 4) — top-N toàn cục thiếu bảng của từng năm.
    refs = json.loads(Path("/tmp/refs_cell.json").read_text())
    PL = {r["id"]: r for r in (json.loads(l) for l in (RA / "phan_loai.jsonl").open(encoding="utf-8") if l.strip())}
    qs = [json.loads(l) for l in (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8") if l.strip()]
    companies = CompanyIndex.from_csv(ROOT / "data/external/vifinqa/code_stock.csv")
    card = sqlite3.connect("file:data/silver/card_index.sqlite?mode=ro", uri=True)
    MU = {f"{d}|{ln}": ue for d, ln, ue in card.execute("SELECT doc_id,line_no,unit_exponent FROM card_meta")}
    work = sqlite3.connect(f"file:{os.path.expanduser('~/fast/artifacts/retrieval/work.db')}?mode=ro", uri=True)
    known = {r[0] for r in work.execute("SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}

    DATA.mkdir(parents=True, exist_ok=True)
    cu = {}
    if GHI.is_file():
        for l in GHI.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l); cu[r["qid"]] = r
    da_ghi = set()
    cache = {}
    n = 0
    for q in qs[tu - 1:den]:
        qid = q["id"]
        if qid in cu:
            continue
        pl = PL[qid]
        lop, don_vi = pl["lop"], pl["don_vi_hoi"]
        slots = parse_question(qid, q["question"], companies, known)
        bangs = []
        for x in (refs.get(str(qid)) or [])[:TOI_DA_BANG]:
            d, _, ln = x.rpartition("|")
            b = E.nap_bang(x, html_tho(d, int(ln), cache), MU.get(x))
            if b:
                bangs.append(b)
        kq = E.KetQua("UNCERTAIN", ghi_chu=[f"lớp `{lop}` chưa có phép toán"])
        if bangs:
            nam = sorted(slots.years)
            # KHÔNG dùng `slots.tickers`: `parse_question` mắc lỗi RC-2,
            # một mã tường minh làm mất mọi mã suy từ tên. Xem 02_engine.
            tks = E.phan_giai_ma(q["question"], companies, known)
            tk1 = tks[0] if len(tks) == 1 else None
            basis = slots.basis          # "separate" khi câu nêu "công ty mẹ"
            if lop == "ratio":
                kq = E.tinh_ratio(q["question"], bangs, tk1, nam[0] if nam else None, don_vi, basis)
            elif lop == "percentage_change":
                kq = E.tinh_percentage_change(q["question"], bangs, tk1, nam, don_vi, basis)
            elif lop == "difference":
                kq = E.tinh_difference(q["question"], bangs, tks, nam, don_vi, basis)
            elif lop in ("sum", "average"):
                kq = E.tinh_gop(q["question"], bangs, tks, nam, don_vi, lop, basis)
            elif lop == "max_min":
                phep = "min" if re.search(r"nho nhat|thap nhat", E.fold(q["question"])) else "max"
                kq = E.tinh_gop(q["question"], bangs, tks, nam, don_vi, phep, basis)
            elif lop == "argmax_year":
                kq = E.tinh_argmax_year(q["question"], bangs, tks, nam, basis)
        if kq.trang_thai == "OK":
            for b in bangs:
                ten = E.csv_ten(b.locator)
                if any(e["csv_path"].endswith(ten) for e in kq.evidence) and ten not in da_ghi:
                    write_long_csv(DATA / ten, b.rows)
                    da_ghi.add(ten)
        cu[qid] = {
            "qid": qid, "lop": lop, "don_vi_hoi": don_vi, "trang_thai": kq.trang_thai,
            "answer": kq.answer, "pandas_query": kq.pandas_query, "evidence": kq.evidence,
            "cong_thuc": kq.cong_thuc, "ghi_chu": kq.ghi_chu,
            "operands": [t.mo_ta() for t in kq.operands],
        }
        n += 1
        if n % 40 == 0:
            with GHI.open("w", encoding="utf-8") as f:
                for k in sorted(cu):
                    f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    with GHI.open("w", encoding="utf-8") as f:
        for k in sorted(cu):
            f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    ok = sum(1 for r in cu.values() if r["trang_thai"] == "OK")
    print(f"chay {n} cau · tong {len(cu)}/1012 · OK {ok} · UNCERTAIN {len(cu)-ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
