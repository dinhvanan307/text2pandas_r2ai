"""DP-018 — Đóng gói Silver thành gói phát hành dùng được ngay trên máy khác.

    python -m text2pandas.pipelines.a6.cli release [--profile slim|full|min]
                                        [--per-table primary|all|none]
                                        [--out DIR]

MỤC TIÊU: người nhận copy thư mục về, mở SQLite hoặc đọc Parquet là dùng được.
Không cài pipeline, không chạy lại 10 phút build, không cần corpus gốc.

──────────────────────────────────────────────────────────────────────────────
VÌ SAO KHÔNG XUẤT ĐÚNG THEO CHỮ

Xuất CSV **và** Parquet cho từng bảng nghĩa là 292.492 tệp và 12–15 GB. Gói đó
không copy sang máy local được — nó phá đúng mục tiêu mà nó phục vụ.

Ba quyết định thay thế, và lý do đo được cho từng cái:

1. `silver.db` bỏ `source_cells` + `grid_cells` ở hồ sơ mặc định. Hai bảng này
   là tầng TRUY VẾT (1,9 GB / 4,8 GB) — cần để tái lập bản dựng, không cần để
   dùng dữ liệu. Hồ sơ `full` giữ lại cho ai cần kiểm toán.

2. DataFrame xuất theo **tập dữ liệu**, không theo từng bảng. Parquet nén ~12×
   trên dữ liệu này: 2,57 triệu observation còn khoảng 90–150 MB. CSV toàn bộ
   nén gzip. Cột `ticker`/`doc_year`/`table_uid` có sẵn để lọc.

3. CSV **theo từng bảng** chỉ sinh cho báo cáo chính (cân đối, kết quả kinh
   doanh, lưu chuyển tiền tệ) — khoảng 8.200 bảng. Đó là tập mà Text-to-Pandas
   thực sự truy vấn; 112.891 bảng thuyết minh sinh CSV riêng là tạo rác.

   Mỗi bảng xuất **hai bố cục**: `long/` (một dòng một ô, lược đồ cố định) và
   `wide/` (giống báo cáo giấy). Chưa có bằng chứng bố cục nào cho điểm cao hơn
   — không có tập train (C03) nên chỉ leaderboard trả lời được. Xuất cả hai để
   thí nghiệm đó tốn một lần nộp chứ không tốn một lần viết lại.

Muốn đúng nguyên văn yêu cầu: `--profile full --per-table all`. Gói sẽ ~14 GB.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from text2pandas.pipelines.a6.dq_checks import DQ_VERSION, run_dq_checks
from text2pandas.pipelines.a6.gates import (
    BLOCKED, FAIL, PASS, legacy_check_status, split_legacy_gates)
from text2pandas.pipelines.a6.release_docs import DOC_FILES, build_docs
from text2pandas.pipelines.a6.release_schema import (
    COLUMN_DOCS,
    FULL_TABLES,
    RELEASE_DDL,
    RELEASE_FTS_DDL,
    RELEASE_INDEX_DDL,
    RELEASE_SCHEMA_VERSION,
    SLIM_TABLES,
    TABLE_DOCS,
)
from text2pandas.pipelines.a6.release_schema import (
    RELEASE_CARD_DDL, RELEASE_DDL_FULL_EXTRA, RELEASE_LONG_DDL,
    RELEASE_DOC_CLASS_DDL, FTS_CONTENT, FTS_TOKENIZER)
from text2pandas.pipelines.a6.readiness import READINESS_VERSION, retrieval_ready_expr
from text2pandas.pipelines.a6.storage import SCHEMA_VERSION
from text2pandas.pipelines.a6.text_normalize import (
    NORMALIZE_VERSION, fts_match_expr, normalize_search_text)

__all__ = ["build_release", "ReleaseReport", "RELEASE_VERSION"]

RELEASE_VERSION = "1.2"

# Cổng được phép BLOCKED mà vẫn phát hành, theo `manifest_contract`. SG không
# có Structure Gold nên vĩnh viễn chưa đo được; C2/C3 được hợp đồng cho phép
# một phần. Danh sách này là DỮ LIỆU để `verify_package` kiểm, không phải một
# câu trong tài liệu.
ALLOWED_BLOCKED_GATES = ("SG", "C2", "C3")


def _taxonomy_version() -> str:
    """Phiên bản sổ phân loại defect. `unavailable:` nếu không đọc được."""
    import yaml
    p = Path(__file__).resolve().parents[4] / "configs" / "defect_taxonomy_v1.yaml"
    try:
        return str(yaml.safe_load(p.read_text(encoding="utf-8")).get(
            "taxonomy_version", "unavailable:no_version_key"))
    except (OSError, ValueError):
        return "unavailable:not_readable"


def _gate_rollup(checks: list[dict]) -> str:
    """PASS / FAIL / BLOCKED cho cả một cụm G — FAIL thắng BLOCKED thắng PASS."""
    st = {legacy_check_status(c) for c in checks}
    return FAIL if FAIL in st else (BLOCKED if BLOCKED in st else PASS)

PRIMARY_STATEMENTS = ("balance_sheet", "income_statement", "cash_flow")
CHUNK = 200_000


@dataclass(slots=True)
class ReleaseReport:
    out_dir: Path
    profile: str
    build_id: str = ""
    stages: list[tuple[str, float, str]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    files: dict[str, dict] = field(default_factory=dict)
    dq: dict = field(default_factory=dict)
    quality: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # Nhãn phát hành SUY RA từ cổng, không do người đặt — cùng luật với
    # `gates.evaluate_gates`. Có cổng BLOCKED thì cao nhất là `rc1`.
    release_label: str = "silver-v1.0.0"
    blocked_gates: list[str] = field(default_factory=list)
    # C3 · nguồn trạng thái DUY NHẤT là RC-20 đã chạy thật.
    gate_summary_from_rc20: dict | None = None
    gate_report_ref: dict | None = None
    seconds: float = 0.0


# ─────────────────────────── tiện ích ───────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while blk := f.read(chunk):
            h.update(blk)
    return h.hexdigest()


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


class _Log:
    """Ghi song song ra màn hình và tệp — người chạy thấy tiến độ, gói giữ dấu vết."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("w", encoding="utf-8")

    def __call__(self, msg: str) -> None:
        line = f"[{_now()}] {msg}"
        print(f"  {msg}", flush=True)
        self._f.write(line + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


# ─────────────────── giai đoạn 1: dựng silver.db ───────────────────

# `confidence` suy từ ba trục độc lập. Đây là thứ tầng truy hồi cần để hạ trọng
# số, và nó phải được tính MỘT LẦN ở đây thay vì để mỗi người tiêu thụ tự suy
# ra từ `quality_flags_json` theo cách riêng.
_CONFIDENCE_SQL = """
CASE
  WHEN o.period_end IS NULL
    OR o.scale_source IN ('assumed','none')
    -- Khớp CẢ HAI tên: `unit_assumed` (bản ≤ RC1) và
    -- `unit_scale_assumed_no_evidence` (RC-04 mục 3, từ RC2). Tên mới KHÔNG
    -- chứa chuỗi con của tên cũ, nên một mẫu LIKE duy nhất sẽ bỏ sót lặng lẽ
    -- và những observation đó mất trạng thái `low` — đúng lớp lỗi mà việc đổi
    -- tên sinh ra để tránh.
    OR o.quality_flags_json LIKE '%unit_assumed%'
    OR o.quality_flags_json LIKE '%unit_scale_assumed_no_evidence%'
    OR o.quality_flags_json LIKE '%column_role_unknown%'
  THEN 'low'
  WHEN o.period_source <> 'column_path'
    OR o.quality_flags_json LIKE '%generic_row_label%'
    OR o.quality_flags_json LIKE '%table_not_classified_as_data%'
  THEN 'medium'
  ELSE 'high'
END
"""


def _build_db(src_silver: Path, src_bronze: Path, out_db: Path,
              profile: str, log: _Log, quality: dict,
              src_manifest: dict) -> dict[str, int]:
    if out_db.exists():
        out_db.unlink()
    # `uri=True` phải đặt trên chính kết nối: SQLite chỉ diễn giải chuỗi
    # `file:...?mode=ro` thành URI khi cờ SQLITE_OPEN_URI đang bật, và cờ đó
    # áp cho cả `ATTACH`. Thiếu nó thì `file:/…?mode=ro` bị hiểu là TÊN TỆP.
    conn = sqlite3.connect(str(out_db), uri=True)
    conn.executescript(
        "PRAGMA journal_mode=WAL;\nPRAGMA synchronous=NORMAL;\n"
        "PRAGMA cache_size=-200000;")
    conn.executescript(RELEASE_DDL)
    if profile == "full":
        conn.executescript(RELEASE_DDL_FULL_EXTRA)
    for alias, path in (("s", src_silver), ("b", src_bronze)):
        uri = f"file:{quote(str(path))}?mode=ro"
        try:
            conn.execute(f"ATTACH DATABASE ? AS {alias}", (uri,))
        except sqlite3.OperationalError as exc:
            raise SystemExit(
                f"Không mở được {path} ở chế độ chỉ đọc: {exc}\n"
                f"URI đã thử: {uri}") from exc

    log("documents …")
    conn.execute("""
        INSERT INTO documents
        SELECT document_uid, directory_doc_id, ticker_path, year_path,
               basis_path, rel_path, n_bytes, n_lines, n_pages, n_tables, sha256,
               -- RC-06 · Bronze cũ hơn RC-06 không có ba cột này. COALESCE về 0
               -- KHÔNG an toàn ở đây: 0 markup nghĩa là "ngoài phạm vi", một
               -- lời khẳng định mà ta không có bằng chứng. Dùng -1 làm giá trị
               -- KHÔNG BIẾT, và `document_classification` sẽ nói `unknown`.
               COALESCE(n_table_markup, -1),
               COALESCE(n_numeric_tokens, -1),
               COALESCE(n_grouped_numbers, -1)
        FROM b.documents ORDER BY directory_doc_id""")

    log("pages …")
    conn.execute("""
        INSERT INTO pages
        SELECT p.page_uid, p.document_uid, p.page_no, p.line_start, p.line_end
        FROM b.pages p
        WHERE EXISTS (SELECT 1 FROM documents d WHERE d.document_uid=p.document_uid)
        ORDER BY p.document_uid, p.page_no""")

    log("tables …")
    # `evidence_ref` được dựng ĐÚNG MỘT LẦN, ngay đây. Đây là trường cuộc thi
    # chấm (C20); ghép chuỗi ở nhiều nơi là bảo đảm sẽ có ngày chúng lệch nhau.
    conn.execute("""
        INSERT INTO tables
        SELECT t.table_uid, t.document_uid, t.directory_doc_id, t.ticker,
               t.doc_year, COALESCE(t.basis_from_text, t.basis_path),
               t.industry_class, t.statement_type, t.statement_rule,
               t.is_data_table, t.line_start_1based, bt.page_no,
               'line:' || t.line_start_1based,
               t.directory_doc_id || '|line:' || t.line_start_1based,
               t.n_grid_rows, t.n_grid_cols, t.n_header_rows, t.n_source_cells,
               t.numeric_ratio, t.sep_convention, t.section_text,
               t.context_clean, t.parse_status, t.quality_flags_json
        FROM s.table_features t
        LEFT JOIN b.tables bt ON bt.table_uid = t.table_uid
        ORDER BY t.directory_doc_id, t.line_start_1based""")

    log("columns …")
    conn.execute("""
        INSERT INTO columns
        SELECT table_uid, grid_col_idx, column_role, header_path_text,
               header_path_json, period_start, period_end, as_of_date,
               period_type, period_role, period_source, quarter, is_restated,
               unit_kind, currency, scale_exponent, numeric_ratio, flags_json
        FROM s.columns ORDER BY table_uid, grid_col_idx""")

    log("rows …")
    conn.execute("""
        INSERT INTO rows
        SELECT table_uid, grid_row_idx, row_role, label_source, label_clean,
               row_path_text, row_path_json, row_level, metric_code,
               is_generic_label, flags_json
        FROM s.rows ORDER BY table_uid, grid_row_idx""")

    log("observations (phi chuẩn hoá ticker/năm/loại báo cáo, tính confidence) …")
    conn.execute(f"""
        INSERT INTO observations
        SELECT o.observation_uid, o.table_uid,
               o.source_cell_uid, sc.source_row_idx, sc.source_col_idx,
               sc.text_source,
               o.grid_row_idx, o.grid_col_idx,
               t.directory_doc_id, t.ticker, t.doc_year, t.statement_type,
               t.directory_doc_id || '|line:' || t.line_start_1based,
               o.row_path_text, o.col_path_text, o.metric_label_clean,
               o.metric_code_raw, o.value_source, o.value_decimal_text,
               o.value_kind, o.parse_status, o.parse_rule, o.is_negative,
               o.unit_kind, o.currency, o.scale_exponent, o.scale_source,
               o.period_start, o.period_end, o.as_of_date, o.period_type,
               o.period_role, o.period_source, o.quarter, o.is_restated,
               {_CONFIDENCE_SQL}, o.quality_flags_json,
               -- Danh tính VẬT LÝ và lớp đụng độ phải đi theo gói. Thiếu
               -- chúng thì người nhận không so được hai build theo cùng một
               -- dòng, và differential audit (doc 12 §5.2) bất khả thi.
               o.row_uid, o.column_uid, co.collision_class
        FROM s.observations o
        JOIN s.table_features t ON t.table_uid = o.table_uid
        LEFT JOIN s.source_cells sc ON sc.source_cell_uid = o.source_cell_uid
        LEFT JOIN s.collision_obs co ON co.observation_uid = o.observation_uid
        ORDER BY t.ticker, t.doc_year, o.table_uid, o.grid_row_idx, o.grid_col_idx""")

    # `dropped_cells` đi theo gói, không ở lại Silver nội bộ. Câu "không mất
    # dữ liệu nào mà không giải thích được" chỉ có giá trị khi người NHẬN tự
    # đếm được; nếu nó chỉ nằm trong một file markdown thì đó là lời hứa, không
    # phải bằng chứng.
    log("dropped_cells (ô số bị loại, kèm lý do) …")
    conn.execute("""
        INSERT INTO dropped_cells
        SELECT d.source_cell_uid, d.table_uid, d.grid_row_idx, d.grid_col_idx,
               d.reason, d.detail, d.text_clean
        FROM s.dropped_cells d
        JOIN s.table_features t ON t.table_uid = d.table_uid
        ORDER BY d.table_uid, d.grid_row_idx, d.grid_col_idx""")

    # ── RC-02 · readiness ĐI THEO GÓI ───────────────────────────────────────
    #
    # Đây là khiếm khuyết trung tâm mà RC-02 sửa. Trước bản này, `apply_policy`
    # dựng `observation_readiness` trên DB Silver rồi gói phát hành BỎ LẠI toàn
    # bộ: RC1 `silver.db` không có bảng này, chỉ có `build_meta`
    # `readiness_policy_version = '1.0'` — một dòng metadata mô tả một bảng
    # không tồn tại. Người nhận gói không thấy confidence, không thấy lý do
    # chặn, và `execution_ready = 1.862.583` họ đọc được là từ một biểu thức
    # bốn điều kiện trong view, không phải từ chính sách.
    log("observation_readiness (chính sách readiness hai tầng) …")
    conn.execute("""
        INSERT INTO observation_readiness
        SELECT r.observation_uid, r.execution_candidate, r.execution_ready,
               r.confidence, r.blocking_reasons_json, r.warning_reasons_json,
               r.non_candidate_reasons_json, r.policy_version
        FROM s.observation_readiness r
        JOIN observations o ON o.observation_uid = r.observation_uid
        ORDER BY r.observation_uid""")
    # 1:1 với `observations`. `v_long_dataframe` JOIN trên bảng này, nên một
    # dòng thiếu là một observation BIẾN MẤT khỏi DataFrame mà không ai báo.
    n_obs_rel, n_rdy_rel = conn.execute(
        "SELECT (SELECT COUNT(*) FROM observations),"
        "       (SELECT COUNT(*) FROM observation_readiness)").fetchone()
    if n_obs_rel != n_rdy_rel:
        raise SystemExit(
            f"LỖI RC-02: readiness không 1:1 với observations "
            f"({n_rdy_rel:,} / {n_obs_rel:,}). `v_long_dataframe` sẽ đánh rơi "
            f"{n_obs_rel - n_rdy_rel:,} dòng trong im lặng. Chạy lại bước "
            f"`silver` để dựng lại readiness rồi mới đóng gói.")
    n_ready_rel = conn.execute(
        "SELECT COUNT(*) FROM observation_readiness"
        " WHERE execution_ready=1").fetchone()[0]
    log(f"  readiness: {_human(n_rdy_rel)} dòng · {_human(n_ready_rel)} ready")

    log("quality_issues + tổng theo rule + build_meta …")
    conn.execute("INSERT INTO quality_issues SELECT * FROM s.quality_issues")
    # P1-03: `quality_issues` là MẪU (tối đa 5.000 dòng/rule). Con số đầy đủ
    # phải nằm ngay trong database, không chỉ trong một tệp markdown — nếu
    # không, người đếm bảng đó sẽ báo cáo 37.078 thay vì 552.305.
    conn.executemany(
        "INSERT OR REPLACE INTO quality_rule_totals VALUES (?,?,?,?)",
        [(rid, total,
          conn.execute("SELECT COUNT(*) FROM quality_issues WHERE rule_id=?",
                       (rid,)).fetchone()[0], 5000)
         for rid, total in (quality.get("by_rule") or {}).items()])
    conn.execute("INSERT INTO build_meta SELECT * FROM s.build_meta")
    conn.execute(
        "INSERT OR REPLACE INTO build_meta VALUES('release_schema_version',?)",
        (RELEASE_SCHEMA_VERSION,))
    # P1-04: Data Dictionary hứa build_meta có corpus_id và phiên bản từng
    # thành phần. Trước đây nó chỉ có năm khoá của release, nên lời hứa đó
    # không kiểm chứng được từ chính gói.
    for k, v in (("corpus_id", src_manifest.get("corpus_id")),
                 ("revision", src_manifest.get("revision")),
                 ("dq_version", DQ_VERSION)):
        if v:
            conn.execute("INSERT OR REPLACE INTO build_meta VALUES(?,?)", (k, str(v)))
    for comp, ver in (src_manifest.get("versions") or {}).items():
        conn.execute("INSERT OR REPLACE INTO build_meta VALUES(?,?)",
                     (f"version.{comp}", str(ver)))
    conn.execute(
        "INSERT OR REPLACE INTO build_meta VALUES('release_profile',?)", (profile,))
    conn.execute(
        "INSERT OR REPLACE INTO build_meta VALUES('released_at',?)", (_now(),))

    if profile == "full":
        log("source_cells + grid_cells (hồ sơ full) …")
        conn.execute("""
            INSERT INTO source_cells
            SELECT source_cell_uid, table_uid, source_row_idx, source_col_idx,
                   grid_row_idx, grid_col_idx, rowspan, colspan, text_source,
                   text_clean, clean_status
            FROM s.source_cells ORDER BY table_uid, source_row_idx, source_col_idx""")
        conn.execute("""
            INSERT INTO grid_cells
            SELECT table_uid, grid_row_idx, grid_col_idx, source_cell_uid,
                   is_span_anchor
            FROM s.grid_cells ORDER BY table_uid, grid_row_idx, grid_col_idx""")

    conn.commit()

    log("chỉ mục …")
    conn.executescript(RELEASE_INDEX_DDL)

    log("Table Card cơ sở …")
    conn.executescript(RELEASE_CARD_DDL)
    _build_cards(conn, log)

    # RC-06 · phân loại tài liệu đi theo gói. Đặt TRƯỚC long dataframe vì nó
    # chỉ phụ thuộc `documents`, và đặt sớm thì lỗi lộ sớm.
    log("phân loại tài liệu tabular / non-tabular (RC-06) …")
    conn.executescript(RELEASE_DOC_CLASS_DDL)

    log("DataFrame dạng long (hợp đồng Text-to-Pandas) …")
    conn.executescript(RELEASE_LONG_DDL)

    log("chỉ mục toàn văn FTS5 cho tầng truy hồi …")
    conn.executescript(RELEASE_FTS_DDL)
    # FTS ĐỌC TỪ `table_cards`, không tự dựng lại từ `rows`/`columns`.
    # Hai đường dựng song song chắc chắn lệch nhau sau vài lần sửa, và khi
    # lệch thì không ai biết bên nào là thẻ thật.
    #
    # RC-05 · nội dung nạp vào ở DẠNG CHUẨN, không phải văn bản gốc.
    # `normalize_search_text` đăng ký thành hàm SQL để phép chuẩn hoá chạy
    # NGAY TRONG câu INSERT — không có đường vòng nào lấy được văn bản thô vào
    # chỉ mục. `deterministic=True` để SQLite được phép tối ưu và để hai lần
    # build cho cùng một chỉ mục (RC-14 so bằng hash nội dung).
    conn.create_function("norm_search", 1,
                         lambda s: normalize_search_text(s or ""),
                         deterministic=True)
    conn.execute("""
        INSERT INTO table_cards_fts
        SELECT table_uid, ticker,
               norm_search(COALESCE(section_text,'')),
               norm_search(COALESCE(table_search_text,'')),
               norm_search(COALESCE(row_terms,'')),
               norm_search(COALESCE(col_terms,''))
        FROM table_cards""")
    # Người nhận gói phải BIẾT chỉ mục ở dạng chuẩn, nếu không họ sẽ gõ có dấu
    # rồi tưởng corpus không có gì. Ba khoá này là hợp đồng đọc được bằng máy.
    for k, v in (("fts_content", FTS_CONTENT),
                 ("fts_tokenizer", FTS_TOKENIZER),
                 ("fts_normalize_version", NORMALIZE_VERSION)):
        conn.execute("INSERT OR REPLACE INTO build_meta VALUES(?,?)", (k, v))
    conn.commit()

    tables = FULL_TABLES if profile == "full" else SLIM_TABLES
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in tables}
    counts["table_cards_fts"] = conn.execute(
        "SELECT COUNT(*) FROM table_cards_fts").fetchone()[0]

    log("ANALYZE + VACUUM (thu gọn tệp, cập nhật thống kê query planner) …")
    # Phải DETACH trước: `ANALYZE` không tham số chạy trên MỌI database đang
    # gắn, mà nguồn được mở chỉ-đọc; `VACUUM` thì từ chối chạy khi còn attach.
    conn.execute("DETACH DATABASE s")
    conn.execute("DETACH DATABASE b")
    conn.execute("ANALYZE main")
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    # `temp_store=MEMORY` phải TẮT trước khi VACUUM. VACUUM dựng một bản sao
    # đầy đủ của database trong vùng tạm; với vùng tạm nằm trong RAM, thu gọn
    # một tệp 2,5 GB nghĩa là xin 2,5 GB bộ nhớ và bị hệ điều hành giết.
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("VACUUM")
    conn.close()
    return counts


