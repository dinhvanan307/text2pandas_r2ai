# SEMANTIC PARSER WAVE 6 — COMPOSITION IMPLEMENTATION REPORT

**Ngày:** 2026-08-31  
**Trạng thái:** `SHADOW_IMPLEMENTED_PROMOTION_BLOCKED`

## Kết luận

Đã triển khai và kiểm thử lớp semantic composition theo hướng tổng quát, fail-closed.
Hệ thống hiện dựng được full `QuestionAST` candidate cho **23/40** development records;
**17/40** còn lại dừng với blocker có mã cụ thể. Full Semantic V3 E2E chạy đủ
**1.012/1.012 QID**; cả **491/491** record `OK` có query, evidence và clean replay `MATCH`.

Chưa bật runtime mới và không tạo submission. Correctness/Answer Accuracy vẫn là
`NOT_MEASURED` vì source evidence của development set là `0/40` và replacement holdout
v2 vẫn được niêm phong, chưa có nhãn độc lập A/B/C.

## Phạm vi đã triển khai

Các thay đổi nằm trong grammar/parser chung, không có nhánh runtime theo QID:

- nhận diện vai trò numerator/denominator cho các mẫu `trên`, `so với`, `trong tổng`;
- bảo toàn thứ tự `derive per member → aggregate`;
- dựng chuỗi `filter nhiều kỳ → growth/ratio/change → aggregate`;
- dựng accrual ratio `(LNST - CFO) / tài sản bình quân` dưới filter;
- giữ đúng outer operation là `sum/average` thay vì flatten thành direct lookup;
- phân biệt dimension `money`, `ratio`, `percent`, `percent_point` trước khi emit;
- phát hiện hai vai trò ratio cùng trỏ một metric và abstain thay vì chọn tùy ý;
- giữ trailing aggregate sau filter thay vì để annotator ghi đè sai operation.

Code và kiểm thử chính:

- [parser.py](../../src/text2pandas/application/parsing/parser.py)
- [legacy_annotator.py](../../src/text2pandas/infrastructure/semantic/legacy_annotator.py)
- [test_semantic_parser_v3.py](../../tests/unit/test_semantic_parser_v3.py)
- [semantic_parser_development.py](../../src/text2pandas/application/usecases/semantic_parser_development.py)
- [audit_semantic_parser_wave6_development.py](../../tools/evaluation/audit_semantic_parser_wave6_development.py)
- [test_semantic_parser_development.py](../../tests/unit/test_semantic_parser_development.py)

Commits:

- `58fe9e9` — `feat(parser): preserve nested composition semantics`
- `7978c9e` — `feat(evaluation): audit reviewed parser development set`

## Kết quả trên 40 development records

| Chỉ số | Kết quả |
| --- | ---: |
| Development records | 40 |
| Full `QuestionAST` candidates | 23 |
| Chưa có full AST | 17 |
| `ABSTAIN → OK` | 9 |
| `OK → ABSTAIN` | 3 |
| `OK → OK` | 14 |
| `ABSTAIN → ABSTAIN` | 14 |
| Source evidence đã review | 0/40 |
| Correctness | `NOT_MEASURED` |

Ba chuyển đổi `OK → ABSTAIN` là tác động dự kiến của fail-closed gate: output cũ có hình
dạng không nhất quán về role/dimension nên bị chặn. Việc emit ít hơn không tự chứng minh
regression hay improvement accuracy.

### 17 blocker còn lại

