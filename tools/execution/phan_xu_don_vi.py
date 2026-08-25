"""B3 · Phân xử 44 `unit_evidence_conflict` bằng RAW EVIDENCE, không bằng "ai khác ai".

Nguyên tắc: đơn vị của một ô là thứ được IN RA trong tài liệu. Nếu `col_path`,
`row_path`, tiêu đề bảng hoặc section có ghi rõ "Triệu đồng"/"Tỷ đồng"/… thì đó là
BẰNG CHỨNG TRỰC TIẾP, mạnh hơn cả A6 lẫn bộ suy đơn vị mức bảng.

Bốn trạng thái cuối (docs/102 §B3) — `KEEP_A6_FLAGGED` bị loại bỏ:
    CONFIRMED_A6        raw evidence khớp scale của A6            -> dùng A6
    A6_DEFECT           raw evidence chứng minh A6 sai            -> ghi đè scale
    FALLBACK_REQUIRED   A6 không có bằng chứng, nguồn khác có     -> không dùng A6
    UNRESOLVED_BLOCKED  không đủ bằng chứng phân xử               -> không dùng A6
"""
from __future__ import annotations
import json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/execution/h0"
NGUON = OUT / "unit_evidence_conflicts.jsonl"
RA = OUT / "unit_conflict_adjudication.jsonl"

# token đơn vị -> số mũ. Thứ tự quan trọng: khớp cụm dài trước.
DV = [("nghin ty", 12), ("nghìn tỷ", 12), ("nghìn tỉ", 12),
      ("ty dong", 9), ("tỷ đồng", 9), ("tỉ đồng", 9), ("ty vnd", 9),
      ("trieu dong", 6), ("triệu đồng", 6), ("triệu vnd", 6), ("trieu vnd", 6),
      ("nghin dong", 3), ("nghìn đồng", 3), ("ngàn đồng", 3), ("ngan dong", 3),
      ("dong viet nam", 0), ("đồng việt nam", 0), ("vnd", 0), ("vnđ", 0)]


def tim_don_vi(*texts) -> list[tuple[int, str, str]]:
    """Trả [(exponent, token, trường nguồn)] theo thứ tự ưu tiên trường."""
    ra = []
    for ten, t in texts:
        s = (t or "").lower()
        if not s:
            continue
        for tok, e in DV:
            if tok in s:
                ra.append((e, tok, ten))
                break
    return ra


def phan_xu(r: dict) -> dict:
    a6 = r["A6"]["scale_exponent"]
    legacy = r["legacy_table_unit"]["unit_exponent"]
    re_ = r["raw_evidence"]
    # Thứ tự ưu tiên bằng chứng: cột > dòng > tiêu đề bảng > section > context.
    bc = tim_don_vi(("col_path_text", re_.get("col_path_text")),
                    ("row_path_text", re_.get("row_path_text")),
                    ("html_header_rows", " | ".join(re_.get("html_header_rows") or [])),
                    ("section_text", re_.get("section_text")),
                    ("context_clean", re_.get("context_clean")))
    if bc:
        exp, tok, truong = bc[0]
        if exp == a6:
            st, final, act, ly = "CONFIRMED_A6", a6, "USE_A6", f"raw '{tok}' o {truong} khop A6 (10^{a6})"
        elif exp == legacy:
            st, final, act, ly = ("A6_DEFECT", legacy, "OVERRIDE_SCALE",
                                  f"raw '{tok}' o {truong} = 10^{exp} khop don vi muc bang, KHAC A6 10^{a6}")
        else:
            st, final, act, ly = ("A6_DEFECT", exp, "OVERRIDE_SCALE",
                                  f"raw '{tok}' o {truong} = 10^{exp}, khac ca A6 (10^{a6}) lan bang (10^{legacy})")
    else:
        if (r["A6"]["scale_source"] or "none") == "none":
            st, final, act, ly = ("FALLBACK_REQUIRED", None, "FALLBACK_HTML",
                                  "A6 khong co nguon scale va khong tim thay token don vi trong raw")
        else:
            st, final, act, ly = ("UNRESOLVED_BLOCKED", None, "BLOCK",
                                  f"A6 khai scale_source={r['A6']['scale_source']} nhung raw khong xac nhan duoc; "
                                  f"bang khai 10^{legacy} - khong du bang chung phan xu")
    return {"final_status": st, "final_scale_exponent": final,
            "resolver_action": act, "decision_reason": ly,
            "evidence_found": [{"exponent": e, "token": t, "field": f} for e, t, f in bc[:3]]}


def main() -> int:
    Q = {q["id"]: q["question"] for q in
         (json.loads(l) for l in (ROOT/"data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8") if l.strip())}
    n = 0
    dem: dict[str, int] = {}
    with RA.open("w", encoding="utf-8") as f:
        for line in NGUON.open(encoding="utf-8"):
            r = json.loads(line)
            p = phan_xu(r)
            dem[p["final_status"]] = dem.get(p["final_status"], 0) + 1
            n += 1
            f.write(json.dumps({
                "qid": r["qid"], "observation_uid": r["observation_uid"],
                "source_cell_uid": r["source_cell_uid"], "evidence_ref": r["evidence_ref"],
                "question": Q.get(r["qid"], "")[:180],
                "question_unit_hint": next((t for t, _ in DV if t in Q.get(r["qid"], "").lower()), None),
                "a6_scale_exponent": r["A6"]["scale_exponent"],
                "a6_scale_source": r["A6"]["scale_source"],
                "competing_scale_exponent": r["legacy_table_unit"]["unit_exponent"],
                "raw_value": r["raw_evidence"]["value_source_raw"],
                "raw_header": (r["raw_evidence"]["html_header_rows"] or [None])[0],
                "raw_col_path": r["raw_evidence"]["col_path_text"],
                "raw_row_path": r["raw_evidence"]["row_path_text"],
                "raw_section": r["raw_evidence"]["section_text"],
                "reviewed_at": "2026-08-19", "reviewer": "rule_v1_raw_evidence",
                **p,
            }, ensure_ascii=False) + "\n")
    print(f"phan xu {n} record ->", dem)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
