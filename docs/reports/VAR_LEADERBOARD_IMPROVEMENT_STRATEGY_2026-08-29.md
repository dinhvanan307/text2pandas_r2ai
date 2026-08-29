# VAR Leaderboard Improvement Strategy — 2026-08-29

## 1. EXECUTIVE SUMMARY

VAR đang thua Top 1 chủ yếu ở khả năng biến evidence thành đáp án đúng, không
chỉ ở retrieval.

Ba bằng chứng mạnh nhất:

1. Execution/Answer Accuracy chỉ `0.2589`, thấp hơn Top 1 `0.4526` điểm tuyệt
   đối.
2. Pipeline hiện trả lời 564/1.012 câu nhưng chỉ khoảng 262 câu đúng theo
   leaderboard. Nghĩa là khoảng 302 câu đã chạy được nhưng cho đáp án sai.
3. Từ submission 3766 → 3770, Tables Recall/F2/MRR5 đều tăng nhưng Execution
   Accuracy vẫn giữ nguyên `0.2589`. Đây là bằng chứng trực tiếp rằng cải thiện
   retrieval tiếp theo chưa chắc chuyển thành điểm Answer.

Quyết định kỹ thuật:

> Không tiếp tục ưu tiên mở rộng retrieval hoặc thêm embedding/reranker chung.
> Ưu tiên xây Minimal Semantic Metric Resolver nối trực tiếp vào SelectorSpec
> và cơ chế bind–validate–rebind cho các lookup đơn giản.

### Lưu ý về schema dữ liệu leaderboard

Các metric dưới đây được map trực tiếp bằng `column_key` trong raw leaderboard
JSON, không suy ra theo vị trí cột của screenshot. Screenshot thứ nhất bị cắt
ngang nên không hiển thị đủ các cột MRR/Docs; screenshot thứ hai xác nhận thứ tự
chi tiết. Raw JSON là nguồn định danh metric có thẩm quyền.

## 2. VAR VS TOP 1

Relative gap được tính bằng:

```text
(Top1 - VAR) / Top1
```

| Metric | VAR | Top 1 | Gap tuyệt đối | Gap tương đối | Mức độ |
|---|---:|---:|---:|---:|---|
| Execution Accuracy | 0.2589 | 0.7115 | 0.4526 | 63.61% | Critical |
| Tables F2-macro | 0.3000 | 0.6120 | 0.3120 | 50.98% | Critical |
| Docs F2-macro | 0.7086 | 0.9618 | 0.2532 | 26.33% | High |
| Tables Precision | 0.2707 | 0.5928 | 0.3221 | 54.34% | Critical |
| Tables Recall | 0.3435 | 0.6261 | 0.2826 | 45.14% | High |
| Tables MRR5 | 0.3801 | 0.6514 | 0.2713 | 41.65% | High |
| Docs Precision | 0.6349 | 0.9587 | 0.3238 | 33.77% | High |
| Docs Recall | 0.7651 | 0.9678 | 0.2027 | 20.94% | Medium |
| Docs MRR5 | 0.7885 | 0.9806 | 0.1921 | 19.59% | Medium |
| Answer Accuracy | 0.2589 | 0.7115 | 0.4526 | 63.61% | Critical |

Điểm đáng chú ý:

- Docs MRR5 tương đối tốt hơn các retrieval metric khác.
- Tables MRR5 thấp rõ rệt so với Docs MRR5: document có thể đã được tìm khá sớm,
  nhưng đúng table trong document chưa được xếp hạng tốt.
- Khoảng cách Execution lớn hơn nhiều so với khoảng cách Recall. Retrieval
  không giải thích hết phần thiếu `0.4526`.

Quy đổi theo 1.012 câu:

| Target | Số câu đúng cần có | Cần tăng so với khoảng 262 câu hiện tại |
|---|---:|---:|
| 0.35 | ≈354 | +92 |
| 0.40 | ≈405 | +143 |
| 0.50 | ≈506 | +244 |
| 0.60 | ≈607 | +345 |
| 0.70 | ≈708 | +446 |
| Top 1: 0.7115 | ≈720 | +458 |

Pipeline hiện answer 564 câu. Nếu toàn bộ 564 câu đều đúng, trần accuracy chỉ
khoảng `0.5573`. Vì vậy:

