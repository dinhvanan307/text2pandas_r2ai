# P0 Metric Resolver + SelectorSpec — Implementation & Differential Report

**Ngày chốt:** 2026-08-29  
**Kết luận:** `IMPLEMENTED / SHADOW COMPLETE / PROMOTION BLOCKED`  
**Runtime mặc định:** `off`  
**Guarded submission:** không tạo

## 1. Executive summary

P0 đã được triển khai đúng chuỗi:

```text
MetricSpec/SelectorSpec
→ Metric Resolver fail-closed
→ MetricAwareSelector
→ bind → validate → rebind tối đa 3 candidates
→ Canonical V2 off/shadow/guarded
→ shadow differential đủ 1.012 QID
→ local independent-gold gate
```

Không mở rộng lên 40 metrics; chỉ giữ đúng 28 metrics đã review. Không đổi
embedding, reranker, validator, multi-entity, derived ranking, select-at-arg hay
complex formulas. Không tạo ontology thứ ba.

Kết quả engineering và replay đều đạt, nhưng promotion gate thất bại:

| Chỉ tiêu trên independent answer gold | Legacy | Guarded projection | Delta |
|---|---:|---:|---:|
| Correct / 31 | 14 | 12 | **-2** |
| Answer Accuracy | 45,16% | 38,71% | **-6,45 điểm %** |
| Wins / losses | — | **0 / 2** | **net -2** |

Hai regression là `Q272 total_assets` và `Q340 inventory`, đều là câu legacy
đang đúng nhưng selector mới abstain với `METRIC_CANDIDATE_EMPTY`.

Theo gate bắt buộc “không mất các 14 local answers hiện đang đúng”, quyết định
cuối là:

```text
KEEP_OFF
```

Không chạy full guarded/package, không tạo ZIP mới và không thay submission đã
seal. Đây là hành vi chủ đích theo directive: chỉ promotion sau khi differential
chứng minh có lợi.

## 2. Baseline 0.2787 đã freeze

Artifact người dùng cung cấp được lưu bất biến tại:

`artifacts/submissions/submission_p0_baseline_02787_20260829.zip`

| Thuộc tính | Giá trị |
|---|---:|
| Leaderboard Answer Accuracy | `0.2787` — user-reported official |
| ZIP SHA-256 | `179d2c10425c96d55304183e27c5326b5bd2072d8d02fe74e211d23df3a060ad` |
| `submission.json` SHA-256 | `c2c34a3eec0ac0aff0752621539fbe5ab220eb4325cf840ddc3194e2a6576153` |
| Records | 1.012 |
| Emitted query/evidence/answer | 604 / 604 / 604 |
| Strict validation | PASS — 0 error, 0 warning |
| Clean replay | PASS — 604/604, 0 error |

Provenance máy đọc:

`provenance/submissions/p0_answer_baseline_02787_20260829.json`

### Giới hạn provenance

ZIP không chứa generation commit và runtime flags đã tạo nó. HEAD lúc tiếp nhận
không thể được suy ngược thành generation commit. So với current default run:

| So sánh scorer-facing | Kết quả |
|---|---:|
| Exact records | 892/1.012 |
| Baseline emissions | 604 |
| Current shadow legacy emissions | 585 |
| Baseline-only emissions | 40 |
| Current-only emissions | 21 |
| Khác emission hoặc numeric answer | 66 |

Vì vậy đây là `NON_CAUSAL_PROVENANCE_COMPARISON_ONLY`, không được dùng để quy
toàn bộ khác biệt hiện tại cho P0. Trên cùng local gold 31 QID, ZIP đạt 17/31,
trong khi current legacy đạt 14/31; con số này củng cố rằng current checkout
không tái tạo chính xác baseline ZIP.

## 3. Implementation theo phase

### P0.0 — Baseline freeze

Commit: `e239565`

- seal exact ZIP và SHA-256;
- strict validate + clean replay;
- lưu provenance;
- giữ runtime behavior không đổi;
- xác nhận MODEL_GOLD vẫn dừng.

Gate: **PASS**, với generation commit/config của ZIP là `UNKNOWN`.

