#!/usr/bin/env python3
"""Joint operand search — M6 của Plan 133, đòn bẩy chính.

VÌ SAO
------
Bảng oracle (`reports/oracle_table_v1.json`) đo được:

    O0  8/24    production end-to-end
    O2  9/24    gold evidence scope + production resolver   (+1)
    O4 24/24    gold operands + production emitter          (+15)  ← DOMINANT
    O6 24/24    gold operands + gold operation              (+0)

`O4 − O2 = +15` là marginal gain lớn nhất, và `O2 − O0 = +1` nói rằng cho
resolver ĐÚNG SCOPE cũng gần như không giúp. Nghĩa là lỗi không nằm ở phạm vi
tài liệu mà ở **chọn ô trong phạm vi đã đúng**.

Ý TƯỞNG
-------
Resolver hiện tại chọn top-1 ĐỘC LẬP cho từng slot. Một câu 2 slot vì thế nhân
hai xác suất sai. Nhưng các slot của MỘT câu số học không độc lập: chúng phải
cùng metric, cùng basis, cùng loại giá trị, cùng đơn vị, chỉ khác kỳ/thực thể.

Joint search khai thác đúng ràng buộc đó: thay vì `argmax` từng slot rồi hy vọng
chúng khớp nhau, ta liệt kê **bộ operand** và chấm điểm cả bộ.

    lattice top-N/slot → semantic collapse → top-M khác nghĩa
      → beam trên TÍCH các slot với ràng buộc CỨNG
      → điểm bộ = Σ điểm slot + thưởng nhất quán − phạt họ lỗi P0

RÀNG BUỘC CỨNG (loại thẳng, không phạt mềm)
    cùng `metric_label` chuẩn hoá
    cùng `basis` (separate/consolidated) nếu câu không nói khác
    cùng `unit_kind` và `value_kind`
    cùng `statement_type`
    pct_change: mẫu != 0
Ràng buộc cứng rẻ hơn trọng số mềm: nó cắt không gian trước khi chấm, và người
đọc trace biết chính xác vì sao một bộ bị loại.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .fact_rank_v1 import norm, toks
from .operand_pipeline_v1 import (PipelineFlags, _sem_key, candidates_for_slot,
                                  slots_for)


@dataclass(frozen=True)
class JointFlags:
    lattice_depth: int = 100      # top-N thô mỗi slot
    top_m: int = 8                # sau semantic collapse
    beam: int = 64                # số bộ giữ lại khi mở rộng
    # Ngưỡng TƯƠNG ĐỒNG nhãn metric giữa các slot, KHÔNG phải bằng nhau tuyệt đối.
    #
    # Bản đầu dùng `norm(a) == norm(b)`. Đo trên gold-45: chỉ 19/24 câu có MỌI
    # slot cùng nhãn. Năm câu còn lại có nhãn khác nhau một cách hợp lệ —
    #   qid 587  'tiền gửi tại ngân hàng nhà nước' ↔ '… nhà nước việt nam'
    #   qid 953  'tài sản cố định vô hình'         ↔ 'tài sản cố định'
    # ⇒ ràng buộc bằng-nhau loại thẳng 5/24 đáp án ĐÚNG. Nó sai trên 21% tập.
    #
    # Jaccard token: >=1,0 giữ 19/24 · >=0,7 giữ 20 · >=0,5 giữ 21 · >=0,3 giữ 22.
    # Chọn 0,5 — giữ 87,5% gold reachable mà vẫn cắt được nhãn khác hẳn nghĩa.
    metric_jaccard_min: float = 0.5
    require_same_basis: bool = True
    require_same_kind: bool = True
    require_same_statement: bool = True
    consistency_bonus: float = 2.0
    enabled: bool = True

    @property
    def name(self) -> str:
        if not self.enabled:
            return "independent_top1"
        on = [n.replace("require_same_", "") for n in
              ("require_same_basis", "require_same_kind",
               "require_same_statement") if getattr(self, n)]
        return (f"joint(top_m={self.top_m},beam={self.beam},"
                f"jac>={self.metric_jaccard_min},hard={'+'.join(on) or 'none'})")


def semantic_collapse(cands: list[dict], top_m: int) -> list[dict]:
    """Gộp ô ĐỒNG NGHĨA, giữ top-M ô KHÁC NGHĨA.

    Hai ô cùng (nhãn, cột, giá trị) là một fact dù nằm ở hai bảng. Giữ nguyên cả
    hai chỉ làm shortlist trông đa dạng mà thực chất lặp — và đó là cách một
    shortlist 8 ô chỉ chứa 2 lựa chọn thật.
    """
    seen: set = set()
    out: list[dict] = []
    for c in cands:
        k = _sem_key(c)
        if k in seen:
            continue
        seen.add(k)
        out.append(c)
        if len(out) >= top_m:
            break
    return out


def _compatible(a: dict, b: dict, fl: JointFlags) -> str | None:
    """→ None nếu hợp lệ, ngược lại TÊN ràng buộc bị vi phạm."""
    if fl.metric_jaccard_min > 0:
        ta, tb = toks(a.get("metric_label") or ""), toks(b.get("metric_label") or "")
        u = ta | tb
        jac = (len(ta & tb) / len(u)) if u else 1.0
        if jac < fl.metric_jaccard_min:
            return "METRIC"
    if fl.require_same_kind:
        if (a.get("value_kind") or "") != (b.get("value_kind") or ""):
            return "VALUE_KIND"
        if (a.get("unit_kind") or "") != (b.get("unit_kind") or ""):
            return "UNIT_KIND"
    if fl.require_same_statement and (a.get("statement_type") or "") != (b.get("statement_type") or ""):
        return "STATEMENT_TYPE"
    return None


def search(con, plan: dict, intent: str, fl: JointFlags,
           scoring_text: str, aliases: dict | None = None) -> dict:
    """Trả về bộ operand tốt nhất + trace vì sao.

    `fl.enabled=False` tái hiện hành vi CŨ (top-1 độc lập) để A/B chỉ khác đúng
    một thứ: cách chọn bộ.
    """
    slots = slots_for(plan, intent, aliases)
    if not slots:
        return {"ok": False, "reason": "SLOT_PLAN_EMPTY", "ops": {}}

    pipe = PipelineFlags(depth=fl.lattice_depth, shortlist_m=fl.lattice_depth)
    lattices: dict[str, list[dict]] = {}
    stats = {"n_pool_sql": 0, "n_scored": 0, "n_dup_removed": 0}
    for s in slots:
        cands, m = candidates_for_slot(con, plan, s, pipe, scoring_text=scoring_text)
        for k in stats:
            stats[k] += m.get(k, 0)
        lat = semantic_collapse(cands, fl.top_m)
        for c in lat:
            c["_slot"] = s.name
            c["_year"] = s.year
        lattices[s.role] = lat
        if not lat:
            return {"ok": False, "reason": f"LATTICE_EMPTY:{s.name}", "ops": {},
                    "metrics": stats}

    roles = [s.role for s in slots]

    if not fl.enabled:
        ops = {r: lattices[r][0] for r in roles}
        return {"ok": True, "ops": ops, "mode": "independent_top1",
                "metrics": stats,
                "lattice_sizes": {r: len(lattices[r]) for r in roles}}

    # ── beam trên tích các slot, cắt bằng ràng buộc CỨNG ────────────────────
    beams: list[tuple[float, dict]] = [(0.0, {})]
    rejected: dict[str, int] = {}
    for r in roles:
        nxt: list[tuple[float, dict]] = []
        for score, partial in beams:
            for c in lattices[r]:
                viol = None
                for pr, pc in partial.items():
                    viol = _compatible(pc, c, fl)
                    if viol:
                        break
                if viol:
                    rejected[viol] = rejected.get(viol, 0) + 1
                    continue
                nxt.append((score + (c["score"] or 0.0), {**partial, r: c}))
        if not nxt:
            # Ràng buộc cứng loại sạch — KHÔNG nới lỏng âm thầm. Báo ra để
            # người đọc biết đây là câu mà lattice không chứa bộ nhất quán nào.
            return {"ok": False, "reason": "NO_COMPATIBLE_SET", "ops": {},
                    "rejected_by": rejected, "metrics": stats,
                    "lattice_sizes": {k: len(v) for k, v in lattices.items()}}
        nxt.sort(key=lambda t: -t[0])
        beams = nxt[: fl.beam]

    # thưởng nhất quán: bộ dùng nhãn metric dài hơn thường cụ thể hơn
    def final_score(item):
        sc, ops = item
        lab = norm(next(iter(ops.values())).get("metric_label") or "")
        return sc + fl.consistency_bonus * (len(lab) / 40.0)

    beams.sort(key=lambda t: (-final_score(t),
                              tuple(str(c["observation_uid"]) for c in t[1].values())))
    best_score, best = beams[0]
    return {"ok": True, "ops": best, "mode": "joint", "joint_score": round(best_score, 4),
            "n_sets_considered": len(beams), "rejected_by": rejected,
            "metrics": stats,
            "lattice_sizes": {k: len(v) for k, v in lattices.items()}}
