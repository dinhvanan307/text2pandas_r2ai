# Text2Pandas

Text2Pandas chuyển câu hỏi tài chính tiếng Việt thành truy vấn Pandas có bằng
chứng trên báo cáo tài chính doanh nghiệp niêm yết. Repository gồm pipeline dữ
liệu A6, retrieval, semantic parser, typed execution, đóng gói submission và các
gate tái hiện/kiểm định.

> Cập nhật trạng thái: **2026-08-31**. Đường nộp chính vẫn là Canonical; các
> engine Semantic/Grounded mới chạy shadow hoặc tạo candidate có gate riêng.
> Replay sạch chứng minh kết quả khớp truy vấn Pandas, **không** tự động chứng
> minh Answer Accuracy.

## Trạng thái mới nhất

| Thành phần | Trạng thái | Bằng chứng gần nhất |
|---|---|---|
| Official submission `3842` | 1.012 record; 798 executable; 214 unresolved; Answer/Execution Accuracy `0.3893` | [`provenance/submissions/submission_3842.json`](provenance/submissions/submission_3842.json) |
| Rule 3 compliance candidate | 798/798 replay khớp; 0 validation error; deterministic; **không tự động upload** | [Rule 3 report](docs/reports/RULE3_COMPLIANCE_REPAIR_2026-08-31.md) |
| Semantic V3 Wave 6 S6 | 492 `OK`, 520 `ABSTAIN`; 492/492 replay khớp; Answer Accuracy `NOT_MEASURED`; promotion `BLOCKED` | [Wave 6 S6 E2E report](docs/reports/SEMANTIC_PARSER_WAVE6_COMPOSITION_S6_E2E_REPORT_2026-08-31.md) |

Các con số parser candidate coverage, executable coverage, replay và official
accuracy là các đại lượng khác nhau. Không dùng một đại lượng thay cho đại lượng
khác khi đánh giá chất lượng.

## Kiến trúc

```text
Câu hỏi tiếng Việt
    -> semantic parsing / operation planning
    -> retrieval bảng và observation
    -> joint binding theo entity, period, basis, unit
    -> typed Decimal execution
    -> restricted Pandas query
    -> evidence CSV + clean replay
    -> validation + submission ZIP
```

Data lineage không chọn thư mục `latest`:

```text
raw ViFinQA
    -> A6 build có build_id
    -> retrieval snapshot có index_id
    -> immutable answer run có run_id
    -> validated submission_<run_id>.zip
```

`configs/datasets/active_snapshot.yaml` là nguồn duy nhất chọn raw/A6/retrieval
đang active.

## Hợp đồng tái hiện

Có ba mức tái hiện độc lập:

1. **Source/offline:** clone source, dựng Python environment và chạy offline CI.
   Mức này không cần payload dữ liệu lớn.
2. **Runtime:** materialize đúng raw, A6 và retrieval snapshot rồi chạy smoke/full
   pipeline. Mức này cần khoảng 8 GB database ngoài Git.
3. **Release:** chạy hai full run độc lập, so determinism, validate, clean replay
   và kiểm tra ZIP cuối. Chỉ mức này tạo release evidence.

Fresh clone **không chứa** `silver.db`, `retrieval.db`, run artifact hoặc ZIP.
Raw ViFinQA có nguồn tải công khai. Bundle A6/retrieval đã acceptance hiện chưa có
URL phát hành công khai trong repository; người vận hành phải nhận bundle đúng
checksum từ maintainer hoặc tự rebuild theo phần bên dưới. Không có bundle và
không rebuild thì chỉ chạy được offline tests, chưa thể vận hành full product.

## Yêu cầu môi trường

| Yêu cầu | Hợp đồng |
|---|---|
| Python | CPython `>=3.11`; dùng **3.11.x** để khớp `requirements.lock` và acceptance |
| Hệ điều hành | macOS hoặc Linux; Windows native chưa được xác minh, nên dùng WSL2 |
| Shell/tool | POSIX shell, Git, GNU Make, `unzip`; SQLite phải bật FTS5 |
| Dung lượng | Khoảng 11 GB để vận hành payload active; tối thiểu 40 GB trống nếu rebuild A6 hai lần và đóng gói |
| Network | Chỉ cần khi cài package/tải dữ liệu hoặc optional local model; production inference không gọi mạng |

