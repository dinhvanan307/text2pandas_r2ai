# PHASE 1 — AUDIT & FIX PARSER / SEMANTIC FRAME

Ngày audit: 2026-08-29

Phạm vi: Canonical V2 public pipeline; Semantic V3 chỉ được audit như shadow path

Active snapshot: raw `ca033190f2e9e99f`, A6 `c6887fb633374fad`, retrieval `872ccb0dda9a2bb6`

# 1. EXECUTIVE DECISION

**PHASE 1 STATUS: FAIL theo phase gate tổng thể; PASS cho minimal entity fix.**

Không thể tuyên bố toàn bộ Phase 1 `PASS` vì repository chưa có Parser Gold
Set 100–300 QID do người độc lập gán nhãn. Registry hiện ghi semantic parser
gold có 40 records, chỉ 6 records full-agreement usable, không có record nào
promotion-eligible. Vì vậy Metric Accuracy, Operand Role Accuracy và Full
Semantic Frame Exact Match vẫn là `NOT_MEASURED`.

Tuy nhiên audit đã phát hiện và sửa một parser-boundary defect có bằng chứng
nhân quả:

- `parse_intent` phân giải đúng entity theo alias có quản trị;
- generic `QuestionSemanticFrame` lại quét mọi acronym viết hoa và có thể ghi
  đè entity đúng, ví dụ `CTCP Chứng khoán FPT` thành `FPT` thay vì `FTS`;
- 32/1.012 câu single-entity trong full run có frame entity khác canonical
  target; cả 32 đều abstain trước fix, 30 câu dừng tại
  `BIND:UNBOUND_OPERANDS`;
- sau fix, 22/32 câu qua đủ execution gates;
- full corpus tăng `563 → 585` emitted answers, không mất old-OK nào và không
  có value/evidence/table drift trên 563 old-OK;
- package vẫn có 1.012 records, validator 0 lỗi, clean replay `585/585` match.

Đây là **coverage uplift**, chưa phải Answer Accuracy hay Execution Accuracy
uplift vì 22 answer mới chưa có independent answer gold.

Trả lời câu hỏi quan trọng nhất:

> Sau khi đọc code và đo parser trên gold set, Parser hiện tại có thực sự là
> bottleneck đủ lớn để đáng sửa trước Metric Resolver không?

**PARTIALLY.**

Evidence:

1. Entity SSOT defect trực tiếp gây 30/40 `BIND:UNBOUND_OPERANDS` trong baseline
   full run và minimal fix cứu 22 câu.
2. Trên 40-case diagnostic semantic set, các field đo được đã cao: entity
   39/40; basis, operation, unit và result kind 40/40; period 29/29.
3. Metric và operand-role correctness không đo được do agreement lần lượt chỉ
   `0,175`, `0,250` và `0,150`; không có bằng chứng để tiếp tục rewrite parser
   metric/operand trước Resolver.

Estimated affected QIDs: **32 QID trực tiếp**, **22 QID chuyển sang OK**, tương
đương `+2,174%` corpus coverage; correctness impact chính thức
`NOT_MEASURED`. Confidence: **HIGH** cho entity-boundary cause và no-regression;
**LOW** cho public accuracy uplift.

# 2. ACTUAL PARSER ARCHITECTURE

Public CLI `run` gọi `run_canonical_pipeline`; đây là Canonical V2. Semantic V3
chỉ chạy qua lệnh `shadow-v3`, không phải public composition root.

