"""S0 · trích ý định từ câu hỏi.

Phần THỰC THỂ và SCOPE chép ngữ nghĩa từ `parse_metadata_intent` của BTC — họ
chấm, nên ta phải phân giải giống họ. Phần NĂM là bổ sung của ta: baseline BTC
cố ý chưa lọc năm ("Year handling intentionally stays out of this module until
it is implemented together with query decomposition"), trong khi Silver có
`doc_year` ở tầng bảng và `period_end` ở tầng ô.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from text2pandas.pipelines.retrieval.normalize import (
    ascii_compact,
    ascii_words,
    company_word_aliases,
    phrase_mentioned,
    ticker_mentioned,
)
from text2pandas.pipelines.retrieval.subject import QuestionMode, classify, pick_subject

__all__ = ["Intent", "parse_intent", "BASIS_OF_SCOPE", "SCOPE_DEFAULT", "QuestionMode"]

# Dấu hiệu scope · nguyên văn của BTC, so trên chuỗi đã nén.
_PARENT_MARKERS = ("congtyme", "baocaorieng", "bctcrieng")
_CONSOLIDATED_MARKERS = ("hopnhat", "baocaohopnhat", "bctchn")

# BTC dùng nhãn tiếng Việt; `documents.basis` của Silver dùng nhãn tiếng Anh.
BASIS_OF_SCOPE = {"công ty mẹ": "separate", "hợp nhất": "consolidated"}

# Khi câu hỏi KHÔNG nói, BTC mặc định `hợp nhất`
# (`target_scope_for_policy`: `intent.explicit_scope or "hợp nhất"`).
# Corpus chia gần đôi — consolidated 957 · separate 954 — nên đây là một quyết
# định có hậu quả, không phải một mặc nhiên. Ta theo BTC vì BTC chấm.
SCOPE_DEFAULT = "hợp nhất"

_YEAR_RE = re.compile(r"(?<!\d)(20[0-2]\d)(?!\d)")


@dataclass(frozen=True, slots=True)
class Intent:
    tickers: frozenset[str]
    explicit_scope: str | None          # "công ty mẹ" | "hợp nhất" | None
    years: tuple[int, ...]
    resolved_by: str                    # ticker | company_name | ticker_shadowed | none
    mode: str = "none"                  # single | screen | compare | related | none
    subject: str | None = None          # mã CHỦ THỂ khi xác định được

    @property
    def basis(self) -> str | None:
        """`documents.basis` để lọc cứng. `None` nghĩa là KHÔNG lọc."""
        return BASIS_OF_SCOPE.get(self.explicit_scope or SCOPE_DEFAULT)

    @property
    def targets(self) -> tuple[str, ...]:
        """Tập mã mà S1 phải lọc theo.

        `screen`/`compare` trả về CẢ NHÓM — 165/1.012 câu là câu nhiều thực thể
        thật, ép chúng về một mã là làm hỏng chúng để cứu nhóm `related`.
        `related` trả về đúng chủ thể nếu xác định được, ngược lại rỗng.
        """
        if self.mode in (QuestionMode.SCREEN, QuestionMode.COMPARE):
            return tuple(sorted(self.tickers))
        if self.subject:
            return (self.subject,)
        # KHÔNG quyết được chủ thể thì trả CẢ TẬP, không trả rỗng.
        #
        # Bản đầu trả `()` với lý do "không đoán". Đó là áp nguyên tắc
        # fail-closed nhầm tầng: ở S1, một tập ứng viên RỘNG vẫn cho S2/S3 cơ
        # hội tìm ra bảng đúng, còn tập RỖNG là bảo đảm 0 điểm. Đo được: 38 câu
        # mất trắng vì luật cũ.
        #
        # Fail-closed thuộc về tầng TRẢ LỜI (S4/S5): ở đó, không phân giải được
        # thì từ chối. Ở tầng sinh ứng viên, recall là thứ phải giữ.
        return tuple(sorted(self.tickers))

    @property
    def is_resolved(self) -> bool:
        """Phân giải được về ĐÚNG MỘT thực thể.

        Không đúng một thì tầng S1 phải đi nhánh không-lọc-ticker và hạ tin cậy
        cả câu. Đoán bừa một mã là hỏng từ gốc mà mọi tầng sau vẫn chạy trơn và
        cho ra một con số rất thuyết phục.
        """
        return len(self.tickers) == 1


def parse_intent(query: str, companies: dict[str, str | list[str]],
                 year_range: tuple[int, int] = (2015, 2025)) -> Intent:
    """`companies`: {ticker: tên} hoặc {ticker: [tên, biến thể...]}.

    Dạng một-tên là hành vi nguyên bản của BTC. Dạng nhiều-tên là mở rộng của
    ta; khi danh sách chỉ có một phần tử, hai dạng cho kết quả giống hệt nhau.

    Bản đầu của hàm gọi này nhét biến thể vào dict dưới khoá `"HPG#0"`, khiến
    `ticker_mentioned` không bao giờ khớp và tỷ lệ phân giải tụt từ 73,0%
    xuống 49,7%. Mã khoá của dict phải LUÔN là mã chứng khoán thật.
    """
    compact = ascii_compact(query)
    words = ascii_words(query)
    names_of = {t: ([n] if isinstance(n, str) else list(n))
                for t, n in companies.items()}

    # Giữ biên từ để alias ngắn ``an binh`` không khớp vào ``tan binh`` hoặc
    # ``lan binh quan`` sau bước bỏ dấu.
    matched_aliases = {
        ticker: {
            alias
            for name in names
            for alias in company_word_aliases(name)
            if phrase_mentioned(words, alias)
        }
        for ticker, names in names_of.items()
    }
    matched_aliases = {ticker: values for ticker, values in matched_aliases.items() if values}
    # Tên LỒNG NHAU · khớp dài nhất thắng.
    #
    # "Công ty CP Nông nghiệp Quốc tế Hoàng Anh Gia Lai" (HNG) chứa trọn
    # "Hoàng Anh Gia Lai" (HAG), nên luật gốc trả về CẢ HAI mã và câu hỏi mất
    # khả năng phân giải. Đo trên 1.012 câu: đây là một phần của 273 câu bị
    # nhận nhiều hơn một công ty.
    #
    # Chỉ loại khi alias của A là chuỗi con THỰC SỰ của alias B đã khớp — hai
    # công ty cùng được nhắc một cách độc lập thì cả hai đều giữ, vì câu hỏi
    # sàng lọc nhiều mã là loại câu có thật ("Xét nhóm cổ phiếu CEO, HPX, …").
    def _bi_bao(t: str) -> bool:
        mine = matched_aliases[t]
        theirs = {
            alias
            for u in matched_aliases
            if u != t
            for alias in matched_aliases[u]
        }
        # Chỉ shadow một ticker khi MỌI alias đã khớp của nó đều nằm trong
        # alias dài hơn của ticker khác. Nếu còn một tên độc lập (ví dụ full
        # legal name của GAS), short brand ``khivietnam`` trùng trong tên POW
        # không được phép xoá mất chủ sở hữu báo cáo.
        return bool(mine) and all(
            any(
                mine_alias != other and phrase_mentioned(other, mine_alias)
                for other in theirs
            )
            for mine_alias in mine
        )

    name_matches = {t for t in matched_aliases if not _bi_bao(t)}
    ticker_matches = {t for t in companies if ticker_mentioned(query, t)}

    # Mã nằm LỌT trong tên một công ty đã khớp thì không phải một lần nhắc mã
    # tường minh. Thiếu luật này, "Ngân hàng TMCP Á Châu" kéo theo mọi mã ba
    # chữ cái là chuỗi con của tên đó.
    shadowed = {t for t in ticker_matches
                if any(t.lower() in ascii_compact(n)
                       for c in name_matches for n in names_of[c])}
    explicit = ticker_matches - shadowed

    if explicit:
        tickers = explicit | name_matches
        how = "ticker_and_company_name" if name_matches - explicit else "ticker"
    elif name_matches:
        tickers, how = name_matches, "company_name"
    elif ticker_matches:
        tickers, how = ticker_matches, "ticker_shadowed"
    else:
        tickers, how = set(), "none"

    parent = any(m in compact for m in _PARENT_MARKERS)
    consolidated = any(m in compact for m in _CONSOLIDATED_MARKERS)
    scope = ("công ty mẹ" if parent and not consolidated
             else "hợp nhất" if consolidated and not parent else None)

    lo, hi = year_range
    years = tuple(sorted({int(m.group(1)) for m in _YEAR_RE.finditer(query)
                          if lo <= int(m.group(1)) <= hi}))
    tk = frozenset(tickers)
    mode = classify(query, len(tk))
    subject = (next(iter(tk)) if len(tk) == 1
               else pick_subject(query, names_of, tk) if mode == QuestionMode.RELATED
               else None)
    return Intent(tk, scope, years, how, mode, subject)
