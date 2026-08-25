#!/usr/bin/env python3
"""RC-15 · cổng C1 — chứng minh KHÔNG MẤT DỮ LIỆU theo TẬP UID.

Sai lầm phải tránh (doc 37 §6): **không** so `count_source_cells` với
`observations + dropped`. Hai đại lượng khác nhau — số đầu là MỌI ô nguồn,
số sau là tập ô MANG CHỮ SỐ đã xử lý. Trên RC1: 6.212.883 vs 3.413.207.

Mệnh đề C1 đúng, phát biểu theo tập:

    U_digit  = { source_cell_uid : ô là span anchor và text_clean có chữ số }
    U_obs    = { source_cell_uid trong observations }
    U_drop   = { source_cell_uid trong dropped_cells }

    (1)  U_obs ∩ U_drop = ∅          — không ô nào vừa giữ vừa bỏ
    (2)  U_digit \\ (U_obs ∪ U_drop) = ∅   — không ô số nào biến mất im lặng
    (3)  (U_obs ∪ U_drop) \\ U_digit = ∅   — không xử lý ô không mang số

Đếm số lượng bằng nhau KHÔNG chứng minh hai tập bằng nhau; công cụ này kiểm
cả ba mệnh đề tập hợp, rồi mới dùng đẳng thức lực lượng làm kiểm tra chéo.

CHỈ ĐỌC. Mở `mode=ro` + `PRAGMA query_only=ON`; không ghi gì vào DB đầu vào.

Exit code:  0 = PASS · 1 = FAIL · 2 = BLOCKED (thiếu bảng để kết luận)
            3 = lỗi sử dụng
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"

# Cổng thật của pipeline: observation_builder.py `_HAS_DIGIT = re.compile(r"\d")`
# áp lên `cell.text_clean`. Bản SQL tương đương cho chữ số ASCII.
SQL_HAS_DIGIT = "text_clean GLOB '*[0-9]*'"

# Ô mang số nhưng KHÔNG phải span anchor thì không sinh observation — nó là bản
# sao của ô gộp. Phải loại, nếu không nó sẽ trông như "mất dữ liệu".
ANCHOR = ("EXISTS(SELECT 1 FROM grid_cells g"
          " WHERE g.source_cell_uid = sc.source_cell_uid AND g.is_span_anchor = 1)")

U_DIGIT = (f"SELECT source_cell_uid FROM source_cells sc"
           f" WHERE sc.{SQL_HAS_DIGIT} AND {ANCHOR}")


class Check:
    def __init__(self, cid, title, expected, core=False):
        self.id, self.title, self.expected, self.core = cid, title, expected, core
        self.status, self.value, self.sql, self.seconds = BLOCKED, None, None, None
        self.note = ""

    def to_dict(self):
        return {"id": self.id, "title": self.title, "expected": self.expected,
                "core": self.core, "status": self.status, "value": self.value,
                "seconds": self.seconds, "sql": self.sql, "note": self.note}


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _scalar(con, sql: str):
    return con.execute(sql).fetchone()[0]


def _run_impl(con, chk: Check, sql: str, need: set[str], have: set[str],
              predicate=lambda v: v == 0):
    """Chạy một kiểm. Thiếu bảng → BLOCKED, KHÔNG bao giờ tự suy ra PASS."""
    missing = sorted(need - have)
    if missing:
        chk.status = BLOCKED
        chk.note = ("thiếu bảng: " + ", ".join(missing) +
                    " — DB này không đủ dữ liệu để kết luận. "
                    "Chạy lại trên build DB (có source_cells/grid_cells).")
        return chk
    chk.sql = " ".join(sql.split())
    t0 = time.time()
    chk.value = _scalar(con, sql)
    chk.seconds = round(time.time() - t0, 2)
    chk.status = PASS if predicate(chk.value) else FAIL
    return chk


def _sha256(p: Path, limit_mb: int | None = None) -> str:
    h = hashlib.sha256()
    cap = None if limit_mb is None else limit_mb * 1024 * 1024
    n = 0
    with p.open("rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
            n += len(blk)
            if cap is not None and n >= cap:
                return "partial:" + h.hexdigest()
    return h.hexdigest()


def build_checks(con, have: set[str], only: set[str] | None = None,
                 prior: dict[str, dict] | None = None) -> list[Check]:
    """`only` giới hạn kiểm sẽ CHẠY; `prior` nạp lại kết quả đã đo lượt trước.

    Kiểm bị bỏ qua mà không có kết quả cũ vẫn nằm trong report ở trạng thái
    BLOCKED kèm lý do — không bao giờ biến mất khỏi danh sách.
    """
    prior = prior or {}
    out: list[Check] = []

    def _run(con_, chk: Check, sql: str, need: set[str], have_: set[str],
             predicate=lambda v: v == 0):
        old = prior.get(chk.id)
        if old is not None:
            chk.status, chk.value = old["status"], old["value"]
            chk.sql, chk.seconds = old.get("sql"), old.get("seconds")
            chk.note = (old.get("note") or "") + " [nạp lại từ lượt trước]"
            return chk
        if only is not None and chk.id not in only:
            chk.status = BLOCKED
            chk.note = ("chưa chạy ở lượt này (--only). Chạy lại với "
                        f"--only {chk.id} --resume để đo.")
            return chk
        return _run_impl(con_, chk, sql, need, have_, predicate)

    c = Check("C1-01", "observation_uid là duy nhất", "= 0")
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM (SELECT observation_uid FROM observations"
        " GROUP BY 1 HAVING COUNT(*)>1)", {"observations"}, have))

    c = Check("C1-02", "một ô nguồn không sinh hai observation", "= 0")
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM (SELECT source_cell_uid FROM observations"
        " GROUP BY 1 HAVING COUNT(*)>1)", {"observations"}, have))

    c = Check("C1-03", "U_obs ∩ U_drop = ∅", "= 0", core=True)
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM (SELECT source_cell_uid FROM observations"
        " INTERSECT SELECT source_cell_uid FROM dropped_cells)",
        {"observations", "dropped_cells"}, have))

    c = Check("C1-04", "mọi ô bỏ đều có lý do", "= 0")
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM dropped_cells"
        " WHERE reason IS NULL OR TRIM(reason) = ''", {"dropped_cells"}, have))

    c = Check("C1-05", "observation không mồ côi khỏi source_cells", "= 0")
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM observations o WHERE NOT EXISTS"
        " (SELECT 1 FROM source_cells sc"
        "  WHERE sc.source_cell_uid = o.source_cell_uid)",
        {"observations", "source_cells"}, have))

    c = Check("C1-06", "dropped_cell không mồ côi khỏi source_cells", "= 0")
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM dropped_cells d WHERE NOT EXISTS"
        " (SELECT 1 FROM source_cells sc"
        "  WHERE sc.source_cell_uid = d.source_cell_uid)",
        {"dropped_cells", "source_cells"}, have))

    # ── ba kiểm CỐT LÕI: đây mới là mệnh đề no-loss ────────────────────────
    c = Check("C1-07", "U_digit \\ (U_obs ∪ U_drop) = ∅ — KHÔNG ô số nào "
                       "biến mất im lặng", "= 0", core=True)
    out.append(_run(con, c,
        f"SELECT COUNT(*) FROM ({U_DIGIT}"
        " EXCEPT SELECT source_cell_uid FROM observations"
        " EXCEPT SELECT source_cell_uid FROM dropped_cells)",
        {"observations", "dropped_cells", "source_cells", "grid_cells"}, have))

    c = Check("C1-08", "(U_obs ∪ U_drop) \\ U_digit = ∅ — không xử lý ô "
                       "không mang số", "= 0", core=True)
    out.append(_run(con, c,
        "SELECT COUNT(*) FROM (SELECT source_cell_uid FROM observations"
        " UNION SELECT source_cell_uid FROM dropped_cells"
        f" EXCEPT {U_DIGIT})",
        {"observations", "dropped_cells", "source_cells", "grid_cells"}, have))

    c = Check("C1-09", "kiểm chéo lực lượng: |U_obs| + |U_drop| − |U_digit|",
              "= 0", core=True)
    out.append(_run(con, c,
        "SELECT (SELECT COUNT(DISTINCT source_cell_uid) FROM observations)"
        "     + (SELECT COUNT(DISTINCT source_cell_uid) FROM dropped_cells)"
        f"     - (SELECT COUNT(*) FROM ({U_DIGIT}))",
        {"observations", "dropped_cells", "source_cells", "grid_cells"}, have))

    tbl = "tables" if "tables" in have else "table_features"
    c = Check("C1-10", "observation trỏ tới bảng có thật", "= 0")
    out.append(_run(con, c,
        f"SELECT COUNT(*) FROM observations o WHERE NOT EXISTS"
        f" (SELECT 1 FROM {tbl} t WHERE t.table_uid = o.table_uid)",
        {"observations", tbl}, have))

    return out


def unicode_digit_probe(con, have: set[str]) -> dict:
    """Kiểm HAI CHIỀU cho định nghĩa 'mang chữ số'.

    SQL dùng GLOB '*[0-9]*' (chỉ chữ số ASCII); Python `\\d` còn khớp chữ số
    Unicode. Nếu hai bên lệch, định nghĩa U_digit của công cụ này không trùng
    cổng thật của pipeline và mọi kết luận phía trên mất hiệu lực.
    """
    if "source_cells" not in have:
        return {"status": BLOCKED, "note": "thiếu source_cells"}
    rx = re.compile(r"\d")
    t0 = time.time()
    n_scan = n_mismatch = 0
    samples = []
    for (txt,) in con.execute(
            "SELECT text_clean FROM source_cells"
            f" WHERE text_clean IS NOT NULL AND NOT ({SQL_HAS_DIGIT})"):
        n_scan += 1
        if rx.search(txt):
            n_mismatch += 1
            if len(samples) < 5:
                samples.append(txt[:80])
    return {"status": PASS if n_mismatch == 0 else FAIL,
            "expected": "= 0",
            "value": n_mismatch,
            "n_scanned_non_ascii_digit_cells": n_scan,
            "samples": samples,
            "seconds": round(time.time() - t0, 2),
            "note": ("số ô mà SQL bảo KHÔNG có chữ số nhưng Python `\\d` bảo CÓ. "
                     "> 0 nghĩa là U_digit của công cụ hẹp hơn cổng thật của "
                     "pipeline — kết luận no-loss KHÔNG còn giá trị.")}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="RC-15 · cổng C1 no-loss theo tập UID (CHỈ ĐỌC)")
    ap.add_argument("--db", required=True, help="silver DB (build hoặc release)")
    ap.add_argument("--report", default=None, help="ghi report JSON ra đây")
    ap.add_argument("--label", default=None, help="nhãn build cho report")
    ap.add_argument("--check-unicode-digits", action="store_true",
                    help="kiểm hai chiều định nghĩa chữ số (quét chậm)")
    ap.add_argument("--db-sha256", action="store_true",
                    help="băm toàn bộ DB (chậm với file nhiều GB)")
    ap.add_argument("--only", default=None,
                    help="chỉ chạy các kiểm này, vd 'C1-07,C1-08'. Dùng với "
                         "--resume để chạy DB nhiều GB thành nhiều lượt.")
    ap.add_argument("--resume", action="store_true",
                    help="nạp report cũ ở --report, giữ kết quả đã đo, chỉ "
                         "chạy phần còn thiếu rồi ghi đè")
    a = ap.parse_args()
    only = {s.strip() for s in a.only.split(",")} if a.only else None

    db = Path(a.db)
    if not db.exists():
        print(f"LỖI: không thấy DB: {db}", file=sys.stderr)
        return 3

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    have = _tables(con)

    meta = {}
    if "build_meta" in have:
        try:
            meta = {k: v for k, v in con.execute(
                "SELECT key, value FROM build_meta")}
        except sqlite3.Error:
            meta = {}

    prior: dict[str, dict] = {}
    carry: dict = {}
    if a.resume and a.report and Path(a.report).exists():
        try:
            old = json.loads(Path(a.report).read_text(encoding="utf-8"))
            prior = {c["id"]: c for c in old.get("checks", [])
                     if c.get("status") in (PASS, FAIL)}
            carry = {k: old[k] for k in ("unicode_digit_probe", "db_sha256")
                     if k in old}
        except (json.JSONDecodeError, KeyError, TypeError):
            prior, carry = {}, {}

    checks = build_checks(con, have, only=only, prior=prior)

    rep = {
        "_schema": "RC-15 · C1 no-loss theo TẬP UID. Chỉ đọc.",
        "tool": "tools/no_loss_check.py",
        "tool_version": "1.0",
        "db_path": str(db),
        "db_bytes": db.stat().st_size,
        "db_label": a.label,
        "db_profile": meta.get("release_profile", "build (không có build_meta.release_profile)"),
        "build_id": meta.get("build_id"),
        "corpus_id": meta.get("corpus_id"),
        "tables_present": sorted(have),
        "digit_definition_sql": SQL_HAS_DIGIT,
        "digit_definition_source": "observation_builder.py `_HAS_DIGIT = re.compile(r'\\d')` trên text_clean",
        "anchor_restriction": "chỉ tính span anchor (grid_cells.is_span_anchor = 1)",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": [c.to_dict() for c in checks],
    }
    rep.update(carry)
    if a.db_sha256:
        rep["db_sha256"] = _sha256(db)
    if a.check_unicode_digits:
        rep["unicode_digit_probe"] = unicode_digit_probe(con, have)

    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_blocked = sum(1 for c in checks if c.status == BLOCKED)
    core_blocked = [c.id for c in checks if c.core and c.status == BLOCKED]
    probe = rep.get("unicode_digit_probe") or {}
    if probe.get("status") == FAIL:
        n_fail += 1

    if n_fail:
        verdict, code = FAIL, 1
    elif core_blocked:
        verdict, code = BLOCKED, 2
    elif n_blocked:
        # kiểm phụ thiếu, nhưng ba mệnh đề cốt lõi đã đo được
        verdict, code = "PASS_WITH_BLOCKED_NON_CORE", 0
    else:
        verdict, code = PASS, 0

    rep["summary"] = {
        "verdict": verdict,
        "n_checks": len(checks),
        "n_pass": sum(1 for c in checks if c.status == PASS),
        "n_fail": n_fail,
        "n_blocked": n_blocked,
        "core_blocked": core_blocked,
        "exit_code": code,
    }
    if core_blocked:
        rep["summary"]["why_blocked"] = (
            "Mệnh đề no-loss cốt lõi cần source_cells + grid_cells. DB slim "
            "release KHÔNG mang hai bảng này. Chạy C1 trên build DB "
            "(data/processed/a6/<ns>/<build_id>/silver.sqlite), không phải trên gói slim."
        )

    for c in checks:
        mark = {PASS: "✓", FAIL: "✗", BLOCKED: "∅"}[c.status]
        val = "—" if c.value is None else c.value
        print(f"  {mark} {c.id}  {str(val):>10}  ({c.expected:<4}) {c.title}")
        if c.note:
            print(f"      ↳ {c.note}")
    if probe:
        print(f"  probe unicode-digit: {probe.get('status')} "
              f"value={probe.get('value')}")
    print(f"\nC1 = {verdict}   pass={rep['summary']['n_pass']} "
          f"fail={n_fail} blocked={n_blocked}")

    if a.report:
        rp = Path(a.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print(f"report → {rp}")
    return code


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    sys.exit(main())
