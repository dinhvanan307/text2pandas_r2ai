#!/usr/bin/env python3
"""Quét đo TOÀN BỘ trên một build — một lệnh, một file JSON.

Thay cho việc chạy năm script rồi dán năm output. Trả lời trực tiếp các câu
hỏi 3, 4, 5, 6, 7 ở `10_FEEDBACK…md` §12 và xuất đúng định dạng
machine-readable mà §11 yêu cầu (numerator/denominator/build_id, không phải
phần trăm trần).

CHỈ ĐỌC.

    python tools/measure_all.py /tmp/dp_work/silver.sqlite -o reports/
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

SCALE_SQL = ("CASE COALESCE(scale_exponent,0) WHEN 0 THEN 1 WHEN 3 THEN 1e3"
             " WHEN 6 THEN 1e6 WHEN 9 THEN 1e9 WHEN 12 THEN 1e12 ELSE 1 END")


def q1(con, sql, args=()):
    return con.execute(sql, args).fetchone()[0]


def _stage(name: str, fn, con, budget: float):
    """Chạy một chặng, in thời gian, cảnh báo khi vượt ngân sách dự kiến.

    Lần chạy trước bị Ctrl-C vì công cụ IM LẶNG: một lần chạy 4 phút và một
    lần chạy 365 giờ trông giống hệt nhau khi không có gì in ra. Ước lượng
    không sửa được điều đó — đo và in từng chặng thì có.
    """
    print(f"  [{name}] đang chạy … (dự kiến ≤ {budget:.0f}s)", flush=True)
    t0 = time.time()
    out = fn(con)
    dt = time.time() - t0
    flag = "" if dt <= budget else f"   !!! VƯỢT {dt / budget:.1f}× ngân sách"
    print(f"  [{name}] xong {dt:6.1f}s{flag}", flush=True)
    if isinstance(out, dict):
        out["_seconds"] = round(dt, 2)
    return out


# ── Q5 · thiệt hại header, ĐO ĐÚNG theo công thức 10 §5.2 ───────────────────
# `query_version` phải đi kèm mọi con số (12 §3.6). Định nghĩa của
# `eligible_financial_source_cells` là DIỄN GIẢI CỦA ĐỘI DATA, không phải của
# doc 12 — nó quyết định con số cuối là 0 hay không, nên phải khai ra để người
# review bác được thay vì để nó ẩn trong một kết quả đẹp.
HEADER_QUERY_VERSION = "q5-v2"

# v1 SAI ba chỗ và bị `max(0, …)` che mất:
#   1. đếm chữ số chỉ REPLACE 0..4, bỏ sót 5..9  -> "99.888" bị loại
#   2. `mapped` đếm MỌI observation, không riêng ô tài chính
#   3. `excluded` không giới hạn ở ô SỐ nên đếm cả ô chữ, trùng với eligible
# Kết quả: 2.183.861 − 2.646.976 − 2.035.424 = −2.498.539, kẹp về 0.
# Không bao giờ được kẹp một hiệu số về 0. Hiệu âm là tín hiệu định nghĩa sai.

_DIGITS = "0123456789"


def _digit_count_sql(col: str) -> str:
    expr = col
    for d in _DIGITS:
        expr = f"REPLACE({expr},'{d}','')"
    return f"(LENGTH({col}) - LENGTH({expr}))"


def do_header(con) -> dict:
    """`unexplained_financial_drop_count` — MỘT LƯỢT QUÉT.

    Bản trước dùng bốn truy vấn, mỗi truy vấn có một
    `EXISTS (… WHERE o.source_cell_uid = sc.source_cell_uid)` tương quan. Mà
    `observations.source_cell_uid` không có chỉ mục, nên mỗi ô nguồn phải quét
    trọn 2,6 triệu dòng: 6,2M × 2,6M × 4 ≈ 6,6·10¹³ lượt đọc ≈ **365 giờ**.
    Không treo — chạy đúng, chỉ là không bao giờ xong.

    Bản này gộp thành một truy vấn: hai tập được vật chất hoá một lần rồi
    LEFT JOIN, và bốn con số rơi ra từ cùng một lượt quét. Nhờ vậy nó chạy
    được cả trên build cũ chưa có chỉ mục.
    """
    dc = _digit_count_sql("sc.text_clean")
    # Lý do được ghi trong `dropped_cells` là "explicit exclusion with reason"
    # theo đúng nghĩa doc 12 §5.2. Nhưng KHÔNG phải lý do nào cũng vô hại:
    # `parse_ambiguous` là ứng viên DEFECT, không phải loại trừ hợp lệ.
    excl = "d.source_cell_uid IS NOT NULL OR b.table_uid IS NOT NULL"
    row = con.execute(f"""
        WITH elig AS (
          SELECT sc.source_cell_uid AS uid, sc.table_uid AS tuid,
                 sc.grid_col_idx AS cidx
          FROM source_cells sc
          JOIN grid_cells g ON g.source_cell_uid = sc.source_cell_uid
                           AND g.is_span_anchor = 1
          WHERE TRIM(sc.text_clean) <> '' AND {dc} >= 4
        ),
        mapped AS (SELECT DISTINCT source_cell_uid AS uid FROM observations),
        badtab AS (SELECT table_uid FROM table_features WHERE parse_status <> 'ok')
        SELECT COUNT(*),
               SUM(m.uid IS NOT NULL),
               SUM(m.uid IS NULL AND ({excl})),
               SUM(m.uid IS NULL AND NOT ({excl}))
        FROM elig e
        LEFT JOIN mapped m ON m.uid = e.uid
        LEFT JOIN dropped_cells d ON d.source_cell_uid = e.uid
        LEFT JOIN badtab b ON b.table_uid = e.tuid""").fetchone()
    eligible, mapped, excluded, unexplained = (int(x or 0) for x in row)

    # Kiểm chéo THẬT: đếm `mapped` theo chiều ngược lại — đi từ observations
    # sang source_cells. Bắt được lỗi nhân bản do join (ví dụ grid_cells có
    # nhiều anchor cho một ô), thứ mà phép cộng trong cùng một lượt quét không
    # thể phát hiện.
    mapped_rev = q1(con, f"""
        SELECT COUNT(DISTINCT o.source_cell_uid)
        FROM observations o
        JOIN source_cells sc ON sc.source_cell_uid = o.source_cell_uid
        JOIN grid_cells g ON g.source_cell_uid = sc.source_cell_uid
                         AND g.is_span_anchor = 1
        WHERE TRIM(sc.text_clean) <> '' AND {dc} >= 4""")
    return {
        "defect_id": "D-01",
        "query_version": HEADER_QUERY_VERSION,
        "eligible_definition": "source cell · is_span_anchor=1 · text khác rỗng · >= 4 chữ số",
        "eligible_financial_source_cells": eligible,
        "mapped_financial_observations": mapped,
        "explicit_exclusions_with_reason": excluded,
        "unexplained_financial_drop_count": unexplained,
        "cross_check_mapped_reverse_join": mapped_rev,
        # `unexplained = 0` sau khi mọi điểm bỏ qua đều ghi lý do là ĐÚNG THEO
        # CẤU TẠO — nó chỉ chứng minh "không vứt im lặng", không chứng minh
        # "vứt hợp lý". Chỗ cần soi là phân rã lý do dưới đây.
        # Mẫu ô bị parser từ chối — 28.065 `parse_ambiguous` là ứng viên
        # defect lớn nhất còn lại ở tầng ô. Không đoán chúng là gì; lấy mẫu.
        "dropped_samples": {
            r: [dict(zip(("text", "rule", "n"), row)) for row in con.execute(
                "SELECT text_clean, detail, COUNT(*) FROM dropped_cells"
                " WHERE reason=? GROUP BY text_clean, detail"
                " ORDER BY 3 DESC LIMIT 12", (r,))]
            for r in ("parse_ambiguous", "parse_not_a_number", "no_structure")
        } if q1(con, "SELECT COUNT(*) FROM sqlite_master"
                     " WHERE type='table' AND name='dropped_cells'") else {},
        "dropped_by_reason": dict(con.execute(
            "SELECT reason, COUNT(*) FROM dropped_cells GROUP BY 1"
            " ORDER BY 2 DESC").fetchall()) if q1(
                con, "SELECT COUNT(*) FROM sqlite_master"
                     " WHERE type='table' AND name='dropped_cells'") else {},
        "partition_holds": eligible == mapped + excluded + unexplained,
        "tables_no_header": q1(con, "SELECT COUNT(*) FROM table_features"
                               " WHERE quality_flags_json LIKE '%no_header_row%'"),
        "tables_header_would_consume": q1(
            con, "SELECT COUNT(*) FROM table_features"
            " WHERE quality_flags_json LIKE '%header_would_consume_table%'"),
        "tables_header_small_numbers": q1(
            con, "SELECT COUNT(*) FROM table_features"
            " WHERE quality_flags_json LIKE '%header_row_has_small_numbers%'"),
    }


# ── Q4 · D-07 nhiễm bậc đơn vị, sáu con số theo 10 §3.3 ─────────────────────
def do_scale(con) -> dict:
    cand = q1(con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
              " AND scale_source IN ('section_context','table_context')"
              " AND COALESCE(scale_exponent,0) > 0")
    caught = q1(con, "SELECT COUNT(*) FROM observations"
                " WHERE quality_flags_json LIKE '%scale_rejected_implausible%'")
    escaped = q1(con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
                 " AND value_decimal_text IS NOT NULL"
                 f" AND ABS(CAST(value_decimal_text AS REAL)) * {SCALE_SQL} > 1e16")
    assumed = q1(con, "SELECT COUNT(*) FROM observations"
                 " WHERE value_kind='money' AND scale_source='assumed'")
    no_ev = q1(con, "SELECT COUNT(*) FROM observations"
               " WHERE value_kind='money' AND scale_source='none'")
    return {
        "defect_id": "D-07",
        "candidates_scale_from_wider_context": cand,
        "caught_by_guard": caught,
        "escaped_still_implausible": escaped,
        "assumed_scale": assumed,
        "no_scale_evidence": no_ev,
        "verified_correct_on_gold": None,          # cần Structure Gold
        # `currency_source='assumed'` KHÔNG kéo theo `scale_source='assumed'`.
        # Đọc lại `unit_resolver`: nhánh `elif scale is None` bị bỏ qua khi
        # currency là None, còn nhánh cuối chỉ bật khi scale CŨNG là None.
        # "Đơn vị tính: triệu" cho bậc mà không cho tiền tệ — hợp lệ.
        # Bản trước tôi khẳng định hai số phải bằng nhau và cho ra một cảnh
        # báo GIẢ. Giữ cả hai làm số liệu tham chiếu, bỏ phép so bằng.
        "cross_check_unit_assumed_flag": q1(
            con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
                 " AND unit_kind_source='assumed'"),
        "cross_check_currency_assumed": q1(
            con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
                 " AND currency_source='assumed'"),
        "note": "verified_correct_on_gold=null vì chưa có Structure Gold (10 §6)",
    }


# ── Q3 · phân loại arithmetic failures ─────────────────────────────────────
def do_arith(con) -> dict:
    """Phân loại 75 failure — doc 12 §10 câu 15–16.

    Bản trước dựng `buckets` rồi `+= 0` và không bao giờ dùng: mã chết giả vờ
    trả lời. Bản này tính LẠI hai vế của đúng đẳng thức bị fail rồi phân lớp
    theo ĐỘ LỆCH TƯƠNG ĐỐI — dấu hiệu duy nhất phân biệt được ba nguyên nhân:

        lệch < 0,5%          làm tròn / sai số trình bày  -> ngoại lệ hợp lệ
        lệch ≈ 10^k lần      sai BẬC ĐƠN VỊ của một số hạng -> defect
        lệch khác            thiếu số hạng hoặc sai dấu     -> cần xem tay
    """
    from text2pandas.pipelines.a6.arithmetic import IDENTITIES, MINUS_ABS, run_arithmetic

    r = run_arithmetic(con)
    fails = r.pop("failures", [])
    by_rule: dict[str, int] = {}
    for rule, _t, _c in fails:
        by_rule[rule] = by_rule.get(rule, 0) + 1

    terms_of = {rule: (target, terms) for rule, _d, target, terms in IDENTITIES}

    # Nạp MỘT LẦN cho mọi bảng có failure thay vì một truy vấn cho mỗi failure.
    # 75 lần quét 2,6 triệu dòng = 2·10⁸ lượt đọc; gộp lại còn một lần dùng
    # `ix_obs_tab`.
    cache: dict[tuple, list] = {}
    tids = sorted({t for _r, t, _c in fails})
    if tids:
        ph = ",".join("?" * len(tids))
        for tuid, cidx, code, txt, exp in con.execute(
                "SELECT table_uid, grid_col_idx, metric_code_raw,"
                " value_decimal_text, scale_exponent FROM observations"
                f" WHERE table_uid IN ({ph}) AND metric_code_raw IS NOT NULL"
                "   AND value_decimal_text IS NOT NULL", tids):
            cache.setdefault((tuid, cidx), []).append((code, txt, exp))
    classes = {"lam_tron_duoi_0_5pct": 0, "sai_bac_don_vi_10_mu_k": 0,
               "lech_khac": 0, "khong_dung_lai_duoc": 0}
    detail = []
    for rule, tid, col in fails:
        target, terms = terms_of.get(rule, (None, ()))
        rows = cache.get((tid, col), ())
        vals: dict[str, Decimal] = {}
        for code, txt, exp in rows:
            m = re.search(r"\d{2,3}", str(code or ""))
            if not m:
                continue
            try:
                vals.setdefault(m.group(0),
                                Decimal(txt) * (Decimal(10) ** int(exp or 0)))
            except (InvalidOperation, ValueError):
                pass
        if target is None or target not in vals:
            classes["khong_dung_lai_duoc"] += 1
            continue
        lhs = vals[target]
        rhs = sum((-abs(vals[c]) if mode is MINUS_ABS else vals[c])
                  for c, mode, _req in terms if c in vals)
        diff = abs(lhs - rhs)
        rel = float(diff / abs(lhs)) if lhs else None
        ratio = float(abs(lhs) / abs(rhs)) if rhs else None
        # Sai bậc: tỷ số hai vế xấp xỉ một luỹ thừa 10 (hoặc nghịch đảo).
        bac = False
        if ratio:
            for k in (1e-12, 1e-9, 1e-6, 1e-3, 1e3, 1e6, 1e9, 1e12):
                if abs(ratio - k) / k < 0.01:
                    bac = True
                    break
        if rel is not None and rel < 0.005:
            cls = "lam_tron_duoi_0_5pct"
        elif bac:
            cls = "sai_bac_don_vi_10_mu_k"
        else:
            cls = "lech_khac"
        classes[cls] += 1
        if len(detail) < 40:
            detail.append({
                "rule": rule, "table_uid": tid, "col": col, "class": cls,
                "lhs": str(lhs), "rhs": str(rhs),
                "rel_diff": round(rel, 6) if rel is not None else None,
                "lhs_over_rhs": round(ratio, 6) if ratio is not None else None,
                "codes_present": sorted(vals)[:12]})

    n_obs = q1(con, "SELECT COUNT(*) FROM observations")
    return {
        "defect_id": "G5-failures",
        "evaluated": r["evaluated"], "passed": r["passed"],
        "failed": r["evaluated"] - r["passed"],
        "pass_rate": r["pass_rate"],
        "coverage_of_all_observations": round(100 * r["evaluated"] / max(1, n_obs), 3),
        "failures_by_rule": by_rule,
        "failures_by_class": classes,
        "legitimate_exception": classes["lam_tron_duoi_0_5pct"],
        "defect": classes["sai_bac_don_vi_10_mu_k"],
        "unresolved": classes["lech_khac"] + classes["khong_dung_lai_duoc"],
        "skipped_other_taxonomy": r["skipped_other_taxonomy"],
        "n_implausible_magnitude_after_scale": r["n_implausible_magnitude"],
        "failure_detail_sample": detail,
        "note": "coverage < 1% — G5 là bằng chứng CỤC BỘ, không chứng nhận toàn corpus (10 §3.2)",
    }


# ── Q6 · RC-1 — ĐỌC từ classifier, không tính lại ──────────────────────────
def do_rc1(con) -> dict:
    """Một nguồn sự thật: `collision.build_collisions`.

    Bản trước tính lại A:B:C:D bằng SQL riêng trong khi `collision.py` cũng
    tính. Hai định nghĩa song song chắc chắn lệch nhau sau vài lần sửa, và khi
    lệch thì không ai biết bên nào đúng.
    """
    if not q1(con, "SELECT COUNT(*) FROM sqlite_master"
              " WHERE type='table' AND name='collision_groups'"):
        return {"defect_id": "D-02/D-03", "status": "BLOCKED",
                "reason": "collision_groups chưa tồn tại — chạy `cli silver` bản mới"}
    rows = con.execute(
        "SELECT collision_class, COUNT(*), SUM(n_obs) FROM collision_groups"
        " GROUP BY 1 ORDER BY 2 DESC").fetchall()
    by_stmt = con.execute("""
        SELECT t.statement_type, cg.collision_class, COUNT(*)
        FROM collision_groups cg JOIN table_features t USING(table_uid)
        GROUP BY 1,2 ORDER BY 3 DESC""").fetchall()
    return {
        "defect_id": "D-02/D-03",
        "source": "collision_groups (collision.py)",
        "collision_groups": sum(g for _c, g, _o in rows),
        "observations_total": q1(
            con, "SELECT COUNT(*) FROM observations WHERE value_decimal_text IS NOT NULL"),
        "classes": {c: {"groups": g, "observations": o or 0} for c, g, o in rows},
        "by_statement_type": [{"statement_type": a, "class": b, "groups": n}
                              for a, b, n in by_stmt[:40]],
    }


# ── Q7 · đụng độ trong execution_ready — dùng CLASSIFIER ───────────────────
def do_exec(con) -> dict:
    has_view = q1(con, "SELECT COUNT(*) FROM sqlite_master"
                  " WHERE type='view' AND name='v_execution_ready'")
    has_cls = q1(con, "SELECT COUNT(*) FROM sqlite_master"
                 " WHERE type='table' AND name='collision_obs'")
    if not has_view or not has_cls:
        return {"defect_id": "C4", "status": "BLOCKED",
                "reason": "thiếu v_execution_ready hoặc collision_obs"
                          " — chạy `cli silver` bản mới"}
    ready = q1(con, "SELECT COUNT(*) FROM v_execution_ready WHERE execution_ready=1")
    by_class = dict(con.execute(
        "SELECT collision_class, COUNT(*) FROM collision_obs GROUP BY 1").fetchall())
    inside = q1(con, """
        SELECT COUNT(*) FROM collision_obs co
        JOIN v_execution_ready v USING(observation_uid)
        WHERE v.execution_ready = 1""")
    unknown_inside = q1(con, """
        SELECT COUNT(*) FROM collision_obs co
        JOIN v_execution_ready v USING(observation_uid)
        WHERE v.execution_ready = 1 AND co.collision_class = 'unknown'""")
    return {
        "defect_id": "C4",
        "execution_ready_observations": ready,
        "collision_observations_total": sum(by_class.values()),
        "collision_by_class": by_class,
        "collision_inside_execution_ready": inside,
        "unknown_inside_execution_ready": unknown_inside,
        "physical_duplicate": by_class.get("physical_duplicate", 0),
        "gate_c4_pass": unknown_inside == 0 and by_class.get("physical_duplicate", 0) == 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("-o", "--out", default="reports")
    a = ap.parse_args()
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)

    meta = dict(con.execute("SELECT key, value FROM build_meta")) \
        if q1(con, "SELECT COUNT(*) FROM sqlite_master WHERE name='build_meta'") else {}
    t_all = time.time()
    print(f"quét đo build {meta.get('build_id', '?')} — 5 chặng", flush=True)
    # Ngân sách lấy từ ước lượng theo hình dạng truy vấn. Vượt ngân sách KHÔNG
    # phải lỗi, nhưng phải nhìn thấy được: một chặng vượt 10× là dấu hiệu
    # truy vấn rơi vào quét toàn bảng vì thiếu chỉ mục.
    rep = {
        "build_meta": meta,
        "observations": q1(con, "SELECT COUNT(*) FROM observations"),
        "tables": q1(con, "SELECT COUNT(*) FROM table_features"),
        "Q6_rc1": _stage("Q6 rc1", do_rc1, con, 10),
        "Q4_scale": _stage("Q4 scale", do_scale, con, 30),
        "Q3_arithmetic": _stage("Q3 arithmetic", do_arith, con, 60),
        "Q7_execution_ready": _stage("Q7 exec_ready", do_exec, con, 150),
        "Q5_header": _stage("Q5 header", do_header, con, 200),
    }
    rep["total_seconds"] = round(time.time() - t_all, 1)
    print(f"  TỔNG {rep['total_seconds']}s\n", flush=True)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"measure_{meta.get('build_id', 'nobuild')}.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    p = print
    p("╔═══════════ QUÉT ĐO TOÀN BỘ ═══════════╗")
    p(f"  {rep['tables']:,} bảng · {rep['observations']:,} obs · "
      f"schema v{meta.get('schema_version','?')}")
    h = rep["Q5_header"]
    p("\n  Q5 · D-01 no-loss (công thức 10 §5.2)")
    p(f"    [{h['query_version']}] {h['eligible_definition']}")
    p(f"    ô nguồn đủ điều kiện       {h['eligible_financial_source_cells']:>12,}")
    p(f"    thành observation          {h['mapped_financial_observations']:>12,}")
    p(f"    loại có lý do              {h['explicit_exclusions_with_reason']:>12,}")
    p(f"    MẤT KHÔNG GIẢI THÍCH ĐƯỢC  {h['unexplained_financial_drop_count']:>12,}"
      "   (ngưỡng RC: 0)")
    p(f"    kiểm chéo mapped (join ngược) {h['cross_check_mapped_reverse_join']:>9,}")
    if h.get("dropped_by_reason"):
        p("    ── lý do bỏ qua (đây MỚI là chỗ cần soi) ──")
        NGHI = ("parse_ambiguous", "parse_malformed", "no_structure")
        for r_, n_ in h["dropped_by_reason"].items():
            canh = "  <-- ứng viên DEFECT" if r_ in NGHI else ""
            p(f"      {r_:<26}{n_:>12,}{canh}")
        for r_, mau in (h.get("dropped_samples") or {}).items():
            if not mau:
                continue
            p(f"      ── mẫu {r_} ──")
            for m in mau[:8]:
                p(f"        {m['n']:>7,}×  {str(m['text'])[:46]:<46} {m['rule']}")
    if h["cross_check_mapped_reverse_join"] != h["mapped_financial_observations"]:
        p("    !!! LỆCH — join hai chiều cho hai số khác nhau."
          " Nghi ô nguồn bị nhân bản qua grid_cells.")
    if not h["partition_holds"]:
        p("    !!! PHÂN HOẠCH HỎNG — eligible != mapped + excluded + unexplained.")
    p(f"    bảng n_header=0 {h['tables_no_header']:,} · chặn kích hoạt "
      f"{h['tables_header_would_consume']:,} · số ngắn {h['tables_header_small_numbers']:,}")
    s = rep["Q4_scale"]
    p("\n  Q4 · D-07 nhiễm bậc đơn vị")
    for k in ("candidates_scale_from_wider_context", "caught_by_guard",
              "escaped_still_implausible", "assumed_scale", "no_scale_evidence",
              "cross_check_currency_assumed", "cross_check_unit_assumed_flag"):
        p(f"    {k:<38}{s[k]:>10,}")
    p("    (assumed_scale = thiếu CẢ tiền tệ LẪN bậc;"
      " currency_assumed = chỉ thiếu tiền tệ — hai tập khác nhau)")
    ar = rep["Q3_arithmetic"]
    p("\n  Q3 · G5 arithmetic")
    p(f"    evaluated {ar['evaluated']:,} · passed {ar['passed']:,} · "
      f"failed {ar['failed']:,} · pass {ar['pass_rate']}%")
    p(f"    phủ {ar['coverage_of_all_observations']}% observation  <- CỤC BỘ")
    p(f"    vượt trần SAU khi áp bậc  {ar['n_implausible_magnitude_after_scale']:,}")
    p(f"    failures theo luật: {ar['failures_by_rule']}")
    r1 = rep["Q6_rc1"]
    p(f"\n  Q6 · RC-1 — {r1['collision_groups']:,} nhóm đụng độ")
    for k, v in sorted(r1["classes"].items()):
        p(f"    {k:<24}{v['groups']:>9,} nhóm{v['observations']:>12,} obs")
    e = rep["Q7_execution_ready"]
    p("\n  Q7 · execution_ready + phân loại đụng độ")
    if e.get("status") == "BLOCKED":
        p(f"    BLOCKED — {e['reason']}")
    else:
        p(f"    obs execution_ready        {e['execution_ready_observations']:>12,}")
        for k, v in sorted(e["collision_by_class"].items(), key=lambda x: -x[1]):
            p(f"      {k:<26}{v:>12,}")
        p(f"    đụng độ TRONG exec_ready   {e['collision_inside_execution_ready']:>12,}")
        p(f"    UNKNOWN trong exec_ready   {e['unknown_inside_execution_ready']:>12,}"
          "   (ngưỡng C4: 0)")
        p(f"    physical_duplicate         {e['physical_duplicate']:>12,}"
          "   (ngưỡng C4: 0)")
        p(f"    -> C4 {'PASS' if e['gate_c4_pass'] else 'FAIL'}")
    p(f"\n  -> {f}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
