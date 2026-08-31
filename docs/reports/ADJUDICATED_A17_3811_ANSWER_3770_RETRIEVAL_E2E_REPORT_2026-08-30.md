# ADJUDICATED A17 × 3811 ANSWER × 3770 RETRIEVAL — E2E REPORT

**Ngày:** 2026-08-30

**Trạng thái:** `READY_NOT_SUBMITTED`

**Release decision:** `BUILD_PASS`
**Official metrics:** `NOT_MEASURED_UNTIL_UPLOAD`

## 1. Kết quả cuối

Đã thực hiện end-to-end candidate đầu tiên theo chiến lược:

```text
Answer layer 3811
+ 4 source-backed corrections
+ 13 source-backed fills

Retrieval layer 3770
= ADJUDICATED-A17 × 3811 × 3770
```

File sẵn sàng nộp:

```text
artifacts/submissions/
submission_adjudicated-a17-3811-answer-3770-retrieval-20260830-01.zip
```

SHA-256:

```text
f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628
```

Kích thước: `1,129,545 bytes`.

Candidate đạt toàn bộ release gate:

| Gate | Kết quả |
|---|---:|
| Records | 1,012/1,012 |
| Emitted answers | 638 |
| Baseline abstentions còn lại | 374 |
| Corrections | 4 |
| Fills | 13 |
| Answer fields ngoài allowlist giữ nguyên 3811 | 995/995 |
| Retrieval fields giống 3770 | 1,012/1,012 |
| Questions giống source | 1,012/1,012 |
| Strict validation | 0 error, 0 warning |
| Clean replay | 638/638 |
| Replay errors | 0 |
| Maximum tables | 10 |
| Missing/orphan CSV | 0/0 |
| Duplicate ID/table/doc | 0/0/0 |
| A/B byte-identical | PASS |

Không upload trong task này. Chưa có submission ID hoặc receipt mới.

## 2. Phạm vi và non-goals

Đã thực hiện:

1. khóa SHA của 3811 answer ZIP, 3770 retrieval ZIP và Semantic V3 source ZIP;
2. băm trực tiếp A6 `silver.db` và retrieval DB;
3. tạo allowlist A17 checksum-bound;
4. implement deterministic composer fail-closed;
5. materialize evidence từ observation UID của active A6;
6. build hai lần độc lập;
7. strict validation, clean replay và exact ownership diff;
8. chạy CI, integration, snapshot verification và full acceptance suite;
9. niêm phong release ZIP, provenance và submission ledger.

Không thực hiện:

- không bật P0 runtime;
- không dùng MODEL_GOLD;
- không chạy generator;
- không promote toàn bộ Semantic V3;
- không thay đổi retrieval ranking/config;
- không chạy lại answer generation;
- không sửa 995 QID ngoài allowlist;
- không dùng external financial data;
- không upload hoặc tuyên bố official uplift.

## 3. Identity đã khóa

### 3.1 Active data lineage

| Layer | Identity | Payload SHA-256 |
|---|---|---|
| Raw | `ca033190f2e9e99f` | snapshot manifest verified |
| A6 | `c6887fb633374fad` | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Retrieval | `872ccb0dda9a2bb6` | `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` |

`make snapshots-verify` đạt PASS trên:

- 1,973 financial-statement documents;
- 1,012 questions;
- 100 tickers;
- 146,246 A6 table cards;
- retrieval DB size `4,239,663,104` bytes;
- required runtime schema và indexes.

### 3.2 Submission inputs

| Owner | Submission | ZIP | SHA-256 |
|---|---:|---|---|
| Answer | 3811 | `submission_baseline-union-retrieval-overlay-20260830-01.zip` | `535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933` |
| Retrieval | 3770 | `submission_actual-table-retrieval-safe-3966500-20260829-01.zip` | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| V3 source, allowlist only | — | `package-stripped-1.zip` | `3e068bc697ac9d34512f16d520af5bf4d51a6e0dc3137c503a25f9acfacb54f0` |

Official score của 3811 và 3770 vẫn là user-reported trong workspace; repo chưa
có receipt chính thức liên kết mọi submission ID lịch sử với exact ZIP SHA.
Candidate mới đã được thêm vào ledger ở trạng thái `READY_NOT_SUBMITTED`, không
được giả lập thành official submission.

## 4. Allowlist A17

Manifest:

```text
configs/evaluation/adjudicated_answer_patch_a17_v1.json
```

