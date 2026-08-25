#!/usr/bin/env python3
"""Xác minh 34 QID unit drift tới TÀI LIỆU GỐC — Pha 9 directive, F16 review 163.

Doc 162 nói "26/34 câu bản hiện tại đúng" nhưng phép kiểm khi đó chỉ là **nhất
quán nội tại** với `value_vnd` của chính pipeline. F16 đòi truy tới source unit.

Ở đây mỗi QID được kiểm bốn tầng độc lập nhau:

1. `question_unit`  — đơn vị câu hỏi đòi, đọc từ CHÍNH văn bản câu hỏi.
2. `source_unit`    — đơn vị của ô, đọc từ `col_path` trong TÀI LIỆU GỐC
                      (`data/external/.../*_extracted.txt`, có SHA256), không
                      lấy từ `scale_exponent` (trường đó là defect đã biết).
3. `source_value`   — chuỗi số thô trong đúng dòng gốc.
4. `expected`       — `source_value` quy về `question_unit`.

`verification_status`:
  `SOURCE_VERIFIED_CURRENT_CORRECT` — dòng gốc xác nhận bản hiện tại đúng, P0I sai
  `SOURCE_VERIFIED_P0I_CORRECT`     — ngược lại
  `SOURCE_VERIFIED_BOTH_WRONG`      — cả hai sai
  `UNIT_NOT_DETERMINED`             — không xác định được đơn vị câu hỏi
  `SOURCE_NOT_FOUND`                — không truy được dòng gốc

Chỉ QID `SOURCE_VERIFIED_CURRENT_CORRECT` mới được vào `proposed_u1_whitelist`.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/163/unit_drift"
FS = ROOT / "data/external/vifinqa/financial_statements"

DON_VI = [("nghìn tỷ", 12), ("nghin ty", 12), ("tỷ đồng", 9), ("tỉ đồng", 9),
          ("triệu usd", 6), ("triệu đồng", 6), ("nghìn đồng", 3), ("đồng", 0)]
COT_DV = [("nghìn tỷ", 12), ("tỷ đồng", 9), ("triệu đồng", 6), ("trieu dong", 6),
          ("nghìn đồng", 3), ("nghin dong", 3), ("triệu", 6), ("tỷ", 9),
          ("nghìn", 3), ("đồng", 0), ("vnd", 0), ("usd", 0)]


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def don_vi_hoi(t: str):
    t = (t or "").lower()
    if "%" in t or "phần trăm" in t:
        return "percent", None
    for k, e in DON_VI:
        if k in t:
            return k, e
    return None, None


def don_vi_cot(c: str):
    c = (c or "").lower()
    for k, e in COT_DV:
        if k in c:
            return k, e
    return None, None


def tach_ref(ev):
    m = re.match(r"^(.*?)\|(?:line[:\-]?)?(\d+)$", str(ev or ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def tim_doc(doc):
    m = re.match(r"^([A-Z0-9]+)_financial_statements_(\d{4})_", doc or "")
    if not m:
        return None
    p = FS / m.group(1) / m.group(2) / doc / f"{doc}_extracted.txt"
    return p if p.is_file() else None


def so(s):
    return re.sub(r"\D", "", str(s or ""))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "source_unit_excerpts").mkdir(exist_ok=True)

    A = {r["id"]: r for r in json.loads(zipfile.ZipFile(
        ROOT / "data/submissions/submission_P0I.zip").read("submission.json"))}
    B = {r["id"]: r for r in json.loads(zipfile.ZipFile(
        Path("/tmp/replay_P0I.zip")).read("submission.json"))}
    a6 = {json.loads(l)["qid"]: json.loads(l) for l in
          (ROOT / "data/dev/answer_a6/records_a6.jsonl").open(encoding="utf-8")
          if l.strip()}

    qs = sorted(q for q in A if A[q].get("answer") != B[q].get("answer"))
    rows, dem = [], {}
    cache = {}
    for q in qs:
        Q = A[q]["question"]
        u_hoi, e_hoi = don_vi_hoi(Q)
        p = (a6.get(q) or {}).get("provenance") or {}
        ev = p.get("evidence_ref")
        doc, ln = tach_ref(ev)
        r = {"qid": q, "question": Q[:180], "question_unit": u_hoi,
             "question_unit_exp": e_hoi,
             "evidence_ref": ev, "row_path": p.get("row_path"),
             "col_path": p.get("col_path"),
             "pipeline_unit_scale_exponent": p.get("scale_exponent"),
             "pipeline_value_vnd": p.get("value_vnd"),
             "query_conversion": str(A[q].get("pandas_query") or "")[-40:],
             "answer_P0I": A[q].get("answer"), "answer_CURRENT": B[q].get("answer")}

        u_cot, e_cot = don_vi_cot(p.get("col_path"))
        r["source_unit_from_col_path"] = u_cot
        r["source_unit_exp"] = e_cot

        if doc:
            if doc not in cache:
                pp = tim_doc(doc)
                cache[doc] = ((pp, shaf(pp), pp.read_text(encoding="utf-8",
                              errors="replace").splitlines()) if pp else (None,) * 3)
            pp, sha, lines = cache[doc]
            if pp is not None and ln and 0 < ln <= len(lines):
                r["source_doc"] = str(pp.relative_to(ROOT))
                r["source_doc_sha256"] = sha
                dong = lines[ln - 1]
                a_, b_ = max(0, ln - 2), min(len(lines), ln + 1)
                r["source_excerpt"] = "\n".join(
                    f"{k+1}: {lines[k]}" for k in range(a_, b_))[:900]
                r["source_value_raw"] = p.get("value_source_raw")
                r["source_value_in_line"] = (
                    bool(so(p.get("value_source_raw")))
                    and so(p.get("value_source_raw")) in so(dong))
            else:
                r["source_doc"] = None

        st = "SOURCE_NOT_FOUND"
        if r.get("source_doc") and r.get("source_value_in_line"):
            if u_hoi == "percent" or e_hoi is None:
                st = "UNIT_NOT_DETERMINED"
            elif e_cot is None:
                st = "UNIT_NOT_DETERMINED"
            else:
                try:
                    raw = float(so(p.get("value_source_raw")))
                    ky_vong = raw * (10 ** (e_cot - e_hoi))
                    r["expected_answer_in_question_unit"] = ky_vong

                    def kh(x):
                        try:
                            x = float(x)
                        except Exception:
                            return False
                        m = max(abs(x), abs(ky_vong), 1e-12)
                        return abs(x - ky_vong) / m < 1e-6
                    cur, p0i = kh(B[q].get("answer")), kh(A[q].get("answer"))
                    st = ("SOURCE_VERIFIED_CURRENT_CORRECT" if cur and not p0i else
                          "SOURCE_VERIFIED_P0I_CORRECT" if p0i and not cur else
                          "SOURCE_VERIFIED_BOTH_WRONG" if not cur and not p0i else
                          "SOURCE_VERIFIED_BOTH_CORRECT")
                except Exception:
                    st = "UNIT_NOT_DETERMINED"
        elif r.get("source_doc"):
            st = "SOURCE_VALUE_NOT_IN_LINE"
        r["verification_status"] = st
        dem[st] = dem.get(st, 0) + 1
        rows.append(r)
        if r.get("source_excerpt"):
            (OUT / "source_unit_excerpts" / f"qid_{q:04d}.md").write_text(
                f"# QID {q}\n\n{Q}\n\n- evidence_ref: {ev}\n"
                f"- col_path: {p.get('col_path')}\n"
                f"- doc_sha256: {r.get('source_doc_sha256')}\n"
                f"- status: {st}\n\n```\n{r['source_excerpt']}\n```\n",
                encoding="utf-8")

    (OUT / "unit_drift_34.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")

    wl = [r["qid"] for r in rows
          if r["verification_status"] == "SOURCE_VERIFIED_CURRENT_CORRECT"]
    (OUT / "unit_verified_26_or_corrected_count.jsonl").write_text(
        "\n".join(json.dumps({
            "qid": r["qid"], "verification_status": r["verification_status"],
            "question_unit": r["question_unit"],
            "source_unit_from_col_path": r["source_unit_from_col_path"],
            "source_value_raw": r.get("source_value_raw"),
            "expected_answer_in_question_unit": r.get("expected_answer_in_question_unit"),
            "answer_P0I": r["answer_P0I"], "answer_CURRENT": r["answer_CURRENT"],
            "source_doc_sha256": r.get("source_doc_sha256"),
        }, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    (OUT / "proposed_u1_whitelist.json").write_text(json.dumps({
        "_schema": "proposed_u1_whitelist v1",
        "quy_tac": ("CHỈ nhận QID có verification_status = "
                    "SOURCE_VERIFIED_CURRENT_CORRECT, tức đã truy tới đúng dòng "
                    "trong tài liệu gốc có SHA256 và đơn vị đọc từ col_path."),
        "claim_doc_162": "26/34",
        "so_thuc_te_xac_minh_duoc": len(wl),
        "CLAIM_STATUS": ("VERIFIED" if len(wl) == 26 else
                         f"CORRECTED_TO_{len(wl)}"),
        "phan_bo_trang_thai": dem,
        "whitelist_qids": wl,
        "loai_tru": {r["verification_status"]: [x["qid"] for x in rows
                     if x["verification_status"] == r["verification_status"]]
                     for r in rows if r["verification_status"]
                     != "SOURCE_VERIFIED_CURRENT_CORRECT"},
        "khong_rebuild_953": True,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({"n_qid_lech": len(rows), "phan_bo": dem,
                      "whitelist_n": len(wl), "whitelist": wl},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
