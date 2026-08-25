"""Bộ dụng cụ dựng GOLD GÁN TAY — lấy mẫu phân tầng, sinh phiếu, kiểm nhất quán.

VÌ SAO CẦN GOLD TAY DÙ ĐÃ CÓ PROXY 99,4%
----------------------------------------
Proxy gold trả **median 8 bảng/câu**, chỉ 63/1006 câu có đúng 1 bảng. Hệ quả đo
được: `F2@N*` = 0,2141 trong khi slice `|gold|=1` cho 0,4921 — chênh **2,3 lần**,
và không con số nào trong hai con số đó là điểm thật. Mẫu số `4g` của công thức
`F2 = 5h/(4g+N)` phồng theo `|gold|`, nên **một gold quá rộng làm F2 mất nghĩa**.

Gold tay giải quyết đúng chỗ đó: người gán chọn bảng **thật sự chứa số cần**,
thường 1 bảng, nên `4g` về đúng giá trị và F2 đọc được như điểm.

BA QUY TẮC CHỐNG NHIỄM, thi hành bằng chính cấu trúc phiếu
---------------------------------------------------------
1. **Phiếu KHÔNG chứa điểm và KHÔNG chứa thứ hạng của S2.** Ứng viên sắp theo
   `table_uid` — thứ tự trung tính. `docs/70` §6.2: *"Người gán gold không được
   nhìn output của hệ thống. Xác nhận thứ hệ thống trả về sẽ đóng dấu 'đúng' lên
   chính lỗi của hệ thống, và sau đó mọi chỉ số đều đẹp mà không chỉ số nào có
   nghĩa."*

2. **Phiếu KHÔNG lọc theo cụm chỉ tiêu.** Proxy gold lọc theo cụm khớp
   `row_labels`; nếu phiếu cũng lọc thế thì gold tay chỉ xác nhận lại proxy. Phiếu
   liệt kê **mọi bảng** của (mã, năm) đã phân giải, kèm metadata để người đọc tự
   phán. Ràng buộc (mã, năm) giữ lại vì nó ĐÚNG về ngữ nghĩa, không phải vì S1
   dùng nó.

3. **Lấy mẫu tất định, không `random`.** Trộn trong từng tầng bằng
   `sha256(qid)` — cùng seed cho cùng kết quả, và không phụ thuộc thứ tự tệp.

    tools/evalkit gold sample   --n 120            # chọn mẫu phân tầng
    tools/evalkit gold sheet    --out artifacts/…  # sinh phiếu gán
    tools/evalkit gold check                       # kiểm gold đã gán
    tools/evalkit gold agree --a ai --b human      # đo đồng thuận hai người gán
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.evalkit.cli import _preflight  # noqa: E402

_preflight()

from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.question_intent import parse_intent         # noqa: E402

OUT = ROOT / "artifacts/runs/retrieval/evalkit"
DEV = ROOT / "data/curated/dev-legacy"
QPATH = ROOT / "data/raw/btc/questions/questions.jsonl"
DB = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"

# Tỷ lệ phân tầng theo `mode`, xấp xỉ phân bố thật (single 741 · screen 160 ·
# related 59 · compare 51 · screen_open 1) nhưng ĐÁNH THÊM TRỌNG SỐ cho nhóm
# nhỏ: `compare`/`related` chỉ ~5% đề nhưng là nơi chính sách N phức tạp nhất,
# nên cần đủ mẫu để nói được điều gì về chúng.
STRATA = {"single": 0.55, "screen": 0.20, "related": 0.12, "compare": 0.12}

# Dấu hiệu `op` — dùng để phân tầng TRONG nhóm `single`, vì câu phái sinh
# (ratio/delta) cần ≥2 bảng và đó là chỗ `|gold|` thật khác 1.
_OP = {
    "ratio": ("tỷ lệ", "tỷ suất", "roe", "roa", "biên", "%", "phần trăm", "lần"),
    "delta": ("tăng", "giảm", "thay đổi", "chênh lệch", "so với"),
    "avg": ("trung bình", "bình quân"),
    "sum": ("tổng", "cộng"),
}


def op_of(q: str) -> str:
    low = q.lower()
    for op, cues in _OP.items():
        if any(c in low for c in cues):
            return op
    return "lookup"


def _rank(qid: int) -> str:
    """Khoá trộn tất định. Không dùng `random` — cùng đề, cùng mẫu, mọi lúc."""
    return hashlib.sha256(str(qid).encode()).hexdigest()


def questions() -> list[dict]:
    return [json.loads(l) for l in QPATH.open(encoding="utf-8") if l.strip()]


def cmd_sample(n: int) -> int:
    qs = questions()
    alias = load_aliases(brands=True)
    meta = []
    for q in qs:
        it = parse_intent(q["question"], alias)
        meta.append({"id": q["id"], "question": q["question"], "mode": it.mode,
                     "op": op_of(q["question"]), "n_targets": len(it.targets),
                     "targets": list(it.targets), "years": list(it.years)})

    by_mode: dict[str, list[dict]] = defaultdict(list)
    for m in meta:
        by_mode[m["mode"]].append(m)

    chosen: list[dict] = []
    for mode, share in STRATA.items():
        pool = by_mode.get(mode, [])
        want = round(n * share)
        # Trong mỗi mode, phân tầng tiếp theo `op` rồi lấy vòng tròn để không
        # dồn hết vào `lookup` (nhóm đông nhất nhưng dễ nhất).
        by_op: dict[str, list[dict]] = defaultdict(list)
        for m in pool:
            by_op[m["op"]].append(m)
        for v in by_op.values():
            v.sort(key=lambda m: _rank(m["id"]))
        ops = sorted(by_op)
        i = 0
        while len([c for c in chosen if c["mode"] == mode]) < want and ops:
            op = ops[i % len(ops)]
            if by_op[op]:
                chosen.append(by_op[op].pop(0))
            else:
                ops.remove(op)
                continue
            i += 1
    # `screen_open` chỉ có 1 câu — luôn lấy, vì nó là ca duy nhất của một lớp lỗi.
    for m in by_mode.get("screen_open", []):
        chosen.append(m)

    chosen.sort(key=lambda m: m["id"])
    DEV.mkdir(parents=True, exist_ok=True)
    p = DEV / "gold_sample_v1.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for m in chosen:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    print(f"đã chọn {len(chosen)} câu → {p.relative_to(ROOT)}")
    print(f"  {'mode':12s} {'n':>4s}   ops")
    for mode in sorted({c['mode'] for c in chosen}):
        v = [c for c in chosen if c["mode"] == mode]
        ops = Counter(c["op"] for c in v)
        print(f"  {mode:12s} {len(v):4d}   " +
              " ".join(f"{k}:{n}" for k, n in sorted(ops.items())))
    print(f"  n_targets: " + " ".join(
        f"{k}mã:{n}" for k, n in sorted(Counter(c['n_targets'] for c in chosen).items())))
    return 0


_SQL_CANDS = """
SELECT t.table_uid, t.statement_type, t.periods, t.units, t.metric_codes,
       t.n_observations, t.execution_ready_obs, t.evidence_ref, d.basis,
       d.doc_year, d.directory_doc_id,
       substr(f.section_text,1,110), substr(f.row_labels,1,320),
       substr(f.col_labels,1,110)
