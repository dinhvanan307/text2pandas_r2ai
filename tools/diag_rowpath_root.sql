-- Truy NGUYÊN NHÂN của 200.416 khoá đụng độ. Không vá trước khi biết vì sao.
-- Ba giả thuyết loại trừ nhau, mỗi khối dưới đây bác bỏ hoặc xác nhận một cái:
--   H1  nhãn dòng RỖNG -> row_path chỉ còn phần section, mọi dòng trùng nhau
--   H2  nhãn dòng CÓ nhưng row_path không nối tổ tiên -> "Cộng" lặp nhiều lần
--   H3  section_text bẩn -> hai bảng khác nhau nhận cùng một tiền tố
--
--   sqlite3 -header -column /tmp/dp_work/silver.sqlite < diag_rowpath_root.sql

.headers on
.mode column

.print '=== H1. row_path KHÔNG có dấu › nghĩa là không nối được thành phần nào ==='
SELECT CASE WHEN row_path_text LIKE '%›%' THEN 'co_phan_cap'
            ELSE 'PHANG (chi 1 thanh phan)' END AS dang,
       COUNT(*) AS n_obs
FROM observations GROUP BY 1;

.print ''
.print '=== H1b. Nhãn dòng rỗng / chỉ có số ==='
SELECT CASE
         WHEN TRIM(metric_label_clean) = '' THEN 'RONG'
         WHEN metric_label_clean GLOB '[0-9]*' AND metric_label_clean NOT GLOB '*[A-Za-zÀ-ỹ]*'
              THEN 'CHI_CO_SO'
         WHEN LENGTH(metric_label_clean) <= 3 THEN 'DUOI_4_KY_TU'
         ELSE 'co_chu' END AS nhan, COUNT(*) n
FROM observations GROUP BY 1 ORDER BY n DESC;

.print ''
.print '=== H1c. Trong các NHÓM ĐỤNG ĐỘ, nhãn dòng ra sao ==='
WITH dungdo AS (
  SELECT table_uid, row_path_text, col_path_text, COALESCE(period_end,'') pe
  FROM observations
  GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT value_decimal_text) > 1
)
SELECT CASE
         WHEN TRIM(o.metric_label_clean) = '' THEN 'RONG'
         WHEN LENGTH(o.metric_label_clean) <= 3 THEN 'DUOI_4_KY_TU'
         ELSE 'co_chu' END AS nhan, COUNT(*) n
FROM observations o JOIN dungdo d
  ON o.table_uid=d.table_uid AND o.row_path_text=d.row_path_text
 AND o.col_path_text=d.col_path_text AND COALESCE(o.period_end,'')=d.pe
GROUP BY 1 ORDER BY n DESC;

.print ''
.print '=== H2. Nhãn dòng CÓ chữ mà vẫn đụng độ -> lỗi nối tổ tiên ==='
.print '     Cùng bảng, cùng row_path, nhưng metric_label_clean KHÁC nhau'
WITH dungdo AS (
  SELECT table_uid, row_path_text, col_path_text, COALESCE(period_end,'') pe
  FROM observations
  GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT value_decimal_text) > 1
)
SELECT COUNT(*) AS n_nhom_co_nhan_khac_nhau FROM (
  SELECT o.table_uid, o.row_path_text, o.col_path_text
  FROM observations o JOIN dungdo d
    ON o.table_uid=d.table_uid AND o.row_path_text=d.row_path_text
   AND o.col_path_text=d.col_path_text AND COALESCE(o.period_end,'')=d.pe
  GROUP BY 1,2,3 HAVING COUNT(DISTINCT o.metric_label_clean) > 1
);

.print ''
.print '=== H2b. Vai trò dòng (row_role) trong bảng rows ==='
SELECT row_role, COUNT(*) n, SUM(row_path_text NOT LIKE '%›%') AS phang
FROM rows GROUP BY 1 ORDER BY n DESC;

.print ''
.print '=== H2c. Nguồn nhãn dòng (label_source) ==='
SELECT label_source, COUNT(*) n FROM rows GROUP BY 1 ORDER BY n DESC LIMIT 12;

.print ''
.print '=== H3. section_text bẩn — bao nhiêu bảng có section là dòng khai đơn vị ==='
SELECT CASE
         WHEN section_text = '' THEN 'RONG'
         WHEN section_text LIKE '%Đơn vị%' THEN 'LA_DONG_KHAI_DON_VI'
         WHEN section_text LIKE '%thuyết minh kèm theo%'
           OR section_text LIKE '%Cac thuyet minh kem theo%' THEN 'LA_BOILERPLATE_CHAN_TRANG'
         WHEN section_text GLOB '*[0-9][0-9][0-9].[0-9][0-9][0-9]*' THEN 'CHUA_CHUOI_TIEN'
         ELSE 'co_ve_sach' END AS loai, COUNT(*) n_bang
FROM table_features GROUP BY 1 ORDER BY n_bang DESC;

.print ''
.print '=== H3b. 20 section_text bẩn phổ biến nhất ==='
.width 8 70
SELECT COUNT(*) n, substr(section_text,1,70) AS section
FROM table_features
WHERE section_text LIKE '%Đơn vị%'
   OR section_text LIKE '%thuyet minh kem theo%'
   OR section_text GLOB '*[0-9][0-9][0-9].[0-9][0-9][0-9]*'
GROUP BY section_text ORDER BY n DESC LIMIT 20;

.print ''
.print '=== TỔNG: bao nhiêu observation nằm trong nhóm đụng độ ==='
WITH dungdo AS (
  SELECT table_uid, row_path_text, col_path_text, COALESCE(period_end,'') pe
  FROM observations
  GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT value_decimal_text) > 1
)
SELECT COUNT(*) AS n_obs_khong_phan_giai_duoc
FROM observations o JOIN dungdo d
  ON o.table_uid=d.table_uid AND o.row_path_text=d.row_path_text
 AND o.col_path_text=d.col_path_text AND COALESCE(o.period_end,'')=d.pe;
