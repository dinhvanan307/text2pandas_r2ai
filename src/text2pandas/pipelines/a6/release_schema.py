"""DP-018a — Lược đồ của GÓI PHÁT HÀNH, tách khỏi lược đồ nội bộ của pipeline.

Hai lược đồ này KHÁC nhau có chủ đích:

* Silver nội bộ tối ưu cho **tái lập**: giữ mọi ô nguồn, mọi ô lưới, mọi dấu vết
  làm sạch. 4,8 GB, phần lớn là tầng truy vết mà người tiêu thụ không cần.
* Gói phát hành tối ưu cho **sử dụng**: khoá chính, khoá ngoại, chỉ mục, và một
  ít phi chuẩn hoá có tính toán để người dùng không phải JOIN cho mọi truy vấn.

Đây cũng là bản khai của hợp đồng DP-015: tên cột ở đây là **giao diện công
khai**. Đổi chúng là breaking change, kể cả khi lược đồ nội bộ không đổi.

PHI CHUẨN HOÁ CÓ CHỦ ĐÍCH
`observations` mang sẵn `ticker`, `doc_year`, `directory_doc_id`,
`statement_type` — vốn thuộc về `tables`. Lý do: mọi truy vấn Text-to-Pandas
đều lọc theo mã chứng khoán và năm. Bắt người dùng JOIN 2,57 triệu dòng cho
từng câu hỏi là đánh đổi sai. Chi phí ~50 MB, đổi lấy việc bỏ được một JOIN
trong 100% truy vấn.
"""

from __future__ import annotations

__all__ = ["RELEASE_DDL", "RELEASE_INDEX_DDL", "RELEASE_FTS_DDL",
           "RELEASE_CARD_DDL", "RELEASE_LONG_DDL", "RELEASE_DOC_CLASS_DDL",
           "TABLE_DOCS", "COLUMN_DOCS", "SLIM_TABLES", "FULL_TABLES",
           "RELEASE_SCHEMA_VERSION"]

RELEASE_SCHEMA_VERSION = "1.2"

SLIM_TABLES = ("documents", "pages", "tables", "columns", "rows",
               "observations", "dropped_cells", "quality_issues",
               "quality_rule_totals", "build_meta",
               # v1.2+RC-02 · APPEND-ONLY. Trước RC-02, toàn bộ máy chính sách
               # readiness chạy trên DB dựng rồi BỊ BỎ LẠI: gói phát hành không
               # có bảng này, và `v_long_dataframe` tự tính lại `execution_ready`
               # bằng một biểu thức 4 điều kiện khác hẳn chính sách. Người nhận
               # gói vì thế không bao giờ thấy confidence, blocking hay warning.
               "observation_readiness")
FULL_TABLES = SLIM_TABLES + ("source_cells", "grid_cells")

