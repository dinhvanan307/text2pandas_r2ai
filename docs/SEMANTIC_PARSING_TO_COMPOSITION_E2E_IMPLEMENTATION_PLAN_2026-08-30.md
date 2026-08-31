# Semantic Parsing → Metric/Source → Axes → Composition

## End-to-End Implementation and Release Plan trên SAFE baseline 3831

**Ngày lập:** 2026-08-30  
**Mục tiêu trực tiếp:** tăng Answer/Execution Accuracy nhưng không làm mất thành quả của submission 3831  
**Baseline leaderboard do người dùng xác nhận:** submission `3831`, Answer/Execution Accuracy `0.3874`  
**Chế độ triển khai:** shadow → differential → source adjudication → recover-only overlay  
**Trạng thái plan:** sẵn sàng thực thi; chưa phải báo cáo kết quả

---

## 1. Executive decision

Không chuyển toàn bộ runtime sang Semantic V3 và không thay thế các answer đang có. Flow nâng cấp được triển khai theo strangler architecture đã chấp nhận trong ADR-0008 và ADR-0015:

```text
Question
  ↓
Semantic parsing
  ↓
Metric/source resolution
  ↓
Entity/period/basis/filter/rank axes
  ↓
Compositional AST + joint binding
  ↓
Typed execution ↔ restricted-Pandas replay
  ↓
Source adjudication
  ↓
Recover-only overlay trên SAFE baseline 3831
```

Quy tắc release:

```text
Nếu baseline 3831 đã có answer:
    giữ nguyên answer/query/evidence tuyệt đối

Nếu baseline 3831 đang abstain:
    chỉ thêm answer khi semantic + source + execution gates đều PASS

Retrieval:
    giữ nguyên relevant_tables/relevant_docs của 1.012 QID
```

Semantic V3 tiếp tục chạy shadow. Một QID vượt các gate có thể được port thành recovery record; điều đó không đồng nghĩa toàn bộ V3 đủ điều kiện production promotion.

---

## 2. Baseline và bằng chứng hiện có

### 2.1 Submission 3831

ZIP đã upload có nguồn từ handoff:

```text
artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830/submission.zip
```

SHA-256:

```text
c1494ea630e7654def93a426d6f00b31f77fef05a67baac4e07e1ac7be262245
```

Baseline shape:

| Thuộc tính | Giá trị |
|---|---:|
| Total QID | 1,012 |
| Executable | 792 |
| Abstention | 220 |
| Clean replay | 792/792 |
| Answer/Execution Accuracy | 0.3874 |
| Tables F2 | 0.3151 |
| Docs F2 | 0.7361 |

Score `0.3874` tương thích với khoảng `392/1,012` câu đúng. Wave 3 thêm 29 answer và tạo khoảng 18 official wins, tương đương conversion rate quan sát được `18/29 ≈ 62.1%`. Đây là aggregate official evidence, không cho biết QID nào đúng/sai.

### 2.2 Active data identity

Đọc duy nhất từ `configs/datasets/active_snapshot.yaml`:

| Layer | Identity |
|---|---|
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| A6 database SHA-256 đã khóa | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |

Không chọn snapshot bằng `latest`, mtime hoặc directory order.

### 2.3 Remaining 220-QID backlog

| Repair class | QID còn lại |
|---|---:|
| Complex composition | 102 |
| Single-metric average | 47 |
| Two-period difference | 25 |
| Simple extremum | 15 |
| Direct lookup | 13 |
| Direct ratio | 11 |
| Single-metric sum | 7 |
| **Tổng** | **220** |

Risk distribution còn lại:

| Risk tier | QID |
|---|---:|
| A | 62 |
| B | 15 |
| C | 99 |
| D | 44 |

Source-attempt status:

| Status | QID |
|---|---:|
| REJECTED | 210 |
| SHADOW_OK | 6 |
| PROMOTED_RECOVERY nhưng chưa vượt source adjudication | 4 |

Vì vậy bottleneck không phải chỉ là formatter. Phần lớn QID chưa có một chuỗi semantic/source/execution đủ chắc chắn để phát answer.

---

## 3. Phạm vi và non-goals

### 3.1 In scope

1. Khóa submission 3831 làm SAFE baseline mới.
2. Tạo full-corpus failure funnel cho 220 abstention.
3. Cải thiện bốn layer theo thứ tự:
   - semantic parsing;
   - metric/source resolution;
   - filter/entity/period/basis/rank axes;
   - compositional planning, binding và execution.