- đạt khoảng 0.50 chủ yếu cần sửa correctness của các câu đang trả lời;
- vượt 0.55 bắt buộc phải đồng thời mở coverage cho các abstention.

## 3. BOTTLENECK ANALYSIS

### Funnel hiện tại

```text
Question:                   1,012
Entity/year recognized:    1,011
Retrieved tables:          1,011
Answered:                     564
Officially correct:          ≈262
Abstained:                    448
Answered but likely wrong:   ≈302
```

### Kết luận theo từng tầng

| Tầng | Đánh giá | Evidence |
|---|---|---|
| Document retrieval | Có vấn đề, nhưng không phải P0 | Docs recall 0.7651 và Docs MRR5 0.7885 tương đối mạnh |
| Table candidate generation | Có miss đáng kể | Official Tables recall 0.3435; manual-95 S1 hit 95/95 không đại diện official scope |
| Table ranking | Bottleneck retrieval lớn | Tables MRR5 0.3801; thấp hơn Docs MRR5 0.7885 |
| Semantic parsing | Bottleneck P0 | `metric_id` thường rỗng, thiếu operand specifications |
| Metric/row resolution | Bottleneck P0 | 40 `BIND:UNBOUND_OPERANDS`; nhiều lookup không map chắc vào row label |
| Planning/composition | Bottleneck P1 | 176 multi-entity unsupported, 32 arg-select, 27 divide, 19 nested extremum |
| Unit/scale | Bottleneck quick-win | 27 dimension mismatch và nhiều câu yêu cầu triệu/tỷ/nghìn tỷ/% |
| Pandas executor | Không phải bottleneck lớn nhất | Clean replay chạy 564/564; chạy được không đồng nghĩa đáp án đúng |
| Validator | Có thể đang pass wrong answer | Khoảng 302 answered nhưng không đúng official |
| Answer rendering | Có vấn đề cục bộ | Unit/scale failures, nhưng không giải thích toàn bộ gap |

Leaderboard cho phép suy ra:

- correctness sau retrieval là bottleneck nghiêm trọng;
- table ranking còn yếu;
- retrieval gain hiện không tự chuyển thành execution gain.

Leaderboard chưa đủ để kết luận:

- có bao nhiêu trong 302 câu sai do metric, period, basis, formula hay scale;
- embedding hiện tại yếu hay chỉ thiếu row/metric semantic signal;
- planner hay binding chịu trách nhiệm chính cho từng QID.

Cần per-QID answer gold hoặc source-adjudicated evidence để tách các nguyên
nhân này.

### Abstention concentration

| Reason | Count | % toàn benchmark |
|---|---:|---:|
| `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` | 176 | 17.4% |
| `BIND:UNBOUND_OPERANDS` | 40 | 4.0% |
| `EXTREMUM_SELECT_AT_ARG_REQUIRES_TWO_METRICS` | 32 | 3.2% |
| `DIVIDE_REQUIRES_REVIEWED_FORMULA` | 27 | 2.7% |
| Unit dimension mismatch | 27 | 2.7% |
| Cross-basis operands | 20 | 2.0% |
| Formula outer extremum unsupported | 19 | 1.9% |
| Entity-difference metric drift | 17 | 1.7% |

Tám nhóm này chiếm 358/448 abstention, gần 80%.

Tuy nhiên, 302 câu đã answer nhưng sai vẫn là pool cải thiện lớn hơn bất kỳ một
abstention bucket nào. Vì thế không nên bắt đầu bằng việc hỗ trợ toàn bộ
multi-entity.

## 4. RETRIEVAL ANALYSIS

### Pattern Precision thấp + Recall chưa đủ + MRR thấp

Pattern này cho thấy ba vấn đề khác nhau:

1. Recall chưa đủ: một phần gold document/table không sống đến final output.
2. Precision thấp: output chứa nhiều bảng cùng ticker/year nhưng sai metric,
   statement, basis hoặc period role.
3. MRR thấp: khi gold đã tồn tại, nó thường đứng sau distractor.

Chênh lệch `0.4084` giữa Docs MRR5 và Tables MRR5 gợi ý:

```text
đúng document có thể được tìm sớm
↓
nhưng table/row đúng trong document chưa được nhận diện tốt
```

