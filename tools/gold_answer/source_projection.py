#!/usr/bin/env python3
"""source_cell_projection + source excerpt — F4 của review 163.

Review 163 §4 F4 nói đúng: `work.db.observations` là **sản phẩm của extraction
pipeline**, không phải nguồn độc lập. Nếu gold chỉ dựa vào nó thì mọi defect
extraction (period bị ép, nhãn bị cắt, scale normalize sai) sẽ đi thẳng vào gold.

Nhưng tài liệu GỐC vẫn còn trên đĩa:

    data/raw/btc/financial_statements/<TICKER>/<YEAR>/<doc>/<doc>_extracted.txt

`evidence_ref` có dạng `DOC|line:N`, và `N` là **số dòng 1-based trong chính file
extracted.txt đó**. Vì vậy mỗi gold operand truy được về **một dòng văn bản gốc**,
độc lập với work.db. Script này:

1. định vị file gốc + SHA256 của nó;
2. trích đúng dòng `N` (kèm 1 dòng trước/sau làm ngữ cảnh);
3. kiểm `value_source_raw` của gold có **thật sự xuất hiện** trong dòng đó không;
4. gắn `observation_uid` từ work.db để reviewer đối chiếu chéo hai nguồn.

Trạng thái từng operand:
  `SOURCE_LINE_VERIFIED`        — giá trị thô có mặt trong dòng gốc
  `SOURCE_LINE_FOUND_VALUE_NOT_MATCHED` — tìm được dòng nhưng không thấy giá trị
  `SOURCE_DOC_NOT_FOUND`       — không định vị được tài liệu gốc
  `NO_EVIDENCE_REF`            — nhãn không ghi `DOC|line:N`
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GD = ROOT / "data/curated/dev-legacy/answer_gold"
OUT = ROOT / "reports/163/gold"
FS = ROOT / "data/raw/btc/financial_statements"
WORK = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tach_ref(ev: str):
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", str(ev or ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def tim_doc(doc: str) -> Path | None:
    """`NAB_financial_statements_2024_consolidated` -> file extracted.txt."""
    m = re.match(r"^([A-Z0-9]+)_financial_statements_(\d{4})_", doc or "")
    if not m:
        return None
    p = FS / m.group(1) / m.group(2) / doc / f"{doc}_extracted.txt"
    return p if p.is_file() else None


def so_hoa(s: str) -> str:
    """Bỏ mọi ký tự không phải chữ số để so khớp giá trị thô kiểu `1.484.894`."""
    return re.sub(r"\D", "", str(s or ""))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "source_excerpts").mkdir(exist_ok=True)

    gold = [json.loads(l) for l in
            (GD / "answer_gold_wave1_final.jsonl").open(encoding="utf-8") if l.strip()]

    con = None
    if WORK.is_file():
        con = sqlite3.connect("file:" + os.path.abspath(WORK) + "?mode=ro", uri=True)

    rows, dem = [], {}
    cache_doc: dict[str, tuple] = {}
    for g in gold:
        q = g["qid"]
        for i, c in enumerate(g.get("gold_cells") or []):
            ev = c.get("evidence_ref")
            doc, ln = tach_ref(ev)
            rec = {"qid": q, "operand_index": i, "role": c.get("role"),
                   "evidence_ref": ev, "doc": doc, "line_1based": ln,
                   "row_path": c.get("row_path"), "col_path": c.get("col_path"),
                   "raw_gold": c.get("raw"),
                   "value_in_col_unit": c.get("value_in_col_unit"),
                   "col_unit": c.get("col_unit"), "period_end": c.get("period_end")}
            if not doc or ln is None:
                rec["source_status"] = "NO_EVIDENCE_REF"
                rows.append(rec); dem[rec["source_status"]] = dem.get(rec["source_status"], 0) + 1
                continue
            if doc not in cache_doc:
                p = tim_doc(doc)
                cache_doc[doc] = ((p, shaf(p),
                                   p.read_text(encoding="utf-8", errors="replace")
                                    .splitlines()) if p else (None, None, None))
            p, sha, lines = cache_doc[doc]
            if p is None:
                rec["source_status"] = "SOURCE_DOC_NOT_FOUND"
            else:
                rec["source_doc_path"] = str(p.relative_to(ROOT))
                rec["source_doc_sha256"] = sha
                rec["source_doc_n_lines"] = len(lines)
                a, b = max(0, ln - 2), min(len(lines), ln + 1)
                excerpt = "\n".join(f"{k+1}: {lines[k]}" for k in range(a, b))
                rec["source_excerpt"] = excerpt[:1200]
                target = lines[ln - 1] if 0 < ln <= len(lines) else ""
                sg = so_hoa(c.get("raw"))
                rec["raw_xuat_hien_trong_dong"] = bool(sg) and sg in so_hoa(target)
                rec["source_status"] = ("SOURCE_LINE_VERIFIED"
                                        if rec["raw_xuat_hien_trong_dong"]
                                        else "SOURCE_LINE_FOUND_VALUE_NOT_MATCHED")
            if con is not None and doc and ln:
                r = con.execute(
                    "SELECT observation_uid, value_source_raw, scale_exponent,"
                    " period_end, statement_type FROM observations"
                    " WHERE evidence_ref = ? AND row_path_text = ?"
                    " AND col_path_text = ? LIMIT 1",
                    (f"{doc}|line:{ln}", c.get("row_path"), c.get("col_path"))
                ).fetchone()
                rec["workdb"] = (
                    {"observation_uid": r[0], "value_source_raw": r[1],
                     "scale_exponent": r[2], "period_end": r[3],
                     "statement_type": r[4]} if r else None)
                rec["workdb_khop_gold_raw"] = (
                    bool(r) and so_hoa(r[1]) == so_hoa(c.get("raw")))
            dem[rec["source_status"]] = dem.get(rec["source_status"], 0) + 1
            rows.append(rec)

    (OUT / "source_cell_projection.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")

    # excerpt riêng theo QID để reviewer đọc nhanh
    theo_qid: dict[int, list] = {}
    for r in rows:
        theo_qid.setdefault(r["qid"], []).append(r)
    for q, v in theo_qid.items():
        txt = [f"# QID {q} — {len(v)} operand", ""]
        for r in v:
            txt += [f"## operand[{r['operand_index']}] role={r.get('role')}",
                    f"evidence_ref: {r.get('evidence_ref')}",
                    f"status: {r['source_status']}",
                    f"doc_sha256: {r.get('source_doc_sha256')}",
                    "```", str(r.get("source_excerpt") or "(không có)"), "```", ""]
        (OUT / "source_excerpts" / f"qid_{q:04d}.md").write_text(
            "\n".join(txt), encoding="utf-8")

    n_ok = sum(1 for g in gold if g["trang_thai"] == "OK")
    qid_ok = {g["qid"] for g in gold if g["trang_thai"] == "OK"}
    r_ok = [r for r in rows if r["qid"] in qid_ok]
    ver = sum(1 for r in r_ok if r["source_status"] == "SOURCE_LINE_VERIFIED")
    qid_full = {q for q, v in theo_qid.items()
                if q in qid_ok and all(x["source_status"] == "SOURCE_LINE_VERIFIED"
                                       for x in v)}
    tom = {
        "_schema": "source_cell_projection_summary v1",
        "n_gold": len(gold), "n_gold_OK": n_ok,
        "n_operand_tong": len(rows), "n_operand_cua_gold_OK": len(r_ok),
        "trang_thai_operand": dem,
        "operand_cua_gold_OK_verified_toi_dong_goc": f"{ver}/{len(r_ok)}",
        "n_QID_OK_co_TOAN_BO_operand_verified": len(qid_full),
        "qid_full_verified": sorted(qid_full),
        "KET_LUAN": (
            "Các operand có SOURCE_LINE_VERIFIED được truy tới ĐÚNG DÒNG trong "
            "tài liệu gốc extracted.txt (có SHA256), độc lập với work.db. "
            "Các operand còn lại vẫn là NOT_INDEPENDENT_SOURCE_VERIFIED."),
    }
    (OUT / "source_cell_projection_summary.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
