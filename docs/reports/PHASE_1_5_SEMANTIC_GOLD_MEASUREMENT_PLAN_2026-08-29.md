# PHASE 1.5 — INDEPENDENT SEMANTIC GOLD & CANONICAL V2 MEASUREMENT PLAN

Ngày lập kế hoạch: 2026-08-29

Repository: Text2Pandas / team VAR

Plan status: **READY FOR IMPLEMENTATION**

Phase 1.5 execution status: **NOT STARTED — BLOCKED UNTIL REVIEWER A/B/C ARE ASSIGNED**

## 1. Executive decision

Mục tiêu đúng của Phase 1.5 là tạo một semantic gold độc lập và dùng nó để trả
lời bằng số liệu:

1. Canonical V2 nhận diện metric phrase/concept chính xác bao nhiêu?
2. Canonical V2 tạo đúng số lượng, thứ tự và vai trò operand bao nhiêu?
3. Toàn bộ semantic frame pre-binding exact-match bao nhiêu?
4. Parser còn là bottleneck hay phần việc tiếp theo nên chuyển sang Metric
   Resolver / Selector / Binding?

Kế hoạch gợi ý ban đầu đúng về nguyên tắc độc lập A/B/C, nhưng chưa thể chạy
nguyên trạng trên repository. Cần tạo một luồng `semantic_gold_v2` riêng vì:

- protocol hiện hữu cố định **300 câu** và gộp ba asset `answer`,
  `semantic_parser`, `evidence_binding`; Phase 1.5 chỉ cần semantic gold
  100–150 câu;
- packet generator hiện hữu chỉ chọn theo hash, chưa có core cohort +
  diagnostic stratification;
- schema/sealer hiện hữu chỉ chấp nhận `OK | UNANSWERABLE`, không biểu diễn đúng
  `RESOLVED | AMBIGUOUS | UNRESOLVED | NOT_APPLICABLE` theo từng semantic field;
- evaluator hiện hữu không đo metric phrase, metric concept, operand roles,
  operand-role + metric hoặc full-frame exact match;
- Canonical V2 là một hệ hybrid: `Intent`, generic
  `QuestionSemanticFrame`/`OperationIR`, formula route và các multi-entity route
  không cùng phát ra một prediction schema thống nhất.

Vì vậy phương án tối ưu là:

```text
100 QID HEADLINE_CORE (equal-probability, prediction-blind)
       +
20 QID DIAGNOSTIC_SUPPLEMENT (rare semantic shapes, excluded from headline)
       +
30 QID PRESEALED_RESERVE (chỉ kích hoạt khi cần, tổng release <= 150)
```

Gold chỉ được seal sau hai annotation độc lập và adjudication bởi người thứ ba.
Prediction của Canonical V2 chỉ được xuất **sau khi gold đã seal**. Không sửa
parser, resolver, retrieval, selector, binder, planner, executor hoặc answer
generator trong Phase 1.5.

## 2. Repository facts đã xác minh

### 2.1 Baseline bất biến của plan

| Thành phần | Identity |
|---|---|
| Source commit | `08907c362d440aeb51ac024aedccf75de98a2b0f` |
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Question source | `data/raw/btc/questions/questions.jsonl` |
| Question records | 1,012 |
| Question SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |

Active snapshot được xác nhận tại
[`active_snapshot.yaml`](../../configs/datasets/active_snapshot.yaml). Canonical
V2 vẫn là public runtime; Semantic V3 chỉ là shadow theo
[`ADR 0008`](../adr/0008-semantic-query-engine-v3.md) và
[`SEMANTIC_V3_MIGRATION_STATUS.md`](../SEMANTIC_V3_MIGRATION_STATUS.md).

### 2.2 Gold và governance hiện có

| Asset | Trạng thái thực tế | Có dùng làm promotion gold? |
|---|---|---:|
| `data/curated/gold/semantic_gold.jsonl` | 40 records, 6 full-agreement usable, hai model pass cùng prior | **Không** |
| `data/curated/gold/coverage_matrix.json` | diagnostic stratification 40 QID | Chỉ dùng để thiết kế coverage |
| `data/curated/gold/field_coverage.json` | metric 7/40, operand role 10/40, role+metric 6/40 agreement | **Không đủ để đo** |
| `configs/evaluation/gold_registry_v1.yaml` | semantic promotion-eligible = 0 | **Không** |
| `configs/evaluation/independent_gold_protocol_v1.yaml` | prediction-blind, 300 QID, A/B/C, answer+semantic+evidence | Có thể reuse governance, không reuse scope/schema |

Registry đang ghi đúng:

```text
semantic_parser.records                    = 40
semantic_parser.usable_records             = 6
semantic_parser.promotion_eligible_records = 0
semantic_parser.independence               = NONE
```

Không được tăng các số này trước khi release mới được adjudicate và seal.

### 2.3 Tooling hiện có và gap

| Tool/contract hiện có | Reuse | Gap cần đóng |
|---|---|---|
| `application/usecases/independent_gold.py` | checksum câu hỏi, deterministic selection, reviewer identity, prediction-leak rejection | schema gộp 3 asset; không có semantic field-level status/spans/full frame |
| `tools/evaluation/prepare_independent_gold.py` | immutable packet pattern | protocol cố định 300; không stratified; template sai scope |
| `tools/evaluation/seal_independent_gold.py` | output `exist_ok=False`, manifest SHA | buộc answer/evidence; không giữ ambiguous/unresolved đúng contract Phase 1.5 |
| `tools/measure_v4/eval_semantic_parser.py` | fingerprint, per-QID + summary pattern | bỏ qua metric/operand/full-frame; chỉ đo fields A/B đã agree của diagnostic set |
| `tests/unit/test_independent_gold.py` | negative governance tests | chưa test span, vocabulary, field status, deterministic frame, core/diagnostic separation |

