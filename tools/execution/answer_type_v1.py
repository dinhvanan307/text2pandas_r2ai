#!/usr/bin/env python3
"""Hợp đồng KIỂU ĐÁP ÁN — suy từ câu hỏi, kiểm trên đáp án.

VẤN ĐỀ ĐO ĐƯỢC (reports/type_audit_v1.json)
Trên bài nộp hiện hành (C0, arithmetic TẮT), 279/1012 câu (27,6%) trả về đáp án
**sai kiểu đại lượng**: hỏi "năm nào" trả về hàng tỷ đồng, hỏi "bao nhiêu lần"
trả về 3.777.947.515.921, hỏi "bao nhiêu công ty" trả về 700.886.434.

Sai kiểu ⇒ chắc chắn sai giá trị. Đây là điều kiện CẦN, kiểm được mà không cần
gold, và suy được từ chính văn bản câu hỏi.

⚠️ ĐIỀU HỢP ĐỒNG NÀY **KHÔNG** LÀM
`Execution Accuracy = (code chạy được VÀ kết quả đúng) / tổng query`
(COMPETITION_SPEC §4.3). Nghĩa là **abstain và sai đều được 0 điểm**. Một bộ
kiểm kiểu chỉ biết nói "sai rồi" rồi bỏ trống thì **không thêm một điểm nào**.

Giá trị thật của nó nằm ở ba chỗ khác:

  1. TRỌNG TÀI giữa các nhánh đã có. argmax_year: C0 trả tiền (0/29 đúng kiểu),
     C3 trả năm (23/29 đúng kiểu). Hợp đồng cho phép chọn nhánh khớp kiểu một
     cách có nguyên tắc, thay vì chọn theo cảm tính hoặc theo điểm leaderboard.
  2. ĐỊNH TUYẾN. Kiểu kỳ vọng cho biết câu hỏi thuộc lớp nào — `max_min`,
     `ratio`, `count` hiện KHÔNG có emitter, và hợp đồng chỉ đúng chỗ thiếu.
  3. CHỐT HỒI QUY. Một thay đổi làm tăng số câu sai kiểu là hồi quy, phát hiện
     được ngay mà không cần nhãn.

NGUYÊN TẮC THIẾT KẾ: THÀ IM LẶNG CÒN HƠN ĐOÁN
`kind=UNKNOWN` là câu trả lời hợp lệ và phổ biến. Một hợp đồng đoán bừa sẽ tạo
ra hồi quy im lặng ở tầng trọng tài — nguy hiểm hơn là không có hợp đồng.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ── mẫu nhận kiểu, xếp theo ĐỘ ĐẶC HIỆU GIẢM DẦN ───────────────────────────
# Thứ tự quan trọng: "bao nhiêu phần trăm" phải khớp trước "bao nhiêu ... đồng"
# vì một câu có thể chứa cả hai cụm.

NAM = re.compile(r"năm\s+nào|vào\s+năm\s+nào|thời\s*điểm\s+nào", re.I)
DEM = re.compile(
    r"bao\s*nhiêu\s+(công\s*ty|doanh\s*nghiệp|mã|cổ\s*phiếu|khoản\s*mục|"
    r"chỉ\s*tiêu|lần\s+xuất\s*hiện)|số\s*lượng\s+(công\s*ty|doanh\s*nghiệp|mã)", re.I)
LAN = re.compile(r"bao\s*nhiêu\s*lần|(hệ\s*số|tỷ\s*số|tỉ\s*số)[^?]{0,40}bao\s*nhiêu|"
                 r"\bD/E\b|\bROE\b|\bROA\b|\bP/E\b", re.I)
PCT = re.compile(r"bao\s*nhiêu\s*(phần\s*trăm|%)|"
                 r"(tỷ\s*lệ|tỉ\s*lệ|tỷ\s*trọng|tỉ\s*trọng)[^?]{0,40}bao\s*nhiêu|"
                 r"(tăng|giảm)[^?]{0,20}bao\s*nhiêu\s*%", re.I)

# Đơn vị tiền — bắt cụm ĐỨNG SAU "bao nhiêu" để không nhầm với đơn vị của cột.
TIEN = re.compile(r"bao\s*nhiêu\s*(nghìn\s*tỷ|tỷ|triệu|nghìn|trăm)?\s*(đồng|vnd)", re.I)

DON_VI_TIEN = (("nghìn tỷ", 1e12), ("tỷ", 1e9), ("triệu", 1e6),
               ("nghìn", 1e3), ("trăm", 1e2))


@dataclass(frozen=True)
class Contract:
    """Hợp đồng kiểu cho MỘT câu hỏi.

    kind        NAM · DEM · LAN · PCT · TIEN · UNKNOWN
    lo, hi      khoảng hợp lệ (bao gồm hai đầu); None = không ràng buộc
    phai_nguyen đáp án phải là số nguyên
    don_vi      hệ số đơn vị câu hỏi yêu cầu (chỉ với TIEN)
    cu          cụm văn bản đã kích hoạt — để truy được vì sao
    """
    kind: str
    lo: float | None = None
    hi: float | None = None
    phai_nguyen: bool = False
    don_vi: float | None = None
    cu: str | None = None

    @property
    def co_rang_buoc(self) -> bool:
        return self.kind != "UNKNOWN"


def suy_hop_dong(question: str) -> Contract:
    """Câu hỏi → hợp đồng. Không chắc thì trả UNKNOWN, KHÔNG đoán."""
    q = question or ""

    if (m := NAM.search(q)):
        # Năm tài chính trong corpus ViFinQA. Nới hai đầu để không bó cứng.
        return Contract("NAM", 1990, 2035, True, cu=m.group(0))

    if (m := DEM.search(q)):
        # Số công ty/mã trong một câu hỏi thực tế không vượt vài trăm.
        return Contract("DEM", 0, 10_000, True, cu=m.group(0))

    if (m := LAN.search(q)):
        # Hệ số tài chính. D/E, ROE, khả năng thanh toán… hiếm khi quá 4 chữ số.
        # Ngưỡng 10.000 cố tình RỘNG: mục tiêu là bắt ca sai 9 chữ số, không
        # phải phân xử một hệ số bất thường.
        return Contract("LAN", -10_000, 10_000, cu=m.group(0))

    if (m := PCT.search(q)):
        # Quy ước dự án: "15 nghĩa là 15%" (formula_registry_v1). Cho phép âm
        # (tăng trưởng âm) và cho phép > 100 (tăng gấp nhiều lần).
        return Contract("PCT", -10_000, 10_000, cu=m.group(0))

    if (m := TIEN.search(q)):
        don_vi = 1.0
        cum = (m.group(1) or "").lower().strip()
        for ten, he in DON_VI_TIEN:
            if ten in cum:
                don_vi = he
                break
        # KHÔNG đặt lo/hi cho TIEN. Bản nháp đầu dùng |v| >= 1000 và luật ấy
        # SAI: "bao nhiêu tỷ đồng" mà đáp án 5,2 (tỷ) là hoàn toàn hợp lệ.
        # Ràng buộc duy nhất kiểm được ở đây là ĐƠN VỊ, không phải độ lớn.
        return Contract("TIEN", None, None, False, don_vi, m.group(0))

    return Contract("UNKNOWN")


def kiem(hd: Contract, answer) -> dict:
    """Kiểm một đáp án theo hợp đồng. → {ok, ly_do, gia_tri}"""
    if not hd.co_rang_buoc:
        return {"ok": None, "ly_do": "KHONG_CO_RANG_BUOC", "gia_tri": None}
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        return {"ok": False, "ly_do": "TRONG", "gia_tri": None}
    try:
        v = float(str(answer).replace(",", "").strip())
    except (TypeError, ValueError):
        return {"ok": False, "ly_do": "KHONG_PARSE_DUOC_SO", "gia_tri": None}
    if v != v or v in (float("inf"), float("-inf")):
        return {"ok": False, "ly_do": "NAN_HOAC_INF", "gia_tri": str(v)}
    if hd.lo is not None and v < hd.lo:
        return {"ok": False, "ly_do": f"DUOI_NGUONG_{hd.kind}", "gia_tri": v}
    if hd.hi is not None and v > hd.hi:
        return {"ok": False, "ly_do": f"VUOT_NGUONG_{hd.kind}", "gia_tri": v}
    if hd.phai_nguyen and not float(v).is_integer():
        return {"ok": False, "ly_do": f"KHONG_NGUYEN_{hd.kind}", "gia_tri": v}
    return {"ok": True, "ly_do": None, "gia_tri": v}


def trong_tai(hd: Contract, ung_vien: list[tuple[str, object]]) -> dict:
    """Trọng tài giữa nhiều nhánh — ứng dụng SINH ĐIỂM của hợp đồng.

    `ung_vien` là [(tên_nhánh, đáp_án), ...] xếp theo ưu tiên mặc định.
    Luật, khai trước:

        1. Không có ràng buộc kiểu  → giữ nhánh ưu tiên đầu. Hợp đồng im lặng.
        2. Đúng một nhánh khớp kiểu → chọn nhánh đó.
        3. Nhiều nhánh khớp         → giữ nhánh ưu tiên đầu trong số khớp.
        4. Không nhánh nào khớp     → giữ nhánh ưu tiên đầu, gắn cờ.

    Luật 4 là chỗ dễ sai nhất nên nói rõ: KHÔNG bỏ trống. Abstain và sai đều 0
    điểm, nên bỏ trống một đáp án sai kiểu chỉ mất đi cơ hội nó tình cờ đúng,
    mà không được gì. Chỉ gắn cờ để đếm.
    """
    if not ung_vien:
        return {"chon": None, "nhanh": None, "ly_do": "KHONG_CO_UNG_VIEN"}
    if not hd.co_rang_buoc:
        return {"chon": ung_vien[0][1], "nhanh": ung_vien[0][0],
                "ly_do": "HOP_DONG_IM_LANG"}
    khop = [(t, a) for t, a in ung_vien if kiem(hd, a)["ok"]]
    if len(khop) == 1:
        return {"chon": khop[0][1], "nhanh": khop[0][0], "ly_do": "DUY_NHAT_KHOP_KIEU"}
    if khop:
        return {"chon": khop[0][1], "nhanh": khop[0][0], "ly_do": "NHIEU_NHANH_KHOP"}
    return {"chon": ung_vien[0][1], "nhanh": ung_vien[0][0],
            "ly_do": "KHONG_NHANH_NAO_KHOP", "co_canh_bao": True}
