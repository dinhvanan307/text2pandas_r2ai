# P0 — Metric Resolver + SelectorSpec Implementation Plan

## 1. Mục tiêu

Nâng Answer/Execution Accuracy bằng cách sửa đúng tầng đang có rủi ro lớn nhất:

```text
Question
→ resolve đúng metric
→ tạo SelectorSpec có kiểu
→ chọn đúng observation/cell
→ validate semantic contract
→ rebind nếu candidate đầu sai
→ execute và replay
```

Mục tiêu P0 không phải tăng số câu trả lời bằng mọi giá. Submission 3799 phát
sinh 585 answer nhưng official accuracy chỉ `0.2609`, tương đương khoảng 264
câu đúng. Khoảng 321 emitted answers còn lại là pool cần ưu tiên sửa
correctness.

Con số 321 là suy luận aggregate từ leaderboard, chưa phải 321 QID đã có nhãn
sai cụ thể.

## 2. Quyết định kiến trúc

Không tạo một ontology thứ ba.

Sử dụng:

- `MetricDefinition` hiện có làm MetricSpec nguồn duy nhất;
- `configs/answer_v2/metrics_v1.yaml` làm baseline bất biến;
- tạo `metrics_v2.yaml` cho P0, không sửa trực tiếp `v1`;
- dùng `OperandSpec`/`QuestionSemanticFrameV2` hiện có làm nền cho SelectorSpec;
- dùng `A6MetricMentionResolver` làm source-label fallback;
- Canonical V2 vẫn là submission runtime;
- V3 tiếp tục shadow; chỉ tái sử dụng ontology, operand contract và validation
  logic.

Luồng mới:

```text
Canonical entity/period/unit parsing
        ↓
Question-only ontology resolver
        ↓
A6 source-label fallback nếu ontology chưa resolve
        ↓
MetricResolution
        ↓
SelectorSpecBuilder
        ↓
MetricAwareSelector
        ↓
bind → validate → rebind tối đa 3 candidates
        ↓
V2 render/execute/replay/package
```

## 3. Phạm vi P0

P0 chỉ bật cho các operation an toàn:

- single-entity lookup;
- same-metric difference giữa hai kỳ;
- same-metric growth;
- sum/average cùng metric qua nhiều kỳ.

Chưa bật trong P0:

- divide giữa hai metric;
- multi-entity;
- select-at-arg;
- filtered extrema;
- derived ranking;
- reported/unreviewed metric trong phép toán dẫn xuất.

Các route bị loại vẫn dùng V2 legacy hoặc abstain như hiện tại.

## 4. Metric rollout

### Wave A — 28 metrics đã được review

Giữ toàn bộ 28 metrics hiện có, trong đó các metric P0 quan trọng gồm:

- `net_revenue`;
- `profit_after_tax`;
- `gross_profit`;
- `profit_before_tax`;
- `total_assets`;
- `total_liabilities`;
- `equity`;
- `current_assets`;
- `current_liabilities`;
- `inventory`;
- `cash_flow_from_operations`;
- `interest_expense`;
- `selling_expense`;
- `admin_expense`;
- `financial_expense`;
- `financial_income`;
- `cogs`.

### Wave B — 12 metric candidates mới

Đưa tổng số lên khoảng 40:

1. `cash_and_cash_equivalents`
2. `current_income_tax_expense`
3. `other_income`
4. `other_expense`
5. `trade_receivables`
6. `short_term_trade_payables`
7. `net_cash_flow_investing`
8. `net_cash_flow_financing`
9. `customer_deposits`
10. `loans_to_customers`
11. `retained_earnings`
12. `held_to_maturity_investments`

Các metric mới phải qua A6 grounding gate trước khi được review. Ví dụ corpus
hiện có:

- Tiền và tương đương tiền: 5.039 observations/78 tickers;
- Chi phí thuế TNDN hiện hành: 1.782/68;
- Thu nhập khác: 6.999/100;
- Chi phí khác: 9.514/98;
- Tiền gửi khách hàng: 10.349/25;
- Cash flow đầu tư: 2.172/81;
- Cash flow tài chính: 2.334/85.

Không thêm `operating_profit` trong P0 vì registry hiện ghi nhận metric này
chưa đạt grounding contract.

## 5. MetricSpec contract

Nguồn YAML:

```yaml
metric_id: net_revenue
aliases:
  - doanh thu thuần
  - doanh thu thuần bán hàng và cung cấp dịch vụ
expected_dimension: MONEY
preferred_statement_types:
  - income_statement
preferred_basis: consolidated
period_semantics: FLOW
forbidden_prefixes:
  - doanh thu thuần khác
forbidden_contains: []
required_context_any: []
review_status: reviewed
legal_operations:
  - lookup
  - subtract
  - growth
  - sum
  - average
```

Các trường bắt buộc:

- `metric_id`;
- `aliases`;
- `expected_dimension`;
- `preferred_statement_types`;
- `preferred_basis`;
- `period_semantics`;
- `forbidden_prefixes`;
- `forbidden_contains`.

Nên bổ sung:

- `required_context_any`;
- `sign_policy`;
- `legal_operations`;
- `review_status`;
- `positive_examples`;
- `negative_examples`.

### Validation của registry

Loader phải fail closed khi:

- alias rỗng;
- alias trùng sau normalize;
- một alias thuộc nhiều metric;
- dimension là `UNKNOWN`;
- period semantics không xác định;
- statement type không hợp lệ;
- forbidden rule chặn toàn bộ positive aliases;
- metric chưa có A6 grounding;
- reviewed metric không có negative examples.

## 6. Metric Resolver

### Output contract

```python
MetricResolution(
    status="RESOLVED | AMBIGUOUS | UNRESOLVED",
    selected_metric_id="net_revenue | None",
    mentions=(...),
    candidates=(...),
    confidence=...,
    resolution_method="EXACT_ALIAS | SOURCE_LABEL | ...",
    reason="...",
    ontology_fingerprint="...",
)
```

Mỗi mention cần:

- exact surface span;
- normalized phrase;
- start/end offsets;
- candidate metric IDs;
- selected metric;
- match method;
- confidence components.

### R0 — Question normalization

- Unicode NFC;
- lowercase/casefold;
- bỏ dấu để matching;
- giữ mapping offsets về nguyên bản;
- mask entity, period và unit;
- không dùng retrieval result, answer hoặc selected table.

### R1 — Reviewed ontology matching

Ưu tiên:

1. exact longest phrase;
2. exact normalized phrase;
3. unique reviewed alias;
4. formula alias nếu route thực sự là formula.

Không cho alias ngắn nuốt alias dài.

Ví dụ:

```text
“lợi nhuận sau thuế của cổ đông công ty mẹ”
```

không được resolve thành `profit_after_tax` tổng hợp vì có forbidden qualifier
`công ty mẹ`.

### R2 — Ambiguity detection

Các tình huống phải trả `AMBIGUOUS`:

- “doanh thu” nhưng không rõ gross/net;
- “tiền” nhưng có thể là tiền mặt hoặc tiền và tương đương tiền;
- “thuế TNDN” nhưng không rõ expense/payable/current/deferred;
- hai metrics có cùng best score;
- question có nhiều metric spans nhưng route chỉ hỗ trợ một metric.

Không dùng thứ tự metric ID để phá tie.

### R3 — A6 source-label fallback

Chỉ gọi khi R1 chưa resolve.

Được sử dụng:

- entity scope;
- period scope;
- question text;
- A6 row labels;
- statement/unit compatibility.

Không được sử dụng:

- retrieval rank;
- selected candidate;
- answer value;
- Pandas query;
- gold fields.

Fallback chỉ `RESOLVED` khi unique winner vượt confidence margin. Nếu không,
trả `AMBIGUOUS`.

### R4 — Operation eligibility

- Reviewed metric: dùng các operation trong `legal_operations`;
- reported metric: chỉ lookup;
- unreviewed metric: không đưa vào arithmetic;
- derived metric noun không được giả lập thành reported metric.

## 7. SelectorSpec

### Contract đề xuất

```python
SelectorSpec(
    metric_id,
    aliases,
    entity,
    period,
    requested_period_role,
    requested_basis,
    preferred_basis,
    expected_dimension,
    allowed_statement_types,
    period_semantics,
    forbidden_prefixes,
    forbidden_contains,
    required_context_any,
    metric_codes,
    resolution_confidence,
    resolution_method,
    ontology_fingerprint,
)
```

Mỗi operand phải có SelectorSpec riêng. Không copy một metric vào cả numerator
và denominator.

### Hard constraints

Candidate bị loại nếu:

- sai entity;
- sai năm/kỳ;
- dimension không tương thích;
- row label khớp forbidden prefix/contains;
- statement type không nằm trong allowed set khi metric yêu cầu cứng;
- explicit basis trong câu không khớp;
- không có bất kỳ metric evidence nào;
- point-in-time metric bị lấy từ flow column hoặc ngược lại.

### Soft ranking

Sau hard gate, dùng tuple ranking ổn định:

1. exact leaf alias;
2. exact metric code;
3. reviewed source-label match;
4. required context match;
5. statement type;
6. requested period role;
7. explicit/preferred basis;
8. section match;
9. retrieval table prior;
10. non-restated;
11. row depth;
12. stable observation UID.

Retrieval table prior không được đứng trước metric correctness.

### Tie policy

Nếu hai candidates:

- có cùng metric score;
- khác observation/value/basis/period semantics;
- margin nhỏ hơn threshold;

thì không tự chọn bằng UID. Chuyển sang `AMBIGUOUS_BINDING` hoặc rebind ở tầng
operation.

## 8. Tích hợp vào Canonical V2

### I1 — Shadow-only

Trong `src/text2pandas/application/usecases/canonical_run.py`:

- resolve metric sau `parse_intent`;
- ghi `MetricResolution` và SelectorSpec vào trace;
- tiếp tục dùng legacy selector;
- không thay answer hoặc table output.

Mục tiêu là đo coverage và differential trước khi thay hành vi.

### I2 — Guarded selector

Bật `MetricAwareSelector` khi:

- status `RESOLVED`;
- review status là `reviewed`;
- confidence đạt threshold;
- operation thuộc P0 safe routes.

Nếu không đủ điều kiện, dùng legacy selector.

`answer_question()` đã nhận tham số `metric_id`, nhưng canonical runtime hiện
chưa truyền metric này. P0 phải nối:

```text
MetricResolution.selected_metric_id
→ QuestionSemanticFrame.metric_id
→ OperandSlot.metric_id
→ MetricAwareSelector
```

### I3 — Bind–validate–rebind

Thay vì lấy candidate đầu tiên:

```text
top candidates
→ bind candidate #1
→ semantic validation
→ fail thì candidate #2
→ fail thì candidate #3
→ fail closed hoặc guarded legacy fallback
```

Các lý do rebind:

- unit mismatch;
- period-role mismatch;
- forbidden child label;
- basis mismatch;
- metric-code conflict;
- point/flow mismatch;
- restated ambiguity.

Không rebind khi:

- divisor bằng 0;
- operation không được review;
- question metric ambiguous;
- cross-basis/currency;
- metric concept khác hẳn.

## 9. Evaluation dataset

Không dùng model checkpoint 71 làm promotion gold. Nó chỉ được dùng chẩn đoán.

Tạo một prediction-blind human set 150 QID:

| Cohort | Số lượng |
|---|---:|
| Emitted nhưng metric frame thiếu/không chắc | 60 |
| Simple lookup của top metrics | 30 |
| Unbound/unit/period mismatch | 25 |
| Parent-vs-child confusions | 20 |
| OOV/ambiguous negative cases | 15 |

Gold fields:

- metric mention spans;
- canonical metric ID;
- resolution status;
- entity/period/basis/unit;
- gold table UID;
- gold observation UID/row;
- numeric answer;
- allowed/forbidden alternatives.

Nên có hai reviewer và adjudication cho các disagreement.

## 10. Test plan

### Unit tests — ontology

- normalized alias collision;
- empty aliases;
- invalid dimension;
- invalid statement type;
- positive alias bị forbidden;
- fingerprint thay đổi khi registry thay đổi.

### Unit tests — resolver

Mỗi metric cần:

- ít nhất 3 positive questions;
- ít nhất 3 negative/confusable questions;
- có dấu/không dấu;
- viết tắt;
- OCR spacing;
- parent/child label;
- multi-metric question;
- ambiguous question.

### Unit tests — selector

Bắt buộc có fixtures cho:

- total liabilities vs vendor liabilities;
- PAT tổng vs PAT công ty mẹ;
- inventory vs inventory provision;
- revenue vs other revenue;
- cash vs cash equivalents;
- current vs opening/closing period;
- consolidated vs separate;
- note vs main statement;
- percent vs money;
- restated vs current value.

### Metamorphic tests

