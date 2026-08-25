import sys,json,collections
sys.path.insert(0,'src')
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg
from text2pandas.pipelines.retrieval.question_intent import parse_intent
cfg=_load_cfg("base",{}); alias=load_aliases(brands=cfg.brands)
Q=[json.loads(l) for l in open('data/raw/btc/questions/questions.jsonl') if l.strip()]
mode=collections.Counter(); byid={}
for r in Q:
    it=parse_intent(r['question'],alias); mode[it.mode]+=1; byid[r['id']]=it.mode
print("mode tren 1012:",dict(mode),{k:round(100*v/1012,1) for k,v in mode.items()})
S=[json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_sample_v2.jsonl') if l.strip()]
print("\nmau 120 keys:",list(S[0]))
tt=collections.Counter((r['tang'],byid.get(r['id'],'?')) for r in S)
print("mau: (tang,mode) ->",dict(tt))
print("\nmau theo tang:",collections.Counter(r['tang'] for r in S))
# tang cua toan bo 1012? tang duoc dinh nghia the nao
print(json.dumps(S[0],ensure_ascii=False)[:400])
