# DEEP AUDIT — QUESTION PARSER → RETRIEVAL IMPACT

**Ngày audit:** 2026-08-28  
**Repository:** `text2pandas`  
**HEAD:** `a2d3ef0308612f3025cf1a78c3d5bc470d0634f6`  
**Phạm vi:** phân tích parser câu hỏi và ảnh hưởng của parser lên table retrieval; không thay đổi production code  
**Đặc tả đối chiếu:** [Text2Pandas.docx](../competition/Text2Pandas.docx)  
**Báo cáo liên quan:** [TABLE_RETRIEVAL_F2_AUDIT_2026-08-28.md](./TABLE_RETRIEVAL_F2_AUDIT_2026-08-28.md)

## Executive Summary

### Kết luận bắt buộc

> **NO — parser hiện tại không phải là nguyên nhân chính đã được chứng minh khiến Tables F2-Macro xấp xỉ 0.25 đối với đường chạy Canonical V2 hiện tại.**  
> **UNKNOWN — chưa thể quy trách nhiệm nhân quả chính xác cho submission 3757**, vì repository không có đúng ZIP/manifest/receipt, hidden gold và official scorer của submission đó.

Kết luận này dựa trên các bằng chứng định lượng sau:

- Trên 95 câu có manual table gold, parser Canonical V2 đưa **toàn bộ 554/554 gold tables vào S1**, tương ứng 95/95 câu có ít nhất một gold candidate. Parser không gây candidate loss tại tầng S1 trên lát cắt đo được.
- Sau ranking, chỉ 86/95 câu còn gold trong top 10; theo dynamic output policy chỉ 50/95 câu còn ít nhất một gold table. Điểm rơi lớn nằm ở **ranking và chính sách số lượng bảng đầu ra**, sau khi parser đã hoàn thành entity/year filtering.
- Trên 31 câu answer gold có nguồn, `parse_intent` đạt entity exact 31/31. Year-set exact đạt 28/31; ba khác biệt đều liên quan miền thời gian so với kỳ kết quả được chọn, không thể coi cả ba là lỗi parser thuần túy.
- Lỗi có độ tin cậy cao nhất của parser Canonical V2 là **chỉ giữ hai đầu mút của khoảng năm**: 35/37 câu có biểu thức year range không chứa các năm ở giữa trong `Intent.years`. Tuy vậy, S1 lọc theo khoảng `min..max` nên lỗi này thường không làm mất candidate; nó chủ yếu ảnh hưởng policy `N` và biểu diễn operand.
- Counterfactual trên 6 câu legacy có table gold cho thấy sửa intent làm số gold table trong top-N tăng từ 6/22 lên 10/22 và macro F2 cục bộ tăng khoảng **+0.0698**, nhưng không đổi số câu có hit. Đây là lát cắt nhỏ, thiên lệch và không thể ngoại suy thành mức tăng official score.
- Semantic V3 có 385/1012 lỗi ở stage `PARSE`, nhưng đây là pipeline shadow, không phải đường chạy tạo canonical submission hiện tại. Nhiều lỗi là fail-closed do thiếu semantic coverage hoặc review gate, không phải lỗi tokenize/entity/year. V3 vì thế không thể giải thích trực tiếp submission 3757.

### Trả lời ngắn theo yêu cầu audit

| Câu hỏi | Trả lời |
|---|---|
| Parser hiện tại có phải nguyên nhân chính của Tables F2-Macro ≈ 0.25? | **NO đối với Canonical V2 hiện tại; UNKNOWN đối với attribution chính xác của submission 3757.** |
| Những câu nào bị ảnh hưởng rõ? | 35/37 câu có year range bị thiếu năm nội suy trong `Intent`; 12/31 câu answer-gold bị V3 chặn ở PARSE; 385/1012 câu V3 bị PARSE fail toàn corpus. |
| Retrieval loss do parser là bao nhiêu? | Canonical: **0/95 câu mất candidate ở S1** trên manual slice; official corpus: **NOT MEASURED**. V3: parse fail làm 385 câu không có retrieval, nhưng V3 không phải production path. |
| Defect parser quan trọng nhất? | Với V3: thiếu coverage cho composition/operand/selector AST. Với Canonical V2: year-range chỉ giữ endpoints là defect nhỏ nhưng chắc chắn nhất. |
| Nên làm gì trước submission? | **Không rewrite parser.** Nếu chỉ sửa parser, chỉ cân nhắc patch nhỏ cho year-range hoặc tách output `N` khỏi số năm đã parse, kèm paired regression. Ưu tiên chính vẫn là table ranking, output policy và evidence binding. |

### Mức độ bằng chứng

- **MEASURED:** tính trực tiếp từ artifact/repository hiện tại.
- **DIAGNOSTIC:** đo được nhưng gold nhỏ, cũ, thiên lệch hoặc không độc lập; chỉ dùng định hướng.
- **NOT MEASURED:** không có đúng artifact/gold/scorer để định lượng.

## 1. Current Parser Architecture

Repository hiện có hai kiến trúc parser khác nhau. Chúng phải được phân biệt khi kết luận nguyên nhân.

### 1.1 Canonical V2 — đường chạy production hiện tại

```text
question
  │
  ├─ parse_intent(question)
  │    └─ Intent: entity/ticker, year, basis, mode, subject
  │
  ├─ S1 hard filter
  │    └─ ticker + year range/slack + optional basis + retrieval_ready
  │
  ├─ S2 lexical ranking
  │    └─ raw question terms + limited metric/unit/period/basis bonuses
  │
  ├─ QuestionSelector / specialized routes
  │    └─ independently infer row, section, context and operation cues
  │
  ├─ answer/evidence binding
  │    └─ successful answers may replace top-N retrieval refs
  │
  └─ submission adapter
       └─ N = clamp(number_of_targets × number_of_years, 1, max)
```