| Blocker | Số lượng |
| --- | ---: |
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 7 |
| `DIMENSION_MISMATCH:money:percent` | 3 |
| `BINARY_OPERANDS_UNRESOLVED` | 2 |
| `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | 2 |
| `EXPLICIT_RATIO_OPERAND_AMBIGUOUS` | 1 |
| `EXPLICIT_RATIO_ROLE_COLLISION` | 1 |
| `FILTER_SELECTED_EXPRESSION_UNRESOLVED` | 1 |

Checkpoint chi tiết:

- [development summary](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v1/summary.json)
- [40 development records](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v1/records.jsonl)
- [development manifest](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v1/manifest.json)

## Differential parser toàn bộ 1.012 QID

| Measurement | S0 trước sửa | S3 candidate | Delta |
| --- | ---: | ---: | ---: |
| Primary `OK` | 784 | 769 | -15 |
| Primary `ABSTAIN` | 228 | 243 | +15 |
| Any-candidate `OK` | 798 | 787 | -11 |
| QID có output thay đổi | — | 79 | — |

Scope của bảng này là `PREDICTED_STRUCTURE_ONLY_NOT_GOLD`. Delta coverage âm phản ánh
validator mới chặn thêm các cấu trúc không chắc chắn; không được diễn giải là Answer Accuracy
giảm. Tương tự, 9 development record mới emit AST cũng chỉ là candidate coverage, chưa phải
9 câu đúng.

Artifacts:

- [S0 manifest](../../artifacts/runs/semantic-parser/semantic-parser-wave6-pre-composition-20260831-v1/manifest.json)
- [S3 manifest](../../artifacts/runs/semantic-parser/semantic-parser-wave6-composition-s3-20260831-v1/manifest.json)

## Full Semantic V3 E2E

Run `semantic-parser-wave6-composition-e2e-20260831-v1` hoàn tất trong `125.096s`:

| Gate | Kết quả |
| --- | ---: |
| Tổng QID | 1.012 |
| Semantic V3 `OK` | 491 |
| Semantic V3 `ABSTAIN` | 521 |
| `OK` có `pandas_query` | 491/491 |
| `OK` có evidence | 491/491 |
| `PANDAS_REPLAY = MATCH` | 491/491 |
| Exact `TYPED_PANDAS_MISMATCH` | 0 |
| Promotion | `BLOCKED` |
| Answer Accuracy | `NOT_MEASURED` |

So với checkpoint axes gần nhất, số `OK` là `492 → 491`. Đồng thời
`REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` giảm `36 → 23`, nhưng
`EXPLICIT_RATIO_OPERAND_UNRESOLVED` tăng `12 → 20` do role gate chặt hơn. Đây là trade-off
coverage/fail-closed, chưa phải bằng chứng score tăng.

Blocker E2E lớn nhất hiện tại:

| Reason | Số lượng |
| --- | ---: |
| `BINDING_TIE` | 121 |
| `METRIC_SOURCE_SPECIFICITY_REQUIRED` | 38 |
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 23 |
| `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | 20 |

Artifacts:

- [E2E manifest](../../artifacts/runs/semantic-v3/semantic-parser-wave6-composition-e2e-20260831-v1/manifest.json)
- [E2E records](../../artifacts/runs/semantic-v3/semantic-parser-wave6-composition-e2e-20260831-v1/records.jsonl)

## Validation

| Gate | Kết quả |
| --- | --- |
| Targeted unit tests | `54 passed` |
| Integration tests | `22 passed` |
| Offline suite | `2473 passed, 42 skipped, 29 deselected` |
| Lint | `PASS` |
| Mypy | `PASS`, 124 source files |
| Snapshot verify | `PASS` |

Active snapshot IDs:

- raw: `ca033190f2e9e99f`
- A6: `c6887fb633374fad`
- retrieval: `872ccb0dda9a2bb6`

Machine-readable checkpoint: [semantic_parser_wave6_composition_checkpoint.json](../../provenance/semantic_parser/semantic_parser_wave6_composition_checkpoint.json).

## Holdout và promotion boundary

20 holdout cũ đã xuất hiện trong review người dùng nên chỉ còn vai trò exposed diagnostic.
Replacement holdout v2 đã được chọn độc lập với prediction/answer, overlap với legacy gold và
review đều bằng 0, nhưng vẫn giữ trạng thái `SEALED_UNOPENED_UNLABELED`:

- scope SHA-256: `82724b7376521e148051ce21276ff3b355190f2f656acbed84478e3025a196a9`;
- A/B/C completed: `0/20`, `0/20`, `0/20`;
- [holdout provenance](../../provenance/semantic_parser/semantic_parser_wave6_replacement_holdout_v2.json).

Do đó không dùng development prose làm runtime truth, không mở holdout để sửa parser, không
tạo submission và không dự báo leaderboard score từ replay/coverage.

## Bước tiếp theo đúng thứ tự

- Hoàn thiện 17/40 AST còn thiếu bằng source-metric evidence và role/dimension rules tổng quát.
- Freeze code/config/parser fingerprint sau khi 40/40 có full candidate schema hợp lệ.
- Giao replacement holdout cho annotator A và B độc lập; adjudicator C chỉ xem các disagreement.
- Đo AST exact, binding exact và answer correctness trên holdout đã adjudicate.
- Chỉ chạy differential với protected baseline khi holdout đạt gate định trước; promotion phải
  không có protected loss và có improvement độc lập.
- Chỉ sau PASS mới bật guarded runtime và build submission candidate.

Ưu tiên kỹ thuật sau parser là giải quyết `BINDING_TIE` và source specificity, nhưng không mở
rộng selector/binder trước khi 17 development blocker của semantic/source layer được phân loại
và source evidence được khóa.
