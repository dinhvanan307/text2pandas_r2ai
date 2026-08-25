#!/usr/bin/env bash
# Đóng gói MÃ NGUỒN để gửi đi — tất định, không kèm artifact/dữ liệu/tài liệu.
#
# Vì sao cần script này thay vì `zip -r`:
#   - repo 73 GB, trong đó artifacts/ 64 GB và data/ 7,7 GB là artifact DẪN XUẤT;
#   - `zip -r` của Finder/macOS nhét `__MACOSX/` và extended attribute vào gói;
#   - thứ tự entry và timestamp mặc định làm hai lần chạy ra hai sha256 khác nhau.
#
# Cách làm: dựng một cây sạch trong thư mục tạm (một root duy nhất), rồi giao cho
# `tools/package_release.py` — bộ đóng gói tất định đã có sẵn của repo (RC-23:
# timestamp cố định, entry sort theo chuỗi POSIX, chặn `.DS_Store`/`__MACOSX`).
#
# Dùng:
#   bash scripts/dong_goi_source.sh [thư_mục_đích]
# Mặc định thư_mục_đích = thư mục cha của repo.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$(dirname "$ROOT")}"

# ---------------------------------------------------------------- định danh gói
#
# Định danh phải bám vào COMMIT, không bám vào lúc chạy. Bản đầu dùng
# `date -u` trong PACKAGE_README.md và hai lần chạy ra hai sha256 khác nhau —
# đúng cái mà `tools/package_release.py` tồn tại để ngăn.
NGAY="$(date +%Y%m%d)"
SHA_GIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
NGAY_COMMIT="$(git -C "$ROOT" show -s --format=%cs HEAD 2>/dev/null || echo unknown)"
TEN="text2pandas_source_${NGAY}_${SHA_GIT}"
OUT="${DEST%/}/${TEN}.zip"

if [ -e "$OUT" ]; then
  echo "✗ $OUT đã tồn tại — từ chối ghi đè" >&2
  exit 2
fi

# ------------------------------------------------------------------- danh sách
# CHỈ mã nguồn + cấu hình + định danh. Mọi thứ khác là artifact dẫn xuất, dựng
# lại được, hoặc quá lớn để gửi.
THU_MUC=(
  src            # 3,6 M  mã lõi
  tools          # 3,8 M  đường sinh bài nộp + dụng cụ đo
  tests          # 5,0 M  1614 test
  configs        # 256 K  cấu hình (ontology, formula, retrieval, readiness)
  evaluation     # 1,3 M  question_plans_1012.jsonl + bộ đánh giá
  identity       # 384 K  source/environment/data identity + seal
  env            #  28 K  bootstrap môi trường review
  scripts        #  24 K  script vận hành
  docker         #        Dockerfile (nếu có)
)

TEP=(
  Makefile
  pyproject.toml
  requirements.lock
  README.md
  CLAUDE.md
  HANDOFF.md
  packet_kind.json
  .gitignore
)

# LOẠI TRỪ có chủ đích — ghi ra để người đọc biết thiếu gì:
#   artifacts/ (64 G) · data/ (7,7 G) · silver_release.zip (1,5 G)
#   .venv-build .venv-review (529 M) · reports/ (75 M) · dist/ (9,4 M)
#   docs/ (5,8 M) · to_read/ (2,1 M) · _TO_DELETE/ (24 M)
#   sync_122_1 sync_122_2 (bản sao source) · .git/ · *.zip

# ------------------------------------------------------------------- dàn dựng
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STAGE="$TMP/$TEN"
mkdir -p "$STAGE"

echo "→ dàn dựng cây sạch tại $STAGE"

for d in "${THU_MUC[@]}"; do
  [ -d "$ROOT/$d" ] || { echo "  · bỏ qua $d/ (không tồn tại)"; continue; }
  # --prune-empty-dirs: không để lại thư mục rỗng sau khi lọc
  rsync -a \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache/' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    --exclude='*.zip' \
    --exclude='*.db' \
    --exclude='*.sqlite' \
    --exclude='.venv*/' \
    --prune-empty-dirs \
    "$ROOT/$d/" "$STAGE/$d/"
  echo "  · $d/"
