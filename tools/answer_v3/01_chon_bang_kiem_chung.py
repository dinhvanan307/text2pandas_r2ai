"""S4-P0 · CHỌN BẢNG BẰNG KIỂM CHỨNG, thay vì luôn lấy hạng 1.

VẤN ĐỀ (đo được, docs/96 §A):
    `answer_question` lấy `primary = chosen[0]` — LUÔN là bảng hạng 1 của
    Retrieval. Trần của kiến trúc ấy = hit@1 = **0,3579** trên gold v2.
    EXECUTION thực tế = 0,1087.
    Nhưng danh sách ĐÃ NỘP (N̄ = 7,67) chứa ít nhất một bảng gold ở
    **0,8211** số câu. ⇒ đổi từ "đọc hạng 1" sang "thử cả danh sách rồi CHỌN"
    nâng trần **×2,29 mà không đụng một dòng nào của Retrieval**.

CƠ CHẾ — vì sao S4 chọn tốt hơn S2 xếp hạng:
    S2 xếp hạng bằng BM25 trên nhãn dòng — nó ĐOÁN bảng nào chứa chỉ tiêu.
    S4 thì PARSE được bảng thật: nó biết dòng ấy có tồn tại không, có ô số
    đọc được không, cột có đúng kỳ không. Kiểm chứng mạnh hơn xếp hạng.

CÁCH LÀM — tối thiểu, không rẽ nhánh pipeline:
    Gọi lại ĐÚNG `answer_question` đã có, mỗi lần với MỘT bảng làm primary,
    rồi giữ kết quả có `confidence` cao nhất. Mọi logic khác (`_pick_cell`,
    quy đổi đơn vị, bất biến `answer == eval(pandas_query)`) dùng nguyên bản.
    `src/text2pandas/**` KHÔNG đổi một byte.

BẤT BIẾN AN TOÀN:
    Không bảng nào cho `confidence > 0` ⇒ **lùi về đúng hành vi cũ** (hạng 1).
    Vì thế bản này không thể tệ hơn bản cũ ở tầng chọn bảng.

`relevant_tables` / `relevant_docs` GIỮ NGUYÊN XI — hợp đồng Retrieval đã FREEZE.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.application.usecases.answer import answer_question, write_long_csv  # noqa: E402
from text2pandas.domain.rules.question import CompanyIndex, parse_question           # noqa: E402
from text2pandas.infrastructure.retrieval.index import TableHit                      # noqa: E402

sys.path.insert(0, str(ROOT / "tools" / "answer_v2"))
if os.environ.get("LOC_COT", "1") == "1":          # bộ lọc cột phi giá trị của P0-f
    import importlib
    importlib.import_module("06_loc_cot_phi_gia_tri").bat()

OCR = ROOT / "data/raw/btc/financial_statements"
CARD = ROOT / "artifacts/legacy/silver-pre-a6/card_index.sqlite"
REFS = ROOT / "artifacts/runs/retrieval/vplus/refs_1012.json"
RA = ROOT / "data/curated/dev-legacy/answer_v3"
DATA = RA / "data"
GHI = RA / "records_v4.jsonl"
SO = RA / "chon_bang_log.jsonl"

M_MAX = int(os.environ.get("M_MAX", "8"))          # số bảng tối đa đem ra thử
K, CAP = 3, 30                                     # chính sách N đã FREEZE

_TABLE = re.compile(r"<table.*?</table>", re.S)


def raw_html(doc_id: str, dong: int, cache: dict) -> str:
    if doc_id not in cache:
        p = OCR / doc_id.split("_")[0] / doc_id.split("_")[-2] / doc_id / f"{doc_id}_extracted.txt"
        cache[doc_id] = (p.read_text(encoding="utf-8", errors="replace").splitlines()
                         if p.is_file() else [])
    lines = cache[doc_id]
    if not (1 <= dong <= len(lines)):
        return ""
    m = _TABLE.search("\n".join(lines[dong - 1: dong + 40]))
    return m.group(0) if m else ""


def main(argv: list[str]) -> int:
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    D = json.loads(REFS.read_text())
    qs = [json.loads(l) for l in
          (ROOT / "data/raw/btc/questions/questions.jsonl").open(encoding="utf-8") if l.strip()]
    companies = CompanyIndex.from_csv(ROOT / "data/raw/btc/metadata/companies.csv")

    card = sqlite3.connect(f"file:{CARD}?mode=ro", uri=True)
    META = {f"{d}|{ln}": (nr, nc, ue) for d, ln, nr, nc, ue in card.execute(
        "SELECT doc_id, line_no, n_rows, n_cols, unit_exponent FROM card_meta")}
    work = sqlite3.connect(
        f"file:{ROOT / 'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro", uri=True)
    known = {r[0] for r in work.execute(
        "SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}

    DATA.mkdir(parents=True, exist_ok=True)
    cu, log, da_ghi = {}, {}, set()
    for p, d in ((GHI, cu), (SO, log)):
        if p.is_file():
            for l in p.open(encoding="utf-8"):
                if l.strip():
                    r = json.loads(l)
                    d[r["qid"]] = r
    for r in cu.values():
        if r.get("csv_name"):
            da_ghi.add(r["csv_name"])

    cache: dict = {}
    n = 0
    for q in qs[tu - 1:den]:
        qid = q["id"]
        if qid in cu:
            continue
        slots = parse_question(qid, q["question"], companies, known)
        ent = D.get(str(qid)) or {"o": 1, "refs": []}
        N = min(max(1, K * ent["o"]), CAP)
        refs = ent["refs"][:N][:M_MAX]

        ung_vien = []
        for i, x in enumerate(refs):
            d, _, ln = x.rpartition("|")
            nr, nc, ue = META.get(x, (0, 0, None))
            h = raw_html(d, int(ln), cache)
            if not h:
                continue
            hit = TableHit(d, int(ln), 100.0, nr, nc, ue)
            try:
                res = answer_question(slots, [hit], {x: h}, n_tables=1,
                                      doc_ranking=[], n_docs=0)
            except Exception as e:                     # fail-closed: bỏ ứng viên
                log.setdefault(qid, {"qid": qid, "loi": []})["loi"].append(f"{x}: {e!r}"[:120])
                continue
            if res.answer is None:
                continue
            ung_vien.append((res.confidence, -i, i, x, res))

        if not ung_vien:
            r = {"qid": qid, "answer": 0.0, "pandas_query": "", "evidence": [],
                 "confidence": 0.0, "csv_name": "", "has_csv": False,
                 "notes": ["khong ung vien nao doc duoc"]}
            log[qid] = {"qid": qid, "n_thu": len(refs), "chon_hang": None, "conf": 0.0}
        else:
            ung_vien.sort(key=lambda t: (t[0], t[1]), reverse=True)
            conf, _, hang, loc, res = ung_vien[0]
            if res.csv_rows and res.csv_name and res.csv_name not in da_ghi:
                write_long_csv(DATA / res.csv_name, res.csv_rows)
                da_ghi.add(res.csv_name)
            r = {"qid": res.qid, "answer": res.answer, "pandas_query": res.pandas_query,
                 "evidence": res.evidence, "confidence": res.confidence,
                 "csv_name": res.csv_name,
                 "has_csv": bool(res.csv_rows) or res.csv_name in da_ghi,
                 "notes": res.notes}
            log[qid] = {"qid": qid, "n_thu": len(ung_vien), "chon_hang": hang,
                        "chon_loc": loc, "conf": conf,
                        "conf_hang1": next((c for c, _, i, _, _ in ung_vien if i == 0), None)}
        cu[qid] = r
        n += 1
        if n % 25 == 0:
            _ghi(cu, log)
            print(f"  ..{n} câu", flush=True)
    _ghi(cu, log)
    doi = sum(1 for k, v in log.items() if v.get("chon_hang") not in (0, None))
    print(f"dựng {n} đáp án mới · tổng {len(cu)}/1012 · csv {len(da_ghi)}")
    print(f"CHỌN KHÁC HẠNG 1: {doi}/{len(log)} câu")
    return 0


def _ghi(cu, log):
    GHI.parent.mkdir(parents=True, exist_ok=True)
    with GHI.open("w", encoding="utf-8") as f:
        for k in sorted(cu):
            f.write(json.dumps(cu[k], ensure_ascii=False) + "\n")
    with SO.open("w", encoding="utf-8") as f:
        for k in sorted(log):
            f.write(json.dumps(log[k], ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
