import json,collections
rows=[json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_pool_v5.jsonl')]
print("candidate keys:",list(rows[0]['candidates'][0]))
tot=0; only_s2=0; fts_only=0; strong=0
sc=collections.Counter()
gold={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold[r['id']]=set(r['gold_table_uids'])
gsrc=collections.Counter(); gtot=0
for r in rows:
    for c in r['candidates']:
        s=set(c.get('sources') or [])
        tot+=1
        for x in s: sc[x]+=1
        if s<= {'s2'}: only_s2+=1
        if s<= {'s2','proxy'}: fts_only+=1
        if s & {'like','code','stmt'}: strong+=1
        if r['id'] in gold and c['table_uid'] in gold[r['id']]:
            gtot+=1
            for x in s: gsrc[x]+=1
print("\n=== POOL v5 · thien lech nguon (%d ung vien) ==="%tot)
for k,v in sc.most_common(): print("  %-8s %5d (%.1f%%)"%(k,v,100*v/tot))
print("  CHI s2            : %5d (%.1f%%)"%(only_s2,100*only_s2/tot))
print("  phu thuoc FTS {s2,proxy}: %5d (%.1f%%)"%(fts_only,100*fts_only/tot))
print("  co tin hieu MANH (like/code/stmt): %5d (%.1f%%)"%(strong,100*strong/tot))
print("\n=== GOLD (%d bang) theo nguon ==="%gtot)
for k,v in gsrc.most_common(): print("  %-8s %5d (%.3f)"%(k,v,v/gtot))
