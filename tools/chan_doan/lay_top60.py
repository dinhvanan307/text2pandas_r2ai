"""Lay top-60 ung vien cho 120 cau gold tay de quet nguong N. Chi doc, khong sua gi."""
import sys, json, sqlite3, os
sys.path.insert(0,"src")
from retrieval.alias_store import load_aliases
from retrieval.evalkit.cli import _load_cfg
from retrieval.evalkit.stages import Bm25StructuralRanker, HardFilterGenerator
from retrieval.question_intent import parse_intent
OUT="/tmp/refs60.json"
cfg=_load_cfg("base", {}); alias=load_aliases(brands=cfg.brands)
conn=sqlite3.connect("file:%s?mode=ro"%os.path.expanduser("~/fast/artifacts/retrieval/work.db"), uri=True)
conn.execute("PRAGMA cache_size=-200000")
s1=HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
s2=Bm25StructuralRanker(alias, top_k=max(cfg.top_k_rank,60), use_hints=cfg.use_hints,
                        basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
u2r={u:ev.replace("|line:","|") for u,ev in conn.execute(
    "SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
mau=[json.loads(l) for l in open("data/dev/gold_tay_sample_v2.jsonl") if l.strip()]
done=json.load(open(OUT)) if os.path.exists(OUT) else {}
tu,den=int(sys.argv[1]),int(sys.argv[2])
n=0
for r in mau[tu-1:den]:
    qid,q=r["id"],r["question"]
    if str(qid) in done: continue
    it=parse_intent(q, alias)
    o1=s1.generate(conn,q,it); o2=s2.rank(conn,q,it,o1)
    done[str(qid)]={"o":max(1,len(it.targets))*max(1,len(it.years)),
                    "refs":[u2r[x.table_uid] for x in o2.ranked[:60] if x.table_uid in u2r]}
    n+=1
    if n%5==0: json.dump(done, open(OUT,"w"))
json.dump(done, open(OUT,"w"))
print("xong %d · tong %d/120"%(n,len(done)))
