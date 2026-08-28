# 1. Executive Summary

Semantic V3 ban đầu dừng 198/1.012 câu tại `PARSE` với `METRIC_UNRESOLVED`, trước khi có AST, plan hay candidate. Root cause là `_metric_mentions()` chỉ giữ literal ontology aliases; khi không match, parser làm mất cả surface/span/hypothesis và `_base_expression()` trả `None`. Bản sửa thêm deterministic A6 source-label fallback theo thứ tự exact-first, source binding có provenance, role composition nhiều metric và fail-closed khi ambiguity. Trên clean B0 so với candidate: `OK` tăng 287 → 362, terminal `METRIC_UNRESOLVED` giảm 198 → 0, 102/198 ca tạo AST/plan, 76 tới binder và 75 thành `NEW_OK`; 287 B0 `OK` có zero regression/zero semantic drift. Kết luận: **CONDITIONALLY PASS** cho shadow implementation; **NON-PROMOTABLE** về accuracy vì 93 ca trong reviewer queue chưa được gold adjudication.

# 2. Baseline

Baseline chính thức là isolated clean worktree tại commit `b0d7b84ec0a97ccaec274ae47c4c6d29cd421982`, `git_dirty=false`. Không stash/reset/clean workspace của người dùng. B0 tái hiện chính xác reference 287/725/198 nên denominator và acceptance gates trong plan không đổi.

| Metric | B0 |
| --- | ---: |
| Questions | 1.012 |
| OK | 287 |
| METRIC_UNRESOLVED | 198 |
| Runtime | 48,637 s |

Baseline seal nằm tại `artifacts/runs/semantic-v3/metric-unresolved-b0-clean-20260828/baseline/`, gồm manifest, records, metrics, runtime, H198, diagnostic records và V2 lexical snapshot. Snapshot checks sau implementation đều `PASS`: raw `ca033190f2e9e99f`, A6 `c6887fb633374fad`, retrieval index `872ccb0dda9a2bb6`.

# 3. Root Cause

Code path thực tế trước fix:

1. `SemanticParser.parse()` ở `parser.py:91` gọi exact ontology/formula matching.
2. `_metric_mentions()` ở `parser.py:481` chỉ tạo mention khi normalized question chứa literal alias trong reviewed/reported ontology.
3. Khi alias không match, không còn `QuestionMetricMention`, span, surface hay hypothesis để phân giải.
4. `_base_expression()` ở `parser.py:220` nhận tuple rỗng và trả `None`.
5. Parser phát `METRIC_UNRESOLVED` trước composer/planner.
6. Vì không có `MetricRef` (`ast.py:75`), `compile_execution_plan()` (`planner.py:45`) không chạy, không có `OperandRequest` (`contracts.py:30`) và `SqliteOperandRetriever.retrieve()` (`operand.py:85`) không được gọi.

Root cause do đó là **mention extraction/resolution và compile order ở Semantic V3**, không phải top-K, retrieval ranking hay binder. Audit A6 xác nhận các case đại diện Q5/Q89/Q502/Q870 có source rows execution-ready; Q100 có nhiều variants gần nghĩa nhưng thiếu specificity để chọn an toàn.

# 4. Failure Taxonomy

Taxonomy audit bao phủ đủ frozen H198; từng QID có `qid`, question, operation, return mode, metric surface, hypotheses, source evidence, root cause và terminal reason trong `diagnostic_records.jsonl`.

| Reason | Count | % |
| --- | ---: | ---: |
| METRIC_HYPOTHESES_AMBIGUOUS | 99 | 50,00% |
| QUESTION_MENTION_NO_MAPPING | 91 | 45,96% |
| QUESTION_MENTION_NOT_EXTRACTED | 5 | 2,53% |
| OPERAND_ROLE_UNRESOLVED | 2 | 1,01% |
| METRIC_SOURCE_SPECIFICITY_REQUIRED | 1 | 0,51% |
| **Total** | **198** | **100,00%** |

