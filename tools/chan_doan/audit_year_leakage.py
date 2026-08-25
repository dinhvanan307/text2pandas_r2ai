"""PHASE 1 · Kiem chung gia thuyet `doc_year == nam hoi` co phai tin hieu THAT
hay chi la he qua cua chinh quy tac phan xu gold (docs/82 §quy tac, dong "doc_year:
lay nam bao cao, khong suy tu cot nam so sanh").

Chi doc. Khong sua gold, khong sua src/retrieval/**.
"""
import json, sys, os, sqlite3, collections, re
sys.path.insert(0,"src"); sys.path.insert(0,"tools")
from gold_pool_v5 import vai_tro_chat

conn=sqlite3.connect('file:%s?mode=ro'%os.path.expanduser('~/fast/artifacts/retrieval/work.db'),uri=True)
ROW={u:(r or "") for u,r in conn.execute("SELECT table_uid,row_terms FROM table_cards")}
PER={u:(p or "") for u,p in conn.execute("SELECT table_uid,periods FROM table_cards")}

MAU={r["id"]:r for r in (json.loads(l) for l in open("data/dev/gold_tay_sample_v2.jsonl") if l.strip())}
POOL={r["id"]:r for r in (json.loads(l) for l in open("data/dev/gold_tay_pool_v5.jsonl") if l.strip())}
GOLD={r["id"]:r["gold_table_uids"] for r in (json.loads(l) for l in open("data/dev/gold_v1.jsonl") if l.strip())
      if r.get("gold_table_uids")}

def tang(qid): return MAU[qid].get("tier") or MAU[qid].get("tang") or "?"

# ── 1 · ty le khop nam cua GOLD va cua UNG VIEN duoc chao, theo tang ────────────
print("═"*74)
print("1 · GOLD khop nam vs UNG VIEN lech nam DUOC CHAO trong cung phieu")
print("═"*74)
print("%-10s %8s %10s %14s %14s"%("tang","so cau","gold khop","uv lech nam","gold lech nam"))
agg=collections.defaultdict(lambda: [0,0,0,0,0])
for qid,uids in GOLD.items():
    t=tang(qid); p=POOL[qid]; yrs=set(p.get("years") or [])
    a=agg[t]; a[0]+=1
    for u in uids:
        a[1]+=1
        m=next((c for c in p["candidates"] if c["table_uid"]==u), None)
        if m and yrs and m.get("doc_year") not in yrs: a[2]+=1
    a[3]+=sum(1 for c in p["candidates"] if yrs and c.get("doc_year") not in yrs)
    a[4]+=len(p["candidates"])
for t,a in sorted(agg.items()):
    print("%-10s %8d %10s %14s %14d"%(t,a[0],"%d/%d = %.3f"%(a[1]-a[2],a[1],(a[1]-a[2])/a[1]),
          "%d/%d = %.3f"%(a[3],a[4],a[3]/a[4]), a[2]))
tong=[sum(x) for x in zip(*agg.values())]
print("%-10s %8d %10s %14s %14d"%("TONG",tong[0],"%d/%d = %.3f"%(tong[1]-tong[2],tong[1],(tong[1]-tong[2])/tong[1]),
      "%d/%d = %.3f"%(tong[3],tong[4],tong[3]/tong[4]), tong[2]))
print("\n=> precision cua `doc_year match` tren gold = 1.000, FP = 0, FN = 0 O MOI TANG.")
print("   Nhung %d ung vien lech nam DA duoc chao trong phieu va bi loai 100%%."%tong[3])
print("   Deu nhau tuyet doi o moi tang la dau van cua MOT QUY TAC, khong phai mot hien tuong.")

# ── 2 · sinh doi lech nam: tap ma bo loc nam se giet ───────────────────────────
def jac(a,b):
    A=set(a.lower().split(" | ")); B=set(b.lower().split(" | "))
    return len(A&B)/len(A|B) if A|B else 0
print()
print("═"*74)
print("2 · Bang gold co 'sinh doi lech nam' gan nhu y het trong chinh pool")
print("═"*74)
loai=collections.Counter(); tong_g=0
for qid,uids in GOLD.items():
    p=POOL[qid]; yrs=set(p.get("years") or []); cand={c["table_uid"]:c for c in p["candidates"]}
    ques=MAU[qid]["question"].lower()
    kieu = "dau nam" if "đầu năm" in ques else ("cuoi nam" if "cuối năm" in ques else "trong ky")
    for u in uids:
        tong_g+=1; g=cand.get(u)
        if not g: continue
        vg=vai_tro_chat(g.get("statement_type"), ROW.get(u,""))
        for c in p["candidates"]:
            if c["table_uid"]==u or c.get("doc_year") in yrs: continue
            if c.get("ticker")!=g.get("ticker") or c.get("basis")!=g.get("basis"): continue
            if vai_tro_chat(c.get("statement_type"), ROW.get(c["table_uid"],""))!=vg: continue
            if jac(ROW.get(u,""), ROW.get(c["table_uid"],""))>=0.5:
                # sinh doi co THUC SU chua ky duoc hoi khong?
                nam_hoi=max(yrs) if yrs else None
                co_ky = nam_hoi is not None and str(nam_hoi) in PER.get(c["table_uid"],"")
                loai[(kieu, co_ky)]+=1
                break
print("%d/%d bang gold (%.3f) co sinh doi lech nam trong pool."
      %(sum(loai.values()),tong_g,sum(loai.values())/tong_g))
print()
print("%-12s %-26s %6s"%("kieu ky hoi","sinh doi co chua ky hoi?","so"))
for (k,c),n in sorted(loai.items()): print("%-12s %-26s %6d"%(k, "CO - thay the duoc" if c else "khong", n))
