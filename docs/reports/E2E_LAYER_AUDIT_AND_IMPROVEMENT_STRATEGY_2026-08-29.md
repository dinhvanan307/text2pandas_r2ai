# E2E Layer Audit and Improvement Strategy — 2026-08-29

## 1. Executive decision

Audit end-to-end đã hoàn tất trên source commit `aadc8f8d2d0c302753396abee2847aa60ef7b71e`, không sửa production code, không đổi threshold, không resume model-gold generation và không promote Semantic V3.

Hai full-corpus run mới đều hoàn thành đủ 1.012 câu và qua package validation:

| Runtime | Emitted | Abstained | Validation | Clean replay | Local Answer / Execution Accuracy |
|---|---:|---:|---:|---:|---:|
| Canonical V2 | 585/1.012 | 427/1.012 | 0 lỗi, 0 cảnh báo | 585/585 | 14/31 = 45,16% |
| Semantic V3 shadow | 362/1.012 | 650/1.012 | 0 lỗi, 0 cảnh báo | 362/362 | 9/31 = 29,03% |

Các con số emitted/replay ở trên là coverage và consistency, không phải official accuracy. Organiser-held Answer Accuracy và Execution Accuracy vẫn là `NOT_MEASURED`.

Ba kết luận hành động có bằng chứng mạnh nhất là:

1. Canonical parser không phát metric phrase/concept tại public pre-bind boundary: metric concept exact và metric F1 đều 0 trên 43 provisional headline records.
2. Multi-entity route là blocker coverage lớn nhất của V2: 177/1.012 abstentions; local answer slice có 12 câu operation `multi` và 0/12 đúng.
3. Candidate generation không phải bottleneck trên manual retrieval gold: S1 hit 95/95; 9 lỗi còn lại là top-10 rank misses, tập trung 6/29 ở `screen` mode.

Không thể tính một overall E2E accuracy: 43 semantic-headline QIDs không giao với 95 retrieval-gold hoặc 31 answer-gold QIDs; evidence/binding gold có 0 usable records.

## 2. Frozen baseline

| Identity | Giá trị |
|---|---|
| Source commit | `aadc8f8d2d0c302753396abee2847aa60ef7b71e` |
| Gold tool commit | `b08643892d589817b42420480058cf86c92afe71` |
| Git dirty trước audit | `false` |
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Canonical V2 run | `canonical-v2-e2e-audit-aadc8f8-20260829-01` |
| Semantic V3 run | `semantic-v3-e2e-audit-aadc8f8-20260829-01` |
| Retrieval evalkit config | `938554ad1ae9e304` |
| Audit run | `e2e-layer-audit-aadc8f8-20260829-01` |
| Runtime | Python 3.13.9, `/opt/anaconda3/bin/python` |

Không có local hash-locked `.venv`; đây là reproducibility limitation. Tuy nhiên source identity, snapshot identities, config fingerprints và mọi output digest đều được ghi trong audit manifest.

## 3. Checkpoint integrity

Model semantic checkpoint chỉ được đọc, không được resume hoặc canonicalize/seal.

| Check | Trước audit | Sau audit | Kết quả |
|---|---|---|---|
| `PARTIAL_CHECKPOINT.json` SHA-256 | `2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636` | giống trước | PASS |
| `generation_state.json` SHA-256 | `b306c8fc96a818ce8da7162afac14976636224572b33f074ebd506df942f3a8d` | giống trước | PASS |
| Completed-record aggregate | `e6cb4bdc1e011ef45cd04abab249118d18d9f94ce8d43e93b63e10d215ee0af2` | giống trước | PASS |
| Raw-attempt aggregate | `88e8037c329264178ac61a2db098a998131ee8708057e8180ddfea1a05c9539d` | giống trước | PASS |
| Completed files | 71 | 71 | PASS |
| Raw-attempt files | 203 | 203 | PASS |
| `records/0539.json` | không tồn tại | không tồn tại | PASS |

Checkpoint vẫn là `PARTIAL_CHECKPOINT / NOT_SEALED`:

- completed coverage: 71/150;
- semantic usable: 51/150;
- provisional headline usable: 43/100;
- diagnostic usable: 2/20;
- reserve observed: 6/30;
- generation failures: 11 headline, 5 diagnostic, 4 reserve;
- QID 539: raw attempts only, bị loại hoàn toàn khỏi evaluation.

Checkpoint hoàn thành theo thứ tự QID nên có prefix bias. Không suy rộng 43 headline records sang 100 headline records hoặc corpus 1.012 câu.

## 4. Foundational gates

| Gate | Kết quả | Evidence |
|---|---|---|
| `make paths-check` | PASS | Repository/data/artifact roots và active snapshot đúng |
| `make snapshots-verify` | PASS | Raw, A6, retrieval identities/counts/indexes đều khớp |
| `make ci` | PASS | Ruff PASS; mypy 88 files, 0 issues; 83 Markdown files, 0 broken links; 2.174 passed, 42 approved skips, 29 deselected |
| `make test-integration` | PASS | 22 passed, 2.223 deselected |
| `make semantic-coverage` | PASS | 684/1.012 eligible, 328 named gaps |
| Pre-audit `git diff --check` | PASS | Không có tracked diff |

Semantic route coverage 67,59% không được gọi là parser accuracy.

## 5. Fresh Canonical V2 E2E

Canonical V2 chạy với production defaults, không experimental flag:

| Metric | Kết quả |
|---|---:|
| Total questions | 1.012 |
| Entity/year/retrieval coverage | 1.011/1.012 |
| Emitted answers | 585/1.012 = 57,81% |
| Fail-closed abstentions | 427/1.012 = 42,19% |
| Total runtime | 473,82 s |
| Mean runtime dẫn xuất | 0,4682 s/câu |
| Median / p95 per-QID | `NOT_MEASURED` — runtime không ghi per-QID timing |
| Validator errors / warnings | 0 / 0 |
| Clean replay | 585 executed, 585 matched, 0 error |
| ZIP SHA-256 | `82b42980cb82754885c17852c5ce8029d1eb22becfba85cb81e97fbd4e7edfe4` |

Top abstention families:

| Family | QIDs |
|---|---:|
| `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` | 177 |
| `ROUTE:EXTREMUM_SELECT_AT_ARG_REQUIRES_TWO_METRICS` | 32 |
| `RENDER:UNIT_CONTRACT_ABSTAIN:value:DIMENSION_MISMATCH` | 29 |
| `DIVIDE_REQUIRES_REVIEWED_FORMULA` | 27 |
| `POLICY:CROSS_BASIS_OPERANDS` | 20 |
| `ROUTE:FORMULA_OUTER_OPERATION_NOT_SUPPORTED:EXTREMUM` | 19 |
| `POLICY:CROSS_PERIOD_METRIC_DRIFT` | 18 |
| `POLICY:ENTITY_DIFFERENCE_METRIC_DRIFT` | 17 |

So với acceptance report lịch sử 561 emitted, fresh code hiện emit 585, tăng 24 câu coverage. Đây không chứng minh tăng accuracy hoặc leaderboard score.

## 6. Fresh Semantic V3 shadow E2E

V3 chạy trên cùng corpus, snapshot, A6, retrieval index và dùng fresh V2 run làm baseline.

| Metric | Kết quả |
|---|---:|
| Total | 1.012 |
| V3 OK | 362 |
| V3 abstain | 650 |
| Runtime | 66,282 s |
| Mean runtime dẫn xuất | 0,06550 s/câu |
| Median / p95 per-QID | `NOT_MEASURED` |
| Both V2/V3 OK and equal | 217 |
| Both OK but different | 100 |
| V2-only OK | 268 |
| V3-only OK | 45 |
| Both abstain, different stage | 381 |
| Both abstain, same stage | 1 |
| Typed/Pandas mismatch | 0 |
| Package validation | 1.012 records, 0 lỗi/cảnh báo |
| Clean packaged replay | 362/362 |
| Package SHA-256 | `3e068bc697ac9d34512f16d520af5bf4d51a6e0dc3137c503a25f9acfacb54f0` |
| Promotion policy | `BLOCKED` |

Top V3 blockers là `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` 162, `BINDING_TIE` 121, `METRIC_SOURCE_SPECIFICITY_REQUIRED` 47, `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED` 40, `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` 21 và `BINARY_OPERANDS_UNRESOLVED` 20.

