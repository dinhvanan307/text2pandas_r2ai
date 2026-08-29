# HUMAN SEMANTIC GOLD V2 — CREATION PROTOCOL

Ngày audit và thiết kế: 2026-08-29

Repository: Text2Pandas / team VAR

Phạm vi: thiết kế protocol, **không tạo human labels**

Khuyến nghị cuối: **INDEPENDENT_HUMAN (A/B/C), prediction-blind, seal trước evaluation**

## A. Repository findings

### A.1 Kết luận audit

Repository đã có nền móng tốt cho một đợt gán nhãn độc lập: source/snapshot đã
đóng băng, contamination ledger đã được tạo, sampling prediction-blind đã chọn
đúng 100 core + 20 diagnostic + 30 reserve, packet A/B/C không chứa model output,
và có validator thuần cho nhiều quan hệ semantic.

Tuy nhiên, **chưa có HUMAN GOLD** và chưa thể chạy official human evaluation:

- `annotator_a.jsonl`, `annotator_b.jsonl`, `adjudication.jsonl` hiện là 120
  template trắng;
- reviewer A, B và C đều là `UNASSIGNED`;
- metric vocabulary và operation vocabulary đều còn
  `DRAFT_FOR_CALIBRATION`;
- chỉ có Make target `semantic-gold-v2-prepare` và
  `semantic-gold-v2-local-e2e`;
- validate/agreement/adjudicate/seal/export/evaluate/report cho human gold chưa
  có implementation;
- local E2E đã chạy trước đây là `LOCAL_SYNTHETIC`, chỉ chứng minh plumbing và
  tuyệt đối không phải ground truth.

Vì vậy trạng thái đúng là:

```text
HUMAN_GOLD_STATUS = NOT_CREATED
INDEPENDENT_HUMAN_GOLD_STATUS = BLOCKED_BEFORE_CALIBRATION
REAL_SEMANTIC_METRICS = NOT_MEASURED
```

### A.2 Authority và packet hiện tại

| Thành phần | Giá trị đã xác minh |
|---|---|
| Target parser | `canonical-v2-effective-public-prebind` |
| Target source commit | `08907c362d440aeb51ac024aedccf75de98a2b0f` |
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Question source | `data/raw/btc/questions/questions.jsonl` |
| Source records | 1,012 |
| Question source SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| Unique contaminated QIDs | 221 |
| Eligible QIDs | 791 |
| Headline core | 100 |
| Diagnostic supplement | 20 |
| Preselected reserve | 30 |
| Active annotation templates | 120 mỗi slot A/B/C |
| Model outputs in packet | `false` |
| Packet status | `OPEN_FOR_INDEPENDENT_REVIEW` |

Packet được audit tại:

```text
artifacts/runs/evaluation/
  semantic-gold-v2-phase1.5-packet-20260829-03/
```

Manifest của packet ghi đúng bốn blocker:

```text
INDEPENDENT_ANNOTATOR_A_UNASSIGNED
INDEPENDENT_ANNOTATOR_B_UNASSIGNED
DISTINCT_ADJUDICATOR_C_UNASSIGNED
SEMANTIC_METRICS_NOT_MEASURED_UNTIL_GOLD_IS_SEALED
```

### A.3 Contracts và implementation đang có

| Asset | Trạng thái thực tế |
|---|---|
| `configs/evaluation/semantic_gold_v2_schema.json` | Có; JSON Schema Draft 2020-12; record schema version 2 |
| `configs/evaluation/semantic_metric_concepts_v1.yaml` | Có 39 concepts; `DRAFT_FOR_CALIBRATION` |
| `configs/evaluation/semantic_operation_vocabulary_v1.yaml` | Có 17 operations; `DRAFT_FOR_CALIBRATION` |
| `configs/evaluation/semantic_gold_v2_protocol.yaml` | Có governance A/B/C và protected surface |
| `configs/evaluation/semantic_gold_v2_sampling.yaml` | Có và đã khóa 100/20/30 |
| `src/text2pandas/application/usecases/semantic_gold_v2.py` | Có sampler, template, contamination, governance/semantic validator và canonicalizer |
| `tools/evaluation/prepare_semantic_gold_v2.py` | Có; tạo immutable output directory, packet và hashes |
| `tests/unit/test_semantic_gold_v2.py` | Có tests cho spans, refs, units, frame, reviewer governance và vocab consistency |
| `tests/unit/test_semantic_gold_v2_sampling.py` | Có tests cho selection, contamination, authority và immutability |
| Human annotation UI/CLI | Không có |
| Human validation CLI | Không có |
| Agreement CLI | Không có |
| Adjudication CLI | Không có |
| Human sealer | Không có |
| Official V2 exporter/evaluator | Không có |

Gold registry hiện ghi semantic parser gold cũ có 40 records, chỉ 6 usable,
`promotion_eligible_records=0`, `independence=NONE`. Không được thay đổi registry
trước khi release human mới được seal.

### A.4 Canonical V2 boundary thực tế

Public pre-binding path gồm các thành phần:

```text
parse_intent(question)
requested_unit_of(question)
classify_operation(question)
parse_question(...) -> QuestionSemanticFrame
special formula/count/multi-entity recognizers
route(...) -> OperationIR
```

Các giới hạn có ảnh hưởng trực tiếp tới evaluation:

- `QuestionSemanticFrame.metric_id` không có metric concept hữu dụng trong public
  pre-bind call;
- generic frame không giữ metric surface span;
- `OperationIR` chỉ biểu diễn một số operation/roles và không phải canonical
  schema V2 đầy đủ;
- formula và một số multi-entity routes bypass generic frame;
- `metric_codes_hint()` là retrieval hint tới VAS code, không phải semantic
  concept prediction;
- selected table/row/cell thuộc resolver/selector/binder, không được dùng để
  backfill parser prediction.

Do đó official exporter phải giữ `MISSING_OUTPUT` khi runtime không phát field.
Không được dùng ontology lookup, V3 AST, A6 row hoặc answer để làm prediction đẹp
hơn.

