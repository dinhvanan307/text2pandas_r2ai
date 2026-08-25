#!/usr/bin/env python3
"""Router deterministic — R0 | R2 | UNRESOLVED. Không có Qwen ở AG1/AG1B.

R2 chỉ được chọn khi **đủ ba điều kiện**, không phải chỉ khớp alias:
    1. khớp alias formula trong `formulas_v1.yaml`
    2. plan có ≥1 entity  (không có công ty thì không bind được lá nào)
    3. plan có ≥1 year    (không có kỳ thì không chọn được cột)

Thiếu bất kỳ điều nào → `UNRESOLVED` → R0. Đây là chỗ dễ sai nhất: khớp alias
mà thiếu entity/year rồi vẫn cố bind sẽ tạo ra một đáp án **có vẻ đúng** từ công
ty ngẫu nhiên.

Câu có cấu trúc HAI TẦNG hoặc ĐIỀU KIỆN bị đẩy về R0 **có chủ đích** — R3/R4
chưa tồn tại, và trả lời chúng bằng R2 một tầng là sai theo cấu trúc.

═══════════════════════════════════════════════════════════════════════════════
P0 · ROUTER PRECISION FIX  (cờ `router_fix_only`, mặc định TẮT)
═══════════════════════════════════════════════════════════════════════════════
NGUYÊN TẮC KHAI BÁO: **mọi lưỡng lự → R0.** R2 là đường một-entity · một-kỳ ·
một-tầng · một-phạm-vi. Bất kỳ dấu hiệu nào vượt khỏi hộp đó đều là lý do RỜI
R2, không phải lý do "thử xem sao". Ghi đè đáp án thừa kế từ parent bằng một
đáp án sai là lỗ ròng kỳ vọng dương — xem doc 147: 4/6 câu R2 của AG1 định
tuyến sai, và net correct delta official = 0.

DECISION TABLE (mỗi dòng có positive + hard negative, test trong
`tests/answer_v2/test_router_p0.py`):

  Intent                     | Dấu hiệu                    | Route | Hard negative
  ---------------------------|-----------------------------|-------|---------------
  group average / share      | NHOM                        | R0    | tên chỉ tiêu
                             |                             |       | chứa "bình quân"
                             |                             |       | (vd "tổng tài sản
                             |                             |       | bình quân") một tầng
  strongest increase/decrease| HAI_TANG (mở rộng "mạnh      | R0    | "giảm 5%" — mô tả
                             | nhất/nhanh nhất/…")         |       | một phép thay đổi đơn
  conditional period/entity  | DIEU_KIEN (mở rộng "ở các    | R0    | câu chỉ mô tả điều
                             | năm có … trên/dưới X")      |       | kiện trong NHÃN
  multi-period average       | TRUNG_BINH khi ≥2 kỳ        | R0    | một kỳ + "bình quân"
                             |                             |       | trong tên chỉ tiêu
  parent-company / separate  | PHAM_VI_RIENG               | R0    | không nhắc phạm vi
  scope                      |                             |       | → giữ R2
  counting query             | DEM                         | R0    | —
  plain 1-entity 1-period    | —                           | R2    | —

VỀ THỨ TỰ PIPELINE: router chạy SAU planner (`run_answer_v2.main` đọc
`question_plans_1012.jsonl` rồi mới gọi `route`), nên dùng `plan_q["years"]`
là hợp lệ — đây là period mentions ĐÃ parse, không phải trạng thái tương lai.
Doc 155 §5.1 nêu đúng rủi ro này; ở đây thứ tự đã xác định và được test khoá.

VỀ PHẠM VI (PHAM_VI_RIENG): binder R2 chỉ có `scope="consolidated_preferred"`
và không đọc phạm vi từ câu hỏi. Câu hỏi nói "công ty mẹ"/"riêng lẻ" mà bind
theo hợp nhất là sai **âm thầm** — đúng loại sai nguy hiểm nhất. Cho tới khi
binder nhận scope từ câu hỏi, mọi câu nhắc phạm vi riêng đều rời R2.
"""
from __future__ import annotations

