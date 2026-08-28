# TABLE RETRIEVAL FULL RECOVERY REPORT

**Ngày:** 2026-08-28
**Trạng thái:** `COMPLETE`
**Production path:** Canonical V2
**Semantic V3:** `SHADOW_ONLY`
**Official status:** `OFFICIAL_NOT_MEASURED`

## A. Baseline

| Thuộc tính | Giá trị |
|---|---|
| Baseline commit | `a2d3ef0308612f3025cf1a78c3d5bc470d0634f6` |
| Current audit HEAD | `421c62c51b4d1bf807e3d48e3b59e6bc88bc82b5` |
| Evaluated candidate commit | `7ed2bfec309accc6a0ef5176e207630fe222a0ed` |
| Dataset | 1.012 câu; raw snapshot `ca033190f2e9e99f` |
| A6 | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Baseline ZIP SHA-256 | `a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c` |
| Full behavior | 563 answered; 449 abstained; replay 563/563; 0 error |
| Release environment | CPython 3.11.15 hash-locked cho frozen A/B; local diagnostics dùng CPython 3.13.9 |
| Official scores supplied | Tables P 0,2921; R 0,2461; F2 0,2500; MRR5 0,3360; Execution 0,2589 |
| Official provenance | `UNKNOWN`: thiếu exact ZIP/receipt mapping cho submission 3757 |

Các số official trên không được dùng làm local baseline có thể tái chấm. Repo
không có hidden gold hoặc official scorer.

## B. Root-cause map trước implementation

| Stage | Current implementation | Known failure / evidence | Impact / confidence | Cost / risk | Change boundary | Evaluation |
|---|---|---|---|---|---|---|
| Intent/entity/year/basis | `parse_intent`; alias có provenance; range semantic tách retrieval endpoints | 95 manual không chứa Q464/Q508/Q783/Q792; open-universe Q464 vẫn rỗng | Có thể catastrophic theo từng case; medium ngoài slice | Medium/high nếu mở resolver | Không rewrite; không relax open-universe gate | Boundary QIDs + parser tests |
| S1 candidate generation | Hard ticker/year filter; basis soft | Manual 95: 95/95 any-hit, 554/554 item-hit | Không phải bottleneck chính trên slice; high trong phạm vi slice | High risk nếu mở universe | Giữ nguyên | S1 recall và candidate identity |
| S2 ranking | BM25 cột + period/unit/basis/code/clean bonus | Hit@10 86/95; unit hit gold 0,332 vs non-gold 0,630; period gần không phân tách | Rank loss 8/95; medium | Ablation rẻ, promotion risk medium | Chỉ A/B từng bonus; không tune nhiều weight cùng lúc | P/R/F2/MRR5, flips, mean rank |
| S3 | `IdentityReranker`, top 10 | Không có model; learned model thiếu held-out labels | Có room nhưng chưa đủ training authority | High leakage/model risk | Không promote model | Untouched held-out bắt buộc |
| Output N | `clamp(targets × retrieval_years, 1, 10)` | `OUTPUT_N_LOSS=23/95`; policy hit 50/95 | Bottleneck local lớn nhất; high trên slice | Precision risk cao | Không promote margin/fixed N trên dev 95 | P/R/F2, mean/max tables |
| Answer pool | Top 50 S2 tables | Có thể thiếu operand ngoài top 50 | Một phần 40 `UNBOUND_OPERANDS`; medium | Pool expansion tăng cost/noise | Giữ 50 trong recovery này | Bind reason distribution |
| Metric/operand resolution | Generic selector + narrow deterministic routes | 177 multi-entity unsupported; nhiều câu composition phức tạp, nhưng có direct-fact subtype | Execution ceiling lớn; high về count, unknown về correctness | Blanket support rất cao | Chỉ direct reported fact, one year, exact metric policy | Targeted source evidence + replay |
| Binding | `QuestionSelector`; success thay refs bằng evidence tables | 10 binding losses; 5 likely mismatch (305/342/354/636/780) | Direct Table F2 mechanism; medium | Existing-answer regression high | Không union mù; không sửa 5 case nếu chưa có independent answer/evidence labels | Per-QID trace + exact table evidence |
| Evidence/final refs | Exact bound tables khi answer OK; retrieval top-N khi abstain | Binding replacement có thể mất retrieval gold | 10/95 loss; high về mechanism | Precision/recall trade-off | Giữ evidence-authoritative contract | Final refs vs binding/output |
| Serialization | `doc|1-based-line`, strict validator | 0 serialization loss trên manual 95; server normalization unknown | Low local / unknown official | Low | Không đổi locator | Validator + package diff |
| Official scorer | Hidden | Không có scorer/gold/receipt | Chặn official causal claim; very high | External blocker | Không giả lập | `OFFICIAL_NOT_MEASURED` |