RELEASE_DDL = """
CREATE TABLE documents (
    document_uid      TEXT PRIMARY KEY,
    directory_doc_id  TEXT NOT NULL UNIQUE,
    ticker            TEXT NOT NULL,
    doc_year          INTEGER,
    basis             TEXT,
    rel_path          TEXT NOT NULL UNIQUE,
    n_bytes           INTEGER NOT NULL,
    n_lines           INTEGER NOT NULL,
    n_pages           INTEGER NOT NULL,
    n_tables          INTEGER NOT NULL,
    sha256            TEXT NOT NULL,
    -- RC-06 · APPEND-ONLY. Đo trên văn bản THÔ, độc lập với bộ phân tích.
    -- Không đóng gói ba số này thì người nhận gói không có cách nào tự phân
    -- biệt "tài liệu vốn không có bảng" với "bảng bị bộ phân tích đánh rơi" —
    -- và câu "không mất dữ liệu nào mà không giải thích được" trở lại thành
    -- một lời hứa thay vì một thứ kiểm được.
    n_table_markup    INTEGER NOT NULL DEFAULT 0,
    n_numeric_tokens  INTEGER NOT NULL DEFAULT 0,
    n_grouped_numbers INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE pages (
    page_uid     TEXT PRIMARY KEY,
    document_uid TEXT NOT NULL REFERENCES documents(document_uid),
    page_no      INTEGER NOT NULL,
    line_start   INTEGER NOT NULL,
    line_end     INTEGER,
    UNIQUE (document_uid, page_no)
);

CREATE TABLE tables (
    table_uid          TEXT PRIMARY KEY,
    document_uid       TEXT NOT NULL REFERENCES documents(document_uid),
    directory_doc_id   TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    doc_year           INTEGER,
    basis              TEXT,
    industry_class     TEXT,
    statement_type     TEXT NOT NULL,
    statement_rule     TEXT,
    is_data_table      INTEGER NOT NULL,
    line_start_1based  INTEGER NOT NULL,
    page_no            INTEGER,
    locator            TEXT NOT NULL,
    evidence_ref       TEXT NOT NULL,
    n_grid_rows        INTEGER NOT NULL,
    n_grid_cols        INTEGER NOT NULL,
    n_header_rows      INTEGER NOT NULL,
    n_source_cells     INTEGER NOT NULL,
    numeric_ratio      REAL NOT NULL,
    sep_convention     TEXT NOT NULL,
    section_text       TEXT,
    context_clean      TEXT,
    parse_status       TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL
);

CREATE TABLE columns (
    table_uid        TEXT NOT NULL REFERENCES tables(table_uid),
    grid_col_idx     INTEGER NOT NULL,
    column_role      TEXT NOT NULL,
    header_path_text TEXT,
    header_path_json TEXT NOT NULL,
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
    PRIMARY KEY (table_uid, grid_col_idx)
);

CREATE TABLE rows (
    table_uid        TEXT NOT NULL REFERENCES tables(table_uid),
    grid_row_idx     INTEGER NOT NULL,
    row_role         TEXT NOT NULL,
    label_source     TEXT,
    label_clean      TEXT,
    row_path_text    TEXT,
    row_path_json    TEXT NOT NULL,
    row_level        INTEGER,
    metric_code      TEXT,
    is_generic_label INTEGER NOT NULL,
    flags_json       TEXT NOT NULL,
    PRIMARY KEY (table_uid, grid_row_idx)
);

CREATE TABLE observations (
    observation_uid    TEXT PRIMARY KEY,
    table_uid          TEXT NOT NULL REFERENCES tables(table_uid),
    -- P0-04: neo về đúng Ô NGUỒN, không chỉ về bảng. Thiếu bốn cột này thì
    -- `observation_uid = hash(table_uid, source_cell_uid)` không kiểm chứng
    -- được từ chính gói, và không ai audit được ánh xạ rowspan/colspan.
    source_cell_uid    TEXT NOT NULL,
    source_row_idx     INTEGER,
    source_col_idx     INTEGER,
    value_source_raw   TEXT,
    grid_row_idx       INTEGER NOT NULL,
    grid_col_idx       INTEGER NOT NULL,
    directory_doc_id   TEXT NOT NULL,
    ticker             TEXT NOT NULL,
    doc_year           INTEGER,
    statement_type     TEXT NOT NULL,
    evidence_ref       TEXT NOT NULL,
    row_path_text      TEXT,
    col_path_text      TEXT,
    metric_label_clean TEXT,
    metric_code        TEXT,
    value_source       TEXT NOT NULL,
    value_decimal_text TEXT,
    value_kind         TEXT NOT NULL,
    parse_status       TEXT NOT NULL,
    parse_rule         TEXT NOT NULL,
    is_negative        INTEGER NOT NULL,
    unit_kind          TEXT NOT NULL,
    currency           TEXT,
    scale_exponent     INTEGER,
    scale_source       TEXT NOT NULL,
    period_start       TEXT,
    period_end         TEXT,
    as_of_date         TEXT,
    period_type        TEXT NOT NULL,
    period_role        TEXT NOT NULL,
    period_source      TEXT NOT NULL,
    quarter            INTEGER,
    is_restated        INTEGER NOT NULL,
    confidence         TEXT NOT NULL,
    quality_flags_json TEXT NOT NULL,
    -- Data Contract v1: danh tính VẬT LÝ phải đi theo gói phát hành, không chỉ
    -- nằm trong Silver nội bộ. Thiếu hai cột này thì người nhận gói không so
    -- được build cũ với build mới theo cùng một dòng, và differential audit
    -- (doc 12 §5.2) không thực hiện được.
    row_uid            TEXT NOT NULL,
    column_uid         TEXT NOT NULL,
    -- Phân loại đụng độ: NULL nghĩa là fact này KHÔNG nằm trong nhóm mơ hồ nào.
    collision_class    TEXT,
    FOREIGN KEY (table_uid, grid_row_idx) REFERENCES rows(table_uid, grid_row_idx),
    FOREIGN KEY (table_uid, grid_col_idx) REFERENCES columns(table_uid, grid_col_idx)
);

CREATE TABLE quality_issues (
    issue_uid    TEXT PRIMARY KEY,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    severity     TEXT NOT NULL,
    rule_id      TEXT NOT NULL,
    message      TEXT NOT NULL,
    details_json TEXT NOT NULL
);

-- P1-03: tổng số vi phạm theo rule, tách khỏi bảng mẫu `quality_issues`.
CREATE TABLE quality_rule_totals (
    rule_id        TEXT PRIMARY KEY,
    total_count    INTEGER NOT NULL,
    sampled_count  INTEGER NOT NULL,
    sample_limit   INTEGER NOT NULL
);

-- Ô số ĐỌC ĐƯỢC nhưng KHÔNG sinh observation, kèm lý do. Bảng này thuộc về
-- gói phát hành chứ không chỉ Silver nội bộ: nếu người nhận muốn kiểm câu
-- "không mất dữ liệu nào mà không giải thích được" thì họ phải tự đếm được,
-- không phải tin một dòng trong file markdown. Đây là bảng mà một người nghi
-- ngờ gói sẽ mở đầu tiên — và nó nên mở được.
CREATE TABLE dropped_cells (
    source_cell_uid TEXT PRIMARY KEY,
    table_uid       TEXT NOT NULL REFERENCES tables(table_uid),
    grid_row_idx    INTEGER NOT NULL,
    grid_col_idx    INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    detail          TEXT,
    text_clean      TEXT
);

CREATE TABLE build_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- RC-02 · readiness HAI TẦNG, vật chất hoá và ĐI THEO GÓI.
--
-- `execution_candidate` = tính được về mặt cơ học (đủ field bắt buộc).
-- `execution_ready`     = candidate ∧ đủ tin cậy ∧ không có lý do chặn nào.
-- Bất biến: ready ⇒ candidate.
--
-- Ba mảng lý do là JSON array ĐÃ SORT, KHÔNG TRÙNG, tách theo mức ưu tiên
-- NON_CANDIDATE > BLOCKING > WARNING > PASS. Tách ra vì chúng trả lời ba câu
-- khác nhau: "thiếu field gì", "vì sao không được tự động dùng", "dùng được
-- nhưng phải biết điều gì".
CREATE TABLE observation_readiness (
    observation_uid           TEXT PRIMARY KEY
                                   REFERENCES observations(observation_uid),
    execution_candidate       INTEGER NOT NULL,
    execution_ready           INTEGER NOT NULL,
    confidence                TEXT    NOT NULL,
    blocking_reasons_json     TEXT    NOT NULL,
    warning_reasons_json      TEXT    NOT NULL,
    non_candidate_reasons_json TEXT   NOT NULL,
    policy_version            TEXT    NOT NULL
);
"""

