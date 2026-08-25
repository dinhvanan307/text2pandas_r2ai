#!/usr/bin/env python3
"""docs/112 §5 — GHI NHẬN (không sửa) các câu có `primary_operation` không khớp
output contract. Dùng để cấm downstream planner coi `primary_operation` hiện tại
là execution plan hoàn chỉnh.

KHÔNG thay đổi rule, KHÔNG thay đổi answer, KHÔNG dùng để mutate scope.

    python3 tools/execution/defect_register_primary_operation.py \
        --precheck op_evidence_v3/answer_operation_precheck.jsonl \
        --out-jsonl op_evidence_v3/defect_register_primary_operation.jsonl \
        --out-json  op_evidence_v3/defect_register_primary_operation_summary.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

# Nhãn phép toán ⇒ kiểu output mà nhãn đó HÀM Ý.
HAM_Y = {"PERCENTAGE": {"percentage"}, "RATIO_MULTIPLE": {"percentage", "money", "share_count"}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", required=True)
    ap.add_argument("--out-jsonl", required=True)
    ap.add_argument("--out-json", required=True)
    a = ap.parse_args(argv)

    rows = [json.loads(l) for l in Path(a.precheck).open(encoding="utf-8") if l.strip()]
    ds = []
    for r in rows:
        prim = r["primary_operation"]
        if prim not in HAM_Y:
            continue
        kind = r["output_spec"]["question_output_kind"]
        if kind in HAM_Y[prim]:
            continue
        ds.append({
            "qid": r["qid"],
            "defect_class": "PRIMARY_OPERATION_OUTPUT_KIND_MISMATCH",
            "severity": "P1",
            "primary_operation": prim,
            "question_output_kind": kind,
            "operation_signals": r["operation_signals"],
            "sub_operations": r["sub_operations"],
            "proposed_action": r["proposed_action"],
            "allow_a6_single_cell": r["allow_a6_single_cell"],
            "blocks_h0_binary_gate": r["proposed_action"] == "ALLOW_A6_CANDIDATE_PENDING_AUDIT",
            "question": r["question"],
            "note": ("primary chọn theo thứ tự regex TIN_HIEU, không theo mệnh đề "
                     "output cuối câu; tỷ lệ ở đây là ĐIỀU KIỆN LỌC. Cần tách "
                     "requested_output_operation / filter_operations[] / "
                     "aggregation_operation trước khi dùng cho arithmetic planner."),
        })
    ds.sort(key=lambda d: d["qid"])
    Path(a.out_jsonl).write_text(
        "\n".join(json.dumps(d, ensure_ascii=False, sort_keys=True) for d in ds) + "\n",
        encoding="utf-8")

    tt = {
        "source_precheck": Path(a.precheck).name,
        "n_defects": len(ds),
        "by_primary_operation": dict(Counter(d["primary_operation"] for d in ds).most_common()),
        "by_output_kind": dict(Counter(d["question_output_kind"] for d in ds).most_common()),
        "by_proposed_action": dict(Counter(d["proposed_action"] for d in ds).most_common()),
        "n_blocking_h0_binary_gate": sum(d["blocks_h0_binary_gate"] for d in ds),
        "qids": [d["qid"] for d in ds],
        "assertions": {
            # docs/112 §5.1: các câu này đều non-direct nên KHÔNG mở đường
            # A6 single-cell. Nếu assertion này FAIL thì defect lên P0.
            "assert_khong_defect_nao_dang_allow":
                all(not d["blocks_h0_binary_gate"] for d in ds),
        },
        "downstream_contract": ("primary_operation KHÔNG phải execution plan đầy đủ; "
                                "planner C2/C3 không được đọc trường này như kế hoạch tính toán."),
    }
    Path(a.out_json).write_text(json.dumps(tt, ensure_ascii=False, indent=1, sort_keys=True),
                                encoding="utf-8")
    print(f"defects={len(ds)} blocking_allow={tt['n_blocking_h0_binary_gate']}")
    return 0 if all(tt["assertions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
