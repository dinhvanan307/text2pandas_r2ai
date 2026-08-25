-- ĐỊNH NGHĨA ĐỤNG ĐỘ CHÍNH THỨC — FREEZE. Mọi báo cáo phải dùng đúng file này.
-- Lý do freeze: 03 đo 200.416, 04 đo 200.418. Chênh 2 nhóm không đổi kết luận,
-- nhưng hai định nghĩa hơi khác nhau thì mọi so sánh before/after đều vô nghĩa.
--
-- Quy ước:
--   * chỉ tính observation có value_decimal_text KHÁC NULL (dash/rỗng không phải giá trị)
--   * period_end NULL được chuẩn hoá thành '' — KHÔNG dùng NULL trong khoá nhóm,
--     vì NULL không bằng chính nó và sẽ tách nhóm một cách âm thầm
--   * "đụng độ" = cùng khoá, nhiều value_decimal_text PHÂN BIỆT
--
--   sqlite3 -header -column silver.sqlite < collision_canonical.sql

.headers on
.mode column

DROP VIEW IF EXISTS v_obs_keyed;
CREATE TEMP VIEW v_obs_keyed AS
SELECT o.*, COALESCE(o.period_end, '') AS pe_key
FROM observations o
WHERE o.value_decimal_text IS NOT NULL;

DROP VIEW IF EXISTS v_collision_group;
CREATE TEMP VIEW v_collision_group AS
SELECT table_uid, row_path_text, col_path_text, pe_key,
       COUNT(*)                            AS n_obs,
       COUNT(DISTINCT value_decimal_text)  AS n_values,
       COUNT(DISTINCT grid_row_idx)        AS n_rows,
       COUNT(DISTINCT grid_col_idx)        AS n_cols
FROM v_obs_keyed
GROUP BY table_uid, row_path_text, col_path_text, pe_key
HAVING COUNT(DISTINCT value_decimal_text) > 1;

.print '=== 1. Quy mô chính thức ==='
SELECT COUNT(*)      AS nhom_dung_do,
       SUM(n_obs)    AS obs_trong_nhom,
       MAX(n_obs)    AS max_obs_mot_nhom,
       MAX(n_values) AS max_gia_tri_mot_nhom
FROM v_collision_group;

.print ''
.print '=== 2. Trục đụng độ ==='
SELECT CASE WHEN n_rows > 1 AND n_cols > 1 THEN 'ca_hai_truc'
            WHEN n_rows > 1 THEN 'truc_DONG'
            WHEN n_cols > 1 THEN 'truc_COT'
            ELSE 'mot_o__nghi_parser_nhan_ban' END AS truc,
       COUNT(*) AS nhom, SUM(n_obs) AS obs
FROM v_collision_group GROUP BY 1 ORDER BY nhom DESC;

.print ''
.print '=== 3. Theo loại báo cáo — dùng để ƯU TIÊN, không phải để thống kê ==='
SELECT t.statement_type, t.is_data_table,
       COUNT(*) AS nhom, SUM(g.n_obs) AS obs
FROM v_collision_group g JOIN table_features t USING(table_uid)
GROUP BY 1,2 ORDER BY obs DESC;

.print ''
.print '=== 4. Mẫu số để tính tỷ lệ ==='
SELECT (SELECT COUNT(*) FROM v_obs_keyed) AS obs_co_gia_tri,
       (SELECT SUM(n_obs) FROM v_collision_group) AS obs_dung_do,
       ROUND(100.0 * (SELECT SUM(n_obs) FROM v_collision_group)
                   / (SELECT COUNT(*) FROM v_obs_keyed), 2) AS pct;
