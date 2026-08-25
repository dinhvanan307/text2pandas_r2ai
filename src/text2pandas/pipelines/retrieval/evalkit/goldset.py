"""Gold set — ba nguồn, một hợp đồng, thang TIER, và một phép kiểm vòng tròn.

BA NGUỒN
--------
  ManualGold   · gán tay. NGUỒN DUY NHẤT đáng tin để chốt quyết định.
  ProxyGoldV2  · dựng bằng máy, có THANG TIER. Dùng để lọc nhanh + tìm failure case.
  FreeScan     · `COUNT(*) GROUP BY ticker`, KHÔNG LIMIT. Không phải gold — là
                 dụng cụ kiểm phân giải thực thể, độc lập với S1.

VÒNG TRÒN CỦA `proxy_gold.py` (bản cũ), VÀ CÁCH SỬA
---------------------------------------------------
Bản cũ nhét `ticker : X` THẲNG VÀO biểu thức MATCH (`proxy_gold.py:64`) trong
khi docstring dòng 12–15 khẳng định "KHÔNG lọc theo mã". Hệ quả không phải "số
hơi lệch" mà là **một loại lỗi biến mất khỏi thước đo**: S0 sai mã → gold rỗng →
câu bị loại khỏi tập đo thay vì bị tính là miss.

Ở đây mã là **vị từ SQL thường** (`t.ticker IN (...)`), không nằm trong MATCH.
Ràng buộc mã vẫn còn — nó ĐÚNG về ngữ nghĩa: bảng gold của "doanh thu VNM" phải
là bảng VNM — nhưng nó không còn quyết định phạm vi quét FTS, và quan trọng hơn,
khi nó làm gold rỗng thì ta ĐO ĐƯỢC điều đó thay vì bỏ câu đi.

BUG ĐÃ SỬA · RETURN SỚM LÀM SỤP COVERAGE 92% → 56,7%
----------------------------------------------------
Bản đầu của tệp này quét tự do rồi thu hẹp theo mã BẰNG PYTHON, và khi `keep`
rỗng thì **`return` ngay** — bỏ luôn mọi cụm ngắn hơn chưa thử. Đo được: 413 câu
báo `no_phrase_match`, trong khi `diag_nogold.py` cho thấy **80% trong số đó có
bảng khớp bằng đúng cụm 2-gram + cùng ràng buộc mã và kỳ**. Tức là gold hoàn
toàn dựng được, chỉ là vòng lặp bị bỏ dở.

Sửa: vòng lặp KHÔNG BAO GIỜ return sớm. Quan sát "cụm khớp ở corpus nhưng không
ở tài liệu của mã" được GHI LẠI rồi tiếp tục thử; nó chỉ trở thành kết luận khi
đã cạn mọi cụm ở mọi tier.

THANG TIER — nới dần, và KHAI nới tới đâu
-----------------------------------------
`diag_nogold.py` đo trên 200 câu không dựng được gold, giữ nguyên ràng buộc mã
và kỳ, chỉ đổi cách khớp cụm:

    T1/T2  cụm n-gram liền nhau trên `row_labels`     →  80% câu có bảng khớp
    T3     AND hai token trên `row_labels`            →  94%
    T4     cụm 2-gram trên MỌI cột nội dung           →  84%

Nên thang là T1 → T2 → T3 → T4. Nhưng nới càng nhiều thì gold càng NHIỄU, nên
mỗi `GoldSet` mang `tier` và `report` tách chỉ số theo tier. Một con số trên gold
T3 không được đọc ngang hàng với cùng con số trên gold T1.

GIỚI HẠN CÒN LẠI — KHAI ĐỦ, KHÔNG GIẤU
--------------------------------------
  · câu phái sinh (ROE, tăng trưởng) vẫn không có gold: Silver không lưu giá
    trị phái sinh, không cụm nào khớp được;
  · gold vẫn định nghĩa phần lớn qua `row_labels`, mà tầng xếp hạng đánh
    `row_labels` trọng số cao nhất (4.0) → thước đo VẪN thưởng một phần chính
    tín hiệu nó đo. Giới hạn này KHÔNG sửa được bằng mã, chỉ bằng gold tay;
  · `n_gold` median 8 → mọi `Precision`/`Recall` trên proxy đều LẠC QUAN. Đọc
    `precision_capped` và slice `g==1`.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from text2pandas.pipelines.retrieval.query_terms import content_terms

from .taxonomy import NoGoldReason

__all__ = ["GoldSet", "GoldProvider", "ProxyGoldV2", "ManualGold",
           "free_ticker_histogram", "TIERS", "GOLD_ERRORS"]

# Lỗi truy vấn khi DỰNG GOLD. Phải phơi ra vì gold hỏng làm hỏng THƯỚC ĐO, mà
# thước đo hỏng thì mọi con số sau đó đều vô nghĩa mà vẫn trông bình thường.
# `runner.collect` đọc danh sách này và kêu to ở cuối lượt chạy.
GOLD_ERRORS: list[str] = []

# Thang nới, theo đúng thứ tự áp dụng. `strict` = dùng được để chốt quyết định.
# `T0_manual` không nằm trong kế hoạch quét — nó là gold tay, luôn strict.
TIERS = {
    "T0_manual": {"strict": True},       # gán tay — nguồn duy nhất để CHỐT
    "T1_row_ngram": {"strict": True},    # cụm ≥3 token liền nhau, row_labels
    "T2_row_2gram": {"strict": True},    # cụm 2 token liền nhau, row_labels
    "T3_row_and2": {"strict": False},    # hai token bất kỳ, row_labels
    "T4_anycol_2gram": {"strict": False},  # cụm 2 token, mọi cột nội dung
}
_SCAN_TIERS = ("T1_row_ngram", "T2_row_2gram", "T3_row_and2", "T4_anycol_2gram")


@dataclass(frozen=True, slots=True)
class GoldSet:
    qid: int
    tables: frozenset[str]
    docs: frozenset[str]
    source: str                       # manual | proxy_v2 | none
    how: str = ""                     # phrase | manual | none
    phrase: str = ""
    tier: str = ""
    n_raw_hits: int = 0               # số bảng khớp cụm TRONG PHẠM VI mã+kỳ
    n_free_hits: int = 0              # số bảng khớp cụm TOÀN CORPUS (chỉ khi cần)
    saturated: bool = False
    reason: NoGoldReason | None = None
    trace: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.tables) and not self.saturated

    @property
    def strict(self) -> bool:
        return bool(self.tables) and TIERS.get(self.tier, {}).get("strict", False)


class GoldProvider(Protocol):
    name: str

    def gold_for(self, conn: sqlite3.Connection, qid: int, question: str,
                 tickers: frozenset[str], years: tuple[int, ...],
                 explicit_scope: str | None) -> GoldSet: ...


# ─────────────────────────────────────────────────────────────────────────────
# Proxy v2 — mã là VỊ TỪ SQL, không nằm trong MATCH
# ─────────────────────────────────────────────────────────────────────────────

_SEL = ("SELECT t.table_uid, t.doc_id, t.ticker FROM table_cards_fts f "
        "JOIN table_cards t ON t.rowid = f.rowid WHERE table_cards_fts MATCH ?")
_CNT = ("SELECT t.ticker, COUNT(*) FROM table_cards_fts f "
        "JOIN table_cards t ON t.rowid = f.rowid WHERE table_cards_fts MATCH ?")


def _scoped(conn, match: str, tickers: tuple[str, ...],
            period_ends: tuple[str, ...], limit: int):
    """Quét cụm, thu hẹp theo mã và kỳ BẰNG SQL (không post-filter Python).

    Mã ở vị từ SQL nghĩa là `LIMIT` áp lên tập ĐÃ thu hẹp — nên `LIMIT` không
    còn làm lệch phân bố như khi cắt trên tập tự do rồi mới lọc.
    """
    sql, args = _SEL, [match]
    if tickers:
        sql += " AND t.ticker IN (" + ",".join("?" * len(tickers)) + ")"
        args += list(tickers)
    if period_ends:
        sql += " AND (" + " OR ".join("t.periods LIKE ?" for _ in period_ends) + ")"
        args += [f"%{p}%" for p in period_ends]
    sql += f" LIMIT {limit}"
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError as e:
        # `None` ≠ `[]`: caller phân biệt được "truy vấn hỏng" với "không khớp".
        GOLD_ERRORS.append(f"_free_rows: {e} · match={match[:60]!r}")
        return None


def free_ticker_histogram(conn, match: str,
                          period_ends: tuple[str, ...] = ()) -> dict[str, int]:
    """`GROUP BY ticker`, KHÔNG LIMIT, KHÔNG ràng buộc mã.

    Không LIMIT vì LIMIT làm lệch phân bố theo rowid, và rowid không liên quan
    gì tới câu hỏi. Đây là dụng cụ kiểm phân giải thực thể ĐỘC LẬP với S1.
    """
    sql, args = _CNT, [match]
    if period_ends:
        sql += " AND (" + " OR ".join("t.periods LIKE ?" for _ in period_ends) + ")"
        args += [f"%{p}%" for p in period_ends]
    sql += " GROUP BY t.ticker"
    try:
        return {tk: n for tk, n in conn.execute(sql, args)}
    except sqlite3.OperationalError as e:
        # KHÔNG được im lặng. `{}` ở đây trông y hệt "không mã nào khác chứa cụm
        # này" — tức là bằng chứng để KHÔNG gắn `entity_suspect`. Một lỗi cú
        # pháp FTS sẽ biến thành một kết luận về phân giải thực thể.
        GOLD_ERRORS.append(f"free_ticker_histogram: {e} · match={match[:60]!r}")
        return {}


def _q(s: str) -> str:
    """Bọc token cho FTS5, thoát dấu nháy kép."""
    return '"' + s.replace('"', '""') + '"'


class ProxyGoldV2:
    """Gold đại diện, có thang tier. Không return sớm, không lọc mã trong MATCH."""

    name = "proxy_v2"

    def __init__(self, raw_limit: int = 400, max_trusted: int = 60,
                 max_phrase_len: int = 4, alias: dict | None = None,
                 max_tier: str = "T4_anycol_2gram"):
        self.raw_limit = raw_limit
        self.max_trusted = max_trusted
        self.max_phrase_len = max_phrase_len
        self.alias = alias or {}
        self.max_tier = max_tier

    def _drop(self, tickers: frozenset[str]) -> tuple[str, ...]:
        return tuple(n for t in tickers for n in self.alias.get(t, [])) + tuple(tickers)

    def _plan(self, terms: list[str]) -> list[tuple[str, str, str]]:
        """`(tier, nhãn cụm, biểu thức MATCH)` theo đúng thứ tự nới dần."""
        plan: list[tuple[str, str, str]] = []
        # T1 · cụm dài trước, trên row_labels
        for n in range(min(self.max_phrase_len, len(terms)), 2, -1):
            for i in range(len(terms) - n + 1):
                ph = " ".join(terms[i:i + n])
                plan.append(("T1_row_ngram", ph, f"row_labels : {_q(ph)}"))
        # T2 · cụm 2 token liền nhau
        for i in range(len(terms) - 1):
            ph = " ".join(terms[i:i + 2])
            plan.append(("T2_row_2gram", ph, f"row_labels : {_q(ph)}"))
        # T3 · AND hai token, KHÔNG cần liền nhau (94% cứu được — đo ở diag_nogold)
        for i in range(min(4, len(terms))):
            for j in range(i + 1, min(5, len(terms))):
                ph = f"{terms[i]} & {terms[j]}"
                plan.append(("T3_row_and2", ph,
                             f"row_labels : {_q(terms[i])} AND row_labels : {_q(terms[j])}"))
        # T4 · cụm 2 token trên MỌI cột nội dung — bắt chỉ tiêu nằm ở tiêu đề mục
        for i in range(len(terms) - 1):
            ph = " ".join(terms[i:i + 2])
            plan.append(("T4_anycol_2gram", ph,
                         "{section_text context_clean row_labels col_labels} : " + _q(ph)))
        # Cắt theo `max_tier`
        allow: list[str] = []
        for t in _SCAN_TIERS:
            allow.append(t)
            if t == self.max_tier:
                break
        return [(tier, ph, expr) for tier, ph, expr in plan if tier in allow]

    def gold_for(self, conn, qid: int, question: str, tickers: frozenset[str],
                 years: tuple[int, ...], explicit_scope: str | None) -> GoldSet:
        period_ends = tuple(f"{y}-12-31" for y in years)
        tk = tuple(sorted(tickers))
        terms = content_terms(question, drop=self._drop(tickers))
        if len(terms) < 2:
            return GoldSet(qid, frozenset(), frozenset(), self.name, "none",
                           reason=NoGoldReason.NO_CONTENT_TERMS,
                           trace={"n_terms": len(terms)})

        # Ghi lại quan sát "khớp corpus nhưng không khớp mã" mà KHÔNG return.
        elsewhere: tuple[str, str] | None = None
        n_syntax_err = 0
        too_big: GoldSet | None = None

        for tier, ph, expr in self._plan(terms):
            rows = _scoped(conn, expr, tk, period_ends, self.raw_limit)
            if rows is None:
                n_syntax_err += 1
                continue
            if not rows:
                if elsewhere is None and tk:
                    # Rẻ: chỉ đếm khi CẦN biết cụm có tồn tại ở nơi khác không.
                    hist = free_ticker_histogram(conn, expr, period_ends)
                    if hist and not (set(hist) & set(tk)):
                        elsewhere = (ph, tier)
                continue

            keep = rows
            if explicit_scope:
                hau = "_separate" if explicit_scope == "công ty mẹ" else "_consolidated"
                loc = [r for r in keep if r[1].endswith(hau)]
                if loc:
                    keep = loc
            saturated = len(rows) >= self.raw_limit
            if len(keep) > self.max_trusted or saturated:
                # Cụm quá phổ thông. GIỮ LẠI làm phương án cuối nhưng tiếp tục
                # thử — một cụm hẹp hơn ở tier sau vẫn có thể tốt hơn.
                if too_big is None:
                    too_big = GoldSet(
                        qid, frozenset(u for u, _, _ in keep),
                        frozenset(d for _, d, _ in keep), self.name, "phrase",
                        phrase=ph, tier=tier, n_raw_hits=len(rows), saturated=True,
                        reason=(NoGoldReason.SATURATED if saturated
                                else NoGoldReason.UNTRUSTED_SIZE))
                continue
            return GoldSet(
                qid, frozenset(u for u, _, _ in keep),
                frozenset(d for _, d, _ in keep), self.name, "phrase",
                phrase=ph, tier=tier, n_raw_hits=len(rows), saturated=False,
                trace={"n_keep": len(keep), "n_terms": len(terms),
                       "syntax_err": n_syntax_err})

        if too_big is not None:
            return too_big
        if elsewhere is not None:
            ph, tier = elsewhere
            hist = free_ticker_histogram(
                conn, f"row_labels : {_q(ph)}" if tier != "T4_anycol_2gram"
                else "{section_text context_clean row_labels col_labels} : " + _q(ph),
                period_ends)
            top = sorted(hist.items(), key=lambda kv: -kv[1])[:8]
            return GoldSet(
                qid, frozenset(), frozenset(), self.name, "none", phrase=ph,
                tier=tier, n_free_hits=sum(hist.values()),
                reason=NoGoldReason.NO_PHRASE_MATCH,
                trace={"entity_suspect": True, "free_top": dict(top),
                       "targets": list(tk), "n_terms": len(terms)})
        return GoldSet(qid, frozenset(), frozenset(), self.name, "none",
                       reason=NoGoldReason.NO_PHRASE_MATCH,
                       trace={"n_terms": len(terms), "syntax_err": n_syntax_err})


# ─────────────────────────────────────────────────────────────────────────────
# Gold gán tay — nguồn duy nhất đáng tin để CHỐT quyết định
# ─────────────────────────────────────────────────────────────────────────────

class ManualGold:
    """Nạp `data/curated/dev-legacy/gold_v1.jsonl`.

    Lược đồ mỗi dòng, tối thiểu:
        {"id": 1, "gold_tables": ["DOC|1293", ...]}         ← khoá nộp bài
      hoặc
        {"id": 1, "gold_table_uids": ["<table_uid>", ...]}  ← khoá nội bộ

    Chấp nhận cả hai vì người gán tay đọc tài liệu qua `evidence_ref`
    (`DOC|line:N`) chứ không qua `table_uid`. Bộ nạp tự đổi `DOC|N` → `table_uid`
    và KHAI ra dòng nào không tra được, thay vì bỏ im lặng.
    """

    name = "manual"

    def __init__(self, path: Path, conn: sqlite3.Connection | None = None):
        self.path = Path(path)
        self._by_qid: dict[int, GoldSet] = {}
        self.unmapped: list[tuple[int, str]] = []
        if self.path.is_file():
            self._load(conn)

    def _ref_index(self, conn) -> dict[str, str]:
        if conn is None:
            return {}
        out = {}
        for uid, ref in conn.execute(
                "SELECT table_uid, evidence_ref FROM table_cards "
                "WHERE evidence_ref IS NOT NULL"):
            out[str(ref).replace("|line:", "|")] = uid
        return out

    def _load(self, conn) -> None:
        idx = None
        for line in self.path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            qid = int(row["id"])
            uids = set(row.get("gold_table_uids") or [])
            refs = row.get("gold_tables") or []
            if refs:
                if idx is None:
                    idx = self._ref_index(conn)
                for r in refs:
                    u = idx.get(str(r).replace("|line:", "|"))
                    if u:
                        uids.add(u)
                    else:
                        self.unmapped.append((qid, str(r)))
            self._by_qid[qid] = GoldSet(
                qid, frozenset(uids),
                frozenset(str(u).rsplit("|", 1)[0] for u in refs) if refs else frozenset(),
                self.name, "manual", tier="T0_manual",
                trace={"n_refs": len(refs), "annotator": row.get("annotator")})

    def __len__(self) -> int:
        return len(self._by_qid)

    def has(self, qid: int) -> bool:
        return qid in self._by_qid

    def gold_for(self, conn, qid: int, question: str, tickers, years,
                 explicit_scope) -> GoldSet:
        g = self._by_qid.get(qid)
        if g is not None:
            return g
        return GoldSet(qid, frozenset(), frozenset(), self.name, "none",
                       reason=NoGoldReason.NOT_RUN)
