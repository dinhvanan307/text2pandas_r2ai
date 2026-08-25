#!/usr/bin/env bash
# Doc 52 §5.3 · MỖI claim phải có command, exit code, thời điểm chạy và report
# băm được. Ghi tay bốn thứ đó cho tám bước là bốn chỗ để sai; script này ghi
# chúng bằng máy.
#
#   tools/acceptance_step.sh <thu_muc_bang_chung> <lệnh...>
#
# Sinh ra trong <thu_muc_bang_chung>/:
#   command.txt · stdout.log · exit_code.txt · step_meta.json · SHA256SUMS
#
# `step_meta.json` ghi started_at_utc / finished_at_utc ĐO THẬT lúc chạy —
# KHÔNG phải thời điểm đóng gói. Doc 52 cấm nhầm hai thứ đó.
set -u
OUT="${1:?can thu muc bang chung}"; shift
mkdir -p "$OUT"
printf '%s\n' "$*" > "$OUT/command.txt"
START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$@" > "$OUT/stdout.log" 2>&1
CODE=$?
END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\n' "$CODE" > "$OUT/exit_code.txt"

TOOL=""
for a in "$@"; do case "$a" in tools/*.py|*/tools/*.py) TOOL="$a"; break;; esac; done
SHA() { [ -f "$1" ] && (shasum -a 256 "$1" 2>/dev/null || sha256sum "$1") | cut -d' ' -f1; }

python3 - "$OUT" "$START" "$END" "$CODE" "$TOOL" <<'PY'
import hashlib, json, os, subprocess, sys
out, start, end, code, tool = sys.argv[1:6]
def sha(p):
    if not p or not os.path.isfile(p): return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
def sh(*c):
    try: return subprocess.run(c, capture_output=True, text=True).stdout.strip() or None
    except Exception: return None
reports = {}
for n in sorted(os.listdir(out)):
    p = os.path.join(out, n)
    if os.path.isfile(p) and n.endswith((".json", ".csv", ".xml")) and n != "step_meta.json":
        reports[n] = {"bytes": os.path.getsize(p), "sha256": sha(p)}
meta = {
    "_schema": "Doc 52 §5.3 · mot buoc acceptance, do bang may.",
    "command": open(os.path.join(out, "command.txt")).read().strip(),
    "started_at_utc": start, "finished_at_utc": end, "exit_code": int(code),
    "evidence_kind": "machine_generated",
    "executed_on_host_role": "build_host",
    "tool_path": tool or None, "tool_sha256": sha(tool),
    "source_commit": sh("git", "rev-parse", "HEAD"),
    "source_tree_dirty": bool(sh("git", "status", "--porcelain")),
    "stdout_sha256": sha(os.path.join(out, "stdout.log")),
    "machine_readable_reports": reports,
}
json.dump(meta, open(os.path.join(out, "step_meta.json"), "w"),
          ensure_ascii=False, indent=1)
lines = []
for n in sorted(os.listdir(out)):
    p = os.path.join(out, n)
    if os.path.isfile(p) and n != "SHA256SUMS":
        lines.append(f"{sha(p)}  {n}")
open(os.path.join(out, "SHA256SUMS"), "w").write("\n".join(lines) + "\n")
PY
echo "  → $OUT  exit=$CODE  ($START → $END)"
exit "$CODE"