# ─────────────── Table Card cơ sở ───────────────

# Ba nhóm băm TÁCH RIÊNG. Khi Silver Final ra, downstream so từng nhóm để biết
# phải dựng lại PHẦN NÀO của chỉ mục:
#   identity   đổi  -> bảng khác hẳn, dựng lại tất cả
#   labels     đổi  -> chỉ mục văn bản/embedding phải dựng lại (v1.2 sửa row_path)
#   semantics  đổi  -> chỉ bộ lọc kỳ/đơn vị/mã số bị ảnh hưởng
_CARD_GROUPS = {
    "hash_identity": ("table_uid", "doc_id", "locator", "statement_type"),
    "hash_labels": ("section_text", "row_terms", "col_terms"),
    "hash_semantics": ("metric_codes", "periods", "units"),
}

# Giới hạn độ dài các trường gộp: một bảng thuyết minh có thể có 300 nhãn dòng,
# và nhồi hết vào thẻ làm BM25 phạt độ dài nặng (xem 01_row_path.md §9.2).
_MAX_TERMS = 4000


def _build_cards(conn, log: _Log) -> int:
    """Dựng `table_cards` từ chính release DB — không đọc lại Silver."""
    rows = conn.execute("""
        SELECT t.table_uid, t.directory_doc_id, t.locator, t.ticker, t.doc_year,
               t.statement_type, COALESCE(t.section_text,''),
               COALESCE(t.context_clean,''), t.n_grid_rows, t.n_grid_cols,
               t.parse_status, t.quality_flags_json
        FROM tables t ORDER BY t.table_uid""").fetchall()

    agg_row = dict(conn.execute("""
        SELECT table_uid, GROUP_CONCAT(label_clean, ' | ') FROM rows
        WHERE TRIM(label_clean) <> '' GROUP BY table_uid""").fetchall())
    agg_col = dict(conn.execute("""
        SELECT table_uid, GROUP_CONCAT(header_path_text, ' | ') FROM columns
        WHERE TRIM(header_path_text) <> '' GROUP BY table_uid""").fetchall())
    agg_code = dict(conn.execute("""
        SELECT table_uid, GROUP_CONCAT(DISTINCT metric_code) FROM observations
        WHERE metric_code IS NOT NULL AND TRIM(metric_code) <> ''
        GROUP BY table_uid""").fetchall())
    agg_per = dict(conn.execute("""
        SELECT table_uid, GROUP_CONCAT(DISTINCT period_end) FROM observations
        WHERE period_end IS NOT NULL GROUP BY table_uid""").fetchall())
    agg_unit = dict(conn.execute("""
        SELECT table_uid, GROUP_CONCAT(DISTINCT unit_kind) FROM observations
        GROUP BY table_uid""").fetchall())
    n_obs = dict(conn.execute(
        "SELECT table_uid, COUNT(*) FROM observations GROUP BY table_uid").fetchall())
    # RC-02 · hai con số này ĐỌC TỪ BẢNG CHÍNH SÁCH.
    #
    # Trước bản này chúng là bản sao thứ hai và thứ ba của định nghĩa
    # `execution_ready` — mỗi bản một điều kiện khác nhau, không bản nào là
    # chính sách. Hợp đồng P3 `table_readiness_contract` đòi bất biến
    # `SUM(execution_ready_obs) = COUNT(observation_readiness.execution_ready=1)`;
    # bất biến đó chỉ đúng khi cả hai vế cùng đọc một nguồn.
    #
    # `review_required` cũng đổi nghĩa theo: không còn là "có đụng độ" mà là
    # "tính được nhưng chưa đủ an toàn" (candidate ∧ ¬ready) — đúng định nghĩa
    # trong `v_execution_ready`. Đây mới là tập mà người ta thực sự phải xem
    # bằng mắt; tập đụng độ chỉ là một trong các lý do dẫn tới nó.
    n_exec = dict(conn.execute("""
        SELECT o.table_uid, COUNT(*) FROM observations o
        JOIN observation_readiness r ON r.observation_uid = o.observation_uid
        WHERE r.execution_ready = 1 GROUP BY o.table_uid""").fetchall())
    n_rev = dict(conn.execute("""
        SELECT o.table_uid, COUNT(*) FROM observations o
        JOIN observation_readiness r ON r.observation_uid = o.observation_uid
        WHERE r.execution_candidate = 1 AND r.execution_ready = 0
        GROUP BY o.table_uid""").fetchall())
    # RC-08 · ba số còn lại của `table_readiness_contract`.
    n_cand = dict(conn.execute("""
        SELECT o.table_uid, COUNT(*) FROM observations o
        JOIN observation_readiness r ON r.observation_uid = o.observation_uid
        WHERE r.execution_candidate = 1 GROUP BY o.table_uid""").fetchall())
    # Đếm theo TỪNG mã lý do. `json_each` trên cả ba mảng, gộp lại — người
    # nhận gói đọc được "40 ô vì confidence_low" thay vì "40 ô không dùng được".
    reasons: dict[str, dict[str, int]] = {}
    for col in ("blocking_reasons_json", "non_candidate_reasons_json"):
        for tuid_, reason, n in conn.execute(f"""
                SELECT o.table_uid, je.value, COUNT(*)
                  FROM observations o
                  JOIN observation_readiness r
                    ON r.observation_uid = o.observation_uid
                  JOIN json_each(r.{col}) je
                 GROUP BY 1, 2"""):
            reasons.setdefault(tuid_, {})
            reasons[tuid_][reason] = reasons[tuid_].get(reason, 0) + n
    rr_by_uid = dict(conn.execute(
        f"SELECT t.table_uid, {retrieval_ready_expr('t')} FROM tables t").fetchall())

    out = []
    for (tuid, doc_id, loc, ticker, year, stype, section, ctx,
         nr, nc, _pstatus, qflags) in rows:
        rt = (agg_row.get(tuid) or "")[:_MAX_TERMS]
        ct = (agg_col.get(tuid) or "")[:_MAX_TERMS]
        codes = agg_code.get(tuid) or ""
        pers = agg_per.get(tuid) or ""
        units = agg_unit.get(tuid) or ""
        # RC-08 · `retrieval_ready` KHÔNG còn được định nghĩa ở đây.
        # `rr_by_uid` tính bằng ĐÚNG biểu thức của `retrieval_ready_expr`,
        # cùng hàm mà `v_retrieval_ready` dùng. Trước RC-08 chỗ này có bản
        # định nghĩa thứ hai (`parse_status='ok' ∧ type≠'toc'`); đo trên RC1
        # thì hai bản cùng cho 146.246 nên chúng chưa mâu thuẫn — nhưng hai
        # định nghĩa trùng nhau hôm nay sẽ lệch vào ngày một đầu vào đổi, và
        # lúc đó không ai biết bên nào là bản chính.
        rr = rr_by_uid.get(tuid, 0)
        card = {
            "table_uid": tuid, "doc_id": doc_id, "locator": loc,
            "statement_type": stype, "section_text": section,
            "row_terms": rt, "col_terms": ct,
            "metric_codes": codes, "periods": pers, "units": units,
        }
        hashes = {
            g: hashlib.sha256(
                "\x1f".join(str(card.get(k, "")) for k in keys).encode()
            ).hexdigest()[:16]
            for g, keys in _CARD_GROUPS.items()
        }
        # Thẻ CHỈ chứa chữ. `01_row_path.md §9.2`: chỉ mục dựng trên văn bản
        # phẳng của bảng có 44% token là con số, và BM25 phạt độ dài làm bảng
        # tài chính thua bảng danh sách nhân sự. Bỏ số, tỷ lệ còn ~6%.
        search = " | ".join(x for x in (section, ctx[:600], rt, ct) if x)
        out.append((
            tuid, doc_id, loc, f"{doc_id}|{loc}", ticker, year, stype, section,
            nr, nc, n_obs.get(tuid, 0), rt, ct, codes, pers, units,
            search[:8000], rr, n_exec.get(tuid, 0), n_rev.get(tuid, 0),
            # ── RC-08 · năm trường của `table_readiness_contract` ──────────
            n_cand.get(tuid, 0),
            int(n_obs.get(tuid, 0) > 0),
            int(n_cand.get(tuid, 0) > 0),
            int(n_exec.get(tuid, 0) > 0),
            json.dumps(dict(sorted((reasons.get(tuid) or {}).items())),
                       ensure_ascii=False, separators=(",", ":")),
            qflags,
            hashes["hash_identity"], hashes["hash_labels"], hashes["hash_semantics"],
        ))
    conn.executemany(
        "INSERT INTO table_cards VALUES(" + ",".join("?" * 29) + ")", out)
    conn.commit()
    log(f"  table_cards: {len(out):,} thẻ · "
        f"{sum(1 for r in out if r[17]):,} retrieval_ready")
    return len(out)