| Stage | File | Class/Function | Input | Output | Used in public path? |
|---|---|---|---|---|---|
| preprocessing | [`normalize.py`](../../src/text2pandas/pipelines/retrieval/normalize.py) | `ascii_compact`, `ascii_words`, alias boundary helpers | question | normalized words/compact form | **YES** |
| entity/scope/period intent | [`question_intent.py`](../../src/text2pandas/pipelines/retrieval/question_intent.py) | `parse_intent`, `Intent` | question + governed aliases | targets, ordered tickers, years, scope, mode | **YES — ACTIVE** |
| unit parsing | [`adapters.py`](../../src/text2pandas/pipelines/answering/adapters.py) | `requested_unit_of` | question | `Unit` | **YES — ACTIVE** |
| operation parsing | [`frame.py`](../../src/text2pandas/pipelines/answering/frame.py) | `classify_operation` | question | `OperationHint` | **YES — ACTIVE** |
| generic semantic frame | [`frame.py`](../../src/text2pandas/pipelines/answering/frame.py) | `parse_question`, `QuestionSemanticFrame` | question + normalized entity/unit | scalar semantic frame | **YES — ACTIVE for generic route** |
| normalization bridge | [`canonical_run.py`](../../src/text2pandas/application/usecases/canonical_run.py) | `run_canonical_pipeline` | `Intent.targets[0]` | `resolved_entity` injected into frame | **YES — FIXED** |
| validation/compile | [`router.py`](../../src/text2pandas/pipelines/answering/router.py) | `route` | `QuestionSemanticFrame` | `OperationIR` or named abstention | **YES — ACTIVE** |
| special semantic routes | `entity_*`, `count_engine.py`, `formula_engine.py` under [`pipelines/answering`](../../src/text2pandas/pipelines/answering/) | operation-specific functions | question + `Intent` fields | bound/executed result | **YES — ACTIVE, bypass generic frame** |
| V3 annotation | [`legacy_annotator.py`](../../src/text2pandas/infrastructure/semantic/legacy_annotator.py) | deterministic annotator | question | `QuestionAnnotations` | **NO — shadow only** |
| V3 AST parser | [`parser.py`](../../src/text2pandas/application/parsing/parser.py) | `SemanticParser.parse` | annotations + ontology/resolver | validated `QuestionAST` | **NO — shadow only** |

Actual Canonical V2 flow:

```text
Question
  ├─ parse_intent(question, governed aliases)
  │    └─ entity targets, scope, years, mode
  ├─ requested_unit_of(question)
  ├─ classify_operation(question)
  ├─ special engine, nếu match
  └─ generic answer_question
       └─ parse_question(..., resolved_entity=Intent.targets[0])
            └─ QuestionSemanticFrame → route → OperationIR
```

Architecture type: **hybrid deterministic rules** gồm regex, normalized alias
dictionary, precedence-ordered operation patterns và typed post-processing.
Canonical path không gọi LLM, không có temperature/retry/model fallback.

# 3. ACTIVE SEMANTIC SSOT

```text
ACTIVE SEMANTIC SSOT:
Không có một SSOT duy nhất cho Canonical V2.

ACTIVE COMPONENTS:
- Intent: entity/scope/year/mode used by retrieval and special answer engines.
- QuestionSemanticFrame: generic answer route.
- OperationIR/OperandSlot: compiled operation and ordered roles.

LEGACY:
- src/text2pandas/answer_pipeline/: compatibility import shim.
- tools/answer_v2/: historical/tooling path, not imported by production code.
- application/usecases/run_pipeline.py: older non-canonical pipeline.

EXPERIMENTAL / SHADOW:
- domain.semantic.QuestionAST + application.parsing.SemanticParser: V3 shadow.
- QuestionSemanticFrameV2 in pipelines/answering/spec.py: schema frozen,
  explicitly not wired into live router.

DUPLICATED CONCEPTS:
- entity/year/basis: Intent vs QuestionSemanticFrame vs QuestionAST.
- operation: string OperationHint/OperationIR vs V3 enums/nested AST.
- result kind: pipelines/answering/result_kind.py vs domain/semantic/types.py.
- filter/operand semantics: answering/spec.py vs V3 Filter/MetricRef AST.
- answer typing: pipelines/a6/answer_contract.AnswerSpec is a separate legacy
  quantity contract, not the parser frame.
```

Trước fix, field `Intent.targets` bị transform nhưng không được truyền vào
generic frame. Frame tự parse entity lần hai; đây là field-loss/overwrite giữa
hai semantic layers. Fix chỉ nối lại field đã được normalize, không tạo schema
thứ ba.

V3 `QuestionAST` là semantic model đầy đủ nhất trong repository, nhưng theo ADR
0008 và migration status nó chưa phải public SSOT. Không được dùng shadow AST
để âm thầm thay Canonical V2.

# 4. CURRENT SEMANTIC CONTRACT

Contract tối thiểu sau audit:

| Field | Meaning | Required? | Source hiện tại | Confidence/provenance |
|---|---|---:|---|---|
| entity | canonical reporting company cho single-entity route | có với public answer | `Intent.targets[0]` | `entity_source=canonical_intent`; fail closed nếu không resolve |
| entities | ordered/set entity domain | có cho multi-entity | `Intent.targets` | `resolved_by`, `mode`; chưa nằm trong scalar frame |
| metric phrase | phrase/concept người dùng nêu, chưa map Silver row | có về semantic | raw question/ontology boundary | **không được preserve trong V2 frame** |
| metric id | canonical metric sau Resolver | không phải parser lexical responsibility | resolver/ontology | V2 generic thường `null`; không được forced guess |
| period(s) | year/date domain, kể cả range | có | `Intent.years`, frame `periods` | deterministic; year-set mismatch `0/1.012` |
| period role | current/previous/opening/closing | có khi explicit | question cues + A6 period semantics | scalar frame chưa biểu diễn đủ per operand |
| basis | consolidated/separate/unspecified | khi explicit | `Intent.answer_basis`, frame regex | mixed-basis per operand chưa biểu diễn được |
| unit | requested display dimension/scale | khi explicit hoặc inferable by result | `requested_unit_of` | deterministic; conversion downstream |
| operation | lookup/divide/subtract/growth/sum/avg/count/extremum | có | `classify_operation` | reason/matched cue preserved |
| result kind | scalar/period/entity/count/ratio semantics | có | return mode + unit/router | V2 taxonomy phân tán |
| operands | ordered semantic roles | bắt buộc cho non-commutative op | `OperationIR.ROLE_SPEC` | role có; per-role metric phrase/id chưa đủ |

Responsibility boundary được giữ như sau:

```text
PARSER
  entity mention + canonical entity reference
  metric phrase/concept
  periods/basis/unit request
  operation/result kind/ordered roles
        ↓
METRIC RESOLVER
  metric phrase → canonical metric_id
        ↓
SELECTOR/BINDER
  metric_id + axes → actual observation row/cell
```

Phase này chỉ sửa entity normalization bridge. Không cho parser chọn Silver row,
không thêm metric ontology và không thay selector.

# 5. PARSER GOLD SET

Repository hiện có bộ diagnostic stratified 40 QID tại
[`semantic_gold.jsonl`](../../data/curated/gold/semantic_gold.jsonl), chọn theo
14 nhóm như lookup, divide/ratio, growth, subtraction/percentage-point,
aggregation, count, multi-entity, nested và arg-extreme-period. Coverage matrix
nằm tại [`coverage_matrix.json`](../../data/curated/gold/coverage_matrix.json).

Giới hạn governance:

| Thuộc tính | Giá trị |
|---|---:|
| Records | 40 |
| RESOLVED | 6 |
| AMBIGUOUS | 4 |
| UNRESOLVED | 30 |
| Case-level full agreement | 6/40 = 15% |
| Metric-set agreement | 7/40 = 17,5% |
| Operand-role agreement | 10/40 = 25% |
| Operand-role + metric agreement | 6/40 = 15% |
| Promotion-eligible | 0 |

Lý do không tự tạo “gold” 100–300 QID trong turn này: gold hợp lệ yêu cầu hai
annotator độc lập, một adjudicator khác, source-evidence review và blind model
outputs theo [`independent_gold_protocol_v1.yaml`](../../configs/evaluation/independent_gold_protocol_v1.yaml).
Tự gán nhãn bằng chính agent sửa parser sẽ tạo prediction leakage và vi phạm
nguyên tắc “không sửa vì đoán”.

Raw baseline 40 QID, chứa question, gold semantic và predicted public semantic,
được ghi tại
[`parser_baseline.jsonl`](../../artifacts/audits/parser-phase1-baseline-20260829/parser_baseline.jsonl),
SHA-256 `dfff7c6eb399da9ab20440f6ea124ffb0d08216c89ede5f5fb31e89d69d877ef`.

# 6. BASELINE MEASUREMENT

Diagnostic score được tái chạy trước fix từ evaluator hiện có. Đây là
diagnostic evidence, không phải promotion accuracy.