4. Chạy shadow/differential trên đủ 1,012 QID sau mỗi phase.
5. Port các QID vượt gate vào một Wave 4 recover-only candidate.
6. Giữ nguyên retrieval và 792 answer hiện có.
7. Validate, replay, build hai lần byte-identical và đóng gói handoff.

### 3.2 Out of scope

- Không resume MODEL_GOLD generation.
- Không dùng model-generated gold làm runtime truth hoặc promotion gold.
- Không tạo ontology thứ ba.
- Không thêm QID-specific branch.
- Không đổi embedding, reranker hoặc retrieval profile trong candidate Answer này.
- Không bật `replace_trusted`/`replace_all`.
- Không hạ validator, binding margin hoặc source requirements để tăng coverage.
- Không tuyên bố accuracy từ route coverage, candidate recall hoặc replay.
- Không promote toàn bộ Semantic V3 khi independent promotion gold vẫn thiếu.

---

## 4. Kiến trúc đích theo repository hiện tại

### 4.1 Không tạo lại các contract đã tồn tại

| Khái niệm cần có | Contract hiện tại cần dùng |
|---|---|
| MetricSpec | `MetricDefinition` trong `domain/metrics/ontology.py` |
| SelectorSpec runtime | `OperandRequest` trong `application/planning/contracts.py` |
| Semantic program | `QuestionAST` trong `domain/semantic/ast.py` |
| Parse result/candidates | `ParseResult` và `ParseCandidate` |
| Global selection | `JointBinder` và `BoundExecutionPlan` |
| Typed calculation | `TypedExecutor` |
| Replayable query | `compile_pandas()` |
| Source-specific fallback | `MetricBindingHint` + `A6MetricMentionResolver` |
| Grounded candidate adapter | `GroundedAstCompiler` / `GroundedAstGenerator` |

`MetricDefinition` đã chứa aliases, statement types, unit/dimension, period semantics, preferred basis, sign policy, forbidden prefixes/contains và legal aggregations. `OperandRequest` đã chứa entity, period, basis, preferred basis, statement types, expected unit, qualifiers, required context và source binding. Plan sẽ mở rộng/siết các contract này nếu có bằng chứng, không tạo `MetricSpecV2` hoặc `SelectorSpecV2` song song.

### 4.2 Runtime boundary

```text
LegacyVietnameseAnnotator
  → SemanticParser.parse_candidates()
  → QuestionAST structural validation
  → compile_execution_plan()
  → operand-aware A6 retrieval
  → JointBinder.bind_candidates(limit=3)
  → TypedExecutor.execute()
  → compile_pandas()
  → sandbox replay
  → evidence from bound observation UIDs
```

Nếu nhiều parse/binding candidates sống sót nhưng tạo answer khác nhau, kết quả phải abstain. Không lấy candidate đầu tiên hoặc candidate có score cao nhất khi semantic ambiguity chưa được giải quyết.

---

## 5. Measurement contract

Mọi report phải giữ riêng các metric sau:

| Layer | Measurement |
|---|---|
| Parser | parse coverage, terminal-reason distribution, AST exact match nếu có independent gold |
| Resolver | mention coverage, candidate recall, unique resolution rate, ambiguity rate |
| Axes | entity/period/basis/filter/rank scope exactness |
| Binding | coherent assignment rate, binding exact match nếu có gold, score margin |
| Execution | typed success, Pandas compile success, typed↔Pandas match |
| Candidate | protected-answer preservation, retrieval preservation, replay |
| Leaderboard | official Answer/Execution Accuracy và retrieval metrics |

Không có gold phù hợp thì ghi `NOT_MEASURED`, không thay bằng coverage proxy.

### Hai release policies tách biệt

1. **Per-QID recovery policy:** cho phép một QID baseline-abstain được thêm vào candidate khi record đã source-adjudicated và replay sạch.
2. **Global Semantic V3 promotion policy:** vẫn chịu `configs/semantic/promotion_policy_v3.yaml`, bao gồm sealed evaluation release và independent parser/binding/answer gold.

Một Wave 4 candidate PASS không làm Global V3 trở thành `PROMOTABLE`.

---

## 6. Phase 0 — Freeze SAFE baseline 3831

### Công việc

1. Copy đúng ZIP SHA `c1494...` vào immutable official directory:

```text
artifacts/official/submission-3831/submission.zip
```

2. Tạo:

```text
provenance/submissions/submission_3831.json
```

3. Append một record vào:

```text
configs/evaluation/submission_ledger_v1.json
```

4. Ghi official row do người dùng cung cấp; `receipt_path` để `null` nếu chưa có receipt bền vững.
5. Inspect ZIP và xác nhận:
   - 1,012 unique records;
   - 792 executable;
   - 220 abstention;
   - 1 root JSON;
   - không orphan CSV/duplicate member;
   - clean replay 792/792.
