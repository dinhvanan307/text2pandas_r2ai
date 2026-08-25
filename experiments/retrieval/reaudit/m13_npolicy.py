import json,sqlite3,os,collections
D=json.load(open('artifacts/runs/retrieval/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
print("=== XAC SUAT TRUNG THEO KHOANG THU HANG (gold tay) ===")
print("khoang | so slot | trung | p        | p/1.91 (uoc luong so gold BTC)")
for lo,hi in [(0,1),(1,3),(3,5),(5,10),(10,15),(15,20),(20,30),(30,60)]:
    slots=hits=0
    for q in Q:
        seg=D[q]['refs'][lo:hi]; slots+=len(seg); hits+=len(set(seg)&G[q])
    p=hits/slots if slots else 0
    print("%2d-%-3d | %6d  | %5d | %7.4f | %7.4f"%(lo+1,hi,slots,hits,p,p/1.91))
print("\nNGUONG BIEN: them 1 ung vien co loi khi p > F2/5")
print("  F2=0.3538 -> 7.08%   |   F2=0.45 -> 9.00%")
print("\n=== N/g (FACT tu bang xep hang) ===")
for nm,(p,r,nb) in {"var (P0E)":(0.1933,0.4744,7761/1012),"hang1":(0.605,0.493,None),"hang2":(0.632,0.653,None)}.items():
    ex="   N_tb=%.2f  g_suy=%.2f"%(nb,(p*nb)/r) if nb else ""
    print("  %-10s N/g = R/P = %.2f%s"%(nm,r/p,ex))
print("\n=== N/g cua ta tren gold tay ===")
for k,cap in ((1,30),(2,30),(3,30),(4,40)):
    tn=sum(min(max(1,k*D[q]['o']),cap) for q in Q); tg=sum(len(G[q]) for q in Q)
    print("  k=%d cap=%-3d : N_tb=%.2f g_tb=%.2f N/g=%.2f"%(k,cap,tn/len(Q),tg/len(Q),tn/tg))
print("\n=== theo tang (k=3 cap=30) ===")
for t in ('T1','T2','screen'):
    qs=[q for q in Q if tang[q]==t]
    tn=sum(min(max(1,3*D[q]['o']),30) for q in qs); tg=sum(len(G[q]) for q in qs)
    print("  %-7s N_tb=%.2f g_tb=%.2f N/g=%.2f"%(t,tn/len(qs),tg/len(qs),tn/tg))
# do nhay: gold bi thu nho ngau nhien con f=0.523
import random
print("\n=== DO NHAY: neu gold BTC la tap con ngau nhien 52,3% cua gold tay ===")
print("(gia dinh manh, chi doc theo CHIEU, khong doc theo tri so)")
for k,cap in ((1,30),(2,30),(3,30),(4,40),(5,40)):
    tot=[]
    for seed in range(20):
        rnd=random.Random(seed); s=0
        for q in Q:
            g=sorted(G[q]); m=max(1,round(0.523*len(g))); gs=set(rnd.sample(g,m))
            N=min(max(1,k*D[q]['o']),cap); rr=D[q]['refs'][:N]; h=len(set(rr)&gs)
            s+=5*h/(4*len(gs)+len(rr))
        tot.append(s/len(Q))
    print("  k=%d cap=%-3d : F2(gold thu nho)=%.4f  (goc %.4f)"%(k,cap,sum(tot)/len(tot),
      sum(5*len(set(D[q]['refs'][:min(max(1,k*D[q]['o']),cap)])&G[q])/(4*len(G[q])+min(max(1,k*D[q]['o']),cap)) for q in Q)/len(Q)))