| Field | Correct / Scored | Accuracy | Status |
|---|---:|---:|---|
| Entity first in gold | 39/40 | 97,5% | DIAGNOSTIC |
| Entity set exact | 39/40 | 97,5% | DIAGNOSTIC |
| Basis | 40/40 | 100% | DIAGNOSTIC |
| Basis explicitness | 40/40 | 100% | DIAGNOSTIC |
| Period exact | 29/29 | 100% | DIAGNOSTIC; 11 không có agreed gold |
| Unit dimension/full | 40/40 | 100% | DIAGNOSTIC |
| Operation family strict | 40/40 | 100% | DIAGNOSTIC |
| Result kind | 40/40 | 100% | DIAGNOSTIC |
| Metric exact | — | — | `NOT_MEASURED` |
| Operand roles exact | — | — | `NOT_MEASURED` |
| Operand-role metric match | — | — | `NOT_MEASURED` |
| Full semantic frame exact | — | — | `NOT_MEASURED` |

Machine-readable summary:
[`parser_vs_gold_summary.json`](../../artifacts/audits/parser-phase1-baseline-20260829/parser_vs_gold_summary.json),
SHA-256 `606dd36b54582c42bb1eea4b657ea74c083c1ff712de25bf8d41296cf33a5bbd`.

Full-corpus structural baseline trước fix:

| Measurement | Result |
|---|---:|
| Questions | 1.012 |
| `Intent.targets` vs lexical frame entity tuple mismatch | 462 |
| Single-target + non-null wrong frame entity | 32 |
| 32 affected QIDs answered | 0 |
| Affected QIDs stopped at `BIND:UNBOUND_OPERANDS` | 30 |
| Canonical default emitted answers | 563 |

Full-corpus counterfactual sau fix:

| Measurement | Before | After | Delta |
|---|---:|---:|---:|
| Emitted answers | 563 | 585 | +22 |
| Abstentions | 449 | 427 | -22 |
| Lost old-OK | — | 0 | 0 |
| Old-OK value drift | — | 0/563 | 0 |
| Old-OK evidence drift | — | 0/563 | 0 |
| Old-OK table-ref drift | — | 0/563 | 0 |
| Clean replay | 563/563 baseline | 585/585 | +22 replayable |

Post-fix records:
[`records.jsonl`](../../artifacts/runs/answer/parser-phase1-entity-bridge-full-20260829/records.jsonl),
SHA-256 `2e9bd66aadb248dfd1ed1da815e24479bd51e505d31b68c55c38c6135edd8bca`.

# 7. FAILURE BREAKDOWN

| Failure | Count | % corpus | Example QID | Root cause / boundary |
|---|---:|---:|---:|---|
| `WRONG_NORMALIZATION / ENTITY_SSOT_CONFLICT` | 32 | 3,162% | 4 | lexical frame đọc acronym nội bộ thay canonical entity |
| `BIND:UNBOUND_OPERANDS` attributable to entity conflict | 30 | 2,964% | 46 | parser output tạo impossible entity constraint; **parser boundary** |
| Remaining after entity fix | 10/32 | 0,988% | 596 | unit/policy/unsupported operation; **downstream report-only** |
| `WRONG_BASIS_REPRESENTATION` structural disagreements | 4 | 0,395% | 952 | 3 `BCTC riêng` lexical variants + 1 mixed-basis question |
| `WRONG_PERIOD` by year-set comparison | 0 | 0% | — | `Intent` và frame preserve cùng year domain |
| `WRONG_OPERATION` on agreed diagnostic fields | 0/40 | 0% diagnostic | — | operation precedence currently passes measured slice |
| `WRONG_UNIT` on agreed diagnostic fields | 0/40 | 0% diagnostic | — | unit scanner passes measured slice |
| `MISSING_METRIC_PHRASE / PER_ROLE_METRIC` | unknown | `NOT_MEASURED` | 672 | frame lacks field; gold agreement insufficient |
| `AMBIGUOUS` gold records | 4/40 | 10% diagnostic | varies | must preserve/abstain, not forced guess |
| `UNRESOLVED` gold records | 30/40 | 75% diagnostic | varies | annotation/gold blocker, not parser error count |

Không quy các abstention còn lại thành parser failures:

