# ObservationRoleSpec + SelectorSpec cho 60 Risk-A

## Wave 5 End-to-End Implementation, Measurement and Release Plan

**Ngày lập:** 2026-08-31

**SAFE baseline:** submission `3842`

**Official Answer/Execution Accuracy:** `0.3893`

**Baseline answer coverage:** `798/1.012`

**Baseline abstention:** `214/1.012`

**Chế độ:** shadow → blinded review → sealed holdout → recover-only candidate

**Trạng thái:** plan sẵn sàng thực thi; chưa phải báo cáo kết quả

---

## 1. Quyết định kỹ thuật

Wave tiếp theo chỉ xử lý **semantic observation selection** cho 60 Risk-A còn lại:

```text
Question semantics
→ canonical metric request
→ ObservationRoleSpec
→ role-aware candidate filtering
→ joint binding
→ family-specific completeness checks
→ typed execution ↔ clean Pandas replay
→ independent exactness evaluation
→ recover-only overlay trên submission 3842
```

Không mở rộng sang 99 complex compositions. Không thay retrieval, không thay 798
answer hiện có và không lấy một giá trị tình cờ trùng nhau làm bằng chứng semantic.

Thứ tự bắt buộc:

| Thứ tự | Family | Risk-A |
|---:|---|---:|
| 1 | Direct lookup | 7 |
| 2 | Direct ratio | 9 |
| 3 | Two-period difference | 11 |
| 4 | Single-metric sum | 3 |
| 5 | Single-metric average | 30 |
|  | **Tổng Wave 5** | **60** |
| 6, chỉ sau Wave 5 PASS | Simple extrema | 14 Risk-B |
| Deferred | Complex composition | 99 Risk-C |

Mục tiêu release là **10–15 fill sạch**, không phải ép coverage. Nếu chỉ có 6 record
đạt chuẩn thì release 6; nếu không có record nào đạt chuẩn thì giữ nguyên 3842.

---

## 2. Baseline và phạm vi đã kiểm chứng

### 2.1 Artifact gốc cần freeze

ZIP đang gắn với submission 3842:

```text
artifacts/handoffs/recovery-wave4-3831-source6-final-20260830/submission.zip
```

SHA-256 đầy đủ:

```text
2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76
```

Official metrics do người dùng cung cấp:

| Metric | Submission 3842 |
|---|---:|
| Answer Accuracy | 0.3893 |
| Execution Accuracy | 0.3893 |
| Tables F2-Macro | 0.3151 |
| Tables Precision | 0.2797 |
| Tables Recall | 0.3571 |
| Tables MRR@5 | 0.3939 |
| Docs F2-Macro | 0.7361 |
| Docs Precision | 0.6534 |
| Docs Recall | 0.7952 |
| Docs MRR@5 | 0.8162 |

`0.3893` tương thích với khoảng `394/1.012` câu đúng. Đây chỉ là suy ra từ
aggregate score; không được suy ra QID thắng/thua riêng lẻ.

### 2.2 Inventory đang có

Inventory sau Wave 4 có 214 abstention:

| Family | Risk-A | Risk-B | Risk-C | Risk-D | Tổng |
|---|---:|---:|---:|---:|---:|
| Direct lookup | 7 | 0 | 3 | 3 | 13 |
| Direct ratio | 9 | 0 | 0 | 2 | 11 |
| Two-period difference | 11 | 0 | 3 | 10 | 24 |
| Single-metric sum | 3 | 0 | 3 | 1 | 7 |
| Single-metric average | 30 | 0 | 4 | 12 | 46 |
| Simple extremum | 0 | 14 | 0 | 0 | 14 |
| Complex composition | 0 | 0 | 83 | 16 | 99 |
| **Tổng** | **60** | **14** | **96** | **44** | **214** |

Wave 5 mutation pool là đúng 60 Risk-A. Mọi QID ngoài set này bất biến.

### 2.3 Protected sets

| Set | Số record | Invariant |
|---|---:|---|
| `P-answer-3842` | 798 | answer, query, evidence và CSV phải giữ nguyên |
| `P-retrieval-3842` | 1.012 | relevant tables/documents phải giữ nguyên |
| `P-out-of-scope` | 154 abstention | không fill trong Wave 5 |
| `W5-risk-a60` | 60 abstention | pool duy nhất được phép thêm answer |

---

## 3. Phạm vi và non-goals

### 3.1 In scope

