#!/usr/bin/env python3
"""Workstream B · nhóm feature `row_path`. Công thức, không phải mô tả.

Doc 140 §3.5 bác bản đầu vì feature được mô tả bằng lời ("chọn theo độ cụ thể
của câu hỏi") chứ không bằng công thức. Mỗi feature dưới đây khai đủ: trường
đầu vào được phép đọc · normalizer · công thức · miền giá trị · hành vi khi hoà ·
nhóm failure dự kiến sửa · có vòng tròn với bộ sinh gold hay không.

VÌ SAO `row_path` ĐÁNG LÀM TRƯỚC (reports/ceiling_analysis_v1.json)

    row_path lệch ở 25/37 miss   ← nhiều nhất trong mọi trường
    7 miss lệch CHỈ row_path      ← mọi chiều khác giống hệt
    STRUCTURAL 5/5 lệch duy nhất row_path
    và `row_path` KHÔNG có mặt trong điểm số

VÒNG TRÒN — nói trước, không giấu
Bộ sinh gold `02_phan_xu_o.py` luật 7 chọn `row_path_text` **ngắn nhất**. Bất kỳ
feature nào thưởng path ngắn đều trùng luật ấy ⇒ đúng trên gold-45 theo cấu tạo.
`row_depth_prior` vì thế mang `circular_with_gold=True` và **không được** dùng để
claim gain. Ba feature còn lại đọc quan hệ path↔câu hỏi và path↔bảng, không nằm
trong luật sinh gold.
"""
from __future__ import annotations

import math
import re

from .fact_rank_v1 import norm, toks

# Hư từ tiếng Việt + từ khung kế toán xuất hiện ở hầu hết row_path. Giữ chúng
# lại thì mọi path đều "khớp câu hỏi" và feature mất khả năng phân biệt.
STOPWORD = frozenset("""
va cua cho tai theo tren duoi trong ngoai cac nhung mot cai chiec la co khong
den tu voi ve boi do nay kia ay day cung deu con neu thi ma nhung bang gom
chi tiet muc khoan phan bao gom tong cong so tien dong vnd trieu ty nghin
""".split())

# Ranh giới đoạn trong row_path/col_path do A6 sinh.
SEP = re.compile(r"\s*›\s*")


def doan(path: str | None) -> list[str]:
    """row_path → danh sách đoạn, đã bỏ đoạn rỗng."""
    return [d for d in SEP.split(path or "") if d.strip()]


def do_sau(path: str | None) -> int:
    """Độ sâu = số đoạn. Path rỗng ⇒ 0."""
    return len(doan(path))


def tok_noi_dung(s: str | None) -> set[str]:
    """Token có nội dung: bỏ hư từ và token quá ngắn.

    Không bỏ token số — "2024", "12" mang thông tin kỳ và không thể loại.
    """
    return {t for t in toks(s or "") if t not in STOPWORD and len(t) > 1}


# ── các feature ────────────────────────────────────────────────────────────
#
# Quy ước chung: mọi hàm trả `float`, 0.0 nghĩa là "không có ý kiến" (trung
# tính), không phải "phạt". Khi hoà điểm, tie-break vẫn là `observation_uid` ở
# `rank_pool` — các hàm này KHÔNG tự phá hoà.

def row_path_overlap(c: dict, ctx: dict) -> float:
    """IDF overlap giữa `row_path` và câu hỏi, TRỪ phần đã tính ở `metric_label`.

    input   : c["row_path"], c["metric_label"], ctx["qt"], ctx["df_row"], ctx["n_pool"]
    công thức:
        R = tok_noi_dung(row_path) − tok_noi_dung(metric_label)
        s = Σ_{t ∈ R ∩ Q} log(1 + n_pool / df_row[t])  /  √(|R| + 1)
    miền     : [0, ~4]
    sửa      : STRUCTURAL, TEMPORAL
    vòng tròn: KHÔNG — bộ sinh gold không đọc quan hệ row_path↔câu hỏi

    Trừ phần `metric_label` là điểm mấu chốt: nếu không trừ, feature này chỉ
    lặp lại `idf_overlap` (vốn đã ghép nhãn + row_path) và ablation sẽ cho gain
    giả do cộng đôi cùng một tín hiệu.
    """
    R = tok_noi_dung(c.get("row_path")) - tok_noi_dung(c.get("metric_label"))
    if not R:
        return 0.0
    inter = R & ctx["qt"]
    if not inter:
        return 0.0
    df = ctx["df_row"]
    return sum(math.log(1 + ctx["n_pool"] / max(df.get(t, 1), 1))
               for t in inter) / ((len(R) + 1) ** 0.5)


