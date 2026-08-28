# TABLE RETRIEVAL F2 RECOVERY — IMPLEMENTATION REPORT

**Ngày thực hiện:** 2026-08-28  
**Baseline HEAD:** `a2d3ef0308612f3025cf1a78c3d5bc470d0634f6`  
**Production path:** Canonical V2  
**Semantic V3:** giữ nguyên `SHADOW_ONLY`, không promote  
**Quyết định cuối:** `KEEP BASELINE`

## 1. Executive Summary

### Baseline

Baseline immutable được đóng băng từ Canonical V2 tại commit
`a2d3ef0308612f3025cf1a78c3d5bc470d0634f6`, với raw snapshot
`ca033190f2e9e99f`, A6 build `c6887fb633374fad`, retrieval index
`872ccb0dda9a2bb6` và submission SHA-256:

```text
a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c
```

Manual gold 95 câu xác nhận bottleneck không nằm ở S1: 95/95 câu có gold
trong S1 và 554/554 gold items còn trong candidate pool. Tuy nhiên chỉ 86/95
câu có gold trong top 10, dynamic N chỉ giữ gold cho 50/95 câu và binding làm
mất gold ở 10 câu.

### Changes

Đã bổ sung trace xuyên suốt `Intent → S1 → S2 → S3 → output N → binding →
final relevant_tables`, classifier gold-aware cho stage loss, công cụ audit
ranking/N/binding, công cụ paired full-run, cùng regression tests.

Parser year-range được harden theo thiết kế kiểm soát:

```text
2021–2024
→ semantic years:  [2021, 2022, 2023, 2024]
→ retrieval years: [2021, 2024]
```

Nhờ tách semantic period domain khỏi lexical retrieval years, parser hiểu đủ
35/37 range questions mà không đổi S1, rank, N hay scorer-facing output. Evalkit
checkpoint được bump từ `evalkit-11` lên `evalkit-12` theo ADR 0013.

Không thay production ranking weights, output-N policy, binding policy hoặc
multi-entity safety gates. Các phương án này chỉ được đo diagnostic vì không có
untouched sealed held-out table gold để chống overfit.

### Results

Full upgraded E2E chạy đủ 1.012/1.012 câu, validator sạch, replay 563/563 câu
có evidence khớp, 449 câu không có evidence và không có replay error. So sánh
toàn bộ scorer-facing fields cho kết quả:

```text
Wins:       0
Losses:     0
Unchanged:  1,012
```

ZIP upgraded có đúng cùng 1.030.304 bytes và cùng SHA-256 với baseline. Vì vậy
đây là bằng chứng đo được rằng thay đổi đã giữ nguyên submission output, không
phải bằng chứng Table F2 chính thức đã tăng.

### Decision

**`KEEP BASELINE`.** Giữ lại observability, attribution tooling và year-range
hardening vì chúng tăng khả năng kiểm toán mà không làm thay đổi scorer-facing
output. Không promote các thử nghiệm ranking/N/binding. Không upload ZIP
upgraded như một “cải thiện” vì nó byte-identical với baseline, official scorer
không có trong repo, và không có upload target/credential/receipt interface để
tạo mapping chính thức an toàn.

## 2. Scope và source verification

Source hiện tại xác nhận production flow:

```text
interface/cli/main.py
→ application/usecases/canonical_run.py
→ pipelines/retrieval/question_intent.py
→ pipelines/retrieval/filter_s1.py
→ pipelines/retrieval/rank_s2.py
→ pipelines/retrieval/evalkit/stages.py::IdentityReranker
→ pipelines/retrieval/policy.py
→ answer/evidence binding
→ pipelines/retrieval/submission_adapter.py
→ submission validator/package
```

Audit ban đầu có một discrepancy quan trọng: deterministic multi-entity routes
cho `COUNT`, `DIFFERENCE`, `AVERAGE` và `SUM` đã tồn tại trong canonical runner.
Do đó P5 là verification/fail-closed audit, không phải lý do để tạo route hoặc
pipeline song song. `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` vẫn có 177 câu trong
full run; không blanket-relax gate khi chưa chứng minh entity/metric/period/basis
và operands resolve duy nhất.

## 3. Changed Components