# `source_cells` / `grid_cells` chỉ có ở hồ sơ `full`. Chúng là tầng TRUY VẾT:
# cần để tái lập và để kiểm toán, không cần để dùng. Chiếm 1,9 GB trên 4,8 GB.
RELEASE_DDL_FULL_EXTRA = """
CREATE TABLE source_cells (
    source_cell_uid  TEXT PRIMARY KEY,
    table_uid        TEXT NOT NULL REFERENCES tables(table_uid),
    source_row_idx   INTEGER NOT NULL,
    source_col_idx   INTEGER NOT NULL,
    grid_row_idx     INTEGER NOT NULL,
    grid_col_idx     INTEGER NOT NULL,
    rowspan          INTEGER NOT NULL,
    colspan          INTEGER NOT NULL,
    text_source      TEXT NOT NULL,
    text_clean       TEXT NOT NULL,
    clean_status     TEXT NOT NULL
);

CREATE TABLE grid_cells (
    table_uid       TEXT NOT NULL REFERENCES tables(table_uid),
    grid_row_idx    INTEGER NOT NULL,
    grid_col_idx    INTEGER NOT NULL,
    source_cell_uid TEXT NOT NULL,
    is_span_anchor  INTEGER NOT NULL,
    PRIMARY KEY (table_uid, grid_row_idx, grid_col_idx)
);
"""