def row_path_specificity(c: dict, ctx: dict) -> float:
    """Thưởng path mà câu hỏi PHỦ, phạt theo token THỪA — không phạt độ dài.

    input   : c["row_path"], c["metric_label"], ctx["qt"]
    công thức:
        R = tok_noi_dung(row_path) − tok_noi_dung(metric_label)
        phu   = |R ∩ Q| / |R|
        thua  = |R − Q| / |R|
        s     = phu − 0.5 · thua                      ∈ [−0.5, 1]
    sửa      : SEMANTIC, STRUCTURAL
    vòng tròn: KHÔNG

    Doc 140 §3.5 cảnh báo đúng: đòi "MỌI token đều xuất hiện" theo nghĩa đen sẽ
    làm feature gần như luôn bằng 0, hoặc thưởng nhầm path ngắn (path 1 token
    dễ được phủ toàn bộ). Vì vậy đây là TỈ LỆ có trừ phần thừa, và mẫu số |R|
    tự chuẩn hoá độ dài — path ngắn không được lợi thế miễn phí.
    """
    R = tok_noi_dung(c.get("row_path")) - tok_noi_dung(c.get("metric_label"))
    if not R:
        return 0.0
    phu = len(R & ctx["qt"]) / len(R)
    thua = len(R - ctx["qt"]) / len(R)
    return phu - 0.5 * thua


def row_sibling_penalty(c: dict, ctx: dict) -> float:
    """Phạt ô nằm trong bảng có NHIỀU dòng cùng nhãn — dấu hiệu bảng phân rã.

    input   : c["metric_label"], c["table_uid"], ctx["dem_nhan_trong_bang"]
    công thức:
        n = số ô trong CÙNG table_uid có cùng norm(metric_label)
        s = − log(1 + max(n − 1, 0)) / 3                ∈ [−~1.5, 0]
    sửa      : AMBIGUITY, STRUCTURAL
    vòng tròn: KHÔNG

    Cơ chế: khi một nhãn ("Phải thu khác") xuất hiện 8 lần trong một bảng thuyết
    minh, mỗi lần là một dòng con khác nhau, thì `idf_overlap` cho cả 8 điểm
    bằng nhau và top-1 do tie-break quyết định. Đó chính là qid 636 và 817.
    Phạt nhẹ nhóm ấy đẩy ô ở bảng KHÔNG phân rã lên trước.
    """
    key = (c.get("table_uid"), norm(c.get("metric_label") or ""))
    n = ctx["dem_nhan_trong_bang"].get(key, 1)
    return -math.log(1 + max(n - 1, 0)) / 3.0


def row_depth_prior(c: dict, ctx: dict) -> float:
    """Phạt độ sâu, NHƯNG miễn khi đoạn sâu được câu hỏi nhắc tới.

    input   : c["row_path"], ctx["qt"]
    công thức:
        d      = số đoạn của row_path
        duoc_hoi = số đoạn có ≥1 token nội dung ∈ Q
        s      = −0.25 · max(d − duoc_hoi − 1, 0)       ∈ [−~1.5, 0]
    sửa      : STRUCTURAL
    vòng tròn: **CÓ** — luật 7 của bộ sinh gold chọn row_path NGẮN NHẤT

    Giữ cờ này tách riêng chính vì nó vòng tròn: mọi gain của nó trên gold-45
    phải bị loại khỏi nhánh NONCIRCULAR. Điểm khác với `section_depth` sẵn có
    (−0.25 × số dấu ›, không điều kiện): ở đây đoạn nào câu hỏi có nhắc thì
    được miễn phạt, nên path sâu-mà-đúng không bị thiệt.
    """
    ds = doan(c.get("row_path"))
    if not ds:
        return 0.0
    duoc_hoi = sum(1 for d in ds if tok_noi_dung(d) & ctx["qt"])
    return -0.25 * max(len(ds) - duoc_hoi - 1, 0)


REGISTRY = {
    "row_path_overlap": {
        "weight": 0.8, "ham": row_path_overlap, "mien": "[0, ~4]",
        "sua_failure": "STRUCTURAL, TEMPORAL", "circular_with_gold": False,
        "hand_tuned": True},
    "row_path_specificity": {
        "weight": 1.0, "ham": row_path_specificity, "mien": "[-0.5, 1]",
        "sua_failure": "SEMANTIC, STRUCTURAL", "circular_with_gold": False,
        "hand_tuned": True},
    "row_sibling_penalty": {
        "weight": 1.0, "ham": row_sibling_penalty, "mien": "[-1.5, 0]",
        "sua_failure": "AMBIGUITY, STRUCTURAL", "circular_with_gold": False,
        "hand_tuned": True},
    "row_depth_prior": {
        "weight": 1.0, "ham": row_depth_prior, "mien": "[-1.5, 0]",
        "sua_failure": "STRUCTURAL", "circular_with_gold": True,
        "hand_tuned": True},
}


def bo_sung_ctx(ctx: dict, pool: list[dict]) -> dict:
    """Thêm `df_row` và `dem_nhan_trong_bang` vào ctx của score_v2."""
    df_row: dict[str, int] = {}
    dem: dict[tuple, int] = {}
    for c in pool:
        R = tok_noi_dung(c.get("row_path")) - tok_noi_dung(c.get("metric_label"))
        for t in R:
            df_row[t] = df_row.get(t, 0) + 1
        k = (c.get("table_uid"), norm(c.get("metric_label") or ""))
        dem[k] = dem.get(k, 0) + 1
    ctx["df_row"] = df_row
    ctx["dem_nhan_trong_bang"] = dem
    return ctx
