#!/usr/bin/env python3
"""Materialize ĐỦ 34 ca UNIT_SCALE thành expectation từng dòng — đóng P0-5 (doc 134).

DOC 134 P0-5 viết: *"133 báo suite 20 cases, trong đó UNIT_SCALE chỉ có 5 …
UNIT_SCALE adjudicated = 5/34 materialized"*.

Đây là **hiểu nhầm đơn vị đếm**, và lỗi diễn đạt là của phía build: `p0_suite`
báo 5 **test function** cho họ UNIT_SCALE, còn số **ca** được kiểm là 34 —
`test_unit_scale_moi_override_duoc_ap_dung` lặp qua toàn bộ 34 override và fail
nếu bất kỳ ca nào không được áp.

Nhưng 134 đúng ở yêu cầu sâu hơn: **không thể kiểm chứng điều đó từ số tổng**.
Một vòng lặp trong một test là hộp đen với người đọc report. Vì vậy tệp này sinh
`tests/expected_p0_cases.jsonl` — MỘT DÒNG MỘT CA, và suite chấm từng dòng.

CHỐNG TAUTOLOGY (yêu cầu cuối của P0-5)
    `expected_scale_exponent` lấy từ `final_scale_exponent` do người phân xử ghi
    trong `unit_conflict_adjudication.jsonl`, dựa trên raw evidence (`raw_header`,
    `raw_col_path`, `raw_section`). KHÔNG lấy từ production emitter, không lấy từ
    A6. Mỗi dòng mang theo `decision_reason` để truy nguyên.

Chạy:  python3 tools/build_expected_p0_cases_v1.py
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "artifacts/execution/h0/unit_conflict_adjudication.jsonl"
DST = ROOT / "tests/expected_p0_cases.jsonl"


def main() -> int:
    rows = [json.loads(l) for l in SRC.open(encoding="utf-8") if l.strip()]
    out = []

    for r in rows:
        status = r.get("final_status")
        if status == "A6_DEFECT":
            out.append({
                "case_id": f"UNIT_SCALE::{r['observation_uid']}",
                "family": "UNIT_SCALE",
                "kind": "OVERRIDE_EXPECTED",
                "qid": r.get("qid"),
                "observation_uid": r["observation_uid"],
                "evidence_ref": r.get("evidence_ref"),
                "raw_value": r.get("raw_value"),
                "a6_scale_exponent": int(r["a6_scale_exponent"] or 0),
                "expected_scale_exponent": int(r["final_scale_exponent"]),
                "delta_exponent": int(r["final_scale_exponent"]) - int(r["a6_scale_exponent"] or 0),
                "expected_source": "human adjudication trên raw evidence (docs/103 F2)",
                "decision_reason": r.get("decision_reason"),
                "raw_col_path": r.get("raw_col_path"),
                "reviewer": r.get("reviewer"),
            })
        elif status == "CONFIRMED_A6":
            # Ca ĐỐI CHỨNG: A6 đúng ⇒ override KHÔNG được đụng vào.
            # Thiếu nhóm này thì một override "áp cho tất cả" cũng pass.
            out.append({
                "case_id": f"UNIT_SCALE_NEGATIVE::{r['observation_uid']}",
                "family": "UNIT_SCALE",
                "kind": "MUST_NOT_OVERRIDE",
                "qid": r.get("qid"),
                "observation_uid": r["observation_uid"],
                "evidence_ref": r.get("evidence_ref"),
                "a6_scale_exponent": int(r["a6_scale_exponent"] or 0),
                "expected_scale_exponent": int(r["a6_scale_exponent"] or 0),
                "delta_exponent": 0,
                "expected_source": "human adjudication xác nhận A6 ĐÚNG",
                "decision_reason": r.get("decision_reason"),
            })
        else:
            out.append({
                "case_id": f"UNIT_SCALE_BLOCKED::{r['observation_uid']}",
                "family": "UNIT_SCALE",
                "kind": "UNRESOLVED_MUST_NOT_OVERRIDE",
                "qid": r.get("qid"),
                "observation_uid": r["observation_uid"],
                "final_status": status,
                "expected_scale_exponent": int(r["a6_scale_exponent"] or 0),
                "expected_source": "chưa đủ bằng chứng ⇒ giữ nguyên A6, KHÔNG đoán",
            })

    with DST.open("w", encoding="utf-8") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    kinds = Counter(o["kind"] for o in out)
    meta = {
        "_schema": "expected_p0_cases v1 — MỘT DÒNG MỘT CA (doc 134 P0-5)",
        "source": str(SRC.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
        "n_case": len(out),
        "theo_kind": dict(kinds),
        "chong_tautology": ("expected lấy từ phân xử người trên raw evidence, "
                            "KHÔNG từ production emitter và KHÔNG từ A6"),
    }
    (ROOT / "tests/expected_p0_cases.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"tổng ca: {len(out)}")
    for k, v in sorted(kinds.items()):
        print(f"   {k:32} {v}")
    print("->", DST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