6. Khóa question SHA, A6 SHA, retrieval index ID và Git identity.

### Gate P0

| Gate | PASS condition |
|---|---|
| ZIP identity | SHA đúng `c1494...` |
| Official mapping | submission ID 3831 + timestamp + 10 metrics được ghi |
| Coverage | 1,012 records, 792 executable, 220 abstain |
| Replay | 792/792, 0 mismatch, 0 execution error |
| Retrieval | metrics/artifact layer đúng lineage 3831 |

Nếu SHA hoặc mapping không khớp: dừng. Không bắt đầu sửa semantic trên một baseline chưa seal.

### Commit

```text
docs(provenance): freeze official submission 3831
```

---

## 7. Phase 1 — Rebuild failure funnel và protected sets

### 7.1 Inventory mới từ 3831

Không tái sử dụng inventory 3830 chỉ bằng tên. Regenerate inventory với baseline 3831 và khóa manifest:

```text
artifacts/runs/evaluation/recovery-wave4-3831-inventory-<run-id>/
├── inventory.jsonl
├── summary.json
└── manifest.json
```

Mỗi QID phải ghi:

- parser status/reason;
- metric resolver status và hypotheses;
- requested operands;
- source candidate counts;
- axis cardinalities;
- binder status/margin;
- typed/compile/replay status;
- repair class;
- risk tier;
- correctness=`NOT_MEASURED` nếu chưa adjudicate.

### 7.2 Protected sets

| Set | Nội dung | Quy tắc |
|---|---|---|
| P-answer | 792 QID executable của 3831 | answer/query/evidence phải byte-equivalent |
| P-retrieval | đủ 1,012 QID | relevant tables/docs phải giống 3831 |
| P-wave3 | 29 QID Wave 3 | không xóa fill; dùng để audit pattern |
| W4-pool | 220 abstention | chỉ pool này được thêm answer |

### 7.3 Diagnostic review của 29 Wave 3

Blind re-audit 29 QID theo metric, basis, period, operation, sign, unit, rounding và source completeness. Không gắn nhãn QID đúng/sai từ aggregate leaderboard vì leaderboard chỉ cho biết tổng `+18`, không tiết lộ 18 QID nào.

Output:

```text
artifacts/runs/evaluation/wave3-29-diagnostic-review-<run-id>/
```

Artifact này là diagnostic, không phải promotion gold trừ khi independence/adjudication được ghi và registry chấp nhận.

### Gate P1

- 220/220 abstention có đúng một terminal stage/reason.
- 792/792 protected answers định danh được.
- 1,012/1,012 retrieval records định danh được.
- Không có QID vừa nằm protected answer vừa nằm W4 mutation pool.
- Inventory manifest khóa baseline/questions/A6/retrieval SHA.

---

## 8. Phase 2 — Semantic parsing

### Mục tiêu

Biến câu hỏi thành một `QuestionAST` có vai trò rõ ràng trước khi tìm cell. Parser không được phát Pandas và không được quyết định fact UID.

### Priority error families

1. `BINARY_OPERANDS_UNRESOLVED`
2. `EXPLICIT_RATIO_OPERAND_UNRESOLVED/AMBIGUOUS`
3. `AGGREGATE_AXIS_UNRESOLVED`
4. `FILTER_PREDICATE_*`
5. `FILTER_SELECTED_EXPRESSION_*`
6. `TEMPORAL_FILTER_*`
7. `SELECT_AT_ARG_RANK_*`
8. `SELECT_AT_ARG_SELECTED_*`
9. `LOOKUP_SCOPE_NON_SCALAR`

### Implementation units

| Unit | File chính | Nội dung |
|---|---|---|
| Annotation | `infrastructure/semantic/legacy_annotator.py` | entities, periods, basis, operation, return mode, direction |
| Parse candidates | `application/parsing/parser.py` | explicit operand/role hypotheses, deterministic candidate IDs |
| AST types | `domain/semantic/ast.py`, `types.py` | chỉ mở rộng khi current AST không biểu diễn được semantics |
| Structural validation | `domain/semantic/validate.py` | reject missing/duplicate axes, empty filter domain, non-scalar output |
| Vocabulary | `configs/evaluation/semantic_operation_vocabulary_v1.yaml` | reviewed roles/nodes; version nếu contract thay đổi |

### Parsing rules