SHA-256:

```text
bb60f27b800e7464eb0cfd9d1a8039c83e228d49b60b1af49c78d0c11ad9b388
```

Manifest khóa:

- question SHA cho từng QID;
- decision `CORRECT` hoặc `FILL`;
- expected answer;
- source kind;
- V3 record SHA hoặc exact A6 observation UIDs;
- manual formula khi cần;
- P0/MODEL_GOLD/V3-promotion đều `false`;
- expected counts `4 + 13 = 17`;
- output emitted count `638`.

### 4.1 Bốn source-backed corrections

| QID | 3811 | A17 | Evidence |
|---:|---:|---:|---|
| 40 | 5,803,007 | **4,642,334** | VIB 2020, exact `Lợi nhuận sau thuế` |
| 118 | -63,322,055 | **2,688,909** | VCB 31/12/2015, exact `Dự phòng chung` |
| 291 | 1,792,876,703,000 | **1,792,876,703** | HAG 2023, remove erroneous ×1,000 |
| 905 | 493.327606619749 | **118.08004899999997** | Sum VIC financial income for 2020/2021/2023/2025 |

Manual source records được rematerialize từ bảy exact observation UIDs trong
active A6. Tool xác nhận table UID, document, locator, row path, column path và
decimal value trước khi cho phép build.

### 4.2 Mười ba source-backed fills

| QID | Answer |
|---:|---:|
| 62 | 428,450,055 |
| 74 | 9,271 |
| 474 | 1,406.490201935 |
| 481 | 1,307.936213643 |
| 513 | 9.497171212 |
| 521 | 500.688616629 |
| 541 | 1.307936213643 |
| 548 | 1.406490201935 |
| 555 | 1.307936213643 |
| 577 | 1.307936213643 |
| 816 | 14.383448 |
| 834 | 135.129055328395 |
| 903 | 0.02130538863 |

Mỗi V3 record phải đồng thời đạt:

1. exact question SHA;
2. exact canonical record SHA;
3. expected answer equality;
4. emitted query/evidence đầy đủ;
5. source CSV có đúng `observation_uid,value`;
6. V3 value bằng active A6 decimal value;
7. clean final replay.

Chỉ 13 record được dùng. Toàn bộ các V3 record khác không đi vào candidate.

### 4.3 QID bị loại

| QID | Lý do loại |
|---:|---|
| 452 | Thiếu current-ratio filter |
| 460 | Thiếu median grouping và division |
| 546 | Predicate current ratio chưa được chứng minh |
| 601 | Metric mismatch |
| 647 | Sign/magnitude ambiguity |
| 808 | Signed/absolute ambiguity |
| 883 | Maturity columns không nhất quán |
| 956 | Bỏ qua regional condition |
| 967 | Max trên negative provision chọn sai magnitude |

## 5. Implementation

### 5.1 Files

| File | Vai trò |
|---|---|
| `configs/evaluation/adjudicated_answer_patch_a17_v1.json` | checksum-bound allowlist và policy |
| `tools/submission/build_adjudicated_factorized_candidate.py` | deterministic fail-closed composer |
| `tests/unit/test_adjudicated_factorized_candidate.py` | ownership, source-binding và evidence tests |
| `configs/evaluation/submission_ledger_v1.json` | local release identity |
| `provenance/submissions/adjudicated_a17_3811_answer_3770_retrieval_20260830.json` | immutable release seal |

Source implementation commit:

```text
00f23494d1376d63e829073312fc3cabb0c8d342
feat(submission): build adjudicated A17 candidate
```

### 5.2 Evidence namespace

Patch evidence không dùng trực tiếp tên `data/<table_uid>.csv`, vì tên đó có
thể trùng với CSV của 3811 nhưng khác schema hoặc subset.

Output path được tạo deterministically:

```text
data/a17_<table_uid>_<observation-set-digest>.csv
```

Kết quả:

- 1,063 evidence CSV được giữ từ 3811;
- 42 namespaced A17 CSV được materialize;
- tổng 1,105 referenced CSV;
- 0 collision;
- 0 missing;
- 0 orphan.

## 6. Full build và determinism

### Run A

```text
artifacts/runs/submission/
adjudicated-a17-3811x3770-20260830-a2/
```

### Run B

```text
artifacts/runs/submission/
adjudicated-a17-3811x3770-20260830-b/
```

