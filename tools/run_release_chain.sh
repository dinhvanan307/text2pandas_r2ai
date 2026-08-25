#!/usr/bin/env bash
# Doc 52 §8 Bước 8–9 · dựng bản phát hành CUỐI rồi đóng gói hai lần và verify.
#
# Khác staging ở đúng một điểm, và điểm đó là lý do phải dựng lại: staging được
# dựng TRƯỚC khi có acceptance reports, nên chúng nằm NGOÀI `manifest.json` và
# `SHA256SUMS` của gói. Doc 52 §8 Bước 8 đòi thứ tự:
#
#   database/views/exports → acceptance reports → docs → counts → manifest → SHA256SUMS
#
# `manifest.json` được `release.py` ghi CUỐI CÙNG và băm mọi tệp khác trong thư
# mục, nên gieo `acceptance/` vào trước rồi mới dựng release là đủ để chúng vào
# cả manifest lẫn checksum. Người nhận gói khi đó có checksum cho chính bằng
# chứng đã chấp nhận nó.
set -u
BID=${BID:-b3e9684004679ffb}
A=${A:-artifacts/rc2/buildA6}
ACC=${ACC:-artifacts/rc2/acceptance_a6}
# REV cho phép dựng lại vào thư mục MỚI mà không phá bản đã chứng nhận.
# `dp-release` từ chối ghi đè, và đó là hành vi đúng — đường ra là đặt tên
# mới, không phải nới guard.
REV=${REV:-}
REL=artifacts/rc2/release_final${REV}
PKG=artifacts/rc2/packages${REV}
SUF=${REV:+_}${REV}
W=./tools/acceptance_step.sh

buoc () { local ten="$1"; shift
  echo ""; echo "═══ $ten ═══"
  "$W" "$ACC/$ten" "$@" || { echo "✗ DỪNG ở buoc [$ten] — xem $ACC/$ten/stdout.log" >&2; exit 1; }
  tail -n 5 "$ACC/$ten/stdout.log"; }

# ── cổng vào: KHÔNG đóng gói khi RC-20 chưa cho phép ─────────────────────
[ -f "$ACC/rc20/exit_code.txt" ] || { echo "✗ chưa chạy RC-20" >&2; exit 2; }
[ "$(cat "$ACC/rc20/exit_code.txt")" = "0" ] || {
  echo "✗ RC-20 exit $(cat "$ACC/rc20/exit_code.txt") — §8 cấm tạo manifest/package trước khi RC-20 cho phép" >&2
  exit 2; }
[ ! -e "$REL" ] || { echo "✗ $REL đã tồn tại — bản phát hành cuối phải ghi vào thư mục MỚI" >&2; exit 2; }

# GUARD · DB nguồn phải ĐÚNG bản dựng được yêu cầu.
#
# Bản trước hardcode `BID` nên biến truyền từ dòng lệnh bị ghi đè: người vận
# hành gọi với build A4 mà script lặng lẽ dựng gói từ A3, đóng gói hai lần
# giống hệt nhau, và verify PASS cả hai — vì gói TỰ NHẤT QUÁN. Verifier kiểm
# toàn vẹn, nó không đọc được ý định. Guard này đọc `build_id` thẳng từ DB.
SRC_DB="$A/silver/$BID/silver.sqlite"
[ -f "$SRC_DB" ] || { echo "✗ không thấy $SRC_DB — BID=$BID có đúng không?" >&2; exit 2; }
THAT=$(python3 - "$SRC_DB" <<'CHECKBID'
import sqlite3, sys
c = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
print(c.execute("SELECT value FROM build_meta WHERE key='build_id'").fetchone()[0])
CHECKBID
)
[ "$THAT" = "$BID" ] || {
  echo "✗ DB nguồn mang build_id '$THAT' nhưng yêu cầu '$BID'" >&2; exit 2; }
echo "• nguồn: $SRC_DB  (build_id $THAT ✓)"