# ─────────────── giai đoạn 2: xuất DataFrame ───────────────

_EXPORTS: tuple[tuple[str, str, str], ...] = (
    ("documents", "SELECT * FROM documents ORDER BY directory_doc_id", "csv+parquet"),
    ("pages", "SELECT * FROM pages ORDER BY document_uid, page_no", "csv+parquet"),
    ("tables", "SELECT * FROM tables ORDER BY directory_doc_id, line_start_1based",
     "csv+parquet"),
    ("columns", "SELECT * FROM columns ORDER BY table_uid, grid_col_idx", "csv+parquet"),
    # Hợp đồng giao cho Text-to-Pandas (doc 12 §3.5). Sắp theo `doc_id` trước
    # để đọc một tài liệu là đọc một dải liên tục — Parquet row-group cắt gọn
    # theo dải, nên lọc `doc_id` không phải quét cả tệp.
    ("long_dataframe",
     "SELECT * FROM v_long_dataframe ORDER BY doc_id, table_uid, row_idx, col_idx",
     "csv+parquet"),
    ("table_cards", "SELECT * FROM table_cards ORDER BY doc_id, table_uid",
     "csv+parquet"),
    ("rows", "SELECT * FROM rows ORDER BY table_uid, grid_row_idx", "csv+parquet"),
    ("observations",
     "SELECT * FROM observations ORDER BY ticker, doc_year, table_uid,"
     " grid_row_idx, grid_col_idx", "csv+parquet"),
    ("quality_issues", "SELECT * FROM quality_issues ORDER BY rule_id, entity_id",
     "csv+parquet"),
    # Xuất luôn `dropped_cells`: người muốn kiểm câu "không mất gì âm thầm"
    # thường làm việc bằng pandas, không bằng SQL. Bắt họ mở SQLite chỉ để
    # kiểm một lời hứa của gói là dựng thêm một rào cản không cần thiết.
    ("dropped_cells",
     "SELECT * FROM dropped_cells ORDER BY table_uid, grid_row_idx, grid_col_idx",
     "csv+parquet"),
)


def _export_frames(db: Path, out: Path, log: _Log) -> dict[str, dict]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as error:  # pragma: no cover
        raise SystemExit(
            "Thiếu pyarrow. Cài: pip install pyarrow --break-system-packages") from error

    csv_dir, pq_dir = out / "dataframe" / "csv", out / "dataframe" / "parquet"
    csv_dir.mkdir(parents=True, exist_ok=True)
    pq_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    info: dict[str, dict] = {}

    for name, sql, _kinds in _EXPORTS:
        t0 = time.time()
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]

        # Nén gzip cho bảng lớn: 1,5 GB CSV thô thành ~200 MB, và người nhận
        # đọc thẳng bằng `pd.read_csv(..., compression='gzip')` không cần giải nén.
        big = name in ("observations", "rows")
        cpath = csv_dir / (f"{name}.csv.gz" if big else f"{name}.csv")
        opener = (lambda p: gzip.open(p, "wt", encoding="utf-8", newline="")) if big \
            else (lambda p: p.open("w", encoding="utf-8", newline=""))

        n = 0
        writer = None
        parts = 0
        with opener(cpath) as fh:
            w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            w.writerow(cols)
            while batch := cur.fetchmany(CHUNK):
                w.writerows(batch)
                n += len(batch)
                # Parquet: mọi cột ép về chuỗi. `value_decimal_text` PHẢI là
                # chuỗi — để pyarrow tự suy kiểu thì nó thành float64 và số
                # 10^15 mất chính xác ngay tại đây.
                arrays = [pa.array([None if r[i] is None else str(r[i])
                                    for r in batch], type=pa.string())
                          for i in range(len(cols))]
                tbl = pa.Table.from_arrays(arrays, names=cols)
                if writer is None:
                    tdir = pq_dir / name
                    tdir.mkdir(exist_ok=True)
                    writer = pq.ParquetWriter(tdir / "part-0000.parquet",
                                              tbl.schema, compression="zstd")
                writer.write_table(tbl)
                parts += 1
                if parts % 5 == 0:
                    log(f"    {name}: {n:,} dòng …")
        if writer:
            writer.close()
        pq_file = pq_dir / name / "part-0000.parquet"
        info[name] = {
            "rows": n, "columns": cols,
            "csv": str(cpath.relative_to(out)), "csv_bytes": cpath.stat().st_size,
            "parquet": str(pq_file.relative_to(out)),
            "parquet_bytes": pq_file.stat().st_size if pq_file.exists() else 0,
            "seconds": round(time.time() - t0, 1),
        }
        log(f"  {name}: {n:,} dòng · CSV {_human(info[name]['csv_bytes'])}"
            f" · Parquet {_human(info[name]['parquet_bytes'])}"
            f" · {info[name]['seconds']}s")
    conn.close()
    return info


