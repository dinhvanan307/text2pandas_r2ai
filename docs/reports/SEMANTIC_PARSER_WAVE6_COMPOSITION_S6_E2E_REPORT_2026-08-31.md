# Semantic Parser Wave 6 — Composition S6 E2E Report

**Ngày:** 2026-08-31  
**Nhánh:** `mentor-grounded-v6`  
**Trạng thái:** `SHADOW_IMPLEMENTED — RUNTIME/SUBMISSION PROMOTION BLOCKED`

## Kết luận

Plan đã được thực thi qua code, parser differential, full Semantic V3 E2E, clean replay,
offline/integration tests và snapshot verification. Bản cuối tạo **28/40 full QuestionAST
candidates** trên development supervision và chạy đủ **1.012/1.012 QID** ở shadow mode.

Không thể hoàn tất gate `40/40` bằng kiến trúc hiện tại mà không đoán category/column/total
semantics. 12 record còn lại vì vậy giữ `ABSTAIN`. Replacement holdout vẫn chưa có ba lượt
review độc lập (`A 0/20`, `B 0/20`, `C 0/20`), nên AST exact, binding exact và Answer Accuracy
đều là `NOT_MEASURED`. Không bật runtime mới và không tạo submission ZIP.

## Các thay đổi đã triển khai

### Derived leaf và compositional grammar

Commit `1ed71ba`:

- tách dimension của source leaf khỏi dimension output cho divide/growth/count/extremum;
- hỗ trợ explicit-ratio bên trong subtract/sum/average;
- thêm closed grammar `sign predicate AND threshold predicate → temporal projection → aggregate`;
- giữ fail-closed khi source qualifier của explicit ratio không được bind;
- chuẩn hóa câu hỏi “tỷ lệ biến động ... giữa hai kỳ ... %” thành growth.

### Governed source-label normalization

Commit `abe5c12`:

- thêm rule có provenance cho biến thể “chi phí nguyên liệu, vật liệu” và
  “chi phí nguyên, vật liệu”;
- rule có positive/negative evidence và không hard-code runtime theo QID.

### Clean replay contract

Commit `e68f704`:

- buộc `observation_uid` được đọc như opaque string khi replay CSV;
- sửa lỗi UID chỉ gồm chữ số bị Pandas ép thành floating point và mất precision;
- thêm regression test bằng UID `125956184363e033`.

### Lending/borrowing và observation-role safety

Commit `fbcc243`:

- không ánh xạ cụm `cho vay ...` sang metric liability `vay ...`;
- explicit ratio không được bỏ mất role nguồn như `nguyên giá`, `giá gốc`,
  `hao mòn lũy kế`, `khấu hao lũy kế`;
- Q723 đổi từ sai metric `long_term_borrowings` sang source label
  `Cho vay dài hạn bên liên quan`;
- Q667 quay về abstain vì kiến trúc V3 chưa bind được cột `nguyên giá`;
- Q308 và Q324 quay về `BINDING_TIE` thay vì phát answer từ borrowing metric không chắc chắn.

## Development checkpoint

So với composition S3:

| Chỉ số parser-only | S3 | S6 | Delta |
| --- | ---: | ---: | ---: |
| Primary `OK` | 769 | 782 | +13 |
| Primary `ABSTAIN` | 243 | 230 | -13 |
| Có ít nhất một candidate `OK` | 787 | 802 | +15 |

Đây là **candidate coverage**, không phải correctness. So với checkpoint development ban đầu,
full AST candidates tăng từ `23/40` lên `28/40`. Checkpoint trung gian từng đạt `29/40`, nhưng
source audit phát hiện ánh xạ `cho vay`/`vay` và role `giá gốc/nguyên giá` không an toàn; bản S6
chủ động hạ coverage thay vì giữ false positive.

Final development summary:

| Gate | Kết quả |
| --- | ---: |
| Development records | 40 |
| Full QuestionAST candidates | 28 |
| Chưa có QuestionAST | 12 |
| Source evidence independently reviewed | 0 |
| Correctness | `NOT_MEASURED` |
| Promotion eligible | `false` |

12 blockers cuối:

| QID | Reason | Capability còn thiếu |
| ---: | --- | --- |
| 427 | `BINARY_OPERANDS_UNRESOLVED` | currency/category axis và sensitivity-table operation |
| 430 | `BINARY_OPERANDS_UNRESOLVED` | filter → multi-metric rank → selected projection; operating-margin composition |
| 691 | `EXPLICIT_RATIO_OPERAND_AMBIGUOUS` | product/geography subtotal theo row hierarchy |
| 707 | `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | allowance numerator và total receivable role |
| 735 | `EXPLICIT_RATIO_OPERAND_UNRESOLVED` | total-borrowings source aggregate trước entity subtraction |
| 844 | `DIMENSION_MISMATCH:money:percent` | implicit equity-ratio denominator |
| 846 | `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | accumulated-depreciation/gross-cost observation roles |
| 881 | `DIMENSION_MISMATCH:money:percent` | gross-cost column total và aligned periods |
| 931 | `DIRECT_OPERATION_METRIC_AMBIGUOUS` | unique depreciation-ratio source across entities |
| 935 | `DIMENSION_MISMATCH:money:percent` | disambiguation của “lợi nhuận thuần” |
| 955 | `DIMENSION_MISMATCH:money:percent` | loan-tenor/category axis; không được dùng short-term borrowings |
| 957 | `DIMENSION_MISMATCH:money:percent` | repricing bucket `1–3 tháng` ở column axis |

Artifacts:

- [S6 parser manifest](../../artifacts/runs/semantic-parser/semantic-parser-wave6-composition-s6-20260831-v1/manifest.json)
- [S6 parser records](../../artifacts/runs/semantic-parser/semantic-parser-wave6-composition-s6-20260831-v1/records.jsonl)
- [development summary](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v3/summary.json)
- [development records](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v3/records.jsonl)
- [development manifest](../../artifacts/runs/evaluation/semantic-parser-wave6-development-checkpoint-20260831-v3/manifest.json)

## Full Semantic V3 E2E

Run `semantic-parser-wave6-composition-s6-e2e-20260831-v1` chạy đủ corpus:

| Gate | Kết quả |
| --- | ---: |
| QID | 1.012 |
| Semantic V3 `OK` | 492 |
| Semantic V3 `ABSTAIN` | 520 |
| `OK` có query và evidence | 492/492 |
| Clean replay `MATCH` | 492/492 |
| Replay mismatch | 0 |
| Replay error | 0 |
| Thời gian | 165,626 giây |
| Promotion | `BLOCKED` |
| Answer Accuracy | `NOT_MEASURED` |

Differential so với E2E checkpoint trước (`491 OK / 521 ABSTAIN`):

| Transition | Số lượng | QID đáng chú ý |
| --- | ---: | --- |
| `OK → OK` | 489 | toàn bộ answer value được giữ nguyên |
| `ABSTAIN → ABSTAIN` | 518 | — |
| `ABSTAIN → OK` | 3 | 629, 721, 723 |
| `OK → ABSTAIN` | 2 | 308, 324 |

Source audit của thay đổi:

- Q629 chọn đúng hai row allowance HBC 2016/2020, nhưng quy ước dấu của phần trăm biến động
  vẫn cần adjudication; không tuyên bố answer đúng.
- Q721 dùng đúng hai source labels đầu tư cổ phiếu và đầu tư liên doanh/liên kết; vẫn là
  source-backed candidate, chưa phải gold win.
- Q723 đã sửa metric/source thật: numerator là `Cho vay dài hạn bên liên quan`, denominator là
  `Các khoản phải thu dài hạn`; answer shadow đổi từ `70.5043...` sai source sang `93.8666...`.
- Q308 và Q324 bị chặn vì cụm `cho vay` không đủ bằng chứng để dùng liability-side borrowing;
  đây là fail-closed safety change.
- Q667 bị loại khỏi S5 output vì S5 đã lấy net tangible fixed assets thay cho `nguyên giá`.

Artifacts:

- [E2E manifest](../../artifacts/runs/semantic-v3/semantic-parser-wave6-composition-s6-e2e-20260831-v1/manifest.json)
- [E2E records](../../artifacts/runs/semantic-v3/semantic-parser-wave6-composition-s6-e2e-20260831-v1/records.jsonl)
- [clean replay report](../../artifacts/runs/semantic-v3/semantic-parser-wave6-composition-s6-e2e-20260831-v1/replay_report.json)

## Validation

| Gate | Kết quả |
| --- | --- |
| Targeted parser/resolver/replay tests | `82 passed` |
| Full offline suite | `2.504 passed, 42 skipped, 29 deselected` |
| Integration suite | `22 passed, 2.553 deselected` |
| Ruff | `PASS` |
| Mypy | `PASS`, 126 source files |
| Snapshot verify | `PASS` |

Active identities không đổi:

- raw snapshot: `ca033190f2e9e99f`;
- A6 build: `c6887fb633374fad`;
- retrieval index: `872ccb0dda9a2bb6`;
- ontology fingerprint: `bdef88d94b814ae60109f3da486a627d02dfbbe5d1e3ad6ede942598532644c8`;
- source resolver fingerprint: `10f756a9ebdf2ecf7e443636ab69c57f8ef10ec8bfd8ad8c38b4085f9c37cfba`.

Machine-readable checkpoint:
[semantic_parser_wave6_composition_s6_checkpoint.json](../../provenance/semantic_parser/semantic_parser_wave6_composition_s6_checkpoint.json).

## Independent holdout và promotion decision

Replacement holdout v2 vẫn giữ nguyên các annotation placeholders. Audit hiện tại:

```text
ANNOTATOR_A_INCOMPLETE:20
ANNOTATOR_B_INCOMPLETE:20
ADJUDICATION_INCOMPLETE:20
DISTINCT_REVIEWER_IDENTITIES_REQUIRED:0:3
```

Không thể tự tạo ba lượt review “độc lập” trong cùng một agent run. Vì vậy:

- code/config freeze để promotion: `BLOCKED` do development chưa đạt 40/40;
- parser AST exact: `NOT_MEASURED`;
- binding exact: `NOT_MEASURED`;
- answer correctness: `NOT_MEASURED`;
- guarded runtime: `KEEP_OFF`;
- submission candidate: `NOT_BUILT`.

## Bước tiếp theo bắt buộc

Muốn xử lý 12 blocker mà không hard-code, plan cần được mở rộng có kiểm soát theo thứ tự:

1. thêm typed `CategoryAxis/ColumnAxis` cho currency, tenor, repricing bucket và geography;
2. đưa `ObservationRoleSpec` vào Semantic V3 planner/retriever ở enforced mode cho
   cost/allowance/total/opening/closing;
3. thêm source total/subtotal aggregation dựa trên row/column hierarchy;
4. chỉ sau đó chạy lại 12 development records và yêu cầu source evidence exact;
5. giao replacement holdout cho A/B/C độc lập, seal kết quả rồi mới đo correctness và quyết định
   promotion.

Cho đến khi các gate trên PASS, việc đóng gói S6 thành bài nộp sẽ là thay đổi không có bằng chứng
và có thể làm giảm Answer Accuracy chính thức.
