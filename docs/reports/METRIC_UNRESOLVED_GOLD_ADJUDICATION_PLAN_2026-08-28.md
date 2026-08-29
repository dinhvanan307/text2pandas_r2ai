# METRIC_UNRESOLVED — Phase 1.5 Gold Adjudication Plan

Date: 2026-08-28  
Status: **READY FOR EXECUTION — REVIEW NOT STARTED**  
Scope: đóng measurement của Phase 1 `METRIC_UNRESOLVED`; không sửa runtime, `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION`, `BINDING_TIE`, retrieval, binder hay promotion policy.

## 1. Executive decision

Hướng đi đúng tại thời điểm này là **dừng code thay đổi semantic runtime và adjudicate 93-case reviewer queue trước**. Candidate đã chứng minh coverage/reachability: terminal `METRIC_UNRESOLVED` giảm 198 → 0, 75 câu thành `NEW_OK`, 287 câu `OK` cũ không drift. Candidate chưa chứng minh 75 answer mới đúng về semantic, source binding và giá trị.

Flow được khóa như sau:

```text
PHASE 1 — IMPLEMENTATION COMPLETE, CONDITIONALLY PASS
METRIC_UNRESOLVED: 198 → 0; NEW_OK: 75
                 ↓
PHASE 1.5 — CURRENT
freeze 93-case cohort
→ prediction-blind dual annotation
→ distinct adjudication
→ immutable gold seal
→ unblind and score
                 ↓
PASS Phase 1.5?
  ├─ NO  → reopen only METRIC_UNRESOLVED defects; Phase 2 blocked
  └─ YES → freeze Phase 1 release and re-baseline full corpus
                 ↓
PHASE 2 — NEW PLAN, NOT PART OF THIS PLAN
REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION
                 ↓
re-measure full corpus
                 ↓
next bottleneck selected from new evidence
```

`BINDING_TIE` không được sửa trong Phase 1.5. Nó là candidate downstream hiện có 19 ca trong frozen H198 và 121 ca trên full candidate corpus. Thứ tự Phase 3 chỉ là dự kiến; phải re-measure sau Phase 2 thay vì pre-commit theo số cũ.

## 2. Những con số cần diễn giải chính xác

| Fact | Count | Meaning |
| --- | ---: | --- |
| Frozen baseline H198 | 198 | Các câu B0 terminal `METRIC_UNRESOLVED` |
| Candidate `NEW_OK` trong H198 | 75 | Emitted answers cần correctness review |
| Review queue | 93 | Union của 75 new OK, toàn bộ T3 và các boundary QIDs |
| Review queue `ABSTAIN` | 18 | Safety/taxonomy/role cases, không nằm trong precision denominator của 75 new OK |
| H198 → reported-derived | 22 | Transition trực tiếp từ frozen H198 |
| Full-corpus reported-derived | 162 | Terminal count trên toàn bộ 1.012 candidate records |
| H198 → binding tie | 19 | Transition trực tiếp từ H198 |
| Full-corpus binding tie | 121 | Terminal count trên toàn candidate corpus |

Không được nói “162 ca đều xuất hiện vì mở khóa H198”. Chỉ 22 ca có provenance transition trực tiếp từ H198; 162 là current full-corpus population của bottleneck kế tiếp.

## 3. Scope và non-goals

### 3.1 In scope

1. Freeze identity của 93 QIDs và candidate output đang được đánh giá.
2. Tạo dossier không làm lộ model output.
3. Hai annotator độc lập gán answer, semantic structure và evidence binding.
4. Một adjudicator khác hai annotator phân xử mọi disagreement.
5. Seal gold release immutable với checksum và reviewer provenance.
6. Sau seal mới unblind candidate và đo precision/correctness/safety.
7. Quyết định `PASS`, `CONDITIONALLY PASS`, `FAIL` hoặc `BLOCKED` cho Phase 1.
8. Nếu pass, phát hành input brief cho một plan Phase 2 riêng.

### 3.2 Out of scope

- Không sửa resolver/parser/planner/retriever/binder/executor.
- Không sửa threshold, top-K, ranking hay `BINDING_TIE`.
- Không nới reported-derived policy.
- Không thêm alias/rule theo kết quả review trong cùng review release.
- Không sửa raw/A6/snapshot/index.
- Không thay V2 canonical behavior.
- Không dùng model answer, model AST, trace hoặc selected evidence để tạo gold.
- Không gọi queue 93 là held-out production gold: cohort được chọn sau khi xem model outcome.
- Không dùng 93 records để tuyên bố V3 production-ready. Production policy vẫn yêu cầu cùng một sealed release có ít nhất 300 answer, 300 semantic và 300 evidence records.

## 4. Source of truth và frozen identity

### 4.1 Governing policies

| Asset | Role | SHA-256 |
| --- | --- | --- |
| `configs/evaluation/independent_gold_protocol_v1.yaml` | Hai annotator, distinct adjudicator, blind output, source review | `8009b44e026f79e259c80d5d47761217f14419096abb66231aebb33ea1988bd5` |
| `configs/semantic/promotion_policy_v3.yaml` | Production thresholds và minimum 300-record release | `6133bff7461eeb883e6cf559b089463e6f931cecbbb6650c1217b0b2ccbaa425` |
| `data/curated/gold/ANNOTATION_GUIDELINE.md` | Entity/basis/period/metric/operation/return/evidence rules | Freeze checksum khi packet được tạo |

