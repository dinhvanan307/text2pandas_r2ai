# SEMANTIC PARSER WAVE 6 — PARTIAL CHECKPOINT REPORT

**Ngày:** 2026-08-31  
**Repository:** Text2Pandas  
**Branch:** `mentor-grounded-v6`  
**Kết luận gate:** `BLOCKED_PENDING_HUMAN_REVIEW`

## 1. Kết quả điều hành

Đã thực hiện đúng thứ tự của plan đến hết Gate P1 có thể tự động hóa:

1. đóng băng baseline parser-only trên đủ 1.012 QID;
2. đo riêng cohort Risk-A60 với split cố định 40 development/20 holdout;
3. tạo contract `CompositionFrame` dùng cho gold semantic parser;
4. tạo packet A/B/C prediction-blind, validator chống prediction leakage và CLI audit;
5. chạy các gate test, lint và typecheck;
6. dừng trước Phase 2 vì chưa có ba lượt review độc lập.

Không có thay đổi nào được đưa vào runtime `SemanticParser`, Canonical V2, retrieval,
execution hoặc submission. Việc dừng là bắt buộc theo plan: nếu tự điền A/B/C bằng cùng
một tác nhân thì holdout không còn độc lập và mọi tuyên bố cải thiện parser sẽ không có
giá trị đo lường.

## 2. Trạng thái từng phase

| Phase | Trạng thái | Kết quả |
| --- | --- | --- |
| P0 — parser-only S0 baseline | PASS | 1.012/1.012 record, source commit sạch |
| P1 — independent semantic gold | BLOCKED | A 0/60, B 0/60, C 0/60 |
| P2 — CompositionFrame runtime | NOT STARTED | Bị chặn bởi P1 |
| P3 — nested operation parser | NOT STARTED | Bị chặn bởi P1 |
| P4 — structural/admission split | NOT STARTED | Bị chặn bởi P1 |
| P5 — static dimension inference | NOT STARTED | Bị chặn bởi P1 |
| P6 — guarded Canonical V2 integration | NOT STARTED | Bị chặn bởi P1 |
| P7 — shadow/differential/holdout | NOT STARTED | Bị chặn bởi P1 |

## 3. Phase 0 — baseline parser-only đã đóng băng

Artifact:

- [manifest baseline](../../artifacts/runs/semantic-parser/semantic-parser-wave6-s0-20260831-v1/manifest.json)
- [records baseline](../../artifacts/runs/semantic-parser/semantic-parser-wave6-s0-20260831-v1/records.jsonl)
- [provenance S0](../../provenance/semantic_parser/semantic_parser_wave6_s0.json)

Định danh:

| Thành phần | Giá trị |
| --- | --- |
| Source commit | `3457612c57074192786c143ade1ef4c98f35e69b` |
| Git dirty khi chạy | `false` |
| Questions SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| A6 build | `c6887fb633374fad` |
| Ontology fingerprint | `bdef88d94b814ae60109f3da486a627d02dfbbe5d1e3ad6ede942598532644c8` |
| Records SHA-256 | `63a2b6da21e3447cf652f8a7e2edf15f8c9ceb1bc1c7f35c1a97006abf93ead4` |
| Measurement scope | `PREDICTED_STRUCTURE_ONLY_NOT_GOLD` |
| Correctness | `NOT_MEASURED` |

### 3.1 Toàn bộ 1.012 QID

| Chỉ số | Giá trị |
| --- | ---: |
| Primary parse `OK` | 784 |
| Primary parse `ABSTAIN` | 228 |
| Có ít nhất một candidate `OK` | 798 |
| Tổng candidate `OK` | 1.190 |
| Tổng candidate `ABSTAIN` | 352 |

Các nhóm dự đoán trên 1.190 candidate `OK`: direct 605, derived 183,
aggregated 147, ranked 145 và compositional 110. Đây là phân bố output của parser,
không phải số câu đúng.

Các blocker primary lớn nhất trên toàn corpus:

| Reason | Số QID |
| --- | ---: |
| `METRIC_SOURCE_SPECIFICITY_REQUIRED` | 38 |
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 36 |
| `BINARY_OPERANDS_UNRESOLVED` | 19 |
| `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED` | 19 |
| `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | 18 |
| `DIRECT_OPERATION_METRIC_AMBIGUOUS` | 14 |
| `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | 12 |
| `QUESTION_MENTION_NO_MAPPING` | 11 |

### 3.2 Cohort Risk-A60

Scope SHA-256:
`9d77ec98fd7a1c2562ec94e4929d023dfbb0552560515c187b20593226d44899`.

| Chỉ số | Giá trị |
| --- | ---: |
| Records | 60 |
| Development/Holdout | 40/20 |
| Primary `OK` | 25 |
| Primary `ABSTAIN` | 35 |
| Có candidate `OK` | 25 |

Breakdown 35 abstention:

| Reason | Số QID |
| --- | ---: |
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 19 |
| `DIRECT_OPERATION_METRIC_AMBIGUOUS` | 4 |
| `BINARY_OPERANDS_UNRESOLVED` | 3 |
| `TEMPORAL_FILTER_SELECTED_EXPRESSION_AMBIGUOUS` | 3 |
| `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | 2 |
| Bốn reason còn lại | 4 |

Con số 25/60 chỉ chứng minh parser phát ra AST, không chứng minh 25 AST đó đúng.

## 4. Phase 1 — packet gold parser độc lập

Packet:

- [manifest review](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/manifest.json)
- [scope 60 QID](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/scope.json)
- [reviewer A](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/annotator_a.jsonl)
- [reviewer B](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/annotator_b.jsonl)
- [adjudicator C](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/adjudication.jsonl)
- [audit hiện tại](../../artifacts/runs/evaluation/semantic-parser-wave6-review-20260831-v1/audit.json)
- [protocol](../../configs/evaluation/semantic_parser_wave6_protocol_v1.json)
- [provenance P1](../../provenance/semantic_parser/semantic_parser_wave6_p1_checkpoint.json)

Mỗi annotation khóa các trường semantic hệ thống:

- entity domain, period domain và basis;
- metric mentions và semantic role;
- predicate clauses và logical connectors;
- temporal transforms;
- projection, aggregate và rank;
- operation order;
- expected AST;
- output dimension;
- ambiguity status.

Packet không chứa model AST, candidate, score, parser status hoặc parser reason. Validator
quét đệ quy và fail-closed nếu reviewer chèn các trường này. Mỗi record còn được khóa bằng
QID, question SHA-256, family và split.

### 4.1 Trạng thái audit

| Gate | Thực tế | Yêu cầu | Kết quả |
| --- | ---: | ---: | --- |
| Annotator A | 0/60 | 60/60 | FAIL |
| Annotator B | 0/60 | 60/60 | FAIL |
| Adjudicator C | 0/60 | 60/60 | FAIL |
| Distinct identities | 0 | 3 | FAIL |
| Prediction leakage | 0 field | 0 field | PASS |
| Split | 40/20 | 40/20 | PASS |

Blocker máy đọc được:

```text
ANNOTATOR_A_INCOMPLETE:60
ANNOTATOR_B_INCOMPLETE:60
ADJUDICATION_INCOMPLETE:60
DISTINCT_REVIEWER_IDENTITIES_REQUIRED:0:3
```

## 5. Thay đổi trong repository

| Commit | Nội dung |
| --- | --- |
| `3457612` | Runner parser-only và record/profile contract |
| `d03ee40` | Provenance baseline S0 |
| `9cd62fc` | Review contract, prediction-blind packet generator, protocol và tests |
| `74147a7` | CLI audit A/B/C độc lập |

Không có QID branch, không sửa gold theo prediction, không hạ validator và không thay đổi
ontology/runtime behavior.

## 6. Verification

| Gate | Kết quả |
| --- | --- |
| Parser baseline targeted tests | 49 passed |
| Review contract targeted tests | 12 passed |
| `ruff check` | PASS |
| `make typecheck` | PASS, 121 source files |
| `make test-offline` | PASS, 2.453 passed, 42 skipped, 29 deselected |
| `make test-integration` | PASS, 22 passed, 2.502 deselected |
| `git diff --check` | PASS |
| `make ci` | BLOCKED ở `docs-check` bởi 15 link artifact lịch sử đã thiếu |

15 broken link thuộc các report ngày 2026-08-29 và trỏ tới artifact lịch sử không có trong
checkout hiện tại. Không link nào đến từ code/packet Wave 6 mới. Vì phạm vi task là semantic
parser và không được phép chế lại artifact lịch sử, lỗi này được ghi nhận chứ không hạ gate
hoặc sửa link để che blocker.

## 7. Điều kiện để tiếp tục Phase 2

1. Reviewer A điền bản A mà không xem output model hoặc bản B.
2. Reviewer B điền bản B mà không xem output model hoặc bản A.
3. Reviewer C độc lập đối chiếu bất đồng A/B, kiểm tra source evidence và điền bản C.
4. Ba trường identity phải là ba người khác nhau và ổn định trên toàn bộ 60 record.
5. Chạy audit:

```bash
PYTHONPATH=src python tools/evaluation/audit_semantic_parser_wave6_review.py \
  --scope <completed-review>/scope.json \
  --annotator-a <completed-review>/annotator_a.jsonl \
  --annotator-b <completed-review>/annotator_b.jsonl \
  --adjudication <completed-review>/adjudication.jsonl \
  --output <new-immutable-audit.json>
```

Chỉ khi audit trả `READY_TO_SEAL` mới được dùng 40 development records để implement
CompositionFrame/nested operations. 20 holdout records tiếp tục sealed đến khi code và
config đã freeze, sau đó mới mở đúng một lần để đo AST exact match và regression.

## 8. Kết luận

Checkpoint này hoàn thành nền đo lường và governance cần thiết để sửa semantic parsing ở
cấp hệ thống. Chưa có bằng chứng cho phép tuyên bố parser tốt hơn, chưa có candidate ZIP và
không có thay đổi submission. Bước tiếp theo không phải viết thêm rule; bước tiếp theo là
hoàn tất gold A/B/C độc lập để mở Gate P1 mà không làm ô nhiễm phép đo.
