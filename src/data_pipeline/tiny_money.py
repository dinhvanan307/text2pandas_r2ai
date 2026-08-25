"""RC-03 · Phân loại 2.836 `Q-OBS-TINY-MONEY` — theo bằng chứng, không theo cảm giác.

Đây là task data-correctness ưu tiên cao nhất của RC2. Trước khi viết một dòng
luật nào, bốn phép đo dưới đây đã chạy trên chính build bị từ chối
`b927c3e8f90aed74`. Chúng **lật ngược** giả thuyết ban đầu của bản audit.

    theo scale_exponent
        scale 0    1.639      scale 6      692
        (không có) 453        scale 9       44        scale 3        8

    sau khi ÁP SCALE
        >= 1.000 VND    740      <- KHÔNG phải số liệu sai
        <  1.000 VND  2.096

    theo nhãn cột (đã chuẩn hoá bỏ dấu)
        header là cột tham chiếu (Mã số · MS · TM · STT)     472
        giá trị là số hiệu thuyết minh dạng `5.1`             79
        header là cột giá trị thật (Năm nay · Năm trước…)  2.285

    theo vai trò cột đã gán
        value 2.750 · unknown 86

**Kết luận quan trọng nhất: 740/2.836 là lỗi của chính RULE, không phải của dữ
liệu.** `Q-OBS-TINY-MONEY` so `ABS(value) < 1000` trên **giá trị thô**, trong
khi bảng khai `Đơn vị tính: triệu đồng`. Một ô ghi `3` trong bảng triệu đồng là
**3.000.000 VND** — hoàn toàn hợp lệ. Đây là lần thứ ba cùng một lớp lỗi xuất
hiện trong dự án: đo sai đại lượng (thô thay vì đã chuẩn hoá). Hai lần trước là
`Q-OBS-IMPLAUSIBLE` và `n_implausible_magnitude` trong `arithmetic.py`.

Vì vậy remediation có **hai** phần, và phần một phải làm trước:

1. Sửa thước đo: `Q-OBS-TINY-MONEY` phải so **sau khi áp scale**.
2. Với phần còn lại, phân loại bằng luật GENERIC — không hard-code `doc_id`,
   `table_uid`, số dòng hay danh sách UID (RC-03 mục 5).

Ba tín hiệu generic được dùng, xếp theo độ mạnh của bằng chứng:

    S1  nhãn cột khớp từ vựng cột tham chiếu, có dung sai OCR
        `Másố` · `M8 số` · `Mã sơ` · `MS ›` · `TM ›` · `Mã Thuyết số minh`
        đều là "Mã số"/"Thuyết minh" bị OCR làm hỏng. Chuẩn hoá bỏ dấu rồi
        khớp mờ bắt được cả cụm, thay vì liệt kê từng biến thể.

    S2  hình dạng giá trị là SỐ HIỆU MỤC (`5.1`, `5.18`)
        Không có khoản mục tài chính nào mang giá trị `5.18` đồng. Đây là số
        hiệu thuyết minh bị dấu chấm làm cho trông như số thập phân.

    S3  cột toàn số ngắn TRONG KHI cột anh em cùng bảng có số dài
        Một cột mà mọi giá trị ≤ 3 chữ số, nằm cạnh cột có ≥ 6 chữ số, thì nó
        không phải cột tiền. Đây là tín hiệu cấp CỘT nên nó sửa được vai trò
        cột, không phải vá từng ô.

Ca không khớp tín hiệu nào thì **giữ nguyên provenance, `execution_ready = 0`,
và vào unresolved registry**. Đoán ở đây là đúng thứ mà DI-07 cấm.
"""

from __future__ import annotations

import re

from data_pipeline.text_normalize import normalize_token

__all__ = ["TINY_MONEY_VERSION", "CLASSES", "classify_tiny_money",
           "is_reference_header", "MIN_MONEY_VND"]

TINY_MONEY_VERSION = "1.0"

# Ngưỡng "quá nhỏ để là tiền" — áp cho giá trị ĐÃ CHUẨN HOÁ ra VND.
# 1.000 VND vì mệnh giá nhỏ nhất đang lưu hành là 200 VND và báo cáo tài chính
# không ghi khoản mục dưới mức nghìn.
MIN_MONEY_VND = 1000

CLASSES = (
    "metric_code_false_value",
    "note_reference_false_value",
    "ordinal_false_value",
    "legitimate_small_money",
    "legitimate_per_share_or_rate_value",
    "parse_or_column_role_unresolved",
)

# ── S1 · từ vựng cột tham chiếu, khớp trên chuỗi ĐÃ bỏ dấu và bỏ dấu câu ──
#
# Không liệt kê biến thể OCR. Sau `normalize_token`, `Másố` → `ma so`,
# `M8 số` → `m8 so`, `Mã sơ` → `ma so`, `TM ›` → `tm`. Ba mẫu dưới đây phủ hết
# mà không phải bảo trì một danh sách chính tả sai.
_H_METRIC_CODE = re.compile(r"\b(ma\s*so|ma\s*s\b|m\s*so|m\d\s*so|ms)\b")
_H_NOTE_REF = re.compile(r"\b(thuyet\s*minh|thuyet|tm|note)\b")
_H_ORDINAL = re.compile(r"\b(stt|so\s*tt|tt|no|order)\b")

# `5.1` · `5.18` · `12.3` — số hiệu mục, KHÔNG phải số thập phân.
# Chặn `5.123` trở lên: ba chữ số sau dấu chấm là quy ước phân cách nghìn.
_SECTION_NO = re.compile(r"^\d{1,2}\.\d{1,2}$")

