"""So A6-first vs đường HTML (P0H) trên cùng dataset. Không kết luận ai đúng
chỉ vì khác nhau — mọi lệch đều quy về KHÔNG GIAN VND trước khi so, và ca chưa
đối chiếu được provenance thì ghi UNCERTAIN."""
from __future__ import annotations
import collections, json, os, re, sqlite3, sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from text2pandas.domain.rules.question import CompanyIndex, parse_question  # noqa: E402

c = sqlite3.connect('file:' + os.path.abspath(ROOT / 'artifacts/retrieval/work.db') + '?mode=ro', uri=True)
ev2uid = {ev.replace("|line:", "|"): u for u, ev in c.execute(
    "SELECT table_uid, evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
known = {r[0] for r in c.execute("SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}
companies = CompanyIndex.from_csv(ROOT / "data/external/vifinqa/code_stock.csv")
Q = {q["id"]: q for q in (json.loads(l) for l in
     (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8") if l.strip())}
A6 = {r["qid"]: r for r in (json.loads(l) for l in (ROOT / "data/dev/answer_a6/records_a6.jsonl").open(encoding="utf-8"))}
HT = {r["qid"]: r for r in (json.loads(l) for l in (ROOT / "data/dev/answer_v3/records_v4.jsonl").open(encoding="utf-8"))}
G = {}
for l in (ROOT / "data/dev/gold_v2.jsonl").open(encoding="utf-8"):
    r = json.loads(l)
    if r.get("gold_table_uids"):
        G[r["id"]] = set(r["gold_table_uids"])


def uid_cua(rec):
    if rec.get("provenance"):
        return rec["provenance"]["table_uid"]
    m = re.match(r"(.+)_line(\d+)\.csv$", rec.get("csv_name") or "")
    if not m:
        return None
    return ev2uid.get(f"{m.group(1)}_extracted|{m.group(2)}") or ev2uid.get(f"{m.group(1)}|{m.group(2)}")


# ── 1 · BẢNG NGUỒN ∈ GOLD (gold v2) ─────────────────────────────────────────
print("=" * 78); print("1 · BẢNG NGUỒN ∈ GOLD  (gold_v2, n=%d)" % len(G)); print("=" * 78)
for ten, D in (("HTML (P0H)", HT), ("A6-first", A6)):
    ok = sum(1 for q in G if uid_cua(D.get(q, {})) in G[q])
    print(f"  {ten:<12} {ok:>3}/{len(G)} = {ok/len(G):.4f}")

# ── 2 · LỆCH GIÁ TRỊ, QUY VỀ VND ────────────────────────────────────────────
print("\n" + "=" * 78); print("2 · SO GIÁ TRỊ TRONG KHÔNG GIAN VND (300 câu đầu)"); print("=" * 78)
ty = collections.Counter(); vd = []
n_so = 0
for qid in sorted(Q)[:300]:
    a, h = A6.get(qid), HT.get(qid)
    if not a or not h or a["nguon"] != "PRIMARY_A6" or h.get("answer") is None:
        continue
    slots = parse_question(qid, Q[qid]["question"], companies, known)
    w = slots.unit_exponent or 0
    try:
        hv = Decimal(str(h["answer"])) * (Decimal(10) ** w)
        av = Decimal(a["provenance"]["value_vnd"])
    except Exception:
        continue
    n_so += 1
    if av == hv or (av and abs(av - hv) <= abs(av) * Decimal("1e-9")):
        ty["BANG_NHAU"] += 1; continue
    if hv == 0 or av == 0:
        ty["MOT_BEN_BANG_0"] += 1
        if len(vd) < 40: vd.append((qid, "0", av, hv, a, h))
        continue
    r = av / hv
    k = None
    for e in range(-15, 16):
        if abs(r - Decimal(10) ** e) <= abs(r) * Decimal("1e-6"):
            k = e; break
    if k is not None:
        ty[f"LECH_10^{k}"] += 1
        if len(vd) < 40: vd.append((qid, f"10^{k}", av, hv, a, h))
    elif abs(abs(av) - abs(hv)) <= abs(av) * Decimal("1e-9"):
        ty["CHI_KHAC_DAU"] += 1
        if len(vd) < 40: vd.append((qid, "dau", av, hv, a, h))
    else:
        ty["KHAC_O"] += 1
print(f"  n so sánh được = {n_so}")
for k, v in ty.most_common():
    print(f"    {k:<18}{v:>4}  ({100*v/n_so:.1f}%)")

print("\n  ── mẫu lệch, kèm provenance để phân xử (KHÔNG tự kết luận A6 đúng) ──")
for qid, kind, av, hv, a, h in vd[:8]:
    pr = a["provenance"]
    print(f"   q{qid} [{kind}] A6={av} · HTML={hv}")
    print(f"        A6 raw={pr['value_source_raw']!r} scale=10^{pr['scale_exponent']}({pr['scale_source']})"
          f" ky={pr['period_end']}({pr['period_source']})")
    print(f"        A6 row={pr['row_path'][:52]!r}")
    print(f"        HTML query={ (h.get('pandas_query') or '')[:96] }")
json.dump({k: v for k, v in ty.items()}, open(ROOT / "data/dev/answer_a6/doi_chieu.json", "w"))
