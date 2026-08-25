"""S2 · xếp hạng ứng viên của S1 bằng BM25 + tín hiệu cấu trúc.

BM25 theo CỘT, không theo khối. `table_cards_fts` có năm cột nội dung; chỉ tiêu
tài chính hầu như luôn là NHÃN DÒNG, nên `row_labels` được đánh trọng số cao
nhất. Gộp năm cột thành một khối là vứt đi thông tin đã có sẵn.

`clean_ratio` là HỆ SỐ NHÂN, KHÔNG phải bộ lọc — 28.453 bảng có
`retrieval_ready=1` mà `execution_ready_obs=0` vẫn phải nằm trong tập ứng viên:
có câu chỉ cần một ô, và ô đó có thể sạch dù cả bảng thì không.

BA SỬA CHỮA SO VỚI BẢN TRƯỚC, ghi lại vì cả ba đều là lỗi IM LẶNG
-----------------------------------------------------------------
1. `table_uid IN (...)` sinh MỘT placeholder cho MỖI ứng viên. Đo trên 1.012
   câu: 240 câu có > 999 ứng viên, max 3.403. Trên bất kỳ bản SQLite biên dịch
   với `SQLITE_MAX_VARIABLE_NUMBER=999` (mặc định trước 3.32), truy vấn ném
   `OperationalError`, `except` cũ nuốt nó và gán `raw = {}` → **mất TOÀN BỘ
   BM25, điểm chỉ còn bonus cấu trúc, và mọi chỉ số vẫn in ra đẹp**. Máy hiện
   tại có trần 200.000 nên lỗi đang VÔ HÌNH; bật `screen_open` (~14.000 ứng
   viên) hoặc đổi môi trường là vỡ. → CHIA LÔ `_CHUNK`.

   Chia lô an toàn về mặt ngữ nghĩa: `bm25()` chấm MỖI DÒNG so với truy vấn,
   không phụ thuộc tập ứng viên. Chuẩn hoá min-max vẫn làm SAU khi gộp đủ lô.

2. `except sqlite3.OperationalError: raw = {}` không log gì. Nay ghi vào
   `LAST_ERRORS` và trả cờ trong `reasons` để tầng đo thấy được.

3. `WEIGHTS` là tuple VỊ TRÍ, không có gì kiểm số cột FTS khớp `len(WEIGHTS)`.
   Đổi thứ tự cột trong lược đồ là sai âm thầm. → `assert_fts_arity()`.

TRỌNG SỐ NAY CẤU HÌNH ĐƯỢC. `weights`/`bonuses` = None thì dùng mặc định dưới
đây; truyền vào thì A/B được mà không sửa mã. 11 hằng số này là **phỏng đoán có
cơ sở, CHƯA hiệu chỉnh** — chúng chưa từng được tối ưu trên gold thật.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from text2pandas.pipelines.retrieval.filter_s1 import Candidate

__all__ = ["Scored", "rank", "WEIGHTS", "BONUSES", "PRIMARY_KINDS",
           "assert_fts_arity",
           "LAST_ERRORS", "NORM_DEFAULT"]

# Cách chuẩn hoá điểm BM25. "rank" bất biến với kích thước pool — xem `_norm_rank`.
NORM_DEFAULT = "minmax"

# Thứ tự cột trong FTS: table_uid(UNINDEXED) · ticker · section_text ·
# context_clean · row_labels · col_labels
WEIGHTS: tuple[float, ...] = (0.0, 0.0, 2.0, 1.0, 4.0, 1.5)

BONUSES: dict[str, float] = {
    "period": 0.35,      # kỳ mục tiêu ∈ table_cards.periods
    "unit": 0.15,        # unit_kind câu hỏi ∈ table_cards.units
    "stmt": 0.10,        # statement_type khớp gợi ý S0 (đo được là LÀM TỆ ĐI)
    "basis": 0.30,       # phạm vi hợp nhất/riêng lẻ khớp
    "code": 0.45,        # mã chỉ tiêu VAS khớp — tín hiệu chính xác nhất ta có
    "clean_floor": 0.70,  # hệ số nhân khi clean_ratio = 0
    "clean_span": 0.30,   # phần cộng thêm khi clean_ratio = 1
    # `primary` — TIÊN NGHIỆM LỚP BÁO CÁO, mặc định 0.0 ⇒ KHÔNG đổi hành vi cũ.
    # Chỉ cộng khi caller truyền `primary_kinds` KHÁC RỖNG (xem `rank`). Cơ sở
    # đo trên gold_v2 (95 câu, docs/118 §3): với câu `screen`, gold là báo cáo
    # chính 77,4% nhưng top-N chỉ 60,8%; riêng `balance_sheet` lift GOLD/topN
    # = 10,4×. Với câu `single`/`compare` gold LẠI là thuyết minh (70%/81%) —
    # nên tiên nghiệm này BẮT BUỘC phải có điều kiện theo `mode`, áp toàn cục
    # là làm tệ đi. `mode` sinh từ `parse_intent`, không phải nhãn tay
    # (đã đối chiếu 95/95 câu) ⇒ không rò gold.
    "primary": 0.00,
}

# Ba lớp báo cáo chính. `note`/`equity_change`/`personnel`/`subsidiary` KHÔNG
# nằm ở đây — thuyết minh chứa phần chi tiết, không chứa số tổng hợp mà câu
# hỏi sàng lọc (`screen`) cần để tính tỉ số.
# `cash_flow` CỐ Ý KHÔNG có ở đây. Lift GOLD/topN của nó trên câu `screen` là
# 0,75 (< 1) — tức nó đã được xếp CAO HƠN mức đáng, cộng thêm là làm tệ đi.
# Đã đo cả hai: {BS,IS,CF} cho F2(A) 0,4891 · {BS,IS} cho 0,4994. Câu q570
# (vòng quay hàng tồn kho) là ca chẩn đoán: bonus đồng đều đẩy 8 bảng
# `cash_flow` không liên quan lên đầu và làm mất 0,17 F2 của riêng câu đó.
PRIMARY_KINDS: frozenset[str] = frozenset({"balance_sheet", "income_statement"})

# SQLite cũ mặc định 999. Lấy 800 để còn chỗ cho tham số khác trong cùng câu.
_CHUNK = 800

# TRẦN THAM SỐ — ràng buộc bằng `assert`, không bằng trí nhớ.
#
# `SQLITE_MAX_VARIABLE_NUMBER` là 999 ở SQLite < 3.32 và 32.766 từ 3.32 trở đi.
# Ta KHÔNG đọc trần thực tế của kết nối (`Connection.getlimit` chỉ có từ Python
# 3.11; máy build chạy 3.10.12) mà chốt theo SÀN 999, vì một con số chạy được
# trên máy này mà vỡ trên máy khác là đúng loại lỗi không tái lập được.
#
# Mỗi lô dùng `len(part)` tham số cho `table_uid IN (…)` cộng **1** cho `MATCH`.
_SQLITE_VAR_FLOOR = 999
assert _CHUNK + 1 <= _SQLITE_VAR_FLOOR, (
    f"_CHUNK={_CHUNK} + 1 tham số MATCH vượt sàn {_SQLITE_VAR_FLOOR}. "
    "Nâng _CHUNK là đổi hành vi trên SQLite < 3.32 — đừng nâng."
)

# Lỗi gần nhất của truy vấn BM25. KHÔNG nuốt im lặng: tầng đo đọc được ở đây.
LAST_ERRORS: list[str] = []


@dataclass(frozen=True, slots=True)
class Scored:
    cand: Candidate
    bm25: float                 # đã đảo dấu: CÀNG LỚN CÀNG TỐT
    period_hit: bool
    unit_hit: bool
    stmt_hit: bool
    score: float
    reasons: tuple[str, ...]
    basis_hit: bool = False


def assert_fts_arity(conn: sqlite3.Connection,
                     weights: tuple[float, ...] = WEIGHTS) -> int:
    """Số cột của `table_cards_fts` phải bằng `len(weights)`.

    `bm25()` nhận trọng số THEO VỊ TRÍ. Thêm/bớt/đổi thứ tự cột trong lược đồ
    FTS mà không sửa `WEIGHTS` là một lỗi không ném ngoại lệ, không sai cú
    pháp, và chỉ lộ ra dưới dạng "chất lượng xếp hạng tự nhiên kém đi".
    """
    row = conn.execute("SELECT * FROM table_cards_fts LIMIT 1").description
    n = len(row) if row else 0
    if n and n != len(weights):
        raise ValueError(
            f"table_cards_fts có {n} cột nhưng WEIGHTS có {len(weights)} phần tử — "
            "trọng số bm25 áp theo VỊ TRÍ, lệch là sai âm thầm.")
    return n


def _norm(vals: list[float]) -> list[float]:
    """Min-max TRONG tập ứng viên của từng câu.

    ⚠ PHỤ THUỘC KÍCH THƯỚC POOL. Ứng viên không khớp BM25 nhận `raw=0.0` và tham
    gia làm `min`, nên pool càng lớn thì `lo` càng bị kéo xuống và điểm BM25 của
    bảng đúng càng bị nén về giữa khoảng — trong khi bonus cấu trúc là HẰNG SỐ
    cộng vào. Kết quả: pool lớn ⇒ bonus lấn BM25.

    Đo được (`docs/76` §7b): `basis_hard` giảm pool 470→245 và mua được hit@1
    +0,0080 · MRR +0,0075 **chỉ nhờ bớt loãng** — nhưng phải trả −0,0219
    candidate hit rate. `_norm_rank` dưới đây lấy phần lợi đó mà không trả giá.
    """
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    return [0.5] * len(vals) if hi - lo < 1e-9 else [(v - lo) / (hi - lo) for v in vals]


def _norm_rank(vals: list[float]) -> list[float]:
    """Chuẩn hoá THEO HẠNG — bất biến với kích thước pool và với ngoại lai.

    Ý tưởng: điểm của một bảng không nên phụ thuộc vào việc có bao nhiêu bảng
    KHÔNG khớp gì nằm cùng pool. Chỉ thứ tự tương đối trong nhóm CÓ khớp mới có
    nghĩa.

    Ba tính chất, tất cả đều cố ý:

    1. **Ứng viên `raw == 0` (không khớp BM25) nhận thẳng 0,0**, không tham gia
       xếp hạng. Trước đây chúng làm `min` và kéo cả thang xuống.
    2. Trong nhóm `raw > 0`, điểm = `1 - (hạng-1)/n` với hạng tính theo giá trị
       giảm dần ⇒ bảng khớp tốt nhất luôn được **1,0** bất kể pool 43 hay 3.403.
    3. **Đồng hạng nhận cùng điểm** (dùng hạng trung bình), nếu không thì thứ tự
       chèn quyết định điểm — một nguồn bất định không ai muốn.
    """
    if not vals:
        return []
    idx_pos = [i for i, v in enumerate(vals) if v > 0.0]
    out = [0.0] * len(vals)
    n = len(idx_pos)
    if n == 0:
        return out
    if n == 1:
        out[idx_pos[0]] = 1.0
        return out
    order = sorted(idx_pos, key=lambda i: -vals[i])
    # Hạng trung bình cho các giá trị bằng nhau.
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        hang_tb = (i + j) / 2.0                      # 0-based
        diem = 1.0 - hang_tb / n
        for k in range(i, j + 1):
            out[order[k]] = diem
        i = j + 1
    return out


def _norm_max(vals: list[float]) -> list[float]:
    """Chia cho GIÁ TRỊ LỚN NHẤT — giữ TỶ LỆ ĐỘ LỚN, và bất biến với số ứng viên
    không khớp.

    VÌ SAO CẦN BẢN THỨ BA — `rank` đã bị dữ liệu bác bỏ
    --------------------------------------------------
    Tôi cho rằng min-max tệ vì phụ thuộc kích thước pool, nên thử chuẩn hoá theo
    HẠNG. Đo trên 1.012 câu: **hit@1 0,6551 → 0,4851 (−0,1700)**, MRR −0,1496.
    Tệ hơn hẳn, và cơ chế rõ ràng khi nhìn vào số:

        `_norm_rank` cho điểm `1 − hạng/n`. Với n = 200 ứng viên có khớp:
        hạng 0 → 1,000 · hạng 1 → 0,995 · hạng 2 → 0,990.
        Top-10 nằm trong khoảng 0,05 — trong khi bonus là 0,35 và 0,45.

    Tức là chuẩn hoá theo hạng **NÉN đỉnh phân bố**, làm bonus lấn BM25 còn
    NẶNG HƠN min-max. Nó chữa đúng bệnh (phụ thuộc pool) bằng cách gây ra một
    bệnh nặng hơn (mất thông tin độ lớn).

    Bản này giữ cả hai tính chất cần:
      · **bất biến với số ứng viên `raw == 0`** — chúng nhận 0,0, không tham gia
        tính `max`, nên thêm 1.000 bảng không khớp không đổi điểm của ai;
      · **giữ tỷ lệ độ lớn** — `[5,0 · 4,9 · 1,0] → [1,00 · 0,98 · 0,20]`. Bảng
        khớp vượt trội vẫn vượt trội, không bị nén về sát bảng thứ hai.

    Khác min-max ở đúng một điểm: min-max lấy `lo = min(vals)` nên **ứng viên
    không khớp kéo cả thang xuống** và làm khoảng cách tương đối bị phóng đại
    theo kích thước pool. Ở đây `lo` cố định bằng 0.
    """
    if not vals:
        return []
    hi = max(vals)
    if hi <= 0.0:
        return [0.0] * len(vals)
    return [v / hi if v > 0.0 else 0.0 for v in vals]


_NORMS = {"minmax": _norm, "rank": _norm_rank, "maxnorm": _norm_max}


def _bm25_scores(conn: sqlite3.Connection, uids: list[str], match: str,
                 weights: tuple[float, ...]) -> tuple[dict[str, float], bool]:
    """BM25 cho `uids`, CHIA LÔ để không vượt trần placeholder của SQLite.

    Trả `(điểm, ok)`. `ok=False` nghĩa là có lô lỗi — điểm KHÔNG đầy đủ và
    caller phải khai ra, không được lặng lẽ coi như "không khớp".
    """
    w = ",".join(str(x) for x in weights)
    out: dict[str, float] = {}
    ok = True
    for i in range(0, len(uids), _CHUNK):
        part = uids[i:i + _CHUNK]
        ph = ",".join("?" * len(part))
        try:
            for uid, s in conn.execute(
                    f"SELECT table_uid, bm25(table_cards_fts,{w}) "
                    f"FROM table_cards_fts "
                    f"WHERE table_cards_fts MATCH ? AND table_uid IN ({ph})",
                    (match, *part)):
                out[uid] = -s        # SQLite trả số ÂM, càng âm càng khớp
        except sqlite3.OperationalError as e:
            ok = False
            LAST_ERRORS.append(f"bm25 chunk[{i}:{i+len(part)}] n={len(part)}: {e}")
    return out, ok


def rank(conn: sqlite3.Connection, cands: list[Candidate], match: str | None,
         period_ends: tuple[str, ...] = (), unit_out: str | None = None,
         stmt_hint: str | None = None, top_k: int = 50,
         basis_hint: str | None = None,
         code_hint: frozenset[str] = frozenset(),
         weights: tuple[float, ...] | None = None,
         bonuses: dict[str, float] | None = None,
         norm: str | None = None,
         per_ticker_k: int | None = None,
         primary_kinds: frozenset[str] = frozenset()) -> list[Scored]:
    if not cands:
        return []
    W = tuple(weights) if weights else WEIGHTS
    B = {**BONUSES, **(bonuses or {})}
    nf = _NORMS.get(norm or NORM_DEFAULT)
    if nf is None:
        raise ValueError(f"norm phải là {sorted(_NORMS)}, nhận {norm!r}")

    by_uid = {c.table_uid: c for c in cands}
    uids = list(by_uid)
    raw: dict[str, float] = {}
    bm25_ok = True
    if match:
        raw, bm25_ok = _bm25_scores(conn, uids, match, W)

    bm = nf([raw.get(u, 0.0) for u in uids])
    out = []
    for u, b in zip(uids, bm):
        c = by_uid[u]
        per = bool(period_ends and c.periods
                   and any(p in c.periods for p in period_ends))
        uni = bool(unit_out and c.units and unit_out in c.units)
        stm = bool(stmt_hint and c.statement_type == stmt_hint)
        bas = bool(basis_hint and c.basis == basis_hint)
        # Mã chỉ tiêu VAS: tín hiệu CHÍNH XÁC nhất ta có. "Doanh thu thuần" ở
        # Báo cáo KQKD mang mã 10; cùng cụm đó nhắc lại trong thuyết minh thì
        # không. BM25 trên nhãn dòng không phân biệt được, mã thì phân biệt.
        ma = (frozenset(str(c.metric_codes).split(",")) & code_hint
              if code_hint and c.metric_codes else frozenset())
        why = []
        s = 1.00 * b
        if per: s += B["period"]; why.append("period")
        if uni: s += B["unit"];   why.append("unit")
        if stm: s += B["stmt"];   why.append("stmt")
        if bas: s += B["basis"];  why.append("basis")
        if ma:  s += B["code"];   why.append("code")
        if primary_kinds and c.statement_type in primary_kinds:
            s += B["primary"]; why.append("primary")
        if u in raw: why.append("bm25")          # `in`, không `.get()` — điểm 0.0 vẫn là khớp
        if not bm25_ok: why.append("bm25_partial")
        # Hệ số nhân, không phải bộ lọc: bảng sạch hơn được ưu tiên nhưng bảng
        # không có ô ready nào KHÔNG bị loại.
        s *= (B["clean_floor"] + B["clean_span"] * c.clean_ratio)
        out.append(Scored(c, raw.get(u, 0.0), per, uni, stm, s, tuple(why), bas))
    out.sort(key=lambda x: (-x.score, x.cand.table_uid))
    if per_ticker_k:
        out = _fanout_by_ticker(out, per_ticker_k, top_k)
    return out[:top_k]


def _fanout_by_ticker(scored: list[Scored], per_k: int, top_k: int) -> list[Scored]:
    """QUOTA THEO MÃ rồi mới gộp — sửa lỗi "top-K toàn cục sai đơn vị đo".

    VẤN ĐỀ ĐO ĐƯỢC
    --------------
    Câu `screen` hỏi 7 mã thì cần ≥7 bảng, mỗi mã ≥1. Nhưng top-10 TOÀN CỤC có
    thể bị một mã chiếm 8 chỗ, và 6 mã còn lại không có bảng nào — không phải vì
    xếp hạng sai, mà vì **đơn vị cắt sai**. `docs/76` đo: nhóm `screen` có
    `F2@10 = 0,299`, **thấp nhất mọi mode**, dù `candidate hit rate = 1,000`.
    Recall bị chặn bởi hình dạng đầu ra, không bởi chất lượng điểm.

    CÁCH LÀM
    --------
    Lấy `per_k` bảng tốt nhất CỦA TỪNG MÃ (giữ nguyên thứ tự điểm trong mã), rồi
    trộn theo kiểu **round-robin theo hạng**: hạng-1 của mọi mã trước, rồi hạng-2
    của mọi mã… Nhờ vậy mỗi mã được phục vụ trước khi bất kỳ mã nào được phục vụ
    lần hai. Phần còn lại (nếu `top_k` chưa đầy) nối tiếp theo điểm giảm dần.

    Thứ tự trong cùng một vòng: theo ĐIỂM giảm dần, tie-break `table_uid` — giữ
    tính tất định của bản gốc.
    """
    by_tk: dict[str, list[Scored]] = {}
    for s in scored:
        by_tk.setdefault(s.cand.ticker, []).append(s)
    if len(by_tk) <= 1:
        return scored
    vong: list[Scored] = []
    for i in range(per_k):
        lop = [v[i] for v in by_tk.values() if len(v) > i]
        lop.sort(key=lambda x: (-x.score, x.cand.table_uid))
        vong.extend(lop)
    da_co = {id(s) for s in vong[:top_k]}
    con_lai = [s for s in scored if id(s) not in da_co]
    return vong[:top_k] + con_lai