1. Freeze chính xác submission 3842 và tạo protected-set manifest.
2. Seal danh sách 60 Risk-A theo 5 family ở trên.
3. Tạo review packet prediction-blind và hai lượt review độc lập.
4. Bổ sung `ObservationRoleSpec` vào `OperandRequest` hiện có.
5. Truyền role metadata từ A6 observation qua retrieval candidate và fact.
6. Hard-filter candidate sai metric/source/row/column/basis/period/sign/scale/entity.
7. Siết semantic equivalence trong `JointBinder`.
8. Thêm completeness gate cho từng family.
9. Chạy full shadow và differential trên đủ 1.012 QID sau mỗi phase.
10. Chỉ package 10–15 record mạnh nhất nếu toàn bộ promotion gate PASS.

### 3.2 Out of scope

- Không đổi embedding, reranker, table/doc retrieval hoặc top-K scorer-facing.
- Không thay 798 answer/query/evidence đã có của 3842.
- Không dùng MODEL_GOLD, không resume generation.
- Không dùng adjudicated answer làm runtime prediction.
- Không tạo ontology metric thứ ba hoặc `MetricSpecV3` song song.
- Không thêm QID-specific conditional vào parser/retriever/binder.
- Không nới validator, replay, source-confidence hoặc consensus gate.
- Không mở 14 simple extrema trước khi 60 Risk-A đạt gate.
- Không mở 99 complex compositions trong Wave 5.
- Không tuyên bố accuracy từ coverage, replay hoặc candidate count.

---

## 4. Thiết kế contract trong kiến trúc hiện tại

### 4.1 Không tạo một pipeline song song

Các contract hiện hữu tiếp tục là source of truth:

| Trách nhiệm | Contract hiện tại |
|---|---|
| Canonical metric | `MetricDefinition` trong `domain/metrics/ontology.py` |
| Semantic expression | `QuestionAST` và `MetricRef` trong `domain/semantic/ast.py` |
| Source fallback | `MetricBindingHint` |
| Selector request | `OperandRequest` trong `application/planning/contracts.py` |
| Candidate | `ObservationCandidate` trong `application/retrieval/contracts.py` |
| Joint selection | `JointBinder` trong `application/binding/binder.py` |
| Grounded value | `FinancialFact` trong `domain/facts.py` |

`ObservationRoleSpec` là phần mở rộng của selector request; nó không định nghĩa
lại aliases hay metric ontology.

### 4.2 Contract đề xuất

Thêm các enum thuần domain/application và một immutable dataclass:

```python
class RowRole(StrEnum):
    TOTAL = "total"
    CHILD = "child"
    ALLOWANCE = "allowance"
    COST = "cost"
    NET = "net"
    UNKNOWN = "unknown"


class ColumnRole(StrEnum):
    CLOSING = "closing"
    OPENING = "opening"
    CURRENT = "current"
    PRIOR = "prior"
    AS_OF = "as_of"
    UNKNOWN = "unknown"


class SignMode(StrEnum):
    AS_REPORTED = "as_reported"
    POSITIVE_MAGNITUDE = "positive_magnitude"
    SIGNED_DIFFERENCE = "signed_difference"


@dataclass(frozen=True, slots=True)
class ObservationRoleSpec:
    source_metric_id: str | None
    accepted_source_metric_codes: tuple[str, ...]
    exact_row_labels: tuple[str, ...]
    required_row_path_tokens: tuple[str, ...]
    forbidden_row_path_tokens: tuple[str, ...]
    allowed_row_roles: tuple[RowRole, ...]
    allowed_column_roles: tuple[ColumnRole, ...]
    allowed_period_roles: tuple[str, ...]
    sign_mode: SignMode
    allowed_scale_sources: tuple[str, ...]
    entity_membership: tuple[str, ...]
```

`OperandRequest.metric_id` tiếp tục khóa canonical `metric_id`.
`ObservationRoleSpec.source_metric_id` và source codes khóa source identity.
Mỗi selected observation vì vậy phải qua đủ 10 trục:

```text
metric_id
source_metric_id / source_metric_code
exact row label/path
row role
column role
basis
period + period role
sign mode
scale source
entity membership
```

### 4.3 Metadata cần truyền end-to-end

`ObservationCandidate` hiện chưa mang `scale_source`, `row_role` và
`column_role`. Wave 5 phải truyền ba trường này từ A6 tới candidate, fact,
binding trace và manifest:

| Field | Nguồn | Hành vi khi thiếu |
|---|---|---|
| `scale_source` | `observations.scale_source` | money fact: reject nếu `assumed/none/unknown` |
| `row_role` | exact normalized row leaf + hierarchy | `UNKNOWN` và abstain nếu spec yêu cầu role cụ thể |
| `column_role` | period role + column hierarchy | `UNKNOWN` và abstain nếu không xác định duy nhất |
| `source_metric_code` | A6 metric code | reject nếu spec khóa code và không match |
| row/column hierarchy | A6 paths | phải có trong semantic-equivalence fingerprint |

Role classification là policy có version trong `configs/semantic/`; không nhét
aliases metric vào policy này và không hard-code theo QID.

### 4.4 Planner responsibility

Planner compile role requirements từ câu hỏi và metric/source resolution:

- `MetricRef` xác định canonical metric, entity, period, basis và unit.
- `MetricBindingHint` cung cấp source identity/labels/path khi ontology không đủ.
- syntax như “cuối năm”, “đầu năm”, “năm nay”, “năm trước”, “giá gốc”, “dự
  phòng”, “tổng”, “chi tiết” tạo `ObservationRoleSpec`.
- nếu câu hỏi không đủ để xác định một role bắt buộc và candidate khác role có
  thể đổi answer, planner trả terminal reason thay vì điền `UNKNOWN` rồi rank.

Không infer “total” chỉ vì value lớn hơn child và không infer “closing” chỉ vì
cột nằm bên trái/phải.

---

## 5. Measurement design: independent 60-QID review

### 5.1 Pre-register split trước khi code

Tạo split deterministic, stratified bằng question checksum:

| Family | Development | Sealed holdout | Tổng |
|---|---:|---:|---:|
| Direct lookup | 5 | 2 | 7 |
| Direct ratio | 6 | 3 | 9 |
| Two-period difference | 7 | 4 | 11 |
| Single-metric sum | 2 | 1 | 3 |
| Single-metric average | 20 | 10 | 30 |
| **Tổng** | **40** | **20** | **60** |

Rules:

1. Freeze `qid`, question SHA, family, risk, split digest trước implementation.
2. Developer chỉ được xem adjudicated labels của 40 development QID.
3. Hai reviewer không xem model answer, AST, candidate score hoặc retrieval rank.
4. Reviewer A và B làm độc lập; adjudicator C phải là người thứ ba.
5. Holdout labels được seal trước code freeze nhưng không mở cho developer.
6. Holdout chỉ được chạy một lần sau khi commit/config đã khóa.
7. Không sửa code/config sau khi mở holdout rồi báo lại cùng holdout như kết quả
   one-shot. Nếu sửa, version đó chỉ là development và cần holdout mới.

### 5.2 Review schema bắt buộc

Mỗi lượt review phải ghi:

```text
qid + question_sha256
operation family
canonical metric_id
source_metric_id/source_metric_code
exact observation_uid(s)
exact row label + full row path
row role
column role
entity/member key
basis
period + period role
sign convention
unit + scale exponent + scale source
member/domain completeness
expected operation order
expected answer + tolerance/rounding rule
source table/document evidence
reviewer identity + independence attestation
```

Decision states:

| State | Ý nghĩa | Candidate eligible |
|---|---|---|
| `PASS_DUAL_AGREEMENT` | A/B đồng thuận toàn bộ field; C xác nhận | Có |
| `PASS_ADJUDICATED` | A/B bất đồng; C xử lý đủ trường bất đồng | Có, nhưng ưu tiên sau |
| `AMBIGUOUS_SOURCE` | source có nhiều cách hiểu hợp lệ | Không |
| `UNRESOLVED_SOURCE` | thiếu exact fact/domain/scale | Không |
| `REJECTED_SEMANTICS` | AST/operation không đúng câu hỏi | Không |

Candidate ưu tiên `PASS_DUAL_AGREEMENT`. `PASS_ADJUDICATED` chỉ được nhận nếu
engine output match toàn bộ sealed fields và không có residual ambiguity.

### 5.3 Chống leakage

Mở rộng workflow `application/usecases/independent_gold.py` hiện có; không tạo
một review protocol tùy ý bỏ qua các guard đang có:

- reject `model_answer`, `model_ast`, `candidate_scores`, `retrieval_scores`;
- reviewer A, B và adjudicator C phải khác nhau;
- source evidence review bắt buộc;
- canonical serialization + SHA-256 manifest;
- không cho runtime đọc review/gold directory;
- candidate record phải do frozen engine sinh, không copy `expected_answer` hoặc
  fact UID từ review packet vào output generator.

