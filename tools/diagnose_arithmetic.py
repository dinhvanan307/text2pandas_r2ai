#!/usr/bin/env python3
"""Đối chiếu số học theo quan hệ Mã số của Thông tư 200 — chỉ ĐỌC.

    python tools/diagnose_arithmetic.py [--limit-fail 6] [--tolerance 2]

Vì sao tồn tại: bốn cổng chất lượng đo ĐỘ PHỦ, không đo ĐỘ ĐÚNG. Vụ 32.346 cột
nhận sai kỳ đã chứng minh mọi cổng xanh vẫn che được lỗi ngữ nghĩa. Cần một
thước đo tính đúng mà không phải gán nhãn tay.

Thông tư 200/2014/TT-BTC cố định quan hệ cộng dồn giữa các Mã số. Đó là **gold
có sẵn trong corpus**: nếu parse số, dấu âm, hoặc bậc đơn vị sai thì đẳng thức
vỡ. Một bảng cân đối mà `270 ≠ 440` là bảng ta đọc sai.

──────────────────────────────────────────────────────────────────────────────
QUY ƯỚC DẤU — phần tinh tế nhất của tệp này

Bản đầu định nghĩa `10 = 01 − 02` và cho ra 63,5% "sai". Kiểm tay thì dữ liệu
ĐÚNG, công thức sai: chứng từ in khoản giảm trừ trong ngoặc, parser đã biến nó
thành số âm, nên trừ lần nữa là phủ định hai lần.

Nhưng KHÔNG phải chứng từ nào cũng in ngoặc. AAA 2015 in chi phí bán hàng dương;
AAA 2019 in trong ngoặc. Cùng một mã số, hai quy ước.

Nên mỗi thành phần khai rõ bản chất:

    "+"      cộng theo dấu ĐÃ LƯU — dùng cho khoản có thể âm hoặc dương thật
             (lưu chuyển tiền thuần, phần lãi/lỗ liên kết, thuế hoãn lại)
    "-abs"   khoản GIẢM TRỪ, luôn lấy −|v| — đúng bất kể chứng từ có in ngoặc
             hay không (giá vốn, chi phí bán hàng, hao mòn luỹ kế)

Mã 52 (thuế TNDN hoãn lại) là "+" chứ không phải "-abs": nó có thể là khoản
THU nhập hoãn lại. Đã kiểm trên 4 chứng từ AAA — cộng theo dấu đã lưu khớp
chính xác cả khi giá trị dương lẫn khi âm.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

DB = Path(os.environ.get("DATA_PIPELINE_SCRATCH", "/tmp/dp_work")) / "silver.sqlite"

PLUS, MINUS_ABS = "+", "-abs"

# (rule, mô tả, mã đích, ((mã, chế độ, bắt_buộc), …), loại báo cáo bắt buộc)
#
# Mã 3 chữ số của B01-DN là duy nhất nên không cần lọc loại bảng. Mã 2 chữ số
# thì KHÔNG: B02-DN và B03-DN dùng chung dải 01–70 với ý nghĩa khác hẳn — mã 50
# ở B02 là lợi nhuận trước thuế, ở B03 là lưu chuyển tiền thuần trong kỳ.
IDENTITIES = (
    # ── B01-DN · Bảng cân đối kế toán ──
    ("BS-BALANCE", "270 = 440  (cân đối)", 270, ((440, PLUS, True),), None),
    ("BS-270", "270 = 100 + 200", 270, ((100, PLUS, True), (200, PLUS, True)), None),
    ("BS-440", "440 = 300 + 400", 440, ((300, PLUS, True), (400, PLUS, True)), None),
    ("BS-100", "100 = 110+120+130+140+150", 100,
     tuple((c, PLUS, True) for c in (110, 120, 130, 140, 150)), None),
    ("BS-200", "200 = 210+220+230+240+250+260", 200,
     tuple((c, PLUS, True) for c in (210, 220, 230, 240, 250, 260)), None),
    ("BS-300", "300 = 310 + 330", 300, ((310, PLUS, True), (330, PLUS, True)), None),
    ("BS-400", "400 = 410 + 430?", 400, ((410, PLUS, True), (430, PLUS, False)), None),
    ("BS-110", "110 = 111 + 112", 110, ((111, PLUS, True), (112, PLUS, True)), None),
    ("BS-221", "221 = 222 − |223|", 221,
     ((222, PLUS, True), (223, MINUS_ABS, True)), None),
    ("BS-227", "227 = 228 − |229|", 227,
     ((228, PLUS, True), (229, MINUS_ABS, True)), None),
    # ── B02-DN · Kết quả hoạt động kinh doanh ──
    ("IS-10", "10 = 01 − |02|", 10,
     ((1, PLUS, True), (2, MINUS_ABS, True)), "income_statement"),
    ("IS-20", "20 = 10 − |11|", 20,
     ((10, PLUS, True), (11, MINUS_ABS, True)), "income_statement"),
    # Mã 24 (phần lãi/lỗ công ty liên kết) chỉ có ở báo cáo HỢP NHẤT — tuỳ chọn.
    ("IS-30", "30 = 20+21−|22|+24?−|25|−|26|", 30,
     ((20, PLUS, True), (21, PLUS, True), (22, MINUS_ABS, True),
      (24, PLUS, False), (25, MINUS_ABS, True), (26, MINUS_ABS, True)),
     "income_statement"),
    ("IS-40", "40 = 31 − |32|", 40,
     ((31, PLUS, True), (32, MINUS_ABS, True)), "income_statement"),
    ("IS-50", "50 = 30 + 40", 50,
     ((30, PLUS, True), (40, PLUS, True)), "income_statement"),
    ("IS-60", "60 = 50 − |51| + 52", 60,
     ((50, PLUS, True), (51, MINUS_ABS, True), (52, PLUS, True)), "income_statement"),
    # ── B03-DN · Lưu chuyển tiền tệ — mọi thành phần là DÒNG TIỀN THUẦN, ──
    # ── âm dương đều có nghĩa thật, nên luôn cộng theo dấu đã lưu.        ──
    ("CF-50", "50 = 20 + 30 + 40", 50,
     ((20, PLUS, True), (30, PLUS, True), (40, PLUS, True)), "cash_flow"),
    ("CF-50b", "50 = 30 + 40  (kiểm mã 20 bị đọc sai)", 50,
     ((30, PLUS, True), (40, PLUS, True)), "cash_flow"),
    ("CF-70", "70 = 50 + 60 + 61?", 70,
     ((50, PLUS, True), (60, PLUS, True), (61, PLUS, False)), "cash_flow"),
)

_DIGITS = re.compile(r"\d+")
_FORM = re.compile(r"\bB\s*0\s*(\d)\s*[-–/]\s*([A-ZĐ]{2,6})", re.I)


def norm_code(raw: str | None) -> int | None:
    if not raw:
        return None
    m = _DIGITS.fullmatch(raw.strip().strip(".)"))
    if not m:
        return None
    v = int(m.group())
    return v if 0 < v <= 999 else None


def to_base(text: str, exponent: int | None) -> Decimal | None:
    """Đưa về ĐƠN VỊ GỐC trước khi cộng — hai ô cùng bảng vẫn có thể khác bậc."""
    try:
        return Decimal(text) * (Decimal(10) ** int(exponent or 0))
    except (InvalidOperation, TypeError, ValueError):
        return None


def classify_failure(lhs, rhs, operands) -> str:
    """Hình dạng sai số nói ra nguyên nhân — đây mới là phần sửa được."""
    ad = abs(lhs - rhs)
    if ad <= 2:
        return "sai số làm tròn ≤ 2"
    if rhs != 0:
        ratio = abs(lhs / rhs)
        for exp in (3, 6, 9, -3, -6, -9):
            if abs(ratio - Decimal(10) ** exp) < Decimal("0.001"):
                return f"lệch đúng bậc 10^{exp} — lỗi ĐƠN VỊ"
    if abs(lhs + rhs) < abs(lhs) * Decimal("0.001"):
        return "ngược dấu hoàn toàn"
    for code, val in operands:
        if val and abs(ad - 2 * abs(val)) <= 2:
            return f"lệch đúng 2× mã {code} — mã {code} SAI DẤU"
    for code, val in operands:
        if val and abs(ad - abs(val)) <= 2:
            return f"lệch đúng bằng mã {code} — mã {code} THỪA/THIẾU"
    if abs(lhs) > 0:
        r = ad / abs(lhs)
        if r < Decimal("0.001"):
            return "lệch < 0,1% — làm tròn hoặc khoản rất nhỏ"
        if r < Decimal("0.02"):
            return "lệch < 2%"
        if r < Decimal("0.5"):
            return "lệch < 50% — thiếu/thừa một khoản mục"
    return "lệch lớn — chưa phân loại"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-fail", type=int, default=4)
    ap.add_argument("--tolerance", type=Decimal, default=Decimal(2))
    args = ap.parse_args()

    if not DB.exists():
        print(f"không thấy {DB}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    print("  nạp ô tiền có Mã số …", flush=True)
    cur = conn.execute(
        "SELECT o.table_uid, o.grid_col_idx, o.metric_code_raw,"
        "       o.value_decimal_text, o.scale_exponent, t.statement_type,"
        "       t.directory_doc_id, o.period_end, t.industry_class, t.context_clean"
        " FROM observations o JOIN table_features t USING(table_uid)"
        " WHERE o.metric_code_raw IS NOT NULL AND TRIM(o.metric_code_raw) <> ''"
        "   AND o.value_decimal_text IS NOT NULL AND o.value_kind = 'money'")

    series: dict[tuple[str, int], dict[int, Decimal]] = defaultdict(dict)
    meta: dict[tuple[str, int], tuple] = {}
    tiny: list[tuple] = []
    n_cells = n_badcode = n_tiny = 0
    for tid, col, raw, txt, exp, stype, doc, per, industry, ctx in cur:
        n_cells += 1
        code = norm_code(raw)
        if code is None:
            n_badcode += 1
            continue
        val = to_base(txt, exp)
        if val is None:
            continue
        # Ô "tiền" trị tuyệt đối < 1.000 trong báo cáo chính là số trang hoặc
        # số hiệu thuyết minh bị đọc thành số liệu, không phải đồng Việt Nam.
        if abs(val) < 1000 and stype in ("balance_sheet", "income_statement",
                                         "cash_flow"):
            n_tiny += 1
            if len(tiny) < 8:
                tiny.append((doc, stype, tid, col, code, val))
        m = _FORM.search(ctx or "")
        form = f"B0{m.group(1)}-{m.group(2).upper()}" if m else "—"
        key = (tid, col)
        if code not in series[key]:
            series[key][code] = val
        meta[key] = (stype, doc, per or "—", industry, form)

    print(f"  {n_cells:,} ô · {n_badcode:,} mã không đọc được"
          f" · {len(series):,} chuỗi (bảng × cột)")
    print(f"  {n_tiny:,} ô 'tiền' có |giá trị| < 1.000 trong báo cáo chính"
          f"  ← gần chắc là số trang / số hiệu thuyết minh\n")

    tol = args.tolerance
    results, fails, shapes = [], defaultdict(list), defaultdict(lambda: defaultdict(int))
    by_form: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # [đánh giá, sai]
    by_ticker: dict[str, int] = defaultdict(int)

    for rule, desc, target, terms, need_type in IDENTITIES:
        n_eval = n_exact = n_tol = 0
        for key, vals in series.items():
            st, doc, per, industry, form = meta[key]
            if need_type and st != need_type:
                continue
            if target not in vals:
                continue
            if any(c not in vals for c, _, req in terms if req):
                continue
            lhs = vals[target]
            ops = []
            for c, mode, _req in terms:
                if c not in vals:
                    continue
                v = vals[c]
                ops.append((c, -abs(v) if mode is MINUS_ABS else v))
            rhs = sum((v for _, v in ops), Decimal(0))
            n_eval += 1
            diff = abs(lhs - rhs)
            if diff == 0:
                n_exact += 1
            elif diff <= tol:
                n_tol += 1
            else:
                shapes[rule][classify_failure(lhs, rhs, ops)] += 1
                by_ticker[doc.split("_")[0]] += 1
                if len(fails[rule]) < args.limit_fail:
                    fails[rule].append((key, lhs, rhs, ops, meta[key]))
            if rule != "CF-50b":
                by_form[form][0] += 1
                by_form[form][1] += 0 if diff <= tol else 1
        results.append((rule, desc, n_eval, n_exact, n_tol))

    W = 40
    print("═" * 92)
    print(f"  {'QUAN HỆ':<{W}} {'đánh giá':>9} {'khớp đúng':>16} {'±ds':>6} {'SAI':>8}")
    print("═" * 92)
    tot_eval = tot_ok = 0
    for rule, desc, n_eval, n_exact, n_tol in results:
        bad = n_eval - n_exact - n_tol
        if rule != "CF-50b":
            tot_eval += n_eval
            tot_ok += n_exact + n_tol
        pct = f"{100*n_exact/n_eval:.1f}%" if n_eval else "—"
        mark = " ‹chẩn›" if rule == "CF-50b" else ""
        print(f"  {desc+mark:<{W}} {n_eval:>9,} {n_exact:>9,} {pct:>6} {n_tol:>6,} {bad:>8,}")
    print("─" * 92)
    print(f"  {'TỔNG (không tính dòng ‹chẩn›)':<{W}} {tot_eval:>9,}"
          f" {'':>9} {'':>6} {'':>6} "
          f"{(f'{100*tot_ok/tot_eval:.2f}%' if tot_eval else '—'):>8}")
    print("═" * 92)

    print("\n  ── THEO MẪU BIỂU (bắt từ ngữ cảnh bảng) ──")
    for form, (n, bad) in sorted(by_form.items(), key=lambda x: -x[1][0])[:12]:
        rate = f"{100*(n-bad)/n:.1f}%" if n else "—"
        print(f"    {form:<12} {n:>8,} đánh giá   đúng {rate:>7}   sai {bad:>7,}")

    print("\n  ── HÌNH DẠNG SAI SỐ ──")
    agg: dict[str, int] = defaultdict(int)
    for s in shapes.values():
        for k, c in s.items():
            agg[k] += c
    for k, c in sorted(agg.items(), key=lambda x: -x[1]):
        print(f"    {c:>8,}  {k}")

    print("\n  ── MÃ CHỨNG KHOÁN SAI NHIỀU NHẤT (top 15) ──")
    print("    ", "  ".join(f"{t}:{c:,}" for t, c in
                            sorted(by_ticker.items(), key=lambda x: -x[1])[:15]))

    if tiny:
        print("\n  ── MẪU Ô 'TIỀN' PHI LÝ (< 1.000 VND) ──")
        for doc, st, tid, col, code, val in tiny:
            print(f"    {doc} · {st} · {tid}:c{col} · mã {code} = {val}")

    print("\n  ── VÍ DỤ SAI ──")
    for rule, desc, *_ in results:
        if not fails.get(rule):
            continue
        print(f"\n  ▸ {desc}")
        for (tid, col), lhs, rhs, ops, (st, doc, per, ind, form) in fails[rule]:
            print(f"    {doc} · {st}/{form}/{ind} · kỳ {per} · {tid}:c{col}")
            print(f"      trái {lhs:>24,}   phải {rhs:>24,}   lệch {lhs-rhs:,}")
            print("      " + "  ".join(f"{c}={v:,}" for c, v in ops))

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
