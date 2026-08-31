# ObservationRoleSpec + SelectorSpec Risk-A60 — E2E Execution Report

**Ngày chạy:** 2026-08-31  
**Branch:** `mentor-grounded-v6`  
**SAFE baseline:** submission `3842`  
**Official Answer/Execution Accuracy:** `0.3893`  
**Kết luận release:** `BLOCKED / DO NOT UPLOAD`  
**Candidate ZIP:** không tạo

## 1. Executive conclusion

Phần kỹ thuật từ freeze baseline đến full shadow S1–S6 đã được triển khai và
chạy trên đủ `1.012` QID. Các contract role, hard selector, strict semantic
binding và completeness gate cho năm family đều đã có test và được tách bằng
policy opt-in để đo từng checkpoint.

Không package candidate vì ba bằng chứng độc lập đều chặn release:

1. S6 emit `0/60` QID trong mutation pool Risk-A; không có fill nào đủ điều
   kiện để overlay lên 3842.
2. Review A, review B và adjudication C đều mới là packet trống: `0/60` hoàn
   tất ở mỗi slot. Holdout correctness vì vậy là `NOT_MEASURED`, không đạt gate
   `>=16/20`.
3. Full shadow còn ghi `6` typed-to-Pandas mismatches, đều là rejected
   alternatives tại Q522. Promotion manifest yêu cầu `0`.

Submission 3842 vẫn là SAFE artifact. SHA-256 được kiểm lại sau toàn bộ run và
không đổi:

```text
2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76
```

Không có claim tăng accuracy. Các số dưới đây là coverage/replay diagnostics,
không phải official score và không phải exact correctness.

## 2. Baseline và protected scope

| Check | Kết quả |
|---|---:|
| ZIP identity | PASS |
| Unique records | `1.012/1.012` |
| Baseline executable | `798` |
| Baseline abstention | `214` |
| Clean replay baseline | `798/798`, 0 error, 0 mismatch |
| P-answer | `798` |
| P-retrieval | `1.012` |
| W5 Risk-A mutation scope | `60` |
| Out-of-scope abstention | `154` |
| Scope split | `40 development + 20 holdout` |

Baseline artifact:

```text
artifacts/official/submission-3842/submission.zip
```

Scope fingerprint:

```text
configs/evaluation/recovery_wave5_riska60_scope_3842_v1.json
SHA-256: 9d77ec98fd7a1c2562ec94e4929d023dfbb0552560515c187b20593226d44899
```

Shadow runs là artifact riêng và không ghi đè submission. Vì không build
overlay, answer/query/evidence/CSV của `798/798` baseline records và retrieval
refs của `1.012/1.012` records vẫn nguyên trạng.

## 3. Implementation delivered

### 3.1 Observation role contract

Đã truyền role metadata qua semantic AST, planner request, retrieval candidate,
fact, trace và fingerprint:

- `metric_id` và `source_metric_id/source_metric_code`;
- exact row label/path, row UID và row role;
- column path/UID và column role;
- basis, period và period role;
- sign mode;
- scale exponent và scale source;
- entity membership.

Role classifier có version tại:

```text
configs/semantic/observation_roles_v1.yaml
```

### 3.2 Metric-aware selector

Candidate hard-incompatible bị loại trước scoring. Trace có terminal reasons và
reject count cho source metric, row, column, period, scale và entity. Candidate
score không thể bù một hard mismatch.

### 3.3 Joint binding

Semantic equivalence strict đã bao gồm physical/semantic observation identity.
Hai candidate cùng số nhưng khác row/source/column role không còn bị collapse.
Top-3 rebind deterministic được giữ nguyên; không thử candidate thứ tư.

### 3.4 Family completeness

Đã triển khai fail-closed validation cho:

1. direct lookup;
2. direct ratio;
3. two-period difference;
4. single-metric sum;
5. single-metric average.

Các gate kiểm cardinality, member-domain completeness, distinct observations,
metric/basis/period consistency, total-child mixing, column roles và money scale
source.

### 3.5 Select-at-arg

Code gate cho complete rank domain, unique selected key, exact projected domain
và selected-key consensus đã được test. Tuy nhiên feature này không được bật
trong S1–S6 và 14 Risk-B extrema không được đưa vào candidate, vì Phase 6 chỉ
được mở sau khi Risk-A review/holdout PASS.

## 4. Commit trail

| Commit | Nội dung |
|---|---|
| `c580bf4` | freeze official submission 3842 |
| `f06fa57` | prepare Risk-A60 review scope |
| `0afb64b` | seal deterministic 40/20 split |
| `62012fc` | add observation role contract |
| `fa6e1fb` | enforce role-aware retrieval compatibility |
| `be3df1a` | require semantic observation equivalence |
| `c9c745d` | validate five Risk-A family contracts |
| `965a53f` | add select-at-arg semantic-key gates, kept off |
| `0b1c544` | isolate S1–S6 runtime policies |
| `5faf018` | add reproducible shadow differential report |