### A.5 WP0–WP10: human flow so với local bypass

| WP | Human-flow status | Nhận định |
|---|---|---|
| WP0 — authority/contamination/protected surface | `IMPLEMENTED` | Packet có hashes, identities, ledger và protected-surface check |
| WP1 — schema/vocab/guideline | `PARTIAL_BLOCKED` | Files tồn tại nhưng còn draft và có schema gaps bắt buộc sửa trước pilot |
| WP2 — sampler/packet | `IMPLEMENTED` | 100/20/30, disjoint, prediction-blind, deterministic |
| WP3 — calibration pilot | `NOT_STARTED` | Chưa có 15-QID pilot manifest, reviewer hoặc tool |
| WP4 — final A/B annotation | `NOT_STARTED` | A/B chưa gán và templates trắng |
| WP5 — agreement | `COMMAND_NOT_IMPLEMENTED` | Chưa có tool/target |
| WP6 — adjudication C | `COMMAND_NOT_IMPLEMENTED` | Chưa có tool và human work |
| WP7 — seal release | `COMMAND_NOT_IMPLEMENTED` | Human sealer chưa có |
| WP8 — official V2 export | `COMMAND_NOT_IMPLEMENTED` | Chỉ có local synthetic exporter |
| WP9 — official evaluation | `COMMAND_NOT_IMPLEMENTED` | Chỉ có local synthetic evaluator |
| WP10 — human report/decision | `BLOCKED` | Không thể có trước sealed human gold |

Việc local report gọi WP3–WP10 là completed trong `LOCAL_SYNTHETIC` mode chỉ có
nghĩa các stage kỹ thuật đã được exercised. Nó không hoàn thành human WP3–WP10.

### A.6 Những schema/vocabulary gaps phải xử lý trước final annotation

Đây là calibration blockers, không phải lý do để annotator đoán:

1. Schema chỉ cho `scale_exponent` là `0, 3, 6, 9, 12` nhưng active 120 có
   **7 headline-core questions dùng “trăm tỷ” = 10^11**. Runtime unit lexicon đã
   hỗ trợ exponent 11, gold schema thì chưa.
2. Schema bắt mọi non-money unit có scale `null`, trong khi runtime hỗ trợ
   `SHARES@1e6`; câu “triệu cổ phiếu” không thể biểu diễn đúng.
3. Active 120 có **12 câu chứa ngày đầy đủ** như `31/12/2024`, nhưng period schema
   chỉ giữ year/quarter/point, không giữ ngày/tháng hoặc period span.
4. `operation_tree.children` không có node ID hoặc input edge. Parent không thể
   tham chiếu output của child, nên `(A-B)/B`, filter → rank → select và các tree
   lồng nhau không có representation unambiguous.
5. `FILTER_THRESHOLD` không giữ comparator/literal threshold. Active 120 có ít
   nhất 5 câu threshold/filter rõ ràng và 2 câu dùng median.
6. Operation vocabulary chỉ là danh sách enum, chưa định nghĩa ranh giới
   `GROWTH` với `PERCENT_CHANGE`, `ADD` với `SUM`, `MAXIMUM` với `ARGMAX`, hay
   `ARGMAX` với `SELECT_AT_ARG`.
7. `entity.semantic_role` là free text; schema không đóng vocabulary cho company,
   subsidiary, investee, industry, segment, population và comparand.
8. `ambiguity_alternatives` và `adjudication` là object tự do; chưa có contract
   bắt buộc `reading_a`, `reading_b`, `decision`, `rationale`, evidence refs.
9. JSON Schema cho `field_status` không bắt buộc đủ 8 components; chỉ pure
   semantic validator làm việc đó khi `require_complete=True`.
10. Schema cho attestations nhận `false` hoặc `null`; chỉ governance validator
    có thể enforce tất cả là `true` và A/B/C distinct.
11. Pure semantic validator chưa kiểm `concept_id` thực sự nằm trong frozen
    metric vocabulary và chưa enforce arity/role signature theo operation.

Không bắt đầu final A/B annotation trên contract hiện tại. Mọi thay đổi cần
version/checksum mới; không sửa sampling selections.

## B. Gold definition

### B.1 Annotation unit

```text
1 exact question = 1 semantic annotation record
```

Record ground-truth cho **ý nghĩa được biểu đạt bởi câu hỏi trước table/row/cell
binding**, gồm:

- entity mentions, canonical entity references và semantic roles;
- metric surface phrases, controlled concepts và reported/derived status;
- periods và vai trò của từng period;
- explicit/unspecified basis;
- requested unit và output shape;
- ordered operands;
- canonical operation/composition tree;
- field-level resolvability và genuine ambiguity;
- source locator dùng để chứng minh terminology/provenance khi cần.

Record **không** ground-truth cho:

- table retrieval candidate hoặc ranking score;
- VAS code, table ID, Silver row ID hay observation UID;
- numeric answer;
- Pandas query;
- correct bound cell/row;
- execution correctness.

`source_evidence` trong semantic gold chỉ là locator hỗ trợ interpretation. Nó
không tự động trở thành evidence-binding gold.

### B.2 Ba provenance modes

| Mode | Có phải semantic authority? | Dùng cho official evaluation? |
|---|---:|---:|
| `LOCAL_SYNTHETIC` | Không | Không |
| `HUMAN` | Có thể dùng nội bộ nếu provenance rõ | Không đủ cho methodology mạnh |
| `INDEPENDENT_HUMAN` | Có, sau A/B/C + seal | Có |

Official release phải ghi:

```text
gold_mode = INDEPENDENT_HUMAN
annotation_source = HUMAN
independent_review = true
human_adjudication = true
```

Các giá trị này chỉ được sealer sinh sau khi xác minh governance; annotator
không tự khai để biến một file thành gold.

### B.3 Question-level semantics

- `operation_tree.node`: operation root hoặc canonical composition root.
- `output.shape`: shape được hỏi, không phải unit dimension.
- `record_status`: trạng thái được derive từ field statuses, không phải confidence
  cảm tính của annotator.

Derivation bắt buộc:

```text
if any required field == UNRESOLVED: record_status = UNRESOLVED
else if any required field == AMBIGUOUS: record_status = AMBIGUOUS
else: record_status = RESOLVED
```

`NOT_APPLICABLE` chỉ tồn tại ở field level.

### B.4 Canonical semantic authority

Annotator chỉ ghi components. `canonical_semantic_frame(record)` phải derive
frame deterministic bằng cách:

- normalize Unicode NFC;
- uppercase enum values;
- sort entities/metrics/periods theo stable refs;
- giữ nguyên operand order và child order;
- bỏ components `NOT_APPLICABLE`;
- loại reviewer metadata, notes, adjudication metadata và evidence locators.

Annotator không được nhập `full_frame`. Hai lần canonicalize cùng input phải
byte-identical.

## C. Recommended annotation protocol

### C.1 Protocol duy nhất được khuyến nghị

```text
Freeze authority and roster
  -> create separate 15-QID calibration packet
  -> A/B question-only draft, independently
  -> A/B evidence verification, independently
  -> lock pilot A/B
  -> measure pilot disagreement
  -> C classifies guideline defect vs genuine ambiguity
  -> version/freeze schema + vocabularies + guideline
  -> regenerate final blank templates against frozen contracts
  -> A/B annotate 120 active QIDs privately
  -> validate and lock A/B
  -> compute pre-adjudication agreement
  -> C adjudicates every record
  -> validate final records and canonical frames
  -> activate reserve only if a predeclared condition is met
  -> seal immutable HUMAN release
  -> export frozen Canonical V2 predictions
  -> evaluate gold vs prediction
  -> publish metrics, taxonomy and boundary report
```

### C.2 Stage 0 — Governance and authority freeze

1. Assign three distinct pseudonymous reviewer IDs: A, B and C.
2. Verify they did not develop/tune the parser being measured.
3. Assign one evaluation engineer who prepares tools but cannot alter labels.
4. Bind source snapshot, question SHA, sampling selections, protected surface and
   target parser commit.
5. Keep selected QIDs unchanged.
6. Prevent parser changes on the protected surface until prediction export is
   sealed. A change requires a new parser target release, not a silent update.

If three eligible people are unavailable, use one human only for guideline
development and call the artifact `HUMAN_DRAFT`; do not seal it as
`INDEPENDENT_HUMAN`.

### C.3 Stage 1 — Calibration pilot

Use **15 questions**, selected deterministically from eligible QIDs that are in
none of core, diagnostic or reserve and are not in the contamination ledger.
Selection is question-text-only and coverage-oriented; it must contain:

- 2 easy/named lookup;
- 1 binary add/sum;
- 1 directional subtraction;
- 1 explicit ratio;
- 1 growth/percent-change boundary;
- 2 nested compositions including select-at-arg;
- 1 count + threshold/filter;
- 1 multi-entity directional;
- 1 basis-sensitive;
- 1 unit/scale-sensitive including 10^11 or scaled shares;
- 1 full-date/period case;
- 1 genuinely ambiguous candidate;
- 1 likely missing-vocabulary/schema case.

Pilot QIDs and their selection rule live in a separate calibration manifest.
They do not alter `semantic_gold_v2_sampling.yaml` and never enter release
metrics.

Pilot exit gate:

```text
no unresolved schema interpretation
operation definitions and arity frozen
all hard-case examples validate
A/B understand status taxonomy consistently
guideline/schema/vocab IDs and SHA-256 frozen
pilot excluded from release
```

Any contract change invalidates prior pilot labels. Regenerate templates and
repeat the affected pilot portion.

### C.4 Stage 2 — Independent final annotation

- A and B each annotate all 120 active records.
- Workspaces are private and access-controlled.
- A cannot see B; B cannot see A.
- Neither sees parser/resolver outputs or evaluation artifacts.
- Each record goes through question-only semantic draft first, then source
  verification.
- Each reviewer locks one canonical JSONL and attestation manifest. Lock means
  content SHA recorded and no further edit without a new pass ID.

### C.5 Stage 3 — Agreement and adjudication

Agreement is computed only after both A and B are locked and before C edits.
C then reviews **every record**, including exact agreements, because correlated
misreadings are possible.

For each differing field C records:

```text
reading_a
reading_b
decision = A | B | NEW | AMBIGUOUS | UNRESOLVED
rationale
source_evidence_refs[]
guideline_rule_id
```

`NEW` requires an explicit explanation of why both A and B are wrong. C cannot
use parser output. Genuine ambiguity is preserved with alternatives.

### C.6 Stage 4 — Reserve

Do not annotate the 30 reserve records initially. Activate a deterministic
prefix of the already checksummed reserve only before viewing predictions and
only for one of the existing reasons:

- corrupt source record;
- duplicate source record;
- fewer than 100 final resolved records;
- missing critical semantic family.

Activation creates a signed manifest amendment with reason, QIDs and timestamp.
It never removes the original unresolved QID, never changes the original
headline denominator and never raises the release over 150 records.

### C.7 Dataset size decision

Recommended initial release workload is 120 questions, with headline metrics on
the 100 equal-probability core only.

- 100 is acceptable for a first headline estimate, but uncertainty remains
  material: near 50% accuracy, a Wilson 95% interval has roughly ±9.6 percentage
  points.
- The 20 diagnostic questions improve failure coverage, not corpus estimation.
  They must not be pooled into headline accuracy.
- 150 is not the default. Reserve exists for the predeclared recovery cases.
  Even at 150, uncertainty improvement is modest and the diagnostic/reserve
  selection is not an unbiased combined headline sample.

Always report resolved/ambiguous/unresolved counts on all 100 core records and
`correct/scored/skipped` for every conditional metric. Never hide unscorable
records by changing the denominator silently.

### C.8 Single annotator vs independent A/B/C

