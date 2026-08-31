# SAFE RECOVERY 3821 — END-TO-END IMPLEMENTATION REPORT

**Ngày thực hiện:** 2026-08-30

**Branch:** `mentor-grounded-v6`

**Baseline official:** submission 3821, Answer/Execution Accuracy `0.3399`

**Kết luận release:** `READY_FOR_MANUAL_LEADERBOARD_UPLOAD_EXPERIMENTAL`

## 1. Kết quả cuối

Candidate tốt nhất là `baseline 3821 + 23 source-adjudicated abstention fills`:

```text
artifacts/handoffs/safe-3821-reviewed23-final-20260830/submission.zip
```

SHA-256:

```text
87d6c6e9da03057994427816599a02a7a1c67b296e2d5252b5b0a2b560086476
```

Các gate quan trọng:

| Gate | Kết quả |
|---|---:|
| Records | 1.012/1.012 |
| Baseline answer/query/evidence được giữ nguyên | 712/712 |
| Baseline retrieval được giữ nguyên | 1.012/1.012 |
| Baseline CSV payload được giữ nguyên | 1.107/1.107 |
| Answer-layer QID thay đổi | đúng 23 QID đã review |
| Retrieval-layer QID thay đổi | 0 |
| Competition validation | 0 error, 554 expected abstention warnings |
| Clean replay | 735/735 matched, 0 error |
| Unresolved còn lại | 277 |
| Build R1/R2 | byte-identical |
| ZIP integrity | PASS |

Candidate không được gắn nhãn production-promoted vì chưa có independent gold
cho 23 câu và chưa có điểm leaderboard. Nó là candidate thủ công có provenance,
fail-closed và có thể rollback về exact ZIP 3821.

## 2. Baseline đã freeze

Exact ZIP do người dùng xác nhận đã upload thành submission 3821:

```text
artifacts/official/submission-3821/submission.zip
SHA-256: 91089cec71f0aa409b8543e5c0201c17ce7b1482b8d73f8c86f62004737ab918
```

Baseline có:

- 1.012 records;
- 712 câu có evidence/query thực thi được;
- 300 abstentions;
- 1.107 CSV members;
- clean replay 712/712 trên emitted records.

Official metrics do người dùng cung cấp:

| Metric | Submission 3821 |
|---|---:|
| Answer Accuracy | 0.3399 |
| Execution Accuracy | 0.3399 |
| Tables F2-Macro | 0.3151 |
| Tables Precision | 0.2797 |
| Tables Recall | 0.3571 |
| Tables MRR@5 | 0.3939 |
| Docs F2-Macro | 0.7361 |
| Docs Precision | 0.6534 |
| Docs Recall | 0.7952 |
| Docs MRR@5 | 0.8162 |

Source commit/config/leaderboard receipt của baseline vẫn chưa được truy ngược
đầy đủ. Exact artifact và official row đã được ghi trong
[`submission_ledger_v1.json`](../../configs/evaluation/submission_ledger_v1.json)
và provenance record tương ứng.

## 3. Phạm vi và chính sách bảo toàn

Đúng theo plan, candidate chỉ được phép đi theo đường:

```text
exact baseline 3821
  + source-adjudicated fills trên baseline abstentions
  + giữ nguyên retrieval
  + giữ nguyên toàn bộ emitted answer/query/evidence hiện có
```

Không thực hiện:

- không chạy lại MODEL_GOLD;
- không dùng MODEL_GOLD làm runtime prediction;
- không áp dụng 250 answer replacements của run mentor;
- không sửa retrieval;
- không thay embedding, reranker hoặc model;
- không hạ validator;
- không sửa gold để khớp prediction;
- không thay một câu nào trong 712 baseline emitted records.

## 4. Tách gate `complete` và `competition`

Trước thay đổi, validator nội bộ coi mọi abstention là release error. Điều này
mâu thuẫn với exact artifact 3821 đã được leaderboard chấp nhận. Hai profile đã
được tách rõ:

- `complete`: mục tiêu nội bộ 1.012/1.012 câu đều có evidence/query;
- `competition`: abstention được ghi thành warning, nhưng mọi lỗi cấu trúc,
  locator, query safety, CSV, replay của emitted records vẫn là blocker.

Candidate cuối:

| Profile | Validation | Replay | Kết luận |
|---|---:|---:|---|
| competition | 0 error, 554 warning | 735/735, 0 error | PASS |
| complete | 554 error | 735/735, 277 no-evidence/error | FAIL expected |

