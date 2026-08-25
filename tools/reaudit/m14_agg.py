import json,sqlite3,os,collections
D=json.load(open('artifacts/retrieval/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/dev/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G)
F2=lambda p,r: 5*p*r/(4*p+r) if (4*p+r)>0 else 0.0

print("=== KIEM DINH: bang xep hang dung PHEP GOP NAO? ===")
print("doi        |   P    |   R    | F2 bao cao | F2(P,R) | lech")
for nm,p,r,f in (("var P0E",.1933,.4744,.3538),("hang1",.605,.493,.4980),("hang2",.632,.653,.6447),
                 ("var P0D",.1768,.1571,.1589)):
    print("%-10s | %.4f | %.4f |   %.4f   | %.4f  | %+.4f"%(nm,p,r,f,F2(p,r),f-F2(p,r)))
print("=> F2 bao cao LUON THAP HON F2(P,R). Dau hieu cua trung binh F2 TUNG CAU (bat dang thuc Jensen).")
print("   Doi cang yeu (nhieu cau h=0) lech cang lon -> khop co che.\n")

def do(k,cap,order=None,qs=None):
    qs=qs or Q; Ps=[];Rs=[];Fs=[]
    for q in qs:
        N=min(max(1,k*D[q]['o']),cap); refs=D[q]['refs']
        if order: refs=order(q,refs)
        rr=refs[:N]; g=G[q]; h=len(set(rr)&g)
        Ps.append(h/len(rr)); Rs.append(h/len(g)); Fs.append(5*h/(4*len(g)+len(rr)))
    P=sum(Ps)/len(Ps); R=sum(Rs)/len(Rs)
    return P,R,sum(Fs)/len(Fs),F2(P,R)

print("=== HAI PHEP GOP TREN GOLD TAY · quet (k,cap) ===")
print(" k  cap |  P_macro  R_macro | A: mean(F2_i) | B: F2(P,R) |  chenh")
best={'A':(0,None),'B':(0,None)}
for k in (1,2,3,4,5,6,8):
    for cap in (10,20,30,40,60):
        P,R,fa,fb=do(k,cap)
        if fa>best['A'][0]: best['A']=(fa,(k,cap))
        if fb>best['B'][0]: best['B']=(fb,(k,cap))
        mark=""
        print(" %-2d %-4d| %.4f  %.4f |    %.4f     |   %.4f   | %+.4f%s"%(k,cap,P,R,fa,fb,fb-fa,mark))
print("\n  TOI UU theo A (mean F2 tung cau): k,cap =",best['A'][1]," F2=%.4f"%best['A'][0])
print("  TOI UU theo B (F2 cua P,R macro): k,cap =",best['B'][1]," F2=%.4f"%best['B'][0])

print("\n=== P/R MACRO THEO TANG (k=3 cap=30) ===")
for t in ('T1','T2','screen'):
    qs=[q for q in Q if tang[q]==t]
    P,R,fa,fb=do(3,30,qs=qs)
    nb=sum(min(max(1,3*D[q]['o']),30) for q in qs)/len(qs)
    gb=sum(len(G[q]) for q in qs)/len(qs)
    print("  %-7s n=%2d  N_tb=%5.2f g_tb=%5.2f | P=%.4f R=%.4f | meanF2=%.4f F2(P,R)=%.4f"%(t,len(qs),nb,gb,P,R,fa,fb))

print("\n=== TRAN PRECISION BI CHINH SACH N CHAN (xep hang HOAN HAO, giu N hien tai) ===")
orc=lambda q,refs:[x for x in refs if x in G[q]]+[x for x in refs if x not in G[q]]
for k,cap in ((1,10),(2,20),(3,30),(4,40)):
    P,R,fa,fb=do(k,cap,orc)
    print("  k=%d cap=%-3d ORACLE : P=%.4f R=%.4f | meanF2=%.4f | F2(P,R)=%.4f"%(k,cap,P,R,fa,fb))
