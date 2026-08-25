"""DP-012 — D5 Quality Assurance: đo, ghi vấn đề, KHÔNG tự sửa dữ liệu.

Nguyên tắc: quality check chỉ sinh `quality_issue`. Nó không bao giờ ghi đè
observation. Mọi phát hiện thủ công phải trở thành **rule hoặc fixture** rồi
build lại — vá trực tiếp vào database làm build mất khả năng tái lập.

Coverage không thay thế correctness. Các gate ở đây đo được ngay bằng corpus;
những gate cần gold (độ chính xác role/path/unit/period) được đánh dấu
`NOT_MEASURABLE` cho tới khi có annotation, **không** tự tuyên bố PASS.
"""

from __future__ import annotations

import json
import sqlite3

from text2pandas.pipelines.a6.arithmetic import run_arithmetic
from text2pandas.pipelines.a6.models import Severity, make_uid

__all__ = ["run_quality", "QUALITY_VERSION"]

QUALITY_VERSION = "1.7"

# rule_id → (mức, mô tả, câu truy vấn tìm phạm vi vi phạm)
_ISSUE_RULES: tuple[tuple[str, Severity, str, str], ...] = (
    ("Q-OBS-NO-SOURCE", Severity.CRITICAL,
     "observation không neo được về source cell",
     "SELECT observation_uid FROM observations o WHERE NOT EXISTS"
     " (SELECT 1 FROM source_cells s WHERE s.source_cell_uid=o.source_cell_uid)"),
    ("Q-OBS-ZERO-FROM-DASH", Severity.CRITICAL,
     "giá trị 0 sinh từ ô dash/rỗng — vi phạm DI-06",
     "SELECT observation_uid FROM observations"
     " WHERE value_decimal_text='0' AND value_source IN ('-','–','—','')"),
    ("Q-OBS-REAL-DECIMAL", Severity.CRITICAL,
     "value_decimal_text không phải chuỗi thập phân hợp lệ",
     "SELECT observation_uid FROM observations"
     " WHERE value_decimal_text IS NOT NULL"
     " AND value_decimal_text NOT GLOB '-*[0-9]*' AND value_decimal_text NOT GLOB '[0-9]*'"),
    ("Q-TAB-NO-STATUS", Severity.CRITICAL,
     "bảng không có parse_status",
     "SELECT table_uid FROM table_features WHERE parse_status IS NULL OR parse_status=''"),
    ("Q-OBS-SPAN-DUP", Severity.ERROR,
     "hai observation cùng source cell — nhân đôi do span",
     "SELECT source_cell_uid FROM observations GROUP BY source_cell_uid, table_uid"
     " HAVING COUNT(*)>1"),
    ("Q-COL-PERIOD-UNRESOLVED", Severity.WARNING,
     "cột giá trị không giải được kỳ",
     "SELECT table_uid||':'||grid_col_idx FROM columns"
     " WHERE column_role='value' AND period_end IS NULL"),
    ("Q-OBS-IMPLAUSIBLE-RAW", Severity.ERROR,
     "chữ số thô vượt 10^16 — hai ô số dính liền, không phải số liệu",
     "SELECT observation_uid FROM observations WHERE value_kind='money'"
     " AND ABS(CAST(value_decimal_text AS REAL)) > 1e16"),
    # Đây mới là đại lượng người dùng thực sự cầm: README bảo họ nhân
    # `value × 10^scale`. Bản cũ chỉ kiểm chữ số THÔ nên báo 0 trong khi
    # 314.023 ô vượt trần SAU khi nhân — cổng đo sai đại lượng thì nó chứng
    # nhận cho chính lỗi mà nó sinh ra để bắt.
    ("Q-OBS-IMPLAUSIBLE-NORMALIZED", Severity.ERROR,
     "giá trị SAU khi áp scale vượt 10^16 VND",
     "SELECT observation_uid FROM observations WHERE value_kind='money'"
     f" AND ABS(CAST(value_decimal_text AS REAL) * CASE COALESCE(scale_exponent,0) WHEN 0 THEN 1 WHEN 3 THEN 1e3 WHEN 6 THEN 1e6 WHEN 9 THEN 1e9 WHEN 12 THEN 1e12 ELSE 1 END) > 1e16"),
    ("Q-COL-INVALID-DATE", Severity.ERROR,
     "period_start/period_end không phải ngày lịch có thật",
     "SELECT table_uid||':'||grid_col_idx FROM columns WHERE"
     " (period_end IS NOT NULL AND date(period_end) IS NOT period_end)"
     " OR (period_start IS NOT NULL AND date(period_start) IS NOT period_start)"),
    ("Q-OBS-INVALID-DATE", Severity.ERROR,
     "observation mang ngày không hợp lệ",
     "SELECT observation_uid FROM observations WHERE"
     " (period_end IS NOT NULL AND date(period_end) IS NOT period_end)"
     " OR (period_start IS NOT NULL AND date(period_start) IS NOT period_start)"),
    ("Q-OBS-TINY-MONEY", Severity.WARNING,
     "giá trị tiền < 1.000 VND trong báo cáo chính — nhiều khả năng số hiệu",
     "SELECT o.observation_uid FROM observations o"
     " JOIN table_features t USING(table_uid)"
     " WHERE o.value_kind='money' AND o.value_decimal_text NOT IN ('0','-0')"
     " AND ABS(CAST(o.value_decimal_text AS REAL)) < 1000"
     " AND t.statement_type IN ('balance_sheet','income_statement','cash_flow')"),
    # Không phải lỗi cần sửa tay — là dấu vết của một quyết định đã ghi.
    # Bậc đơn vị là LỜI KHAI, chữ số in trong ô là BẰNG CHỨNG; khi áp lời
    # khai ra độ lớn bất khả thì lời khai thua và chuyện đó phải đếm được.
    ("Q-OBS-SCALE-REJECTED", Severity.WARNING,
     "bậc đơn vị bị bác vì áp vào ra độ lớn bất khả (lời khai ≠ chữ số)",
     "SELECT observation_uid FROM observations"
     " WHERE quality_flags_json LIKE '%scale_rejected_implausible%'"),
    ("Q-COL-DEMOTED-REF", Severity.INFO,
     "cột giá trị bị hạ xuống tham chiếu vì toàn số 1–2 chữ số",
     "SELECT table_uid||':'||grid_col_idx FROM columns"
     " WHERE flags_json LIKE '%demoted_short_digits%'"),
    ("Q-COL-ROLE-UNKNOWN", Severity.WARNING,
     "observation sinh từ cột chưa phân loại được vai trò",
     "SELECT observation_uid FROM observations"
     " WHERE quality_flags_json LIKE '%column_role_unknown%'"),
    # ── D-01: ranh giới tiêu đề ──────────────────────────────────────────
    # Luật cũ xoá cứng 85.095 giá trị ở 29.071 bảng mà không cờ nào ghi lại.
    # Ba luật dưới đây biến rủi ro tồn dư của luật mới thành số đo ở MỌI build.
    ("Q-TAB-HEADER-CONSUME", Severity.ERROR,
     "bộ nhận diện tiêu đề định nhận trọn cả bảng — đã chặn, giữ dữ liệu",
     "SELECT table_uid FROM table_features"
     " WHERE quality_flags_json LIKE '%header_would_consume_table%'"),
    ("Q-TAB-HEADER-SMALL-NUM", Severity.WARNING,
     "dòng tiêu đề có số 1–2 chữ số cạnh nhãn chữ — có thể là dữ liệu thật",
     "SELECT table_uid FROM table_features"
     " WHERE quality_flags_json LIKE '%header_row_has_small_numbers%'"),
    ("Q-TAB-NO-HEADER", Severity.INFO,
     "bảng không có dòng tiêu đề nào (n_header=0) — trạng thái HỢP LỆ",
     "SELECT table_uid FROM table_features"
     " WHERE quality_flags_json LIKE '%no_header_row%'"),
    ("Q-TAB-GLOBAL-HEADER", Severity.INFO,
     "bảng có đoạn tiêu đề phủ toàn bộ cột, đã loại khỏi phân loại vai trò",
     "SELECT table_uid FROM table_features"
     " WHERE quality_flags_json LIKE '%global_header_segment%'"),
    ("Q-COL-PERIOD-FROM-TABLE", Severity.INFO,
     "kỳ suy ra từ ngữ cảnh bảng, không đọc được từ nhãn cột",
     "SELECT table_uid||':'||grid_col_idx FROM columns"
     " WHERE column_role='value' AND period_source='table_context'"),
    ("Q-OBS-UNIT-NO-EVIDENCE", Severity.WARNING,
     "ô tiền không có bằng chứng đơn vị ở bất cứ tầng nào",
     "SELECT observation_uid FROM observations"
     " WHERE value_kind='money' AND unit_kind<>'money'"),
    ("Q-OBS-UNIT-ASSUMED", Severity.WARNING,
     "đơn vị mặc định, không có bằng chứng",
     "SELECT observation_uid FROM observations WHERE scale_source='assumed'"),
    ("Q-OBS-GENERIC-LABEL", Severity.INFO,
     "nhãn dòng chung chung, phụ thuộc đường dẫn để định danh",
     "SELECT observation_uid FROM observations"
     " WHERE quality_flags_json LIKE '%generic_row_label%'"),
    ("Q-TAB-NOT-DATA", Severity.INFO,
     "bảng không được phân loại là dữ liệu nhưng vẫn sinh observation",
     "SELECT DISTINCT table_uid FROM observations"
     " WHERE quality_flags_json LIKE '%table_not_classified_as_data%'"),
    ("Q-TAB-TOO-LARGE", Severity.WARNING,
     "bảng vượt hạn mức lưới, không rút được giá trị",
     "SELECT table_uid FROM table_features WHERE parse_status='table_too_large'"),
    ("Q-TAB-PARSE-FAIL", Severity.ERROR,
     "bảng không parse được",
     "SELECT table_uid FROM table_features WHERE parse_status='table_parse_failed'"),
)