---

## 6. Phase 0 — Freeze submission 3842

### Tasks

1. Copy exact ZIP SHA vào immutable official path:

```text
artifacts/official/submission-3842/submission.zip
```

2. Tạo identity:

```text
provenance/submissions/submission_3842.json
```

3. Append submission 3842 vào:

```text
configs/evaluation/submission_ledger_v1.json
```

4. Ghi `receipt_path: null` nếu chưa có leaderboard receipt bền vững.
5. Verify ZIP shape, 1.012 record, 798 executable, 214 abstain, clean replay.
6. Seal question, raw snapshot, A6 database, retrieval index, config và Git SHA.

### Gate W5-P0

| Gate | PASS |
|---|---|
| ZIP SHA | đúng `2a3457ee...fa93d76` |
| Official mapping | submission `3842`, đủ 10 metrics |
| Shape | `1.012` unique records |
| Replay | `798/798`, 0 error, 0 mismatch |
| Baseline retrieval | định danh đủ 1.012 record |

Nếu bất kỳ identity nào lệch: dừng Wave 5.

### Commit khi PASS

```text
docs(provenance): freeze official submission 3842
```

---

## 7. Phase 1 — Seal Risk-A60 scope và independent review

### Tasks

1. Regenerate inventory từ exact 3842, không tái dùng inventory chỉ bằng tên.
2. Assert cross-tab đúng `7/9/11/3/30` và tổng 60.
3. Tạo protected sets P-answer, P-retrieval, P-out-of-scope và W5-risk-a60.
4. Tạo deterministic split 40/20.
5. Tạo A/B packet prediction-blind và adjudication packet C.
6. Review đủ 60, seal release, ghi agreement per field và unresolved counts.

### Artifacts dự kiến

```text
configs/evaluation/recovery_wave5_riska60_scope_3842_v1.json
data/curated/evaluation/recovery_wave5_riska60_v1/
artifacts/runs/evaluation/recovery-wave5-3842-inventory-<run-id>/
artifacts/runs/evaluation/recovery-wave5-riska60-review-<run-id>/
```

`data/curated` chỉ chứa sealed review release nhỏ, có provenance; raw packet và
model outputs ở `artifacts/`.

### Gate W5-P1

- exactly 60 unique QID, không overlap P-answer;
- family counts đúng 7/9/11/3/30;
- 40 dev + 20 sealed holdout;
- 2 independent annotations/record và distinct adjudicator;
- 100% question checksum match;
- 0 forbidden model field trong review packet;
- unresolved/ambiguous được giữ nguyên, không ép thành PASS.

### Commit khi PASS

```text
feat(evaluation): seal risk-a60 observation review scope
```

---

## 8. Phase 2 — Implement ObservationRoleSpec contract

### Files chính

```text
src/text2pandas/application/planning/contracts.py
src/text2pandas/application/planning/planner.py
src/text2pandas/application/retrieval/contracts.py
src/text2pandas/domain/facts.py
configs/semantic/observation_roles_v1.yaml
```

### Tasks

1. Thêm enum + immutable `ObservationRoleSpec`.
2. Thêm optional `observation_role` vào `OperandRequest`.
3. Đưa spec vào `to_dict()` và `ExecutionPlan.fingerprint`.
4. Compile roles từ semantic surface/source hint, không từ candidate score.
5. Truyền `scale_source`, `row_role`, `column_role` qua candidate/fact.
6. Version role-classification config và fingerprint vào manifest.
7. Backward compatibility: request không có spec giữ hành vi cũ trong shadow;
   Wave 5 policy yêu cầu spec đầy đủ cho 60 Risk-A.

### Unit gates

- serialization/fingerprint thay đổi khi bất kỳ role field nào thay đổi;
- exact label/path normalize nhưng không làm mất hierarchy;
- cost và allowance không tương đương;
- closing/opening và current/prior không tương đương;
- money scale source `assumed/none/unknown` bị reject trong strict mode;
- entity member không thuộc domain bị reject;
- existing requests ngoài Wave 5 không functional-drift.

### Required test gate

```text
targeted planning/retrieval/fact tests
make typecheck
make test-offline
git diff --check
```

### Commit khi PASS

```text
feat(planning): add observation role selection contract
```

---

## 9. Phase 3 — MetricAwareSelector hard compatibility

### Hành vi bắt buộc