| Tiêu chí | Một annotator | A/B độc lập + C adjudicate |
|---|---|---|
| Chi phí | Khoảng một pass | Hai full passes + C review toàn bộ; xấp xỉ 2.5–3 pass |
| Thời gian | Nhanh nhất | Dài hơn do lock, agreement và adjudication |
| Reliability | Không phát hiện systematic misreading của chính reviewer | Disagreement và rationale được quan sát; C vẫn kiểm correlated agreement |
| Bias | Phụ thuộc một người và prior của họ | Giảm single-reviewer bias nếu A/B/C thực sự độc lập |
| Reproducibility | Chỉ có final label | Có locked A/B, agreement artifact, C decision và audit trail |
| Methodology/submission | Chỉ phù hợp `HUMAN_DRAFT` hoặc local diagnosis | Phù hợp official semantic evaluation sau khi seal |

Giữ A/B/C cho official release vì protocol và packet hiện tại đã được thiết kế
theo mô hình này. Có thể dùng một annotator để thử UI, viết guideline hoặc tạo
non-official draft; không được giản lược official pass thành một người rồi giữ
nhãn `INDEPENDENT_HUMAN`.

## D. Annotator interface

### D.1 What A and B may see

First-pass interface:

- exact NFC question text;
- QID only as an opaque identifier;
- frozen schema, metric vocabulary, operation vocabulary and guideline;
- span selection and structured component/tree editor.

Second-pass evidence interface:

- source structure from the complete A6 files allowed by the fixed A6 build,
  with numeric cell payloads redacted from the semantic-labeling view;
- exact company/document metadata needed to resolve identity;
- deterministic, non-ranked search over the allowed source corpus;
- source path, row path and column label;
- no numeric value copied into the semantic annotation.

The UI must hide `cohort`, `primary_stratum` and `secondary_tags` while labeling.
Those question-text proxies are useful for sampling but can anchor annotators to
an expected operation family.

### D.2 What A and B must not see

```text
Canonical V2 prediction or trace
Semantic V3 AST/prediction
metric resolver output or VAS hints
retrieval candidates, ranks or scores
selected/bound table rows or cells from runtime
current answer, Pandas query or evidence list
LOCAL_SYNTHETIC labels
old semantic/answer/execution gold for the same QID
failure taxonomy or evaluation score
the other annotator's label
```

### D.3 Two-stage evidence rule

Source context is necessary for entity identity, reported terminology and
provenance, but it can bias meaning. Therefore each annotator must:

1. save a question-only semantic draft;
2. open source evidence only after the draft;
3. use evidence to verify identity/terminology/location, not derive an operation
   from numeric values;
4. log every semantic change made after source access with a reason.

`access_log.jsonl` records reviewer, QID, source path and action. It must never
record parser outputs. Source access and label work remain offline.

### D.4 Annotator ergonomics

Do not require manual JSON editing for the official pass. The proposed offline
annotator should provide:

- click/drag spans with exact offset preview;
- vocabulary search showing definitions, inclusion and exclusion examples;
- explicit status/reason selection;
- ordered operand builder;
- typed operation tree editor;
- inline schema/semantic validation;
- evidence locator picker against the frozen A6 build;
- save/lock with SHA-256.

The interface stores schema-valid JSONL; it is not a semantic recommender and
must not prefill parser-derived labels.

## E. Schema mapping

### E.1 Immutable envelope

| Field | Creation rule |
|---|---|
| `schema_version` | Set by frozen contract; annotator cannot edit |
| `qid` | Copied from selection manifest |
| `question` | Copied exactly from source, NFC |
| `question_sha256` | Recomputed and compared with source |
| `cohort` | Copied from selection; hidden in annotation UI |
| `selection_digest` | Copied from selection authority |
| `primary_stratum`, `secondary_tags` | Sampling metadata only; never semantic gold |
| `reviewer_slot` | A/B/C assigned by workspace |
| `reviewer_id` | Pseudonymous identity from roster; no free reassignment |
| `attestations` | Bound to reviewer and frozen contract hashes |

### E.2 Semantic fields

| Field | Human action | Validator/canonical action |
|---|---|---|
| `entities` | Select exact mention; choose canonical ref, resolution status and role | Validate occurrence/order/ref uniqueness; close role vocabulary |
| `metrics` | Select maximal concept phrase; choose concept ID and reported/derived | Validate span, frozen concept membership and version |
| `periods` | Enter every explicit/derived semantic period and role | Validate uniqueness, range expansion and operand refs |
| `basis` | Map explicit wording or `UNSPECIFIED,false` | Enforce explicit/value invariant |
| `unit` | Enter dimension, scale, currency and explicitness | Enforce scaled dimension rules |
| `operation_tree` | Build canonical ordered operation/composition | Enforce node types, arity, roles and child-output edges |
| `output` | Choose output shape | Keep distinct from unit dimension |
| `operands` | Define ordered leaves/axes and their refs | Validate entity/metric/period/basis/unit closure |
| `field_status` | Resolve field state with a reason for non-resolved | Require all 8 component keys |
| `record_status` | Not manually authoritative | Derive deterministically from field statuses |
| `source_evidence` | Select allowed locator or `NOT_LOCATED` | Verify path/build/existence; exclude values |
| `ambiguity_alternatives` | Enter each complete viable reading | Validate structured alternative contract |
| `adjudication` | C only | Enforce decision/rationale/evidence for all records |
| `notes` | Concise human explanation | Never part of canonical frame |

Only entity and metric currently carry text spans. Period span accuracy is
`NOT_REPRESENTED` in the current schema; do not claim it is measured.

### E.3 Required contract revision before pilot

Keep the dataset name “Semantic Gold V2”, but issue a new, checksummed annotation
contract revision before labeling. At minimum it must:

- support money exponent 11 and scaled shares;
- represent full date/month where semantically explicit;
- close entity type/role vocabulary;
- add typed tree node IDs and explicit input edges from operand or child output;
- represent filter comparator and literal/metric threshold;
- define operation arity and allowed ordered roles;
- structure ambiguity and adjudication;
- add reason codes for `MISSING_EVIDENCE`, `MISSING_VOCABULARY`,
  `SCHEMA_LIMITATION` and `QUESTION_AMBIGUITY` without turning them into new
  record statuses;