### 4.2 Frozen evaluation inputs

| Asset | Records | SHA-256 |
| --- | ---: | --- |
| Question corpus | 1.012 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| B0 records | 1.012 | `44ac6bc9b858c69ab11fa92f3bad546247af06e256a7706700a053d88368ffa3` |
| Candidate records | 1.012 | `b95a86861e99779f65ad276b5314d8ef74ccb902df71f454e05b57d08c8bf51b` |
| New-OK QIDs | 75 | `25f5e3765f43994f3182c15cf9cab38defdd9bd32feceabbdce1f701be455eab` |
| Review queue | 93 | `a5c1437f75e1221d0dc60381fe8dc892917145304ff8589670bc5d0e15a47ea7` |

Candidate runtime identity phải được giữ cùng resolver fingerprint `a4848b2e9b67b7e4e501663a8913211d01f3c779ed0b6e9abd79a5a94cb154cb`, A6 build `c6887fb633374fad` và retrieval index `872ccb0dda9a2bb6`.

### 4.3 Queue composition

| Axis | Cohort | Count |
| --- | --- | ---: |
| Candidate status | `OK` | 75 |
| Candidate status | `ABSTAIN` | 18 |
| Tier | T1 | 57 |
| Tier | T2 | 16 |
| Tier | T3 | 18 |
| Tier | `NO_PHRASE` | 1 |
| Tier | `BOUNDARY` | 1 |
| New OK by tier | T1 / T2 / T3 | 55 / 15 / 5 |

Selection rule đã materialize là:

```text
all 75 new OK
UNION all 18 T3
UNION Q100, Q426, Q502, Q508, Q870
= 93 unique QIDs
```

Đây là **exhaustive post-hoc audit của affected/risk cohort**, không phải random sample. Vì review toàn bộ 75 new OK, observed precision mô tả chính xác finite cohort này; confidence interval chỉ mang tính tham khảo khi suy rộng sang câu hỏi tương lai.

## 5. Hai decision level không được gộp

### 5.1 Phase 1 resolver closure

Question: implementation `METRIC_UNRESOLVED` vừa thêm có đủ chính xác và an toàn để được giữ lại, đóng Phase 1 và mở một plan Phase 2 hay không?

Denominator: fixed 93-case queue, với metric riêng cho 75 new OK và 18 safety/boundary cases.

### 5.2 Production promotion

Question: Semantic V3 có thay canonical V2 hay không?

Decision này **không thể** được trả lời chỉ bằng 93 post-hoc cases. `semantic-v3-production` còn yêu cầu minimum 300 records cho từng answer/semantic/evidence asset, cùng parser, retrieval, binding, answer, reranker và replay gates trong một sealed release.

Kết quả Phase 1.5 phải ghi:

```text
measurement_scope = POST_HOC_EXHAUSTIVE_METRIC_UNRESOLVED_COHORT
promotion_scope = PHASE_1_CLOSURE_ONLY
production_promotion_eligible = false
```

Ngay cả khi Phase 1.5 `PASS`, trạng thái production vẫn là `BLOCKED` cho đến khi policy 300-record được đáp ứng.

## 6. Governance và reviewer independence

### 6.1 Roles

| Role | Responsibility | Restriction |
| --- | --- | --- |
| Gold coordinator | Freeze cohort, distribute blind packets, verify completeness | Không annotate/adjudicate |
| Annotator A | Independent pass A trên cả 93 | Không xem pass B/model output |
| Annotator B | Independent pass B trên cả 93 | Không xem pass A/model output |
| Adjudicator C | Resolve every disagreement, re-check source | Khác A/B và không xem model output trước seal |
| Evaluation engineer | Unblind, score, generate report sau seal | Không sửa gold labels |
| Release owner | Approve final Phase 1 decision | Không override failed machine gate bằng nhận xét miệng |

Mỗi reviewer phải có stable reviewer ID. `annotator_id`, `adjudicator_id`, role, independence attestation và assignment timestamp được khóa trong manifest trước khi label đầu tiên được nhập. Không ghi tên tự do theo từng row.

### 6.2 Minimum quorum

- Hai annotator hoàn thành độc lập 93/93.
- Một adjudicator distinct hoàn thành 100% disagreement records.
- Tất cả ba xác nhận độc lập với việc phát triển resolver.
- Nếu chỉ có một reviewer hoặc reviewer đã trực tiếp viết resolver, run chỉ được gắn `DIAGNOSTIC_SINGLE_REVIEWER`, không được dùng để đóng Phase 1.

### 6.3 Leakage boundary

Reviewer không được xem:

- candidate answer/status/reason;
- baseline reason/tier/selection reason;
- model AST/plan/query/trace;
- resolver source bindings, scores hoặc selected row paths;
- `review_queue.jsonl`, `records.jsonl`, `new_ok_qids.jsonl` trực tiếp;
- báo cáo có danh sách 75 new-OK QIDs trong thời gian review.

Reviewer được xem:

- nguyên văn câu hỏi;
- guideline đã freeze;
- raw/A6 corpus đã freeze;
- toàn bộ execution-ready rows trong scope entity/period/basis, nếu scope bundle được tạo độc lập với model output;
- raw report/page/line provenance để xác minh;
- công cụ search không hiển thị resolver ranking hoặc parent prediction.