`complete` không bị làm yếu. Candidate chỉ được đóng gói với profile
`competition`, còn thiếu coverage vẫn được báo công khai.

## 5. Audit 46 QID

Ledger đầy đủ nằm tại
[`grounded_v6_recovery_review_3821_v1.json`](../../configs/evaluation/grounded_v6_recovery_review_3821_v1.json).
Mỗi QID được kiểm theo bảy trục bắt buộc:

```text
metric, entity, period, basis, operation, unit, source
```

### 5.1 Cohort `PROMOTED_RECOVERY`

| Trạng thái | Số lượng | QID |
|---|---:|---|
| PASS_SOURCE_PROVEN | 17 | 99, 363, 369, 370, 371, 375, 380, 386, 387, 395, 400, 439, 475, 479, 523, 570, 695 |
| REJECT | 7 | 151, 379, 407, 447, 448, 917, 942 |

Các lỗi quan trọng bị gate bắt:

- Q151 chọn tiền gửi không kỳ hạn thay vì tiền gửi tiết kiệm;
- Q379/Q447/Q448 thiếu tăng trưởng doanh thu và median filter;
- Q407 không dịch sang thời điểm cuối năm kế tiếp;
- Q917 dùng tổng nợ phải trả cho VSC thay vì phải trả người bán ngắn hạn;
- Q942 thiếu EIB và HDB trong phép trung bình ba ngân hàng.

Kết luận: nhãn tự động `PROMOTED_RECOVERY` chỉ đạt 17/24 sau source audit.

### 5.2 Cohort `SHADOW_OK`

| Trạng thái | Số lượng | QID |
|---|---:|---|
| PASS_SOURCE_PROVEN | 6 | 494, 520, 530, 545, 816, 975 |
| REJECT | 15 | 267, 412, 465, 495, 590, 652, 700, 724, 826, 883, 949, 952, 967, 979, 999 |
| AMBIGUOUS | 1 | 525 |

Các lỗi phổ biến gồm metric gần nghĩa nhưng sai, thiếu entity, sai basis
consolidated/separate, dùng prior-period column, và xử lý sai dấu của provision.
Q525 được giữ fail-closed do chưa giải quyết độc lập sign/balance convention.

## 6. Hai candidate bất biến

| Candidate | Fills | Executable | SHA-256 | Mục đích |
|---|---:|---:|---|---|
| SAFE-17 | 17 | 729 | `4f7c397f942843eb8e7a73ab2ed1aa9f855c7b0ec67897cfef8070cf3fecbab5` | conservative backup |
| REVIEWED-23 | 23 | 735 | `87d6c6e9da03057994427816599a02a7a1c67b296e2d5252b5b0a2b560086476` | best candidate |

Mỗi candidate được build hai lần độc lập. R1 và R2 có SHA-256 giống nhau.

Candidate tốt nhất thêm đúng các QID:

```text
99, 363, 369, 370, 371, 375, 380, 386, 387, 395, 400,
439, 475, 479, 494, 520, 523, 530, 545, 570, 695, 816, 975
```

## 7. Lỗi scale được phát hiện trong E2E

Build đầu của candidate 23 chỉ replay 732/735. Gate đã dừng đóng gói và xác
định ba QID lỗi: 530, 816 và 975.

Nguyên nhân là evidence materializer ghi `canonical_value`, trong khi generated
query đã tự nhân `10^scale_exponent`. Điều này áp dụng scale hai lần. Fix sử dụng
`raw_value`, đúng với `_materialize_synthesized_result` của Grounded V5.

Sau fix:

- Q530 replay đúng `131.188339`;
- Q816 replay đúng `14.383448`;
- Q975 replay đúng `1261.80261206275`;
- candidate 23 đạt 735/735 matched.

Không có candidate lỗi nào được giữ lại trong handoff.

## 8. Differential và bảo toàn

So với exact baseline 3821:

- 712/712 answer/query/evidence tuples cũ giống hệt;
- 1.012/1.012 `relevant_tables` và `relevant_docs` giống hệt;
- 1.107/1.107 baseline CSV payloads giống byte;
- chỉ 23 baseline abstentions đổi answer/query/evidence;
- không có answer replacement;
- không có retrieval overlay;
- không có QID ngoài ledger thay đổi.

Do retrieval không đổi, candidate được thiết kế để giữ nguyên official retrieval
profile của submission 3821. Điều này là artifact-level preservation, không phải
cam kết rằng leaderboard sẽ trả về chính xác cùng số làm tròn.

