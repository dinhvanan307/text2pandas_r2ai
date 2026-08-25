#!/usr/bin/env bash
# Doc 52 §12 · dựng TRỌN BỘ bàn giao trong một lượt, từ MỘT snapshot duy nhất.
#
# Lý do phải gom: bốn artifact dựng rời rạc ở bốn thời điểm sẽ trỏ vào bốn
# trạng thái khác nhau của cùng một repo. Người nhận dựng lại và không khớp,
# rồi mất buổi chiều tìm xem cái nào đúng. Một lượt, một snapshot.
set -u
# Tham số hoá cho A6. Bản trước hardcode A3 ở bốn chỗ khác nhau — BID, đường
# gói release, thư mục acceptance, và tên gói bằng chứng — nên "đổi một biến"
# là không đủ và người vận hành dễ đổi ba chỗ rồi quên chỗ thứ tư.
BID=${BID:-b3e9684004679ffb}
TAG=${TAG:-a6}
ACC=${ACC:-artifacts/rc2/acceptance_a6}
PKG=${PKG:-artifacts/rc2/packagesa6}
RELZIP=${RELZIP:-$PKG/silver_v1_rc2_${BID}_${TAG}_run1.zip}
H=artifacts/rc2/handoff
TRASH=artifacts/rc2/_to_delete
export BID TAG ACC PKG
[ -f "$RELZIP" ] || { echo "✗ thiếu gói release $RELZIP" >&2; exit 2; }
[ -d "$ACC" ] || { echo "✗ thiếu bằng chứng $ACC" >&2; exit 2; }
# GUARD · gói release phải ĐÚNG bản dựng được yêu cầu. Cùng bài học với
# `run_release_chain.sh`: một lần gói A3 đi ra dưới nhãn A4, và mọi checksum
# vẫn khớp vì gói TỰ NHẤT QUÁN.
GOT=$(python - "$RELZIP" "$BID" <<'GUARD'
import json, sys, zipfile
z, want = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(z) as f:
    n = [x for x in f.namelist() if x.endswith("/manifest.json")]
    print(json.loads(f.read(n[0]))["build_id"] if n else "")
GUARD
)
[ "$GOT" = "$BID" ] || { echo "✗ $RELZIP mang build_id '$GOT' nhưng yêu cầu '$BID'" >&2; exit 2; }
echo "• gói release: $RELZIP  (build_id $GOT ✓)"

[ -z "$(git status --porcelain)" ] || {
  echo "✗ cây làm việc BẨN — commit trước khi dựng bộ bàn giao:" >&2
  git status --porcelain >&2; exit 2; }
SNAP=$(git rev-parse --short HEAD)
echo "snapshot = $SNAP"
mkdir -p "$H" "$TRASH"

