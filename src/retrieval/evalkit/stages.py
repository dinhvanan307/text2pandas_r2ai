"""Tách BẠCH ba tầng: sinh ứng viên (lọc cứng) · xếp hạng · xếp hạng lại.

VÌ SAO PHẢI TÁCH BẰNG KIỂU, KHÔNG PHẢI BẰNG QUY ƯỚC
---------------------------------------------------
`pipeline.run` gộp S0+S1+S2 vào một hàm và trả một `Result`. Tiện để chạy,
nhưng làm hai việc trở nên bất khả thi:

  1. đo `Recall@K` SAU TỪNG TẦNG (không biết tầng nào làm mất thì không sửa được);
  2. thay một tầng mà giữ nguyên các tầng khác (A/B đúng một biến).

Nên ở đây mỗi tầng là một `Protocol` với hợp đồng vào/ra rõ ràng, và tầng nào
cũng phải trả `StageOutput` mang theo `candidates` + `trace`. Runner gọi lần
lượt và chụp ảnh sau mỗi tầng.

BA HỢP ĐỒNG, KHÔNG ĐƯỢC LẪN
---------------------------
  CandidateGenerator  → TẬP (không thứ tự). Đây là chỗ recall được quyết định.
                        Mất ở đây là mất hẳn. KHÔNG cắt, KHÔNG sort.
  Ranker              → DÃY có thứ tự, có điểm. Cắt được, nhưng phải khai cắt ở đâu.
  Reranker            → DÃY có thứ tự, đầu vào là đầu ra của Ranker.
                        Mặc định là IdentityReranker để đường đi luôn chạy thông
                        trước khi có model — và để `F4_RERANK_MISS` luôn = 0 một
                        cách có thể kiểm chứng, chứ không phải vì quên đo.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from retrieval.filter_s1 import Candidate, filter_tables
from retrieval.metric_hint import metric_codes_hint, statement_hint
from retrieval.query_terms import build_match, content_terms, drop_terms
from retrieval.question_intent import Intent
from retrieval.rank_s2 import PRIMARY_KINDS, Scored, rank

__all__ = [
    "StageOutput", "RankedItem", "CandidateGenerator", "Ranker", "Reranker",
    "HardFilterGenerator", "Bm25StructuralRanker", "IdentityReranker",
    "unit_kind_of", "period_ends_of",
]

_UNIT_KIND = {"tỷ đồng": "money", "triệu đồng": "money", "nghìn đồng": "money",
              "đồng": "money", "%": "percent", "phần trăm": "percent",
              "cổ phiếu": "shares", "lần": None}


def unit_kind_of(question: str) -> str | None:
    low = question.lower()
    for k, v in _UNIT_KIND.items():
        if k in low:
            return v
    return None


def period_ends_of(years: tuple[int, ...]) -> tuple[str, ...]:
    """Giả định năm tài chính = năm dương lịch. Đúng với corpus này (đã kiểm
    trên `documents.doc_year`), nhưng là GIẢ ĐỊNH — ghi ở đúng một chỗ để khi
    sai thì chỉ phải sửa một chỗ."""
    return tuple(f"{y}-12-31" for y in years)


@dataclass(frozen=True, slots=True)
class RankedItem:
    """`scored` mang NGUYÊN đối tượng `Scored` của tầng xếp hạng, nếu có.

    Vì sao không chỉ giữ `score` + `reasons`: `pipeline.run` phải trả `Scored`
    cho hai script cũ. Nếu ở đây bỏ mất `bm25`/`period_hit`/`unit_hit`/
    `stmt_hit`/`basis_hit` thì `pipeline.run` buộc phải DỰNG LẠI bằng giá trị
    giả (`0.0`/`False`) — không script nào hiện đọc chúng, nhưng một trường
    mang giá trị giả mà trông như thật là cái bẫy y hệt lớp lỗi P0-2 vừa sửa.
    Giữ nguyên đối tượng thì không phải nói dối.
    """

    table_uid: str
    score: float
    reasons: tuple[str, ...] = ()
    cand: Candidate | None = None
    scored: Scored | None = None


@dataclass(frozen=True, slots=True)
class StageOutput:
    """`uids` là TẬP đầy đủ tầng này còn giữ. `ranked` chỉ có ở tầng xếp hạng.

    Hai trường tách nhau vì `candidate recall` phải đo trên `uids` còn
    `Recall@K` phải đo trên `ranked`. Gộp lại là nguồn của đúng lỗi phương pháp
    mà `docs/74` §2 đã phải tự sửa một lần.
    """

    stage: str
    uids: frozenset[str]
    ranked: tuple[RankedItem, ...] = ()
    truncated_at: int | None = None
    trace: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.uids)

    def positions_of(self, gold: frozenset[str]) -> tuple[int, ...]:
        """Vị trí 1-based của bảng gold trong `ranked`."""
        return tuple(i + 1 for i, it in enumerate(self.ranked)
                     if it.table_uid in gold)


@runtime_checkable
class CandidateGenerator(Protocol):
    name: str

    def generate(self, conn: sqlite3.Connection, question: str,
                 intent: Intent) -> StageOutput: ...


@runtime_checkable
class Ranker(Protocol):
    name: str

    def rank(self, conn: sqlite3.Connection, question: str, intent: Intent,
             upstream: StageOutput) -> StageOutput: ...


@runtime_checkable
class Reranker(Protocol):
    name: str

    def rerank(self, conn: sqlite3.Connection, question: str, intent: Intent,
               upstream: StageOutput) -> StageOutput: ...


class HardFilterGenerator:
    """S1 · lọc cứng. Trả TẬP ĐẦY ĐỦ — không cắt, không sort.

    `basis_mode="soft"` (mặc định) bỏ `basis` khỏi mệnh đề WHERE và để nó thành
    điểm cộng ở tầng xếp hạng. Đo được: candidate recall 97,42% → 99,68%.
    """

    name = "s1_hard_filter"

    def __init__(self, basis_mode: str = "soft", year_slack: int = 1):
        if basis_mode not in ("soft", "hard"):
            raise ValueError(f"basis_mode phải là soft|hard, nhận {basis_mode!r}")
        self.basis_mode = basis_mode
        self.year_slack = year_slack

    def generate(self, conn, question: str, intent: Intent) -> StageOutput:
        loc_basis = intent.basis if self.basis_mode == "hard" else None
        cands = filter_tables(conn, intent.targets, intent.years, loc_basis,
                              year_slack=self.year_slack)
        return StageOutput(
            stage=self.name,
            uids=frozenset(c.table_uid for c in cands),
            trace={
                "basis_mode": self.basis_mode,
                "basis_applied": loc_basis,
                "targets": list(intent.targets),
                "years": list(intent.years),
                "year_slack": self.year_slack,
                "n_candidates": len(cands),
                # Mệnh đề đang thực sự hoạt động — để không ai lại tin rằng
                # `retrieval_ready=1` đang lọc gì (146.246/146.246 đạt = no-op).
                "active_clauses": self._active_clauses(intent, loc_basis),
            },
            ranked=tuple(RankedItem(c.table_uid, 0.0, (), c) for c in cands),
        )

    @staticmethod
    def _active_clauses(intent: Intent, loc_basis: str | None) -> list[str]:
        out = ["ticker"]
        if loc_basis:
            out.append("basis")
        if intent.years:
            out.append("doc_year")
        out.append("retrieval_ready:NOOP")
        return out


class Bm25StructuralRanker:
    """S2 · BM25 theo cột + tín hiệu cấu trúc. Cắt ở `top_k` và KHAI ra."""

    name = "s2_bm25_structural"

    def __init__(self, alias: dict[str, list[str]], *,
                 top_k: int = 50, use_hints: str = "code_single",
                 basis_mode: str = "soft", weights=None, bonuses=None,
                 norm: str | None = None, per_ticker_k: int | None = None,
                 fanout_modes: tuple[str, ...] = ("screen", "compare"),
                 stop_mode: str = "fold",
                 primary_boost: float = 0.0,
                 primary_modes: tuple[str, ...] = ("screen", "related"),
                 primary_kinds: frozenset[str] | None = None,
                 alias_rong_co_y: bool = False):
        # `alias` là THAM SỐ ĐẦU, BẮT BUỘC, VỊ TRÍ — không có mặc định.
        #
        # Bản trước để `alias=None` ở cuối danh sách keyword. Hệ quả: quên nó thì
        # ranker vẫn dựng được, vẫn chạy, vẫn trả kết quả — chỉ là kết quả SAI
        # (tên công ty còn trong truy vấn BM25, −0,0706 hit@1). Đó đúng là hình
        # dạng của regression vừa mất ba phiên để tìm: một mặc định "an toàn"
        # cho phép chạy sai âm thầm.
        #
        # Mặc định an toàn phải là KHÔNG CHẠY ĐƯỢC. Muốn tái hiện hành vi cũ
        # (test cơ chế) thì phải viết ra một cờ có tên nói đúng việc nó làm.
        if alias is None:
            raise TypeError(
                "Bm25StructuralRanker cần `alias` = {ticker: [tên, …]} từ "
                "`alias_store.load_aliases`. Thiếu nó thì tên công ty còn lại "
                "trong truy vấn BM25 và mất ~0,07 hit@1 — xem query_terms.drop_terms."
            )
        if not alias and not alias_rong_co_y:
            raise ValueError(
                "`alias` rỗng. Đây gần như luôn là lỗi nạp (sai đường dẫn, sai "
                "cờ `brands`). Nếu CỐ Ý muốn hành vi 'không loại tên công ty' — "
                "chỉ dùng cho test cơ chế — hãy truyền alias_rong_co_y=True."
            )
        self.alias = alias
        self.alias_rong_co_y = alias_rong_co_y
        self.top_k = top_k
        self.use_hints = use_hints
        self.basis_mode = basis_mode
        self.weights = weights
        self.bonuses = bonuses
        self.norm = norm
        # Fan-out CHỈ cho câu nhiều thực thể. Áp cho `single` là vô nghĩa (một
        # mã ⇒ `_fanout_by_ticker` trả về nguyên trạng) nhưng khai tường minh để
        # không ai phải đoán, và để A/B được từng nhóm.
        self.per_ticker_k = per_ticker_k
        self.fanout_modes = fanout_modes
        # `fold` (mặc định) đối chiếu STOP với dạng bỏ dấu — nuốt oan từ nội
        # dung ở 61,4% số câu. `dau` sửa điều đó. Xem `query_terms.STOP_DAU`.
        self.stop_mode = stop_mode
        # Tiên nghiệm lớp báo cáo, CHỈ cho `primary_modes`. 0.0 = tắt.
        self.primary_boost = primary_boost
        self.primary_modes = primary_modes
        self.primary_kinds = (PRIMARY_KINDS if primary_kinds is None
                              else frozenset(primary_kinds))

    def rank(self, conn, question: str, intent: Intent,
             upstream: StageOutput) -> StageOutput:
        cands = [it.cand for it in upstream.ranked if it.cand is not None]
        if not cands:
            return StageOutput(stage=self.name, uids=frozenset(),
                               trace={"reason": "upstream_empty"})
        drop = drop_terms(intent.targets, self.alias)
        terms = content_terms(question, drop=drop, stop_mode=self.stop_mode)
        don_the = intent.mode in ("single", "related")
        dung_code = (self.use_hints in ("both", "code")
                     or (self.use_hints == "code_single" and don_the))
        scored: list[Scored] = rank(
            conn, cands, build_match(terms), period_ends_of(intent.years),
            unit_kind_of(question),
            statement_hint(question) if self.use_hints in ("both", "stmt") else None,
            self.top_k,
            basis_hint=None if self.basis_mode == "hard" else intent.basis,
            code_hint=metric_codes_hint(question) if dung_code else frozenset(),
            weights=self.weights,
            # LỖI ĐÃ XẢY RA THẬT: bản đầu chỉ truyền `primary_kinds` mà quên đưa
            # ĐỘ LỚN vào `bonuses`. `BONUSES["primary"]` mặc định 0.0 nên lý do
            # "primary" vẫn hiện trong `reasons`, điểm vẫn y nguyên, và cả một
            # lượt quét 4 giá trị boost trả về Δ = 0,0000 tuyệt đối — dấu hiệu
            # duy nhất cho thấy knob không nối. Giữ hai thứ ở CÙNG một chỗ.
            bonuses={**(self.bonuses or {}), "primary": self.primary_boost},
            norm=self.norm,
            per_ticker_k=(self.per_ticker_k
                          if self.per_ticker_k and intent.mode in self.fanout_modes
                          else None),
            primary_kinds=(self.primary_kinds
                           if self.primary_boost and intent.mode in self.primary_modes
                           else frozenset()),
        )
        return StageOutput(
            stage=self.name,
            uids=frozenset(s.cand.table_uid for s in scored),
            ranked=tuple(RankedItem(s.cand.table_uid, s.score, s.reasons, s.cand, s)
                         for s in scored),
            truncated_at=self.top_k,
            trace={
                "n_terms": len(terms), "terms": terms[:12],
                "use_hints": self.use_hints, "code_applied": dung_code,
                "norm": self.norm or "minmax", "stop_mode": self.stop_mode,
                "primary_boost": (self.primary_boost
                                  if intent.mode in self.primary_modes else 0.0),
                "fanout_k": (self.per_ticker_k
                             if self.per_ticker_k and intent.mode in self.fanout_modes
                             else None),
                "n_in": len(cands), "n_out": len(scored),
                # Phơi ra để đọc checkpoint là biết ngay có nạp alias hay không —
                # thiếu nó là regression mất ~7 điểm hit@1, và nó từng sống sót
                # ba phiên vì không có dấu vết nào trong dữ liệu đo.
                "alias_loaded": bool(self.alias),
                "n_drop": len(drop),
            },
        )


class IdentityReranker:
    """S3 · CHƯA CÓ MODEL. Đi qua không đổi thứ hạng, chỉ cắt về `top_k`.

    Tồn tại để đường đi S1→S2→S3 chạy thông và `F4_RERANK_MISS` là một con số
    ĐO ĐƯỢC (bằng 0) chứ không phải một ô trống vì quên. Khi cắm cross-encoder
    vào, chỉ thay lớp này — không tệp nào khác phải sửa.
    """

    name = "s3_identity"

    def __init__(self, top_k: int = 10):
        self.top_k = top_k

    def rerank(self, conn, question: str, intent: Intent,
               upstream: StageOutput) -> StageOutput:
        keep = upstream.ranked[:self.top_k]
        return StageOutput(
            stage=self.name, uids=frozenset(it.table_uid for it in keep),
            ranked=keep, truncated_at=self.top_k,
            trace={"model": None, "passthrough": True,
                   "n_in": len(upstream.ranked), "n_out": len(keep)},
        )