# Chỉ mục chọn theo ĐƯỜNG TRUY CẬP đã biết, không phải theo linh cảm. Mỗi chỉ
# mục ở đây phục vụ một câu hỏi cụ thể mà tầng dưới sẽ hỏi hàng nghìn lần.
RELEASE_INDEX_DDL = """
CREATE INDEX ix_tables_ticker_year   ON tables(ticker, doc_year);
CREATE INDEX ix_tables_statement     ON tables(statement_type);
CREATE INDEX ix_tables_doc           ON tables(document_uid);
CREATE INDEX ix_tables_docid         ON tables(directory_doc_id);

CREATE INDEX ix_cols_role            ON columns(column_role);
CREATE INDEX ix_cols_period          ON columns(period_end);

CREATE INDEX ix_rows_metric_code     ON rows(metric_code);

CREATE INDEX ix_obs_table            ON observations(table_uid);
CREATE INDEX ix_obs_ticker_year      ON observations(ticker, doc_year);
CREATE INDEX ix_obs_period           ON observations(period_end);
CREATE INDEX ix_obs_metric_code      ON observations(metric_code);
CREATE INDEX ix_obs_statement        ON observations(statement_type, ticker, doc_year);
CREATE INDEX ix_obs_kind             ON observations(value_kind);
CREATE INDEX ix_obs_confidence       ON observations(confidence);
CREATE INDEX ix_obs_source_cell      ON observations(source_cell_uid);

CREATE INDEX ix_issues_rule          ON quality_issues(rule_id);
CREATE INDEX ix_issues_entity        ON quality_issues(entity_id);

CREATE INDEX ix_dropped_reason       ON dropped_cells(reason);
CREATE INDEX ix_dropped_table        ON dropped_cells(table_uid);

CREATE INDEX ix_rdy_ready            ON observation_readiness(execution_ready);
CREATE INDEX ix_rdy_cand             ON observation_readiness(execution_candidate);
CREATE INDEX ix_rdy_conf             ON observation_readiness(confidence);
"""

# FTS5 trên thẻ bảng — đây chính là đầu vào cho tầng Retrieval. Đặt sẵn trong
# gói để nhóm truy hồi không phải dựng lại chỉ mục từ đầu.
# ── Table Card CƠ SỞ ────────────────────────────────────────────────────────
# Trước đây gói chỉ có `table_cards_fts` — một CHỈ MỤC toàn văn. FTS5 không
# join được, không mang cờ readiness, không băm được nội dung. Doc 12 §7 điều
# kiện 8 đòi "Table Card base tồn tại"; §10 câu 27–28 đòi schema và
# `content_hash` theo nhóm trường.
#
# `content_hash` tách theo NHÓM: downstream so hash để biết phải dựng lại
# PHẦN NÀO của chỉ mục khi Silver Final ra, thay vì dựng lại tất cả hoặc chạy
# tiếp trên chỉ mục cũ mà không biết.
RELEASE_CARD_DDL = """
CREATE TABLE table_cards (
    table_uid        TEXT PRIMARY KEY REFERENCES tables(table_uid),
    doc_id           TEXT NOT NULL,
    locator          TEXT NOT NULL,
    evidence_ref     TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    doc_year         INTEGER,
    statement_type   TEXT NOT NULL,
    section_text     TEXT,
    n_rows           INTEGER NOT NULL,
    n_cols           INTEGER NOT NULL,
    n_observations   INTEGER NOT NULL,
    row_terms        TEXT,
    col_terms        TEXT,
    metric_codes     TEXT,
    periods          TEXT,
    units            TEXT,
    table_search_text TEXT,
    retrieval_ready  INTEGER NOT NULL,
    execution_ready_obs INTEGER NOT NULL,
    review_required_obs INTEGER NOT NULL,
    -- ── RC-08 · năm trường của `table_readiness_contract` ────────────────
    --
    -- Thiếu chúng thì tầng truy hồi phải JOIN 2,6 triệu observation chỉ để
    -- trả lời "bảng này có ô nào dùng được không" — một câu hỏi cấp BẢNG.
    --
    -- `has_*` là cờ dẫn xuất từ `*_obs`, có chủ đích: chỉ mục trên cờ 0/1
    -- lọc nhanh hơn nhiều so với `> 0` trên số đếm, và tầng truy hồi lọc
    -- theo đúng ba cờ này ở mọi truy vấn.
    execution_candidate_obs INTEGER NOT NULL DEFAULT 0,
    has_observations        INTEGER NOT NULL DEFAULT 0,
    has_execution_candidate INTEGER NOT NULL DEFAULT 0,
    has_execution_ready     INTEGER NOT NULL DEFAULT 0,
    -- Đếm theo TỪNG lý do, không phải một tổng. "Bảng này 40 ô không dùng
    -- được" không nói được gì; "40 ô vì confidence_low" thì sửa được.
    not_ready_reason_counts_json TEXT NOT NULL DEFAULT '{}',
    quality_flags_json TEXT NOT NULL,
    hash_identity    TEXT NOT NULL,
    hash_labels      TEXT NOT NULL,
    hash_semantics   TEXT NOT NULL
);
CREATE INDEX ix_tc_doc  ON table_cards(doc_id);
CREATE INDEX ix_tc_type ON table_cards(statement_type);
CREATE INDEX ix_tc_rr   ON table_cards(retrieval_ready);
CREATE INDEX ix_tc_hasx ON table_cards(has_execution_ready);
CREATE INDEX ix_tc_hasc ON table_cards(has_execution_candidate);
"""

