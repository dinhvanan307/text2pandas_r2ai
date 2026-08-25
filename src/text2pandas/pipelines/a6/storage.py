"""DP-001/DP-011 — DDL và truy cập SQLite cho Bronze và Silver.

Ba luật cứng được thi hành ở tầng này:
  DI-05  Không cột nào lưu giá trị tài chính bằng REAL. Canonical TEXT.
  DI-03  Mọi bản ghi dẫn xuất có FK về source cell / table / document.
  DI-02  Mọi document và table có trạng thái cuối cùng, không silent drop.

Ràng buộc vận hành: SQLite không chạy được trên FUSE mount (ném `disk I/O
error` ngay lệnh đầu). Build ở đĩa cục bộ rồi copy sau khi đóng connection.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from text2pandas.infrastructure.paths import ProjectPaths

from text2pandas.pipelines.a6.collision import COLLISION_DDL

__all__ = ["BRONZE_DDL", "SILVER_DDL", "connect", "publish_db", "integrity_check",
           "SCHEMA_VERSION", "stamp_schema_version",
           "make_build_id", "source_fingerprint"]

# ── Data Contract v1 ────────────────────────────────────────────────────────
# Đóng băng ngày 08/08/2026. Quy tắc phiên bản:
#   major  đổi tên/xoá trường, đổi công thức UID, đổi ngữ nghĩa NULL  -> CẤM
#   minor  ENRICHMENT: điền trường [F3] đang NULL, không đụng identity/value
#   patch  sửa lỗi correctness: value/unit/kỳ sai, observation mất, locator sai
#
# Trường [F3] cố ý để NULL ở 1.0. Chúng tồn tại từ ngày đóng băng để mọi cải
# tiến ngữ nghĩa về sau là ENRICHMENT chứ không phải breaking change:
#   rows            parent_row_uid, hierarchy_level, hierarchy_source,
#                   hierarchy_confidence, structural_role, accounting_role
#   columns         parent_column_uid, column_group_source,
#                   column_group_confidence
#   table_features  table_group_uid, table_group_role, table_group_confidence,
#                   section_source_line, section_rule, section_confidence
SCHEMA_VERSION = "1.0"


def source_fingerprint() -> dict[str, str]:
    """Vân tay NỘI DUNG của mã nguồn và cấu hình.

    `build_id` bản đầu = sha256(phiên bản khai báo + số đếm). Nó KHÔNG phân
    biệt được hai build khác nhau: thêm bảng `dropped_cells` và bốn chỉ mục
    không bump `*_VERSION` nào, số đếm cũng không đổi, nên hai build ra cùng
    một ID `fbe651efc9fd11a6`. Doc 12 §7 đòi `build ID ↔ source commit ↔
    manifest` khớp — với một ID không mã hoá nội dung thì không thể khớp.

    Bản này băm chính NỘI DUNG các file, nên mọi thay đổi mã đều đổi ID, kể
    cả thay đổi không ai nhớ bump phiên bản.
    """
    here = Path(__file__).resolve().parent
    root = ProjectPaths.discover(here).repo_root
    def _hash(paths) -> str:
        h = hashlib.sha256()
        for f in sorted(paths):
            if f.is_file():
                h.update(f.name.encode())
                h.update(f.read_bytes())
        return h.hexdigest()
    src = _hash(here.glob("*.py"))
    # `configs` — SỐ NHIỀU. Bản đầu băm `config/` (số ít), một thư mục mà
    # **không mã nào đọc**: `readiness.load_policy` ưu tiên `configs/`, và
    # `dp-build` nhận config qua `configs/vifinqa_silver_v1.yaml`.
    #
    # Hậu quả đo được trên chính build RC1 `b927c3e8f90aed74`:
    #
    #     config_hash đã ghi vào build_id      02ee1eeb3114c749  ← config/
    #     nếu băm đúng thư mục đang dùng       2e370bc63f795a1b  ← configs/
    #
    # Nghĩa là: sửa ngưỡng trong `configs/vifinqa_silver_v1.yaml` KHÔNG đổi
    # `build_id`, còn sửa một tệp chết thì đổi. Đúng kiểu va chạm ID mà
    # `cmd_publish` đã phải sửa một lần — lần này ở tầng sâu hơn.
    #
    # KHÔNG đặt fallback về `config/`: một fallback im lặng chính là cách hai
    # nguồn sự thật sống sót qua lần dọn dẹp tiếp theo.
    cfg_dir = root / "configs"
    cfg = _hash(cfg_dir.glob("*.yaml")) if cfg_dir.is_dir() else "no-config"
    return {"source_hash": src[:16], "config_hash": cfg[:16]}


def make_build_id(counts: dict, components: dict) -> tuple[str, dict]:
    """`build_id` = băm của (nội dung mã · cấu hình · phiên bản · số đếm).

    Trả thêm toàn bộ thành phần để manifest ghi được, chứ không chỉ con số
    cuối — người review phải tái lập được ID chứ không phải tin nó.
    """
    fp = source_fingerprint()
    parts = {**fp, **{f"component_{k}": v for k, v in components.items()},
             **{f"count_{k}": str(v) for k, v in sorted(counts.items())},
             "schema_version": SCHEMA_VERSION}
    bid = hashlib.sha256(repr(sorted(parts.items())).encode()).hexdigest()[:16]
    return bid, parts


def stamp_schema_version(conn, extra: dict | None = None) -> None:
    """Ghi phiên bản hợp đồng vào `build_meta`.

    Bản ghi trong DB KHÔNG mang `schema_version` từng dòng: 2,5 triệu chuỗi
    lặp lại là chi phí không đổi lấy gì, vì một file DB chỉ có đúng một phiên
    bản. Ngược lại, BẢN XUẤT (CSV/parquet giao cho Text-to-Pandas) PHẢI mang
    nó từng dòng, vì hai bản xuất khác phiên bản có thể được ghép trong cùng
    một DataFrame. Xem `release.py`.
    """
    rows = {"schema_version": SCHEMA_VERSION}
    rows.update(extra or {})
    conn.executemany(
        "INSERT OR REPLACE INTO build_meta(key, value) VALUES (?, ?)",
        [(k, str(v)) for k, v in rows.items()])
    conn.commit()

_PRAGMA = """
PRAGMA journal_mode=MEMORY;
PRAGMA synchronous=OFF;
PRAGMA temp_store=MEMORY;
PRAGMA foreign_keys=ON;
"""

BRONZE_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_uid      TEXT PRIMARY KEY,
    literal_file_stem TEXT NOT NULL,
    directory_doc_id  TEXT NOT NULL,
    ticker_path       TEXT NOT NULL,
    year_path         INTEGER,
    basis_path        TEXT,
    rel_path          TEXT NOT NULL UNIQUE,
    n_bytes           INTEGER NOT NULL,
    n_lines           INTEGER NOT NULL,
    n_pages           INTEGER NOT NULL,
    n_tables          INTEGER NOT NULL,
    sha256            TEXT NOT NULL,
    corpus_id         TEXT NOT NULL,
    scan_status       TEXT NOT NULL,
    discovery_status  TEXT NOT NULL,
    -- RC-06 · APPEND-ONLY. Đo trên văn bản THÔ, độc lập với bộ phân tích.
    -- `n_tables` nói bộ phân tích dựng được bao nhiêu bảng; `n_table_markup`
    -- nói tệp gốc CÓ bao nhiêu chỗ mở thẻ bảng. Hai số bằng 0 cùng lúc là
    -- ngoài phạm vi; số sau lớn hơn 0 mà số trước bằng 0 là LỖI PARSER.
    n_table_markup    INTEGER NOT NULL DEFAULT 0,
    n_numeric_tokens  INTEGER NOT NULL DEFAULT 0,
    n_grouped_numbers INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pages (
    page_uid     TEXT PRIMARY KEY,
    document_uid TEXT NOT NULL,
    page_no      INTEGER NOT NULL,
    line_start   INTEGER NOT NULL,
    line_end     INTEGER,
    char_start   INTEGER NOT NULL,
    FOREIGN KEY (document_uid) REFERENCES documents(document_uid)
);

CREATE TABLE IF NOT EXISTS tables (
    table_uid              TEXT PRIMARY KEY,
    document_uid           TEXT NOT NULL,
    line_start_1based      INTEGER NOT NULL,
    line_end_1based        INTEGER NOT NULL,
    line_start_0based      INTEGER NOT NULL,
    table_ordinal_document INTEGER NOT NULL,
    table_ordinal_page     INTEGER,
    page_no                INTEGER,
    char_start             INTEGER NOT NULL,
    char_end               INTEGER NOT NULL,
    raw_html               TEXT NOT NULL,
    raw_html_sha256        TEXT NOT NULL,
    discovery_status       TEXT NOT NULL,
    FOREIGN KEY (document_uid) REFERENCES documents(document_uid)
);

CREATE INDEX IF NOT EXISTS ix_doc_ticker  ON documents(ticker_path, year_path);
CREATE INDEX IF NOT EXISTS ix_doc_dirid   ON documents(directory_doc_id);
CREATE INDEX IF NOT EXISTS ix_tab_doc     ON tables(document_uid);
CREATE INDEX IF NOT EXISTS ix_tab_line    ON tables(document_uid, line_start_1based);

-- ── RC-06 · phân loại tài liệu tabular / non-tabular ───────────────────────
--
-- VIEW chứ không phải ba cột lưu sẵn, có chủ ý. `document_kind` và
-- `table_exclusion_reason` là hàm THUẦN của `n_tables`, thứ đã nằm sẵn trong
-- `documents`. Lưu thêm một bản sao tạo ra nguồn sự thật thứ hai và một cơ
-- hội để hai bản lệch nhau — đúng lớp lỗi vừa gặp ở `corpus.root`.
--
-- `retrieval_route` là CHÍNH SÁCH, không suy được từ dữ liệu. Đặt
-- `explicit_out_of_scope` cho tám tài liệu không có markup bảng vì hôm nay
-- KHÔNG có bằng chứng nào trong repo này cho thấy tầng truy hồi đánh chỉ mục
-- văn xuôi. Khi có, đổi một dòng ở đây thành `text_fallback` — và đó phải là
-- một thay đổi CÓ BẰNG CHỨNG, không phải một mặc định lạc quan.
--
-- ── RC-06 bản 2 · BA trạng thái, không phải hai ───────────────────────────
--
-- Bản 1 chỉ hỏi `n_tables > 0`, và vì thế gán `no_table_markup` cho MỌI tài
-- liệu không có bảng — kể cả tài liệu mà bộ phân tích bỏ sót. Đó là một lời
-- khẳng định về VĂN BẢN GỐC được suy ra từ KẾT QUẢ PHÂN TÍCH, tức là đúng
-- kiểu suy luận đã làm hỏng `execution_ready` ở RC-02.
--
-- Nay `n_table_markup` đo thẳng trên văn bản thô, nên ba trạng thái tách bạch:
--
--   n_tables > 0                        → tabular              (bình thường)
--   n_tables = 0 ∧ n_table_markup = 0   → non_tabular          (NGOÀI PHẠM VI)
--   n_tables = 0 ∧ n_table_markup > 0   → tabular_parse_failed (LỖI THẬT)
--
-- Trạng thái thứ ba là thứ mà bản 1 KHÔNG THỂ nhìn thấy. Nó phải làm đỏ cổng
-- DQ, không phải nằm im trong nhóm "đã biết".
--
-- `numeric_content` là TÓM TẮT NỘI DUNG SỐ. Nó trả lời câu mà review 28 hỏi:
-- bỏ những tài liệu này ra thì mất bao nhiêu con số? Ngưỡng đặt theo mật độ
-- đo được trên corpus, không phải theo cảm giác — xem to_read/35 §2.
CREATE VIEW IF NOT EXISTS document_classification AS
SELECT
    document_uid,
    rel_path,
    ticker_path,
    year_path,
    n_tables,
    n_table_markup,
    n_numeric_tokens,
    n_grouped_numbers,
    CASE WHEN n_tables > 0            THEN 'tabular'
         WHEN n_table_markup > 0      THEN 'tabular_parse_failed'
         ELSE 'non_tabular' END           AS document_kind,
    CASE WHEN n_tables > 0            THEN NULL
         WHEN n_table_markup > 0      THEN 'markup_present_but_no_table_parsed'
         ELSE 'no_table_markup' END       AS table_exclusion_reason,
    CASE WHEN n_tables > 0            THEN 'table'
         WHEN n_table_markup > 0      THEN 'blocked_defect'
         ELSE 'explicit_out_of_scope' END AS retrieval_route,
    CASE WHEN n_grouped_numbers = 0   THEN 'none'
         WHEN n_grouped_numbers < 50  THEN 'sparse'
         ELSE 'dense' END                 AS numeric_content
FROM documents;
"""