Trong `SqliteOperandRetriever`, mỗi candidate phải qua hard compatibility trước
khi tính/rank score:

```text
canonical metric exact
AND source metric/code exact khi spec yêu cầu
AND exact row label/path compatible
AND row role allowed
AND column role allowed
AND basis exact
AND period + period role exact
AND sign mode compatible
AND unit/scale evidence safe
AND entity membership exact
```

Score chỉ được dùng để xếp hạng các candidate đã semantically compatible. Score
không được bù cho một hard-role mismatch.

### Terminal reasons cần quan sát được

```text
SOURCE_METRIC_MISMATCH
ROW_LABEL_MISMATCH
ROW_ROLE_MISMATCH
COLUMN_ROLE_MISMATCH
BASIS_MISMATCH
PERIOD_ROLE_MISMATCH
SIGN_MODE_MISMATCH
SCALE_SOURCE_UNSAFE
ENTITY_MEMBERSHIP_MISMATCH
ROLE_AMBIGUOUS
```

Candidate batch trace phải có count reject theo từng reason, spec fingerprint và
danh sách observation UID được trả về.

### Ambiguity policy

- Hai row/path khác nhau nhưng cùng value vẫn là ambiguity nếu role khác nhau.
- Collision có nhiều value sống sót: abstain.
- Exact metric nhưng source code trái spec: reject.
- Source label fallback không được vượt exact reviewed ontology match nếu hai
  source meanings không equivalent.
- Không chọn value lớn nhất, gần nhất hay candidate đầu tiên để phá tie.

### Gate W5-P3

- Dev40 observation exact match được báo riêng theo 10 fields.
- Không có candidate hard-incompatible trong top-K.
- 798 protected records có zero functional outcome change.
- 60 Risk-A chỉ chuyển từ abstain sang candidate khi trace có role proof.

### Commit khi PASS

```text
fix(retrieval): enforce observation role compatibility
```

---

## 10. Phase 4 — Siết JointBinder và semantic equivalence

`JointBinder._semantically_equivalent()` hiện chủ yếu so value/unit/basis/entity/
period/restated. Wave 5 phải thêm semantic observation identity:

```text
canonical metric
source metric/code
row UID + normalized hierarchy + row role
column UID + normalized hierarchy + column role
period role
scale exponent + scale source
sign mode
entity member key
```

Hai assignments cho cùng numeric answer nhưng khác source row/role không được coi
là equivalent.

### Bind → validate → rebind

Giữ tối đa ba semantically distinct binding candidates:

1. bind candidate 1;
2. validate toàn bộ role/family constraints;
3. nếu fail, thử candidate 2;
4. nếu fail, thử candidate 3;
5. nếu nhiều candidate sống sót nhưng khác semantic key hoặc answer: abstain;
6. không thử candidate thứ 4 và không giảm validation để lấy coverage.

### Constraint additions

Chỉ thêm constraint tổng quát khi AST yêu cầu:

- same source metric;
- same entity member set;
- same period role pattern;
- compatible scale evidence;
- distinct observation for two-period operands;
- complete aggregation domain.

### Gate W5-P4

- top-3 rebind deterministic;
- same number/different row role không collapse;
- tie khác source/column role → `BINDING_TIE`/abstain;
- every accepted assignment has one semantic observation fingerprint;
- typed result bằng restricted-Pandas replay.

### Commit khi PASS

```text
fix(binding): require semantic observation equivalence
```

---

## 11. Phase 5 — Family rollout theo thứ tự

Mỗi family là một checkpoint riêng: targeted tests → Dev40 slice → full 1.012
differential → commit nếu PASS. Không gộp cả năm family rồi mới đo.

### 11.1 Direct lookup — 7 Risk-A

Gate per record:

- đúng một canonical metric;
- đúng một entity/member và một period;
- exact row/column role;
- scalar cardinality = 1 sau hard filtering;
- không aggregation, không implicit summation;
- source scale và sign có bằng chứng.

Reject nếu total và child cùng sống hoặc opening/closing chưa phân giải.

### 11.2 Direct ratio — 9 Risk-A

Gate per record:

- numerator/denominator roles được parser khóa riêng;
- exact metric/source cho cả hai operand;
- cùng entity, basis và period theo AST;
- dimension hợp lệ và denominator khác 0;
- sign policy rõ;
- phân biệt `mean(a/b)` với `sum(a)/sum(b)`;
- không lấy một operand của reported ratio thay cho ratio được hỏi.

