# Grounded V5 — root cause, rearchitecture và release evidence

Ngày chốt phân tích: 2026-08-30  
Phạm vi: `refs/prediction_result`, `refs/scoring_result`, `refs/prediction_result 2`,
`refs/scoring_result 2`, active raw/A6/retrieval snapshot và production source.

## 1. Kết luận điều hành

Điểm thấp không đến từ một lỗi riêng lẻ. Có ba bottleneck độc lập:

1. V4 thu hẹp scorer references quá mạnh. Precision tăng nhẹ nhưng recall bảng và
   tài liệu giảm sâu.
2. Decision core vẫn trả nhiều query chạy được nhưng sai semantic binding. Submission
   mới có 604 query executable, trong đó official chỉ công nhận 282 câu đúng; 322
   query chạy đúng cú pháp nhưng sai metric/period/basis/formula.
3. A6 chưa phải financial fact graph hoàn chỉnh. Duplicate axis, comparative-period,
   fiscal year, statement basis, unknown scale và note-table collisions vẫn truyền
   ambiguity lên retrieval và binder.

V5 đã thay decision core bằng pipeline typed, corpus-grounded và fail-closed. Full
preflight hiện recover 95 abstention, chỉ replace 2 seed có canonical evidence đủ
tin cậy, validation bằng 0 và replay 731/731. Đây là cải thiện kiến trúc thực, không
có QID override, answer hardcode hay đọc gold khi inference.

Tuy nhiên chưa có cơ sở trung thực để cam kết official Answer/Execution Accuracy
`>= 0.5`. Local answer gold chỉ có 31 câu và không đại diện toàn bộ 1.012 câu.

## 2. Official score: thay đổi và nguyên nhân

| Metric | Submission cũ | Submission V4 | Delta |
|---|---:|---:|---:|
| Tables F2 macro | 0.3151 | 0.2511 | -0.0640 |
| Tables precision | 0.2797 | 0.2904 | +0.0107 |
| Tables recall | 0.3571 | 0.2475 | **-0.1096** |
| Tables MRR@5 | 0.3939 | 0.3375 | -0.0564 |
| Docs F2 macro | 0.7361 | 0.6321 | -0.1040 |
| Docs precision | 0.6534 | 0.6877 | +0.0343 |
| Docs recall | 0.7952 | 0.6253 | **-0.1699** |
| Docs MRR@5 | 0.8162 | 0.7650 | -0.0512 |
| Answer accuracy | 0.2688 | 0.2787 | +0.0099 |
| Execution accuracy | 0.2688 | 0.2787 | +0.0099 |

Reference cardinality giải thích trực tiếp pattern trên:

| Submission | Executable | Mean tables | Mean docs |
|---|---:|---:|---:|
| Cũ | 606 | 4.916 | 3.622 |
| V4 | 604 | 2.579 | 2.342 |

V4 giảm gần một nửa số table refs và hơn một phần ba doc refs. Precision tăng đúng
như dự kiến, nhưng F2 ưu tiên recall nên tổng điểm giảm mạnh. Đây là regression
policy, không phải regression packaging.

Answer accuracy V4 tăng 10 câu, nhưng executable giảm 2 câu. Điều này chứng minh
việc “chạy được” không phải accuracy: 604 executable - 282 correct = **322 emitted
answers sai**. Muốn đạt 0.5 cần ít nhất 506 câu đúng, tức tăng ròng 224 câu so với
282; chỉ cứu abstention là chưa đủ, còn phải sửa một phần lớn nhóm đang trả sai.

## 3. Root cause theo tầng

### 3.1 Data/A6

- Một entity-period-metric có thể còn nhiều observation cạnh tranh từ current,
  comparative, restated hoặc nhiều report-year khác nhau.
- Fiscal-year labels không đồng nhất. Ví dụ báo cáo năm tài chính kết thúc tháng 9
  có thể bị chuẩn hóa về calendar year nếu chỉ nhìn document year.
- Consolidated/separate/unspecified từng được xếp hạng độc lập theo operand, tạo
  phép tính trộn basis.
- Unit và scale còn bất định ở một số shares/note tables. Full preflight vẫn từ
  chối 8 trường hợp shares unknown scale.