Các nguyên nhân có xác suất cao:

- BM25/table score thiếu signal từ resolved metric;
- câu hỏi và row label dùng cách diễn đạt khác nhau;
- statement table và note table cạnh tranh mà không có statement compatibility
  đủ mạnh;
- period/current/prior/restated chưa được dùng nhất quán;
- top-k rộng đưa nhiều bảng cùng doanh nghiệp vào selector;
- document-to-table linking không biểu diễn metric thường nằm ở note/statement
  nào;
- selector dùng lexical evidence trước khi có `metric_id` ổn định.

### Candidate generation có phải lỗi chính?

Không thể kết luận chỉ từ final Recall.

Manual audit cho thấy S1 hit 95/95, nhưng official recall thấp hơn nhiều. Có
thể do:

- development slice không đại diện;
- gold bị mất ở S2/output-N;
- final binding thay table refs;
- official gold định nghĩa khác manual gold.

Do đó không có bằng chứng để nói embedding là nguyên nhân chính.

### Có nên thêm reranker ngay?

Không phải ưu tiên số một.

Reranker có thể tăng MRR/precision, nhưng submission 3770 đã chứng minh
retrieval metrics tăng mà Execution không tăng. Reranker chỉ đáng làm sau khi
có metric resolver, để rerank bằng:

```text
resolved metric
+ entity
+ period
+ basis
+ unit
+ statement compatibility
```

Một reranker lexical/embedding chung lúc này có nguy cơ chỉ tối ưu proxy
retrieval.

## 5. ROOT-CAUSE HYPOTHESES

| Rank | Hypothesis | Evidence | Impact | Confidence | Priority |
|---:|---|---|---:|---:|---:|
| 1 | Metric resolution failure | `metric_id` rỗng; lookup phrase chưa link ổn định tới Silver row | Rất cao | Cao | P0 |
| 2 | Operand binding/selector failure | 40 unbound; khoảng 302 answered nhưng sai; selector chịu nhiều lexical ambiguity | Rất cao | Cao | P0 |
| 3 | Semantic composition failure | 176 multi-entity, 32 arg-select, 19 nested extremum | Rất cao | Cao | P1 |
| 4 | Unit/scale resolution failure | 27 hard abstain; câu hỏi dùng triệu/tỷ/trăm tỷ/nghìn tỷ/% | Trung bình-cao | Cao | P0 |
| 5 | Table ranking failure | Tables MRR5 thấp; primary boost từng tạo six positive flips | Cao | Cao | P1 |
| 6 | Derived metric coverage thiếu | Nhiều ratio, margin, CAGR, median filter, average, growth | Cao | Cao | P1 |
| 7 | Validator pass wrong evidence | 564 executed nhưng chỉ khoảng 262 đúng | Cao | Trung bình | P1 |
| 8 | Document retrieval failure | Docs recall thấp nhưng MRR tương đối cao | Trung bình | Trung bình | P2 |
| 9 | Semantic parser operation failure | Operation có nhưng thiếu result/operand semantics đầy đủ | Cao | Trung bình | P1 |
| 10 | Entity resolution failure | Local entity recognition 1.011/1.012 | Thấp | Cao | P3 |
| 11 | Pandas executor failure | Replay 564/564, không có runtime error | Thấp | Cao | P3 |
| 12 | Answer rendering thuần túy | Có scale/unit issue nhưng không giải thích 302 wrong answers | Trung bình | Trung bình | P2 |

Validator đơn thuần không tăng accuracy: biến một wrong answer thành abstain
vẫn là sai trên leaderboard. Validator chỉ có giá trị khi nó kích hoạt
rebind/replan/fallback.

## 6. TOP 5–8 INTERVENTIONS

Các expected impact dưới đây là range giả thuyết, không cộng tuyến tính.

