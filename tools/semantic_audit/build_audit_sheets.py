#!/usr/bin/env python3
"""Sinh phiếu audit ngữ nghĩa cho 24 U1 case — Pha 2 directive 165.

Mỗi phiếu chứa ĐỦ thứ để một auditor độc lập phán quyết chín chiều A–I mà
**không cần** tin bất kỳ kết luận nào của team:

* câu hỏi nguyên văn;
* **ô mà P0I đang dùng** — row_path/col_path/evidence_ref/giá trị;
* `pandas_query` thật trong bài nộp;
* **dòng gốc** trong `*_extracted.txt` kèm SHA256 tài liệu và ±12 dòng ngữ cảnh
  (đủ để thấy tiêu đề bảng, đơn vị cột, dòng tổng);
* danh sách tài liệu cùng ticker để kiểm entity/basis/kỳ.

Cố ý KHÔNG đưa vào phiếu: `answer_CURRENT`, whitelist, kết luận unit-drift,
funnel. Auditor phải tự phán quyết, không được mồi.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/165/audit_sheets"
FS = ROOT / "data/raw/btc/financial_statements"
WORK = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"
NGU_CANH = 12


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def tach(ev):
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", str(ev or ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def tim(doc):
    m = re.match(r"^([A-Z0-9]+)_financial_statements_(\d{4})_", doc or "")
    if not m:
        return None
    p = FS / m.group(1) / m.group(2) / doc / f"{doc}_extracted.txt"
    return p if p.is_file() else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wl = json.loads((ROOT / "reports/163/unit_drift/proposed_u1_whitelist.json")
                    .read_text(encoding="utf-8"))["whitelist_qids"]
    sub = {r["id"]: r for r in json.loads(zipfile.ZipFile(
        ROOT / "artifacts/submissions/legacy/submission_P0I.zip").read("submission.json"))}
    a6 = {json.loads(l)["qid"]: json.loads(l) for l in
          (ROOT / "data/curated/dev-legacy/answer_a6/records_a6.jsonl").open(encoding="utf-8")
          if l.strip()}
    con = sqlite3.connect("file:" + os.path.abspath(WORK) + "?mode=ro", uri=True)

    idx = []
    for q in wl:
        rec, m = sub[q], a6.get(q) or {}
        p = m.get("provenance") or {}
        ev = p.get("evidence_ref")
        doc, ln = tach(ev)
        fp = tim(doc) if doc else None

        t = [f"# PHIẾU AUDIT NGỮ NGHĨA — QID {q}", "",
             "## 1 · Câu hỏi (nguyên văn)", "", rec["question"], "",
             "## 2 · Ô mà bài nộp P0I đang dùng", "",
             f"- evidence_ref : `{ev}`",
             f"- row_path     : `{p.get('row_path')}`",
             f"- col_path     : `{p.get('col_path')}`",
             f"- giá trị thô  : `{p.get('value_source_raw')}`",
             f"- period_end   : `{p.get('period_end')}` · period_role "
             f"`{p.get('period_role')}`",
             f"- statement    : `{doc}`", "",
             "## 3 · pandas_query trong bài nộp", "", "```python",
             str(rec.get("pandas_query"))[:600], "```", "",
             "## 4 · evidence đính kèm", "",
             "```json", json.dumps(rec.get("evidence"), ensure_ascii=False), "```", "",
             "## 5 · relevant_tables mà retrieval trả về", "",
             "```json", json.dumps(rec.get("relevant_tables"), ensure_ascii=False), "```", ""]

        if fp and ln:
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            a, b = max(0, ln - 1 - NGU_CANH), min(len(lines), ln + NGU_CANH)
            t += ["## 6 · DÒNG GỐC trong tài liệu (nguồn sự thật)", "",
                  f"- file      : `{fp.relative_to(ROOT)}`",
                  f"- sha256    : `{shaf(fp)}`",
                  f"- dòng đích : **{ln}** (1-based) — đánh dấu `>>>`", "", "```"]
            for k in range(a, b):
                t.append(("&gt;&gt;&gt; " if k + 1 == ln else "    ")
                         + f"{k+1}: {lines[k]}")
            t += ["```", ""]
        else:
            t += ["## 6 · DÒNG GỐC", "", "**KHÔNG ĐỊNH VỊ ĐƯỢC TÀI LIỆU GỐC**", ""]

        # các tài liệu cùng ticker — để kiểm entity/basis/kỳ
        tk = (doc or "").split("_")[0]
        docs = [r[0] for r in con.execute(
            "SELECT DISTINCT directory_doc_id FROM observations WHERE ticker=?"
            " ORDER BY directory_doc_id", (tk,))] if tk else []
        t += ["## 7 · Mọi tài liệu của cùng mã (kiểm entity/basis/kỳ)", "",
              "```", "\n".join(docs[:40]), "```", "",
              "## 8 · Việc của bạn", "",
              "Phán quyết ĐỘC LẬP chín chiều A–I. Xem prompt.", ""]

        f = OUT / f"qid_{q:04d}.md"
        f.write_text("\n".join(t), encoding="utf-8")
        idx.append({"qid": q, "sheet": str(f.relative_to(ROOT)),
                    "question": rec["question"],
                    "selected_row_path": p.get("row_path"),
                    "selected_col_path": p.get("col_path"),
                    "selected_evidence_ref": ev,
                    "selected_raw": p.get("value_source_raw"),
                    "source_doc_sha256": shaf(fp) if fp else None})
    (ROOT / "reports/165/audit_index.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in idx) + "\n",
        encoding="utf-8")
    print(f"đã sinh {len(idx)} phiếu -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
