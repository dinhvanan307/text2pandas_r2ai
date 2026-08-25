"""Audit SCALE: A6 nói gì vs bảng khai gì. Không bên nào được mặc định là đúng."""
from __future__ import annotations
import collections, json, os, sqlite3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
c = sqlite3.connect('file:'+os.path.abspath(ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db')+'?mode=ro', uri=True)
card = sqlite3.connect('file:'+os.path.abspath(ROOT/'artifacts/legacy/silver-pre-a6/card_index.sqlite')+'?mode=ro', uri=True)
UEXP = {}
for d, ln, ue in card.execute("SELECT doc_id,line_no,unit_exponent FROM card_meta"):
    UEXP[f"{d}|{ln}"] = ue
A6 = [json.loads(l) for l in (ROOT/"data/curated/dev-legacy/answer_a6/records_a6.jsonl").open(encoding="utf-8")]
mau = collections.Counter(); vidu = collections.defaultdict(list)
for r in A6:
    pr = r.get("provenance")
    if not pr: continue
    ev = (pr["evidence_ref"] or "").replace("|line:", "|")
    ue = UEXP.get(ev)
    a6s = pr["scale_exponent"]
    if ue is None: k = "bang_khong_co_card"
    elif ue == a6s: k = f"KHOP (10^{a6s})"
    else:
        k = f"XUNG DOT: A6=10^{a6s} vs bang=10^{ue}"
        if len(vidu[k]) < 3: vidu[k].append((r["qid"], pr["value_source_raw"], pr["scale_source"], pr["row_path"][:44]))
    mau[k] += 1
print("== A6 scale_exponent vs unit_exponent khai o muc BANG (n=%d dap an A6) ==" % sum(mau.values()))
for k, v in mau.most_common():
    print(f"  {k:<34}{v:>5}  ({100*v/sum(mau.values()):.1f}%)")
print("\n== vi du XUNG DOT (can phan xu tay, hien ghi UNCERTAIN) ==")
for k in sorted(vidu):
    for q, raw, src, row in vidu[k]:
        print(f"  [{k}] q{q} raw={raw!r} scale_source={src} row={row!r}")
print("\n== scale_source cua cac ca XUNG DOT ==")
xd = collections.Counter()
for r in A6:
    pr = r.get("provenance")
    if not pr: continue
    ue = UEXP.get((pr["evidence_ref"] or "").replace("|line:", "|"))
    if ue is not None and ue != pr["scale_exponent"]:
        xd[pr["scale_source"]] += 1
for k, v in xd.most_common(): print(f"  {str(k):<20}{v:>5}")
json.dump(dict(mau), open(ROOT/"data/curated/dev-legacy/answer_a6/scale_audit.json", "w"), ensure_ascii=False)