- bind schema/vocabulary/guideline version IDs and hashes in every pass.

If changes are breaking, bump the record schema version. Do not mutate the
meaning of `schema_version=2` in place merely by replacing a checksum.

## F. Guideline

### F.1 Status taxonomy

| Status | Exact use |
|---|---|
| `RESOLVED` | Meaning is determined by allowed inputs and representable in frozen schema |
| `AMBIGUOUS` | Question genuinely licenses at least two readings; alternatives are recorded |
| `UNRESOLVED` | A required field cannot be determined or represented; reason code is mandatory |
| `NOT_APPLICABLE` | Field has no semantic role for this question; field-level only |

Annotator uncertainty is not automatically ambiguity. The annotator must review
the guideline and allowed evidence first. UI/format mistakes are
`ANNOTATION_ERROR` and must be corrected before lock; they are not a gold status.

Examples of `UNRESOLVED` reasons:

- entity cannot be identified from allowed source;
- metric meaning is clear but frozen vocabulary lacks it;
- required evidence is unavailable;
- frozen schema cannot express the structure.

Do not force `RESOLVED` to meet the minimum record count.

### F.2 Spans

- Unicode NFC.
- Zero-based, half-open offsets `[start,end)`.
- Require `question[start:end] == text` exactly.
- Choose the maximal phrase carrying the concept, excluding entity, period,
  unit and boilerplate.
- Repeated occurrences get separate refs in source order when they play separate
  semantic roles.
- Do not normalize diacritics inside stored spans.

### F.3 Metrics

- A metric concept is question meaning, not a Silver/A6 row or VAS code.
- A named reported ratio such as “tỷ lệ nợ xấu” is one named metric when no
  components are spelled out.
- An explicit expression such as “nợ xấu trên tổng dư nợ” is a composed
  `DIVIDE`, with separate metric phrases and operands.
- `REPORTED` means the question asks for a named reported concept.
- `DERIVED` means the question explicitly composes/calculates the concept.
- Synonyms map only through the frozen vocabulary definition and examples.
- A missing concept discovered in pilot is added/versioned before final A/B.
- During final A/B, never use vague `OTHER_REPORTED_METRIC` to conceal a missing
  controlled concept; mark unresolved and trigger governance review.

### F.4 Entities

- Annotate legal company/ticker mention independently of canonical reference.
- Resolve company, subsidiary/investee, industry, segment and explicit group as
  distinct entity types after the revised entity vocabulary is frozen.
- Preserve mention order for directional comparisons.
- A ticker embedded in a legal name is not automatically a second entity.
- Multi-entity population membership is not alphabetically reordered unless the
  semantics are explicitly set-like.
- If identity is not supported by question and allowed source, do not guess.

### F.5 Periods

- Annotate every named year/quarter/date.
- Expand an explicit ascending year range to every included year.
- `CURRENT/PREVIOUS` and `NEW/OLD` follow question direction, not file column
  order.
- Distinguish flow period from opening/closing/instant point.
- Preserve per-operand periods.
- YoY uses `NEW` at current period and `OLD` at previous period.
- A full date stays a full date after the schema revision; do not silently reduce
  `31/12/2024` to year 2024.

### F.6 Basis

```text
hợp nhất              -> CONSOLIDATED, explicit=true
công ty mẹ/riêng lẻ   -> SEPARATE, explicit=true
no basis wording      -> UNSPECIFIED, explicit=false
```

The runtime consolidated default is a retrieval prior, not user-stated gold.
Mixed-basis composition stores basis per operand. “Khối ngân hàng mẹ” and other
domain wording must be covered by frozen examples before final labeling.

### F.7 Units and output

Unit and output shape remain orthogonal:

```text
triệu đồng       -> MONEY, 10^6, VND
tỷ đồng          -> MONEY, 10^9, VND
trăm tỷ đồng     -> MONEY, 10^11, VND
nghìn tỷ đồng    -> MONEY, 10^12, VND
triệu cổ phiếu   -> SHARES, 10^6
%                -> PERCENT
điểm phần trăm   -> PERCENT_POINT
lần              -> RATIO
số lượng         -> COUNT
```

`SCALAR`, `ENTITY`, `PERIOD`, `COUNT`, `TABLE`, `SET`, `BOOLEAN`, `OTHER` are
output shapes. `RATIO` and `PERCENT` are dimensions, not output shapes.

### F.8 Operations

Only the 17 current vocabulary symbols may be used after their definitions are
frozen:

```text
LOOKUP ADD SUBTRACT DIVIDE GROWTH PERCENT_CHANGE SUM AVERAGE COUNT
MINIMUM MAXIMUM ARGMIN ARGMAX SELECT_AT_ARG FILTER MEDIAN OTHER
```

`MULTIPLY` is not supported. A multiplication question cannot be labeled
`MULTIPLY`; calibration must decide whether to version the vocabulary or mark
the field unresolved. Do not misuse `OTHER` to avoid a contract decision.

Mandatory semantic conventions:

- `LOOKUP(VALUE)` returns the requested value.
- `ADD(LEFT,RIGHT)` is binary addition; `SUM(SUMMAND...)` is a variadic
  aggregation. Exact arity is frozen in the revised operation vocabulary.
- `SUBTRACT(MINUEND,SUBTRAHEND)` preserves A−B direction.
- `DIVIDE(NUMERATOR,DENOMINATOR)` preserves A/B direction.
- `GROWTH(NEW,OLD)` represents a frozen time-growth definition. The pilot must
  resolve its boundary with `PERCENT_CHANGE` before final annotation.
- `MINIMUM/MAXIMUM` return a value.
- `ARGMIN/ARGMAX` return the entity/period attaining an extremum.
- `SELECT_AT_ARG` returns a projected value at the arg selected by a rank key.
- `FILTER` restricts a population and must carry comparator/threshold after the
  schema revision.
- `COUNT` counts members of an explicitly represented domain/filter.
- `MEDIAN` is a real operation node, not a reported metric phrase.

## G. Hard cases

### G.1 Directional arithmetic truth table