Nếu filesystem chung không thể enforce boundary, coordinator phải phát packet sang thư mục/quyền truy cập riêng. Nếu không thể chứng minh separation, manifest phải ghi `BLINDING_NOT_VERIFIABLE` và decision là `BLOCKED`.

## 7. Artifact layout

Không overwrite candidate evaluation hiện tại. Tạo run directory mới:

```text
artifacts/evaluation/metric-unresolved-phase1_5-v1/
├── control/
│   ├── cohort_control.jsonl
│   ├── candidate_commitment.json
│   ├── input_checksums.json
│   └── reviewer_assignments.json
├── blind-common/
│   ├── questions.jsonl
│   ├── question_manifest.json
│   ├── guideline.md
│   └── scope-evidence/
├── pass-a/
│   ├── annotations.jsonl
│   └── manifest.json
├── pass-b/
│   ├── annotations.jsonl
│   └── manifest.json
├── adjudication/
│   ├── disagreements.jsonl
│   ├── decisions.jsonl
│   └── manifest.json
├── sealed/
│   ├── gold.jsonl
│   ├── manifest.json
│   └── checksums.json
└── evaluation/
    ├── comparison.json
    ├── metrics.json
    ├── error_taxonomy.jsonl
    ├── slice_metrics.json
    ├── phase_decision.json
    └── checksums.json
```

`control/` và `evaluation/` không được phân phối cho annotators. `blind-common/` không chứa field hoặc filename tiết lộ candidate outcome.

## 8. Tooling plan

Current generic independent-gold preparer chọn 300 câu bằng hash order; nó không nhận fixed 93-case cohort. Không dùng sai tool rồi thay denominator. Tạo ba wrapper nhỏ, chỉ phục vụ evaluation governance và tái sử dụng contracts hiện có:

1. `tools/evaluation/prepare_metric_unresolved_gold.py`
   - đọc frozen 93 QIDs ở coordinator side;
   - đối chiếu question bytes với corpus checksum;
   - strip recursive mọi model field;
   - tạo hai annotation templates và adjudication template;
   - tạo model-independent scope evidence bundle;
   - fail nếu count khác 93, QID trùng/thiếu hoặc forbidden field xuất hiện.
2. `tools/evaluation/seal_metric_unresolved_gold.py`
   - gọi `validate_and_merge_release()` hoặc shared validator tương đương;
   - enforce distinct identities, evidence review, completeness và explicit disagreement review;
   - tạo immutable `gold.jsonl`, manifest, SHA-256.
3. `tools/evaluation/evaluate_metric_unresolved_gold.py`
   - chỉ chạy sau seal;
   - hỗ trợ numeric, count, period, percent và member outputs;
   - so sánh semantic/source binding/answer theo rubric dưới đây;
   - báo cả fixed denominator và gold-evaluable denominator;
   - không mutate labels hoặc runtime.

Các tool mới phải có unit tests cho leakage, identity reuse, incomplete rows, unreviewed disagreement, denominator laundering, tolerance và immutable output. Không thay đổi resolver code trong work package này.

## 9. Blind dossier construction

### 9.1 Questions packet

Mỗi row chỉ có:

```json
{
  "schema_version": 1,
  "qid": 5,
  "question": "...",
  "question_sha256": "...",
  "packet_record_id": "opaque-id"
}
```

Không đưa `tier`, candidate status/reason/answer, selection reason hoặc source binding vào packet.

### 9.2 Model-independent source bundle

Để source review khả thi mà không dẫn reviewer theo model, bundle cho mỗi câu được tạo từ frozen entity/period/basis scope trước khi dùng metric resolver output. Bundle chứa tất cả rows phù hợp hard scope, sorted bằng stable source identity:

- A6 build ID;
- entity/ticker và basis;
- period/point/column label;
- row label, clean label, full row path/hierarchy;
- source metric code;
- unit/dimension/scale;
- statement type;
- execution-ready flag;
- observation UID, CSV/source reference và raw report locator.

Bundle tuyệt đối không chứa resolver score, overlap, selected candidate, binding score, rank hoặc “expected row”. Nếu scope quá lớn, reviewer search trực tiếp A6; không được cắt top-K theo resolver.

### 9.3 Packet validation

Preflight scan phải recursively reject các key:

```text
answer (nếu là model answer)
candidate_scores
candidate_status
candidate_reason
model_answer
model_ast
model_output
pandas_query
predicted_answer
retrieval_scores
source_bindings (nếu lấy từ model AST)
trace
```

Question text và corpus evidence là allowed. Gold answer fields chỉ xuất hiện trống trong annotation templates.

## 10. Annotation schema

Mỗi pass phải gán ba asset cho mọi QID.

### 10.1 Answer asset

```json
{
  "status": "RESOLVED | AMBIGUOUS | NOT_IN_SOURCE | INSUFFICIENT_EVIDENCE",
  "value": null,
  "result_kind": "MONEY | PERCENT_VALUE | PERCENT_POINT | RATIO_FRACTION | COUNT | PERIOD_YEAR | ENTITY_LABEL",
  "dimension": "money | percent | ratio | count | period | member",
  "scale_exponent": null,
  "currency": null,
  "display_unit": null,
  "normalization_notes": null
}
```

`value` chỉ được điền khi evidence đủ để reproduce. Không suy ra answer từ candidate output.