import re
import unicodedata

from formula_registry import FormulaSpec, tim_theo_cau_hoi

# ══════════════════════════════════════════════════════════════════════════════
# Chuẩn hoá TRƯỚC detection.
# ══════════════════════════════════════════════════════════════════════════════
# Không bỏ dấu (các pattern dưới đây viết bằng tiếng Việt có dấu), nhưng phải
# gộp Unicode về NFC, đưa mọi biến thể khoảng trắng/gạch nối/dấu ngoặc kép về
# dạng ASCII chuẩn và ép toán tử so sánh về một ký tự. Không làm bước này thì
# "≥" (U+2265) và ">=" là hai thứ khác nhau với regex, và một câu điều kiện lọt
# lưới chỉ vì nguồn dữ liệu dùng ký tự khác.
_KHOANG_TRANG = dict.fromkeys(map(ord, "      "
                                       "      "
                                       "  　\t\r\n"), " ")
_DAU_CAU = {
    ord("‘"): "'", ord("’"): "'", ord("“"): '"', ord("”"): '"',
    ord("‐"): "-", ord("‑"): "-", ord("‒"): "-", ord("–"): "-",
    ord("—"): "-", ord("―"): "-", ord("−"): "-",
    ord("≤"): "<", ord("≥"): ">", ord("≪"): "<", ord("≫"): ">",
    ord("＜"): "<", ord("＞"): ">", ord("％"): "%",
}


def chuan_hoa_cau_hoi(q: str | None) -> str:
    """NFC + khoảng trắng/dấu câu/toán tử về dạng chuẩn + gộp space."""
    s = unicodedata.normalize("NFC", q or "")
    s = s.translate(_KHOANG_TRANG).translate(_DAU_CAU)
    return re.sub(r"\s+", " ", s).strip()


# ══════════════════════════════════════════════════════════════════════════════
# Pattern gốc (giữ nguyên hành vi khi cờ TẮT)
# ══════════════════════════════════════════════════════════════════════════════
CUC_TRI = r"(cao|thấp|lớn|nhỏ|nhiều|ít)\s*nhất"

# Dấu hiệu câu HAI TẦNG: "năm/công ty nào có X cao nhất … thì Y là bao nhiêu".
HAI_TANG = re.compile(
    r"(năm|công\s*ty|doanh\s*nghiệp|mã)\s*\w*\s*(có|đạt|ghi\s*nhận)[^,?]{5,80}"
    r"(cao nhất|thấp nhất|lớn nhất|nhỏ nhất|nhiều nhất|ít nhất)[^?]{5,}", re.I)
# Dấu hiệu MỆNH ĐỀ LỌC.
DIEU_KIEN = re.compile(
    r"\bnếu\b|\btrong số các .{2,60} có\b|\bxét các .{2,60} có\b|"
    r"\bvới điều kiện\b|\btrung vị\b|\bphân nhóm\b|\bchỉ xét\b", re.I)
# Dấu hiệu SO SÁNH nhiều kỳ — thuộc R1, không phải R2.
NHIEU_KY = re.compile(r"so với năm|tăng trưởng|thay đổi so với|chênh lệch giữa", re.I)

# ══════════════════════════════════════════════════════════════════════════════
# P0 · pattern bổ sung — chỉ hoạt động khi `router_fix=True`
# ══════════════════════════════════════════════════════════════════════════════
# (1) NHÓM / bình quân nhiều thực thể / tỷ trọng trong nhóm.
#     Neo vào NGỮ CẢNH NHÓM, không neo vào chữ "bình quân" trần — "tổng tài sản
#     bình quân" của MỘT công ty MỘT kỳ là tên chỉ tiêu, không phải phép gộp.
NHOM = re.compile(
    r"(bình quân|trung bình)\s+(của\s+)?(các|nhóm|những)\b"
    r"|(các|nhóm|những)\s+(doanh nghiệp|công ty|mã)\b[^?]{0,120}"
    r"(bình quân|trung bình|tỷ trọng)"
    r"|\btrong nhóm\b"
    r"|\bcủa\s+\d+\s+(doanh nghiệp|công ty|mã)\b"
    r"|(tỷ trọng|tỉ trọng)[^?]{0,60}\bnhóm\b", re.I)