| Question meaning | Root/tree | Ordered roles |
|---|---|---|
| `A - B` | `SUBTRACT` | `MINUEND=A`, `SUBTRAHEND=B` |
| `B - A` | `SUBTRACT` | `MINUEND=B`, `SUBTRAHEND=A` |
| `A / B` | `DIVIDE` | `NUMERATOR=A`, `DENOMINATOR=B` |
| `B / A` | `DIVIDE` | `NUMERATOR=B`, `DENOMINATOR=A` |
| `(A-B)/B` | `DIVIDE(SUBTRACT(A,B),B)` | child output is numerator; B denominator |
| `(A-B)/A` | `DIVIDE(SUBTRACT(A,B),A)` | child output is numerator; A denominator |

The last two require the revised typed-edge tree. They are not safely encodable
with current `children[] + operands[]` alone.

### G.2 Required hard-family policy

| Family | Required interpretation rule |
|---|---|
| `NESTED_COMPOSED` | Identify outer requested result first; then build typed child nodes bottom-up |
| `ARG_SELECT_PROJECT` | Separate ranking metric (`RANK_KEY`) from returned metric (`PROJECTED_VALUE`) |
| `DIVIDE_EXPLICIT_RATIO` | Named ratio stays a metric; explicit numerator/denominator becomes `DIVIDE` |
| `SUBTRACT_DIRECTIONAL` | Follow grammar/source order; “A thấp hơn B bao nhiêu” still requires explicit minuend policy in frozen examples |
| `GROWTH_PERCENT_CHANGE` | Use only the post-pilot definitions; never infer formula from answer value |
| `MULTI_ENTITY_DIRECTIONAL` | Preserve entity roles and direction; do not canonical-sort away semantics |
| `COUNT` | Represent counted domain, filter predicate and threshold before `COUNT` |
| `BASIS_SENSITIVE` | Explicit wording controls gold; runtime default is excluded |
| `UNIT_SCALE_SENSITIVE` | Preserve explicit scale exactly, including 10^11 and scaled shares |

### G.3 Rank/filter/select examples

- “Năm có X cao nhất” → `ARGMAX` with period output.
- “Y tại năm có X cao nhất” → `SELECT_AT_ARG`, rank key X, projected value Y.
- “Trong các năm X > 10%, Y thấp nhất” → `FILTER` then `MINIMUM` over Y.
- “Công ty có X thấp nhất có Y là bao nhiêu” → rank/select across entity domain.
- “Thấp hơn trung vị rồi chọn cao nhất” → `MEDIAN` feeds `FILTER`, then rank,
  then select if returned metric differs from rank key.

These examples must be serialized in valid fixture JSON under the revised
schema before annotators see the final packet.

### G.4 Ambiguity and insufficiency

- Two linguistically valid operand directions → `AMBIGUOUS` plus both full
  alternatives.
- Metric wording clear but absent vocabulary → `UNRESOLVED/MISSING_VOCABULARY`.
- Entity alias maps to multiple companies after allowed evidence →
  `AMBIGUOUS` if both readings are supported; otherwise
  `UNRESOLVED/MISSING_EVIDENCE`.
- Schema cannot encode a clear meaning → `UNRESOLVED/SCHEMA_LIMITATION`, never a
  fabricated nearest label.
- Answer values may not be consulted to choose among readings.

## H. QC

### H.1 Per-record validation

Every draft and locked record must pass both full JSON Schema validation and
semantic relation validation. Required checks:

```text
exact source QID/question/question_sha256
NFC and exact half-open span occurrence
stable span order and unique refs
concept membership in frozen vocabulary
entity-role membership in frozen vocabulary
all eight field_status keys present
record_status equals deterministic derivation
operation node, arity and ordered role signature
operand/entity/metric/period closure
typed child-output closure
basis explicitness invariant
unit dimension/scale/currency invariant
evidence path inside frozen A6 build
non-resolved reason/alternative present
no forbidden prediction-shaped field
reviewer slot/identity/attestation consistency
```

The current prepare tool only checks template top-level fields plus the pure
semantic validator; official validator must execute the full schema and the
stronger relation checks above.

### H.2 Dataset validation

- A and B QID sets exactly equal the 120 active selection.
- No duplicate, missing or extra QID.
- A/B question and selection digests match packet.
- Cohorts are disjoint and contamination QIDs absent.
- A/B/C identities are pairwise distinct.
- A/B locked before agreement; C starts after agreement artifact is sealed.
- All C records exist; every disagreement has structured adjudication.
- C reviews exact-agreement records too.
- Canonical output generated twice is byte-identical.
- Protected surface matches the target parser authority.
- Existing output directory fails closed; no in-place overwrite.

### H.3 Pre-adjudication agreement

Use the metrics already specified in the Phase 1.5 plan:

- entity mention exact and overlap F1;
- entity reference exact;
- metric phrase exact and overlap F1;
- metric concept exact;
- operand count exact;
- ordered operand role exact;
- operand metric and role+metric exact;
- period and period-role exact;
- basis, unit, operation and output exact;
- full canonical frame exact.

Report numerator/denominator. Cohen's kappa is used only for a supported
single-label categorical field, never forced onto nested trees.

Pause and investigate when pilot/final checkpoint is below the existing plan:

```text
metric concept agreement < 0.85
OR ordered operand role agreement < 0.85
OR full-frame agreement < 0.70
```

If the cause is a guideline defect, version the contract and have **both A and
B** reannotate the affected scope. Do not fix agreement by consulting parser
behavior.

### H.4 Tests to add before human work

Add positive and negative fixtures for:

- exponent 11 and scaled shares;
- full dates;
- nested child-output references;
- filter comparators/thresholds and median;
- every operation arity/role signature;
- unknown concept ID;
- free/invalid entity role;
- record/field status mismatch;
- incomplete/invalid ambiguity alternative;
- incomplete adjudication;
- evidence path outside active A6;
- annotator UI leaking cohort/tags/predictions;
- A/B file mutation after lock;
- reserve activation after prediction access.

## I. Freeze

### I.1 Seal conditions