# ── DataFrame dạng LONG — hợp đồng giao cho Text-to-Pandas ──────────────────
# Doc 12 §3.5 khoá danh sách cột. Tên cột của DataFrame là schema CỐ ĐỊNH; nhãn
# nguồn nằm trong `col_label`/`col_path`, nên `n_header=0` không tạo trùng tên.
RELEASE_LONG_DDL = """
CREATE VIEW v_long_dataframe AS
SELECT
    o.directory_doc_id                        AS doc_id,
    o.table_uid                               AS table_uid,
    t.locator                                 AS table_locator,
    o.statement_type                          AS statement_type,
    o.row_uid                                 AS row_uid,
    o.grid_row_idx                            AS row_idx,
    o.metric_label_clean                      AS row_label,
    o.row_path_text                           AS row_path,
    o.metric_code                             AS metric_code,
    o.column_uid                              AS column_uid,
    o.grid_col_idx                            AS col_idx,
    COALESCE(NULLIF(o.col_path_text, ''), 'col:' || o.grid_col_idx) AS col_label,
    o.col_path_text                           AS col_path,
    o.period_end                              AS period_end,
    o.period_role                             AS period_role,
    o.value_source_raw                        AS value_raw,
    o.value_decimal_text                      AS value,
    o.value_kind                              AS value_kind,
    o.unit_kind                               AS unit,
    o.currency                                AS currency,
    o.scale_exponent                          AS scale,
    o.source_cell_uid                         AS source_cell_uid,
    o.quality_flags_json                      AS quality_flags,
    o.collision_class                         AS collision_class,
    c.retrieval_ready                         AS retrieval_ready,
    -- RC-02 · ĐỌC TỪ BẢNG CHÍNH SÁCH, không tự tính lại.
    --
    -- Bản v1.2 cũ đặt ở đây một biểu thức CASE bốn điều kiện
    -- (collision IS NULL ∧ period_end ∧ unit≠unknown ∧ label≠''). Đó là một
    -- ĐỊNH NGHĨA THỨ HAI của `execution_ready`, không biết gì về confidence,
    -- tiny-money, hay bằng chứng của kỳ — và vì `observation_readiness` không
    -- được đóng gói, nó là định nghĩa DUY NHẤT mà người nhận gói nhìn thấy.
    -- Toàn bộ cổng C4 vì thế đo trên một tập không hề được phát hành.
    r.execution_ready                         AS execution_ready,
    r.execution_candidate                     AS execution_candidate,
    r.confidence                              AS confidence,
    r.blocking_reasons_json                   AS blocking_reasons,
    r.warning_reasons_json                    AS warning_reasons,
    r.non_candidate_reasons_json              AS non_candidate_reasons,
    CASE WHEN r.execution_candidate = 1 AND r.execution_ready = 0
         THEN 1 ELSE 0 END                    AS review_required
FROM observations o
JOIN tables t      ON t.table_uid = o.table_uid
JOIN observation_readiness r ON r.observation_uid = o.observation_uid
LEFT JOIN table_cards c ON c.table_uid = o.table_uid;
"""

