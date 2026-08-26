"""DP-011 — D4e: dựng observations từ source cell, có provenance đầy đủ.

Luật quan trọng nhất của module: **duyệt SOURCE CELL, không duyệt lưới.**
Một ô số có `colspan=2` phủ hai vị trí lưới nhưng chỉ là một giá trị — duyệt
lưới sẽ tạo hai observation trùng. Bản prototype mắc đúng lỗi này.

Luật thứ hai: **không hard-exclude bằng classifier.** Bảng có
`is_data_table=false` vẫn sinh observation, chỉ gắn cờ. Phân loại bằng luật từ
khoá có lớp lỗi đã đo được; loại nhầm một bảng gold là mất recall không hồi
phục, còn gắn cờ nhầm chỉ tốn một lượt review.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from text2pandas.pipelines.a6.cleaning import clean_text
from text2pandas.pipelines.a6.html_parser import parse_table
from text2pandas.pipelines.a6.models import (
    ColumnRole,
    EvidenceSource,
    Observation,
    ParseStatus,
    RowRole,
    UnitKind,
    ValueKind,
    canonical_json,
    decimal_to_text,
    make_uid,
)
from text2pandas.pipelines.a6.number_parser import (
    SepConvention,
    classify_value_kind,
    detect_convention,
    is_percent_value_implausible,
    is_unit_ambiguous_share_cell,
    parse_number,
)
from text2pandas.pipelines.a6.period_resolver import (
    resolve_period,
    resolve_row_period,
    resolve_table_period,
)
from text2pandas.pipelines.a6.structure import interpret_structure
from text2pandas.pipelines.a6.tiny_money import (
    FALSE_VALUE_CLASSES, MIN_MONEY_VND, TINY_MONEY_VERSION, UNRESOLVED_CLASSES,
    classify_tiny_money)
from text2pandas.pipelines.a6.unit_resolver import (
    UnitResolution, reconcile_scale, resolve_unit)

_PERCENT_UNIT = UnitResolution(
    UnitKind.PERCENT, None, None, EvidenceSource.CELL,
    EvidenceSource.NONE, EvidenceSource.NONE)
_NON_MONEY_KINDS = {
    ValueKind.SHARE_COUNT, ValueKind.DAYS, ValueKind.INTEREST_RATE,
    ValueKind.QUANTITY, ValueKind.RATIO,
}
_KIND_TO_UNIT = {
    ValueKind.SHARE_COUNT: UnitKind.SHARES,
    ValueKind.DAYS: UnitKind.DAYS,
    ValueKind.INTEREST_RATE: UnitKind.RATE,
    ValueKind.QUANTITY: UnitKind.COUNT,
    ValueKind.RATIO: UnitKind.NONE,
}


def _kind_unit(kind: ValueKind) -> UnitResolution:
    return UnitResolution(
        _KIND_TO_UNIT.get(kind, UnitKind.UNKNOWN), None, None,
        EvidenceSource.CELL, EvidenceSource.NONE, EvidenceSource.NONE)

__all__ = ["BuildReport", "build_silver_tables", "SEMANTIC_VERSION"]

# 1.3 — nối `tiny_money` (RC-03). Nội dung observation đổi (ba lớp false-value
# chuyển sang `dropped_cells`), nên phiên bản ngữ nghĩa phải tăng: nó đi vào
# `build_id`, và một build cũ không được phép trông giống build mới.
SEMANTIC_VERSION = "1.4"

_PAGE = re.compile(r"^===== PAGE \d+ =====$")
_SECTION_TAIL = re.compile(
    r"(\d{1,2}(?:\.\d{1,2}){0,2})\s*[.)]?\s+([A-ZÀ-Ỹ][^.]{4,90}?)\s*$")
_SECTION_ANY = re.compile(
    r"(\d{1,2}(?:\.\d{1,2}){0,2})\s*[.)]\s+([A-ZÀ-Ỹ][^.]{4,90})")
_CTX_BEFORE = 12
_CTX_AFTER = 3
_WS = re.compile(r"\s+")
_HAS_DIGIT = re.compile(r"\d")

_SIG_CONS = ("hợp nhất", "HỢP NHẤT")
_SIG_SEP = ("riêng", "RIÊNG", "công ty mẹ")
_FORM_BANK = re.compile(r"B0[25]\s*/\s*TCTD", re.I)


@dataclass(slots=True)
class BuildReport:
    n_tables: int = 0
    n_parsed: int = 0
    n_too_large: int = 0
    n_failed: int = 0
    n_source_cells: int = 0
    n_grid_cells: int = 0
    n_observations: int = 0
    n_ambiguous: int = 0
    n_dash: int = 0
    n_unit_assumed: int = 0
    n_scale_rejected: int = 0
    n_dropped_cells: int = 0
    n_period_resolved: int = 0
    n_period_from_table: int = 0
    n_period_from_row_path: int = 0
    # RC-03 — `n_tiny_money_flagged` là số ca mà LUẬT CŨ `Q-OBS-TINY-MONEY`
    # bắt được (so ngưỡng trên giá trị thô). Giữ nguyên định nghĩa cũ để con
    # số này đối chiếu được với bản audit; kết quả phân loại nằm ở
    # `by_tiny_money_class`.
    n_tiny_money_flagged: int = 0
    n_tiny_money_dropped: int = 0
    n_tiny_money_unresolved: int = 0
    by_statement: dict[str, int] = field(default_factory=dict)
    by_value_kind: dict[str, int] = field(default_factory=dict)
    by_tiny_money_class: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0


def _context_window(lines: list[str], line_start_1: int, line_end_1: int) -> tuple[str, str]:
    before: list[str] = []
    i = line_start_1 - 2
    while i >= 0 and len(before) < _CTX_BEFORE:
        ln = lines[i].strip()
        i -= 1
        if not ln or ln.startswith("<table") or _PAGE.match(ln):
            continue
        before.append(ln)
    after: list[str] = []
    j = line_end_1
    while j < len(lines) and len(after) < _CTX_AFTER:
        ln = lines[j].strip()
        j += 1
        if not ln or ln.startswith("<table") or _PAGE.match(ln):
            continue
        after.append(ln)
    return " ".join(reversed(before)), " ".join(after)


def _extract_section(context: str) -> str:
    if not context:
        return ""
    ctx = _WS.sub(" ", context).strip()
    if m := _SECTION_TAIL.search(ctx):
        return f"{m.group(1)} {m.group(2).strip()}"
    hits = _SECTION_ANY.findall(ctx)
    if hits:
        num, title = hits[-1]
        return f"{num} {title.strip()}"
    return ""


def _column_digit_profile(pt, row_by_idx) -> dict[int, tuple[int, int]]:
    """Tín hiệu S3 của `tiny_money`, tính MỘT lần cho cả bảng.

    Trả `{grid_col_idx: (col_max_digits, peer_max_digits)}` — số chữ số dài
    nhất của chính cột, và của cột dài nhất **khác** nó trong cùng bảng.

    Tính ở đây thay vì trong `tiny_money` vì đây là tín hiệu cấp CỘT: gọi lại
    cho từng ô sẽ quét lại toàn bộ bảng vài trăm lần. Bỏ dòng header vì tiêu
    đề hay chứa năm (`2024`) — bốn chữ số đó không nói gì về độ lớn giá trị.
    """
    per_col: dict[int, int] = {}
    for c in pt.source_cells:
        row = row_by_idx.get(c.grid_row_idx)
        if row is None or row.row_role is RowRole.HEADER:
            continue
        n = sum(ch.isdigit() for ch in (c.text_clean or ""))
        if n and n > per_col.get(c.grid_col_idx, 0):
            per_col[c.grid_col_idx] = n
    if not per_col:
        return {}
    # `peer` = lớn nhất trong các cột CÒN LẠI. Lấy hai giá trị lớn nhất một
    # lần là đủ: nếu cột đang xét chính là cực đại thì peer là cực đại thứ hai.
    ordered = sorted(per_col.values(), reverse=True)
    top1 = ordered[0]
    top2 = ordered[1] if len(ordered) > 1 else 0
    return {ci: (v, top2 if v == top1 else top1) for ci, v in per_col.items()}


def _basis_from_text(text: str) -> str | None:
    cons = sum(text.count(s) for s in _SIG_CONS)
    sep = sum(text.count(s) for s in _SIG_SEP)
    if cons == 0 and sep == 0:
        return None
    if cons >= 2 * max(sep, 1):
        return "consolidated"
    if sep >= 2 * max(cons, 1):
        return "separate"
    return None


def build_silver_tables(
    bronze, silver, corpus_root: Path, offset: int = 0, limit: int = 0,
    grid_budget: int = 120_000, progress=None,
) -> BuildReport:
    """Quét theo TÀI LIỆU vì đặc trưng bảng phụ thuộc dòng ngữ cảnh phía trên."""
    t0 = time.time()
    rep = BuildReport()

    docs = bronze.execute(
        "SELECT document_uid, directory_doc_id, rel_path, ticker_path, year_path,"
        " basis_path FROM documents ORDER BY rel_path"
    ).fetchall()
    docs = docs[offset:]
    if limit:
        docs = docs[:limit]

    buf_tf, buf_sc, buf_gc, buf_rows, buf_cols, buf_obs = [], [], [], [], [], []
    buf_drop: list = []

    for k, (doc_uid, dir_doc_id, rel, ticker, doc_year, basis_path) in enumerate(docs, 1):
        text = (corpus_root / rel).read_text(encoding="utf-8")
        lines = text.split("\n")
        head = text[:200_000]
        basis_text = _basis_from_text(head)
        industry = "bank" if _FORM_BANK.search(head) else "corporate"

        tables = bronze.execute(
            "SELECT table_uid, line_start_1based, line_end_1based, raw_html"
            " FROM tables WHERE document_uid=? ORDER BY line_start_1based",
            (doc_uid,),
        ).fetchall()

        for tbl_uid, ls, le, raw_html in tables:
            rep.n_tables += 1
            pt = parse_table(tbl_uid, raw_html, grid_budget)
            rep.n_source_cells += len(pt.source_cells)
            rep.n_grid_cells += len(pt.grid_cells)

            ctx_before, ctx_after = _context_window(lines, ls, le)
            ctx_clean = clean_text(ctx_before).text_clean
            section = _extract_section(ctx_clean)

            if pt.parse_status is ParseStatus.TABLE_TOO_LARGE:
                rep.n_too_large += 1
            elif not pt.ok:
                rep.n_failed += 1
            else:
                rep.n_parsed += 1

            st = interpret_structure(pt, ctx_clean, section)
            rep.by_statement[st.statement_type] = (
                rep.by_statement.get(st.statement_type, 0) + 1)

            all_text = [c.text_clean for c in pt.source_cells]
            conv, n_dot, n_comma = detect_convention(all_text)
            sep_source = "table" if conv != SepConvention.UNKNOWN else "corpus_prior"
            if conv == SepConvention.UNKNOWN:
                conv = SepConvention.DOT   # quy ước áp đảo: 1.961/1.973 tài liệu

            table_text = " ".join(all_text)
            col_by_idx = {c.grid_col_idx: c for c in st.columns}
            col_unit: dict[int, UnitResolution] = {}
            col_unit_money: dict[int, UnitResolution] = {}
            row_by_idx = {r.grid_row_idx: r for r in st.rows}

            for col in st.columns:
                hdr = col.header_path_text
                per = resolve_period(hdr, doc_year, ctx_clean)
                col.period_start, col.period_end = per.period_start, per.period_end
                col.as_of_date, col.period_type = per.as_of_date, per.period_type
                col.period_role, col.period_source = per.period_role, per.source
                col.quarter, col.is_restated = per.quarter, per.is_restated
                unit = resolve_unit("", hdr, "", table_text, ctx_clean)
                col_unit[col.grid_col_idx] = unit
                # RC2-036 · bản đơn vị dành cho ô ĐÃ được kết luận là TIỀN.
                # Giải một lần cho mỗi cột, y như bản thường — không phải gọi
                # bảy lớp regex cho từng ô.
                col_unit_money[col.grid_col_idx] = resolve_unit(
                    "", hdr, "", table_text, ctx_clean, money_view=True)
                col.unit_kind, col.currency = unit.unit_kind, unit.currency
                col.scale_exponent = unit.scale_exponent
                if unit.assumed:
                    # RC-04 mục 3 — đổi tên, xem `unit_resolver.UnitResolution.flags`.
                    col.flags.append("unit_scale_assumed_no_evidence")
                if per.resolved:
                    rep.n_period_resolved += 1

            # ── rơi xuống kỳ cấp BẢNG theo thứ bậc bằng chứng ──
            # Thứ bậc là cell → column → row → table → section → document. Nhãn
            # cột là bậc `column`; khi nó im lặng, bậc kế tiếp còn hiệu lực là
            # `table`. Bảng thuyết minh dùng cột cho CHIỀU (`Nguyên giá`, `Hao
            # mòn luỹ kế`) và khai kỳ đúng một lần ở dòng ngữ cảnh.
            #
            # Điều kiện `all(... is None)` là ràng buộc an toàn, không phải tối
            # ưu: nếu bảng ĐÃ có cột mang ngày tường minh (bảng cân đối: `31/12`
            # và `01/01`), thì cột còn trống thuộc kỳ khác hoặc là chiều — gán
            # kỳ của bảng cho nó sẽ tạo giá trị sai kỳ, tệ hơn hẳn để trống.
            val_cols = [c for c in st.columns if c.column_role is ColumnRole.VALUE]
            if val_cols and all(c.period_end is None for c in val_cols):
                tper = resolve_table_period(ctx_clean, doc_year)
                if tper.resolved:
                    for c in val_cols:
                        c.period_start, c.period_end = tper.period_start, tper.period_end
                        c.as_of_date, c.period_type = tper.as_of_date, tper.period_type
                        c.period_role, c.period_source = tper.period_role, tper.source
                        c.is_restated = c.is_restated or tper.is_restated
                        c.flags.append("period_from_table")
                        rep.n_period_resolved += 1
                        rep.n_period_from_table += 1

            buf_tf.append((
                tbl_uid, doc_uid, dir_doc_id, ls, ticker, doc_year, basis_path,
                basis_text, industry, st.statement_type, st.statement_rule,
                int(st.is_data_table), st.numeric_ratio, len(pt.source_cells),
                pt.n_grid_rows, pt.n_grid_cols, st.n_header_rows,
                conv, sep_source, section, ctx_before[:2000], ctx_clean[:2000],
                pt.parse_status.value, canonical_json(st.flags + pt.diagnostics),
                # [F3] ghép bảng tách đôi — v1.3/v1.4
                None, None, None,
                # [F3] xuất xứ section — v1.1
                None, None, None,
            ))
            buf_sc += [(
                c.source_cell_uid, tbl_uid, c.source_row_idx, c.source_col_idx,
                c.grid_row_idx, c.grid_col_idx, c.rowspan, c.colspan,
                c.text_source, c.text_clean, canonical_json(c.clean_rules),
                c.clean_status.value,
            ) for c in pt.source_cells]
            buf_gc += [(
                g.table_uid, g.grid_row_idx, g.grid_col_idx, g.source_cell_uid,
                int(g.is_span_anchor), g.cell_role.value,
            ) for g in pt.grid_cells]
            buf_rows += [(
                r.table_uid, r.grid_row_idx, r.row_role.value, r.label_source,
                r.label_clean, canonical_json(r.row_path_json), r.row_path_text,
                r.row_level, r.metric_code, int(r.is_generic_label),
                canonical_json(r.flags),
                r.row_uid,
                # [F3] phân cấp — v1.2
                r.parent_row_uid, r.hierarchy_level, r.hierarchy_source,
                r.hierarchy_confidence, r.structural_role, r.accounting_role,
            ) for r in st.rows]
            buf_cols += [(
                c.table_uid, c.grid_col_idx, c.column_role.value,
                canonical_json(c.header_path_json), c.header_path_text,
                c.period_start, c.period_end, c.as_of_date, c.period_type.value,
                c.period_role.value, c.period_source.value, c.quarter,
                int(c.is_restated), c.unit_kind.value, c.currency,
                c.scale_exponent, c.numeric_ratio, canonical_json(c.flags),
                c.column_uid,
                # [F3] nhóm cột — v1.1
                c.parent_column_uid, c.column_group_source,
                c.column_group_confidence,
            ) for c in st.columns]

            digit_profile = _column_digit_profile(pt, row_by_idx)

            # ── observations: duyệt SOURCE CELL (anchor), không duyệt lưới ──
            for cell in pt.source_cells:
                col = col_by_idx.get(cell.grid_col_idx)
                row = row_by_idx.get(cell.grid_row_idx)

                def _drop(
                    reason: str,
                    detail: str | None = None,
                    *,
                    _cell=cell,
                    _table_uid=tbl_uid,
                ) -> None:
                    """Ghi LÝ DO một ô có chữ số không thành observation.

                    Chỉ ghi ô CÓ CHỮ SỐ: ô chữ thuần không bao giờ là ứng viên
                    số liệu nên ghi lại chỉ làm phình bảng audit.
                    """
                    if _HAS_DIGIT.search(_cell.text_clean or ""):
                        buf_drop.append((
                            _cell.source_cell_uid, _table_uid, _cell.grid_row_idx,
                            _cell.grid_col_idx, reason, detail,
                            (_cell.text_clean or "")[:120]))

                if col is None or row is None:
                    _drop("no_structure")
                    continue
                if row.row_role is RowRole.HEADER:
                    _drop("header_row")
                    continue
                if col.column_role in (ColumnRole.LABEL, ColumnRole.METRIC_CODE,
                                       ColumnRole.NOTE_REFERENCE,
                                       ColumnRole.ORDINAL):
                    _drop("non_value_column", col.column_role.value)
                    continue
                if not cell.text_clean.strip():
                    continue

                kind = classify_value_kind(
                    cell.text_clean, col.column_role.value,
                    col.header_path_text, "percent_header" in col.flags,
                    row_path=row.row_path_text or "")
                np_ = parse_number(cell.text_clean, conv, kind)
                if np_.status is ParseStatus.AMBIGUOUS:
                    rep.n_ambiguous += 1
                elif np_.status is ParseStatus.DASH:
                    rep.n_dash += 1
                if np_.status is not ParseStatus.OK:
                    _drop(f"parse_{np_.status.value}", np_.parse_rule)
                    continue

                # Đơn vị đã giải ở cấp CỘT; chỉ tính lại khi chính ô mang dấu
                # hiệu riêng (`%`) hoặc value-kind ép khác. Gọi resolve_unit cho
                # từng ô là 7 lớp regex × 2,5 triệu ô — không cần thiết và làm
                # đơn vị của các ô cùng cột có thể lệch nhau.
                if np_.value_kind is ValueKind.PERCENTAGE:
                    unit = _PERCENT_UNIT
                elif np_.value_kind in _NON_MONEY_KINDS:
                    unit = _kind_unit(np_.value_kind)
                else:
                    # `value_kind` ĐÃ qua cổng hình dạng và kết luận TIỀN; đơn
                    # vị phải nhất quán với kết luận đó. Xem RC2-036.
                    unit = col_unit_money[col.grid_col_idx]
                if unit.assumed:
                    rep.n_unit_assumed += 1

                # Bậc đơn vị giải ở cấp CỘT nên nó chưa từng nhìn thấy chữ số
                # của ô. Đây là chỗ duy nhất trong pipeline mà LỜI KHAI (bậc)
                # và BẰNG CHỨNG (độ lớn chữ số) gặp nhau — nên đối chiếu ở đây.
                obs_scale, obs_scale_src, scale_flag = reconcile_scale(
                    abs(np_.value_decimal) if np_.value_decimal is not None
                    else None,
                    np_.value_kind is ValueKind.MONEY,
                    unit.scale_exponent, unit.scale_source)

                flags = list(row.flags) + list(col.flags) + list(unit.flags)
                if scale_flag:
                    flags.append(scale_flag)
                    rep.n_scale_rejected += 1
                if not st.is_data_table:
                    flags.append("table_not_classified_as_data")
                if row.is_generic_label:
                    flags.append("generic_row_label")
                # ── A5-B2 · kỳ ở trục DÒNG, phương án CUỐI CÙNG ─────────
                #
                # Chỉ chạy khi cột KHÔNG có kỳ — nghĩa là `resolve_period` và
                # `resolve_table_period` đều đã bó tay. Điều kiện `p_end is
                # None` là ràng buộc an toàn chứ không phải tối ưu: nếu cột đã
                # mang kỳ thì kỳ của cột thắng, và ô này không đổi gì so với
                # A4. Nhờ vậy 2.448.169 ô đã có kỳ KHÔNG thể trôi, và blast
                # radius bị chặn cứng trong 185.385 ô hiện không có kỳ.
                #
                # Đo trước khi làm, trên A4: 9.528 ô nhận được kỳ; 19 ô trong
                # số đó rơi vào nhóm khoá ngữ nghĩa của một ô đã có kỳ với giá
                # trị khác, kéo 41 ô cũ vào va chạm mới, trong đó 8 ô đang
                # `execution_ready` sẽ mất ready. Mất 8 ô đó là ĐÚNG — chúng
                # thật sự trở nên không địa chỉ hoá được — nên không tìm cách
                # né, chỉ khai báo reason code cho differential.
                (p_start, p_end, p_asof, p_type, p_role, p_src, p_quarter,
                 p_restated) = (col.period_start, col.period_end,
                                col.as_of_date, col.period_type,
                                col.period_role, col.period_source,
                                col.quarter, col.is_restated)
                if p_end is None:
                    _rp = resolve_row_period(row.row_path_text or "",
                                             row.label_clean or "")
                    if _rp.resolved:
                        p_start, p_end = _rp.period_start, _rp.period_end
                        p_asof, p_type = _rp.as_of_date, _rp.period_type
                        p_role, p_src = _rp.period_role, _rp.source
                        p_restated = p_restated or _rp.is_restated
                        flags.append("period_from_row_path")
                        rep.n_period_from_row_path += 1
                if p_end is None:
                    flags.append("period_unresolved")
                # ── RC2-039 · đơn vị chưa kết luận trên cột "cổ phiếu" ────
                if is_unit_ambiguous_share_cell(
                        cell.text_clean, col.header_path_text,
                        row.row_path_text or "", bool(np_.is_negative)):
                    flags.append("unit_ambiguous_share_column")
                # ── A5-A2 · độ lớn không thể là phần trăm ─────────────────
                # Giữ observation, chặn ready. Xem `PERCENT_ABS_MAX`.
                if is_percent_value_implausible(np_.value_kind,
                                                np_.value_decimal):
                    flags.append("percent_value_implausible")
                if col.column_role is ColumnRole.UNKNOWN:
                    # DI-02 cấm loại cứng, nên cột chưa phân loại vẫn sinh
                    # observation. Nhưng cổng kỳ chỉ đếm cột `value`, nên nếu
                    # không gắn cờ thì 5.684 observation này vô hình với mọi
                    # thước đo — có mặt trong dữ liệu, vắng mặt trong báo cáo.
                    flags.append("column_role_unknown")

                # ── RC-03 · Q-OBS-TINY-MONEY, xử lý chứ không chỉ gắn cờ ─────
                #
                # Điều kiện kích hoạt cố tình giữ NGUYÊN luật cũ — `|giá trị
                # THÔ| < 1.000` — để con số ở đây đối chiếu được với 2.836 ca
                # của bản audit. Việc *sửa thước đo* (áp scale trước khi so)
                # nằm trong `classify_tiny_money`, và nó trả về
                # `legitimate_small_money` cho đúng nhóm 740 ca mà luật cũ
                # buộc tội oan.
                #
                # Giá trị 0 KHÔNG vào đây: 0 là một con số hợp lệ trong báo
                # cáo tài chính, và DI-06 đã tách nó khỏi dấu gạch.
                dec = np_.value_decimal
                if (np_.value_kind is ValueKind.MONEY and dec is not None
                        and dec != 0 and abs(dec) < MIN_MONEY_VND):
                    rep.n_tiny_money_flagged += 1
                    cmax, pmax = digit_profile.get(cell.grid_col_idx, (None, None))
                    tm_class, tm_reason = classify_tiny_money(
                        value_decimal_text=decimal_to_text(dec),
                        value_source=np_.value_source,
                        scale_exponent=obs_scale,
                        unit_kind=unit.unit_kind.value,
                        scale_source=obs_scale_src.value,
                        header_path_text=col.header_path_text,
                        row_label=row.label_clean,
                        col_max_digits=cmax, peer_max_digits=pmax)
                    rep.by_tiny_money_class[tm_class] = (
                        rep.by_tiny_money_class.get(tm_class, 0) + 1)

                    if tm_class in FALSE_VALUE_CLASSES:
                        # KHÔNG phải hard-delete theo nghĩa DI-02 cấm: ô đi
                        # vào `dropped_cells` cùng lý do và văn bản gốc, nên
                        # nó vẫn đếm được trong bất biến "không mất mát" và
                        # vẫn truy ngược được về `source_cell_uid`.
                        _drop(f"tiny_money_{tm_class}", tm_reason)
                        rep.n_tiny_money_dropped += 1
                        continue
                    if tm_class in UNRESOLVED_CLASSES:
                        # Giữ observation, chặn khỏi `execution_ready`. Cờ này
                        # là cờ mà `readiness_policy_v1.yaml` đã khai sẵn ở
                        # `blocking_flags`.
                        flags.append("tiny_money_unresolved")
                        rep.n_tiny_money_unresolved += 1
                    else:
                        flags.append("tiny_money_legitimate")

                obs_uid = make_uid(tbl_uid, cell.source_cell_uid)
                buf_obs.append((
                    obs_uid, tbl_uid, cell.source_cell_uid,
                    cell.grid_row_idx, cell.grid_col_idx,
                    canonical_json(row.row_path_json), row.row_path_text,
                    canonical_json(col.header_path_json), col.header_path_text,
                    row.label_source, row.label_clean, row.metric_code,
                    np_.value_source, np_.value_clean,
                    decimal_to_text(np_.value_decimal),
                    np_.value_kind.value, np_.status.value, np_.parse_rule,
                    int(np_.is_negative), unit.unit_kind.value, unit.currency,
                    obs_scale, unit.unit_kind_source.value,
                    unit.currency_source.value, obs_scale_src.value,
                    p_start, p_end, p_asof,
                    p_type.value, p_role.value,
                    p_src.value, p_quarter, int(p_restated),
                    doc_year, canonical_json({}), canonical_json(sorted(set(flags))),
                    row.row_uid, col.column_uid,
                ))
                rep.n_observations += 1
                rep.by_value_kind[np_.value_kind.value] = (
                    rep.by_value_kind.get(np_.value_kind.value, 0) + 1)

        if len(buf_tf) >= 300:
            _flush(silver, buf_tf, buf_sc, buf_gc, buf_rows, buf_cols, buf_obs, buf_drop)
            if progress:
                progress(k, rep.n_tables, rep.n_observations)

    _flush(silver, buf_tf, buf_sc, buf_gc, buf_rows, buf_cols, buf_obs, buf_drop)
    silver.commit()
    rep.seconds = round(time.time() - t0, 1)
    return rep


def _flush(conn, tf, sc, gc, rows, cols, obs, drop) -> None:
    def many(sql: str, buf: list) -> None:
        if buf:
            conn.executemany(sql, buf)
            buf.clear()

    many("INSERT OR REPLACE INTO table_features VALUES (" + ",".join("?" * 30) + ")", tf)
    many("INSERT OR REPLACE INTO source_cells   VALUES (" + ",".join("?" * 12) + ")", sc)
    many("INSERT OR REPLACE INTO grid_cells     VALUES (" + ",".join("?" * 6) + ")", gc)
    many("INSERT OR REPLACE INTO rows           VALUES (" + ",".join("?" * 18) + ")", rows)
    many("INSERT OR REPLACE INTO columns        VALUES (" + ",".join("?" * 22) + ")", cols)
    many("INSERT OR REPLACE INTO observations   VALUES (" + ",".join("?" * 38) + ")", obs)
    many("INSERT OR REPLACE INTO dropped_cells  VALUES (" + ",".join("?" * 7) + ")", drop)
    conn.commit()