# Bằng chứng gieo vào phải cùng bản dựng với DB. Gieo acceptance của bản khác
# là tạo ra một gói tự mâu thuẫn mà verify không bắt được.
GR="$ACC/rc20/gate_report.json"
[ -f "$GR" ] || { echo "✗ thiếu $GR" >&2; exit 2; }
ACC_BID=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['build_id'])" "$GR")
[ "$ACC_BID" = "$BID" ] || {
  echo "✗ bằng chứng ở $ACC thuộc build '$ACC_BID', không phải '$BID'" >&2; exit 2; }
echo "• bằng chứng: $ACC  (build_id $ACC_BID ✓)"

# ── Bước 8 · gieo acceptance vào TRƯỚC, rồi dựng release ─────────────────
mkdir -p "$REL/acceptance"
cp -R "$ACC"/. "$REL/acceptance"/
rm -f "$REL/acceptance/chain.console.log"
echo "• đã gieo $(find "$REL/acceptance" -type f | wc -l | tr -d ' ') tệp acceptance vào $REL"

# RC2-039 · limitation phải nằm TRONG gói mà bên dùng sẽ mở, không chỉ trong
# tài liệu bàn giao. `KNOWN_ISSUES.md` do `release_docs.py` sinh, mà tệp đó
# thuộc `source_hash` — sửa nó là đổi `build_id`. Nên khai bằng phụ lục gieo
# vào, cùng cohort đã khóa sha256 để bên dùng loại trừ được bằng một phép join.
cp artifacts/rc2/handoff/KNOWN_ISSUES_ADDENDUM_RC2_039.md "$REL/"
mkdir -p "$REL/cohorts"
cp artifacts/rc2/cohorts/share_count_rc1_to_a3.csv \
   artifacts/rc2/cohorts/rc2_039_cases.csv \
   artifacts/rc2/cohorts/removed_78_cases.csv "$REL/cohorts/"
echo "• đã gieo phụ lục RC2-039 và 3 cohort CSV vào $REL"

buoc release_final  make dp-release \
                      DB="$A/silver/$BID/silver.sqlite" \
                      BRONZE="$A/bronze/catalog_v2.sqlite" \
                      QUALITY="$A/silver/$BID/quality_report.json" \
                      REPORT_DIR="$ACC/release_final" \
                      GATE_REPORT="$GR" \
                      OUTPUT="$REL"

# ── Bước 9 · đóng gói HAI LẦN, so sha256 ─────────────────────────────────
mkdir -p "$PKG"
buoc package_run1${SUF}  python tools/package_release.py --dir "$REL" \
                     --out "$PKG/silver_v1_rc2_${BID}${SUF}_run1.zip"
buoc package_run2${SUF}  python tools/package_release.py --dir "$REL" \
                     --out "$PKG/silver_v1_rc2_${BID}${SUF}_run2.zip"

H1=$( (shasum -a 256 "$PKG/silver_v1_rc2_${BID}${SUF}_run1.zip" 2>/dev/null || sha256sum "$PKG/silver_v1_rc2_${BID}${SUF}_run1.zip") | cut -d' ' -f1)
H2=$( (shasum -a 256 "$PKG/silver_v1_rc2_${BID}${SUF}_run2.zip" 2>/dev/null || sha256sum "$PKG/silver_v1_rc2_${BID}${SUF}_run2.zip") | cut -d' ' -f1)
mkdir -p "$ACC/package_determinism${SUF}"
printf 'run1 %s\nrun2 %s\nidentical %s\n' "$H1" "$H2" \
  "$([ "$H1" = "$H2" ] && echo true || echo false)" \
  | tee "$ACC/package_determinism${SUF}/sha256.txt"
[ "$H1" = "$H2" ] || { echo "✗ HAI LẦN ĐÓNG GÓI KHÁC NHAU — gói không tất định" >&2; exit 1; }

# ── Bước 9 · verify từ bản giải nén SẠCH, cả hai gói ─────────────────────
buoc verify_run1${SUF}  make dp-verify PACKAGE="$PKG/silver_v1_rc2_${BID}${SUF}_run1.zip" TYPE=release
buoc verify_run2${SUF}  make dp-verify PACKAGE="$PKG/silver_v1_rc2_${BID}${SUF}_run2.zip" TYPE=release

echo ""
echo "✓ BƯỚC 8–9 HOÀN TẤT"
echo "  release : $REL"
echo "  package : $PKG/  (sha256 $H1)"
