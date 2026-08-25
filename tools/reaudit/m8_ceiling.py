import json,sqlite3,os,collections
D=json.load(open('/tmp/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/dev/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
print("n=%d  tong gold=%d  do sau tb=%.0f"%(len(Q),sum(len(G[q]) for q in Q),sum(len(D[q]['refs']) for q in Q)/len(Q)))
print("\n=== micro-Recall theo do sau tap ung vien S2 ===")
print("depth |  all  |  T1   |  T2   | screen | cau du gold")
for d in (10,30,60,100,150,200,250,300):
    line=[]
    for t in (None,'T1','T2','screen'):
        qs=[q for q in Q if t is None or tang[q]==t]
        num=sum(len(set(D[q]['refs'][:d])&G[q]) for q in qs); den=sum(len(G[q]) for q in qs)
        line.append(num/den)
    full=sum(1 for q in Q if G[q]<=set(D[q]['refs'][:d]))
    print("%5d | %.4f| %.4f| %.4f| %.4f | %2d/%d"%(d,line[0],line[1],line[2],line[3],full,len(Q)))
# gold khong bao gio xuat hien trong top-300
never=[]
for q in Q:
    m=G[q]-set(D[q]['refs'])
    if m: never.append((q,tang[q],len(m),len(G[q])))
print("\n=== gold NGOAI top-300 (tran that cua candidate generation) ===")
print("so cau con thieu: %d/%d · tong bang thieu %d/%d (%.1f%%)"%(
  len(never),len(Q),sum(x[2] for x in never),sum(len(G[q]) for q in Q),
  100*sum(x[2] for x in never)/sum(len(G[q]) for q in Q)))
for x in sorted(never,key=lambda z:-z[2])[:20]: print("   q%-5s %-7s thieu %2d/%2d"%x)
print("\n=== |gold| theo tang ===")
for t in ('T1','T2','screen'):
    qs=[q for q in Q if tang[q]==t]; gs=sorted(len(G[q]) for q in qs)
    print("  %-7s n=%2d  median=%d  mean=%.1f  max=%d  tong=%d"%(t,len(qs),gs[len(gs)//2],sum(gs)/len(gs),max(gs),sum(gs)))
# F2 with deeper candidate pool
def f2(k,cap,depth=300,order=None):
    s=0
    for q in Q:
        N=min(max(1,k*D[q]['o']),cap); refs=D[q]['refs'][:depth]
        if order: refs=order(q,refs)
        rr=refs[:N]; g=G[q]; h=len(set(rr)&g)
        s+=5*h/(4*len(g)+len(rr))
    return s/len(Q)
orc=lambda q,refs:[x for x in refs if x in G[q]]+[x for x in refs if x not in G[q]]
print("\n=== F2: co giup gi khi dao sau hon 60 khong? (thu tu S2) ===")
for k in (2,3,4):
    for cap in (30,40,60,100):
        print("  k=%d cap=%-4d depth=60 %.4f | depth=300 %.4f"%(k,cap,f2(k,cap,60),f2(k,cap,300)))
print("\n=== TRAN RERANK theo do sau ===")
for depth in (60,300):
    for k in (1,2,3):
        print("  depth=%-4d k=%d : S2 %.4f -> oracle %.4f (+%.4f)"%(depth,k,f2(k,30,depth),f2(k,30,depth,orc),f2(k,30,depth,orc)-f2(k,30,depth)))
# tran tuyet doi trong tap ung vien
for depth in (60,300):
    s=0
    for q in Q:
        g=G[q]; h=len(set(D[q]['refs'][:depth])&g); N=max(1,h)
        s+=5*h/(4*len(g)+N)
    print("  TRAN CHON HOAN HAO (N=h) depth=%d : F2=%.4f"%(depth,s/len(Q)))