### 10.2 Semantic parser asset

```json
{
  "status": "RESOLVED | AMBIGUOUS | UNRESOLVED",
  "entity_set": [],
  "basis": null,
  "basis_explicit": false,
  "periods": [],
  "operation_family": null,
  "operation_tree": null,
  "operand_specs": [
    {
      "role": "value | rank | selected | filter | numerator | denominator | minuend | subtrahend | old | new",
      "metric_surface": null,
      "metric_concept": null,
      "period": null,
      "basis": null,
      "dimension": null
    }
  ],
  "return_spec": null,
  "ambiguity_alternatives": []
}
```

Source-backed metric không bị ép thành ontology ID global. Reviewer ghi meaning và source evidence đủ để xác định, hoặc `AMBIGUOUS` nếu không unique.

### 10.3 Evidence binding asset

```json
{
  "status": "RESOLVED | AMBIGUOUS | NOT_LOCATED | SOURCE_DEFECT",
  "source_evidence_reviewed": true,
  "ordered_operands": [
    {
      "role": "value",
      "acceptable_observation_uids": [],
      "source_metric_code": null,
      "row_label": null,
      "row_path": null,
      "statement_type": null,
      "period": null,
      "basis": null,
      "unit": null,
      "raw_value": null,
      "source_locator": null
    }
  ],
  "notes": null
}
```

Cho phép nhiều `acceptable_observation_uids` chỉ khi các cells thực sự equivalent về meaning, entity, period, basis, unit và value. Không dùng equivalence để hợp thức hóa ambiguous metric variants.

## 11. Annotation rubric theo từng lớp

Annotator xử lý mỗi case theo cùng một thứ tự, không nhảy thẳng tới số answer.

### 11.1 Question answerability

Chọn đúng một trạng thái:

- `UNIQUE_ANSWERABLE`: question và source xác định duy nhất semantic/evidence/answer;
- `GENUINELY_AMBIGUOUS`: có ít nhất hai interpretation/evidence hợp lệ và question không đủ specificity;
- `METRIC_NOT_IN_SOURCE`: requested metric không tồn tại trong frozen source;
- `SOURCE_EVIDENCE_INSUFFICIENT`: source có liên quan nhưng không đủ để trả lời;
- `SOURCE_DEFECT`: raw/A6 inconsistency chặn kết luận;
- `QUESTION_INVALID`: entity/period/unit/question contract tự mâu thuẫn.

### 11.2 Entity, basis và period

1. Resolve entity từ text, không dùng model intent.
2. Apply explicit basis; nếu không explicit, dùng guideline default nhưng ghi cờ.
3. Resolve period type `PERIOD`, `OPENING`, `CLOSING`, range/quarter.
4. Mọi mismatch entity/year/basis là critical semantic error; không được bỏ qua chỉ vì value trùng.

### 11.3 Operation và roles

1. Viết operation tree thật.
2. Ghi đầy đủ roles theo thứ tự.
3. Với `SELECT_AT_ARG`, tách `rank` và `selected`.
4. Với filter/count, giữ predicate metric/operator/threshold.
5. Với binary operations, giữ numerator/denominator hoặc old/new/minuend/subtrahend.
6. Nếu role không xác định duy nhất, đánh `AMBIGUOUS`; không chọn mention cuối cùng.

### 11.4 Metric/source meaning

1. Xác định metric surface trong question.
2. Tìm evidence độc lập trong full hard scope.
3. Kiểm label, hierarchy, code và statement type.
4. Parent/child match chỉ đúng nếu meaning ở requested granularity khớp.
5. Person/entity/category leaf không tự động là financial metric.
6. Nhiều variants gần nhau nhưng thiếu modifier → `GENUINELY_AMBIGUOUS`.
7. Source row tồn tại nhưng sai unit/period/basis → không phải acceptable binding.

### 11.5 Answer normalization

- Money: lưu raw value, source scale và normalized requested-unit value.
- Percent: phân biệt percent value với fraction và percentage point.
- Count/year: exact integer semantics.
- Member/entity label: lưu canonical display và normalized comparison form.
- Derived answer: lưu ordered operands và phép tính independent; không copy query của system.
- Numeric tolerance chỉ áp dụng lúc evaluator so sánh; annotator lưu exact source-derived value tốt nhất có thể.

## 12. Reviewer workflow

### 12.1 Calibration trước scored cohort

Reviewer A/B/C đọc guideline và xử lý một calibration set nằm **ngoài 93 QIDs**. Calibration chỉ dùng để thống nhất interpretation của schema, không dùng trong metrics. Nếu guideline phải sửa, sửa và freeze trước scored pass; không sửa guideline sau khi thấy candidate output.

### 12.2 Independent pass A và B

- A và B nhận cùng question/source packet nhưng template riêng.
- Không trao đổi case-level decision trong thời gian pass.
- Mỗi pass phải hoàn thành 93/93, không để placeholder.
- `AMBIGUOUS`/`UNRESOLVED` phải có notes và alternatives/blocked field.
- Mỗi resolved answer phải có source locator và reproducible arithmetic nếu derived.
- Coordinator chạy schema/checksum validation nhưng không sửa nội dung.

### 12.3 Agreement report trước adjudication

Coordinator tạo machine diff theo field:

- answer status/value/unit;
- entity/basis/period;
- operation family/tree;
- operand roles/metric meaning;
- evidence UID/path;
- answerability class.

Agreement report không chứa candidate output. Báo raw agreement và categorical agreement theo field. Nếu field-level agreement tổng <0,90 hoặc một critical field slice <0,80, dừng adjudication, làm rõ guideline và restart cả affected pass; không dùng adjudicator để che một guideline chưa ổn định.

### 12.4 Distinct adjudication

Adjudicator C xem question, source, pass A/B và disagreement fields, vẫn blind với candidate. Với mỗi disagreement:

1. independently locate source;
2. chọn A/B hoặc ghi decision thứ ba;
3. liệt kê `reviewed_disagreement_fields`;
4. giải thích evidence/rule;
5. không quyết định theo majority vì chỉ có hai passes;
6. ghi `GOLD_UNRESOLVED` nếu evidence không đủ.

Các field A/B đồng thuận vẫn được C spot-check theo deterministic 20% sample cộng 100% T3 và Q100/Q426/Q502/Q508/Q870. Spot-check disagreement mới phải được đưa vào explicit adjudication.

## 13. Sealing protocol

Sealer chỉ thành công khi:

- expected QID set đúng 93 và mỗi pass/adjudication có unique rows;
- question hashes khớp frozen corpus;
- A/B/C identities distinct và attestation hợp lệ;
- A/B đủ 93 rows;
- source evidence reviewed cho mọi row;
- không có forbidden model field;
- mọi disagreement field có explicit adjudication;
- answer/semantic/evidence schema hợp lệ;
- output directory chưa tồn tại;
- manifest ghi protocol/guideline/input checksums;
- `gold.jsonl` canonical-sort theo QID và SHA-256 được ghi.

Manifest tối thiểu:

```json
{
  "schema_version": 1,
  "kind": "text2pandas.metric_unresolved_phase1_5_gold",
  "status": "SEALED",
  "measurement_scope": "POST_HOC_EXHAUSTIVE_METRIC_UNRESOLVED_COHORT",
  "promotion_scope": "PHASE_1_CLOSURE_ONLY",
  "production_promotion_eligible": false,
  "records": 93,
  "new_ok_records": 75,
  "safety_boundary_records": 18,
  "annotators": ["reviewer-A", "reviewer-B"],
  "adjudicator": "reviewer-C",
  "inputs": {},
  "assets": {}
}
```

Sau seal không sửa file. Correction phải tạo release ID mới, có `supersedes` và lý do; release cũ được giữ để audit.

## 14. Unblind và comparison

Chỉ sau khi sealer tạo `SEALED` manifest, evaluation engineer mới join gold với frozen candidate bằng QID.

Mỗi new-OK case được đánh ở bốn lớp độc lập:

1. `SEMANTIC_EXACT`: entity/basis/period/operation/roles/metric meaning đúng.
2. `SOURCE_BINDING_EXACT`: ordered evidence thuộc acceptable gold set, đúng statement/unit/scope.
3. `ANSWER_MATCH`: answer đúng result kind/unit và tolerance.
4. `REPLAY_MATCH`: candidate query replay từ materialized evidence ra đúng candidate answer.

`FULLY_CORRECT` chỉ khi cả bốn lớp pass. Value trùng ngẫu nhiên nhưng metric/scope sai không được tính đúng.

Mỗi 18 abstain/boundary case được đánh:

- `ABSTENTION_CORRECT`;
- `FALSE_ABSTENTION_UNIQUE_ANSWERABLE`;
- `SEMANTIC_REPRESENTATION_CORRECT_BUT_DOWNSTREAM_BLOCKED`;
- `FAILURE_REASON_ACCURATE`;
- `ROLE_BOUNDARY_CORRECT` cho Q426/Q502/Q508/Q870;
- `SPECIFICITY_FAIL_CLOSED_CORRECT` cho Q100/T3 ambiguity.

## 15. Metric definitions và denominators

Không được đổi denominator sau khi xem kết quả.

### 15.1 Review-process metrics

```text
annotation_completeness = rows completed by both passes / 93
adjudication_completeness = reviewed disagreement fields / all disagreement fields
gold_evaluable_rate = rows with final RESOLVED answer / cohort rows
field_agreement = exact A/B field matches / compared fields
```

### 15.2 New-OK metrics — fixed cohort 75

```text
semantic_exact_rate = SEMANTIC_EXACT / 75
metric_resolution_exact_rate = correct metric meaning for all required roles / 75
binding_exact_rate = SOURCE_BINDING_EXACT / 75
answer_accuracy_evaluable = ANSWER_MATCH / gold-evaluable new OK
certified_new_ok_rate = FULLY_CORRECT / 75
gold_unsafe_emissions = system OK but gold says ambiguous/not answerable,
                        or critical entity/basis/period/operation/role/metric error
```

Nếu gold không resolve được một new OK, case đó bị loại khỏi `answer_accuracy_evaluable` nhưng **không** bị loại khỏi `certified_new_ok_rate`. Báo cả numerator và denominator, không chỉ phần trăm.

### 15.3 Abstain/boundary metrics — fixed cohort 18

```text
correct_abstention_rate = correct abstain or correct downstream boundary / 18
false_abstention_rate = unique-answerable cases incorrectly abstained / 18
failure_reason_exact_rate = exact/acceptable terminal taxonomy / 18
```