| File | Function/class | Old behavior | New behavior | Reason |
|---|---|---|---|---|
| `src/text2pandas/pipelines/retrieval/submission_adapter.py` | `SubmissionRefs` | Chỉ trả refs, N và ranked IDs | Có thêm trace compact theo từng stage | Đóng measurement gap mà không đổi submission contract |
| `src/text2pandas/pipelines/retrieval/submission_adapter.py` | `RetrievalToSubmission.refs_for` | Không lưu score/features/candidate transitions | Lưu intent, full S1 IDs, S2/S3 rank-score components, N reason và selected IDs | Xác định chính xác gold bị mất ở đâu |
| `src/text2pandas/pipelines/retrieval/submission_adapter.py` | `RetrievalToSubmission.n_for` | N dùng `intent.years` | N dùng `intent.retrieval_years` | Không để semantic range expansion làm phình output N |
| `src/text2pandas/application/usecases/canonical_run.py` | `run_canonical_pipeline` | Internal records thiếu pre/post-binding state | Ghi retrieval, answer-pool, selected evidence, binding effect và final refs | Phân biệt output loss, binding loss và serialization loss |
| `src/text2pandas/pipelines/retrieval/evalkit/attribution.py` | `StageLoss`, `classify_stage_loss` | Chưa có classifier thống nhất | Thêm 7 mutually exclusive labels, chỉ dùng gold trong evalkit | Attribution diagnostic không rò gold vào production |
| `src/text2pandas/pipelines/retrieval/question_intent.py` | `Intent`, `parse_intent` | Range chỉ biểu diễn hai endpoint | Expand ascending dash range vào full semantic domain; lưu riêng lexical endpoints | Sửa parser defect có evidence, giữ retrieval-neutral |
| `src/text2pandas/pipelines/retrieval/evalkit/stages.py` | `Bm25StructuralRanker.run` | Period bonus dùng semantic years trực tiếp | Period bonus dùng `retrieval_years` | Chặn interior years vô tình reweight ranking |
| `src/text2pandas/pipelines/retrieval/evalkit/runner.py` | `SCHEMA_VERSION`, `collect` | `evalkit-11`, không ghi retrieval years | `evalkit-12`, ghi cả semantic và retrieval years | Version hóa behavior checkpoint và trace rõ semantics |
| `src/text2pandas/pipelines/retrieval/evalkit/__init__.py` | `SCHEMA_VERSION` | Public marker `evalkit-11` | Public marker `evalkit-12` | Đồng bộ checkpoint public/runtime |
| `tools/retrieval/evaluate_stage_attribution.py` | CLI mới | Không có exact P1 reproduction tool | Sinh immutable trace, metrics và manifest cho manual 95 | Gate P1 có thể tái chạy |
| `tools/retrieval/analyze_recovery_options.py` | CLI mới | Không có rank/feature/N/binding audit thống nhất | Sinh rank buckets, feature audit, policy và binding sweeps | So sánh giả thuyết trước khi chạm production |
| `tools/retrieval/compare_canonical_runs.py` | CLI mới | Không có exact 1.012-QID paired comparator | So sánh mọi scorer-facing field, metrics, validation, ZIP SHA | Chứng minh wins/losses và output identity |
| `docs/adr/0013-year-range-intent-checkpoint-version.md` | ADR 0013 | Chưa có contract cho year range | Ghi quyết định semantic expansion + lexical retrieval boundary | Giải thích trade-off và rollback point |
| `tests/test_retrieval_stage_attribution.py` | Unit tests mới | Không có transition classifier coverage | Cover tất cả loss labels và recovery cases | Ngăn attribution sai stage |
| `tests/test_retrieval_r0_entity.py` | Parser regressions | Thiếu range dash/reversed/clipping cases | Cover `-`, `–`, `—`, reversed fail-closed và boundary clipping | Bảo vệ parser hardening |
| `tests/test_integration_smoke.py` | Retrieval integration | Không assert trace/range-N boundary | Assert trace contract và range không phình N/S1 | Bảo vệ stage interaction |
| `tests/test_p0_unify.py` | Behavior fingerprint | Chỉ biết đến `evalkit-11` | Thêm fingerprint `evalkit-12` | Bắt buộc bump checkpoint khi behavior đổi |

