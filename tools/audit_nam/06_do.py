"""P0-e buoc 6 · do hai vi tu NAM tren gold audit trung lap, va do F2."""
from __future__ import annotations
import json, os, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "data/curated/dev-legacy/audit"
DB = Path(os.path.expanduser("data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"))

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
META = {}
for u, ev, yr, per in conn.execute(
        "SELECT t.table_uid,t.evidence_ref,d.doc_year,t.periods FROM table_cards t "
        "JOIN documents d ON t.doc_id=d.directory_doc_id"):
    META[u] = {"ref": (ev or "").replace("|line:", "|"), "doc_year": yr, "periods": per or ""}

GA = {r["id"]: r for r in (json.loads(l) for l in (AUD / "gold_audit_nam.jsonl").open(encoding="utf-8") if l.strip())}
POOL = {r["id"]: r for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/gold_tay_pool_v5.jsonl").open(encoding="utf-8") if l.strip())}
GOLD_CU = {r["id"]: set(r.get("gold_table_uids") or []) for r in (json.loads(l) for l in (ROOT / "data/curated/dev-legacy/gold_v1.jsonl").open(encoding="utf-8") if l.strip())}
CAU = [q for q, r in GA.items() if r["neo_chi_tieu"]]


def vi_tu_doc_year(u, nam_hoi):
    return META.get(u, {}).get("doc_year") in set(nam_hoi)


def vi_tu_periods(u, nam_hoi):
    ys = {int(x) for x in re.findall(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])",
                                     META.get(u, {}).get("periods", ""))}
    return bool(ys & set(nam_hoi))


def pr(vi_tu, tang=None):
    tp = fp = fn = 0
    for q in CAU:
        r = GA[q]
        if tang and r["tang"] != tang:
            continue
        g = {b["table_uid"] for b in r["gold"]}
        unc = {b["table_uid"] for b in r["uncertain"]}
        for c in POOL[q]["candidates"]:
            u = c["table_uid"]
            if u in unc:
                continue                      # UNCERTAIN khong tinh vao ca hai chieu
            p = vi_tu(u, r["nam_hoi"])
            if p and u in g: tp += 1
            elif p: fp += 1
            elif u in g: fn += 1
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    return P, R, tp, fp, fn


print("═" * 74)
print("A · GOLD AUDIT so voi GOLD CU")
print("═" * 74)
moi = cu_ = lech = 0
for q in CAU:
    r = GA[q]; g = {b["table_uid"] for b in r["gold"]}
    moi += len(g); cu_ += len(GOLD_CU.get(q, set()) & {c["table_uid"] for c in POOL[q]["candidates"]})
    lech += sum(1 for u in g if META.get(u, {}).get("doc_year") not in set(r["nam_hoi"]))
print(f"  {len(CAU)} cau phan xu duoc")
print(f"  gold cu (trong pool)                 : {cu_}")
print(f"  gold audit trung lap                 : {moi}")
print(f"  trong do doc_year != nam hoi         : {lech}  ({lech/moi:.1%})")
print(f"  => {lech} bang nay gold cu KHONG THE co, vi quy tac gold cu cam.")

print()
print("═" * 74)
print("B · PRECISION / RECALL cua hai vi tu, do tren gold audit")
print("═" * 74)
print(f"{'vi tu':<34}{'P':>8}{'R':>8}{'TP':>7}{'FP':>7}{'FN':>7}")
for ten, f in (("doc_year == nam hoi", vi_tu_doc_year),
               ("ky duoc hoi ∈ periods", vi_tu_periods)):
    P, R, tp, fp, fn = pr(f)
    print(f"{ten:<34}{P:>8.4f}{R:>8.4f}{tp:>7}{fp:>7}{fn:>7}")
print()
for tang in ("T1", "T2", "screen"):
    print(f"  ── {tang}")
    for ten, f in (("doc_year == nam hoi", vi_tu_doc_year),
                   ("ky duoc hoi ∈ periods", vi_tu_periods)):
        P, R, tp, fp, fn = pr(f, tang)
        print(f"     {ten:<31}{P:>8.4f}{R:>8.4f}{tp:>7}{fp:>7}{fn:>7}")


# ═══════════════════════════════════════════════════════════════════════════
# C · F2 tren gold audit — S2 goc so voi S2 + tin hieu ky
# ═══════════════════════════════════════════════════════════════════════════
U2R = {u: m["ref"] for u, m in META.items() if m["ref"]}
R2U = {v: k for k, v in U2R.items()}
D = json.load(open("/tmp/refs60.json"))
CAU_F2 = [q for q in CAU if str(q) in D]


def f2(khoa, k=3, cap=30, tang=None):
    s, n = 0.0, 0
    for q in CAU_F2:
        r = GA[q]
        if tang and r["tang"] != tang:
            continue
        g = {U2R[b["table_uid"]] for b in r["gold"] if b["table_uid"] in U2R}
        if not g:
            continue
        d = D[str(q)]; N = min(max(1, k * d["o"]), cap)
        rr = khoa(q, d["refs"])[:N]
        s += 5 * len(set(rr) & g) / (4 * len(g) + len(rr)); n += 1
    return (s / n if n else 0.0), n


goc = lambda q, refs: refs


def _key(q, refs, f):
    nh = GA[q]["nam_hoi"]
    return [x for _, _, x in sorted(
        ((0 if (x in R2U and f(R2U[x], nh)) else 1), i, x) for i, x in enumerate(refs))]


theo_doc_year = lambda q, refs: _key(q, refs, vi_tu_doc_year)
theo_periods = lambda q, refs: _key(q, refs, vi_tu_periods)

print()
print("═" * 74)
print("C · F2 tren GOLD AUDIT (chinh sach N hien tai: k=3, cap 30)")
print("═" * 74)
print(f"{'xep hang':<34}{'tat ca':>10}{'T1':>10}{'T2':>10}{'screen':>10}")
for ten, kh in (("S2 goc (baseline)", goc),
                ("S2 + uu tien doc_year", theo_doc_year),
                ("S2 + uu tien periods", theo_periods)):
    v = [f2(kh)[0]] + [f2(kh, tang=t)[0] for t in ("T1", "T2", "screen")]
    print(f"{ten:<34}" + "".join(f"{x:>10.4f}" for x in v))
print(f"\n  so cau vao phep do F2: {f2(goc)[1]}")