217 equal và 45 V3-only chỉ là differential/coverage. 100 value differences không thể gọi đúng hoặc sai nếu không có trusted answer gold.

## 7. Layer scorecard

### L0 — Data/A6

Status: `PASS_STRUCTURAL_WITH_ACCURACY_BLOCKERS`.

- 1.973 documents, 146.246 tables, 2.634.120 observations.
- 1.817.629 execution-ready observations; 1.884.911 execution candidates; ready rows có blocker = 0.
- 0 critical quality issues; 560.615 quality-rule violations được taxonomy hóa.
- Blocker lớn: generic row label 202.542, unknown column role 121.127, unit without evidence 115.497, unresolved column period 17.619, rejected scale 2.130.
- Arithmetic reconciliation: 11.170/11.247 = 99,32%.
- Structure accuracy: `NOT_MEASURED`; Structure Gold `SG/C2/C3` chưa tồn tại.
- Deterministic identity dựa trên immutable manifest và prior A/B acceptance; audit này không rebuild A6 6,8 GB hai lần.

### L1 — Semantic parsing

Gold source: `MODEL_SEMANTIC_GOLD_V1`, model-generated, provisional, not sealed, không human review. Denominator chính chỉ gồm 43 `HEADLINE_CORE / RESOLVED` QIDs.

| Metric | Numerator / denominator | Value |
|---|---:|---:|
| Record exact match | 0/43 | 0,00% |
| Entity exact match | 0/43 | 0,00% |
| Entity strict micro F1 | TP 0, FP 43, FN 46 | 0,0000 |
| Metric concept exact match | 0/43 | 0,00% |
| Metric strict micro F1 | TP 0, FP 0, FN 44 | 0,0000 |
| Period exact match | 0/43 | 0,00% |
| Period strict micro F1 | TP 0, FP 43, FN 43 | 0,0000 |
| Period value exact, bỏ qua mention span | 19/43 | 44,19% |
| Basis accuracy | 36/43 | 83,72% |
| Unit dimension accuracy | 36/43 | 83,72% |
| Unit scale accuracy | 32/43 | 74,42% |
| Operation exact match | 42/43 | 97,67% |
| Operation-tree structural match | 42/43 | 97,67% |
| Output-shape accuracy | 43/43 | 100,00% |
| Field missing rate | 93/313 applicable field instances | 29,71% |
| Field not-emitted rate | 43/313 applicable field instances | 13,74% |

Các strict-zero có nguyên nhân contract cụ thể:

- parser public pre-bind không emit metric phrase/concept;
- entity prediction không emit `entity_type` theo model-gold schema;
- period prediction không emit exact mention spans;
- không có downstream evidence, selected table, row, answer hoặc query nào được dùng để backfill.

QID 427 là operation/arity/operand-role miss duy nhất trên 43 headline (`GROWTH_PERCENT_CHANGE`). Mọi số L1 đều gắn nhãn `PROVISIONAL_PARTIAL_MODEL_GOLD`, không phải official, independent hoặc promotion accuracy.

### L2 — Operand planning

| Metric | Kết quả |
|---|---:|
| Required/emitted operand count | 42/43 |
| Operand role exact | 42/43 |
| Operation arity | 42/43 |
| Entity-period-basis-unit scope exact | 2/43 |
| Operand order/scope exact | 2/43 |
| Child/reference closure | 43/43 |

Scope/order thấp chủ yếu do metric/scope contract không được public parser emit đầy đủ, không phải dangling-reference failure.

### L3 — Candidate retrieval

Gold source: fresh evalkit `T0_manual`, 95/1.012 QIDs.

| Metric | Kết quả |
|---|---:|
| Manual-gold coverage | 95/1.012 = 9,39% |
| S1 candidate hit | 95/95 = 100,00% |
| S1 candidate miss | 0 |
| S1 pool size | median 500, p90 1.575, max 3.403 |
| Latency all 1.012 | mean 332 ms, median 239 ms, p95 796,8 ms |
| Latency manual 95 | mean 400,12 ms, median 249 ms, p95 1.076,4 ms |