done

for f in "${TEP[@]}"; do
  [ -f "$ROOT/$f" ] && { cp "$ROOT/$f" "$STAGE/$f"; echo "  · $f"; }
done

# ------------------------------------------------------- ghi manifest loại trừ
cat > "$STAGE/PACKAGE_README.md" <<EOF
# text2pandas — gói MÃ NGUỒN

**Commit:** \`$SHA_GIT\` · **ngày commit:** $NGAY_COMMIT
**Đóng gói bằng:** \`scripts/dong_goi_source.sh\` → \`tools/package_release.py\` (tất định)

## Gói này CÓ

\`src/\` \`tools/\` \`tests/\` \`configs/\` \`evaluation/\` \`identity/\` \`env/\` \`scripts/\`
+ \`Makefile\` \`pyproject.toml\` \`requirements.lock\` \`README.md\` \`CLAUDE.md\` \`HANDOFF.md\`

## Gói này KHÔNG có, và vì sao

| Bị loại | Dung lượng | Lý do |
|---|---|---|
| \`artifacts/\` | 64 G | artifact dẫn xuất (\`work.db\` 4,2 G, \`rc2/\` 60 G) |
| \`data/silver/\` | 7,3 G | Silver SSOT — dựng lại bằng \`make dp-build\` |
| \`data/external/\` | 379 M | corpus ViFinQA — tải lại bằng \`tools/data_acquisition/\` |
| \`data/submissions/\` | 20 M | bài nộp ZIP |
| \`silver_release.zip\` | 1,5 G | gói phát hành |
| \`reports/\` | 75 M | số liệu đo |
| \`docs/\` | 5,8 M | 168 tài liệu (loại theo yêu cầu) |
| \`to_read/\`, \`_TO_DELETE/\`, \`dist/\`, \`sync_122_*\` | — | tạm / bản sao |
| \`.venv-build/\`, \`.venv-review/\` | 529 M | môi trường ảo |
| \`.git/\` | 11 M | lịch sử |

## Chạy

\`\`\`bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python3 -m pytest tests/ -q --continue-on-collection-errors
\`\`\`

⚠️ **Đã biết:** không có \`conftest.py\` ⇒ \`pytest tests/\` (không cờ) dừng ở
3 lỗi collect (\`test_a5_row_path_period\`, \`test_a5_scale_applicability\`,
\`test_a6_manifest_identity\` — \`ModuleNotFoundError: data_pipeline\`). Cài
\`pip install -e .\` trước, hoặc dùng \`--continue-on-collection-errors\`.
Xem \`docs/179_TECHNICAL_ARCHITECTURE_AUDIT.md\` §P0-2.

Phần lớn \`tools/\` cần \`artifacts/retrieval/work.db\` và \`data/silver/\`; không
có hai thứ đó thì chỉ đọc và chạy test đơn vị được.
EOF

# ------------------------------------------------------------------ đóng gói
echo "→ đóng gói tất định"
python3 "$ROOT/tools/package_release.py" --dir "$STAGE" --out "$OUT"

# sha256 kèm TÊN FILE (không phải "-"), để `sha256sum -c` chạy được ở phía nhận.
# macOS không có sha256sum; shasum -a 256 là bản thay thế có sẵn.
if command -v sha256sum >/dev/null 2>&1; then
  H="$(sha256sum "$OUT" | cut -d' ' -f1)"
else
  H="$(shasum -a 256 "$OUT" | cut -d' ' -f1)"
fi
printf '%s  %s\n' "$H" "$(basename "$OUT")" > "$OUT.sha256"

echo
echo "✓ $OUT"
echo "  $(du -h "$OUT" | cut -f1) · $(unzip -Z1 "$OUT" | wc -l | tr -d ' ') entry"
echo "  sha256: $(cut -d' ' -f1 "$OUT.sha256")"
