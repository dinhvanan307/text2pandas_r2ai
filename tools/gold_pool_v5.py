"""POOL GOLD v5 = v4 với **một** thay đổi: siết lại phép nhận VAI TRÒ của bảng.

VÌ SAO CÓ v5 — bằng chứng đo được ở P0-d
----------------------------------------
Khi phân xử thật trên pool v4, 90 ô × nhu cầu không có bảng dùng được. Tra
ngược vào A6 cho kết quả rất rõ:

    89/90 slot ĐÃ CÓ bảng đúng vai trò, đúng phạm vi, `ready_obs > 0` trong A6.
     1/90 là thiếu hụt A6 thật (ACB/2024 bản riêng không có BCKQKD).

Nghĩa là pool v4 không thiếu hạn ngạch — nó **tiêu hạn ngạch vào nhầm bảng**.
`_vai_tro` của v4 nhận diện quá rộng nên một BÁO CÁO LƯU CHUYỂN TIỀN TỆ được
tính là đã đáp ứng nhu cầu `balance_sheet_tai_san`, chỉ vì trong đó có dòng
"tăng, giảm hàng tồn kho" hay "tiền chi ... và các tài sản dài hạn khác". Suất
dành cho nửa bảng cân đối bị dùng mất, và bảng cân đối thật không bao giờ được
gọi vào.

Đây là một bài học chung: **một phép nhận diện quá rộng không chỉ làm thống kê
đẹp lên, nó còn khiến cơ chế hạn ngạch phân bổ sai.** Ở v4 tôi đã cố ý để
`_vai_tro` rộng với lập luận "sai về phía rộng chỉ làm pool to hơn" — lập luận
ấy sai, vì hạn ngạch là hữu hạn và được cấp THEO nhu cầu.

THAY ĐỔI DUY NHẤT
-----------------
`_vai_tro` → `vai_tro_chat`. Mọi thứ khác của v4 giữ nguyên: bộ mẫu nhu cầu
đọc từ câu hỏi, hạn ngạch `PER_CELL_BASE + PER_NEED × |needs|`, ưu tiên
`basis`, hạt giống gold, S2 nạp sau cùng và bị chặn trần, phần bù không lấy từ
S2, tất định.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gold_pool_v4 as v4                                  # noqa: E402
import gold_tay as g3                                      # noqa: E402
from retrieval.alias_store import load_aliases             # noqa: E402
from retrieval.evalkit.cli import _load_cfg                # noqa: E402
from retrieval.evalkit.goldset import ProxyGoldV2          # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator)
from retrieval.question_intent import parse_intent         # noqa: E402

POOL_V5 = v4.DEV / "gold_tay_pool_v5.jsonl"

_NV = ("no phai tra", "no ngan han", "tong cong nguon von", "von chu so huu",
       "phai tra nguoi ban ngan han", "nguoi mua tra tien truoc ngan han",
       "von gop cua chu so huu", "loi nhuan sau thue chua phan phoi")
# "tai san dai han" bị bỏ khỏi danh sách cứng: BCLCTT có cụm "tiền chi ... và
# các tài sản dài hạn khác", và đó chính là một trong bốn đường khớp nhầm.
_TS = ("tai san ngan han", "tong cong tai san")


def _co(t: str, mau: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", t) for m in mau)


def vai_tro_chat(stmt: str | None, rows: str) -> set[str]:
    """Vai trò một bảng THỰC SỰ đóng được, nhận bằng dấu văn của bảng.

    Không tin một mình `statement_type`: A6 gán BCKQKD riêng của HPG/2018
    (`b545aa2d`) nhãn `cash_flow`, và gán nửa nguồn vốn của BCĐKT nhãn `note`.
    Cũng không tin một dòng chỉ tiêu lẻ: phải có tiêu đề mục hoặc dòng tổng.
    """
    t = (rows or "").lower()
    ra: set[str] = set()
    if stmt == "cash_flow" or re.search(
            r"luu chuyen tien thuan.{0,30}hoat ?dong ?kinh ?doanh", t):
        ra.add("cash_flow")
    thuong = _co(t, ("doanh thu thuan", "doanh thu cung cap dich vu")) and _co(
        t, ("loi nhuan gop", "gia von hang ban", "gia von dich vu cung cap",
            "loi nhuan sau thue thu nhap doanh nghiep", "loi nhuan sau thue tndn"))
    ngan_hang = _co(t, ("thu nhap lai thuan",)) and _co(t, ("tong loi nhuan truoc thue",))
    if stmt == "income_statement" or thuong or ngan_hang:
        ra.add("income_statement")
    if stmt != "cash_flow":
        if _co(t, _TS) or (_co(t, ("tai san dai han",)) and not _co(t, ("tien chi",))):
            ra.add("balance_sheet_tai_san")
        if _co(t, _NV):
            ra.add("balance_sheet_nguon_von")
    return ra


def cmd_pool_v5(db: Path, tu: int, den: int) -> int:
    mau = [json.loads(l) for l in v4.MAU.open(encoding="utf-8") if l.strip()]
    cfg = _load_cfg("base", {})
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=cfg.brands)
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)
    seed = v4._hat_giong()
    cu = {}
    if POOL_V5.is_file():
        for line in POOL_V5.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                cu[r["id"]] = r
    n = 0
    for r in mau[tu - 1:den]:
        qid, q = r["id"], r["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        gg = proxy.gold_for(conn, qid, q, frozenset(it.targets) or it.tickers,
                            it.years, it.explicit_scope)
        cu[qid] = v4.build_pool_v4(conn, qid, q, it, [x.table_uid for x in o2.ranked],
                                   sorted(gg.tables), o1.uids, alias, seed)
        n += 1
        POOL_V5.write_text("".join(json.dumps(cu[k], ensure_ascii=False) + "\n"
                                   for k in sorted(cu)), encoding="utf-8")
    print(f"dựng pool v5 cho {n} câu · tổng {len(cu)} câu trong "
          f"{POOL_V5.relative_to(ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="gold_pool_v5")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--tu", type=int, default=1)
    p.add_argument("--den", type=int, default=10**9)
    a = p.parse_args(argv)
    # Thay phép nhận vai trò TẠI CHỖ — `build_pool_v4` gọi `_vai_tro` qua tên
    # module, nên gán đè ở đây là đủ và không phải nhân bản 100 dòng dựng pool.
    v4._vai_tro = vai_tro_chat
    return cmd_pool_v5(a.db, a.tu, a.den)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