| Priority | Intervention | Metric tác động | Expected impact | Effort | Risk |
|---|---|---|---:|---:|---:|
| P0 | Minimal Semantic Metric Resolver từ question phrase → canonical `metric_id`/row aliases | Answer, Execution, bind rate | +0.04–0.09 | Medium | Medium |
| P0 | `SelectorSpec` typed: entity, metric, period role, basis, unit, aggregation | Answer, evidence accuracy | +0.04–0.10 | Medium | Medium |
| P0 | Bind–validate–rebind: thử candidate tiếp theo khi semantic contract fail | Answer, Execution | +0.02–0.06 | Low–Medium | Medium |
| P0 | Canonical unit/scale conversion cho VND/triệu/tỷ/trăm tỷ/nghìn tỷ/% | Answer, coverage | +0.01–0.03 | Low | Low |
| P1 | Hai composition template: `argmax(metric A) → project metric B` và reviewed `divide(A,B)` | Execution, coverage | +0.02–0.05 | Medium | Medium |
| P1 | Multi-entity DSL tối thiểu: filter → rank/median → aggregate/project | Execution, coverage | +0.04–0.12 | High | High |
| P1 | Adjudicated answer-gold slice + oracle funnel theo stage | Gián tiếp, chống sửa mù | Không trực tiếp | Medium | Low |
| P2 | Metric-aware table reranking sau resolver; không dùng generic embedding-only | Table MRR/P, Answer | +0.01–0.04 | Medium | Medium |

Minimal Viable Fix không phải xây ontology lớn. Chỉ cần bắt đầu với 30–50
metric families xuất hiện nhiều:

```text
revenue
profit_after_tax
gross_profit
CFO
cash
inventory
current_assets
current_liabilities
total_assets
total_liabilities
equity
interest_expense
selling_expense
admin_expense
tax_expense
```

Mỗi metric cần aliases, dimension, preferred statement/note type và allowed
period roles.

## 7. ARCHITECTURE DECISION

Điểm cao nghĩa là nhiều hơn; riêng Effort/Risk cao nghĩa là khó/rủi ro hơn.

| Option | Impact /10 | Effort /10 | Risk /10 | Expected gain /10 |
|---|---:|---:|---:|---:|
| A. Retrieval trước | 4 | 5 | 5 | 3 |
| B. Semantic Metric Resolver | **9** | 5 | 4 | **9** |
| C. SelectorSpec/lookup layer | **9** | **4** | 4 | **9** |
| D. Derived metric + composition | 8 | 8 | 7 | 7 |
| E. Thêm reranker | 4 | 5 | 5 | 3 |
| F. Cải thiện planner tổng quát | 7 | 8 | 7 | 6 |
| G. Executor/validator | 4 | 4 | 6 | 3 |

Hướng chính được chọn: **Option B — Semantic Metric Resolver**.

Implementation tối thiểu của Option B phải kết thúc ở một thin SelectorSpec:

```text
question
→ metric resolver
→ MetricSpec
→ SelectorSpec
→ bind best valid cell
→ validate semantic contract
→ rebind next candidate nếu fail
```

Không xây planner tổng quát hoặc ontology hoàn chỉnh trong vòng đầu.

## 8. EXPERIMENT PLAN

### Baseline

Khóa submission 3770:

```text
Execution/Answer = 0.2589
Tables F2       = 0.3000
Tables Recall   = 0.3435
Tables MRR5     = 0.3801
```

### E1 — Metric Resolver + SelectorSpec cho simple lookup

Hypothesis: phần đáng kể trong khoảng 302 answered-but-wrong là chọn sai
row/cell.

Change:

- resolve metric family;
- dùng alias + statement type + period role;
- không đổi retrieval;
- không hỗ trợ composition mới.

Đo:

- end-to-end exact answer;
- conditional accuracy trên answered;
- `metric_id_coverage`;
- gold row/cell hit@1;
- slot bind rate;
- new answer regressions.

Expected result: answer correctness tăng mà coverage gần như giữ nguyên.

Stopping condition:

- dừng nếu cell-hit không tăng;
- rollback nếu answer regression > answer wins;
- nếu cell-hit tăng nhưng answer không tăng, chuyển thẳng sang unit/executor
  audit.

### E2 — Unit/scale canonicalization

Hypothesis: đúng cell nhưng sai dimension hoặc hệ số chuyển đổi.

Change:

- canonical amount in raw VND;
- render-only conversion sang triệu/tỷ/trăm tỷ/nghìn tỷ;
- ratio/percent không đi qua money conversion;
- provenance ghi storage exponent và render exponent.

Đo:

- 27 dimension-mismatch cases;
- correct-cell/wrong-answer cases;
- scale-error count.

