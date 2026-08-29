# PHASE 1.5 — INDEPENDENT SEMANTIC GOLD V2 PREPARATION REPORT

Ngày báo cáo: 2026-08-29

Repository: Text2Pandas / team VAR

Trạng thái tổng: **BLOCKED — OPEN FOR INDEPENDENT REVIEW**

## 1. Kết luận điều hành

WP0, WP1 và WP2 của
[measurement plan](PHASE_1_5_SEMANTIC_GOLD_MEASUREMENT_PLAN_2026-08-29.md)
đã được thực hiện đầy đủ. Annotation packet độc lập, prediction-blind đã được
tạo và kiểm chứng deterministic. Không có file thuộc production parser,
retrieval, selector, binder, planner, executor hoặc answer path bị thay đổi.

Luồng dừng đúng cổng WP3 vì chưa có reviewer A, reviewer B và adjudicator C là
ba người độc lập. Đây là blocker bắt buộc của plan, không phải task bị skip.
WP4–WP10 chưa được phép chạy vì làm tiếp khi chưa có human gold đã seal sẽ phá
tính độc lập của phép đo.

Không có semantic accuracy nào được suy diễn từ template trống. Không dùng mô
hình để giả lập người review và không xuất prediction Canonical V2 cho cohort
đã chọn trước khi seal.

## 2. Trạng thái theo work package

| Work package | Trạng thái | Kết quả |
|---|---|---|
| WP0 — Freeze baseline | **PASS** | Commit/snapshot/index/question source và protected surface đã được fingerprint |
| WP1 — Contract & guideline | **PASS** | Protocol, sampling contract, JSON Schema, metric vocabulary, operation vocabulary và guideline đã được tạo |
| WP2 — Prediction-blind sampling | **PASS** | 100 headline core + 20 diagnostic + 30 reserve; loại 221 QID contaminated |
| WP3 — Pilot calibration | **BLOCKED** | A/B/C đang `UNASSIGNED`; chưa được phép annotation |
| WP4 — Independent annotation | **NOT STARTED** | Chờ WP3 pass |
| WP5 — Agreement | **NOT STARTED** | Chờ hai annotation độc lập hoàn tất |
| WP6 — Adjudication & seal | **NOT STARTED** | Chờ agreement và adjudicator C |
| WP7 — Prediction adapter | **NOT STARTED** | Chỉ được chạy sau sealed gold |
| WP8 — Canonical V2 measurement | **NOT STARTED** | Chưa có sealed gold |
| WP9 — Failure taxonomy | **NOT STARTED** | Chưa có kết quả đo |
| WP10 — Boundary decision | **NOT STARTED** | Chưa có số liệu hợp lệ để ra quyết định |

## 3. Baseline và tính bất biến

| Thành phần | Identity |
|---|---|
| Target parser commit | `08907c362d440aeb51ac024aedccf75de98a2b0f` |
| Preparation source commit | `3941ce42252aa4a5d70a0c371e3cdf249afd0eaa` |
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Question records | 1,012 |
| Question SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| Protected-surface SHA-256 | `807439034d9e642f1c9911b76a2b2f31ba760e1d926b6fca3f410e831b123102` |

Protected surface được đối chiếu byte-for-byte với target parser commit. Kết quả
khớp hoàn toàn.

## 4. Kết quả sampling prediction-blind

Packet chuẩn:
`artifacts/runs/evaluation/semantic-gold-v2-phase1.5-packet-20260829-03`

Manifest SHA-256:
`1be7b639e135abb4fb4de87cd167f87e18821dbe8ede82df54f05bc354e7fa8a`

| Cohort | Số QID | Vai trò |
|---|---:|---|
| `HEADLINE_CORE` | 100 | Equal-probability; dùng cho headline decision thresholds |
| `DIAGNOSTIC_SUPPLEMENT` | 20 | Tăng coverage shape hiếm; báo riêng, không trộn headline |
| `PRESEALED_RESERVE` | 30 | Chỉ kích hoạt theo protocol; không thay ngầm QID unresolved |
| Active annotation | 120 | Hai template A/B và một template adjudication C |
| Contaminated excluded | 221 | Union của năm nguồn gold/dev/evaluation cũ |
| Eligible pool | 791 | Phần còn lại của corpus 1,012 câu |

