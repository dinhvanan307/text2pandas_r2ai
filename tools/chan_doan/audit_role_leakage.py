"""PHASE 1b · Tin hieu VAI TRO co bi nhiem tu quy trinh phan xu P0-d khong?
Tach 89 cau thanh 65 cau phan xu o P0-b (pool v3, CHUA co logic vai tro) va
24 cau phan xu o P0-d (pool v5, CO logic vai tro). Neu loi ich cua vai tro chi
xuat hien o nhom P0-d thi do la nhiem, khong phai tin hieu."""
import json, sqlite3, os, sys, math
sys.path.insert(0,"src"); sys.path.insert(0,"tools")
import gold_pool_v4 as v4
from gold_pool_v5 import vai_tro_chat
from retrieval.alias_store import load_aliases
from retrieval.evalkit.cli import _load_cfg
from retrieval.question_intent import parse_intent
conn=sqlite3.connect('file:%s?mode=ro'%os.path.expanduser('~/fast/artifacts/retrieval/work.db'),uri=True)
M={}
for u,ev,s,rt,yr in conn.execute("SELECT table_uid,evidence_ref,statement_type,row_terms,doc_year FROM table_cards WHERE evidence_ref IS NOT NULL"):
    M[ev.replace("|line:","|")]={"st":s,"rows":rt or "","yr":yr}
u2r={u:ev.replace("|line:","|") for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
gold={r["id"]:set(u2r[u] for u in r["gold_table_uids"] if u in u2r)
      for r in (json.loads(l) for l in open("data/dev/gold_v1.jsonl") if l.strip()) if r.get("gold_table_uids")}
D=json.load(open("/tmp/refs60.json"))
mau={r["id"]:r["question"] for r in (json.loads(l) for l in open("data/dev/gold_tay_sample_v2.jsonl") if l.strip())}
cfg=_load_cfg("base", {}); alias=load_aliases(brands=cfg.brands)
CTX={q:(set(v4.nhu_cau_cua(mau[q])), set(parse_intent(mau[q],alias).years or [])) for q in gold}
P0B=set(json.load(open("/tmp/qid_p0b.json"))); P0D=set(json.load(open("/tmp/qid_p0d.json")))

def order(kind, qid, refs):
    if kind=="s2": return refs
    need,yrs=CTX[qid]; out=[]
    for i,x in enumerate(refs):
        m=M.get(x); 
        if not m: out.append((9,i,x)); continue
        sc=0
        if kind in ("nam","nam_vt"): sc+= 4 if (not yrs or m["yr"] in yrs) else 0
        if kind in ("vt","nam_vt"):
            sc+= 2 if (need and vai_tro_chat(m["st"],m["rows"]) & need) else 0
        out.append((-sc,i,x))
    return [x for _,_,x in sorted(out)]

def f2(kind, qids, k=3):
    s=0
    for qid in qids:
        g=gold[qid]; d=D[str(qid)]; N=min(max(1,k*d["o"]),30)
        rr=order(kind,qid,d["refs"])[:N]
        s+=5*len(set(rr)&g)/(4*len(g)+len(rr))
    return s/len(qids)

print("%-34s %10s %10s %10s"%("thu tu","89 cau","P0-b (65)","P0-d (24)"))
for kind,ten in (("s2","S2 hien tai"),("vt","chi VAI TRO"),("nam","chi NAM"),("nam_vt","NAM + VAI TRO")):
    print("%-34s %10.4f %10.4f %10.4f"%(ten,f2(kind,gold),f2(kind,P0B),f2(kind,P0D)))
print()
b=f2("s2",P0B); d=f2("s2",P0D)
print("loi ich cua VAI TRO   : P0-b %+.4f   P0-d %+.4f"%(f2("vt",P0B)-b, f2("vt",P0D)-d))
print("loi ich cua NAM       : P0-b %+.4f   P0-d %+.4f"%(f2("nam",P0B)-b, f2("nam",P0D)-d))