Các phiên bản chính trong lock hiện tại:

| Package | Phiên bản |
|---|---:|
| pandas | `2.3.3` |
| pyarrow | `25.0.0` |
| lxml | `6.1.1` |
| PyYAML | `6.0.3` |
| pytest | `9.1.1` |
| Ruff | `0.16.2` |
| mypy | `2.3.0` |

Kiểm tra SQLite FTS5:

```bash
python3.11 - <<'PY'
import sqlite3

enabled = sqlite3.connect(":memory:").execute(
    "select sqlite_compileoption_used('ENABLE_FTS5')"
).fetchone()[0]
print("sqlite", sqlite3.sqlite_version, "fts5", bool(enabled))
raise SystemExit(0 if enabled else 1)
PY
```

## 1. Clone đúng source

Nhánh chứa dòng phát triển mới nhất là `mentor-grounded-v6`. `main` và nhánh này
có lịch sử riêng; không tự merge hai nhánh khi chỉ muốn tái hiện một checkpoint.

```bash
git clone https://github.com/dinhvanan307/text2pandas_r2ai.git
cd text2pandas_r2ai
git switch mentor-grounded-v6
git status --short --branch
```

Để tái hiện một report/checkpoint cụ thể, checkout đúng commit ghi trong report
hoặc manifest trước khi cài/chạy. Luôn lưu `git rev-parse HEAD` cùng kết quả.

## 2. Cài môi trường hash-locked

Chạy từ repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
make dp-env-check
```

`make dp-env-check` phải xác nhận Python đúng hợp đồng, lock có hash, dependency
đã cài khớp lock và không có source path ngoài kiểm soát. Không dùng
`pip install -e ".[dev]"` cho acceptance/release vì đường đó không frozen.

Kiểm tra nhanh source và CLI:

```bash
text2pandas --help
make lint
make typecheck
make test-offline
```

## 3. Cấu hình data/artifact root

Mặc định project dùng `data/` và `artifacts/` trong repo. Có thể đặt payload lớn
trên volume khác:

```bash
export T2P_DATA_ROOT=/absolute/path/to/text2pandas-data
export T2P_ARTIFACT_ROOT="$PWD/artifacts"
export TEXT2PANDAS_SCRATCH=/absolute/path/to/fast-local-scratch
mkdir -p "$T2P_DATA_ROOT" "$T2P_ARTIFACT_ROOT" "$TEXT2PANDAS_SCRATCH"
make paths-check
```

Các biến phải trỏ tới đường dẫn tuyệt đối có quyền ghi. Scratch chỉ chứa bản làm
việc; run artifact chính thức nằm trong `T2P_ARTIFACT_ROOT` và không được ghi đè.
Các pipeline chính tôn trọng hai biến root, nhưng helper `submission-handoff`
hiện vẫn resolve `data/` và `artifacts/` từ repository root. Vì vậy giữ artifact
root mặc định như trên. Luồng Rule 3 ở phần 7 truyền rõ `--run-root` và mọi input
path nên không phụ thuộc helper này.

## 4. Tải raw ViFinQA đúng revision

Nguồn raw active:

| Thuộc tính | Giá trị |
|---|---|
| Hugging Face dataset | [`AIGuruTinix/ViFinQA`](https://huggingface.co/datasets/AIGuruTinix/ViFinQA) |
| Revision | `0450088ab22ec946f04f097586967ca405955b3b` |
| Project snapshot ID | `ca033190f2e9e99f` |
| Expected counts | 1.973 báo cáo, 1.012 câu hỏi, 100 ticker |
| License | Corpus tài chính CC BY-NC 4.0; license riêng của question annotations chưa được công bố rõ |

Dùng environment riêng cho downloader để không làm bẩn runtime lock:

```bash
python3.11 -m venv .venv-data
.venv-data/bin/python -m pip install -r tools/data_acquisition/requirements.txt