Diagnostic quota đều đạt, không cần random top-up:

| Stratum | Selected / target | Available proxy |
|---|---:|---:|
| `NESTED_COMPOSED` | 3 / 3 | 58 |
| `ARG_SELECT_PROJECT` | 3 / 3 | 75 |
| `DIVIDE_EXPLICIT_RATIO` | 4 / 4 | 39 |
| `SUBTRACT_DIRECTIONAL` | 3 / 3 | 99 |
| `GROWTH_PERCENT_CHANGE` | 2 / 2 | 63 |
| `MULTI_ENTITY_DIRECTIONAL` | 2 / 2 | 60 |
| `COUNT` | 1 / 1 | 12 |
| `BASIS_SENSITIVE` | 1 / 1 | 259 |
| `UNIT_SCALE_SENSITIVE` | 1 / 1 | 435 |

Manifest xác nhận `selection_uses_predictions=false` và
`model_outputs_included=false`. Hai lần tạo packet độc lập `-03` và
`-04-determinism` giống nhau hoàn toàn theo `diff -qr`.

## 5. Contract và artifact đã tạo

### 5.1 Tracked source

- [`semantic_gold_v2.py`](../../src/text2pandas/application/usecases/semantic_gold_v2.py):
  validation, contamination union, deterministic core/diagnostic/reserve
  selection và protected-surface fingerprint.
- [`prepare_semantic_gold_v2.py`](../../tools/evaluation/prepare_semantic_gold_v2.py):
  immutable packet builder và manifest.
- [`semantic_gold_v2_protocol.yaml`](../../configs/evaluation/semantic_gold_v2_protocol.yaml):
  identity, reviewer, freeze và release contract.
- [`semantic_gold_v2_sampling.yaml`](../../configs/evaluation/semantic_gold_v2_sampling.yaml):
  cohort sizes, source exclusions và diagnostic quotas.
- [`semantic_gold_v2_schema.json`](../../configs/evaluation/semantic_gold_v2_schema.json):
  field-level status, spans, semantic frame, provenance và reviewer contract.
- [`semantic_metric_concepts_v1.yaml`](../../configs/evaluation/semantic_metric_concepts_v1.yaml):
  draft metric vocabulary cho calibration.
- [`semantic_operation_vocabulary_v1.yaml`](../../configs/evaluation/semantic_operation_vocabulary_v1.yaml):
  draft operation vocabulary cho calibration.
- [`semantic_gold_v2/README.md`](../../data/curated/gold/semantic_gold_v2/README.md):
  annotation guideline và quy tắc độc lập.
- [`test_semantic_gold_v2.py`](../../tests/unit/test_semantic_gold_v2.py) và
  [`test_semantic_gold_v2_sampling.py`](../../tests/unit/test_semantic_gold_v2_sampling.py):
  contract, negative governance và deterministic sampling tests.
- [`Makefile`](../../Makefile): target `semantic-gold-v2-prepare` yêu cầu explicit
  protocol và packet directory.

### 5.2 Packet asset hashes

| Asset | Records | SHA-256 |
|---|---:|---|
| `annotator_a.jsonl` | 120 | `c196f110f76419f02e77ab672d08556e2af0768e3e5fc1876e5dbb1e1ceb1ba5` |
| `annotator_b.jsonl` | 120 | `2313574c4186064815e98c0205ee74ceab086c0247980145b90a07c712561544` |
| `adjudication.jsonl` | 120 | `38d93843e65554b3b1e08d6a71af25a265b03358b60ce69e0321903323931449` |
| `selection_core.jsonl` | 100 | `fbf8bba6c59eba3ba0c684fd1e7090edd6c083f7d5a8b6218973e6eba0d53de5` |
| `selection_diagnostic.jsonl` | 20 | `13d757fc4017e195ccc1a6303a8c0ffc8e585fd9efc33471aa20950b0be0f6f6` |
| `selection_reserve.jsonl` | 30 | `17bb9df01215136f2c60b0bcacdfe2475927620937b2442b8bc4c12539776f1c` |
| `contamination_ledger.json` | — | `fa070992927a7a5eef3af8d96aeab69e029586b9b710808c503d6289871aafe0` |
| `coverage_matrix.json` | — | `2911bce490eaeffab9e5764aeed82c4d0f99a351e4b275539fb6b8323f211c7a` |
| `protected_surface.json` | — | `807439034d9e642f1c9911b76a2b2f31ba760e1d926b6fca3f410e831b123102` |
| `access_log.jsonl` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