README nói packet 300-record “ready”, nhưng không có packet tương ứng dưới
`artifacts/runs/evaluation/` trong workspace hiện tại. Plan không dựa vào artifact
không tồn tại này.

### 2.4 Prediction contract thực tế của Canonical V2

Public semantic path hiện gồm:

```text
parse_intent(question)
requested_unit_of(question)
classify_operation(question)
        ├─ special formula/count/multi-entity recognizers
        └─ parse_question(...) → QuestionSemanticFrame → route(...) → OperationIR
```

Các giới hạn quan trọng:

- generic `QuestionSemanticFrame.metric_id` là `None` trong public call;
- generic frame không giữ raw metric phrase;
- `OperationIR` có ordered roles nhưng cùng copy một scalar `metric_id` vào các
  slot, nên không biểu diễn hai metric khác nhau của một phép chia;
- period role và basis theo từng operand chưa có trong generic frame;
- formula và multi-entity engines bypass generic frame;
- `metric_codes_hint()` là retrieval hint tới VAS code, không phải parser
  metric-concept prediction;
- selected A6 row/cell là output của Selector/Binder, tuyệt đối không được dùng
  để backfill parser prediction.

Hệ quả: evaluator mới phải quan sát **effective pre-binding semantics** của
public V2 và giữ `MISSING/NOT_EMITTED` nếu runtime thật không phát field. Adapter
không được sáng tạo metric concept từ evidence hoặc V3 AST để làm score đẹp hơn.

## 3. Những điều chỉnh bắt buộc so với plan gợi ý

### 3.1 Không dùng aggregate của oversample làm headline

Các category như `multi_entity`, `period_comparison`, `nested` và
`unit_sensitive` có thể overlap. Cộng quota overlap rồi gọi đó là 120 unique QID
sẽ không xác định được selection probability. Chọn nhiều câu khó rồi tính một
accuracy chung cũng làm headline thấp giả tạo.

Plan dùng hai cohort:

- `HEADLINE_CORE`: 100 QID equal-probability từ phần corpus chưa bị dùng làm
  parser development gold; chỉ cohort này dùng cho decision thresholds;
- `DIAGNOSTIC_SUPPLEMENT`: 20 QID prediction-blind để tăng coverage các shape
  hiếm; báo riêng, không nhập vào headline accuracy;
- `RESERVE`: 30 QID được chọn và checksum cùng lúc, nhưng không thay ngầm QID
  unresolved trong headline.

### 3.2 Tách semantic gold khỏi answer/evidence gold

Phase 1.5 không cần người review gán numeric answer hay ordered observation UID.
Buộc họ làm cả ba asset sẽ tăng chi phí, kéo sai scope và làm blocker không cần
thiết. Protocol v1 vẫn giữ nguyên cho promotion release 300-record sau này.

### 3.3 Không overwrite diagnostic v1

Giữ nguyên:

```text
data/curated/gold/semantic_gold.jsonl
data/curated/gold/coverage_matrix.json
tools/measure_v4/*
configs/evaluation/independent_gold_protocol_v1.yaml
```

Phase 1.5 tạo sibling v2. Diagnostic 40 QID chỉ được dùng để tìm schema gap,
không được coi là independent gold và không được trộn vào headline core.

### 3.4 Tách output shape khỏi unit dimension

Plan gợi ý trộn `SCALAR`, `RATIO`, `PERCENTAGE`, `COUNT`, `ENTITY`, `PERIOD` vào
một `result_kind`. Repository đã cho thấy shape và unit là hai khái niệm khác
nhau. Schema v2 dùng:

```text
output_shape = SCALAR | ENTITY | PERIOD | COUNT | TABLE | SET | BOOLEAN | OTHER
unit.dimension = MONEY | PERCENT | PERCENT_POINT | RATIO | COUNT | SHARES | UNKNOWN
unit.scale_exponent = 0 | 3 | 6 | 9 | 12 | null
```

`Result Kind Accuracy` trong report nghĩa là `output_shape` accuracy; unit
dimension/scale được đo riêng.

### 3.5 Basis không explicit phải là `UNSPECIFIED` ở parser gold

`Intent.basis` có consolidated default để retrieval ưu tiên, nhưng
`Intent.answer_basis` chỉ hard-bind khi câu hỏi nói rõ. Gold phải giữ:

```text
basis.value    = UNSPECIFIED
basis.explicit = false
```

Evaluator có thể báo thêm `effective_default_basis`, nhưng không được chấm
default retrieval prior như thể người dùng đã nói “hợp nhất”.

### 3.6 Final report theo convention thật của repo

Repository hiện dùng `docs/reports/`, không có `docs/audits/`. Final execution
report sẽ là:

```text
docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<YYYY-MM-DD>.md
```

Generated predictions/metrics nằm trong `artifacts/audits/`, không commit vào
docs.

## 4. Scope, non-goals và protected surface

### 4.1 Allowed changes

- evaluation protocol/config/vocabulary;
- JSON Schema và annotation guideline;
- prediction-blind sampler và packet builder;
- validator, agreement calculator, adjudication/sealing tool;
- read-only Canonical V2 semantic observation adapter;
- evaluator, failure taxonomy và report renderer;
- unit/contract tests và Makefile targets;
- curated sealed release sau khi A/B/C hoàn tất.

### 4.2 Forbidden changes

- `parse_intent`, `classify_operation`, `parse_question`, Router semantics;
- metric resolver/ontology dùng trong production;
- retrieval candidate generation/ranking/reranking;
- Selector, Binder, Planner, Executor;
- answer generation, evidence generation, submission packaging;
- wiring Semantic V3 vào public path;
- thay threshold chỉ để đạt decision;
- sửa gold sau khi đã xem prediction.