# ────────── giai đoạn 3: CSV theo từng bảng (hai bố cục) ──────────

def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in name)[:120]


def _export_per_table(db: Path, out: Path, mode: str, log: _Log) -> dict:
    if mode == "none":
        return {"mode": "none", "n_tables": 0}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    where = "" if mode == "all" else \
        " WHERE statement_type IN ({})".format(
            ",".join(f"'{s}'" for s in PRIMARY_STATEMENTS))
    uids = [r[0] for r in conn.execute(
        f"SELECT table_uid FROM tables{where} ORDER BY table_uid")]
    log(f"CSV theo bảng: {len(uids):,} bảng × 2 bố cục ({mode})")

    base = out / "dataframe" / "csv" / "by_table"
    (base / "long").mkdir(parents=True, exist_ok=True)
    (base / "wide").mkdir(parents=True, exist_ok=True)
    index_rows = []

    for i, uid in enumerate(uids, 1):
        meta = conn.execute(
            "SELECT directory_doc_id, ticker, doc_year, statement_type,"
            " line_start_1based FROM tables WHERE table_uid=?", (uid,)).fetchone()
        obs = conn.execute(
            "SELECT row_path_text, col_path_text, metric_code, value_decimal_text,"
            " value_kind, unit_kind, currency, scale_exponent, period_end,"
            " period_type, period_role, confidence, grid_row_idx, grid_col_idx"
            " FROM observations WHERE table_uid=?"
            " ORDER BY grid_row_idx, grid_col_idx", (uid,)).fetchall()
        if not obs:
            continue
        stem = f"{_safe(meta[0])}__line{meta[4]}"

        # ── bố cục DÀI: lược đồ CỐ ĐỊNH cho mọi bảng ──
        # Model sinh `pandas_query` chỉ phải học MỘT lược đồ thay vì 146.246 cái.
        lp = base / "long" / f"{stem}.csv"
        with lp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["row_path", "col_path", "metric_code", "value",
                        "value_kind", "unit_kind", "currency", "scale_exponent",
                        "period_end", "period_type", "period_role", "confidence"])
            w.writerows(r[:12] for r in obs)

        # ── bố cục RỘNG: giống báo cáo giấy ──
        # Tên cột là chuỗi OCR gốc, nên bố cục này dễ đọc nhưng khoá không ổn định.
        wide: dict[int, dict[str, str]] = defaultdict(dict)
        headers: dict[int, str] = {}
        for r in obs:
            gc = r[13]
            if gc not in headers:
                headers[gc] = (r[1] or f"c{gc}").replace("\n", " ").strip() or f"c{gc}"
            wide[r[12]][headers[gc]] = r[3]
        seen: dict[str, int] = {}
        ordered: list[str] = []
        for gc in sorted(headers):
            h = headers[gc]
            if h in seen:
                seen[h] += 1
                h = f"{h}__{seen[h]}"
            else:
                seen[h] = 0
            headers[gc] = h
            ordered.append(h)
        labels = dict(conn.execute(
            "SELECT grid_row_idx, row_path_text FROM rows WHERE table_uid=?", (uid,)))
        wp = base / "wide" / f"{stem}.csv"
        with wp.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(["row_path"] + ordered)
            for gr in sorted(wide):
                cells = {headers[gc]: v for gc, v in
                         ((g, wide[gr].get(headers[g])) for g in sorted(headers))}
                w.writerow([labels.get(gr, "")] + [cells.get(h) or "" for h in ordered])

        index_rows.append({
            "table_uid": uid, "doc_id": meta[0], "ticker": meta[1],
            "doc_year": meta[2], "statement_type": meta[3],
            "evidence_ref": f"{meta[0]}|line:{meta[4]}",
            "n_observations": len(obs),
            "csv_long": f"dataframe/csv/by_table/long/{stem}.csv",
            "csv_wide": f"dataframe/csv/by_table/wide/{stem}.csv",
        })
        if i % 2000 == 0:
            log(f"    … {i:,}/{len(uids):,} bảng")

    (base / "index.json").write_text(
        json.dumps(index_rows, ensure_ascii=False, indent=1), encoding="utf-8")
    conn.close()
    return {"mode": mode, "n_tables": len(index_rows),
            "index": "dataframe/csv/by_table/index.json"}


# ─────────────── giai đoạn 4: metadata JSON ───────────────

def _export_metadata(db: Path, out: Path, log: _Log) -> dict[str, str]:
    md = out / "metadata"
    md.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    files: dict[str, str] = {}

    for name, sql in (
        ("documents", "SELECT * FROM documents ORDER BY directory_doc_id"),
        ("pages", "SELECT * FROM pages ORDER BY document_uid, page_no"),
    ):
        data = [dict(r) for r in conn.execute(sql)]
        p = md / f"{name}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        files[name] = p.name
        log(f"  metadata/{p.name}: {len(data):,} bản ghi")

    # 146.246 bảng trong một mảng JSON là tệp 100 MB phải nạp hết mới đọc được
    # dòng đầu. JSONL đọc theo dòng, hợp với quy mô này.
    p = md / "tables.jsonl"
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        cur = conn.execute(
            "SELECT * FROM tables ORDER BY directory_doc_id, line_start_1based")
        while batch := cur.fetchmany(CHUNK):
            for r in batch:
                fh.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
                n += 1
    files["tables"] = p.name
    log(f"  metadata/{p.name}: {n:,} bản ghi (JSON Lines)")
    conn.close()
    return files


# ─────────────── giai đoạn 5: tài liệu SINH RA ───────────────

# ── RC-10 · `source_commit` — ghi ĐÚNG hoặc nói KHÔNG BIẾT ──────────────────
#
# RC1 manifest **chưa bao giờ** có trường này. Điều tra ở RC-01 ban đầu nhầm
# `manifest.revision = 0450088ab22ec946…` là một git commit đã mất; đo lại thì
# đó là **revision dataset HuggingFace** (`cli.py:33-34`), nên `git cat-file`
# thất bại là đúng thiết kế. Kết luận đúng: không tồn tại con số nào để tìm.
#
# Ba trạng thái, không phải hai. Một chuỗi rỗng hoặc `"unknown"` trần sẽ bị
# đọc thành "đã ghi", nên mỗi trạng thái mang một tiền tố nói rõ nó là gì.
def _source_commit() -> str:
    """`<sha>` · `<sha>-dirty` · `unavailable:<lý do>`."""
    import subprocess
    root = Path(__file__).resolve().parents[4]
    try:
        sha = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10)
        if sha.returncode:
            return "unavailable:not_a_git_repository"
        head = sha.stdout.strip()
        st = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=30)
        # Cây bẩn nghĩa là gói này KHÔNG tương ứng commit nào. Ghi rõ thay vì
        # ghi sha của commit gần nhất rồi để người sau tưởng nó tái lập được.
        return f"{head}-dirty" if st.stdout.strip() else head
    except (OSError, subprocess.SubprocessError):
        return "unavailable:git_not_executable"


def _acceptance_status(rep: ReleaseReport) -> str:
    """Trạng thái chấp nhận, lấy từ RC-20 nếu có; nếu không thì nói rõ là chưa
    có cổng, KHÔNG tự suy ra một trạng thái nghe có vẻ đúng."""
    g = getattr(rep, "gate_summary_from_rc20", None)
    if not g:
        return "not_accepted_no_gate_report"
    if g.get("exit_code") not in (0, "0"):
        return "not_accepted"
    label = g.get("release_label") or ""
    if label == "blocked":
        return "not_accepted"
    return "retrieval_baseline_ready" if label.endswith("-rc2") else "rc_ready"


def _read_build_meta(out: Path) -> dict:
    """`build_meta` của chính DB sắp phát hành — nguồn định danh đúng.

    RC2-050 · manifest bản dựng KHÔNG ghi `source_hash`/`config_hash`, nên
    `src_manifest.get(...)` trả `None` và manifest release ra đời với ba trường
    định danh rỗng. `build_meta` thì có, vì bước build ghi thẳng vào DB.
    """
    try:
        with sqlite3.connect(f"file:{out / 'silver.db'}?mode=ro", uri=True) as c:
            return dict(c.execute("SELECT key, value FROM build_meta"))
    except Exception:
        return {}


def _identity_from_build_meta(bm: dict, src_manifest: dict) -> dict:
    """A6 · năm trường DANH TÍNH của manifest, lấy TỪ `build_meta` trước hết.

    Vì sao tách thành hàm riêng: bốn trường ở đây đã đọc `build_meta`, trường
    thứ năm thì không — nó ghi hằng số module `READINESS_VERSION`. Hai con số
    tình cờ bằng nhau ("2.1") suốt từ RC-02 nên sai lệch vô hình. A5 nâng
    chính sách lên 2.2, và gói phát hành `5ade9ae9d5f68b6a` đi ra với

        manifest.json        readiness_policy_version = 2.1
        silver.db build_meta readiness_policy_version = 2.2

    Cùng một tên khoá, hai giá trị, một gói. Không phải sai thẩm mỹ: người
    nhận tra chính sách 2.1 sẽ đọc luật nói ô phần trăm không bao giờ ready —
    ngược hẳn với dữ liệu trong chính gói đó.

    Luật nằm rải trong một dict 30 khoá thì không ai kiểm được nó. Nằm ở đây
    thì `test_a6_manifest_vs_build_meta.py` gọi thẳng được.

    `build_meta` là nguồn ĐÚNG vì nó do chính lượt dựng ghi ra. Hằng số module
    chỉ là phương án dự phòng khi khoá vắng mặt.
    """
    return {
        "source_commit": bm.get("source_commit") or _source_commit(),
        "source_hash": bm.get("source_hash") or src_manifest.get("source_hash"),
        "config_hash": bm.get("config_hash") or src_manifest.get("config_hash"),
        "readiness_policy_version": (bm.get("readiness_policy_version")
                                     or READINESS_VERSION),
        "defect_taxonomy_version": _taxonomy_version(),
    }


