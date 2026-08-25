import sys,json,re,collections
sys.path.insert(0,'src')
from retrieval.alias_store import load_aliases
from retrieval.normalize import ascii_compact, company_aliases, ticker_mentioned
from retrieval.question_intent import parse_intent
from retrieval.subject import classify, pick_subject, QuestionMode
import retrieval.subject as subj
from retrieval.evalkit.cli import _load_cfg
cfg=_load_cfg("base",{}); alias=load_aliases(brands=cfg.brands)
Q=[json.loads(l) for l in open('data/external/vifinqa/questions/questions.jsonl') if l.strip()]
print("so cau:",len(Q))
names_of={t:([n] if isinstance(n,str) else list(n)) for t,n in alias.items()}

def branches(q):
    compact=ascii_compact(q)
    hit={}
    for t,ns in names_of.items():
        b=max((len(a) for n in ns for a in company_aliases(n) if a in compact),default=0)
        if b: hit[t]=b
    def bibao(t):
        mine={a for n in names_of[t] for a in company_aliases(n) if a in compact}
        for u in hit:
            if u==t: continue
            th={a for n in names_of[u] for a in company_aliases(n) if a in compact}
            if any(m!=o and m in o for m in mine for o in th): return True
        return False
    nm={t for t in hit if not bibao(t)}
    tm={t for t in alias if ticker_mentioned(q,t)}
    shad={t for t in tm if any(t.lower() in ascii_compact(n) for c in nm for n in names_of[c])}
    return nm, tm-shad

# ---- RC-2: explicit nuot name ----
rc2=[]
for r in Q:
    nm,ex=branches(r['question'])
    if ex and (nm-ex):
        rc2.append((r['id'],sorted(ex),sorted(nm-ex)))
print("\nRC-2 · nhanh ticker nuot nhanh ten: %d/%d cau"%(len(rc2),len(Q)))
for x in rc2[:12]: print("   q%s  giu=%s  MAT=%s"%x)

# ---- RC-1: alias ngan khop chuoi con khong neo bien tu ----
# phat hien: alias khop nhung KHONG khop khi neo bien tu tren chuoi co dau cach
def compact_sp(s):
    s=ascii_compact.__wrapped__(s) if hasattr(ascii_compact,'__wrapped__') else None
    return s
import unicodedata
def deacc(s):
    s=unicodedata.normalize('NFD',s)
    s=''.join(c for c in s if unicodedata.category(c)!='Mn')
    return s.replace('đ','d').replace('Đ','D').lower()
def spaced(s):
    return re.sub(r'[^a-z0-9]+',' ',deacc(s)).strip()
rc1=[]
for r in Q:
    q=r['question']; compact=ascii_compact(q); sp=spaced(q)
    for t,ns in names_of.items():
        for n in ns:
            for a in company_aliases(n):
                if a in compact:
                    if not re.search(r'(?<![a-z0-9])%s(?![a-z0-9])'%re.escape(a.strip()), sp.replace(' ','')) :
                        pass
                    # kiem tra neo bien tu tren chuoi CO khoang trang
                    a_sp=' '.join(re.findall(r'[a-z0-9]+',a)) or a
                    if not re.search(r'(?<![a-z0-9])%s(?![a-z0-9])'%re.escape(a_sp), sp):
                        rc1.append((r['id'],t,a)); break
            else: continue
            break
seen=set(); rc1u=[x for x in rc1 if not (x[0] in seen or seen.add(x[0]))]
print("\nRC-1 · alias khop chuoi con KHONG neo bien tu: %d/%d cau"%(len(rc1u),len(Q)))
for x in rc1u[:15]: print("   q%s  ma=%s  alias='%s'"%x)

# ---- RC-3: mau compare thieu ----
print("\nRC-3 · _COMPARE hien tai:",subj._COMPARE)
pat=("chenh lech voi","so voi","chenh lech giua","cao hon","thap hon","giua","khac biet","bang bao nhieu lan")
cnt=collections.Counter()
rc3=[]
for r in Q:
    c=ascii_compact(r['question']); sp=spaced(r['question'])
    if 'chenh lech voi' in sp and not any(m in sp for m in subj._COMPARE):
        rc3.append(r['id'])
print("RC-3 · cau co 'chenh lech voi' ma khong khop mau _COMPARE nao: %d  %s"%(len(rc3),rc3[:20]))

# ---- RC-4: khoang nam khong no ----
YR=re.compile(r'(?<!\d)(20[0-2]\d)(?!\d)')
GD=re.compile(r'(giai doan|tu nam|trong khoang|giai đoạn|từ năm|trong giai doan)')
rc4=[]
for r in Q:
    q=r['question']; sp=spaced(q)
    ys=sorted({int(m.group(1)) for m in YR.finditer(q) if 2015<=int(m.group(1))<=2025})
    if len(ys)==2 and ys[1]-ys[0]>=2 and GD.search(sp):
        rc4.append((r['id'],ys,ys[1]-ys[0]-1))
print("\nRC-4 · 'giai doan A-B' co nam giua bi bo sot: %d cau · tong nam mat=%d"%(len(rc4),sum(x[2] for x in rc4)))
for x in rc4[:12]: print("   q%s %s  mat %d nam"%x)
# them: moi cau co 2 nam cach nhau >=2 (khong doi tu khoa)
loose=[r['id'] for r in Q if (lambda ys: len(ys)==2 and ys[1]-ys[0]>=2)(sorted({int(m.group(1)) for m in YR.finditer(r['question']) if 2015<=int(m.group(1))<=2025}))]
print("   (noi long, khong doi tu khoa 'giai doan'): %d cau"%len(loose))

# ---- tong ket phan giai ----
res=collections.Counter()
ntk=collections.Counter()
for r in Q:
    it=parse_intent(r['question'],alias)
    res[it.resolved_by]+=1
    ntk[min(len(it.tickers),5)]+=1
print("\nphan giai thuc the tren 1012 cau:",dict(res))
print("so ma nhan dien duoc/cau:",dict(sorted(ntk.items())))
print("cau KHONG co ma nao:",res['none'])