FROM documents d
JOIN table_cards t ON t.doc_id = d.directory_doc_id
JOIN table_cards_fts f ON f.rowid = t.rowid
WHERE d.ticker IN ({tk}) AND d.doc_year BETWEEN ? AND ?
  {per}
  {mt}
ORDER BY t.table_uid
"""


def cmd_sheet(limit: int | None, max_cands: int) -> int:
    """Sinh phiếu gán. KHÔNG điểm, KHÔNG thứ hạng, sắp theo `table_uid`.

    HAI BỘ LỌC NGỮ NGHĨA — và vì sao chúng KHÔNG phải nhiễm
    ------------------------------------------------------
    Bản đầu chỉ lọc (mã, năm) rồi cắt 60 ứng viên đầu theo `table_uid`. Đo được:
    **118/119 câu có > 60 ứng viên** (câu mẫu: 406), nên "cắt 60 theo uid" chính
    là **lấy một tập con ngẫu nhiên** — bảng gold gần như chắc không nằm trong đó.
    Phiếu vô dụng, và tệ hơn: vô dụng một cách âm thầm.

    Sửa bằng hai bộ lọc, cả hai đều là **điều kiện cần về ngữ nghĩa**, không phải
    tín hiệu xếp hạng:

      1. `periods LIKE %<năm>-12-31%` — bảng không chứa kỳ được hỏi thì KHÔNG
         THỂ chứa số cần. Đây là định nghĩa, không phải phỏng đoán.
      2. `row_labels` khớp **OR của các token nội dung** — rộng hơn hẳn proxy
         gold (proxy đòi CỤM liền nhau). Đây là hành vi tra cứu bắt buộc: không
         ai đọc tay 406 bảng, và một phiếu 406 dòng thì không ai gán.

    Giới hạn phải khai: người gán làm việc trên **danh sách rút gọn**, nên trần
    recall của gold tay bị chặn bởi trần của bộ lọc (2). Đó là đánh đổi có ý
    thức — và nó vẫn KHÁC BẢN CHẤT với việc nhìn thứ hạng của hệ thống, là thứ
    `docs/70` §6.2 cấm.
    """
    p = DEV / "gold_sample_v1.jsonl"
    if not p.is_file():
        print("✗ chưa có mẫu — chạy `gold sample` trước")
        return 2
    sample = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    if limit:
        sample = sample[:limit]
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")

    out = DEV / "gold_worksheet_v1.jsonl"
    n_big = 0
    with out.open("w", encoding="utf-8") as f:
        for s in sample:
            tk = tuple(s["targets"]) or ()
            yrs = s["years"] or []
            lo = min(yrs) if yrs else 2015
            hi = (max(yrs) + 1) if yrs else 2025
            cands = []
            rows = []
            if tk:
                from retrieval.query_terms import content_terms
                toks = content_terms(s["question"], drop=tuple(tk))[:8]
                args: list = [*tk, lo, hi]
                per = mt = ""
                if yrs:
                    per = ("AND (" + " OR ".join("t.periods LIKE ?" for _ in yrs)
                           + ")")
                    args += [f"%{y}-12-31%" for y in yrs]
                if toks:
                    mt = "AND table_cards_fts MATCH ?"
                    args.append(" OR ".join(
                        'row_labels : "' + t.replace('"', '""') + '"' for t in toks))
                sql = _SQL_CANDS.format(tk=",".join("?" * len(tk)), per=per, mt=mt)
                try:
                    rows = conn.execute(sql, args).fetchall()
                except sqlite3.OperationalError:
                    rows = []
                if len(rows) > max_cands:
                    n_big += 1
                for r in rows[:max_cands]:
                    cands.append({
                        "uid": r[0], "ref": r[7], "stmt": r[1],
                        "basis": r[8], "doc_year": r[9],
                        "periods": r[2], "units": r[3], "codes": r[4],
                        "ready": f"{r[6]}/{r[5]}",
                        "section": r[11], "rows": r[12], "cols": r[13],
                    })
            f.write(json.dumps({
                "id": s["id"], "question": s["question"], "mode": s["mode"],
                "op": s["op"], "targets": s["targets"], "years": s["years"],
                "n_cands_total": len(rows) if tk else 0,
                "candidates": cands,
                # ── người gán điền hai trường dưới đây ──
                "gold_tables": [], "annotator": "", "note": "",
            }, ensure_ascii=False) + "\n")
    print(f"phiếu {len(sample)} câu → {out.relative_to(ROOT)}")
    print(f"  {n_big} câu vẫn > {max_cands} ứng viên sau hai bộ lọc ngữ nghĩa")
    print("  (đã cắt — `n_cands_total` ghi số THẬT để biết phiếu phủ bao nhiêu)")
    print("  điền `gold_tables` = danh sách `ref` (dạng DOC|line) THẬT SỰ chứa số cần.")
    print("  KHÔNG có điểm/thứ hạng trong phiếu — đó là chủ ý, xem docstring.")
    return 0


def cmd_check() -> int:
    """Kiểm gold đã gán: định dạng, tra được `table_uid`, phân bố `|gold|`."""
    p = DEV / "gold_v1.jsonl"
    if not p.is_file():
        print(f"✗ chưa có {p.relative_to(ROOT)}")
        return 2
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    idx = {str(ref).replace("|line:", "|"): uid for uid, ref in conn.execute(
        "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
    rows = [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]
    bad, sizes, by_mode = [], [], Counter()
    for r in rows:
        refs = r.get("gold_tables") or []
        if not refs:
            bad.append((r["id"], "gold_tables RỖNG"))
            continue
        for ref in refs:
            if str(ref).replace("|line:", "|") not in idx:
                bad.append((r["id"], f"không tra được: {ref}"))
        sizes.append(len(refs))
        by_mode[r.get("mode", "?")] += 1
    print(f"gold đã gán : {len(rows)} câu")
    print(f"  lỗi       : {len(bad)}")
    for qid, why in bad[:15]:
        print(f"     q{qid}: {why}")
    if sizes:
        sizes.sort()
        print(f"  |gold|    : median={sizes[len(sizes)//2]} max={sizes[-1]} "
              f"mean={sum(sizes)/len(sizes):.2f}")
        print(f"     =1: {sizes.count(1)}  =2: {sizes.count(2)}  ≥3: {sum(1 for x in sizes if x>=3)}")
        print("     ↑ so với proxy: median 8, chỉ 6,3% câu có đúng 1 bảng")
    print(f"  theo mode : " + " ".join(f"{k}:{v}" for k, v in sorted(by_mode.items())))
    ann = Counter(r.get("annotator") or "(trống)" for r in rows)
    print(f"  người gán : " + " ".join(f"{k}:{v}" for k, v in ann.most_common()))
    return 1 if bad else 0


def cmd_agree(a: str, b: str) -> int:
    """Đo đồng thuận giữa hai người gán trên các câu CẢ HAI đã gán.

    Không có số này thì không biết gold tay đáng tin bao nhiêu — và một gold mà
    hai người gán khác nhau 30% thì không dùng để phán xử proxy được.
    """
    pa, pb = DEV / f"gold_{a}.jsonl", DEV / f"gold_{b}.jsonl"
    for p in (pa, pb):
        if not p.is_file():
            print(f"✗ thiếu {p.relative_to(ROOT)}")
            return 2
    A = {r["id"]: set(r.get("gold_tables") or [])
         for r in (json.loads(l) for l in pa.open(encoding="utf-8") if l.strip())}
    B = {r["id"]: set(r.get("gold_tables") or [])
         for r in (json.loads(l) for l in pb.open(encoding="utf-8") if l.strip())}
    common = sorted(set(A) & set(B))
    if not common:
        print("✗ không có câu chung")
        return 1
    exact = sum(1 for i in common if A[i] == B[i])
    overlap = sum(1 for i in common if A[i] & B[i])
    jac = sum(len(A[i] & B[i]) / max(len(A[i] | B[i]), 1) for i in common) / len(common)
    print(f"câu chung        : {len(common)}")
    print(f"khớp HOÀN TOÀN   : {exact}/{len(common)}  ({100*exact/len(common):.1f}%)")
    print(f"có giao ≥1 bảng  : {overlap}/{len(common)}  ({100*overlap/len(common):.1f}%)")
    print(f"Jaccard trung bình: {jac:.4f}")
    print("")
    print("Ngưỡng của `docs/75` §PHA 1: đồng thuận < 85% ⇒ định nghĩa 'liên quan'")
    print("của ta chưa rõ, phải chốt lại TRƯỚC khi gán tiếp.")
    khac = [i for i in common if A[i] != B[i]]
    for i in khac[:12]:
        print(f"  q{i:<5d} {a}={sorted(A[i])}  {b}={sorted(B[i])}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="goldkit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample"); s.add_argument("--n", type=int, default=120)
    s = sub.add_parser("sheet")
    s.add_argument("--limit", type=int)
    s.add_argument("--max-cands", type=int, default=60)
    sub.add_parser("check")
    s = sub.add_parser("agree")
    s.add_argument("--a", default="ai"); s.add_argument("--b", default="human")
    ns = ap.parse_args(argv)
    if ns.cmd == "sample":
        return cmd_sample(ns.n)
    if ns.cmd == "sheet":
        return cmd_sheet(ns.limit, ns.max_cands)
    if ns.cmd == "check":
        return cmd_check()
    return cmd_agree(ns.a, ns.b)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