### P0.1 — MetricSpec và SelectorSpec

Commit: `9bf06d7`

- dùng `MetricDefinition` hiện có làm MetricSpec source of truth;
- giữ đúng 28 reviewed metrics và 36 aliases;
- thêm immutable `SelectorSpec` per operand;
- contract chứa metric ID, aliases, dimension, statement types, basis,
  period semantics, forbidden prefixes/contains, required context, metric codes,
  entity/period và ontology fingerprint;
- loader fail-closed cho alias/dimension/period contract không hợp lệ;
- không tạo ontology thứ ba.

Registry gate:

| Check | Kết quả |
|---|---:|
| Reviewed metrics | 28 |
| Aliases | 36 |
| Alias collisions | 0 |
| Unknown dimensions | 0 |
| Missing period semantics | 0 |
| Ontology fingerprint | `9cca72a35c6f45b25714ce8571f75832d2ee4ff898e0b2f867dfa872cf794e2c` |

Gate: **PASS**.

### P0.2 — Metric Resolver fail-closed

Commit: `f7ebde5`

Đã triển khai:

1. exact/normalized reviewed alias;
2. longest-span semantics;
3. ambiguity detection, không phá tie bằng metric ID;
4. A6 source-label fallback chỉ trong 28 reviewed metrics;
5. `RESOLVED / AMBIGUOUS / UNRESOLVED` contract;
6. operation eligibility;
7. ontology/resolver fingerprints và trace;
8. fail-closed khi confidence/uniqueness không đạt.

Đo coverage trên đủ 1.012 câu:

| Resolver status | Số QID |
|---|---:|
| `RESOLVED` | 257 |
| `AMBIGUOUS` | 369 |
| `UNRESOLVED` | 386 |
| Operation-eligible trước Canonical guarded scope | 170 |

Resolver fingerprint:
`84e0df779e8754c674ec3666a3a28bf09aba55570f31ed27f4ef4c567a174165`.

Đây là **coverage/status**, không phải metric correctness. Independent gold hiện
không có canonical `metric_id`/mention spans, nên Metric Concept Exact và
Mention-span F1 được ghi đúng là `NOT_MEASURED`, không suy diễn từ số resolved.

Gate engineering: **PASS**. Gate accuracy: **NOT_MEASURED**.

### P0.3 — MetricAwareSelector và rebind

Commit: `fbf6805`

Hard gates được đặt trước table prior:

- entity;
- period;
- dimension;
- statement type;
- explicit basis;
- point-in-time/flow semantics;
- forbidden parent/child labels;
- required context;
- alias/metric-code evidence.

Ranking ổn định dùng semantic score trước retrieval table prior. Candidate tie
khác value/basis/period semantics trả `AMBIGUOUS_BINDING`, không chọn theo UID.

Bind flow:

```text
candidate #1 → bind/render/policy/validate
             → fail hợp lệ thì candidate #2
             → fail hợp lệ thì candidate #3
             → fail closed
```

Không rebind divisor bằng 0 và không vượt quá 3 candidates. Metamorphic tests
đã chứng minh đảo candidate order không đổi kết quả; unit test chứng minh
render failure có thể được cứu bởi candidate thứ hai.

Gate: **PASS**.

### P0.4 — Canonical V2 guarded modes

Commit: `097ab24`

Ba mode được tích hợp:

| Mode | Hành vi |
|---|---|
| `off` | Default; không resolve/select P0, behavior cũ giữ nguyên |
| `shadow` | Chạy P0, ghi trace/differential, không thay output |
| `guarded` | Dùng candidate P0 cho eligible safe routes |

`off` không ghi `metric_p0` trace. `shadow` và `off` cho cùng output khi bỏ
trace shadow. Multi-entity, divide, select-at-arg, derived ranking và complex
formula không được P0 chọn.

Gate: **PASS**.

### P0.5 — Full shadow 1.012 và differential

Run:

`artifacts/runs/answer/p0-shadow-full-1012-20260829-01`

Records SHA-256:
`4179da8814bcac1c03a4ab7a1755a55cadbe8a78c01082591d69717ebf91907e`.