Không đổi DB schema, submission JSON schema, entity resolver, V3 promotion
policy hoặc canonical answer safety gates.

## 4. Measurement classification

| Nhóm | Classification | Ý nghĩa |
|---|---|---|
| Full 1.012 run counts, validation, replay, per-QID equality, ZIP checksum | `MEASURED` | Đo trực tiếp trên artifact local |
| Manual 95 gold metrics và sweeps | `DIAGNOSTIC` | Gold phát triển, không đại diện official hidden gold |
| Official Table Precision/Recall/F2, Answer Accuracy, Execution Accuracy | `NOT_MEASURED` | Không có official scorer/hidden gold và chưa upload |
| Causal attribution cho submission ID 3757 | `UNKNOWN` | Thiếu exact ZIP/receipt mapping của submission đó |

## 5. Baseline vs upgraded metrics

| Metric | Baseline | Upgraded | Delta | Classification |
|---|---:|---:|---:|---|
| S1 gold-item recall | 1.000000 | 1.000000 | 0.000000 | `DIAGNOSTIC` |
| S1 question any-hit | 95/95 | 95/95 | 0 | `DIAGNOSTIC` |
| Hit@1 | 0.347368 | 0.347368 | 0.000000 | `DIAGNOSTIC` |
| Hit@5 | 0.842105 | 0.842105 | 0.000000 | `DIAGNOSTIC` |
| Hit@10 | 0.905263 | 0.905263 | 0.000000 | `DIAGNOSTIC` |
| Hit@20 | 0.968421 | 0.968421 | 0.000000 | `DIAGNOSTIC` |
| MRR@5 | 0.536491 | 0.536491 | 0.000000 | `DIAGNOSTIC` |
| Dynamic-output macro precision | 0.360597 | 0.360597 | 0.000000 | `DIAGNOSTIC` |
| Dynamic-output macro recall | 0.297080 | 0.297080 | 0.000000 | `DIAGNOSTIC` |
| Dynamic-output macro F2 | 0.303466 | 0.303466 | 0.000000 | `DIAGNOSTIC` |
| Canonical-final macro precision | 0.440246 | 0.440246 | 0.000000 | `DIAGNOSTIC` |
| Canonical-final macro recall | 0.374624 | 0.374624 | 0.000000 | `DIAGNOSTIC` |
| Canonical-final macro F2 | 0.381360 | 0.381360 | 0.000000 | `DIAGNOSTIC` |
| Official Table Precision | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | Hidden gold/scorer absent |
| Official Table Recall | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | Hidden gold/scorer absent |
| Official Table F2 | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | Hidden gold/scorer absent |
| Questions | 1,012 | 1,012 | 0 | `MEASURED` |
| Answered / answer success | 563 | 563 | 0 | `MEASURED` |
| Abstain | 449 | 449 | 0 | `MEASURED` |
| Official Answer Accuracy | `NOT_MEASURED` | `NOT_MEASURED` | `NOT_MEASURED` | Hidden gold/scorer absent |
| Replay matched / executed | 563/563 | 563/563 | 0 | `MEASURED` |
| Replay errors | 0 | 0 | 0 | `MEASURED` |
| Empty `relevant_tables` | 1 | 1 | 0 | `MEASURED` |
| Mean tables/question | 2.538538 | 2.538538 | 0.000000 | `MEASURED` |
| Max tables/question | 10 | 10 | 0 | `MEASURED` |
| Runtime | 440.46 s | 447.06 s | +6.60 s | `MEASURED`; trace overhead/runtime variance |

Không dùng runtime delta để suy ra quality. Scorer-facing outputs mới là acceptance
surface và chúng giống hệt nhau.

## 6. Per-stage attribution

Classifier được chạy trên manual 95 và reproduce đúng P1 gate:

| Stage label | Questions | Diễn giải |
|---|---:|---|
| `S1_LOSS` | 0 | Không câu nào mất toàn bộ gold tại candidate generation |
| `S2_RANK_LOSS` | 8 | Gold còn ở S1 nhưng không sống trong ranked window được xét |
| `OUTPUT_N_LOSS` | 23 | Gold ở ranked output nhưng bị dynamic N cắt |
| `BINDING_LOSS` | 10 | Retrieval output có gold nhưng answer/evidence binding thay thế |
| `SERIALIZATION_LOSS` | 0 | Không phát hiện mất gold riêng ở serialization |
| `NO_LOSS` | 54 | Final refs còn ít nhất một gold table |
| `UNKNOWN` | 0 | Manual slice có gold đầy đủ để phân loại |

