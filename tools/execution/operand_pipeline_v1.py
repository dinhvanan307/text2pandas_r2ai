#!/usr/bin/env python3
"""Đường ống operand: top-N tất định → dedupe → group → shortlist → gate.

Review 131 §3.3 bác việc "truyền thẳng 100 candidate vào emitter": recall@100
cao mở trần, nhưng đồng thời tăng duplicate, đồng nhãn nhiều section/restatement,
mập mờ period/basis/unit, latency và nguy cơ ghi đè sai. Hai tầng là bắt buộc.

    retrieve top-N (deterministic)
      → dedupe semantic key
      → group theo operand slot (entity, year, role)
      → shortlist top-M mỗi slot
      → ambiguity / multiplicity gate
      → resolver / emitter

MỘT QUYẾT ĐỊNH CẦN GIẢI THÍCH — khoá thứ tự là BẮT BUỘC ở đây.
`fact_rank_v1` có `legacy_order` tái hiện bản 20/08, nhưng đường ống này luôn
chạy `legacy_order=False`. Lý do đo được: 39/45 QID có nhiều ô CÙNG ĐIỂM tại
ngưỡng cắt; để thứ tự quét bảng quyết định thì dedupe và shortlist cũng thành
ngẫu nhiên, và mọi số downstream mất tính tái lập. Đổi lại, lookup recall@1 tụt
57,1% → 33,3% — cái giá đã biết, ghi rõ, không giấu.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .fact_rank_v1 import Flags, apply_quota, fetch_pool, norm, score_pool

# Thứ tự TẤT ĐỊNH cho mọi đường ống mới. Không có cờ để tắt.
DET = Flags(idf_pool=True, exact_phrase=True, quota=True, legacy_order=False)

_ALIAS_CACHE: dict | None = None


def load_aliases(path: str = "configs/retrieval/company_alias_v1.yaml") -> dict[str, list[str]]:
    """ticker -> danh sách tên công ty. Parser tối giản, không cần PyYAML.

    File do `src/text2pandas/pipelines/retrieval/build_alias.py` sinh, cấu trúc cố định 2 mức dưới
    khoá `aliases:`. Dừng ở khoá `rejected:` — các biến thể ở đó đã bị loại vì
    mơ hồ và dùng chúng sẽ tái tạo đúng lỗi mà build_alias vừa tránh.
    """
    global _ALIAS_CACHE
    if _ALIAS_CACHE is not None:
        return _ALIAS_CACHE
    import pathlib as _pl
    root = _pl.Path(__file__).resolve().parents[2]
    f = root / path
    out: dict[str, list[str]] = {}
    if f.is_file():
        cur = None
        inside = False
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("aliases:"):
                inside = True
                continue
            if inside and line and not line[0].isspace():
                break                      # sang khoá cấp 1 khác (rejected:)
            if not inside:
                continue
            m = re.match(r"^  ([A-Z0-9]{3,4}):\s*$", line)
            if m:
                cur = m.group(1)
                out[cur] = []
                continue
            m = re.match(r'^\s+-\s*"?(.+?)"?\s*$', line)
            if m and cur:
                out[cur].append(m.group(1))
    _ALIAS_CACHE = out
    return out


@dataclass(frozen=True)
class SlotKey:
    ticker: str
    year: int
    role: str = "x"          # old/new cho 2 kỳ; x_i cho chuỗi

    @property
    def name(self) -> str:
        return f"{self.ticker}/{self.year}"


@dataclass(frozen=True)
class PipelineFlags:
    depth: int = 100          # top-N thô
    shortlist_m: int = 10     # top-M mỗi slot sau dedupe
    dedupe: bool = True
    metric_consistency: bool = True   # mọi slot phải cùng một nhãn metric
    margin_min: float = 0.05
    # Số GIÁ TRỊ khác nhau tối đa trong shortlist.
    # BẢN ĐẦU ĐẶT 3 VÀ SAI: đo trên 60 slot arithmetic của gold-45, top-5 có
    # 4 giá trị khác nhau ở 25 slot và 5 giá trị ở 32 slot — chỉ 3 slot có <=3.
    # Cổng ấy chặn 57/60 slot, tức nó không phân biệt "mập mờ" với "bình
    # thường". Mặc định nay = shortlist_m (tắt hiệu lực), giữ tham số để bật
    # lại KHI có bằng chứng hiệu chuẩn trên DEV.
    ambiguity_max_distinct: int = 10

    # ── D1(a) · A1/A2/A3 ────────────────────────────────────────────────────
    # `scorer` là cách đóng doc 140 §3.4 "A1 parity". Trước đây
    # `run_scoring_ablation_v2` gọi thẳng fetch_pool → rank_pool và BỎ QUA
    # dedupe + ambiguity_gate + enforce_metric_consistency ở dưới, nên số của
    # nó không so được với production. Nay scorer là THAM SỐ của chính đường
    # ống này: cả hai nhánh đi qua đúng một đoạn code, parity đúng theo cấu
    # tạo chứ không phải nhờ trùng hợp.
    #
    #   None                → score_pool + DET  (hành vi production hiện tại)
    #   một `ScoreFlags`    → score_v2.rank_pool
    #
    # `ScoreFlags()` (S0) tái tạo ĐÚNG công thức của score_pool+DET: cùng
    # idf/exact_phrase/col_year/doc_year/ready, cùng tie-break observation_uid.
    # Đó là điều kiện để dòng cổng A1 xanh.
    scorer: object | None = None
    score_floor: bool = False     # A3 — ô 0 token chung nhận điểm sàn
    operand_phrase: str | None = None


def _sem_key(c: dict) -> tuple:
    """Khoá ngữ nghĩa để dedupe.

    Hai ô là MỘT fact nếu cùng nhãn metric, cùng cột, cùng giá trị — kể cả khi
    chúng nằm ở hai `evidence_ref` khác nhau (restatement, bảng lặp ở thuyết
    minh). Đây chính là nguồn duplicate mà review 131 cảnh báo khi tăng depth.
    """
    return (norm(c.get("metric_label") or ""), norm(c.get("col_path") or ""),
            str(c.get("value")))


def mention_order(plan: dict, aliases: dict[str, list[str]] | None) -> list[str]:
    """Sắp entity theo THỨ TỰ XUẤT HIỆN trong câu hỏi, không theo thứ tự plan.

    Cần vì câu so sánh hai công ty ("chênh lệch X giữa A và B") có vai trò
    operand phụ thuộc vị trí nhắc tên. Ticker không xuất hiện literal trong
    câu — chỉ tên công ty — nên phải tra alias.
    """
    ents = list(plan.get("entities") or [])
    if not aliases or len(ents) < 2:
        return ents
    q = norm(plan.get("question", ""))
    pos = {}
    for e in ents:
        best = None
        for nm in [e] + list(aliases.get(e, [])):
            i = q.find(norm(nm))
            if i >= 0 and (best is None or i < best):
                best = i
        pos[e] = best if best is not None else 10 ** 6
    return sorted(ents, key=lambda e: (pos[e], e))


def slots_for(plan: dict, intent: str,
              aliases: dict[str, list[str]] | None = None) -> list[SlotKey]:
    """Sinh danh sách operand slot. `slot` của gold có dạng 'TICKER/YEAR'.

    HAI HÌNH DẠNG cho so sánh hai vế — bản đầu chỉ có một và đó là lỗi:

        1 entity × 2 năm      "X năm 2016 so với 2022"
        2 entity × 1 năm      "chênh lệch X giữa công ty A và công ty B"

    Đo được: 5/7 câu `difference` của gold-45 thuộc hình dạng THỨ HAI. Bản đầu
    yêu cầu `len(ents)==1 and len(years)==2` nên trả rỗng cho cả 5 câu ấy
    (`SLOT_PLAN_EMPTY`) — tức 71% lớp difference bị bỏ trước khi kịp tính.
    """
    ents = list(plan.get("entities") or [])
    years = sorted(plan.get("years") or [])
    if not ents or not years:
        return []

    if intent in ("percentage_change", "difference"):
        if len(ents) == 1 and len(years) == 2:
            # Vai trò theo thứ tự NĂM: kỳ sớm = old.
            return [SlotKey(ents[0], years[0], "old"),
                    SlotKey(ents[0], years[1], "new")]
        if len(ents) == 2 and len(years) == 1:
            # Vai trò theo thứ tự NHẮC TÊN. Quy ước preregistered:
            #     đáp án = (vế nhắc SAU) − (vế nhắc TRƯỚC)
            # Khớp 4/5 câu cross-entity của gold-45; qid 740 KHÔNG khớp và được
            # ghi là xung đột quy ước dấu cần người phân xử, KHÔNG fit theo nó.
            a, b = mention_order(plan, aliases)
            return [SlotKey(a, years[0], "old"), SlotKey(b, years[0], "new")]
        return []

    if intent in ("sum", "average", "argmax_year"):
        return [SlotKey(e, y, f"x{i}")
                for i, (e, y) in enumerate((e, y) for e in ents for y in years)]
    return []


def candidates_for_slot(con, plan: dict, slot: SlotKey, fl: PipelineFlags,
                        scoring_text: str | None = None) -> tuple[list[dict], dict]:
    """→ (shortlist, metrics). Pool riêng cho ĐÚNG một (entity, year)."""
    sub = dict(plan)
    sub["entities"] = [slot.ticker]
    sub["years"] = [slot.year]
    if scoring_text:
        sub["question"] = scoring_text
    pool = fetch_pool(con, sub, legacy_order=False)
    m = {"n_pool_sql": len(pool)}
    if not pool:
        return [], m | {"n_scored": 0, "n_after_dedupe": 0, "n_dup_removed": 0}

    if fl.scorer is None:
        scored = score_pool(pool, sub, DET)
    else:
        from .score_v2 import rank_pool
        scored = rank_pool(pool, sub, sub["question"], fl.scorer,
                           fl.operand_phrase, floor=fl.score_floor)
    m["n_scored"] = len(scored)
    m["n_khong_cham_duoc"] = len(pool) - len([c for c in scored
                                              if c.get("score_parts", {}).get(
                                                  "scorable", True)])
    ranked = apply_quota(scored, sub, fl.depth)

    if fl.dedupe:
        seen: set = set()
        kept = []
        for c in ranked:
            k = _sem_key(c)
            if k in seen:
                continue
            seen.add(k)
            kept.append(c)
        m["n_dup_removed"] = len(ranked) - len(kept)
    else:
        kept = ranked
        m["n_dup_removed"] = 0
    m["n_after_dedupe"] = len(kept)
    m["duplicate_rate"] = round(m["n_dup_removed"] / len(ranked), 4) if ranked else 0.0
    return kept[: fl.shortlist_m], m


def ambiguity_gate(shortlist: list[dict], fl: PipelineFlags) -> dict:
    """Chặn khi shortlist mập mờ. Trả về quyết định + LÝ DO, không chỉ bool."""
    if not shortlist:
        return {"ok": False, "reason": "EMPTY_SHORTLIST", "margin": 0.0,
                "n_distinct_values": 0}
    vals = []
    for c in shortlist:
        if c["value"] not in vals:
            vals.append(c["value"])
    top = shortlist[0]
    rival = next((c for c in shortlist[1:] if c["value"] != top["value"]), None)
    if rival is None:
        margin = 1.0
    elif top["score"] is None or top["score"] <= 0:
        # Điểm đỉnh không dương thì `(s0−s1)/s0` cho số lớn cho ứng viên tệ.
        margin = 0.0
    else:
        margin = (top["score"] - rival["score"]) / top["score"]

    if len(vals) > fl.ambiguity_max_distinct:
        return {"ok": False, "reason": "TOO_MANY_DISTINCT_VALUES",
                "margin": round(margin, 4), "n_distinct_values": len(vals)}
    if margin < fl.margin_min:
        return {"ok": False, "reason": "LOW_MARGIN",
                "margin": round(margin, 4), "n_distinct_values": len(vals)}
    return {"ok": True, "reason": None, "margin": round(margin, 4),
            "n_distinct_values": len(vals)}


def enforce_metric_consistency(per_slot: dict, fl: PipelineFlags) -> dict:
    """Mọi slot của MỘT câu số học phải nói về CÙNG một metric.

    Không có ràng buộc này thì `(B − A)` có thể lấy A là 'Cho vay khách hàng'
    còn B là 'Số dư cuối năm' của bảng dự phòng — đúng cơ chế đã tạo ra sai số
    của qid 592 trong C0. Ràng buộc rẻ, kiểm được, và bắt đúng lớp lỗi đó.
    """
    if not fl.metric_consistency or len(per_slot) < 2:
        return {"ok": True, "reason": None, "chosen_label": None}
    labels = [norm(v["pick"]["metric_label"] or "") for v in per_slot.values()
              if v.get("pick")]
    if len(labels) != len(per_slot):
        return {"ok": False, "reason": "SLOT_MISSING", "chosen_label": None}
    if len(set(labels)) == 1:
        return {"ok": True, "reason": None, "chosen_label": labels[0]}

    # Thử cứu: có nhãn nào xuất hiện trong shortlist của MỌI slot không?
    common = None
    sets = [{norm(c["metric_label"] or "") for c in v["shortlist"]}
            for v in per_slot.values()]
    inter = set.intersection(*sets) if sets else set()
    if inter:
        # chọn nhãn dài nhất — cụ thể hơn thì ít mơ hồ hơn
        common = max(inter, key=len)
        for v in per_slot.values():
            v["pick"] = next(c for c in v["shortlist"]
                             if norm(c["metric_label"] or "") == common)
            v["repaired_by_consistency"] = True
        return {"ok": True, "reason": "REPAIRED_BY_COMMON_LABEL",
                "chosen_label": common}
    return {"ok": False, "reason": "METRIC_MISMATCH_ACROSS_SLOTS",
            "chosen_label": None, "labels": sorted(set(labels))}
