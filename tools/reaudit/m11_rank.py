import json,sqlite3,os,collections,statistics
D=json.load(open('/tmp/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
u2r={};meta={}
for u,ev,st,ro,nr,ty,yr in conn.execute("SELECT table_uid,evidence_ref,statement_type,execution_ready_obs,n_rows,ticker,doc_year FROM table_cards WHERE evidence_ref IS NOT NULL"):
    r=ev.replace('|line:','|'); u2r[u]=r; meta[r]=(st,ro or 0,nr or 0,ty,yr)
G={}
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/dev/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
print("=== thu hang cua gold trong danh sach S2 (top-300) ===")
for t in ('T1','T2','screen'):
    qs=[q for q in Q if tang[q]==t]
    first=[]; allr=[]
    for q in qs:
        pos=[i+1 for i,x in enumerate(D[q]['refs']) if x in G[q]]
        if pos: first.append(min(pos)); allr+=pos
    allr.sort()
    print("  %-7s n=%2d | hang gold DAU TIEN: median=%d  p90=%d  max=%d | moi hang gold: median=%d p75=%d p90=%d"%(
      t,len(qs),statistics.median(first),first[int(.9*len(first))-1],max(first),
      statistics.median(allr),allr[int(.75*len(allr))-1],allr[int(.9*len(allr))-1]))
print("\n=== hang-1 dung khong? (precision@1) ===")
for t in ('T1','T2','screen',None):
    qs=[q for q in Q if t is None or tang[q]==t]
    p1=sum(1 for q in qs if D[q]['refs'][0] in G[q])
    p3=sum(1 for q in qs if set(D[q]['refs'][:3])&G[q])
    print("  %-7s n=%2d  hit@1=%d (%.3f)  hit@3=%d (%.3f)"%(t or 'ALL',len(qs),p1,p1/len(qs),p3,p3/len(qs)))
print("\n=== cai gi nam TREN gold dau tien? (T1/T2, chan doan rerank) ===")
same_doc=0; same_tk_yr=0; other=0; tot=0
ex=[]
for q in Q:
    if tang[q]=='screen': continue
    pos=[i for i,x in enumerate(D[q]['refs']) if x in G[q]]
    if not pos: continue
    fp=min(pos); g1=D[q]['refs'][fp]
    gdoc=g1.split('|')[0]; gm=meta.get(g1)
    for x in D[q]['refs'][:fp]:
        tot+=1
        if x.split('|')[0]==gdoc: same_doc+=1
        elif meta.get(x) and gm and meta[x][3]==gm[3] and meta[x][4]==gm[4]: same_tk_yr+=1
        else: other+=1
    if fp>0 and len(ex)<8: ex.append((q,tang[q],fp,[ (x.split('|')[0][:26],meta.get(x,('?',))[0]) for x in D[q]['refs'][:min(fp,3)]],(gdoc[:26],gm[0])))
print("  tong ung vien xep TREN gold dau tien: %d"%tot)
if tot:
    print("   - CUNG tai lieu voi gold        : %d (%.1f%%)  <- sai bang trong dung tai lieu"%(same_doc,100*same_doc/tot))
    print("   - cung (ma,nam) khac tai lieu   : %d (%.1f%%)"%(same_tk_yr,100*same_tk_yr/tot))
    print("   - khac hoan toan                : %d (%.1f%%)"%(other,100*other/tot))
print("\n  vi du:")
for q,t,fp,tops,g in ex: print("   q%-5s %-3s gold o hang %d · tren no: %s · gold: %s"%(q,t,fp+1,tops,g))
# statement_type cua nhieu tren gold
c=collections.Counter()
for q in Q:
    if tang[q]=='screen': continue
    pos=[i for i,x in enumerate(D[q]['refs']) if x in G[q]]
    if not pos: continue
    for x in D[q]['refs'][:min(pos)]: c[meta.get(x,('?',))[0]]+=1
print("\n  statement_type cua ung vien chen tren gold:",dict(c.most_common()))
cg=collections.Counter(meta[x][0] for q in Q if tang[q]!='screen' for x in G[q] if x in meta)
print("  statement_type cua chinh gold T1/T2 :",dict(cg.most_common()))