Gate P1 đạt chính xác:

```text
Questions:                   95
Gold items:                 554
S1 question any-hit:      95/95
S1 gold-item hit:        554/554
Hit@10:                   86/95
Dynamic-policy hit:       50/95
```

## 7. Ranking audit

### Rank-loss buckets

| Bucket | Questions |
|---|---:|
| `GOLD_RANK_1` | 33 |
| `GOLD_RANK_2_5` | 47 |
| `GOLD_RANK_6_10` | 6 |
| `GOLD_RANK_11_20` | 6 |
| `GOLD_RANK_21_50` | 0 |
| `GOLD_NOT_IN_TOP50` | 3 |
| `GOLD_NOT_IN_S1` | 0 |

### Feature contribution

Trên các ranked items có annotation trong manual slice:

| Signal | Gold | Non-gold | Observation |
|---|---:|---:|---|
| Mean normalized lexical | 0.784478 | 0.507607 | Lexical signal phân tách hữu ích |
| Basis hit rate | 0.997085 | 0.809848 | Basis giúp gold |
| Code hit rate | 0.102041 | 0.018380 | Code signal hiếm nhưng có ích |
| Period hit rate | 0.979592 | 0.972090 | Ít khả năng phân tách trên slice này |
| Unit hit rate | 0.332362 | 0.629680 | Unit signal hiện thường xuất hiện ở non-gold hơn |
| Mean rank | 12.734694 | 26.493533 | Gold có xu hướng xếp cao hơn nhưng vẫn có tail loss |

Đây là evidence để tiếp tục nghiên cứu unit/row-label signals, chưa phải evidence
đủ để đổi weight production. Không có untouched held-out labels nên ranking gate
promotion không đạt.

## 8. Output-N policy experiments

Các profile đều chạy offline trên cùng manual 95 development gold:

| Policy | Output macro P | Output macro R | Output macro F2 | Canonical-final macro F2 |
|---|---:|---:|---:|---:|
| Baseline dynamic | 0.360597 | 0.297080 | 0.303466 | 0.381360 |
| Fixed N=5 | 0.273684 | 0.566376 | 0.392803 | 0.389083 |
| Fixed N=8 | 0.236842 | 0.672256 | 0.395774 | 0.410540 |
| Fixed N=10 | 0.212632 | 0.711742 | 0.384460 | 0.422153 |
| Score margin 0.2 | 0.355576 | 0.603233 | 0.472382 | 0.420351 |
| Score margin 0.5 | 0.244223 | 0.706479 | 0.428065 | 0.434739 |

Score margin 0.2 tốt nhất ở pre-binding diagnostic F2; margin 0.5 tốt nhất ở
canonical-final simulation. Tuy vậy cùng 95 câu này đã tạo giả thuyết, nên dùng
chính nó để promote sẽ là development-set optimization. Production N được giữ
nguyên; không hardcode N=10.

## 9. Binding experiments

| Binding policy | Macro P | Macro R | Macro F2 | Mean tables |
|---|---:|---:|---:|---:|
| Baseline final | 0.440246 | 0.374624 | 0.381360 | 3.336842 |
| Union(bound, retrieval output) | 0.398901 | 0.460238 | 0.427120 | 3.915789 |
| Union(bound, top 5) | 0.292310 | 0.560238 | 0.401818 | 5.410526 |
| Union(bound, top 10) | 0.247615 | 0.613221 | 0.348293 | 7.768421 |

Union với retrieval output cho local diagnostic gain, nhưng precision giảm và
không có sealed held-out/official contract proof. Vì vậy không đổi binding
production. Trace mới vẫn cho phép audit 10 `BINDING_LOSS` cases trực tiếp.

## 10. Year-range hardening

### Rejected experiment

Thử nghiệm đầu tiên dùng full expanded years trực tiếp cho S2 period bonus và N.
Aggregate Hit@10 vẫn giữ nhưng Hit@5 giảm từ 80 xuống 79. QID `q425` có best
gold rank giảm 5 → 6, N tăng 2 → 4 nhưng không recover gold. Thay đổi này bị
reject và artifact được giữ immutable để ghi lại negative result.

