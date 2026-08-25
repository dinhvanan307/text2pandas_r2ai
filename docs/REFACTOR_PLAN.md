# Text2Pandas — Kế hoạch refactor cấu trúc repository

## 1. Kết luận kiến trúc

Repository phải phản ánh đúng data lineage của bài toán:

```text
BTC raw snapshot
  ├── 1.973 báo cáo tài chính .txt / 100 công ty
  ├── 1.012 câu hỏi test
  └── metadata mã cổ phiếu
          │
          ▼
      A6 processed dataset
      build_id = b3e9684004679ffb
          │
          ▼
      Retrieval index
      index/config fingerprint = 286973b134a189ee
          │
          ▼
      Answering → validation → submission.zip
```

Quy ước đề xuất:

- `data/raw/btc/` là dữ liệu gốc do BTC cấp và **bất biến**.
- `data/processed/a6/<build_id>/` là dữ liệu đã xử lý, có manifest và checksum.
- `data/indexes/retrieval/<a6_build_id>/<index_id>/` là index dẫn xuất từ đúng
  snapshot A6.
- `data/curated/` chỉ chứa nhãn dev/gold được quản trị như dữ liệu đầu vào.
- `artifacts/` chứa output của run, report, submission, handoff và package có thể
  tái tạo.
- Git chỉ quản lý source, config, test fixture nhỏ, tài liệu, schema, manifest và
  checksum. Không commit corpus, DB, Parquet, ZIP hay output run dung lượng lớn.

Không thực hiện big-bang refactor. Mọi bước di chuyển phải có compatibility layer,
checksum trước/sau và rollback point.

## 2. Baseline hiện tại

### 2.1 Dữ liệu vật lý đang nằm ngoài repository

| Hiện tại | Dung lượng / định danh | Vai trò thực tế | Vấn đề |
|---|---:|---|---|
| `../data/` | 7,7 GB | raw BTC + bronze/silver + dev/gold + submission + handoff | Trộn immutable input, curated input và generated output |
| `../data/external/vifinqa/financial_statements/` | 1.973 `.txt`, 100 mã | Raw corpus BTC | Tên `external` sai ngữ nghĩa; `_codebase` nằm cạnh corpus có nguy cơ làm bẩn corpus hash |
| `../data/external/vifinqa/questions/questions.jsonl` | 1.012 câu hỏi | Raw test questions | Đúng là raw input nhưng đang nằm trong namespace `external` |
| `../release_finala6/` | 6,5 GB; build `b3e9684004679ffb` | A6 processed release | Tên mutable, không namespace theo build; đứng ngoài repo nhưng code dùng path khác |
| `../retrieval/work.db` | 4.240.060.416 bytes | DB A6 được bổ sung index cho retrieval | Chép gần như toàn bộ A6; tên `work.db` không nói rõ source snapshot |
| `../retrieval/{evalkit,reaudit,audit,vplus}/` | khoảng 57 MB | Experiment/evaluation outputs | Đang trộn với production index |

### 2.2 Source repository

- Ba package Python cùng tồn tại: `data_pipeline`, `retrieval`, `text2pandas`.
- `text2pandas` đã có skeleton theo layer nhưng implementation chính vẫn phân tán
  trong hai top-level package còn lại.
- Có 104 source files, 80 test files và 238 Python files trong `tools/`.
- 64 test files nằm phẳng ở `tests/`, chưa thể hiện ownership theo module.
- `tools/` đang gánh cả production command, migration, audit, experiment và script
  dùng một lần.
- `evaluation/` và `identity/` đang trộn input được quản trị với output/audit artifact.
- `env/` chứa script và evidence môi trường nhưng bị `.gitignore` loại toàn bộ do tên
  trùng quy ước virtual environment.
- `src/text2pandas.egg-info/`, `.DS_Store`, `__pycache__` là generated files và không
  thuộc source tree.
- `README.md` tham chiếu nhiều file `docs/*` và entrypoint hiện không có trong source
  packet; cần audit lại sau khi ổn định layout.

## 3. Cấu trúc đích