- Report-note metrics chưa có canonical statement code nên lexical rows có thể
  đụng tên nhưng khác nghĩa hoặc khác scope.

Hệ quả: retrieval có thể đúng document nhưng chọn sai observation/table. Khoảng
cách official Docs F2 lớn hơn Tables F2 là bằng chứng phù hợp với lỗi row/table
resolution này.

### 3.2 Retrieval và scorer references

- Rank cũ tối ưu từng fact độc lập, chưa tối ưu bundle metric × entity × period ×
  basis.
- Dedup trước đây chưa giữ basis trong key, có thể loại observation đúng trước khi
  coherence được đánh giá.
- Answer refs và scorer refs bị coupling. Khi route đổi từ abstain sang executable,
  ref rộng có thể bị thay bằng bound-only ref hẹp, làm recall giảm dù answer tốt hơn.
- V4 áp pruning/cap quá mạnh, thể hiện bằng recall regression official nêu trên.

### 3.3 Query understanding và semantic planning

- Annotator operation đơn (`lookup`, `average`, `extremum`,...) không mô tả được
  nested programs như median-filter → temporal-change → cohort-average.
- Synonym “số ngày tồn kho” từng không kích hoạt prior-year expansion vì parser chỉ
  nhận đúng cụm “hàng tồn kho”. Kết quả là average inventory balance thiếu kỳ đầu.
- Comparator “lớn hơn” có thể là explicit threshold filter hoặc relative rank.
  Nếu không phân biệt context, formula role bị gán sai.
- Ratio phổ biến như current ratio, quick ratio, inventory days từng không có formula
  contract đầy đủ hoặc không được nối vào operation lineage.
- Period expansion dùng chung cho mọi metric khiến prior-year phục vụ average balance
  có thể vô tình đi vào gross-margin change.

### 3.4 Binding, execution và promotion

- Flat operation plan không biểu diễn cohort predicates, median, top-K, rolling
  operations, select-at-key và chained formulas.
- Chọn operands theo lexical score không đảm bảo cùng basis, đủ coverage hay cùng
  axis key.
- `replace_all` tăng coverage nhưng local proxy đã regression q213, q483, q688 và
  q709; do đó không đủ an toàn để submit.
- Local Qwen semantic fallback chưa đạt release quality: sample semantic-v5 có 0
  promotion trong 13 attempt đầu, chủ yếu do missing metric source, invented literal,
  unknown node hoặc basis mix. Release deterministic tắt fallback này.

## 4. Kiến trúc V5 đã triển khai

```text
Question
  -> Vietnamese annotation + canonical ontology/formula expansion
  -> coherent retrieval bundle (metric/entity/period/basis)
  -> deterministic vectorized composer
       -> typed DAG: facts/literal/arithmetic/temporal/filter/rank/select/aggregate
  -> context + formula-lineage + literal + basis validator
  -> Decimal executor
  -> restricted Pandas query compiler
  -> clean replay against packaged evidence CSV
  -> replace_trusted promotion policy
  -> immutable 1,012-record submission ZIP
```

Các thay đổi cốt lõi:

- Canonical query ontology cho formulas/aliases và formula roles filter/rank/output.
- Retrieval prior theo dimension, exact metric coverage và one-basis-per-entity.
- Typed temporal operators: growth/change/rolling average/rolling change/CAGR,
  earliest/latest, entity reducers và `drop_first_by_entity`.
- Vector operations cho median predicates, logical cohort, top/bottom K, filter,
  arg key và select-at-key.
- Inventory-days dùng average inventory × 365 / absolute COGS; prior-year chỉ là
  support period và bị loại khỏi requested gross-margin change.
- Scale support cho 0/3/6/9/11/12 và Decimal đến submission boundary.
- Optional model chỉ nhìn value-free metadata; không nhìn answer hoặc corpus value.
- Append-only plan cache, deterministic replay và fail-closed validation.
- `replace_trusted`: recovery được phép; replacement chỉ được phép với compositional
  DAG và toàn bộ facts có canonical statement code/approved exact label.