Proxy tiers được seal riêng: T1=124, T2=55, T3=18, NO_PHRASE=1. Đây là evidence taxonomy, không phải semantic gold.

# 5. Architecture Before

```text
Question
  → Legacy V3 annotations
  → literal ontology/formula matching
  → _metric_mentions()
  → _base_expression()
      └─ no literal alias → None → METRIC_UNRESOLVED

Không có AST → không có plan → không retrieval → không binding/execution
```

Hai khái niệm “question phrase” và “ontology metric” bị gộp thành một phép literal match; multi-role questions cũng bị generic base chặn trước role composer.

# 6. Architecture After

```text
Question
  → existing exact ontology/formula path
  → nếu exact path không resolve:
      QuestionMetricMention
        → scoped A6 MetricHypothesis
        → deterministic unique winner / fail closed
        → source-backed MetricRef + provenance
  → operation-aware role composition
      rank / selected / filter / count predicate
  → AST
  → ExecutionPlan + OperandRequest(source_binding)
  → current retrieval gates
  → current binder/executor/replay
```

Exact path vẫn đi trước và không gọi resolver. Q508 là V3-only boundary: resolver chỉ bổ sung role source không overlap với exact mention; shared V2 lexical frame không đổi.

# 7. Files Changed

| File | Change | Reason |
| --- | --- | --- |
| `configs/semantic/metric_resolution_v1.yaml` | Versioned source build, thresholds và evidence-backed TNDN rule | Deterministic/config-fingerprinted resolution |
| `src/text2pandas/application/parsing/contracts.py` | Mention, hypothesis, result và resolver protocol | Tách mention → hypothesis → resolution |
| `src/text2pandas/application/parsing/parser.py` | Exact-first fallback, source mention conversion, role preservation, count sign predicate, Q508 V3 grammar | Sửa đúng parse/role root cause |
| `src/text2pandas/domain/semantic/ast.py` | Additive `MetricBindingHint` trong `MetricRef` | Truyền provenance mà không promote ontology |
| `src/text2pandas/application/planning/contracts.py` | Additive source binding trong `OperandRequest` | Giữ evidence qua plan |
| `src/text2pandas/application/planning/planner.py` | Validate/materialize source-backed operands | Cho unknown source metric đi tiếp an toàn |
| `src/text2pandas/infrastructure/semantic/a6_metric_resolver.py` | Scoped deterministic SQLite resolver và telemetry | Resolve label/code/path trong đúng entity/period/basis |
| `src/text2pandas/infrastructure/retrieval/operand.py` | Source build/label/code/path/statement validation | Bind observed source row mà không bypass current gates |
| `src/text2pandas/interface/cli/main.py` | Wire resolver, build identity và performance metrics | Full-corpus shadow measurement |
| Các `__init__.py` liên quan | Export additive contracts/adapters | Public architecture boundary |
| `tests/unit/test_a6_metric_resolver_v3.py` | Positive/negative/tie/scope/hierarchy/determinism | Resolver safety |
| `tests/unit/test_semantic_ast_v3.py` | Source-binding và backward-compatible round trip | Schema compatibility |
| `tests/unit/test_planning_and_joint_binding_v3.py` | Source-backed planner test | Không promote global ontology |
| `tests/unit/test_operand_retrieval_v3.py` | Build/path/scope/unit rejection | Không bypass retrieval gates |
| `tests/integration/test_metric_unresolved_recovery_v3.py` | Q5/Q15/Q89/Q100/Q426/Q502/Q508/Q870 | Required regression boundaries |
| `tools/diagnose_metric_unresolved_v3.py` | Seal B0/taxonomy/V2 snapshot | Reproducible audit |
| `tools/evaluate_metric_unresolved_candidate_v3.py` | Funnel/transitions/runtime/safety/review queue | Reproducible before/after proof |

# 8. Implementation Details

