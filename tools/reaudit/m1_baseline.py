import json, collections, math
D=json.load(open('/tmp/refs60.json'))
gold={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold[str(r['id'])]=set(r['gold_table_uids'])
# map uid -> ref  (need db) -> instead map ref->uid via table_cards; but refs60 stores refs.
import sqlite3,os
db='data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath(db),uri=True)
u2r={}
for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL"):
    u2r[u]=ev.replace('|line:','|')
G={q:set(u2r[u] for u in s if u in u2r) for q,s in gold.items()}
miss={q:len(s)-len(G[q]) for q,s in gold.items() if len(s)!=len(G[q])}
print("qid gold co uid khong map duoc ref:",miss)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
print("n cau co gold:",len(Q),"tong bang gold:",sum(len(G[q]) for q in Q))

def stats_at(depth):
    hit_any=0; hit_full=0; rec=0.0; num=0; den=0
    for q in Q:
        refs=D[q]['refs'][:depth]; g=G[q]
        h=len(set(refs)&g)
        if h: hit_any+=1
        if h==len(g): hit_full+=1
        rec+=h/len(g); num+=h; den+=len(g)
    return hit_any,hit_full,rec/len(Q),num/den
print("\n=== Recall@N (tap ung vien top-60 cua S2) ===")
print("N   | co>=1 gold | du gold | macro-R | micro-R")
for d in (1,3,5,10,20,30,40,50,60):
    a,f,mr,ur=stats_at(d)
    print("%-4d| %2d/%d      | %2d/%d   | %.4f | %.4f"%(d,a,len(Q),f,len(Q),mr,ur))

def f2_policy(k,cap,order=None):
    tot=0; Ns=[]; per=collections.defaultdict(list)
    for q in Q:
        d=D[q]; N=min(max(1,k*d['o']),cap)
        refs=d['refs'] if order is None else order(q,d['refs'])
        rr=refs[:N]; g=G[q]; h=len(set(rr)&g)
        f=5*h/(4*len(g)+len(rr)) if (len(g)+len(rr)) else 0
        tot+=f; Ns.append(len(rr)); per[tang[q]].append(f)
    return tot/len(Q), sum(Ns)/len(Ns), {t:sum(v)/len(v) for t,v in per.items()}
print("\n=== F2 theo (k,cap) · thu tu S2 hien tai ===")
print("k \\ cap | " + " | ".join("%6d"%c for c in (10,20,30,40,50,60)))
for k in (1,2,3,4,5,10):
    row=[]
    for cap in (10,20,30,40,50,60):
        row.append("%.4f"%f2_policy(k,cap)[0])
    print("k=%-6d| "%k + " | ".join(row))
f2,nbar,pert=f2_policy(3,30)
print("\nk=3 cap=30: F2=%.4f  N_tb=%.2f  theo tang=%s"%(f2,nbar,{k:round(v,4) for k,v in pert.items()}))
# P, R at k=3 cap 30
P=R=0
for q in Q:
    d=D[q]; N=min(max(1,3*d['o']),30); rr=d['refs'][:N]; g=G[q]; h=len(set(rr)&g)
    P+=h/len(rr); R+=h/len(g)
print("k=3 cap=30 macro P=%.4f R=%.4f"%(P/len(Q),R/len(Q)))
# DOCS level
def doc(x): return x.split('|')[0]
Pd=Rd=F2d=0
for q in Q:
    d=D[q]; N=min(max(1,3*d['o']),30); rr=[doc(x) for x in d['refs'][:N]]; g=set(doc(x) for x in G[q])
    s=set(rr); h=len(s&g)
    Pd+=h/len(s); Rd+=h/len(g); F2d+=5*h/(4*len(g)+len(s))
print("DOCS (suy tu cung danh sach) macro P=%.4f R=%.4f F2=%.4f"%(Pd/len(Q),Rd/len(Q),F2d/len(Q)))
# oracle
def oracle(q,refs): return [x for x in refs if x in G[q]]+[x for x in refs if x not in G[q]]
print("\n=== Tran rerank (oracle: gold len dau, GIU nguyen tap ung vien) ===")
for k in (1,2,3,4,5):
    b=f2_policy(k,30)[0]; o=f2_policy(k,30,oracle)[0]
    print("k=%d cap=30 : S2=%.4f  oracle=%.4f  delta=%+.4f"%(k,b,o,o-b))
# ceiling: perfect selection of exactly gold that is present in top-60
tot=0
for q in Q:
    g=G[q]; present=set(D[q]['refs'])&g
    h=len(present); N=max(1,h)
    tot+=5*h/(4*len(g)+N)
print("\nTRAN TAP UNG VIEN (chon dung & du gold co trong top-60, N=h): F2=%.4f"%(tot/len(Q)))
tot=0
for q in Q:
    g=G[q]; tot+=5*len(g)/(4*len(g)+len(g))
print("TRAN TUYET DOI (gold hoan hao, N=g): F2=%.4f"%(tot/len(Q)))
# per tier recall@60
print("\n=== Recall@60 theo tang ===")
for t in ('T1','T2','screen'):
    qs=[q for q in Q if tang[q]==t]
    a=sum(1 for q in qs if set(D[q]['refs'])&G[q]); f=sum(1 for q in qs if G[q]<=set(D[q]['refs']))
    mr=sum(len(set(D[q]['refs'])&G[q])/len(G[q]) for q in qs)/len(qs)
    print("%-7s n=%2d  co>=1:%2d  du:%2d  macro-R@60=%.4f"%(t,len(qs),a,f,mr))
