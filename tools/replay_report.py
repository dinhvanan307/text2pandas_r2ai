#!/usr/bin/env python3
"""RC-19 / C5 · replay theo HỢP ĐỒNG GOLD ĐÃ ĐÓNG BĂNG.

Vì sao viết lại: bản trước tự chọn dòng bằng `df.iloc[0]` **từ chính DB đang
kiểm**, rồi so kết quả với thứ nó vừa chọn. Đó là self-fulfilling test —
output sai vẫn có thể tự chọn một dòng sai và PASS (audit 42 · B0-04).

Nguyên tắc của bản này:

1. **Selector đến từ hợp đồng, không đến từ dữ liệu.** Mỗi ca chỉ định
   `doc_id`/`table_uid`/`row_uid`/`column_uid` đã khoá trong
   `configs/replay_expected_v1.yaml`. Công cụ KHÔNG được chọn dòng nào khác.
2. **Expected đến từ RC1**, ghim bằng `evidence_db_sha256`. Không đọc bất kỳ
   output nào của bản đang kiểm để suy ra kỳ vọng.
3. **Thiếu dữ liệu là ERROR, không phải SKIP.** Một ca không kiểm được thì C5
   không đạt — im lặng bỏ qua chính là cách một cổng trở nên vô dụng.
4. Ca `abstain` phải chứng minh hệ thống **TỪ CHỐI trả lời**, không phải trả
   một con số trông hợp lý.

    python tools/replay_report.py <db> --expected configs/replay_expected_v1.yaml -o reports/

Exit: 0 = 10/10 PASS · 3 = có FAIL/ERROR/SKIP · 2 = lỗi sử dụng.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import traceback
from pathlib import Path

try:
    import pandas as pd
except ImportError:                                            # pragma: no cover
    print("cần pandas: pip install pandas pyarrow", file=sys.stderr)
    raise SystemExit(2)

try:
    import yaml
except ImportError:                                            # pragma: no cover
    print("cần PyYAML", file=sys.stderr)
    raise SystemExit(2)

# Trường của `expected` được so khớp. Mọi trường khai trong hợp đồng mà có mặt
# ở DataFrame đều bị so — không có trường nào được lặng lẽ bỏ qua.
COMPARABLE = (
    "observation_uid", "source_cell_uid", "evidence_ref", "metric_label_clean",
    "period_end", "value_source_raw", "value_decimal_text", "unit_kind",
    "currency", "scale_exponent", "row_path_text", "col_path_text",
)
SELECTORS = ("doc_id", "table_uid", "row_uid", "column_uid")

# RC2-042 · Hợp đồng gold đặt tên trường theo lược đồ bảng `observations`;
# `v_long_dataframe` — mặt phẳng mà người dùng gói thật sự đọc — đổi tên chúng
# cho gọn. Cùng một giá trị, hai cái tên.
#
# Đo trên ca 01 của bản dựng `7aa8b4c22984bf5f`: mọi giá trị kỳ vọng KHỚP CHÍNH
# XÁC, chỉ nằm dưới cột khác tên (`value` = `4500000000`, `unit` = `money`,
# `scale` = `0`, `row_label` = nhãn kỳ vọng). Không có sai lệch dữ liệu nào.
#
# Bảng ánh xạ này là KHAI BÁO, không phải suy đoán lúc chạy: chỉ thêm cột mang
# tên hợp đồng khi cột đó VẮNG và cột nguồn CÓ. Không bao giờ ghi đè.
VIEW_ALIASES = {
    "metric_label_clean": "row_label",
    "value_decimal_text": "value",
    "value_source_raw":   "value_raw",
    "unit_kind":          "unit",
    "scale_exponent":     "scale",
    "row_path_text":      "row_path",
    "col_path_text":      "col_path",
}


def apply_view_aliases(df) -> list[str]:
    """Thêm cột mang tên hợp đồng. Trả danh sách ánh xạ ĐÃ áp dụng để ghi report."""
    da_dung = []
    for hop_dong, view in VIEW_ALIASES.items():
        if hop_dong not in df.columns and view in df.columns:
            df[hop_dong] = df[view]
            da_dung.append(f"{hop_dong} <- {view}")
    # `evidence_ref` không phải một cột — nó là cách hợp đồng ghi định vị:
    # `<doc_id>|<table_locator>`. Ghép, không đoán.
    if ("evidence_ref" not in df.columns
            and "doc_id" in df.columns and "table_locator" in df.columns):
        df["evidence_ref"] = (df["doc_id"].astype("string") + "|"
                              + df["table_locator"].astype("string"))
        da_dung.append("evidence_ref <- doc_id|table_locator")
    return da_dung


# RC2-044 · `0` và `0.0` là CÙNG MỘT bậc 10.
#
# `scale` trong `v_long_dataframe` có NULL, nên pandas nạp cả cột thành float64
# và `0` thành `0.0`. Hợp đồng khoá `scale_exponent: '0'`. Tám trong mười ca
# FAIL chỉ vì dấu chấm đó — dữ liệu không lệch một chữ số nào.
#
# Chuẩn hoá này KHÔNG nới lỏng phép so: nó chỉ gộp hai cách VIẾT của cùng một
# số nguyên, và chỉ khi phần thập phân toàn số 0. `0.5` vẫn khác `0`, `1e3` vẫn
# giữ nguyên hình dạng của nó.
_SO_NGUYEN_DANG_THAP_PHAN = re.compile(r"^-?\d+\.0+$")


def _norm(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    if _SO_NGUYEN_DANG_THAP_PHAN.match(s):
        s = s.split(".", 1)[0]
    return s


def _select(df, case: dict):
    """Lọc DataFrame CHỈ bằng selector đã khoá trong hợp đồng."""
    sel = {k: _norm(case.get(k)) for k in SELECTORS if _norm(case.get(k))}
    if not sel:
        return None, sel, "hợp đồng không khai selector nào"
    d = df
    for k, v in sel.items():
        if k not in d.columns:
            return None, sel, f"DataFrame không có cột selector `{k}`"
        d = d[d[k].astype("string") == v]
    return d, sel, None


def _run_cells(df, case: dict, base: dict) -> dict:
    """Ca ĐA Ô: `expected_cells` là danh sách ô đã ghim, mỗi ô có selector riêng.

    Ca như "so hai kỳ", "tỷ số", "cộng dòng con" không diễn đạt được bằng một ô.
    Ghim TỪNG ô rồi đòi tất cả khớp — vẫn giữ nguyên tắc: selector và kỳ vọng
    đều đến từ hợp đồng, không đến từ dữ liệu đang kiểm.
    """
    cells = case["expected_cells"]
    results, bad = [], 0
    for idx, cell in enumerate(cells):
        d, sel, err = _select(df, cell)
        if err:
            results.append({"i": idx, "status": "ERROR", "reason": err})
            bad += 1
            continue
        if len(d) != 1:
            results.append({"i": idx, "status": "FAIL", "selectors": sel,
                            "reason": f"selector khớp {len(d)} dòng, cần đúng 1"})
            bad += 1
            continue
        row = d.iloc[0]        # an toàn: `d` đã bị selector của hợp đồng ghim còn 1 dòng
        exp = cell.get("expect") or {}
        mism = [f for f in exp if _norm(exp[f]) !=
                (_norm(row[f]) if f in d.columns else None)]
        results.append({"i": idx, "status": "FAIL" if mism else "PASS",
                        "selectors": sel, "mismatched_fields": mism,
                        "n_fields_checked": len(exp)})
        bad += bool(mism)
    return {**base, "status": "PASS" if bad == 0 else "FAIL",
            "n_cells": len(cells), "cells": results,
            "derived_assertion": case.get("derived")}


def _run_case(df, case: dict) -> dict:
    cid, name = case.get("id"), case.get("name")
    base = {"case_id": cid, "name": name,
            "abstain_expected": bool(case.get("abstain"))}
    if case.get("expected_cells") and not case.get("abstain"):
        return _run_cells(df, case, base)
    d, sel, err = _select(df, case)
    base["selectors"] = sel
    if err:
        return {**base, "status": "ERROR", "reason": err}

    n = int(len(d))
    base["n_rows_selected"] = n

    # ── ca ABSTAIN ────────────────────────────────────────────────────────
    if case.get("abstain"):
        reason = _norm(case.get("expected_abstain_reason")
                       or case.get("abstain_reason"))
        if not reason:
            return {**base, "status": "ERROR",
                    "reason": "ca abstain nhưng hợp đồng chưa khoá `abstain_reason`"}
        if n == 0:
            return {**base, "status": "PASS", "abstain_reason": reason,
                    "trace": "selector không khớp dòng nào — hệ thống không thể trả lời"}
        if "execution_ready" in d.columns:
            # RC2-043 · Đo trên ĐÚNG QUẦN THỂ mà hợp đồng nói tới.
            #
            # Kỳ vọng đóng băng là: "fact MƠ HỒ không được vào execution_ready".
            # Selector của ca 10 chỉ ghim tới mức BẢNG, nên nó lấy cả 41 dòng
            # của bảng — trong đó chỉ 14 dòng mang `collision_class`. Đếm
            # `execution_ready` trên cả 41 là đếm nhầm quần thể: 27 dòng ready
            # kia là những fact KHÔNG mơ hồ, chúng được phép trả lời.
            #
            # Đo trên `7aa8b4c22984bf5f`: ready ∩ collision = 0 ở bảng đó và 0
            # trên TOÀN DB. Hệ thống đã từ chối đúng chỗ.
            #
            # Kỳ vọng KHÔNG đổi; chỉ phép đo được đưa về đúng tập nó mô tả.
            lop = _norm(case.get("collision_class"))
            pham_vi = d
            if lop:
                if "collision_class" not in d.columns:
                    return {**base, "status": "ERROR",
                            "reason": "hợp đồng khoá `collision_class` nhưng "
                                      "DataFrame không có cột đó để khoanh vùng"}
                pham_vi = d[d["collision_class"].astype("string") == lop]
                base["n_rows_ambiguous"] = int(len(pham_vi))
                if len(pham_vi) == 0:
                    return {**base, "status": "ERROR", "abstain_reason": reason,
                            "reason": f"không dòng nào mang collision_class={lop} — "
                                      "fact mơ hồ đã biến mất, KHÔNG kiểm được"}
            ready = pham_vi[pham_vi["execution_ready"].astype("string")
                            .isin(["1", "True", "true"])]
            if len(ready) == 0:
                return {**base, "status": "PASS", "abstain_reason": reason,
                        "scope": (f"collision_class={lop}" if lop else "toàn bộ selector"),
                        "trace": f"{n} dòng khớp selector · {len(pham_vi)} dòng mơ hồ · "
                                 "0 dòng execution_ready → TỪ CHỐI đúng"}
            return {**base, "status": "FAIL", "abstain_reason": reason,
                    "scope": (f"collision_class={lop}" if lop else "toàn bộ selector"),
                    "trace": f"{len(ready)}/{len(pham_vi)} dòng MƠ HỒ vẫn "
                             "execution_ready — hệ thống TRẢ LỜI một ca lẽ ra phải từ chối"}
        return {**base, "status": "ERROR",
                "reason": "DataFrame không có cột `execution_ready` để kiểm abstain"}

    # ── ca có KỲ VỌNG ─────────────────────────────────────────────────────
    exp = case.get("expected") or {}
    if not exp:
        return {**base, "status": "ERROR",
                "reason": "hợp đồng CHƯA khoá `expected` cho ca này — "
                          "chưa đủ điều kiện kiểm, KHÔNG được coi là skip"}
    if n == 0:
        return {**base, "status": "FAIL",
                "trace": "selector đã khoá nhưng không khớp dòng nào trong DB đang kiểm"}
    if n > 1:
        return {**base, "status": "FAIL",
                "trace": f"selector khớp {n} dòng — hợp đồng đòi ĐÚNG MỘT ô"}

    row = d.iloc[0]          # an toàn: `d` đã bị selector của hợp đồng ghim còn 1 dòng
    mism, checked = [], {}
    for f in COMPARABLE:
        if f not in exp:
            continue
        want = _norm(exp[f])
        got = _norm(row[f]) if f in d.columns else None
        checked[f] = {"expected": want, "actual": got}
        if want != got:
            mism.append(f)
    if not checked:
        return {**base, "status": "ERROR",
                "reason": "không trường nào của `expected` so được với DataFrame"}
    return {**base, "status": "FAIL" if mism else "PASS",
            "n_fields_checked": len(checked), "mismatched_fields": mism,
            "comparison": checked}


def run(df, spec: dict) -> dict:
    cases = spec.get("cases") or []
    out = [_run_case(df, c) for c in cases]
    tally = {s: sum(1 for r in out if r["status"] == s)
             for s in ("PASS", "FAIL", "ERROR")}
    return {
        "contract_version": spec.get("contract_version"),
        "evidence_db": spec.get("evidence_db"),
        "evidence_db_sha256": spec.get("evidence_db_sha256"),
        "selector_tool": spec.get("selector"),
        "total": len(cases),
        "passed": tally["PASS"], "failed": tally["FAIL"],
        "errors": tally["ERROR"], "skipped": 0,
        "acceptance": "10/10 PASS · 0 skip · 0 error",
        "cases": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="RC-19 · replay theo hợp đồng gold đã đóng băng")
    ap.add_argument("db", help="release silver.db (có v_long_dataframe)")
    ap.add_argument("--expected", required=True,
                    help="configs/replay_expected_v1.yaml — BẮT BUỘC. Không có "
                         "hợp đồng thì không có kỳ vọng, và không có kỳ vọng "
                         "thì bài kiểm tự chấm chính nó.")
    ap.add_argument("-o", "--out", default="reports")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    spec_path = Path(a.expected)
    if not spec_path.is_file():
        print(f"LỖI: không thấy hợp đồng {spec_path}", file=sys.stderr)
        return 2
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not spec.get("cases"):
        print("LỖI: hợp đồng không có ca nào", file=sys.stderr)
        return 2

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    lim = f" LIMIT {a.limit}" if a.limit else ""
    # `value` đọc dạng CHUỖI có chủ đích: `Decimal` qua TEXT là bất biến DI-05.
    # Ép CHUỖI ngay từ SQL cho mọi trường số có thể mang NULL: pandas nạp cột
    # có NULL thành float64, và dấu chấm sinh ra ở đây đi thẳng vào phép so.
    #
    # Chỉ khai `dtype` cho cột CÓ THẬT trong view — pandas ném KeyError nếu khoá
    # không tồn tại, và một view rút gọn (hoặc bản lược đồ khác) sẽ làm cả công
    # cụ chết thay vì báo FAIL đúng chỗ.
    co_that = {r[1] for r in con.execute("PRAGMA table_info(v_long_dataframe)")}
    ep_chuoi = {c: "string" for c in
                ("value", "value_raw", "scale", "row_idx", "col_idx")
                if c in co_that}
    df = pd.read_sql_query(f"SELECT * FROM v_long_dataframe{lim}", con,
                           dtype=ep_chuoi or None)
    aliases = apply_view_aliases(df)
    # `observation_uid` KHÔNG có trong `v_long_dataframe` nhưng hợp đồng khoá
    # nó, và nó là bằng chứng mạnh nhất về tính ổn định danh tính. Lấy từ bảng
    # `observations` của CHÍNH DB đang kiểm, nối bằng `source_cell_uid` — danh
    # tính vật lý, không phải nhãn.
    if "observation_uid" not in df.columns and "source_cell_uid" in df.columns:
        try:
            m = pd.read_sql_query(
                "SELECT source_cell_uid, observation_uid FROM observations", con)
            df = df.merge(m, on="source_cell_uid", how="left")
            aliases.append("observation_uid <- observations JOIN source_cell_uid")
        except Exception as exc:                             # pragma: no cover
            aliases.append(f"observation_uid KHÔNG nối được: {exc.__class__.__name__}")
    con.close()

    try:
        _c = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        _bid = _c.execute(
            "SELECT value FROM build_meta WHERE key='build_id'").fetchone()
        _c.close()
        _bid = _bid[0] if _bid else None
    except sqlite3.Error:
        _bid = None
    rep = {"db": str(a.db),
           # RC2-047 · Doc 52 §7 doi moi report mang build ID.
           "build_id": _bid,
           "expected_contract": str(spec_path),
           "expected_contract_sha256": hashlib.sha256(
               spec_path.read_bytes()).hexdigest(),
           "rows": int(len(df)),
           # Ghi RÕ đã ánh xạ những gì: người review thấy được cột nào so với
           # cột nào, không phải tin một bảng tên ẩn trong mã.
           "view_aliases_applied": aliases,
           "docs": int(df.doc_id.nunique()) if "doc_id" in df.columns else None,
           **run(df, spec)}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "replay_report.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"╔═══ REPLAY · hợp đồng {rep['contract_version']} ═══╗")
    for c in rep["cases"]:
        mark = {"PASS": "✓", "FAIL": "✗", "ERROR": "!"}[c["status"]]
        extra = ""
        if c["status"] == "FAIL" and c.get("mismatched_fields"):
            extra = "  lệch: " + ", ".join(c["mismatched_fields"])
        elif c["status"] != "PASS":
            extra = "  " + str(c.get("reason") or c.get("trace") or "")[:70]
        print(f"  {mark} {str(c['case_id']):>2} {str(c['name'])[:38]:<40}"
              f"{c['status']:<6}{extra}")
    print(f"\n  {rep['passed']}/{rep['total']} PASS · {rep['failed']} FAIL "
          f"· {rep['errors']} ERROR · {rep['skipped']} SKIP")
    print(f"  -> {f}")

    ok = (rep["passed"] == rep["total"] and rep["failed"] == 0
          and rep["errors"] == 0 and rep["skipped"] == 0)
    print(f"  C5 = {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
