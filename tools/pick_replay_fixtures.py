"""RC-19 · chon 10 ca replay bang REVIEW DOC LAP tren RC1 release DB (read-only).

Moi ca chon TAT DINH: sap xep theo UID roi lay dau. Chay lai cho cung ket qua.
KHONG doc bat ky output nao cua RC2.
"""
import sqlite3, json
from decimal import Decimal, getcontext
getcontext().prec = 40

DB = "artifacts/rc1_baseline/silver.db"
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.execute("PRAGMA temp_store=FILE")
c.row_factory = sqlite3.Row

R = ("collision_class IS NULL AND period_end IS NOT NULL AND unit_kind<>'unknown'"
     " AND TRIM(COALESCE(metric_label_clean,''))<>'' AND confidence='high'"
     " AND quality_flags_json='[]'")
F = ("observation_uid,source_cell_uid,directory_doc_id,table_uid,evidence_ref,"
     "metric_label_clean,row_path_text,col_path_text,period_end,value_source_raw,"
     "value_decimal_text,unit_kind,currency,scale_exponent,ticker,doc_year,row_uid,"
     "column_uid,grid_row_idx,grid_col_idx")
c.executescript(
    f"CREATE TEMP TABLE cand AS SELECT {F} FROM observations WHERE {R};"
    "CREATE INDEX c1 ON cand(table_uid);"
    "CREATE INDEX c2 ON cand(table_uid,row_uid);"
    "CREATE INDEX c3 ON cand(table_uid,column_uid);"
    "CREATE INDEX c4 ON cand(table_uid,metric_label_clean,period_end);")

def one(sql, *a):
    r = c.execute(sql, a).fetchone()
    return dict(r) if r else None

def keep(d, *ks):
    return {k: d[k] for k in ks if k in d}

OUT = {}

# ── 01 · mot chi tieu, mot ky. Nhan DUY NHAT trong bang co DUNG 1 ky.
OUT["01"] = one("""
WITH tp AS (SELECT table_uid FROM cand GROUP BY 1 HAVING COUNT(DISTINCT period_end)=1),
     uq AS (SELECT table_uid,metric_label_clean FROM cand GROUP BY 1,2 HAVING COUNT(*)=1)
SELECT cand.* FROM cand JOIN tp ON tp.table_uid=cand.table_uid
  JOIN uq ON uq.table_uid=cand.table_uid AND uq.metric_label_clean=cand.metric_label_clean
ORDER BY cand.observation_uid LIMIT 1""")

# ── 02 · so hai ky. CUNG dong, CUNG nhan, hai ky khac nhau, moi (dong,ky) 1 o.
pair = c.execute("""
WITH r2 AS (SELECT table_uid,row_uid FROM cand GROUP BY 1,2
            HAVING COUNT(DISTINCT period_end)=2 AND COUNT(*)=2)
SELECT cand.* FROM cand JOIN r2 USING(table_uid,row_uid)
ORDER BY cand.table_uid, cand.row_uid, cand.period_end
LIMIT 2""").fetchall()
if len(pair) == 2:
    a, b = dict(pair[0]), dict(pair[1])
    OUT["02"] = {"earlier": a, "later": b}
    va, vb = Decimal(a["value_decimal_text"]), Decimal(b["value_decimal_text"])
    OUT["03"] = {"earlier": a, "later": b,
                 "expected_growth_decimal": str((vb - va) / va) if va != 0 else None,
                 "abstain_if_denominator_zero": va == 0}

# ── 04 · ty so hai chi tieu CUNG bang, CUNG ky, CUNG cot. Mau so != 0.
#   Doi hoi HAI DONG KHAC NHAU va GIA TRI KHAC NHAU: ty so = 1 tu hai nhan gan
#   trung khong kiem duoc gi — no dung ca khi code lay nham cung mot o hai lan.
rr = c.execute("""
WITH t AS (SELECT table_uid,column_uid,period_end FROM cand
           GROUP BY 1,2,3 HAVING COUNT(*)>=2)
SELECT a.observation_uid ua, b.observation_uid ub
FROM cand a JOIN t ON t.table_uid=a.table_uid AND t.column_uid=a.column_uid
                  AND t.period_end=a.period_end
JOIN cand b ON b.table_uid=a.table_uid AND b.column_uid=a.column_uid
           AND b.period_end=a.period_end AND b.row_uid<>a.row_uid
WHERE CAST(b.value_decimal_text AS REAL) <> 0
  AND a.value_decimal_text <> b.value_decimal_text
  AND a.metric_label_clean <> b.metric_label_clean
ORDER BY a.observation_uid, b.observation_uid LIMIT 1""").fetchone()
if rr:
    n = one("SELECT * FROM cand WHERE observation_uid=?", rr["ua"])
    d = one("SELECT * FROM cand WHERE observation_uid=?", rr["ub"])
    ratio = Decimal(n["value_decimal_text"]) / Decimal(d["value_decimal_text"])
    assert ratio != 1
    OUT["04"] = {"numerator": n, "denominator": d,
                 "expected_ratio_decimal": str(ratio)}