- Tách rõ numerator/denominator, minuend/subtrahend, rank key/projected value và filter operand/threshold.
- `reverse_difference` và `absolute_difference` phải nằm trong semantic trace, không suy từ thứ tự fact.
- Entity và period chỉ tạo axes; không tạo operation engine riêng.
- `SELECT_AT_ARG` phải có hai expression roles khác nhau hoặc cùng metric được chứng minh rõ.
- Filter phải có finite domain và predicate unit-compatible.
- Một câu có nhiều parse candidates được giữ N-best; không silently collapse ambiguity.
- Mọi terminal failure phải có reason code ổn định.

### Tests

Thêm positive, negative và metamorphic fixtures cho từng rule:

- đảo thứ tự entity nhưng giữ nghĩa;
- đổi alias nhưng AST không đổi;
- đổi “chênh lệch A so với B” để kiểm tra direction;
- company-parent vs consolidated;
- point-in-time vs flow period;
- rank metric khác output metric;
- filter threshold percent vs ratio;
- câu mơ hồ phải abstain.

### Gate P2

| Gate | PASS condition |
|---|---|
| Structural validity | 100% AST emitted không có validation issue |
| Parser crashes | 0/1,012 |
| Protected differential | mọi AST drift trên protected fixtures được liệt kê và adjudicate |
| New pattern tests | positive PASS, negative fail-closed, metamorphic PASS |
| Independent AST exact | `>=0.95` chỉ khi có sealed eligible gold; nếu không: `NOT_MEASURED` |

Coverage tăng không đủ để PASS nếu AST correctness chưa được adjudicate.

### Commit

```text
feat(parser): resolve reviewed operand and filter roles
```

---

## 9. Phase 3 — Metric/source resolution

### Mục tiêu

Mỗi semantic metric mention tạo một canonical metric hoặc một source-bound metric có provenance; resolver phải abstain khi có semantic collision.

### Không tạo ontology mới

Sử dụng và version hóa đúng các nguồn hiện tại:

```text
configs/semantic/ontology_v3.yaml
configs/semantic/extensions_v3.yaml
configs/semantic/metric_resolution_v1.yaml
configs/answer_v2/metrics_v1.yaml
configs/execution/metric_registry_v1.yaml
```

Nếu thay resolver policy/schema, tạo `metric_resolution_v2.yaml`; không overwrite identity v1 trong artifact cũ.

### Resolution ladder

```text
1. exact canonical alias
2. normalized reviewed alias
3. canonical formula alias
4. A6 source-label/path/code match trong scoped entity/period/basis
5. ambiguity detection
6. fail closed
```

### Selector constraints phải được materialize vào OperandRequest

- expected dimension/unit;
- statement types;
- requested và preferred basis;
- period semantics;
- qualifiers/context phrases;
- forbidden child labels/prefixes;
- source metric ID/build ID/labels/row paths;
- legal aggregation/derived-operation policy.

### Derived-operation policy

- Reported/source metric mặc định chỉ được `lookup`.
- Ratio, growth, sum, average hoặc rank chỉ được dùng khi metric/formula family đã reviewed.
- Không hạ `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` hàng loạt.
- Mỗi promotion rule cần evidence QID và negative example.

### Priority Pack R1

Từ 62 Risk-A QID còn lại, audit trước 31 phép toán đơn giản:

| Family | QID pool |
|---|---:|
| Direct lookup | 7 |
| Direct ratio | 9 |
| Two-period/entity difference | 12 |
| Sum | 3 |

Các blocker đã biết phải giữ fail-closed cho đến khi có bằng chứng mới:

- Q151/Q267: source semantic collision;
- Q590: period interpretation;
- Q661: denominator chưa execution-ready;
- Q979: multi-entity scope không đầy đủ.

### Tests

- alias collision;
- parent/child row discrimination;
- required/forbidden label context;
- statement-type preference;
- basis mismatch;
- point/flow period mismatch;
- sign convention;
- unit compatibility;
- unique winner vs tie;
- A6 source binding fingerprint.

### Gate P3

| Gate | PASS condition |
|---|---|
| Ontology validation | 0 alias/formula collision error |
| Resolver identity | config + ontology + A6 fingerprints trong manifest |
| Ambiguity | khác value/scope mà tied → abstain |
| Source provenance | 100% selected source metrics có build ID + labels + row paths |
| Protected metrics | không đổi binding của protected cases nếu chưa adjudicate |
| Candidate recall | đo riêng trên eligible gold; thiếu gold → `NOT_MEASURED` |

Expected output của phase là nhiều operand requests đúng hơn, không phải tự động promote answer.

### Commit

```text
feat(semantic): tighten metric and source selector contracts
```

---

## 10. Phase 4 — Filter/entity/period/basis/rank axes

### Mục tiêu