Command:

```bash
PYTHONPATH=src python -m text2pandas.interface.cli.main -v run \
  --run-id p0-shadow-full-1012-20260829-01 \
  --no-package \
  --metric-selector-mode shadow
```

Run summary:

| Chỉ tiêu | Kết quả |
|---|---:|
| Questions | 1.012 |
| Entity/year/retrieved | 1.011 / 1.011 / 1.011 |
| Legacy answered/abstained | 585 / 427 |
| Canonical P0 eligible | 126 |
| Runtime | 527,98 giây |

Differential:

| Class | QID |
|---|---:|
| `NOT_ELIGIBLE` | 886 |
| `BOTH_SAME_ANSWER_SAME_EVIDENCE` | 30 |
| `BOTH_SAME_ANSWER_DIFFERENT_EVIDENCE` | 14 |
| `BOTH_DIFFERENT_ANSWER` | 14 |
| `LEGACY_ONLY` | 52 |
| `P0_ONLY` | 2 |
| `BOTH_ABSTAIN` | 14 |

P0 có 60 candidate `OK`. Shadow mode chỉ materialize evidence được chọn cho
legacy output:

| Candidate replay check | Kết quả |
|---|---:|
| Candidate `OK` | 60 |
| Có evidence đã materialize trong shadow | 31 |
| Replay match trên phần đã materialize | 31/31 |
| Execution failures trên phần đã materialize | 0 |
| Candidate-only evidence chưa materialize | 29 |

29 candidate còn lại là `NOT_MATERIALIZED_BY_SHADOW`, không phải replay error.
Do promotion đã fail trên correctness, không chạy full guarded chỉ để
materialize chúng.

### P0.6 — Independent correctness gate và promotion

Evaluator commits: `25b88ec`, `959d802`.

Tool:

`tools/evaluation/evaluate_metric_selector_p0.py`

Inputs:

- `data/curated/dev-legacy/answer_gold/answer_gold_wave1_final.jsonl`;
- 31 records có `trang_thai=OK`;
- gold SHA-256:
  `e14248e8480afe783444eba70e824ad23184c78c4dee962a1f663d358f2ca3e2`;
- không đọc MODEL_GOLD.

Kết quả answer:

| Chỉ tiêu | Legacy | Guarded | Delta |
|---|---:|---:|---:|
| Correct | 14/31 | 12/31 | -2 |
| Accuracy | 45,16% | 38,71% | -6,45 điểm % |
| Wins | — | 0 | 0 |
| Losses | — | 2 | +2 regression |

Gold-cell exact strict được định nghĩa là khớp đồng thời table reference, row
leaf và year cho tất cả gold cells. Kết quả là 3/31 ở cả legacy và guarded,
0 win/0 loss. Coverage exact thấp vì một số answer đúng đến từ bảng comparative
hoặc duplicate row khác gold reference; không được diễn giải 3/31 thành official
cell accuracy của toàn corpus.

#### Hai protected losses

| QID | Metric | Legacy | P0 | Bằng chứng blocker |
|---:|---|---:|---|---|
| 272 | `total_assets` | `477839594` đúng | abstain | Correct row `TỔNG TÀI SẢN CÓ` bị A6 gắn `statement_type=note`; SelectorSpec chỉ cho `balance_sheet`, nên hard gate loại |
| 340 | `inventory` | `36.320271261` đúng | abstain | Correct row `Hàng tồn kho`, column `Số cuối năm` bị gắn `period_role=current`; question yêu cầu closing, nên period hard gate loại |

Đây không phải lỗi resolver: cả hai metric đều resolve đúng với confidence 0,99.
Blocker nằm ở xung đột giữa hard SelectorSpec và metadata A6 trên candidate đúng.

Sửa blocker cần một phase calibration riêng, có gold cho selector và quy tắc
source-backed xử lý metadata defect. Không được tự hạ hard validator hoặc bỏ
statement/period gate chỉ để tăng coverage.

Promotion rule:

```text
answer_wins > answer_losses
AND protected_correct_losses == 0
```