export VIFINQA_REVISION=0450088ab22ec946f04f097586967ca405955b3b
.venv-data/bin/python - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

dest = Path(os.environ["T2P_DATA_ROOT"]) / "raw" / "btc"
snapshot_download(
    repo_id="AIGuruTinix/ViFinQA",
    repo_type="dataset",
    revision=os.environ["VIFINQA_REVISION"],
    local_dir=dest,
)
print(dest)
PY

.venv-data/bin/python tools/data_acquisition/download_vifinqa.py \
  --dest "$T2P_DATA_ROOT/raw/btc" \
  --verify-only \
  --skip-github

cp data/raw/btc/manifest.json "$T2P_DATA_ROOT/raw/btc/manifest.json"
```

`--verify-only` chuẩn hóa `code_stock.csv` thành `metadata/companies.csv` và
kiểm 13 mục count/structure. Lệnh tải được pin bằng revision; không dùng HEAD mới
nhất của dataset cho active lineage nếu chưa tạo snapshot ID mới.

## 5. Materialize A6 và retrieval

Active identities và checksum certified:

| Layer | Đường dẫn dưới `T2P_DATA_ROOT` | Bytes | SHA-256 |
|---|---|---:|---|
| A6 | `processed/a6/c6887fb633374fad/silver.db` | `4,140,924,928` | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Retrieval | `indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db` | `4,239,663,104` | `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` |

### Cách A — dùng certified bundle

Nhận hai database và thư mục metadata/manifest tương ứng từ maintainer. Repository
hiện chỉ version-control manifest nhỏ, không chứa payload và chưa khai URL tải
bundle công khai. Sau khi copy đúng cấu trúc, kiểm hash bằng máy:

```bash
python - <<'PY'
import hashlib
import os
from pathlib import Path

root = Path(os.environ["T2P_DATA_ROOT"])
expected = {
    root / "processed/a6/c6887fb633374fad/silver.db":
        "fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8",
    root / "indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db":
        "72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf",
}
for path, wanted in expected.items():
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    actual = digest.hexdigest()
    print(path, actual, "PASS" if actual == wanted else "FAIL")
    if actual != wanted:
        raise SystemExit(1)
PY
```

### Cách B — rebuild local từ raw

Đây là đường tái dựng chức năng khi không có certified bundle. Hai build phải dùng
hai output directory mới và cùng config. Không tái sử dụng run ID hoặc output cũ.
Certified A6 manifest ghi source commit
`7837635188639c7fb68b167b2b80ddfbc3935d30`; exact historical rebuild phải chạy
trên commit đó trong một clean checkout/worktree. Rebuild ở source commit khác là
một candidate mới, kể cả khi lệnh giống nhau.

```bash
export A6_ID=c6887fb633374fad
export RETRIEVAL_ID=872ccb0dda9a2bb6
export BUILD_A="$T2P_ARTIFACT_ROOT/runs/a6/reproduce-a"
export BUILD_B="$T2P_ARTIFACT_ROOT/runs/a6/reproduce-b"

make dp-build FINALIZE=1 \
  CONFIG=configs/vifinqa_silver_v1.yaml \
  INPUT="$T2P_DATA_ROOT/raw/btc/financial_statements" \
  OUTPUT="$BUILD_A"

make dp-build FINALIZE=1 \
  CONFIG=configs/vifinqa_silver_v1.yaml \
  INPUT="$T2P_DATA_ROOT/raw/btc/financial_statements" \
  OUTPUT="$BUILD_B"

python tools/rebuild_check.py \
  --build-a "$BUILD_A" \
  --build-b "$BUILD_B" \
  --mode final \
  --db-sha256 \
  --report "$T2P_ARTIFACT_ROOT/reports/a6-reproduce-c0-final.json"
