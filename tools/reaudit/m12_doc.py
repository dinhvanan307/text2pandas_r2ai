import json,sqlite3,os,collections,statistics
D=json.load(open('/tmp/reaudit/refs300.json'))
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
u2r={u:ev.replace('|line:','|') for u,ev in conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
G={}
for l in open('data/dev/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): G[str(r['id'])]=set(u2r[u] for u in r['gold_table_uids'] if u in u2r)
tang={str(r['id']):r['tang'] for r in (json.loads(l) for l in open('data/dev/gold_tay_sample_v2.jsonl') if l.strip())}
Q=sorted(G); doc=lambda x:x.split('|')[0]
W_A,W_B=851/1012,161/1012
A=[q for q in Q if tang[q]!='screen']; B=[q for q in Q if tang[q]=='screen']
covA,covB=61/80,28/40
def f2(qs,k,cap,filt=None):
    s=0
    for q in qs:
        refs=D[q]['refs']
        if filt: refs=[x for x in refs if filt(q,x)]
        N=min(max(1,k*D[q]['o']),cap); rr=refs[:N] or refs[:1]
        g=G[q]; h=len(set(rr)&g); s+=5*h/(4*len(g)+max(1,len(rr)))
    return s/len(qs) if qs else 0
def rep(name,k,cap,filt=None):
    a=f2(A,k,cap,filt); b=f2(B,k,cap,filt)
    print("  %-34s T1T2=%.4f screen=%.4f | mau=%.4f | HIEU CHUAN=%.4f"%(name,a,b,(len(A)*a+len(B)*b)/89,W_A*a*covA+W_B*b*covB))
golddoc={q:set(doc(x) for x in G[q]) for q in Q}
print("=== TRAN 'LOC TAI LIEU HOAN HAO' (chi giu bang thuoc tai lieu gold, giu thu tu S2) ===")
rep("baseline k=3 cap=30",3,30)
rep("+ loc tai lieu hoan hao k=3",3,30,lambda q,x: doc(x) in golddoc[q])
rep("+ loc tai lieu hoan hao k=2",2,30,lambda q,x: doc(x) in golddoc[q])
rep("+ loc tai lieu hoan hao k=1",1,30,lambda q,x: doc(x) in golddoc[q])
print("\n=== do nhap nhang TRONG tai lieu gold (T1/T2) ===")
amb=[]
for q in A:
    gd=golddoc[q]; inl=[x for x in D[q]['refs'] if doc(x) in gd]
    amb.append((len(inl),len(G[q])))
n=[x[0] for x in amb]
print("  so BANG ung vien thuoc dung tai lieu gold: median=%d mean=%.1f max=%d"%(statistics.median(n),sum(n)/len(n),max(n)))
print("  so bang gold                             : median=%d mean=%.1f"%(statistics.median([x[1] for x in amb]),sum(x[1] for x in amb)/len(amb)))
print("  => ty le nhieu trong dung tai lieu       : %.1f bang sai / 1 bang dung"%((sum(n)-sum(x[1] for x in amb))/sum(x[1] for x in amb)))
print("\n=== DOCS metric o chinh sach hien tai (k=3 cap=30, depth 60) ===")
D60=json.load(open('/tmp/refs60.json'))
for name,qs,w in (("T1+T2",A,None),("screen",B,None),("ALL",Q,None)):
    P=R=F=0
    for q in qs:
        N=min(max(1,3*D60[q]['o']),30); rr=set(doc(x) for x in D60[q]['refs'][:N]); g=golddoc[q]
        h=len(rr&g); P+=h/len(rr); R+=h/len(g); F+=5*h/(4*len(g)+len(rr))
    print("  %-8s DOCS P=%.4f R=%.4f F2=%.4f"%(name,P/len(qs),R/len(qs),F/len(qs)))
