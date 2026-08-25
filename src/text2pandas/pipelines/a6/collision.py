"""Phân loại đụng độ ngữ nghĩa — điều kiện §7 của doc 12 để RC được nhận.

Doc 12 §7 từ chối RC nếu *"unknown ambiguity nằm trong execution-ready mà
không classifier"*. Đo được trên build 05/08: **181.075 observation** đụng độ
nằm trong `execution_ready=true`, và vì chưa có classifier nên **toàn bộ** là
`unknown`.

Module này KHÔNG sửa dữ liệu và KHÔNG khử trùng lặp. Nó chỉ **đặt tên** cho
từng nhóm đụng độ, theo đúng bất biến đã duyệt ở doc 10 §4:

    Đụng độ ngữ nghĩa toàn corpus KHÔNG bắt buộc bằng 0.
    Đụng độ CHƯA ĐƯỢC PHÂN LOẠI trong execution_ready thì bắt buộc bằng 0.

Bốn lớp dưới đây đến từ số đo, không từ suy đoán. Đo trên build 05/08
(171.799 nhóm):

    missing_row_parent      45.691 nhóm · 130.916 obs   cây phân cấp SẼ tách được
    missing_dimension       63.807 nhóm · 136.653 obs   cùng tổ tiên — cây VÔ DỤNG
    missing_label_or_split  54.505 nhóm · 157.171 obs   không có tổ tiên nào
    missing_column_group     7.796 nhóm ·  17.234 obs   đụng độ trục CỘT

Kết quả ghi vào hai bảng riêng, KHÔNG ghi đè `quality_flags_json` của
observation. Lý do: phân loại là **phép chiếu** suy ra từ dữ liệu, không phải
sự thật về ô. Sửa luật phân loại thì sinh lại bảng trong vài giây; nướng vào
observation thì phải rebuild 2,6 triệu dòng — cùng nguyên tắc đã áp cho
readiness policy.
"""

from __future__ import annotations

__all__ = ["COLLISION_DDL", "COLLISION_VERSION", "build_collisions", "CLASSES"]

COLLISION_VERSION = "1.0"

CLASSES = (
    "missing_row_parent",
    "missing_dimension",
    "missing_label_or_split",
    "missing_column_group",
    "physical_duplicate",
    "unknown",
)

COLLISION_DDL = """
CREATE TABLE IF NOT EXISTS collision_groups (
    group_uid      TEXT PRIMARY KEY,
    table_uid      TEXT NOT NULL,
    row_path_text  TEXT NOT NULL,
    col_path_text  TEXT NOT NULL,
    period_key     TEXT NOT NULL,
    collision_class TEXT NOT NULL,
    n_obs          INTEGER NOT NULL,
    n_distinct_values INTEGER NOT NULL,
    n_rows         INTEGER NOT NULL,
    n_cols         INTEGER NOT NULL,
    n_anchors      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS collision_obs (
    observation_uid TEXT PRIMARY KEY,
    group_uid       TEXT NOT NULL,
    collision_class TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_cg_class ON collision_groups(collision_class);
CREATE INDEX IF NOT EXISTS ix_co_class ON collision_obs(collision_class);
"""

# Neo tổ tiên ỨNG VIÊN: dòng gần nhất phía trên có nhãn nhưng KHÔNG mang giá
# trị. Chính là "dòng mở phạm vi" mà cơ chế ngăn xếp hiện tại bỏ lỡ (RC-1a).
_ANCHOR_VIEW = """
CREATE TEMP VIEW IF NOT EXISTS v_anchor AS
SELECT r.table_uid, r.grid_row_idx,
       (SELECT MAX(s.grid_row_idx) FROM rows s
         WHERE s.table_uid = r.table_uid
           AND s.grid_row_idx < r.grid_row_idx
           AND s.row_role IN ('section','empty')
           AND TRIM(s.label_clean) <> '') AS anchor_row
FROM rows r
"""


