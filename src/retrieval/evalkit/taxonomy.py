"""Phân loại thất bại — quy trách nhiệm mỗi câu về ĐÚNG MỘT tầng.

VÌ SAO CẦN MỘT BẢNG PHÂN LOẠI, KHÔNG PHẢI MỘT CON SỐ
----------------------------------------------------
"Recall@10 = 93%" không nói được phải sửa gì. Ba loại lỗi dưới đây đòi ba cách
sửa hoàn toàn khác nhau, và gộp chúng vào một con số là mù:

  · gold bị LỌC CỨNG loại   → nới mệnh đề lọc. Không tầng sau nào cứu được.
  · gold có trong ứng viên nhưng RỚT TOP-K → chỉnh trọng số / thêm rerank.
  · KHÔNG DỰNG ĐƯỢC GOLD    → không phải lỗi truy hồi. Là lỗi THƯỚC ĐO.

Điều thứ ba là điều `eval_retrieval.py` làm sai nghiêm trọng nhất: nó lọc
`n_gold > 0 and n_gold <= 60 and n_gold_cells < 400` rồi **im lặng bỏ 81 câu**
khỏi mọi con số. Một câu mà S0 phân giải sai mã sẽ có gold RỖNG, và vì thế
KHÔNG bị tính là miss — nó biến mất. Bảng phân loại ở đây bắt buộc mọi câu
phải rơi vào đúng một nhãn, tổng luôn bằng 1.012.

MỘT NHÃN, KHÔNG HAI
-------------------
Thứ tự kiểm là thứ tự ƯU TIÊN, và nó không tuỳ ý: một câu vừa không có gold
vừa không có ứng viên thì lỗi ĐÁNG SỬA là cái sau, nhưng lỗi ĐÁNG BÁO là cái
trước — vì không có gold thì ta không biết ứng viên rỗng có hại hay không.
Nên `NO_GOLD` được kiểm TRƯỚC, và cờ `also_no_candidate` giữ lại thông tin kia.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

__all__ = ["Bucket", "NoGoldReason", "Diagnosis", "classify", "TOP_K_DEFAULT"]

TOP_K_DEFAULT = 10


class _StrEnum(str, Enum):
    """`enum.StrEnum` chỉ có từ Python 3.11. Máy build chạy 3.10.12.

    Mixin `str` cho cùng hành vi ở mọi chỗ ta dùng (so sánh, `.value`, khoá
    dict, `json.dumps`). Khác biệt duy nhất là `str(x)` trả `'Bucket.SUCCESS'`
    thay vì `'F5_SUCCESS'`, nên MỌI nơi ghi ra tệp đều dùng `.value` tường minh
    — không dựa vào `__str__`.
    """

    def __str__(self) -> str:            # để `f"{bucket}"` cũng ra giá trị thật
        return str(self.value)


class Bucket(_StrEnum):
    """Sáu rổ, phủ kín và đôi một rời nhau."""

    NO_GOLD = "F0_NO_GOLD"                    # không đo được — lỗi thước đo
    NO_CANDIDATE = "F1_NO_CANDIDATE"          # S1 trả tập rỗng
    HARD_FILTER_DROP = "F2_HARD_FILTER_DROP"  # gold bị lọc cứng loại
    RANK_MISS = "F3_RANK_MISS"                # có ứng viên, rớt top-K
    RERANK_MISS = "F4_RERANK_MISS"            # vào top-K của ranker, rớt sau rerank
    SUCCESS = "F5_SUCCESS"                    # gold trong top-K


class NoGoldReason(_StrEnum):
    NO_CONTENT_TERMS = "no_content_terms"     # câu hỏi không còn từ nội dung nào
    NO_PHRASE_MATCH = "no_phrase_match"       # không cụm nào khớp nhãn dòng
    SATURATED = "gold_saturated"              # gold quá lớn / chạm trần LIMIT
    UNTRUSTED_SIZE = "gold_too_large"         # |gold| > ngưỡng tin cậy
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    qid: int
    bucket: Bucket
    mode: str
    n_candidates: int
    n_gold: int
    best_rank: int | None = None
    no_gold_reason: NoGoldReason | None = None
    also_no_candidate: bool = False
    # Mệnh đề lọc cứng đã loại bảng gold — quy trách nhiệm cho ĐÚNG mệnh đề,
    # không đoán. Rỗng nghĩa là chưa chạy attribution hoặc không mệnh đề nào khớp.
    drop_clauses: tuple[str, ...] = ()
    # Nghi vấn phân giải thực thể: quét tự do tìm được bảng khớp cụm nhưng
    # KHÔNG mã nào trùng `Intent.targets`. Tín hiệu ĐỘC LẬP với S1.
    entity_suspect: bool = False
    notes: dict = field(default_factory=dict)

    @property
    def is_failure(self) -> bool:
        return self.bucket is not Bucket.SUCCESS

    @property
    def is_measurable(self) -> bool:
        return self.bucket is not Bucket.NO_GOLD


def classify(*, qid: int, mode: str, n_candidates: int, n_gold: int,
             gold_in_candidates: bool, hits_at: tuple[int, ...],
             hits_at_pre_rerank: tuple[int, ...] | None = None,
             top_k: int = TOP_K_DEFAULT,
             no_gold_reason: NoGoldReason | None = None,
             drop_clauses: tuple[str, ...] = (),
             entity_suspect: bool = False,
             notes: dict | None = None) -> Diagnosis:
    """Gán ĐÚNG MỘT nhãn. Thứ tự kiểm là thứ tự ưu tiên, xem docstring module."""
    common = dict(qid=qid, mode=mode, n_candidates=n_candidates, n_gold=n_gold,
                  best_rank=min(hits_at) if hits_at else None,
                  entity_suspect=entity_suspect, notes=notes or {})

    if n_gold == 0 or no_gold_reason is not None:
        return Diagnosis(bucket=Bucket.NO_GOLD,
                         no_gold_reason=no_gold_reason or NoGoldReason.NO_PHRASE_MATCH,
                         also_no_candidate=(n_candidates == 0),
                         drop_clauses=drop_clauses, **common)

    if n_candidates == 0:
        return Diagnosis(bucket=Bucket.NO_CANDIDATE, drop_clauses=drop_clauses,
                         also_no_candidate=True, **common)

    if not gold_in_candidates:
        return Diagnosis(bucket=Bucket.HARD_FILTER_DROP,
                         drop_clauses=drop_clauses, **common)

    if any(h <= top_k for h in hits_at):
        return Diagnosis(bucket=Bucket.SUCCESS, **common)

    # Vào được top-K TRƯỚC rerank rồi bị đẩy ra: đó là lỗi của rerank, không
    # phải của ranker. Tách ra vì hai tầng, hai cách sửa.
    if hits_at_pre_rerank and any(h <= top_k for h in hits_at_pre_rerank):
        return Diagnosis(bucket=Bucket.RERANK_MISS, **common)

    return Diagnosis(bucket=Bucket.RANK_MISS, **common)


def summarize(diags: list[Diagnosis]) -> dict[str, int]:
    """Đếm theo rổ. Tổng LUÔN bằng len(diags) — đó là bất biến của bảng này."""
    out = {b.value: 0 for b in Bucket}
    for d in diags:
        out[d.bucket.value] += 1
    assert sum(out.values()) == len(diags), "bảng phân loại phải phủ kín"
    return out
