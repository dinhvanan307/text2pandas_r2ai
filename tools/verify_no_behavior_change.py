"""PHÁT LẠI một mẫu câu bằng CODE HIỆN TẠI và so với checkpoint đã có.

VÌ SAO CẦN
----------
`tests/test_p0_unify.py::test_behavior_fingerprint` bắt được "code hành vi đã
đổi", nhưng nó KHÔNG biết đổi đó có làm lệch kết quả hay không. Docstring của nó
bảo người sửa tự phân loại:

    có đổi hành vi  → bump SCHEMA_VERSION, chạy lại toàn bộ
    không đổi       → chỉ cập nhật số ghim

Và "tự phân loại" là chỗ để lọt. Script này biến câu trả lời thành một PHÉP ĐO:
chạy lại S1→S2→S3 cho `--n` câu bằng code trong cây làm việc, rồi so từng câu
với `hits_at_rank`/`hits_at_final`/`s1_n` đã lưu trong checkpoint.

    ĐỒNG NHẤT   ⇒ refactor trung tính ⇒ được phép chỉ cập nhật số ghim
    LỆCH        ⇒ ĐỔI HÀNH VI         ⇒ bắt buộc bump SCHEMA_VERSION + đo lại

Cố ý KHÔNG so `ms` (thời gian chạy không phải hành vi) và KHÔNG so `gold_*` khi
`--bo-gold` (dùng khi cố ý sửa bộ dựng gold).

    python tools/verify_no_behavior_change.py --tag base --n 150
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.evalkit.cli import OUTDIR, _load_cfg       # noqa: E402
from retrieval.evalkit.runner import _questions           # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator, IdentityReranker)
from retrieval.evalkit.goldset import ProxyGoldV2         # noqa: E402
from retrieval.question_intent import parse_intent        # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="verify_no_behavior_change")
    ap.add_argument("--tag", default="base")
    ap.add_argument("--n", type=int, default=150, help="số câu phát lại")
    ap.add_argument("--db", default="artifacts/retrieval/work.db")
    ap.add_argument("--bo-gold", action="store_true",
                    help="chỉ so xếp hạng, bỏ qua gold (khi cố ý sửa bộ dựng gold)")
    ns = ap.parse_args(argv)

    cfg = _load_cfg(ns.tag, {})
    ck = OUTDIR / cfg.checkpoint_name
    if not ck.is_file():
        print(f"✗ chưa có checkpoint {ck.name}")
        return 2
    cu = {}
    for line in ck.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            cu[r["id"]] = r
    print(f"checkpoint {ck.name}  ·  {len(cu)} câu  ·  cfg_sha={cfg.sha}")

    db = ROOT / ns.db
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-300000")
    alias = load_aliases(brands=cfg.brands)

    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, weights=cfg.weights,
                              bonuses=cfg.bonuses, norm=cfg.norm,
                              per_ticker_k=cfg.per_ticker_k)
    s3 = IdentityReranker(top_k=cfg.top_k_rerank)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)

    # Lấy mẫu TRẢI ĐỀU theo id thay vì `[:n]`: 150 câu đầu tệp thiên về một vài
    # mã và một vài dạng câu, nên "giống nhau ở 150 câu đầu" là bằng chứng yếu.
    qs = [q for q in _questions(ROOT) if q["id"] in cu]
    buoc = max(1, len(qs) // ns.n)
    mau = qs[::buoc][:ns.n]

    lech, xet = [], 0
    t0 = time.time()
    for q in mau:
        qid, question = q["id"], q["question"]
        old = cu[qid]
        it = parse_intent(question, alias)
        tickers = frozenset(it.targets) or it.tickers
        gold = proxy.gold_for(conn, qid, question, tickers, it.years,
                              it.explicit_scope)
        o1 = s1.generate(conn, question, it)
        o2 = s2.rank(conn, question, it, o1)
        o3 = s3.rerank(conn, question, it, o2)
        moi = {
            "s1_n": o1.n, "s2_n": len(o2.ranked), "s3_n": len(o3.ranked),
            "hits_at_rank": list(o2.positions_of(gold.tables)) if gold.tables else [],
            "hits_at_final": list(o3.positions_of(gold.tables)) if gold.tables else [],
        }
        if not ns.bo_gold:
            moi["n_gold"] = len(gold.tables)
            moi["gold_ok"] = gold.ok
            moi["gold_tier"] = gold.tier
        khac = {k: (old.get(k), v) for k, v in moi.items() if old.get(k) != v}
        xet += 1
        if khac:
            lech.append((qid, khac))

    dt = time.time() - t0
    print(f"phát lại {xet} câu trong {dt:.0f}s  ·  lệch {len(lech)} câu")
    for qid, khac in lech[:10]:
        print(f"  q{qid}")
        for k, (a, b) in khac.items():
            print(f"      {k:14s} checkpoint={a!r}  hiện tại={b!r}")
    if lech:
        print("\n✗ CODE HIỆN TẠI KHÔNG TÁI LẬP checkpoint.")
        print("  Đây là ĐỔI HÀNH VI: phải bump SCHEMA_VERSION và đo lại toàn bộ,")
        print("  KHÔNG được chỉ cập nhật số ghim trong test fingerprint.")
        return 1
    print("\n✓ ĐỒNG NHẤT từng câu — thay đổi là refactor trung tính.")
    print("  Được phép cập nhật số ghim fingerprint mà không bump SCHEMA_VERSION.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