Sealer fails closed unless:

- release contains 100–150 records;
- resolved/ambiguous/unresolved counts are explicit;
- dual annotation and full C adjudication are complete;
- roster and attestations validate;
- all record/dataset QC passes;
- contract/source/selection/protected hashes match;
- no prediction-shaped data exists in review/gold files;
- agreement was computed before adjudication;
- final canonical frames are deterministic;
- output release directory does not already exist.

### I.2 Recommended immutable release layout

```text
data/curated/gold/semantic_gold_v2/<release_id>/
  manifest.json
  gold.jsonl
  canonical_frames.jsonl
  reviews/
    annotator_a.locked.jsonl
    annotator_b.locked.jsonl
    adjudicator_c.locked.jsonl
  adjudication.jsonl
  agreement_pre_adjudication.json
  coverage_matrix.json
  contamination_ledger.json
  reserve_activation.json
  reviewer_attestations.json
  contracts/
    schema.json
    metric_vocabulary.yaml
    operation_vocabulary.yaml
    guideline.md
    sampling.yaml
    protocol.yaml
  checksums.sha256
```

`access_log.jsonl` may remain in a controlled audit artifact if it contains
sensitive reviewer metadata; the release manifest must still bind its SHA and a
non-sensitive access-policy summary.

### I.3 Manifest minimum

```text
release_id and supersedes
status = SEALED
gold_mode = INDEPENDENT_HUMAN
annotation_source = HUMAN
independent_review = true
human_adjudication = true
question source path/count/SHA-256
raw/A6/retrieval IDs
target parser source commit
selection and contamination hashes
schema/vocabulary/guideline/protocol versions and hashes
A/B/C pseudonymous IDs and attestation hashes
record/cohort/status counts
reserve activation state/reasons
gold and canonical-frame SHA-256
protected-surface SHA-256/result
tool source commit and environment
```

After seal, no file is edited in place. A correction creates a new release ID,
records `supersedes`, carries a changelog and triggers a fresh prediction/eval
run. Registry update occurs only from a verified SEALED manifest.

## J. Evaluation

### J.1 Gold vs prediction contract

```text
SEALED HUMAN GOLD                    FROZEN CANONICAL V2
canonical semantic components        effective public pre-bind export
              \                      /
               strict comparison
                      |
          metrics + failures + boundary
```

Gold and prediction are produced separately. Exporter verifies the release is
SEALED, but reads only selected questions and fixed parser authority when
generating predictions. Evaluator is the first component allowed to read both
locked assets.

Prediction must not update gold. Gold must not be used to fill missing
prediction fields.

### J.2 Metrics that human semantic gold can support

The local-only evaluator currently contains exact definitions for these 14
metrics:

```text
Entity Reference Accuracy
Metric Phrase Exact Match
Metric Concept Accuracy
Period Exact Match
Period Role Accuracy
Basis Accuracy
Unit Accuracy
Operation Accuracy
Result Kind Accuracy
Operand Count Accuracy
Operand Role Accuracy
Operand Metric Accuracy
Operand Role+Metric Accuracy
Full Semantic Frame Exact
```

These formulas are reusable evidence of intended scoring, but the current code
is coupled to `LOCAL_SYNTHETIC`; **official human evaluation remains
COMMAND_NOT_IMPLEMENTED**.

Scoring contract:

- headline uses only `HEADLINE_CORE`;
- score only adjudicated `RESOLVED` records for field accuracy;
- `NOT_APPLICABLE` is skipped, never counted correct;
- missing or extra applicable prediction is wrong;
- ordered lists/roles are record-level exact unless the named metric explicitly
  says span overlap;
- report correct/scored/skipped, point estimate and Wilson 95% CI;
- report core status yield on the fixed 100 denominator;
- diagnostic and activated reserve are separate tables;
- never publish one combined 100+20(+reserve) corpus accuracy.

### J.3 Current measurable/not-measurable matrix

| Quantity | After sealed human gold + official evaluator | Current repository now |
|---|---|---|
| 14 strict semantic metrics above | `MEASURABLE` | `NOT_MEASURED`; official command absent |
| Entity mention parser accuracy | Schema can represent it | `COMMAND_NOT_IMPLEMENTED` in current evaluator |
| Record status accuracy | Prediction status taxonomy is not aligned to gold status | `NOT_MEASURABLE` |
| A/B inter-annotator agreement | Measurable after two locked human passes | `NOT_MEASURED`; command absent |
| Metric resolver to VAS/table row accuracy | Semantic gold does not contain binding authority | `NOT_MEASURABLE` |
| Selector/binder accuracy | No independent ordered observation/cell gold | `NOT_MEASURABLE` |
| Numeric answer/execution accuracy | No answer/query gold in this dataset | `NOT_MEASURABLE` |

Do not rename route coverage, prediction completeness, abstention rate or replay
consistency to “accuracy”.

### J.4 Failure taxonomy and boundary

For each mismatch preserve:

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

Parser-only boundaries supported by this dataset:

- phrase/concept/entity/period/basis/unit mismatch before binding → `PARSER`;
- operation/tree/ordered role mismatch → `PARSER_OR_SEMANTIC_COMPILER`.

Do not assert `METRIC_RESOLVER` or `SELECTOR_BINDER` correctness from semantic
gold alone. Those labels require a separate independent evidence-binding gold.
E2E traces may describe where execution abstained, but cannot create resolver
accuracy.

## K. Files

### K.1 Keep unchanged as authorities

```text
configs/evaluation/semantic_gold_v2_sampling.yaml
configs/evaluation/semantic_gold_v2_known_development_qids.jsonl
data/raw/btc/questions/questions.jsonl
configs/datasets/active_snapshot.yaml
```

Do not modify production parser/protected surface in this workstream.

### K.2 Version before pilot

Do not overwrite the existing semantics silently. Create/version:

```text
configs/evaluation/semantic_gold_v2_human_protocol.yaml
configs/evaluation/semantic_gold_v2_pilot_sampling.yaml
configs/evaluation/semantic_gold_v2_schema_<revision>.json
configs/evaluation/semantic_metric_concepts_<revision>.yaml
configs/evaluation/semantic_operation_vocabulary_<revision>.yaml
data/curated/gold/semantic_gold_v2/GUIDELINE_<revision>.md
```

