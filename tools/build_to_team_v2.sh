#!/usr/bin/env bash
# Bộ gửi team cho tầng Retrieval — bản A6.
#
# Khác `build_handoff_set.sh` ở mục đích: bộ kia là hồ sơ ĐẦY ĐỦ cho reviewer
# kiểm toán (source zip, evidence build, acceptance). Bộ này là thứ người viết
# tầng Retrieval cần MỞ RA LÀ DÙNG: dữ liệu, tài liệu, và vừa đủ bằng chứng
# để tin dữ liệu.
set -eu
BID=${BID:-b3e9684004679ffb}
TAG=${TAG:-a6}
PKG=${PKG:-artifacts/rc2/packagesa6}
ACC=${ACC:-artifacts/rc2/acceptance_a6}
REL=${REL:-data/processed/a6/b3e9684004679ffb}
RELZIP=$PKG/silver_v1_rc2_${BID}_${TAG}_run1.zip
OUT=artifacts/rc2/to_team_v2
TRASH=artifacts/rc2/_to_delete

[ -f "$RELZIP" ] || { echo "✗ thiếu $RELZIP" >&2; exit 2; }
[ -d "$ACC" ]    || { echo "✗ thiếu $ACC" >&2; exit 2; }

# GUARD · gói phải ĐÚNG bản dựng. Cùng bài học với run_release_chain.sh:
# một gói sai bản vẫn tự nhất quán và mọi checksum vẫn khớp.
GOT=$(python - "$RELZIP" <<'GUARD'
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as f:
    n = [x for x in f.namelist() if x.endswith("/manifest.json")]
    print(json.loads(f.read(n[0]))["build_id"] if n else "")
GUARD
)
[ "$GOT" = "$BID" ] || { echo "✗ $RELZIP mang build_id '$GOT', yêu cầu '$BID'" >&2; exit 2; }
echo "• gói dữ liệu: $RELZIP  (build_id $GOT ✓)"

if [ -e "$OUT" ]; then
  mkdir -p "$TRASH"
  mv "$OUT" "$TRASH/to_team_v2.superseded_$(date -u +%Y%m%dT%H%M%SZ)"
  echo "  ⊘ dọn bản cũ sang $TRASH"
fi
[ ! -e "$OUT.zip" ] || { echo "✗ $OUT.zip đã tồn tại — đổi tên thay vì ghi đè" >&2; exit 2; }
mkdir -p "$OUT"/{data,docs,acceptance}

echo "── 1/4 · dữ liệu ──"
cp "$RELZIP" "$OUT/data/"
A=$( (shasum -a 256 "$RELZIP" || sha256sum "$RELZIP") | cut -d' ' -f1)
B=$( (shasum -a 256 "$OUT/data/$(basename "$RELZIP")" || sha256sum "$OUT/data/$(basename "$RELZIP")") | cut -d' ' -f1)
[ "$A" = "$B" ] || { echo "✗ bản chép KHÁC bản gốc" >&2; exit 1; }
echo "  $(basename "$RELZIP")  $B"
# manifest phẳng bên ngoài: kiểm định danh mà không phải giải nén 1,7 GB.
cp "$REL/manifest.json" "$OUT/data/release_manifest.json"

echo "── 2/4 · tài liệu ──"
for d in 65_BAN_GIAO_DATA_CHO_RETRIEVAL_A6.md 63_RETRIEVAL_COLLISION_SPEC.md \
         64_DANH_GIA_TOAN_DIEN_A5.md 62_A5_PLAN.md 61_DANH_GIA_DATA_A4.md \
         56_MO_TA_DU_LIEU_SILVER_V1_RC2.md; do
  if [ -f "docs/$d" ]; then cp "docs/$d" "$OUT/docs/"; echo "  $d"
  else printf 'KHONG CO: docs/%s\n' "$d" > "$OUT/docs/MISSING_$d.txt"; echo "  ⚠ MISSING $d"; fi
done

