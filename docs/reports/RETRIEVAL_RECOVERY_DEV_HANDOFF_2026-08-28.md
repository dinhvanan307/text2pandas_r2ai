# Retrieval Recovery — Dev Handoff

**Ngày:** 2026-08-28  
**Phạm vi:** Semantic V3 parser, ontology, fact-level retrieval, candidate contract và binding

## Vấn đề chính

- V2 tìm bảng tương đối tốt: candidate hit `95/95`, nhưng V3 không sử dụng ranking của V2 mà scan observation trực tiếp từ A6.
- Bottleneck lớn nhất vẫn là semantic:
  - `492/1.012` câu fail ở Parser/Ontology.
  - `217` câu fail ở Binding.
- Trong `106` câu `NO_CANDIDATES`, có `104` câu đã scan được dữ liệu đúng scope nhưng metric matcher reject toàn bộ. Nghĩa là bảng/dữ liệu đã có, nhưng row/fact linking chưa tốt.
- Metric matcher đang lỗi với punctuation và hierarchy. Ví dụ:
  - Alias: `tài sản ngắn hạn`.
  - Row: `TÀI SẢN NGẮN HẠN(100 = ...)`.
  - Bị reject vì matcher yêu cầu sau alias phải là khoảng trắng.
- Candidate hiện copy `metric_id` từ request, chưa lưu độc lập:
  - `source_metric_code`.
  - `matched_metric_id`.
  - `row_uid`.
  - Match method/features.
- Binder đã có beam search và margin nhưng chưa có confidence threshold được calibrate.

## Thứ tự xử lý đề xuất

### 1. P0 — Regression và measurement

- Thêm test trực tiếp cho Q464/Q508/Q586/Q783/Q792.
- Chuẩn hóa failure reason: `SCOPE_EMPTY`, `METRIC_REJECT_ALL`, `BINDING_TIE`...
- Đồng bộ `MAX_N`, CLI defaults và evaluation config.

### 2. P0 — Entity/Alias

- Fix lỗi YAML serialization tạo literal `...`.
- Bổ sung alias STB/EIB có provenance.

### 3. P1 — Fact-level retrieval

- Tạo `normalize_fact_label()` để xử lý punctuation, numbering, Roman prefix và formula suffix.
- Match theo row leaf, full hierarchy, section và statement type.
- Giữ negative constraints để tránh nhầm total/detail.
- Diagnostic hiện cho thấy fix deterministic này có thể rescue `47/203` empty operand requests.

### 4. P1 — Parser/Ontology

- Xử lý `198 METRIC_UNRESOLVED`.
- Review các reported metric dùng trong derived operations.
- Thay `mentions[-1]` bằng top-M metric hypotheses có semantic role: `filter`, `rank`, `selected`, `numerator`, `denominator`.
- Hoàn thiện `SelectAtArg`; Q508 không thể sửa chỉ bằng alias.

### 5. P1 — Candidate contract

- Bổ sung `row_uid`, nullable `source_metric_code`, `matched_metric_id`, `match_method`, `match_features`.
- Tách:
  - `hard_allowed_table_uids`.
  - `table_rank_priors`.
- V2 table rank chỉ được dùng làm soft prior, không làm whitelist.

### 6. P1 — Binding

- Calibrate score/margin theo operation family.
- Chỉ retry broader theo failure type; không relax entity/year/basis explicit.

## Chưa nên làm

- Chưa đưa BGE, ColBERT, cross-encoder hoặc Qwen vào default pipeline.
- Chưa tăng top-K mù để chữa `NO_CANDIDATES`.
- Chưa thiết kế lại AST/binder từ đầu vì các thành phần này đã tồn tại.
- Không hạ promotion gate `300 semantic + 300 evidence + 300 answer gold`.

## Kiến trúc mục tiêu

```text
Question
→ AST + top-M metric-role hypotheses
→ OperandRequest riêng cho từng metric/entity/period
→ deterministic fact retrieval
→ soft V2 table prior
→ joint binding
→ calibrated ANSWER | RETRY | ABSTAIN
→ typed execution + Pandas replay
→ evidence-grounded output
```

## Kết luận triển khai

Ưu tiên thực tế:

> Parser/Ontology → deterministic fact matcher → candidate identity → binder calibration → neural challenger.

