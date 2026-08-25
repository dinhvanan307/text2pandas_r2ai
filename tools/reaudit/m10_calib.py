import json,sqlite3,os,collections
D60=json.load(open('/tmp/refs60.json')); D300=json.load(open('/tmp/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
S={str(r['id']):r for r in (json.loads(l) for l in open('data/dev/gold_tay_sample_v2.jsonl') if l.strip())}
tang={q:S[q]['tang'] for q in S}
Q=sorted(G)
NLAB=collections.Counter(tang[q] for q in Q); NTOT=collections.Counter(S[q]['tang'] for q in S)
print("gan duoc theo tang:",dict(NLAB),"/",dict(NTOT))
W={'T1T2':851/1012,'screen':161/1012}
print("trong so quan the: T1+T2=%.4f screen=%.4f"%(W['T1T2'],W['screen']))
def f2set(qs,k,cap,D,order=None):
    if not qs: return 0
    s=0
    for q in qs:
        N=min(max(1,k*D[q]['o']),cap); refs=D[q]['refs']
        if order: refs=order(q,refs)
        rr=refs[:N]; g=G[q]; h=len(set(rr)&g); s+=5*h/(4*len(g)+len(rr))
    return s/len(qs)
orc=lambda q,refs:[x for x in refs if x in G[q]]+[x for x in refs if x not in G[q]]
A=[q for q in Q if tang[q] in ('T1','T2')]; B=[q for q in Q if tang[q]=='screen']
covA=(NLAB['T1']+NLAB['T2'])/(NTOT['T1']+NTOT['T2']); covB=NLAB['screen']/NTOT['screen']
print("do phu nhan: T1+T2=%.4f  screen=%.4f  tong=%.4f"%(covA,covB,len(Q)/120))
def est(k,cap,D,order=None,label=""):
    a=f2set(A,k,cap,D,order); b=f2set(B,k,cap,D,order)
    raw=(len(A)*a+len(B)*b)/(len(A)+len(B))
    pop=W['T1T2']*a+W['screen']*b
    cal=W['T1T2']*a*covA+W['screen']*b*covB
    print("  %-22s T1T2=%.4f screen=%.4f | mau=%.4f | tai can=%.4f | HIEU CHUAN=%.4f"%(label,a,b,raw,pop,cal))
    return cal
print("\n=== uoc luong F2 bang xep hang (mo hinh hieu chuan hai tang) ===")
est(3,30,D60,None,"hien tai k=3 cap=30")
print("   (thuc te bang xep hang P0E = 0.3538)")
print("\n=== cac kich ban ===")
for k,cap in ((2,30),(3,30),(3,40),(4,40)):
    est(k,cap,D60,None,"S2 k=%d cap=%d"%(k,cap))
print()
est(2,30,D60,orc,"ORACLE depth60 k=2")
est(3,30,D60,orc,"ORACLE depth60 k=3")
est(2,30,D300,orc,"ORACLE depth300 k=2")
est(3,30,D300,orc,"ORACLE depth300 k=3")
# tran chon hoan hao
for name,D in (("depth60",D60),("depth300",D300)):
    def per(qs):
        s=0
        for q in qs:
            g=G[q]; h=len(set(D[q]['refs'])&g); N=max(1,h); s+=5*h/(4*len(g)+N)
        return s/len(qs)
    a,b=per(A),per(B)
    print("  %-22s T1T2=%.4f screen=%.4f | HIEU CHUAN=%.4f"%("TRAN N=h "+name,a,b,W['T1T2']*a*covA+W['screen']*b*covB))