```

Hai build phải cho cùng `build_id`. Nếu không phải `c6887fb633374fad`, dừng lại:
không sửa `active_snapshot.yaml` để ép một artifact khác thành active.

Tạo local A6 release phục vụ runtime:

```bash
make dp-release \
  DB="$BUILD_A/silver/$A6_ID/silver.sqlite" \
  BRONZE="$BUILD_A/bronze/catalog_v2.sqlite" \
  QUALITY="$BUILD_A/silver/$A6_ID/quality_report.json" \
  OUTPUT="$T2P_DATA_ROOT/processed/a6/$A6_ID" \
  REPORT_DIR="$T2P_ARTIFACT_ROOT/reports/a6-reproduce-release"
```

Không truyền `GATE_REPORT` nên release này được ghi đúng là local/not accepted.
Muốn tạo certified release phải chạy đầy đủ C0/C1/readiness/replay/quality gate
theo [acceptance report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md), không
đổi nhãn acceptance bằng tay.

Tạo retrieval snapshot bất biến từ A6 release:

```bash
python - <<'PY'
import os
from pathlib import Path
from text2pandas.infrastructure.retrieval.snapshot import build_retrieval_snapshot

root = Path(os.environ["T2P_DATA_ROOT"])
a6_id = os.environ["A6_ID"]
index_id = os.environ["RETRIEVAL_ID"]
result = build_retrieval_snapshot(
    root / "processed" / "a6" / a6_id / "silver.db",
    root / "indexes" / "retrieval" / a6_id / index_id,
    expected_build_id=a6_id,
)
print(result)
PY
```

`build_retrieval_snapshot` từ chối output đã tồn tại. Nếu cần rebuild, dùng data
root mới; không xóa hoặc ghi đè snapshot đã được run khác tham chiếu.

## 6. Xác minh active lineage

```bash
make paths-check
make snapshots-verify
python tools/data_acquisition/download_vifinqa.py \
  --dest "$T2P_DATA_ROOT/raw/btc" \
  --verify-only \
  --skip-github
```

`make snapshots-verify` kiểm identity, schema, count, kích thước và index contract,
nhưng cố ý không hash database nhiều GB. Với certified bundle phải chạy thêm bước
SHA-256 ở phần 5.

## 7. Chạy sản phẩm

Mỗi `run-id` là bất biến. Dùng ID mới cho mọi lần thử.

### Smoke test 10 câu

```bash
text2pandas run \
  --run-id reproduce-smoke-001 \
  --offset 0 \
  --limit 10 \
  --no-package
```

Partial run bắt buộc có `--no-package`. Artifact nằm tại
`$T2P_ARTIFACT_ROOT/runs/answer/reproduce-smoke-001/`.

### Full Canonical baseline

```bash
export RUN_A=reproduce-canonical-a-001
export RUN_B=reproduce-canonical-b-001

text2pandas run --run-id "$RUN_A" --no-package
text2pandas run --run-id "$RUN_B" --no-package

cmp \
  "$T2P_ARTIFACT_ROOT/runs/answer/$RUN_A/records.jsonl" \
  "$T2P_ARTIFACT_ROOT/runs/answer/$RUN_B/records.jsonl"
```

Hai run phải xử lý cùng 1.012 câu và cho `records.jsonl` byte-identical. Manifest
khác nhau hợp lệ vì chứa `run-id` và thời điểm chạy. Canonical hiện còn abstention;
vì vậy `text2pandas run --run-id <id>` không có `--no-package` sẽ fail closed ở
complete-profile packaging thay vì tạo ZIP có record thiếu evidence/query. Đây là
hành vi đúng, không phải lỗi cài đặt.

Artifact chính:

```text
$T2P_ARTIFACT_ROOT/runs/answer/<run-id>/manifest.json
$T2P_ARTIFACT_ROOT/runs/answer/<run-id>/records.jsonl
```

`make verify-active-candidate RUN_A=... RUN_B=...` chỉ áp dụng khi **cả hai** run
đã tạo validated ZIP; không dùng gate đó để biến baseline có abstention thành
complete candidate.

### Rebuild Rule 3 competition candidate mới nhất

Candidate mới nhất là phép sửa compliance từ exact official baseline 3842; nó
không được tạo chỉ từ Canonical baseline ở trên. Cần cung cấp ZIP gốc có SHA-256:

```text
2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76
```

ZIP này nằm ngoài Git. Nếu không có exact baseline, trạng thái là `BLOCKED`; không
dùng một ZIP “gần giống”. Tool yêu cầu clean committed source tree, kiểm identity,
traceability, competition validation, clean replay và tự build lần hai để kiểm
determinism.

```bash
export BASELINE_3842=/absolute/path/to/submission-3842.zip
export RULE3_RUN=rule3-3842-reproduce-001