`annotator_a.jsonl`, `annotator_b.jsonl` và `adjudication.jsonl` là template
trống, không chứa prediction hay nhãn do hệ thống tự điền.

## 6. Verification evidence

| Gate | Kết quả |
|---|---|
| Targeted semantic-gold unit tests | **7 passed** |
| Targeted Ruff | **PASS** |
| Targeted strict mypy | **PASS** |
| Full `make ci PY=/opt/anaconda3/bin/python` | **PASS** |
| Full pytest trong CI | **2,112 passed, 42 skipped, 29 deselected** |
| Full Ruff | **PASS** |
| Full mypy | **86 source files — PASS** |
| Docs link check | **65 Markdown files, 0 broken links** |
| `make snapshots-verify` | **PASS** |
| JSON Schema validation | **360/360 A/B/C templates valid** |
| Deterministic packet reproduction | **PASS; no diff** |
| `git diff --check` | **PASS** |

## 7. Mười output bắt buộc của Phase 1.5

| # | Output | Trạng thái hiện tại |
|---:|---|---|
| 1 | Files changed | **AVAILABLE**, liệt kê tại mục 5.1; implementation commit `3941ce4` |
| 2 | Gold dataset location | **NOT CREATED**; mới có review packet tại đường dẫn mục 4 |
| 3 | Gold size và status distribution | Active 120 + reserve 30; `RESOLVED/AMBIGUOUS/UNRESOLVED` **NOT ANNOTATED** |
| 4 | Inter-annotator agreement | **NOT MEASURED** |
| 5 | Sealed gold SHA-256 | **NOT CREATED** |
| 6 | Parser semantic metrics | **NOT MEASURED** |
| 7 | Failure taxonomy | **NOT MEASURED** |
| 8 | Component boundary attribution | **NOT MEASURED** |
| 9 | Phase decision | **NOT PERMITTED** trước sealed gold |
| 10 | Exact next task | Gán A/B/C độc lập và chạy pilot calibration 12–15 QID |

## 8. Blocker và điều kiện tiếp tục

Manifest đang ghi bốn blocker:

1. `INDEPENDENT_ANNOTATOR_A_UNASSIGNED`;
2. `INDEPENDENT_ANNOTATOR_B_UNASSIGNED`;
3. `DISTINCT_ADJUDICATOR_C_UNASSIGNED`;
4. `SEMANTIC_METRICS_NOT_MEASURED_UNTIL_GOLD_IS_SEALED`.

Để mở WP3, cần cung cấp danh tính ba người khác nhau:

- A và B annotate độc lập, không xem output của nhau và không xem prediction;
- C chỉ adjudicate disagreement sau khi A/B khóa bản nộp;
- pilot 12–15 QID phải hoàn tất trước khi freeze vocabulary/guideline;
- sau calibration mới chạy full annotation, agreement, adjudication và seal;
- chỉ sau sealed SHA mới xuất Canonical V2 predictions và đo metric.

Final report đúng nghĩa chỉ được tạo sau WP10 tại:
`docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<YYYY-MM-DD>.md`.

## 9. Quyết định hiện tại

**Không tuyên bố Phase 1.5 hoàn tất và không ra quyết định parser bottleneck.**

Kết quả hợp lệ của lượt này là một packet audit-ready, deterministic,
prediction-blind ở trạng thái `OPEN_FOR_INDEPENDENT_REVIEW`. Exact next action
là gán reviewer A, reviewer B và adjudicator C, sau đó chạy WP3 pilot calibration
theo guideline đã tạo.