# ── RC-05 · nội dung FTS lưu ở DẠNG CHUẨN ──────────────────────────────────
#
# `unicode61 remove_diacritics 2` gập được MỌI dấu tiếng Việt trừ đúng một ký
# tự: `đ` (U+0111). Nó không phải `d` + dấu phụ mà là một code point riêng, nên
# NFD không tách được và bộ lọc combining mark không chạm tới.
#
# Đo trên RC1: `đồng` 104.792 thẻ có dấu / 997 không dấu (mất 99,0%);
# `đầu tư` 63.407 / 289 (99,5%); `tương đương` 10.496 / 12 (99,9%). Trong khi
# `tiền`, `chi phí`, `tài sản` — không có `đ` — mất **0,0%**. Lỗi nằm ở đúng
# một ký tự, và 96,4% thẻ chứa nó ở ít nhất một trường được đánh chỉ mục.
#
# Cách chữa: chuẩn hoá NỘI DUNG khi nạp, bằng `normalize_search_text()` —
# cùng một hàm mà tầng truy vấn phải gọi. Đã cân nhắc phương án thêm 4 cột
# `*_norm` song song và ĐO trên dữ liệu thật: chỉ mục 437,5 MB → 784,2 MB
# (+79%), cộng thêm việc mọi từ KHÔNG chứa `đ` bị đếm hai lần làm lệch BM25.
# Không đáng cho một lỗi nằm ở một ký tự.
#
# Tên cột GIỮ NGUYÊN (hợp đồng schema cấm rename). Chúng nay chứa dạng chuẩn;
# văn bản gốc để hiển thị và trích dẫn vẫn nằm nguyên vẹn ở `table_cards`.
FTS_CONTENT = "normalized"      # ghi vào build_meta để người nhận gói kiểm được
FTS_TOKENIZER = "unicode61 remove_diacritics 2"

# ── RC-06 · phân loại tài liệu, ĐI THEO GÓI ────────────────────────────────
#
# Bản Bronze có `document_classification`, nhưng nó ở lại DB dựng — đúng lỗi
# mà RC-02 vừa chữa cho `observation_readiness`. Người nhận gói phải tự trả
# lời được ba câu, từ chính gói:
#
#   tài liệu nào không có bảng · vì sao · bỏ nó ra thì mất bao nhiêu con số
#
# `-1` nghĩa là KHÔNG BIẾT (Bronze dựng trước RC-06 không có số đo thô). Nó
# KHÔNG được gộp vào `non_tabular`: nói "ngoài phạm vi" khi chưa đo văn bản
# gốc là dựng bằng chứng.
RELEASE_DOC_CLASS_DDL = """
CREATE VIEW v_document_classification AS
SELECT
    document_uid,
    directory_doc_id,
    ticker,
    doc_year,
    rel_path,
    n_tables,
    n_table_markup,
    n_numeric_tokens,
    n_grouped_numbers,
    CASE WHEN n_tables > 0        THEN 'tabular'
         WHEN n_table_markup < 0  THEN 'unknown'
         WHEN n_table_markup > 0  THEN 'tabular_parse_failed'
         ELSE 'non_tabular' END       AS document_kind,
    CASE WHEN n_tables > 0        THEN NULL
         WHEN n_table_markup < 0  THEN 'raw_markup_not_measured'
         WHEN n_table_markup > 0  THEN 'markup_present_but_no_table_parsed'
         ELSE 'no_table_markup' END   AS table_exclusion_reason,
    CASE WHEN n_tables > 0        THEN 'table'
         WHEN n_table_markup < 0  THEN 'unknown'
         WHEN n_table_markup > 0  THEN 'blocked_defect'
         ELSE 'explicit_out_of_scope' END AS retrieval_route,
    CASE WHEN n_grouped_numbers < 0  THEN 'unknown'
         WHEN n_grouped_numbers = 0  THEN 'none'
         WHEN n_grouped_numbers < 50 THEN 'sparse'
         ELSE 'dense' END             AS numeric_content
FROM documents;
"""

RELEASE_FTS_DDL = f"""
CREATE VIRTUAL TABLE table_cards_fts USING fts5(
    table_uid UNINDEXED,
    ticker,
    section_text,      -- DẠNG CHUẨN (normalize_search_text), không phải văn bản gốc
    context_clean,     -- DẠNG CHUẨN
    row_labels,        -- DẠNG CHUẨN
    col_labels,        -- DẠNG CHUẨN
    tokenize = '{FTS_TOKENIZER}'
);
"""

