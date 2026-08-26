"""Chỉ số truy hồi — HÀM THUẦN, không DB, không I/O, test được offline.

Mọi chỉ số ở đây nhận `list[QueryOutcome]` và trả số. Không hàm nào đọc tệp,
không hàm nào mở kết nối. Đó là điều kiện để `tests/test_evalkit_metrics.py`
chạy không cần `work.db` 4,24 GB.

BỐN ĐIỀU PHẢI ĐỌC TRƯỚC KHI TIN MỘT CON SỐ Ở ĐÂY
------------------------------------------------
1. `F2@N` dùng CÔNG THỨC THẬT của BTC, rút gọn:

       P = h/N · R = h/g · F2 = 5PR/(4P+R) = 5h/(4g+N)

   Không phải `f2(precision_macro, recall_macro)`. Trung bình rồi mới ghép hai
   chỉ số cho ra số KHÁC với ghép từng câu rồi mới trung bình, và BTC nói rõ
   "macro-average (tính chỉ số cho từng truy vấn rồi lấy trung bình)".
   `eval_retrieval.py:167` đang làm cách sai — chênh lệch đo được ở §báo cáo.

2. `Precision@K` có HAI biến thể, và phải đọc đúng cái:
     · `precision_at_k`        = h/K            — định nghĩa của BTC
     · `precision_at_k_capped` = h/min(K, g)    — trần đạt được khi g < K
   Với proxy gold median 8 bảng, biến thể đầu LẠC QUAN CÓ HỆ THỐNG. Biến thể
   sau cho biết "trong số chỗ có thể đúng, ta đúng bao nhiêu".

3. Mọi chỉ số nhận `denominator_note`: số câu tính được / tổng số câu. Một
   chỉ số không kèm mẫu số là một chỉ số nói dối — nó im lặng bỏ đi phần khó.

4. `NDCG@K` dùng relevance NHỊ PHÂN với g item liên quan:
       IDCG@K = Σ_{i=1..min(g,K)} 1/log2(i+1)
   Không chuẩn hoá theo `min(g,K)` thì câu có g=32 không bao giờ đạt 1,0 và
   NDCG biến thành hàm của kích thước gold thay vì của chất lượng xếp hạng.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "QueryOutcome", "MetricBlock",
    "candidate_hit_rate", "recall_at_k", "precision_at_k",
    "precision_at_k_capped", "f2_at_k", "f2_from_pr", "mrr", "mrr_at_k",
    "ndcg_at_k",
    "metric_block", "gold_size_stats", "f2_at_policy", "hit_rate_at_policy",
]


@dataclass(frozen=True, slots=True)
class QueryOutcome:
    """Kết quả một câu, ĐỦ để dựng lại mọi chỉ số mà không cần quét lại DB.

    `hits_at` là các vị trí 1-based trong bảng xếp hạng cuối có bảng gold.
    `n_gold` là |gold| — bắt buộc để tính F2 thật (mẫu số `4g+N`).
    `n_ranked` là số bảng thực sự trả về; với câu bị cắt ngắn thì N < K.
    """

    qid: int
    mode: str
    n_gold: int
    n_candidates: int          # |s1_uids| — tập ứng viên ĐẦY ĐỦ, trước khi cắt
    gold_in_candidates: bool
    n_ranked: int
    hits_at: tuple[int, ...] = ()
    measurable: bool = True    # dựng được gold tin cậy hay không

    @property
    def best_rank(self) -> int | None:
        return min(self.hits_at) if self.hits_at else None

    def hits_within(self, k: int) -> int:
        return sum(1 for h in self.hits_at if h <= k)

    def n_returned(self, k: int) -> int:
        """Số bảng thực nộp nếu chính sách là top-k. Không bao giờ vượt n_ranked."""
        return min(k, self.n_ranked)


@dataclass(frozen=True, slots=True)
class MetricBlock:
    """Một khối chỉ số kèm MẪU SỐ. Không tách hai thứ này ra được."""

    n_measured: int
    n_total: int
    candidate_hit_rate: float
    mrr: float
    per_k: dict[int, dict[str, float]] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        return self.n_measured / self.n_total if self.n_total else 0.0


def _measurable(rows: list[QueryOutcome]) -> list[QueryOutcome]:
    return [r for r in rows if r.measurable and r.n_gold > 0]


def candidate_hit_rate(rows: list[QueryOutcome]) -> float:
    """Tỷ lệ câu mà LỌC CỨNG còn giữ ≥1 bảng gold.

    Đo trên tập ứng viên ĐẦY ĐỦ (`n_candidates`/`gold_in_candidates`), KHÔNG
    trên danh sách đã cắt top-K. Đo trên danh sách đã cắt là đo lại `Recall@K`
    dưới một cái tên khác — hai lỗi khác nhau, hai cách sửa khác nhau.
    """
    m = _measurable(rows)
    return sum(1 for r in m if r.gold_in_candidates) / len(m) if m else 0.0


def recall_at_k(rows: list[QueryOutcome], k: int) -> float:
    """Macro-recall: trung bình của `h/g` từng câu (KHÔNG phải hit-rate)."""
    m = _measurable(rows)
    if not m:
        return 0.0
    return sum(r.hits_within(k) / r.n_gold for r in m) / len(m)


def hit_rate_at_k(rows: list[QueryOutcome], k: int) -> float:
    """Tỷ lệ câu có ÍT NHẤT MỘT bảng gold trong top-K.

    Khác `recall_at_k` khi g > 1. Với gold thật 1 bảng thì hai chỉ số trùng
    nhau; với proxy gold median 8 thì chúng KHÁC NHAU đáng kể, và
    `eval_retrieval.py:164` đang in cái này dưới nhãn "Recall@K".
    """
    m = _measurable(rows)
    if not m:
        return 0.0
    return sum(1 for r in m if r.hits_within(k) > 0) / len(m)


def precision_at_k(rows: list[QueryOutcome], k: int) -> float:
    """`h/N` với N = số bảng thực nộp. Định nghĩa của BTC."""
    m = _measurable(rows)
    if not m:
        return 0.0
    tot = 0.0
    for r in m:
        n = r.n_returned(k)
        tot += r.hits_within(k) / n if n else 0.0
    return tot / len(m)


def precision_at_k_capped(rows: list[QueryOutcome], k: int) -> float:
    """`h/min(K, g)` — trần đạt được. Dùng để tách "xếp hạng kém" khỏi "K > g"."""
    m = _measurable(rows)
    if not m:
        return 0.0
    tot = 0.0
    for r in m:
        den = min(r.n_returned(k), r.n_gold)
        tot += r.hits_within(k) / den if den else 0.0
    return tot / len(m)


def f2_from_pr(p: float, r: float) -> float:
    """`5PR/(4P+R)`. CHỈ dùng cho một câu, không dùng cho hai số đã macro."""
    return 0.0 if p + r <= 0 else 5 * p * r / (4 * p + r)


def f2_at_k(rows: list[QueryOutcome], k: int) -> float:
    """Macro-F2 THẬT: trung bình của `5h/(4g+N)` từng câu.

    Đây là con số dự báo điểm F2 của BTC nếu ta nộp top-k cho mọi câu. Nó
    KHÔNG bằng `f2_from_pr(precision_at_k, recall_at_k)`.
    """
    m = _measurable(rows)
    if not m:
        return 0.0
    tot = 0.0
    for r in m:
        n = r.n_returned(k)
        den = 4 * r.n_gold + n
        tot += 5 * r.hits_within(k) / den if den else 0.0
    return tot / len(m)


def f2_at_policy(rows: list[QueryOutcome],
                 n_of: dict[int, int] | None = None) -> float:
    """F2 dưới CHÍNH SÁCH N THẬT của bài nộp — bộ SO SÁNH TƯƠNG ĐỐI tốt nhất.

    ĐỌC CHO ĐÚNG: đây KHÔNG phải dự báo điểm tuyệt đối. Trên proxy gold có
    `|gold|` median 8, mẫu số `4g` bị phồng lên ~8× so với gold thật 1 bảng, nên
    `F2@N*` **bi quan có hệ thống** (đo được: 0,2141 trong khi slice `|gold|=1`
    cho 0,4921). Dùng nó để so HAI CẤU HÌNH; dùng `f2_at_k` trên slice `g==1` để
    ước lượng điểm tuyệt đối.

    VÌ SAO `F2@K` KHÔNG ĐỦ
    ---------------------
    `F2@K` giả định nộp CÙNG một K cho mọi câu. Bài nộp thật thì không:
    `tools/rewrite_submission.py` dùng `N = clamp(n_mã × n_năm, 1, 10)`, nên câu
    `single` một năm nộp 1 bảng còn câu `screen` 7 mã nộp 7 bảng. Chọn cấu hình
    theo `F2@10` là chọn theo một chính sách KHÔNG được dùng — và hai chính sách
    có thể xếp hạng các cấu hình theo thứ tự KHÁC NHAU.

    Đã xảy ra thật khi so `base` với `basis_hard`: `F2@1` nói `basis_hard` tốt hơn
    (+0,0014) còn `F2@10` nói tệ hơn rõ rệt (−0,0446). Không con số nào trong hai
    con số đó trả lời được câu hỏi "nộp cái nào thì điểm cao hơn".

    `n_of` là map `qid → N`. Thiếu qid nào thì mặc định N = số bảng đã xếp hạng.
    """
    m = _measurable(rows)
    if not m:
        return 0.0
    n_of = n_of or {}
    tot = 0.0
    for r in m:
        n = min(n_of.get(r.qid, r.n_ranked), r.n_ranked)
        den = 4 * r.n_gold + n
        tot += 5 * r.hits_within(n) / den if den else 0.0
    return tot / len(m)


def hit_rate_at_policy(rows: list[QueryOutcome],
                       n_of: dict[int, int] | None = None) -> float:
    """Tỷ lệ câu có ≥1 gold trong N bảng THẬT SẼ NỘP."""
    m = _measurable(rows)
    if not m:
        return 0.0
    n_of = n_of or {}
    ok = 0
    for r in m:
        n = min(n_of.get(r.qid, r.n_ranked), r.n_ranked)
        ok += 1 if r.hits_within(n) > 0 else 0
    return ok / len(m)


def mrr(rows: list[QueryOutcome]) -> float:
    """Reciprocal rank của bảng gold ĐẦU TIÊN, 0 nếu không có trong xếp hạng."""
    m = _measurable(rows)
    if not m:
        return 0.0
    return sum(1.0 / r.best_rank for r in m if r.best_rank) / len(m)


def mrr_at_k(rows: list[QueryOutcome], k: int) -> float:
    """MRR trên cùng một cutoff K.

    So sánh hai stage chỉ hợp lệ khi cùng cutoff. Nếu S2 giữ top-50 còn S3 giữ
    top-10, `mrr(S2)` và `mrr(S3)` có sample space khác nhau: một gold ở hạng
    12 đóng góp cho S2 nhưng bị truncation khỏi S3, dù reranker không đổi thứ
    tự. `mrr_at_k` loại sai lệch đo lường đó.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    m = _measurable(rows)
    if not m:
        return 0.0
    return sum(
        1.0 / r.best_rank
        for r in m
        if r.best_rank is not None and r.best_rank <= k
    ) / len(m)