# Bản cũ KHÔNG được nằm cạnh bản mới trong cùng thư mục gửi đi.
for f in "$H"/*.zip; do
  [ -e "$f" ] || continue
  mv "$f" "$TRASH/$(basename "$f").superseded_$SNAP" && echo "  ⊘ dọn bản cũ: $(basename "$f")"
done
for d in "$H"/data_pipeline_source_* "$H"/rc2_acceptance_* "$H"/rc2_*_build_evidence_*; do
  [ -d "$d" ] && mv "$d" "$TRASH/$(basename "$d").superseded_$SNAP" || true
done

sums () { python - "$1" <<'PY'
import hashlib, os, sys
d = sys.argv[1]
def sha(p):
    h = hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(1<<20), b""): h.update(c)
    return h.hexdigest()
rows=[]
for root,_,ns in os.walk(d):
    for n in ns:
        p=os.path.join(root,n); r=os.path.relpath(p,d)
        if r=="SHA256SUMS": continue
        rows.append((r, sha(p)))
rows.sort()
open(os.path.join(d,"SHA256SUMS"),"w").write("".join(f"{h}  {r}\n" for r,h in rows))
print(f"  SHA256SUMS · {len(rows)} dòng")
PY
}

echo ""; echo "══ 1/4 · gói source ══"
S="$H/data_pipeline_source_$SNAP"
python - "$S" <<'PY'
import shutil, sys
from pathlib import Path
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True)
IGN = shutil.ignore_patterns("__pycache__","*.pyc","*.pyo",".DS_Store","*.db",
    "*.sqlite","*.zip",".pytest_cache","*.egg-info","build","dist",
    ".mypy_cache",".ruff_cache")
for d in ("src","tools","tests","configs","docs","to_read"):
    if Path(d).is_dir(): shutil.copytree(d, OUT/d, ignore=IGN)
for f in ("Makefile","pyproject.toml","requirements.lock","HANDOFF.md",
          "README.md","pytest.ini","setup.cfg"):
    if Path(f).is_file(): shutil.copy2(f, OUT/f)
# C5 · Doc 56 P1-02 · KHONG chep ca thu muc snapshot cu vao goi. Goi truoc
# mang SOURCE_FINGERPRINT.json mo ta build 5ffc07216708d9fd o commit f7c88649,
# cay ban — mot ban dung da bi thay the tu lau. Reviewer mo goi ra thay hai ho
# so nguon khac nhau va khong biet cai nao la cua ban dang cam.
snap = OUT/"snapshot"; snap.mkdir()
for name in ("SNAPSHOT_DECLARATION.json",):
    src = Path("artifacts/rc2/source_snapshot")/name
    if src.is_file(): shutil.copy2(src, snap/name)
shutil.copy2("artifacts/rc2/deferred/RC2-048_release_sha256sums_scope.patch",
             snap/"RC2-048_release_sha256sums_scope.patch")
print(f"  {sum(1 for _ in OUT.rglob('*') if _.is_file())} tệp")
PY
python - "$S" "$SNAP" <<'SRCMAN'
import hashlib, json, os, subprocess, sys
from pathlib import Path
out, snap = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(out / "src"))
def sh(*c):
    return subprocess.run(c, capture_output=True, text=True).stdout.strip() or None
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
try:
    from data_pipeline.storage import source_fingerprint
    fp = source_fingerprint()
except Exception as exc:
    fp = {"error": repr(exc)}
files = {}
for root, _, ns in os.walk(out):
    for n in ns:
        p = Path(root) / n
        r = p.relative_to(out).as_posix()
        if r in ("SOURCE_MANIFEST.json", "SHA256SUMS"): continue
        files[r] = {"bytes": p.stat().st_size, "sha256": sha(p)}
porcelain = sh("git", "status", "--porcelain") or ""
man = {
 "_schema": "Doc 52 muc 5.1 · source package manifest.",
 "source_snapshot_id": snap,
 "git_commit": sh("git", "rev-parse", "HEAD"),
 "git_tree": sh("git", "rev-parse", "HEAD^{tree}"),
 "source_tree_dirty": bool(porcelain),
 "untracked_in_source_paths": [
     l[3:] for l in porcelain.splitlines()
     if l.startswith("??") and l[3:].split("/")[0] in ("src","tools","configs","tests")],
 "source_hash": fp.get("source_hash"),
 "config_hash": fp.get("config_hash"),
 "canonical_rule": "source_hash = sha256(noi dung src/data_pipeline/*.py theo ten); config_hash = sha256(noi dung configs/*.yaml theo ten)",
 "component_versions": {},
 "n_files": len(files),
 "files": dict(sorted(files.items())),
}
try:
    import data_pipeline.number_parser as npmod
    import data_pipeline.observation_builder as obmod
    man["component_versions"] = {"number": npmod.NUMBER_VERSION,
                                 "semantic": obmod.SEMANTIC_VERSION}
except Exception:
    pass
(out / "SOURCE_MANIFEST.json").write_text(
    json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
print("  SOURCE_MANIFEST.json · %d tep · source_hash %s" % (len(files), man["source_hash"]))
SRCMAN
sums "$S"
./tools/acceptance_step.sh "$ACC/handoff_source_pkg" python tools/package_release.py --dir "$S" --out "$S.zip" >/dev/null
tail -2 "$ACC/handoff_source_pkg/stdout.log"
./tools/acceptance_step.sh "$ACC/handoff_source_verify" python tools/verify_package.py --package "$S.zip" --type source --report "$ACC/handoff_source_verify/verify.json" >/dev/null
tail -2 "$ACC/handoff_source_verify/stdout.log"

echo ""; echo "══ 2/4 · gói release ══"
cp "$RELZIP" "$H/silver_v1_rc2_${BID}.zip"
A=$( (shasum -a 256 "$RELZIP" || sha256sum "$RELZIP") | cut -d' ' -f1)
B=$( (shasum -a 256 "$H/silver_v1_rc2_${BID}.zip" || sha256sum "$H/silver_v1_rc2_${BID}.zip") | cut -d' ' -f1)
[ "$A" = "$B" ] || { echo "✗ bản chép KHÁC bản gốc" >&2; exit 1; }
echo "  bản chép khớp bản gốc · $B"

echo ""; echo "══ 3/4 · gói bằng chứng §5.2 ══"
./tools/build_evidence_package.sh | tail -4

echo ""; echo "══ 4/4 · gói acceptance ══"
E="$H/rc2_acceptance_${BID}_${SNAP}_run1"
python - "$E" "$SNAP" "$BID" "$ACC" <<'PY'
import json, shutil, subprocess, sys
from pathlib import Path
OUT, snap, bid, acc = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
shutil.copytree(acc, OUT,
                ignore=shutil.ignore_patterns("__pycache__",".DS_Store"))
(OUT/"cohorts").mkdir(exist_ok=True)
# Thiếu một cohort thì GHI RA chứ không làm chết cả gói, và cũng không im lặng.
for n in ("share_count_rc1_to_a3.csv","rc2_039_cases.csv","removed_78_cases.csv"):
    src = Path("artifacts/rc2/cohorts")/n
    if src.is_file():
        shutil.copy2(src, OUT/"cohorts"/n)
    else:
        (OUT/"cohorts"/f"MISSING_{n}.txt").write_text(
            f"KHONG CO: {src}", encoding="utf-8")
cs = Path("artifacts/rc2/evidence_parts/cohort_summary.json")
if cs.is_file():
    shutil.copy2(cs, OUT/"cohorts")
else:
    (OUT/"cohorts"/"MISSING_cohort_summary.json.txt").write_text(
        f"KHONG CO: {cs}", encoding="utf-8")
import hashlib
def sha(p):
    h=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda: f.read(1<<20), b""): h.update(c)
    return h.hexdigest()
files={}
for p in sorted(OUT.rglob("*")):
    if p.is_file():
        r=p.relative_to(OUT).as_posix()
        if r in ("manifest.json","SHA256SUMS"): continue
        files[r]={"bytes":p.stat().st_size,"digest":sha(p),"digest_mode":"sha256"}
(OUT/"manifest.json").write_text(json.dumps({
 "_schema":"Doc 52 muc 12 artifact 2 · bang chung acceptance.",
 "acceptance_dir":acc,
 "bundle":OUT.name,"build_id":bid,"acceptance_tool_snapshot":snap,
 "_limit":"Goi nay KHONG chua bang chung cua chinh buoc dong goi no — "
          "mot goi khong the chua checksum cua chinh minh.",
 "steps":sorted(p.name for p in OUT.iterdir() if p.is_dir()),
 "n_files":len(files),"files":files}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"  {len(files)} tệp · {len([p for p in OUT.iterdir() if p.is_dir()])} bước")
PY
sums "$E"
./tools/acceptance_step.sh "$ACC/handoff_acceptance_pkg" python tools/package_release.py --dir "$E" --out "$E.zip" >/dev/null
tail -2 "$ACC/handoff_acceptance_pkg/stdout.log"
python tools/package_coverage_check.py --package "$E.zip" --report "$ACC/handoff_acceptance_pkg/coverage.json" | tail -6

echo ""; echo "════════ BỘ BÀN GIAO ════════"
for f in "$H"/*.zip; do
  printf '%14s  %s  %s\n' "$(wc -c < "$f" | tr -d ' ')" \
    "$( (shasum -a 256 "$f" || sha256sum "$f") | cut -d' ' -f1)" "$(basename "$f")"
done