Đường CLI production gọi `run_canonical_pipeline`; `parse_intent` được gọi trong canonical runner và thêm một lần trong submission adapter. Parser này là đối tượng chính khi đánh giá submission Canonical V2.

Điểm kiến trúc quan trọng: `Intent` chỉ biểu diễn entity, year, basis và mode. Nó **không có** metric, unit, operation, operand, selector, row label hay column label. Semantic retrieval vì vậy vẫn phụ thuộc mạnh vào raw question và các recognizer downstream.

### 1.2 Semantic V3 — shadow pipeline

```text
question
  │
  ├─ LegacyVietnameseAnnotator
  │    └─ entities, periods, basis, unit, operation, mode, rank cues
  │
  ├─ ontology / metric resolution
  │
  ├─ AST compiler + validator
  │    └─ MetricRef / Arithmetic / Aggregate / Filter / Rank / SelectAtArg...
  │
  ├─ planner
  │    └─ OperandRequest per entity × period × metric
  │
  ├─ operand retrieval → binding → typed execute
  │
  └─ pandas compile/replay → evidence refs
```

V3 có contract semantic đầy đủ hơn nhưng fail-closed. Nếu AST không hợp lệ, pipeline dừng trước retrieval. CLI hiện gọi V3 theo chế độ shadow, còn production `cmd_run` vẫn đi Canonical V2.

### 1.3 Kiến trúc legacy không còn là current path

`domain/rules/question.py` chứa `QuestionSlots` cũ với tickers, years, basis, unit exponent và percent cue. `application/usecases/run_pipeline.py` còn dùng contract này, nhưng current CLI không dùng nó để tạo canonical run.

Một sibling checkout `text2pandas-release-6a12c33` có cùng HEAD và cùng hash parser, do đó không tạo được đối chứng “old parser project” độc lập.

## 2. Parser Output Contract

### 2.1 Canonical V2 `Intent`

| Field | Ý nghĩa | Có dùng trực tiếp trong retrieval? | Hạn chế |
|---|---|---:|---|
| `tickers` | Tập mã doanh nghiệp đã resolve | Có, S1 hard filter | Không mang confidence hoặc span nguồn |
| `explicit_scope` | Scope được nêu trực tiếp | Có gián tiếp | Không thay thế full semantic scope |
| `years` | Các năm nhận diện được | Có, S1 và output policy | Range thường chỉ có endpoints |
| `resolved_by` | ticker/company/ticker-and-name | Trace/diagnostic | Không phải confidence score |
| `mode` | single/related/screen/compare | Có trong policy/routing | Không diễn tả phép toán đầy đủ |
| `subject` | Chủ đề câu hỏi | Có giới hạn | Không phải ontology metric ID |
| `ticker_order` | Thứ tự entities | Có ích cho compare/select | Không chứa vai trò operand |

Properties bổ sung gồm `ordered_tickers`, `basis`, `answer_basis`, `targets` và `is_resolved`. Basis mặc định là consolidated, trong khi `answer_basis` chỉ giữ basis nếu câu hỏi nêu rõ.

### 2.2 Semantic frame, IR và answer contract của V2

`QuestionSemanticFrame` chứa entity đơn, `metric_id`, periods, basis, requested dimension/unit, operation và missing fields. Tuy nhiên parser frame không tự resolve metric; trace thực tế có thể chứa `metric_id: null` và `missing: ["metric_id"]` trong khi `QuestionSelector` vẫn bind đúng bảng từ raw text.

`OperandSlot` trong IR có role, metric, period, basis và entity. Generic router hiện dùng cùng một `metric_id` cho các slot, nên không biểu diễn tốt ratio/subtraction giữa hai metric khác nhau, select-at-arg hoặc filter phức tạp. `QuestionSemanticFrameV2` có per-operand semantics mới chỉ là spec, chưa được wire vào production.

`AnswerSpec` chứa value kind, unit exponent/label, arity, evidence và flags. Đây là contract của answer layer, không phải query contract của retrieval.

### 2.3 Semantic V3 contract

| Tầng | Contract chính | Nội dung |
|---|---|---|
| Annotation | `QuestionAnnotations` | entities, periods, basis, requested unit, operation, mode, rank direction, return mode, reverse/absolute difference, evidence |
| Metric resolution | `MetricHypothesis`, `MetricResolutionResult` | metric candidates, evidence, resolution status |
| AST | `QuestionAST` và nodes | metric refs, arithmetic, aggregate, comparison, predicate, filter, rank, select-at-arg |
| Planning | `OperandRequest` | metric, entity, period, basis, statement types, unit, semantics, qualifiers, consumers, context/source binding |

AST hỗ trợ round-trip JSON qua `to_dict`/`from_dict`. Planner tạo operand requests trên tích entity × period. Retrieval V3 hard-filter entity/period/explicit basis rồi xếp hạng theo metric/source label và unit dimension.

### 2.4 Khoảng trống contract quan trọng

Canonical V2 không có một parser output thống nhất nối trực tiếp câu hỏi với tất cả điều kiện retrieval. Thực tế có ba nguồn semantic song song:

1. `Intent` cho S1 và output policy.
2. Raw lexical terms/metric hints cho S2.
3. `QuestionSelector` và specialized routes cho row/section/operation/evidence.

Vì vậy, “parser đúng/sai” không đồng nghĩa trực tiếp với “retrieval đúng/sai”; một parser field thiếu có thể được downstream bù, và một intent đúng vẫn có thể bị ranking hoặc binding làm mất gold.

## 3. Parser Error Taxonomy