- `MULTI_ENTITY_OPERATION_NOT_SUPPORTED = 177`: route/engine coverage;
- `EXTREMUM_SELECT_AT_ARG_REQUIRES_TWO_METRICS = 32`: metric/operand contract
  hoặc resolver/planner dependency;
- `DIVIDE_REQUIRES_REVIEWED_FORMULA = 27`: formula/metric resolution policy;
- unit dimension mismatch, cross-basis, cross-period metric drift: binding,
  unit contract hoặc source-selection boundary.

# 8. ROOT CAUSES

1. **Hai entity parsers trong cùng public request.** `parse_intent` dùng alias
   normalization và longest-name rules; `QuestionSemanticFrame` trước fix chỉ
   lấy acronym đầu tiên không nằm trong stop-list.
2. **Normalized entity bị mất khi chuyển layer.** Canonical runner đã có đúng
   `Intent.targets[0]` nhưng generic `answer_question` không nhận field đó.
3. **Scalar semantic frame không phải SSOT đầy đủ.** `entities[]`, metric phrase,
   per-operand metric, period role và basis role chưa đồng nhất.
4. **Operation-specific engines bypass generic frame.** Hành vi public không thể
   đo bằng cách chỉ gọi `parse_question()` cô lập.
5. **Gold không đủ cho metric/operand decisions.** Agreement thấp làm mọi
   schema expansion ở đây có nguy cơ mã hóa assumption của implementation.

Ví dụ causal:

```text
QID 4: CTCP Chứng khoán FPT

parse_intent       → FTS
old generic frame  → FPT
candidate pool     → FTS observations
old binding        → UNBOUND

new generic frame  → FTS, source=canonical_intent
new binding        → OK
```

# 9. MINIMAL FIX DESIGN

Fix gồm ba thay đổi hành vi nhỏ:

1. `parse_question` nhận optional `resolved_entity` từ canonical normalizer.
2. `QuestionSemanticFrame` ghi `entity_source` để trace phân biệt normalized
   entity và lexical ticker fallback.
3. Canonical single-entity generic route truyền `Intent.targets[0]` vào frame.

Fallback standalone vẫn giữ nguyên: caller không truyền normalized entity thì
frame tiếp tục dùng lexical ticker. Multi-entity special routes không thay đổi.

Không thay đổi:

- retrieval query, top-k, score hoặc candidate pool;
- metric resolver/ontology;
- selector scoring;
- planner/router operation taxonomy;
- executor, unit conversion hoặc answer generation.

Ambiguity policy hiện hành:

- canonical entity resolve đúng một target → accept deterministic reference;
- zero target → public answer fail closed;
- nhiều target → giữ ordered/set domain và đi special multi-entity route;
- metric ambiguity → không forced guess; vẫn là Resolver/Phase 2 dependency.

# 10. FILES TO CHANGE

| File | Existing responsibility | Change | Why | Risk |
|---|---|---|---|---|
| [`frame.py`](../../src/text2pandas/pipelines/answering/frame.py) | lexical semantic frame | thêm `resolved_entity`, `entity_source` | preserve canonical normalization | Low; optional API |
| [`pipeline.py`](../../src/text2pandas/pipelines/answering/pipeline.py) | frame→route→bind orchestration | forward normalized entity | keep downstream contract explicit | Low |
| [`canonical_run.py`](../../src/text2pandas/application/usecases/canonical_run.py) | public composition root | inject `Intent.targets[0]` | remove duplicate entity interpretation | Low; single-target only |
| [`test_question_frame_regressions.py`](../../tests/unit/test_question_frame_regressions.py) | parser unit regressions | normalized override + lexical fallback tests | prevent SSOT loss | None runtime |
| [`test_pipeline_e2e.py`](../../tests/test_pipeline_e2e.py) | semantic pipeline contract | FTS frame→IR→binding test | prove downstream compatibility | None runtime |

Không sửa `spec.py` hoặc V3 AST vì đó sẽ tạo/wire một semantic path mới khi
metric/operand gold chưa đủ.

# 11. TEST PLAN

