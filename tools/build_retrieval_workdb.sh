#!/usr/bin/env bash
# Dựng DB LÀM VIỆC cho tầng Retrieval từ gói Silver đã chứng nhận.
#
# Vì sao không dùng thẳng `silver.db` trong gói: nó thiếu chỉ mục cho các truy
# vấn của tầng này, và THÊM CHỈ MỤC VÀO GÓI LÀ PHÁ `SHA256SUMS` — gói đã chứng
# nhận sẽ không verify được nữa. Đo trên A6, lọc cứng lái sai chiều mất
# 2.478 ms; đúng chiều mất 2 ms. Chỉ mục ở đây là để không ai phải nhớ điều đó.
#
# `PROVENANCE.json` là BẮT BUỘC. Sáu tháng nữa không ai nhớ `work.db` sinh từ
# gói nào, và một bản làm việc mồ côi là nguồn của những con số không ai giải
# thích được.
#
# HỢP ĐỒNG THAM SỐ (sửa theo review 127 §2.6 — "Cách A")
# -----------------------------------------------------
# README của packet sync_122_1 dạy chạy `bash tools/build_retrieval_workdb.sh
# <silver.db> <work.db>`, nhưng bản cũ chỉ đọc SRC/OUT/PKG từ environment nên
# lệnh trong tài liệu LUÔN thất bại trên máy review. Đây là lỗi thực thi P0, đã
# sửa: positional arguments được ưu tiên, environment vẫn dùng được, default
# giữ nguyên. Ba cách gọi dưới đây tương đương:
#
#   bash tools/build_retrieval_workdb.sh                       # default
#   bash tools/build_retrieval_workdb.sh <silver.db> <work.db> [<a6.zip>]
#   SRC=… OUT=… PKG=… bash tools/build_retrieval_workdb.sh
#
# `--verify-only <work.db>` chỉ kiểm identity + 4 index + smoke, không dựng lại.
set -eu

usage() {
  cat >&2 <<'USAGE'
dùng:
  build_retrieval_workdb.sh [SILVER_DB] [WORK_DB] [A6_PACKAGE_ZIP]
  build_retrieval_workdb.sh --verify-only WORK_DB
biến môi trường tương đương: SRC, OUT, PKG, BID
USAGE
}

BID=${BID:-b3e9684004679ffb}

VERIFY_ONLY=0
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  --verify-only)
    VERIFY_ONLY=1
    [ $# -ge 2 ] || { echo "✗ --verify-only cần đường dẫn work.db" >&2; usage; exit 2; }
    OUT=$2 ;;
  *)
    # positional THẮNG environment; environment THẮNG default.
    SRC=${1:-${SRC:-artifacts/rc2/release_finala6/silver.db}}
    OUT=${2:-${OUT:-artifacts/retrieval/work.db}}
    PKG=${3:-${PKG:-artifacts/rc2/packagesa6/silver_v1_rc2_${BID}_a6_run1.zip}} ;;
esac

# Kiểm identity + 4 index + smoke trên một work.db đã có. Review 127 §2.6 yêu
# cầu kiểm ĐỦ BỐN INDEX, không chỉ table/row counts.
verify_workdb() {
  python3 - "$1" <<'PY'
import hashlib, json, sqlite3, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file():
    print(f"✗ không thấy {p}", file=sys.stderr); raise SystemExit(2)
c = sqlite3.connect(f"file:{p}?mode=ro&immutable=1", uri=True)
want_ix = ["ix_doc_tky", "ix_obs_tab_period", "ix_tc_stmt_ticker", "ix_tc_ticker_year"]
got_ix = sorted(n for (n,) in c.execute(
    "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%'"))
missing = [i for i in want_ix if i not in got_ix]
tables = sorted(n for (n,) in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table'"))
counts = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
          for t in ("observations", "documents", "table_cards", "tables", "rows")}
meta = dict(c.execute("SELECT key,value FROM build_meta"))
rep = {"work_db": str(p), "bytes": p.stat().st_size,
       "build_id": meta.get("build_id"),
       "n_tables_in_schema": len(tables), "row_counts": counts,
       "indexes_required": want_ix, "indexes_present": got_ix,
       "indexes_missing": missing,
       "verdict": "PASS" if not missing else "FAIL_MISSING_INDEX"}
out = p.parent / "workdb_verify_report.json"
out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=1))
print("->", out)
raise SystemExit(0 if not missing else 3)
PY
}