SILVER_DDL = """
CREATE TABLE IF NOT EXISTS build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS table_features (
    table_uid          TEXT PRIMARY KEY,
    document_uid       TEXT NOT NULL,
    directory_doc_id   TEXT NOT NULL,
    line_start_1based  INTEGER NOT NULL,
    ticker             TEXT NOT NULL,
    doc_year           INTEGER,
    basis_path         TEXT,
    basis_from_text    TEXT,
    industry_class     TEXT NOT NULL,
    statement_type     TEXT NOT NULL,
    statement_rule     TEXT NOT NULL,
    is_data_table      INTEGER NOT NULL,
    numeric_ratio      REAL NOT NULL,
    n_source_cells     INTEGER NOT NULL,
    n_grid_rows        INTEGER NOT NULL,
    n_grid_cols        INTEGER NOT NULL,
    n_header_rows      INTEGER NOT NULL,
    sep_convention     TEXT NOT NULL,
    sep_source         TEXT NOT NULL,
    section_text       TEXT NOT NULL,
    context_raw        TEXT NOT NULL,
    context_clean      TEXT NOT NULL,
    parse_status       TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL,
    -- ── [F3] ghép bảng bị tách đôi: NULL ở v1.0, được điền ở v1.3/v1.4 ──
    table_group_uid        TEXT,
    table_group_role       TEXT,
    table_group_confidence TEXT,
    -- ── [F3] xuất xứ section: NULL ở v1.0, được điền ở v1.1 ──
    section_source_line INTEGER,
    section_rule        TEXT,
    section_confidence  TEXT
);

CREATE TABLE IF NOT EXISTS source_cells (
    source_cell_uid  TEXT PRIMARY KEY,
    table_uid        TEXT NOT NULL,
    source_row_idx   INTEGER NOT NULL,
    source_col_idx   INTEGER NOT NULL,
    grid_row_idx     INTEGER NOT NULL,
    grid_col_idx     INTEGER NOT NULL,
    rowspan          INTEGER NOT NULL,
    colspan          INTEGER NOT NULL,
    text_source      TEXT NOT NULL,
    text_clean       TEXT NOT NULL,
    clean_rules_json TEXT NOT NULL,
    clean_status     TEXT NOT NULL,
    FOREIGN KEY (table_uid) REFERENCES table_features(table_uid)
);

CREATE TABLE IF NOT EXISTS grid_cells (
    table_uid       TEXT NOT NULL,
    grid_row_idx    INTEGER NOT NULL,
    grid_col_idx    INTEGER NOT NULL,
    source_cell_uid TEXT NOT NULL,
    is_span_anchor  INTEGER NOT NULL,
    cell_role       TEXT NOT NULL,
    PRIMARY KEY (table_uid, grid_row_idx, grid_col_idx),
    FOREIGN KEY (source_cell_uid) REFERENCES source_cells(source_cell_uid)
);

CREATE TABLE IF NOT EXISTS rows (
    table_uid        TEXT NOT NULL,
    grid_row_idx     INTEGER NOT NULL,
    row_role         TEXT NOT NULL,
    label_source     TEXT NOT NULL,
    label_clean      TEXT NOT NULL,
    row_path_json    TEXT NOT NULL,
    row_path_text    TEXT NOT NULL,
    row_level        INTEGER NOT NULL,
    metric_code      TEXT,
    is_generic_label INTEGER NOT NULL,
    flags_json       TEXT NOT NULL,
    -- ── Data Contract v1: danh tính VẬT LÝ, không phụ thuộc text ──
    row_uid          TEXT NOT NULL,
    -- ── [F3] ngữ nghĩa phân cấp: NULL ở v1.0, được điền ở v1.2 ──
    parent_row_uid       TEXT,
    hierarchy_level      INTEGER,
    hierarchy_source     TEXT,
    hierarchy_confidence TEXT,
    structural_role      TEXT,
    accounting_role      TEXT,
    PRIMARY KEY (table_uid, grid_row_idx),
    FOREIGN KEY (table_uid) REFERENCES table_features(table_uid)
);

CREATE TABLE IF NOT EXISTS columns (
    table_uid        TEXT NOT NULL,
    grid_col_idx     INTEGER NOT NULL,
    column_role      TEXT NOT NULL,
    header_path_json TEXT NOT NULL,
    header_path_text TEXT NOT NULL,
    period_start     TEXT,
    period_end       TEXT,
    as_of_date       TEXT,
    period_type      TEXT NOT NULL,
    period_role      TEXT NOT NULL,
    period_source    TEXT NOT NULL,
    quarter          INTEGER,
    is_restated      INTEGER NOT NULL,
    unit_kind        TEXT NOT NULL,
    currency         TEXT,
    scale_exponent   INTEGER,
    numeric_ratio    REAL NOT NULL,
    flags_json       TEXT NOT NULL,
    column_uid       TEXT NOT NULL,
    -- ── [F3] nhóm cột: NULL ở v1.0, được điền ở v1.1 ──
    parent_column_uid       TEXT,
    column_group_source     TEXT,
    column_group_confidence TEXT,
    PRIMARY KEY (table_uid, grid_col_idx),
    FOREIGN KEY (table_uid) REFERENCES table_features(table_uid)
);

-- value_decimal_text: canonical TEXT. KHÔNG BAO GIỜ dùng REAL cho giá trị
-- tài chính — số quan sát tới 10^15, float64 hỏng ở ngưỡng đó.
CREATE TABLE IF NOT EXISTS observations (
    observation_uid           TEXT PRIMARY KEY,
    table_uid                 TEXT NOT NULL,
    source_cell_uid           TEXT NOT NULL,
    grid_row_idx              INTEGER NOT NULL,
    grid_col_idx              INTEGER NOT NULL,
    row_path_json             TEXT NOT NULL,
    row_path_text             TEXT NOT NULL,
    col_path_json             TEXT NOT NULL,
    col_path_text             TEXT NOT NULL,
    metric_label_source       TEXT NOT NULL,
    metric_label_clean        TEXT NOT NULL,
    metric_code_raw           TEXT,
    value_source              TEXT NOT NULL,
    value_clean               TEXT NOT NULL,
    value_decimal_text        TEXT,
    value_kind                TEXT NOT NULL,
    parse_status              TEXT NOT NULL,
    parse_rule                TEXT NOT NULL,
    is_negative               INTEGER NOT NULL,
    unit_kind                 TEXT NOT NULL,
    currency                  TEXT,
    scale_exponent            INTEGER,
    unit_kind_source          TEXT NOT NULL,
    currency_source           TEXT NOT NULL,
    scale_source              TEXT NOT NULL,
    period_start              TEXT,
    period_end                TEXT,
    as_of_date                TEXT,
    period_type               TEXT NOT NULL,
    period_role               TEXT NOT NULL,
    period_source             TEXT NOT NULL,
    quarter                   INTEGER,
    is_restated               INTEGER NOT NULL,
    reported_in_document_year INTEGER,
    dimensions_json           TEXT NOT NULL,
    quality_flags_json        TEXT NOT NULL,
    -- Data Contract v1: neo về DÒNG và CỘT vật lý, không qua row_path.
    row_uid                   TEXT NOT NULL,
    column_uid                TEXT NOT NULL,
    FOREIGN KEY (table_uid)       REFERENCES table_features(table_uid),
    FOREIGN KEY (source_cell_uid) REFERENCES source_cells(source_cell_uid)
);

CREATE TABLE IF NOT EXISTS quality_issues (
    issue_uid    TEXT PRIMARY KEY,
    scope_type   TEXT NOT NULL,
    scope_uid    TEXT NOT NULL,
    severity     TEXT NOT NULL,
    rule_id      TEXT NOT NULL,
    message      TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_tf_tick   ON table_features(ticker, doc_year);
CREATE INDEX IF NOT EXISTS ix_tf_type   ON table_features(statement_type, is_data_table);
CREATE INDEX IF NOT EXISTS ix_sc_tab    ON source_cells(table_uid);
CREATE INDEX IF NOT EXISTS ix_obs_tab   ON observations(table_uid);
CREATE INDEX IF NOT EXISTS ix_obs_path  ON observations(row_path_text);
CREATE INDEX IF NOT EXISTS ix_obs_per   ON observations(period_end);
CREATE INDEX IF NOT EXISTS ix_qi_scope  ON quality_issues(scope_type, severity);
"""