Checkpoint chỉ expose boolean “có ít nhất một gold trong S1”, nên macro recall của toàn bộ gold items ở S1 là `NOT_MEASURED`; không đổi candidate-hit thành candidate-recall.

### L4 — Ranking/reranking

| Metric | Numerator / denominator | Value |
|---|---:|---:|
| Top-1 hit | 33/95 | 34,74% |
| Top-5 hit | 80/95 | 84,21% |
| Top-10 hit | 86/95 | 90,53% |
| Precision@10 macro | sum 20,20 / 95 | 0,2126 |
| Recall@10 macro | sum 67,62 / 95 | 0,7117 |
| F2@10 macro | sum 36,52 / 95 | 0,3845 |
| MRR@10 | sum 51,78 / 95 | 0,5450 |
| nDCG@10 | sum 52,40 / 95 | 0,5516 |

Rank-miss QIDs: `374, 376, 385, 397, 436, 542, 723, 767, 975`.

S2 MRR@10 = S3 MRR@10 = 0,5450; paired uplift = 0 và CI95 = `[0, 0]` vì production S3 là `IdentityReranker`. Kết quả này không đủ promote reranker: 95 labels là dev/manual, không phải sealed held-out dual-annotated release.

### L5 — Selector/binder

Status: `NOT_MEASURED`.

Gold registry ghi evidence/binding `usable_records = 0`. Không dùng selected document/table/row/cell của runtime làm gold cho chính runtime. Chỉ báo runtime blocker counts; document/table/row/column/observation selection accuracy, global binding exact, period/basis/currency/unit coherence đều `NOT_MEASURED`.

### L6 — Planner/executor

| Metric | Canonical V2 | Semantic V3 shadow |
|---|---:|---:|
| Full-corpus execution coverage | 585/1.012 | 362/1.012 |
| Clean replay consistency | 585/585 | 362/362 |
| Local Answer Accuracy | 14/31 | 9/31 |
| Local Execution Accuracy | 14/31 | 9/31 |
| Local emitted/replay coverage | 14/31 | 12/31 |

V3 raw trace dùng internal evidence schema, nên lần thử evaluator trực tiếp trên raw trace không replay được và bị loại khỏi metrics. Số V3 hợp lệ ở trên được đo lại từ package đã validate; 12/12 emitted replay, trong đó 9/31 đúng local gold.

Formula correctness và binding-vs-execution attribution là `NOT_MEASURED` vì không có aligned formula/binding gold. Replay consistency không được gọi là Execution Accuracy.

### L7 — Evidence/grounding

Hai package đều qua structural evidence validation và replay, nhưng document correctness, table correctness, citation correctness, evidence completeness và answer-supported-by-evidence đều `NOT_MEASURED`. Không có usable trusted evidence labels.

### L8 — Packaging

| Invariant | V2 | V3 shadow |
|---|---:|---:|
| Records | 1.012 | 1.012 |
| Unique QID | 1.012 | 1.012 |
| Exact question preservation | PASS | PASS |
| JSON/ZIP/CSV/evidence contract | PASS | PASS |
| Safe query + clean replay | PASS | PASS |
| Errors / warnings | 0 / 0 | 0 / 0 |

V2 package là validated canonical candidate. V3 package vẫn là shadow artifact và không được promote.

## 8. Coverage/intersection matrix

| Intersection | Count | QIDs | Có thể đo |
|---|---:|---|---|
| Headline semantic × retrieval gold | 0 | — | Không cross-layer |
| Headline semantic × answer gold | 0 | — | Không cross-layer |
| Headline × retrieval × answer | 0 | — | Overall E2E accuracy `NOT_MEASURED` |
| Diagnostic semantic × retrieval/answer | 0 | — | Diagnostic chỉ là case study semantic |
| Reserve semantic × retrieval/answer | 0 | — | Reserve không dùng strategy |
| Retrieval × answer | 2 | 543, 708 | Retrieval + local answer outcome |
| Evidence/binding × bất kỳ set | 0 | — | L5/L7 correctness `NOT_MEASURED` |
| V2 trace × V3 trace | 1.012 | 1–1.012 | Coverage/differential only |