# (2) HAI TẦNG mở rộng: cực trị diễn đạt bằng "mạnh/nhanh/chậm/sâu nhất".
#
# CỬA SỔ 240 KÝ TỰ, không phải 80. Đo trên chính tập câu hỏi: qid 386 có 110 ký
# tự giữa "năm" và "thấp nhất" ("ở năm Công ty Cổ phần Tập đoàn Masan (MSN) có
# tỷ lệ dòng tiền thuần từ hoạt động kinh doanh (CFO) trên lợi nhuận sau thuế
# thấp nhất…"), nên cửa sổ 80 để lọt. Nới cửa sổ an toàn ở đây vì mệnh đề đã
# bị chặn cứng bởi `[^?]` — không vượt qua dấu hỏi, tức không bắc cầu sang câu
# khác. Cái giá của cửa sổ hẹp là một câu HAI TẦNG lọt vào R2; cái giá của cửa
# sổ rộng là một câu một-tầng có chữ "nhất" bị đẩy về R0 — lỗi rẻ hơn nhiều.
HAI_TANG_P0 = re.compile(
    r"(mức\s+)?(giảm|tăng|biến động|sụt giảm|cải thiện)\s[^?]{0,60}"
    r"(mạnh|lớn|nhanh|chậm|sâu|ít)\s*nhất"
    r"|(doanh nghiệp|công ty|mã|năm|kỳ)\s[^?]{0,240}" + CUC_TRI, re.I)

# (3) ĐIỀU KIỆN mở rộng: "ở/trong/tại các năm|kỳ có <chỉ tiêu> trên|dưới|>|< X".
DIEU_KIEN_P0 = re.compile(
    r"(ở|trong|tại)\s+(các|những|nhũng)?\s*(năm|kỳ|quý|giai đoạn)\b[^?]{0,60}"
    r"\bcó\b[^?]{0,60}(trên|dưới|vượt|ít hơn|lớn hơn|nhỏ hơn|từ|>|<)\s*\d"
    r"|\bcó\b[^?]{0,50}(dương|âm)\b[^?]{0,80}(bình quân|trung bình|bao nhiêu)"
    r"|(các|những)\s+(doanh nghiệp|công ty|năm|mã)\s+có\b[^?]{0,80}"
    r"(trên|dưới|vượt|lớn hơn|nhỏ hơn|>|<|dương|âm)", re.I)

# (4) TRUNG BÌNH NHIỀU KỲ — chỉ chặn khi plan thật sự có ≥2 kỳ.
TRUNG_BINH = re.compile(r"\b(trung bình|bình quân)\b", re.I)

# (5) PHẠM VI RIÊNG LẺ / CÔNG TY MẸ — binder R2 không nhận scope từ câu hỏi.
PHAM_VI_RIENG = re.compile(
    r"công\s*ty\s*mẹ|riêng\s*lẻ|báo cáo\s*riêng|(bctc|báo cáo tài chính)\s*riêng",
    re.I)

# (6) CÂU ĐẾM — "có bao nhiêu doanh nghiệp …". Đầu ra là đếm, không phải tỷ số.
DEM = re.compile(r"\bcó\s+bao\s+nhiêu\s+(doanh nghiệp|công ty|mã|năm|kỳ)\b", re.I)

# Hard negative cho NHOM/TRUNG_BINH: tên CHỈ TIÊU chứa "bình quân".
# Đây là tên dòng trong BCTC, không phải phép gộp nhiều thực thể.
TEN_CHI_TIEU_BINH_QUAN = re.compile(
    r"(tổng tài sản|vốn chủ sở hữu|nợ phải trả|hàng tồn kho|khoản phải thu|"
    r"số dư|số lượng cổ phiếu|tổng nguồn vốn)\s+(bình quân|trung bình)", re.I)