```text
Text2Pandas/
├── README.md
├── pyproject.toml
├── Makefile
├── .gitignore
├── configs/
│   ├── datasets/
│   │   ├── btc.yaml
│   │   └── active_snapshot.yaml
│   ├── pipelines/
│   │   ├── a6.yaml
│   │   ├── retrieval.yaml
│   │   └── answering.yaml
│   ├── evaluation/
│   └── policies/
├── src/
│   └── text2pandas/
│       ├── domain/
│       ├── application/
│       ├── pipelines/
│       │   ├── ingest/
│       │   ├── a6/
│       │   ├── retrieval/
│       │   ├── answering/
│       │   └── submission/
│       ├── infrastructure/
│       │   ├── storage/
│       │   ├── indexing/
│       │   ├── execution/
│       │   └── models/
│       └── interfaces/
│           ├── cli/
│           └── api/
├── tests/
│   ├── unit/
│   │   ├── domain/
│   │   ├── a6/
│   │   ├── retrieval/
│   │   └── answering/
│   ├── integration/
│   │   ├── a6/
│   │   ├── retrieval/
│   │   ├── answering/
│   │   └── submission/
│   ├── contract/
│   ├── regression/
│   └── fixtures/
├── data/                              # runtime data; mặc định không commit
│   ├── README.md
│   ├── raw/
│   │   └── btc/
│   │       ├── financial_statements/<ticker>/<year>/...txt
│   │       ├── questions/questions.jsonl
│   │       ├── metadata/companies.csv
│   │       └── manifest.json
│   ├── processed/
│   │   └── a6/
│   │       └── <build_id>/
│   │           ├── manifest.json
│   │           ├── silver.db
│   │           ├── dataframe/
│   │           └── metadata/
│   ├── indexes/
│   │   └── retrieval/
│   │       └── <a6_build_id>/<index_id>/
│   │           ├── manifest.json
│   │           └── retrieval.db
│   └── curated/
│       ├── dev/
│       └── gold/
├── artifacts/                         # generated; không commit, trừ manifest nhỏ
│   ├── runs/
│   │   ├── a6/
│   │   ├── retrieval/
│   │   ├── answering/
│   │   └── evaluation/
│   ├── reports/
│   ├── submissions/
│   ├── packages/
│   └── handoffs/
├── provenance/                        # manifest/seal/checksum được commit
│   ├── raw/
│   ├── a6/
│   ├── retrieval/
│   └── releases/
├── tools/
│   ├── data/
│   ├── migrations/
│   ├── audits/
│   ├── evaluation/
│   └── release/
├── experiments/                       # không được import bởi production code
│   ├── retrieval/
│   └── answering/
├── ops/
│   ├── docker/
│   ├── environment/
│   └── scripts/
└── docs/
    ├── competition/
    ├── architecture/
    ├── operations/
    └── adr/
```

### 3.1 Tách logical root và physical root

Code không được hardcode đường dẫn máy hoặc tự suy ra mọi dữ liệu từ `Path.cwd()`.
Tạo một `ProjectPaths` duy nhất với:

- `repo_root`: source repository.
- `data_root`: mặc định `<repo_root>/data`, override bằng `T2P_DATA_ROOT` khi dữ liệu
  nằm trên volume khác.
- `artifact_root`: mặc định `<repo_root>/artifacts`, override bằng
  `T2P_ARTIFACT_ROOT`.
- `active_snapshot.yaml`: chọn raw snapshot, A6 build và retrieval index đang dùng.

Không dùng absolute symlink được commit vào Git. Không dùng `current/` mutable mà
không có manifest; lựa chọn active version phải nằm trong config có review.

## 4. Mapping từ cấu trúc cũ sang cấu trúc mới

