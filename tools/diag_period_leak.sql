-- Đo mức rò "ngày ban hành văn bản" vào bậc SUY DIỄN cấp bảng.
-- Chạy TRÊN BUILD HIỆN TẠI (period_resolver 1.5) để biết thiệt hại thật,
-- rồi chạy lại SAU khi build với 1.6 — cột `ngoai_cua_so` phải về 0.
--
--   sqlite3 -header -column /tmp/dp_work/silver.sqlite < diag_period_leak.sql

.headers on
.mode column

.print '=== A. Cột suy diễn cấp bảng: năm kỳ so với năm tài liệu ==='
SELECT CAST(substr(c.period_end,1,4) AS INT) - t.doc_year AS lech_nam,
       COUNT(*) AS n
FROM columns c JOIN table_features t USING(table_uid)
WHERE c.period_source='table_context' AND c.period_end IS NOT NULL
  AND t.doc_year IS NOT NULL
GROUP BY 1 ORDER BY lech_nam;

.print ''
.print '=== B. Tổng số nằm NGOÀI cửa sổ [doc_year-2, doc_year] ==='
SELECT COUNT(*) AS ngoai_cua_so
FROM columns c JOIN table_features t USING(table_uid)
WHERE c.period_source='table_context' AND c.period_end IS NOT NULL
  AND t.doc_year IS NOT NULL
  AND (CAST(substr(c.period_end,1,4) AS INT) < t.doc_year - 2
       OR CAST(substr(c.period_end,1,4) AS INT) > t.doc_year);

.print ''
.print '=== C. Bao nhiêu trong số đó rơi đúng vào ngày ký Thông tư 200 ==='
SELECT c.period_end, COUNT(*) n
FROM columns c JOIN table_features t USING(table_uid)
WHERE c.period_source='table_context' AND c.period_end IS NOT NULL
  AND t.doc_year IS NOT NULL
  AND (CAST(substr(c.period_end,1,4) AS INT) < t.doc_year - 2
       OR CAST(substr(c.period_end,1,4) AS INT) > t.doc_year)
GROUP BY 1 ORDER BY n DESC LIMIT 15;

.print ''
.print '=== D. 15 ngữ cảnh mẫu đã sinh ra kỳ lệch ==='
.width 12 6 70
SELECT c.period_end, t.doc_year, substr(t.context_clean,1,70) AS ngu_canh
FROM columns c JOIN table_features t USING(table_uid)
WHERE c.period_source='table_context' AND c.period_end IS NOT NULL
  AND t.doc_year IS NOT NULL
  AND (CAST(substr(c.period_end,1,4) AS INT) < t.doc_year - 2
       OR CAST(substr(c.period_end,1,4) AS INT) > t.doc_year)
GROUP BY t.context_clean ORDER BY COUNT(*) DESC LIMIT 15;

.print ''
.print '=== E. Đối chứng: cột có kỳ TƯỜNG MINH (nhãn cột) lệch năm ra sao ==='
.print '     (cửa sổ KHÔNG áp cho bậc này — bảng 5 năm là hợp lệ)'
SELECT CAST(substr(c.period_end,1,4) AS INT) - t.doc_year AS lech_nam,
       COUNT(*) AS n
FROM columns c JOIN table_features t USING(table_uid)
WHERE c.period_source IN ('column_path','cell') AND c.period_end IS NOT NULL
  AND t.doc_year IS NOT NULL
GROUP BY 1 ORDER BY lech_nam;