### 4.3 Protected-file fingerprint

Trước implementation phải tạo manifest SHA-256 ít nhất cho:

```text
configs/datasets/active_snapshot.yaml
src/text2pandas/application/usecases/canonical_run.py
src/text2pandas/pipelines/retrieval/question_intent.py
src/text2pandas/pipelines/retrieval/metric_hint.py
src/text2pandas/pipelines/answering/frame.py
src/text2pandas/pipelines/answering/router.py
src/text2pandas/pipelines/answering/ir.py
src/text2pandas/pipelines/answering/formula_engine.py
src/text2pandas/pipelines/answering/pipeline.py
configs/answer_v2/metrics_v1.yaml
configs/answer_v2/formulas_v1.yaml
```

Manifest sau task phải khớp byte-for-byte. Nếu khác, Phase 1.5 `FAIL` do
production contamination.

## 5. Target artifact architecture

### 5.1 Tracked contracts

```text
configs/evaluation/
  semantic_gold_v2_protocol.yaml
  semantic_gold_v2_schema.json
  semantic_gold_v2_sampling.yaml
  semantic_metric_concepts_v1.yaml
  semantic_operation_vocabulary_v1.yaml

data/curated/gold/
  semantic_gold_v2/
    <release_id>/
      questions.jsonl
      annotations_a.jsonl
      annotations_b.jsonl
      adjudications.jsonl
      semantic_gold.jsonl
      agreement.json
      coverage_matrix.json
      reviewer_attestations.json
      manifest.json
      README.md
```

Reviewer IDs trong tracked artifact dùng pseudonymous stable IDs. Không ghi tên,
email hoặc thông tin cá nhân không cần thiết.

### 5.2 Open/generated artifacts

```text
artifacts/runs/evaluation/
  semantic-gold-v2-packet-<run_id>/
    selection_core.jsonl
    selection_diagnostic.jsonl
    selection_reserve.jsonl
    annotator_a.jsonl
    annotator_b.jsonl
    adjudication.jsonl
    access_log.jsonl
    manifest.json

artifacts/audits/
  parser-phase1.5-<run_id>/
    parser_predictions.jsonl
    parser_metrics.json
    parser_metrics_by_category.json
    parser_vs_gold_per_qid.jsonl
    failure_taxonomy.json
    boundary_analysis.json
    manifest.json
```

Packet và audit run là immutable: output đã tồn tại thì command phải fail, không
overwrite.

## 6. Semantic gold v2 contract

### 6.1 Record envelope

Mỗi annotation record có cấu trúc tối thiểu:

```json
{
  "schema_version": 2,
  "qid": 123,
  "question": "...",
  "question_sha256": "...",
  "cohort": "HEADLINE_CORE",
  "selection_digest": "...",
  "record_status": "RESOLVED",
  "entities": [],
  "metrics": [],
  "periods": [],
  "basis": {},
  "unit": {},
  "operation_tree": {},
  "output": {},
  "operands": [],
  "field_status": {},
  "source_evidence": [],
  "ambiguity_alternatives": [],
  "notes": null
}
```

Allowed status:

```text
RESOLVED | AMBIGUOUS | UNRESOLVED | NOT_APPLICABLE
```

Chỉ record `RESOLVED` được dùng cho strict accuracy. `AMBIGUOUS` và
`UNRESOLVED` được báo count riêng, không tính parser wrong. `NOT_APPLICABLE` chỉ
dùng ở field-level.

### 6.2 Span policy

Entity/metric mention dùng Unicode NFC, zero-based half-open character offsets:

```json
{
  "text": "doanh thu thuần",
  "start": 18,
  "end": 33
}
```

Validator phải kiểm:

- `question[start:end] == text` sau NFC normalization;
- span không âm, không vượt question;
- thứ tự span ổn định theo source text;
- maximal semantic phrase, không tự thêm từ không nằm trong câu;
- multiple occurrences giữ occurrence riêng.

### 6.3 Entity

```json
{
  "mention": {"text": "CTCP Chứng khoán FPT", "start": 0, "end": 22},
  "canonical_ref": "FTS",
  "resolution_status": "RESOLVED",
  "semantic_role": "REPORTING_ENTITY"
}
```

Mention và canonical ref là hai label khác nhau. Ticker nằm trong tên không tự
động trở thành canonical ref. Entity order trong question được giữ; operand
mapping quyết định khi order có ý nghĩa tính toán.

### 6.4 Metric phrase và concept

```json
{
  "metric_ref": "m1",
  "phrase": {"text": "lợi nhuận sau thuế", "start": 0, "end": 20},
  "concept_id": "PROFIT_AFTER_TAX",
  "concept_status": "RESOLVED",
  "reported_or_derived": "REPORTED",
  "definition_version": "semantic-metric-concepts-v1"
}
```

Nguyên tắc:

- phrase là surface text; concept là semantic meaning;
- concept không phải Silver row, VAS code, table ID hay observation UID;
- reported named ratio là một concept nếu câu hỏi không spell out operands;
- nếu câu hỏi spell out numerator/denominator thì annotate operation và từng
  metric operand;
- concept chưa có definition chắc chắn là `UNRESOLVED`, không tạo ID tùy ý;
- vocabulary có definition tiếng Việt, inclusion/exclusion examples và checksum;
- vocabulary được freeze trước final A/B pass và không đọc parser prediction.

Có thể tham khảo tên ID ổn định từ registry production, nhưng definition của
evaluation vocabulary phải được review độc lập. Production registry không phải
annotation authority.

### 6.5 Period và period role

```json
{
  "period_ref": "p1",
  "year": 2024,
  "quarter": null,
  "point": "PERIOD",
  "role": "CURRENT",
  "explicit": true
}
```

Vocabulary:

```text
point = PERIOD | OPENING | CLOSING | INSTANT | UNKNOWN
role  = VALUE | CURRENT | PREVIOUS | START | END | RANK_DOMAIN | FILTER_DOMAIN
```

Range phải expand thành period set. Khi mỗi operand dùng period khác nhau,
operand tham chiếu `period_ref` riêng.

### 6.6 Basis

```json
{
  "value": "UNSPECIFIED",
  "explicit": false
}
```

Vocabulary:

```text
CONSOLIDATED | SEPARATE | UNSPECIFIED
```

Mỗi operand có thể override basis bằng basis ref. Không force scalar common
basis cho mixed-basis question.

### 6.7 Unit và output

```json
{
  "unit": {
    "dimension": "MONEY",
    "scale_exponent": 9,
    "currency": "VND",
    "explicit": true
  },
  "output": {
    "shape": "SCALAR"
  }
}
```

Scale dùng exponent theo convention hiện có của repo: triệu = 6, tỷ = 9, nghìn
tỷ = 12. `%` có `dimension=PERCENT`, `scale_exponent=null`; điểm phần trăm là
`PERCENT_POINT`.

### 6.8 Operation tree và operand roles

Không dùng một flat `OTHER` nếu composition xác định được. Ví dụ:

```json
{
  "node": "DIVIDE",
  "operands": ["o1", "o2"]
}
```

```json
[
  {"operand_ref": "o1", "role": "NUMERATOR", "metric_ref": "m1"},
  {"operand_ref": "o2", "role": "DENOMINATOR", "metric_ref": "m2"}
]
```

Top-level vocabulary:

```text
LOOKUP | ADD | SUBTRACT | DIVIDE | GROWTH | PERCENT_CHANGE
SUM | AVERAGE | COUNT | MINIMUM | MAXIMUM
ARGMIN | ARGMAX | SELECT_AT_ARG | FILTER | MEDIAN | OTHER
```

Canonical roles:

```text
VALUE
LEFT / RIGHT
MINUEND / SUBTRAHEND
NUMERATOR / DENOMINATOR
NEW / OLD
SUMMAND
RANK_KEY / PROJECTED_VALUE
FILTER_OPERAND / FILTER_THRESHOLD
```

Operand list là order-sensitive. Nested roles thuộc node tương ứng; không tạo
các tên composite tùy ý như `minuend_numerator` nếu có thể biểu diễn bằng tree.

### 6.9 Full frame

`full_frame` không được annotator copy/paste lần thứ hai. Sealer tạo canonical
frame từ các component đã adjudicate, sort/canonicalize theo schema và ghi vào
`semantic_gold.jsonl`. Điều này loại hai nguồn sự thật trong cùng record.

Full-frame comparison:

- bỏ metadata, notes, evidence locator và reviewer IDs;
- giữ ordered operands và operation-tree child order;
- normalize enum case và Unicode theo schema;
- entity membership exact; entity order chỉ bắt buộc ở nơi role/order có nghĩa;
- missing prediction ở field applicable = wrong;
- gold field `NOT_APPLICABLE` không vào denominator.

## 7. Sampling design

### 7.1 Contamination ledger trước khi sample

Tạo union QID đã xuất hiện trong:

- diagnostic semantic gold 40;
- answer/evidence/retrieval dev labels;
- parser regression tests hoặc các tracked adjudication cohort;
- các known failure cohorts đã dùng để sửa/tune Canonical V2.

Ghi `contamination_ledger.json` với source path + reason. QID bị contamination
không vào `HEADLINE_CORE`; có thể vào một breakdown `KNOWN_DEV` riêng nhưng
không ảnh hưởng phase decision.

### 7.2 Headline core

Chọn 100 QID từ uncontaminated universe bằng:

```text
SHA256(seed + NUL + qid + NUL + question)
```

sort theo digest rồi qid. Không đọc parser output, answer, retrieval score,
abstention hoặc known score. Selection manifest ghi universe checksum, excluded
QIDs/checksum, seed và selected digests.

### 7.3 Diagnostic supplement

Chọn thêm 20 QID từ phần còn lại bằng question-text-only proxy rules. Các rule
nằm trong `semantic_gold_v2_sampling.yaml`, không import production parser.

Primary quota đề xuất:

| Primary diagnostic stratum | Target |
|---|---:|
| Divide / explicit ratio | 4 |
| Subtract / directional difference | 3 |
| Growth / percent change | 2 |
| Arg-select-project | 3 |
| Nested / composed | 3 |
| Multi-entity directional | 2 |
| Count | 1 |
| Basis-sensitive | 1 |
| Unit/scale-sensitive | 1 |
| **Total** | **20** |

Mỗi QID có đúng một `primary_stratum` theo precedence để quota cộng thành 20,
nhưng có nhiều `secondary_tags`. Category thật dùng trong report được xác định
từ adjudicated gold, không coi proxy sampling tag là gold.

### 7.4 Reserve

Preselect 30 QID reserve bằng seed riêng và seal cùng selection manifest. Reserve
chỉ kích hoạt khi:

- source record bị hỏng/duplicate;
- final release dưới 100 resolved records;
- một critical semantic family không có đủ scored cases.

Kích hoạt reserve cần manifest amendment trước khi xem prediction. Không xóa
unresolved QID cũ, không thay đổi original headline denominator và tổng annotated
release không vượt 150.

### 7.5 Coverage output

`coverage_matrix.json` phải có:

- unique QID count theo cohort;
- primary stratum count;
- adjudicated secondary category count;
- contaminated QID count;
- activated reserve count + reason;
- resolved/ambiguous/unresolved theo cohort;
- parser prediction không xuất hiện trong file.

## 8. Independent annotation workflow

### 8.1 Reviewer roles