Loại lỗi “có đúng metric nhưng tính trên sai tập”. Đây là layer quyết định cohort members, period roles, basis và alignment trước composition.

### Axis contract

| Axis | Phải khóa |
|---|---|
| Entity | declared members, filtered members, rank domain, selected entity |
| Period | requested years, current/prior/start/end, point/flow, restated/current column |
| Basis | separate/consolidated/explicit unspecified preference |
| Filter | domain, predicate expression, comparator, threshold, quantifier |
| Rank | rank expression, direction, tie policy, projected expression |

### Implementation units

- `QuestionAST`: axes là typed nodes, không string hints.
- `compile_execution_plan()`: expand mỗi `MetricRef` theo entity×period scope.
- `OperandRequest`: giữ exact scope của từng operand.
- `JointBinder`: enforce same-basis/currency/dimension/document/period khi contract yêu cầu.
- `GroundedAstCompiler`: chỉ scalarize khi cardinality thật sự bằng 1.

### Priority Pack A1 — averages

31 Risk-A average QID là pool lớn tiếp theo, nhưng chỉ xử lý sau Pack R1. Chia thành:

1. average theo entity cùng một period;
2. average theo period của một entity;
3. average ratio per member rồi mới average;
4. filtered average;
5. average của change/growth.

Không biến `average(sum(values))` thành `sum(average(values))`. Không lấy ratio của tổng khi câu hỏi yêu cầu trung bình các ratio.

### Priority Pack A2 — extrema/select-at-arg

15 simple extremum QID xử lý sau averages:

- rank domain phải đủ members;
- rank và projected series phải có cùng axis keys;
- tie khác projected value → abstain;
- result kind period/member/value phải đúng câu hỏi.

### Gate P4

- Không có silent member drop.
- Filter/rank/projected series key sets align đúng contract.
- Every output scalar có trace từ domain → surviving members → selected member/value.
- Point-in-time và flow period semantics không bị trộn.
- Basis của mọi operands trong một coherent group thống nhất hoặc formula cho phép khác.
- 100% reviewed axis fixtures exact; chưa có eligible gold thì global axis accuracy=`NOT_MEASURED`.

### Commit

```text
feat(planning): enforce entity period and filter axes
```

---

## 11. Phase 5 — Compositional planning, binding và execution

### Mục tiêu

Thay vì thêm template QID/family mới vào `grounded_composer.py`, biên chuẩn là:

```text
QuestionAST
→ ExecutionPlan
→ candidate operands
→ BoundExecutionPlan
→ typed result
→ Pandas program
```

`GroundedAstCompiler` là adapter để port typed AST vào grounded candidate DAG. Template composer chỉ còn fallback đã tồn tại; không mở thêm nhánh bằng QID.

### Closed grammar rollout order

1. Direct lookup.
2. Binary arithmetic: add/subtract/divide/growth.
3. Aggregate over entity hoặc period axis.
4. Filter → aggregate.
5. Rank/min/max.
6. SelectAtArg(rank expression, projected expression).
7. Nested compositions: median-filter, multi-predicate, rolling formula.

Không làm bước 7 trước khi 1–6 có differential sạch.

### Bind → validate → rebind

Sử dụng API hiện có:

```text
parse_candidates()
  → compile_execution_plan() cho từng candidate
  → retrieve operands
  → JointBinder.bind_candidates(limit=3)
  → typed execute
  → Pandas compile
  → clean replay
```

Decision policy:

- loại candidate vi phạm scope/unit/basis/period/source;
- loại candidate typed↔Pandas mismatch;
- nếu mọi candidate còn lại semantic-equivalent và cùng answer/evidence meaning: accept;
- nếu candidate còn lại tạo answer khác nhau: abstain `SEMANTIC_CANDIDATE_DISAGREEMENT`;
- tối đa 3 binding candidates; không loop không giới hạn;
- score margin chỉ là gate phụ, không thay semantic equivalence.

### Execution invariants

- giữ `Decimal` đến submission boundary;
- divide-by-zero fail closed;
- output dimension/unit phải khớp `OutputSpec`;
- every operand xuất hiện trong evidence;
- `answer == restricted_pandas_replay`;
- evidence chỉ lấy từ bound observation UIDs;
- query không truy cập ngoài evidence frames.

### Gate P5

| Gate | PASS condition |
|---|---|
| Typed execution | 0 crash trên 1,012 QID |
| Pandas compile | mọi accepted typed result compile được |
| Differential replay | accepted typed == Pandas, mismatch 0 |
| Evidence completeness | 100% bound operands được materialize |
| Ambiguous candidates | disagreement → abstain |
| Protected outputs | 792/792 baseline outputs chưa bị thay |

