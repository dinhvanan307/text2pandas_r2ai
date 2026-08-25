"""Tin hieu nao tach duoc gold khoi khong-gold trong top-60? (chi doc)"""
import json, sqlite3, os, sys, statistics as st
sys.path.insert(0,"src"); sys.path.insert(0,"tools")
import gold_pool_v4 as v4
from gold_pool_v5 import vai_tro_chat
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg
from text2pandas.pipelines.retrieval.question_intent import parse_intent
conn=sqlite3.connect('file:%s?mode=ro'%os.path.expanduser('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'),uri=True)
conn.execute("PRAGMA cache_size=-200000")
M={}
for u,ev,st_,rt,ero,tk,yr,nr,nc,mc in conn.execute(
  "SELECT table_uid,evidence_ref,statement_type,row_terms,execution_ready_obs,ticker,doc_year,n_rows,n_cols,metric_codes FROM table_cards WHERE evidence_ref IS NOT NULL"):
    M[ev.replace("|line:","|")]={"st":st_,"rows":rt or "","obs":ero or 0,"tk":tk,"yr":yr,
      "nr":nr or 0,"nc":nc or 0,"mc":mc or "","basis":"separate" if "_separate" in ev else "consolidated"}
u2r={u:ev.replace("|line:","|") for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
gold={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold[r['id']]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
D=json.load(open('/tmp/refs60.json'))
mau={r["id"]:r["question"] for r in (json.loads(l) for l in open("data/curated/dev-legacy/gold_tay_sample_v2.jsonl") if l.strip())}
cfg=_load_cfg("base", {}); alias=load_aliases(brands=cfg.brands)
FE={"g":[], "n":[]}
for qid,g in gold.items():
    it=parse_intent(mau[qid], alias); need=set(v4.nhu_cau_cua(mau[qid]))
    yrs=set(it.years or [])
    for ref in D[str(qid)]["refs"]:
        m=M.get(ref)
        if not m: continue
        vt=vai_tro_chat(m["st"], m["rows"])
        f={"vaitro": int(bool(need and vt&need)), "co_vaitro": int(bool(vt)),
           "nam_khop": int(m["yr"] in yrs) if yrs else -1,
           "basis_khop": int(m["basis"]==(it.explicit_scope or "consolidated")),
           "obs>0": int(m["obs"]>0), "obs": m["obs"], "nr": m["nr"], "nc": m["nc"],
           "co_ma": int(bool(m["mc"].strip())),
           "la_bctc_chinh": int(m["st"] in ("income_statement","balance_sheet","cash_flow"))}
        FE["g" if ref in g else "n"].append(f)
print("so ung vien: gold %d · khong-gold %d"%(len(FE["g"]),len(FE["n"])))
print()
print("%-16s %10s %10s %8s"%("dac trung","gold","khong-gold","ty le"))
for k in ("vaitro","co_vaitro","nam_khop","basis_khop","obs>0","co_ma","la_bctc_chinh"):
    a=st.mean([x[k] for x in FE["g"] if x[k]>=0]); b=st.mean([x[k] for x in FE["n"] if x[k]>=0])
    print("%-16s %10.3f %10.3f %8s"%(k,a,b,"%.2fx"%(a/b) if b else "inf"))
for k in ("obs","nr","nc"):
    a=st.median([x[k] for x in FE["g"]]); b=st.median([x[k] for x in FE["n"]])
    print("%-16s %10.1f %10.1f  (median)"%(k,a,b))