| Nguồn hiện tại | Đích đề xuất | Hành động |
|---|---|---|
| `../data/external/vifinqa/financial_statements/` | `data/raw/btc/financial_statements/` | Move/copy có checksum; đặt read-only sau verify |
| `../data/external/vifinqa/questions/` | `data/raw/btc/questions/` | Giữ nguyên bytes và line count |
| `../data/external/vifinqa/code_stock.csv` | `data/raw/btc/metadata/companies.csv` | Ghi original path/name trong manifest |
| `../data/external/vifinqa/_codebase/` | `vendor/vifinqa-reference/` hoặc loại khỏi runtime | Tuyệt đối không để dưới corpus scan root |
| `../release_finala6/` | `data/processed/a6/b3e9684004679ffb/` | Canonical processed snapshot; verify theo manifest hiện có |
| `../retrieval/work.db` | `data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db` | Giai đoạn đầu chỉ rename/relocate, không rebuild |
| `../retrieval/PROVENANCE.json` | cùng retrieval snapshot `manifest.json` + `provenance/retrieval/` | Chuẩn hoá schema và giữ source DB SHA |
| `../retrieval/freeze/` | `configs/pipelines/retrieval-frozen-v1.yaml` + provenance | Config được commit; report không để lẫn index |
| `../retrieval/{evalkit,reaudit,audit,vplus}/` | `artifacts/runs/retrieval/<run_id>/` | Generated evaluation output |
| `../data/dev/` | `data/curated/dev/` hoặc `artifacts/runs/answering/` | Tách hand-authored labels khỏi generated records |
| `../data/gold/` | `data/curated/gold/` | Commit chỉ file nhỏ, có schema/provenance |
| `../data/bronze/` | `artifacts/runs/a6/<run_id>/bronze/` | Intermediate, tái tạo được |
| `../data/silver/` | `artifacts/legacy/` rồi loại sau audit | Không để tồn tại hai canonical A6 stores |
| `../data/submissions/` | `artifacts/submissions/` | Generated package |
| `../data/handoff/` | `artifacts/handoffs/` | Generated delivery packet |
| `evaluation/` | `data/curated/evaluation/` hoặc `artifacts/runs/evaluation/` | Phân loại theo input hay output |
| `identity/` | `provenance/` hoặc `artifacts/reports/audit/` | Manifest/seal vào provenance; patch/log vào artifacts |
| `env/` | `ops/environment/` | Tránh bị ignore như virtualenv |
| `docker/` | `ops/docker/` | Gom operational assets |
| `src/text2pandas.egg-info/` | không có đích | Xoá khỏi working tree sau khi xác nhận; tái sinh khi build |

## 5. Refactor source code

### 5.1 Một public package

Đích cuối chỉ có public namespace `text2pandas`:

- `data_pipeline.*` → `text2pandas.pipelines.a6.*`.
- `retrieval.*` → `text2pandas.pipelines.retrieval.*`.
- Answer pipeline hiện có → `text2pandas.pipelines.answering.*`.
- CLI và API chỉ gọi application use cases; không gọi thẳng storage/parser internals.

Không rename tất cả trong một commit. Trong một release chuyển tiếp, giữ module shim:

```python
# src/data_pipeline/cli.py — compatibility only
from text2pandas.pipelines.a6.cli import *
```

Xoá shim khi `rg` xác nhận không còn import cũ trong `src/`, `tests/`, `tools/` và
downstream automation.

### 5.2 Quy tắc dependency

```text
interfaces → application → domain
                    └────→ infrastructure (qua ports)

pipelines/a6 → domain + infrastructure
pipelines/retrieval → domain + A6 read model + infrastructure/indexing
pipelines/answering → retrieval contract + execution sandbox
pipelines/submission → validated answering result
```

- `domain` không import pandas, SQLite, filesystem hoặc CLI framework.
- Retrieval chỉ đọc A6 qua contract ổn định (`A6Store`), không biết layout nội bộ của
  release package.
- Answering nhận `RetrievalResult`; không truy vấn `work.db` bằng path hardcode.
- Production code không import từ `tools/` hoặc `experiments/`.

### 5.3 Giảm duplication của retrieval DB

`work.db` hiện là bản sao khoảng 3,9 GB của A6 DB cộng thêm index. Thực hiện hai bước:

1. Migration không đổi hành vi: giữ nguyên DB, chỉ version hoá và thêm manifest.
2. Sau khi parity đạt: chuyển thành sidecar `retrieval.db` chỉ chứa index/ranking
   structures và stable `table_uid`; mở A6 read-only hoặc `ATTACH` khi cần.

Mục tiêu là retrieval artifact nhỏ hơn, build nhanh hơn và không thể drift khỏi A6.

## 6. Chuẩn manifest và lineage

Mỗi layer phải có machine-readable manifest.

### Raw manifest

- `snapshot_id`, `source`, `received_at`.
- số công ty, số `.txt`, số câu hỏi.
- checksum tree và schema version.
- quy định immutable/read-only.

### A6 manifest

- `build_id`, `raw_snapshot_id`, `raw_tree_sha256`.
- source commit, config hash, schema version, policy versions.
- row/table/document counts, checksums, quality gates.
- lệnh build/rebuild và trạng thái deterministic check.

