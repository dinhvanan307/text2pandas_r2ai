#!/usr/bin/env bash
# Verify packet từ MỘT BẢN GIẢI NÉN MỚI — copy-paste được, không đoán.
#
# Review 127 §9 liệt kê 7 dấu tick để mở `GO_D0_VERIFIED`. Script này chạy hết
# và ghi `reports/reviewer_replay_report.json` với verdict từng mục. Nó KHÔNG
# dừng ở lỗi đầu tiên: người review cần thấy TOÀN BỘ bức tranh trong một lần
# chạy, không phải sửa-chạy-lại bảy vòng.
#
# ── SỬA 21/08 (bản 2) — ba lỗi của bản đầu ────────────────────────────────────
# Bản đầu giả định MỌI packet đều self-contained. Sai: `sync_122_2` là packet
# BỔ SUNG, cố ý KHÔNG chứa `source/`, `controls/`, `work.db` (SHA đã khớp hai
# máy, gửi lại 1,68 GB là lãng phí). Hậu quả khi chạy nó từ bản giải nén:
#
#   ✗ import_pipeline   FAIL   <- KHÔNG phải lỗi, packet vốn không có source
#   ✗ primary_boost     FAIL   <- như trên
#   ✓ source_identity   PASS   <- NGUY HIỂM NHẤT: pass với n_files = 22,
#                                 băm 22 file lẻ rồi báo một tree_sha256 vô nghĩa
#
# Một dấu ĐỎ sai làm người ta mất thời gian. Một dấu XANH sai làm người ta tin
# nhầm. Bản này sửa cả ba:
#
#   1. Không tìm thấy tài nguyên  → `N/A` kèm LÝ DO, không phải FAIL.
#   2. `N/A` không tính là pass; verdict tổng ghi rõ packet còn thiếu gì.
#   3. `--repo <path>` trỏ sang cây có source/controls/work.db để chạy đủ.
#
# Dùng:
#   bash ops/environment/verify_packet.sh
#   bash ops/environment/verify_packet.sh --repo /path/to/Text2Pandas
set -u

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"

REPO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO=$(cd "$2" && pwd); shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "tham số lạ: $1" >&2; exit 2 ;;
  esac
done

# ── định vị tài nguyên: packet đầy đủ > repo hiện tại > --repo ───────────────
find_first() { for p in "$@"; do [ -e "$p" ] && { echo "$p"; return 0; }; done; return 1; }

SRC_ROOT=$(find_first source/src src ${REPO:+"$REPO/src"}) || SRC_ROOT=""
CTRL=$(find_first controls/submission_P0I.zip sync_122_1/controls/submission_P0I.zip \
        artifacts/submissions/legacy/submission_P0I.zip \
        ${REPO:+"$REPO/sync_122_1/controls/submission_P0I.zip"}) || CTRL=""
WDB=$(find_first data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db ${REPO:+"$REPO/data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"}) || WDB=""

# Bản-1 của script không in dòng nào trước `• layout:`, nên một bản GIẢI NÉN CŨ
# chạy y hệt bản mới trong mắt người đọc log. Đó là cách một lần chạy sai được
# tin là đúng. Nay script tự khai phiên bản packet ở dòng đầu tiên.
SCRIPT_VER="verify_packet.sh v2"
PACKET_KIND="unknown"; PACKET_VER="<không có packet_kind.json>"
if [ -f packet_kind.json ]; then
  PACKET_KIND=$(python3 -c "import json;print(json.load(open('packet_kind.json')).get('kind','unknown'))" 2>/dev/null || echo unknown)
  PACKET_VER=$(python3 -c "import json;d=json.load(open('packet_kind.json'));print(d.get('packet_version','?'),'·',d.get('built_at_utc','?'))" 2>/dev/null || echo "?")
elif [ -f MANIFEST.sha256 ]; then
  echo "⚠ ĐANG CHẠY TRÊN MỘT BẢN GIẢI NÉN CŨ." >&2
  echo "  Có MANIFEST.sha256 nhưng KHÔNG có packet_kind.json ⇒ packet trước bản 2." >&2
  echo "  Xoá thư mục này và giải nén lại từ sync_122_2.zip mới." >&2
fi

echo "• $SCRIPT_VER"
echo "• packet      : $PACKET_VER"
echo "• packet_kind : $PACKET_KIND"

# ── venv MA ──────────────────────────────────────────────────────────────────
# `bootstrap_review_env.sh` tạo `.venv-review` NGAY TRONG thư mục packet. Nên
# `rm -rf /tmp/s2` để giải nén lại cũng XOÁ LUÔN venv đang activate. Shell vẫn
# hiện `(.venv-review)` ở prompt và `$VIRTUAL_ENV` vẫn trỏ vào đường dẫn đã
# chết ⇒ `python3` rơi xuống interpreter khác, thường là conda, nơi KHÔNG có
# pandas/numpy. Triệu chứng: `env_contract` và `clean_replay` FAIL trong khi
# `evaluator_smoke` vẫn PASS (tool đó không cần pandas).
if [ -n "${VIRTUAL_ENV:-}" ] && [ ! -x "$VIRTUAL_ENV/bin/python3" ]; then
  cat >&2 <<MSG