SILVER_DDL += COLLISION_DDL

# ── DI-02, mức Ô ─────────────────────────────────────────────────────────────
# Bất biến DI-02 cấm hard-delete ở mức BẢNG, nhưng ở mức Ô thì pipeline vẫn
# đang vứt im lặng: 162.715 ô có ≥4 chữ số không thành observation và không có
# nơi nào ghi vì sao. Đo bằng công thức doc 12 §5.2 thì chúng rơi vào
# `unexplained_financial_drop_count` — đúng chỗ RC bị chặn.
#
# Bảng này ghi LÝ DO cho mọi ô có chữ số bị bỏ qua. Nó không giữ lại dữ liệu
# (ô nguồn vẫn nguyên trong `source_cells`), nó giữ lại QUYẾT ĐỊNH.
SILVER_DDL += """
CREATE TABLE IF NOT EXISTS dropped_cells (
    source_cell_uid TEXT PRIMARY KEY,
    table_uid       TEXT NOT NULL,
    grid_row_idx    INTEGER NOT NULL,
    grid_col_idx    INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    detail          TEXT,
    text_clean      TEXT
);
CREATE INDEX IF NOT EXISTS ix_dc_reason ON dropped_cells(reason);
CREATE INDEX IF NOT EXISTS ix_dc_tab    ON dropped_cells(table_uid);
"""