### Accepted implementation

Final design dùng:

- `Intent.years`: full semantic domain cho operand/period reasoning;
- `Intent.lexical_years`: năm thực sự xuất hiện trong câu;
- `Intent.retrieval_years`: lexical endpoints cho ranking bonus và output N.

Paired manual 95 sau decoupling giống baseline trên toàn bộ S1 IDs, S2 order,
S3 order, output IDs và stage-loss labels. Partial E2E 37 range questions cũng
giống baseline ở status, answer, refs, reason và pandas query; 35/37 câu nhận
semantic expansion đầy đủ.

## 11. Full 1,012-QID regression

Full comparison kiểm tra các field:

```text
status
answer
relevant_tables
relevant_docs
evidence
pandas_query
confidence
reason
```

Kết quả:

| Regression class | Count |
|---|---:|
| New wins | 0 |
| New losses | 0 |
| New table wins | 0 |
| New table losses | 0 |
| Answer wins | 0 |
| Answer losses | 0 |
| Unchanged | 1,012 |

Validator: 1.012 records, 0 errors, 0 warnings. Replay: 563 executed, 563
matched, 449 no-evidence, 0 errors.

## 12. Failed or unproven hypotheses

1. **“Tăng N toàn cục sẽ giải quyết F2.” — không được chứng minh để promote.**
   Fixed N và score-margin tăng recall/F2 trên development slice nhưng tạo
   precision trade-off và thiếu untouched held-out evaluation.

2. **“Luôn union retrieval refs với bound evidence.” — không được chứng minh để
   promote.** Local F2 tăng từ 0.381360 lên 0.427120, nhưng precision giảm và
   hidden impact không biết.

3. **“Expand range rồi dùng mọi interior year cho ranking/N.” — bị bác bỏ.**
   QID `q425` regression rank 5 → 6 và N 2 → 4 mà không recover gold.

4. **“Table F2 thấp đồng nghĩa parser/entity resolver sai.” — không được chứng
   minh.** S1 đạt 95/95 và 554/554; entity coverage full run là 1.011/1.012.

5. **“Cần rewrite retriever hoặc promote Semantic V3.” — không có evidence.**
   V3 vẫn shadow; không có thay đổi nào trong plan này justify promotion.

6. **“Cần mở toàn bộ multi-entity composition.” — không được chứng minh.** Các
   deterministic routes đã tồn tại; 177 abstains phản ánh các safety/coverage
   constraints còn lại. Không blanket-relax khi operands chưa resolve duy nhất.

7. **“Có thể tuyên bố official Table F2 tăng từ 0.2500.” — không thể đo.** Repo
   thiếu hidden gold/scorer, exact ZIP/receipt mapping của submission 3757 và
   upgraded ZIP chưa được upload.

## 13. Test and gate results

| Gate | Result |
|---|---|
| P0 immutable baseline + 4 required JSON files | `PASS` |
| P1 exact 95-question reproduction | `PASS` |
| Targeted retrieval/parser/attribution tests | `106 passed` |
| Raw/A6/retrieval snapshots and identity checks | `PASS` |
| `make snapshots-verify` | `PASS` |
| `make ci` | `PASS`: mypy 85 source files; docs links clean; 2.091 passed, 42 skipped, 27 deselected |
| `make test-integration` | `PASS`: 20 passed, 2.140 deselected |
| Full 1.012 canonical run | `PASS` |
| Submission validator | `PASS`: 0 errors, 0 warnings |
| Replay | `PASS`: 563/563 matched, 0 errors |
| Scorer-facing paired equality | `PASS`: 1.012/1.012 unchanged |
| ZIP checksum equality | `PASS`: exact SHA-256 match |
| Official leaderboard measurement | `NOT_MEASURED` |

Local environment là CPython 3.13.9, SQLite 3.51.0, pandas 2.3.3, NumPy
2.3.5, pytest 8.4.2 và PyYAML 6.0.3. Đây là môi trường chạy local, không được
tuyên bố là hash-locked official acceptance environment.

## 14. Artifact inventory

### Baseline freeze