### Retrieval manifest

- `index_id`, `source_a6_build_id`, `source_a6_sha256`.
- retrieval code commit, config fingerprint, schema/index versions.
- index checksum, row counts, build command và evaluation summary reference.

### Run/submission manifest

- raw/A6/retrieval IDs đã dùng.
- code commit, configs, model identity và seed.
- output checksum, validation result và metric report references.

Invariant bắt buộc:

```text
retrieval.source_a6_build_id == active A6.build_id
answering.retrieval_index_id == active retrieval.index_id
submission.answer == execute(submission.pandas_query, submission.evidence)
```

## 7. Git policy

### Commit

- `src/`, `tests/`, `configs/`, `docs/`, `ops/`, schemas.
- Small deterministic fixtures.
- Curated labels/gold có ownership rõ và kích thước hợp lý.
- Manifest, checksum, provenance seal và frozen policy.

### Không commit

- Raw BTC corpus và third-party dataset payload.
- A6 SQLite/CSV/Parquet và unpacked release lớn.
- Retrieval DB/index.
- ZIP/TGZ, submissions, handoff bundles.
- Run outputs, reports tái tạo được, caches, virtualenv, `.egg-info`, `.DS_Store`.

Không dùng Git LFS để che một layout chưa rõ. Trước mắt dùng manifest + checksum +
materialization script. Khi cần đồng bộ nhiều máy, chọn DVC/object storage sau khi xác
định remote, retention và access policy.

## 8. Migration plan

### Phase 0 — Freeze baseline (0,5–1 ngày)

Deliverables:

- Inventory path, size, owner, tracked/ignored status.
- SHA-256/tree hash cho raw BTC, A6 và retrieval index.
- Baseline test/evaluation commands và kết quả.
- Tag/commit `pre-folder-refactor` sau initial commit được duyệt.

Gate:

- Không có file lớn bị stage.
- Raw count giữ `1.973` `.txt`, `100` mã, `1.012` câu hỏi.
- A6 build ID và retrieval source A6 ID khớp.

### Phase 1 — Repository foundation (1 ngày)

Deliverables:

- Tạo `docs/`, `ops/`, `provenance/`, `experiments/`, target data directories.
- Viết lại `.gitignore` theo allowlist cho manifest/README thay vì rule chồng chéo.
- Thêm `data/README.md` mô tả ownership và lifecycle.
- Tạo `ProjectPaths`, `active_snapshot.yaml`, `make paths-check`.

Gate:

- Mọi command chạy từ repo root.
- Không có absolute path máy dev trong source/config.
- `git status --ignored` phân loại đúng dữ liệu lớn và evidence nhỏ.

### Phase 2 — Relocate data không đổi bytes (1–2 ngày)

Deliverables:

- Chuyển raw BTC, A6 snapshot và retrieval index theo mapping ở mục 4.
- Tạo manifest chuẩn hoá, nhưng giữ manifest gốc để audit.
- Chuyển evaluation/report ra khỏi index directory.
- Giữ legacy path bằng resolver compatibility có warning trong một release; không
  dùng absolute symlink trong Git.

Gate:

- Checksum trước/sau giống nhau.
- A6 mở read-only được; retrieval smoke trả cùng ordered IDs cho fixture cố định.
- Không xoá nguồn cũ trước khi parity và backup được xác nhận.

### Phase 3 — Consolidate Python packages (3–5 ngày)

Deliverables:

- Chuyển `data_pipeline` và `retrieval` vào `text2pandas.pipelines` theo từng module.
- Tạo ports/contracts cho A6 store, retrieval index, execution sandbox.
- Giữ compatibility shims và deprecation warnings.
- Một CLI duy nhất, ví dụ `text2pandas data verify`, `text2pandas a6 build`,
  `text2pandas retrieval build`, `text2pandas evaluate`, `text2pandas submit`.

Gate:

- Test parity đạt trước/sau mỗi nhóm module.
- Không có circular dependency.
- Không có production import từ `tools/`.

### Phase 4 — Tools, tests và experiments (3–5 ngày)

Deliverables:

- Phân loại 238 tool files: production CLI, reusable library, migration, audit,
  experiment, obsolete.
