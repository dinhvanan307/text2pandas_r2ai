-- KIỂM ĐỊNH RC-1 ĐÚNG CÁCH.
--
-- Phép kiểm H2 trong `diag_rowpath_root.sql` (tài liệu 03) SAI VỀ CẤU TẠO:
-- nó đếm nhóm có `metric_label_clean` khác nhau trong cùng `row_path_text`.
-- Nhưng `row_path` được dựng bằng `parts + [label]` — label là thành phần
-- CUỐI của chính chuỗi đó. Cùng `row_path` thì gần như bắt buộc cùng label.
-- Phép kiểm ấy luôn trả ~0 dù RC-1 đúng hay sai. Tài liệu 04 đo ra 46 nhóm,
-- đúng như cấu tạo dự báo. Đừng dùng lại nó.
--
-- Phép kiểm ĐÚNG: các dòng vật lý đang đụng độ có TỔ TIÊN KHÁC NHAU hay không.
-- Nếu có → thiếu tổ tiên là nguyên nhân (RC-1) và dựng được cây sẽ tách chúng.
-- Nếu không → chúng thật sự trùng nhau và cần dimension khác, không phải cây.
--
--   sqlite3 -header -column silver.sqlite < collision_canonical.sql > /dev/null
--   sqlite3 -header -column silver.sqlite < diag_rc1_correct.sql

.headers on
.mode column

CREATE TEMP VIEW v_obs_keyed AS
SELECT o.*, COALESCE(o.period_end,'') AS pe_key
FROM observations o WHERE o.value_decimal_text IS NOT NULL;

CREATE TEMP VIEW v_cg AS
SELECT table_uid, row_path_text, col_path_text, pe_key
FROM v_obs_keyed
GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT value_decimal_text) > 1;

-- Neo tổ tiên ỨNG VIÊN: dòng gần nhất PHÍA TRÊN có nhãn nhưng KHÔNG có giá trị.
-- Đây chính là "dòng mở phạm vi" (Nguyên giá / Giá trị hao mòn lũy kế) mà cơ
-- chế stack hiện tại bỏ lỡ.
CREATE TEMP VIEW v_anchor AS
SELECT r.table_uid, r.grid_row_idx,
       (SELECT MAX(s.grid_row_idx) FROM rows s
         WHERE s.table_uid = r.table_uid
           AND s.grid_row_idx < r.grid_row_idx
           AND s.row_role IN ('section','empty')
           AND TRIM(s.label_clean) <> '') AS anchor_row
FROM rows r;

.print '=== A. RC-1 THẬT: nhóm đụng độ có tổ tiên ứng viên KHÁC NHAU ==='
.print '     Đây là con số phải so với tổng số nhóm, KHÔNG phải phép kiểm H2 cũ.'
WITH g AS (
  SELECT c.table_uid, c.row_path_text, c.col_path_text, c.pe_key,
         COUNT(DISTINCT a.anchor_row)          AS n_anchor,
         COUNT(DISTINCT o.grid_row_idx)        AS n_rows,
         SUM(a.anchor_row IS NULL)             AS n_khong_co_anchor
  FROM v_cg c
  JOIN v_obs_keyed o ON o.table_uid=c.table_uid AND o.row_path_text=c.row_path_text
                    AND o.col_path_text=c.col_path_text AND o.pe_key=c.pe_key
  LEFT JOIN v_anchor a ON a.table_uid=o.table_uid AND a.grid_row_idx=o.grid_row_idx
  GROUP BY 1,2,3,4
)
SELECT CASE
    WHEN n_rows = 1                 THEN 'D_khong_phai_truc_dong'
    WHEN n_anchor > 1               THEN 'A_TO_TIEN_KHAC_NHAU__cay_se_tach_duoc'
    WHEN n_anchor = 1               THEN 'B_cung_to_tien__cay_KHONG_tach_duoc'
    ELSE                                 'C_khong_co_to_tien_ung_vien'
  END AS ket_luan, COUNT(*) AS nhom
FROM g GROUP BY 1 ORDER BY nhom DESC;

.print ''
.print '=== B. Taxonomy Mã số: nhóm có nhiều mã số khác nhau ==='
.print '     Nhiều mã số trong cùng row_path = chắc chắn là dòng kế toán khác nhau.'
SELECT t.statement_type, COUNT(*) AS nhom FROM (
  SELECT o.table_uid, o.row_path_text, o.col_path_text, o.pe_key
  FROM v_cg c JOIN v_obs_keyed o
    ON o.table_uid=c.table_uid AND o.row_path_text=c.row_path_text
   AND o.col_path_text=c.col_path_text AND o.pe_key=c.pe_key
  GROUP BY 1,2,3,4 HAVING COUNT(DISTINCT o.metric_code) > 1
) x JOIN table_features t USING(table_uid)
GROUP BY 1 ORDER BY nhom DESC;

.print ''
.print '=== C. Bảng KHÔNG CÓ CỘT NHÃN NÀO — nghi bảng bị tách đôi ==='
.print '     Không có cột label thì cây phân cấp không cứu được; phải ghép bảng.'
SELECT COUNT(*) AS n_bang, SUM(n_obs) AS n_obs FROM (
  SELECT t.table_uid, COUNT(o.observation_uid) AS n_obs
  FROM table_features t
  JOIN observations o USING(table_uid)
  WHERE NOT EXISTS (SELECT 1 FROM columns c
                    WHERE c.table_uid=t.table_uid AND c.column_role='label')
  GROUP BY 1
);

.print ''
.print '=== D. Bảng láng giềng nghi là hai nửa của cùng một bảng ==='
.print '     numeric-heavy không cột nhãn  +  text-only ngay sát dòng'
.width 40 8 8 8
SELECT a.directory_doc_id,
       a.line_start_1based AS dong_A, b.line_start_1based AS dong_B,
       ABS(b.line_start_1based - a.line_start_1based) AS khoang_cach
FROM table_features a JOIN table_features b
  ON a.document_uid=b.document_uid
 AND b.line_start_1based > a.line_start_1based
 AND b.line_start_1based - a.line_start_1based <= 6
WHERE a.numeric_ratio >= 0.6 AND b.numeric_ratio <= 0.1
   OR a.numeric_ratio <= 0.1 AND b.numeric_ratio >= 0.6
ORDER BY khoang_cach LIMIT 30;

.print ''
.print '=== E. ĐO GIÁ TRỊ: đụng độ nằm ở bảng nào — bảng chính hay thuyết minh ==='
.print '     Quyết định ưu tiên. Đụng độ trong bảng `other`/`toc` gần như vô hại.'
SELECT t.statement_type,
       COUNT(DISTINCT c.table_uid) AS bang_dinh,
       COUNT(*)                    AS nhom
FROM v_cg c JOIN table_features t USING(table_uid)
GROUP BY 1 ORDER BY nhom DESC;