def route(question: str, plan_q: dict,
          formulas: dict[str, FormulaSpec], *,
          router_fix: bool = False) -> tuple[str, FormulaSpec | None, str]:
    """→ (route, formula_spec|None, lý_do).

    `router_fix=False` tái hiện **chính xác** hành vi PRE-FIX (AG1). Mọi pattern
    P0 nằm sau cờ, nên ablation `router_fix_only` là một phép thử nhân quả sạch.
    """
    q = chuan_hoa_cau_hoi(question) if router_fix else (question or "")
    ents = list(plan_q.get("entities") or [])
    yrs = sorted(plan_q.get("years") or [])

    if HAI_TANG.search(q):
        return "R0", None, "HAI_TANG_CHUA_HO_TRO"      # R3 chưa có
    if DIEU_KIEN.search(q):
        return "R0", None, "DIEU_KIEN_CHUA_HO_TRO"     # R4 chưa có

    if router_fix:
        # Thứ tự: cấu trúc trước, phạm vi sau. Lý do trả về phải là lý do CẤU
        # TRÚC khi cả hai cùng đúng — đó mới là thứ R3/R4 phải mở, còn phạm vi
        # là hạn chế của binder.
        if DEM.search(q):
            return "R0", None, "DEM_CHUA_HO_TRO"
        if HAI_TANG_P0.search(q):
            return "R0", None, "HAI_TANG_CHUA_HO_TRO"
        if DIEU_KIEN_P0.search(q):
            return "R0", None, "DIEU_KIEN_CHUA_HO_TRO"
        if NHOM.search(q) and not TEN_CHI_TIEU_BINH_QUAN.search(q):
            return "R0", None, "NHOM_CHUA_HO_TRO"
        if len(yrs) > 1 and TRUNG_BINH.search(q):
            # KHÔNG áp dụng hard negative `TEN_CHI_TIEU_BINH_QUAN` ở đây, dù nó
            # đúng cho luật NHOM. Lý do đo được: qid 962 hỏi "tỷ số nợ phải trả
            # trên vốn chủ sở hữu TRUNG BÌNH … trong các năm 2016…2022" — chuỗi
            # "vốn chủ sở hữu trung bình" khớp hard negative một cách TÌNH CỜ,
            # trong khi "trung bình" ở đây thật sự là phép gộp nhiều kỳ. Khi
            # plan đã có ≥2 kỳ thì R2 (vốn chỉ lấy `yrs[-1]`) không biểu diễn
            # được câu hỏi dù "trung bình" mang nghĩa nào — nên R0 là đúng ở cả
            # hai cách đọc. Ngoại lệ chỉ còn ý nghĩa với MỘT kỳ.
            return "R0", None, "TRUNG_BINH_DA_KY_THUOC_R1"
        if len(ents) > 1:
            # Nhiều thực thể mà R2 chỉ lấy `ents[0]` = chọn công ty tuỳ tiện.
            return "R0", None, "NHIEU_ENTITY_CHUA_HO_TRO"
        if PHAM_VI_RIENG.search(q):
            return "R0", None, "PHAM_VI_RIENG_CHUA_HO_TRO"

    sp = tim_theo_cau_hoi(formulas, q)
    if sp is None:
        return "R0", None, "KHONG_KHOP_FORMULA"
    if not ents:
        return "R0", sp, "THIEU_ENTITY"
    if not yrs:
        return "R0", sp, "THIEU_YEAR"
    if len(yrs) > 1 and NHIEU_KY.search(q):
        # Formula một tầng trên nhiều kỳ = tăng trưởng của tỷ số ⇒ thuộc R1/R3.
        return "R0", sp, "NHIEU_KY_THUOC_R1"
    return "R2", sp, "OK"


def entity_nam(plan_q: dict) -> tuple[str, int]:
    """Chọn (entity, year) cho R2. Một entity, một kỳ — đúng phạm vi wave 1."""
    ents = list(plan_q.get("entities") or [])
    yrs = sorted(plan_q.get("years") or [])
    return ents[0], int(yrs[-1])
