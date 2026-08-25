"""P0-B · Trả lời §5.7 của docs/119 bằng SỐ ĐO, không bằng lời.

CÂU HỎI: nếu E2 chỉ rerank một cache top-300 cố định thì thành viên top-300
không thể đổi. Vậy vì sao "gold ngoài top-300" giảm 76 → 46?

Script này đo tại từng ranh giới stage cho cả `base` và `treatment`:
    S1 pool  →  S2 nhận  →  cộng primary  →  cắt top_k(=300)
và in ra kích thước ở mỗi điểm, cùng với việc S2 có chạy lại trên TOÀN pool
hay chỉ trên 300 phần tử.
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from text2pandas.pipelines.retrieval.alias_store import load_aliases                 # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg                    # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.stages import (Bm25StructuralRanker,    # noqa: E402
                                      HardFilterGenerator)
from text2pandas.pipelines.retrieval.question_intent import parse_intent             # noqa: E402

DEPTH = 300


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"))
    ap.add_argument("--boost", type=float, default=0.60)
    ap.add_argument("--out", default=str(ROOT / "artifacts/runs/retrieval/reaudit/e2_stage_boundary.json"))
    a = ap.parse_args(argv)
    cfg = _load_cfg("base", {})
    alias = load_aliases(brands=cfg.brands)
    conn = sqlite3.connect(f"file:{os.path.abspath(a.db)}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    S = {r["id"]: r for r in (json.loads(l) for l in
         (ROOT / "data/curated/dev-legacy/gold_tay_sample_v2.jsonl").open(encoding="utf-8") if l.strip())}
    qids = sorted(r["id"] for r in (json.loads(l) for l in
                  (ROOT / "data/curated/dev-legacy/gold_v2.jsonl").open(encoding="utf-8") if l.strip())
                  if r.get("gold_table_uids"))
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    mk = lambda b: Bm25StructuralRanker(
        alias, top_k=max(cfg.top_k_rank, DEPTH), use_hints=cfg.use_hints,
        basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode, primary_boost=b)
    # S2 KHÔNG chạy lại ở đây: dùng đúng hai tệp refs đã cache của `e2_run.py`
    # (base = boost 0,00 · treat = boost 0,60 + BS/IS). S1 thì phải chạy vì
    # kích thước pool chính là con số §5.7 cần.
    RE = ROOT / "artifacts/runs/retrieval/reaudit"
    CA = json.loads((RE / "exp_refs_base.json").read_text(encoding="utf-8"))["refs"]
    CB = json.loads((RE / "exp_refs_pri060_bsis.json").read_text(encoding="utf-8"))["refs"]

    rows, t0 = [], time.time()
    for qid in qids:
        q = S[qid]["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        n_pool = len([x for x in o1.ranked if x.cand is not None])
        A = CA[str(qid)]["refs"]
        B = CB[str(qid)]["refs"]
        rows.append({
            "qid": qid, "mode": it.mode,
            "s1_pool": len(o1.uids), "s2_input": n_pool,
            "s2_out_base": len(A), "s2_out_treat": len(B),
            "top300_base": A, "top300_treat": B,
            "n_moi_vao_top300": len(set(B) - set(A)),
            "n_bi_day_ra": len(set(A) - set(B)),
        })
    tong = {
        "n_qid": len(rows), "boost": a.boost, "depth": DEPTH,
        "s2_input_min": min(r["s2_input"] for r in rows),
        "s2_input_max": max(r["s2_input"] for r in rows),
        "s2_input_mean": round(sum(r["s2_input"] for r in rows) / len(rows), 1),
        "n_qid_s2_input_gt_300": sum(1 for r in rows if r["s2_input"] > DEPTH),
        "n_qid_top300_doi_thanh_vien": sum(1 for r in rows if r["n_moi_vao_top300"]),
        "tong_bang_moi_vao_top300": sum(r["n_moi_vao_top300"] for r in rows),
        "ket_luan": ("S2 chạy lại trên TOÀN BỘ S1 pool rồi mới cắt top-300. "
                     "Primary boost nằm TRƯỚC phép cắt. Vì vậy thành viên "
                     "top-300 ĐƯỢC PHÉP đổi — đây KHÔNG phải rerank-only "
                     "trên một cache 300 phần tử cố định."),
        "he_qua": ("So sánh trần (ceiling) trong docs/118 §1.2 được tính trên "
                   "universe top-300 CỦA BASE. Với treatment, universe khác ⇒ "
                   "hai trần KHÔNG cùng universe và phải đọc riêng."),
        "seconds": round(time.time() - t0, 1),
    }
    Path(a.out).write_text(json.dumps({"tong": tong, "per_qid": [
        {k: v for k, v in r.items() if not k.startswith("top300_")} for r in rows]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in tong.items():
        print(f"  {k:<28s} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
