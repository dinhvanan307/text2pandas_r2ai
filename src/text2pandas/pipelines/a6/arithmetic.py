"""DP-017 — D5b: đối chiếu số học theo quan hệ Mã số của Thông tư 200.

Đây là thước đo **tính đúng** đầu tiên của pipeline. Bốn cổng G1–G4 đo ĐỘ PHỦ:
có bao nhiêu phần trăm ô rút được kỳ, được đơn vị, có provenance. Không cổng nào
trả lời được câu hỏi *con số đó có đúng không*. Vụ 32.346 cột nhận kỳ suy diễn
sai đã chứng minh mọi cổng xanh vẫn che được lỗi ngữ nghĩa.

Thông tư 200/2014/TT-BTC cố định quan hệ cộng dồn giữa các Mã số. Đó là **gold
có sẵn trong corpus**: nếu parse số, dấu ngoặc âm, hoặc bậc đơn vị sai thì đẳng
thức vỡ. Không cần ai gán nhãn.

──────────────────────────────────────────────────────────────────────────────
PHẠM VI — hẹp có chủ đích

Chỉ dùng mã 3 chữ số của B01-DN, chỉ trên bảng đã phân loại `balance_sheet`.
Lý do đo được, không phải phòng xa:

* Mã 2 chữ số va nhau giữa B02-DN và B03-DN — mã 50 ở B02 là lợi nhuận trước
  thuế, ở B03 là lưu chuyển tiền thuần.
* Bảng thuyết minh (B09-DN) tái sử dụng cùng mã số cho bảng biến động TSCĐ, nơi
  cột "Giảm trong năm" làm nguyên giá mang dấu âm. Áp đẳng thức bảng cân đối vào
  đó sinh ra "sai" giả — đã đo: toàn bộ ca 221/227 lệch lớn đều là bảng note.
* Công ty chứng khoán (B01-CTCK) và bảo hiểm dùng hệ mã số khác hẳn. Đo được
  71,7% trên B01-CTCK so với 98,8% trên B01-DN — không phải pipeline tệ hơn ở
  đó, mà là áp sai chuẩn mực.

Một cổng chỉ có giá trị khi nó sai thì có nghĩa là dữ liệu sai. Mở rộng phạm vi
để tăng số lượng phép kiểm sẽ đổi tín hiệu lấy tiếng ồn.

Mã 52 (thuế TNDN hoãn lại) bị loại hẳn: đo được 1.206 ca "lệch đúng 2× mã 52",
và kiểm tay hai chứng từ AAA cho hai chiều NGƯỢC NHAU với cùng giá trị dương.
Quy ước dấu của nó không suy được từ dữ liệu đã parse, nên nó không đủ tư cách
làm gold.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation

__all__ = ["run_arithmetic", "ARITHMETIC_VERSION", "IDENTITIES"]

ARITHMETIC_VERSION = "1.1"

PLUS, MINUS_ABS = "+", "-abs"

# (rule_id, mô tả, mã đích, ((mã, chế độ, bắt_buộc), …))
#
#   "+"      cộng theo dấu ĐÃ LƯU — khoản âm dương đều có nghĩa thật
#   "-abs"   khoản GIẢM TRỪ, luôn lấy −|v| — đúng bất kể chứng từ in ngoặc hay
#            không. Cùng một mã, hai chứng từ hai quy ước: AAA 2015 in chi phí
#            dương, AAA 2019 in trong ngoặc.
IDENTITIES: tuple[tuple[str, str, int, tuple[tuple[int, str, bool], ...]], ...] = (
    ("A-BALANCE", "270 = 440", 270, ((440, PLUS, True),)),
    ("A-270", "270 = 100 + 200", 270, ((100, PLUS, True), (200, PLUS, True))),
    ("A-440", "440 = 300 + 400", 440, ((300, PLUS, True), (400, PLUS, True))),
    ("A-100", "100 = 110+120+130+140+150", 100,
     tuple((c, PLUS, True) for c in (110, 120, 130, 140, 150))),
    ("A-200", "200 = 210+220+230+240+250+260", 200,
     tuple((c, PLUS, True) for c in (210, 220, 230, 240, 250, 260))),
    ("A-300", "300 = 310 + 330", 300, ((310, PLUS, True), (330, PLUS, True))),
    ("A-400", "400 = 410 + 430?", 400, ((410, PLUS, True), (430, PLUS, False))),
    ("A-110", "110 = 111 + 112", 110, ((111, PLUS, True), (112, PLUS, True))),
    ("A-221", "221 = 222 − |223|", 221, ((222, PLUS, True), (223, MINUS_ABS, True))),
    ("A-227", "227 = 228 − |229|", 227, ((228, PLUS, True), (229, MINUS_ABS, True))),
)

# Dung sai 2 đồng: báo cáo làm tròn tới đơn vị đồng, sai lệch lớn hơn 2 không
# giải thích được bằng làm tròn.
TOLERANCE = Decimal(2)

# Ngưỡng phi lý: tổng tài sản lớn nhất trong corpus ở mức 10^15 VND. Giá trị
# vượt 10^16 không phải số liệu — đo được ca 9,7×10^22 do hai ô số dính liền.
IMPLAUSIBLE_ABS = Decimal(10) ** 16

_DIGITS = re.compile(r"\d+")
# Hệ mã số KHÁC Thông tư 200 — loại khỏi phép đối chiếu.
_OTHER_TAXONOMY = re.compile(r"CTCK|TCTD|DNBH|B0\d\s*[-–/]\s*(?:CTCK|TCTD|DNBH)", re.I)


def _norm_code(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _DIGITS.fullmatch(raw.strip().strip(".)"))
    if not m:
        return None
    v = int(m.group())
    # Chỉ mã 3 chữ số của B01-DN. Mã 2 chữ số va nhau giữa B02-DN và B03-DN.
    return v if 100 <= v <= 999 else None


def _to_base(text: str, exponent: int | None) -> Decimal | None:
    """Đưa về đơn vị gốc trước khi cộng — hai ô cùng bảng vẫn có thể khác bậc."""
    try:
        return Decimal(text) * (Decimal(10) ** int(exponent or 0))
    except (InvalidOperation, TypeError, ValueError):
        return None


def run_arithmetic(conn: sqlite3.Connection) -> dict:
    """Trả thống kê đối chiếu. KHÔNG ghi vào database — quality gọi và ghi issue."""
    rows = conn.execute(
        "SELECT o.table_uid, o.grid_col_idx, o.metric_code_raw,"
        "       o.value_decimal_text, o.scale_exponent, t.context_clean"
        " FROM observations o JOIN table_features t USING(table_uid)"
        " WHERE t.statement_type = 'balance_sheet'"
        "   AND o.value_kind = 'money'"
        "   AND o.metric_code_raw IS NOT NULL AND TRIM(o.metric_code_raw) <> ''"
        "   AND o.value_decimal_text IS NOT NULL").fetchall()

    series: dict[tuple[str, int], dict[int, Decimal]] = defaultdict(dict)
    skipped_taxonomy = 0
    for tid, col, raw, txt, exp, ctx in rows:
        if ctx and _OTHER_TAXONOMY.search(ctx):
            skipped_taxonomy += 1
            continue
        code = _norm_code(raw)
        if code is None:
            continue
        val = _to_base(txt, exp)
        if val is None:
            continue
        key = (tid, col)
        if code not in series[key]:
            series[key][code] = val

    by_rule: dict[str, dict[str, int]] = {}
    failures: list[tuple[str, str, int]] = []      # (rule, table_uid, grid_col_idx)
    n_eval = n_ok = 0
    for rule, desc, target, terms in IDENTITIES:
        ev = ok = 0
        for (tid, col), vals in series.items():
            if target not in vals:
                continue
            if any(c not in vals for c, _, req in terms if req):
                continue
            lhs = vals[target]
            rhs = sum(
                (-abs(vals[c]) if mode is MINUS_ABS else vals[c])
                for c, mode, _ in terms if c in vals
            )
            ev += 1
            if abs(lhs - rhs) <= TOLERANCE:
                ok += 1
            else:
                failures.append((rule, tid, col))
        by_rule[rule] = {"desc": desc, "evaluated": ev, "passed": ok}
        n_eval += ev
        n_ok += ok

    # Trần độ lớn phải đo trên giá trị SAU KHI ÁP BẬC, không phải chữ số thô.
    # Bản trước đo `value_decimal_text` trần nên báo 0 trong khi thực tế có
    # 94.700 observation vượt trần sau khi nhân scale. Cùng lỗi đã sửa ở
    # `quality.Q-OBS-IMPLAUSIBLE-NORMALIZED` nhưng còn sống ở đây — đúng bài
    # học "sửa một luật thì quét MỌI NƠI có luật đó" (02 §6.4).
    n_implausible = conn.execute(
        "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
        " AND value_decimal_text IS NOT NULL"
        " AND ABS(CAST(value_decimal_text AS REAL))"
        "     * CASE COALESCE(scale_exponent, 0)"
        "         WHEN 0 THEN 1 WHEN 3 THEN 1e3 WHEN 6 THEN 1e6"
        "         WHEN 9 THEN 1e9 WHEN 12 THEN 1e12 ELSE 1 END > ?",
        (float(IMPLAUSIBLE_ABS),)).fetchone()[0]

    return {
        "arithmetic_version": ARITHMETIC_VERSION,
        "series": len(series),
        "skipped_other_taxonomy": skipped_taxonomy,
        "evaluated": n_eval,
        "passed": n_ok,
        "pass_rate": round(100 * n_ok / n_eval, 2) if n_eval else 0.0,
        "by_rule": by_rule,
        "failures": failures,
        "n_implausible_magnitude": n_implausible,
    }
