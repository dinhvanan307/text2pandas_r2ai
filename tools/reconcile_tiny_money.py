#!/usr/bin/env python3
"""RC-03 · Đối chiếu bộ phân loại tiny-money với COHORT ĐÃ ĐÓNG BĂNG.

Cohort `artifacts/policy/tiny_money_rc1_cohort.json` khoá 2.836 ca của RC1
**trước** remediation. Sau remediation, false value rời `observations` — nếu
chỉ query RC2 thì mất mẫu số gốc và không chứng minh được lineage.

Công cụ này chạy bộ phân loại HIỆN TẠI trên cohort đó và trả lời ba câu:

  1. Mỗi ca rơi vào lớp nào, và vì bằng chứng gì.
  2. Bao nhiêu ca là **lỗi của RULE CŨ** (đo trên giá trị thô) chứ không phải
     của dữ liệu — con số này phải bằng đúng 740 như đã ghi nhận ở RC1.
  3. Phần dư thật sự mơ hồ còn bao nhiêu.

Ba tín hiệu cần dữ liệu ngoài cohort:
  · S3 (`col_max_digits` / `peer_max_digits`) — cấp cột, lấy từ DB
  · RC-04 (bậc đơn vị suy từ nhãn cột) — lấy từ chính `col_path_text`

Chạy:
    python tools/reconcile_tiny_money.py \
        --cohort artifacts/policy/tiny_money_rc1_cohort.json \
        --db artifacts/rc1_baseline/silver.db \
        --out reports/rc03_tiny_money_reconciliation.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from text2pandas.pipelines.a6.tiny_money import (  # noqa: E402
    FALSE_VALUE_CLASSES, TINY_MONEY_VERSION, UNRESOLVED_CLASSES,
    classify_tiny_money)
from text2pandas.pipelines.a6.unit_resolver import UNIT_VERSION, _find_scale  # noqa: E402

RECONCILE_VERSION = "1.0"
_DIGIT = re.compile(r"\d")


def _num(raw) -> str | None:
    """`(676)` → `-676` · `7,49` → `7.49`. Trả None nếu không phải số."""
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(".", "").replace(",", ".") if s.count(",") == 1 \
        else s.strip("()")
    try:
        float(s)
    except ValueError:
        return None
    return ("-" + s) if neg else s


def _column_digit_signals(db: Path, table_uids: list[str]):
    """S3 · số chữ số lớn nhất theo cột, và lớn nhất trong cả bảng."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA temp_store=FILE")
    colmax: dict[tuple[str, int], int] = {}
    for i in range(0, len(table_uids), 500):
        chunk = table_uids[i:i + 500]
        q = ("SELECT table_uid, grid_col_idx, value_decimal_text FROM observations"
             " WHERE table_uid IN (%s)" % ",".join("?" * len(chunk)))
        for t, c, v in con.execute(q, chunk):
            n = len(_DIGIT.findall((v or "").split(".")[0]))
            if n > colmax.get((t, c), 0):
                colmax[(t, c)] = n
    peermax: dict[str, int] = collections.defaultdict(int)
    for (t, _c), n in colmax.items():
        if n > peermax[t]:
            peermax[t] = n
    uid2col: dict[str, tuple[str, int]] = {}
    con.close()
    return colmax, peermax, uid2col


def _uid_columns(db: Path, uids: list[str]) -> dict[str, tuple[str, int]]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = {}
    for i in range(0, len(uids), 900):
        chunk = uids[i:i + 900]
        q = ("SELECT observation_uid, table_uid, grid_col_idx FROM observations"
             " WHERE observation_uid IN (%s)" % ",".join("?" * len(chunk)))
        for u, t, c in con.execute(q, chunk):
            out[u] = (t, c)
    con.close()
    return out


