# HANDOFF — Silver v1 RC2

> **Trạng thái:** `IN_PROGRESS` — **chưa build RC2**. Mọi ô ghi `⬜ sau build` là
> chưa có, **không phải đã có mà quên điền**.
> **Baseline RC1:** immutable, READ-ONLY. Không ghi đè, không regenerate thay thế.
> **`source_snapshot_id`:** xem `SOURCE_MANIFEST.json` trong gói này. Nó phải
> khớp `EVIDENCE_MANIFEST.json` của gói evidence; không khớp thì **từ chối cả hai**.

---

## 0. Đọc cái này trước — gói này KHÔNG khẳng định điều gì

| Khẳng định | Trạng thái |
|---|---|
| Test suite xanh trên **build host** | ✅ **478 collected · 478 passed · 0 failed · 0 skipped · 0 error** (11/08/2026) |
| Toolchain chạy được đầu-cuối | ✅ nhưng **chỉ trên fixture** — xem `status/smoke_run.json` của gói evidence |
| Môi trường **frozen** đã xác nhận | ❌ **NOT_VERIFIED** — lock đã có hash, nhưng chưa có bằng chứng `pip install --require-hashes` |
| RC2 metric (readiness, recall FTS, coverage) | ❌ **NOT_MEASURED** — chưa có RC2 build |
| C0 / C1 / C4 / C5 trên corpus thật | ❌ **NOT_RUN** |
| C1 no-loss trên **RC1** | ✅ PASS 10/10 (đây là RC1, không phải RC2) |
| RC1 source reproduction | ❌ revision của RC1 không có trong repo này. **Không tái lập được. Nguyên nhân: chưa xác minh.** |

---

## 1. Môi trường

| | Build host (đo 11/08/2026) |
|---|---|
| OS | `Darwin 25.5.0 (arm64)` |
| Python | `3.11.15` (`/opt/anaconda3/envs/text2pandas/bin/python`) |
| SQLite | `3.53.2` |
| pandas / pyarrow / PyYAML | `2.3.3` / `25.0.0` / `6.0.3` |
| pytest | `9.1.1` |
| `corpus_file_count` | `1973` |
| Đĩa trống tối thiểu để build | **40 GB** (`MIN_FREE_GB_BUILD`) |

`requirements.lock`: **22 pin · 647 hash**, sinh bằng
`pip-compile --extra=dev --generate-hashes` dưới Python 3.11.

---

## 2. Cài đặt

Cách **đúng** (frozen, tái lập được):

```bash
python3.11 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
```

> Dùng `python -m pip`, **không** dùng `pip` trần. Trên macOS `pip` trần rơi vào
> `~/Library/Python/3.9/bin/pip` của hệ thống và cài nhầm interpreter.

Kiểm import:

```bash
python -c "import data_pipeline, sys; print('ok', sys.version)"
```

**Cổng xác nhận frozen** — chạy `make dp-env-check` và đọc ba trường:

```text
lock_matches_installed = True      ← điều kiện thoát RC2-006
lock_has_hashes        = True
untracked_in_source_paths = []     ← khác rỗng là FAIL cứng
```

`lock_matches_installed = None` nghĩa là **chưa đo được** (không có lock), khác
hẳn `False` (đo rồi và lệch). Đừng gộp hai cái.

---

## 3. Lệnh — hợp đồng duy nhất

```bash
CFG=configs/vifinqa_silver_v1.yaml
CORPUS=data/external/vifinqa/financial_statements     # ← KHÔNG phải .../vifinqa
RC2=artifacts/rc2

make dp-env-check
make dp-test          REPORT_DIR=$RC2/test_report

# build A
export DATA_PIPELINE_SCRATCH="$PWD/$RC2/buildA"
make dp-build         CONFIG=$CFG INPUT=$CORPUS OUTPUT=$RC2/buildA

# build B — SHELL/PROCESS KHÁC
export DATA_PIPELINE_SCRATCH="$PWD/$RC2/buildB"
make dp-build         CONFIG=$CFG INPUT=$CORPUS OUTPUT=$RC2/buildB

# C0 — TRƯỚC quality/publish, TRƯỚC mọi lệnh dọn dẹp
make dp-rebuild-check BUILD_A=$RC2/buildA BUILD_B=$RC2/buildB \
                      REPORT=$RC2/rebuild_check.json

# quality → publish (shell của build A)
python -m data_pipeline.cli quality
python -m data_pipeline.cli publish

# C1 no-loss — chạy trên BUILD DB, KHÔNG phải gói slim
python tools/no_loss_check.py --db data/silver/vifinqa/<BID>/silver.sqlite \
                              --report $RC2/c1_no_loss.json --check-unicode-digits

# sổ ca chưa giải quyết
python tools/unresolved_registry.py --db data/silver/vifinqa/<BID>/silver.sqlite \
                              --report $RC2/unresolved.json --cases $RC2/unresolved.csv

make dp-release       DB=data/silver/vifinqa/<BID>/silver.sqlite \
                      OUTPUT=$RC2/release REPORT_DIR=$RC2/release_report
make dp-package       DIR=$RC2/release OUT=$RC2/silver_rc2.zip
make dp-verify        PACKAGE=$RC2/silver_rc2.zip TYPE=release

# CHỈ BÂY GIỜ mới được dọn
rm -f $RC2/buildA/silver.sqlite ; rm -rf $RC2/buildB
```