Phân biệt đại lượng:

```text
Candidate Recall ≠ Ranking Recall ≠ Output-N Recall ≠ Binding Recall
                 ≠ Serialization correctness ≠ Execution Accuracy
```

## C. Backlog ROI đã khóa

1. **P0 measurement:** giữ immutable baseline, per-QID comparator, manifests,
   checksum và submission ledger. Không gọi measurement work là quality gain.
2. **P1 unit/period ablation:** kiểm định hai signal có evidence yếu/ngược chiều,
   mỗi experiment chỉ đổi một bonus.
3. **P2 deterministic direct-fact aggregate:** mở đúng một subtype
   multi-entity average có metric exact, một năm, money unit và unique operand.
4. **P3 N/binding:** chỉ giữ diagnostic cũ; chưa promote vì 95 câu là development
   gold và promotion-eligible table gold hiện bằng 0.
5. **P4 composition/open-universe/V3:** không mở trong change này vì blast radius
   và thiếu gold độc lập.

## D. Preregistered experiment matrix

| ID | Change duy nhất | Hypothesis / mechanism | Metrics | Regression guard | Promotion rule |
|---|---|---|---|---|---|
| E0 | Frozen baseline | Đối chứng | Full counts, replay, refs, ZIP | SHA + manifests | N/A |
| E1 | `unit bonus: 0.15 → 0` | Unit kind quá coarse nên đang nâng non-gold | Manual P/R/F2/MRR5, flips | S1 unchanged; no new top-10 losses guard reported | Diagnostic only; không promote từ dev 95 |
| E2 | `period bonus: 0.35 → 0` | Period hit gần constant, có thể chỉ thêm noise | Manual P/R/F2/MRR5, flips | S1 unchanged; compare E0 only | Diagnostic only; không promote từ dev 95 |
| E3 | Direct multi-entity average: `chi phí lãi vay` | Q954 là one-year, exact reported-money metric; mỗi entity có thể bind một unique operand rồi average | Abstain→answer, exact rows/tables, replay | Existing 563 scorer-facing outputs unchanged; fail closed nếu thiếu entity/basis/period/unit/metric | Candidate only nếu targeted source audit + full E2E sạch; official quality vẫn NOT_MEASURED |
| E4 | Combined candidate | Chỉ E3 được phép vào candidate; E1/E2 không đổi production | Full 1.012 diff, answer/ref changes, replay, validator, determinism | 0 existing-answer/table regression; no errors | Quyết định cuối sau full run |

Gold 95 đã tham gia tạo hypothesis nên E1/E2 không có quyền promote. E3 không
dùng table gold để chọn QID; route được giới hạn bằng semantic contract. Dù vậy,
không có independent answer gold cho subtype nên official quality vẫn chưa đo.

## E. Implemented changes

Candidate E3 được triển khai như một **opt-in experiment, mặc định tắt**:

- `entity_average` nhận diện metric exact `chi phí lãi vay`, chỉ chấp nhận leaf
  `Chi phí lãi vay`/`Trong đó: Chi phí lãi vay` thuộc `income_statement`;
  balance payable note và cash-flow adjustment bị loại.
- Các expense operand được đưa về economic magnitude bằng `abs()` trước khi
  tính trung bình. Route vẫn yêu cầu nhiều entity duy nhất, đúng một năm,
  money unit tương thích, cùng basis, unique physical cell và không có formula,
  comparison hoặc filtering cue.
- Canonical V2 có cờ
  `--experimental-direct-interest-average`; không truyền cờ thì Q954 tiếp tục
  abstain như baseline. Manifest ghi rõ trạng thái cờ.
- Unit test khóa exact metric/statement policy, sign normalization và default-off.
  Integration test khóa cả baseline abstain lẫn candidate answer, table IDs,
  locators, query và replayable evidence của Q954.

E1/E2 chỉ thêm profile evalkit `manual_unit_off` và `manual_period_off`; không
đổi production retrieval config.