def _count(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return len(conn.execute(sql).fetchall())
    except sqlite3.Error:
        return -1


def _scalar(conn: sqlite3.Connection, sql: str) -> float:
    try:
        row = conn.execute(sql).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    except sqlite3.Error:
        return 0.0


def run_quality(conn: sqlite3.Connection) -> dict:
    conn.execute("DELETE FROM quality_issues")

    by_rule: dict[str, int] = {}
    n_issues = n_critical = 0
    for rule_id, severity, message, sql in _ISSUE_RULES:
        rows = conn.execute(sql).fetchall()
        if not rows:
            continue
        by_rule[rule_id] = len(rows)
        n_issues += len(rows)
        if severity is Severity.CRITICAL:
            n_critical += len(rows)
        # Lưu tối đa 5.000 mẫu mỗi rule; con số tổng vẫn báo đầy đủ.
        conn.executemany(
            "INSERT OR REPLACE INTO quality_issues VALUES (?,?,?,?,?,?,?)",
            [(make_uid(rule_id, r[0]), "observation", str(r[0]), severity.value,
              rule_id, message, json.dumps({}, ensure_ascii=False))
             for r in rows[:5000]],
        )
    conn.commit()

    n_tab = _scalar(conn, "SELECT COUNT(*) FROM table_features")
    n_obs = _scalar(conn, "SELECT COUNT(*) FROM observations")
    n_col_val = _scalar(conn, "SELECT COUNT(*) FROM columns WHERE column_role='value'")

    def pct(sql: str, denom: float) -> float:
        return round(100 * _scalar(conn, sql) / denom, 2) if denom else 0.0

    # Kỳ được đo bằng HAI thước, không gộp. Gộp lại thì một con số cao che mất
    # việc phần lớn kỳ là suy diễn cấp bảng chứ không đọc được từ nhãn cột —
    # đúng thứ mà tầng truy hồi cần biết để chọn độ tin cậy.
    _COL_VAL = "FROM columns WHERE column_role='value'"
    pct_period_explicit = round(100 - pct(
        f"SELECT COUNT(*) {_COL_VAL} AND (period_end IS NULL"
        f" OR period_source='table_context')", n_col_val), 2)
    pct_period_any = round(100 - pct(
        f"SELECT COUNT(*) {_COL_VAL} AND period_end IS NULL", n_col_val), 2)

    # Đơn vị cũng phải đo trên ĐÚNG mẫu số. Bản cũ đo `scale_source='assumed'`
    # trên MỌI observation và cho 97,88% — trong khi 95% ô tiền không có bậc đơn
    # vị nào cả. Lý do: ô bị gán nhầm loại phi tiền tệ thoát sớm với
    # `scale_source = none`, mà `none` thì không phải `assumed`, nên nó lọt lưới.
    # Một thước đo lấy sai mẫu số không chỉ vô dụng — nó tuyên bố an toàn.
    n_money = _scalar(conn, "SELECT COUNT(*) FROM observations WHERE value_kind='money'")
    pct_money_unit = round(pct(
        "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
        " AND unit_kind='money'", n_money), 2)
    pct_money_scale = round(pct(
        "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
        " AND scale_exponent IS NOT NULL AND scale_source NOT IN ('assumed','none')",
        n_money), 2)

    gates: dict[str, list[dict]] = {}

    gates["G1 Catalog"] = [
        {"name": "bảng có parse_status", "value": f"{pct('SELECT COUNT(*) FROM table_features WHERE parse_status IS NOT NULL', n_tab)}%",
         "threshold": "100%", "pass": by_rule.get("Q-TAB-NO-STATUS", 0) == 0},
    ]
    gates["G2 Parsing"] = [
        {"name": "bảng parse thành công", "value": f"{pct(chr(83)+'ELECT COUNT(*) FROM table_features WHERE parse_status=' + chr(39) + 'ok' + chr(39), n_tab)}%",
         "threshold": "≥ 95%", "pass": pct("SELECT COUNT(*) FROM table_features WHERE parse_status='ok'", n_tab) >= 95},
        {"name": "observation trùng do span", "value": by_rule.get("Q-OBS-SPAN-DUP", 0),
         "threshold": "0", "pass": by_rule.get("Q-OBS-SPAN-DUP", 0) == 0},
        {"name": "bảng parse lỗi", "value": by_rule.get("Q-TAB-PARSE-FAIL", 0),
         "threshold": "0", "pass": by_rule.get("Q-TAB-PARSE-FAIL", 0) == 0},
    ]
    gates["G3 Structure"] = [
        {"name": "bảng có cột giá trị", "value": f"{pct('SELECT COUNT(DISTINCT table_uid) FROM columns WHERE column_role=' + chr(39) + 'value' + chr(39), n_tab)}%",
         "threshold": "≥ 85%", "pass": pct("SELECT COUNT(DISTINCT table_uid) FROM columns WHERE column_role='value'", n_tab) >= 85},
        # P0-02: `NOT_MEASURABLE` KHÔNG phải `PASS`. Cổng không đo được thì
        # nó chặn, không phải nó gật. Ghi pass=True ở đây là false pass về quản
        # trị: gói được phát hành với tuyên bố "mọi cổng xanh" trong khi độ
        # chính xác cấu trúc chưa từng được đo trên gold.
        #
        # `blocked=True` phân biệt "chưa có dụng cụ đo" với "đo rồi, hỏng".
        # Cả hai đều `pass=False` — nhưng chỉ cái sau được quyền chặn phát
        # hành. Doc 12 §7: RC ĐƯỢC PHÉP mang gate BLOCKED miễn khai rõ. Gộp
        # hai loại thì RC không bao giờ ra được, và áp lực gỡ cổng cho xong
        # việc sẽ kéo theo cả những FAIL thật.
        {"name": "độ chính xác role trên gold (DP-002 chưa có)",
         "value": "BLOCKED — chưa có gold", "threshold": "≥ 98%", "pass": False,
         "blocked": True,
         "blocking_reason": "Structure Gold (DP-002) chưa tồn tại — không có"
                            " mẫu đối chiếu để đo độ chính xác role"},
    ]
    gates["G4 Semantics"] = [
        {"name": "observation có provenance", "value": f"{100 - pct('SELECT COUNT(*) FROM observations o WHERE NOT EXISTS (SELECT 1 FROM source_cells s WHERE s.source_cell_uid=o.source_cell_uid)', n_obs)}%",
         "threshold": "100%", "pass": by_rule.get("Q-OBS-NO-SOURCE", 0) == 0},
        {"name": "dash/rỗng biến thành 0", "value": by_rule.get("Q-OBS-ZERO-FROM-DASH", 0),
         "threshold": "0", "pass": by_rule.get("Q-OBS-ZERO-FROM-DASH", 0) == 0},
        {"name": "cột giá trị có kỳ TƯỜNG MINH (từ nhãn cột)",
         "value": f"{pct_period_explicit}%",
         "threshold": "≥ 55%", "pass": pct_period_explicit >= 55},
        {"name": "cột giá trị có kỳ, kể cả suy diễn cấp bảng",
         "value": f"{pct_period_any}%",
         "threshold": "≥ 85%", "pass": pct_period_any >= 85},
        # Ngưỡng 93% đặt theo TRẦN ĐO ĐƯỢC, không phải theo mong muốn.
        #
        #   đạt hiện tại                                    94,24%
        #   + vá mọi ca còn dấu vết ở nhãn cột (18.708)     95,02%
        #   + vá cả ca còn dấu vết ở ngữ cảnh (4.510)       95,21%  ← TRẦN
        #   im lặng hoàn toàn, không bằng chứng ở đâu      115.282 ô = 4,79%
        #
        # 4,79% ô tiền nằm trong bảng không khai đơn vị ở bất cứ đâu — thuộc
        # tính của corpus, không phải của pipeline. Đặt ngưỡng 95% là đặt cách
        # trần 0,21 điểm: cổng sẽ đỏ vì nhiễu chứ không vì hồi quy. 93% chừa
        # 1,24 điểm để phát hiện hồi quy thật.
        {"name": "ô TIỀN mang unit_kind = money", "value": f"{pct_money_unit}%",
         "threshold": "≥ 93% (trần đo được 95,21%)", "pass": pct_money_unit >= 93},
        {"name": "ô TIỀN có bậc đơn vị tường minh", "value": f"{pct_money_scale}%",
         "threshold": "≥ 60%", "pass": pct_money_scale >= 60},
    ]

    # ── G5: thước đo TÍNH ĐÚNG, không phải độ phủ ──
    # Ngưỡng 97% đặt theo bằng chứng, không đoán: build 4941cb2a đo được 98,8%
    # trên 18.303 phép kiểm B01-DN. Đặt dưới mức đã đạt một khoảng đủ để dung
    # sai OCR, nhưng đủ chặt để một hồi quy về parse số làm cổng đỏ ngay.
    arith = run_arithmetic(conn)
    conn.executemany(
        "INSERT OR REPLACE INTO quality_issues VALUES (?,?,?,?,?,?,?)",
        [(make_uid("Q-ARITH-BROKEN", rule, tid, col), "column", f"{tid}:{col}",
          Severity.ERROR.value, "Q-ARITH-BROKEN",
          f"đẳng thức {rule} không khớp", json.dumps({"rule": rule},
                                                     ensure_ascii=False))
         for rule, tid, col in arith["failures"][:5000]],
    )
    conn.commit()
    n_arith_fail = len(arith["failures"])
    by_rule["Q-ARITH-BROKEN"] = n_arith_fail
    n_issues += n_arith_fail

    gates["G5 Arithmetic"] = [
        {"name": "đẳng thức Mã số B01-DN khớp", "value": f"{arith['pass_rate']}%",
         "threshold": "≥ 97%", "pass": arith["pass_rate"] >= 97},
        {"name": "số phép kiểm thực hiện được", "value": arith["evaluated"],
         "threshold": "≥ 10.000", "pass": arith["evaluated"] >= 10_000},
        {"name": "giá trị tiền vượt 10^16 VND (chữ số thô)",
         "value": by_rule.get("Q-OBS-IMPLAUSIBLE-RAW", 0),
         "threshold": "0", "pass": by_rule.get("Q-OBS-IMPLAUSIBLE-RAW", 0) == 0},
        {"name": "giá trị vượt 10^16 VND SAU khi áp scale",
         "value": by_rule.get("Q-OBS-IMPLAUSIBLE-NORMALIZED", 0),
         "threshold": "0", "pass": by_rule.get("Q-OBS-IMPLAUSIBLE-NORMALIZED", 0) == 0},
        {"name": "ngày không hợp lệ trong observation",
         "value": by_rule.get("Q-OBS-INVALID-DATE", 0),
         "threshold": "0", "pass": by_rule.get("Q-OBS-INVALID-DATE", 0) == 0},
    ]

    return {
        "quality_version": QUALITY_VERSION,
        # P1-03: `by_rule` là TỔNG số vi phạm; bảng `quality_issues` chỉ giữ
        # tối đa `sample_limit` dòng mỗi rule. Trước đây hai con số này được
        # trình bày lẫn nhau (552.305 vs 37.078) nên người đọc tưởng bảng chứa
        # toàn bộ. Khai rõ ở đây để không ai phải suy ra.
        "issue_store": {"is_sampled": True, "sample_limit": 5000,
                        "total_violations": n_issues,
                        "exported_samples": min(n_issues, 5000 * len(by_rule))},
        "n_issues": n_issues, "n_critical": n_critical,
        "by_rule": by_rule, "gates": gates,
        "arithmetic": {k: v for k, v in arith.items() if k != "failures"},
        "counts": {"tables": int(n_tab), "observations": int(n_obs),
                   "value_columns": int(n_col_val)},
    }