def build_collisions(conn) -> dict:
    """Dựng lại hai bảng phân loại từ đầu. Idempotent, không đụng observations."""
    conn.executescript(COLLISION_DDL)
    conn.execute("DELETE FROM collision_obs")
    conn.execute("DELETE FROM collision_groups")
    conn.executescript(_ANCHOR_VIEW)

    # Khoá nhóm dùng COALESCE(period_end,'') — KHÔNG dùng NULL, vì NULL không
    # bằng chính nó và sẽ tách nhóm một cách âm thầm.
    conn.execute("""
        CREATE TEMP TABLE IF NOT EXISTS _cg AS
        SELECT o.table_uid, o.row_path_text, o.col_path_text,
               COALESCE(o.period_end,'') AS pe,
               COUNT(*)                             AS n_obs,
               COUNT(DISTINCT o.value_decimal_text) AS n_val,
               COUNT(DISTINCT o.grid_row_idx)       AS n_rows,
               COUNT(DISTINCT o.grid_col_idx)       AS n_cols,
               COUNT(DISTINCT o.source_cell_uid)    AS n_cells
        FROM observations o
        WHERE o.value_decimal_text IS NOT NULL
        GROUP BY 1,2,3,4
        HAVING COUNT(DISTINCT o.value_decimal_text) > 1""")

    conn.execute("""
        INSERT INTO collision_groups
        SELECT
          -- RC2-020 · KHONG duoc co thanh phan ngau nhien trong group_uid.
          -- Ban truoc co `lower(hex(randomblob(0))) ||` o day. Theo tai lieu
          -- SQLite: randomblob(N) voi N < 1 tra ve MOT BYTE NGAU NHIEN, khong
          -- phai blob rong. Nen moi build sinh mot tien to 2 ky tu hex khac
          -- nhau -> group_uid bat dinh -> C0 do. C0-core khong bat duoc vi
          -- collision_* khong nam trong pham vi so cua no.
            g.table_uid || '#' || g.row_path_text || '#' || g.col_path_text
            || '#' || g.pe,
          g.table_uid, g.row_path_text, g.col_path_text, g.pe,
          CASE
            -- Nhiều observation trên CÙNG một ô nguồn: lỗi nhân bản của parser,
            -- không phải mơ hồ ngữ nghĩa. Phải bằng 0 (doc 10 §4).
            WHEN g.n_cells < g.n_obs                 THEN 'physical_duplicate'
            WHEN g.n_rows = 1 AND g.n_cols > 1       THEN 'missing_column_group'
            WHEN a.n_anchor > 1                      THEN 'missing_row_parent'
            WHEN a.n_anchor = 1                      THEN 'missing_dimension'
            WHEN a.n_anchor = 0                      THEN 'missing_label_or_split'
            ELSE 'unknown' END,
          g.n_obs, g.n_val, g.n_rows, g.n_cols, COALESCE(a.n_anchor, 0)
        FROM _cg g
        LEFT JOIN (
          SELECT o.table_uid, o.row_path_text, o.col_path_text,
                 COALESCE(o.period_end,'') pe,
                 COUNT(DISTINCT v.anchor_row) AS n_anchor
          FROM observations o
          JOIN v_anchor v ON v.table_uid = o.table_uid
                         AND v.grid_row_idx = o.grid_row_idx
          WHERE o.value_decimal_text IS NOT NULL
          GROUP BY 1,2,3,4) a
          ON a.table_uid = g.table_uid AND a.row_path_text = g.row_path_text
         AND a.col_path_text = g.col_path_text AND a.pe = g.pe""")

    conn.execute("""
        INSERT INTO collision_obs
        SELECT o.observation_uid, cg.group_uid, cg.collision_class
        FROM observations o
        JOIN collision_groups cg
          ON cg.table_uid = o.table_uid
         AND cg.row_path_text = o.row_path_text
         AND cg.col_path_text = o.col_path_text
         AND cg.period_key = COALESCE(o.period_end,'')
        WHERE o.value_decimal_text IS NOT NULL""")
    conn.commit()

    by_class = dict(conn.execute(
        "SELECT collision_class, COUNT(*) FROM collision_groups"
        " GROUP BY 1 ORDER BY 2 DESC").fetchall())
    obs_by_class = dict(conn.execute(
        "SELECT collision_class, COUNT(*) FROM collision_obs"
        " GROUP BY 1 ORDER BY 2 DESC").fetchall())
    return {
        "collision_version": COLLISION_VERSION,
        "groups": sum(by_class.values()),
        "observations": sum(obs_by_class.values()),
        "groups_by_class": by_class,
        "observations_by_class": obs_by_class,
        "unclassified": by_class.get("unknown", 0),
    }