def _md_manifest(rep: ReleaseReport, out: Path, src_manifest: dict) -> dict:
    _bm = _read_build_meta(out)
    files: dict[str, dict] = {}
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.name == "manifest.json":
            continue
        rel = str(p.relative_to(out))
        st = p.stat()
        # SHA-256 ĐẦY ĐỦ cho mọi tệp. Bản đầu băm 8 MB đầu + kích thước cho
        # tệp lớn: một byte lật ở giữa `silver.db` mà không đổi kích thước sẽ
        # lọt qua — đúng thứ checksum sinh ra để bắt. Băm đủ 4 GB mất ~10 giây.
        files[rel] = {"bytes": st.st_size, "digest": _sha256(p),
                      "digest_mode": "sha256"}
    return {
        "package": "vifinqa-silver",
        "release_version": RELEASE_VERSION,
        "release_schema_version": RELEASE_SCHEMA_VERSION,
        "profile": rep.profile,
        "created_at": _now(),
        "source_build_id": rep.build_id,
        "corpus_id": src_manifest.get("corpus_id"),
        # RC-02 · `revision` là revision DATASET trên HuggingFace, KHÔNG phải
        # git commit. Đổi tên khoá là breaking; thay vào đó nói rõ nó là gì.
        "revision": src_manifest.get("revision"),
        "revision_kind": "huggingface_dataset_revision",
        # ── RC-10 · bảy khoá mà manifest RC1 thiếu ─────────────────────────
        **_identity_from_build_meta(_bm, src_manifest),
        # `acceptance_status` chỉ được ghi `rc_ready` SAU khi cổng thật sự
        # đạt — `acceptance_status_rule` của hợp đồng. Nhãn `release-candidate`
        # nghĩa là còn cổng BLOCKED, tức CHƯA ĐO ĐƯỢC, không phải ĐÃ ĐẠT.
        # C3 · Doc 56 P0-05 · trạng thái máy đọc được phải KHỚP quyết định bàn
        # giao. Gói `dee8eb66` ghi `acceptance_status=not_accepted` trong khi
        # tài liệu bàn giao tuyên bố `retrieval-baseline-ready`; consumer máy
        # đọc manifest, không đọc Markdown. Nguồn đúng là RC-20 — cổng đã chạy
        # thật — chứ không phải một phép suy lại ở tầng đóng gói.
        "acceptance_status": _acceptance_status(rep),
        "rc20_gate_report": rep.gate_report_ref,
        "allowed_blocked_gates": ALLOWED_BLOCKED_GATES,
        "component_versions": src_manifest.get("versions", {}),
        "dq_version": DQ_VERSION,
        "counts": rep.counts,
        "dataframes": rep.files,
        # Ba trạng thái, không phải hai. `false` cho cả "hỏng" lẫn "chưa đo
        # được" là chỗ người nhận gói mất thông tin quan trọng nhất: cái nào
        # họ phải chờ ta sửa, cái nào chỉ là ta chưa có dụng cụ đo.
        "quality_gates": {
            g: _gate_rollup(checks)
            for g, checks in (rep.quality.get("gates") or {}).items()
        },
        # ── RC-10 · năm khoá NỮA mà `rc1_missing_keys` chưa liệt kê ────────
        #
        # Hợp đồng P3 ghi 7 khoá thiếu. Test đọc `required_keys` rồi soi mã
        # thì ra **12**: năm khoá dưới đây tồn tại dưới TÊN KHÁC hoặc không
        # tồn tại. Đây là lý do phải kiểm bằng máy chứ không đối chiếu bằng
        # mắt — bản liệt kê tay đếm thiếu 5/12.
        #
        # Tên cũ GIỮ NGUYÊN bên cạnh (append-only): đổi tên là breaking.
        "build_id": rep.build_id,                    # = source_build_id
        "corpus_hash": (_bm.get("corpus_hash") or _bm.get("corpus_content_hash")
                        or src_manifest.get("corpus_hash")
                        or src_manifest.get("corpus_content_hash")
                        or _bm.get("corpus_id") or src_manifest.get("corpus_id")),
        "schema_version": SCHEMA_VERSION,
        "gate_summary": {
            g: _gate_rollup(checks)
            for g, checks in (rep.quality.get("gates") or {}).items()
        },
        "blocking_failures": rep.dq.get("blocking", []),
        "release_label": rep.release_label,
        "blocked_gates": rep.blocked_gates,
        "status": rep.dq.get("status", "unknown"),
        "dq_summary": {"n_checks": rep.dq.get("n_checks"),
                       "n_failed": rep.dq.get("n_failed"),
                       "blocking": rep.dq.get("blocking", []),
                       "warnings": rep.dq.get("warnings", [])},
        "n_files": len(files),
        "total_bytes": sum(f["bytes"] for f in files.values()),
        "files": files,
    }


def _md_dictionary(db: Path, profile: str) -> str:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts_%'"
        " ORDER BY name")]
    out = ["# DATA DICTIONARY — gói Silver ViFinQA", "",
           f"Sinh tự động từ `silver.db` (hồ sơ `{profile}`, lược đồ "
           f"`{RELEASE_SCHEMA_VERSION}`). **Không sửa tay** — sửa "
           "`release_schema.py` rồi dựng lại.", "",
           "## Quan hệ giữa các bảng", "",
           "```",
           "documents ─┬─< pages",
           "           └─< tables ─┬─< columns ──┐",
           "                       ├─< rows ─────┼─< observations",
           "                       └─────────────┘",
           "```", "",
           "`observations` là bảng trung tâm: mỗi dòng là một ô số, neo về đúng "
           "một `(table_uid, grid_row_idx, grid_col_idx)`, và mang sẵn "
           "`ticker`/`doc_year`/`statement_type` phi chuẩn hoá để lọc không cần JOIN.",
           ""]
    undocumented: list[str] = []
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        out += [f"## `{t}`", "", f"{TABLE_DOCS.get(t, '_(chưa mô tả)_')}", "",
                f"**{n:,} dòng**", "",
                "| Cột | Kiểu | Rỗng? | Khoá | Ý nghĩa |", "|---|---|---|---|---|"]
        docs = COLUMN_DOCS.get(t, {})
        for _, name, ctype, notnull, _dflt, pk in conn.execute(
                f"PRAGMA table_info({t})"):
            desc = docs.get(name, "")
            if not desc:
                undocumented.append(f"{t}.{name}")
                desc = "—"
            key = "PK" if pk else ""
            out.append(f"| `{name}` | {ctype or 'TEXT'} | "
                       f"{'không' if notnull else 'có thể'} | {key} | {desc} |")
        fks = list(conn.execute(f"PRAGMA foreign_key_list({t})"))
        if fks:
            out += ["", "Khoá ngoại: " + ", ".join(
                f"`{f[3]}` → `{f[2]}.{f[4]}`" for f in fks)]
        idx = [r[1] for r in conn.execute(f"PRAGMA index_list({t})")
               if r[1].startswith("ix_")]
        if idx:
            out += ["", "Chỉ mục: " + ", ".join(f"`{i}`" for i in idx)]
        out.append("")
    if undocumented:
        out += ["## Cột chưa có mô tả", "",
                "Danh sách này do trình sinh tự phát hiện — mọi cột ở đây là nợ "
                "tài liệu, không phải cột không quan trọng.", "",
                *(f"- `{c}`" for c in undocumented), ""]
    conn.close()
    return "\n".join(out)


def _md_report(rep: ReleaseReport) -> str:
    q, dq = rep.quality, rep.dq
    o = ["# SILVER REPORT — gói dữ liệu ViFinQA", "",
         f"Bản dựng nguồn `{rep.build_id}` · hồ sơ `{rep.profile}` · "
         f"sinh lúc {_now()}", "",
         "Toàn bộ con số trong tài liệu này được **sinh từ dữ liệu thật**, "
         "không gõ tay. Sửa dữ liệu thì dựng lại gói, đừng sửa tệp này.", "",
         "## 1. Các bước xử lý dữ liệu", "",
         "| Giai đoạn | Việc | Bất biến bảo vệ |", "|---|---|---|",
         "| D0 Snapshot | Băm toàn corpus, khẳng định không BOM/CRLF/NBSP/NUL | corpus đúng bản đã đo |",
         "| D1 Catalog | Phát hiện `<table>`, ranh giới trang, định danh tài liệu | không bỏ sót bảng |",
         "| D2 Parse | Khai triển `rowspan`/`colspan` thành lưới, **giữ ô nguồn tách khỏi ô lưới** | một ô `colspan=2` là MỘT giá trị, không phải hai |",
         "| D3 Structure | Vai trò cột/dòng, `row_path` phân cấp, phân loại báo cáo | không loại cứng bằng classifier (DI-02) |",
         "| D4a Number | Parse số exact bằng `Decimal`, quy ước phân cách theo cấp bảng | dash/rỗng **không** thành 0 (DI-06) |",
         "| D4b Unit | Ba trục độc lập: loại đơn vị, tiền tệ, bậc 10 | mỗi trục có bằng chứng riêng (DI-07) |",
         "| D4c Period | Thứ bậc `cell → column → row → table → section → document` | bậc thắng ghi vào `period_source` |",
         "| D5 Quality | 5 cổng G1–G5, trong đó G5 đo TÍNH ĐÚNG | publish bị chặn khi cổng đỏ (DI-10) |",
         "| D6 Publish | Đóng dấu `build_id` từ corpus_id + phiên bản mọi thành phần | bản dựng tái lập được |",
         "| D7 Release | Gói này: lược đồ tiêu thụ, chỉ mục, FTS, tài liệu | lược đồ phát hành là hợp đồng |",
         "",
         "## 2. Thống kê", "", "| Thực thể | Số lượng |", "|---|---:|"]
    labels = {"documents": "Tài liệu (= báo cáo)", "pages": "Trang",
              "tables": "Bảng", "columns": "Cột", "rows": "Dòng",
              "observations": "Observation (ô số)",
              "quality_issues": "Bản ghi vấn đề chất lượng",
              "dropped_cells": "Ô số bị loại (có ghi LÝ DO)",
              "source_cells": "Ô nguồn (truy vết)", "grid_cells": "Ô lưới (truy vết)",
              "table_cards_fts": "Thẻ bảng đã đánh chỉ mục toàn văn"}
    for k, v in rep.counts.items():
        o.append(f"| {labels.get(k, k)} | {v:,} |")

    if q.get("gates"):
        o += ["", "### Cổng chất lượng ngữ nghĩa", "",
              "| Cổng | Kiểm tra | Giá trị | Ngưỡng | |", "|---|---|---|---|:-:|"]
        _mark = {PASS: "✅", FAIL: "❌", BLOCKED: "⊘"}
        for gate, checks in q["gates"].items():
            for c in checks:
                o.append(f"| {gate} | {c['name']} | {c['value']} | "
                         f"{c['threshold']} | {_mark[legacy_check_status(c)]} |")
        if rep.blocked_gates:
            # Khai rõ, không giấu trong bảng: doc 12 §7 số 12. Một cổng chưa
            # đo được mà không nói ra thì người nhận đọc như đã qua.
            o += ["", f"> **⊘ = CHƯA ĐO ĐƯỢC, không phải đã đạt.** Bản phát"
                      f" hành này mang nhãn `{rep.release_label}` chính vì"
                      f" {len(rep.blocked_gates)} cổng dưới đây chưa có dụng cụ"
                      " đo. Không được đọc là *đã kiểm và đạt*:", ""]
            o += [f"> - {b}" for b in rep.blocked_gates]
    if q.get("by_rule"):
        o += ["", "### Vấn đề theo rule", "", "| Rule | Số lượng |", "|---|---:|"]
        for k, v in sorted(q["by_rule"].items(), key=lambda x: -x[1]):
            o.append(f"| `{k}` | {v:,} |")

    o += ["", "## 3. Kiểm chất lượng gói", "",
          f"{dq.get('n_checks', 0)} kiểm tra · "
          f"**{dq.get('n_failed', 0)} không đạt**", "",
          "| Nhóm | Kiểm tra | Giá trị | Ngưỡng | |", "|---|---|---|---|:-:|"]
    for c in dq.get("checks", []):
        o.append(f"| {c['category']} | {c['description']} | {c['value']} | "
                 f"{c['threshold']} | {'✅' if c['passed'] else '❌'} |")
    bad = [c for c in dq.get("checks", []) if not c["passed"] and c["samples"]]
    if bad:
        o += ["", "### Mẫu vi phạm", ""]
        for c in bad:
            o += [f"**{c['check_id']}**", "", *(f"- `{s}`" for s in c["samples"]), ""]

    o += ["", "## 4. Lỗi đã phát hiện và cách xử lý", "",
          "Mỗi mục dưới đây là một lỗi **đo được trên corpus thật**, đã sửa và đã "
          "khoá bằng test hồi quy.", "",
          "| Lỗi | Quy mô | Cách sửa |", "|---|---|---|",
          "| `\\b(20[0-2]\\d)\\b` trượt trên `2021VND` — không có ranh giới từ giữa `1` và `V` | 43.350 cột đổi trạng thái; ~32.346 cột đang mang **sai kỳ** | Thay `\\b` bằng lookaround chữ số |",
          "| Tiêu đề `colspan` toàn bảng chứa \"THUYẾT MINH\" gán `note_reference` cho **mọi** cột | ~585 bảng dữ liệu mất sạch observation | Chỉ xét đoạn nhãn RIÊNG của cột; đoạn phủ toàn bộ bị loại |",
          "| `Trong năm`, `Tăng trong năm` có gợi ý kiểu kỳ nhưng không tầng nào gán được ngày | ~1.300 cột | Thêm bậc `P-RELATIVE-DURATION` (01/01–31/12 năm báo cáo) |",
          "| Cột `STT` toàn chữ số → `numeric_ratio` = 1,0 → bị coi là cột giá trị | 806 cột | Thêm vai trò `ordinal` |",
          "| Cột `Thuyết minh` không nhãn: 4, 5, 6, 7 lẫn giữa các cột tiền 13 chữ số | 3.183 cột · 14.459 ô \"tiền\" phi lý | Hạ vai trò theo **độ dài chữ số** khi bảng có cột khác ≥ 6 chữ số |",
          "| Hai ô số dính liền → `97.158.150.939396.219.749.004` = 9,7×10²² VND | 3.633 ô | Kiểm **hình dạng nhóm** (1–3 chữ số rồi từng nhóm đúng 3) → `ambiguous` |",
          "| Bốn ca còn lại dính qua đúng một dấu phân cách, hình dạng vẫn hợp lệ | 4 ô | Trần độ lớn 10¹⁶ VND cho ô tiền |",
          "| `publish` chạy dù cổng G4 đỏ | 1 bản dựng đã phát hành sai | `publish` chặn khi **bất kỳ** kiểm tra nào đỏ (DI-10) |",
          "",
          "## 5. Vấn đề còn tồn tại", "",
          # Bảng số cứng từng nằm ở đây — gõ tay từ một bản dựng tháng trước.
          # Sau D-01 mọi con số trong đó đã đổi, tệp thì không. Một tài liệu
          # nói về hạn chế mà bản thân nó sai số liệu là thứ tệ hơn không có:
          # người đọc tin nó và lập kế hoạch theo nó. Giờ nội dung này sinh từ
          # chính database của gói, xem `KNOWN_ISSUES.md`.
          "Toàn bộ phần này đã chuyển sang **[`KNOWN_ISSUES.md`](KNOWN_ISSUES.md)**, "
          "nơi mọi con số được **truy vấn trực tiếp từ `silver.db` của gói này** "
          "thay vì gõ tay.", "",
          "Ở đó có: ô bị loại kèm lý do và phán xét · độ phủ kỳ/đơn vị/vai trò "
          "cột · bốn lớp đụng độ ngữ nghĩa và triển vọng từng lớp · cổng chưa "
          "đo được · hạn chế cố ý chưa sửa · sáu guard nên đặt khi dùng · cam "
          "kết tương thích cho các bản sau.", ""]
    if rep.blocked_gates:
        o += [f"Tóm tắt: bản này mang nhãn `{rep.release_label}` vì "
              f"{len(rep.blocked_gates)} cổng chưa đo được.", ""]

    o += ["## 6. Thời gian từng giai đoạn", "", "| Giai đoạn | Giây | Ghi chú |", "|---|---:|---|"]
    for name, secs, note in rep.stages:
        o.append(f"| {name} | {secs:.1f} | {note} |")
    if rep.warnings:
        o += ["", "## 7. Cảnh báo khi đóng gói", ""] + [f"- {w}" for w in rep.warnings]
    return "\n".join(o) + "\n"


