import sqlite3,os,collections
conn=sqlite3.connect('file:%s?mode=ro'%os.path.abspath('artifacts/retrieval/work.db'),uri=True)
cur=conn.cursor()
print("documents",cur.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
      "| table_cards",cur.execute("SELECT COUNT(*) FROM table_cards").fetchone()[0],
      "| observations",cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
print("ma:",cur.execute("SELECT COUNT(DISTINCT ticker) FROM documents").fetchone()[0],
      "nam:",sorted(x[0] for x in cur.execute("SELECT DISTINCT doc_year FROM documents WHERE doc_year IS NOT NULL ORDER BY 1")))
print("basis:",dict(cur.execute("SELECT basis,COUNT(*) FROM documents GROUP BY 1").fetchall()))
print("\nstatement_type (table_cards):")
for k,v in cur.execute("SELECT statement_type,COUNT(*) FROM table_cards GROUP BY 1 ORDER BY 2 DESC"): print("  %-20s %6d"%(k,v))
rows=cur.execute("""SELECT ticker,doc_year,
   SUM(statement_type='income_statement'),SUM(statement_type='balance_sheet'),SUM(statement_type='cash_flow'),
   SUM(execution_ready_obs>0),COUNT(*)
 FROM table_cards WHERE ticker IS NOT NULL AND doc_year IS NOT NULL GROUP BY 1,2""").fetchall()
tot=len(rows)
f=lambda i:sum(1 for r in rows if r[i]>0)
c3=sum(1 for r in rows if r[2]>0 and r[3]>0 and r[4]>0)
print("\n=== o (ticker x doc_year) tren table_cards: %d o ==="%tot)
print("  co IS %d (%.1f%%) · BS %d (%.1f%%) · CF %d (%.1f%%) · DU CA 3 %d (%.1f%%)"%(
  f(2),100*f(2)/tot,f(3),100*f(3)/tot,f(4),100*f(4)/tot,c3,100*c3/tot))
byy=collections.defaultdict(lambda:[0,0,0,0,0])
for t,y,i,b,c,rdy,n in rows:
    a=byy[y]; a[0]+=1
    a[1]+= i>0; a[2]+= b>0; a[3]+= c>0; a[4]+= (i>0 and b>0 and c>0)
print("\n  nam |  o  |  IS  |  BS  |  CF  | du3")
for y in sorted(byy):
    a=byy[y]; print("  %4d | %3d | %3d | %3d | %3d | %3d (%.0f%%)"%(y,a[0],a[1],a[2],a[3],a[4],100*a[4]/a[0]))
# so o KHONG co bao cao chinh nao
c0=sum(1 for r in rows if r[2]==0 and r[3]==0 and r[4]==0)
print("\n  o KHONG co bao cao chinh nao: %d (%.1f%%)"%(c0,100*c0/tot))