def reconcile(cohort_path: Path, db: Path, rows_out: Path | None = None) -> dict:
    """P1-03 · `rows_out` xuat QUYET DINH TUNG CA.

    CSV cohort cu chi la DAU VAO (uid + gia tri tho), khong co classification/
    reason/decision — nen khong ai tai kiem duoc phan loai, chi co the TIN.
    """
    blob = json.loads(cohort_path.read_text(encoding="utf-8"))
    coh = blob["cohort"]
    uids = [r["observation_uid"] for r in coh]
    tabs = sorted({r["table_uid"] for r in coh})

    colmax, peermax, _ = _column_digit_signals(db, tabs)
    uid2col = _uid_columns(db, uids)

    counts: collections.Counter[str] = collections.Counter()
    by_signal: collections.Counter[str] = collections.Counter()
    rc04_rescued = 0
    residual = []
    row_records: list[dict] = []

    for r in coh:
        key = uid2col.get(r["observation_uid"])
        cm = colmax.get(key) if key else None
        pm = peermax.get(key[0]) if key else None

        scale = r["scale_exponent"]
        rescued_by_rc04 = False
        if scale in (0, None):
            s2 = _find_scale(r["col_path_text"] or "")
            if s2 is not None:
                scale, rescued_by_rc04 = s2, True

        cls, why = classify_tiny_money(
            value_decimal_text=_num(r["value_source"]) or r["value_decimal_text"],
            value_source=r["value_source"], scale_exponent=scale,
            unit_kind=r["unit_kind"], scale_source=r["scale_source"],
            header_path_text=r["col_path_text"],
            row_label=r["metric_label_clean"] or r["row_path_text"],
            col_max_digits=cm, peer_max_digits=pm)
        counts[cls] += 1
        by_signal[why.split("—")[0].strip()[:60]] += 1
        row_records.append({
            "observation_uid": r["observation_uid"],
            "source_cell_uid": r.get("source_cell_uid", ""),
            "classification": cls,
            "reason_code": why.split("—")[0].strip()[:60],
            "decision": ("BLOCK_execution_ready" if cls in UNRESOLVED_CLASSES
                         else "ALLOW"),
            "rule_version": TINY_MONEY_VERSION,
            "unit_version": UNIT_VERSION,
            "scale_exponent_used": scale,
            "rescued_by_rc04": int(rescued_by_rc04),
            "evidence_ref": r.get("evidence_ref", ""),
        })
        if rescued_by_rc04 and cls != "parse_or_column_role_unresolved":
            rc04_rescued += 1
        if cls in UNRESOLVED_CLASSES:
            residual.append({
                "observation_uid": r["observation_uid"],
                "evidence_ref": r["evidence_ref"],
                "col_path_text": r["col_path_text"],
                "metric_label_clean": r["metric_label_clean"],
                "value_source": r["value_source"],
                "scale_exponent": scale,
                "col_max_digits": cm, "peer_max_digits": pm,
            })

    n = len(coh)
    n_false = sum(v for k, v in counts.items() if k in FALSE_VALUE_CLASSES)
    n_legit = sum(v for k, v in counts.items() if k.startswith("legitimate"))
    n_unres = sum(v for k, v in counts.items() if k in UNRESOLVED_CLASSES)
    rep = {
        "reconcile_version": RECONCILE_VERSION,
        "tiny_money_version": TINY_MONEY_VERSION,
        "unit_version": UNIT_VERSION,
        "cohort_sha256": blob["cohort_sha256"],
        "denominator": blob["denominator"],
        "classified": n,
        "completeness": "OK" if n == blob["denominator"] else "MISMATCH",
        "by_class": dict(counts),
        "rollup": {
            "false_value_rời_observations": n_false,
            "hợp_lệ_giữ_không_chặn": n_legit,
            "unresolved_giữ_và_chặn_ready": n_unres,
        },
        "rule_cũ_đo_sai_thước": counts.get("legitimate_small_money", 0),
        "rc04_gỡ_thêm": rc04_rescued,
        "residual_pct": round(n_unres / n * 100, 2),
        "residual_sample": residual[:40],
        "_invariant": "false + hợp lệ + unresolved = denominator",
        "_invariant_holds": n_false + n_legit + n_unres == blob["denominator"],
    }
    if rows_out is not None:
        rows_out.parent.mkdir(parents=True, exist_ok=True)
        cols = ["observation_uid", "source_cell_uid", "classification",
                "reason_code", "decision", "rule_version", "unit_version",
                "scale_exponent_used", "rescued_by_rc04", "evidence_ref"]
        with rows_out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for rec in row_records:
                w.writerow({k: rec.get(k, "") for k in cols})
        # Tu kiem: tong theo classification trong CSV PHAI tai tao dung
        # class_counts trong JSON. Lech = mot trong hai sai.
        from collections import Counter as _C
        csv_counts = dict(_C(r["classification"] for r in row_records))
        rep["row_level_output"] = {
            "path": str(rows_out), "n_rows": len(row_records),
            "counts_from_csv": csv_counts,
            "reconciles_with_class_counts": csv_counts == dict(counts),
        }
    return rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--out-rows", type=Path, dest="out_rows",
                    help="P1-03 · CSV quyet dinh TUNG CA (uid, classification, "
                         "reason_code, decision, rule_version, unit_version)")
    a = ap.parse_args()
    for p in (a.cohort, a.db):
        if not p.exists():
            print(f"MISSING ARTIFACT: {p}", file=sys.stderr)
            return 2
    rep = reconcile(a.cohort, a.db, rows_out=a.out_rows)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
        print(f"đã ghi {a.out}")
    for k, v in rep["by_class"].items():
        print(f"  {k:42s} {v:6,}")
    print(f"  → phần dư mơ hồ: {rep['rollup']['unresolved_giữ_và_chặn_ready']:,}"
          f" ({rep['residual_pct']}%)")
    rl = rep.get("row_level_output")
    if rl:
        print(f"  → row-level: {rl['n_rows']:,} dòng → {rl['path']}")
        if not rl["reconciles_with_class_counts"]:
            print("LỖI: tổng theo classification trong CSV KHÔNG tái tạo được "
                  "class_counts trong JSON — một trong hai sai.", file=sys.stderr)
            return 3
    return 0 if rep["_invariant_holds"] and rep["completeness"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