PYTHONPATH=src python tools/build_rule3_compliance_candidate.py \
  --run-id "$RULE3_RUN" \
  --baseline "$BASELINE_3842" \
  --a6-database "$T2P_DATA_ROOT/processed/a6/c6887fb633374fad/silver.db" \
  --corpus "$T2P_DATA_ROOT/raw/btc/financial_statements" \
  --questions "$T2P_DATA_ROOT/raw/btc/questions/questions.jsonl" \
  --run-root "$T2P_ARTIFACT_ROOT/runs/rule3-compliance"

unzip -t \
  "$T2P_ARTIFACT_ROOT/runs/rule3-compliance/${RULE3_RUN}.zip"
```

Kết quả mong đợi theo checkpoint đã seal: 1.012 record, 798 query thực thi và
khớp, 214 unresolved, 0 competition validation error, hai ZIP byte-identical.
Complete profile vẫn `FAIL`; official Answer Accuracy của candidate mới là
`NOT_MEASURED`. Output chính:

```text
$T2P_ARTIFACT_ROOT/runs/rule3-compliance/<run-id>/manifest.json
$T2P_ARTIFACT_ROOT/runs/rule3-compliance/<run-id>.zip
```

Không gọi ZIP “đạt accuracy” chỉ vì validation/replay PASS. Khi upload, lưu
submission ID, exact ZIP SHA-256 và score receipt cùng một provenance record.

### Semantic V3 shadow

```bash
text2pandas shadow-v3 \
  --run-id reproduce-semantic-v3-001 \
  --operand-k 20 \
  --legacy-run-id "$RUN_A" \
  --canonical-table-priors