### 15.4 Slice metrics

Báo theo:

- T1/T2/T3/NO_PHRASE/BOUNDARY;
- operation family;
- lookup vs derived;
- source-backed vs exact/source mixed;
- explicit/default basis;
- period/closing/opening;
- single-role vs multi-role;
- ambiguity/specificity cohort;
- Q5/Q15/Q89/Q100/Q426/Q502/Q508/Q870 riêng.

Không kết luận từ slice có denominator <10; chỉ liệt kê case-level outcome.

### 15.5 Tolerance

Pre-register trước unblind:

- finite numeric: `abs(pred-gold) <= 0.005 * max(1, abs(gold))`;
- count và period year: exact integer;
- entity/member label: exact canonical identity, normalized display chỉ hỗ trợ comparison;
- result kind, dimension, currency và requested scale phải đúng;
- NaN/Infinity/empty không bao giờ là answer match.

Mọi ngoại lệ tolerance phải nằm trong frozen config trước unblind; không điều chỉnh theo từng mismatch.

## 16. Error taxonomy sau unblind

Mỗi incorrect/non-certified case phải có một primary root cause và zero-or-more contributing factors.

| Primary error | Meaning | Owner if Phase 1 reopens |
| --- | --- | --- |
| `WRONG_METRIC_MENTION` | Span/meaning của metric sai | Parser/resolver |
| `WRONG_METRIC_SPECIFICITY` | Chọn variant khi question thiếu modifier | Resolver fail-closed policy |
| `WRONG_HIERARCHY_LEVEL` | Parent/child granularity sai | Resolver/source binding |
| `WRONG_OPERAND_ROLE` | Rank/selected/filter/numerator/... sai | Role composer |
| `WRONG_ENTITY` | Scope entity sai | Out-of-scope confounder; do not relabel metric success |
| `WRONG_PERIOD` | Period/point sai | Parser/scope confounder |
| `WRONG_BASIS` | Separate/consolidated sai | Parser/scope confounder |
| `WRONG_SOURCE_BINDING` | Semantic đúng nhưng selected observation sai | Source binding/retrieval boundary |
| `WRONG_UNIT_OR_SCALE` | Source/value đúng nhưng normalization sai | Execution/unit boundary |
| `WRONG_OPERATION` | Lookup/divide/select-at-arg/... sai | Parser/composer |
| `ANSWER_MISMATCH` | Semantic/evidence đúng nhưng answer sai | Execution |
| `GOLD_AMBIGUOUS_SYSTEM_EMITTED` | System phát OK khi gold không unique | Critical unsafe emission |
| `FALSE_ABSTENTION` | Gold unique-answerable nhưng system abstain | Record only unless Phase 1 component caused it |
| `SOURCE_DEFECT` | Frozen source inconsistent | Data work item, never silently fix in Phase 1 |
| `GOLD_UNRESOLVED` | Reviewer cannot determine | Not certified; preserve denominator reporting |

Nếu lỗi không thuộc `METRIC_UNRESOLVED`, báo confounder và defer; không tiện tay sửa trong Phase 1.5.

## 17. Pre-registered acceptance gates

Các threshold dưới đây phải được owner chấp nhận và freeze trước pass A/B. Chúng dùng để mở Phase 2, không phải production promotion.

### 17.1 Governance gates — all mandatory

- [ ] 93/93 present in both A and B.
- [ ] Distinct A/B/C identities and independence attestations verified.
- [ ] Blind packet recursive leakage scan = 0 violations.
- [ ] 100% rows have source evidence review status.
- [ ] 100% disagreement fields explicitly adjudicated.
- [ ] Sealed immutable release and checksums valid.
- [ ] Field agreement overall ≥0,90; critical-field slice agreement ≥0,80 before adjudication.

### 17.2 Phase 1 correctness gates — all mandatory to open Phase 2

- [ ] `gold_unsafe_emissions = 0` for critical semantic safety errors.
- [ ] Gold-evaluable new OK ≥72/75 (≥0,95).
- [ ] `semantic_exact_rate ≥0,95` on fixed 75.
- [ ] `metric_resolution_exact_rate ≥0,95` on fixed 75.
- [ ] `binding_exact_rate ≥0,90` on fixed 75.
- [ ] `answer_accuracy_evaluable ≥0,95`.
- [ ] `certified_new_ok_rate ≥0,90` on fixed 75.
- [ ] `correct_abstention_rate ≥17/18`.
- [ ] Q100 remains correctly fail-closed.
- [ ] Q426/Q502/Q508/Q870 have gold-confirmed role semantics or correctly named boundary abstention.
- [ ] Frozen candidate still has B0 old-OK drift 0/287, V2 lexical drift 0/1.012 and replay mismatch 0.

Why stricter than production answer minimum 0,80: đây là precision audit của một newly emitted, source-backed cohort nhỏ và exhaustive; nó không phải overall 300-record production accuracy. Gate production 0,80 vẫn giữ nguyên và không được sửa.

### 17.3 Decision table

| Outcome | Conditions | Action |
| --- | --- | --- |
| `BLOCKED` | Thiếu reviewer/quorum, leakage, incomplete evidence hoặc không seal được | Không score, không mở Phase 2 |
| `FAIL` | Critical unsafe emission >0, identity violation, candidate/gold mismatch lineage | Reopen Phase 1 only; root-cause affected cases |
| `CONDITIONALLY PASS` | Governance valid, không critical unsafe, nhưng một correctness threshold chưa đạt | Giữ shadow; create bounded remediation plan; Phase 2 blocked |
| `PASS` | Mọi gate 17.1 và 17.2 pass | Close Phase 1, freeze release, prepare clean re-baseline; Phase 2 may be planned |