if [ "$VERIFY_ONLY" = 1 ]; then
  verify_workdb "$OUT"; exit $?
fi

[ -f "$SRC" ] || { echo "✗ thiếu $SRC" >&2; usage; exit 2; }
mkdir -p "$(dirname "$OUT")"
[ ! -e "$OUT" ] || { echo "✗ $OUT đã tồn tại — xoá hoặc đặt OUT= khác" >&2; exit 2; }

GOT=$(python3 -c "
import sqlite3,sys
c=sqlite3.connect('file:$SRC?mode=ro',uri=True)
print(dict(c.execute('SELECT key,value FROM build_meta'))['build_id'])")
[ "$GOT" = "$BID" ] || { echo "✗ $SRC mang build_id '$GOT', yêu cầu '$BID'" >&2; exit 2; }
echo "• nguồn: $SRC  (build_id $GOT ✓)"

echo "── chép ──"
cp "$SRC" "$OUT"

echo "── chỉ mục cho lọc cứng ──"
python3 - "$OUT" <<'PY'
import sqlite3, sys, time
c = sqlite3.connect(sys.argv[1])
IX = [
    # S1 lọc theo (ticker, năm). `table_cards` KHÔNG có chỉ mục này trong gói.
    ("ix_tc_ticker_year", "table_cards(ticker, doc_year)"),
    ("ix_tc_stmt_ticker", "table_cards(statement_type, ticker)"),
    # `documents` là bảng lái (1.973 dòng) — chỉ mục để join không quét.
    ("ix_doc_tky",        "documents(ticker, doc_year, basis)"),
    # S4 lấy ô theo khoá ngữ nghĩa.
    ("ix_obs_tab_period", "observations(table_uid, period_end)"),
]
for name, spec in IX:
    t0 = time.time()
    c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {spec}")
    print(f"   {name:20s} {time.time()-t0:6.1f}s")
t0 = time.time(); c.execute("ANALYZE"); c.commit()
print(f"   ANALYZE              {time.time()-t0:6.1f}s")
c.close()
PY

echo "── PROVENANCE ──"
python3 - "$OUT" "$SRC" "$PKG" "$BID" <<'PY'
import hashlib, json, os, subprocess, sys
from pathlib import Path
out, src, pkg, bid = map(Path, sys.argv[1:4]), None, None, None
out, src, pkg, bid = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""): h.update(c)
    return h.hexdigest()
def sh(*c):
    try: return subprocess.run(c, capture_output=True, text=True).stdout.strip() or None
    except Exception: return None
man = {
 "_schema": "DB lam viec cua tang Retrieval — DAN XUAT, khong phai goi chung nhan.",
 "build_id": bid,
 "source_release_db": str(src),
 "source_release_db_sha256": sha(src),
 "source_package": str(pkg) if pkg.is_file() else None,
 "source_package_sha256": sha(pkg) if pkg.is_file() else "MISSING: khong tim thay goi",
 "work_db": str(out), "work_db_bytes": out.stat().st_size,
 "indexes_added": ["ix_tc_ticker_year", "ix_tc_stmt_ticker",
                   "ix_doc_tky", "ix_obs_tab_period"],
 "created_by_commit": sh("git", "rev-parse", "HEAD"),
 "canh_bao": ("work.db KHAC goi chung nhan o chi muc va thong ke ANALYZE. "
              "KHONG dung no lam bang chung; moi khang dinh ve du lieu phai "
              "quy ve goi va sha256 o tren."),
}
(out.parent / "PROVENANCE.json").write_text(
    json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
print("   ->", out.parent / "PROVENANCE.json")
print("   package sha256:", str(man["source_package_sha256"])[:32], "…")
PY
echo "── kiểm 4 index + smoke ──"
verify_workdb "$OUT"

echo "✓ xong · $(du -h "$OUT" | cut -f1)  $OUT"
