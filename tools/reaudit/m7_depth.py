import sys,json,sqlite3,os,time
sys.path.insert(0,"src")
from retrieval.alias_store import load_aliases
from retrieval.evalkit.cli import _load_cfg
from retrieval.evalkit.stages import Bm25StructuralRanker, HardFilterGenerator
from retrieval.question_intent import parse_intent
DEPTH=300
OUT="/tmp/reaudit/refs300.json"
cfg=_load_cfg("base", {}); alias=load_aliases(brands=cfg.brands)
conn=sqlite3.connect("file:%s?mode=ro"%os.path.abspath("artifacts/retrieval/work.db"), uri=True)
conn.execute("PRAGMA cache_size=-200000")
s1=HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
s2=Bm25StructuralRanker(alias, top_k=max(cfg.top_k_rank,DEPTH), use_hints=cfg.use_hints,
                        basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
u2r={u:ev.replace("|line:","|") for u,ev in conn.execute(
    "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
gold=set()
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold.add(r['id'])
mau=[r for r in (json.loads(l) for l in open("data/dev/gold_tay_sample_v2.jsonl") if l.strip()) if r['id'] in gold]
done=json.load(open(OUT)) if os.path.exists(OUT) else {}
t0=time.time(); n=0
for r in mau:
    qid,q=r["id"],r["question"]
    if str(qid) in done: continue
    it=parse_intent(q, alias)
    o1=s1.generate(conn,q,it); o2=s2.rank(conn,q,it,o1)
    done[str(qid)]={"o":max(1,len(it.targets))*max(1,len(it.years)),
                    "n_s1":len(o1.candidates) if hasattr(o1,'candidates') else None,
                    "refs":[u2r[x.table_uid] for x in o2.ranked[:DEPTH] if x.table_uid in u2r]}
    n+=1
    if n%10==0:
        json.dump(done, open(OUT,"w")); print("  ..%d  %.0fs"%(n,time.time()-t0),flush=True)
json.dump(done, open(OUT,"w"))
print("xong %d cau · %.0fs · tong %d"%(n,time.time()-t0,len(done)))