# Chỉ tiêu mang giá trị nhỏ một cách CHÍNH ĐÁNG. Nhận diện qua nhãn dòng, vì
# đây là thuộc tính ngữ nghĩa của khoản mục chứ không phải của cột.
_PER_SHARE = re.compile(
    r"(lai\s*co\s*ban\s*tren\s*co\s*phieu|lai\s*suy\s*giam\s*tren\s*co\s*phieu"
    r"|tren\s*co\s*phieu|eps|menh\s*gia|ty\s*le|ty\s*gia|phan\s*tram"
    r"|so\s*luong|so\s*nam|thoi\s*gian\s*khau\s*hao)")


def is_reference_header(header_path_text: str | None) -> str | None:
    """Trả `metric_code` / `note_reference` / `ordinal` nếu nhãn cột là cột tham chiếu."""
    h = normalize_token(header_path_text or "")
    if not h:
        return None
    # Thứ tự có ý nghĩa: `Mã Thuyết số minh` (OCR trộn hai tiêu đề) khớp cả
    # hai mẫu. Ưu tiên `thuyet minh` vì cột kiểu đó mang số hiệu mục, còn cột
    # Mã số mang mã Thông tư 200 — hai loại nội dung khác nhau.
    if _H_NOTE_REF.search(h):
        return "note_reference"
    if _H_METRIC_CODE.search(h):
        return "metric_code"
    if _H_ORDINAL.search(h):
        return "ordinal"
    return None


def classify_tiny_money(
    *,
    value_decimal_text: str | None,
    value_source: str | None,
    scale_exponent: int | None,
    unit_kind: str | None,
    scale_source: str | None,
    header_path_text: str | None,
    row_label: str | None,
    col_max_digits: int | None = None,
    peer_max_digits: int | None = None,
) -> tuple[str, str]:
    """Phân loại MỘT observation. Trả `(class, lý do)`.

    `col_max_digits` / `peer_max_digits` là tín hiệu S3 ở cấp cột, gọi tầng
    trên tính sẵn một lần cho cả bảng thay vì truy vấn lại cho từng ô.
    """
    raw = (value_source or "").strip()
    lbl = normalize_token(row_label or "")

    # ── S2 trước tiên: hình dạng số hiệu mục là bằng chứng mạnh nhất, vì
    # không giá trị tiền hợp lệ nào có hình dạng đó.
    if _SECTION_NO.match(raw):
        return ("note_reference_false_value",
                f"giá trị {raw!r} là số hiệu mục thuyết minh, không phải tiền")

    # ── Sửa thước đo TRƯỚC khi kết tội dữ liệu.
    # 740/2.836 ca rơi vào nhánh này: bảng khai `triệu đồng`, ô ghi `3`, và
    # rule cũ so `3 < 1000` trên giá trị THÔ. Đó là lỗi của thước, không phải
    # của ô. Không sửa chỗ này thì mọi phân loại phía sau đều nhiễm sai số.
    try:
        vnd = abs(float(value_decimal_text or 0)) * (10 ** int(scale_exponent or 0))
    except (TypeError, ValueError):
        vnd = 0.0
    if vnd >= MIN_MONEY_VND:
        return ("legitimate_small_money",
                f"{value_decimal_text} × 10^{scale_exponent or 0} = {vnd:,.0f} VND"
                " — đạt ngưỡng, rule cũ đo trên giá trị THÔ nên báo nhầm")

    # ── S1 · nhãn cột là cột tham chiếu.
    kind = is_reference_header(header_path_text)
    if kind == "note_reference":
        return ("note_reference_false_value",
                f"nhãn cột {header_path_text!r} là cột Thuyết minh")
    if kind == "metric_code":
        return ("metric_code_false_value",
                f"nhãn cột {header_path_text!r} là cột Mã số")
    if kind == "ordinal":
        return ("ordinal_false_value",
                f"nhãn cột {header_path_text!r} là cột số thứ tự")

    # ── Chỉ tiêu chính đáng nhỏ, nhận qua nhãn DÒNG.
    if _PER_SHARE.search(lbl):
        return ("legitimate_per_share_or_rate_value",
                "nhãn chỉ tiêu là đại lượng trên mỗi cổ phiếu / tỷ lệ / số lượng")

    # ── S3 · cột toàn số ngắn cạnh cột có số dài.
    if (col_max_digits is not None and peer_max_digits is not None
            and col_max_digits <= 3 and peer_max_digits >= 6):
        return ("metric_code_false_value",
                f"cột chỉ có số ≤{col_max_digits} chữ số trong khi cột cùng bảng"
                f" đạt {peer_max_digits} — không phải cột tiền")

    # ── Không đủ bằng chứng. Giữ provenance, chặn khỏi execution_ready.
    # Đây KHÔNG phải thất bại của bộ phân loại; đây là điều DI-07 yêu cầu.
    return ("parse_or_column_role_unresolved",
            "không có tín hiệu cột/nhãn/độ lớn nào đủ mạnh — giữ nguyên,"
            " chặn khỏi execution_ready, đưa vào unresolved registry")


# Ba lớp dưới đây KHÔNG được phép còn tồn tại dưới dạng observation sau RC2.
FALSE_VALUE_CLASSES = frozenset({
    "metric_code_false_value",
    "note_reference_false_value",
    "ordinal_false_value",
})

# Lớp này giữ observation nhưng BẮT BUỘC `execution_ready = 0`.
UNRESOLVED_CLASSES = frozenset({"parse_or_column_role_unresolved"})