TABLE_DOCS: dict[str, str] = {
    "documents": "Một dòng cho mỗi tệp báo cáo `.txt` trong corpus. Trong bộ dữ liệu này "
                 "**document ≡ report**: mỗi tệp là một báo cáo tài chính của một mã "
                 "chứng khoán trong một năm, ở một cơ sở lập (hợp nhất / riêng).",
    "pages": "Ranh giới trang suy từ dấu `===== PAGE n =====`. Dùng để định vị bảng "
             "theo trang khi cần trích dẫn.",
    "tables": "Một dòng cho mỗi khối `<table>` phát hiện trong corpus, kèm đặc trưng "
              "cấp bảng: loại báo cáo, tiêu đề mục, ngữ cảnh, quy ước phân cách nghìn.",
    "columns": "Một dòng cho mỗi cột lưới của mỗi bảng, kèm vai trò và **kỳ báo cáo đã "
               "giải**. Đây là nơi ngữ nghĩa thời gian được quyết định.",
    "rows": "Một dòng cho mỗi dòng lưới, kèm `row_path_text` — đường dẫn phân cấp "
            "`mục › tổ tiên › nhãn` dùng làm khoá truy hồi chính.",
    "observations": "**Bảng trung tâm.** Một dòng cho mỗi ô SỐ đọc được, đã chuẩn hoá "
                    "giá trị, đơn vị và kỳ, kèm dấu vết nguồn gốc đầy đủ.",
    "dropped_cells": "Ô có nội dung SỐ nhưng **không** sinh observation, kèm `reason`. "
                     "Đây là bảng thú nhận của gói: mỗi ô biến mất đều phải có tên lý "
                     "do ở đây. Đếm `dropped_cells + observations` rồi so với số ô số "
                     "trong `grid_cells` là cách tự kiểm 'không mất gì âm thầm'.",
    "quality_issues": "Kết quả kiểm chất lượng. Mỗi dòng là một vi phạm rule đã khai "
                      "báo. Bảng này KHÔNG bao giờ được dùng để sửa dữ liệu — nó chỉ mô tả.",
    "build_meta": "Siêu dữ liệu bản dựng: `build_id`, `corpus_id`, revision, và "
                  "phiên bản TỪNG thành phần pipeline.",
    "quality_rule_totals": "Tổng số vi phạm theo rule. `quality_issues` chỉ chứa "
                           "**mẫu** (tối đa `sample_limit` dòng mỗi rule); bảng này "
                           "giữ con số đầy đủ. Đừng đếm `quality_issues` rồi coi đó "
                           "là tổng vi phạm.",
    "source_cells": "(chỉ hồ sơ `full`) Ô `<td>` nguyên bản trước khi khai triển span. "
                    "Tầng truy vết — cần để tái lập, không cần để dùng.",
    "grid_cells": "(chỉ hồ sơ `full`) Lưới sau khai triển span. Một ô `colspan=2` chiếm "
                  "hai vị trí lưới nhưng chỉ có một ô nguồn; `is_span_anchor` đánh dấu "
                  "vị trí gốc.",
    "table_cards_fts": "Chỉ mục toàn văn FTS5 trên thẻ bảng, dựng sẵn cho tầng truy hồi. "
                       "Bỏ dấu tiếng Việt để khớp cả khi người dùng gõ không dấu.",
}

