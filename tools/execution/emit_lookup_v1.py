#!/usr/bin/env python3
"""Lookup emitter C1a–C1e — MỖI BẬC ĐÚNG MỘT THAY ĐỔI HÀNH VI.

Review 127 §5 bác bỏ D4 của doc 126 vì gộp 7 việc vào một candidate. Thang ở
đây đúng theo bảng review 127 §5:

    C1a  emitter lookup tất định                (tạo baseline execution mới)
    C1b  + operand-spec                          (đo chain-slot)
    C1c  + margin gate / tie policy              (đo occurrence mập mờ)
    C1d  + statement prior (họ SIGN)             (đo họ dấu)
    C1e  + unit scale                            (đo họ scale)

Mỗi cờ bật độc lập được ⇒ ablate được từng họ, không chỉ so đầu-cuối.

BA QUYẾT ĐỊNH THIẾT KẾ CẦN GIẢI THÍCH
------------------------------------
1. `.item()` chứ không `.values[0]`. Gate C1 đòi "first-cell usage = 0".
   `.values[0]` LẶNG LẼ lấy ô đầu khi filter khớp nhiều dòng — đúng cơ chế sinh
   ra lỗi occurrence mà doc 97 đã đo. `.item()` NÉM lỗi khi multiplicity != 1,
   nên sai sót lộ ra ở replay thay vì thành một con số trông hợp lý.

2. Quy đổi đơn vị NẰM TRONG query. Luật:  đáp án = raw · 10^scale / hệ_số_đơn_vị.
   ⚠️ Luật này khớp 21/21 câu lookup gold-45 nhưng đó là TAUTOLOGY: bộ sinh gold
   (`tools/gold_dap_an/02_phan_xu_o.py`) dùng CHÍNH công thức ấy. Nhãn đúng:
   `TAUTOLOGY_KHONG_XAC_NHAN`. Tập xác nhận độc lập là DEV-60 sau khi gán nhãn.
   `scale` lấy qua `effective_scale()` để áp 34 override đã phân xử (docs/103 F2).

3. Emitter KHÔNG ghi đè C0 khi không đủ tự tin. Lý do đo được: recall@1 của
   ranker là 20,7% (bản legacy) / 12,6% (bản tất định), trong khi C0 đang đúng
   57,1% ở lớp lookup của gold-45. Ghi đè vô điều kiện là TỤT ĐIỂM. Cổng tự tin
   (C1c) vì vậy không phải tuỳ chọn — nó là điều kiện để C1 không âm.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from .fact_rank_v1 import Flags, V1_2, apply_quota, fetch_pool, norm, score_pool, toks

# Hệ số quy đổi từ ĐỒNG về đơn vị câu hỏi.
UNIT_FACTOR = {
    "trieu": 1e6, "million_VND": 1e6,
    "ty": 1e9, "billion_VND": 1e9,
    "tram_ty": 1e11, "nghin_ty": 1e12,
    "dong": 1.0, "VND": 1.0,
}
UNIT_FACTOR["nghin"] = 1e3

# ── lớp phủ scale cho 34 ca A6_DEFECT (docs/103 F2, review 131 §6.2) ─────────
_OVERRIDES: dict | None = None


def unit_overrides() -> dict:
    """observation_uid -> scale đã phân xử. Rỗng nếu chưa sinh bảng override."""
    global _OVERRIDES
    if _OVERRIDES is None:
        import json as _json
        import pathlib as _pl
        f = _pl.Path(__file__).resolve().parents[2] / "configs/execution/unit_scale_overrides_v1.json"
        _OVERRIDES = (_json.loads(f.read_text(encoding="utf-8"))["overrides"]
                      if f.is_file() else {})
    return _OVERRIDES


def effective_scale(cell: dict) -> int:
    """Scale THỰC DỤNG của một ô = override nếu có, ngược lại giá trị A6.

    Một hàm duy nhất cho mọi tầng. Nếu có hai đường tính scale thì sớm muộn
    chúng trôi dạt, và đó đúng là cách 34 ca kia sinh ra.
    """
    uid = cell.get("observation_uid")
    ov = unit_overrides().get(uid) if uid else None
    if ov:
        cell["effective_scale_exponent"] = int(ov["final_scale_exponent"])
        cell["scale_override_applied"] = True
        return int(ov["final_scale_exponent"])
    return int(cell.get("scale_exponent") or 0)


# THỨ TỰ QUAN TRỌNG: "nghìn tỷ" phải khớp trước "tỷ", "nghìn đồng" phải khớp
# trước "đồng". Bản đầu thiếu "nghìn đồng" nên 16 câu bị quy về hệ số 1,0 thay
# vì 1e3 — sai đúng 1.000 lần mà không có gì báo.
UNIT_LEXICON = [
    (r"nghìn\s+tỷ|nghin\s+ty", "nghin_ty", 1e12),
    (r"trăm\s+tỷ|tram\s+ty", "tram_ty", 1e11),
    (r"nghìn\s+đồng|nghin\s+dong", "nghin", 1e3),
    (r"\btỷ\b|\bty\b|tỉ\s+đồng", "ty", 1e9),
    (r"\btriệu\b", "trieu", 1e6),
    (r"\bđồng\b", "dong", 1.0),
]
# Câu hỏi %/lần KHÔNG phải lookup tiền tệ — emitter này không có quyền trả lời.
# Trả về hệ số None để `pick` bỏ qua, thay vì lặng lẽ dùng 1,0.
NON_MONEY = re.compile(r"bao nhiêu\s*%|\btỷ lệ\b|\btỷ trọng\b|bao nhiêu lần|\bsố lần\b", re.I)

# C1d — statement prior. qid 1 của C0 lấy đúng TRỊ TUYỆT ĐỐI nhưng từ dòng LƯU
# CHUYỂN TIỀN TỆ (khoản điều chỉnh, mang dấu âm) thay vì dòng thuyết minh doanh
# thu tài chính. Đó không phải "lỗi dấu" cần lật dấu — đó là chọn nhầm loại báo
# cáo. Lật dấu sẽ vá đúng qid 1 và hỏng những câu thật sự hỏi về dòng tiền.
CASHFLOW_CUES = re.compile(r"lưu chuyển|dòng tiền|luồng tiền|chi ra|thu vào", re.I)
EQUITY_CUES = re.compile(r"biến động vốn|thay đổi vốn chủ", re.I)


@dataclass(frozen=True)
class EmitFlags:
    lookup_emitter: bool = False   # C1a
    operand_spec: bool = False     # C1b
    margin_gate: bool = False      # C1c
    statement_prior: bool = False  # C1d (họ SIGN)
    unit_scale: bool = False       # C1e
    depth: int = 20
    margin_min: float = 0.15       # chênh lệch tương đối top1 vs top2 cùng-giá-khác
    rank_flags: Flags = V1_2

    @property
    def name(self) -> str:
        on = [n for n in ("lookup_emitter", "operand_spec", "margin_gate",
                          "statement_prior", "unit_scale") if getattr(self, n)]
        return "+".join(on) or "none"


LADDER = {
    "C1a": EmitFlags(lookup_emitter=True),
    "C1b": EmitFlags(lookup_emitter=True, operand_spec=True),
    "C1c": EmitFlags(lookup_emitter=True, operand_spec=True, margin_gate=True),
    "C1d": EmitFlags(lookup_emitter=True, operand_spec=True, margin_gate=True,
                     statement_prior=True),
    "C1e": EmitFlags(lookup_emitter=True, operand_spec=True, margin_gate=True,
                     statement_prior=True, unit_scale=True),
}


def asked_unit(plan: dict) -> tuple[str, float | None]:
    """Đơn vị câu hỏi + hệ số chia. Đọc từ CÂU, không từ nhãn gold.

    Trả `None` = KHÔNG XÁC ĐỊNH ⇒ emitter phải bỏ qua. Bản đầu trả `1,0` cho
    mọi trường hợp không nhận ra, tức đoán "đồng" — và đoán im lặng ở tầng đơn
    vị là cách sinh ra lỗi sai 10³/10⁶ mà docs/103 F2 đã đếm được 34 ca.
    """
    q = unicodedata.normalize("NFC", plan["question"].lower())
    if NON_MONEY.search(q):
        return "khong_phai_tien", None
    ou = plan.get("output_unit")
    if ou in UNIT_FACTOR:
        return ou, UNIT_FACTOR[ou]
    for pat, name, f in UNIT_LEXICON:
        if re.search(pat, q):
            return name, f
    return "khong_xac_dinh", None


def metric_phrase(plan: dict, registry_labels: list[str]) -> str | None:
    """C1b — operand-spec: nhãn metric DÀI NHẤT là chuỗi con của câu.

    Vì sao cần: chấm điểm bằng TOÀN BỘ câu làm mọi token phụ (tên công ty, năm,
    'là bao nhiêu') tham gia, kéo các nhãn dài ngẫu nhiên lên. Dùng đúng cụm
    metric thu hẹp không gian và là bước bắt buộc trước khi xử chain-slot.
    """
    qn = norm(plan["question"])
    best = None
    for lab in registry_labels:
        ln = norm(lab)
        if len(ln) >= 6 and ln in qn and (best is None or len(ln) > len(best)):
            best = ln
    return best


CHAIN_CUES = ("số dư cuối năm", "số dư đầu năm", "số cuối năm", "số đầu năm",
              "số dư cuối kỳ", "số dư đầu kỳ", "tổng cộng", "tổng quỹ lương")


def spec_text(plan: dict, phrase: str | None) -> str:
    """Văn bản dùng để chấm điểm. C1b thay câu đầy đủ bằng cụm metric + cue chuỗi."""
    if not phrase:
        return plan["question"]
    qn = norm(plan["question"])
    extra = [c for c in CHAIN_CUES if c in qn]
    return " ".join([phrase, *extra])


def _stmt_penalty(cell: dict, plan: dict) -> float:
    q = plan["question"]
    st = cell.get("statement_type")
    if st == "cash_flow" and not CASHFLOW_CUES.search(q):
        return -1.5
    if st == "equity_change" and not EQUITY_CUES.search(q):
        return -1.0
    return 0.0


def pick(con: sqlite3.Connection | None, plan: dict, fl: EmitFlags,
         registry_labels: list[str], pool: list[dict] | None = None) -> dict | None:
    """Chọn MỘT ô cho câu lookup. → dict quyết định, hoặc None nếu bỏ qua.

    `pool` truyền sẵn để ablation không phải quét lại DB 5 lần cho cùng một QID
    (572 câu × 5 bậc × ~0,2s = ~10 phút chỉ để đọc lại đúng dữ liệu ấy).
    """
    if pool is None:
        pool = fetch_pool(con, plan, legacy_order=fl.rank_flags.legacy_order)
    if not pool:
        return None

    phrase = metric_phrase(plan, registry_labels) if fl.operand_spec else None
    scoring_plan = dict(plan)
    scoring_plan["question"] = spec_text(plan, phrase) if fl.operand_spec else plan["question"]

    scored = score_pool(pool, scoring_plan, fl.rank_flags)
    if fl.statement_prior:
        for c in scored:
            c["score"] = round(c["score"] + _stmt_penalty(c, plan), 6)
        # PHẢI dùng ĐÚNG quy ước thứ tự của bậc đang chạy. Bản đầu luôn sắp xếp
        # tie-break tất định ở đây, nên C1d/C1e âm thầm mang THÊM một thay đổi
        # hành vi (khoá tie-break) ngoài statement prior — đúng thứ mà chính báo
        # cáo này nói là làm sai lệch mọi phép đo ranking. Một bậc, một thay đổi.
        if fl.rank_flags.legacy_order:
            scored.sort(key=lambda c: -c["score"])
        else:
            scored.sort(key=lambda c: (-c["score"], str(c["observation_uid"])))
    top = apply_quota(scored, plan, fl.depth) if fl.rank_flags.quota else scored[:fl.depth]
    if not top:
        return None

    c0 = top[0]
    unit_name, factor = asked_unit(plan)

    # Margin: chỉ tính với ứng viên có GIÁ TRỊ KHÁC top-1. Hai ô cùng giá trị
    # thì chọn ô nào cũng ra cùng đáp án — không phải mập mờ đáng chặn.
    rival = next((c for c in top[1:] if c["value"] != c0["value"]), None)
    if rival is None:
        margin = 1.0          # mọi ứng viên đồng thuận giá trị ⇒ không mập mờ
        margin_note = "NO_RIVAL_VALUE"
    elif c0["score"] <= 0:
        # `_stmt_penalty` có thể kéo điểm xuống âm. Khi ấy `(s0−s1)/|s0|` cho
        # số LỚN cho một ứng viên TỆ (s0=−0,5, s1=−2,0 → 3,0) và cổng mở toang.
        # Điểm đỉnh không dương thì không có cơ sở nào để tự tin.
        margin = 0.0
        margin_note = "TOP1_SCORE_NON_POSITIVE"
    else:
        margin = (c0["score"] - rival["score"]) / c0["score"]
        margin_note = "REL_GAP"

    if factor is None:
        return {"cell": c0, "phrase": phrase, "margin": round(margin, 4),
                "unit_name": unit_name, "unit_factor": None,
                "scale_exponent_applied": None, "answer": None,
                "abstain": True, "abstain_reason": "UNIT_UNRESOLVED",
                "margin_note": margin_note, "n_top": len(top)}

    scale = effective_scale(c0) if fl.unit_scale else 0
    try:
        raw = float(c0["value"])
    except (TypeError, ValueError):
        return None
    answer = raw * (10 ** scale) / factor
    low = bool(fl.margin_gate and margin < fl.margin_min)

    return {
        "cell": c0, "phrase": phrase, "margin": round(margin, 4),
        "margin_note": margin_note,
        "rival_value": rival["value"] if rival else None,
        "unit_name": unit_name, "unit_factor": factor,
        "scale_exponent_applied": scale,
        "answer": answer,
        "abstain": low,
        "abstain_reason": "LOW_MARGIN" if low else None,
        "n_top": len(top),
    }


def build_query(cell: dict, var: str, factor: float, scale: int) -> str:
    """pandas_query tất định. `.item()` ném lỗi nếu filter khớp != 1 dòng."""
    def lit(s: str) -> str:
        return "'" + str(s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"

    mul = f" * {10 ** scale}" if scale else ""
    div = f" / {factor:.0f}" if factor != 1.0 else ""
    return (f"float({var}.loc[({var}['row_path'] == {lit(cell['row_path'])}) & "
            f"({var}['col_label'] == {lit(cell['col_path'])}) & "
            f"({var}['row_label'] == {lit(cell['metric_label'])}), 'value'].item())"
            f"{mul}{div}")


CSV_COLS = ["row_path", "row_label", "col_label", "value_raw", "value"]


def evidence_csv(con: sqlite3.Connection, evidence_ref: str) -> list[list]:
    """Bảng CSV cho một evidence_ref — ĐÚNG schema mà C0 đang dùng."""
    rows = con.execute("""
        SELECT row_path_text, metric_label_clean, col_path_text,
               value_source_raw, value_decimal_text
        FROM observations WHERE evidence_ref = ?
        ORDER BY grid_row_idx, grid_col_idx, observation_uid""", (evidence_ref,)).fetchall()
    return [[a or "", b or "", c or "", d or "", e or ""] for a, b, c, d, e in rows]