✗ VENV MA: \$VIRTUAL_ENV trỏ tới một thư mục KHÔNG CÒN TỒN TẠI.
    VIRTUAL_ENV = $VIRTUAL_ENV

  Gần như chắc chắn bạn vừa \`rm -rf\` thư mục packet trong khi venv nằm bên
  trong nó. Prompt vẫn hiện (.venv-review) nhưng đó là xác.

  Sửa:
      deactivate 2>/dev/null || true
      bash ops/environment/bootstrap_review_env.sh
      . .venv-review/bin/activate
      bash ops/environment/verify_packet.sh ${REPO:+--repo "$REPO"}

MSG
  exit 2
fi
echo "• python3     : $(command -v python3) ($(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo '?'))"
echo "• SRC_ROOT    : ${SRC_ROOT:-<không tìm thấy>}"
echo "• CTRL        : ${CTRL:-<không tìm thấy>}"
echo "• work.db     : ${WDB:-<không tìm thấy>}"
[ -n "$REPO" ] && echo "• --repo      : $REPO"
echo

# Báo cáo KHÔNG được ghi vào chính packet đang kiểm: lần chạy thứ hai sẽ thấy
# `manifest FAIL` vì lần chạy thứ nhất đã sửa `reports/reviewer_replay_report.json`
# nằm trong manifest. Một công cụ verify tự làm hỏng thứ nó verify là lỗi nặng.
if [ -f MANIFEST.sha256 ]; then OUTDIR=verify_out; else OUTDIR=reports; fi
mkdir -p "$OUTDIR"

RES=$(mktemp); : >"$RES"
rec() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >>"$RES"; }
na()  { echo "  – $1  N/A: $2"; rec "$1" "N/A" "$2"; }
run() { # run <name> <cmd...>
  local name=$1; shift
  local out rc
  out=$("$@" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then echo "  ✓ $name"; rec "$name" PASS "$(echo "$out" | tail -3 | tr '\n' ' ')"
  else echo "  ✗ $name"; rec "$name" FAIL "$(echo "$out" | tail -3 | tr '\n' ' ')"; fi
  return 0
}

echo "── 1. manifest ──"
if [ -f MANIFEST.sha256 ]; then
  if command -v sha256sum >/dev/null 2>&1; then run manifest sha256sum -c --quiet MANIFEST.sha256
  else run manifest shasum -a 256 -c MANIFEST.sha256; fi
else
  na manifest "không có MANIFEST.sha256 — đang chạy trong repo, không phải từ packet"
fi

echo "── 2. môi trường đúng contract ──"
# Tách hai nguyên nhân FAIL: sai PHIÊN BẢN vs thiếu THƯ VIỆN. Gộp lại thì người
# chạy không biết phải cài python mới hay chỉ cần `pip install pandas`.
run env_contract python3 - <<'PY'
import sys
v = "%d.%d.%d" % sys.version_info[:3]
if sys.version_info[:2] < (3, 11):
    print(f"SAI PHIEN BAN: python {v} < 3.11 (pyproject.requires-python)")
    print("  -> cai python3.11+ roi chay lai ops/environment/bootstrap_review_env.sh")
    sys.exit(1)
try:
    import numpy, pandas
except ImportError as e:
    print(f"THIEU THU VIEN trong interpreter dang dung ({sys.executable}): {e}")
    print("  -> gan nhu chac chan dang chay NGOAI .venv-review.")
    print("     bash ops/environment/bootstrap_review_env.sh && . .venv-review/bin/activate")
    sys.exit(1)
print("python", v, "pandas", pandas.__version__, "numpy", numpy.__version__)
PY

echo "── 3. import source ──"
if [ -n "$SRC_ROOT" ]; then
  run import_pipeline python3 -c "import sys;sys.path.insert(0,'$SRC_ROOT');import text2pandas.pipelines.retrieval.pipeline;print('import text2pandas.pipelines.retrieval.pipeline OK')"
else
  na import_pipeline "packet '$PACKET_KIND' KHÔNG chứa source/ (đúng thiết kế). Dùng --repo <path> hoặc giải nén sync_122_1 cạnh đây."
fi

echo "── 4. primary_boost default = 0 (static 3/3) ──"
if [ -n "$SRC_ROOT" ]; then
  SRC_ROOT="$SRC_ROOT" run primary_boost python3 - <<'PY'
import os, re, sys
r = os.environ["SRC_ROOT"]
pats = [(f"{r}/retrieval/pipeline.py", r"primary_boost:\s*float\s*=\s*0\.00"),
        (f"{r}/retrieval/evalkit/runner.py", r"primary_boost:\s*float\s*=\s*0\.00"),
        (f"{r}/retrieval/evalkit/stages.py", r"primary_boost:\s*float\s*=\s*0\.0")]
bad = [f for f, p in pats if not re.search(p, open(f, encoding="utf-8").read())]
if bad:
    print("KHONG default 0:", bad); sys.exit(1)
print("primary_boost 3/3 default zero PASS")
PY
else
  na primary_boost "cần source/ — xem mục 3"
fi

echo "── 5. source identity (tree_sha256) ──"
# `--min-files` chặn dấu XANH SAI: chạy trong packet bổ sung thì chỉ thấy ~22
# file lẻ và vẫn exit 0, sinh ra một tree_sha256 trông hợp lệ mà vô nghĩa.
if [ -n "$SRC_ROOT" ] && [ -d "$(dirname "$SRC_ROOT")/tests" -o -d tests ]; then
  run source_identity python3 tools/build_source_identity_v1.py \
      ${REPO:+--root "$REPO"} --min-files 200
else
  na source_identity "cần cây source đầy đủ; chạy trong packet bổ sung sẽ băm nhầm vài file lẻ"
fi

echo "── 6. evaluator smoke trên control (kỳ vọng 13/45 = 28,9%) ──"
if [ -n "$CTRL" ]; then run evaluator_smoke python3 tools/eval_answer_v1.py "$CTRL"
else na evaluator_smoke "packet '$PACKET_KIND' KHÔNG chứa controls/*.zip (đúng thiết kế). Dùng --repo hoặc sync_122_1."; fi

echo "── 7. clean replay (kỳ vọng OK=1011, NO_QUERY=1) ──"
# `replay_submission_v1.py` mặc định ghi `data/curated/evaluation/legacy/run_trace_1012.jsonl` và
# `reports/*_clean_replay.json` — CẢ HAI nằm trong MANIFEST. Chạy trong packet
# mà không đổi đường ghi thì lần verify thứ hai sẽ báo `manifest FAIL` do chính
# lần thứ nhất gây ra. Đây là lỗi đã quan sát được, không phải giả định.
if [ -n "$CTRL" ]; then
  run clean_replay python3 tools/replay_submission_v1.py "$CTRL" \
      --trace-out "$OUTDIR/run_trace_1012.jsonl" \
      --report-out "$OUTDIR/clean_replay.json"
else na clean_replay "cần controls/*.zip — xem mục 6"; fi

echo "── 8. work.db rebuild contract + 4 index ──"
if [ -n "$WDB" ]; then
  run workdb_verify bash tools/build_retrieval_workdb.sh --verify-only "$WDB"
else
  echo "  – work.db không có (4,24 GB, intentionally omitted). Kiểm hợp đồng lệnh thay thế:"
  run workdb_contract bash tools/build_retrieval_workdb.sh --help
  rec workdb_verify "N/A" "work.db không kèm packet; chỉ kiểm được hợp đồng lệnh. Dùng --repo để kiểm 4 index thật."
fi

echo
echo "── tổng hợp ──"
RES="$RES" PACKET_KIND="$PACKET_KIND" OUTDIR="$OUTDIR" python3 - <<'PY'
import json, os, pathlib, sys
rows = [l.rstrip("\n").split("\t") for l in open(os.environ["RES"], encoding="utf-8") if l.strip()]
items = [{"check": a, "verdict": b, "tail": c} for a, b, c in rows]
n = lambda v: sum(i["verdict"] == v for i in items)
n_fail, n_na = n("FAIL"), n("N/A")
if n_fail:
    verdict = "HOLD_CO_MUC_FAIL"
elif n_na:
    verdict = "PARTIAL_PACKET_BO_SUNG"      # N/A KHÔNG phải pass
else:
    verdict = "GO_D0_VERIFIED_ELIGIBLE"
rep = {"_schema": "reviewer_replay_report v2 (review 127 §9) — N/A tách khỏi FAIL và khỏi PASS",
       "packet_kind": os.environ.get("PACKET_KIND", "unknown"),
       "n_checks": len(items), "n_pass": n("PASS"), "n_fail": n_fail,
       "n_na": n_na, "n_skip": n("SKIP"),
       "verdict": verdict,
       "quy_uoc": ("N/A = packet không mang tài nguyên để kiểm mục đó (đúng thiết kế). "
                   "N/A KHÔNG phải PASS và KHÔNG phải FAIL. Chỉ `GO_D0_VERIFIED_ELIGIBLE` "
                   "khi mọi mục PASS."),
       "checks": items}
outdir = pathlib.Path(os.environ.get("OUTDIR", "reports"))
outdir.mkdir(exist_ok=True)
(outdir / "reviewer_replay_report.json").write_text(
    json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
for i in items:
    print(f"{i['verdict']:5} {i['check']}")
print(f"\n{verdict}  (pass {rep['n_pass']} / fail {n_fail} / N/A {n_na} / skip {rep['n_skip']})")
if n_na and not n_fail:
    print("→ Mọi mục kiểm được đều PASS. Các mục N/A cần cây có source/controls/work.db:")
    print("    bash ops/environment/verify_packet.sh --repo /duong/dan/Text2Pandas")
print(f"-> {outdir}/reviewer_replay_report.json")
sys.exit(1 if n_fail else 0)
PY