Mọi S1–S6 run được tạo từ clean commit
`0b1c544e8b6cad9217843d996e161686bd38cdff`.

## 5. Full 1.012-QID shadow results

S0 là exact submission 3842, không phải Semantic V4 shadow count. S1–S6 là
V4-only diagnostics nên không được so `OK` trực tiếp với 798 baseline answers để
suy accuracy.

| Run | Thay đổi bật thêm | OK | Abstain | No verified | Disagreement | Risk-A OK | Replay mismatch |
|---|---|---:|---:|---:|---:|---:|---:|
| S0 | exact 3842 | 798 executable | 214 | n/a | n/a | n/a | 0 |
| S1 | role contract/metadata only | 199 | 813 | 392 | 421 | 1/60 | 6 |
| S2 | role inference + hard selector | 106 | 906 | 683 | 223 | 0/60 | 6 |
| S3 | strict binding equivalence | 137 | 875 | 683 | 192 | 0/60 | 6 |
| S4 | lookup + ratio completeness | 140 | 872 | 683 | 189 | 0/60 | 6 |
| S5 | difference + sum completeness | 132 | 880 | 705 | 175 | 0/60 | 6 |
| S6 | average completeness | 128 | 884 | 727 | 157 | 0/60 | 6 |

S6 policy:

```text
configs/semantic/search_v4_wave5_s6_average.yaml
SHA-256: 81868644a94431aa2e89c85b2f269c903ac6a270d5ef047a5be7ee377c89c7ce
status: SHADOW_UNCALIBRATED
production_eligible: false
```

### 5.1 Risk-A60 at S6

| Family | Total | OK | No verified | Disagreement |
|---|---:|---:|---:|---:|
| Direct lookup | 7 | 0 | 5 | 2 |
| Direct ratio | 9 | 0 | 9 | 0 |
| Two-period difference | 11 | 0 | 11 | 0 |
| Single-metric sum | 3 | 0 | 2 | 1 |
| Single-metric average | 30 | 0 | 30 | 0 |
| **Total** | **60** | **0** | **57** | **3** |

Ba QID tạo được verified alternatives nhưng không có answer consensus:

| QID | Family | Alternatives |
|---:|---|---|
| 151 | direct lookup | `4.565.000`, `542.634`, `81.426` |
| 267 | direct lookup | `6.501.084`, `3.177`, `4.954.665` |
| 922 | single-metric sum | `6.56794224915`, `6.68340318722`, `2.43446938652` |

Plan yêu cầu nhiều semantic bindings khác nhau cùng sống phải abstain, nên cả ba
không candidate-eligible.

### 5.2 S1 → S6 differential

| Cohort | Status changed | Output fingerprint changed | OK gained | OK lost |
|---|---:|---:|---:|---:|
| All 1.012 | 139 | 463 | 34 | 105 |
| P-answer 798, shadow behavior | 133 | 445 | 32 | 101 |
| Risk-A60 | 1 | 4 | 0 | 1 |
| Out-of-scope 154, shadow behavior | 5 | 14 | 2 | 3 |

Đây là thay đổi trong shadow outputs, không phải mutation của submission 3842.
Nó cho thấy không thể bật behavior mới toàn cục: strict selector làm mất 101
shadow emits trên P-answer giữa S1 và S6. Recover-only overlay vẫn bảo vệ
baseline, nhưng Risk-A60 lại không tạo được fill nào.

Differential artifact:

```text
artifacts/runs/evaluation/recovery-wave5-shadow-differential-20260831-v1/report.json
SHA-256: 6840922fe6009880e2a3e649a5ca777320a8240726bdbfc8944431e73be5e586
measurement_scope: COVERAGE_REPLAY_ONLY_NOT_ACCURACY
```

## 6. Root-cause audit of the 60-QID scope

Failure category dưới đây tính theo record và có thể overlap vì một record có
nhiều parse/binding alternatives:

| Failure layer | Records affected |
|---|---:|
| Parser | 39 |
| Binding/retrieval | 12 |
| Typed execution | 7 |
| Family verifier | 3 |
| Has successful alternatives but no consensus | 3 |

Các reason lớn nhất:

- `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION`: 23 failures;
- `DIMENSION_MISMATCH:money:percent`: 15;
- direct-operation metric ambiguity: 4;
- unknown scale: 3;
- unresolved binary operands: 3;
- temporal-filter selected expression ambiguity: 3;
- average-domain verifier phát hiện duplicate/metric/period/column-role mismatch.