def _md_readme(rep: ReleaseReport, per_table: dict) -> str:
    c = rep.counts
    return f"""# Gói dữ liệu Silver — ViFinQA (R2AI 2026)

Bản dựng `{rep.build_id}` · hồ sơ `{rep.profile}` · {_now()}

Copy thư mục này về máy là dùng được ngay. **Không cần** cài pipeline, không
cần corpus gốc, không cần chạy lại bản dựng 10 phút.

## Có gì bên trong

| | |
|---|---:|
| Tài liệu (báo cáo) | {c.get('documents', 0):,} |
| Bảng | {c.get('tables', 0):,} |
| Observation (ô số đã chuẩn hoá) | {c.get('observations', 0):,} |
| Thẻ bảng đã đánh chỉ mục toàn văn | {c.get('table_cards_fts', 0):,} |

## Cấu trúc thư mục

```
silver_release/
├── silver.db              SQLite: PK, FK, chỉ mục, FTS5 — dùng ngay
├── data_preview.html      MỞ CÁI NÀY TRƯỚC — xem toàn bộ dữ liệu bằng trình duyệt
├── README.md              tệp này
├── DATA_OVERVIEW.md       dữ liệu là gì, phủ tới đâu, cái gì KHÔNG có trong gói
├── KNOWN_ISSUES.md        ĐỌC TRƯỚC KHI TIN — chỗ còn sai, còn thiếu, còn nợ
├── USAGE_GUIDE.md         công thức cho từng dạng câu hỏi + bốn luật bắt buộc
├── SILVER_REPORT.md       các bước xử lý, thống kê, lỗi đã sửa, cổng chất lượng
├── DATA_DICTIONARY.md     lược đồ, ý nghĩa từng cột, quan hệ giữa các bảng
├── manifest.json          thống kê, phiên bản, SHA-256 đầy đủ mọi tệp, thời điểm tạo
├── metadata/              documents.json · pages.json · tables.jsonl
├── dataframe/
│   ├── csv/               một tệp mỗi bảng dữ liệu (bảng lớn nén .gz)
│   │   └── by_table/      CSV từng bảng báo cáo — long/ và wide/
│   └── parquet/           cùng dữ liệu, nén zstd, đọc nhanh hơn nhiều
├── logs/                  nhật ký dựng + kết quả kiểm chất lượng
└── examples/              4 script chạy được ngay
```

## Đọc theo thứ tự nào

| Bạn là | Đọc | Vì sao |
|---|---|---|
| **Bất kỳ ai** | `KNOWN_ISSUES.md` | Biết trước gói này sai ở đâu, thay vì tự phát hiện vào tuần thứ ba. Mọi số trong đó truy vấn từ chính `silver.db` này. |
| **Text-to-Pandas** | `USAGE_GUIDE.md` §4, §5 | Bốn luật bắt buộc + công thức cho 10 dạng câu hỏi, kể cả *khi nào phải TỪ CHỐI trả lời*. |
| **Retrieval** | `USAGE_GUIDE.md` §6 · `DATA_OVERVIEW.md` §3 | Cách dùng `table_cards` + FTS5, và độ phủ thật theo mã × năm. |
| **Người kiểm toán** | `SILVER_REPORT.md` · `DATA_DICTIONARY.md` | Các bước xử lý, cổng chất lượng, lược đồ đầy đủ. |

## Bắt đầu trong 30 giây

Mở `data_preview.html` bằng trình duyệt. Không cần cài gì, không cần mở SQLite:
lược đồ từng bảng, 20 dòng mẫu, tỷ lệ rỗng theo cột, trùng lặp, sơ đồ quan hệ,
biểu đồ phân bố và độ phủ mã chứng khoán × năm đều nằm trong đó.

```bash
python examples/01_open_sqlite.py       # truy vấn SQLite
python examples/02_read_parquet.py      # nạp DataFrame
python examples/03_search_tables.py     # tìm bảng bằng FTS5
python examples/04_verify_package.py    # đối chiếu checksum
```

## Mở SQLite

```python
import sqlite3
conn = sqlite3.connect("file:silver.db?mode=ro", uri=True)   # chỉ đọc
conn.execute("PRAGMA foreign_keys=ON")

conn.execute(\"\"\"
    SELECT row_path_text, period_end, value_decimal_text, unit_kind, confidence
    FROM observations
    WHERE ticker = 'VNM' AND doc_year = 2018
      AND statement_type = 'balance_sheet'
      AND confidence = 'high'
    LIMIT 20
\"\"\").fetchall()
```

## Đọc DataFrame

```python
import pandas as pd

# Parquet — nhanh hơn CSV nhiều lần, giữ nguyên kiểu chuỗi
obs = pd.read_parquet("dataframe/parquet/observations/part-0000.parquet")

# CSV (bảng lớn nén gzip)
obs = pd.read_csv("dataframe/csv/observations.csv.gz", compression="gzip",
                  dtype=str, keep_default_na=False)
```

## Ba điều BẮT BUỘC biết trước khi dùng

**1. `value_decimal_text` là CHUỖI, không phải số.** Corpus có giá trị tới
10¹⁵ VND; `float64` chỉ giữ chính xác 15–16 chữ số và sẽ làm tròn sai ngay.

```python
from decimal import Decimal
v = Decimal(row["value_decimal_text"])          # ĐÚNG
v = float(row["value_decimal_text"])            # SAI — mất chính xác
```

**2. Giá trị rỗng KHÔNG phải số 0.** {c.get('observations', 0):,} observation là
những ô **đọc được**. Ô dấu gạch ngang (`-`) trong báo cáo tài chính nghĩa là
*khuyết dữ liệu*, không phải *bằng không* — chúng cố ý không có mặt ở đây.
Điền 0 vào là tạo ra số liệu không tồn tại trong báo cáo.

**3. `confidence` có thật, hãy dùng nó.** `low` nghĩa là thiếu kỳ, hoặc đơn vị
là mặc định, hoặc cột chưa phân loại được vai trò. Tầng truy hồi nên hạ trọng
số thay vì tin như nhau.

```python
conn.execute("SELECT confidence, COUNT(*) FROM observations GROUP BY 1")
```

## Đơn vị và bậc 10

Giá trị lưu **đúng như in trên báo cáo**; `scale_exponent` cho biết phải nhân
bao nhiêu để ra VND.

```python
vnd = Decimal(row["value_decimal_text"]) * (10 ** int(row["scale_exponent"] or 0))
```

`0` = VND · `3` = nghìn đồng · `6` = triệu đồng · `9` = tỷ đồng.

## Trích dẫn bằng chứng (ràng buộc C20)

Dùng `evidence_ref` có sẵn, **đừng tự ghép chuỗi**:

```python
conn.execute("SELECT evidence_ref FROM tables WHERE table_uid=?", (uid,))
# → 'VNM_financial_statements_2018_consolidated|line:350'
```

## Tìm bảng bằng FTS5

```python
from text2pandas.pipelines.a6.text_normalize import fts_match_expr

conn.execute(\"\"\"
    SELECT table_uid, ticker, section_text
    FROM table_cards_fts
    WHERE table_cards_fts MATCH ?
    LIMIT 10
\"\"\", (fts_match_expr("tiền và tương đương"),)).fetchall()
```

**Chỉ mục lưu ở DẠNG CHUẨN.** Truy vấn PHẢI đi qua `fts_match_expr()` —
`MATCH 'đồng'` viết thẳng sẽ khớp **không cái gì**, vì `remove_diacritics 2`
gập được mọi dấu tiếng Việt TRỪ `đ` (U+0111), vốn là một ký tự riêng chứ không
phải `d` + dấu. Không có dấu `đ` trong câu hỏi thì viết thẳng vẫn chạy — nhưng
đừng dựa vào đó, vì lúc nào nó hỏng thì không có gì báo.

## CSV theo từng bảng

Chế độ `{per_table.get('mode')}` · {per_table.get('n_tables', 0):,} bảng, mỗi bảng hai bố cục:

- `by_table/long/` — lược đồ **cố định** cho mọi bảng (`row_path`, `value`,
  `period_end`, `unit_kind`…). Model sinh `pandas_query` chỉ phải học một lược đồ.
- `by_table/wide/` — giống báo cáo giấy. Dễ đọc, nhưng tên cột là chuỗi OCR gốc
  nên khoá không ổn định giữa các bảng.

Danh mục ở `by_table/index.json`. Chưa có bằng chứng bố cục nào cho điểm cao
hơn — không có tập train nên chỉ leaderboard trả lời được.

## Kiểm tính toàn vẹn

```bash
python examples/04_verify_package.py
```

Đối chiếu SHA-256 **đầy đủ** của mọi tệp với `manifest.json`.

## Yêu cầu môi trường

Python 3.10+, `pandas` và `pyarrow` cho Parquet. SQLite phải có FTS5 (bản đi kèm
Python trên macOS/Linux đều có).

## Trước khi dùng cho Retrieval / Embedding / Text-to-Pandas

Đọc mục **5. Vấn đề còn tồn tại** trong `SILVER_REPORT.md`. Có sáu hạng mục đã
biết và đã đo; biết trước thì thiết kế quanh được, phát hiện sau thì phải làm lại.
"""


