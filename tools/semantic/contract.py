#!/usr/bin/env python3
"""Semantic Answer Contract — Pha 4 directive 165.

Một đáp án chỉ được `PROVEN_CORRECT` khi **mọi** tiền đề áp dụng đều `PASS`.
Thiếu bằng chứng ⇒ `UNCERTAIN`. **Không bao giờ** hạ `UNCERTAIN` thành
`PROVEN_INCORRECT` — đó là hai trạng thái nhận thức khác nhau, và trộn chúng
chính là cách một hệ thống chưa được chứng minh trông như đã được chứng minh.

Bảng chân lý:

| có ≥1 FAIL | có ≥1 NOT_MEASURABLE/UNCERTAIN | kết luận |
|---|---|---|
| có | bất kỳ | `PROVEN_INCORRECT` |
| không | có | `UNCERTAIN` |
| không | không | `PROVEN_CORRECT` |

`answer_exact` KHÔNG nằm trong bảng trên. Số khớp mà đường ngữ nghĩa sai thì
`semantic_correctness = PROVEN_INCORRECT` và gắn cờ `SPURIOUS_CORRECT`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .predicates import (FAIL, NOT_APPLICABLE, NOT_MEASURABLE, PASS, UNCERTAIN,
                         Verdict)

# thứ tự cố định — dùng cho báo cáo và cho quy tắc quy trách nhiệm
CHIEU = ("entity", "metric", "period", "basis", "operation", "operands",
         "unit", "computation", "evidence")

FAILURE_CLASS = {
    "entity": "ENTITY_MISMATCH", "metric": "METRIC_MISMATCH",
    "period": "PERIOD_MISMATCH", "basis": "BASIS_MISMATCH",
    "operation": "OPERATION_MISMATCH", "operands": "OPERAND_MISMATCH",
    "unit": "UNIT_MISMATCH", "computation": "COMPUTATION_MISMATCH",
    "evidence": "EVIDENCE_INSUFFICIENT",
}

PROVEN_CORRECT = "PROVEN_CORRECT"
PROVEN_INCORRECT = "PROVEN_INCORRECT"


@dataclass
class ContractResult:
    semantic_correctness: str
    primary_failure: str
    secondary_failures: list = field(default_factory=list)
    unmeasurable: list = field(default_factory=list)
    per_dimension: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "semantic_correctness": self.semantic_correctness,
            "primary_failure": self.primary_failure,
            "secondary_failures": self.secondary_failures,
            "unmeasurable_dimensions": self.unmeasurable,
            "per_dimension": self.per_dimension,
            "diagnostic_flags": self.flags,
        }


def danh_gia(verdicts: dict, answer_exact: bool | None = None) -> ContractResult:
    """`verdicts`: dict chiều -> Verdict. Chiều thiếu coi là NOT_MEASURABLE."""
    per, fails, unmeas = {}, [], []
    for c in CHIEU:
        # KHÔNG dùng `or`: Verdict cố tình không có giá trị chân lý, và chính
        # cái guard đó đã bắt được lỗi này khi chạy test lần đầu.
        v = verdicts.get(c)
        if v is None:
            v = Verdict(NOT_MEASURABLE, "không cung cấp")
        per[c] = {"status": v.status, "reason": v.reason, "evidence": v.evidence}
        if v.status == FAIL:
            fails.append(c)
        elif v.status in (NOT_MEASURABLE, UNCERTAIN):
            unmeas.append(c)
        # NOT_APPLICABLE cố ý không tính vào cả hai

    if fails:
        kq = PROVEN_INCORRECT
        primary = FAILURE_CLASS[fails[0]]
        secondary = [FAILURE_CLASS[c] for c in fails[1:]]
    elif unmeas:
        kq = UNCERTAIN
        primary = ("GOLD_UNCERTAIN" if "operation" in unmeas or "operands" in unmeas
                   else "EVIDENCE_INSUFFICIENT")
        secondary = []
    else:
        kq = PROVEN_CORRECT
        primary, secondary = "NO_FAILURE_PROVEN", []

    flags = []
    if answer_exact is True and kq != PROVEN_CORRECT:
        flags.append("SPURIOUS_CORRECT")
    if answer_exact is False and kq == PROVEN_CORRECT:
        flags.append("SEMANTIC_OK_BUT_ANSWER_MISMATCH")
    if unmeas:
        flags.append("HAS_UNMEASURABLE_DIMENSION")
    return ContractResult(kq, primary, secondary, unmeas, per, flags)


def du_dieu_kien_whitelist(res: ContractResult) -> tuple[bool, str]:
    """Luật whitelist §6.3 review 165 — MỌI chiều PASS, không có NOT_MEASURABLE."""
    if res.semantic_correctness != PROVEN_CORRECT:
        return False, f"semantic_correctness={res.semantic_correctness}"
    if res.unmeasurable:
        return False, "còn chiều NOT_MEASURABLE: " + ",".join(res.unmeasurable)
    return True, "ALL_DIMENSIONS_PROVEN"