### Commits

```text
feat(binding): validate top semantic assignments
feat(execution): preserve axes through compositional replay
```

---

## 12. Phase 6 — Full shadow/differential trên 1,012 QID

### Run matrix

| Run | Mục đích |
|---|---|
| S0 | exact code/config trước thay đổi |
| S1 | parser changes only |
| S2 | parser + resolver |
| S3 | parser + resolver + axes |
| S4 | full composition candidate |

Mỗi run dùng unique immutable run ID và cùng questions/A6/retrieval identity.

### Funnel report bắt buộc

```text
1,012 questions
  → parse OK / abstain by reason
  → plan OK / abstain by reason
  → operand candidates reachable
  → coherent binding
  → typed execute
  → Pandas compile
  → replay match
  → source-adjudication queue
```

### Verified command templates

```bash
PYTHONPATH=src python -m text2pandas.interface.cli.main shadow-v3 \
  --run-id <immutable-run-id> \
  --operand-k 20

PYTHONPATH=src python -m text2pandas.interface.cli.main grounded-v5 \
  --run-id <immutable-grounded-run-id> \
  --questions data/raw/btc/questions/questions.jsonl \
  --baseline-zip artifacts/official/submission-3831/submission.zip \
  --promotion-mode shadow \
  --release-profile competition \
  --deterministic-only
```

Không dùng `--canonical-table-priors` hoặc model fallback trong experiment chính nếu chưa preregister thành một biến A/B riêng.

### Differential outputs

- stage-transition matrix S0→S1→S2→S3→S4;
- QID-level AST/metric/axis/binding/value diff;
- protected regression list;
- new replay-clean abstention recoveries;
- ambiguity/tie list;
- source review queue;
- correctness=`NOT_MEASURED` trước adjudication.

### Gate P6

- full scope 1,012/1,012;
- zero crash;
- zero typed/Pandas mismatch;
- all protected-answer differences = 0;
- retrieval differences = 0;
- every newly executable QID has complete stage trace;
- no promotion claim from terminal-count reduction.

---

## 13. Phase 7 — Source adjudication và Wave 4 ledger

### Candidate selection order

1. Pack R1: 31 simple Risk-A cases.
2. Pack A1: reviewed simple averages.
3. Pack A2: reviewed simple extrema.
4. Complex compositions chỉ khi closed grammar path đã PASS.

### Per-QID acceptance checklist

Mỗi QID phải PASS tất cả:

```text
[ ] question text exact
[ ] operation/return mode exact
[ ] metric IDs and source labels exact
[ ] entity domain exact
[ ] period and point/flow semantics exact
[ ] basis exact
[ ] formula/operand roles exact
[ ] sign and subtraction direction exact
[ ] unit/scale/rounding exact
[ ] every fact execution_ready=1
[ ] source table/document locator valid
[ ] evidence includes every operand
[ ] typed result == Pandas replay
[ ] baseline QID was abstain
```

### Ledger

```text
configs/evaluation/recovery_wave4_review_3831_v1.json
```

Mỗi record chứa baseline SHA, questions SHA, A6 SHA, ontology/resolver fingerprints, parse candidate ID, AST fingerprint, plan fingerprint, fact UIDs, source labels, pandas query, expected answer, rationale, reviewer decision và gate booleans.

### Quantity target

Mục tiêu vận hành là `20–24` PASS_SOURCE_PROVEN fills vì cần khoảng 13 official wins để đạt xấp xỉ `0.4002`:

```text
392 + 13 = 405
405 / 1,012 ≈ 0.4002
```

Với conversion rate Wave 3 khoảng 62%, khoảng 21 candidate tương đương chất lượng là estimate hợp lý. Đây không phải release gate và không được dùng để ép nhận QID yếu.

### Gate P7

- every accepted QID PASS toàn checklist;
- reviewer không sửa source/gold để khớp prediction;
- unresolved/ambiguous giữ abstain;
- review ledger schema-valid và checksum-locked;
- no candidate replacement trên 792 protected answers.

---

## 14. Phase 8 — Build Wave 4 candidate

### Candidate contract

```text
Answer layer:
  baseline 3831 giữ nguyên
  + Wave 4 fills tại baseline abstentions

Retrieval layer:
  giữ nguyên 3831 cho đủ 1.012 QID
```

### Builder

Dùng generic recovery builder hiện có sau khi ledger được seal:

```bash
PYTHONPATH=src:. python tools/build_recovery_wave2_candidate.py \
  --candidate-kind text2pandas.recovery_wave4_candidate \
  --evidence-prefix wave4 \
  --run-root artifacts/runs/recovery-wave4 \
  --run-id recovery-wave4-3831-<run-id>-r1 \
  --baseline artifacts/official/submission-3831/submission.zip \
  --review-ledger configs/evaluation/recovery_wave4_review_3831_v1.json
```