QID 543: retrieval top-10 success nhưng V2 abstain do multi-entity unsupported. QID 708: retrieval top-10 success và V2 local answer/replay đúng. Hai câu không đủ để suy rộng.

## 9. Earliest-failure attribution

Machine artifact có đúng 1.012 dòng, mỗi QID ghi available gold, confidence, strategy eligibility, V2/V3 status và evidence artifact.

| Family | Count | Diễn giải |
|---|---:|---|
| `GOLD_UNAVAILABLE` | 901 | Không có trusted label đủ để quy lỗi system |
| `SEMANTIC_PARSE` | 67 | 51 provisional semantic cases + answer-gold runtime route failures; chỉ 59 strategy-eligible |
| `GOLD_GENERATION_FAILURE` | 20 | Annotation-generation failure, không phải parser failure |
| `UNKNOWN` | 14 | Không quan sát failure trên available local gold hoặc không tách được layer |
| `RANKING` | 9 | Gold có ở S1 nhưng ngoài top-10 |
| `OPERAND_PLAN` | 1 | Select-at-arg operand requirement blocker |

Không có `CANDIDATE_RETRIEVAL` failure trên 95 manual-gold QIDs; không có packaging/replay failure. Attribution không ép 901 câu thiếu gold vào một system failure family.

## 10. Improvement strategy

### P0

1. **Emit metric phrase/concept tại canonical public pre-bind boundary** — 43/43 provisional headline records thiếu metric output; target trực tiếp metric exact/F1. Phải dùng reviewed ontology, exact spans, explicit OOV/ambiguity và leakage tests. Confidence `MEDIUM`, cost `M`.
2. **Typed multi-entity operand planning** — 177 full-corpus abstentions; 12/31 local answer operations là `multi`, đúng 0/12. Bảo vệ entity order, one-fact-per-entity, basis/currency coherence và explicit absolute difference. Confidence `HIGH`, cost `L`.
3. **Ranker/reranker trên sealed held-out evidence gold** — 9 rank misses, gồm 6 screen misses. Acceptance: paired F2 delta CI95 low ≥ 0, protected slice delta ≥ -0,01. Không tune trên 95-question manual dev set. Confidence `HIGH`, cost `M`.

### P1

1. **V3 metric governance + deterministic binder specificity** — observed blockers: review-required 162, binding tie 121, source specificity 47. Không phá fail-closed behavior; binding exact vẫn blocked đến khi có gold. Confidence `MEDIUM`, cost `L`.
2. **Hoàn thiện entity/period/basis/unit prediction contract** — exact entity/period đang 0 do schema fields/spans không emit; period-value 19/43, basis 36/43, unit dimension 36/43, scale 32/43. Confidence `MEDIUM`, cost `M`.

### P2

1. **Measurement instrumentation và intersecting gold** — thêm per-QID timing cho V2/V3; xây prediction-blind human gold có giao giữa semantic, retrieval, binding, evidence và answer. Không backfill từ runtime output. Confidence `HIGH`, cost `M`.

Reserve QIDs không được dùng để chọn backlog hoặc acceptance threshold.

## 11. Measured, not measured, blockers

Measured:

- raw/A6/retrieval identity và structural gates;
- route coverage;
- Canonical/V3 full-corpus coverage, validation và replay;
- provisional semantic parser fields trên 43 headline model-gold records;
- manual retrieval/ranking trên 95 QIDs;
- local Answer/Execution Accuracy trên 31 QIDs;
- package contract trên 1.012 records.

Not measured:

- official Answer Accuracy và Execution Accuracy;
- A6 structure accuracy;
- trusted document/table/row/column/observation binding accuracy;
- evidence correctness/completeness;
- formula correctness trên aligned gold;
- one-denominator overall E2E accuracy;
- V2/V3 per-QID latency median/p95;
- promotion-eligible parser, reranker, binding hoặc answer metrics.

Blockers:

- no sealed independent evaluation release;
- model semantic checkpoint chỉ 71/150 completed, 51 usable, prefix-biased;
- evidence/binding usable gold = 0;
- semantic/retrieval/answer sets gần như không giao;
- Python runtime không phải hash-locked local acceptance venv;
- V3 promotion policy thiếu mọi required sealed metric và vẫn `BLOCKED`.