Stopping condition: không có correct-answer uplift trên adjudicated set.

### E3 — Bind–validate–rebind

Hypothesis: candidate đúng nằm trong answer pool nhưng selector chọn distractor
đầu tiên.

Change:

```text
rank candidates
→ semantic gate
→ execute
→ validate metric/unit/period/basis
→ fail thì thử candidate tiếp theo
```

Đo:

- first-choice vs final-choice accuracy;
- rebind success rate;
- false rebind regressions.

Stopping condition: rebind wins/losses ≤ 1 hoặc precision giảm mạnh.

### E4 — Hai composition templates

Implement riêng biệt:

1. `argmax/argmin metric A → return metric B`;
2. `divide metric A / metric B`.

Đo từng experiment, không combine ngay.

Stopping condition:

- route coverage tăng nhưng answer accuracy không tăng;
- cross-period/basis regression xuất hiện.

### E5 — Multi-entity minimal DSL

Chỉ sau khi E1–E4 thắng.

Bắt đầu với:

```text
filter(predicate)
→ argmax/argmin
→ project(metric)
```

Sau đó:

```text
filter
→ average/sum/count
```

Không bắt đầu bằng median split, CAGR và nested derived metrics cùng lúc.

### Decision tree

```text
Official/local answer sai
│
├─ Gold table không có trong answer pool
│  └─ Sửa retrieval/candidate generation
│
├─ Gold table có, metric_id không resolve
│  └─ Sửa Metric Resolver
│
├─ Metric resolve, gold row có, operand không bind
│  └─ Sửa SelectorSpec/binding
│
├─ Operand bind đúng, operation/plan sai
│  └─ Thêm composition template
│
├─ Plan đúng, pandas query sai/runtime error
│  └─ Sửa executor
│
└─ Query/value đúng, output sai
   └─ Sửa unit/scale/rendering
```

Nếu retrieval metric tăng nhưng Execution không tăng, như 3766 → 3770, dừng
retrieval experiment và chuyển sang resolver/binding.

Nếu retrieval chỉ tăng nhẹ nhưng Execution tăng mạnh, giữ candidate: đúng table
có thể vốn đã nằm trong answer pool, còn semantic selector mới là phần tạo giá
trị.

### Internal metrics cần dùng

- `EndToEndExactAnswerAccuracy`;
- `ConditionalAccuracy = correct / non_abstain`;
- `SupportedCoverage`;
- `MetricIdCoverage`;
- `OperandSlotBindRate`;
- `GoldCellHit@1`;
- `GoldPathSurvival`: S1 → S2 → output → bind → final;
- `OracleTableAnswerAccuracy`: cấp gold table cho answer pipeline;
- `OracleCellAnswerAccuracy`: cấp gold cells cho planner/executor;
- accuracy theo operation/template;
- rebind win/loss;
- unit/scale error rate.

Table F2 hoặc MRR không được dùng một mình làm promotion gate.

## 9. TARGET SCENARIOS

### Scenario A — Quick Win: 0.35–0.40

Cần thêm khoảng 92–143 câu đúng.

Thay đổi:

- metric resolver cho top metric families;
- SelectorSpec cho lookup;
- unit/scale fix;
- bind–validate–rebind.

Độ khó: Medium  
Thời gian tương đối: 1–3 ngày  
Risk: Low–Medium  
Ưu tiên: P0

Range thực tế kỳ vọng: khoảng `0.32–0.38`; chạm 0.40 cần resolver bao phủ tốt
và answer-gold slice đại diện.

### Scenario B — Strong Improvement: 0.45–0.50

Cần thêm khoảng 193–244 câu đúng.

Ngoài Scenario A:

- subtract/growth/average ổn định;
- reviewed divide;
- arg-select-project;
- metric aliases rộng hơn;
- validator kích hoạt fallback.

Độ khó: Medium–High  
Thời gian: 3–7 ngày  
Risk: Medium  
Ưu tiên: P1

Range hợp lý: `0.40–0.50`.

### Scenario C — Competitive: 0.55–0.60

Cần thêm khoảng 295–345 câu đúng.

Bắt buộc:

- correctness cao trên 564 câu đang answer;
- rescue một phần đáng kể 448 abstention;
- typed composition;
- derived metric catalog;
- multi-entity filter/rank/aggregate;
- strong unit/basis/period contracts.