```

Shadow run không thay Canonical output. Chỉ package/promote khi policy và gold
gate tương ứng PASS; trạng thái hiện tại vẫn `BLOCKED`.

## 8. Checkpoint và model

Đường Canonical và Semantic V3 deterministic **không cần tải LLM checkpoint**.

- `configs/retrieval/models/linear_reranker_v1.json` là checkpoint nhỏ đã tracked,
  nhưng learned S3 chưa được promote làm default vì held-out evidence gold chưa đủ.
- `configs/models.yaml` hiện không khai embedding/reranker/coder production model.
- `grounded-v5` có optional Ollama fallback, nhưng default inputs gồm baseline ZIP,
  secondary ZIP và semantic records nằm ngoài Git. Model/input digest chưa được
  phát hành như một public reproducible bundle, nên đường này không thuộc fresh-clone
  production runbook.
- Release deterministic phải dùng `--deterministic-only` và vẫn cần cung cấp rõ
  mọi input ZIP/record bằng path + SHA-256. Không tải model đóng hoặc remote API.

## 9. Test và gate

| Gate | Lệnh | Phạm vi |
|---|---|---|
| Link tài liệu | `make docs-check` | Markdown tracked |
| Static correctness | `make lint` | Ruff syntax/name/safety checks |
| Typed architecture | `make typecheck` | `domain/application/infrastructure/interface` |
| Offline suite | `make test-offline` | Không cần payload lớn |
| Materialized integration | `make test-integration` | Cần active raw/A6/retrieval |
| Full report | `make dp-test REPORT_DIR=<new-dir>` | JSON/text/JUnit report |
| Route coverage | `make semantic-coverage` | Coverage, không phải accuracy |
| Snapshot lineage | `make snapshots-verify` | Active raw → A6 → retrieval |

Gate tối thiểu trước release:

```bash
make lint
make typecheck
make test-offline
make test-integration
make snapshots-verify
git diff --check
```

Historical tests cần authentic pre-refactor artifacts và chỉ chạy bằng
`make test-historical`. Không tạo file giả hoặc đổi skip để làm gate xanh.

## 10. Cấu hình quan trọng

| Tệp | Vai trò |
|---|---|
| [`configs/datasets/active_snapshot.yaml`](configs/datasets/active_snapshot.yaml) | Chọn raw/A6/retrieval identity |
| [`configs/vifinqa_silver_v1.yaml`](configs/vifinqa_silver_v1.yaml) | Cấu hình build A6 và determinism |
| [`configs/semantic/promotion_policy_v3.yaml`](configs/semantic/promotion_policy_v3.yaml) | Gate promote Semantic V3 |
| [`configs/models.yaml`](configs/models.yaml) | Registry production model và ràng buộc model |
| [`configs/testing/approved_skips_v1.yaml`](configs/testing/approved_skips_v1.yaml) | Allowlist skip có quản trị |

Không sửa ID/path trong active snapshot để né verification. Artifact mới phải có
manifest, checksum, source identity và gate trước khi trở thành active.

## 11. Cấu trúc repository

| Path | Trách nhiệm |
|---|---|
| `src/text2pandas/domain/` | Pure types và business rules |
| `src/text2pandas/application/` | Parser, planner, binder, compiler, executor |
| `src/text2pandas/infrastructure/` | SQLite, filesystem, retrieval, ontology, sandbox |
| `src/text2pandas/interface/` | CLI thống nhất |
| `src/text2pandas/pipelines/` | Canonical/migration pipelines |
| `configs/` | Identity, policy, registry, formula, ontology |
| `data/` | Raw/processed/indexed/curated data classes; payload lớn bị ignore |
| `artifacts/` | Generated run/report/package/submission; bị ignore mặc định |
| `provenance/` | Identity, checksum và audit seal nhỏ được track |
| `tests/` | Unit, contract, regression và materialized integration |
| `docs/` | ADR, competition contract, migration status và report |

`data_pipeline`, `retrieval` và `text2pandas.answer_pipeline` là compatibility
namespace. Code production mới phải import từ `text2pandas`.

## 12. Submission contract

Một package hợp lệ có đúng một JSON ở root và mọi CSV được tham chiếu dưới
`data/`:

```text
submission.zip
|-- submission.json
`-- data/
    |-- table_001.csv
    `-- table_002.csv
```

Mỗi record gồm `id`, `question`, `answer`, `relevant_docs`, `relevant_tables`,
`evidence`, `pandas_query`. Validator từ chối path không an toàn, locator sai,
CSV orphan, query không an toàn, duplicate evidence variable, câu hỏi lệch source
và answer không khớp clean Pandas replay.

## 13. Giới hạn và stop conditions

- Official score chỉ gắn với exact submission receipt/ZIP SHA; không suy từ local proxy.
- Semantic Wave 6 S6 còn 520 abstention và chưa có independent answer gold.
- Rule 3 candidate còn 214 unresolved; `complete` profile chưa PASS.
- A6 Structure Gold `SG/C2/C3` chưa đủ review độc lập.
- Public URL cho certified A6/retrieval bundle hiện chưa được khai báo.
- Không promote model/reranker từ development set hoặc contaminated proxy.
- Không overwrite raw snapshot, immutable run, database snapshot hoặc release path.

Nếu một prerequisite thiếu, báo `BLOCKED`/`NOT_MEASURED`; không thay bằng file giả,
hard-code answer hoặc nới gate.

## Tài liệu tham chiếu

- [Agent operating contract](AGENTS.md)
- [Contribution workflow](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Data ownership and lifecycle](data/README.md)
- [Competition source and license notes](docs/competition/README.md)
- [Semantic V3 migration status](docs/SEMANTIC_V3_MIGRATION_STATUS.md)
- [Active A6 acceptance report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md)
- [Rule 3 compliance report](docs/reports/RULE3_COMPLIANCE_REPAIR_2026-08-31.md)
- [Latest Semantic Wave 6 S6 E2E report](docs/reports/SEMANTIC_PARSER_WAVE6_COMPOSITION_S6_E2E_REPORT_2026-08-31.md)
- [Architecture decisions](docs/adr/)