- Handoff tool hỗ trợ cả `artifacts/runs/answer` và `artifacts/runs/grounded-v5`,
  reject path traversal và ambiguous run ID.

## 5. Evidence hiện tại

Full preflight run:
`grounded-v5-deterministic-replace-trusted-full-20260829-r3-preflight`.

| Gate | Kết quả |
|---|---:|
| Questions | 1,012 |
| Seed executable | 636 |
| Attempted | 1,012 |
| Generated candidate plans | 575 |
| Recovered abstention | 95 |
| Trusted replacements | 2 |
| Final executable | 731 |
| ZIP validation errors | 0 |
| Fresh replay | 731/731 matched, 0 errors |

Local governed proxy (31 answer cases):

| Metric | Kết quả |
|---|---:|
| Answer accuracy | 0.9354839 (29/31) |
| Execution accuracy | 0.9354839 (29/31) |
| Tables F2 macro | 0.4807665 |
| Docs F2 macro | 0.7566814 |
| All 10 metrics vs prior trusted candidate | Non-regressing |

Proxy này là regression gate, không phải estimator đáng tin cậy cho hidden official
accuracy. Hai lỗi proxy còn lại là q366 và q410; không được dùng QID patch để xử lý.

Các case compositional thực được audit riêng và replay sạch:

- q373: `6.2268844277`
- q374: `-3.2956955249` điểm phần trăm
- q376: `61.6572822605%`

Release verification:

- CI offline: 2,282 passed, 42 skipped, 29 deselected.
- Materialized integration: 22 passed, 2,331 deselected.
- Ruff correctness gate: pass.
- Strict mypy trên 111 production source files: pass.
- Documentation links: 86 files, 0 broken links.
- Active snapshot lineage: raw 1,973 reports/1,012 questions, A6 build
  `c6887fb633374fad`, retrieval index `872ccb0dda9a2bb6`; toàn bộ gate pass.

## 6. Trần hiện tại và phần chưa thể hoàn tất

Nếu lấy official V4 282 câu đúng làm mốc, ngay cả khi cả 95 recovery mới đều đúng,
accuracy lý thuyết mới khoảng `(282 + 95) / 1012 = 0.3725`, chưa tính hai replacement.
Do đó V5 hiện tại **không thể được tuyên bố chắc chắn đạt 0.5** chỉ bằng coverage gain.

Các nhóm còn bị từ chối nhiều nhất trong full preflight:

| Nhóm | Số case |
|---|---:|
| Simple aggregate cần nhiều metric/composition | 72 |
| Direct change thiếu generalized multi-entity plan | 57 |
| Extremum/member/select-at-arg chưa có template đủ tin cậy | 55 |
| Lexical direct row cluster mơ hồ | 55 |
| Conditional/ranked simple question | 33 |
| Output dimension mismatch | 31 |
| Direct ratio chưa xác định đúng hai operands | 30 |
| Canonical metric coverage thiếu | 29 |

Những case này không nên giải bằng regex/QID patch. Cần phase tiếp theo:

1. Dựng A7 financial fact graph với unique logical fact key, explicit
   current/comparative/restated role, fiscal period, basis và unit provenance.
2. Tách hoàn toàn answer evidence khỏi scorer-reference policy; tối ưu table/doc
   candidates bằng independent calibrated ranker.
3. Thay deterministic template dispatch bằng generalized semantic IR compiler từ
   operation tree/operand specs; templates chỉ còn optimization, không là coverage
   boundary.
4. Tạo 200-300 labels stratified theo failure shape, giữ sealed test riêng; dùng để
   mở rộng trusted replacement thay vì dựa vào 31 proxy cases.
5. Sau mỗi phase chạy official/public submission A/B; local replay chỉ kiểm execution,
   không được diễn giải thành accuracy.

## 7. Release rule

Chỉ đóng gói run tạo từ clean Git commit, đúng 1.012 record, zero validation error,
zero replay mismatch. Semantic model fallback giữ disabled cho release này. Final
ZIP, source manifest và SHA-256 nằm trong immutable handoff directory do
`make submission-handoff` tạo; leaderboard upload vẫn là bước thủ công và kết quả
official phải được ghi lại riêng.