- đảo thứ tự candidate không đổi result;
- thêm bảng không liên quan không đổi result;
- thêm forbidden child không được làm candidate đó thắng;
- có dấu/không dấu cho cùng metric phải resolve giống nhau;
- candidate UID thay đổi nhưng semantics giống nhau không đổi answer.

### Integration tests

- question → metric → SelectorSpec → bound observation;
- query dùng đúng evidence variable;
- final tables chứa selected evidence;
- clean replay;
- full submission validation.

## 11. Metrics và promotion gates

### Resolver gates

- Metric concept exact ≥ `0.90`;
- Mention-span F1 ≥ `0.90`;
- False resolved rate ≤ `0.02`;
- ambiguous/OOV forced resolution = `0`;
- registry alias collision = `0`.

### Selector/binding gates

- Gold-cell Hit@1 tăng tối thiểu `+0.10`;
- Gold-cell Hit@3 ≥ `0.90` trên supported cohort;
- parent-child false binding giảm tối thiểu 50%;
- rebind wins > losses;
- không có cross-basis/currency emission mới.

### Answer gates

- Held-out Answer Accuracy tăng tối thiểu `+0.05` tuyệt đối hoặc đạt ít nhất
  10 net wins;
- không mất các 14 local answers hiện đang đúng;
- supported coverage không giảm quá 1 điểm phần trăm;
- protected route regression ≤ 1%;
- full 1.012 replay mismatch = `0`.

### Retrieval/submission protection

- Scorer-facing S1/S2 behavior phải byte-identical trong P0 answer-only;
- manual Tables/Docs F2 không giảm quá `0.01`;
- validator errors/warnings = `0`;
- hai full runs phải byte-identical;
- `git diff --check`, CI và integration đều PASS.

## 12. Thứ tự triển khai

| Phase | Công việc | Thời gian ước lượng |
|---|---|---:|
| P0.0 | Freeze baseline, cohort và metrics | 0,5 ngày |
| P0.1 | MetricSpec/SelectorSpec contracts | 1 ngày |
| P0.2 | Registry v2 và 40 metrics | 1–2 ngày |
| P0.3 | Resolver + ambiguity/OOV logic | 1–2 ngày |
| P0.4 | MetricAwareSelector | 1–2 ngày |
| P0.5 | Bind–validate–rebind | 1 ngày |
| P0.6 | Shadow full corpus và differential | 0,5–1 ngày |
| P0.7 | Guarded candidate, E2E, report | 1 ngày |

Tổng engineering: khoảng 6–9 ngày, không tính thời gian human annotation.

## 13. File dự kiến thay đổi/tạo mới

```text
configs/answer_v2/metrics_v2.yaml
configs/semantic/ontology_v3_metric_p0.yaml
configs/answer_v2/metric_selector_p0.yaml

src/text2pandas/application/parsing/contracts.py
src/text2pandas/application/selection/contracts.py
src/text2pandas/application/selection/selector_spec.py
src/text2pandas/pipelines/answering/metric_selector.py
src/text2pandas/pipelines/answering/binding.py
src/text2pandas/application/usecases/canonical_run.py
src/text2pandas/interface/cli/main.py

tests/unit/test_metric_spec_p0.py
tests/unit/test_metric_resolver_p0.py
tests/unit/test_metric_selector_p0.py
tests/unit/test_metric_rebind_p0.py
tests/integration/test_metric_answer_p0.py

tools/evaluation/evaluate_metric_selector_p0.py
```

## 14. Deliverables cuối cùng

- Metric registry v2 có fingerprint;
- 40 reviewed/candidate MetricSpecs;
- resolver có `RESOLVED/AMBIGUOUS/UNRESOLVED`;
- SelectorSpec per operand;
- metric-aware selector và rebind;
- shadow differential 1.012 QID;
- human-gold evaluation;
- full candidate ZIP;
- validator/replay/determinism reports;
- báo cáo wins/losses theo QID và metric family;
- promotion decision `PASS/BLOCKED`, không tự động promote.

Điểm quan trọng nhất của plan là triển khai theo thứ tự:

```text
Metric correctness
→ cell correctness
→ answer correctness
→ mở thêm operation coverage
```

Không mở rộng multi-entity hoặc derived formulas trước khi chứng minh
SelectorSpec làm tăng correctness của các câu đơn giản hiện đang được emitted.
