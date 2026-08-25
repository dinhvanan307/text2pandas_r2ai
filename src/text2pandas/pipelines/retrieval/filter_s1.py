"""S1 · lọc cứng — thu hẹp 146.246 bảng về vài chục trước khi khớp văn bản.

Đo trên A6: lọc `ticker + doc_year + basis` còn trung bình 75 bảng (max 248),
tức thu hẹp ~1.950 lần. Đây là lý do tầng này tồn tại và là lý do KHÔNG cần
vector store ở vòng đầu.

BA QUYẾT ĐỊNH CÓ HẬU QUẢ, ghi lại để lần sau không ai phải đoán:

1. LÁI TỪ `documents` (1.973 dòng), KHÔNG từ `table_cards` (146.246 dòng).
   Đo thật: 2 ms so với 2.478 ms cho cùng một kết quả.

2. KHÔNG lọc cứng `doc_year = năm hỏi`. 96.224 bảng có 2 kỳ, chỉ 33.123 có 1
   kỳ — báo cáo năm N in kèm cột N−1. Câu hỏi năm 2017 trả lời được từ tài
   liệu 2017 HOẶC 2018. Nới ở tầng bảng, siết ở tầng ô bằng `period_end`.

3. `basis` theo chính sách `scope_or_unknown` của BTC: khớp scope HOẶC không
   xác định. Corpus có 957 consolidated · 954 separate · 55 NULL · 7
   aggregated; loại thẳng 62 tài liệu không khai scope là mất dữ liệu thật.

KHÔNG lọc theo `statement_type`: suy loại báo cáo từ câu hỏi hay sai, và sai
một lần là mất trắng. Nó là điểm cộng ở S2.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

__all__ = ["Candidate", "filter_tables", "SQL"]

SQL = """
SELECT t.table_uid, t.doc_id, d.ticker, d.doc_year, d.basis,
       t.statement_type, t.n_observations, t.execution_ready_obs,
       t.periods, t.units, t.metric_codes
FROM documents d
JOIN table_cards t ON t.doc_id = d.directory_doc_id
WHERE d.ticker IN ({tickers})
  AND ({basis_pred})
  AND ({year_pred})
  AND t.retrieval_ready = 1
"""


@dataclass(frozen=True, slots=True)
class Candidate:
    table_uid: str
    doc_id: str
    ticker: str
    doc_year: int
    basis: str | None
    statement_type: str | None
    n_observations: int
    execution_ready_obs: int
    periods: str | None
    units: str | None
    metric_codes: str | None = None

    @property
    def clean_ratio(self) -> float:
        """Tỷ lệ ô dùng được tự động. HỆ SỐ NHÂN khi xếp hạng, KHÔNG phải bộ lọc.

        28.453 bảng có `retrieval_ready=1` mà `execution_ready_obs=0` vẫn phải
        nằm trong tập ứng viên: có câu chỉ cần một ô, và ô đó có thể sạch dù cả
        bảng thì không.
        """
        return (self.execution_ready_obs / self.n_observations
                if self.n_observations else 0.0)


def filter_tables(conn: sqlite3.Connection, tickers, years=(), basis=None,
                  year_slack: int = 1) -> list[Candidate]:
    tk = tuple(sorted(set(tickers)))
    if not tk:
        return []                       # không phân giải được thực thể → S1 im lặng
    args: list = list(tk)

    if basis:
        basis_pred = "(d.basis = ? OR d.basis IS NULL)"     # scope_or_unknown
        args.append(basis)
    else:
        basis_pred = "1"

    if years:
        lo, hi = min(years), max(years) + year_slack
        year_pred = "d.doc_year BETWEEN ? AND ?"
        args += [lo, hi]
    else:
        year_pred = "1"

    sql = SQL.format(tickers=",".join("?" * len(tk)),
                     basis_pred=basis_pred, year_pred=year_pred)
    return [Candidate(*r) for r in conn.execute(sql, args)]
