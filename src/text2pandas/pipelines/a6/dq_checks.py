"""DP-018b — Kiểm chất lượng GÓI PHÁT HÀNH: trùng lặp, rỗng, lược đồ, mã hoá, quan hệ.

Khác với `quality.py`. Kia đo **ngữ nghĩa tài chính** (kỳ có đúng không, đẳng
thức Mã số có khớp không). Đây đo **tính toàn vẹn của gói**: người nhận copy về
máy có mở được không, JOIN có gãy không, chữ tiếng Việt có vỡ không.

Hai loại lỗi hoàn toàn khác nhau và không thay thế được cho nhau. Một gói có
99,33% đẳng thức khớp vẫn vô dụng nếu khoá ngoại gãy hoặc `row_path` vỡ dấu.

Mọi kiểm tra ở đây chạy trên silver.db **đã dựng xong**, không chạy trên nguồn.
Kiểm nguồn thì đo được cái ta đã biết; kiểm sản phẩm mới đo được cái người nhận
thực sự cầm trên tay.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

__all__ = ["run_dq_checks", "DQResult", "DQ_VERSION"]

DQ_VERSION = "1.0"

# Ký tự điều khiển không được xuất hiện trong văn bản đã làm sạch. Loại trừ
# tab/newline vì chúng hợp lệ trong ngữ cảnh nhiều dòng.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Dấu hiệu mojibake: UTF-8 bị đọc như Latin-1 rồi mã hoá lại.
_MOJIBAKE = re.compile(r"Ã[-¿]|â€[-]|Ä[-¿]")


@dataclass(slots=True)
class DQCheck:
    check_id: str
    category: str
    description: str
    value: int | str
    threshold: str
    passed: bool
    samples: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DQResult:
    checks: list[DQCheck] = field(default_factory=list)
    dq_version: str = DQ_VERSION

    @property
    def failed(self) -> list[DQCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_json(self) -> dict:
        return {
            "dq_version": self.dq_version,
            "n_checks": len(self.checks),
            "n_failed": len(self.failed),
            "checks": [
                {"check_id": c.check_id, "category": c.category,
                 "description": c.description, "value": c.value,
                 "threshold": c.threshold, "passed": c.passed,
                 "samples": c.samples[:5]}
                for c in self.checks
            ],
        }


def _rows(conn: sqlite3.Connection, sql: str, args=()) -> list[tuple]:
    return conn.execute(sql, args).fetchall()


def _scalar(conn: sqlite3.Connection, sql: str, args=()) -> int:
    r = conn.execute(sql, args).fetchone()
    return int(r[0]) if r and r[0] is not None else 0


def _add(res: DQResult, check_id: str, category: str, desc: str,
         value, threshold: str, passed: bool, samples=None) -> None:
    res.checks.append(DQCheck(check_id, category, desc, value, threshold,
                              passed, list(samples or [])))


# ─────────────────────────── 1. TRÙNG LẶP ───────────────────────────

def _check_duplicates(conn: sqlite3.Connection, res: DQResult, tables: tuple[str, ...]) -> None:
    """Khoá chính do SQLite bảo đảm; ta kiểm **khoá NGHIỆP VỤ**.

    Trùng khoá chính là không thể (ràng buộc chặn). Trùng khoá nghiệp vụ thì
    có thể, và nguy hiểm hơn: hai observation cùng trỏ về một ô lưới nghĩa là
    một giá trị bị đếm hai lần trong mọi phép tổng hợp xuôi dòng.
    """
    dup_obs = _rows(conn,
        "SELECT table_uid, grid_row_idx, grid_col_idx, COUNT(*) c"
        " FROM observations GROUP BY 1,2,3 HAVING c > 1 LIMIT 100")
    _add(res, "DQ-DUP-OBS-CELL", "duplicate",
         "hai observation cùng một ô lưới (giá trị bị đếm hai lần)",
         len(dup_obs), "0", not dup_obs,
         [f"{t}:r{r}c{c} ×{n}" for t, r, c, n in dup_obs])

    dup_doc = _rows(conn,
        "SELECT directory_doc_id, COUNT(*) c FROM documents"
        " GROUP BY 1 HAVING c > 1 LIMIT 20")
    _add(res, "DQ-DUP-DOC-ID", "duplicate",
         "`doc_id` trùng — sẽ làm chuỗi bằng chứng C20 mơ hồ",
         len(dup_doc), "0", not dup_doc, [d for d, _ in dup_doc])

    # KHÔNG kiểm "dòng trùng hoàn toàn" bằng `SELECT DISTINCT *`.
    #
    # Mọi bảng trong lược đồ phát hành đều có khoá chính, nên hai dòng giống
    # nhau hoàn toàn là điều SQLite đã chặn ở tầng ràng buộc — phép kiểm đó
    # **không thể đỏ**. Đổi lại nó bắt SQLite sắp xếp 2,57 triệu dòng × 33 cột
    # để khử trùng, mất vài phút và tốn cả GB vùng tạm.
    #
    # Một phép kiểm không bao giờ đỏ được thì không phải phép kiểm; nó là thuế.
    # Cái cần kiểm là khoá NGHIỆP VỤ mà khoá chính không phủ — đã làm ở
    # `DQ-DUP-OBS-CELL` và `DQ-DUP-DOC-ID` phía trên.
    for tbl in ("tables", "columns", "rows", "observations"):
        if tbl not in tables:
            continue
        has_pk = any(r[5] for r in _rows(conn, f"PRAGMA table_info({tbl})"))
        _add(res, f"DQ-PK-{tbl.upper()}", "duplicate",
             f"`{tbl}` có khoá chính (khoá chính chặn dòng trùng hoàn toàn)",
             "có" if has_pk else "KHÔNG", "có", has_pk)


# ────────────────────────── 2. GIÁ TRỊ RỖNG ──────────────────────────

# (bảng, cột, ngưỡng % tối đa được phép rỗng, phạm vi SQL, lý do)
#
# Phạm vi quan trọng ngang ngưỡng. Đo `rows.row_path_text` trên MỌI dòng cho ra
# 16,7% rỗng và trông như lỗi — nhưng dòng tiêu đề vốn không có đường dẫn chỉ
# tiêu, chúng không phải chỉ tiêu. Một kiểm tra đo sai phạm vi thì hoặc kêu oan
# hoặc im lặng, và cả hai đều làm người ta ngừng tin bộ kiểm tra.
_NULL_BUDGET: tuple[tuple[str, str, float, str, str], ...] = (
    ("observations", "value_decimal_text", 0.0, "1=1",
     "mọi observation phải có giá trị — nếu không thì nó không nên tồn tại"),
    ("observations", "evidence_ref", 0.0, "1=1", "trường được chấm theo C20"),
    ("observations", "row_path_text", 2.0, "1=1", "khoá truy hồi chính"),
    ("observations", "period_end", 10.0, "1=1", "kỳ báo cáo, kể cả suy diễn"),
    # Chỉ ô TIỀN mới bắt buộc có bậc 10. Phần trăm, số cổ phiếu, số ngày không
    # có bậc tiền tệ, và ép chúng phải có là đặt câu hỏi vô nghĩa.
    ("observations", "scale_exponent", 5.0, "value_kind='money'",
     "bậc đơn vị của ô tiền"),
    ("tables", "statement_type", 0.0, "1=1", "phân loại báo cáo"),
    ("tables", "evidence_ref", 0.0, "1=1", "trường được chấm theo C20"),
    ("documents", "ticker", 0.0, "1=1", "khoá lọc chính"),
    ("documents", "doc_year", 0.0, "1=1", "khoá lọc chính"),
    ("rows", "row_path_text", 5.0, "row_role <> 'header'",
     "khoá truy hồi (dòng tiêu đề không phải chỉ tiêu, không tính)"),
)


def _check_nulls(conn: sqlite3.Connection, res: DQResult, tables: tuple[str, ...]) -> None:
    """Rỗng không phải lúc nào cũng là lỗi — nhưng phải nằm trong NGÂN SÁCH.

    Đặt ngưỡng cho từng cột buộc ta phải biết trước mức rỗng nào là chấp nhận
    được. Đo rồi mới đặt ngưỡng thì ngưỡng chỉ mô tả hiện trạng, không phát
    hiện được hồi quy.
    """
    for tbl, col, budget, scope, why in _NULL_BUDGET:
        if tbl not in tables:
            continue
        n = _scalar(conn, f"SELECT COUNT(*) FROM {tbl} WHERE {scope}")
        if not n:
            continue
        n_null = _scalar(conn, f"SELECT COUNT(*) FROM {tbl}"
                               f" WHERE ({scope}) AND ({col} IS NULL OR {col}='')")
        pct = round(100 * n_null / n, 3)
        note = "" if scope == "1=1" else f" · phạm vi `{scope}`"
        _add(res, f"DQ-NULL-{tbl.upper()}-{col.upper()}", "null",
             f"`{tbl}.{col}` rỗng — {why}{note}",
             f"{pct}% ({n_null:,}/{n:,})", f"≤ {budget}%", pct <= budget)


# ─────────────────────── 3. LƯỢC ĐỒ & KIỂU DỮ LIỆU ───────────────────────

def _check_schema(conn: sqlite3.Connection, res: DQResult,
                  expected_tables: tuple[str, ...]) -> None:
    present = {r[0] for r in _rows(
        conn, "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [t for t in expected_tables if t not in present]
    _add(res, "DQ-SCHEMA-TABLES", "schema",
         "đủ bảng theo lược đồ phát hành", len(missing), "0", not missing, missing)

    # DI-05: giá trị tiền KHÔNG được lưu dạng REAL. `float64` chỉ giữ chính xác
    # 15–16 chữ số; corpus có số tới 10^15 và còn nhân hệ số đơn vị sau đó.
    real_cols: list[str] = []
    for tbl in expected_tables:
        if tbl not in present:
            continue
        for _, name, ctype, *_ in _rows(conn, f"PRAGMA table_info({tbl})"):
            if ("value" in name or "decimal" in name) and ctype.upper() in ("REAL", "FLOAT", "DOUBLE"):
                real_cols.append(f"{tbl}.{name} ({ctype})")
    _add(res, "DQ-SCHEMA-NO-REAL", "schema",
         "không cột giá trị nào lưu dạng REAL (DI-05)",
         len(real_cols), "0", not real_cols, real_cols)

    # Kiểu lưu THỰC TẾ, không phải kiểu khai báo — SQLite cho phép lệch.
    bad_typed = _scalar(conn,
        "SELECT COUNT(*) FROM observations"
        " WHERE value_decimal_text IS NOT NULL"
        "   AND typeof(value_decimal_text) <> 'text'")
    _add(res, "DQ-SCHEMA-DECIMAL-TEXT", "schema",
         "`value_decimal_text` lưu đúng kiểu TEXT trên từng dòng",
         bad_typed, "0", bad_typed == 0)

    n_idx = _scalar(conn,
        "SELECT COUNT(*) FROM sqlite_master WHERE type='index'"
        " AND name LIKE 'ix_%'")
    _add(res, "DQ-SCHEMA-INDEXES", "schema",
         "chỉ mục đã tạo (hợp đồng khai bắt buộc có)",
         n_idx, "≥ 15", n_idx >= 15)

    fk_on = _scalar(conn, "PRAGMA foreign_keys")
    _add(res, "DQ-SCHEMA-FK-ENABLED", "schema",
         "ràng buộc khoá ngoại đang bật", "bật" if fk_on else "TẮT",
         "bật", bool(fk_on))


# ─────────────────────────── 4. MÃ HOÁ ───────────────────────────

_TEXT_COLS = (
    ("documents", "directory_doc_id"), ("documents", "ticker"),
    ("tables", "section_text"), ("tables", "context_clean"),
    ("rows", "row_path_text"), ("rows", "label_clean"),
    ("observations", "row_path_text"), ("observations", "col_path_text"),
    ("observations", "value_source"),
)


def _check_encoding(conn: sqlite3.Connection, res: DQResult,
                    tables: tuple[str, ...], sample_limit: int = 200_000) -> None:
    """Tiếng Việt hỏng theo ba kiểu, và cả ba đều IM LẶNG.

    Không kiểu nào ném lỗi khi đọc; chúng chỉ làm truy hồi trượt. Một
    `row_path` ở dạng NFD trông giống hệt NFC trên màn hình nhưng khác byte,
    nên so khớp chuỗi trượt và BM25 tách token khác nhau.
    """
    n_control = n_nfd = n_moji = 0
    s_control: list[str] = []
    s_nfd: list[str] = []
    s_moji: list[str] = []
    for tbl, col in _TEXT_COLS:
        if tbl not in tables:
            continue
        for (v,) in _rows(conn,
                f"SELECT {col} FROM {tbl} WHERE {col} IS NOT NULL"
                f" LIMIT {sample_limit}"):
            if not isinstance(v, str) or not v:
                continue
            if _CONTROL.search(v):
                n_control += 1
                if len(s_control) < 5:
                    s_control.append(f"{tbl}.{col}: {v[:60]!r}")
            if unicodedata.normalize("NFC", v) != v:
                n_nfd += 1
                if len(s_nfd) < 5:
                    s_nfd.append(f"{tbl}.{col}: {v[:60]!r}")
            if _MOJIBAKE.search(v):
                n_moji += 1
                if len(s_moji) < 5:
                    s_moji.append(f"{tbl}.{col}: {v[:60]!r}")

    _add(res, "DQ-ENC-CONTROL", "encoding",
         "ký tự điều khiển trong văn bản đã làm sạch",
         n_control, "0", n_control == 0, s_control)
    _add(res, "DQ-ENC-NFC", "encoding",
         "chuỗi chưa chuẩn hoá NFC — làm so khớp chuỗi trượt im lặng",
         n_nfd, "0", n_nfd == 0, s_nfd)
    _add(res, "DQ-ENC-MOJIBAKE", "encoding",
         "dấu hiệu mojibake (UTF-8 đọc nhầm thành Latin-1)",
         n_moji, "0", n_moji == 0, s_moji)


# ────────────────────── 5. QUAN HỆ KHOÁ NGOẠI ──────────────────────

_RELATIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("tables", "document_uid", "documents", "document_uid", "bảng → tài liệu"),
    ("pages", "document_uid", "documents", "document_uid", "trang → tài liệu"),
    ("columns", "table_uid", "tables", "table_uid", "cột → bảng"),
    ("rows", "table_uid", "tables", "table_uid", "dòng → bảng"),
    ("observations", "table_uid", "tables", "table_uid", "observation → bảng"),
)


def _check_relations(conn: sqlite3.Connection, res: DQResult,
                     tables: tuple[str, ...]) -> None:
    for child, ckey, parent, pkey, label in _RELATIONS:
        if child not in tables or parent not in tables:
            continue
        orphans = _scalar(conn,
            f"SELECT COUNT(*) FROM {child} c WHERE NOT EXISTS"
            f" (SELECT 1 FROM {parent} p WHERE p.{pkey} = c.{ckey})")
        _add(res, f"DQ-FK-{child.upper()}-{parent.upper()}", "relationship",
             f"khoá ngoại mồ côi: {label}", orphans, "0", orphans == 0)

    # Khoá ngoại ghép — observation phải neo được về ĐÚNG ô lưới, không chỉ về bảng.
    for kind, idx, tgt in (("dòng", "grid_row_idx", "rows"),
                           ("cột", "grid_col_idx", "columns")):
        if tgt not in tables:
            continue
        orphans = _scalar(conn,
            f"SELECT COUNT(*) FROM observations o WHERE NOT EXISTS"
            f" (SELECT 1 FROM {tgt} t WHERE t.table_uid=o.table_uid"
            f"  AND t.{idx}=o.{idx})")
        _add(res, f"DQ-FK-OBS-{tgt.upper()}", "relationship",
             f"observation không neo được về {kind} lưới", orphans, "0",
             orphans == 0)

    # ── RC-06 · TÁCH "ngoài phạm vi" khỏi "lỗi parser" ──────────────────────
    #
    # Bản cũ đếm gộp rồi bắt phải bằng 0, nên tám công văn giải trình của PRT
    # — vốn không hề có markup bảng — làm cổng đỏ vĩnh viễn. Một cổng đỏ vì lý
    # do đã biết và không sửa được sẽ bị bỏ qua theo thói quen, và ngày nó đỏ
    # vì lý do THẬT thì không còn ai nhìn.
    #
    # Nay hỏi bằng hai câu khác hẳn nhau:
    #   ngoài phạm vi → không có markup nào trong văn bản gốc → KNOWN
    #   lỗi thật      → có markup mà không dựng được bảng nào → phải = 0
    have = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    empty_docs = _scalar(conn,
        "SELECT COUNT(*) FROM documents d WHERE NOT EXISTS"
        " (SELECT 1 FROM tables t WHERE t.document_uid = d.document_uid)")
    if "n_table_markup" not in have:
        # Silver cũ hơn RC-06: không có cột để phân biệt. Nói rõ là KHÔNG
        # BIẾT, đừng đoán — §15 cấm dựng bằng chứng.
        _add(res, "DQ-REL-DOC-NO-TABLE", "relationship",
             "tài liệu không có bảng nào (thiếu `n_table_markup` nên KHÔNG"
             " phân biệt được ngoài-phạm-vi với lỗi parser)",
             empty_docs, "0", empty_docs == 0)
    else:
        parse_failed = _scalar(conn,
            "SELECT COUNT(*) FROM documents"
            " WHERE n_tables = 0 AND n_table_markup > 0")
        out_of_scope = _scalar(conn,
            "SELECT COUNT(*) FROM documents"
            " WHERE n_tables = 0 AND n_table_markup = 0")
        # Đây mới là lỗi: markup có, bảng không ra.
        _add(res, "DQ-REL-DOC-PARSE-FAILED", "relationship",
             "tài liệu CÓ markup bảng nhưng không dựng được bảng nào",
             parse_failed, "0", parse_failed == 0)
        # Còn đây là hiện trạng đã biết — ghi lại để theo dõi, không chặn.
        _add(res, "DQ-REL-DOC-NO-MARKUP", "relationship",
             "tài liệu KHÔNG có markup bảng trong văn bản gốc (ngoài phạm vi)",
             out_of_scope, "KNOWN", True)
        # Bất biến review 28 đòi: không tài liệu nào rơi ra ngoài phân loại.
        #
        # Tên VIEW khác nhau giữa hai tầng — `document_classification` ở Bronze,
        # `v_document_classification` trong gói phát hành (tiền tố `v_` là quy
        # ước của release schema). Bản đầu chỉ hỏi tên Bronze, nên `run_dq_checks`
        # chạy trên release DB thì ném `no such table` và làm hỏng cả bước dựng
        # gói. Không unit test nào bắt được, vì fixture DQ dùng schema Bronze;
        # smoke run trên fixture corpus mới lộ ra.
        have_views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('view','table')")}
        view = next((v for v in ("document_classification",
                                 "v_document_classification")
                     if v in have_views), None)
        if view is None:
            _add(res, "DQ-REL-DOC-UNCLASSIFIED", "relationship",
                 "tài liệu không-có-bảng mà không nói được LÝ DO"
                 " (KHÔNG có view phân loại — không kiểm được)",
                 -1, "0", False)
        else:
            unclassified = _scalar(conn,
                f"SELECT COUNT(*) FROM {view}"
                " WHERE document_kind IS NULL"
                "    OR document_kind NOT IN"
                "       ('tabular','non_tabular','tabular_parse_failed','unknown')"
                "    OR (document_kind NOT IN ('tabular')"
                "        AND table_exclusion_reason IS NULL)")
            _add(res, "DQ-REL-DOC-UNCLASSIFIED", "relationship",
                 "tài liệu không-có-bảng mà không nói được LÝ DO",
                 unclassified, "0", unclassified == 0)

    pragma_fk = _rows(conn, "PRAGMA foreign_key_check")
    _add(res, "DQ-FK-PRAGMA", "relationship",
         "`PRAGMA foreign_key_check` của SQLite", len(pragma_fk), "0",
         not pragma_fk, [str(r) for r in pragma_fk[:5]])


# ─────────────────── 6. BẤT BIẾN NGHIỆP VỤ ───────────────────

def _check_invariants(conn: sqlite3.Connection, res: DQResult) -> None:
    """Bất biến đã trả giá để học. Mỗi cái tương ứng một lỗi từng xảy ra thật."""
    zero_from_dash = _scalar(conn,
        "SELECT COUNT(*) FROM observations"
        " WHERE value_decimal_text='0' AND value_source IN ('-','–','—','')")
    _add(res, "DQ-INV-DASH-NOT-ZERO", "invariant",
         "ô dash/rỗng biến thành 0 (DI-06) — 444.863 ô dash, điền 0 là bịa số liệu",
         zero_from_dash, "0", zero_from_dash == 0)

    giant = _scalar(conn,
        "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
        " AND ABS(CAST(value_decimal_text AS REAL)) > 1e16")
    _add(res, "DQ-INV-MAGNITUDE", "invariant",
         "giá trị tiền vượt 10^16 VND — hai ô số dính liền",
         giant, "0", giant == 0)

    bad_ref = _scalar(conn,
        "SELECT COUNT(*) FROM tables WHERE evidence_ref NOT LIKE '%|line:%'")
    _add(res, "DQ-INV-EVIDENCE-C20", "invariant",
         "`evidence_ref` sai định dạng `<doc_id>|<locator>` (C20)",
         bad_ref, "0", bad_ref == 0)

    bad_decimal = _scalar(conn,
        "SELECT COUNT(*) FROM observations WHERE value_decimal_text IS NOT NULL"
        " AND value_decimal_text NOT GLOB '-*[0-9]*'"
        " AND value_decimal_text NOT GLOB '[0-9]*'")
    _add(res, "DQ-INV-DECIMAL-FORMAT", "invariant",
         "`value_decimal_text` không phải chuỗi thập phân hợp lệ",
         bad_decimal, "0", bad_decimal == 0)


def run_dq_checks(conn: sqlite3.Connection, tables: tuple[str, ...]) -> DQResult:
    res = DQResult()
    conn.execute("PRAGMA foreign_keys=ON")
    _check_schema(conn, res, tables)
    _check_duplicates(conn, res, tables)
    _check_nulls(conn, res, tables)
    _check_encoding(conn, res, tables)
    _check_relations(conn, res, tables)
    _check_invariants(conn, res)
    return res
