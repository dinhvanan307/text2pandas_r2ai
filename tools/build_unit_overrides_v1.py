#!/usr/bin/env python3
"""Materialize 34 ca `A6_DEFECT` thành bảng override scale — review 131 §6.2.

VÌ SAO
------
`docs/103` F2 phân xử 47 ca xung đột đơn vị bằng raw evidence và kết luận **34
ca A6 sai hệ số 10³/10⁶**. Bằng chứng có sẵn từng ca trong
`artifacts/execution/h0/unit_conflict_adjudication.jsonl`, nhưng nó chưa bao
giờ thành thứ code đọc được. Vì vậy `observations.scale_exponent` vẫn trả giá
trị A6 sai, và mọi tầng phía sau nhân sai 1.000 hoặc 1.000.000 lần.

Review 131 §6.2 xếp việc này là `PRE_SUBMISSION_BLOCKER`, không còn là P2 tuỳ
chọn. Tệp này sinh bảng override; `emit_arith_v1._to_dong` và
`emit_lookup_v1` đọc nó.

QUAN TRỌNG — đây KHÔNG phải sửa dữ liệu A6.
A6 là SSOT và bất biến (`work.db` chỉ là derived artifact). Override là một lớp
phủ CÓ TÊN, có bằng chứng từng dòng, áp ở tầng execution. Ai muốn kiểm đều truy
được về `evidence_ref` + `decision_reason` gốc.

Chạy:  python3 tools/build_unit_overrides_v1.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "artifacts/execution/h0/unit_conflict_adjudication.jsonl"
DST = ROOT / "configs/execution/unit_scale_overrides_v1.json"


def main() -> int:
    rows = [json.loads(l) for l in SRC.open(encoding="utf-8") if l.strip()]
    defects = [r for r in rows if r.get("final_status") == "A6_DEFECT"]
    confirmed = [r for r in rows if r.get("final_status") == "CONFIRMED_A6"]
    blocked = [r for r in rows if r.get("final_status") not in
               ("A6_DEFECT", "CONFIRMED_A6")]

    ov = {}
    conflicts = []
    for r in defects:
        uid = r["observation_uid"]
        new = int(r["final_scale_exponent"])
        old = int(r["a6_scale_exponent"] or 0)
        if uid in ov and ov[uid]["final_scale_exponent"] != new:
            conflicts.append(uid)
            continue
        ov[uid] = {
            "final_scale_exponent": new,
            "a6_scale_exponent": old,
            "delta_exponent": new - old,
            "qid": r.get("qid"),
            "evidence_ref": r.get("evidence_ref"),
            "raw_value": r.get("raw_value"),
            "raw_col_path": r.get("raw_col_path"),
            "decision_reason": r.get("decision_reason"),
            "reviewer": r.get("reviewer"),
            "reviewed_at": r.get("reviewed_at"),
        }

    out = {
        "_schema": "unit_scale_overrides v1 — lớp phủ scale ở tầng EXECUTION",
        "khong_phai": "sửa A6. A6 là SSOT bất biến; đây là override có tên và có bằng chứng.",
        "nguon": str(SRC.relative_to(ROOT)),
        "nguon_sha256": hashlib.sha256(SRC.read_bytes()).hexdigest(),
        "n_rows_adjudicated": len(rows),
        "n_A6_DEFECT": len(defects),
        "n_CONFIRMED_A6": len(confirmed),
        "n_khac": len(blocked),
        "n_override_uid": len(ov),
        "uid_xung_dot": conflicts,
        "phan_bo_delta_exponent": {},
        "overrides": ov,
    }
    d = {}
    for v in ov.values():
        d[str(v["delta_exponent"])] = d.get(str(v["delta_exponent"]), 0) + 1
    out["phan_bo_delta_exponent"] = dict(sorted(d.items()))

    DST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"adjudicated {len(rows)} · A6_DEFECT {len(defects)} · CONFIRMED_A6 "
          f"{len(confirmed)} · khác {len(blocked)}")
    print(f"override uid duy nhất: {len(ov)} · xung đột: {len(conflicts)}")
    print(f"delta exponent: {out['phan_bo_delta_exponent']}")
    print("->", DST.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
