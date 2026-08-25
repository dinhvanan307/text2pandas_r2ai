#!/usr/bin/env bash
# Doc 52 §5.2 · gói bằng chứng cho A3/B3.
#
# PHẢI chạy trên BUILD HOST. `env_check` ghi lại chính máy đang chạy nó; chạy
# qua bridge sẽ ghi môi trường của VM Linux chứ không phải máy đã dựng A3/B3,
# và một hồ sơ môi trường sai còn tệ hơn không có hồ sơ.
#
# Thứ gì KHÔNG có thì ghi ra `MISSING_<tên>.txt` nêu rõ thiếu gì và vì sao —
# không im lặng bỏ qua, cũng không tạo tệp rỗng cho đủ cấu trúc.
set -u
# Tham số hoá cho A6. Bản trước hardcode A3/B3, nên mỗi vòng dựng lại phải sửa
# script — và sửa script giữa hai lần chạy là cách hai lần chạy trở nên không
# so được với nhau. Mặc định trỏ bản dựng ĐANG PHÁT HÀNH.
BID=${BID:-b3e9684004679ffb}
TAG=${TAG:-a6}
A=${A:-artifacts/rc2/buildA6}
B=${B:-artifacts/rc2/buildB6}
ACC=${ACC:-artifacts/rc2/acceptance_a6}
# EXPORT chứ không chỉ gán: các đoạn `python - <<PY` bên dưới đọc
# `os.environ`, và biến shell thường không đi vào môi trường tiến trình con.
export BID TAG A B ACC TESTDIR
SNAP=$(git rev-parse --short HEAD)
EV=artifacts/rc2/handoff/rc2_${TAG}_build_evidence_${SNAP}_run1
PARTS=artifacts/rc2/evidence_parts
[ -d "$A" ] || { echo "✗ thiếu $A" >&2; exit 2; }
[ -d "$B" ] || { echo "✗ thiếu $B — cần cho bằng chứng determinism" >&2; exit 2; }
[ -d "$ACC" ] || { echo "✗ thiếu $ACC" >&2; exit 2; }
# Thư mục TRONG gói dùng tên chung `buildA`/`buildB`, không nhúng nhãn vòng
# dựng. Bố cục gói vì thế ổn định qua các vòng, và `build_id` trong manifest
# mới là thứ nói bản dựng nào — một chỗ, không hai.

[ ! -e "$EV" ] || { echo "✗ $EV đã tồn tại — đặt tên khác thay vì ghi đè" >&2; exit 2; }

# Gói bàn giao KHÔNG được dựng từ cây bẩn. Nó khai `acceptance_tool_snapshot`
# bằng commit hiện tại; nếu cây có thay đổi chưa commit thì nhãn đó trỏ vào một
# thứ khác với nội dung thật — đúng loại nhập nhằng Doc 52 §5.1 cấm.
# ALLOW_DIRTY=1 để ép khi cần chẩn đoán, và khi đó manifest sẽ ghi rõ.
DIRTY=$([ -n "$(git status --porcelain)" ] && echo true || echo false)
if [ "$DIRTY" = true ] && [ "${ALLOW_DIRTY:-}" != 1 ]; then
  echo "✗ cây làm việc đang BẨN — commit trước, hoặc ALLOW_DIRTY=1 nếu cố ý:" >&2
  git status --porcelain >&2
  exit 2
fi
mkdir -p "$EV"/{environment,input,buildA,buildB,tests,quality,cohorts,status}
TRASH_EMPTY=artifacts/rc2/_to_delete/empty_files; mkdir -p "$TRASH_EMPTY"