Resolver chỉ query execution-ready A6 rows trong annotated entity/period/basis scope. Discovery là label-led; hierarchy được giữ làm binding evidence nhưng không được phép biến unrelated child row thành metric của parent. Threshold v1 yêu cầu ít nhất 3 contiguous tokens, 3-token overlap và source coverage ≥0,600. Source identities chịu được OCR word-boundary loss; note-number suffixes được hợp nhất deterministically. Tie không có unique winner sẽ trả `METRIC_HYPOTHESES_AMBIGUOUS`.

`MetricBindingHint` giữ source build, raw labels, source metric codes, row paths, match method, question surface/span và preferred basis. Planner không thêm source metric vào global ontology. Retriever chỉ chấp nhận hint đúng active A6 build và vẫn áp dụng execution-ready, entity, period, basis, statement type, unit, exact source code/path cùng các gates hiện có.

Source-backed metrics vẫn mang `review_status=source`; divide/growth/subtract/sum/average không được phép đi qua reported-derived policy. COUNT chỉ được compose khi có explicit numeric/sign predicate; đây là role preservation, không phải nới arithmetic policy.

Telemetry candidate: 198 DB cache misses, 1 cache hit, 8,510 s cumulative resolver và 5,822 s DB lookup. Fingerprint resolver là `a4848b2e9b67b7e4e501663a8913211d01f3c779ed0b6e9abd79a5a94cb154cb`.

# 9. Regression Tests