Chạy lần hai bằng run ID `-r2`. Không overwrite R1.

### Required implementation adjustment

Thêm `recovery-wave4` vào `RUN_ROOTS` của `tools/package_submission_handoff.py` và thêm unit test resolver tương ứng trước khi package.

### Candidate differential gates

| Gate | PASS condition |
|---|---|
| Records | 1,012/1,012 |
| Protected answer/query/evidence | 792/792 unchanged |
| Retrieval | 1,012/1,012 unchanged |
| Baseline CSV payloads | 100% byte-preserved |
| Changed QIDs | đúng tập PASS trong Wave 4 ledger |
| Validation | competition profile: 0 error |
| Replay | all emitted matched, 0 execution error |
| ZIP | R1 và R2 byte-identical |
| Source identity | clean committed Git source |

Warning do remaining abstentions phải được đếm và giải thích; không báo “strict 0 warning” nếu competition validator đang biểu diễn abstention bằng warning.

---

## 15. Phase 9 — Test matrix và release gate

### Per-phase development gates

```bash
PYTHONPATH=src pytest -q tests/unit/test_semantic_parser_v3.py
PYTHONPATH=src pytest -q tests/unit/test_a6_metric_resolver_v3.py
PYTHONPATH=src pytest -q tests/unit/test_planning_and_joint_binding_v3.py
PYTHONPATH=src pytest -q tests/unit/test_grounded_ast_compiler_v6.py
PYTHONPATH=src pytest -q tests/unit/test_typed_executor_and_pandas_v3.py
PYTHONPATH=src pytest -q tests/integration/test_semantic_v3_filtered_extrema.py
PYTHONPATH=src pytest -q tests/integration/test_semantic_v3_select_at_arg.py
```

### Cross-cutting gates trước candidate

```bash
make typecheck
make test-offline
make snapshots-verify
make test-integration
make ci
make dp-test REPORT_DIR=artifacts/reports/recovery-wave4-3831-e2e-<run-id>
git diff --check
```

### Handoff

Sau khi `package_submission_handoff.py` hỗ trợ Wave 4:

```bash
PYTHONPATH=src:. python tools/package_submission_handoff.py \
  --candidate-run-id recovery-wave4-3831-<run-id>-r1 \
  --output artifacts/handoffs/recovery-wave4-3831-final-<run-id> \
  --release-profile competition
```

Final inspection:

```bash
shasum -a 256 artifacts/handoffs/recovery-wave4-3831-final-<run-id>/submission.zip
unzip -t artifacts/handoffs/recovery-wave4-3831-final-<run-id>/submission.zip
cmp artifacts/runs/recovery-wave4/recovery-wave4-3831-<run-id>-r1.zip \
    artifacts/runs/recovery-wave4/recovery-wave4-3831-<run-id>-r2.zip
```

---

## 16. Phase 10 — Official submission decision

### Trước upload

Giữ ba artifact bất biến:

1. `SAFE`: exact submission 3831.
2. `SHADOW`: full semantic run + differential, không upload.
3. `WAVE4`: SAFE + source-adjudicated fills, retrieval unchanged.

### Sau upload

Khóa ngay:

- submission ID;
- submitted timestamp;
- exact uploaded ZIP SHA;
- leaderboard receipt/screenshot nếu có;
- toàn bộ 10 metrics;
- mapping về Git commit, config and ledger SHA.

### Promotion rule

| Official result | Decision |
|---|---|
| Answer Accuracy > 0.3874, retrieval unchanged | Promote candidate thành SAFE mới |
| Answer Accuracy = 0.3874 | Không có measured gain; giữ 3831 làm SAFE |
| Answer Accuracy < 0.3874 hoặc retrieval giảm | Rollback 3831 và audit artifact mapping |

Không dùng local replay để override kết luận leaderboard.

---

## 17. Phase dependencies và checkpoints

```text
P0 Freeze 3831
  ↓
P1 Inventory + protected sets
  ↓
P2 Parser
  ↓
P3 Metric/source resolver ───────────────┐
  ↓                                     │
P4 Axes                                 │
  ↓                                     │
P5 Composition/binding/execution        │
  ↓                                     │
P6 Full shadow differential             │
  ↓                                     │
P7 Source adjudication ◄────────────────┘
  ↓
P8 Two-run candidate build
  ↓
P9 Test/release handoff
  ↓
P10 One official measurement
```