### 11.3 Two-period difference — 11 Risk-A

Gate per record:

- hai observation khác nhau, cùng metric/source/entity/basis;
- period A và B đúng thứ tự câu hỏi;
- current/prior hoặc closing/opening roles exact;
- common normalized unit/scale;
- AST khóa `A-B`, `B-A`, absolute difference hoặc growth;
- không tự dùng absolute value khi câu hỏi hỏi chênh lệch có dấu.

### 11.4 Single-metric sum — 3 Risk-A

Gate per record:

- requested member set đầy đủ và unique;
- một exact observation cho mỗi member;
- same metric/source/basis/period/column role;
- unit normalize trước sum;
- total row không được cộng cùng child rows;
- thiếu một member → abstain, không partial sum.

### 11.5 Single-metric average — 30 Risk-A

Gate per record:

- requested entity/period member domain đầy đủ;
- đúng một observation/member;
- same metric/source/basis/column role;
- unit/scale normalize trước average;
- no member drop và no duplicate member;
- arithmetic mean chỉ dùng khi câu hỏi thực sự hỏi mean;
- ratio average giữ đúng semantics đã review;
- consolidated và parent-company không trộn.

### Promotion gate sau mỗi family

| Gate | PASS condition |
|---|---|
| Protected answers | `798/798` unchanged |
| Retrieval | `1.012/1.012` unchanged |
| Dev observation exactness | không giảm so checkpoint trước |
| Newly emitted | 100% có exact role trace |
| Replay | 0 mismatch, 0 execution error |
| Ambiguity | fail closed, không forced candidate |

---

## 12. Phase 6 — Select-at-arg gate cho 14 simple extrema

Phase này chỉ bắt đầu khi Wave 5 Risk-A đã PASS và candidate chính đã được khóa.
Không trộn 14 Risk-B vào candidate Risk-A đầu tiên.

Một `select-at-arg` chỉ được emit khi:

```text
rank domain đầy đủ
AND rank metric exact
AND selected key duy nhất
AND projected metric exact
AND tất cả surviving bindings chọn cùng key
```

Chi tiết:

1. `expected_rank_keys == bound_rank_keys`; không được thiếu member/period.
2. Mọi rank fact match exact metric/source/row/column/basis/period/scale roles.
3. Argmax/argmin có đúng một key; numeric tie không có tie-break → abstain.
4. Projected series có đúng cùng key domain và exact projected metric.
5. Mỗi surviving parse/binding candidate phải expose `selected_key` trong trace.
6. Tất cả selected keys phải bằng nhau.
7. Sau semantic-key consensus mới kiểm final numeric answer consensus.

Hai candidate chọn khác key nhưng tình cờ projected value bằng nhau vẫn phải
abstain. Answer consensus không thay cho key consensus.

Terminal reasons:

```text
RANK_DOMAIN_INCOMPLETE
RANK_METRIC_MISMATCH
RANK_KEY_TIE
PROJECTED_DOMAIN_MISMATCH
PROJECTED_METRIC_MISMATCH
SELECTED_KEY_DISAGREEMENT
```

---

## 13. Phase 7 — Full shadow/differential 1.012 QID

### Checkpoints bắt buộc

| Run | Thay đổi duy nhất |
|---|---|
| S0 | exact 3842 baseline behavior |
| S1 | role contract + metadata only |
| S2 | role-aware candidate hard filtering |
| S3 | binder semantic equivalence + top-3 rebind |
| S4 | direct lookup + ratio |
| S5 | difference + sum |
| S6 | average; frozen Wave 5 implementation |

Mỗi run có unique immutable run ID và manifest khóa:

- Git commit;
- questions SHA;
- active snapshot/A6/retrieval identities;
- ontology/resolver/role-policy fingerprints;
- split/review release fingerprints;
- terminal reason histogram;
- per-QID semantic fingerprint và selected observation UIDs.

### Differential report

Phải tách bốn nhóm:

```text
Protected 798 changed / unchanged
Risk-A60 newly correct / still abstain / incorrect emit
Out-of-scope 154 changed / unchanged
Retrieval 1.012 changed / unchanged
```

Measurements không được gộp:

| Layer | Metric |
|---|---|
| Role resolver | field exact match cho 10 role fields |
| Candidate selection | exact observation set match |
| Binding | exact semantic assignment match |
| Family execution | exact operation/domain match |
| Replay | typed↔Pandas equality |
| Candidate answer | answer exact match trên governed review set |
| Official | chỉ từ leaderboard sau upload |