## 12. Files and reproduction

Tracked report:

`docs/reports/E2E_LAYER_AUDIT_AND_IMPROVEMENT_STRATEGY_2026-08-29.md`

Generated audit directory, không commit:

`artifacts/reports/e2e-layer-audit-aadc8f8-20260829-01/`

Các file bắt buộc:

- `summary.json`
- `failure_attribution.jsonl` — 1.012 rows
- `layer_metrics.json`
- `coverage_intersections.json`
- `improvement_backlog.json`
- `manifest.json`
- `checkpoint_integrity.json`

Supporting evidence:

- `semantic_metrics_detail.json`
- `semantic_parser_predictions.jsonl`
- `canonical_v2_answer_eval.json`
- `semantic_v3_packaged_answer_eval.json`
- `logs/`

Core reproduce commands:

```bash
make paths-check
make snapshots-verify
make ci
make test-integration
make semantic-coverage
git diff --check

PYTHONPATH=src python -m text2pandas.interface.cli.main run \
  --run-id <new-canonical-run-id>

PYTHONPATH=src python -m text2pandas.interface.cli.main shadow-v3 \
  --run-id <new-v3-run-id> \
  --operand-k 20 \
  --legacy-run-id <new-canonical-run-id>

PYTHONPATH=src python -m text2pandas.interface.cli.main package-v3 \
  --run-id <new-v3-run-id> \
  --doc-id stripped \
  --locator-base 1

PYTHONPATH=src python -m text2pandas.pipelines.retrieval.evalkit.cli collect \
  --tag <new-evalkit-tag> \
  --gold-source manual \
  --loop

PYTHONPATH=src python -m text2pandas.pipelines.retrieval.evalkit.cli report \
  --tag <new-evalkit-tag> \
  --gold-source manual
```

Mọi reproduction phải dùng run-id mới; không overwrite run của audit này.

## 13. Final status block

