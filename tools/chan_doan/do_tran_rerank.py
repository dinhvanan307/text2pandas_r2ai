import json, sqlite3, os, sys, math, itertools
sys.path.insert(0,"src"); sys.path.insert(0,"tools")
import gold_pool_v4 as v4
from gold_pool_v5 import vai_tro_chat
from retrieval.alias_store import load_aliases
from retrieval.evalkit.cli import _load_cfg
from retrieval.question_intent import parse_intent
conn=sqlite3.connect('file:%s?mode=ro'%os.path.expanduser('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'),uri=True)
conn.execute("PRAGMA cache_size=-200000")
M={}
for u,ev,s,rt,ero,tk,yr,nr,mc in conn.execute("SELECT table_uid,evidence_ref,statement_type,row_terms,execution_ready_obs,ticker,doc_year,n_rows,metric_codes FROM table_cards WHERE evidence_ref IS NOT NULL"):
    M[ev.replace("|line:","|")]={"st":s,"rows":rt or "","obs":ero or 0,"yr":yr,"nr":nr or 0,
        "mc":mc or "","basis":"separate" if "_separate" in ev else "consolidated"}
u2r={u:ev.replace("|line:","|") for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
gold={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold[r['id']]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
D=json.load(open('/tmp/refs60.json'))
mau={r["id"]:r["question"] for r in (json.loads(l) for l in open("data/curated/dev-legacy/gold_tay_sample_v2.jsonl") if l.strip())}
cfg=_load_cfg("base", {}); alias=load_aliases(brands=cfg.brands)
CTX={}
for qid in gold:
    it=parse_intent(mau[qid], alias)
    CTX[qid]=(set(v4.nhu_cau_cua(mau[qid])), set(it.years or []), it.explicit_scope)
def feats(qid, ref):
    need,yrs,scope=CTX[qid]; m=M.get(ref)
    if not m: return None
    vt=vai_tro_chat(m["st"], m["rows"])
    return {"nam": 1 if (not yrs or m["yr"] in yrs) else 0,
            "vt": 1 if (need and vt&need) else 0,
            "ma": 1 if m["mc"].strip() else 0,
            "chinh": 1 if m["st"] in ("income_statement","balance_sheet","cash_flow") else 0,
            "bas": 1 if m["basis"]==(scope or "consolidated") else 0,
            "sz": math.log1p(m["obs"])/6.0}
def mk(w):
    def order(qid, refs):
        out=[]
        for i,x in enumerate(refs):
            f=feats(qid,x)
            sc=-sum(w[k]*f[k] for k in w) if f else 99
            out.append((sc,i,x))
        return [x for _,_,x in sorted(out)]
    return order
def f2(order,k=3,cap=30):
    s=0
    for qid,g in gold.items():
        d=D[str(qid)]; N=min(max(1,k*d["o"]),cap)
        rr=order(qid,d["refs"])[:N]
        s+=5*len(set(rr)&g)/(4*len(g)+len(rr))
    return s/len(gold)
hien=lambda q,r:r
oracle=lambda q,r:[x for x in r if x in gold[q]]+[x for x in r if x not in gold[q]]
CAU=[("S2 hien tai",hien),
     ("chi nam",              mk({"nam":1})),
     ("nam+vaitro",           mk({"nam":4,"vt":2})),
     ("nam+vaitro+ma",        mk({"nam":4,"vt":2,"ma":1})),
     ("nam+vt+ma+chinh",      mk({"nam":4,"vt":2,"ma":1,"chinh":1})),
     ("nam+vt+ma+chinh+bas",  mk({"nam":4,"vt":2,"ma":1,"chinh":1,"bas":1})),
     ("+kich thuoc bang",     mk({"nam":4,"vt":2,"ma":1,"chinh":1,"bas":1,"sz":1})),
     ("oracle",oracle)]
for ten,o in CAU:
    print("%-24s k=2 %.4f | k=3 %.4f | k=4 %.4f"%(ten,f2(o,2),f2(o,3),f2(o,4)))