miss () { printf '%s\n' "$2" > "$EV/$1"; echo "  ⚠ MISSING → $1"; }
take () { [ -f "$1" ] && cp "$1" "$2" || miss "$(dirname "${2#$EV/}")/MISSING_$(basename "$2").txt" \
          "KHONG CO: $1"; }

echo "── environment ──"
python tools/env_check.py --json > "$EV/environment/env_check.json" 2> "$EV/environment/env_check.log" \
  || echo "  env_check exit=$? (ghi lai nguyen trang, khong che)"
pip freeze > "$EV/environment/dependency_snapshot.txt" 2>/dev/null || \
  miss environment/MISSING_dependency_snapshot.txt "pip freeze that bai"
# Đọc lại chính env_check.json vừa ghi thay vì chạy env_check lần hai — hai
# lần chạy có thể ra hai kết quả khác nhau, và khi đó không biết tin cái nào.
python - "$EV" <<'PY'
import json, sys
from pathlib import Path
ev = Path(sys.argv[1])
src = ev/"environment/env_check.json"
dst = ev/"environment/requirements_lock_verification.json"
try:
    r = json.loads(src.read_text(encoding="utf-8"))
except Exception as exc:
    (ev/"environment/MISSING_requirements_lock_verification.txt").write_text(
        f"KHONG DOC DUOC {src}: {exc!r}\n"
        "Nguyen nhan thuong gap: env_check --json in them chu ra stdout (RC2-052).\n",
        encoding="utf-8")
    dst.unlink(missing_ok=True)
    print("  ⚠ MISSING → environment/requirements_lock_verification.json"); raise SystemExit(0)
dst.write_text(json.dumps({k: r.get(k) for k in
  ("lock_path","lock_sha256","lock_n_pins","lock_n_hashes","lock_has_hashes",
   "lock_mismatches","lock_not_installed","lock_matches_installed",
   "lock_covers_imports","imports_third_party_count","imports_unpinned")},
  ensure_ascii=False, indent=1), encoding="utf-8")
print("  lock verification: OK")
PY
{ echo "commit  $(git rev-parse HEAD)"; echo "short   $SNAP"
  echo "dirty   $([ -n "$(git status --porcelain)" ] && echo true || echo false)"
  echo "--- git log -1 ---"; git log -1 --stat | head -40
} > "$EV/environment/git_identity.txt"

echo "── input ──"
take "$A/manifest.json"           "$EV/input/corpus_manifest.json"
python - <<PY > "$EV/input/corpus_content_hash.txt"
import json
m = json.load(open("$A/manifest.json"))
print("corpus_id        ", m.get("corpus_id"))
print("n_files          ", len(m.get("files") or {}) or m.get("n_files"))
PY
cp artifacts/rc2/source_snapshot/SNAPSHOT_DECLARATION.json "$EV/input/" 2>/dev/null || true
python - <<PY > "$EV/input/uid_namespace_id.txt"
import json
m = json.load(open("artifacts/rc2/release_finalv2/manifest.json"))
print("uid_namespace_id  dong bang theo corpus_id cua RC1 (AMD-04)")
print("corpus_id build A", m.get("corpus_id"))
PY

echo "── buildA / buildB ──"
for P in A B; do
  SRC=$([ "$P" = A ] && echo "$A" || echo "$B"); DST="$EV/build$P"
  take "$SRC/build_invocation.json"  "$DST/build_invocation.json"
  take "$SRC/build.log"              "$DST/build.log"
  take "$SRC/completion_marker.json" "$DST/stage_status.json"
  take "$SRC/silver/$BID/manifest.json" "$DST/publish_manifest.json"
  take "$SRC/source_validation.json" "$DST/source_validation.json"
  D="$SRC/silver/$BID/silver.sqlite"
  if [ -f "$D" ]; then (shasum -a 256 "$D" || sha256sum "$D") > "$DST/silver_sha256.txt"
  else miss "build$P/MISSING_silver_sha256.txt" "KHONG CO DB: $D"; fi
done
cp "$ACC/c0_final/rebuild_check.json" "$EV/buildA/rebuild_check_byte_identity.json" 2>/dev/null || true

echo "── tests ──"
# Bản trước tìm `test_report_rc2_*` — tên đã đổi từ A4 — rồi ghi cứng một dòng
# MISSING nói "run_tests.py khong sinh junit.xml". Cả hai đều đã cũ: thư mục
# nay là `test_report_<tag>`, và C6 đã làm `run_tests.py` sinh junit.xml. Khai
# THIẾU một thứ đang CÓ cũng sai như khai CÓ một thứ đang thiếu.
T=${TESTDIR:-$(ls -dt artifacts/rc2/test_report_* 2>/dev/null | head -1)}
echo "  test report: ${T:-<khong tim thay>}"
take "$T/test_report.json" "$EV/tests/test_report.json"
take "$T/test_report.txt"  "$EV/tests/test_stdout.log"
take "$T/exit_code.txt"    "$EV/tests/exit_code.txt"
take "$T/junit.xml"        "$EV/tests/junit.xml"

echo "── quality ──"
take "$A/silver/$BID/quality_report.json" "$EV/quality/quality_report_buildA.json"
take "$B/silver/$BID/quality_report.json" "$EV/quality/quality_report_buildB.json"
# Hai tệp dưới đây là số đo của A3. Chép chúng vào gói A6 dưới tên không ghi
# rõ nguồn là nói dối bằng cách sắp xếp; nên đặt tên có hậu tố `_A3_lich_su`.
take "$PARTS/quality_rule_totals_A3.json" "$EV/quality/quality_rule_totals_A3_lich_su.json"
take "$PARTS/quality_delta_RC1_A3.json"   "$EV/quality/quality_delta_RC1_A3_lich_su.json"
miss quality/MISSING_quality_delta_A2_A3.txt "Doc 52 doi delta A2->A3. A2 da bi thay the boi A3 sau khi RC2-036/037 duoc sua; chi con artifacts/rc2/keep/buildA2. Delta duoc do la RC1->A3 (quality_delta_RC1_A3.json), mang y nghia acceptance that su."

echo "── cohorts ──"
# Cohort là bằng chứng LỊCH SỬ của các vòng trước, vẫn có giá trị truy nguyên.
# `take` chứ không `cp`: thiếu thì ghi MISSING, không làm chết cả gói.
take artifacts/rc2/cohorts/share_count_rc1_to_a3.csv "$EV/cohorts/share_count_rc1_to_a3.csv"
take artifacts/rc2/cohorts/rc2_039_cases.csv         "$EV/cohorts/rc2_039_cases.csv"
take artifacts/rc2/cohorts/removed_78_cases.csv      "$EV/cohorts/removed_78_cases.csv"
take "$PARTS/cohort_summary.json" "$EV/cohorts/cohort_summary.json"

echo "── status ──"
take docs/53_RC2_STATUS_DA_GIAI_QUYET_VA_CON_LAI.md "$EV/status/OPEN_ISSUES.md"
take docs/55_RC2_DOI_CHIEU_DOC52.md                 "$EV/status/RC_STATUS_doi_chieu_doc52.md"
take docs/56_MO_TA_DU_LIEU_SILVER_V1_RC2.md         "$EV/status/MO_TA_DU_LIEU.md"
take to_read/43_RESPONSE_TO_AUDIT_42.md             "$EV/status/RESPONSE_TO_AUDIT_42.md"
take docs/50_RC2_UNIT_KIND_REGRESSION.md            "$EV/PLAN_50.md"
take to_read/52_REVIEW_OF_RC2_BUILD_7AA8B4C2_REPORT.md "$EV/status/REVIEW_52.md"
cp artifacts/rc2/handoff/KNOWN_ISSUES_ADDENDUM_RC2_039.md "$EV/status/" 2>/dev/null || true

# Tệp RỖNG trong gói bằng chứng còn tệ hơn tệp thiếu: manifest đếm nó như một
# bằng chứng hợp lệ. Đổi mọi tệp 0 byte thành MISSING_ kèm lý do.
find "$EV" -type f -size 0 | while read -r z; do
  r="${z#$EV/}"
  printf 'TEP RONG khi dong goi: %s\nCong cu sinh ra no da chay nhung khong ghi duoc noi dung.\n' "$r" \
    > "$(dirname "$z")/MISSING_$(basename "$z").txt"
  mv "$z" "$TRASH_EMPTY/$(echo "$r" | tr '/' '_')" 2>/dev/null || rm -f "$z" 2>/dev/null || true
  echo "  ⚠ RỖNG → MISSING: $r"
done

echo "── manifest + checksum ──"
python - "$EV" "$SNAP" "$DIRTY" <<'PY'
import hashlib, json, os, subprocess, sys
ev, snap, dirty = sys.argv[1], sys.argv[2], sys.argv[3]
def sha(p):
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(1<<20), b""): h.update(c)
    return h.hexdigest()
