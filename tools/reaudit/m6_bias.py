import json,collections,statistics
# --- pool v5 source bias ---
tot=0; only_s2=0; fts_only=0; strong=0; per=[]
src_cnt=collections.Counter()
for l in open('data/curated/dev-legacy/gold_tay_pool_v5.jsonl'):
    r=json.loads(l)
    cands=r.get('cands') or r.get('candidates') or []
    if not cands:
        print("key mau:",list(r)[:12]); break
else:
    pass
rows=[json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_pool_v5.jsonl')]
print("pool v5 rows:",len(rows),"| keys:",list(rows[0])[:14])
k=[x for x in rows[0] if isinstance(rows[0][x],list)]
print("list keys:",k)
print(json.dumps({kk:(rows[0][kk][:2] if isinstance(rows[0][kk],list) else rows[0][kk]) for kk in rows[0]},ensure_ascii=False)[:900])
