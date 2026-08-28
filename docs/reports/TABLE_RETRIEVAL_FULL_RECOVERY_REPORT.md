# TABLE RETRIEVAL FULL RECOVERY REPORT

**Ngày:** 2026-08-28
**Trạng thái:** `IN_PROGRESS`
**Production path:** Canonical V2
**Semantic V3:** `SHADOW_ONLY`
**Official status:** `OFFICIAL_NOT_MEASURED`

## A. Baseline

| Thuộc tính | Giá trị |
|---|---|
| Baseline commit | `a2d3ef0308612f3025cf1a78c3d5bc470d0634f6` |
| Current audit HEAD | `421c62c51b4d1bf807e3d48e3b59e6bc88bc82b5` |
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

Sẽ cập nhật sau khi artifacts được sinh.

## G. Full E2E và per-QID regression

Sẽ cập nhật sau full 1.012 run.

## H. Retrieval / execution metrics

Sẽ cập nhật sau full run, validator và replay.

## I. Official status

```text
OFFICIAL_NOT_MEASURED
```

## J. Final decision

Sẽ chọn đúng một trong `PROMOTE`, `KEEP_BASELINE`, `ROLLBACK` sau các gate.