def ndcg_at_k(rows: list[QueryOutcome], k: int) -> float:
    """NDCG@K, relevance nhị phân, IDCG chuẩn hoá theo `min(g, K)`."""
    m = _measurable(rows)
    if not m:
        return 0.0
    tot = 0.0
    for r in m:
        dcg = sum(1.0 / math.log2(h + 1) for h in r.hits_at if h <= k)
        ideal = min(r.n_gold, k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal))
        tot += dcg / idcg if idcg else 0.0
    return tot / len(m)


def gold_size_stats(rows: list[QueryOutcome]) -> dict[str, float]:
    """Phân bố |gold|. `n_exactly_one` là con số quyết định đọc Precision thế nào."""
    m = _measurable(rows)
    if not m:
        return {}
    g = sorted(r.n_gold for r in m)
    n = len(g)
    return {
        "n": n,
        "min": g[0], "median": g[n // 2],
        "p90": g[min(int(0.9 * n), n - 1)], "max": g[-1],
        "mean": sum(g) / n,
        "n_exactly_one": sum(1 for x in g if x == 1),
        "pct_exactly_one": 100.0 * sum(1 for x in g if x == 1) / n,
    }


def metric_block(rows: list[QueryOutcome], ks: tuple[int, ...],
                 n_total: int | None = None) -> MetricBlock:
    m = _measurable(rows)
    per_k = {
        k: {
            "hit_rate": hit_rate_at_k(rows, k),
            "recall": recall_at_k(rows, k),
            "precision": precision_at_k(rows, k),
            "precision_capped": precision_at_k_capped(rows, k),
            "f2": f2_at_k(rows, k),
            "ndcg": ndcg_at_k(rows, k),
        }
        for k in ks
    }
    return MetricBlock(
        n_measured=len(m),
        n_total=n_total if n_total is not None else len(rows),
        candidate_hit_rate=candidate_hit_rate(rows),
        mrr=mrr(rows),
        per_k=per_k,
    )
