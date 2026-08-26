"""Chọn CHỦ THỂ trong câu hỏi nhắc nhiều công ty.

Đo trên 1.012 câu: 733 câu nhắc đúng một công ty, **273 câu nhắc từ hai trở
lên**. 273 câu đó không phải một bài toán mà là ba:

  screen   "Xét nhóm cổ phiếu CEO, HPX, KBC, SNZ, VIC, VPI và VRE trong 2022…"
           → nhiều mã THẬT, pipeline phải fan-out, KHÔNG được khử xuống một
  compare  "Chênh lệch … giữa công ty mẹ X và Y"
           → hai chủ thể, cần cả hai
  related  "Vay dài hạn VỚI Công ty CP Hoàng Anh Gia Lai CỦA công ty mẹ HAGL Agrico"
           → một chủ thể, một bên liên quan; chỉ chủ thể mới là chủ sở hữu báo cáo

Chỉ nhóm `related` mới cần chọn một. Gộp cả ba rồi ép về một mã là cách làm
hỏng 152 câu screen/compare để cứu vài chục câu related.

Tín hiệu vị trí: trong tiếng Việt tài chính, chủ sở hữu báo cáo đứng sau `của`
(`… của công ty mẹ X`, `… của X`). Bên liên quan đứng sau `với`, `cho`, `tại`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["QuestionMode", "classify", "pick_subject"]


class QuestionMode:
    SINGLE = "single"
    SCREEN = "screen"
    COMPARE = "compare"
    RELATED = "related"
    NONE = "none"
    SCREEN_OPEN = "screen_open"


# Dấu hiệu câu SÀNG LỌC · regex, không phải chuỗi con.
#
# Bản đầu dùng một danh sách chuỗi con hẹp và bỏ sót 81/1.012 câu — chúng rơi
# vào `related`, `pick_subject` không kết luận được, `targets` rỗng, và S1 trả
# về KHÔNG ứng viên nào. Một câu không có ứng viên là một câu chắc chắn 0 điểm,
# nên đây là lớp lỗi đắt nhất của cả tầng.
#
# Các mẫu dưới đây rút từ chính 87 câu rỗng đó, không phải từ trí tưởng tượng.
_SCREEN_RE = __import__("re").compile("|".join((
    r"trong nhom", r"nhom co phieu", r"nhom ma", r"xet nhom", r"xet cac",
    r"trong danh sach",
    # "trong 8 mã cổ phiếu" · "trong bốn mã cổ phiếu"
    r"ma co phieu",
    # "trong các công ty" · "đối với các doanh nghiệp" · "các công ty có"
    r"cac (cong ty|doanh nghiep)",
    # "trong số" · "trong 3 doanh nghiệp"
    r"trong so\b",
    r"trong (\d+|hai|ba|bon|nam|sau|bay|tam|chin|muoi) (cong ty|doanh nghiep|ma)",
    # "thuộc ngành X" · "doanh nghiệp ngành Y"
    r"(thuoc|doanh nghiep|cong ty) nganh",
    # câu hỏi chọn-một-trong-nhiều
    r"(cong ty|doanh nghiep|ma) nao\b", r"bao nhieu (doanh nghiep|cong ty)",
    # "doanh nghiệp có X cao nhất" — `cong ty co` phải LOẠI "công ty cổ phần"
    r"doanh nghiep co\b", r"cong ty co (?!phan)",
)))
_COMPARE = ("giua", "so voi", "chenh lech giua", "hieu so", "cao hon", "thap hon")
_OWNER = ("cua",)
_RELATED = ("voi", "cho", "tai", "den", "tu")


def _plain(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    d = d.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", d)).strip()


@dataclass(frozen=True, slots=True)
class Placed:
    ticker: str
    start: int
    alias_len: int


def _place(query: str, names_of: dict[str, list[str]],
           tickers: frozenset[str]) -> list[Placed]:
    """Vị trí xuất hiện DÀI NHẤT của mỗi mã trong câu, trên văn bản đã bỏ dấu."""
    text = _plain(query)
    out = []
    for t in tickers:
        best = None
        for n in names_of.get(t, []):
            a = _plain(n)
            i = text.find(a)
            if i >= 0 and (best is None or len(a) > best.alias_len):
                best = Placed(t, i, len(a))
        if best is None:                      # khớp qua MÃ chứ không qua tên
            m = re.search(rf"(?<![a-z0-9]){t.lower()}(?![a-z0-9])", text)
            if m:
                best = Placed(t, m.start(), len(t))
        if best:
            out.append(best)
    return sorted(out, key=lambda p: p.start)


def classify(query: str, n_tickers: int) -> str:
    if n_tickers == 0:
        # Sàng lọc mở: "doanh nghiệp có biên lợi nhuận giảm mạnh nhất…" —
        # không nêu mã nào, vũ trụ là toàn bộ 100 công ty. Đây KHÔNG phải lỗi
        # phân giải; nó là một loại câu cần đường đi riêng ở S2, và gộp nó vào
        # `none` sẽ làm ta đi sửa nhầm bộ phân giải thực thể.
        import re as _re
        if _SCREEN_RE.search(_plain(query)):
            return QuestionMode.SCREEN_OPEN
        return QuestionMode.NONE
    if n_tickers == 1:
        return QuestionMode.SINGLE
    p = _plain(query)
    if _SCREEN_RE.search(p):
        return QuestionMode.SCREEN
    if any(k in p for k in _COMPARE):
        return QuestionMode.COMPARE
    return QuestionMode.RELATED


def pick_subject(query: str, names_of: dict[str, list[str]],
                 tickers: frozenset[str]) -> str | None:
    """Mã đứng ngay sau `của` gần nhất. `None` khi không kết luận được.

    KHÔNG đoán: không có `của` đứng trước mã nào thì trả `None` và để tầng trên
    đi nhánh nhiều-thực-thể. Chọn bừa chủ thể là hỏng từ gốc mà mọi tầng sau
    vẫn chạy trơn và cho ra một con số rất thuyết phục.
    """
    placed = _place(query, names_of, tickers)
    if not placed:
        return None
    if len(placed) == 1:
        return placed[0].ticker
    text = _plain(query)
    owners = [m.end() for w in _OWNER
              for m in re.finditer(rf"(?<![a-z]){w}(?![a-z])", text)]
    if not owners:
        return None
    # Mã nào có một `của` đứng ngay trước (trong 40 ký tự) thì là chủ thể.
    ung_vien = [p for p in placed
                if any(0 <= p.start - o <= 40 for o in owners)]
    if len(ung_vien) == 1:
        return ung_vien[0].ticker
    return None