```text
E2E AUDIT STATUS: COMPLETE

BASELINE: FROZEN_AND_MEASURED
SOURCE COMMIT: aadc8f8d2d0c302753396abee2847aa60ef7b71e
GOLD TOOL COMMIT: b08643892d589817b42420480058cf86c92afe71
RAW SNAPSHOT: ca033190f2e9e99f
A6 BUILD: c6887fb633374fad
RETRIEVAL INDEX: 872ccb0dda9a2bb6
CANONICAL V2 RUN: canonical-v2-e2e-audit-aadc8f8-20260829-01
SEMANTIC V3 RUN: semantic-v3-e2e-audit-aadc8f8-20260829-01
GIT DIRTY: false

CHECKPOINT:
STATUS: PARTIAL_CHECKPOINT / NOT_SEALED
COMPLETED COVERAGE: 71/150
SEMANTIC USABLE: 51/150
PROVISIONAL HEADLINE USABLE: 43/100
DIAGNOSTIC USABLE: 2/20
RESERVE OBSERVED: 6/30
INCOMPLETE QID EXCLUDED: 539
PREFIX-BIAS LIMITATION: YES; QID-ORDERED PARTIAL PREFIX
MODEL-GOLD LIMITATION: MODEL-GENERATED, NO HUMAN REVIEW, NOT PROMOTION GOLD
CHECKPOINT SHA BEFORE: 2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636
CHECKPOINT SHA AFTER: 2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636
CHECKPOINT INTEGRITY: PASS

GATES:
PATHS: PASS
SNAPSHOTS: PASS
CI: PASS — 2174 passed, 42 approved skips, 29 deselected
INTEGRATION: PASS — 22 passed, 2223 deselected
SEMANTIC COVERAGE: PASS — 684/1012 eligible; NOT accuracy
DIFF CHECK: PASS PRE-REPORT

LAYER RESULTS:
L0 DATA: PASS STRUCTURAL; STRUCTURE ACCURACY NOT_MEASURED
L1 SEMANTIC: PROVISIONAL_PARTIAL_MODEL_GOLD — FULL EXACT 0/43
L2 OPERAND PLAN: PROVISIONAL — COUNT/ROLE 42/43; SCOPE 2/43
L3 RETRIEVAL: CANDIDATE HIT 95/95 ON MANUAL GOLD
L4 RANKING: TOP10 HIT 86/95; F2@10 0.3845; 9 RANK MISSES
L5 BINDING: NOT_MEASURED
L6 EXECUTION: V2 14/31 LOCAL; V3 9/31 LOCAL; OFFICIAL NOT_MEASURED
L7 EVIDENCE: STRUCTURALLY VALID; CORRECTNESS NOT_MEASURED
L8 PACKAGING: V2 PASS; V3 SHADOW PASS

CANONICAL V2:
TOTAL: 1012
EMITTED: 585
ABSTAINED: 427
VALIDATION: 0 ERRORS / 0 WARNINGS
REPLAY: 585/585

SEMANTIC V3:
TOTAL: 1012
OK: 362
ABSTAINED: 650
V2/V3 EQUAL: 217
V2/V3 DIFFERENT: 100
V2-ONLY: 268
V3-ONLY: 45
PROMOTION POLICY: BLOCKED; NO PROMOTION PERFORMED

ACCURACY:
SEMANTIC: PROVISIONAL FULL EXACT 0/43; MODEL GOLD ONLY
RETRIEVAL: CANDIDATE HIT 95/95; EXACT S1 ALL-GOLD RECALL NOT_MEASURED
RANKING: P@10 0.2126 / R@10 0.7117 / F2@10 0.3845 / MRR@10 0.5450
BINDING: NOT_MEASURED
ANSWER: V2 14/31 LOCAL; V3 9/31 LOCAL; OFFICIAL NOT_MEASURED
EXECUTION: V2 14/31 LOCAL; V3 9/31 LOCAL; OFFICIAL NOT_MEASURED
EVIDENCE: NOT_MEASURED
REPLAY CONSISTENCY: V2 585/585; V3 362/362
SUBMISSION VALIDATION: V2 PASS; V3 SHADOW PASS

COVERAGE INTERSECTIONS: HEADLINE×RETRIEVAL×ANSWER=0; RETRIEVAL×ANSWER=2; EVIDENCE GOLD=0

TOP FAILURE FAMILIES:
1. MULTI_ENTITY_OPERATION_NOT_SUPPORTED — 177 V2 ABSTAINS
2. MODEL-GOLD METRIC OUTPUT MISSING — 43/43 PROVISIONAL HEADLINE
3. V3 REPORTED_METRIC_REQUIRES_REVIEW — 162
4. V3 BINDING_TIE — 121
5. TOP10 RANK MISS — 9/95 MANUAL GOLD

TOP IMPROVEMENTS:
P0: METRIC EMISSION; MULTI-ENTITY TYPED PLANNING; HELD-OUT RERANKING
P1: V3 METRIC/BINDING GOVERNANCE; COMPLETE ENTITY/PERIOD/UNIT CONTRACT
P2: PER-QID TIMING AND INTERSECTING INDEPENDENT GOLD

MEASURED: IDENTITIES, GATES, COVERAGE, REPLAY, 43 SEMANTIC, 95 RETRIEVAL, 31 LOCAL ANSWER
NOT MEASURED: OFFICIAL ACCURACY, STRUCTURE ACCURACY, BINDING/EVIDENCE CORRECTNESS, OVERALL E2E ACCURACY
BLOCKERS: NO SEALED INDEPENDENT RELEASE; NO USABLE BINDING/EVIDENCE GOLD; NEAR-ZERO GOLD INTERSECTION
LIMITATIONS: MODEL GOLD PROVISIONAL/PREFIX-BIASED; MANUAL RETRIEVAL DEV GOLD; LOCAL ANSWER GOLD; UNLOCKED PYTHON ENV
FILES CREATED: MARKDOWN REPORT + 7 REQUIRED MACHINE ARTIFACTS + SUPPORTING EVIDENCE/LOGS
EXACT REPRODUCE COMMANDS: SECTION 12 AND artifacts/reports/e2e-layer-audit-aadc8f8-20260829-01/manifest.json
RECOMMENDED NEXT IMPLEMENTATION TASK: P0 METRIC EMISSION + TYPED MULTI-ENTITY PLAN, FROZEN BEFORE NEW HELD-OUT EVALUATION
```
