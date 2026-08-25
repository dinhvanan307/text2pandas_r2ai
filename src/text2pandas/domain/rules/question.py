"""Phân tích câu hỏi tiếng Việt -> các slot cần cho truy hồi.

Đo trên 1.012 câu hỏi thật:
  99,9% có năm · 93,2% có mã CK viết hoa · 36,0% nói "công ty mẹ"
   1,4% nói "hợp nhất" · 60,6% hỏi tỷ đồng · 22,2% hỏi triệu đồng
  35,2% nhắc từ hai năm trở lên

Hệ quả thiết kế: `basis` KHÔNG được mặc định. "công ty mẹ" -> separate là tín
hiệu mạnh và phổ biến; thiếu tín hiệu thì để None và tầng truy hồi xét cả hai.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["QuestionSlots", "CompanyIndex", "parse_question"]

_YEAR = re.compile(r"\b(20[0-2]\d)\b")
_UPPER_TOKEN = re.compile(r"\b([A-Z][A-Z0-9]{2,3})\b")

# Từ viết hoa 3–4 ký tự nhưng KHÔNG phải mã chứng khoán.
_NOT_TICKER = {
    "CTCP", "TMCP", "VND", "VNĐ", "USD", "EUR", "JPY", "ROE", "ROA", "EPS",
    "GDP", "CIR", "NIM", "CAR", "HOSE", "HNX", "UPCO", "BCTC", "TNHH", "MTV",
    "TSCĐ", "VCSH", "LNST", "LNTT", "EBIT", "CAGR", "NHNN", "TCTD", "II",
}

_UNIT_PATTERNS: tuple[tuple[str, int], ...] = (
    ("nghìn tỷ", 12),
    ("nghìn tỉ", 12),
    ("tỷ đồng", 9),
    ("tỉ đồng", 9),
    ("triệu đồng", 6),
    ("nghìn đồng", 3),
    ("ngàn đồng", 3),
)


def _fold(s: str) -> str:
    """Bỏ dấu + hạ chữ thường, để khớp tên công ty bất kể cách gõ dấu."""
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]+", " ", s.replace("đ", "d"))


@dataclass(slots=True)
class QuestionSlots:
    qid: int
    text: str
    tickers: list[str] = field(default_factory=list)
    years: list[int] = field(default_factory=list)
    basis: str | None = None  # 'separate' | 'consolidated' | None
    unit_exponent: int | None = None  # 9 = tỷ, 6 = triệu ...
    wants_percent: bool = False
    ticker_source: str = "none"  # 'literal' | 'company_name' | 'none'

    @property
    def resolved(self) -> bool:
        return bool(self.tickers and self.years)


class CompanyIndex:
    """Ánh xạ tên công ty -> mã CK, dựng từ `code_stock.csv` của chính BTC.

    Đây là dữ liệu **trong bản phát hành của BTC**, không phải nguồn ngoài.
    """

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.by_ticker = {t: n for t, n in rows}
        self._folded = [(t, _fold(n)) for t, n in rows]
        # Khoá phụ: bỏ tiền tố pháp lý để khớp phần lõi của tên.
        self._core = [
            (t, re.sub(r"^(ctcp|cong ty co phan|ngan hang tmcp|tap doan)\s+", "", f))
            for t, f in self._folded
        ]

    @classmethod
    def from_csv(cls, path: Path) -> "CompanyIndex":
        rows: list[tuple[str, str]] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("Mã CK") or "").strip()
                name = (row.get("Tên công ty") or "").strip()
                if code:
                    rows.append((code, name))
        return cls(rows)

    def lookup(self, question: str) -> list[str]:
        """Tìm mã CK từ tên công ty nêu trong câu hỏi. Ưu tiên khớp dài nhất."""
        fq = _fold(question)
        hits: list[tuple[int, str]] = []
        for ticker, folded in self._folded:
            if folded and folded in fq:
                hits.append((len(folded), ticker))
        for ticker, core in self._core:
            if len(core) >= 8 and core in fq:
                hits.append((len(core), ticker))
        if not hits:
            return []
        hits.sort(reverse=True)
        seen: list[str] = []
        for _, t in hits:
            if t not in seen:
                seen.append(t)
        return seen


def parse_question(
    qid: int, text: str, companies: CompanyIndex, known_tickers: set[str]
) -> QuestionSlots:
    slots = QuestionSlots(qid=qid, text=text)

    slots.years = sorted({int(y) for y in _YEAR.findall(text)})

    literal = [
        t
        for t in dict.fromkeys(_UPPER_TOKEN.findall(text))
        if t not in _NOT_TICKER and t in known_tickers
    ]
    if literal:
        slots.tickers = literal
        slots.ticker_source = "literal"
    else:
        found = [t for t in companies.lookup(text) if t in known_tickers]
        if found:
            slots.tickers = found
            slots.ticker_source = "company_name"

    low = text.lower()
    if "công ty mẹ" in low or "riêng lẻ" in low or "báo cáo riêng" in low:
        slots.basis = "separate"
    elif "hợp nhất" in low:
        slots.basis = "consolidated"

    for pat, exp in _UNIT_PATTERNS:
        if pat in low:
            slots.unit_exponent = exp
            break
    slots.wants_percent = "%" in text or "phần trăm" in low or "tỷ lệ" in low

    return slots