Kết quả: **FAIL → KEEP_OFF**.

## 4. Verification gates

| Gate | Kết quả |
|---|---|
| Registry validation | PASS |
| Unit/integration additions | PASS |
| `make test-offline` | **2.201 passed, 42 skipped, 30 deselected** |
| Targeted strict mypy cho evaluator | PASS |
| Ruff cho evaluator | PASS |
| `git diff --check` | PASS |
| `make snapshots-verify` | PASS toàn bộ Raw/A6/Retrieval |
| Candidate replay trên shadow-materialized evidence | 31/31 PASS |
| Independent answer gate | **FAIL: 0 win / 2 loss** |
| Full guarded ZIP validation/replay/determinism | `NOT_RUN_BY_DESIGN` |

Không chạy full guarded ZIP là kết quả đúng của promotion gate, không phải task
bị skip: directive yêu cầu chỉ bật behavior mới sau khi differential chứng minh
có lợi.

## 5. MODEL_GOLD vẫn được freeze

Không generator/model nào được gọi trong P0.

| Thuộc tính | Trước P0 | Sau P0 |
|---|---:|---:|
| Completed records | 71 | 71 |
| RESOLVED / AMBIGUOUS / UNRESOLVED | 51 / 0 / 20 | 51 / 0 / 20 |
| Raw attempt files | 203 | 203 |
| `PARTIAL_CHECKPOINT.json` SHA-256 | `2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636` | không đổi |
| `generation_state.json` SHA-256 | `b306c8fc96a818ce8da7162afac14976636224572b33f074ebd506df942f3a8d` | không đổi |

Candidate dở Q539 vẫn raw-only, không có completed record và không được promote.

## 6. Artifacts

| Artifact | Path |
|---|---|
| Frozen baseline ZIP | `artifacts/submissions/submission_p0_baseline_02787_20260829.zip` |
| Baseline provenance | `provenance/submissions/p0_answer_baseline_02787_20260829.json` |
| Full shadow manifest | `artifacts/runs/answer/p0-shadow-full-1012-20260829-01/manifest.json` |
| Full shadow records | `artifacts/runs/answer/p0-shadow-full-1012-20260829-01/records.jsonl` |
| Resolver coverage summary | `artifacts/reports/p0-metric-answer-20260829/resolver_full_corpus_summary.json` |
| Final differential summary | `artifacts/reports/p0-metric-answer-20260829/differential_summary_v3.json` |
| Per-QID independent-gold cases | `artifacts/reports/p0-metric-answer-20260829/differential_cases_v3.jsonl` |
| Legacy local answer eval | `artifacts/reports/p0-metric-answer-20260829/legacy_local_answer_eval.json` |

Các artifact dưới `artifacts/` là generated/ignored; report, provenance và code
evaluator được commit.

## 7. Commit ledger

| Phase | Commit | Nội dung |
|---|---|---|
| P0.0 | `e239565` | Freeze baseline 0.2787 |
| P0.1 | `9bf06d7` | MetricSpec/SelectorSpec contracts |
| P0.2 | `f7ebde5` | Fail-closed reviewed metric resolver |
| P0.3 | `fbf6805` | Metric selector + bind/validate/rebind max 3 |
| P0.4 | `097ab24` | Canonical off/shadow/guarded modes |
| P0.5 | `25b88ec` | Reproducible shadow evaluator |
| P0.5 fix | `959d802` | Normalize scorer-facing baseline comparison |

## 8. Quyết định cuối

```text
Metric correctness: implementation complete; independent metric-label accuracy NOT_MEASURED
Cell correctness: no measured improvement on 31-QID strict gold-cell check
Answer correctness: regression 0 wins / 2 losses
Promotion: BLOCKED
Default runtime: OFF
New submission ZIP: NOT CREATED
Baseline 0.2787 ZIP: PRESERVED
```

P0 code được giữ ở guarded/shadow mode để tiếp tục calibration có kiểm soát,
nhưng không được dùng cho submission cho đến khi sửa hai metadata-conflict
blocker, đo lại trên independent selector gold và đạt zero protected losses.