### One-shot holdout gate

Sau khi S6 code/config đã commit và holdout được mở một lần:

| Gate | Threshold |
|---|---:|
| Overall exact observation + operation | **≥ 16/20 = 80%** |
| Direct group: lookup+ratio+difference | **≥ 70%** |
| Aggregate group: sum+average | **≥ 70%** |
| Incorrect emitted answer | **0 trên record candidate-eligible** |
| Protected-answer regression | **0/798** |
| Out-of-scope mutation | **0/154** |
| Retrieval mutation | **0/1.012** |

Nếu chỉ đạt 14/20 = 70% thì giữ shadow, không package lượt nộp chính. Mốc 70%
là minimum diagnostic; mốc release được chọn là 80% vì quota leaderboard hữu hạn.

---

## 14. Phase 8 — Candidate selection và packaging

### 14.1 Eligibility per QID

Một record chỉ được vào candidate nếu đồng thời:

1. baseline 3842 đang abstain;
2. QID thuộc sealed Risk-A60;
3. review decision hợp lệ;
4. frozen engine output match exact reviewed metric/source/roles/domain/operation;
5. binding consensus trên tối đa ba candidates;
6. typed execution = clean Pandas replay;
7. answer convention, sign, scale và rounding match review;
8. evidence chỉ gồm selected observation UIDs;
9. không sửa relevant tables/documents;
10. không có warning semantic chưa được adjudicate.

Review packet dùng để **đánh giá output**, không dùng để viết output. Nếu engine
không tự tạo được exact query/evidence thì QID tiếp tục abstain.

### 14.2 Chọn 10–15 record

Ranking release được preregister theo:

1. `PASS_DUAL_AGREEMENT` trước `PASS_ADJUDICATED`;
2. exact-source code/row path trước alias-only;
3. direct lookup/ratio/difference trước sum/average;
4. zero ambiguity và full role proof;
5. deterministic QID order để phá tie.

Target là 10–15. Không thêm record thứ 16 yếu hơn chỉ để tăng coverage; các record
đạt chuẩn còn lại được giữ cho candidate sau. Không ép đủ 10 nếu gate không đủ.

### 14.3 Build contract

Candidate Wave 5 là recover-only overlay:

```text
Nếu 3842 đã có answer:
    copy answer/query/evidence/CSV byte-identical

Nếu 3842 abstain và QID nằm trong accepted set:
    lấy frozen engine record đã replay và adjudicated

Nếu không:
    giữ nguyên abstention 3842

Retrieval:
    copy relevant_tables/relevant_docs từ 3842 cho đủ 1.012 QID
```

Build R1 và R2 độc lập. Hai ZIP phải byte-identical.

### Release gate bắt buộc

| Gate | PASS |
|---|---|
| Records | `1.012/1.012` unique |
| Baseline answer layer | `798/798` byte-equivalent |
| Baseline CSV payload | 100% preserved |
| Retrieval | `1.012/1.012` exact |
| Changed QID | chỉ accepted subset của Risk-A60 |
| Clean replay | all emitted matched; 0 error/mismatch |
| Strict competition validation | 0 error; chỉ warning abstention được giải thích |
| Evidence | selected UIDs only; no orphan/duplicate CSV |
| Determinism | R1 SHA = R2 SHA |
| Provenance | manifest khóa mọi input/config/commit SHA |

### Handoff dự kiến

```text
artifacts/handoffs/recovery-wave5-3842-riska<k>-final-<date>/
├── submission.zip
├── HANDOFF.json
├── candidate_manifest.json
├── SHA256SUMS
└── README.md
```

`k` là số fill thực tế, không ghi trước là 15.

---

## 15. Expected score và quota decision

Baseline xấp xỉ `394/1.012` correct.

| Scenario | Fill | Conversion | Expected wins | Expected score |
|---|---:|---:|---:|---:|
| Conservative | 10 | 70% | 7 | `401/1.012 ≈ 0.3962` |
| Target | 15 | 60% | 9 | `403/1.012 ≈ 0.3982` |
| Strong gate outcome | 15 | 80% | 12 | `406/1.012 ≈ 0.4012` |

Đây là planning estimate, không phải score claim. Official accuracy chỉ có sau
khi leaderboard map đúng submission ID với exact ZIP SHA.

Submission decision:

- **Upload** nếu one-shot holdout ≥80%, candidate eligibility 100%, all release
  gates PASS và protected sets không đổi.
