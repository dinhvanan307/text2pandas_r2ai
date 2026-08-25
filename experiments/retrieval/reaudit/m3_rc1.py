import sys,json,re,unicodedata,collections
sys.path.insert(0,'src')
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.normalize import ascii_compact, company_aliases, ticker_mentioned
from text2pandas.pipelines.retrieval.question_intent import parse_intent
from text2pandas.pipelines.retrieval.evalkit.cli import _load_cfg
cfg=_load_cfg("base",{}); alias=load_aliases(brands=cfg.brands)
Q=[json.loads(l) for l in open('data/raw/btc/questions/questions.jsonl') if l.strip()]
names_of={t:([n] if isinstance(n,str) else list(n)) for t,n in alias.items()}

def compact_with_bounds(text):
    d=unicodedata.normalize("NFD",text)
    s="".join(c for c in d if unicodedata.category(c)!="Mn").replace("đ","d").replace("Đ","D").lower()
    out=[]; start=[]; end=[]
    prev_sep=True
    for i,c in enumerate(s):
        if re.match(r'[a-z0-9]',c):
            out.append(c); start.append(prev_sep); end.append(False); prev_sep=False
        else:
            if end: end[-1]=True
            prev_sep=True
    if end: end[-1]=True
    return "".join(out), start, end

def anchored_hits(text):
    """tra ve {ticker: (co_khop, co_khop_NEO_BIEN_TU)}"""
    comp,st,en=compact_with_bounds(text)
    res={}
    for t,ns in names_of.items():
        any_hit=False; anchored=False
        for n in ns:
            for a in company_aliases(n):
                i=comp.find(a)
                while i>=0:
                    any_hit=True
                    j=i+len(a)-1
                    if st[i] and en[j]: anchored=True
                    i=comp.find(a,i+1)
        if any_hit: res[t]=(True,anchored)
    return res

rc1=[]; rc1_cases=collections.Counter()
for r in Q:
    h=anchored_hits(r['question'])
    bad=[t for t,(a,anc) in h.items() if a and not anc]
    if bad:
        rc1.append((r['id'],sorted(bad)))
        for t in bad: rc1_cases[t]+=1
print("RC-1 · alias khop nhung KHONG neo bien tu (khop nham vao giua tu): %d/%d cau"%(len(rc1),len(Q)))
print("theo ma:",rc1_cases.most_common(15))
for x in rc1[:20]: print("   q%s -> %s"%x)

# anh huong thuc te: bad ticker co lot vao targets khong?
anh_huong=[]
for r in Q:
    h=anchored_hits(r['question'])
    bad=set(t for t,(a,anc) in h.items() if a and not anc)
    if not bad: continue
    it=parse_intent(r['question'],alias)
    if bad & set(it.targets): anh_huong.append((r['id'],sorted(bad & set(it.targets)),sorted(it.targets)))
print("\nRC-1 · so cau ma ma khop-nham THUC SU vao targets cua S1: %d"%len(anh_huong))
for x in anh_huong[:20]: print("   q%s  nham=%s  targets=%s"%x)

# RC-2 sach: loai bo cac ma khop khong neo bien tu
def branches_clean(text):
    comp,st,en=compact_with_bounds(text)
    h=anchored_hits(text)
    hit={t for t,(a,anc) in h.items() if anc}
    def alset(t):
        return {a for n in names_of[t] for a in company_aliases(n) if a in comp}
    def bibao(t):
        mine=alset(t)
        for u in hit:
            if u==t: continue
            th=alset(u)
            if any(m!=o and m in o for m in mine for o in th): return True
        return False
    nm={t for t in hit if not bibao(t)}
    tm={t for t in alias if ticker_mentioned(text,t)}
    shad={t for t in tm if any(t.lower() in ascii_compact(n) for c in nm for n in names_of[c])}
    return nm, tm-shad
rc2=[]
for r in Q:
    nm,ex=branches_clean(r['question'])
    if ex and (nm-ex): rc2.append((r['id'],sorted(ex),sorted(nm-ex)))
print("\nRC-2 (SAU khi khu RC-1) · nhanh ticker nuot nhanh ten: %d/%d cau"%(len(rc2),len(Q)))
for x in rc2: print("   q%s  giu=%s  MAT=%s"%x)