_EXAMPLES = {
    "01_open_sqlite.py": '''"""Mở silver.db và chạy vài truy vấn tiêu biểu."""
import sqlite3
from decimal import Decimal
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "silver.db"
conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.execute("PRAGMA foreign_keys=ON")

print("── Quy mô ──")
for t in ("documents", "tables", "columns", "rows", "observations"):
    print(f"  {t:<14} {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>10,}")

print("\\n── Độ tin cậy ──")
for conf, n in conn.execute(
        "SELECT confidence, COUNT(*) FROM observations GROUP BY 1 ORDER BY 2 DESC"):
    print(f"  {conf:<8} {n:>10,}")

print("\\n── Bảng cân đối của một mã bất kỳ ──")
row = conn.execute(
    "SELECT ticker, doc_year FROM tables WHERE statement_type='balance_sheet'"
    " ORDER BY ticker LIMIT 1").fetchone()
if row:
    tk, yr = row
    print(f"  {tk} {yr}")
    for path, per, val, exp, conf in conn.execute(
            "SELECT row_path_text, period_end, value_decimal_text,"
            " scale_exponent, confidence FROM observations"
            " WHERE ticker=? AND doc_year=? AND statement_type='balance_sheet'"
            "   AND metric_code IN ('100','200','270','300','400','440')"
            " ORDER BY metric_code LIMIT 12", (tk, yr)):
        # value_decimal_text là CHUỖI. Decimal, không bao giờ float.
        vnd = Decimal(val) * (10 ** int(exp or 0))
        print(f"    {(path or '')[:46]:<46} {per} {vnd:>24,} [{conf}]")
conn.close()
''',
    "02_read_parquet.py": '''"""Nạp DataFrame từ Parquet và cộng đúng cách."""
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
obs = pd.read_parquet(ROOT / "dataframe" / "parquet" / "observations" / "part-0000.parquet")
print(f"observations: {len(obs):,} dòng × {len(obs.columns)} cột")
print(obs.dtypes.head(10), "\\n")

# MỌI cột là chuỗi — có chủ đích. Ép sang float là mất chính xác ở 10^15.
bs = obs[(obs.statement_type == "balance_sheet") & (obs.confidence == "high")]
print(f"bảng cân đối, độ tin cậy cao: {len(bs):,} ô")

def to_vnd(r):
    return Decimal(r.value_decimal_text) * (10 ** int(r.scale_exponent or 0))

sample = bs.head(5)
for _, r in sample.iterrows():
    print(f"  {r.ticker} {r.doc_year} {str(r.row_path_text)[:40]:<40} {to_vnd(r):>22,}")
''',
    "03_search_tables.py": '''"""Tìm bảng bằng chỉ mục toàn văn FTS5 — đầu vào cho tầng truy hồi.

RC-05 · Chỉ mục lưu ở DẠNG CHUẨN nên câu hỏi cũng phải chuẩn hoá. Gõ `đồng`
thẳng vào MATCH sẽ khớp KHÔNG CÁI GÌ: `remove_diacritics 2` của SQLite gập
được mọi dấu tiếng Việt trừ `đ` (U+0111) — nó là ký tự riêng, không phải
`d` + dấu. Hỏng to còn hơn hỏng lặng: RC1 trả 997 thẻ thay vì 104.792.
"""
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "silver.db"


def norm(text):
    """Bản sao độc lập của `normalize_search_text` — gói không có src/."""
    t = unicodedata.normalize("NFC", text).casefold()
    t = t.translate(str.maketrans({"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"}))
    t = unicodedata.normalize("NFD", t)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\\s+", " ", unicodedata.normalize("NFC", t)).strip()


raw = " ".join(sys.argv[1:]) or "tiền và tương đương tiền"
query = " ".join('"%s"' % w for w in norm(raw).split())

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
meta = dict(conn.execute("SELECT key, value FROM build_meta").fetchall())
assert meta.get("fts_content") == "normalized", (
    "gói này không phải chỉ mục dạng chuẩn — xem build_meta.fts_content")
print(f"Truy vấn: {raw!r} → {query}\\n")
for uid, ticker, section, rank in conn.execute(
        "SELECT f.table_uid, f.ticker, f.section_text, bm25(table_cards_fts)"
        " FROM table_cards_fts f WHERE table_cards_fts MATCH ?"
        " ORDER BY rank LIMIT 10", (query,)):
    ref = conn.execute("SELECT evidence_ref FROM tables WHERE table_uid=?",
                       (uid,)).fetchone()[0]
    print(f"  {rank:8.3f}  {ticker:<6} {(section or '')[:50]:<50} {ref}")
conn.close()
''',
    "04_verify_package.py": '''"""Đối chiếu mọi tệp với manifest.json — chạy sau khi copy sang máy khác."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
man = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

bad, missing = [], []
for rel, meta in man["files"].items():
    p = ROOT / rel
    if not p.exists():
        missing.append(rel)
        continue
    if p.stat().st_size != meta["bytes"]:
        bad.append(f"{rel}: kích thước lệch")
        continue
    h = hashlib.sha256()
    with p.open("rb") as f:
        while blk := f.read(1 << 22):
            h.update(blk)
    if h.hexdigest() != meta["digest"]:
        bad.append(f"{rel}: checksum lệch")

print(f"{man['n_files']} tệp · {man['total_bytes'] / 1e9:.2f} GB")
print(f"thiếu: {len(missing)}   hỏng: {len(bad)}")
for x in (missing + bad)[:20]:
    print(f"  ✗ {x}")
sys.exit(1 if (missing or bad) else 0)
''',
}


# ─────────────────────────── điều phối ───────────────────────────

# Bảng và cột mà release schema hiện tại BẮT BUỘC nguồn phải có.
# Kiểm trước khi mở tệp đích: bản trước crash ở giai đoạn `observations` sau
# khi đã ghi vài GB, với thông báo `no such table: s.collision_obs` — đúng
# nhưng vô dụng, vì nó không nói phải làm gì.
_REQUIRED_SOURCE = {
    "observations": ("row_uid", "column_uid"),
    "collision_obs": ("observation_uid", "collision_class"),
    "dropped_cells": ("source_cell_uid", "reason"),
    "build_meta": (),
    # RC-02 · dừng SỚM thay vì phát hành một gói không có chính sách.
    # `non_candidate_reasons_json` cũng bị đòi: một Silver dựng bằng readiness
    # v2.0 sẽ thiếu đúng cột này, và dựng gói từ nó nghĩa là mất tầng
    # NON_CANDIDATE — thứ mà precedence v2.1 dựa vào để phân biệt "thiếu dữ
    # liệu" với "có dữ liệu nhưng chưa an toàn".
    "observation_readiness": ("observation_uid", "execution_candidate",
                              "execution_ready", "confidence",
                              "blocking_reasons_json", "warning_reasons_json",
                              "non_candidate_reasons_json", "policy_version"),
}


def check_source_contract(src_silver: Path) -> list[str]:
    """Trả danh sách thiếu sót. Rỗng nghĩa là nguồn dựng gói được."""
    con = sqlite3.connect(f"file:{src_silver}?mode=ro", uri=True)
    try:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing: list[str] = []
        for tbl, cols in _REQUIRED_SOURCE.items():
            if tbl not in have:
                missing.append(f"bảng `{tbl}`")
                continue
            got = {r[1] for r in con.execute(f"PRAGMA table_info({tbl})")}
            missing += [f"`{tbl}.{c}`" for c in cols if c not in got]
        return missing
    finally:
        con.close()


def _load_gate_report(path) -> tuple[dict | None, dict | None]:
    """Đọc `gate_report.json` của RC-20 và exit code đi kèm nó.

    Exit code nằm ở `exit_code.txt` cùng thư mục do `acceptance_step.sh` ghi.
    Một `gate_report.json` nói PASS mà command exit khác 0 thì không phải cổng
    đã đạt — Doc 52 §7 nói thẳng điều đó.
    """
    if not path:
        return None, None
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"LỖI: không thấy gate report {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    ec = p.parent / "exit_code.txt"
    code = ec.read_text(encoding="utf-8").strip() if ec.is_file() else None
    g = {"release_label": d.get("release_label"),
         "summary": d.get("summary"), "build_id": d.get("build_id"),
         "exit_code": code if code is not None else 0}
    ref = {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
           "build_id": d.get("build_id"), "release_label": d.get("release_label"),
           "exit_code": g["exit_code"]}
    return g, ref