Không skip P0/P1. Không source-adjudicate bằng prediction-only packet. Không build final candidate trước khi full differential bảo vệ 792 baseline outputs.

---

## 18. Suggested execution schedule

| Window | Work | Release opportunity |
|---|---|---|
| Day 0–1 | P0–P1 baseline/inventory/protected sets | none |
| Day 1–2 | P2 parser direct/binary roles | shadow only |
| Day 2–3 | P3 resolver Pack R1 | có thể tạo small direct-safe checkpoint |
| Day 3–5 | P4 averages/extrema axes | shadow only cho đến review |
| Day 5–7 | P5 composition + replay | source-review queue |
| Day 7–8 | P6–P7 full differential + adjudication | chốt Wave 4 ledger |
| Day 8–9 | P8–P9 deterministic build + handoff | upload-ready |

Nếu deadline ngắn, dừng sau P3 và chỉ release Pack R1 đã source-proven. Không kéo P4/P5 chưa đủ kiểm chứng vào cùng lượt nộp.

---

## 19. Blockers và stop conditions

| Blocker | Response |
|---|---|
| 3831 ZIP/score không map được về exact SHA | dừng P0 |
| Active snapshot drift | dừng run, re-seal identities |
| Parser coverage tăng nhưng reviewed correctness giảm | rollback đúng parser rule |
| Resolver tạo non-equivalent tie | abstain; không chọn tùy ý |
| Axis drops entity/period member | reject candidate |
| Typed/Pandas mismatch | reject candidate và fix executor/compiler |
| Missing or non-execution-ready fact | reject QID |
| Protected 792 output thay đổi | fail release |
| Retrieval record thay đổi | fail release |
| Independent gold thiếu | report `NOT_MEASURED`; global promotion blocked |
| Candidate target chưa đủ 20 QID | vẫn release được nếu từng QID đủ gate; không ép coverage |

---

## 20. Deliverables

### Tracked code/config/provenance

```text
provenance/submissions/submission_3831.json
configs/evaluation/submission_ledger_v1.json
configs/evaluation/recovery_wave4_review_3831_v1.json
configs/semantic/<versioned resolver or ontology changes>
src/text2pandas/application/parsing/parser.py
src/text2pandas/application/planning/planner.py
src/text2pandas/application/binding/binder.py
src/text2pandas/application/execution/{executor,compiler}.py
src/text2pandas/application/usecases/grounded_ast_compiler.py
tests/unit/<layer tests>
tests/integration/<composition tests>
docs/reports/RECOVERY_WAVE4_3831_E2E_REPORT_<date>.md
```

Chỉ các file thật sự cần sửa mới được commit; danh sách trên là routing map, không phải yêu cầu chạm mọi file.

### Generated immutable artifacts

```text
artifacts/official/submission-3831/submission.zip
artifacts/runs/evaluation/recovery-wave4-3831-inventory-<run-id>/
artifacts/runs/semantic-v3/<shadow-run-id>/
artifacts/runs/grounded-v5/<grounded-run-id>/
artifacts/runs/recovery-wave4/<candidate-run-id>-r1.zip
artifacts/runs/recovery-wave4/<candidate-run-id>-r2.zip
artifacts/reports/recovery-wave4-3831-e2e-<run-id>/
artifacts/handoffs/recovery-wave4-3831-final-<run-id>/submission.zip
```

---

## 21. Definition of done

Task implementation chỉ hoàn tất khi:

1. submission 3831 được freeze và replay lại thành công;
2. 220 abstention có full stage funnel;
3. parser/resolver/axes/composition changes có targeted tests và terminal reasons rõ;
4. full 1,012-QID shadow run không crash;
5. typed/Pandas replay mismatch bằng 0;
6. 792/792 protected answer/query/evidence giữ nguyên;
7. retrieval 1,012/1,012 giữ nguyên;
8. Wave 4 ledger chỉ chứa source-adjudicated baseline abstentions;
9. competition validation có 0 error;
10. all emitted answers replay sạch;
11. R1/R2 ZIP byte-identical;
12. handoff có SHA256SUMS, manifest và exact upload path;
13. report tách rõ coverage/replay/local review khỏi official accuracy;
14. global V3 vẫn BLOCKED nếu promotion gold chưa đủ;
15. Git worktree chỉ chứa intentional changes và mỗi phase có commit riêng khi PASS.

Kết quả mong muốn của plan là một Wave 4 nhỏ nhưng đo được, có khả năng đưa Answer Accuracy từ `0.3874` lên vùng `0.395–0.402` mà không làm mất baseline. Đây là mục tiêu thí nghiệm, không phải score guarantee.
