import sqlite3,os,json,collections
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
cur=conn.cursor()
print("=== quy mo corpus ===")
for t in ('documents','table_cards','observations'):
    try: print(" %-14s %d"%(t,cur.execute("SELECT COUNT(*) FROM %s"%t).fetchone()[0]))
    except Exception as e: print(" %s ERR %s"%(t,e))
print("\n=== documents theo basis ===",dict(cur.execute("SELECT basis,COUNT(*) FROM documents GROUP BY basis").fetchall()))
print("\n=== so ma / so nam ===")
print(" ma:",cur.execute("SELECT COUNT(DISTINCT ticker) FROM documents").fetchone()[0],
      " nam:",sorted(x[0] for x in cur.execute("SELECT DISTINCT year FROM documents ORDER BY year")))
print("\n=== statement_type tren table_cards ===")
for k,v in cur.execute("SELECT statement_type,COUNT(*) FROM table_cards GROUP BY 1 ORDER BY 2 DESC"): print("  %-20s %d"%(k,v))
print("\n=== coverage o (ticker x year): co du 3 bao cao chinh khong ===")
rows=cur.execute("""SELECT d.ticker,d.year,d.basis,
   SUM(CASE WHEN tc.statement_type='income_statement' THEN 1 ELSE 0 END),
   SUM(CASE WHEN tc.statement_type='balance_sheet' THEN 1 ELSE 0 END),
   SUM(CASE WHEN tc.statement_type='cash_flow' THEN 1 ELSE 0 END),
   COUNT(*)
 FROM table_cards tc JOIN documents d ON d.doc_id=tc.doc_id
 GROUP BY 1,2,3""").fetchall()
tot=len(rows)
cIS=sum(1 for r in rows if r[3]>0); cBS=sum(1 for r in rows if r[4]>0); cCF=sum(1 for r in rows if r[5]>0)
c3=sum(1 for r in rows if r[3]>0 and r[4]>0 and r[5]>0)
c0=sum(1 for r in rows if r[3]==0 and r[4]==0 and r[5]==0)
print(" so o (ma,nam,basis) = %d"%tot)
print("  co income_statement : %d (%.1f%%)"%(cIS,100*cIS/tot))
print("  co balance_sheet    : %d (%.1f%%)"%(cBS,100*cBS/tot))
print("  co cash_flow        : %d (%.1f%%)"%(cCF,100*cCF/tot))
print("  co DU CA 3          : %d (%.1f%%)"%(c3,100*c3/tot))
print("  KHONG co bao cao chinh nao: %d (%.1f%%)"%(c0,100*c0/tot))
print("\n=== o thieu theo nam ===")
byy=collections.defaultdict(lambda:[0,0])
for t,y,b,i,bs,cf,n in rows:
    byy[y][0]+=1
    if i>0 and bs>0 and cf>0: byy[y][1]+=1
for y in sorted(byy): print("  %d: %3d o · du 3 bao cao %3d (%.0f%%)"%(y,byy[y][0],byy[y][1],100*byy[y][1]/byy[y][0]))