Điều này cho thấy nhãn inventory `direct_ratio`, `two_period_difference` hay
`single_metric_average` chỉ mô tả repair class/output shape, không bảo đảm câu
hỏi là một phép toán đơn giản. Ví dụ Q406/Q408/Q438 chứa filter, ratio và growth
trước average; Q430 chứa select-at-arg; Q567 được gắn difference nhưng thực tế là
filter rồi sum. Do đó một phần đáng kể của “Risk-A60” vẫn là compositional
semantics, trong khi plan tuyên bố complex composition là non-goal.

Không sửa bằng QID-specific conditions và không hạ parser/verifier gate. Muốn
tiếp tục phải re-triage scope bằng AST complexity/source evidence hoặc mở một
phase compositional riêng; cả hai đều là thay đổi phạm vi cần phê duyệt mới.

## 7. Independent review and holdout

| Review gate | Required | Actual | Status |
|---|---:|---:|---|
| Reviewer A | 60 | 0 | BLOCKED |
| Reviewer B | 60 | 0 | BLOCKED |
| Adjudicator C | 60 | 0 | BLOCKED |
| Distinct reviewer identities | 3 | 0 | BLOCKED |
| Holdout exactness | >=16/20 | NOT_MEASURED | BLOCKED |
| Direct-group exactness | >=70% | NOT_MEASURED | BLOCKED |
| Aggregate-group exactness | >=70% | NOT_MEASURED | BLOCKED |

Review packet vẫn prediction-blind, không có model answer/AST/candidate score,
nhưng chưa được con người điền:

```text
artifacts/runs/evaluation/recovery-wave5-riska60-review-20260831-v1/
status: AWAITING_INDEPENDENT_REVIEW
```

Agent không tự đóng vai ba reviewer vì sẽ phá independence, leak model context và
làm vô hiệu one-shot holdout.

## 8. Verification matrix

| Gate | Kết quả |
|---|---|
| Targeted Wave 5 unit tests | PASS, `25` |
| `make paths-check` | PASS |
| `make snapshots-verify` | PASS |
| `make typecheck` | PASS, `119 source files` |
| `make test-offline` | PASS, `2446 passed, 42 skipped, 29 deselected` |
| `make test-integration` | PASS, `22 passed, 2495 deselected` |
| `git diff --check` | PASS |
| `make ci` lint | PASS |
| `make ci` typecheck | PASS |
| `make ci` docs-check | FAIL: 15 missing historical artifact links |
| Full S1–S6 record shape | PASS, `1.012` unique mỗi run |
| S6 replay mismatch gate | FAIL, `6` tại Q522 alternatives |
| Review/holdout | BLOCKED |
| Candidate determinism R1/R2 | NOT RUN; không có eligible fill |
| Strict submission validation | NOT RUN; không build submission |

`make ci` bị dừng bởi 15 broken links có sẵn trong bốn báo cáo ngày
2026-08-29. Không tạo artifact lịch sử giả và không sửa ngoài phạm vi Wave 5.
Offline tests được chạy độc lập và PASS đầy đủ như bảng trên.

## 9. Release decision

Không tạo candidate và không có đường dẫn bài nộp Wave 5. Việc tạo ZIP lúc này
sẽ vi phạm các gate:

- `0/60` Risk-A emit an toàn;
- `0/60` A/B/C review;
- holdout `NOT_MEASURED`, không đạt 80%;
- replay mismatch `6`, không đạt 0;
- global shadow có protected/out-of-scope behavior drift lớn.

Artifact duy nhất an toàn để nộp lại vẫn là:

```text
/Users/andinh307/Documents/Dagoras-R2AI/text2pandas-main/text2pandas/artifacts/official/submission-3842/submission.zip
```

Không nên dùng S6 output để thay Answer layer 3842 và không nên upload một
candidate retrieval-identical nhưng không có fill mới.

## 10. Required next action before resuming release

1. Ba người độc lập hoàn tất A/B/C review với source evidence cho đúng 60 QID.
2. Trước khi mở holdout, audit lại family labels theo AST complexity. Nếu giữ
   non-goal “không complex composition”, loại/re-scope các câu thực sự
   compositional bằng một versioned scope mới; không sửa scope hiện tại im lặng.
3. Dùng dev40 để sửa các lỗi tổng quát theo thứ tự parser → metric/source →
   role binding → execution; không QID patch.
4. Freeze code/config mới rồi mới mở holdout một lần.
5. Chỉ build recover-only overlay khi có ít nhất một output exact, consensus,
   replay-clean và toàn bộ gate release PASS.

Cho tới khi các điều kiện đó tồn tại, trạng thái chính xác là:

```text
SHADOW_IMPLEMENTED
CORRECTNESS_NOT_MEASURED
PROMOTION_BLOCKED
NO_SUBMISSION_CANDIDATE
SAFE_BASELINE_3842_PRESERVED
```