files, missing = {}, []
for root, _, ns in os.walk(ev):
    for n in ns:
        p = os.path.join(root, n); r = os.path.relpath(p, ev)
        if r in ("EVIDENCE_MANIFEST.json","SHA256SUMS"): continue
        files[r] = {"bytes": os.path.getsize(p), "sha256": sha(p)}
        if n.startswith("MISSING_"): missing.append(r)
man = {"_schema":"Doc 52 muc 5.2 · goi bang chung build A/B.",
 "build_id":os.environ.get("BID",""),"acceptance_tool_snapshot":snap,
 "source_tree_dirty_at_packaging":dirty=="true",
 "build_source_commit":os.environ.get("BUILD_SOURCE_COMMIT") or snap,
 "build_a_dir":os.environ.get("A",""),"build_b_dir":os.environ.get("B",""),
 "evidence_kind":"machine_generated","executed_on_host_role":"build_host",
 "n_files":len(files),"n_missing_declared":len(missing),
 "missing_declared":sorted(missing),"files":dict(sorted(files.items()))}
open(os.path.join(ev,"EVIDENCE_MANIFEST.json"),"w").write(
    json.dumps(man, ensure_ascii=False, indent=1))
lines=[]
for root,_,ns in os.walk(ev):
    for n in sorted(ns):
        p=os.path.join(root,n); r=os.path.relpath(p,ev)
        if r=="SHA256SUMS": continue
        lines.append(f"{sha(p)}  {r}")
open(os.path.join(ev,"SHA256SUMS"),"w").write("\n".join(sorted(lines,key=lambda l:l.split('  ',1)[1]))+"\n")
print(f"  {len(files)} tep · {len(missing)} muc MISSING da khai")
PY

echo "── đóng gói ──"
./tools/acceptance_step.sh artifacts/rc2/acceptance/handoff_evidence_pkg \
  python tools/package_release.py --dir "$EV" --out "$EV.zip"
tail -3 artifacts/rc2/acceptance/handoff_evidence_pkg/stdout.log
echo ""
echo "✓ XONG · $EV.zip"
