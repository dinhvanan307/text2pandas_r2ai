"""ADAPTER · Retrieval (A6/work.db) → định danh bảng của BÀI NỘP.

VÌ SAO PHẢI CÓ MỘT LỚP RIÊNG, KHÔNG PHẢI ĐỔI TÊN CSDL
-----------------------------------------------------
Đường nộp hiện tại đọc `artifacts/legacy/silver-pre-a6/silver.sqlite` — **một thế hệ lược đồ khác**
(2 bảng, sinh 02/08) chứ không phải gói Silver A6 (19 bảng). Cám dỗ ở đây là
trỏ đường nộp thẳng vào `work.db` rồi coi như xong. Làm thế là **giả lập tích
hợp**: hai lược đồ khác nhau về cột, về khoá, về ngữ nghĩa `retrieval_ready`, và
lỗi sẽ hiện ra dưới dạng "điểm thấp" chứ không phải dưới dạng ngoại lệ.

Lớp này làm đúng một việc và khai rõ ràng: đổi **định danh nội bộ** của tầng
truy hồi (`table_uid`) sang **định danh bài nộp** mà BTC chấm, rồi trả về đúng
hai trường `relevant_tables` / `relevant_docs`.

HỢP ĐỒNG ĐỊNH DANH — căn cứ và phần CHƯA ĐÓNG
---------------------------------------------
Thể lệ: `relevant_tables[i] = "<id_báo_cáo>|<vị trí bảng trong báo cáo>"`.

  · `id_báo_cáo` = tên tệp bỏ `_extracted.txt` (= tên thư mục cha).
    Căn cứ: chuỗi BTC tự in trong ví dụ chính thức. `docs/RULES_SOURCES.md` [D-R04].
  · `vị trí bảng` = **số dòng bắt đầu bảng** trong tệp `.txt`.
    Căn cứ: BTC trả lời trực tiếp trong kênh hỏi đáp — *"vị trí bảng ở đây là số
    line bắt đầu bảng trong file ocr báo cáo tương ứng"*. `[D-R05]`.
    Con số `350` trong ví dụ chính thức là **placeholder** (`[F-R01]`: tệp đó có
    1.686 dòng, 47 bảng, dòng 350 trống) — không suy ra ngữ nghĩa từ nó được.

  ⏳ **CHƯA ĐÓNG:** 1-based hay 0-based. Ta phát 1-based, và đã kiểm 400/400
  `evidence_ref` trỏ đúng vào dòng mở `<table>` khi đọc 1-based trên chính
  corpus BTC. Nhưng "nhất quán nội bộ" ≠ "khớp BTC". Chỉ **một lượt nộp** đóng
  được câu này, nên `off_by_one` để chỉnh mà không phải sửa code.

  ⚠ Đừng nhầm với `doc_name|table_N` trong `_codebase/schemas/table_ref.py`. Đó
  là định dạng NỘI BỘ của bộ sinh câu hỏi, và corpus công khai không phát kèm
  cách đánh số ấy (`docs/73` §2 đã rút kết luận sai của `docs/70` §2).

CHÍNH SÁCH N — nộp bao nhiêu bảng
---------------------------------
`F2 = 5PR/(4P+R)` tối ưu khi N = |gold|. Ta không biết `|gold|`, nên ước lượng
`N = clamp(n_mã × n_năm, 1, MAX_N)`: câu một mã một năm nộp 1 bảng, câu sàng lọc
7 mã nộp 7. Đây là ƯỚC LƯỢNG, và nó là biến đáng đo bậc nhất sau khi có gold tay.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from text2pandas.pipelines.retrieval.evalkit.stages import (Bm25StructuralRanker, HardFilterGenerator,
                                      IdentityReranker)
from text2pandas.pipelines.retrieval.policy import (
    MAX_RELEVANT_TABLES,
    submission_table_limit,
)
from text2pandas.pipelines.retrieval.question_intent import parse_intent

__all__ = ["SubmissionRefs", "RetrievalToSubmission", "MAX_N", "to_submission_ref"]

MAX_N = MAX_RELEVANT_TABLES
_REF = re.compile(r"^(?P<doc>.+)\|line:(?P<line>\d+)$")


def to_submission_ref(evidence_ref: str, off_by_one: int = 0) -> str:
    """`DOC|line:1293` → `DOC|1293`. KHÔNG chấp nhận dạng lạ.

    Ném `ValueError` thay vì trả về chuỗi gốc: một `relevant_tables` sai định
    dạng làm mất TRỌN điểm C20 của câu đó, và nó sẽ đi qua mọi kiểm tra kiểu
    "có phải chuỗi không" mà không ai thấy.
    """
    m = _REF.match(evidence_ref)
    if not m:
        raise ValueError(
            f"evidence_ref không đúng dạng '<doc_id>|line:<n>': {evidence_ref!r}")
    return f"{m['doc']}|{int(m['line']) + off_by_one}"


@dataclass(frozen=True, slots=True)
class SubmissionRefs:
    """Đúng những gì bài nộp cần cho một câu, cộng dấu vết để chẩn đoán."""

    qid: int
    relevant_tables: list[str]
    relevant_docs: list[str]
    n_policy: int
    n_candidates: int
    table_uids: list[str]
    ranked_table_uids: list[str]
    trace: dict[str, object] = field(default_factory=dict)

    def as_item(self, question: str, answer: str = "") -> dict:
        """Một phần tử của tệp JSON nộp bài. `answer` để trống là HỢP LỆ ở giai
        đoạn này — C20 (retrieval) chấm độc lập với đáp án."""
        return {"id": self.qid, "question": question, "answer": answer,
                "relevant_docs": self.relevant_docs,
                "relevant_tables": self.relevant_tables}


class RetrievalToSubmission:
    """S0→S3 trên work.db, rồi đổi sang định danh bài nộp.

    `alias` bắt buộc — cùng lý do như `Bm25StructuralRanker` (xem `drop_terms`).
    """

    def __init__(self, alias: dict[str, list[str]], *,
                 top_k_rank: int = 50, top_k_rerank: int = MAX_N,
                 basis_mode: str = "soft", use_hints: str = "code_single",
                 stop_mode: str = "fold", year_slack: int = 1,
                 off_by_one: int = 0, max_n: int = MAX_N):
        self.alias = alias
        self.s1 = HardFilterGenerator(basis_mode=basis_mode, year_slack=year_slack)
        self.s2 = Bm25StructuralRanker(alias, top_k=top_k_rank,
                                       use_hints=use_hints, basis_mode=basis_mode,
                                       stop_mode=stop_mode)
        self.s3 = IdentityReranker(top_k=max(top_k_rerank, max_n))
        self.off_by_one = off_by_one
        self.max_n = max_n

    def n_for(self, intent) -> int:
        return submission_table_limit(
            len(intent.targets), len(intent.retrieval_years), maximum=self.max_n
        )

    def submission_refs_for_uids(
        self,
        conn: sqlite3.Connection,
        table_uids: list[str] | tuple[str, ...],
    ) -> tuple[list[str], list[str]]:
        """Map the exact downstream tables to submission references.

        Retrieval's top-N is only a prior. Once answer binding has selected
        concrete tables, those tables are the authoritative grounding set.
        Publishing the earlier top-N can otherwise make a replayable answer
        cite unrelated tables. First-use order is stable and duplicates fold.
        """
        refs: list[str] = []
        docs: list[str] = []
        seen_uids: set[str] = set()
        for uid in table_uids:
            if uid in seen_uids:
                continue
            seen_uids.add(uid)
            row = conn.execute(
                "SELECT evidence_ref FROM table_cards WHERE table_uid = ?",
                (uid,),
            ).fetchone()
            if row is None or not row[0]:
                raise ValueError(f"table_uid {uid} không có evidence_ref")
            ref = to_submission_ref(row[0], self.off_by_one)
            if ref not in refs:
                refs.append(ref)
            doc = ref.rsplit("|", 1)[0]
            if doc not in docs:
                docs.append(doc)
        return refs, docs

    def refs_for(self, conn: sqlite3.Connection, qid: int,
                 question: str) -> SubmissionRefs:
        it = parse_intent(question, self.alias)
        o1 = self.s1.generate(conn, question, it)
        o2 = self.s2.rank(conn, question, it, o1)
        o3 = self.s3.rerank(conn, question, it, o2)
        n = self.n_for(it)
        ranked = [r.table_uid for r in o3.ranked]
        chon = ranked[:n]
        refs, docs = self.submission_refs_for_uids(conn, chon)
        trace: dict[str, object] = {
            "qid": qid,
            "question": question,
            "intent": {
                "tickers": list(it.ordered_tickers),
                "targets": list(it.targets),
                "years": list(it.years),
                "retrieval_years": list(it.retrieval_years),
                "basis": it.basis,
                "explicit_scope": it.explicit_scope,
                "mode": it.mode,
                "resolved_by": it.resolved_by,
            },
            "s1": {
                "candidate_count": o1.n,
                # Full compact IDs are intentional: a count/hash alone cannot
                # prove whether a later gold table survived the hard filter.
                "candidate_table_ids": sorted(o1.uids),
                "trace": o1.trace,
            },
            "s2": {
                "truncated_at": o2.truncated_at,
                "top_k": [_ranked_item_trace(index, item)
                          for index, item in enumerate(o2.ranked, 1)],
                "trace": o2.trace,
            },
            "s3": {
                "truncated_at": o3.truncated_at,
                "top_k": [_ranked_item_trace(index, item)
                          for index, item in enumerate(o3.ranked, 1)],
                "trace": o3.trace,
            },
            "output_policy": {
                "n": n,
                "reason": "targets_x_years_clamped",
                "n_targets": len(it.targets),
                "n_years": len(it.retrieval_years),
                "maximum": self.max_n,
                "selected_table_ids": chon,
            },
            "submission_refs": {
                "relevant_tables": refs,
                "relevant_docs": docs,
            },
        }
        return SubmissionRefs(qid=qid, relevant_tables=refs, relevant_docs=docs,
                              n_policy=n, n_candidates=o1.n, table_uids=chon,
                              ranked_table_uids=ranked, trace=trace)


def _ranked_item_trace(rank: int, item) -> dict[str, object]:
    """Serialize score contributions without changing ranker behavior."""

    scored = item.scored
    candidate = item.cand
    return {
        "rank": rank,
        "table_uid": item.table_uid,
        "score": item.score,
        "bm25": scored.bm25 if scored is not None else None,
        "reasons": list(item.reasons),
        "period_hit": scored.period_hit if scored is not None else None,
        "unit_hit": scored.unit_hit if scored is not None else None,
        "statement_hit": scored.stmt_hit if scored is not None else None,
        "basis_hit": scored.basis_hit if scored is not None else None,
        "ticker": candidate.ticker if candidate is not None else None,
        "doc_year": candidate.doc_year if candidate is not None else None,
        "basis": candidate.basis if candidate is not None else None,
        "statement_type": candidate.statement_type if candidate is not None else None,
        "clean_ratio": candidate.clean_ratio if candidate is not None else None,
    }