Không được đổi `CONDITIONALLY PASS` thành `PASS` bằng cách loại difficult/gold-unresolved cases khỏi fixed denominator.

## 18. Remediation loop nếu gate fail

1. Freeze original gold; không relabel theo candidate.
2. Nhóm errors theo taxonomy Mục 16.
3. Xác định lỗi nào thực sự thuộc resolver/mention/role scope.
4. Viết một bounded remediation plan chỉ cho dominant Phase 1 defect.
5. Sửa code trong branch/run mới; giữ raw/A6/index/policy bất biến.
6. Rerun targeted tests, B0 regression, full 1.012, determinism và performance.
7. Re-evaluate toàn bộ 93 bằng sealed gold; không chỉ rerun failed QIDs.
8. Tạo candidate release mới; không overwrite candidate v1.
9. Không cần annotate lại nếu question/source/guideline/gold lineage không đổi. Nếu source/guideline đổi, release gold mới là bắt buộc.

Nếu errors chủ yếu là entity/period/unit/retrieval downstream, Phase 1 resolver không được “sửa số” bằng cách nới resolver. Report phải tách confounders và quyết định có đóng resolver hay không dựa trên metric-resolution fields.

## 19. Phase execution plan

### Work package 0 — Authorization and preregistration

Deliverables:

- owner chấp nhận fixed cohort, thresholds và tolerance;
- assign reviewer A/B/C IDs;
- freeze guideline/protocol checksums;
- declare `POST_HOC_EXHAUSTIVE...` scope;
- confirm no resolver code changes during review.

Exit gate: signed/committed preregistration manifest.

### Work package 1 — Packet builder and integrity tests

Deliverables:

- task-specific packet wrapper;
- 93-question blind packets;
- model-independent source scope bundles;
- recursive leakage scan;
- unit tests and packet checksum manifest.

Exit gate: packet contains exactly 93 question hashes and zero forbidden fields.

### Work package 2 — Calibration

Deliverables:

- out-of-cohort calibration cases;
- frozen schema examples;
- reviewer agreement on ambiguous/source-defect conventions;
- final guideline checksum.

Exit gate: no unresolved procedural question before scored review.

### Work package 3 — Independent annotation

Deliverables:

- pass A 93/93;
- pass B 93/93;
- per-pass validation manifests.

Exit gate: both passes complete and identity/source-review fields valid.

### Work package 4 — Reconciliation and adjudication

Deliverables:

- field-level agreement report;
- disagreement ledger;
- distinct adjudicator decisions;
- required spot-check results.

Exit gate: every disagreement field resolved or explicitly `GOLD_UNRESOLVED`.

### Work package 5 — Immutable seal

Deliverables:

- `gold.jsonl`;
- sealed manifest;
- checksums;
- machine validation report.

Exit gate: release status `SEALED`; no mutation afterward.

### Work package 6 — Unblind and evaluate

Deliverables:

- case-level comparison 93 rows;
- 75 new-OK precision/correctness metrics;
- 18 abstain/boundary safety metrics;
- tier/operation/role slices;
- error taxonomy and critical unsafe list;
- rerun of frozen safety checks.

Exit gate: all metrics reproducible from sealed inputs.

### Work package 7 — Decision and Phase 1 closure report

Deliverable path:

```text
docs/reports/METRIC_UNRESOLVED_GOLD_ADJUDICATION_REPORT_<completion-date>.md
```

Report decision follows Mục 17.3. Chỉ khi `PASS` mới tạo Phase 2 planning brief.

## 20. Effort and capacity estimate

Đây là effort estimate, không phải deadline:

| Work | Expected effort |
| --- | ---: |
| Packet tooling, manifests, integrity tests | 0,5–1,0 engineer-day |
| Calibration ngoài cohort | 0,5 reviewer-day tổng |
| Pass A — 93 cases | khoảng 18–31 reviewer-hours |
| Pass B — 93 cases | khoảng 18–31 reviewer-hours |
| Adjudication + spot-check | khoảng 6–16 reviewer-hours, tùy disagreement |
| Seal, unblind evaluation, report | 0,5–1,0 engineer-day |

Estimate giả định trung bình 12–20 phút/case vì nhiều source-backed rows cần kiểm hierarchy, unit và provenance. Không ép throughput bằng cách bỏ source review.

## 21. Risks và controls