| Test | Purpose | Expected | Actual |
|---|---|---|---|
| parser unit: FTS legal name | canonical entity overrides internal acronym | frame entity `FTS` | PASS |
| parser unit: lexical fallback | preserve standalone API | frame entity `VCB` | PASS |
| schema contract E2E | normalized entity survives frame→IR→bind | slot/entity `FTS`, result OK | PASS |
| 5-QID causal smoke | former entity failures reach execution | 5/5 OK | PASS |
| 32-QID affected cohort | measure recovery and remaining boundaries | no wrong-entity bind failure | 22 OK, 10 named downstream abstain |
| full corpus regression | no old-OK loss/drift | zero significant regression | PASS: 0/563 drift/loss |
| submission contract | 1.012 records, valid refs/schema | 0 errors | PASS |
| clean replay | every emitted query reproduces answer | 585/585 | PASS |
| static gates | Ruff + strict mypy | 0 errors | PASS, 85 typed files |
| offline suite | unit/contract/regression | 0 failure | PASS: 2.105 passed, 42 approved skips |
| integration suite | materialized active snapshot contracts | 0 failure | PASS: 22 passed |
| parser gold full-frame | semantic exact over independent gold | measurable | **BLOCKED / NOT_MEASURED** |

# 12. EXPERIMENT PLAN

| Experiment | Isolation | Result | Decision |
|---|---|---|---|
| EXP-0 | current parser diagnostic baseline | field scores measured where gold agrees | complete |
| EXP-1 | entity provenance + normalized bridge only | +22 emitted, zero old-OK drift | **accept fix** |
| EXP-2 | operation/period/operand interpretation | operation and period already pass measured fields; operand unmeasured | do not modify |
| EXP-3 | metric phrase extraction | no reliable metric gold | blocked; do not implement blindly |
| EXP-4 | ambiguity/confidence/fallback | deterministic entity source now visible; metric confidence unmeasured | defer |
| EXP-5 | full regression + package/replay | all technical gates pass | complete |

Causal success statement được giới hạn chính xác:

```text
Entity semantic consistency ↑
AND downstream-compatible binding coverage ↑ by 22 QIDs
AND old-OK regression = 0
```

Không được đổi thành “Parser Accuracy tổng thể tăng” vì full semantic gold chưa
có, và không được đổi thành “Execution Accuracy tăng” vì scorer gold là hidden.

# 13. ACCEPTANCE GATE

Gate điều chỉnh theo evidence hiện có:

| Gate | Threshold/condition | Actual | Verdict |
|---|---|---|---|
| Entity diagnostic | ≥97% trên agreed fields | 97,5% | PASS diagnostic |
| Period diagnostic | ≥95% | 100% trên 29 | PASS diagnostic |
| Basis diagnostic | ≥95% | 100% trên 40 | PASS diagnostic |
| Unit diagnostic | ≥95% | 100% trên 40 | PASS diagnostic |
| Operation diagnostic | ≥95% | 100% trên 40 | PASS diagnostic |
| Metric phrase/concept | ≥95% trên controlled gold | `NOT_MEASURED` | FAIL/BLOCKED |
| Operand roles | ≥95% trên controlled gold | `NOT_MEASURED` | FAIL/BLOCKED |
| Full frame exact | ≥90% trên ≥100 stratified independent records | `NOT_MEASURED` | FAIL/BLOCKED |
| No significant regression | zero lost old-OK; no old-OK value/evidence drift | 0/563 | PASS |
| Downstream schema/replay | zero validation/replay mismatch | 0; 585/585 | PASS |

Threshold của các field diagnostic không đủ để promote vì `n=40`, independence
`NONE`, promotion-eligible `0`. Gate quan trọng nhất “No significant
regression” đã pass, nhưng phase gate tổng thể vẫn fail closed.

# 14. IMPLEMENTATION PLAN

Đã hoàn thành:

1. Trace public composition root và phân loại active/legacy/shadow.
2. Re-run diagnostic baseline trước sửa.
3. Đo 1.012-question cross-parser entity/period/basis consistency.
4. Isolate 32-QID wrong non-null entity cohort.
5. Implement normalized entity bridge và provenance.
6. Run unit/schema tests, 5-QID smoke, 32-QID cohort và full 1.012 E2E.
7. Compare per-QID old/new; validate package và clean replay.

Còn bắt buộc để Phase 1 PASS:

1. Tạo 100–300 QID stratified packet theo contract ở Mục 4, không chứa
   prediction.