Độ khó: High  
Thời gian: 1–3 tuần  
Risk: High

Range aggressive: `0.52–0.62`.

### Scenario D — Top-tier: 0.65+

Cần thêm ít nhất khoảng 396 câu đúng.

Bắt buộc:

- retrieval recall/ranking gần nhóm đầu;
- structured planner đầy đủ;
- multi-entity và nested composition;
- derived metrics;
- deterministic binding;
- automatic repair/replan;
- source-grounded validator;
- broad answer-gold regression suite.

Độ khó: Very High  
Thời gian: nhiều tuần  
Risk: Very High

Không thể đạt bền vững chỉ bằng tuning top-k hoặc thêm reranker.

## 10. 1-DAY / 3-DAY / 1-WEEK PLAN

### Nếu chỉ có 1 ngày

1. Không sửa retrieval.
2. Lấy 120–150 câu stratified:
   - answered nhưng nghi sai;
   - 40 unbound;
   - 27 unit mismatch;
   - simple lookup theo top metric families.
3. Gán source-grounded gold cell và answer.
4. Implement Metric Resolver tối thiểu cho 15–20 metric phổ biến.
5. Dùng resolver làm hard semantic preference trong SelectorSpec.
6. Thêm bind–validate–rebind tối đa ba candidates.
7. A/B toàn bộ 1.012 và submit nếu answer wins > losses.

### Nếu có 3 ngày

- Ngày 1: resolver + adjudicated answer slice.
- Ngày 2: SelectorSpec, unit contract và rebind.
- Ngày 3: implement riêng `divide(A,B)` và `argselect(A)→project(B)`, chạy
  controlled A/B rồi combine winners.

Không dùng ba ngày này để đổi embedding model.

### Nếu có 1 tuần

- hoàn thiện metric registry cho 30–50 metric families;
- typed operand slots và SelectorSpec làm SSOT;
- unit/basis/period contracts;
- derived metric catalog cơ bản;
- composition DAG:

```text
filter
→ compute
→ rank/select
→ project
→ aggregate
```

- hỗ trợ 2–3 template multi-entity xuất hiện nhiều nhất;
- metric-aware table reranking;
- oracle funnel và regression gates trên 1.012 QID;
- hai deterministic full runs trước submission.

### Nếu mục tiêu vượt 0.50

Kiến trúc tối thiểu:

```text
Metric Resolver
→ typed SelectorSpec
→ deterministic operand binder
→ unit/basis/period contracts
→ derived metric registry
→ arg-select/divide composition
→ validate-and-rebind fallback
```

Chỉ sửa lookup không đủ để vượt 0.50; cần vừa tăng correctness của 564 câu hiện
tại, vừa rescue một phần abstention.

### Nếu mục tiêu cạnh tranh Top 3

Bắt buộc có:

- high-recall document/table retrieval;
- metric-aware table and row ranking;
- canonical metric ontology;
- typed semantic IR;
- multi-entity filter/rank/aggregate;
- derived metrics và nested composition;
- deterministic Pandas generation;
- evidence-grounded validator có repair;
- unit/scale/basis/period correctness;
- broad per-template answer-gold regression suite.

## 11. FINAL RECOMMENDATION

Không ưu tiên ngay:

- embedding mới;
- tăng top-k;
- generic reranker;
- planner tổng quát;
- validator chỉ biết abstain;
- redesign toàn bộ pipeline.

Ưu tiên ngay:

```text
MetricResolver
→ SelectorSpec
→ bind
→ semantic validation
→ rebind
```

Đây là hướng có khả năng sửa cả:

- khoảng 302 câu đang answer nhưng sai;
- 40 unbound cases;
- một phần unit/period/basis mismatch;
- table ranking trong answer pool thông qua resolved metric.

> **Nếu là tôi trực tiếp phụ trách team VAR, tôi sẽ xây Minimal Semantic Metric
> Resolver nối thẳng vào typed SelectorSpec và bind–validate–rebind trước, vì
> retrieval đã tăng mà Execution không tăng, trong khi pool lớn nhất hiện tại
> là hàng trăm câu đã chạy được nhưng đang chọn hoặc tính sai evidence.**