### Ba thứ không được đảo

1. **`INPUT` phải là `data/external/vifinqa/financial_statements`.** Trỏ vào
   thư mục cha gộp thêm 15 tệp `_codebase/prompts/*.txt` vào `corpus_hash` —
   hai nguồn sự thật cho cùng một đường dẫn. Xem RC2-016.
2. **C0 trước `publish`.** Publish một bản dựng chưa chứng minh tất định là
   công bố thứ chưa kiểm được.
3. **Dọn `buildA/silver.sqlite` SAU C0.** `tools/rebuild_check.py:52` đọc thẳng
   tệp đó; xoá trước thì C0 không chạy được và phải build lại.

### `OUTPUT` phải nằm ngoài cây `snapshot` quét

`cmd_snapshot` quét `CORPUS.parent` = `data/external/vifinqa/`. `artifacts/rc2/…`
nằm ngoài — an toàn. Nếu ai đổi `OUTPUT` vào trong `data/external/`, build A
trở thành đầu vào của build B và **C0 đỏ với lý do sai** (giá trị giống hệt,
chỉ UID lệch). Tự kiểm: `corpus_file_count` phải vẫn là `1973` trước build B.

---

## 4. Smoke — chứng minh toolchain, không chứng minh dữ liệu

```bash
export SMK=/tmp/smk
mkdir -p "$SMK/corpus/vifinqa/financial_statements"
# chép 2 tệp *_extracted.txt bất kỳ vào đúng cây trên, rồi fork config:
sed 's#^\( *root:\).*#\1 '"$SMK"'/corpus/vifinqa/financial_statements#' \
    configs/vifinqa_silver_v1.yaml > "$SMK/config.yaml"

python tools/env_check.py --config "$SMK/config.yaml" --json
DATA_PIPELINE_SCRATCH=$SMK/A python tools/build_runner.py \
    --config "$SMK/config.yaml" --input "$SMK/corpus/vifinqa/financial_statements" \
    --output "$SMK/A" --allow-low-disk
env -i PATH="$PATH" HOME="$HOME" PYTHONHASHSEED=0 TZ=UTC LC_ALL=C.UTF-8 \
    DATA_PIPELINE_SCRATCH="$SMK/B" python tools/build_runner.py \
    --config "$SMK/config.yaml" --input "$SMK/corpus/vifinqa/financial_statements" \
    --output "$SMK/B" --allow-low-disk
python tools/rebuild_check.py --build-a "$SMK/A" --build-b "$SMK/B" \
    --report "$SMK/rebuild_check.json"
DATA_PIPELINE_SCRATCH=$SMK/A python -m data_pipeline.cli quality
DATA_PIPELINE_SCRATCH=$SMK/A python -m data_pipeline.cli publish   # kỳ vọng exit 2
```

`publish` **phải** trả exit 2 trên fixture — G5 đòi ≥10.000 phép kiểm số học,
fixture 2 bảng không thể đạt. Đó là **bằng chứng cổng an toàn hoạt động**,
không phải lỗi.

---

## 5. Verify gói

```bash
# gói release
make dp-package DIR=<release_dir> OUT=/tmp/z1.zip
make dp-package DIR=<release_dir> OUT=/tmp/z2.zip
shasum -a 256 /tmp/z1.zip /tmp/z2.zip     # hai dòng PHẢI trùng
make dp-verify PACKAGE=/tmp/z1.zip TYPE=release

# gói source
git archive --format=zip --prefix=text2pandas-rc2/ -o /tmp/src.zip HEAD
make dp-verify PACKAGE=/tmp/src.zip TYPE=source
```