2. Hai annotator độc lập hoàn tất entity mention/reference, metric phrase,
   periods/roles, basis, unit, operation, result kind và operands.
3. Adjudicator thứ ba xử lý disagreements, review source evidence và seal
   checksum release.
4. Chạy parser baseline trên release đó; xuất per-field accuracy, full exact và
   failure taxonomy.
5. Chỉ implement thêm parser changes nếu failure count chứng minh cần thiết.

# 15. RISKS / REGRESSIONS

1. **22 new answers chưa được adjudicate.** Replay chứng minh tính tái lập, không
   chứng minh metric/row semantic correctness.
2. **Alias resolution trở thành hard entity constraint.** Risk được giảm vì
   candidate pool đã dùng cùng `Intent.targets`; full regression có zero old-OK
   drift.
3. **Entity mention vs canonical reference bị trộn trong một field.**
   `entity_source` làm provenance rõ hơn nhưng V2 vẫn chưa giữ raw mention span.
4. **Mixed basis chưa biểu diễn per operand.** QID 952 không thể sửa bằng scalar
   `basis`; cần typed operands và gold, không thêm regex.
5. **Metric phrase vẫn mất trong V2 frame.** Selector đọc raw question nên lookup
   có thể chạy, nhưng multi-metric composition vẫn yếu; đây là ranh giới sang
   Resolver/typed semantic work.
6. **Diagnostic set nhỏ và correlated.** Các accuracy 100% có confidence thấp;
   không ngoại suy thành 1.012-question accuracy.

# 16. PHASE 1 DEFINITION OF DONE

```text
[x] Active parser path đã được xác định
[x] Semantic SSOT đã được audit — kết luận: Canonical V2 chưa có một SSOT duy nhất
[ ] Parser gold set 100–300 independent đã có
[x] Current parser diagnostic baseline đã được đo
[x] Failure taxonomy đã có
[x] Parser semantic contract tối thiểu đã được định nghĩa
[x] Entity field-loss đã được chứng minh bằng full-corpus trace
[ ] Metric phrase/operand missing fields đã được đo bằng reliable gold
[x] Minimal entity fix đã được implement
[x] Unit tests pass
[x] Existing diagnostic gold tests pass
[x] Regression tests pass
[x] Downstream contract/package/replay pass
[ ] Full parser evaluation trên sealed independent gold pass
```

```text
PHASE 1 STATUS:
FAIL

Parser accuracy:
Field-level diagnostic only; xem Mục 6.

Full semantic frame accuracy:
NOT_MEASURED.

Regression:
0 lost old-OK; 0 value/evidence/table drift trên 563 old-OK.

Remaining parser failures:
Metric phrase, per-role metric/period/basis và full-frame failures chưa đo được.

Downstream issues discovered:
Multi-entity routing, select-at-arg two-metric composition, reviewed formula
coverage, unit mismatch, cross-basis/cross-period binding.

Recommended Phase 2:
Chưa tự động bắt đầu. Hoàn tất independent semantic gold trước; sau đó chỉ mở
Metric Resolution nếu metric/operand measurements xác nhận bottleneck.
```

# 17. PHASE 2 RECOMMENDATION

**Không tự động chuyển production sang Phase 2 trong trạng thái hiện tại.**

Đề xuất có điều kiện:

1. Giữ minimal entity bridge vì causal coverage uplift và no-regression đã được
   chứng minh.
2. Adjudicate ít nhất 100 stratified QID để chấm metric phrase và operand roles;
   target production vẫn là common sealed 300-record release.
3. Nếu parser trả đúng metric phrase/roles nhưng canonical metric ID hoặc row
   sai, classify là **Resolver failure** và bắt đầu
   `PHASE 2 — Metric Resolution`.
4. Nếu parser sai phrase/role có hệ thống, tiếp tục Phase 1 bằng một experiment
   cô lập; không combine Resolver changes.
5. Không thay retrieval, embedding, reranker, top-k, selector, planner hoặc
   answer generator dựa trên kết quả Phase 1 này.

Final decision: **Parser là bottleneck cục bộ, đã sửa đúng một defect có ảnh
hưởng 32 QID; chưa có bằng chứng để coi parser là bottleneck chính của khoảng
cách Execution Accuracy 0,4526.**