COLUMN_DOCS: dict[str, dict[str, str]] = {
    "documents": {
        "document_uid": "Khoá kỹ thuật, băm từ đường dẫn tương đối.",
        "directory_doc_id": "Định danh theo tên thư mục — **đây là `doc_id` mà cuộc thi chấm**.",
        "ticker": "Mã chứng khoán, suy từ tên thư mục.",
        "doc_year": "Năm tài chính của báo cáo, suy từ tên thư mục.",
        "basis": "`consolidated` (hợp nhất) / `separate` (riêng) / `aggregated`.",
        "rel_path": "Đường dẫn tương đối trong corpus gốc.",
        "sha256": "Băm nội dung tệp gốc — neo mọi thứ về đúng bản corpus đã dùng.",
    },
    "tables": {
        "locator": "Vị trí bảng trong tài liệu, dạng `line:<số dòng 1-based>`.",
        "evidence_ref": "`\"<doc_id>|<locator>\"` — **chuỗi bằng chứng theo ràng buộc C20**. "
                        "Dựng đúng một chỗ trong toàn hệ thống; không tự nối lại.",
        "statement_type": "`balance_sheet` / `income_statement` / `cash_flow` / "
                          "`equity_change` / `note` / `subsidiary` / `personnel` / `other`.",
        "is_data_table": "Cờ HẠ TRỌNG SỐ, không phải cờ loại bỏ. Bảng `0` vẫn sinh "
                         "observation — loại cứng một bảng gold là mất recall không hồi phục.",
        "sep_convention": "`dot_thousands` (1.234.567,89) hoặc `comma_thousands`. "
                          "139 tài liệu dùng cả hai, nên quy ước được quyết ở cấp bảng.",
        "section_text": "Tiêu đề thuyết minh gần bảng nhất. Gốc của `row_path_text`.",
        "numeric_ratio": "Tỷ lệ ô thân bảng parse được thành số.",
        "parse_status": "`ok` / `table_too_large` / `table_parse_failed`.",
    },
    "columns": {
        "column_role": "`value` (số liệu) / `label` / `metric_code` (Mã số) / "
                       "`note_reference` (Thuyết minh) / `ordinal` (STT) / `unknown`.",
        "period_end": "Ngày KẾT THÚC kỳ mà giá trị thuộc về. Lưu ý: cột `01/01/YYYY` có "
                      "`period_end = YYYY-1-12-31` vì số dư đầu kỳ YYYY **là** số dư cuối "
                      "kỳ YYYY−1.",
        "as_of_date": "Ngày ghi trên nhãn cột, giữ nguyên mặt chữ.",
        "period_source": "Bậc bằng chứng đã dùng: `column_path` (đọc từ nhãn cột — tin cậy "
                         "nhất) / `document_default` (nhãn tương đối + năm tài liệu) / "
                         "`row_context` (ngày tuyệt đối đọc từ nhãn DÒNG — bố cục chuyển "
                         "vị của bảng biến động vốn chủ sở hữu, xem A5-B1; chỉ dùng khi "
                         "cột và bảng đều không mang kỳ) / `table_context` (**suy diễn** "
                         "từ ngữ cảnh bảng) / `none` (chưa giải được).",
        "period_role": "`closing` / `opening` / `current` / `prior`.",
        "period_type": "`instant` (số dư thời điểm) / `duration` (phát sinh trong kỳ) / `quarter`.",
        "scale_exponent": "Số mũ 10 của đơn vị. `0` = VND, `3` = nghìn đồng, `6` = triệu đồng.",
    },
    "rows": {
        "row_path_text": "Đường dẫn phân cấp `mục › tổ tiên › nhãn`, ngăn bằng ` › `. "
                         "**Khoá truy hồi chính** — nhãn phẳng không định danh được chỉ tiêu.",
        "is_generic_label": "Nhãn thuộc tập tổng hợp (`Cộng`, `TỔNG CỘNG`, `Số dư cuối năm`…). "
                            "16 nhãn này chiếm 200.195 ô; chúng chỉ có nghĩa khi kèm đường dẫn.",
        "metric_code": "Giá trị ở cột `Mã số` — khoá chuẩn tắc theo Thông tư 200.",
    },
    "observations": {
        "observation_uid": "Khoá chính, băm từ `(table_uid, source_cell_uid)` — "
                           "kiểm chứng được vì `source_cell_uid` có mặt ngay trong bảng này.",
        "source_cell_uid": "Ô `<td>` nguyên bản sinh ra giá trị này. Một ô `colspan=2` "
                           "phủ hai vị trí lưới nhưng chỉ có MỘT ô nguồn.",
        "source_row_idx": "Chỉ số dòng trong markup gốc, TRƯỚC khi khai triển span.",
        "source_col_idx": "Chỉ số cột trong markup gốc, TRƯỚC khi khai triển span.",
        "value_source_raw": "Văn bản ô đúng như trong markup, trước mọi làm sạch.",
        "evidence_ref": "Sao chép từ `tables` để trích dẫn không cần JOIN.",
        "value_source": "Chuỗi NGUYÊN BẢN trong ô, trước mọi biến đổi.",
        "value_decimal_text": "Giá trị chuẩn tắc, lưu dạng **TEXT** để không mất chính xác. "
                              "Corpus có số tới 10^15; `float64` hỏng ở ngưỡng đó. "
                              "Đọc bằng `Decimal(...)`, tuyệt đối không `float(...)`.",
        "value_kind": "`money` / `percentage` / `share_count` / `interest_rate` / `days` / "
                      "`quantity` / `ratio`.",
        "parse_rule": "Rule đã áp để đọc con số — dấu vết để truy nguyên khi nghi ngờ.",
        "scale_source": "`cell` / `column_path` / `table_context` / `document_default` / "
                        "`assumed`. Giá trị `assumed` nghĩa là **không có bằng chứng đơn vị**.",
        "confidence": "`high` — kỳ đọc từ nhãn cột, đơn vị có bằng chứng, nhãn dòng riêng biệt. "
                      "`medium` — có suy diễn ở một trong ba. `low` — thiếu kỳ, hoặc đơn vị "
                      "mặc định, hoặc cột chưa phân loại. Tầng truy hồi nên hạ trọng số `low`.",
        "quality_flags_json": "Mảng JSON các cờ: `period_from_table`, `period_unresolved`, "
                              "`unit_scale_assumed_no_evidence` (tên cũ `unit_assumed`), "
                              "`generic_row_label`, `column_role_unknown`, "
                              "`table_not_classified_as_data`.",
    },
}
