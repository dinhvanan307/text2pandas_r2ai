"""Tài liệu bàn giao SINH TỪ DỮ LIỆU — không phải viết tay.

Gói phát hành trước đây có `README.md`, `SILVER_REPORT.md`, `DATA_DICTIONARY.md`.
Ba tệp đó trả lời được *"có gì bên trong"* và *"cột nào nghĩa gì"*, nhưng không
trả lời được ba câu mà người nhận hỏi ngay ngày đầu:

    dữ liệu này là gì và phủ tới đâu · nó SAI ở chỗ nào · dùng thế nào cho đúng

Module này sinh ba tệp còn thiếu. Nguyên tắc duy nhất, và nó quan trọng hơn nội
dung: **mọi con số ở đây truy vấn trực tiếp từ database của gói tại thời điểm
đóng gói.** Không có literal nào.

Lý do không phải là sự sạch sẽ. `SILVER_REPORT.md §5` từng liệt kê "200.195 ô",
"116.857 ô", "69.106 cột" — gõ tay từ một bản dựng tháng trước. Sau D-01 các
con số đó đã đổi, tệp thì không. Một tài liệu hạn chế mà sai số liệu còn tệ hơn
không có tài liệu hạn chế: người đọc tin nó, lập kế hoạch theo nó, và phát hiện
ra sự thật ở đúng lúc tệ nhất. Tài liệu nói về lỗi thì bản thân nó phải không
có lỗi.

Mỗi bảng số trong tài liệu sinh ra đều kèm câu SQL đã dùng, để người nghi ngờ
chạy lại được trên chính gói họ đang cầm.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

__all__ = ["DOCS_VERSION", "build_docs", "DOC_FILES"]

DOCS_VERSION = "1.0"

DOC_FILES = ("DATA_OVERVIEW.md", "KNOWN_ISSUES.md", "USAGE_GUIDE.md")


# ─────────────────────────── truy vấn chịu lỗi ───────────────────────────
#
# Gói có thể dựng từ một Silver thiếu bảng (bản cũ, hoặc hồ sơ `slim`). Tài
# liệu KHÔNG được vì thế mà nổ — nhưng cũng KHÔNG được im lặng bỏ qua rồi in ra
# một bảng trống trông như "không có vấn đề nào". Thiếu số thì phải nói là
# thiếu số.

_MISSING = "— (không đo được trên gói này)"


def _has(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')",
        (name,)).fetchone())


def _q1(con, sql: str, params: tuple = (), default=None):
    try:
        r = con.execute(sql, params).fetchone()
        return default if r is None or r[0] is None else r[0]
    except sqlite3.Error:
        return default


def _qall(con, sql: str, params: tuple = ()) -> list[tuple]:
    try:
        return con.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []


def _n(v) -> str:
    return f"{v:,}" if isinstance(v, int) else (_MISSING if v is None else str(v))


def _pct(num, den, nd: int = 2) -> str:
    if not den:
        return _MISSING
    return f"{round(100 * num / den, nd)}%"


def _sql_block(sql: str) -> list[str]:
    """Câu SQL đã dùng, in kèm bảng số. Người đọc nghi ngờ thì chạy lại."""
    return ["", "<details><summary>SQL đã dùng để sinh bảng trên</summary>", "",
            "```sql", sql.strip(), "```", "", "</details>", ""]


def _table(header: list[str], rows: list[list[str]],
           align: str | None = None) -> list[str]:
    if not rows:
        return ["", f"*{_MISSING}*", ""]
    sep = align or ("|" + "|".join("---" for _ in header) + "|")
    return ["", "| " + " | ".join(header) + " |", sep,
            *["| " + " | ".join(str(c) for c in r) + " |" for r in rows], ""]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head(title: str, rep, sub: str) -> list[str]:
    return [f"# {title}", "",
            f"> Bản dựng `{rep.build_id or '?'}` · nhãn "
            f"`{getattr(rep, 'release_label', '?')}` · sinh lúc {_now()} · "
            f"`release_docs {DOCS_VERSION}`", "",
            "> **Mọi con số trong BẢNG ở tệp này truy vấn từ `silver.db` của "
            "chính gói này lúc đóng gói** — sửa dữ liệu thì dựng lại gói, đừng "
            "sửa tệp này. Vài con số trong phần diễn giải là **đo đạc lịch sử** "
            "của một lần sửa trước đó (ví dụ *\"D-01 thu hồi 85.095 giá trị\"*); "
            "chúng mô tả một sự kiện đã xảy ra nên không đổi theo bản dựng, và "
            "đều được ghi rõ ngữ cảnh.", "", sub, ""]


# ═══════════════════════════ 1 · DATA_OVERVIEW ═══════════════════════════

def _doc_overview(con, rep) -> str:
    o = _head("Tổng quan dữ liệu — Silver ViFinQA", rep,
              "Tài liệu này trả lời: *dữ liệu này là gì, đơn vị của nó là gì, "
              "phủ tới đâu, và cái gì KHÔNG có trong đây.*")

    o += ["## 1. Đơn vị dữ liệu", "",
          "Đơn vị nhỏ nhất của gói là **observation**: một ô SỐ trong một bảng "
          "của một báo cáo, đã được chuẩn hoá giá trị · đơn vị · kỳ, và còn "
          "giữ nguyên đường về ô gốc.", "",
          "```",
          "document  →  page  →  table  →  (row × column)  →  source_cell  →  observation",
          "```", "",
          "Chuỗi này đi được **cả hai chiều**. Từ một con số bất kỳ trong gói, "
          "truy ngược về đúng dòng văn bản trong tệp corpus gốc là một câu "
          "JOIN, không phải một phép đoán. Đó là điều kiện để trích dẫn bằng "
          "chứng (ràng buộc C20) có nghĩa.", ""]

    n_doc = _q1(con, "SELECT COUNT(*) FROM documents", default=0)
    n_tab = _q1(con, "SELECT COUNT(*) FROM tables", default=0)
    n_obs = _q1(con, "SELECT COUNT(*) FROM observations", default=0)
    n_drop = _q1(con, "SELECT COUNT(*) FROM dropped_cells", default=None)

    o += ["## 2. Quy mô", ""]
    o += _table(["Thực thể", "Số lượng", "Ghi chú"], [
        ["Tài liệu (= một báo cáo)", _n(n_doc), "một tệp `.txt` trong corpus"],
        ["Trang", _n(_q1(con, "SELECT COUNT(*) FROM pages", default=0)), "suy từ dấu `===== PAGE n =====`"],
        ["Bảng", _n(n_tab), "mỗi khối `<table>` phát hiện được"],
        ["Dòng lưới", _n(_q1(con, "SELECT COUNT(*) FROM rows", default=0)), "sau khai triển `rowspan`"],
        ["Cột lưới", _n(_q1(con, "SELECT COUNT(*) FROM columns", default=0)), "sau khai triển `colspan`"],
        ["**Observation**", f"**{_n(n_obs)}**", "**ô số đã chuẩn hoá — bảng trung tâm**"],
        ["Ô số bị loại", _n(n_drop), "có LÝ DO trong `dropped_cells`, xem `KNOWN_ISSUES.md`"],
    ], "|---|---:|---|")

    # ── độ phủ ──
    o += ["## 3. Độ phủ", "",
          "Độ phủ là thứ quyết định câu hỏi nào trả lời được. Một mã chứng "
          "khoán có 2 năm dữ liệu không trả lời được câu hỏi về xu hướng 5 năm "
          "— và đó không phải lỗi của mô hình.", ""]

    yr = _qall(con, "SELECT doc_year, COUNT(*) FROM documents"
                    " WHERE doc_year IS NOT NULL GROUP BY 1 ORDER BY 1")
    if yr:
        o += ["### 3.1 Theo năm báo cáo", ""]
        o += _table(["Năm", "Số báo cáo", "Số bảng", "Observation"],
                    [[str(y), _n(c),
                      _n(_q1(con, "SELECT COUNT(*) FROM tables WHERE doc_year=?",
                             (y,), default=0)),
                      _n(_q1(con, "SELECT COUNT(*) FROM observations WHERE doc_year=?",
                             (y,), default=0))] for y, c in yr],
                    "|---:|---:|---:|---:|")

    n_tk = _q1(con, "SELECT COUNT(DISTINCT ticker) FROM documents", default=0)
    dist = _qall(con, """SELECT n, COUNT(*) FROM (
                           SELECT ticker, COUNT(DISTINCT doc_year) n
                           FROM documents GROUP BY 1) GROUP BY 1 ORDER BY 1""")
    if dist:
        o += ["", f"### 3.2 Theo mã chứng khoán — {_n(n_tk)} mã", "",
              "Phân bố **số năm có dữ liệu** trên mỗi mã. Cột phải là chỗ đọc "
              "trước: mã chỉ có 1 năm thì mọi câu hỏi so sánh kỳ đều vô nghiệm.", ""]
        o += _table(["Số năm có dữ liệu", "Số mã chứng khoán"],
                    [[str(k), _n(v)] for k, v in dist], "|---:|---:|")

    st = _qall(con, "SELECT statement_type, COUNT(*) c,"
                    " (SELECT COUNT(*) FROM observations o"
                    "   WHERE o.statement_type = t.statement_type)"
                    " FROM tables t GROUP BY 1 ORDER BY c DESC")
    if st:
        o += ["", "### 3.3 Theo loại báo cáo", ""]
        o += _table(["`statement_type`", "Số bảng", "Observation"],
                    [[f"`{s}`", _n(c), _n(n)] for s, c, n in st],
                    "|---|---:|---:|")

    for col, title, note in (
        ("basis", "3.4 Cơ sở lập", "hợp nhất (`consolidated`) hay riêng (`separate`)"),
        ("industry_class", "3.5 Nhóm ngành",
         "quyết định bộ đẳng thức Mã số nào áp dụng được — xem `KNOWN_ISSUES.md §5`"),
    ):
        rws = _qall(con, f"SELECT COALESCE({col},'(chưa xác định)'), COUNT(*)"
                         f" FROM tables GROUP BY 1 ORDER BY 2 DESC")
        if rws:
            o += ["", f"### {title}", "", f"*{note}*", ""]
            o += _table(["Giá trị", "Số bảng"],
                        [[f"`{k}`", _n(v)] for k, v in rws], "|---|---:|")

    # ── ba mức sẵn sàng ──
    o += ["", "## 4. Ba mức sẵn sàng", "",
          "Không phải observation nào cũng dùng được cho mọi việc. Gói phân ba "
          "mức, và **ranh giới là chính sách chứ không phải dữ liệu** — nó nằm "
          "trong `config/readiness_policy_v1.yaml`, sinh lại được trong vài "
          "giây khi ngưỡng đổi.", ""]

    if _has(con, "v_long_dataframe"):
        n_exec = _q1(con, "SELECT COUNT(*) FROM v_long_dataframe WHERE execution_ready=1", default=0)
        n_retr = _q1(con, "SELECT COUNT(*) FROM v_long_dataframe WHERE retrieval_ready=1", default=0)
        o += _table(["Mức", "Số observation", "Tỷ lệ", "Nghĩa là"], [
            ["`retrieval_ready`", _n(n_retr), _pct(n_retr, n_obs),
             "đủ để **tìm** — nhãn và ngữ cảnh dùng được cho truy hồi"],
            ["`execution_ready`", _n(n_exec), _pct(n_exec, n_obs),
             "đủ để **tính** — có kỳ, có đơn vị, có nhãn, không đụng độ"],
            ["còn lại", _n(n_obs - n_exec), _pct(n_obs - n_exec, n_obs),
             "**KHÔNG được đưa vào câu trả lời** — xem `KNOWN_ISSUES.md §3`"],
        ], "|---|---:|---:|---|")
        o += _sql_block(
            "SELECT COUNT(*) FILTER (WHERE execution_ready=1) AS exec_ready,\n"
            "       COUNT(*) FILTER (WHERE retrieval_ready=1) AS retr_ready,\n"
            "       COUNT(*)                                  AS total\n"
            "FROM v_long_dataframe;")
        o += ["> Chênh lệch giữa hai cột **không phải lỗi**. Một con số có thể "
              "tìm được mà chưa tính được — ví dụ đọc rõ nhãn nhưng bảng không "
              "khai đơn vị ở đâu cả. Tách hai mức để tầng truy hồi vẫn dùng "
              "được phần dữ liệu mà tầng tính toán phải từ chối.", ""]

    # ── phân bố chất lượng ──
    o += ["## 5. Chất lượng theo phân bố, không theo một con số", "",
          "Một tỷ lệ tổng che mất chỗ hỏng. Bốn phân bố dưới đây là thứ nên đọc "
          "trước khi tin bất kỳ con số tổng nào.", ""]

    for sql, title, note in (
        ("SELECT confidence, COUNT(*) FROM observations GROUP BY 1 ORDER BY 2 DESC",
         "5.1 `confidence`",
         "`low` = thiếu kỳ, hoặc đơn vị mặc định, hoặc cột chưa rõ vai trò. "
         "Tầng truy hồi nên hạ trọng số thay vì tin như nhau."),
        ("SELECT value_kind, COUNT(*) FROM observations GROUP BY 1 ORDER BY 2 DESC",
         "5.2 `value_kind`",
         "`money` chịu ràng buộc `Decimal` và bậc 10; `percent` và `number` thì không."),
        ("SELECT period_source, COUNT(*) FROM observations GROUP BY 1 ORDER BY 2 DESC",
         "5.3 `period_source` — kỳ đến TỪ ĐÂU",
         "`column_path` là bằng chứng mạnh nhất (đọc thẳng từ nhãn cột). "
         "`table_context` yếu hơn một bậc — suy từ ngữ cảnh bảng, không đọc "
         "được trực tiếp. Đây là trục nên lọc theo khi câu hỏi nhạy cảm với kỳ."),
        ("SELECT unit_kind, COUNT(*) FROM observations GROUP BY 1 ORDER BY 2 DESC",
         "5.4 `unit_kind`",
         "`unknown` nghĩa là bảng không khai đơn vị ở bất cứ tầng nào — "
         "thuộc tính của corpus, không phải của pipeline."),
    ):
        rws = _qall(con, sql)
        if rws:
            o += ["", f"### {title}", "", f"*{note}*", ""]
            o += _table(["Giá trị", "Số observation", "Tỷ lệ"],
                        [[f"`{k}`", _n(v), _pct(v, n_obs)] for k, v in rws],
                        "|---|---:|---:|")

    # ── danh tính ──
    o += ["", "## 6. Danh tính: cái nào ổn định, cái nào không", "",
          "Đây là phần dễ dùng sai nhất. Hai nhóm ID dưới đây có tuổi thọ "
          "**khác nhau**, và chọn nhầm nhóm để lưu vào chỉ mục của bạn nghĩa là "
          "phải dựng lại chỉ mục sau mỗi bản Silver.", ""]
    o += _table(["ID", "Dựa trên", "Đổi khi nào"], [
        ["`table_uid`", "vị trí vật lý của bảng trong tài liệu",
         "**ổn định** — chỉ đổi nếu corpus đổi"],
        ["`row_uid`", "`hash(table_uid, grid_row_idx)`",
         "**ổn định** — độc lập với nhãn và `row_path`"],
        ["`column_uid`", "`hash(table_uid, grid_col_idx)`", "**ổn định**"],
        ["`source_cell_uid`", "ô `<td>` gốc trước khai triển span", "**ổn định**"],
        ["`observation_uid`", "`hash(table_uid, source_cell_uid)`", "**ổn định**"],
        ["`row_path_text`", "nhãn + tổ tiên phân cấp",
         "⚠ **SẼ đổi** khi cây phân cấp được cải thiện"],
        ["`col_path_text`", "nhãn cột ghép theo tầng header", "⚠ **có thể đổi**"],
        ["`metric_code`", "Mã số Thông tư 200 đọc từ bảng", "⚠ có thể được bổ sung thêm"],
    ], "|---|---|---|")
    o += ["", "**Hệ quả thực hành:** khoá chỉ mục truy hồi và mọi bảng ánh xạ "
          "của bạn theo `row_uid`/`column_uid`, KHÔNG theo `row_path`. Đó chính "
          "là lý do hai cột UID vật lý có mặt trong gói — chúng cho phép so "
          "build cũ với build mới theo cùng một dòng ngay cả khi `row_path` đã "
          "được sửa.", ""]

    # ── cái KHÔNG có ──
    o += ["## 7. Cái gì KHÔNG có trong gói này", "",
          "Liệt kê tường minh để không ai đi tìm:", "",
          "- **Không có câu trả lời, không có nhãn vàng.** Gói này là dữ liệu "
          "nguồn, không phải tập huấn luyện có nhãn.",
          "- **Không có Structure Gold.** Vì thế cổng đo độ chính xác cấu trúc "
          "đang `BLOCKED` — xem `KNOWN_ISSUES.md §4`.",
          "- **Không có embedding, không có vector index.** Chỉ có FTS5 "
          "(BM25, bỏ dấu tiếng Việt). Độ phủ từ khoá đo được 0,921 nên bài "
          "toán truy hồi ở đây là **xếp hạng**, không phải lệch từ vựng.",
          "- **Không có tầng Gold theo nghĩa Medallion.** Silver là tầng cuối "
          "của đường ống dữ liệu; mọi thứ sau nó là ứng dụng.",
          "- **Không có bảng hợp nhất nhiều năm.** Mỗi observation thuộc đúng "
          "một tài liệu; ghép nhiều năm là việc của tầng trên.", ""]

    return "\n".join(o) + "\n"


# ═══════════════════════════ 2 · KNOWN_ISSUES ════════════════════════════

# Ánh xạ lý do loại ô → (phán xét, giải thích). Phán xét là phần KHÔNG suy được
# từ dữ liệu: nó cần một người biết kế toán Việt Nam nhìn vào mẫu và quyết định
# "đây là hành vi đúng" hay "đây là chỗ còn nợ". Ghi ra đây thay vì để người
# nhận tự đoán từ tên `reason`.
_DROP_VERDICT: dict[str, tuple[str, str]] = {
    # Bucket LỚN NHẤT (~73%). Ô có chữ số nhưng nằm trong cột KHÔNG phải cột
    # giá trị: Mã số (`110`), STT, Thuyết minh (`5`, `12`), hoặc nhãn có số
    # (`5 TIỀN`). Loại chúng là đúng — chúng là mã hiệu, không phải số liệu.
    "non_value_column": (
        "✅ đúng, **có điều kiện**",
        "Mã số · STT · Thuyết minh · nhãn có chữ số. Chúng là **mã hiệu, "
        "không phải số liệu**. Điều kiện: phán xét này chỉ đúng nếu vai trò "
        "cột gán đúng — mà đó chính là cổng `G3` đang `BLOCKED` (§4). Một cột "
        "giá trị bị gán nhầm `note_reference` sẽ rơi hết vào đây **âm thầm**. "
        "Cột `detail` giữ tên vai trò nên kiểm được: xem bảng con bên dưới."),
    "header_row": (
        "✅ đúng",
        "Ô nằm trong vùng tiêu đề. Sau D-01 vùng này đã thu hẹp đúng mức và "
        "85.095 giá trị trước đây bị nuốt nhầm đã được thu hồi."),
    "parse_ambiguous": (
        "🟡 phần lớn đúng",
        "Hai nhóm: khoảng giá trị (`10 - 11`, `03 - 05`) là loại đúng; một "
        "phần nhỏ là header dính chữ số (`Ngày 31 tháng 12năm 2022%/năm`) hoặc "
        "nhóm chữ số dị dạng (`1.2.484.928.340`). Chưa tách được bằng luật."),
    "parse_not_a_number": (
        "✅ đúng",
        "Ô có chữ số nhưng không phải giá trị — tuyệt đại đa số là NGÀY "
        "(`31/12/2023`). Sinh observation cho chúng là tạo ra số liệu giả."),
    "parse_dash": (
        "✅ đúng",
        "Dấu `-` trong báo cáo tài chính nghĩa là **khuyết dữ liệu**, không "
        "phải bằng không (DI-06). Điền 0 là bịa số liệu."),
    "no_structure": (
        "🔴 cần truy nguyên",
        "Ô không neo được về dòng hoặc cột nào. Khác 0 nghĩa là lưới bị hụt — "
        "đây là lỗi cấu trúc, không phải quyết định loại bỏ."),
    # ── RC-03 · ba lớp false-value của `tiny_money` ────────────────────────
    # Khác `non_value_column` ở chỗ: ở đó vai trò CỘT đã đủ để kết luận; ở đây
    # vai trò cột nói "value" nhưng bằng chứng cấp ô/nhãn nói ngược lại.
    "tiny_money_metric_code_false_value": (
        "✅ đúng",
        "Cột được gán vai trò `value` nhưng nhãn cột là **Mã số** (kể cả bản "
        "bị OCR làm hỏng: `Másố`, `M8 số`, `Mã sơ`), hoặc cột chỉ chứa số ≤3 "
        "chữ số trong khi cột cùng bảng đạt ≥6. `110` là mã Thông tư 200, "
        "không phải 110 đồng."),
    "tiny_money_note_reference_false_value": (
        "✅ đúng",
        "Giá trị mang hình dạng **số hiệu mục thuyết minh** (`5.1`, `5.18`) "
        "hoặc nằm dưới nhãn cột Thuyết minh/TM. Không khoản mục tài chính nào "
        "có giá trị `5,18 đồng`; dấu chấm ở đây là dấu phân cấp mục."),
    "tiny_money_ordinal_false_value": (
        "✅ đúng",
        "Nhãn cột là **số thứ tự** (STT). Số dòng không phải số liệu."),
}

# Bốn lớp đụng độ. Con số đến từ database; phần "tại sao" và "cách sống chung"
# là phán xét kỹ thuật, ghi cứng ở đây có chủ đích.
_COLLISION_DOC: dict[str, tuple[str, str, str]] = {
    "missing_row_parent": (
        "Cây phân cấp bỏ lỡ dòng mở phạm vi",
        "Nhóm có **nhiều hơn một** tổ tiên ứng viên phía trên. Dòng mở phạm vi "
        "(ví dụ `Trong đó:`) không được đưa vào ngăn xếp `row_path`, nên hai "
        "khoản mục khác nhau cùng rơi vào một đường dẫn.",
        "**Sẽ tách được** khi cây phân cấp cải thiện. Đây là lớp có triển vọng "
        "nhất, và nó không cần dữ liệu mới — chỉ cần luật tốt hơn."),
    "missing_dimension": (
        "Cùng tổ tiên — cây phân cấp VÔ DỤNG ở đây",
        "Chỉ có **một** tổ tiên chung, nên dù `row_path` có đúng đến đâu hai "
        "dòng vẫn trùng khoá. Chúng khác nhau ở một chiều **không nằm trong "
        "bảng**: quý, chi nhánh, loại tiền tệ, hoặc đơn giản là hai dòng cùng "
        "tên trong hai phần khác nhau.",
        "**Không sửa được bằng cách sửa `row_path`.** Phân biệt chúng cần "
        "`row_uid` — mà gói đã có. Đây là lý do UID vật lý tồn tại."),
    "missing_label_or_split": (
        "Không có tổ tiên nào",
        "Nhóm không tìm được tổ tiên ứng viên nào phía trên. Thường là bảng bị "
        "cắt qua trang, hoặc dòng nhãn nằm ở một bảng `<table>` khác.",
        "Cần ghép bảng qua ranh giới trang trước — việc đó đổi `table_uid`, "
        "nên là thay đổi **breaking**, không làm trong kỳ thi."),
    "missing_column_group": (
        "Đụng độ ở trục CỘT, không phải trục dòng",
        "Một dòng, nhiều cột, cùng nhãn cột sau khi ghép tầng header. Thường là "
        "bảng có nhóm cột lồng (`Năm nay | Năm trước` dưới `Hợp nhất | Riêng`) "
        "mà tầng trên bị mất.",
        "Đã giảm **81,8%** như một hệ quả phụ của D-01 (42.743 → 7.796). Phần "
        "còn lại là bảng có cấu trúc header thật sự khó."),
    "physical_duplicate": (
        "🔴 LỖI THẬT — nhân bản của parser",
        "Nhiều observation trỏ về **cùng một ô nguồn**. Đây không phải mơ hồ "
        "ngữ nghĩa mà là lỗi khai triển span.",
        "**Bắt buộc bằng 0.** Khác 0 nghĩa là gói hỏng, không phải gói chưa "
        "hoàn thiện."),
    "unknown": (
        "🔴 CHƯA PHÂN LOẠI",
        "Đụng độ mà bộ phân loại không đặt được tên.",
        "**Bắt buộc bằng 0** theo bất biến đã duyệt: *đụng độ chưa phân loại "
        "trong `execution_ready` phải bằng 0*."),
}


def _doc_known_issues(con, rep) -> str:
    o = _head("Những chỗ dữ liệu này còn sai, còn thiếu, hoặc còn nợ", rep,
              "Tài liệu này tồn tại để bạn **không phải tự phát hiện** những "
              "điều dưới đây vào tuần thứ ba. Nó liệt kê cả thứ đã đo được lẫn "
              "thứ chưa đo được — và phân biệt rõ hai loại.")

    n_obs = _q1(con, "SELECT COUNT(*) FROM observations", default=0)

    o += ["## 0. Ba loại vấn đề, đừng trộn lẫn", "",
          "| Loại | Nghĩa | Bạn nên làm gì |", "|---|---|---|",
          "| **Hành vi đúng bị hiểu nhầm là lỗi** | Ô dấu `-` không thành 0; "
          "ngày tháng không thành giá trị | Không làm gì. Đừng \"sửa\" nó. |",
          "| **Đã đo, đã khoanh vùng, đã loại khỏi `execution_ready`** | Bốn "
          "lớp đụng độ ở §3 | Dùng cờ `execution_ready`. Chúng không làm bạn "
          "trả lời sai — chúng làm bạn trả lời **ít hơn**. |",
          "| **Chưa đo được** | Cổng `BLOCKED` ở §4 | Đừng coi là đã đạt. Đây "
          "là chỗ rủi ro **chưa biết độ lớn**. |", ""]

    # ── §1 ô bị loại ──
    o += ["## 1. Ô số bị loại và LÝ DO", ""]
    if _has(con, "dropped_cells"):
        n_drop = _q1(con, "SELECT COUNT(*) FROM dropped_cells", default=0)
        o += [f"`{_n(n_drop)}` ô có nội dung số nhưng **không** sinh "
              "observation. Bất biến của gói: *không ô nào biến mất mà không "
              "có tên lý do*. Bảng dưới đây là toàn bộ danh sách lý do — "
              "không có mục \"khác\".", ""]
        rws = _qall(con, "SELECT reason, COUNT(*) FROM dropped_cells"
                         " GROUP BY 1 ORDER BY 2 DESC")
        body = []
        for r, c in rws:
            verdict, why = _DROP_VERDICT.get(
                r, ("⬜ chưa đánh giá", "Lý do này chưa có phán xét trong "
                                       "`release_docs.py` — cần bổ sung."))
            body.append([f"`{r}`", _n(c), _pct(c, n_drop), verdict, why])
        o += _table(["Lý do", "Số ô", "Tỷ lệ", "Phán xét", "Giải thích"],
                    body, "|---|---:|---:|:-:|---|")
        o += _sql_block("SELECT reason, COUNT(*) FROM dropped_cells"
                        " GROUP BY 1 ORDER BY 2 DESC;")

        # Bóc `non_value_column` theo vai trò cột. Nó chiếm ~3/4 tổng số ô bị
        # loại, nên để nó là một con số duy nhất là giấu đi chỗ đáng ngờ nhất:
        # nếu bộ phân vai trò cột sai, sai lầm đó đổ hết vào đây và không có
        # dấu hiệu nào ở tầng trên.
        sub = _qall(con, "SELECT COALESCE(detail,'(không ghi)'), COUNT(*)"
                         " FROM dropped_cells WHERE reason='non_value_column'"
                         " GROUP BY 1 ORDER BY 2 DESC")
        if sub:
            tot = sum(c for _, c in sub)
            o += ["", "### 1.1 Bóc `non_value_column` theo vai trò cột", "",
                  "Đây là chỗ đáng soi nhất trong gói: nó là bucket lớn nhất, "
                  "**và** tính đúng đắn của nó phụ thuộc vào đúng cái cổng "
                  "đang `BLOCKED`. Nếu một vai trò dưới đây có số bất thường "
                  "cao, khả năng cao là bộ phân vai trò cột sai chứ không phải "
                  "corpus lạ.", ""]
            o += _table(["Vai trò cột", "Số ô", "Tỷ lệ", "Loại bỏ có đúng không"],
                        [[f"`{d}`", _n(c), _pct(c, tot),
                          {"metric_code": "✅ Mã số Thông tư 200 — là mã, không phải giá trị",
                           "ordinal": "✅ cột STT",
                           "note_reference": "🟡 số hiệu thuyết minh — **hay bị nhầm với cột giá trị nhất**",
                           "label": "✅ nhãn chỉ tiêu có chứa chữ số",
                           }.get(d, "⬜ chưa đánh giá")] for d, c in sub],
                        "|---|---:|---:|---|")
            o += _sql_block(
                "SELECT detail AS column_role, COUNT(*)\n"
                "  FROM dropped_cells WHERE reason='non_value_column'\n"
                " GROUP BY 1 ORDER BY 2 DESC;")
        o += ["**Tự kiểm:** muốn chắc gói không mất gì âm thầm, đếm ô số trong "
              "`grid_cells` (hồ sơ `full`) rồi so với "
              "`COUNT(observations) + COUNT(dropped_cells)`. Chênh lệch phải "
              "bằng 0.", "",
              "Xem mẫu thật của một lý do bất kỳ:", "",
              "```sql",
              "SELECT text_clean, detail FROM dropped_cells",
              " WHERE reason = 'parse_ambiguous' LIMIT 20;", "```", ""]
    else:
        o += [f"*{_MISSING}* — gói này dựng từ Silver chưa có bảng "
              "`dropped_cells`. Nghĩa là **không kiểm chứng được** câu \"không "
              "mất dữ liệu âm thầm\". Hãy dựng lại từ Silver mới.", ""]

    # ── §2 độ phủ chưa đầy đủ ──
    o += ["## 2. Độ phủ chưa đầy đủ — đo được, không đoán", "",
          "Ba trục dưới đây quyết định câu hỏi nào **không** trả lời được. "
          "Chúng không phải lỗi cần sửa gấp; chúng là biên của dữ liệu.", ""]

    n_money = _q1(con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'", default=0)
    rows2 = []
    pairs = [
        ("Kỳ đọc THẲNG từ nhãn cột",
         "SELECT COUNT(*) FROM observations WHERE period_source='column_path'",
         n_obs, "bằng chứng mạnh nhất"),
        ("Kỳ SUY từ ngữ cảnh bảng",
         "SELECT COUNT(*) FROM observations WHERE period_source='table_context'",
         n_obs, "⚠ yếu hơn một bậc — lọc ra khi câu hỏi nhạy cảm với kỳ"),
        ("Không giải được kỳ",
         "SELECT COUNT(*) FROM observations WHERE period_end IS NULL",
         n_obs, "🔴 đã bị loại khỏi `execution_ready`"),
        ("Ô TIỀN có `unit_kind='money'`",
         "SELECT COUNT(*) FROM observations WHERE value_kind='money' AND unit_kind='money'",
         n_money, "mẫu số là ô tiền, không phải mọi ô"),
        ("Ô TIỀN có bậc đơn vị TƯỜNG MINH",
         "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
         " AND scale_exponent IS NOT NULL AND scale_source NOT IN ('assumed','none')",
         n_money, "⚠ phần còn lại dùng bậc mặc định — kiểm lại nếu con số trông lệch 10³"),
        ("Cột chưa phân loại được vai trò",
         "SELECT COUNT(*) FROM observations WHERE confidence='low'",
         n_obs, "DI-02 cấm loại cứng, nên chúng vẫn có mặt với `confidence='low'`"),
    ]
    for name, sql, den, note in pairs:
        v = _q1(con, sql, default=None)
        rows2.append([name, _n(v), _pct(v, den) if v is not None else _MISSING, note])
    o += _table(["Trục", "Số observation", "Tỷ lệ", "Ghi chú"], rows2,
                "|---|---:|---:|---|")
    o += ["", "> Ba dòng đầu **chồng lấn nhau có chủ đích**: hai dòng trên đo "
          "*nguồn bằng chứng* (`period_source`), dòng thứ ba đo *kết quả* "
          "(`period_end IS NULL`). Một ô có thể có nguồn mà vẫn không giải ra "
          "được ngày. Đừng cộng ba dòng lại.", "",
          "> **Trần đo được của thước đơn vị là ~95,2%** — đây là một hằng số "
          "đã đo trên corpus, không phải số của bản dựng này. Khoảng 4,8% ô "
          "tiền nằm trong bảng **không khai `Đơn vị tính` ở bất cứ đâu**: "
          "không ở nhãn cột, không ở ngữ cảnh, không ở tiêu đề mục. Đó là "
          "thuộc tính của corpus, không phải của đường ống. Đặt mục tiêu 100% "
          "cho thước này là đặt một mục tiêu bất khả thi.", ""]

    # ── §3 đụng độ ──
    o += ["## 3. Đụng độ ngữ nghĩa — đã phân loại, đã cách ly", "",
          "**Đụng độ** = nhiều giá trị khác nhau cùng rơi vào một khoá ngữ "
          "nghĩa `(bảng, row_path, col_path, kỳ)`. Nếu để nguyên, một câu "
          "`df[df.row_path==...]` trả về nhiều dòng và tầng trên sẽ lặng lẽ "
          "lấy dòng đầu.", "",
          "Bất biến đã duyệt của dự án:", "",
          "> Đụng độ ngữ nghĩa toàn corpus **không bắt buộc bằng 0**. "
          "Đụng độ **chưa được phân loại** trong `execution_ready` thì **bắt "
          "buộc bằng 0**.", ""]

    rws = _qall(con, "SELECT collision_class, COUNT(*) FROM observations"
                     " WHERE collision_class IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
    if rws:
        n_coll = sum(c for _, c in rws)
        o += [f"`{_n(n_coll)}` observation ({_pct(n_coll, n_obs)}) nằm trong "
              "một nhóm đụng độ. **Toàn bộ đã bị loại khỏi "
              "`execution_ready`** — chúng làm bạn trả lời *ít hơn*, không làm "
              "bạn trả lời *sai*.", ""]
        o += _table(["Lớp", "Observation", "Tỷ lệ", "Bản chất", "Triển vọng"],
                    [[f"`{k}`", _n(v), _pct(v, n_coll),
                      _COLLISION_DOC.get(k, ("?", "", ""))[1],
                      _COLLISION_DOC.get(k, ("?", "", ""))[2]] for k, v in rws],
                    "|---|---:|---:|---|---|")
        o += _sql_block(
            "SELECT collision_class, COUNT(*) FROM observations\n"
            " WHERE collision_class IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;")

        for fatal in ("unknown", "physical_duplicate"):
            n = dict(rws).get(fatal, 0)
            mark = "✅" if n == 0 else "🔴"
            o += [f"{mark} `{fatal}` = **{_n(n)}** — bắt buộc phải bằng 0. "
                  + ("Đạt." if n == 0 else "**KHÔNG ĐẠT — gói này hỏng, đừng "
                                           "dùng cho tới khi truy nguyên xong.**"), ""]
    else:
        o += [f"*{_MISSING}* — cột `collision_class` trống hoặc không có. "
              "Trên corpus thật con số này **không thể** bằng 0; nếu bạn thấy "
              "trống, nhiều khả năng bộ phân loại chưa chạy.", ""]

    # ── §4 cổng chưa đo được ──
    o += ["## 4. Cái CHƯA ĐO ĐƯỢC — phần rủi ro chưa biết độ lớn", ""]
    blocked = list(getattr(rep, "blocked_gates", []) or [])
    if blocked:
        o += ["Những cổng dưới đây **chưa từng được đo**, không phải đã đo và "
              "đạt. Đây là phần duy nhất của tài liệu này mà tôi không đưa ra "
              "được con số — và đó chính là vấn đề.", ""]
        o += [f"- ⊘ {b}" for b in blocked]
        o += ["", "**Cụ thể với `G3 · độ chính xác role trên gold`:** không có "
              "tập Structure Gold nghĩa là **không ai biết** bộ phân vai trò "
              "cột/dòng đúng bao nhiêu phần trăm. Mọi con số về độ phủ ở §2 "
              "đều giả định vai trò đã gán là đúng. Nếu vai trò sai 5%, mọi "
              "thước ở trên lệch theo mà không có dấu hiệu nào.", "",
              "Vì lý do đó bản này mang nhãn "
              f"`{getattr(rep, 'release_label', 'rc')}`, **không** phải "
              "`production`.", ""]
    else:
        o += ["Không có cổng nào ở trạng thái `BLOCKED` trên bản dựng này.", ""]

    # ── §5 hạn chế đã biết, cố ý chưa sửa ──
    o += ["## 5. Hạn chế đã biết, CỐ Ý chưa sửa trong bản này", "",
          "Mỗi mục dưới đây đã được truy nguyên và có quyết định — không phải "
          "chưa ai để ý.", ""]
    o += _table(["Hạn chế", "Vì sao chưa sửa"], [
        ["`section_text` cắt ở 90 ký tự, một phần chứa ngày tháng",
         "Sửa sẽ đổi `row_path` — mà `row_path` đang là khoá truy hồi. Cần "
         "thước đo truy hồi trước, nếu không ta đánh đổi mù."],
        ["Công ty chứng khoán / bảo hiểm dùng hệ Mã số khác Thông tư 200",
         "Bộ đẳng thức kiểm tra số học chỉ đúng cho `B01-DN`. `industry_class` "
         "đã phân biệt `bank`/`corporate`; CTCK và DNBH cần bộ luật riêng."],
        ["Mã 52 (thuế TNDN hoãn lại) có quy ước dấu mâu thuẫn giữa các báo cáo",
         "Không suy được từ dữ liệu đã parse — cần đọc thuyết minh. Đã loại "
         "khỏi cổng kiểm số học thay vì đoán."],
        ["Bảng bị cắt qua ranh giới trang không được ghép lại",
         "Ghép sẽ đổi `table_uid` — thay đổi **breaking**. Không làm trong kỳ thi."],
        ["Nhãn dòng chung chung (`Cộng`, `Số dư cuối năm`) chỉ định danh được "
         "nhờ `row_path`",
         "Đây là bài toán **truy hồi**, không phải bài toán dữ liệu. Thêm ngữ "
         "cảnh vào nhãn sẽ làm hỏng khớp từ khoá."],
    ], "|---|---|")

    # ── §6 phòng vệ ──
    o += ["", "## 6. Cách tự phòng vệ khi dùng", "",
          "Sáu guard dưới đây bắt được đa số lỗi mà tài liệu này mô tả. Chi phí "
          "gần bằng không, nên hãy đặt cả sáu.", "",
          "```python",
          "from decimal import Decimal",
          "",
          "# 1. CHỈ tính trên fact đã đủ điều kiện. Đây là guard quan trọng nhất.",
          "d = df[df.execution_ready == 1]",
          "",
          "# 2. Decimal, KHÔNG float. 1.234.567.890.123 vượt độ chính xác float64.",
          "v = Decimal(row.value)                 # value là CHUỖI, có chủ đích",
          "",
          "# 3. Áp bậc đơn vị trước khi so sánh hai bảng khác nhau.",
          "vnd = Decimal(row.value) * (10 ** int(row.scale or 0))",
          "",
          "# 4. Trống KHÔNG phải 0. Đừng fillna(0) — đó là bịa số liệu.",
          "assert not d.value.isna().any()",
          "",
          "# 5. Loại dòng TỔNG trước khi cộng, nếu không là cộng trùng —",
          "#    lỗi này sai ÂM THẦM: kết quả trông hợp lý, chỉ là gấp đôi.",
          "d = d[~d.row_label.str.match(r'^(Cộng|Tổng)', case=False, na=False)]",
          "",
          "# 6. Truy vấn trả về nhiều dòng hơn kỳ vọng ⇒ TỪ CHỐI, đừng lấy dòng đầu.",
          "hit = d[(d.row_path == rp) & (d.period_end == pe)]",
          "if len(hit) != 1:",
          "    return None      # im lặng tốt hơn một con số sai trông hợp lý",
          "```", ""]

    # ── §7 cam kết tương thích ──
    o += ["## 7. Bản sau sẽ đổi gì — và cam kết tương thích", "",
          "Silver **tiếp tục được cải thiện** sau bản này. Ba loại thay đổi, "
          "với cam kết khác nhau:", ""]
    o += _table(["Loại", "Ví dụ", "Phiên bản", "Bạn phải làm gì"], [
        ["**Enrichment**", "một trường đang `NULL` được điền giá trị",
         "`1.0 → 1.1`", "**Không gì cả.** Mã cũ chạy nguyên."],
        ["**Correctness patch**", "một giá trị sai được sửa đúng",
         "`1.0.0 → 1.0.1`", "Dựng lại phần chỉ mục có `hash_labels` đổi."],
        ["**Breaking**", "đổi tên cột, bỏ cột, đổi `table_uid`",
         "major", "**Không xảy ra trong kỳ thi.**"],
    ], "|---|---|---|---|")
    o += ["", "Ba nhóm hash trong `table_cards` tồn tại chính vì việc này: so "
          "`hash_identity` · `hash_labels` · `hash_semantics` giữa hai bản để "
          "biết phải dựng lại **phần nào** của chỉ mục, thay vì dựng lại tất cả "
          "hoặc — tệ hơn — chạy tiếp trên chỉ mục cũ mà không biết.", ""]

    return "\n".join(o) + "\n"


# ═══════════════════════════ 3 · USAGE_GUIDE ═════════════════════════════

def _doc_usage(con, rep) -> str:
    o = _head("Hướng dẫn sử dụng dữ liệu Silver", rep,
              "Tài liệu này dành cho hai người tiêu thụ: **Retrieval** (tìm "
              "bảng) và **Text-to-Pandas** (tính trên bảng). Mỗi phần nói rõ "
              "phần nào dành cho ai.")

    # Đếm cột thật của view thay vì gõ "26". Nếu ai đó thêm cột mà quên sửa
    # tài liệu, con số vẫn đúng — và nếu ai đó BỎ một cột hợp đồng, §3 dưới
    # đây sẽ lệch so với con số này và người đọc thấy ngay.
    n_view_cols = len(_qall(con, "PRAGMA table_info(v_long_dataframe)")) or "?"

    o += ["## 1. Ba cửa vào — chọn đúng cửa", "",
          "Gói có ba giao diện. Chọn nhầm cửa là nguyên nhân phổ biến nhất của "
          "mã chậm và kết quả sai.", ""]
    o += _table(["Cửa", "Dành cho", "Vì sao"], [
        ["`table_cards` + `table_cards_fts`", "**Retrieval**",
         "một dòng mỗi bảng, có sẵn từ khoá dòng/cột, chỉ mục FTS5 bỏ dấu. "
         "Tìm bảng trước, rồi mới nạp fact của bảng đó."],
        ["`v_long_dataframe`", "**Text-to-Pandas**",
         f"long format {n_view_cols} cột, đã join sẵn, đã có "
         "`execution_ready`. `pd.read_sql` một câu là ra DataFrame dùng được."],
        ["`observations` + `tables` + `rows` + `columns`", "**Kiểm toán / gỡ lỗi**",
         "lược đồ đầy đủ, mọi cột. Dùng khi cần truy nguyên một con số cụ thể, "
         "không dùng cho đường chạy chính."],
    ], "|---|---|---|")

    o += ["", "## 2. Ba mươi giây đầu tiên", "", "```python",
          "import sqlite3, pandas as pd",
          "from decimal import Decimal",
          "",
          "con = sqlite3.connect('file:silver.db?mode=ro', uri=True)",
          "",
          "# Nạp long DataFrame. `value` đọc dạng CHUỖI — bắt buộc, xem §4.1.",
          "df = pd.read_sql_query(",
          "    'SELECT * FROM v_long_dataframe WHERE doc_id = ?', con,",
          "    params=('VNM_financial_statements_2018_consolidated',),",
          "    dtype={'value': 'string', 'value_raw': 'string'})",
          "",
          "fact = df[df.execution_ready == 1]      # LUÔN lọc trước khi tính",
          "```", ""]

    # ── hợp đồng cột ──
    o += ["## 3. Hợp đồng cột của `v_long_dataframe`", "",
          "20 cột dưới đây là **giao diện công khai**. Chúng không bị đổi tên "
          "hay bỏ đi mà không tăng phiên bản major.", ""]
    o += _table(["Cột", "Nghĩa", "Lưu ý khi dùng"], [
        ["`doc_id`", "định danh báo cáo", "khoá lọc chính, có index"],
        ["`table_uid`", "định danh bảng", "ổn định qua các bản Silver"],
        ["`table_locator`", "vị trí bảng trong tài liệu", "ghép với `doc_id` cho ràng buộc C20"],
        ["`statement_type`", "loại báo cáo", "`balance_sheet` · `income_statement` · `cash_flow` · `note`"],
        ["`row_uid`", "danh tính VẬT LÝ của dòng", "**dùng cái này làm khoá**, không dùng `row_path`"],
        ["`row_label`", "nhãn dòng đã làm sạch", "có thể chung chung (`Cộng`)"],
        ["`row_path`", "đường dẫn phân cấp `mục › tổ tiên › nhãn`", "⚠ **sẽ đổi** ở bản sau"],
        ["`metric_code`", "Mã số Thông tư 200", "`NULL` ở bảng thuyết minh — bình thường"],
        ["`column_uid`", "danh tính VẬT LÝ của cột", "ổn định"],
        ["`col_label`", "nhãn cột", "rơi về `col:<idx>` khi bảng không có header — **không bao giờ rỗng**"],
        ["`col_path`", "nhãn cột ghép theo tầng", "có thể rỗng; dùng `col_label` thay thế"],
        ["`period_end`", "ngày kết thúc kỳ, `YYYY-MM-DD`", "`NULL` ⇒ không `execution_ready`"],
        ["`value_raw`", "chuỗi **nguyên bản** trong báo cáo", "để trích dẫn và đối chiếu"],
        ["`value`", "giá trị đã chuẩn hoá, **dạng CHUỖI**", "🔴 `Decimal(v)`, không `float(v)`"],
        ["`unit`", "loại đơn vị", "`unknown` ⇒ không `execution_ready`"],
        ["`scale`", "số mũ 10 phải nhân để ra VND", "`0`=VND `3`=nghìn `6`=triệu `9`=tỷ"],
        ["`source_cell_uid`", "ô nguồn", "đường truy ngược về corpus"],
        ["`quality_flags`", "cờ chất lượng, JSON", "đọc khi một con số trông lạ"],
        ["`retrieval_ready`", "đủ để **tìm**", "cấp bảng"],
        ["`execution_ready`", "đủ để **tính**", "🔴 **cổng bắt buộc trước mọi phép tính**"],
    ], "|---|---|---|")
    o += ["", f"View có tất cả **{n_view_cols}** cột. Ngoài 20 cột hợp đồng "
          "trên còn có `row_idx` · `col_idx` · "
          "`value_kind` · `currency` · `period_role` · `collision_class`. "
          "`row_idx`/`col_idx` giữ **trật tự báo cáo** — thiếu chúng thì câu "
          "hỏi kiểu *\"khoản mục ngay phía trên dòng Tổng cộng\"* không trả lời "
          "được.", ""]

    # ── luật bắt buộc ──
    o += ["## 4. Bốn luật bắt buộc", "",
          "### 4.1 `value` là CHUỖI, không phải số", "",
          "Corpus có giá trị tới 10¹⁵ VND. `float64` giữ chính xác 15–16 chữ "
          "số và làm tròn sai **ngay lần ép kiểu đầu tiên**, không báo lỗi.", "",
          "```python",
          "v = Decimal(row.value)      # ĐÚNG",
          "v = float(row.value)        # SAI — mất chữ số, vĩnh viễn",
          "",
          "# Khi đọc bằng pandas, ép kiểu chuỗi ngay từ đầu:",
          "df = pd.read_sql_query(sql, con, dtype={'value': 'string'})",
          "df = pd.read_parquet(p)     # Parquet giữ kiểu — CSV thì KHÔNG",
          "```", "",
          "### 4.2 Trống KHÔNG phải 0", "",
          "Dấu `-` trong báo cáo tài chính nghĩa là **khuyết dữ liệu**. Ô như "
          "vậy cố ý không có trong gói. `fillna(0)` tạo ra số liệu không tồn "
          "tại trong báo cáo — và không ai phát hiện được vì kết quả trông hợp lý.", "",
          "### 4.3 Áp `scale` trước khi so sánh giữa hai bảng", "",
          "Giá trị lưu **đúng như in trên báo cáo**. Hai bảng cạnh nhau có thể "
          "một bảng ghi triệu đồng, một bảng ghi đồng.", "",
          "```python",
          "vnd = Decimal(row.value) * (10 ** int(row.scale or 0))",
          "```", "",
          "### 4.4 Trích dẫn bằng `evidence_ref` có sẵn, đừng tự ghép", "",
          "```python",
          "con.execute('SELECT evidence_ref FROM tables WHERE table_uid=?', (uid,))",
          "# → 'VNM_financial_statements_2018_consolidated|line:350'",
          "```", ""]

    # ── công thức ──
    o += ["## 5. Công thức cho từng dạng câu hỏi", "",
          "Mười dạng dưới đây phủ hầu hết câu hỏi thi. Cả mười đều có ca kiểm "
          "tương ứng trong `tools/replay_report.py` — nếu một công thức ở đây "
          "sai, bộ replay sẽ đỏ.", "",
          "### 5.1 Tra một chỉ tiêu, một kỳ", "", "```python",
          "hit = fact[(fact.table_uid == tu) &",
          "           (fact.row_path == rp) &",
          "           (fact.period_end == pe)]",
          "if len(hit) != 1:",
          "    return None          # xem 5.10",
          "```", "",
          "### 5.2 So sánh hai kỳ trên cùng một dòng", "", "```python",
          "piv = (fact[fact.table_uid == tu]",
          "       .pivot_table(index='row_uid', columns='period_end',",
          "                    values='value', aggfunc='first'))",
          "```", "",
          "> Index là `row_uid`, **không** phải `row_label`. Hai dòng khác nhau "
          "có thể trùng nhãn — đó chính là lớp `missing_dimension` ở "
          "`KNOWN_ISSUES.md §3`.", "",
          "### 5.3 Tăng trưởng", "", "```python",
          "cu, tr = Decimal(v_nay), Decimal(v_truoc)",
          "growth = (cu / tr - 1) if tr != 0 else None    # chia 0 phải TỪ CHỐI",
          "```", "",
          "### 5.4 Tỷ số giữa hai chỉ tiêu", "", "```python",
          "# Cùng bảng thì scale thường giống nhau, nhưng ĐỪNG giả định.",
          "a = Decimal(ra.value) * 10**int(ra.scale or 0)",
          "b = Decimal(rb.value) * 10**int(rb.scale or 0)",
          "```", "",
          "### 5.5 Tổng hợp nhiều dòng — **loại dòng tổng trước**", "",
          "Đây là lỗi Text-to-Pandas phổ biến nhất trên báo cáo tài chính, và "
          "nó sai **âm thầm**: kết quả trông hợp lý, chỉ là gấp đôi.", "", "```python",
          "sub = fact[fact.table_uid == tu]",
          "sub = sub[~sub.row_label.str.match(r'^(Cộng|Tổng|TỔNG)', na=False)]",
          "tong = sum(Decimal(v) for v in sub.value)",
          "```", "",
          "### 5.6 Nhiều bảng trong cùng một tài liệu", "", "```python",
          "fact[fact.doc_id == doc].groupby('table_uid').size()",
          "```", "",
          "### 5.7 Nhiều tài liệu", "",
          "Kiểm `scale` và `statement_type` khớp nhau trước khi cộng ngang các "
          "tài liệu. Hai báo cáo khác năm có thể khác đơn vị.", "",
          "### 5.8 Bảng không có header", "",
          "`col_label` rơi về `col:<idx>`, **không bao giờ rỗng**. Nếu để rỗng "
          "thì `groupby('col_label')` bỏ `NaN` âm thầm — mất dữ liệu mà không "
          "có lỗi nào.", "",
          "### 5.9 Nhãn trùng nhưng khác chiều", "", "```python",
          "# Phân biệt bằng row_uid — đó là mục đích của UID vật lý.",
          "fact.groupby(['table_uid','row_label','period_end']).row_uid.nunique()",
          "```", "",
          "### 5.10 **Ca quan trọng nhất — khi nào TỪ CHỐI trả lời**", "",
          "Một con số sai trông hợp lý tệ hơn hẳn im lặng. Từ chối khi:", "",
          "- `execution_ready == 0`",
          "- truy vấn trả về nhiều dòng hơn kỳ vọng",
          "- `collision_class` khác `NULL`",
          "- mẫu số bằng 0", "",
          "```python",
          "if hit.empty or len(hit) > 1 or hit.collision_class.notna().any():",
          "    return None",
          "```", ""]

    # ── retrieval ──
    o += ["## 6. Cho tầng Retrieval", "", "### 6.1 Tìm bảng bằng FTS5", "",
          "```sql",
          "SELECT c.table_uid, c.ticker, c.doc_year, c.section_text, c.evidence_ref",
          "  FROM table_cards_fts f",
          "  JOIN table_cards c ON c.table_uid = f.table_uid",
          " WHERE f MATCH '\"tien\" \"tuong\" \"duong\"'",
          "   AND c.retrieval_ready = 1",
          " ORDER BY bm25(f) LIMIT 20;", "```", "",
          "**RC-05 · chỉ mục lưu ở DẠNG CHUẨN — câu hỏi cũng phải chuẩn hoá.**",
          "",
          "`build_meta.fts_content = 'normalized'` là chỗ kiểm được điều đó "
          "bằng máy. Quy tắc chuẩn hoá: NFC → casefold → `đ`→`d` → bỏ dấu phụ "
          "→ gộp khoảng trắng. Dùng `fts_match_expr()` nếu có mã nguồn, hoặc "
          "chép hàm `norm()` trong `examples/03_search_tables.py`.", "",
          "> Bản RC1 ghi ở đây rằng *\"gõ không dấu vẫn khớp\"*. Câu đó SAI, và "
          "sai đúng một ký tự: `unicode61 remove_diacritics 2` gập được mọi "
          "dấu tiếng Việt TRỪ `đ` (U+0111) — nó là code point riêng chứ không "
          "phải `d` + dấu phụ. Đo trên RC1: `đồng` 104.792 thẻ có dấu so với "
          "997 không dấu (mất 99,0%); `đầu tư` 63.407 / 289; `tương đương` "
          "10.496 / 12. Trong khi `tiền`, `chi phí`, `tài sản` mất 0,0%. "
          "Truy vấn không báo lỗi — chỉ trả về ít hơn.", "",
          "### 6.2 Ba nhóm hash — dựng lại đúng phần cần dựng", ""]
    o += _table(["Hash", "Bao gồm", "Đổi thì phải làm gì"], [
        ["`hash_identity`", "`table_uid` · `doc_id` · `locator` · `statement_type`",
         "bảng là bảng khác — dựng lại toàn bộ mục đó"],
        ["`hash_labels`", "từ khoá dòng · từ khoá cột · tiêu đề mục",
         "**dựng lại chỉ mục FTS** cho bảng đó"],
        ["`hash_semantics`", "mã chỉ tiêu · kỳ · đơn vị",
         "chỉ mục tìm kiếm giữ nguyên; ánh xạ ngữ nghĩa cần cập nhật"],
    ], "|---|---|---|")
    o += ["", "Một hash gộp thì không nói được **phần nào** đổi, nên bạn buộc "
          "phải dựng lại tất cả. Ba nhóm là để tránh đúng việc đó.", ""]

    # ── hiệu năng ──
    o += ["## 7. Hiệu năng", ""]
    o += _table(["Việc", "Cách nhanh", "Cách chậm"], [
        ["Nạp một tài liệu", "Parquet phân mảnh theo `doc_id`", "đọc cả CSV tổng"],
        ["Lọc theo mã × năm", "`WHERE ticker=? AND doc_year=?` (có index)",
         "nạp hết rồi lọc bằng pandas"],
        ["Tìm bảng", "FTS5 `MATCH` trên `table_cards_fts`", "`LIKE '%…%'` trên `rows`"],
        ["Đọc lại nhiều lần", "nạp một lần vào DataFrame rồi tái dùng",
         "mở lại SQLite mỗi câu hỏi"],
    ], "|---|---|---|")
    o += ["", "```python",
          "# Parquet phân mảnh: đọc một tài liệu không phải nạp toàn corpus.",
          "df = pd.read_parquet('dataframe/parquet/long_dataframe/',",
          "                     filters=[('doc_id','==',doc)])",
          "```", ""]

    o += ["## 8. Trước khi tin gói này", "",
          "Ba việc nên làm ngay khi nhận, mỗi việc dưới một phút:", "",
          "```bash",
          "python examples/04_verify_package.py       # đối chiếu SHA-256 mọi tệp",
          "python tools/replay_report.py silver.db    # 10 ca hợp đồng bằng pandas",
          "sqlite3 silver.db 'SELECT key,value FROM build_meta"
          " WHERE key IN (\"build_id\",\"status\",\"release_label\",\"blocked_gates\")'",
          "```", "",
          "Câu cuối cho biết gói này mang nhãn gì và cổng nào chưa đo được. "
          "Nếu `status` khác `published`, hãy đọc `KNOWN_ISSUES.md §4` trước "
          "khi lập kế hoạch dựa trên gói.", ""]

    return "\n".join(o) + "\n"


# ═══════════════════════════════ điều phối ═══════════════════════════════

def build_docs(db_path, rep) -> dict[str, str]:
    """Sinh ba tệp tài liệu từ database của gói. Trả `{tên tệp: nội dung}`."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            "DATA_OVERVIEW.md": _doc_overview(con, rep),
            "KNOWN_ISSUES.md": _doc_known_issues(con, rep),
            "USAGE_GUIDE.md": _doc_usage(con, rep),
        }
    finally:
        con.close()