- **Do not upload** nếu có bất kỳ protected regression, retrieval drift, unsafe
  scale, semantic-key disagreement hoặc holdout <80%.
- **Keep SAFE 3842** cho đến khi candidate mới có official score cao hơn.
- Sau official result, freeze exact candidate ZIP và record đủ 10 metrics; không
  suy QID winner từ aggregate delta.

---

## 16. Test matrix

| Scope | Required gate |
|---|---|
| Contract/enums/fingerprint | targeted unit tests + strict typecheck |
| Planner role compilation | parser/planner unit and property tests |
| Retrieval hard filtering | retrieval unit + active A6 integration tests |
| Binder equivalence/rebind | binder/compiler/executor unit tests |
| Family semantics | five family fixture suites + real A6 integration slices |
| Review workflow | leakage, identity, checksum, disagreement and seal tests |
| Full behavior | immutable 1.012-QID S0–S6 differential |
| Submission | contract validation + clean replay + deterministic R1/R2 |

Repository gates trước release:

```text
make paths-check
make snapshots-verify
make typecheck
make test-offline
make test-integration
make ci
git diff --check
```

Nếu `make ci` gặp blocker lịch sử không thuộc Wave 5, report phải ghi đúng failing
paths/tests và chạy các scope-specific mandatory gates. Không sửa hoặc giả lập
historical artifacts để làm xanh report.

---

## 17. Phase-by-phase commit discipline

Sau mỗi phase:

1. chạy targeted tests;
2. chạy full differential cần thiết;
3. inspect manifest/output, không chỉ nhìn exit code;
4. ghi metrics trước/sau và `NOT_MEASURED` nơi thiếu gold;
5. `git diff --check`;
6. commit đúng một logical change nếu PASS;
7. nếu FAIL, dừng phase, giữ artifact và báo blocker; không tự đổi kiến trúc.

Commit sequence đề xuất:

```text
docs(provenance): freeze official submission 3842
feat(evaluation): seal risk-a60 observation review scope
feat(planning): add observation role selection contract
fix(retrieval): enforce observation role compatibility
fix(binding): require semantic observation equivalence
fix(execution): validate direct risk-a families
fix(execution): validate aggregate risk-a families
feat(submission): package recovery wave5 risk-a candidate
docs(report): record observation role wave5 e2e results
```

Không commit candidate packaging nếu holdout/release gate chưa PASS.

---

## 18. Blocker và stop conditions

Dừng ngay và báo bằng chứng khi gặp một trong các điều kiện:

1. không tái tạo được exact 3842 ZIP identity;
2. Risk-A60 count/family membership không deterministic;
3. thiếu hai reviewer độc lập hoặc distinct adjudicator;
4. review packet lộ model output;
5. row/column role không thể suy ra từ source evidence;
6. A6 money observation chỉ có unsafe scale source;
7. nhiều semantic bindings khác nhau cùng sống;
8. một family làm thay đổi bất kỳ protected answer/retrieval record nào;
9. one-shot holdout <80%;
10. R1/R2 không byte-identical;
11. strict validation hoặc clean replay không PASS.

Không giải blocker bằng QID-specific patch, lowering threshold, lấy candidate đầu
tiên, hoặc copy answer từ adjudicated release vào runtime.

---

## 19. Definition of done

Wave 5 chỉ hoàn thành khi có đủ:

- immutable official identity cho submission 3842;
- sealed Risk-A60 scope và protected sets;
- 60 records có A/B/C review audit trail;
- 40-dev/20-holdout protocol không leakage;
- `ObservationRoleSpec` truyền end-to-end;
- role-aware selector và semantic-equivalent binder fail closed;
- five Risk-A families chạy theo đúng thứ tự;
- full 1.012-QID differential sau mỗi checkpoint;
- one-shot holdout ≥80%;
- 798/798 baseline answers và 1.012/1.012 retrieval records bất biến;
- candidate chỉ gồm 10–15 hoặc ít hơn các fill thực sự đủ chuẩn;
- strict validation, clean replay và deterministic ZIP PASS;
- báo cáo cuối phân biệt coverage, exactness, replay và official accuracy;
- upload-ready ZIP có exact path và SHA-256.

Nếu chưa có official leaderboard result, trạng thái cuối phải ghi:

```text
UPLOAD_READY / OFFICIAL_ACCURACY_NOT_MEASURED
```

Không được ghi “đã tăng accuracy” trước khi leaderboard xác nhận exact ZIP.
