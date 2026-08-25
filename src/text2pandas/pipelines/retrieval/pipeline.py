"""S0 → S1 → S2 · LỚP MỎNG gọi `evalkit.stages`, giữ nguyên API cũ.

VÌ SAO TỆP NÀY KHÔNG CÒN CÀI GÌ NỮA — P0-2
------------------------------------------
Trước đây tệp này cài S0+S1+S2 độc lập với `evalkit/stages.py`. **Hai cài đặt
cùng một logic, và chúng đã trôi dạt**: đo trên 30 câu, S1 giống 30/30 nhưng
**S2 chỉ giống 12/30**. Nguyên nhân duy nhất là luật `drop` bị viết ở hai chỗ —
`evalkit` thiếu alias tên công ty, mất **~9 điểm hit@1** (xem
`query_terms.drop_terms`).

Trôi dạt kiểu này **không ném ngoại lệ, không sai cú pháp, không test nào đỏ**.
Nó chỉ hiện ra khi có người so hai cài đặt với nhau. Nên cách sửa không phải
"đồng bộ lại hai bên" — đó là mời lỗi quay lại — mà là **xoá hẳn một bên**.

Nay `run()` chỉ:
  1. `parse_intent`                            (S0)
  2. `HardFilterGenerator.generate`            (S1)
  3. `Bm25StructuralRanker.rank`               (S2)
và gói kết quả về `Result` để hai script cũ (`eval_retrieval.py`,
`diag_s1_miss.py`) không phải sửa. **Không còn đường code thứ hai.**

`tests/test_p0_unify.py` khoá bất biến: `run()` và stages phải cho ĐÚNG cùng
`table_uid` + cùng thứ tự.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from text2pandas.pipelines.retrieval.evalkit.stages import (Bm25StructuralRanker, HardFilterGenerator,
                                      unit_kind_of)
from text2pandas.pipelines.retrieval.question_intent import Intent, parse_intent
from text2pandas.pipelines.retrieval.rank_s2 import Scored

__all__ = ["Result", "run"]


@dataclass(frozen=True, slots=True)
class Result:
    """`s1_uids` là TẬP ỨNG VIÊN ĐẦY ĐỦ của S1, trước khi cắt top-K.

    Phải phơi ra thì `candidate recall` mới đo được đúng. Đo trên `hits` là đo
    lại `Recall@top_k` dưới một cái tên khác — hai lỗi khác nhau, hai cách sửa
    khác nhau, gộp vào là mù.
    """

    intent: Intent
    n_s1: int
    hits: list[Scored]
    s1_uids: frozenset[str]


def run(conn: sqlite3.Connection, question: str, alias: dict,
        top_k: int = 50, basis_mode: str = "soft",
        use_hints: str = "code_single",
        primary_boost: float = 0.00,
        primary_modes: tuple[str, ...] = ("screen", "related")) -> Result:
    """Hai tham số dưới đây là hai quyết định ĐÃ ĐO, không phải sở thích.

    `basis_mode`
      hard  · `basis` là BỘ LỌC CỨNG ở S1 (mặc định `hợp nhất` khi câu im lặng)
      soft  · `basis` chỉ là ĐIỂM CỘNG ở S2; S1 giữ cả hai phạm vi  ← MẶC ĐỊNH

    Thể lệ BTC KHÔNG nói gì về phạm vi mặc định — định nghĩa "liên quan" của họ
    chỉ là "bảng chứa số liệu cần để tính ra đáp án". Mặc định `hợp nhất` là
    GIẢ ĐỊNH CỦA TA, và một giả định sai ở tầng lọc cứng thì mất trắng.
    Đo đủ 1.012 câu, ghép cặp theo id: `hard` mất **0,0219 candidate hit rate**
    (~22 câu mất gold VĨNH VIỄN) để đổi **+0,0080 hit@1**. Dưới F2 (recall nặng
    gấp 4) và với thực tế "mất ở lọc cứng thì không tầng nào cứu", đây là đổi lỗ.

    `use_hints`
      none        · chỉ BM25 + kỳ + đơn vị
      stmt        · thêm điểm cho `statement_type` suy từ câu hỏi
      code        · thêm điểm cho mã chỉ tiêu VAS suy từ câu hỏi
      both
      code_single · `code`, nhưng CHỈ cho câu một thực thể  ← MẶC ĐỊNH

    Đo đủ 1.012 câu: `hints_none` mất **0,0635 trên slice |gold|=1** — lớn nhất
    trong các thí nghiệm đã chạy. `stmt` bị loại từ vòng trước (Recall@10
    0,9345 → 0,9205).

    `primary_boost` / `primary_modes`
      Điểm cộng cho `balance_sheet` + `income_statement` (KHÔNG có `cash_flow`)
      khi câu ở mode `screen`/`related`. **MẶC ĐỊNH 0,00 = TẮT.**
      Giá trị thí nghiệm là 0,60 — ĐO trên 95 câu gold_v2: F2(A) 0,4549 →
      0,4994. Nhưng đó là gain trên DEVELOPMENT set: cùng 95 câu ấy đã được
      dùng để phát hiện feature, chọn `PRIMARY_KINDS` và quét boost. Theo
      docs/119 §5.8 default production giữ 0,00 cho tới khi held-out PASS.
      Cổng theo mode là BẮT BUỘC, không phải tinh chỉnh: gold của `single` là
      thuyết minh 70% và của `compare` là 81% — áp toàn cục sẽ làm tệ đi. Đặt
      0,0 để tắt hoàn toàn. `cash_flow` bị loại khỏi tiên nghiệm vì lift
      GOLD/topN của nó là 0,75 < 1 (đã bị xếp CAO hơn mức đáng) — xem docs/118.
      Số 0,60 ổn định trên cả hai nửa chia đôi của 32 câu bị tác động.

    ⚠ `alias` PHẢI là `{ticker: [tên, …]}` từ `alias_store.load_aliases`.
    Truyền `{}` hay `None` sẽ khiến tên công ty còn lại trong truy vấn BM25 và
    mất ~9 điểm hit@1 — xem `query_terms.drop_terms`.
    """
    it = parse_intent(question, alias)
    s1 = HardFilterGenerator(basis_mode=basis_mode)
    s2 = Bm25StructuralRanker(alias, top_k=top_k, use_hints=use_hints,
                              basis_mode=basis_mode,
                              primary_boost=primary_boost,
                              primary_modes=primary_modes)
    o1 = s1.generate(conn, question, it)
    o2 = s2.rank(conn, question, it, o1)
    # `RankedItem.scored` là chính đối tượng `Scored` mà `rank_s2.rank` trả về —
    # KHÔNG dựng lại, để không có trường nào mang giá trị giả (xem `RankedItem`).
    hits: list[Scored] = [r.scored for r in o2.ranked if r.scored is not None]
    return Result(it, o1.n, hits, o1.uids)


# Giữ tên cũ cho hai script chẩn đoán; `unit_kind_of` từng là `_unit_out` ở đây.
_unit_out = unit_kind_of
