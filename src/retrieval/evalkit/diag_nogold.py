"""Chẩn đoán 413 câu KHÔNG dựng được gold — nới từng ràng buộc, đo cái nào cứu được.

VÌ SAO CẦN TỆP NÀY
------------------
`report` nói 43,3% câu không đo được. Đó là con số quan trọng nhất của cả khung
đo — nhưng nó không nói ràng buộc NÀO giết chúng. Bốn ràng buộc đang cùng áp:

    A. cụm phải khớp `row_labels`        (không thử `section_text`/`context_clean`)
    B. kỳ phải khớp `periods LIKE %Y-12-31%`
    C. bảng phải thuộc tài liệu của mã đã phân giải
    D. cụm dài ≥ 2 token

Nới từng cái MỘT, trên cùng tập câu, rồi đếm số câu được cứu. Đó là cách duy
nhất quy trách nhiệm cho đúng ràng buộc thay vì đoán.

    python3 src/retrieval/evalkit/diag_nogold.py --tag base --sample 120
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.evalkit.cli import _load_cfg, _preflight   # noqa: E402

_preflight()

from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.query_terms import content_terms           # noqa: E402
from retrieval.question_intent import parse_intent        # noqa: E402

OUT = ROOT / "artifacts/retrieval/evalkit"

_BASE = ("SELECT COUNT(*) FROM table_cards_fts f "
         "JOIN table_cards t ON t.rowid = f.rowid WHERE table_cards_fts MATCH ?")


def _count(conn, match: str, tickers=(), period_ends=()) -> int:
    sql, args = _BASE, [match]
    if tickers:
        sql += " AND t.ticker IN (" + ",".join("?" * len(tickers)) + ")"
        args += list(tickers)
    if period_ends:
        sql += " AND (" + " OR ".join("t.periods LIKE ?" for _ in period_ends) + ")"
        args += [f"%{p}%" for p in period_ends]
    try:
        return conn.execute(sql, args).fetchone()[0]
    except sqlite3.OperationalError:
        return -1


def variants(terms: list[str]) -> dict[str, list[str]]:
    """Sinh biểu thức MATCH cho từng mức nới. Mỗi mức đổi ĐÚNG MỘT thứ."""
    out: dict[str, list[str]] = {}
    if len(terms) >= 2:
        out["A0_row_2gram"] = [f'row_labels : "{terms[i]} {terms[i+1]}"'
                               for i in range(len(terms) - 1)]
    if terms:
        # A1 · nới CỘT: thử cả section_text và context_clean, cùng cụm 2-gram
        if len(terms) >= 2:
            out["A1_any_col_2gram"] = [
                f'({{section_text context_clean row_labels col_labels}} : "{terms[i]} {terms[i+1]}")'
                for i in range(len(terms) - 1)]
        # A2 · nới ĐỘ DÀI: token đơn trên row_labels
        out["A2_row_1tok"] = [f'row_labels : "{t}"' for t in terms[:8]]
        # A3 · AND hai token bất kỳ trên row_labels (không cần liền nhau)
        if len(terms) >= 2:
            out["A3_row_AND2"] = [f'row_labels : "{terms[i]}" AND row_labels : "{terms[j]}"'
                                  for i in range(min(3, len(terms)))
                                  for j in range(i + 1, min(4, len(terms)))]
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="base")
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--budget-s", type=float, default=38.0)
    ns = ap.parse_args(argv)

    # DÙNG CHECKPOINT CHÍNH DANH, không `glob(...)[-1]`.
    #
    # Bản trước lấy tệp CUỐI theo thứ tự chữ cái. Với tag `base` có 4 tệp
    # (3189bebc · 52cd55a9 · 81e7eae6 · da55067a) thì "cuối" là `da55067a` —
    # đúng tệp sinh bởi **gold builder có bug return sớm**, tức chẩn đoán chạy
    # trên dữ liệu sai mà không một dòng nào báo. `cfg.checkpoint_name` suy ra từ
    # `cfg_sha` của cấu hình hiện tại, nên không còn chỗ cho nhập nhằng.
    cfg = _load_cfg(ns.tag, {})
    ck = OUT / cfg.checkpoint_name
    if not ck.is_file():
        print(f"✗ chưa có checkpoint chính danh cho tag={ns.tag}: {ck.name}")
        khac = sorted(OUT.glob(f"ek_{ns.tag}_*.jsonl"))
        if khac:
            print("  có tệp khác cùng tag nhưng CẤU HÌNH KHÁC — không dùng:")
            for f in khac:
                print(f"    {f.name}")
        print(f"  chạy: tools/evalkit collect --tag {ns.tag} --loop --budget-s 300")
        return 2
    rows = list({json.loads(l)["id"]: json.loads(l)
                 for l in ck.open(encoding="utf-8") if l.strip()}.values())
    print(f"checkpoint: {ck.name}  ({len(rows)} câu)")
    nogold = [r for r in rows if not r.get("gold_ok")
              and r.get("gold_reason") == "no_phrase_match"]
    print(f"câu no_phrase_match: {len(nogold)} · lấy mẫu {min(ns.sample, len(nogold))}")

    qmap = {q["id"]: q["question"] for q in (
        json.loads(l) for l in
        (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8")
        if l.strip())}
    alias = load_aliases(brands=True)
    conn = sqlite3.connect(f"file:{ROOT/'artifacts/retrieval/work.db'}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-300000")

    # Bốn cấu hình ràng buộc, mỗi cấu hình nới ĐÚNG MỘT chiều so với gốc.
    modes = [
        ("goc            (mã + kỳ)", True, True),
        ("bo KỲ          (mã)     ", True, False),
        ("bo MÃ          (kỳ)     ", False, True),
        ("bo cả hai              ", False, False),
    ]
    tally = {f"{v}|{m[0]}": 0 for m in modes
             for v in ("A0_row_2gram", "A1_any_col_2gram", "A2_row_1tok", "A3_row_AND2")}
    seen = {k: 0 for k in ("A0_row_2gram", "A1_any_col_2gram", "A2_row_1tok", "A3_row_AND2")}
    n = 0
    t0 = time.time()
    per_q = []
    for r in nogold[:ns.sample]:
        q = qmap.get(r["id"])
        if not q:
            continue
        it = parse_intent(q, alias)
        tk = tuple(sorted(frozenset(it.targets) or it.tickers))
        drop = tuple(x for t in tk for x in alias.get(t, [])) + tk
        terms = content_terms(q, drop=drop)
        pe = tuple(f"{y}-12-31" for y in it.years)
        vs = variants(terms)
        rec = {"id": r["id"], "n_terms": len(terms)}
        for vname, exprs in vs.items():
            seen[vname] += 1
            for label, use_tk, use_pe in modes:
                hit = 0
                for e in exprs[:6]:
                    c = _count(conn, e, tk if use_tk else (), pe if use_pe else ())
                    if c > 0:
                        hit = c
                        break
                if hit:
                    tally[f"{vname}|{label}"] += 1
                rec[f"{vname}|{label.strip()}"] = hit
        per_q.append(rec)
        n += 1
        if time.time() - t0 > ns.budget_s:
            break

    print(f"\nđã thử {n} câu · {time.time()-t0:.0f}s")
    print("\nSỐ CÂU ĐƯỢC CỨU (có ≥1 bảng khớp) — nới đúng MỘT chiều mỗi lần\n")
    print(f"{'biến thể cụm':20s} " + " ".join(f"{m[0][:14]:>16s}" for m in modes))
    for v in ("A0_row_2gram", "A1_any_col_2gram", "A2_row_1tok", "A3_row_AND2"):
        if not seen[v]:
            continue
        cells = []
        for m in modes:
            c = tally[f"{v}|{m[0]}"]
            cells.append(f"{c:5d} ({100*c/seen[v]:4.0f}%)".rjust(16))
        print(f"{v:20s} " + " ".join(cells) + f"   [n={seen[v]}]")

    p = OUT / f"diag_nogold_{ns.tag}.json"
    p.write_text(json.dumps({"n": n, "seen": seen, "tally": tally,
                             "per_q": per_q[:400]}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    print(f"\nchi tiết → {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
