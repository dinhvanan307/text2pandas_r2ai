-- Chất lượng KHOÁ TRUY XUẤT: row_path_text và col_path_text.
-- Đây là hai trường Retrieval/Text-to-Pandas dùng để tìm dòng và cột. Gate
-- G1–G5 không đo chúng: một row_path rác vẫn "có provenance", vẫn "có kỳ",
-- vẫn khớp đẳng thức Mã số. Nên phải đo riêng.
--
--   sqlite3 -header -column /tmp/dp_work/silver.sqlite < diag_path_quality.sql

.headers on
.mode column

.print '=== A. col_path chứa CHỮ SỐ DÀI (dòng dữ liệu bị nhận nhầm là header) ==='
SELECT COUNT(*) AS n_obs,
       COUNT(DISTINCT table_uid) AS n_bang
FROM observations
WHERE col_path_text GLOB '*[0-9][0-9][0-9].[0-9][0-9][0-9].[0-9][0-9][0-9]*';

.print ''
.print '=== B. 20 col_path bẩn nhất theo số observation ==='
.width 8 72
SELECT COUNT(*) n, substr(col_path_text,1,72) AS col_path
FROM observations
WHERE col_path_text GLOB '*[0-9][0-9][0-9].[0-9][0-9][0-9].[0-9][0-9][0-9]*'
GROUP BY col_path_text ORDER BY n DESC LIMIT 20;

.print ''
.print '=== C. row_path bắt đầu bằng dòng khai đơn vị / tiêu đề kỹ thuật ==='
.width 8 72
SELECT COUNT(*) n, substr(row_path_text,1,72) AS row_path
FROM observations
WHERE row_path_text LIKE '%Đơn vị tính%'
   OR row_path_text LIKE '%Đơn vị:%'
   OR row_path_text LIKE '%Thuyết minh theo%'
GROUP BY row_path_text ORDER BY n DESC LIMIT 20;

.print ''
.print '=== D. Độ dài row_path — quá ngắn thì không phân biệt được dòng ==='
SELECT CASE
         WHEN LENGTH(row_path_text) = 0 THEN '0 (rỗng)'
         WHEN LENGTH(row_path_text) < 10 THEN '1-9'
         WHEN LENGTH(row_path_text) < 30 THEN '10-29'
         WHEN LENGTH(row_path_text) < 80 THEN '30-79'
         WHEN LENGTH(row_path_text) < 160 THEN '80-159'
         ELSE '160+ (nghi phình)'
       END AS do_dai, COUNT(*) n
FROM observations GROUP BY 1 ORDER BY 1;

.print ''
.print '=== E. Trùng khoá: cùng (bảng, row_path, col_path, kỳ) mà khác giá trị ==='
.print '     Đây là trường hợp Retrieval KHÔNG THỂ phân giải — phải bằng 0.'
SELECT COUNT(*) AS n_khoa_dung_do
FROM (
  SELECT table_uid, row_path_text, col_path_text, COALESCE(period_end,'')
  FROM observations
  GROUP BY 1,2,3,4
  HAVING COUNT(DISTINCT value_decimal_text) > 1
);

.print ''
.print '=== F. 15 ví dụ khoá đụng độ ==='
.width 40 30 12 6
SELECT substr(row_path_text,1,40) AS row_path,
       substr(col_path_text,1,30) AS col_path,
       COALESCE(period_end,'(khong ky)') AS ky,
       COUNT(DISTINCT value_decimal_text) AS n_gia_tri
FROM observations
GROUP BY table_uid, row_path_text, col_path_text, COALESCE(period_end,'')
HAVING COUNT(DISTINCT value_decimal_text) > 1
ORDER BY n_gia_tri DESC LIMIT 15;

.print ''
.print '=== G. Nhãn dòng chung chung (Q-OBS-GENERIC-LABEL 200.195) — top 20 ==='
.width 8 60
SELECT COUNT(*) n, substr(metric_label_clean,1,60) AS nhan
FROM observations
WHERE quality_flags_json LIKE '%generic_row_label%'
GROUP BY metric_label_clean ORDER BY n DESC LIMIT 20;