| Role | Quyền xem trước adjudication | Bắt buộc |
|---|---|---|
| Annotator A | question, guideline, vocabulary, source evidence locator | Không xem B, C, parser/V3/downstream output |
| Annotator B | giống A | Không xem A, C, parser/V3/downstream output |
| Adjudicator C | question, source, A và B sau khi cả hai lock | Distinct identity; review cả agreement và disagreement |

A/B/C phải dùng ba reviewer ID khác nhau và attest:

```text
independent_of_model_development = true
blind_to_model_outputs           = true
source_evidence_reviewed         = true
guideline_version                = fixed version
vocabulary_sha256                = fixed checksum
```

Nếu không có ba người đáp ứng contract, Phase 1.5 dừng ở
`OPEN_FOR_INDEPENDENT_REVIEW`; metric vẫn `NOT_MEASURED`.

### 8.2 Calibration pilot

Trước final 120, dùng 12–15 QID calibration riêng, không thuộc headline/gold:

1. A và B annotate độc lập;
2. đo disagreement theo field;
3. C xác định disagreement do guideline hay do genuine ambiguity;
4. sửa guideline/vocabulary/schema;
5. bump version/checksum;
6. bỏ pilot khỏi evaluation release.

Không dùng parser/V3 prediction trong calibration.

### 8.3 Agreement checkpoint

Tính trước adjudication:

- Entity Mention Span Exact và overlap F1;
- Entity Reference Exact;
- Metric Phrase Span Exact và overlap F1;
- Metric Concept Exact;
- Operand Count Exact;
- Ordered Operand Role Exact;
- Operand Metric Exact;
- Operand Role+Metric Exact;
- Period/Period-role Exact;
- Basis/Unit/Operation/Output Exact;
- Full Semantic Frame Exact.

Báo cả numerator/denominator, không chỉ percentage. Cohen's kappa chỉ dùng cho
single-label categorical field có đủ support; không ép kappa cho nested tree.

Checkpoint guideline:

```text
metric concept agreement < 0.85
OR ordered operand role agreement < 0.85
OR full-frame agreement < 0.70
```

thì pause, phân tích guideline, reannotate affected scope bằng **cả A và B**.
Đây không phải parser gate và không được sửa parser để tăng agreement.

### 8.4 Adjudication

C review mọi record, kể cả A/B agree. Disagreement field phải có:

```text
reading_a
reading_b
decision = A | B | NEW | AMBIGUOUS | UNRESOLVED
rationale
source_evidence_refs[]
```

`NEW` chỉ hợp lệ khi C nêu lý do cả A và B đều sai. Genuine ambiguity giữ
alternatives và status `AMBIGUOUS`, không forced guess.

## 9. Sealing and immutability

Sealer phải fail-closed với:

- thiếu/duplicate QID;
- source/question checksum mismatch;
- A/B/C identity trùng nhau;
- thiếu independence/blind/source attestations;
- invalid enum, span, operand ref hoặc operation tree;
- disagreement chưa được C review;
- record `UNRESOLVED` không có reason;
- model/prediction-shaped forbidden fields;
- vocabulary/guideline checksum mismatch;
- manually supplied `full_frame` khác canonical derived frame;
- output directory đã tồn tại.

Manifest tối thiểu:

```json
{
  "kind": "text2pandas.semantic_gold_v2_release",
  "release_id": "semantic-gold-v2-<date>",
  "status": "SEALED",
  "question_source_sha256": "...",
  "records": 120,
  "resolved_records": 0,
  "ambiguous_records": 0,
  "unresolved_records": 0,
  "headline_core_records": 100,
  "diagnostic_records": 20,
  "independence": "VERIFIED_BY_ATTESTATION",
  "gold_sha256": "...",
  "schema_sha256": "...",
  "vocabulary_sha256": "...",
  "protected_surface_sha256": "..."
}
```

Các số `0` trong ví dụ là placeholder schema, không phải kết quả dự kiến.
Sealer ghi số thực từ release.

Sau seal:

- chmod/read-only hoặc equivalent immutable policy;
- không chạy tool nào sửa release tại chỗ;
- correction phải tạo release ID mới với `supersedes` và changelog;
- không update gold sau khi xem prediction;
- registry chỉ được update từ manifest đã seal và checksum đã verify.

## 10. Canonical V2 prediction export

### 10.1 Target being measured

Headline đo source commit đã freeze:

```text
08907c362d440aeb51ac024aedccf75de98a2b0f
```

Nếu code thay đổi trong thời gian human annotation, dùng clean worktree tại
commit này để xuất baseline. Candidate mới phải có run ID và metric report riêng;
không thay headline target giữa chừng.

### 10.2 Read-only semantic observation adapter

Tạo `tools/evaluation/export_canonical_v2_semantics.py` và pure normalization
logic trong application evaluation use case. Adapter chỉ gọi pre-binding public
semantic functions:

- `parse_intent` cho entity/scope/period domain;
- `requested_unit_of` cho requested unit;
- `classify_operation` cho operation hint;
- `parse_question(..., resolved_entity=...)` cho generic frame;
- `route(frame)` cho compilable `OperationIR`/ordered roles;
- pure route recognizers đang thực sự nằm trước candidate binding.

Adapter không gọi:

- retrieval DB/A6 selector/binder;
- row/cell matching;
- answer/pandas/evidence output;
- Semantic V3 parser/AST;
- evaluation gold trong quá trình tạo prediction.

Mỗi prediction ghi:

```text
prediction_status
prediction_source per field
entities + source
metric phrase/concept hoặc MISSING_OUTPUT
periods + roles hoặc MISSING_OUTPUT
basis explicit/effective prior
unit
operation tree/family
output shape
ordered operands
missing_fields
implementation fingerprint
```

`metric_codes_hint()` không được đổi thành metric concept. Concept suy từ bound
row không được credit. Route-specific recognizer chỉ được credit field mà nó
thực sự phát trước binding, và `prediction_source` phải chỉ ra route.