## F. Experiments

### F1. Retrieval bonus ablations

| Metric | E0 manual | E1 unit=0 | Delta E1 | E2 period=0 | Delta E2 |
|---|---:|---:|---:|---:|---:|
| F2@N* | 0,3035 | 0,3095 | +0,0060 | 0,2899 | -0,0136 |
| hit@N* | 0,5263 | 0,5368 | +0,0105 | 0,5158 | -0,0105 |
| F2@1, `|gold|=1` | 0,3333 | 0,3333 | 0 | 0,3030 | -0,0303 |
| hit@1 | 0,3474 | 0,3474 | 0 | 0,3053 | -0,0421 |
| hit@3 | 0,6842 | 0,6842 | 0 | 0,6211 | -0,0632 |
| hit@10 | 0,9053 | 0,9053 | 0 | 0,8842 | -0,0211 |
| MRR toàn top-50 | 0,5497 | 0,5519 | +0,0022 | 0,5073 | -0,0424 |

E1 không tạo top-10 win/loss nào; cải thiện chỉ xuất hiện ở thứ tự sâu và
proxy F2@N* trên development gold. Vì `unit_hit` còn là feature coarse, có tỷ
lệ trên non-gold cao hơn gold, kết quả này không đủ quyền promotion. **Giữ
unit bonus 0,15.**

E2 làm Q774 từ hạng 7 xuống 17 và Q886 từ hạng 5 xuống 15, đồng thời giảm mọi
metric chính. **Giữ period bonus 0,35.**

Artifacts:

- baseline: `artifacts/runs/retrieval/evalkit/metrics_manual_9e7a2cb0c56b510f.json`;
- unit-off: `artifacts/runs/retrieval/evalkit/metrics_manual_unit_off_2b70a6c9d6f6d3ce.json`;
- period-off: `artifacts/runs/retrieval/evalkit/metrics_manual_period_off_4f0f161eb1322f12.json`.

Đây là diagnostic trên 95/1.012 câu, không phải official measurement.

### F2. Direct multi-entity interest-expense average

Q954 được bind tới ba direct P&L facts của năm 2018:

| Entity | Evidence table/locator | Raw VND | Normalized tỷ đồng |
|---|---|---:|---:|
| DPM | `DPM_financial_statements_2019_consolidated|337` | 62.586.468.519 | 62,586468519 |
| VIF | `VIF_financial_statements_2018_consolidated|300` | 9.589.605.241 | 9,589605241 |
| HSG | `HSG_financial_statements_2018_consolidated|238` | -811.669.226.449 | 811,669226449 |

Candidate tính economic expense magnitude:

```text
(abs(62.586468519) + abs(9.589605241) + abs(-811.669226449)) / 3
= 294.61510006966665 tỷ đồng
```

Các table IDs lần lượt là `feb5f4e440a5c1e0`, `8b7c2752e32f8112`,
`eed2f40df8900789`. Payable-note/cash-flow rows cùng tên không được phép bind.
Source audit và replay chứng minh phép tính có thể thi hành; chúng không thay
thế independent answer gold.

## G. Full E2E và per-QID regression

Hai run độc lập trên CPython 3.11.15, dependency hash-lock khớp, source commit
và snapshot giống nhau:

- A: `table-retrieval-full-recovery-7ed2bfe-a-20260828-01`;
- B: `table-retrieval-full-recovery-7ed2bfe-b-20260828-01`.

| Gate | A | B | Kết quả |
|---|---:|---:|---|
| Questions | 1.012 | 1.012 | PASS |
| Answered / abstained | 564 / 448 | 564 / 448 | PASS |
| Validator errors / warnings | 0 / 0 | 0 / 0 | PASS |
| Replay matched / executed / errors | 564 / 564 / 0 | 564 / 564 / 0 | PASS |
| records SHA-256 | `c23a68f…783164` | `c23a68f…783164` | byte-identical |
| ZIP bytes | 1.031.950 | 1.031.950 | identical |
| ZIP SHA-256 | `587b83b8…0ecf7` | `587b83b8…0ecf7` | byte-identical |

Determinism gate:
`artifacts/runs/evaluation/table-retrieval-full-recovery-7ed2bfe-20260828-01/determinism_gate.json`.

Exact baseline/candidate comparator trên 1.012 QID:

| Classification | Count | QID / diễn giải |
|---|---:|---|
| `UNCHANGED` | 1.011 | Mọi scorer-facing field byte-equivalent |
| `CHANGED_UNMEASURED` | 1 | Q954: abstain → answer 294,6151000697 |
| `NEW_REGRESSION` | 0 | Không có |
| `NEW_TABLE_REGRESSION` | 0 | Không có |
| `ANSWER_LOSS` / `EXECUTION_LOSS` | 0 / 0 | Không có |
| Official `NEW_WIN` / `TABLE_WIN` / `ANSWER_WIN` / `EXECUTION_WIN` | 0 | Không được gắn nhãn win khi thiếu independent gold |

Q954 thay toàn bộ output hợp lý cho một abstain→answer: status, answer, refs,
evidence, query, confidence và reason. Candidate ZIP vì thế khác baseline ZIP
`a96ecc3c…00445c`. Comparator gắn đúng nhãn `gold unavailable`, không suy diễn
official win. Artifact đầy đủ:
`artifacts/runs/evaluation/table-retrieval-full-recovery-compare-7ed2bfe-20260828-01/`.

Boundary cases được giữ nguyên:

| QID | Baseline và candidate |
|---:|---|
| 464 | `ABSTAIN: NO_RETRIEVED_TABLE` |
| 508 | `ABSTAIN: MULTI_ENTITY_OPERATION_NOT_SUPPORTED` |
| 783 | `ABSTAIN: POLICY:CROSS_BASIS_OPERANDS` |
| 792 | `ABSTAIN: POLICY:ENTITY_DIFFERENCE_METRIC_DRIFT` |

## H. Retrieval / execution metrics

| Metric | Baseline | Candidate | Status |
|---|---:|---:|---|
| Answered | 563 | 564 | measured coverage +1 |
| Abstained | 449 | 448 | measured -1 |
| `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` | 177 | 176 | measured -1 |
| Mean relevant tables | 2,5385375494 | 2,5385375494 | unchanged |
| Max relevant tables | 10 | 10 | unchanged |
| Replay | 563/563 | 564/564 | PASS |
| Local table P/R/F2 | `NOT_MEASURED` | `NOT_MEASURED` | không có promotion-eligible table gold |
| Answer accuracy | `NOT_MEASURED` | `NOT_MEASURED` | không có independent answer gold |
| Execution accuracy | `NOT_MEASURED` | `NOT_MEASURED` | replay chỉ đo reproducibility, không đo correctness |
| Official score delta | `NOT_MEASURED` | `NOT_MEASURED` | không có scorer/receipt |

Tests trên release environment:

- `make ci`: 2.096 passed, 42 skipped, 29 deselected;
- `make test-integration`: 22 passed, 2.145 deselected;
- semantic route mặc định: 684/1.012 eligible, 328 gaps, không đổi baseline;
- `make test-historical`: 7 failures chỉ vì thiếu authentic legacy ZIP
  `submission_C1R_LOCAL.zip`, `submission_P0G2.zip` và H0 determinism report;
  không phải failure của active Canonical V2 gate.

## I. Official status

```text
OFFICIAL_NOT_MEASURED
```

Không có hidden table/answer gold, official scorer hoặc receipt liên kết exact
candidate ZIP. Vì vậy các số Tables P/R/F2/MRR5 và Execution Accuracy của
candidate không thể được báo cáo trung thực. Submission không được upload.

## J. Final decision

```text
KEEP_BASELINE
```

Lý do:

1. Candidate kỹ thuật đạt: source-grounded, fail-closed, 1.012/1.012,
   validator/replay sạch, A/B byte-deterministic và không đổi 1.011 QID.
2. Candidate tạo một coverage gain có cơ sở cho Q954, nhưng chưa có independent
   gold để chứng minh answer/table correctness hoặc official metric uplift.
3. Strict acceptance không cho phép đổi production chỉ dựa trên execution
   success hay development proxy. Comparator vì thế trả `BLOCKED` cho
   promotion, và release decision giữ baseline.
4. Implementation được giữ sau cờ opt-in mặc định tắt để có thể adjudicate lại;
   Canonical V2 mặc định và Semantic V3 `SHADOW_ONLY` không đổi.

Điều kiện mở lại promotion: adjudicate độc lập Q954 (answer và exact evidence),
đưa case vào promotion-eligible registry, sau đó chạy lại cùng full A/B gate.
