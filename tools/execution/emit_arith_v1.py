#!/usr/bin/env python3
"""Arithmetic emitter — MỖI INTENT MỘT FEATURE FLAG RIÊNG.

Review 131 §6.3: nếu C2 bật 5 intent cùng lúc rồi điểm official đổi, không ai
biết intent nào gây ra. Vì vậy cờ ở đây là **theo intent**, không phải một cờ
`arithmetic` duy nhất, và thang public là:

    C2A = percentage_change
    C2B = C2A + difference
    C3  = + sum + argmax_year + average

CHÍNH SÁCH ĐÃ KHAI TRƯỚC (formula_registry_v1 + review 131 §6.2)

    unit          : quy về ĐỒNG trước khi tính  → giá_trị = raw × 10^scale
                    rồi mới chia hệ số đơn vị câu hỏi. Hai operand PHẢI cùng
                    đơn vị trước khi trừ.
    percent       : quy ước "15 nghĩa là 15%" (dải type-contract của
                    validate_submission). Không nhân thêm 100 lần hai.
    sign          : giữ dấu tự nhiên của dữ liệu; KHÔNG abs kết quả
                    difference/percentage_change — chiều tăng/giảm là thông tin.
    zero denom    : old == 0 → KHÔNG emit inf/nan. Abstain, reason
                    ZERO_DENOMINATOR.
    argmax_year   : trả về NĂM (không đơn vị tiền). Hoà điểm → abstain, vì
                    "năm nào lớn nhất" không có đáp án khi hai năm bằng nhau.
    multiplicity  : mọi operand phải qua `ambiguity_gate`; một slot hỏng thì
                    CẢ câu abstain — không đoán bù.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .emit_lookup_v1 import (CHAIN_CUES, asked_unit, effective_scale,
                             metric_phrase, spec_text)
from .operand_pipeline_v1 import (PipelineFlags, ambiguity_gate,
                                  candidates_for_slot,
                                  enforce_metric_consistency, load_aliases,
                                  slots_for)

ARITH_INTENTS = ("percentage_change", "difference", "sum", "average", "argmax_year")


@dataclass(frozen=True)
class ArithFlags:
    percentage_change: bool = False
    difference: bool = False
    sum: bool = False
    average: bool = False
    argmax_year: bool = False
    pipeline: PipelineFlags = PipelineFlags()

    def enabled(self, intent: str) -> bool:
        return bool(getattr(self, intent, False))

    @property
    def name(self) -> str:
        on = [i for i in ARITH_INTENTS if self.enabled(i)]
        return "+".join(on) or "none"


# Cổng tự tin của thang arithmetic: `margin_min = 0.0`, tức "emit khi dựng
# được ĐỦ operand plan", không đòi thêm khoảng cách điểm.
#
# Vì sao — hiệu chuẩn đo trên 24 câu arithmetic của gold-45 (TRAIN_FIT):
#
#     ngưỡng  emit  đúng  sai   acc_khi_emit
#      0,00     23     8   15         34,8%
#      0,01      2     2    0        100,0%
#      0,05      2     2    0        100,0%
#      0,10      0     0    0            —
#
# margin CÓ mang tín hiệu, nhưng vùng tự tin chỉ còn n = 2 — quá nhỏ để làm
# cổng. Ở ngưỡng 0, tầng số học đúng 8/24 so với baseline C0 1/24 trên CÙNG
# tập. Đây là siêu tham số TRAIN_FIT, phải xác nhận lại trên DEV trước khi nộp.
ARITH_PIPE = PipelineFlags(margin_min=0.0)

LADDER = {
    "C2A": ArithFlags(percentage_change=True, pipeline=ARITH_PIPE),
    "C2B": ArithFlags(percentage_change=True, difference=True, pipeline=ARITH_PIPE),
    "C3": ArithFlags(percentage_change=True, difference=True, sum=True,
                     average=True, argmax_year=True, pipeline=ARITH_PIPE),
}


def _to_dong(cell: dict) -> float:
    """raw × 10^scale. Đây là điểm DUY NHẤT áp scale — không lặp ở nơi khác.

    Scale lấy qua `effective_scale` để 34 ca `A6_DEFECT` đã phân xử (docs/103 F2)
    được sửa. Không đọc thẳng `cell['scale_exponent']` ở bất kỳ đâu khác.
    """
    return float(cell["value"]) * (10 ** effective_scale(cell))


def compute(intent: str, ops: dict[str, dict], unit_factor: float | None) -> dict:
    """Áp công thức lên operand ĐÃ chọn. Tách khỏi việc chọn ô để test được riêng.

    `ops` là dict role → cell. Trả về {'answer', 'abstain', 'abstain_reason',
    'expr'} — `expr` là biểu thức người đọc được, dùng cho trace và cho O6.
    """
    if intent == "argmax_year":
        vals = [(int(r.split("__")[-1]) if "__" in r else None, _to_dong(c), r)
                for r, c in ops.items()]
        years = [c.get("_year") for c in ops.values()]
        pairs = sorted(zip(years, (_to_dong(c) for c in ops.values())))
        if len(pairs) < 2:
            return {"abstain": True, "abstain_reason": "ARGMAX_NEEDS_2_SLOTS"}
        best = max(pairs, key=lambda p: p[1])
        ties = [p for p in pairs if p[1] == best[1]]
        if len(ties) > 1:
            return {"abstain": True, "abstain_reason": "ARGMAX_TIE"}
        return {"answer": float(best[0]), "abstain": False, "abstain_reason": None,
                "expr": f"argmax({{{', '.join(f'{y}:{v:g}' for y, v in pairs)}}}) -> {best[0]}"}

    if unit_factor is None:
        return {"abstain": True, "abstain_reason": "UNIT_UNRESOLVED"}

    if intent in ("percentage_change", "difference"):
        if "old" not in ops or "new" not in ops:
            return {"abstain": True, "abstain_reason": "MISSING_OPERAND"}
        a, b = _to_dong(ops["old"]), _to_dong(ops["new"])
        if intent == "difference":
            return {"answer": (b - a) / unit_factor, "abstain": False,
                    "abstain_reason": None, "expr": f"({b:g} - {a:g}) / {unit_factor:g}"}
        if a == 0:
            return {"abstain": True, "abstain_reason": "ZERO_DENOMINATOR"}
        return {"answer": (b - a) / abs(a) * 100.0, "abstain": False,
                "abstain_reason": None,
                "expr": f"({b:g} - {a:g}) / |{a:g}| * 100"}

    vals = [_to_dong(c) for c in ops.values()]
    if not vals:
        return {"abstain": True, "abstain_reason": "MISSING_OPERAND"}
    if intent == "sum":
        return {"answer": sum(vals) / unit_factor, "abstain": False,
                "abstain_reason": None,
                "expr": f"sum({len(vals)} ops) / {unit_factor:g}"}
    if intent == "average":
        return {"answer": (sum(vals) / len(vals)) / unit_factor, "abstain": False,
                "abstain_reason": None,
                "expr": f"sum({len(vals)} ops)/{len(vals)} / {unit_factor:g}"}
    return {"abstain": True, "abstain_reason": f"INTENT_NOT_IMPLEMENTED:{intent}"}


def emit(con, plan: dict, intent: str, fl: ArithFlags,
         registry_labels: list[str]) -> dict | None:
    """Chọn operand cho từng slot rồi tính. → dict quyết định, hoặc None."""
    if not fl.enabled(intent):
        return None
    slots = slots_for(plan, intent, load_aliases())
    if not slots:
        return {"abstain": True, "abstain_reason": "SLOT_PLAN_EMPTY",
                "intent": intent}

    phrase = metric_phrase(plan, registry_labels)
    stext = spec_text(plan, phrase)

    per_slot: dict[str, dict] = {}
    metrics = {"n_pool_sql": 0, "n_dup_removed": 0, "n_scored": 0}
    for s in slots:
        short, m = candidates_for_slot(con, plan, s, fl.pipeline, scoring_text=stext)
        for k in ("n_pool_sql", "n_dup_removed", "n_scored"):
            metrics[k] += m.get(k, 0)
        gate = ambiguity_gate(short, fl.pipeline)
        per_slot[s.role] = {"slot": s.name, "year": s.year, "ticker": s.ticker,
                            "shortlist": short, "gate": gate,
                            "pick": short[0] if short else None}
        if not gate["ok"]:
            return {"abstain": True, "abstain_reason": f"SLOT_{gate['reason']}",
                    "intent": intent, "slot_failed": s.name,
                    "per_slot": _thin(per_slot), "metrics": metrics}

    cons = enforce_metric_consistency(per_slot, fl.pipeline)
    if not cons["ok"]:
        return {"abstain": True, "abstain_reason": cons["reason"], "intent": intent,
                "per_slot": _thin(per_slot), "metrics": metrics}

    ops = {}
    for role, v in per_slot.items():
        c = dict(v["pick"])
        c["_year"] = v["year"]
        ops[role] = c

    unit_name, factor = asked_unit(plan)
    if intent == "percentage_change":
        factor = 1.0                      # output là percent, không quy tiền
        unit_name = "percent"
    res = compute(intent, ops, factor)

    return {"intent": intent, "phrase": phrase, "unit_name": unit_name,
            "unit_factor": factor, "n_slot": len(slots),
            "metric_label": cons.get("chosen_label")
                            or (ops[next(iter(ops))]["metric_label"]),
            "consistency": cons, "per_slot": _thin(per_slot),
            "metrics": metrics, **res}


def _thin(per_slot: dict) -> dict:
    """Rút gọn để ghi trace mà không kéo theo cả shortlist 5 ô × mọi trường."""
    out = {}
    for role, v in per_slot.items():
        p = v.get("pick") or {}
        out[role] = {
            "slot": v["slot"], "gate": v["gate"],
            "n_shortlist": len(v.get("shortlist") or []),
            "repaired_by_consistency": v.get("repaired_by_consistency", False),
            "pick": {"observation_uid": p.get("observation_uid"),
                     "evidence_ref": p.get("evidence_ref"),
                     "metric_label": p.get("metric_label"),
                     "col_path": (p.get("col_path") or "")[:60],
                     "value": p.get("value"),
                     "scale_exponent": p.get("scale_exponent"),
                     "score": p.get("score")} if p else None}
    return out


def build_query(res: dict, varmap: dict[str, str]) -> str:
    """pandas_query tất định cho câu số học.

    `.item()` chứ không `.values[0]`: filter khớp != 1 dòng thì NÉM lỗi, để sai
    sót lộ ra ở replay thay vì thành một con số trông hợp lý.
    """
    def lit(s) -> str:
        return "'" + str(s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"

    def cell(role: str) -> str:
        p = res["per_slot"][role]["pick"]
        v = varmap[role]
        sc = int(p.get("effective_scale_exponent", p["scale_exponent"]) or 0)
        mul = f" * {10 ** sc}" if sc else ""
        return (f"float({v}.loc[({v}['row_label'] == {lit(p['metric_label'])}) & "
                f"({v}['col_label'] == {lit(p['col_path'])}), 'value'].item()){mul}")

    it = res["intent"]
    f = res["unit_factor"]
    if it == "difference":
        return f"({cell('new')} - {cell('old')}) / {f:.0f}"
    if it == "percentage_change":
        return f"({cell('new')} - {cell('old')}) / abs({cell('old')}) * 100.0"
    roles = [r for r in res["per_slot"] if r.startswith("x")]
    terms = " + ".join(cell(r) for r in roles)
    if it == "sum":
        return f"({terms}) / {f:.0f}"
    if it == "average":
        return f"(({terms}) / {len(roles)}) / {f:.0f}"
    if it == "argmax_year":
        yrs = [res["per_slot"][r]["slot"].split("/")[1] for r in roles]
        pairs = ", ".join(f"({cell(r)}, {y})" for r, y in zip(roles, yrs))
        return f"float(max([{pairs}])[1])"
    raise ValueError(f"intent chưa có query builder: {it}")