### 10.3 Hai diagnostic views, một headline

Evaluator có thể xuất hai view:

1. `GENERIC_FRAME_CONTRACT`: chỉ generic frame/IR, để thấy schema gap;
2. `EFFECTIVE_PUBLIC_PREBIND`: hợp nhất các active pre-bind recognizers theo
   đúng dispatcher precedence.

Critical decision dùng `EFFECTIVE_PUBLIC_PREBIND`. Không average hai view và
không chọn view có score cao hơn sau khi xem kết quả.

## 11. Metric definitions

Tất cả strict metrics dùng only `record_status=RESOLVED`. Field
`NOT_APPLICABLE` không vào denominator. Gold applicable nhưng prediction
missing/extra là wrong.

| Metric | Exact definition |
|---|---|
| Entity Reference Accuracy | record exact canonical entity membership + required role/order |
| Metric Phrase Exact Match | exact ordered list of NFC half-open spans |
| Metric Concept Accuracy | record exact concept IDs aligned to metric refs/operands |
| Period Exact Match | exact normalized period set; range đã expand |
| Period Role Accuracy | exact role per period/operand |
| Basis Accuracy | explicit semantic basis; `UNSPECIFIED` khác default prior |
| Unit Accuracy | exact dimension + scale exponent + currency where applicable |
| Operation Accuracy | canonical root/tree node exact; báo thêm family-level diagnostic |
| Result Kind Accuracy | exact output shape |
| Operand Count Accuracy | exact declared operand count at canonical tree boundary |
| Operand Role Accuracy | exact ordered role sequence; threshold dùng record-level exact |
| Operand Metric Accuracy | exact metric concept per ordered operand |
| Operand Role+Metric Accuracy | exact ordered `(role, concept)` sequence |
| Full Semantic Frame Exact | canonical full-frame JSON exact after metadata removal |

Ngoài point estimate, báo Wilson 95% CI và `correct/scored/skipped`. CI là thông
tin uncertainty; decision threshold vẫn dùng exact ratio chưa round theo rule
đã lock.

### 11.1 Headline vs conditional metrics

Headline chỉ dùng `HEADLINE_CORE`. Bắt buộc breakdown:

```text
Metric Concept | simple lookup
Metric Concept | multi-metric
Operand Role   | non-commutative operations
Full Frame     | all resolved headline
LOOKUP | DIVIDE | SUBTRACT | GROWTH
ARG_SELECT_PROJECT | MULTI_ENTITY | NESTED
```

Diagnostic supplement và activated reserve có bảng riêng. Không xuất một
“combined accuracy” dễ bị hiểu nhầm là corpus estimate.

## 12. Failure taxonomy and boundary rules

Mỗi failed QID có:

```text
primary_failure
secondary_failures[]
failed_fields[]
gold_value
prediction_value
prediction_source
category_tags[]
boundary
```

Taxonomy:

```text
MISSING_OUTPUT
ENTITY_MENTION
ENTITY_REFERENCE
METRIC_PHRASE
METRIC_CONCEPT
PERIOD
PERIOD_ROLE
BASIS
UNIT
OPERATION
RESULT_KIND
OPERAND_COUNT
OPERAND_ROLE
OPERAND_METRIC
COMPOSITION
EXTRA_FIELD
OTHER
```

Primary failure precedence phản ánh dependency:

```text
MISSING_OUTPUT → ENTITY → OPERATION/COMPOSITION → OPERAND_COUNT
→ OPERAND_ROLE → METRIC → PERIOD/BASIS/UNIT → RESULT_KIND
```

Secondary failures giữ toàn bộ mismatch; không collapse thành `PARSER_ERROR`.

Boundary attribution:

- question phrase/span/concept sai hoặc missing trước binding → `PARSER`;
- operation/tree/role/axis sai → `PARSER_OR_SEMANTIC_COMPILER`;
- parser concept đúng nhưng lookup VAS code/table row sai → `METRIC_RESOLVER`;
- concept/axes đúng nhưng observation assignment sai → `SELECTOR_BINDER`;
- tất cả semantic field đúng nhưng unit conversion/answer sai → `DOWNSTREAM`;
- không có answer/evidence gold → downstream correctness `NOT_MEASURED`.

Phase 1.5 được phép chạy E2E trace trên same QIDs để báo
`abstention stage | parser-correct`, nhưng không được biến coverage/abstention
thành resolver accuracy.

## 13. Implementation work packages

### WP0 — Freeze authority, contamination và protected surface

**Changes**

- tạo source/protected fingerprint manifest;
- tạo contamination ledger;
- xác nhận 1,012 source records và active snapshot IDs;
- lock target commit và report path.

**Gate**

```text
question checksum exact
active snapshot exact
duplicate source QID = 0
protected manifest complete
```

**Stop if** source checksum hoặc active snapshot khác plan.

### WP1 — Schema, vocabulary và guideline v2

**Planned files**

```text
configs/evaluation/semantic_gold_v2_schema.json
configs/evaluation/semantic_metric_concepts_v1.yaml
configs/evaluation/semantic_operation_vocabulary_v1.yaml
data/curated/gold/semantic_gold_v2/README.md
```

**Gate**

- valid/invalid fixtures cover every enum and relation;
- full frame generated deterministically;
- metric concept definition không chứa Silver row/table IDs;
- basis/unit/result-shape policies không mâu thuẫn.

### WP2 — Prediction-blind sampler và packet builder

**Planned files**

```text
configs/evaluation/semantic_gold_v2_protocol.yaml
configs/evaluation/semantic_gold_v2_sampling.yaml
src/text2pandas/application/usecases/semantic_gold_v2.py
tools/evaluation/prepare_semantic_gold_v2.py
tests/unit/test_semantic_gold_v2_sampling.py
tests/unit/test_semantic_gold_v2.py
```