```text
artifacts/runs/retrieval/table-f2-recovery-baseline-a2d3ef-20260828-01/
├── baseline_manifest.json
├── baseline_metrics.json
├── baseline_environment.json
└── baseline_checksums.json
```

### P1 attribution

```text
artifacts/runs/retrieval/table-f2-recovery-p1-attribution-a2d3ef-20260828-01/
├── stage_attribution.jsonl
├── metrics.json
└── manifest.json
```

### P2–P4 diagnostic sweeps

```text
artifacts/runs/retrieval/table-f2-recovery-p2p4-options-a2d3ef-20260828-01/
├── ranking_audit.json
├── policy_sweep.json
├── binding_sweep.json
├── per_qid_options.jsonl
└── manifest.json
```

### P6 range experiments

```text
artifacts/runs/retrieval/table-f2-recovery-p6-range-eval-a2d3ef-20260828-01/
artifacts/runs/retrieval/table-f2-recovery-p6-range-decoupled-a2d3ef-20260828-01/
artifacts/runs/answer/table-f2-recovery-p6-range-37-a2d3ef-20260828-01/
```

Thư mục `range-eval` là negative result immutable; `range-decoupled` là final
accepted behavior-neutral design.

### Full upgraded run and final comparison

```text
artifacts/runs/answer/table-f2-recovery-upgraded-a2d3ef-20260828-01/

artifacts/runs/evaluation/table-f2-recovery-final-a2d3ef-20260828-01/
├── baseline_metrics.json
├── upgraded_metrics.json
├── paired_metrics.json
├── per_qid_regression.jsonl
├── submission_validation_report.json
├── FINAL_E2E_METRICS.json
├── FINAL_SUBMISSION_MANIFEST.json
├── FINAL_SUBMISSION_SHA256.txt
└── manifest.json
```

## 15. Submission provenance

**Candidate package:**

```text
artifacts/submissions/submission_table-f2-recovery-upgraded-a2d3ef-20260828-01.zip
```

**Size:** 1.030.304 bytes  
**SHA-256:**

```text
a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c
```

SHA này giống hệt frozen baseline ZIP. Upgraded run manifest ghi baseline commit
với `git_dirty: true` vì run được thực hiện sau code changes và trước final
commit. Điều này không làm package mất tính so sánh: candidate output trùng byte
với frozen clean-baseline package có manifest/checksum riêng. Tuy vậy không được
gắn candidate này với một source commit mới như một submission đã cải thiện.

Upload status:

```text
status:        NOT_UPLOADED
submission_id: null
timestamp:     null
receipt:       null
```

Repo không chứa một upload endpoint/CLI/credential flow đủ để nộp và lưu receipt
an toàn. Quan trọng hơn, Phase 11 yêu cầu review trước upload và quyết định hiện
tại là `KEEP BASELINE`; dùng leaderboard slot cho một ZIP byte-identical không
tạo phép thử baseline-vs-upgraded mới. Nếu người sở hữu tài khoản vẫn muốn một
controlled official baseline measurement, phải cung cấp/điều khiển upload target
và sau đó lưu `submission_id ↔ ZIP ↔ SHA-256 ↔ git HEAD ↔ timestamp ↔ receipt`
trong một artifact mới, không sửa các artifact immutable ở trên.

## 16. Final recommendation

### `KEEP BASELINE`

Giữ các thay đổi code sau:

- stage-level observability và binding trace;
- gold-aware attribution trong evalkit;
- reproducible ranking/N/binding audit tools;
- exact full-run comparator;
- semantic year-range hardening với retrieval years tách riêng;
- schema checkpoint `evalkit-12`, ADR và regression tests.

Không promote:

- ranking weight/feature changes;
- fixed hoặc adaptive output-N policy;
- union binding policy;
- parser rewrite/entity resolver rewrite;
- Semantic V3;
- relaxed multi-entity safety gates.

Kết luận thẳng: implementation đã đóng measurement gap và sửa range semantics
an toàn, nhưng **không tạo Table F2 improvement đã được chứng minh**. Muốn nâng
Table F2 thật sự, blocker tiếp theo là một sealed held-out table-evidence gold set
hoặc một controlled official submission có receipt. Trước khi có một trong hai,
mọi promotion từ các local gains hiện tại đều có nguy cơ overfit.
