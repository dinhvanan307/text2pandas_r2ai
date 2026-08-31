# Recovery Wave 3 — Submission 3830 E2E Report

**Ngày thực hiện:** 2026-08-30  
**Baseline chính thức:** submission 3830  
**Baseline Answer/Execution Accuracy:** `0.3696`  
**Trạng thái candidate:** `READY_FOR_MANUAL_LEADERBOARD_UPLOAD_EXPERIMENTAL`

## 1. Kết luận

Recovery Wave 3 đã được thực hiện end-to-end theo chính sách **additive-only, source-sealed và fail-closed** trên đúng ZIP của submission 3830. Candidate cuối:

- giữ nguyên answer/query/evidence của `763/763` câu baseline đang thực thi;
- giữ nguyên relevant tables/docs của `1,012/1,012` QID;
- giữ nguyên byte của `1,158/1,158` CSV baseline;
- chỉ bổ sung 29 câu tại đúng 29 vị trí baseline đang abstain;
- bind 71 observation từ A6, tất cả đều tồn tại và có `execution_ready=1`;
- tăng executable coverage từ `763` lên `792`, còn 220 abstention;
- clean replay `792/792`, mismatch `0`, execution error `0`;
- hai lần build độc lập và bản handoff cuối đều byte-identical.

Candidate không dùng MODEL_GOLD runtime, không thay answer baseline, không đổi retrieval và không hạ validator. Mục tiêu số lượng không được dùng để ép thêm QID thiếu chứng cứ: audit chỉ chấp nhận 29 trường hợp đáp ứng đủ metric, entity, period, basis, operation, unit và source evidence.

**Answer Accuracy chính thức của candidate vẫn là `NOT_MEASURED`.** Coverage, source checks, validation và replay PASS không phải là bằng chứng candidate đã tăng official accuracy. Submission 3830 tiếp tục là SAFE baseline cho đến khi leaderboard xác nhận candidate này.

## 2. File nộp

File ZIP cần upload trực tiếp:

```text
/Users/andinh307/Documents/Dagoras-R2AI/text2pandas-main/text2pandas/artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830/submission.zip
```

SHA-256:

```text
c1494ea630e7654def93a426d6f00b31f77fef05a67baac4e07e1ac7be262245
```

Handoff đầy đủ:

```text
artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830/
├── submission.zip
├── HANDOFF.json
├── candidate_manifest.json
├── SHA256SUMS
└── README.md
```

`unzip -t` trả PASS, không phát hiện lỗi trong dữ liệu nén. File handoff `submission.zip` giống byte với cả run R1 và run R2.

## 3. Baseline và provenance đã khóa

| Thành phần | Identity |
|---|---|
| Baseline ZIP | `artifacts/official/submission-3830/submission.zip` |
| Baseline SHA-256 | `b79fe44c110ecca5a3657ed360cc1c02f5badb4f7f7c9f4b1d456f48b20fb601` |
| Số QID | `1,012` |
| Baseline executable / abstain | `763 / 249` |
| A6 build | `c6887fb633374fad` |
| A6 database SHA-256 | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Question SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| Review-ledger SHA-256 | `00403f52ee2d5213f39111bc7f487560de1b9dfdecea9a528e3925226121c852` |
| Baseline-freeze commit | `b043ff5` |
| Inventory commit | `66c9a6d` |
| Candidate source commit | `2c080f15e2944de4358183a86d3dc99b7dacae76` |
| Handoff-support commit | `8e78cd3` |

Official metrics người dùng cung cấp cho submission 3830:

| Metric | Score |
|---|---:|
| Answer/Execution Accuracy | 0.3696 |
| Tables F2 | 0.3151 |
| Docs F2 | 0.7361 |
| Tables Precision / Recall / MRR5 | 0.2797 / 0.3571 / 0.3939 |
| Docs Precision / Recall / MRR5 | 0.6534 / 0.7952 / 0.8162 |

Chưa có leaderboard receipt trong repository để map submission ID 3830 với SHA baseline một cách độc lập. Vì vậy bảng trên được ghi nhận là **official metrics do người dùng cung cấp**, còn artifact identity được khóa bằng SHA-256 nội bộ.

## 4. Inventory 249 abstention

Inventory bất biến:

```text
artifacts/runs/evaluation/recovery-wave3-3830-inventory-20260830-v1/
├── inventory.jsonl
├── manifest.json
└── summary.json
```

Phân tầng rủi ro:

| Risk tier | QID |
|---|---:|
| A | 78 |
| B | 16 |
| C | 99 |
| D | 56 |
| **Tổng** | **249** |

Phân lớp repair:

| Repair class | QID |
|---|---:|
| Direct lookup | 22 |
| Direct ratio | 19 |
| Two-period difference | 35 |
| Single-metric sum | 8 |
| Single-metric average | 47 |
| Simple extremum | 16 |
| Complex composition | 102 |

Inventory chỉ là triage/reachability view, không phải gold và không chứng minh correctness. Sau source audit, chỉ 29 QID được đưa vào ledger PASS; 220 QID còn lại giữ abstain.

## 5. Source adjudication và 29 QID được chấp nhận

Ledger source-sealed:

```text
configs/evaluation/recovery_wave3_review_3830_v1.json
```

Mỗi record PASS khóa baseline SHA, A6 SHA, QID, cohort, fact UID, pandas query, expected answer, rationale và bảy gate semantic/source:

```text
metric → entity → period → basis → operation → unit → source evidence
```

| Cohort | Số QID | QID |
|---|---:|---|
| Direct | 3 | 284, 319, 729 |
| Difference | 10 | 580, 677, 714, 734, 773, 781, 785, 787, 800, 812 |
| Ratio | 13 | 658, 660, 664, 669, 671, 676, 680, 685, 692, 696, 697, 711, 717 |
| Count | 1 | 963 |
| Extremum | 1 | 967 |
| Sum | 1 | 987 |
| **Tổng** | **29** | |

Các QID mới dùng tổng cộng 71 observation A6 execution-ready. Builder xác minh lại existence/readiness của từng fact UID, clean replay expected answer và SHA nguồn trước khi cho phép ghi candidate.

### Các nhóm bị giữ fail-closed

Không đưa vào candidate các trường hợp không chứng minh được đầy đủ semantics, ví dụ:

- Q151 và Q267: semantic/source collision;
- Q590: period chưa resolve chắc chắn;
- Q379, Q447 và Q448: điều kiện/selector có nguy cơ chọn sai;
- Q412: segment scope chưa đủ chắc chắn;
- Q495: source chưa chứng minh đủ total cần tính;
- Q661: denominator không có observation execution-ready phù hợp;
- Q979: multi-entity composition chưa đầy đủ.

Đây là ví dụ của các lỗi bị loại, không phải khẳng định toàn bộ 220 QID còn lại đã được adjudicate thủ công ở cùng độ sâu. Toàn bộ 249 QID đã được triage; 29 QID vượt source gate; phần còn lại không được phát answer trong candidate này.

## 6. Differential so với submission 3830

| Gate | Kết quả |
|---|---:|
| QID scope | `1,012 / 1,012` |
| Baseline answer/query/evidence | `763 / 763` giữ nguyên |
| Baseline retrieval | `1,012 / 1,012` giữ nguyên |
| Baseline CSV payload | `1,158 / 1,158` giữ nguyên byte |
| Answer-layer changed QID | đúng 29 QID trong ledger |
| Retrieval-layer changed QID | 0 |
| CSV members trước → sau | `1,158 → 1,187` |
| Executable trước → sau | `763 → 792` |
| Abstention trước → sau | `249 → 220` |
| Coverage trước → sau | `75.40% → 78.26%` |

Candidate không thay một answer baseline nào. Do đó regression do overwrite trên 763 answer cũ đã được loại ở mức artifact differential. Điều này không chứng minh 29 answer mới sẽ khớp scorer chính thức.

Retrieval layer giống baseline ở cả `1,012/1,012` QID, nên không có thay đổi artifact nào dự kiến tác động Tables/Docs metrics. Official retrieval metrics vẫn cần leaderboard xác nhận.

## 7. Validation, replay và determinism

### Competition profile — PASS

| Gate | Kết quả |
|---|---:|
| Records | 1,012 |
| Validation errors | 0 |
| Validation warnings | 440 |
| Replay executed | 792 |
| Replay matched | 792 |
| Replay mismatches | 0 |
| Replay execution errors | 0 |
| Remaining abstentions | 220 |

`440` warning là đúng hai coverage warning cho mỗi QID còn abstain: evidence rỗng và pandas_query rỗng. Đây không phải lỗi của 792 query đã phát. Competition profile cho phép abstention dưới dạng warning và gate đã PASS.

### Complete profile — FAIL có chủ đích

Complete profile yêu cầu mọi `1,012/1,012` QID có query/evidence. Vì còn 220 abstention, profile này ghi 440 validation errors và 220 replay errors. Không hạ gate hoặc điền câu thiếu source proof chỉ để làm complete profile PASS.

### Determinism — PASS

Hai build độc lập:

```text
artifacts/runs/recovery-wave3/recovery-wave3-3830-safe29-20260830-r1.zip
artifacts/runs/recovery-wave3/recovery-wave3-3830-safe29-20260830-r2.zip
```

Cả hai và file handoff cuối có cùng SHA-256:

```text
c1494ea630e7654def93a426d6f00b31f77fef05a67baac4e07e1ac7be262245
```

Hai phép `cmp` (`R1 ↔ R2` và `handoff ↔ R1`) đều trả PASS.

## 8. Test và quality gates

| Gate | Kết quả |
|---|---:|
| Targeted Wave 3 tests | 5 passed |
| Handoff resolver tests | 5 passed |
| `make typecheck` | PASS, 115 source files, 0 issue |
| `make test-offline` | 2,412 passed, 42 skipped, 29 deselected |
| `make dp-test REPORT_DIR=...` | 2,434 passed, 0 failed, 42 skipped |
| `make test-integration` | 22 passed, 0 failed |
| `make snapshots-verify` | raw/A6/retrieval PASS |
| `git diff --check` | PASS |
| ZIP integrity (`unzip -t`) | PASS |

Machine-readable test report:

```text
artifacts/reports/recovery-wave3-3830-e2e-20260830/test_report.json
```

## 9. Diễn giải score

Score `0.3696` của submission 3830 tương thích với khoảng `374/1,012` câu đúng. Candidate thêm 29 answer chỉ tại baseline abstention.

Nếu scorer dùng mẫu số cố định và abstain/sai cùng nhận 0, biên lý thuyết là:

```text
0 answer mới đúng: 374 / 1,012 ≈ 0.3696
29 answer mới đúng: 403 / 1,012 ≈ 0.3982
```

Biên này chỉ mô tả miền kết quả có thể có, không phải dự báo. Không có independent gold cho 29 QID và chưa có lượt leaderboard, nên không được tuyên bố mức tăng trước khi đo official.

### Quyết định release

- Candidate đủ gate kỹ thuật để dùng **một lượt upload đo lường thủ công**.
- Submission 3830 vẫn là SAFE baseline.
- Không promote candidate vào production/baseline chính thức trước khi có leaderboard receipt.
- Sau upload cần khóa: submission ID, timestamp, ZIP SHA-256 đã nộp và toàn bộ 10 official metrics.
- Nếu official Answer Accuracy không tăng, rollback về đúng baseline 3830; không suy diễn từ replay.

## 10. Các thay đổi mã nguồn

- `src/text2pandas/application/usecases/wave2_recovery.py`: tách generic recovery builder, giữ wrapper Wave 2 tương thích.
- `tools/build_recovery_wave2_candidate.py`: hỗ trợ candidate kind và evidence prefix cho Wave 3.
- `tools/evaluation/build_recovery_wave2_inventory.py`: hỗ trợ baseline/run/output/version có định danh.
- `configs/evaluation/recovery_wave3_review_3830_v1.json`: ledger 29 quyết định source-proven.
- `tools/package_submission_handoff.py`: hỗ trợ run root `recovery-wave3`.
- `tests/unit/test_package_submission_handoff.py`: test resolver cho Wave 3.

## 11. Lệnh tái lập

```bash
PYTHONPATH=src:. python tools/build_recovery_wave2_candidate.py \
  --candidate-kind text2pandas.recovery_wave3_candidate \
  --evidence-prefix wave3 \
  --run-root artifacts/runs/recovery-wave3 \
  --run-id recovery-wave3-3830-safe29-20260830-r1 \
  --baseline artifacts/official/submission-3830/submission.zip \
  --review-ledger configs/evaluation/recovery_wave3_review_3830_v1.json

PYTHONPATH=src:. python tools/build_recovery_wave2_candidate.py \
  --candidate-kind text2pandas.recovery_wave3_candidate \
  --evidence-prefix wave3 \
  --run-root artifacts/runs/recovery-wave3 \
  --run-id recovery-wave3-3830-safe29-20260830-r2 \
  --baseline artifacts/official/submission-3830/submission.zip \
  --review-ledger configs/evaluation/recovery_wave3_review_3830_v1.json

PYTHONPATH=src:. python tools/package_submission_handoff.py \
  --candidate-run-id recovery-wave3-3830-safe29-20260830-r1 \
  --output artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830 \
  --release-profile competition
```

## 12. Artifact index

| Artifact | Path |
|---|---|
| Upload ZIP | `artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830/submission.zip` |
| Handoff manifest | `artifacts/handoffs/recovery-wave3-3830-safe29-final-20260830/HANDOFF.json` |
| Candidate manifest | `artifacts/runs/recovery-wave3/recovery-wave3-3830-safe29-20260830-r1/manifest.json` |
| Review ledger | `configs/evaluation/recovery_wave3_review_3830_v1.json` |
| Abstention inventory | `artifacts/runs/evaluation/recovery-wave3-3830-inventory-20260830-v1/summary.json` |
| Test report | `artifacts/reports/recovery-wave3-3830-e2e-20260830/test_report.json` |