| Nhóm lỗi | Ví dụ | Ảnh hưởng dự kiến | Pipeline |
|---|---|---|---|
| Entity resolution | bỏ sót ticker/company, alias sai, substring collision | Mất toàn bộ candidate của entity | V2/V3 |
| Period extraction | thiếu năm, hiểu sai fiscal year, range chỉ endpoints | Mất candidate, sai operand hoặc sai output `N` | V2/V3 |
| Basis | consolidated/separate không đúng hoặc default không phù hợp | Chọn sai statement/table | V2/V3 |
| Metric resolution | không có metric ID, ambiguous/reject-all | Ranking yếu hoặc parse/bind fail | V2/V3 |
| Unit semantics | money/percent/count/ratio không đúng | Chọn sai row/table hoặc reject binding | V2/V3 |
| Operation | lookup/ratio/difference/growth/aggregate sai | Sai routing, AST hoặc operand structure | V2/V3 |
| Operand role | không biết tử/mẫu, selected/ranking expression | Không thể lập AST/planner đúng | Chủ yếu V3 |
| Selector/composition | filter, rank, select-at-arg chưa resolve | Parse fail trước retrieval | V3 |
| Normalization | accent-aware stop words/alias normalization | Thay đổi lexical ranking | S2, không phải core parser |
| Trace observability | trace không serialize đủ annotation | Khó audit, không nhất thiết sai runtime | V3 |
| Policy coupling | `N` phụ thuộc số targets × years | Intent chưa đủ làm rơi gold ở serialization | V2 |

Phân biệt bắt buộc:

- **Lỗi nhận diện:** parser đọc sai nội dung câu hỏi.
- **Lỗi coverage/policy:** hệ thống hiểu cue nhưng chủ động fail-closed vì chưa có rule hoặc chưa review công thức.
- **Lỗi retrieval/ranking:** gold còn trong candidate pool nhưng bị xếp thấp.
- **Lỗi binding/serialization:** retrieval có candidate nhưng table refs cuối bị thay hoặc cắt.

## 4. Parser Error Measurement

### 4.1 Full-corpus lexical coverage của Canonical V2

Trên 1,012 câu:

| Chỉ số | Kết quả |
|---|---:|
| Có ít nhất một entity | 1,011/1,012 |
| Có ít nhất một year | 1,011/1,012 |
| Có cả entity và year | 1,010/1,012 |
| Single-entity | 724 |
| Multi-entity | 287 |
| Mode single / related / screen / compare / screen_open | 724 / 59 / 162 / 66 / 1 |

Phân bố lexical operations là LOOKUP 413, EXTREMUM 242, COUNT 26, AVG 98, DIVIDE 54, SUBTRACT 138, GROWTH 37 và SUM 4. Phân bố units là MONEY 628, PERCENT 219, SHARES 12, RATIO 47, COUNT 22, PERCENT_POINT 22 và UNKNOWN 62.

Đây là coverage, không phải accuracy, do toàn bộ 1,012 câu không có blind human parser gold.

### 4.2 Answer-gold slice: 31 câu có nguồn

| Field | Kết quả | Đánh giá |
|---|---:|---|
| Entity exact | 31/31 | MEASURED trên lát cắt nhỏ |
| Year set exact | 28/31 | DIAGNOSTIC; khác biệt q378/q485/q528 liên quan domain vs selected output period |
| Operation exact, bỏ `multi` | 18/19 | q708 ratio bị gọi LOOKUP |
| Unit exact theo coarse answer gold | 23/30 | DIAGNOSTIC; taxonomy hai phía không hoàn toàn đồng nhất |

Không chấm basis bằng answer gold vì basis ở gold là basis của source/evidence, không nhất thiết là semantic basis người dùng yêu cầu.

### 4.3 Year-range defect

Corpus có 37 câu chứa biểu thức khoảng năm; 35/37 câu bị thiếu ít nhất một năm nội suy trong `parse_intent`. Tỷ lệ bề mặt là **94.59%**.

Ví dụ kỳ vọng `2019–2023` có thể được lưu thành `{2019, 2023}`. Tuy nhiên S1 dùng khoảng từ năm nhỏ nhất đến lớn nhất cộng slack nên các năm ở giữa vẫn có thể vào candidate pool. Defect này dễ ảnh hưởng:

- số lượng bảng được xuất vì `N` dùng `n_targets × n_years`;
- số operand/kỳ cần xử lý;
- phân biệt domain periods và selected output period.

Corpus hiện có 0 câu quarter, 0 câu 6/9-month, 10 fiscal-year, 22 opening và 429 closing. Do đó thiếu representation quarter chưa có observed impact trên dataset hiện tại. Opening/closing được `QuestionSelector` xử lý ở tầng sau, không nằm trong `Intent`.

### 4.4 Semantic parser gold governance

Semantic gold registry có 40 câu nhưng chỉ 6 câu usable cho promotion; independence được đánh giá `NONE`. Trong 40 rows có 30 `UNRESOLVED`, 6 `RESOLVED`, 4 `AMBIGUOUS`; provenance gồm 3 `LOCATED`, 7 `NOT_LOCATED`, 30 `NOT_ATTEMPTED`.

Existing parser-vs-gold summary thực chất đánh giá lexical frame V2, không phải current `parse_intent` contract hoặc V3 AST:

- basis 40/40;
- entity 39/40;
- operation 40/40;
- periods 29/29;
- result kind 40/40;
- unit 40/40;
- metric exact và operand-role exact: **NOT MEASURED**;
- annotator agreement cho metric 0.175, operand role 0.250, operand-role-metric 0.150.

Mismatch entity q4 của evaluator đến từ uppercase token `FPT`; current retrieval parser thực tế resolve đúng FTS từ tên pháp lý đầy đủ. Đây là bằng chứng rằng benchmark lexical cũ không thể thay thế audit current parser.

### 4.5 Semantic V3 operational failures