| QID | Parser/plan result | Full-run terminal | Gate result |
| ---: | --- | --- | --- |
| Q5 | Source-backed `Chi phí phạt`, plan + candidate | `OK` | PASS |
| Q15 | Không đủ hierarchy/context cho bare person row | `METRIC_SOURCE_SPECIFICITY_REQUIRED` | PASS, không ép answer |
| Q89 | Versioned paraphrase → `Chi phí thuế TNDN hiện hành`, code 51 | `OK` | PASS |
| Q100 | Nhiều share variants, không unique specificity | `METRIC_SOURCE_SPECIFICITY_REQUIRED` | PASS |
| Q426 | Không shortcut generic base | `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | PASS, role-specific abstain |
| Q502 | `SelectAtArg` với rank/selected metric IDs khác nhau; planner giữ consumer paths | `METRIC_REJECT_ALL` | PASS semantic boundary; defer retrieval outcome |
| Q870 | `COUNT(Filter(metric < 0))`; plan giữ source predicate | `SCALE_UNKNOWN` | PASS semantic boundary; defer execution scale |
| Q508 | `SelectAtArg`; rank=`Chi phí chờ phân bổ`, selected=exact `lãi thuần…` | `METRIC_REJECT_ALL` | PASS boundary; không còn flat maximum |

Test results:

- Targeted pytest suite: 57 passed, 0 failed; 3 static gates (`lint`, `typecheck`, `docs-check`) cũng pass.
- `make lint`: pass.
- `make typecheck`: pass trên 85 production source files.
- `make test-offline`: 2.076 passed, 42 skipped, 27 deselected.
- `make test-integration`: 20 passed, 7 failed. Cả 7 fail do thiếu pre-existing materialized legacy artifacts (`submission_C1R_LOCAL.zip`, `submission_P0G2.zip`, `determinism_report_v2.json`), không do code path này; targeted integration liên quan đều pass.
- Snapshot verification: tất cả raw/A6/retrieval checks pass.

# 10. Full Corpus Results

Các funnel metrics `AST_CREATED` đến `BINDER_REACHED` dưới đây được đo riêng trên frozen H198; OK/METRIC totals là full 1.012 corpus.

| Metric | Before | After | Delta |
| --- | ---: | ---: | ---: |
| OK | 287 | 362 | +75 |
| METRIC_UNRESOLVED | 198 | 0 | -198 |
| AMBIGUOUS | 0 | 10 | +10 |
| AST_CREATED (H198) | 0 | 102 | +102 |
| PLAN_CREATED (H198) | 0 | 102 | +102 |
| CANDIDATE_AVAILABLE (H198) | 0 | 102 | +102 |
| BINDER_REACHED (H198) | 0 | 76 | +76 |
| NEW_OK (H198) | 0 | 75 | +75 |
| REGRESSION (B0 OK) | 0 | 0 | 0 |

T1 gates: 124/124 rời umbrella terminal reason, 74/124 tạo AST/plan (gate ≥60), 74/124 có candidate và 56/124 tới binder (gate ≥40), 55/124 thành `OK`. Cần đọc “124 rời umbrella” cùng funnel: 50 T1 vẫn abstain trước AST với reason cụ thể, không được tính là semantic recovery.

75 new-OK QIDs: `5, 20, 26, 39, 42, 52, 65, 74, 75, 78, 89, 94, 95, 97, 103, 106, 110, 115, 116, 117, 120, 129, 133, 134, 137, 140, 150, 156, 158, 161, 162, 165, 166, 187, 191, 194, 200, 215, 217, 219, 223, 238, 243, 248, 252, 260, 262, 263, 266, 269, 270, 274, 277, 287, 296, 300, 305, 306, 314, 330, 333, 338, 339, 355, 359, 657, 682, 683, 703, 704, 725, 726, 815, 925, 969`.

Machine-readable list và reviewer queue nằm trong `artifacts/runs/semantic-v3/metric-unresolved-candidate-v1-20260828/evaluation/`.

# 11. Failure Transition Matrix

| Before | After | Count |
| --- | --- | ---: |
| METRIC_UNRESOLVED | OK | 75 |
| METRIC_UNRESOLVED | METRIC_SOURCE_SPECIFICITY_REQUIRED | 47 |
| METRIC_UNRESOLVED | REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION | 22 |
| METRIC_UNRESOLVED | BINDING_TIE | 19 |
| METRIC_UNRESOLVED | METRIC_HYPOTHESES_AMBIGUOUS | 10 |
| METRIC_UNRESOLVED | METRIC_REJECT_ALL | 7 |
| METRIC_UNRESOLVED | BINARY_OPERANDS_UNRESOLVED | 6 |
| METRIC_UNRESOLVED | QUESTION_MENTION_NO_MAPPING | 4 |
| METRIC_UNRESOLVED | AGGREGATE_AXIS_UNRESOLVED | 3 |
| METRIC_UNRESOLVED | LOOKUP_SCOPE_NON_SCALAR | 2 |
| METRIC_UNRESOLVED | COUNT_PREDICATE_EXPRESSION_UNRESOLVED | 1 |
| METRIC_UNRESOLVED | SCALE_UNKNOWN | 1 |
| METRIC_UNRESOLVED | SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED | 1 |
| OK | OK | 287 |
| OK | REGRESSION | 0 |

Chỉ 75 transition tới `OK` được gọi là new-OK. 47 specificity, 10 ambiguity và các downstream abstentions không được gọi là recovered answer.

# 12. Accuracy / Correctness

Kết quả chứng minh **coverage và semantic reachability**, không chứng minh answer accuracy tăng. 75 new answers chưa có sealed gold/adjudication; review queue gồm 93 cases (mọi new OK, toàn bộ T3 và role/boundary risks) đang `UNADJUDICATED`. Vì vậy trạng thái accuracy là **NON-PROMOTABLE**.

Correctness evidence hiện có:

- Q5/Q89 source bindings khớp trực tiếp A6 label/code/path và replay đúng.
- Q100/Q15 fail closed thay vì arbitrary top-1.
- Q502/Q508/Q870 giữ đúng role AST dù terminal downstream chưa `OK`.
- 287 B0 `OK` không đổi status, AST, plan, answer hay evidence semantics.
- Source hint mismatch về build/path/code/scope/unit bị test reject.

Không tuyên bố precision/accuracy cho 75 new answers trước reviewer adjudication. `review_queue.jsonl` là artifact bắt buộc cho bước đó.

# 13. Performance

| Metric | Value | Gate | Result |
| --- | ---: | ---: | --- |
| B0 runtime | 48,637 s | reference | — |
| Candidate cold runtime | 64,658 s | ≤120 s | PASS |
| Delta vs B0 | +16,021 s / +32,94% | informative | — |
| Warm runs | 63,219 s; 61,427 s | — | — |
| Warm median | 62,323 s | ≤90 s | PASS |
| Resolver cumulative | 8,510 s | ≤45 s | PASS |
| DB lookup cumulative | 5,822 s | included | PASS |
| Cache hit/miss | 1 / 198 | measured | — |
| Peak RSS | 461.586.432 bytes (440,2 MiB) | measured | — |

Direct read-only SQLite implementation đáp ứng absolute gates; không kích hoạt materialized semantic label index contingency.

# 14. Safety / Regression

| Gate | Result |
| --- | ---: |
| B0 OK regressions | 0/287 |
| B0 OK semantic drift | 0/287 |
| V2 lexical drift | 0/1.012 |
| V2 snapshot SHA before/after | `c31d306cccfe3ae39a9600436a22092caf5415ec4e8f5d9302134464eb3b68cc` |
| Deterministic rerun mismatches | 0/1.012 trên cả 2 reruns |
| Mechanically detectable unsafe emissions | 0 |
| New typed/Pandas replay mismatches | 0 |
| Package validation errors | 0 |
| Package replay | 362 executed / 362 matched / 0 errors |

“Unsafe emission = 0” ở đây là structural gate: mọi emitted `OK` có evidence và `PANDAS_REPLAY=MATCH`. Nó không thay thế semantic gold review; phần đó vẫn `NON-PROMOTABLE` như Mục 12.

# 15. Remaining Failures

Trong H198, 75 thành `OK`, còn 123 abstain. Umbrella exact `METRIC_UNRESOLVED` bằng 0, nhưng 61 câu vẫn là metric-resolution-specific abstentions: 47 specificity, 10 ambiguity và 4 no mapping.

| Remaining terminal reason trong H198 | Count |
| --- | ---: |
| METRIC_SOURCE_SPECIFICITY_REQUIRED | 47 |
| REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION | 22 |
| BINDING_TIE | 19 |
| METRIC_HYPOTHESES_AMBIGUOUS | 10 |
| METRIC_REJECT_ALL | 7 |
| BINARY_OPERANDS_UNRESOLVED | 6 |
| QUESTION_MENTION_NO_MAPPING | 4 |
| AGGREGATE_AXIS_UNRESOLVED | 3 |
| LOOKUP_SCOPE_NON_SCALAR | 2 |
| COUNT_PREDICATE_EXPRESSION_UNRESOLVED | 1 |
| SCALE_UNKNOWN | 1 |
| SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED | 1 |
| **Total remaining** | **123** |

Danh sách từng QID cùng tier, AST/plan/candidate/binder flags nằm ở `remaining_h198.jsonl`. Các downstream reasons được đo và defer; không có retrieval-ranking, top-K, binder threshold hay reported-derived policy nào bị sửa trong task này.

# 16. Decision

**CONDITIONALLY PASS.**

Lý do pass về implementation: clean B0 tái lập; coverage gates đạt; 102 AST/plan, 76 binder, 75 new OK; zero regression/V2 drift/replay mismatch; deterministic reruns; performance dưới absolute budgets; package 1.012 records validate/replay sạch.

Điều kiện còn thiếu: reviewer/gold adjudication cho 93-case queue chưa hoàn thành, nên không được promote hoặc tuyên bố answer accuracy tăng. Bảy full integration failures do thiếu legacy materialized artifacts cũng cần được materialize bởi owner của H0 nếu muốn toàn repository integration gate xanh; chúng không thuộc `METRIC_UNRESOLVED` và không được sửa trong task này.

# 17. Next Bottleneck

Sau khi reviewer adjudication của resolver hoàn tất, bottleneck đơn tiếp theo theo full-corpus terminal count là `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` (162 cases). Báo cáo này chỉ xác định và defer bottleneck đó; không thay đổi policy của nó.