| Run | ZIP SHA-256 | submission.json SHA-256 | Gate |
|---|---|---|---|
| A2 | `f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628` | `859d732d500d795a875c59e5a72de36f73444b2fdbac00a3e33d8f6a512ae62c` | PASS |
| B | `f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628` | `859d732d500d795a875c59e5a72de36f73444b2fdbac00a3e33d8f6a512ae62c` | PASS |

`cmp` trên hai ZIP: PASS.

Lần gọi đầu tiên với run suffix `a` dừng trước khi tạo artifact vì script-mode
import chưa tìm thấy namespace `tools`. Import path được sửa và unit test chạy
lại; theo immutable-run rule, full build sử dụng run ID mới `a2`, không tái sử
dụng một run ID đã thất bại.

## 7. Validation và replay

Final release được kiểm lại độc lập sau khi copy vào `artifacts/submissions`:

```text
strict validation:
  records  = 1,012
  errors   = 0
  warnings = 0

clean replay:
  total       = 1,012
  executed    = 638
  matched     = 638
  no_evidence = 374
  error       = 0
```

Corpus root canonical:

```text
data/raw/btc/financial_statements
```

## 8. Test và environment gates

### Environment

`make dp-env-check`:

| Field | Value |
|---|---|
| Python | 3.11.15 |
| SQLite | 3.53.2 |
| pandas | 2.3.3 |
| pyarrow | 25.0.0 |
| lock matches installed | true |
| source tree dirty | false |
| untracked source paths | none |
| disk free | 60.0 GB |
| result | PASS |

Checkout chính không còn `.venv`; acceptance sử dụng hash-locked Python 3.11
environment của release worktree. Environment check xác nhận lockfile, installed
packages, imports, config và source commit đều khớp.

### CI và tests

| Gate | Kết quả |
|---|---:|
| Ruff | PASS |
| Strict mypy production packages | 92 files, 0 issue |
| Markdown links | 90 files, 0 broken |
| Offline CI | 2,223 passed, 42 skipped |
| Materialized integration | 23 passed |
| A17 targeted unit tests | 6 passed |
| Full `dp-test` | **2,246 passed, 42 skipped, 0 failed** |
| Missing required suites | 0 |
| Dependency-related skips | 0 |

Full machine-readable report:

```text
artifacts/reports/adjudicated_a17_acceptance_20260830_01/test_report.json
```

SHA-256:

```text
d6b1fb1a4a64664c6ee64f3ac9c5c59368ebb42978107d4917248ae6cbbf5fca
```

## 9. Score interpretation

User-reported score của submission 3811:

```text
Answer/Execution Accuracy = 0.2826
```

Nếu cả 17 A17 changes là official wins và không có hidden scorer interaction:

```text
286 + 17 = 303 correct
303 / 1,012 ≈ 0.2994
```

Đây chỉ là upside estimate. Repo không có official per-QID gold để đo candidate
này trước upload. Validation, replay, source grounding và determinism chứng minh
tính hợp lệ/reproducible, không chứng minh official Answer Accuracy.

Retrieval fields giống 3770 tuyệt đối, nhưng khả năng khôi phục official Tables
F2/Docs F2 vẫn là hypothesis cho đến khi leaderboard trả score của exact ZIP SHA.

## 10. Upload checklist

Trước upload:

```text
shasum -a 256 \
  artifacts/submissions/submission_adjudicated-a17-3811-answer-3770-retrieval-20260830-01.zip
```

Expected:

```text
f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628
```

Sau upload phải ghi ngay:

1. submission ID;
2. submitted timestamp UTC;
3. exact ZIP SHA;
4. screenshot/receipt path;
5. toàn bộ leaderboard metrics;
6. mapping vào `configs/evaluation/submission_ledger_v1.json`;
7. so sánh riêng Answer/Execution và Retrieval với 3811/3770.

Không được upload một ZIP khác cùng tên hoặc thay bytes sau khi đã ghi receipt.

## 11. Quyết định cuối

```text
BUILD:       PASS
VALIDATION:  PASS
REPLAY:      PASS
DETERMINISM: PASS
PROVENANCE:  PASS
UPLOAD:      NOT PERFORMED
OFFICIAL:    NOT MEASURED
```

Candidate này là artifact được đề xuất cho lượt nộp đầu tiên trong bốn lượt còn
lại, vì nó kết hợp retrieval owner tốt nhất đã biết với một answer patch nhỏ,
allowlisted, source-backed và có rollback rõ ràng.
