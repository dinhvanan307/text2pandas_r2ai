# SEMANTIC PARSER WAVE 6 — USER REVIEW INGESTION

**Ngày:** 2026-08-31  
**Trạng thái:** `SINGLE_USER_REVIEW_COMPLETE_RUNTIME_BLOCKED`

## 1. Kết quả

Đã chuẩn hóa và nhập đủ review người dùng cho 60/60 QID. Queue gốc được giữ nguyên;
review được materialize thành một file mới để bảo toàn provenance.

| Quyết định | Số QID |
| --- | ---: |
| `ACCEPT` | 8 |
| `ACCEPT_PENDING_SOURCE` | 8 |
| `CORRECT` | 44 |
| `REJECT` | 0 |
| **Tổng** | **60** |

Artifacts:

- [review input đã chuẩn hóa](../../configs/evaluation/semantic_parser_wave6_user_review_20260831_v1.json)
- [reviewed queue](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/user_review_queue_reviewed.jsonl)
- [review summary](../../artifacts/runs/evaluation/semantic-parser-wave6-model-draft-20260831-v4/user_review_summary.json)
- [machine-readable provenance](../../provenance/semantic_parser/semantic_parser_wave6_user_review_checkpoint.json)

## 2. So sánh với model draft

| Model status | User decision | Số QID |
| --- | --- | ---: |
| `OK` | `ACCEPT` | 8 |
| `OK` | `CORRECT` | 8 |
| `UNRESOLVED` | `ACCEPT_PENDING_SOURCE` | 8 |
| `UNRESOLVED` | `CORRECT` | 36 |

Trong 16 draft model từng qua structural gate, 8 được chấp nhận và 8 cần sửa. Agreement
một reviewer trên nhóm này là `8/16 = 50%`. Đây không phải accuracy vì chưa có independent
gold và chưa kiểm source evidence.

Tám `ACCEPT_PENDING_SOURCE` đều thuộc nhóm model `UNRESOLVED`: review đã nêu semantic
structure hợp lý nhưng chưa có model AST hợp lệ và chưa xác nhận source-label mapping.

## 3. Những gì review đã và chưa hoàn thành

Đã hoàn thành:

- quyết định semantic triage cho 60/60 QID;
- mô tả cấu trúc ngữ nghĩa đúng cho từng QID;
- mô tả lỗi chính cho từng QID;
- exact QID-set validation và machine-readable normalization.

Chưa hoàn thành:

- source evidence: 0/60;
- full corrected `CompositionFrame`/`QuestionAST`: 0/44 correction;
- full AST cho 8 accepted proposals mà model đã unresolved;
- independent annotator A/B và adjudicator C;
- runtime differential và holdout accuracy.

Vì vậy `corrected_annotation` được giữ `null`; importer không tự suy AST từ prose.

## 4. Hướng sửa hệ thống rút ra từ review

Ưu tiên tiếp theo không phải sửa từng QID trong runtime. Các pattern cần giải quyết theo lớp:

1. **Nested composition:** biểu diễn đúng `filter → derive → aggregate/rank`, đặc biệt điều
   kiện nhiều kỳ và predicate kết hợp AND.
2. **Aggregation domain:** tính ratio cho từng entity/kỳ trước, sau đó mới sum/average trên
   đúng entity hoặc period domain.
3. **Axis semantics:** phân biệt phép trừ giữa hai doanh nghiệp với chênh lệch theo thời gian;
   khóa `closing/opening/current/prior` thay vì suy thành Q1/Q4.
4. **Reported versus derived metrics:** không biến `equity_ratio_average` hoặc composite ratio
   thành một chỉ tiêu báo cáo có sẵn.
5. **Basis and output discipline:** không tự thêm `hợp nhất`; không suy output cardinality từ
   family; giữ unit và điểm phần trăm đúng operation.
6. **Source resolution:** audit riêng 8 `ACCEPT_PENDING_SOURCE` trước khi dựng full AST.

## 5. Gate còn lại

| Gate | Trạng thái |
| --- | --- |
| Single user semantic review | PASS, 60/60 |
| Source evidence | BLOCKED, 0/60 |
| Full corrected annotations | BLOCKED, 44 corrections + 8 proposals thiếu AST |
| Independent A/B/C | BLOCKED, 0/60 mỗi vai trò |
| Runtime promotion | BLOCKED |
| Submission candidate | NOT BUILT |

Review này là bằng chứng chẩn đoán rất có giá trị và đã chỉ ra structural validator hiện tại
chưa đủ precision. Tuy nhiên, nó chưa cấp quyền dùng review prose làm runtime truth. Bước an
toàn tiếp theo là chuyển 40 development records thành full CompositionFrame/AST. Hai mươi
QID holdout cũ đã xuất hiện trong review này nên được hạ thành exposed diagnostic, không còn
đủ độc lập để promotion. Holdout v2 mới gồm 20 QID chưa có nhãn, legacy-overlap 0 và
review-overlap 0; chỉ được mở sau khi code/config freeze.
