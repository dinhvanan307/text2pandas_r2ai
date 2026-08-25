"""POOL GOLD v6 = v5 + GHI ĐÈ THỰC THỂ/NĂM cho 12 câu bị lỗi S0 đã chứng minh.

Vì sao cần: pool v5 lấy `targets`/`years` từ `parse_intent`, nên nó **thừa hưởng
nguyên vẹn** bốn lỗi RC-1..RC-4 (docs/83, docs/91 §4.1). Hệ quả: 12/31 câu
UNCERTAIN không phải vì thiếu bằng chứng trong corpus mà vì pool đi tìm sai mã
hoặc sai năm. Một bộ gold dựng như thế **đo chính cái lỗi thay vì đo thế giới**,
và tệ hơn: nó MIỄN TỘI cho Retrieval ở đúng những câu Retrieval đang làm hỏng.

Ranh giới phải giữ:
  * `src/retrieval/**` KHÔNG đổi một byte — Retrieval khi được CHẤM vẫn mang
    nguyên bốn lỗi ấy và vẫn bị trừ điểm ở 12 câu này. Đó là điều đúng.
  * Ghi đè là DỮ LIỆU KHAI BÁO (`data/dev/gold_entity_override_v1.json`), có
    `evidence` từng câu, không phải suy diễn lúc chạy.
  * Mọi mã thêm vào đều PHẢI có trong bảng alias A6. Không bịa thực thể.

Chạy:  python tools/gold_pool_v6.py --db artifacts/retrieval/work.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gold_pool_v4 as v4                                    # noqa: E402
from gold_pool_v5 import vai_tro_chat                        # noqa: E402
from retrieval.alias_store import load_aliases               # noqa: E402
from retrieval.evalkit.cli import _load_cfg                  # noqa: E402
from retrieval.evalkit.goldset import ProxyGoldV2            # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator)
from retrieval.question_intent import Intent, parse_intent   # noqa: E402

POOL_V5 = v4.DEV / "gold_tay_pool_v5.jsonl"
POOL_V6 = v4.DEV / "gold_tay_pool_v6.jsonl"
GHI_DE = v4.DEV / "gold_entity_override_v1.json"


def _nap_ghi_de() -> dict[int, dict]:
    d = json.loads(GHI_DE.read_text(encoding="utf-8"))
    return {int(k): v for k, v in d["overrides"].items()}


def _kiem_ghi_de(ghi_de: dict[int, dict], alias: dict) -> None:
    """Fail-closed: mã ghi đè phải có trong bảng alias A6. Không bịa thực thể."""
    for qid, o in ghi_de.items():
        la = [t for t in o["targets"] if t not in alias]
        if la:
            raise SystemExit(f"q{qid}: mã {la} KHÔNG có trong bảng alias A6 — từ chối ghi đè")
        if not o["targets"] or not o["years"]:
            raise SystemExit(f"q{qid}: targets/years rỗng")
        if not o.get("evidence"):
            raise SystemExit(f"q{qid}: thiếu `evidence` — mọi ghi đè phải có bằng chứng")


def _intent_ghi_de(goc: Intent, o: dict) -> Intent:
    """Dựng Intent mới. Giữ nguyên scope/mode/subject của S0 — ta chỉ sửa đúng
    hai trục đã có bằng chứng lỗi (thực thể và năm), không sửa gì khác."""
    tk = frozenset(o["targets"])
    return Intent(tickers=tk, explicit_scope=goc.explicit_scope,
                  years=tuple(sorted(o["years"])), resolved_by="ghi_de_gold",
                  mode="screen" if len(tk) > 1 else goc.mode,
                  subject=None if len(tk) > 1 else (next(iter(tk))))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="gold_pool_v6")
    p.add_argument("--db", type=Path, required=True)
    a = p.parse_args(argv)

    v4._vai_tro = vai_tro_chat                    # đúng như v5
    ghi_de = _nap_ghi_de()
    cfg = _load_cfg("base", {})
    alias = load_aliases(brands=cfg.brands)
    _kiem_ghi_de(ghi_de, alias)

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit, max_trusted=cfg.gold_max_trusted,
                        alias=alias, max_tier=cfg.gold_max_tier)
    seed = v4._hat_giong()

    cu = {}
    for line in POOL_V5.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            cu[r["id"]] = r

    mau = [json.loads(l) for l in v4.MAU.open(encoding="utf-8") if l.strip()]
    n = 0
    for r in mau:
        qid, q = r["id"], r["question"]
        if qid not in ghi_de:
            continue
        it = _intent_ghi_de(parse_intent(q, alias), ghi_de[qid])
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        gg = proxy.gold_for(conn, qid, q, frozenset(it.targets), it.years,
                            it.explicit_scope)
        moi = v4.build_pool_v4(conn, qid, q, it, [x.table_uid for x in o2.ranked],
                               sorted(gg.tables), o1.uids, alias, seed)
        moi["ghi_de"] = {k: ghi_de[qid][k] for k in ("rc", "bo", "them", "evidence")}
        cu[qid] = moi
        n += 1
        print(f"  q{qid:<5} ô={len(moi['cells']):>2} ứng viên={len(moi['candidates']):>3} "
              f"thiếu nhu cầu={len(moi.get('needs_missing') or [])}", flush=True)

    POOL_V6.write_text("".join(json.dumps(cu[k], ensure_ascii=False) + "\n"
                               for k in sorted(cu)), encoding="utf-8")
    print(f"pool v6: dựng lại {n} câu · tổng {len(cu)} câu · {POOL_V6.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