The human protocol references the unchanged sampling selection and new contract
hashes. After pilot, all final templates are regenerated against these frozen
files.

### K.3 Code/tools to implement

Reuse `semantic_gold_v2.py` pure functions, then add:

```text
tools/evaluation/prepare_semantic_gold_v2_pilot.py
tools/evaluation/annotate_semantic_gold_v2.py
tools/evaluation/validate_semantic_gold_v2.py
tools/evaluation/measure_semantic_agreement_v2.py
tools/evaluation/adjudicate_semantic_gold_v2.py
tools/evaluation/seal_semantic_gold_v2.py
tools/evaluation/export_canonical_v2_semantics.py
tools/evaluation/evaluate_semantic_gold_v2.py
tools/evaluation/report_semantic_gold_v2.py
```

Add corresponding unit tests for annotation UI isolation, schema/semantic
validation, agreement, adjudication, seal, export and evaluator. Add fail-closed
Make targets only when the underlying tools exist.

## L. Commands

### L.1 Commands that exist now

Packet preparation is implemented:

```bash
make semantic-gold-v2-prepare \
  PY=/opt/anaconda3/bin/python \
  PROTOCOL=configs/evaluation/semantic_gold_v2_protocol.yaml \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-<run_id>
```

This creates blank reviewer templates. It does not create human gold.

The following also exists, but is explicitly excluded from the human flow:

```bash
make semantic-gold-v2-local-e2e MODE=LOCAL_SYNTHETIC ...
```

It may validate plumbing only.

### L.2 Target command-level human flow

| Stage | Intended command | Current status |
|---|---|---|
| prepare pilot/final packet | `make semantic-gold-v2-prepare ...` | `IMPLEMENTED` for current packet; pilot/revised contract support still needed |
| annotate A/B | `make semantic-gold-v2-annotate ...` | `COMMAND_NOT_IMPLEMENTED` |
| validate/lock A/B | `make semantic-gold-v2-validate ...` | `COMMAND_NOT_IMPLEMENTED` |
| measure agreement | `make semantic-gold-v2-agreement ...` | `COMMAND_NOT_IMPLEMENTED` |
| adjudicate C | `make semantic-gold-v2-adjudicate ...` | `COMMAND_NOT_IMPLEMENTED` |
| freeze/seal | `make semantic-gold-v2-seal ...` | `COMMAND_NOT_IMPLEMENTED` |
| export V2 predictions | `make semantic-parser-v2-export ...` | `COMMAND_NOT_IMPLEMENTED` |
| evaluate | `make semantic-parser-v2-evaluate ...` | `COMMAND_NOT_IMPLEMENTED` |
| final report | `make semantic-parser-v2-report ...` | `COMMAND_NOT_IMPLEMENTED` |

The target sequence after implementation is:

```text
prepare
-> annotate A/B
-> validate + lock
-> agreement
-> adjudicate C
-> validate final
-> seal
-> export frozen prediction
-> evaluate
-> report
```

Do not paste planned Make targets into operational instructions until their
scripts, tests and fail-closed checks exist.

## M. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Synthetic/self-label leakage | Circular evaluation | Isolate human workspaces; forbid local labels and predictions; audit access |
| Proxy tags shown to annotator | Operation anchoring | Hide cohort/strata/tags in UI |
| Evidence selected by runtime | Resolver output becomes gold authority | Full, deterministic non-ranked source browser; log access |
| Numeric answer reverse-engineering | Operation direction chosen from outcome | Do not expose/copy values; direction comes from language only |
| Draft schema cannot encode real questions | False unresolved or fabricated nearest label | Version/fix schema before pilot/final annotation |
| Operation vocabulary underspecified | A/B disagreement and unstable frame | Add definitions, arity, roles and canonical examples during pilot |
| One annotator bias | Unobservable systematic error | Use independent A/B + distinct C for official release |
| A/B share parser-development priors | Correlated error | Require non-developer reviewers and blindness attestation; C reviews agreements |
| Attestation not machine-provable | Independence overclaimed | Treat as verified-by-attestation, preserve roster/access audit, never claim cryptographic proof |
| Unresolved records silently skipped | Inflated conditional accuracy | Report fixed-core status yield and correct/scored/skipped |
| Pooling diagnostic with core | Biased headline | Separate all cohort tables |
| Reserve activated after seeing scores | Evaluation tuning | Activate only before prediction access with manifest amendment |
| Source/version drift | Non-reproducible gold | Bind all source/contracts/tools with SHA-256 |
| Gold edited after evaluation | Test-set leakage and moving target | Immutable release IDs; corrections supersede |
| Semantic evidence mistaken for binding gold | False resolver accuracy | Keep resolver/binder/answer metrics `NOT_MEASURABLE` |
| n=100 overinterpreted | Unstable phase decision | Wilson CI, exact denominators and follow-up independent release |

## N. Final recommendation

Use exactly one official protocol: **15-QID excluded calibration pilot, followed
by independent A/B annotation of the existing 100 core + 20 diagnostic packet,
full review by distinct adjudicator C, immutable seal, then frozen Canonical V2
export and strict core-only evaluation**.

Do not start human labels yet. The immediate next engineering milestone is:

```text
1. version/fix the schema and operation vocabulary gaps identified in A.6;
2. implement the prediction-blind 15-QID pilot packet and offline annotator;
3. implement full validator + lock + agreement + adjudication contracts;
4. run the pilot with real A/B/C;
5. freeze contracts before touching the 120 final records.
```

If three independent eligible reviewers cannot be assigned, stop at
`HUMAN_DRAFT`/`OPEN_FOR_INDEPENDENT_REVIEW`. Do not relabel the existing
`LOCAL_SYNTHETIC` artifacts, do not weaken the release gate, and do not publish
real semantic accuracy until a SEALED `INDEPENDENT_HUMAN` release exists.