**Gate**

- same input/seed → byte-identical packet;
- selection contains no prediction/output/score;
- core=100, diagnostic=20, reserve=30;
- cohorts disjoint;
- contamination absent from headline core;
- output existing → fail.

### WP3 — Calibration pilot

**Human work**

- A/B annotate 12–15 excluded pilot QIDs;
- C analyzes disagreements;
- freeze guideline/schema/vocabulary versions.

**Gate**

- no unresolved schema interpretation;
- all changes versioned before final packet;
- pilot excluded from release metrics.

**Stop if** A/B/C roster or source-evidence access chưa có.

### WP4 — Final A/B annotation

**Gate**

- 100% selected records completed by A;
- 100% selected records completed by B;
- reviewer identities distinct;
- all attestations true;
- no access to predictions or each other's labels.

Không chạy parser prediction trên selected QIDs ở bước này.

### WP5 — Agreement analysis

**Planned files/tools**

```text
tools/evaluation/validate_semantic_gold_v2.py
tools/evaluation/measure_semantic_agreement_v2.py
```

**Gate**

- agreement metrics generated before C labels;
- every disagreement listed field-by-field;
- low-agreement checkpoint resolved by guideline/reannotation, không bằng parser change.

### WP6 — Adjudication C

**Gate**

- C distinct from A/B;
- every record reviewed;
- every disagreement has decision/rationale/source refs;
- ambiguity preserved;
- no forced label to hit target count.

### WP7 — Seal release

**Planned tool**

```text
tools/evaluation/seal_semantic_gold_v2.py
```

**Gate**

```text
records >= 100 and <= 150
resolved records reported explicitly
dual annotation complete
adjudication complete
independence verified
gold SHA-256 created
release status = SEALED
```

Nếu resolved records < 100, kích hoạt reserve theo protocol hoặc giữ status
`BLOCKED`; không hạ gate.

### WP8 — Export frozen Canonical V2 predictions

**Planned files**

```text
tools/evaluation/export_canonical_v2_semantics.py
tests/unit/test_canonical_v2_semantic_export.py
```

**Gate**

- export chỉ chạy sau verified SEALED manifest;
- no A6/retrieval/prediction leakage into gold;
- two exports byte-identical;
- source commit + implementation fingerprint recorded;
- V3 imports absent.

### WP9 — Evaluate and taxonomize

**Planned files**

```text
tools/evaluation/evaluate_semantic_gold_v2.py
tests/unit/test_semantic_gold_v2_evaluator.py
```

**Gate**

- all mandatory metrics present, kể cả metric/operand/full frame;
- missing applicable prediction counted wrong;
- N/A excluded, not counted correct;
- headline and diagnostic denominators separate;
- every failed QID has taxonomy;
- parser vs resolver boundary report does not infer answer accuracy.

### WP10 — Final report and decision

**Output**

```text
docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<YYYY-MM-DD>.md
```

**Report sections**

1. Executive Summary;
2. Dataset and checksums;
3. Annotation agreement;
4. Parser accuracy;
5. Failure breakdown;
6. Category breakdown;
7. Parser vs Resolver boundary;
8. Phase decision;
9. Exact next engineering task.

## 14. Reproducible command contract

Thêm Makefile targets fail-closed:

```bash
make semantic-gold-v2-prepare \
  PY=/opt/anaconda3/bin/python \
  PROTOCOL=configs/evaluation/semantic_gold_v2_protocol.yaml \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-<run_id>

make semantic-gold-v2-validate \
  PY=/opt/anaconda3/bin/python \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-<run_id>

make semantic-gold-v2-agreement \
  PY=/opt/anaconda3/bin/python \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-<run_id>

make semantic-gold-v2-seal \
  PY=/opt/anaconda3/bin/python \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-<run_id> \
  RELEASE=data/curated/gold/semantic_gold_v2/<release_id> \
  RELEASE_ID=<release_id>

make semantic-parser-v2-export \
  PY=/opt/anaconda3/bin/python \
  GOLD=data/curated/gold/semantic_gold_v2/<release_id> \
  OUT=artifacts/audits/parser-phase1.5-<run_id>

make semantic-parser-v2-evaluate \
  PY=/opt/anaconda3/bin/python \
  GOLD=data/curated/gold/semantic_gold_v2/<release_id> \
  RUN=artifacts/audits/parser-phase1.5-<run_id>

make semantic-parser-v2-report \
  PY=/opt/anaconda3/bin/python \
  RUN=artifacts/audits/parser-phase1.5-<run_id> \
  REPORT=docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<YYYY-MM-DD>.md
```

Target phải yêu cầu explicit paths/IDs, ghi invocation/environment vào manifest
và không có `latest` default.

## 15. Verification matrix

### 15.1 Targeted tests

```bash
/opt/anaconda3/bin/python -m pytest -q \
  tests/unit/test_independent_gold.py \
  tests/unit/test_semantic_gold_v2.py \
  tests/unit/test_semantic_gold_v2_sampling.py \
  tests/unit/test_canonical_v2_semantic_export.py \
  tests/unit/test_semantic_gold_v2_evaluator.py
```

Negative fixtures bắt buộc:

- same reviewer in two roles;
- missing attestation;
- leaked `model_ast`, `predicted_answer`, retrieval/score fields;
- invalid span;
- unresolved disagreement;
- wrong vocabulary checksum;
- duplicate QID;
- full-frame/component mismatch;
- missing prediction on applicable field;
- extra/reordered operand;
- output overwrite attempt.

### 15.2 Repository gates

Nếu chỉ docs/config/tooling thay đổi:

```bash
make docs-check PY=/opt/anaconda3/bin/python
git diff --check
```

