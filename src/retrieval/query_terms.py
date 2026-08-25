"""Dựng truy vấn FTS5 từ câu hỏi.

Chỉ mục `table_cards_fts` có NĂM cột nội dung — `ticker`, `section_text`,
`context_clean`, `row_labels`, `col_labels` — và tokenizer KHÔNG phân biệt dấu
(đo: `"lãi tiền gửi"` và `"lai tien gui"` cùng ra 3.760 bảng). Hai điều đó
quyết định thiết kế ở đây:

  · không cần bỏ dấu thủ công;
  · chỉ tiêu tài chính hầu như luôn là NHÃN DÒNG, nên `row_labels` phải được
    đánh trọng số cao nhất.

Dùng OR chứ không AND. Đo trên chỉ mục thật: `lãi AND "tiền gửi"` ra 14.356
bảng, `lãi OR "tiền gửi"` ra 77.780. Nhưng ở S2 ta đã bị S1 thu hẹp, nên rủi ro
thật không phải là quá nhiều ứng viên mà là **AND cứng loại mất bảng đúng chỉ
vì thiếu một từ**. Recall là thứ phải giữ ở tầng này.

SỬA CHỮA · XOÁ ALIAS PHẢI TÔN TRỌNG BIÊN TỪ
-------------------------------------------
Bản trước xoá `drop` bằng `re.sub(re.escape(d), " ", text, flags=re.I)` — KHÔNG
biên từ. Hệ quả trên chính 100 mã của cuộc thi: `GAS`, `SAM`, `CEO`, `FIT`,
`FOX`, `HAG`, `DIG`, `PAN`, `TIP` là chuỗi con của rất nhiều từ tiếng Việt
thường ("**gas**", "**sam**e", "giám đốc **CEO**", "bene**fit**", …). Xoá chúng
như chuỗi con làm rỗng đúng cụm chỉ tiêu cần tìm.

Đây cùng một lớp lỗi với 36/570 ca phân giải sai của đường nộp cũ
(`reports/metric_audit_V2.json`: khai `FTS` khi bằng chứng là `FPT`, khai `FOX`
khi bằng chứng là `FPT`). Ở đó là `ticker_mentioned`; ở đây là `content_terms`.

Luật mới, hai lớp:
  · alias NGẮN (≤5 ký tự, gần như luôn là mã) → chỉ xoá khi có biên từ hai bên;
  · alias DÀI (tên công ty) → xoá tự do, vì một tên dài trùng ngẫu nhiên vào
    giữa một từ khác là chuyện không xảy ra.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["content_terms", "build_match", "drop_terms", "STOP",
           "STOP_DAU", "STOP_MODES", "SHORT_ALIAS_MAX"]

# Từ chức năng + từ khung câu hỏi + đơn vị đích. Chúng có mặt ở mọi câu nên
# không phân biệt được bảng nào với bảng nào, mà lại kéo điểm BM25 lung tung.
STOP = {
    "la", "bao", "nhieu", "cua", "va", "cac", "trong", "nam", "cho", "voi",
    "tai", "den", "tu", "co", "khong", "duoc", "bi", "o", "vao", "ra", "theo",
    "tren", "duoi", "giua", "so", "hay", "hoac", "thi", "ma", "nhung", "nay",
    "do", "kia", "mot", "hai", "ba", "bon", "sau", "bay", "tam", "chin", "muoi",
    "cong", "ty", "me", "nghiep", "ctcp", "tmcp",
    "tap", "doan", "tong", "phan", "hop", "rieng",
    "dong", "trieu", "nghin", "vnd",
    "tinh", "xac", "dinh", "hoi", "cau",
    # `doanh`, `gia`, `tri`, `muc`, `ngan`, `hang`, `nhat` CỐ Ý không nằm đây:
    # "doanh thu", "giá trị", "giá vốn", "ngắn hạn", "hàng tồn kho", "thuần
    # nhất" đều là chỉ tiêu thật. Cắt chúng là cắt đúng thứ cần tìm.
}
# ── STOP DẠNG CÓ DẤU · sửa một lỗi làm mất từ nội dung ở 61,4% số câu ───────
#
# `STOP` ở trên được đối chiếu với dạng ĐÃ BỎ DẤU. Tokenizer FTS5 bỏ dấu, nên
# lúc viết thì điều đó có vẻ nhất quán. Nhưng bỏ dấu làm SẬP nhiều từ tiếng Việt
# khác nghĩa về cùng một chuỗi, và `STOP` khi đó nuốt luôn cả từ nội dung:
#
#     tài (tài sản)   → "tai"  ← STOP có "tai" cho **tại**     170 câu
#     động (bất động sản, hoạt động) → "dong" ← STOP có "dong" cho **đồng**  158 câu
#     cổ (cổ phiếu, cổ phần) → "co"  ← STOP có "co" cho **có**   129 câu
#     sở, tư, mã, trọng, đoạn, cố, cơ, dở, dòng, hải …
#
# Đo trên đúng 1.012 câu của cuộc thi: **621 câu (61,4%) mất ít nhất một từ nội
# dung** theo cách này. "Tài sản cố định" rút còn "sản"; "bất động sản đầu tư"
# rút còn "bất sản đầu".
#
# `stop_mode="dau"` đối chiếu STOP với dạng CÓ DẤU đã hạ chữ thường. Vẫn giữ
# nhánh không dấu cho token người dùng gõ thiếu dấu (`low == fold`), nên câu hỏi
# viết "nam 2020" vẫn được lọc đúng.
#
# Để MẶC ĐỊNH là "fold" (hành vi cũ) cho tới khi A/B trên 1.012 câu chứng minh
# được — nguyên tắc dự án: mọi thay đổi phải có bằng chứng, kể cả thay đổi
# trông hiển nhiên đúng.
STOP_DAU = {
    "là", "bao", "nhiêu", "của", "và", "các", "trong", "năm", "cho", "với",
    "tại", "đến", "từ", "có", "không", "được", "bị", "ở", "vào", "ra", "theo",
    "trên", "dưới", "giữa", "số", "hay", "hoặc", "thì", "mà", "những", "này",
    "đó", "kia", "một", "hai", "ba", "bốn", "sáu", "bảy", "tám", "chín", "mười",
    "công", "ty", "tỷ", "mẹ", "nghiệp", "ctcp", "tmcp",
    "tập", "đoàn", "tổng", "phần", "hợp", "riêng",
    "đồng", "triệu", "nghìn", "vnd",
    "tính", "xác", "định", "hỏi", "câu",
}
STOP_MODES = ("fold", "dau")

_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_NUM = re.compile(r"^\d+([.,]\d+)?$")

# Alias không dài hơn ngưỡng này được coi là MÃ và chỉ xoá khi có biên từ.
SHORT_ALIAS_MAX = 5

# Biên "từ" cho tiếng Việt: chữ Latin có dấu vẫn là chữ. Không dùng `\b` của
# `re` vì `\b` coi `ỹ` là ký tự không-từ và sẽ cắt sai giữa tiếng Việt.
_W = r"0-9A-Za-zÀ-ỹ"


def _fold(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return d.replace("đ", "d").replace("Đ", "D").lower()


def drop_terms(targets, alias: dict[str, list[str]] | None = None) -> tuple[str, ...]:
    """NGUỒN DUY NHẤT của luật "chuỗi nào phải bị loại khỏi truy vấn BM25".

    Trả về: mọi **tên công ty** của các mã đã phân giải, cộng chính các **mã**.

    VÌ SAO HÀM NÀY TỒN TẠI — một regression thật
    --------------------------------------------
    Luật này từng được viết ở HAI chỗ và **đã trôi dạt**:

        pipeline.py:79          drop = alias TÊN + mã       ← đúng
        evalkit/stages.py:230   drop = CHỈ mã               ← thiếu tên

    Hệ quả đo được trên 100 câu (cùng proxy gold, cùng S1, khác duy nhất `drop`):
    tên công ty còn lại trong truy vấn BM25, **+2,3 token nhiễu/câu** (7,8 so với
    5,5), và **hit@1 0,7800 → 0,6900 (−0,0900)** · hit@10 0,9600 → 0,8900.

    Tệ hơn con số: mọi phép đo của `evalkit` trong ba phiên trước đều mang lỗi
    này, nên mọi số TUYỆT ĐỐI ở `docs/76`/`docs/77` thấp hơn thực tế ~9 điểm, và
    một giải thích ở `docs/76` §2 ("hiệu ứng coverage") là SAI.

    Nên luật phải nằm ở ĐÚNG MỘT chỗ, và `tests/test_p0_unify.py` khoá việc đó.

    VÌ SAO PHẢI LOẠI TÊN CÔNG TY
    ----------------------------
    Tên công ty đã được dùng làm **bộ lọc cứng** ở S1 (`d.ticker IN (…)`), nên
    mọi bảng còn lại trong tập ứng viên đều thuộc đúng công ty đó. Để tên trong
    truy vấn BM25 là cộng điểm cho một thứ **không phân biệt được ứng viên nào
    với ứng viên nào** — thuần nhiễu, và nó lấn chỗ của cụm chỉ tiêu.
    """
    tk = tuple(targets)
    if not alias:
        return tk
    return tuple(n for t in tk for n in alias.get(t, [])) + tk


def _strip_alias(text: str, alias: str) -> str:
    """Xoá một alias. Alias ngắn phải có biên từ hai bên; alias dài thì không cần."""
    if not alias:
        return text
    pat = re.escape(alias)
    if len(alias) <= SHORT_ALIAS_MAX:
        pat = rf"(?<![{_W}]){pat}(?![{_W}])"
    return re.sub(pat, " ", text, flags=re.IGNORECASE)


def _bi_loai(low: str, fold: str, mode: str) -> bool:
    """Token này có phải từ chức năng cần loại không.

    `fold` · đối chiếu dạng bỏ dấu — hành vi gốc, nuốt oan 61,4% số câu.
    `dau`  · đối chiếu dạng CÓ DẤU; chỉ rơi về dạng bỏ dấu khi chính token đó
             vốn không có dấu, để câu gõ thiếu dấu vẫn được lọc.
    """
    if mode == "fold":
        return fold in STOP
    return low in STOP_DAU or (low == fold and fold in STOP)


def content_terms(question: str, drop: tuple[str, ...] = (),
                  stop_mode: str = "fold") -> list[str]:
    """Từ nội dung, giữ THỨ TỰ xuất hiện và giữ dấu (tokenizer tự bỏ dấu).

    `drop`: chuỗi cần loại — thường là tên công ty và mã đã khớp ở S0, vì chúng
    đã được dùng làm bộ lọc cứng và để lại chỉ làm nhiễu điểm.

    Xoá alias DÀI trước alias NGẮN: "Hoàng Anh Gia Lai" phải mất trước khi luật
    biên từ xét "HAG", nếu không thì thứ tự xoá đổi kết quả.

    `stop_mode`: xem `_bi_loai`. Mặc định giữ hành vi cũ.
    """
    if stop_mode not in STOP_MODES:
        raise ValueError(f"stop_mode phải là {STOP_MODES}, nhận {stop_mode!r}")
    text = question
    for d in sorted(drop, key=len, reverse=True):
        text = _strip_alias(text, d)
    text = _YEAR.sub(" ", text)
    out, seen = [], set()
    for raw in re.split(rf"[^{_W}]+", text):
        if not raw:
            continue
        f = _fold(raw)
        if len(f) < 2 or _bi_loai(raw.lower(), f, stop_mode) \
                or _NUM.match(f) or f in seen:
            continue
        seen.add(f)
        out.append(raw)
    return out


def build_match(terms: list[str], max_terms: int = 24,
                phrase_n: int = 3) -> str | None:
    """Truy vấn FTS5 · CỤM trước, rồi OR từng token.

    Cụm liên tiếp ("lãi tiền gửi") là tín hiệu mạnh hơn hẳn ba token rời, vì
    chỉ tiêu tài chính là cụm danh từ cố định. FTS5 chấm cụm cao hơn token đơn
    một cách tự nhiên, nên chỉ cần đưa cả hai vào cùng một truy vấn OR.
    """
    t = terms[:max_terms]
    if not t:
        return None
    parts = []
    for n in range(min(phrase_n, len(t)), 1, -1):
        for i in range(len(t) - n + 1):
            parts.append('"' + " ".join(t[i:i + n]) + '"')
    parts += [f'"{x}"' for x in t]
    return " OR ".join(parts)