echo "── 3/4 · bằng chứng chấp nhận ──"
cp -R "$ACC"/. "$OUT/acceptance/"
find "$OUT/acceptance" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$OUT/acceptance" -name '.DS_Store' -delete 2>/dev/null || true
echo "  $(find "$OUT/acceptance" -type f | wc -l | tr -d ' ') tệp · $(ls -1 "$OUT/acceptance" | wc -l | tr -d ' ') bước"

cat > "$OUT/README.md" <<'RD'
# to_team_v2 · Silver A6 cho tầng Retrieval

**Đọc `docs/65_BAN_GIAO_DATA_CHO_RETRIEVAL_A6.md` trước.** Nó có quickstart,
sơ đồ dữ liệu, và ba giới hạn phải biết trước khi thiết kế.

```
data/       gói Silver đã chứng nhận (1,68 GB) + release_manifest.json
docs/       tài liệu dữ liệu — bắt đầu ở doc 65
acceptance/ 13 bước chấp nhận, đủ command/stdout/exit_code/step_meta
manifest.json · SHA256SUMS
```

## Kiểm trước khi dùng

```bash
shasum -a 256 -c SHA256SUMS
cd data && unzip silver_v1_rc2_*_a6_run1.zip && cd release && shasum -a 256 -c SHA256SUMS
```

`data/release_manifest.json` cho phép kiểm định danh (`build_id`, `source_hash`,
`config_hash`, `corpus_hash`, `acceptance_status`) mà không phải giải nén 1,7 GB.

## Ba con số đáng nhớ

* `146.246 / 146.246` bảng tìm được (`retrieval_ready`)
* `117.793` bảng có ít nhất một ô dùng được tự động
* `1.798.943` ô `execution_ready`, **100,00%** trong đó đủ `unit + scale + currency`

## Hai điều dễ mất thời gian nếu không biết trước

1. Dữ liệu **không có giá trị phái sinh**. Câu hỏi dạng tỷ lệ, "gấp mấy lần",
   trung bình, chênh lệch phải truy hồi ≥2 ô rồi tính — không tra được một ô.
2. `questions.jsonl` của BTC **không có đáp án chuẩn**. Muốn đo cải tiến thì
   phải tự dựng tập dev có gold.
RD
echo "  README.md"

echo "── 4/4 · manifest + checksum ──"
python - "$OUT" "$BID" "$B" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
out, bid, relsha = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""): h.update(c)
    return h.hexdigest()
files = {}
for p in sorted(out.rglob("*")):
    if not p.is_file(): continue
    r = p.relative_to(out).as_posix()
    if r in ("manifest.json", "SHA256SUMS"): continue
    files[r] = {"bytes": p.stat().st_size, "sha256": sha(p)}
(out / "manifest.json").write_text(json.dumps({
  "_schema": "bo gui team cho tang Retrieval",
  "bundle": "to_team_v2",
  "build_id": bid,
  "release_package_sha256": relsha,
  "gom_gi": {
    "data/": "goi Silver da chung nhan + release_manifest.json de kiem dinh danh nhanh",
    "docs/": "tai lieu du lieu; doc 65 truoc tien",
    "acceptance/": "13 buoc chap nhan, moi buoc co command/stdout/exit_code/step_meta",
  },
  "khong_gom": [
    "ma nguon pipeline (xem bo build_handoff_set.sh)",
    "gold answer / gold table — BTC khong phat hanh",
    "embedding, index dense — chi co BM25/FTS5 trong goi",
  ],
  "n_files": len(files), "total_bytes": sum(v["bytes"] for v in files.values()),
  "files": files}, ensure_ascii=False, indent=1), encoding="utf-8")
(out / "SHA256SUMS").write_text(
    "".join(f"{v['sha256']}  {k}\n" for k, v in files.items()), encoding="utf-8")
print(f"  {len(files)} tệp · {sum(v['bytes'] for v in files.values()):,} B")
PY

python tools/package_release.py --dir "$OUT" --out "$OUT.zip"
echo ""
echo "════════ to_team_v2 ════════"
printf '%14s  %s  %s\n' "$(wc -c < "$OUT.zip" | tr -d ' ')" \
  "$( (shasum -a 256 "$OUT.zip" || sha256sum "$OUT.zip") | cut -d' ' -f1)" "$(basename "$OUT.zip")"