Run `metric-unresolved-candidate-v1-20260828`:

| Stage cuối | Số câu |
|---|---:|
| OK | 362 |
| PARSE | 385 |
| BIND | 226 |
| TYPED_EXECUTE | 38 |
| PANDAS_COMPILE | 1 |
| Tổng abstain | 650 |

Top PARSE reasons:

| Reason | Số câu |
|---|---:|
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 162 |
| `METRIC_SOURCE_SPECIFICITY_REQUIRED` | 47 |
| `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED` | 40 |
| `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | 21 |
| `BINARY_OPERANDS_UNRESOLVED` | 20 |
| `UNREVIEWED_RELATIONAL_FORMULA` | 15 |
| `SELECT_AT_ARG_RANK_FORMULA_UNRESOLVED` | 14 |
| `COUNT_PREDICATE_REQUIRED` | 11 |
| `AGGREGATE_AXIS_UNRESOLVED` | 11 |
| `METRIC_HYPOTHESES_AMBIGUOUS` | 10 |
| `LOOKUP_SCOPE_NON_SCALAR` | 8 |
| `QUESTION_MENTION_NO_MAPPING` | 4 |

Các lỗi này là operational parse-to-AST failures. Nhiều reason là review/coverage gate có chủ đích, không đủ bằng chứng để gắn nhãn “lexical parser hiểu sai”.

Tỷ lệ PARSE fail theo operation annotation:

| Operation | Tổng | PARSE fail | Tỷ lệ |
|---|---:|---:|---:|
| lookup | 393 | 36 | 9.16% |
| divide | 49 | 30 | 61.22% |
| subtract | 131 | 106 | 80.92% |
| growth | 37 | 27 | 72.97% |
| sum | 37 | 21 | 56.76% |
| average | 97 | 49 | 50.52% |
| count | 26 | 18 | 69.23% |
| extremum | 242 | 98 | 40.50% |

## 5. Parser → Retrieval Dependency

### 5.1 Canonical V2 dependency

| Parser field | S1 | S2 | Output/binding |
|---|---:|---:|---:|
| Entity/ticker | Hard filter | Context | Tăng `N` theo targets |
| Years | Range/slack filter | Period bonus | Tăng `N` theo số years |
| Basis | Optional hard filter | Basis bonus | Có thể chi phối source |
| Mode/scope | Giới hạn | Query behavior | Routing/policy |
| Metric | Không có trong `Intent` | Raw lexical hint | Selector tự suy luận |
| Unit | Không có trong `Intent` | Limited hint | Selector/answer layer |
| Operation/operands | Không đầy đủ | Raw lexical | Specialized routes |

Canonical retrieval không phụ thuộc vào một AST semantic duy nhất. Điều này làm parser errors có thể được downstream bù, nhưng cũng làm khó truy vết causal attribution.

### 5.2 Semantic V3 dependency

V3 có dependency chặt hơn:

```text
PARSE fail → không có AST → không có plan → không có operand retrieval → table refs rỗng
```

Vì vậy 385 PARSE failures là bottleneck vận hành thật đối với V3. Tuy nhiên đây không phải evidence rằng parser đã gây Tables F2 ≈ 0.25 cho submission 3757, vì V3 shadow không tạo canonical submission hiện tại.

### 5.3 Retrieval, answer binding và table refs cuối

Ở Canonical V2, khi answer thành công, runner có thể thay top-N retrieval refs bằng exact bound evidence tables. Do đó table score cuối là kết quả hỗn hợp của:

1. parser/S1 candidate generation;
2. S2 ranking;
3. output `N` policy;
4. question routing và table/row binding;
5. evidence replacement và serialization.

Không thể quy toàn bộ table miss cuối cho parser nếu chưa tách từng tầng.

## 6. Per-question Failure Analysis

### 6.1 Năm ca semantic/retrieval thành công

| QID | Kỳ vọng | Parser/AST | Kết quả |
|---:|---|---|---|
| 52 | NAB, 2024-12-31, lookup, triệu | V3 annotation đúng entity/year/operation; AST `metric_ref` | V3 và Canonical cùng chạm exact gold `NAB...|1539` |
| 77 | VRE separate, 2024, lookup | Basis/entity/year được giữ đúng | Cả hai chạm exact gold `VRE...|236` |
| 359 | VIB, 2024, lookup | V3 semantic parse thành công | V3 chạm `VIB...2024|264`; Canonical dẫn `2025|269`, cho thấy downstream miss dù parser cue đơn giản |
| 410 | HPG/HSG/NKG, 2024, extremum aggregate | V3 tạo aggregate AST | V3 lấy 4/5 unique gold refs; Canonical chỉ 1 |
| 506 | 5 entities, 2024, select-at-arg | V3 tạo `select_at_arg` AST | V3 chạm đủ 6 unique gold refs; Canonical miss |

Các ca q410 và q506 cho thấy structured AST có thể giúp multi-entity composition. q359 cho thấy parser/semantic success chưa đảm bảo Canonical downstream chọn đúng table.

### 6.2 Mười ca V3 dừng ở PARSE trên answer-gold slice

| QID | Reason | Annotation quan sát được | Ảnh hưởng | Canonical có table hit? |
|---:|---|---|---|---:|
| 378 | `FILTER_PREDICATE_REQUIRED` | Entity/year/domain nhận diện được | Không có AST/refs V3 | 1 |
| 382 | `SELECT_AT_ARG_SUPERLATIVE_UNRESOLVED` | Multi-entity + superlative cue | Không resolve selector | 2 |
| 398 | `SELECT_AT_ARG_RANK_FORMULA_UNRESOLVED` | Rank cue có mặt | Không resolve rank formula | 0 |
| 421 | `LOOKUP_SCOPE_NON_SCALAR` | Bị annotation thành lookup | Scope thực tế không scalar | 0 |
| 477 | `SELECT_AT_ARG_RANK_FORMULA_UNRESOLVED` | Rank cue có mặt | Không resolve rank formula | 1 |
| 485 | `FILTER_VALUE_UNIT_MISMATCH` | Entity/year được nhận diện | Predicate/unit không tương thích | 1 |
| 528 | `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED` | Entity/year được nhận diện | Không resolve selected expression | 1 |
| 543 | `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | Rank cue có mặt | Không resolve ranking expression | 0 |
| 556 | `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | Rank cue có mặt | Không resolve ranking expression | 0 |
| 709 | `UNREVIEWED_RELATIONAL_FORMULA` | Relational operation được phát hiện | Bị review gate chặn | 2 |

Bảy trong 12 V3 PARSE failures của toàn bộ 31-câu slice vẫn có ít nhất một gold table qua Canonical V2. Điều này cho thấy một đường retrieval ít semantic hơn có thể cứu candidate, nhưng không chứng minh rằng chỉ sửa parser V3 sẽ đảm bảo exact evidence.

### 6.3 Mười retrieval failures không thể quy trực tiếp cho parser

Chín ca manual gold sau có **toàn bộ gold trong S1**, nhưng không có gold ở top 10:

| QID | Parsed scope | S1 candidates | Gold tables | Gold ranks quan sát |
|---:|---|---:|---:|---|
| 374 | HPG/HSG/MSR/NKG; 2022, 2024; screen | 2,080 | 16 | 11, 13, 15, 19, 21, 24, 25, 35, ... |
| 376 | 7 entities; 2024; screen | 2,084 | 14 | 12, 35, ... |
| 385 | 5 entities; 2023, 2024; screen | 2,052 | 20 | Không có gold trong top 50 |
| 397 | 8 entities; 2024; screen | 2,663 | 16 | Không có gold trong top 50 |
| 436 | 6 entities; 2023; screen | 1,905 | 6 | 14, ... |
| 542 | DCM/DPM/GVR; 2021, 2022; screen | 1,156 | 6 | Không có gold trong top 50 |
| 723 | HAG; 2018; single | 340 | 1 | 12 |
| 767 | DLG/ACV; 2015; compare separate | 467 | 2 | 19, 27 |
| 975 | MCH/MSN/VNM/ASM; 2024; related | 1,406 | 4 | 16, 19, 30, 36 |

Năm ví dụ rõ nhất của “parser fields đúng nhưng retrieval sai” là q374, q376, q436, q723 và q767: entity/year/mode có thể kiểm tra độc lập, gold sống sót qua S1, nhưng ranking không đưa gold vào top 10. Đây là lỗi phân hạng/candidate density, không phải candidate loss từ parser.

Ca thứ mười, q213, kỳ vọng ACV, 2018-12-31, lookup, million USD. Parser lấy ACV/2018/LOOKUP, nhưng Canonical dẫn `ACV_financial_statements_2019_separate|1271` thay vì gold `ACV_financial_statements_2018_consolidated|1297`. Root cause nằm ở basis/year/table ranking hoặc selection downstream, không phải entity/operation extraction.

## 7. Candidate Recall Impact

### 7.1 Manual table-gold slice 95 câu

| Metric | Kết quả |
|---|---:|
| Câu có ít nhất một gold trong S1 | 95/95 = 100% |
| Gold table items còn trong S1 | 554/554 = 100% |
| Câu có hit@1 | 33/95 = 34.74% |
| Câu có hit@5 | 80/95 = 84.21% |
| Câu có hit@10 | 86/95 = 90.53% |
| Câu có hit@20 | 92/95 = 96.84% |
| Câu có hit theo dynamic policy | 50/95 = 52.63% |

Gold-item recall lần lượt là 18.18% ở top 1, 56.64% ở top 5, 71.17% ở top 10 và 79.56% ở top 20.

Kết luận đo được: **parser-caused S1 candidate loss = 0/95 câu và 0/554 gold items trên lát cắt này**. Sau đó có 9/95 top-10 question misses và 45/95 dynamic-policy misses. Parser accuracy trên 917 câu còn lại vẫn **NOT MEASURED**.

### 7.2 Phân tích theo question type

| Type | Câu | S1 any-hit | Hit@10 | Dynamic-policy hit | Gold items | Gold@10 |
|---|---:|---:|---:|---:|---:|---:|
| AGGREGATION | 10 | 10 | 10 | 6 | 120 | 32 |
| COMPARE/DIFFERENCE | 15 | 15 | 14 | 14 | 32 | 25 |
| COUNT | 5 | 5 | 5 | — | 62 | 17 |
| LOOKUP | 36 | 36 | 36 | — | 75 | 44 |
| PERCENTAGE_CHANGE | 2 | 2 | 2 | — | 4 | 4 |
| RANK/FILTER | 21 | 21 | 18 | — | 240 | 72 |
| RATIO | 6 | 6 | 5 | — | 21 | 8 |

LOOKUP đạt 36/36 question hit@10 trên manual slice. Các nhóm aggregation/rank/filter có nhiều gold tables và candidate density cao, nên item recall thấp dù entity/year candidate generation đúng.

### 7.3 Final scorer-facing refs trên 31 answer-gold questions

| Pipeline | Câu có exact table hit | Gold table-item hits | Empty output |
|---|---:|---:|---:|
| Canonical V2 | 17/31 = 54.84% | 23/123 = 18.70% | 0 |
| Semantic V3 | 7/31 = 22.58% | 15/123 = 12.20% | 19 |

V3 breakdown: 12 PARSE fail, 5 BIND fail, 2 TYPED_EXECUTE fail và 12 OK; trong 12 OK có 7 câu hit, 5 câu vẫn miss. Parser success vì thế chưa đủ để bảo đảm table evidence success.

## 8. Counterfactual Analysis

### 8.1 Current intent so với corrected intent trên 12 legacy cases

`gold_entity_override_v1.json` chứa 12 corrections lịch sử. Current code đã sửa phần lớn RC-1/RC-2/RC-3, nên override là artifact cũ và chỉ dùng làm stress test. Audit chạy actual và corrected intents trên cùng current DB, S1 và S2 top 300.

Chỉ 6/12 câu có legacy table gold mappable: q425, q542, q767, q774, q790, q791; tổng 22 gold tables.

| Chỉ số trên 6 câu | Actual | Corrected |
|---|---:|---:|
| Câu có any gold trong S1 | 6/6 | 6/6 |
| Gold tables trong S1 | 22/22 | 22/22 |
| Câu có any gold trong top 300 | 6/6 | 6/6 |
| Gold tables trong top 300 | 22/22 | 22/22 |
| Câu có any gold theo top-N policy | 3/6 | 3/6 |
| Gold tables trong top-N | 6/22 | 10/22 |
| Macro per-question F2 cục bộ | ≈0.2820 | ≈0.3517 |

Delta F2 cục bộ khoảng **+0.0698**. Toàn bộ gain 4 gold tables đến từ q425 vì `N` tăng 6→12 và hit tăng 2→6. Question-level hit không đổi. q542 có first-gold rank 77, q767 là 19, q774 là 7, q790 là 2 và q791 là 3.

Diễn giải: corrected intent có thể cải thiện **output policy**, nhưng không cải thiện candidate recall hoặc top-300 retrieval trên lát cắt này. Kết quả quá nhỏ và thiên lệch để dự đoán official score.

### 8.2 Gold-AST → V3 retrieval counterfactual

Counterfactual đầy đủ chưa thực hiện được vì:

- semantic parser gold chỉ có 6 rows usable;
- không có sealed, machine-compatible AST/evidence gold;
- gold không độc lập và metric/operand agreement thấp;
- không có official table gold/scorer.

Do đó số table misses có thể phục hồi nếu parser hoàn hảo là **NOT MEASURED**.

### 8.3 Counterfactual normalization

Default query stop mode là accent-fold. Sau current alias dropping, 559/1,012 câu có term list khác accent-aware mode; các token mất phổ biến gồm `tài`, `động`, `cổ`, `tư`, `sở`, `mã`, `trọng`.

Historical proxy A/B cho `stop_mode=dau` lại làm Hit@10 giảm từ 0.9162 xuống 0.9051 và F2@10 giảm từ 0.4764 xuống 0.4664, với 4 flip-ins và 15 flip-outs. Vì proxy không phải official gold, không nên đổi normalization ngay trước submission. Đây cũng là ranking preprocessing, không phải parser core.

## 9. Old vs New Parser Regression

### 9.1 Legacy `QuestionSlots` so với current `parse_intent`

Trên 1,012 câu:

| Chỉ số | Old | New/current |
|---|---:|---:|
| Entity resolved | 991 | 1,011 |
| Year resolved | 1,011 | 1,011 |
| Entity exact set agreement | \- | 948/1,012 |
| Year exact agreement | \- | 1,012/1,012 |
| Old empty → new nonempty | \- | 20 |
| Old nonempty → new empty | \- | 0 |
| Basis exact agreement | \- | 1,008/1,012 |

Old sources là literal 648, company 343, none 21. New `resolved_by` là ticker 576, company 411, ticker-and-name 24, none 1. Không có tín hiệu regression diện rộng ở entity/year coverage.

### 9.2 Historical paired retrieval run

`origin_main_before` so với current chỉ đổi targets ở 3 qids: 508, 783, 792, liên quan attested aliases STB/EIB.

Trên paired manual 95:

| Metric | Before | Current | Delta |
|---|---:|---:|---:|
| F2@10 | 0.3786125 | 0.3844605 | +0.005848 |
| Hit@10 | 0.894737 | 0.905263 | +0.010526 |
| Policy F2 | 0.303466 | 0.303466 | 0 |

Không có top-10 loss; q586 cải thiện first-gold rank từ 25 xuống 5. Đây là thay đổi alias/config artifact, không phải bằng chứng của parser rewrite.

### 9.3 Regression conclusion

Không phát hiện regression có hệ thống của current entity/year parser so với legacy. Ngược lại, entity resolution coverage tăng 20 câu mà không có câu chuyển từ resolved thành empty. Regression semantic đầy đủ vẫn không thể đo vì thiếu independent AST gold.

## 10. Root Causes

| Priority | Root cause | Evidence | Mức tin cậy | Có phải parser issue? |
|---|---|---|---|---|
| P0 | Table ranking và candidate density sau S1 | 554/554 gold trong S1, chỉ 202/554 ở top 10; 9/95 question misses | Cao trên manual slice | Không |
| P0 | Dynamic output `N` quá hẹp/coupled với intent | 95/95 S1 hit nhưng chỉ 50/95 policy hit | Cao trên manual slice | Mixed: policy dùng parser fields |
| P1 | Evidence binding/final ref replacement | Canonical chỉ 17/31 exact question hit; success path có thể thay refs | Trung bình | Không thuần parser |
| P1 | V3 thiếu composition/operand/selector AST coverage | 385 PARSE fail; subtract 80.92%, growth 72.97%, divide 61.22% | Cao cho V3 | Có, nhưng V3 shadow |
| P1 | Canonical V2 thiếu structured metric/operand contract | `Intent` không có metric/unit/operation; generic router không có per-operand metric | Cao về kiến trúc, impact chưa tách | Có |
| P1 | Year ranges chỉ giữ endpoints | 35/37 bề mặt; counterfactual ảnh hưởng `N` | Cao | Có |
| P2 | Unit/period-role semantics bị chia qua nhiều tầng | Contract phân mảnh, q485 unit mismatch | Trung bình | Mixed |
| P2 | V3 trace omit một số annotation fields khi fail | Trace thiếu requested unit/mode/rank/reverse difference | Cao | Observability, không runtime |
| NOT A PROBLEM | Current entity resolver trên các lát cắt đo được | 31/31 answer gold; 95/95 S1 hit; 1,011/1,012 coverage | Cao trong phạm vi đo | Không ưu tiên sửa |
| NOT A PROBLEM | Quarter parsing cho corpus hiện tại | 0 câu quarter/6-month/9-month | Cao | Không có observed impact |
| UNKNOWN | Exact cause của official submission 3757 | Không có exact ZIP/receipt/hidden gold/scorer | — | Không thể kết luận |

Root cause có bằng chứng mạnh nhất cho low table F2 của current canonical artifacts là: **ranking chưa phân biệt đủ bảng đúng trong candidate pool lớn, output policy cắt quá sớm, và evidence binding/serialization không bảo toàn đủ gold refs**.

## 11. Expected Score Impact

### 11.1 Những gì có thể định lượng

- Parser correction counterfactual trên 6 legacy-gold cases: macro per-question F2 tăng khoảng **+0.0698** và table hits tăng 6/22→10/22; question hit không đổi.
- Current manual 95 cho thấy S1 candidate recall đã đạt 100%, nên room chính nằm ở rank cutoff và output policy.
- V3 metric-recovery candidate tăng OK từ 287 lên 362, giảm abstain 725→650, tạo 75 new OK và 0 regression trong so sánh nội bộ. Run vẫn `NON-PROMOTABLE`.

### 11.2 Những gì không được phép ngoại suy

Không có cơ sở để nói “sửa parser sẽ tăng Tables F2 từ 0.25 lên X” vì:

- manual table gold chỉ phủ 95/1,012 = 9.387%; 
- answer gold chỉ có 31 usable source-grounded cases;
- parser gold chỉ có 6 usable và không độc lập;
- official hidden gold và scorer không có;
- exact artifact của submission 3757/3721 không có trong repo.

Vì vậy expected official score impact của parser-only change là **UNKNOWN**. Mọi con số khác chỉ là diagnostic local delta.

### 11.3 Đối chiếu official scores do người dùng cung cấp

| Submission | EA | Tables F2 | Tables P | Tables R | Tables MRR@5 | Docs F2 |
|---|---:|---:|---:|---:|---:|---:|
| 3757 | 0.2589 | 0.2500 | 0.2921 | 0.2461 | 0.3360 | 0.6326 |
| 3721 | 0.2549 | 0.2511 | 0.2904 | 0.2475 | 0.3375 | 0.6321 |

Chênh lệch Tables F2 chỉ -0.0011 trong khi EA tăng +0.0040. Không có provenance để gắn thay đổi này với parser. Canonical artifact hiện tại cũng chưa được chứng minh là ZIP đã upload.

V3 candidate chỉ có 362/1,012 non-empty outputs. Nếu toàn bộ 1,012 câu được chấm, trần recall theo số câu non-empty là 0.3577, thấp hơn official Docs recall 0.6257; đây là thêm một lý do V3 candidate khó có thể là submission 3757.

## 12. Recommendation Before Submission

### Quyết định

> **Không rewrite parser trước submission.**  
> Nếu buộc phải chọn một thay đổi parser, chọn **CHỈ SỬA MỘT PHẦN**: patch nhỏ, dễ rollback cho year-range expansion hoặc tách output `N` khỏi số endpoints đã parse; chỉ promote sau paired regression.

Thứ tự ưu tiên đề xuất:

1. **Freeze current entity resolution/alias behavior.** Các số đo hiện tại không cho thấy entity parser là bottleneck.
2. **Ưu tiên table reranking và output policy.** Đo recall theo nhiều cutoff, đặc biệt với screen/rank/aggregation có candidate pool lớn và nhiều gold tables.
3. **Audit evidence binding/final serialization.** So sánh S1, S2, selected tables và final refs trên cùng bộ gold để biết gold bị mất tại bước nào.
4. **Nếu có slot an toàn, sửa year-range nhỏ.** Expansion phải giữ compatibility với S1, operand semantics và policy; cần test trên 37 range questions và paired manual 95.
5. **Giữ Semantic V3 ở shadow.** Chưa promote cho đến khi composition/operand/selector coverage tăng và có tối thiểu khoảng 300 sealed, independently adjudicated semantic/evidence cases.
6. **Không đổi accent stop mode ngay trước submission.** Proxy A/B hiện cho tín hiệu xấu.

### Go/no-go cho parser change

| Lựa chọn | Khuyến nghị | Lý do |
|---|---|---|
| Rewrite parser/AST toàn diện | **NO-GO** | Blast radius cao, không có independent gold đủ lớn, chưa chứng minh là root cause official |
| Promote Semantic V3 | **NO-GO** | 650/1,012 abstain, 385 PARSE fail, candidate non-promotable |
| Patch range expansion nhỏ | **CONDITIONAL GO** | Defect rõ, chi phí thấp; phải qua paired no-regression và không tăng noisy output |
| Tối ưu reranking/output policy | **GO** | Bằng chứng trực tiếp nhất: gold còn trong S1 nhưng rơi ở ranking/cutoff |
| Tăng kiểm tra evidence binding | **GO** | Final table refs đang thấp hơn candidate availability đáng kể |

### Câu trả lời cuối cùng

- **Kết luận:** `NO` cho Canonical V2 hiện tại; attribution chính xác cho official submission 3757 là `UNKNOWN`.
- **Evidence:** manual 95 giữ 554/554 gold trong S1; entity exact 31/31 trên answer-gold slice; losses lớn xuất hiện sau candidate generation.
- **Affected questions:** 35/37 year-range surfaces có thiếu năm nội suy; 12/31 answer-gold cases bị V3 PARSE fail; 385/1,012 V3 cases fail ở PARSE.
- **Retrieval loss:** Canonical parser-caused S1 loss đo được là 0/95 câu; top-10 ranking miss là 9/95; dynamic-policy miss là 45/95. Official parser-caused loss là `NOT MEASURED`.
- **Most important defect:** V3 thiếu compositional operand/selector AST; với Canonical, year-range endpoints là defect parser chắc chắn nhất nhưng không phải bottleneck lớn nhất đã đo được.
- **Recommended action:** không rewrite; tối đa sửa range có kiểm soát, còn ngân sách submission nên dành cho ranking, output policy và exact evidence binding.

## 13. Appendix

### 13.1 Artifact inventory

| Artifact | Path / ID |
|---|---|
| Active raw snapshot | `ca033190f2e9e99f` |
| A6 version | `c6887fb633374fad` |
| Retrieval version | `872ccb0dda9a2bb6` |
| Active retrieval DB | `data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db` |
| Canonical run manifest | `artifacts/runs/answer/canonical-v2-a2d3ef030861-b-e2e-01/manifest.json` |
| Current submission ZIP | `artifacts/submissions/submission.zip` |
| V3 records | `artifacts/runs/semantic-v3/metric-unresolved-candidate-v1-20260828/records.jsonl` |
| Retrieval paired current | `artifacts/runs/retrieval/release-paired-20260828/current_after.jsonl` |
| Gold registry | `configs/evaluation/gold_registry_v1.yaml` |

Canonical run có 1,012 câu, 1,011 entity-resolved, 1,011 year-resolved, 1,011 non-empty retrievals, 563 answered và 449 abstain. Chỉ một record có `NO_RETRIEVED_TABLE`; abstain lớn nhất là `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` với 177 câu.

### 13.2 Checksums

| Artifact | SHA-256 |
|---|---|
| Questions | `64a428d...6ff0` |
| Semantic gold | `2d637d...425` |
| Parser summary | `2e45dbe...06d2` |
| Answer gold | `e14248...3e2` |
| Gold V2 | `0d40d66...7337` |
| Entity overrides | `4fc04c...83c` |
| Current paired retrieval | `9cecb8...522` |
| Origin paired retrieval | `022c62...8b6` |
| Paired comparison | `b07493...ee0` |
| V3 records | `b95a86...f51b` |
| V3 comparison | `93fddb...bd9` |
| Submission ZIP | `a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c` |

Rút gọn checksum bằng dấu `...` được dùng cho artifact phụ để báo cáo dễ đọc; submission ZIP giữ full checksum vì liên quan provenance.

### 13.3 Tests đã chạy

```bash
python -m pytest -q \
  tests/test_retrieval_r0_entity.py \
  tests/test_entity_resolution_trace.py \
  tests/test_semantic_gold.py \
  tests/unit/test_semantic_parser_v3.py \
  tests/unit/test_a6_metric_resolver_v3.py \
  tests/unit/test_operand_retrieval_v3.py