`verify_package.py` nhận **tệp zip** và tự giải nén vào thư mục tạm sạch —
verify thẳng thư mục vừa build là kiểm **một thứ khác** với thứ sẽ gửi đi.

---

## 6. Baseline RC1 — đã khoá

| | |
|---|---|
| Gói | `silver_release.zip` |
| sha256 gói | `11159af3bb5929c0e7b58a1f544a35448c957fad8a6e6992f27a336f974c7b10` |
| sha256 `silver.db` (release slim) | `fe4e75ce9ada37c0eb8fa6ad82fe487c196e6ef7a3ecf288da5e436ce4e00eaa` |
| build_id | `b927c3e8f90aed74` |
| release_label / status | `silver-v1.0.0-rc1` / `blocked` |
| Source revision ghi trong manifest | `0450088ab22ec946f04f097586967ca405955b3b` — **không resolve được trong repo này** |

**Counts RC1** (đã xác minh trực tiếp):

```
documents 1.973 · pages 121.756 · tables 146.246 · observations 2.646.976
dropped_cells 766.231 · collision_obs 441.974 · table_cards 146.246
execution_ready 1.862.583 · zero-obs tables 12.353 · zero-ready tables 27.144
source_cells 6.212.883  (CHỈ có trong build DB, KHÔNG có trong release slim)
```

> `execution_ready = 1.862.583` là con số RC1 **công bố**, nhưng RC-02 chứng
> minh nó thực chất là `execution_candidate`. Không dùng làm ngưỡng cho RC2.

**C1 no-loss đo trên RC1 build DB — PASS 10/10:**

```
ô nguồn        6.212.883        ô MANG CHỮ SỐ (U_digit)  3.413.207
observations   2.646.976        dropped_cells             766.231
2.646.976 + 766.231 = 3.413.207 ✓   theo TẬP UID, không chỉ theo số đếm
```

Đừng so `6.212.883` với `3.413.207` rồi kết luận "mất 45% dữ liệu".

## 7. RC2 — chưa có

| | |
|---|---|
| build_id · counts · checksums | ⬜ sau build |
| Gate SG/C0–C5 | ⬜ sau RC-20 |
| `allowed_blocked_gates` | `SG`, `C2`, `C3` |
| `release_label` | `silver-v1.0.0-rc2` |

## 8. Ngoại lệ đã ghi nhận

**RC-01 = `WAIVED_WITH_EVIDENCE`.** Source revision của RC1 không có trong
repository chung; không tái checkout được tại đây. Nguyên nhân **chưa xác
minh** — nhiều khả năng là clone/working tree khác. Bù rủi ro bằng: clean build
A/B từ source RC2 đã commit · C0 deterministic · differential RC1→RC2 theo
physical key · C1 no-loss trên build DB RC2 · source package verify từ bản
giải nén sạch.

**Không tuyên bố "RC1 đã được tái hiện".**

## 9. Bất biến không được vi phạm

```
RC1 READ-ONLY                      · không ghi đè silver_release/
RAW → TRANSFORM → OBSERVATION → DROPPED LINEAGE
mọi observation bị loại phải có    : source_cell_uid · reason · rule · policy_version · stage
execution_ready ⇒ execution_candidate
U_observation ∩ U_dropped = ∅      · U_digit = U_observation ∪ U_dropped
```

## 10. Bố cục repo — khác với bố cục mặc định

Yêu cầu bàn giao nhắc `tests/data_pipeline/`, `fixtures/`, `scripts/`,
`schema/`. Repo này **không có** bốn đường dẫn đó. Bố cục thật:

| Yêu cầu | Thực tế trong repo |
|---|---|
| `src/data_pipeline/` | ✅ `src/data_pipeline/` (76 tệp) |
| `configs/` | ✅ `configs/` (11 tệp) |
| `tests/data_pipeline/` | ⚠ test nằm phẳng ở `tests/*.py` (24 tệp) |
| `fixtures/` | ⚠ `tests/fixtures/` (rỗng — fixture dựng trong test) |
| `tools/` | ✅ `tools/` (32 tệp) |
| `scripts/` | ❌ **KHÔNG TỒN TẠI** — vai trò này do `tools/` + `Makefile` đảm nhiệm |
| `schema/` | ❌ **KHÔNG TỒN TẠI** — schema khai trong `src/data_pipeline/release_schema.py` và `storage.py` |
| `Makefile` · `pyproject.toml` · lock | ✅ |

Ghi ra đây thay vì tạo thư mục rỗng cho khớp danh sách.
