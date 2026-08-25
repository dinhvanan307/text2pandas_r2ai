#!/usr/bin/env bash
# Doc 52 §8 · chuỗi acceptance, chạy ĐÚNG thứ tự và DỪNG ở lỗi đầu tiên.
#
# Vì sao là một script chứ không phải bảy lệnh dán tay: Doc 52 §7 đòi mỗi bước
# có `command.txt`, `stdout.log`, `exit_code.txt` và report băm được. Gõ tay bảy
# lần là bảy chỗ để quên một tệp — và một bộ bằng chứng thiếu một exit code thì
# theo §5.3 phải hạ xuống `OPERATOR_REPORTED`, không được ghi `PASS`.
#
#   ./tools/run_acceptance_chain.sh
#
# KHÔNG dựng lại A3/B3. Mọi bước chỉ ĐỌC artifact đã có; bước release ghi vào
# một thư mục MỚI.
set -u
# Tham số hoá cho A4. Mặc định trỏ A4; đặt biến môi trường để chạy lại cho
# một bản dựng khác mà không phải sửa script — sửa script giữa hai lần chạy là
# cách hai lần chạy trở nên không so được với nhau.
BID=${BID:-b3e9684004679ffb}
A=${A:-artifacts/rc2/buildA6}
B=${B:-artifacts/rc2/buildB6}
DB=$A/silver/$BID/silver.sqlite
ACC=${ACC:-artifacts/rc2/acceptance_a6}
STAGING=${STAGING:-artifacts/rc2/staging_a6}
# Mốc differential là A3, KHÔNG phải RC1.
#
# Doc 58 Bước 5: A4 phải chứng minh CHỈ những thay đổi đã khai mới xảy ra so
# với A3 — bản mà kiểm toán độc lập đã soi từng con số. So thẳng với RC1 sẽ
# trộn lẫn thay đổi của RC2 với thay đổi của A4, và không tách được cái nào
# do bản sửa RC2-039 gây ra.
# Mặc định luôn trỏ VÒNG TRƯỚC bản đang dựng. Để mặc định cũ (A3) sau khi
# đã qua A4/A5/A6 là mời một lần chạy sai mốc mà chain vẫn báo PASS.
BASE=${BASE:-artifacts/rc2/buildA5/silver/5ade9ae9d5f68b6a/silver.sqlite}
W=./tools/acceptance_step.sh

buoc () {  # buoc <ten> <lenh...>
  local ten="$1"; shift
  echo ""
  echo "═══ $ten ═══"
  "$W" "$ACC/$ten" "$@" || {
      echo "✗ DỪNG ở buoc [$ten] — xem $ACC/$ten/stdout.log" >&2
      exit 1; }
  tail -n 6 "$ACC/$ten/stdout.log"
}

[ -f "$DB" ] || { echo "✗ thiếu $DB" >&2; exit 2; }
[ -f "$BASE" ] || { echo "✗ thiếu mốc so sánh $BASE" >&2; exit 2; }
[ -d "$B" ] || { echo "✗ thiếu $B — cần cho C0-final" >&2; exit 2; }
# Release ĐÃ chạy thì không dựng lại: 6,96 GB và bảy phút, trong khi artifact
# đã có và mang đúng `build_id`. Nhưng chỉ bỏ qua khi CHỨNG MINH được nó thuộc
# đúng bản dựng này — không bao giờ bỏ qua vì "thư mục có vẻ ổn".
SKIP_RELEASE=0
if [ -e "$STAGING" ]; then
  got=$(python3 - "$STAGING/silver.db" <<'PY' 2>/dev/null
import sqlite3, sys
try:
    c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    r = c.execute("SELECT value FROM build_meta WHERE key='build_id'").fetchone()
    v = {x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    print(r[0] if r and "v_long_dataframe" in v else "")
except Exception:
    print("")
PY
)
  if [ "$got" = "$BID" ]; then
    SKIP_RELEASE=1
    echo "• $STAGING đã có silver.db build $BID kèm v_long_dataframe — bỏ qua Bước 5"
  else
    echo "✗ $STAGING đã tồn tại nhưng KHÔNG phải release của $BID (đọc được: '$got')" >&2
    echo "  Dọn hoặc đổi tên nó rồi chạy lại — release phải ghi vào thư mục MỚI." >&2
    exit 2
  fi
fi
mkdir -p "$ACC"

# ── Bước 1–4 · chạy LẠI qua bộ ghi bằng chứng ────────────────────────────
# Bốn cổng này đã PASS, nhưng chạy trước khi có `acceptance_step.sh` nên thiếu
# command/exit_code mà §7 đòi. Kết quả phải lặp lại y hệt — nếu không, chính
# việc đó là một phát hiện.
buoc c0_final    python tools/rebuild_check.py --build-a "$A" --build-b "$B" \
                   --mode final --db-sha256 \
                   --report "$ACC/c0_final/rebuild_check.json"
buoc c1_no_loss  python tools/no_loss_check.py --db "$DB" --label "$BID" \
                   --check-unicode-digits --db-sha256 \
                   --report "$ACC/c1_no_loss/c1_no_loss.json"
buoc differential python tools/differential_audit.py "$BASE" "$DB" \
                   -o "$ACC/differential" --samples 40 \
                   --cases "$ACC/differential/differential_cases.csv"
buoc readiness   python tools/readiness_report.py --db "$DB" --label "$BID" \
                   --report "$ACC/readiness/readiness_report.json" \
                   --by-reason-csv "$ACC/readiness/readiness_by_reason.csv"
buoc unresolved  python tools/unresolved_registry.py --db "$DB" --label "$BID" \
                   --report "$ACC/unresolved/unresolved.json" \
                   --cases "$ACC/unresolved/unresolved_cases.csv"

# ── Bước 5 · staging release ─────────────────────────────────────────────
if [ "$SKIP_RELEASE" = "0" ]; then
buoc release     make dp-release \
                   DB="$DB" \
                   BRONZE="$A/bronze/catalog_v2.sqlite" \
                   QUALITY="$A/silver/$BID/quality_report.json" \
                   REPORT_DIR="$ACC/release" \
                   OUTPUT="$STAGING"
fi

REL_DB="$STAGING/silver.db"
[ -f "$REL_DB" ] || { echo "✗ release không sinh $REL_DB" >&2; exit 1; }

# ── Bước 6 · replay 10/10 ────────────────────────────────────────────────
# Kỳ vọng đọc từ hợp đồng ĐÃ ĐÓNG BĂNG trước khi A3 tồn tại (§8 Bước 6).
buoc replay      python tools/replay_report.py "$REL_DB" \
                   --expected configs/replay_expected_v1.yaml -o "$ACC/replay"

# ── Bước 7 · RC-20 ───────────────────────────────────────────────────────
buoc rc20        python tools/gate_report.py "$DB" -o "$ACC/rc20" \
                   --rebuild-check "$ACC/c0_final/rebuild_check.json" \
                   --no-loss       "$ACC/c1_no_loss/c1_no_loss.json" \
                   --differential  "$ACC/differential/differential_audit.json" \
                   --readiness     "$ACC/readiness/readiness_report.json" \
                   --unresolved    "$ACC/unresolved/unresolved.json" \
                   --replay        "$ACC/replay/replay_report.json" \
                   --quality       "$A/silver/$BID/quality_report.json" \
                   --require-all

echo ""
echo "✓ CHUỖI ACCEPTANCE HOÀN TẤT — mọi bước exit 0"
echo "  bằng chứng: $ACC/"