```

Kết quả xác minh cuối: **121 passed in 0.26s**.

### 13.4 Reproducibility notes

- Audit chỉ đọc source, artifacts, SQLite retrieval DB, manifests, JSON/JSONL/YAML và competition spec.
- Không thay đổi parser, retrieval, config hoặc submission artifact.
- Counterfactual actual/corrected dùng cùng current database và ranking implementation; chỉ thay intent đầu vào trong phiên đo.
- Không có exact upload receipt hoặc server-side evaluation trace cho submissions 3757/3721.
- Mọi kết luận vượt quá các lát cắt 95/31/6 câu được đánh dấu DIAGNOSTIC hoặc NOT MEASURED.

### 13.5 Source locations chính

- Canonical CLI: `src/text2pandas/interface/cli/main.py`
- Canonical runner: `src/text2pandas/application/canonical_run.py`
- Current intent parser: `src/text2pandas/domain/question_intent.py`
- S1 filter: `src/text2pandas/infrastructure/retrieval/filter_s1.py`
- S2/query terms: `src/text2pandas/evalkit/stages.py`, `src/text2pandas/infrastructure/retrieval/query_terms.py`
- Submission adapter: `src/text2pandas/application/submission_adapter.py`
- V2 semantic frame/router/IR: `src/text2pandas/domain/semantic/frame.py`, `router.py`, `ir.py`, `spec.py`
- V3 parsing contracts/parser: `src/text2pandas/application/parsing/contracts.py`, `parser.py`
- V3 AST/planner/retrieval: `src/text2pandas/domain/semantic/ast.py`, `src/text2pandas/application/planning/`, `src/text2pandas/infrastructure/retrieval/operand.py`
- Semantic V3 runner: `src/text2pandas/application/semantic_v3.py`

### 13.6 Audit limitations

1. Không có hidden official gold hoặc official scorer.
2. Không xác nhận được exact artifact đã upload cho submission 3757.
3. Manual retrieval gold chỉ phủ 9.387% câu hỏi.
4. Semantic gold chưa đủ independence và usable volume.
5. Table F2 là kết quả end-to-end; parser attribution cần stage-level gold và controlled counterfactual lớn hơn.

---

**Final audit verdict:** **NO** — current Canonical V2 parser không phải nguyên nhân chính đã được chứng minh cho Tables F2-Macro ≈ 0.25. **UNKNOWN** — nguyên nhân chính xác của official submission 3757 chưa thể xác định từ artifacts hiện có.
