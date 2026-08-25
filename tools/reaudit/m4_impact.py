import sys,json,re,collections,sqlite3,os
sys.path.insert(0,'src')
RC2=[70,413,416,419,422,435,534,594,774,788,790,791,797,800,819,853,942,955,963,979,987,991,1001,1012]
RC1=[429,540,542]
RC3=[767]
Q=[json.loads(l) for l in open('data/raw/btc/questions/questions.jsonl') if l.strip()]
YR=re.compile(r'(?<!\d)(20[0-2]\d)(?!\d)')
import unicodedata
def sp(s):
    d=unicodedata.normalize('NFD',s); s2=''.join(c for c in d if unicodedata.category(c)!='Mn').replace('đ','d').lower()
    return re.sub(r'[^a-z0-9]+',' ',s2).strip()
GD=re.compile(r'(giai doan|tu nam|trong khoang)')
RC4=[]
for r in Q:
    ys=sorted({int(m.group(1)) for m in YR.finditer(r['question']) if 2015<=int(m.group(1))<=2025})
    if len(ys)==2 and ys[1]-ys[0]>=2 and GD.search(sp(r['question'])): RC4.append(r['id'])
print("RC-1 anh huong targets:",len(RC1)," RC-2:",len(RC2)," RC-3:",len(RC3)," RC-4:",len(RC4))
U=set(RC1)|set(RC2)|set(RC3)|set(RC4)
print("hop cua 4 RC (khong trung):",len(U),"cau /1012 = %.1f%%"%(100*len(U)/1012))

# giao voi gold tay
sample={r['id']:r['tang'] for r in (json.loads(l) for l in open('data/curated/dev-legacy/gold_tay_sample_v2.jsonl') if l.strip())}
gold={}; unc={}
for l in open('data/curated/dev-legacy/gold_v1.jsonl'):
    r=json.loads(l)
    if r.get('gold_table_uids'): gold[r['id']]=r
    else: unc[r['id']]=r
print("\ngiao voi 120 cau mau gold tay:", sorted(U & set(sample)))
print("  trong do dang UNCERTAIN:", sorted(U & set(unc)))
print("  trong do da gan gold   :", sorted(U & set(gold)))

# 31 UNCERTAIN: phan loai reason
c=collections.Counter(r.get('reason','?') for r in unc.values())
print("\n31 cau UNCERTAIN theo reason:",dict(c))
print("  danh sach:",sorted(unc))
for qid in sorted(unc):
    r=unc[qid]; print("   q%-5s %-8s %-16s %s"%(qid,sample.get(qid,'?'),r.get('reason','?'),(r.get('missing_evidence') or '')[:70]))