- Reusable logic chuyển vào package; `tools/` chỉ còn thin entrypoint.
- Retrieval ablation/reaudit chuyển vào `experiments/` và `artifacts/runs/`.
- Tests tổ chức theo unit/integration/contract/regression và module ownership.
- Mỗi pipeline có fixture nhỏ chạy offline.

Gate:

- `pytest` không cần `sys.path` mutation.
- Test collection không phụ thuộc full corpus.
- Integration test fail rõ khi thiếu materialized dataset, không skip âm thầm.

### Phase 5 — Reproducibility, docs và CI (1–2 ngày)

Deliverables:

- Chuẩn hoá Make targets/CLI và cập nhật README theo command thực tế.
- Thêm `data verify`, `a6 rebuild-check`, `retrieval verify`, `submission validate`.
- CI chạy lint, unit, contract, fixture integration và `git diff --check`.
- Audit các tài liệu được README tham chiếu nhưng đang thiếu.
- Ghi ADR cho data layout, A6 SSOT, retrieval sidecar và artifact retention.

Gate:

- Fresh clone cài được và chạy unit/contract tests không cần corpus.
- Khi materialize đúng snapshot, pipeline xác minh được toàn bộ lineage.

### Phase 6 — Remove compatibility và legacy data (1 ngày)

Deliverables:

- Xoá shim/import cũ sau khi `rg` về 0.
- Archive hoặc xoá duplicate silver DB/output chỉ sau khi checksum + parity + backup
  được sign off.
- Tạo tag `folder-refactor-complete`.

Gate:

- Không còn path `release_finala6`, `artifacts/retrieval/work.db` hay
  `data/external/vifinqa` bị hardcode.
- Chỉ còn một canonical A6 snapshot được active config chọn.
- Working tree sạch và không có large binary trong Git history.

Ước lượng tổng: **10–16 engineer-days**, không bao gồm cải thiện model/retrieval
quality. Phần rủi ro cao nhất là phân loại `tools/`, đổi import namespace và chứng
minh output parity.

## 9. Quality gates bắt buộc

| Gate | Kiểm tra |
|---|---|
| G0 — Git safety | Không stage file lớn; `.gitignore` đúng; không nested Git dưới corpus |
| G1 — Raw integrity | 1.973 `.txt`, 100 mã, 1.012 câu hỏi; tree hash không đổi |
| G2 — A6 identity | `build_id`, corpus ID, schema/policy version và checksums hợp lệ |
| G3 — Retrieval identity | Index trỏ đúng A6 build/SHA; không tự chọn `latest` |
| G4 — Behavioral parity | Retrieval ordered IDs, answer và submission fixture không đổi |
| G5 — Reproducibility | Rebuild A/B deterministic hoặc có differential được giải thích |
| G6 — Architecture | Một public package; dependency direction đúng; không hardcode path |
| G7 — Delivery | Submission ZIP validate: một JSON, `data/` top-level, mọi CSV path tồn tại |

## 10. Definition of Done

- Một clone mới hiểu được project chỉ từ README và `make help`.
- Có đúng một source namespace public: `text2pandas`.
- Raw BTC, A6 và retrieval index có ownership, lifecycle và manifest riêng.
- Retrieval index luôn truy ngược được về A6 và raw snapshot cụ thể.
- Không có generated binary lớn trong Git history.
- Unit/contract tests chạy offline; integration/e2e chạy khi data snapshot được
  materialize.
- Không còn duplicated SSOT giữa `data/silver`, `release_finala6` và `work.db`.
- Mỗi submission truy ngược được code commit + config + raw/A6/retrieval IDs.
- Legacy folders chỉ bị xoá sau khi checksum, parity và rollback package đã được xác
  nhận.

## 11. Thứ tự commit đề xuất

```text
chore(repo): establish baseline and data inventory
docs(architecture): define raw-a6-retrieval lineage
refactor(paths): centralize project data and artifact roots
chore(data): relocate raw btc snapshot without byte changes
chore(data): version a6 and retrieval snapshots
refactor(a6): move data pipeline under text2pandas namespace
refactor(retrieval): move retrieval pipeline under text2pandas namespace
refactor(tools): separate production commands from experiments
test(layout): align tests with module ownership
docs(ops): document reproducible build and submission workflow
chore(cleanup): remove compatibility paths after parity sign-off
```

Mỗi commit phải độc lập, review được và có gate tương ứng; không gộp file move với
behavior change nếu có thể tránh.