## 9. Local proxy

Proxy report:

[`safe-3821-reviewed23-final-20260830-proxy.json`](../../artifacts/reports/evaluation/safe-3821-reviewed23-final-20260830-proxy.json)

Scope local:

- answer gold: 31 QID;
- retrieval gold: 95 QID;
- classification: `LOCAL_DEVELOPMENT_PROXY_NOT_OFFICIAL`.

Kết quả candidate so với baseline là 0 win, 0 loss trên answer gold và cả mười
proxy metrics không regression. Tuy nhiên 23 QID mới không giao với 31 answer
gold QID, nên proxy này chỉ chứng minh protected set không đổi; nó **không đo
được correctness của 23 fills** và không được dùng để tuyên bố tăng official
accuracy.

## 10. Test và verification

| Gate | Kết quả |
|---|---|
| Targeted unit/contract | 12 passed |
| Full offline tests | 2.405 passed, 42 skipped, 29 deselected |
| Integration tests | 22 passed, 2.454 deselected |
| Ruff correctness lint | PASS |
| Targeted mypy cho submission/recovery | PASS |
| Active snapshot verification | PASS |
| A6 `silver.db` SHA-256 | PASS: `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Retrieval DB SHA-256 | PASS: `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` |
| ZIP integrity | PASS |
| Two-run candidate determinism | PASS |

Hai gate toàn repo có blocker nền, không thuộc diff này:

- full mypy: 71 lỗi có sẵn trong các module mentor `pipelines/answering` và
  `pipelines/retrieval`; hai module mới type-check sạch;
- docs-check: 15 broken links trong các report 2026-08-29 trỏ tới historical
  ignored artifacts hiện không còn trên máy. Không tạo artifact giả để làm xanh
  gate.

## 11. Commits

| Commit | Nội dung |
|---|---|
| `d9c1d47` | freeze provenance của exact submission 3821 |
| `860bece` | tách complete/competition validation profiles |
| `e61f926` | seal ledger audit 46 QID |
| `4277c87` | deterministic baseline-preserving recovery builder |
| `336a2ca` | sửa raw-value/scale evidence materialization |
| `97224d3` | cho local proxy dùng explicit release profile |

Candidate ZIP được build từ clean commit:

```text
336a2cac6ac7b425acc971a0988ec2cf7574db7a
```

## 12. Kỳ vọng điểm và giới hạn

Submission 3821 tương ứng xấp xỉ 344 câu đúng trên 1.012 câu. Nếu cả 23 fill
được official scorer chấp nhận, upper scenario là khoảng:

```text
(344 + 23) / 1.012 ≈ 0.3626
```

Tức mức tăng tối đa thực tế của candidate này khoảng `+0.0227`, không phải
`+0.10`. Không có evidence để hứa trước official gain. Giá trị của candidate là:

- không chạm các câu baseline đã trả lời;
- không làm nhiễu retrieval đã có official score tốt;
- chỉ thêm source-reviewed opportunities trên abstentions;
- có rollback exact về 3821 và một conservative backup 17 fills.

## 13. File bàn giao

### Candidate khuyến nghị nộp

[`submission.zip`](../../artifacts/handoffs/safe-3821-reviewed23-final-20260830/submission.zip)

```text
SHA-256: 87d6c6e9da03057994427816599a02a7a1c67b296e2d5252b5b0a2b560086476
```

Handoff metadata:

- [`HANDOFF.json`](../../artifacts/handoffs/safe-3821-reviewed23-final-20260830/HANDOFF.json)
- [`candidate_manifest.json`](../../artifacts/handoffs/safe-3821-reviewed23-final-20260830/candidate_manifest.json)
- [`SHA256SUMS`](../../artifacts/handoffs/safe-3821-reviewed23-final-20260830/SHA256SUMS)

### Conservative backup

[`submission.zip`](../../artifacts/handoffs/safe-3821-trusted17-final-20260830/submission.zip)

```text
SHA-256: 4f7c397f942843eb8e7a73ab2ed1aa9f855c7b0ec67897cfef8070cf3fecbab5
```

## 14. Quyết định đề xuất

Nếu mục tiêu là candidate có upside cao nhất trong phạm vi plan, nộp
`REVIEWED-23`. Giữ `SAFE-17` và exact submission 3821 bất biến để rollback.

Sau khi leaderboard trả kết quả, phải ghi submission ID, timestamp, exact ZIP
SHA và đủ mười metrics vào submission ledger trước khi làm thay đổi tiếp theo.
