#!/usr/bin/env python3
"""Per-slot scoring v2 — D1(a). Mỗi feature một cờ, mỗi cờ một lý do.

⚠️ CẢNH BÁO VÒNG TRÒN — ĐỌC TRƯỚC MỌI CON SỐ
--------------------------------------------
Bộ sinh gold `tools/gold_dap_an/02_phan_xu_o.py` chọn ô bằng CHÍNH những tín
hiệu mà scoring đang thiếu:

    SQL filter   o.period_end LIKE '<year>%'
    luật 3       period_role == 'current'
    luật 4       doc_year == year
    luật 5       is_restated == 0
    luật 6       confidence != 'low'
    luật 7       row_path_text NGẮN NHẤT
    tiền lọc     chuan(metric_label) là chuỗi con của câu hỏi

Vì vậy mọi feature trùng danh sách trên sẽ **tự động đúng trên gold-45** —
không phải vì nó tốt, mà vì gold được DỰNG bằng nó. Đo gain của chúng trên
gold-45 là tautology, đúng loại lỗi mà luật đơn vị đã dính (docs/132 §3.3).

Mỗi feature dưới đây vì thế mang cờ `circular_with_gold`:

    True   trùng luật của bộ sinh gold ⇒ gain trên gold-45 KHÔNG chứng minh gì.
           Vẫn cài, vì nó ĐÚNG về ngữ nghĩa kế toán và cần cho DEV/official.
    False  không nằm trong luật sinh gold ⇒ gain đo được CÓ nghĩa.

Báo cáo BẮT BUỘC tách hai nhóm. Một `operand_set_exact` cao nhờ nhóm circular
là con số vô giá trị.

TAXONOMY DẪN ĐƯỜNG (reports/diag_slot_scoring_v1.json, n = 66 slot)

    TEMPORAL            17  25,8%   đúng nhãn, sai cột (cuối/đầu năm, nay/trước)
    SEMANTIC             8  12,1%   nhãn gần giống, khác nghĩa
    STRUCTURAL           6   9,1%   đúng nhãn, khác section
    ACCOUNTING_CONTEXT   5   7,6%   khác statement_type
    LEXICAL              5   7,6%   top-1 trùng nhiều token hơn
    UNSCORABLE           4   6,1%   0 token chung ⇒ không vào bảng xếp hạng
    AMBIGUITY            2   3,0%   cùng giá trị, khác ô
    HIT                 19  28,8%
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .fact_rank_v1 import norm, toks
from .period_parse_v1 import period_match
from .row_feats_v1 import REGISTRY as ROW_REGISTRY, bo_sung_ctx

# Cột ĐẦU KỲ / KỲ TRƯỚC — nguồn của nhóm TEMPORAL (17/66).
OPENING_CUES = re.compile(
    r"số\s*đầu\s*(năm|kỳ)|đầu\s*kỳ|năm\s*trước|kỳ\s*trước|"
    r"\b0?1[/.-]0?1[/.-]|don\s*vi\s*tính.*năm\s*trước", re.I)
CLOSING_CUES = re.compile(
    r"số\s*cuối\s*(năm|kỳ)|cuối\s*kỳ|năm\s*nay|kỳ\s*này|"
    r"\b31[/.\s-]*(tháng)?\s*12\b", re.I)


@dataclass(frozen=True)
class ScoreFlags:
    """S0 → S5. Mỗi bậc thêm ĐÚNG một nhóm feature."""
    # S0 · nguyên trạng
    idf_overlap: bool = True
    exact_phrase: bool = True
    col_year: bool = True
    doc_year_bonus: bool = True
    ready: bool = True
    # S1 · operand-specific phrase
    operand_phrase: bool = False
    # S2 · structural / table context
    section_depth: bool = False
    statement_prior: bool = False
    # S3 · period / year / basis
    period_end_year: bool = False
    period_role: bool = False
    period_col_cue: bool = False
    not_restated: bool = False
    # S4 · accounting semantic
    unit_compat: bool = False
    confidence_bonus: bool = False
    label_specificity: bool = False
    # B · nhóm row_path (doc 140 §3.5) — công thức ở execution/row_feats_v1.py
    row_path_overlap: bool = False
    row_path_specificity: bool = False
    row_sibling_penalty: bool = False
    row_depth_prior: bool = False
    # B-2 · TÁCH nhãn khỏi row_path trong idf_overlap. Xem ghi chú ở score_cell.
    split_label_row: bool = False
    # C · parser kỳ. `period_parse` THAY `col_year` (không cộng thêm lên trên).
    period_parse: bool = False

    @property
    def name(self) -> str:
        on = [k for k, v in self.__dict__.items() if v and k not in
              ("idf_overlap", "exact_phrase", "col_year", "doc_year_bonus", "ready")]
        return "S0" if not on else "S0+" + "+".join(on)


# Đăng ký feature: trọng số · ý nghĩa · failure mode nó sửa · circular · hand-tuned
FEATURE_REGISTRY = {
    "idf_overlap": {
        "weight": "biến thiên", "y_nghia": "IDF token chung câu↔nhãn, chia √len(nhãn)",
        "sua_failure": "cơ sở", "circular_with_gold": True,
        "hand_tuned": False,
        "ghi_chu": "gold lọc trước bằng 'nhãn là chuỗi con của câu' ⇒ trùng ý tưởng"},
    "exact_phrase": {
        "weight": 3.0, "y_nghia": "nhãn metric xuất hiện nguyên văn trong câu",
        "sua_failure": "LEXICAL", "circular_with_gold": True, "hand_tuned": True},
    "col_year": {
        "weight": 0.6, "y_nghia": "năm hỏi là chuỗi con của col_path",
        "sua_failure": "TEMPORAL (yếu)", "circular_with_gold": False,
        "hand_tuned": True,
        "ghi_chu": "KHÔNG phân biệt 31/12/2019 với 1/1/2019 — nguồn của 17 ca TEMPORAL"},
    "doc_year_bonus": {
        "weight": 0.3, "y_nghia": "doc_year thuộc năm hỏi",
        "sua_failure": "TEMPORAL", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "trùng luật 4 của bộ sinh gold"},
    "ready": {
        "weight": 0.3, "y_nghia": "execution_ready", "sua_failure": "nhiễu parse",
        "circular_with_gold": False, "hand_tuned": True},

    "operand_phrase": {
        "weight": 2.0, "y_nghia": "cụm metric TÍNH RIÊNG cho từng operand thay vì dùng chung cả câu",
        "sua_failure": "LEXICAL, SEMANTIC", "circular_with_gold": True,
        "hand_tuned": True,
        "ghi_chu": "gold tiền lọc bằng 'nhãn ⊂ câu' nên mọi tín hiệu nhãn↔câu đều circular"},

    "section_depth": {
        "weight": -0.25, "y_nghia": "phạt theo ĐỘ SÂU row_path (số dấu ›)",
        "sua_failure": "STRUCTURAL", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "trùng luật 7 (row_path NGẮN NHẤT) của bộ sinh gold"},
    "statement_prior": {
        "weight": -1.5, "y_nghia": "phạt cash_flow/equity_change khi câu không hỏi dòng tiền",
        "sua_failure": "ACCOUNTING_CONTEXT", "circular_with_gold": False,
        "hand_tuned": True},

    "period_end_year": {
        "weight": 2.5, "y_nghia": "period_end bắt đầu bằng năm hỏi",
        "sua_failure": "TEMPORAL", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "CHÍNH LÀ filter SQL của bộ sinh gold — 66/66 theo cấu tạo"},
    "period_role": {
        "weight": 1.5, "y_nghia": "period_role ∈ {current, closing}",
        "sua_failure": "TEMPORAL", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "trùng luật 3 của bộ sinh gold"},
    "period_col_cue": {
        "weight": 1.2, "y_nghia": "col_path có dấu hiệu CUỐI kỳ (+) / ĐẦU kỳ (−)",
        "sua_failure": "TEMPORAL", "circular_with_gold": False, "hand_tuned": True,
        "ghi_chu": "đọc từ VĂN BẢN cột, độc lập với period_role của A6"},
    "not_restated": {
        "weight": 0.5, "y_nghia": "is_restated == 0",
        "sua_failure": "AMBIGUITY", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "trùng luật 5"},

    "unit_compat": {
        "weight": 0.4, "y_nghia": "unit_kind khớp loại đơn vị câu hỏi (money/percent)",
        "sua_failure": "SEMANTIC", "circular_with_gold": False, "hand_tuned": True},
    "confidence_bonus": {
        "weight": 0.4, "y_nghia": "confidence != 'low'",
        "sua_failure": "nhiễu parse", "circular_with_gold": True, "hand_tuned": True,
        "ghi_chu": "trùng luật 6"},
    "label_specificity": {
        "weight": 0.5, "y_nghia": "thưởng nhãn PHỦ nhiều token của cụm hỏi (recall nhãn)",
        "sua_failure": "SEMANTIC", "circular_with_gold": False, "hand_tuned": True,
        "ghi_chu": "bù mẫu số √len(lt) vốn phạt nhãn dài"},
}

LADDER = {
    "S0": ScoreFlags(),
    "S1": ScoreFlags(operand_phrase=True),
    "S2": ScoreFlags(operand_phrase=True, section_depth=True, statement_prior=True),
    "S3": ScoreFlags(operand_phrase=True, section_depth=True, statement_prior=True,
                     period_end_year=True, period_role=True, period_col_cue=True,
                     not_restated=True),
    "S4": ScoreFlags(operand_phrase=True, section_depth=True, statement_prior=True,
                     period_end_year=True, period_role=True, period_col_cue=True,
                     not_restated=True, unit_compat=True, confidence_bonus=True,
                     label_specificity=True),
}
LADDER["S5"] = LADDER["S4"]          # v2 cuối = S4 (không thêm gì sau ablation)

# Chỉ những feature KHÔNG vòng tròn với bộ sinh gold — con số duy nhất có nghĩa.
NONCIRCULAR = ScoreFlags(statement_prior=True, period_col_cue=True,
                         unit_compat=True, label_specificity=True)


def _cue(col: str) -> float:
    """+1 nếu cột là CUỐI kỳ, −1 nếu ĐẦU kỳ/kỳ trước, 0 nếu không rõ."""
    if OPENING_CUES.search(col or ""):
        return -1.0
    if CLOSING_CUES.search(col or ""):
        return 1.0
    return 0.0


def score_cell(c: dict, ctx: dict, fl: ScoreFlags) -> tuple[float | None, dict]:
    """→ (điểm, phân rã). `None` = không chấm được (0 token chung)."""
    lt = toks((c["metric_label"] or "") + " " + c["row_path"])
    qt = ctx["qt_operand"] if (fl.operand_phrase and ctx.get("qt_operand")) else ctx["qt"]
    inter = qt & lt
    if not (lt and inter):
        return None, {"scorable": False}

    p: dict[str, float] = {}
    # ⚠️ ĐÍNH CHÍNH TIỀN ĐỀ CỦA DOC 138
    # Doc 138 viết "`row_path` KHÔNG hề có trong scorer" và xếp workstream B lên
    # đầu vì lý do đó. SAI. Dòng `lt` ngay trên GHÉP metric_label với row_path
    # rồi mới tách token — nên row_path đã tham gia cả TỬ SỐ (qua `inter`) lẫn
    # MẪU SỐ `√|lt|`. Nó không vắng mặt; nó bị TRỘN LẪN và không cân riêng được.
    #
    # Hệ quả đo được (reports/scoring_ablation_v3.json): cộng thêm
    # `row_path_overlap` lên trên làm slot_top1 TỤT 29→22, vì đó là cộng đôi
    # cùng một tín hiệu. Cách đúng không phải CỘNG THÊM mà là TÁCH RA.
    #
    # `split_label_row` = True: idf chỉ tính trên token của NHÃN, chuẩn hoá theo
    # √|nhãn|; phần row_path để các feature row_* cân riêng. Nhờ vậy nhãn dài
    # không còn bị mẫu số của row_path pha loãng, và ngược lại.
    if fl.split_label_row:
        lab_t = toks(c["metric_label"] or "")
        it2 = qt & lab_t
        p["idf_overlap"] = (sum(math.log(1 + ctx["n_pool"] / ctx["df"][t]) for t in it2)
                            / (len(lab_t) ** 0.5)) if (lab_t and it2) else 0.0
    else:
        p["idf_overlap"] = (sum(math.log(1 + ctx["n_pool"] / ctx["df"][t]) for t in inter)
                            / (len(lt) ** 0.5))

    if fl.exact_phrase:
        labn = norm(c["metric_label"])
        p["exact_phrase"] = 3.0 if (len(labn) >= 8 and labn in ctx["qnorm"]) else 0.0
    if fl.period_parse:
        # THAY col_year, không cộng chồng. Cộng chồng là đúng sai lầm đã đo được
        # ở workstream B: hai số hạng cùng đọc một chiều thì cộng đôi tín hiệu.
        p["period_parse"] = 1.2 * period_match(c, ctx)
    elif fl.col_year:
        p["col_year"] = 0.6 if any(y in (c["col_path"] or "") for y in ctx["years"]) else 0.0
    if fl.doc_year_bonus:
        p["doc_year_bonus"] = 0.3 if str(c["doc_year"]) in ctx["years"] else 0.0
    if fl.ready:
        p["ready"] = 0.3 * (c.get("ready") or 0)

    if fl.section_depth:
        p["section_depth"] = -0.25 * (c["row_path"] or "").count("›")
    if fl.statement_prior:
        st = c.get("statement_type")
        pen = 0.0
        if st == "cash_flow" and not ctx["hoi_dong_tien"]:
            pen = -1.5
        elif st == "equity_change" and not ctx["hoi_von"]:
            pen = -1.0
        p["statement_prior"] = pen

    if fl.period_end_year:
        pe = str(c.get("period_end") or "")
        p["period_end_year"] = 2.5 if pe[:4] in ctx["years"] else 0.0
    if fl.period_role:
        p["period_role"] = 1.5 if c.get("period_role") in ("current", "closing") else 0.0
    if fl.period_col_cue:
        p["period_col_cue"] = 1.2 * _cue(c.get("col_path") or "")
    if fl.not_restated:
        p["not_restated"] = 0.5 if not c.get("is_restated") else 0.0

    if fl.unit_compat:
        uk = c.get("unit_kind")
        p["unit_compat"] = 0.4 if (uk == ctx["unit_kind_hoi"]) else 0.0
    if fl.confidence_bonus:
        p["confidence_bonus"] = 0.4 if (c.get("confidence") not in ("low", None)) else 0.0
    if fl.label_specificity:
        lab = toks(c["metric_label"] or "")
        p["label_specificity"] = 0.5 * (len(qt & lab) / len(qt)) if qt else 0.0

    # B · row_path. ctx["qt"] dùng chung; các hàm tự lấy df_row / đếm nhãn.
    for ten, meta in ROW_REGISTRY.items():
        if getattr(fl, ten, False):
            p[ten] = meta["weight"] * meta["ham"](c, ctx)

    return round(sum(p.values()), 6), p | {"scorable": True}


def build_ctx(pool: list[dict], plan: dict, scoring_text: str,
              operand_phrase: str | None) -> dict:
    q = plan.get("question", "")
    lts = [toks((c["metric_label"] or "") + " " + c["row_path"]) for c in pool]
    df: dict[str, int] = {}
    for lt in lts:
        for t in lt:
            df[t] = df.get(t, 0) + 1
    qn = norm(scoring_text)
    return bo_sung_ctx({
        "qt": toks(scoring_text), "qnorm": qn,
        "qt_operand": toks(operand_phrase) if operand_phrase else None,
        "years": {str(y) for y in (plan.get("years") or [])},
        "df": df, "n_pool": max(len(pool), 1),
        "hoi_dong_tien": bool(re.search(r"lưu chuyển|dòng tiền|luồng tiền", q, re.I)),
        "hoi_von": bool(re.search(r"biến động vốn|thay đổi vốn chủ", q, re.I)),
        "unit_kind_hoi": ("percent" if re.search(r"%|tỷ lệ|tỷ trọng", q, re.I)
                          else "money"),
    }, pool)


def rank_pool(pool: list[dict], plan: dict, scoring_text: str, fl: ScoreFlags,
              operand_phrase: str | None = None,
              floor: bool = False) -> list[dict]:
    """Xếp hạng TẤT ĐỊNH (tie-break theo observation_uid).

    `floor` là A3 của doc 138/140. Mặc định OFF, ô `score=None` bị LOẠI khỏi
    bảng — nghĩa là 4 slot có 0 token chung không bao giờ chọn được ô nào, và
    câu chứa chúng không bao giờ đúng. Đó là lỗi cấu trúc, không phải xếp hạng
    kém.

    Khi bật, ô không chấm được nhận điểm SÀN = (điểm thấp nhất − 1) và xếp
    cuối, tie-break theo `observation_uid` nên replay hai lần cho cùng kết quả.
    Doc 140 §3.4 cảnh báo đúng: nếu hàng trăm ô cùng điểm sàn thì "cho cạnh
    tranh" KHÔNG tự tạo tín hiệu chọn đúng — nó chỉ biến "chắc chắn sai" thành
    "gần như chắc chắn sai". Vì vậy hàm trả kèm `_floor_rank` để đếm được có
    bao nhiêu ô cùng sàn, và người đọc tự phán xét.
    """
    ctx = build_ctx(pool, plan, scoring_text, operand_phrase)
    out, unscored = [], []
    for c in pool:
        s, parts = score_cell(c, ctx, fl)
        cc = dict(c)
        cc["score_parts"] = parts
        if s is None:
            cc["score"] = None
            unscored.append(cc)
            continue
        cc["score"] = s
        out.append(cc)
    out.sort(key=lambda c: (-c["score"], str(c["observation_uid"])))

    if floor and unscored:
        sàn = (out[-1]["score"] - 1.0) if out else -1.0
        unscored.sort(key=lambda c: str(c["observation_uid"]))
        for i, c in enumerate(unscored):
            c["score"] = sàn
            c["_floor_rank"] = i
            c["_n_cung_san"] = len(unscored)
        out.extend(unscored)
    return out