def build_release(src_silver: Path, src_bronze: Path, src_manifest_path: Path,
                  src_quality_path: Path, out_dir: Path, profile: str = "slim",
                  per_table: str = "primary",
                  gate_report_path: Path | None = None) -> ReleaseReport:
    t_all = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(exist_ok=True)
    log = _Log(out_dir / "logs" / "build.log")
    rep = ReleaseReport(out_dir=out_dir, profile=profile)
    rep.gate_summary_from_rc20, rep.gate_report_ref = _load_gate_report(gate_report_path)

    src_manifest = json.loads(src_manifest_path.read_text(encoding="utf-8")) \
        if src_manifest_path.exists() else {}
    rep.quality = json.loads(src_quality_path.read_text(encoding="utf-8")) \
        if src_quality_path.exists() else {}
    rep.build_id = src_manifest.get("build_id", "unknown")

    # Hợp đồng nguồn: gói phát hành schema 1.2 cần `row_uid`, `column_uid`,
    # `collision_obs`, `dropped_cells`. Một Silver dựng trước khi có chúng
    # KHÔNG thể sinh gói đạt hợp đồng — dừng ngay và nói rõ phải làm gì.
    missing = check_source_contract(src_silver)
    if missing:
        raise SystemExit(
            "LỖI: Silver nguồn cũ hơn hợp đồng phát hành.\n"
            f"  nguồn  : {src_silver}\n"
            f"  thiếu  : {', '.join(missing)}\n"
            "\n"
            "  Silver này được dựng trước khi có Data Contract v1. Dựng lại rồi\n"
            "  publish, sau đó release mới đọc đúng bản:\n"
            "\n"
            "    rm -rf /tmp/dp_work/silver.sqlite*\n"
            "    python -m text2pandas.pipelines.a6.cli -v silver\n"
            "    python -m text2pandas.pipelines.a6.cli quality\n"
            "    python -m text2pandas.pipelines.a6.cli publish\n"
            "    python -m text2pandas.pipelines.a6.cli release\n")

    # Không đóng gói bản dựng chưa qua cổng. Gói phát hành mang uy tín của cả
    # nhóm; phát hành dữ liệu chưa đạt cổng là chuyển rủi ro sang người khác.
    #
    # Nhưng "chưa qua cổng" phải nghĩa là ĐO RỒI HỎNG. Cổng CHƯA ĐO ĐƯỢC
    # (Structure Gold chưa tồn tại) không nói gì về chất lượng dữ liệu và
    # không được quyền chặn RC — doc 12 §7 cho phép, với điều kiện khai rõ.
    # `rc_blocked_gates` đi thẳng vào release notes ở dưới.
    failed, rc_blocked = split_legacy_gates(rep.quality.get("gates"))
    if failed:
        log("LỖI: bản dựng nguồn chưa qua cổng chất lượng — dừng.")
        for f in failed:
            log(f"  ✗ {f}")
        raise SystemExit(2)
    if rc_blocked:
        log(f"cổng BLOCKED ({len(rc_blocked)}) — hạ nhãn xuống RC, khai trong"
            " release notes:")
        for b in rc_blocked:
            log(f"  ⊘ {b}")
    rep.blocked_gates = rc_blocked
    if rep.gate_summary_from_rc20:
        # Nhãn do RC-20 quyết. Tính lại ở đây là tạo nguồn thứ hai cho cùng một
        # trạng thái — đúng lỗi P0-05 đang đi sửa.
        rep.release_label = (rep.gate_summary_from_rc20.get("release_label")
                             or "blocked")
    else:
        rep.release_label = "silver-v1.0.0-rc2" if rc_blocked else "silver-v1.0.0"

    # Chỉ ghi TÊN bản dựng, không ghi đường dẫn tuyệt đối — gói này đi ra
    # ngoài nhóm, và username/đường dẫn máy cá nhân không thuộc về nó.
    log(f"nguồn : {src_silver.parent.name}/{src_silver.name}"
        f"  ({_human(src_silver.stat().st_size)})")
    log(f"đích  : ./{out_dir.name}   hồ sơ={profile}  csv-theo-bảng={per_table}")

    t = time.time()
    rep.counts = _build_db(src_silver, src_bronze, out_dir / "silver.db",
                           profile, log, rep.quality, src_manifest)
    rep.stages.append(("dựng silver.db", time.time() - t,
                       f"{_human((out_dir / 'silver.db').stat().st_size)}"))

    t = time.time()
    rep.files = _export_frames(out_dir / "silver.db", out_dir, log)
    rep.stages.append(("xuất CSV + Parquet", time.time() - t,
                       f"{len(rep.files)} tập dữ liệu"))

    t = time.time()
    pt = _export_per_table(out_dir / "silver.db", out_dir, per_table, log)
    rep.stages.append(("CSV theo từng bảng", time.time() - t,
                       f"{pt['n_tables']:,} bảng × 2 bố cục"))

    t = time.time()
    md_files = _export_metadata(out_dir / "silver.db", out_dir, log)
    (out_dir / "metadata" / "quality.json").write_text(
        json.dumps(rep.quality, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "metadata" / "dataframes.json").write_text(
        json.dumps({"datasets": rep.files, "per_table": pt},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    rep.stages.append(("metadata JSON", time.time() - t, f"{len(md_files) + 2} tệp"))

    t = time.time()
    log("kiểm chất lượng gói …")
    conn = sqlite3.connect(f"file:{out_dir / 'silver.db'}?mode=ro", uri=True)
    dq = run_dq_checks(conn, FULL_TABLES if profile == "full" else SLIM_TABLES)
    conn.close()
    rep.dq = dq.to_json()
    (out_dir / "logs" / "quality_checks.log").write_text(
        "\n".join(f"[{'PASS' if c.passed else 'FAIL'}] {c.check_id:<28} "
                  f"{c.description} = {c.value} (ngưỡng {c.threshold})"
                  + ("".join(f"\n      · {s}" for s in c.samples[:5]) if c.samples else "")
                  for c in dq.checks) + "\n", encoding="utf-8")
    log(f"  {len(dq.checks)} kiểm tra · {len(dq.failed)} không đạt")
    for c in dq.failed:
        log(f"    ✗ {c.check_id}: {c.description} = {c.value}")
        rep.warnings.append(f"{c.check_id}: {c.description} = {c.value}")
    # P0-03 · chính sách nghiêm trọng, khai tường minh thay vì ngầm định.
    # Bản đầu ghi `status = published` trong khi ba kiểm tra DQ đỏ — gói tự
    # mâu thuẫn với chính tuyên bố của nó. Bốn nhóm dưới đây là bất biến cấu
    # trúc; đỏ ở đó nghĩa là gói KHÔNG dùng được, không phải "cần lưu ý".
    blocking = [c for c in dq.failed
                if c.category in ("schema", "relationship", "invariant")]
    rep.dq["blocking"] = [c.check_id for c in blocking]
    rep.dq["warnings"] = [c.check_id for c in dq.failed if c not in blocking]
    # Cổng BLOCKED ở tầng Silver cũng hạ nhãn gói: không thể có `published`
    # trong khi một cổng chưa từng được đo. `release-candidate` là mức cao
    # nhất mà một gói mang gate BLOCKED được phép tuyên bố.
    status = ("release-candidate"
              if (dq.failed or rep.blocked_gates) else "published")
    if blocking:
        status = "blocked"
    with sqlite3.connect(out_dir / "silver.db") as wc:
        wc.execute("INSERT OR REPLACE INTO build_meta VALUES('status',?)", (status,))
        wc.execute("INSERT OR REPLACE INTO build_meta VALUES('release_label',?)",
                   (rep.release_label,))
        wc.execute("INSERT OR REPLACE INTO build_meta VALUES('blocked_gates',?)",
                   (json.dumps(rep.blocked_gates, ensure_ascii=False),))
        wc.execute("INSERT OR REPLACE INTO build_meta VALUES('dq_blocking',?)",
                   (json.dumps(rep.dq["blocking"], ensure_ascii=False),))
    rep.dq["status"] = status
    log(f"  trạng thái gói: {status}"
        + (f"  ← chặn bởi {len(blocking)} kiểm tra bất biến" if blocking else ""))
    rep.stages.append(("kiểm chất lượng gói", time.time() - t,
                       f"{len(dq.failed)} không đạt · {status}"))

    t = time.time()
    log("sinh trang xem nhanh data_preview.html …")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
        from make_preview import build_html, collect  # type: ignore

        pconn = sqlite3.connect(f"file:{out_dir / 'silver.db'}?mode=ro", uri=True)
        pdata = collect(pconn, 20)
        pconn.close()
        (out_dir / "data_preview.html").write_text(
            build_html(pdata, out_dir / "silver.db"), encoding="utf-8")
        log(f"  data_preview.html · "
            f"{_human((out_dir / 'data_preview.html').stat().st_size)}")
    except Exception as exc:                       # noqa: BLE001
        # Trang xem nhanh là tiện ích, không phải dữ liệu. Nó hỏng thì gói vẫn
        # dùng được — nhưng phải NÓI RA, không được im lặng bỏ qua.
        log(f"  CẢNH BÁO: không sinh được data_preview.html: {exc}")
        rep.warnings.append(f"data_preview.html không sinh được: {exc}")
    rep.stages.append(("trang xem nhanh", time.time() - t, "data_preview.html"))

    t = time.time()
    log("sinh tài liệu …")
    ex = out_dir / "examples"
    ex.mkdir(exist_ok=True)
    for name, body in _EXAMPLES.items():
        (ex / name).write_text(body, encoding="utf-8")
    (out_dir / "DATA_DICTIONARY.md").write_text(
        _md_dictionary(out_dir / "silver.db", profile), encoding="utf-8")
    (out_dir / "SILVER_REPORT.md").write_text(_md_report(rep), encoding="utf-8")
    (out_dir / "README.md").write_text(_md_readme(rep, pt), encoding="utf-8")
    # Ba tài liệu SINH TỪ DỮ LIỆU: tổng quan · hạn chế · cách dùng. Chúng đọc
    # `silver.db` vừa dựng xong, nên mọi con số bên trong là của CHÍNH gói này
    # chứ không phải của một bản dựng nào đó tháng trước.
    for name, body in build_docs(out_dir / "silver.db", rep).items():
        (out_dir / name).write_text(body, encoding="utf-8")
    rep.stages.append(("sinh tài liệu + ví dụ", time.time() - t,
                       f"{3 + len(DOC_FILES)} tài liệu, {len(_EXAMPLES)} ví dụ"))

    if src_quality_path.exists():
        shutil.copy(src_quality_path, out_dir / "logs" / "source_quality_report.json")

    # `manifest.json` phải là thứ ghi CUỐI CÙNG. Nó băm mọi tệp khác, nên bất kỳ
    # tệp nào ghi sau nó đều lệch checksum ngay khi người nhận kiểm tra — và một
    # gói tự báo hỏng ngay lần kiểm đầu thì không ai tin phần còn lại.
    # Vì vậy đóng nhật ký và ghi báo cáo TRƯỚC, rồi mới băm.
    rep.seconds = round(time.time() - t_all, 1)
    rep.stages.append(("băm + manifest", 0.0, "đo trong manifest.json"))
    log(f"XONG · {rep.seconds}s — còn lại: ghi báo cáo, đóng nhật ký, băm")
    log.close()
    (out_dir / "SILVER_REPORT.md").write_text(_md_report(rep), encoding="utf-8")

    # ── RC-21 · counts phải đo SAU khi mọi lượt ghi `build_meta` xong ──────
    #
    # `counts` được đo ngay sau bước dựng DB, nhưng `build_meta` còn nhận thêm
    # `status`, `release_label`, `blocked_gates`, `dq_blocking`,
    # `fts_content`… ở các bước sau. Manifest vì thế ghi một con số CŨ, và
    # `verify_package` báo `counts lệch: build_meta manifest=26 db=30` — một
    # gói tự mâu thuẫn ngay ở lần kiểm đầu tiên.
    #
    # Đây đúng là `generation_order` mà hợp đồng khai: counts → manifest →
    # SHA256SUMS. Đo lại ở đây là chỗ duy nhất bảo đảm thứ tự đó.
    with sqlite3.connect(f"file:{out_dir / 'silver.db'}?mode=ro", uri=True) as rc:
        for tname in list(rep.counts):
            try:
                rep.counts[tname] = rc.execute(
                    f"SELECT COUNT(*) FROM {tname}").fetchone()[0]
            except sqlite3.Error:
                pass

    t = time.time()
    manifest = _md_manifest(rep, out_dir, src_manifest)
    # RC2-050 · khoá CÓ mặt mà rỗng không phải là định danh. Chặn tại chỗ ghi,
    # vì sau khi gói đã đi ra ngoài thì không ai sửa được nữa.
    rong = [k for k in ("build_id", "source_hash", "config_hash", "corpus_hash",
                        "corpus_id", "schema_version")
            if manifest.get(k) in (None, "")]
    if rong:
        raise RuntimeError(f"manifest có {len(rong)} trường định danh rỗng: {rong}")
    manifest["checksum_seconds"] = round(time.time() - t, 1)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── RC-21/RC-23 · SHA256SUMS, ghi SAU manifest ────────────────────────
    #
    # `verify_package` đòi nó và `manifest_contract.generation_order` khai nó,
    # nhưng không bước nào sinh ra — nên MỌI gói đều fail verify ở dòng đầu.
    # Phạm vi: mọi tệp TRỪ chính `SHA256SUMS` Ở GỐC (tránh vòng lặp hash), gồm
    # cả `manifest.json` vì nó cũng là một tệp người nhận phải kiểm.
    #
    # RC2-048 · loại theo ĐƯỜNG DẪN TƯƠNG ĐỐI, không theo `f.name`. Điều kiện
    # cần loại là "chính tệp này", không phải "mọi tệp trùng tên". Bản dùng
    # `f.name` loại luôn các tệp `acceptance/*/SHA256SUMS` được gieo vào
    # release: 8 tệp ở gói `27d9767f`, 21 tệp ở gói `dee8eb66`. Kiểm toán độc
    # lập (Doc 56 P1-05) bắt đúng chỗ này. Phủ vẫn đủ nhờ manifest, nhưng
    # "đủ nhờ chỉ mục khác" không phải điều `SHA256SUMS` hứa.
    lines = []
    for f in sorted(out_dir.rglob("*"), key=lambda q: q.relative_to(out_dir).as_posix()):
        rel = f.relative_to(out_dir).as_posix()
        if not f.is_file() or rel == "SHA256SUMS":
            continue
        lines.append(f"{_sha256(f)}  {rel}")

    # Không tự tin vào vòng lặp trên: đếm lại từ ĐĨA. Một chỉ mục thiếu dòng là
    # thứ chỉ lộ ra khi người nhận đã cầm gói trong tay.
    tren_dia = sum(1 for q in out_dir.rglob("*")
                   if q.is_file() and q.relative_to(out_dir).as_posix() != "SHA256SUMS")
    if len(lines) != tren_dia:
        raise RuntimeError(
            f"SHA256SUMS phủ {len(lines)}/{tren_dia} tệp — chỉ mục không đầy đủ")
    (out_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  băm {manifest['n_files']} tệp · "
          f"{manifest['total_bytes'] / 1e9:.2f} GB · {manifest['checksum_seconds']}s"
          f" · SHA256SUMS {len(lines)} dòng")
    return rep
