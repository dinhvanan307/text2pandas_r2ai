"""P0-f · dựng lại ĐÁP ÁN từ bảng do Retrieval MỚI xếp hạng #1.

VÌ SAO
------
Gói P0E thay `relevant_tables` bằng kết quả Retrieval mới (TABLES F2 0.1589 →
0.3538) nhưng GIỮ NGUYÊN `answer`/`pandas_query`/`evidence` của đường sinh cũ.
Đo lại trên chính gói đã nộp:

    986 câu có evidence
    102 (10,3%) có evidence == relevant_tables[0]
    288 (29,2%) có evidence nằm trong relevant_tables

Nghĩa là **71% câu** đang trả lời bằng một bảng thậm chí không có trong danh
sách ta nộp. Toàn bộ công Retrieval chưa hề chạm tới tầng đáp án.

THAY ĐỔI DUY NHẤT
-----------------
Nguồn `hits` cho `answer_question`: `search_cards` (chỉ mục BM25 cũ) →
xếp hạng của S1+S2 hiện tại. Mọi thứ khác giữ nguyên: `_pick_cell`, quy đổi đơn
vị, bất biến `answer == eval(pandas_query)`, định dạng CSV dài.

`relevant_tables` và `relevant_docs` được GIỮ NGUYÊN như P0E, để phép so sánh
chỉ có một biến. Đây là điều kiện để quy được thay đổi điểm về đúng nguyên nhân.
"""
from __future__ import annotations

import json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.application.usecases.answer import answer_question, write_long_csv  # noqa: E402
from text2pandas.domain.rules.question import CompanyIndex, parse_question           # noqa: E402
from text2pandas.infrastructure.retrieval.index import TableHit                      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get("LOC_COT") == "1":                    # bật bản ghi đè lọc cột
    import importlib
    _loc = importlib.import_module("06_loc_cot_phi_gia_tri")
    _loc.bat()

OCR = ROOT / "data/raw/btc/financial_statements"
CARD = ROOT / "artifacts/legacy/silver-pre-a6/card_index.sqlite"
WORK = Path(os.path.expanduser("data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"))
REFS = Path("/tmp/refs.json")
RA = ROOT / "data/curated/dev-legacy/answer_v2"
DATA = RA / ("data_v3" if os.environ.get("LOC_COT") == "1" else "data")
GHI = RA / ("records_v3.jsonl" if os.environ.get("LOC_COT") == "1" else "records.jsonl")

_TABLE = re.compile(r"<table.*?</table>", re.S)


def raw_html(doc_id: str, dong: int, cache: dict) -> str:
    """Đọc thẳng khối <table> từ văn bản OCR gốc — cùng nguồn P0-e đã dùng."""
    if doc_id not in cache:
        p = OCR / doc_id.split("_")[0] / doc_id.split("_")[-2] / doc_id / f"{doc_id}_extracted.txt"
        cache[doc_id] = p.read_text(encoding="utf-8", errors="replace").splitlines() if p.is_file() else []
    lines = cache[doc_id]
    if not (1 <= dong <= len(lines)):
        return ""
    s = "\n".join(lines[dong - 1: dong + 40])
    m = _TABLE.search(s)
    return m.group(0) if m else ""


def main(argv: list[str]) -> int:
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    refs = json.loads(REFS.read_text())
    qs = [json.loads(l) for l in
          (ROOT / "data/raw/btc/questions/questions.jsonl").open(encoding="utf-8") if l.strip()]
    companies = CompanyIndex.from_csv(ROOT / "data/raw/btc/metadata/companies.csv")

    card = sqlite3.connect(f"file:{CARD}?mode=ro", uri=True)
    META = {}
    for d, ln, nr, nc, ue in card.execute(
            "SELECT doc_id, line_no, n_rows, n_cols, unit_exponent FROM card_meta"):
        META[f"{d}|{ln}"] = (nr, nc, ue)
    work = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True)
    known = {r[0] for r in work.execute("SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}

    DATA.mkdir(parents=True, exist_ok=True)
    da_ghi = set()
    cu = {}
    if GHI.is_file():
        for l in GHI.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l); cu[r["qid"]] = r
                da_ghi.add(r.get("csv_name", ""))
    cache: dict = {}
    n = 0
    for q in qs[tu - 1:den]:
        if q["id"] in cu:
            continue
        slots = parse_question(q["id"], q["question"], companies, known)
        rr = refs.get(str(q["id"])) or []
        hits, html = [], {}
        for i, x in enumerate(rr[:5]):
            d, _, ln = x.rpartition("|")
            nr, nc, ue = META.get(x, (0, 0, None))
            # điểm giảm dần theo thứ hạng: `_select_tables` chỉ dùng nó để cắt,
            # còn `answer_question` luôn lấy `chosen[0]` làm bảng chính.
            hits.append(TableHit(d, int(ln), 100.0 - i, nr, nc, ue))
            h = raw_html(d, int(ln), cache)
            if h:
                html[f"{d}|{ln}"] = h
        if not hits:
            r = {"qid": q["id"], "answer": 0.0, "pandas_query": "", "evidence": [],
                 "confidence": 0.0, "csv_name": "", "has_csv": False,
                 "notes": ["Retrieval khong tra ve bang nao"]}
        else:
            res = answer_question(slots, hits, html, n_tables=5, doc_ranking=[], n_docs=0)
            if res.csv_rows and res.csv_name and res.csv_name not in da_ghi:
                write_long_csv(DATA / res.csv_name, res.csv_rows)
                da_ghi.add(res.csv_name)
            r = {"qid": res.qid, "answer": res.answer, "pandas_query": res.pandas_query,
                 "evidence": res.evidence, "confidence": res.confidence,
                 "csv_name": res.csv_name, "has_csv": bool(res.csv_rows) or res.csv_name in da_ghi,
                 "notes": res.notes}
        cu[q["id"]] = r
        n += 1
        if n % 25 == 0:
            with GHI.open("w", encoding="utf-8") as f:
                for k in sorted(cu):
                    f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    with GHI.open("w", encoding="utf-8") as f:
        for k in sorted(cu):
            f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    print(f"dung {n} dap an moi · tong {len(cu)}/1012 · csv {len(da_ghi)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
