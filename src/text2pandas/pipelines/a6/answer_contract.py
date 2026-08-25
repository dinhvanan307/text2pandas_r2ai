"""B1 · Hợp đồng KIỂU giữa câu hỏi và fact.

Chẩn đoán dẫn tới module này, đo trên `submission_CARD.zip` (1.012 câu):

    260 câu hỏi "bao nhiêu %"
        197 trả về một SỐ TIỀN THÔ  (10³ – 10²⁹)
         34 trả về giá trị trong dải 1–100

    Silver có sẵn:  money 2.449.952 · percentage 129.021
                    share_count 57.037 · interest_rate 9.997 · days 969

Tầng trả lời **không đọc `value_kind`**. Nó chọn ô theo độ khớp từ khoá rồi
trả giá trị, bất kể ô đó là tiền, tỷ lệ hay số cổ phiếu. 129.021 ô
`percentage` nằm im trong khi 197 câu hỏi phần trăm nhận về số tiền.

Module này đảo thứ tự suy nghĩ: **biết trước cần loại số gì, rồi mới đi tìm.**
Đó là khác biệt giữa tìm kiếm mù và tìm kiếm có ràng buộc.

Nó KHÔNG tự trả lời câu hỏi và KHÔNG đụng vào truy hồi. Nó chỉ trả về một
`AnswerSpec` để tầng chọn fact lọc theo, và tầng quy đổi tính theo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from text2pandas.pipelines.a6.text_normalize import normalize_search_text

__all__ = ["CONTRACT_VERSION", "AnswerSpec", "classify_question",
           "convert_to_requested_unit", "is_plausible", "PLAUSIBLE_RANGE"]

CONTRACT_VERSION = "1.0"


@dataclass(slots=True)
class AnswerSpec:
    """Hợp đồng cho MỘT câu hỏi: đáp án phải mang kiểu gì, đơn vị gì."""

    value_kind: str                  # kiểu Silver mà fact phải mang
    unit_exponent: int = 0           # luỹ thừa 10 của ĐƠN VỊ ĐÁP ÁN
    unit_label: str = "đồng"
    arity: str = "scalar"            # scalar | ratio | aggregate
    evidence: str = ""               # luật nào khớp — để truy nguyên
    flags: list[str] = field(default_factory=list)

    @property
    def is_ratio(self) -> bool:
        return self.arity == "ratio"


# ── Dải hợp lý theo KIỂU · B6 ───────────────────────────────────────────────
#
# Ngoài dải KHÔNG có nghĩa là sai — nó có nghĩa là **ta không hiểu chuyện gì
# đã xảy ra**. Nhân chia thêm ở đó là đoán chồng lên đoán (DI-07).
PLAUSIBLE_RANGE: dict[str, tuple[float, float]] = {
    # Tỷ trọng có thể vượt 100% (tăng trưởng, đòn bẩy) nhưng không tới 10⁶.
    "percentage": (-100.0, 1_000.0),
    "interest_rate": (0.0, 100.0),
    "share_count": (1.0, 1e11),
    "days": (0.0, 36_500.0),
    "ratio": (-1e3, 1e3),
    # `money` phụ thuộc đơn vị yêu cầu nên tính động, xem `is_plausible`.
}

# Biên độ lớn của tiền SAU khi đã quy về đơn vị câu hỏi đòi. Neo theo VND:
# khoản mục nhỏ nhất đáng ghi ~10⁶ VND, lớn nhất trong corpus ~10¹⁵ VND.
_MONEY_VND_MIN = Decimal("1e5")
_MONEY_VND_MAX = Decimal("1e16")

# Dải "đọc được" của đáp án TRONG đơn vị mà câu hỏi dùng. Người ra đề chọn
# đơn vị sao cho đáp án gọn — `0,001` tới `1.000.000` phủ hết ca thực tế
# (1 triệu tỷ đồng đã vượt GDP Việt Nam nhiều lần).
_READABLE_MIN = Decimal("0.001")
_READABLE_MAX = Decimal("1e6")


# ── B1 · luật phân loại, xếp theo ĐỘ MẠNH bằng chứng ────────────────────────
#
# Thứ tự có ý nghĩa và không được sắp lại tuỳ tiện. `lãi suất ... %/năm` khớp
# cả luật lãi suất lẫn luật phần trăm; luật hẹp hơn phải thắng.
#
# Mẫu khớp trên chuỗi ĐÃ chuẩn hoá bỏ dấu (`normalize_search_text`), nên
# `phần trăm` → `phan tram`, `tỷ đồng` → `ty dong`. Nhờ đó một mẫu bắt được
# cả biến thể có dấu lẫn không dấu mà không phải liệt kê hai lần.
_RULES: tuple[tuple[str, str, int, str, str, str], ...] = (
    # (regex, value_kind, unit_exponent, unit_label, arity, mô tả)
    (r"bao nhieu\s+co\s*phieu|so\s*luong\s+co\s*phieu|so\s*co\s*phan",
     "share_count", 0, "cổ phiếu", "scalar", "hỏi số lượng cổ phiếu"),

    (r"lai\s*suat|%\s*/\s*nam|moi\s*nam.*%",
     "interest_rate", 0, "%", "scalar", "hỏi lãi suất"),

    (r"bao\s*nhieu\s*lan|he\s*so\s|he\s*so$|vong\s*quay",
     "money", 0, "lần", "ratio", "hỏi hệ số / số lần — tỷ số không thứ nguyên"),

    (r"ty\s*le|ty\s*trong|phan\s*tram|%|chiem\s*bao\s*nhieu|co\s*cau",
     "percentage", 0, "%", "ratio", "hỏi tỷ lệ / phần trăm"),

    (r"nghin\s*ty\s*dong", "money", 12, "nghìn tỷ đồng", "scalar", "đơn vị nghìn tỷ"),
    (r"ty\s*dong", "money", 9, "tỷ đồng", "scalar", "đơn vị tỷ"),
    (r"trieu\s*dong", "money", 6, "triệu đồng", "scalar", "đơn vị triệu"),
    (r"nghin\s*dong", "money", 3, "nghìn đồng", "scalar", "đơn vị nghìn"),
    (r"bao\s*nhieu\s*dong|\bdong\b", "money", 0, "đồng", "scalar", "đơn vị đồng"),
)
_COMPILED = tuple((re.compile(p), *rest) for p, *rest in _RULES)

# Câu ghép: hỏi cả giá trị lẫn tỷ lệ. Đo được 8 câu chứa cả `nghìn tỷ` và `%`.
_COMPOUND = re.compile(r"(nghin\s*ty|ty\s*dong|trieu\s*dong).*(phan\s*tram|%)"
                       r"|(phan\s*tram|%).*(nghin\s*ty|ty\s*dong|trieu\s*dong)")


# ── Luật ưu tiên 0 · MỆNH ĐỀ HỎI TRỰC TIẾP ─────────────────────────────────
#
# Chạy trên 1.012 câu thật bắt được hai ca sai của bộ luật từ khoá:
#
#   #140 "Giá trị tài sản tài chính chịu LÃI SUẤT cố định của HPG … là bao
#         nhiêu TRIỆU ĐỒNG?"          → phân loại nhầm `interest_rate`
#   #755 "… mức chênh nhạy cảm với LÃI SUẤT … là bao nhiêu TRIỆU ĐỒNG?"
#                                     → phân loại nhầm `interest_rate`
#
# Nguyên nhân: `lãi suất` ở đây là **bổ ngữ mô tả chỉ tiêu**, không phải đại
# lượng được hỏi. Quét từ khoá trên toàn câu không phân biệt được hai vai trò
# đó.
#
# Tiếng Việt khai đơn vị đáp án ngay sau cụm hỏi: `là bao nhiêu <đơn vị>`.
# Đó là bằng chứng MẠNH NHẤT về kiểu, mạnh hơn mọi từ khoá rải rác trong câu,
# nên nó chạy trước.
_DIRECT_ASK = re.compile(
    r"bao\s*nhieu\s*(nghin\s*ty\s*dong|ty\s*dong|trieu\s*dong|nghin\s*dong"
    r"|phan\s*tram|%|lan|co\s*phieu|dong)\b")

_DIRECT_MAP: dict[str, tuple[str, int, str, str]] = {
    "nghin ty dong": ("money", 12, "nghìn tỷ đồng", "scalar"),
    "ty dong": ("money", 9, "tỷ đồng", "scalar"),
    "trieu dong": ("money", 6, "triệu đồng", "scalar"),
    "nghin dong": ("money", 3, "nghìn đồng", "scalar"),
    "dong": ("money", 0, "đồng", "scalar"),
    "phan tram": ("percentage", 0, "%", "ratio"),
    "%": ("percentage", 0, "%", "ratio"),
    "lan": ("money", 0, "lần", "ratio"),
    "co phieu": ("share_count", 0, "cổ phiếu", "scalar"),
}


def classify_question(question: str) -> AnswerSpec:
    """Suy `AnswerSpec` từ câu hỏi. Không truy vấn gì, thuần văn bản."""
    q = normalize_search_text(question or "")
    if not q:
        return AnswerSpec("money", 0, "đồng", "scalar", "câu hỏi rỗng",
                          ["empty_question"])

    flags: list[str] = []

    # Ưu tiên 0 — lấy cụm hỏi CUỐI CÙNG. Câu ghép "… bao nhiêu tỷ đồng, chiếm
    # bao nhiêu %?" phải cho `%`, vì tiếng Việt đặt yêu cầu chính ở cuối.
    direct = _DIRECT_ASK.findall(q)
    if direct:
        key = re.sub(r"\s+", " ", direct[-1]).strip()
        hit = _DIRECT_MAP.get(key)
        if hit:
            if len(set(direct)) > 1:
                flags.append("compound_question")
            kind, exp, label, arity = hit
            return AnswerSpec(kind, exp, label, arity,
                              f"cụm hỏi trực tiếp `bao nhiêu {key}`", flags)

    # Câu ghép: phân loại theo MỆNH ĐỀ CUỐI. Tiếng Việt đặt yêu cầu chính ở
    # cuối câu — "… là bao nhiêu tỷ đồng, chiếm bao nhiêu %?" hỏi %.
    scope = q
    if _COMPOUND.search(q):
        flags.append("compound_question")
        parts = re.split(r"[,;]|\bva\b", q)
        scope = parts[-1] if parts else q

    for rx, kind, exp, label, arity, why in _COMPILED:
        if rx.search(scope) or (scope is not q and rx.search(q) and
                                not any(r.search(scope) for r, *_ in _COMPILED)):
            return AnswerSpec(kind, exp, label, arity, why, flags)

    # Không khai đơn vị — 94/1.012 câu. Mặc định `money` ở đơn vị đồng, nhưng
    # GẮN CỜ để tầng trên biết đây là suy đoán chứ không phải khai báo.
    flags.append("unit_unstated")
    return AnswerSpec("money", 0, "đồng", "scalar",
                      "không khai đơn vị — mặc định đồng", flags)


# ── B5 · quy đổi đơn vị · phép TÍNH, không phải suy đoán ────────────────────

def convert_to_requested_unit(
    value_decimal_text: str | None,
    scale_exponent: int | None,
    spec: AnswerSpec,
    *,
    scale_source: str | None = None,
) -> tuple[Decimal | None, str]:
    """Quy giá trị fact về đơn vị câu hỏi đòi. Trả `(giá trị, lý do)`.

    Silver ghi `scale_exponent` kèm `scale_source` cho biết bằng chứng đến từ
    đâu, nên đây là phép nhân chia xác định — không phải đoán "con số này chắc
    là VND". Không có bằng chứng đơn vị thì TỪ CHỐI quy đổi.
    """
    if value_decimal_text is None:
        return None, "không có giá trị"
    if scale_source == "none":
        # Quy đổi khi không biết đơn vị gốc là bịa ra một con số.
        return None, "không có bằng chứng đơn vị — từ chối quy đổi"
    try:
        raw = Decimal(str(value_decimal_text))
    except (InvalidOperation, ValueError):
        return None, f"giá trị không parse được: {value_decimal_text!r}"

    if spec.value_kind != "money":
        # `percentage`, `interest_rate`, `share_count` không có bậc đơn vị —
        # nhân scale vào là làm hỏng một con số đang đúng.
        return raw, f"kiểu {spec.value_kind} — giữ nguyên, không áp scale"

    vnd = raw * (Decimal(10) ** int(scale_exponent or 0))
    out = vnd / (Decimal(10) ** spec.unit_exponent)
    return out, (f"{raw} × 10^{scale_exponent or 0} = {vnd} VND"
                 f" → ÷ 10^{spec.unit_exponent} = {out} {spec.unit_label}")


# ── B6 · kiểm dải hợp lý ────────────────────────────────────────────────────

def is_plausible(answer, spec: AnswerSpec) -> tuple[bool, str]:
    """Đáp án có nằm trong dải hợp lý của KIỂU nó không.

    Trả `False` KHÔNG có nghĩa "đáp án sai" — nghĩa là "ta không hiểu chuyện
    gì đã xảy ra". Người gọi gắn cờ, không tự sửa số.
    """
    if answer is None:
        return False, "không có đáp án"
    try:
        v = Decimal(str(answer))
    except (InvalidOperation, ValueError):
        return False, f"không phải số: {answer!r}"

    kind = "ratio" if (spec.is_ratio and spec.value_kind == "money") \
        else spec.value_kind
    rng = PLAUSIBLE_RANGE.get(kind)
    if rng is not None:
        lo, hi = Decimal(str(rng[0])), Decimal(str(rng[1]))
        ok = lo <= v <= hi
        return ok, ("trong dải" if ok else
                    f"{v} ngoài dải hợp lý của `{kind}` [{lo}, {hi}]")

    # `money`: dải phụ thuộc đơn vị đáp án, nên quy ngược về VND rồi mới xét.
    if v == 0:
        return False, "đáp án 0 — không phân biệt được 'thật sự 0' với 'không tìm được'"
    vnd = abs(v) * (Decimal(10) ** spec.unit_exponent)
    if not (_MONEY_VND_MIN <= vnd <= _MONEY_VND_MAX):
        return False, (f"{v} {spec.unit_label} = {vnd:.3E} VND, ngoài dải"
                       f" [{_MONEY_VND_MIN:.0E}, {_MONEY_VND_MAX:.0E}]")

    # Tín hiệu thứ hai, yếu hơn nhưng bắt được lớp mà dải VND bỏ lọt.
    #
    # `0,0001675619` cho câu hỏi "bao nhiêu nghìn tỷ đồng" quy ra 167 triệu VND
    # — nằm gọn trong dải tiền hợp lệ, nên kiểm độ lớn tuyệt đối không bắt
    # được. Nhưng **đơn vị người hỏi chọn chính là bằng chứng về độ lớn kỳ
    # vọng**: không ai hỏi "bao nhiêu nghìn tỷ" cho một khoản 167 triệu. Người
    # ta chọn đơn vị sao cho đáp án ĐỌC ĐƯỢC.
    #
    # Đây là lớp 118 câu `|đáp án| < 1` của gói CARD.
    if spec.unit_exponent > 0 and not (_READABLE_MIN <= abs(v) <= _READABLE_MAX):
        return False, (f"{v} quá {'nhỏ' if abs(v) < _READABLE_MIN else 'lớn'}"
                       f" so với đơn vị `{spec.unit_label}` mà câu hỏi dùng —"
                       f" nghi sai chiều quy đổi (dải đọc được"
                       f" [{_READABLE_MIN}, {_READABLE_MAX:.0E}])")
    return True, "trong dải"