Nếu thêm typed code dưới `src/text2pandas/application/`:

```bash
make typecheck PY=/opt/anaconda3/bin/python
make test-offline PY=/opt/anaconda3/bin/python
```

Data identity:

```bash
make snapshots-verify PY=/opt/anaconda3/bin/python
```

Cuối task so sánh protected-file manifest trước/sau và chạy deterministic
prepare/export/evaluate hai lần với output IDs khác nhau; file hashes phải bằng
nhau.

## 16. Acceptance and decision rules

### 16.1 Gold governance gate

```text
100 <= total annotated records <= 150
resolved records >= 100, hoặc phase giữ BLOCKED
2 independent completed annotation passes
1 distinct completed adjudication pass
source-evidence review attested
prediction blindness attested
gold SEALED + SHA-256 verified
```

### 16.2 Measurement gate

Các field sau không được `NOT_MEASURED`:

```text
Metric Phrase Exact
Metric Concept Accuracy
Operand Role Accuracy
Operand Metric Accuracy
Operand Role+Metric Accuracy
Full Semantic Frame Exact
```

Mỗi metric phải có `correct`, `scored`, `skipped`, point estimate và CI95.

### 16.3 Phase decision

Trên resolved `HEADLINE_CORE`, dùng exact unrounded ratios:

```text
Metric Concept Accuracy >= 0.95
AND Ordered Operand Role Exact >= 0.95
AND Full Semantic Frame Exact >= 0.90
```

Nếu tất cả pass:

```text
PROMOTE_TO_PHASE_2_METRIC_RESOLUTION
```

Nếu bất kỳ metric nào dưới threshold:

```text
CONTINUE_PHASE_1
```

Nếu gold/measurement gate chưa hoàn tất, chưa được tạo final phase decision;
interim status là `BLOCKED`, không ép vào hai outcome trên.

`PROMOTE_TO_PHASE_2_METRIC_RESOLUTION` chỉ quyết định ưu tiên engineering tiếp
theo. Nó **không** promote Semantic V3 và không pass production promotion policy:
V3 vẫn yêu cầu 300 semantic, answer và evidence records cùng các gate khác.

## 17. RACI, effort và critical path

| Work | Owner | Estimate | Depends on |
|---|---|---:|---|
| WP0–WP2 schema/tooling/tests | Evaluation engineer | 2–3 engineering days | repo access |
| Calibration pilot | A + B + C | 0.5–1 reviewer day each | frozen draft guideline |
| Final annotation A | Independent reviewer A | 15–25 reviewer hours | final packet |
| Final annotation B | Independent reviewer B | 15–25 reviewer hours | final packet |
| Agreement + adjudication | Evaluation engineer + C | 10–20 reviewer hours | A/B locked |
| Seal/export/evaluate/report | Evaluation engineer | 1–2 engineering days | C complete |
| Governance acceptance | Gold owner | 0.5 day | sealed manifest + report |

Critical path:

```text
reviewer roster/access
→ calibration
→ vocabulary freeze
→ A and B in parallel
→ C adjudication
→ seal
→ prediction export
→ measurement/decision
```

Không thể tự động hóa reviewer independence. Đây là blocker tổ chức, không phải
lỗi tooling.

## 18. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A/B dùng cùng prior hoặc trao đổi labels | agreement giả cao | separate packets/access log; identity + blindness attestation |
| Vocabulary quá hẹp | nhiều unresolved metric | calibration trước freeze; definitions + examples, không invent after prediction |
| Oversample làm sai headline | bottleneck conclusion bias | core100 equal-probability; diagnostic20 báo riêng |
| Existing dev QIDs inflate score | parser accuracy lạc quan | contamination ledger; exclude from headline |
| V2 không phát metric span/concept | score rất thấp hoặc missing | chấm `MISSING_OUTPUT` trung thực; không infer từ bound rows |
| Formula/resolver bị tính nhầm là parser | boundary attribution sai | per-field `prediction_source`; exclude VAS/bound row hints |
| Operation roles “đúng theo template” nhưng metric sai | role score đánh lừa | bắt buộc role, metric, role+metric và full frame |
| A/B agreement thấp | gold không đáng tin | pause, refine guideline, reannotate; không sửa parser |
| Gold bị sửa sau prediction | test contamination | sealed checksum, new release only, no in-place edits |
| 120 < V3 promotion minimum 300 | hiểu nhầm promotion | decision chỉ Phase 1→2 priority; V3 policy vẫn BLOCKED |

## 19. Required handoff after execution

Cuối Phase 1.5 phải trả đúng mười mục:

1. Files changed;
2. Gold dataset location;
3. Total/core/diagnostic/resolved/ambiguous/unresolved QIDs;
4. A/B annotation agreement;
5. Sealed gold SHA-256;
6. Canonical V2 parser metrics;
7. Failure taxonomy;
8. Parser vs Resolver boundary analysis;
9. `CONTINUE_PHASE_1` hoặc `PROMOTE_TO_PHASE_2_METRIC_RESOLUTION`;
10. Một exact next engineering task, không implement Phase 2 trong cùng task.

## 20. Exact next action

Engineering task đầu tiên nên là:

> Implement WP0–WP2 only: freeze the Phase 1.5 authority/fingerprints, define
> and test the semantic-gold-v2 schema/vocabularies, and generate a
> prediction-blind 100-core + 20-diagnostic + 30-reserve annotation packet.
> Stop at `OPEN_FOR_INDEPENDENT_REVIEW`; do not generate Canonical V2
> predictions and do not fabricate A/B/C labels.

Song song, gold owner phải chỉ định reviewer A, reviewer B và adjudicator C đáp
ứng independence contract. Chỉ sau khi hai đầu việc này hoàn tất mới bắt đầu
annotation pilot.
