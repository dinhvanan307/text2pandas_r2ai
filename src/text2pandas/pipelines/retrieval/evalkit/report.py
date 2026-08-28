"""Xuất báo cáo: bảng văn bản + JSON máy đọc + CSV failure case.

BA ĐẦU RA, BA MỤC ĐÍCH KHÁC NHAU
--------------------------------
  text  · để người đọc ngay trên terminal và ra quyết định
  json  · để so hai lần chạy bằng máy (A/B cấu hình), không phải bằng mắt
  csv   · để mở ra và ĐỌC TỪNG CÂU sai — đây là thứ dẫn tới cải thiện thật

MỌI BẢNG ĐỀU IN MẪU SỐ. Một chỉ số không kèm mẫu số là một chỉ số nói dối: nó
im lặng bỏ đi phần khó rồi báo con số đẹp trên phần dễ.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .metrics import (QueryOutcome, f2_at_k, f2_at_policy, gold_size_stats,
                      hit_rate_at_k, hit_rate_at_policy, metric_block, mrr,
                      mrr_at_k,
                      ndcg_at_k, precision_at_k, precision_at_k_capped,
                      recall_at_k)
from .taxonomy import Bucket
from ..policy import MAX_RELEVANT_TABLES, submission_table_limit

__all__ = ["load_rows", "to_outcomes", "render", "write_artifacts",
           "policy_n_map", "MAX_N"]

# Chính sách N của bài nộp thật — `tools/rewrite_submission.py`.
# Shared with submission generation and the public CLI. Keeping the cap and
# formula in one module makes evaluation report the exact production policy.
MAX_N = MAX_RELEVANT_TABLES


def policy_n_map(rows: list[dict]) -> dict[int, int]:
    """`qid → N` theo chính sách nộp bài: `clamp(n_mã × n_năm, 1, 10)`.

    Tính lại từ checkpoint (`n_targets`, `years`) nên KHÔNG cần chạy lại đo.
    """
    out: dict[int, int] = {}
    for r in rows:
        n_tick = max(1, int(r.get("n_targets") or 0) or 1)
        n_year = max(1, len(r.get("years") or []))
        out[r["id"]] = submission_table_limit(n_tick, n_year)
    return out


def load_rows(ck: Path) -> list[dict]:
    rows = [json.loads(l) for l in ck.open(encoding="utf-8") if l.strip()]
    return list({r["id"]: r for r in rows}.values())      # dòng CUỐI thắng


def guard_single_config(rows: list[dict]) -> str:
    """Từ chối in bảng nếu checkpoint TRỘN nhiều cấu hình.

    Đây là cổng chặn lỗi im lặng đắt nhất của một khung đo. Xem docstring
    `runner.py`. Trả về `cfg_sha` duy nhất, hoặc raise.
    """
    shas = Counter(r.get("cfg_sha", "?") for r in rows)
    if len(shas) > 1:
        raise SystemExit(
            "✗ CHECKPOINT TRỘN NHIỀU CẤU HÌNH — mọi con số sẽ vô nghĩa.\n"
            + "".join(f"    {s}: {n} câu\n" for s, n in shas.most_common())
            + "  Sửa: dùng checkpoint riêng cho từng cấu hình (tên tệp đã mang\n"
              "  cfg_sha), hoặc chuyển tệp này sang tên khác rồi chạy lại collect."
        )
    return next(iter(shas), "?")


def to_outcomes(rows: list[dict], use_final: bool = False) -> list[QueryOutcome]:
    """`use_final=True` đo SAU rerank; False đo sau ranker. Hai tầng, hai số."""
    key = "hits_at_final" if use_final else "hits_at_rank"
    out = []
    for r in rows:
        out.append(QueryOutcome(
            qid=r["id"], mode=r.get("mode", "?"),
            n_gold=r.get("n_gold", 0) if r.get("gold_ok") else 0,
            n_candidates=r.get("s1_n", 0),
            gold_in_candidates=bool(r.get("gold_in_s1")),
            n_ranked=r.get("s3_n" if use_final else "s2_n", 0),
            hits_at=tuple(r.get(key) or ()),
            measurable=bool(r.get("gold_ok")),
        ))
    return out


def _bar(pct: float, width: int = 28) -> str:
    n = int(round(pct * width))
    return "█" * n + "·" * (width - n)


def render(rows: list[dict], ks: tuple[int, ...], top_k: int) -> str:
    cfg_sha = guard_single_config(rows)
    oc = to_outcomes(rows, use_final=False)
    n_all = len(rows)
    L: list[str] = []
    P = L.append

    P("=" * 78)
    P(f"  BÁO CÁO TẦNG RETRIEVAL · cfg={cfg_sha} · {n_all} câu đã chạy")
    P("=" * 78)

    # ── 1 · phủ của thước đo ────────────────────────────────────────────────
    meas = [r for r in rows if r.get("gold_ok")]
    P("")
    P("1 · PHỦ CỦA THƯỚC ĐO — đọc mục này TRƯỚC mọi con số khác")
    P(f"    câu đã chạy                     : {n_all}")
    P(f"    dựng được gold TIN CẬY (tập đo) : {len(meas)}"
      f"  ({100*len(meas)/max(n_all,1):.1f}%)")
    P(f"    KHÔNG đo được                   : {n_all-len(meas)}"
      f"  ({100*(n_all-len(meas))/max(n_all,1):.1f}%)  ← không phải 'đúng', là 'không biết'")
    nog = Counter(r.get("gold_reason") for r in rows if not r.get("gold_ok"))
    for reason, cnt in nog.most_common():
        P(f"        {str(reason):26s} {cnt:5d}")
    gs = gold_size_stats(oc)
    if gs:
        P(f"    |gold|/câu: median={gs['median']:.0f} p90={gs['p90']:.0f} "
          f"max={gs['max']:.0f} mean={gs['mean']:.2f}")
        P(f"    câu có ĐÚNG 1 bảng gold        : {gs['n_exactly_one']:.0f}"
          f"  ({gs['pct_exactly_one']:.1f}%)  ← Precision chỉ đáng tin ở slice này")

    # ── 1b · theo TIER · nới càng nhiều thì gold càng nhiễu ─────────────────
    tiers = Counter(r.get("gold_tier") for r in meas)
    if tiers:
        P("")
        P("1b · GOLD THEO TIER — số ở tier nới KHÔNG đọc ngang hàng số ở tier chặt")
        P("    " + f"{'tier':18s} {'n':>5s} {'chặt?':>6s} {'|gold| median':>14s} "
                   f"{'hit@1':>7s} {'hit@10':>7s} {'F2@1':>7s}")
        for t, c in sorted(tiers.items(), key=lambda kv: str(kv[0])):
            v = [r for r in meas if r.get("gold_tier") == t]
            o = to_outcomes(v)
            strict = "CÓ" if all(r.get("gold_strict") for r in v) else "không"
            g = sorted(r.get("n_gold", 0) for r in v)
            P("    " + f"{str(t):18s} {c:5d} {strict:>6s} {g[len(g)//2]:>14d} "
                       f"{hit_rate_at_k(o,1):>7.3f} {hit_rate_at_k(o,10):>7.3f} "
                       f"{f2_at_k(o,1):>7.3f}")
        strict_rows = [r for r in meas if r.get("gold_strict")]
        if strict_rows and len(strict_rows) != len(meas):
            os_ = to_outcomes(strict_rows)
            P(f"    → CHỈ tier chặt (n={len(strict_rows)}): hit@1={hit_rate_at_k(os_,1):.4f}"
              f" hit@10={hit_rate_at_k(os_,10):.4f} MRR={mrr(os_):.4f}")

    # ── 2 · bảng phân loại thất bại ────────────────────────────────────────
    P("")
    P("2 · PHÂN LOẠI — mỗi câu ĐÚNG MỘT rổ, tổng = số câu đã chạy")
    buckets = Counter(r.get("bucket") for r in rows)
    order = [b.value for b in Bucket]
    names = {
        "F0_NO_GOLD": "không dựng được gold      (lỗi THƯỚC ĐO, không phải retrieval)",
        "F1_NO_CANDIDATE": "S1 trả TẬP RỖNG           (chắc chắn 0 điểm)",
        "F2_HARD_FILTER_DROP": "gold bị LỌC CỨNG loại     (không tầng sau nào cứu được)",
        "F3_RANK_MISS": f"gold có, RỚT top-{top_k:<2d}       (sửa được: trọng số / rerank)",
        "F4_RERANK_MISS": "vào top-K rồi bị rerank đẩy ra",
        "F5_SUCCESS": f"gold TRONG top-{top_k:<2d}         (thành công)",
    }
    for b in order:
        c = buckets.get(b, 0)
        pct = c / max(n_all, 1)
        P(f"    {b:22s} {c:5d} {100*pct:5.1f}%  {_bar(pct)}  {names[b]}")
    P(f"    {'TỔNG':22s} {sum(buckets.values()):5d}")

    # ── 3 · chỉ số theo TẦNG ───────────────────────────────────────────────
    P("")
    P("3 · CHỈ SỐ THEO TẦNG — tách bạch, vì mỗi tầng hỏng đòi một cách sửa")
    chr_ = sum(1 for r in meas if r.get("gold_in_s1")) / max(len(meas), 1)
    P(f"    S1 · CANDIDATE HIT RATE  : {chr_:.4f}"
      f"   ({sum(1 for r in meas if r.get('gold_in_s1'))}/{len(meas)})"
      "   ← đo trên TẬP ĐẦY ĐỦ, không phải top-K")
    P(f"    S1 · ứng viên/câu        : median={_med([r['s1_n'] for r in rows])}"
      f"  p90={_p90([r['s1_n'] for r in rows])}  max={max((r['s1_n'] for r in rows), default=0)}")
    s2_mrr_at_k = mrr_at_k(oc, top_k)
    ocf = to_outcomes(rows, use_final=True)
    s3_mrr_at_k = mrr_at_k(ocf, top_k)
    P(f"    S2 · MRR@{top_k:<2d}              : {s2_mrr_at_k:.4f}")
    P(f"    S3 · MRR@{top_k:<2d} sau rerank   : {s3_mrr_at_k:.4f}")
    P(f"    S3 − S2 · MRR@{top_k:<2d} uplift  : {s3_mrr_at_k-s2_mrr_at_k:+.4f}"
      "   (cùng cutoff, không lẫn truncation)")
    P(f"    S2 · MRR toàn top-{max((r.get('s2_n', 0) for r in rows), default=0):<2d}"
      f"      : {mrr(oc):.4f}   (diagnostic, không so trực tiếp với S3 top-{top_k})")

    # ── 4 · bảng K ─────────────────────────────────────────────────────────
    P("")
    P("4 · THEO K · tập đo n=" + str(len(meas)))
    P("    " + f"{'K':>3s} {'hit_rate':>9s} {'recall':>8s} {'prec':>7s} "
                f"{'prec_cap':>9s} {'F2(thật)':>9s} {'nDCG':>7s}")
    for k in ks:
        P("    " + f"{k:>3d} {hit_rate_at_k(oc,k):>9.4f} {recall_at_k(oc,k):>8.4f} "
                   f"{precision_at_k(oc,k):>7.4f} {precision_at_k_capped(oc,k):>9.4f} "
                   f"{f2_at_k(oc,k):>9.4f} {ndcg_at_k(oc,k):>7.4f}")
    P("    hit_rate = có ≥1 gold trong top-K  ·  recall = h/g macro")
    P("    F2(thật) = macro của 5h/(4g+N), CÔNG THỨC BTC — không phải f2(P̄,R̄)")
    # ── Chính sách N THẬT · số dự báo leaderboard sát nhất ─────────────────
    nmap = policy_n_map(rows)
    from collections import Counter as _C
    dist = _C(nmap[r["id"]] for r in meas)
    P("")
    P("4c · DƯỚI CHÍNH SÁCH N THẬT của bài nộp — N = clamp(n_mã × n_năm, 1, 10)")
    P(f"    F2@N*      : {f2_at_policy(oc, nmap):.4f}   ← bộ SO SÁNH TƯƠNG ĐỐI tốt nhất")
    P(f"    hit_rate@N*: {hit_rate_at_policy(oc, nmap):.4f}")
    P("    phân bố N  : " + "  ".join(f"N={k}:{v}" for k, v in sorted(dist.items())))
    P("    ⚠ F2@N* KHÔNG phải dự báo tuyệt đối: proxy gold có |gold| median 8 nên")
    P("      mẫu số 4g phồng ~8× so với gold thật 1 bảng ⇒ BI QUAN có hệ thống.")
    P("      Ước lượng tuyệt đối đáng tin nhất = F2@1 ở §4b (slice |gold|=1).")
    P("    (F2@K cố định giả định nộp cùng K cho mọi câu — bài nộp thật thì KHÔNG)")

    # ── 4b · slice g==1 ────────────────────────────────────────────────────
    one = [r for r in meas if r.get("n_gold") == 1]
    if one:
        oc1 = to_outcomes(one, use_final=False)
        P("")
        P(f"4b · SLICE |gold|=1 · n={len(one)} — số ĐÁNG TIN NHẤT về F2 thật")
        P("    " + f"{'K':>3s} {'hit_rate':>9s} {'F2(thật)':>9s}")
        for k in (1, 2, 3, 5, 10):
            P("    " + f"{k:>3d} {hit_rate_at_k(oc1,k):>9.4f} {f2_at_k(oc1,k):>9.4f}")

    # ── 5 · theo mode ──────────────────────────────────────────────────────
    P("")
    P("5 · THEO MODE")
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.get("mode", "?"), []).append(r)
    P("    " + f"{'mode':12s} {'chạy':>5s} {'đo':>5s} {'cand_hit':>9s} "
                f"{'hit@1':>7s} {'hit@10':>7s} {'F2@10':>7s}")
    for m in sorted(by, key=lambda x: -len(by[x])):
        v = by[m]
        vm = [r for r in v if r.get("gold_ok")]
        o = to_outcomes(v)
        ch = (sum(1 for r in vm if r.get("gold_in_s1")) / len(vm)) if vm else 0.0
        P("    " + f"{m:12s} {len(v):5d} {len(vm):5d} {ch:>9.3f} "
                   f"{hit_rate_at_k(o,1):>7.3f} {hit_rate_at_k(o,10):>7.3f} "
                   f"{f2_at_k(o,10):>7.3f}")

    # ── 6 · quy trách nhiệm lọc cứng ───────────────────────────────────────
    drops = Counter()
    for r in rows:
        for c in r.get("drop_clauses") or []:
            drops[c] += 1
    P("")
    P("6 · MỆNH ĐỀ LỌC CỨNG loại bảng gold — đọc thẳng từ DB, KHÔNG suy diễn")
    if drops:
        tot = sum(drops.values())
        for c, n in drops.most_common():
            P(f"    {c:20s} {n:5d}  ({100*n/tot:.1f}% số câu bị loại)")
    else:
        P("    (không câu nào bị lọc cứng loại gold — hoặc chưa chạy attribution)")

    # ── 7 · nghi vấn phân giải thực thể ────────────────────────────────────
    ent = [r for r in rows if r.get("entity_suspect")]
    P("")
    P("7 · NGHI VẤN PHÂN GIẢI THỰC THỂ — tín hiệu ĐỘC LẬP với S1")
    P("    Điều kiện: đã CẠN mọi cụm ở mọi tier, và `COUNT(*) GROUP BY ticker`")
    P("    (KHÔNG LIMIT) cho thấy cụm tồn tại ở mã KHÁC. Không suy diễn từ tên biến.")
    P(f"    số câu: {len(ent)}")
    for r in ent[:12]:
        hist = r.get("free_ticker_hist") or {}
        top = ", ".join(f"{k}×{v}" for k, v in list(hist.items())[:5])
        P(f"    q{r['id']:<5d} targets={r.get('targets')} phrase={r.get('gold_phrase')!r}"
          f" free[{r.get('gold_free_hits')}]={{{top}}}")

    # ── 8 · failure case ───────────────────────────────────────────────────
    P("")
    P("8 · FAILURE CASE — 12 câu đầu mỗi rổ đáng sửa")
    for b in ("F1_NO_CANDIDATE", "F2_HARD_FILTER_DROP", "F3_RANK_MISS"):
        v = [r for r in rows if r.get("bucket") == b]
        P(f"    ── {b}  (n={len(v)})")
        for r in v[:12]:
            P(f"       q{r['id']:<5d} {r.get('mode',''):11s} s1={r.get('s1_n'):<5d} "
              f"g={r.get('n_gold'):<3d} rank={r.get('hits_at_rank') or []} "
              f"drop={r.get('drop_clauses') or []} phrase={r.get('gold_phrase')!r}")

    P("")
    P("=" * 78)
    return "\n".join(L)


def _med(v: list[int]) -> int:
    s = sorted(v)
    return s[len(s) // 2] if s else 0


def _p90(v: list[int]) -> int:
    s = sorted(v)
    return s[min(int(0.9 * len(s)), len(s) - 1)] if s else 0


def write_artifacts(rows: list[dict], outdir: Path, ks: tuple[int, ...],
                    top_k: int, tag: str) -> dict[str, Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    cfg_sha = guard_single_config(rows)
    oc = to_outcomes(rows)
    ocf = to_outcomes(rows, use_final=True)
    mb = metric_block(oc, ks, n_total=len(rows))
    mbf = metric_block(ocf, ks, n_total=len(rows))
    s2_mrr_at_top_k = mrr_at_k(oc, top_k)
    s3_mrr_at_top_k = mrr_at_k(ocf, top_k)

    payload = {
        "cfg_sha": cfg_sha, "tag": tag, "n_rows": len(rows), "top_k": top_k,
        "coverage": mb.coverage, "n_measured": mb.n_measured,
        "buckets": dict(Counter(r.get("bucket") for r in rows)),
        "gold_size": gold_size_stats(oc),
        "gold_tiers": dict(Counter(r.get("gold_tier") for r in rows
                                   if r.get("gold_ok"))),
        "n_strict": sum(1 for r in rows if r.get("gold_strict")),
        "no_gold_reasons": dict(Counter(r.get("gold_reason") for r in rows
                                       if not r.get("gold_ok"))),
        "after_rank": {"candidate_hit_rate": mb.candidate_hit_rate,
                       "mrr": mb.mrr,
                       "mrr_at_top_k": s2_mrr_at_top_k,
                       "per_k": mb.per_k},
        "after_rerank": {"mrr": mbf.mrr,
                           "mrr_at_top_k": s3_mrr_at_top_k,
                           "per_k": mbf.per_k},
        "rerank_comparison": {
            "cutoff": top_k,
            "s2_mrr": s2_mrr_at_top_k,
            "s3_mrr": s3_mrr_at_top_k,
            "mrr_uplift": s3_mrr_at_top_k - s2_mrr_at_top_k,
            "comparison_scope": "same_cutoff",
        },
        "drop_clauses": dict(Counter(c for r in rows
                                     for c in (r.get("drop_clauses") or []))),
        "entity_suspect": sum(1 for r in rows if r.get("entity_suspect")),
        "by_mode": {},
    }
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.get("mode", "?"), []).append(r)
    for m, v in by.items():
        o = to_outcomes(v)
        vm = [r for r in v if r.get("gold_ok")]
        payload["by_mode"][m] = {
            "n": len(v), "n_measured": len(vm),
            "candidate_hit_rate": (sum(1 for r in vm if r.get("gold_in_s1"))
                                   / len(vm)) if vm else 0.0,
            "hit_rate_1": hit_rate_at_k(o, 1), "hit_rate_10": hit_rate_at_k(o, 10),
            "f2_10": f2_at_k(o, 10), "mrr": mrr(o),
        }

    jp = outdir / f"metrics_{tag}_{cfg_sha}.json"
    jp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    cp = outdir / f"failures_{tag}_{cfg_sha}.csv"
    cols = ["id", "bucket", "mode", "resolved_by", "targets", "years", "s1_n",
            "s2_n", "n_gold", "gold_ok", "gold_tier", "gold_strict",
            "gold_reason", "gold_in_s1", "best_rank", "hits_at_rank",
            "drop_clauses", "entity_suspect", "gold_phrase", "ms"]
    with cp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x.get("bucket", ""), x["id"])):
            hits = r.get("hits_at_rank") or []
            w.writerow({
                "id": r["id"], "bucket": r.get("bucket"), "mode": r.get("mode"),
                "resolved_by": r.get("resolved_by"),
                "targets": "|".join(r.get("targets") or []),
                "years": "|".join(str(y) for y in (r.get("years") or [])),
                "s1_n": r.get("s1_n"), "s2_n": r.get("s2_n"),
                "n_gold": r.get("n_gold"), "gold_ok": r.get("gold_ok"),
                "gold_tier": r.get("gold_tier"),
                "gold_strict": r.get("gold_strict"),
                "gold_reason": r.get("gold_reason"),
                "gold_in_s1": r.get("gold_in_s1"),
                "best_rank": min(hits) if hits else "",
                "hits_at_rank": "|".join(str(h) for h in hits[:8]),
                "drop_clauses": "|".join(r.get("drop_clauses") or []),
                "entity_suspect": r.get("entity_suspect"),
                "gold_phrase": r.get("gold_phrase"), "ms": r.get("ms"),
            })

    tp = outdir / f"report_{tag}_{cfg_sha}.txt"
    tp.write_text(render(rows, ks, top_k), encoding="utf-8")
    return {"json": jp, "csv": cp, "txt": tp}
