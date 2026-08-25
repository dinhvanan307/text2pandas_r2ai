-- Chẩn đoán 2.075 observation vượt 10^16 VND SAU khi áp scale (G5 đỏ)
-- Chạy:  sqlite3 -header -column /tmp/dp_work/silver.sqlite < diag_2075.sql

.headers on
.mode column
.width 4 22 8 60

CREATE TEMP VIEW big AS
SELECT o.*,
       ABS(CAST(o.value_decimal_text AS REAL)) AS raw_abs,
       ABS(CAST(o.value_decimal_text AS REAL)) *
         CASE COALESCE(o.scale_exponent,0)
              WHEN 0 THEN 1 WHEN 3 THEN 1e3 WHEN 6 THEN 1e6
              WHEN 9 THEN 1e9 WHEN 12 THEN 1e12 ELSE 1 END AS norm_abs
FROM observations o
WHERE o.value_kind='money';

.print '=== A. Phân rã theo (scale_exponent, scale_source) ==='
SELECT COALESCE(scale_exponent,-1) AS sc, scale_source, COUNT(*) AS n,
       MIN(LENGTH(REPLACE(value_decimal_text,'-',''))) AS min_digits,
       MAX(LENGTH(REPLACE(value_decimal_text,'-',''))) AS max_digits
FROM big WHERE norm_abs > 1e16
GROUP BY 1,2 ORDER BY n DESC;

.print ''
.print '=== B. Raw đã vượt ngưỡng từ trước (lỗi parse) vs chỉ vượt sau scale (lỗi unit) ==='
SELECT CASE WHEN raw_abs > 1e16 THEN 'raw_da_vuot__loi_PARSE'
            ELSE 'chi_vuot_sau_scale__loi_UNIT' END AS nguyen_nhan,
       COUNT(*) AS n
FROM big WHERE norm_abs > 1e16 GROUP BY 1;

.print ''
.print '=== C. Theo parse_rule ==='
SELECT parse_rule, COUNT(*) n FROM big WHERE norm_abs > 1e16
GROUP BY 1 ORDER BY n DESC LIMIT 15;

.print ''
.print '=== D. Tập trung ở bảng nào? (top 15 table_uid) ==='
SELECT b.table_uid, t.statement_type, COUNT(*) n
FROM big b LEFT JOIN table_features t USING(table_uid)
WHERE b.norm_abs > 1e16 GROUP BY 1,2 ORDER BY n DESC LIMIT 15;

.print ''
.print '=== E. 25 mẫu thô: raw / scale / row_path ==='
.width 30 14 4 14 50
SELECT substr(observation_uid,1,12) AS obs,
       value_source              AS raw_goc,
       COALESCE(scale_exponent,-1) AS sc,
       scale_source,
       substr(row_path_text,1,50) AS row_path
FROM big WHERE norm_abs > 1e16
ORDER BY norm_abs DESC LIMIT 25;

.print ''
.print '=== F. 25 mẫu nhãn cột (nơi scale thường bị bắt sai) ==='
.width 14 4 14 60
SELECT b.value_source AS raw_goc, COALESCE(b.scale_exponent,-1) AS sc,
       b.scale_source, substr(b.col_path_text,1,60) AS col_path
FROM big b WHERE b.norm_abs > 1e16
GROUP BY b.col_path_text, b.scale_source ORDER BY COUNT(*) DESC LIMIT 25;