# Tra ngược ô nguồn -> observation là truy vấn HẠNG NHẤT của người tiêu thụ
# ("con số này lấy từ ô nào") và của mọi thước no-loss. Thiếu chỉ mục này,
# một `EXISTS (… WHERE source_cell_uid = …)` phải quét trọn 2,6 triệu dòng cho
# TỪNG ô trong 6,2 triệu ô nguồn — đo được là ~365 giờ cho một lần đo.
SILVER_DDL += """
CREATE INDEX IF NOT EXISTS ix_obs_srccell ON observations(source_cell_uid);
CREATE INDEX IF NOT EXISTS ix_obs_rowuid  ON observations(row_uid);
CREATE INDEX IF NOT EXISTS ix_obs_coluid  ON observations(column_uid);
CREATE INDEX IF NOT EXISTS ix_gc_anchor   ON grid_cells(source_cell_uid, is_span_anchor);
"""


def connect(path: Path, ddl: str, fresh: bool = False) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fresh:
        path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_PRAGMA + ddl)
    return conn


def integrity_check(conn: sqlite3.Connection) -> list[str]:
    """Trả về danh sách lỗi. Rỗng nghĩa là đạt."""
    errs: list[str] = []
    row = conn.execute("PRAGMA integrity_check").fetchone()
    if row and row[0] != "ok":
        errs.append(f"integrity_check: {row[0]}")
    for r in conn.execute("PRAGMA foreign_key_check").fetchall():
        errs.append(f"foreign_key_check: {r}")
    # DI-05: không cột giá trị tài chính nào được khai REAL
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall():
        for col in conn.execute(f"PRAGMA table_info({name})").fetchall():
            if col[2].upper() == "REAL" and (
                "value" in col[1] or "amount" in col[1] or "decimal" in col[1]
            ):
                errs.append(f"DI-05 vi phạm: {name}.{col[1]} khai REAL")
    return errs


def publish_db(src: Path, dst: Path) -> str:
    """Copy artifact sau khi đã đóng connection, trả checksum."""
    import hashlib
    import shutil

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    h = hashlib.sha256()
    with dst.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
