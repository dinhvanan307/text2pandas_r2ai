import json,sqlite3,os
D=json.load(open('artifacts/runs/retrieval/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
F2g=lambda p,r: 5*p*r/(4*p+r) if (4*p+r)>0 else 0.0
def mix(q,refs,frac,seed=0):
    """tron mot phan gold len dau: frac=0 -> S2 goc, frac=1 -> oracle"""
    import random; rnd=random.Random(hash((q,seed))&0xffff)
    gold=[x for x in refs if x in G[q]]; rest=[x for x in refs if x not in G[q]]
    up=[x for x in gold if rnd.random()<frac]
    return up+[x for x in refs if x not in set(up)]
def ev(k,cap,frac):
    Ps=[];Rs=[];Fs=[]
    for q in Q:
        N=min(max(1,k*D[q]['o']),cap)
        rr=mix(q,D[q]['refs'],frac)[:N]; g=G[q]; h=len(set(rr)&g)
        Ps.append(h/len(rr)); Rs.append(h/len(g)); Fs.append(5*h/(4*len(g)+len(rr)))
    P=sum(Ps)/len(Ps); R=sum(Rs)/len(Rs)
    return P,R,sum(Fs)/len(Fs),F2g(P,R)
print("=== GHEP CAP: chat luong xep hang <-> N toi uu  (phep gop A = mean F2 tung cau) ===")
print("chat luong |  (k,cap) toi uu  |  F2   |  P     |  R     | N_tb")
GRID=[(k,c) for k in (1,2,3,4,5,6) for c in (5,10,15,20,30,40)]
for frac,nm in ((0.0,"S2 hien tai"),(0.25,"tot hon 25%"),(0.5,"tot hon 50%"),(0.75,"tot hon 75%"),(1.0,"ORACLE")):
    best=(-1,None,None)
    for k,c in GRID:
        P,R,fa,fb=ev(k,c,frac)
        if fa>best[0]: best=(fa,(k,c),(P,R))
    nb=sum(min(max(1,best[1][0]*D[q]['o']),best[1][1]) for q in Q)/len(Q)
    print("%-11s|  k=%d cap=%-3d    | %.4f | %.4f | %.4f | %5.2f"%(nm,best[1][0],best[1][1],best[0],best[2][0],best[2][1],nb))
print("\n=== cung the, theo phep gop B = F2(P_macro, R_macro) ===")
for frac,nm in ((0.0,"S2 hien tai"),(0.5,"tot hon 50%"),(1.0,"ORACLE")):
    best=(-1,None,None)
    for k,c in GRID:
        P,R,fa,fb=ev(k,c,frac)
        if fb>best[0]: best=(fb,(k,c),(P,R))
    print("%-11s|  k=%d cap=%-3d    | %.4f | %.4f | %.4f"%(nm,best[1][0],best[1][1],best[0],best[2][0],best[2][1]))
print("\n=== TRAN PRECISION theo chinh sach N (xep hang hoan hao) ===")
print("(P_max = trung binh min(g,N)/N — chinh sach N CHAN precision o day)")
for k,cap in ((1,10),(2,10),(2,20),(3,30),(4,40),(5,10)):
    P,R,fa,fb=ev(k,cap,1.0)
    print("  k=%d cap=%-3d : P_max=%.4f  R_max=%.4f   (hang 1 that: P=0.605 R=0.493)"%(k,cap,P,R))
print("\n=== N CO DINH (khong nhan so o) · phep gop A ===")
def evN(Nfix):
    Ps=[];Rs=[];Fs=[]
    for q in Q:
        rr=D[q]['refs'][:Nfix]; g=G[q]; h=len(set(rr)&g)
        Ps.append(h/len(rr)); Rs.append(h/len(g)); Fs.append(5*h/(4*len(g)+len(rr)))
    P=sum(Ps)/len(Ps);R=sum(Rs)/len(Rs);return P,R,sum(Fs)/len(Fs),F2g(P,R)
for n in (1,2,3,4,5,6,8,10,15,20):
    P,R,fa,fb=evN(n); print("  N=%-3d : P=%.4f R=%.4f | meanF2=%.4f | F2(P,R)=%.4f"%(n,P,R,fa,fb))