# ── 05 · cong dong con, LOAI subtotal. Tim (bang,cot) co dung 1 dong tong va
#         tong cac dong con KHOP chinh xac (Decimal, khong lam tron).
TOT = ("(metric_label_clean LIKE 'Cộng%' OR metric_label_clean LIKE 'Tổng%'"
       " OR metric_label_clean LIKE 'TỔNG%' OR metric_label_clean LIKE 'CỘNG%')")
groups = c.execute(f"""
SELECT table_uid, column_uid, period_end FROM cand
GROUP BY 1,2,3
HAVING COUNT(*) BETWEEN 3 AND 12
   AND SUM(CASE WHEN {TOT} THEN 1 ELSE 0 END) = 1
ORDER BY table_uid, column_uid, period_end LIMIT 4000""").fetchall()
for g in groups:
    rows = [dict(r) for r in c.execute(f"""
        SELECT * FROM cand WHERE table_uid=? AND column_uid=? AND period_end=?
        ORDER BY grid_row_idx""", (g["table_uid"], g["column_uid"], g["period_end"]))]
    tot = [r for r in rows if r["metric_label_clean"].upper().startswith(("CỘNG", "TỔNG"))]
    kids = [r for r in rows if r not in tot]
    if len(tot) != 1 or len(kids) < 2:
        continue
    s = sum(Decimal(k["value_decimal_text"]) for k in kids)
    if s == Decimal(tot[0]["value_decimal_text"]) and s != 0:
        OUT["05"] = {"total_row": tot[0],
                     "child_rows": [keep(k, "observation_uid", "source_cell_uid",
                                         "metric_label_clean", "value_decimal_text",
                                         "grid_row_idx") for k in kids],
                     "expected_sum_decimal": str(s),
                     "rule": "LOAI dong tong khoi phep cong; tong con PHAI bang dong tong"}
        break

# ── 06 · hai bang CUNG tai lieu
d6 = one("""SELECT directory_doc_id FROM cand GROUP BY 1
            HAVING COUNT(DISTINCT table_uid)>=2 ORDER BY 1 LIMIT 1""")
if d6:
    ts = [dict(r) for r in c.execute("""
        SELECT * FROM cand WHERE directory_doc_id=?
        GROUP BY table_uid ORDER BY table_uid LIMIT 2""", (d6["directory_doc_id"],))]
    OUT["06"] = {"doc_id": d6["directory_doc_id"], "tables": ts,
                 "rule": "join theo table_uid; CAM tron ky giua hai bang"}

# ── 07 · nhieu tai lieu cung ticker
t7 = one("""SELECT ticker FROM cand GROUP BY 1
            HAVING COUNT(DISTINCT doc_year)>=2 ORDER BY 1 LIMIT 1""")
if t7:
    ds = [dict(r) for r in c.execute("""
        SELECT * FROM cand WHERE ticker=? GROUP BY doc_year ORDER BY doc_year LIMIT 2""",
        (t7["ticker"],))]
    OUT["07"] = {"ticker": t7["ticker"], "documents": ds,
                 "rule": "khoa theo (ticker, doc_year, basis)"}

# ── 08 · bang KHONG header -> PHAI abstain
OUT["08"] = one("""
SELECT o.observation_uid,o.table_uid,o.directory_doc_id,o.evidence_ref,
       o.metric_label_clean,o.col_path_text,o.grid_col_idx,t.n_header_rows,t.locator
FROM observations o JOIN tables t ON t.table_uid=o.table_uid
WHERE t.n_header_rows=0 ORDER BY o.observation_uid LIMIT 1""")

# ── 09 · nhan TRUNG, phan biet duoc bang row_path/column_uid
dup = c.execute("""
WITH d AS (SELECT table_uid,metric_label_clean,period_end FROM cand
           GROUP BY 1,2,3 HAVING COUNT(*)=2 AND COUNT(DISTINCT row_path_text)=2)
SELECT cand.* FROM cand JOIN d USING(table_uid,metric_label_clean,period_end)
ORDER BY cand.table_uid, cand.metric_label_clean, cand.period_end, cand.row_uid
LIMIT 2""").fetchall()
if len(dup) == 2:
    OUT["09"] = {"variant_a": dict(dup[0]), "variant_b": dict(dup[1]),
                 "rule": "PHAI phan biet bang row_path/column_uid; khong phan biet duoc thi abstain"}

# ── 10 · mo ho co chu dinh -> PHAI abstain
OUT["10"] = one("""
SELECT observation_uid,source_cell_uid,table_uid,directory_doc_id,evidence_ref,
       metric_label_clean,row_path_text,col_path_text,period_end,
       value_decimal_text,collision_class
FROM observations WHERE collision_class IS NOT NULL
ORDER BY observation_uid LIMIT 1""")

print(json.dumps(OUT, ensure_ascii=False, indent=1))