| Risk | Failure mode | Control |
| --- | --- | --- |
| Model leakage từ current queue | Gold lặp prediction | Không phát queue trực tiếp; recursive forbidden-field scan |
| Post-hoc selection bị gọi là held-out | Overclaim production accuracy | Manifest đóng dấu post-hoc/phase-only |
| Reviewer A/B trao đổi | False agreement | Separate packets, timestamps, identities, no shared draft |
| Adjudicator là resolver author | Correlated error | Distinct independent reviewer C |
| Evidence bundle dẫn theo selected row | Binding bias | Full hard-scope bundle, no rank/top-K/score |
| Gold denominator bị thu nhỏ | Inflated precision | Báo fixed denominator 75/18 cùng evaluable denominator |
| Value trùng nhưng metric sai | False correct | `FULLY_CORRECT` yêu cầu semantic + binding + answer + replay |
| Ambiguous case bị force | Unsafe gold | Explicit `AMBIGUOUS/GOLD_UNRESOLVED` statuses |
| Guideline đổi sau unblind | Outcome tuning | Freeze checksum before scored passes |
| Label sửa tại chỗ | Audit loss | Immutable release; corrections create superseding release |
| Phase 2 bắt đầu sớm | Compound bugs | Phase 2 entry checklist là hard gate |
| 162 count bị hiểu sai | Wrong denominator | Tách 22 H198 transitions khỏi 162 full corpus |
| 93 pass nhưng production claim | Governance breach | Production eligible luôn false cho phase-specific release |

## 22. Phase 2 entry checklist

Chỉ mở plan `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` khi tất cả điều sau đúng:

- [ ] Phase 1.5 decision = `PASS`.
- [ ] Sealed 93-case release exists and checksum verifies.
- [ ] Error taxonomy không còn unresolved critical metric-resolution defect.
- [ ] Resolver implementation được freeze thành commit/patch identity rõ ràng.
- [ ] Một clean full-corpus rerun từ frozen implementation canonical-match candidate records, hoặc mọi drift được giải thích và re-evaluate against gold.
- [ ] B0 287 old OK vẫn zero drift; V2 hash và replay vẫn sạch.
- [ ] Full-corpus terminal counts được re-baseline; `162` chỉ dùng nếu clean rerun tái hiện.
- [ ] Phase 2 có baseline/cohort/acceptance gates riêng.
- [ ] Phase 2 không sửa `BINDING_TIE` hay retrieval/binder trong cùng task.

Phase 2 audit phải phân loại 162 records ít nhất theo:

```text
reported source metric used in lookup-safe operation
reported source metric used as derived operand
formula explicitly requested by question
formula inferred but not explicit
multi-role/source-backed interaction
gold-supported vs policy-only block
```

Đây chỉ là entry brief; không thiết kế hoặc implement Phase 2 trong plan này.

## 23. Phase 1.5 definition of done

Phase 1.5 chỉ hoàn thành khi có đủ:

1. Frozen identity cho 93 cases và candidate lineage.
2. Blind packet không lộ model output.
3. Hai independent passes 93/93.
4. Distinct adjudication cho mọi disagreement.
5. Immutable sealed gold release.
6. Case-level unblind comparison.
7. Accuracy/precision/safety metrics với denominators rõ ràng.
8. Error taxonomy và list QIDs incorrect/non-certified.
9. Safety rerun trên B0 old OK, V2 và replay.
10. Final `PASS/CONDITIONALLY PASS/FAIL/BLOCKED` report.
11. Production status được giữ `BLOCKED` trừ khi independent 300-record policy riêng cũng pass.
12. Phase 2 chỉ được mở nếu Phase 1.5 `PASS`.

## 24. Required final report tables

Final adjudication report phải có tối thiểu:

### Review integrity

| Metric | Result |
| --- | ---: |
| Cohort | 93/93 |
| Pass A complete | |
| Pass B complete | |
| Distinct adjudication | |
| Leakage violations | |
| Disagreement fields | |
| Gold unresolved | |

### New-OK correctness

| Metric | Numerator | Denominator | Rate | Gate |
| --- | ---: | ---: | ---: | --- |
| Semantic exact | | 75 | | ≥0,95 |
| Metric resolution exact | | 75 | | ≥0,95 |
| Binding exact | | 75 | | ≥0,90 |
| Answer accuracy evaluable | | | | ≥0,95 |
| Certified new OK | | 75 | | ≥0,90 |
| Critical unsafe emissions | | 75 | | 0 |

### Boundary safety

| Metric | Numerator | Denominator | Rate | Gate |
| --- | ---: | ---: | ---: | --- |
| Correct abstention/boundary | | 18 | | ≥17/18 |
| False abstention | | 18 | | Report |
| Failure reason exact | | 18 | | Report |

### Decision

```text
PHASE 1.5 STATUS:
PASS / CONDITIONALLY PASS / FAIL / BLOCKED

COHORT:
93/93

NEW OK REVIEWED:
75/75

CERTIFIED NEW OK:
X/75

ANSWER ACCURACY:
X/Y

CRITICAL UNSAFE EMISSIONS:
X

CORRECT BOUNDARY/ABSTAIN:
X/18

PRODUCTION PROMOTION:
BLOCKED / ELIGIBLE UNDER SEPARATE 300-RECORD RELEASE

PHASE 2:
OPEN / BLOCKED
```

## 25. Immediate next action

Việc đầu tiên không phải annotate ngay và cũng không phải sửa code runtime. Thứ tự thực thi là:

1. Owner chấp nhận thresholds Mục 17.
2. Gán reviewer A/B/C độc lập.
3. Freeze guideline checksum và reviewer assignment manifest.
4. Build/validate blind packet 93 cases.
5. Chỉ sau bốn bước trên mới bắt đầu Pass A/B.

Nếu chưa có đủ hai annotator và một adjudicator, trạng thái đúng là `BLOCKED_PENDING_INDEPENDENT_REVIEW`; tuyệt đối không thay bằng self-review rồi gọi là gold.
