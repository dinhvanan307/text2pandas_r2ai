# Recovery Wave 2 — Submission 3828 E2E Report

**Ngày thực hiện:** 2026-08-30  
**Baseline chính thức:** submission 3828  
**Baseline Answer/Execution Accuracy:** `0.3498`  
**Trạng thái:** `READY_FOR_MANUAL_LEADERBOARD_UPLOAD_EXPERIMENTAL`

## 1. Kết luận

Recovery Wave 2 đã được triển khai end-to-end theo chế độ **additive-only** trên đúng ZIP của submission 3828. Candidate mới:

- giữ nguyên answer/query/evidence của toàn bộ `735/735` câu baseline đã thực thi;
- giữ nguyên relevant tables/docs của `1,012/1,012` QID;
- giữ nguyên byte của `1,130/1,130` CSV baseline;
- chỉ bổ sung 28 câu baseline đang abstain;
- dùng 100 observation A6, tất cả đều tồn tại và có `execution_ready=1`;
- replay sạch `763/763`, không mismatch và không execution error;
- hai lần build độc lập tạo ZIP byte-identical.

Answer Accuracy chính thức của candidate là **`NOT_MEASURED`**. Coverage và replay PASS không được diễn giải thành accuracy; cần một lượt leaderboard để xác nhận.

## 2. Artifact cần nộp

File nộp trực tiếp:

```text
/Users/andinh307/Documents/Dagoras-R2AI/text2pandas-main/text2pandas/artifacts/handoffs/recovery-wave2-3828-source-sealed-final-20260830/submission.zip
```

SHA-256:

```text
b79fe44c110ecca5a3657ed360cc1c02f5badb4f7f7c9f4b1d456f48b20fb601
```

Handoff đi kèm:

```text
artifacts/handoffs/recovery-wave2-3828-source-sealed-final-20260830/
├── submission.zip
├── HANDOFF.json
├── candidate_manifest.json
├── SHA256SUMS
└── README.md
```

## 3. Baseline và provenance đã khóa

| Thành phần | Identity |
|---|---|
| Baseline ZIP | `artifacts/official/submission-3828/submission.zip` |
| Baseline SHA-256 | `87d6c6e9da03057994427816599a02a7a1c67b296e2d5252b5b0a2b560086476` |
| Số QID | `1,012` |
| Baseline executable/abstain | `735 / 277` |
| A6 build | `c6887fb633374fad` |
| A6 database SHA-256 | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Question SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |
| Builder commit | `869c6550c96a52a20be37a8912c1e86644679d52` |
| Handoff-support commit | `db40328` |

Official metrics người dùng cung cấp cho submission 3828:

| Metric | Score |
|---|---:|
| Answer/Execution Accuracy | 0.3498 |
| Tables F2 | 0.3151 |
| Docs F2 | 0.7361 |
| Tables Precision / Recall / MRR5 | 0.2797 / 0.3571 / 0.3939 |
| Docs Precision / Recall / MRR5 | 0.6534 / 0.7952 / 0.8162 |

## 4. Source adjudication

Ledger bất biến:

```text
configs/evaluation/recovery_wave2_review_3828_v1.json
```

Ledger chứa 31 quyết định đã audit:

- `PASS_SOURCE_PROVEN`: 28;
- `FAIL_CLOSED`: 3;
- observation A6 được đóng gói: 100;
- observation thiếu hoặc không execution-ready: 0.

### Pack A — 12 QID được chấp nhận

```text
407, 465, 652, 700, 724, 826, 883, 917, 942, 949, 952, 999
```

Các sửa chữa chính gồm next-period selection, basis công ty mẹ/hợp nhất, thành phần doanh thu, average/difference/unit conversion, argmax theo năm và count theo ngưỡng.

### Pack B direct-safe — 16 QID được chấp nhận

```text
656, 663, 673, 686, 690, 731, 738, 744,
765, 783, 803, 809, 824, 833, 853, 943
```

Đây là các phép ratio, sum, difference và average trực tiếp, có đủ metric, entity, period, basis, operation, unit và source evidence.

### Fail-closed — 3 QID không được đưa vào candidate

| QID | Lý do |
|---:|---|
| 151 | Observation tiền gửi tiết kiệm VND nằm trong semantic collision/non-candidate |
| 267 | Observation tiền gửi có kỳ hạn ngoại tệ ACB nằm trong semantic collision/non-candidate |
| 590 | Observation hạn mức tín dụng HHV 2025 chưa resolve được period |

Không hạ validator, không dùng MODEL_GOLD runtime và không điền ba QID này bằng phỏng đoán.

## 5. Differential so với submission 3828

| Gate | Kết quả |
|---|---:|
| QID scope | `1,012 / 1,012` giữ nguyên |
| Baseline answer/query/evidence | `735 / 735` giữ nguyên |
| Baseline retrieval | `1,012 / 1,012` giữ nguyên |
| Baseline CSV payload | `1,130 / 1,130` giữ nguyên byte |
| Answer-layer changed QID | đúng 28 QID đã review |
| Retrieval-layer changed QID | 0 |
| Executable trước → sau | `735 → 763` |
| Abstention trước → sau | `277 → 249` |
| Coverage trước → sau | `72.63% → 75.40%` |

Vì candidate không thay một answer baseline nào, rủi ro regression trực tiếp trên 735 câu đang phát answer đã được loại ở mức artifact differential. Điều này không chứng minh 28 answer mới đúng theo scorer chính thức.

## 6. Validation, replay và determinism

### Competition profile

| Gate | Kết quả |
|---|---:|
| Validation errors | 0 |
| Validation warnings | 498 |
| Replay executed | 763 |
| Replay matched | 763 |
| Replay mismatches | 0 |
| Replay errors | 0 |
| Remaining abstentions | 249 |

`498` warning là hai cảnh báo coverage cho mỗi QID còn abstain: evidence rỗng và pandas_query rỗng. Đây không phải lỗi của 763 query đã phát. Competition gate coi abstention là warning và đã PASS.

### Complete profile

Complete profile còn FAIL do yêu cầu mọi `1,012/1,012` QID phải có query/evidence. Có 249 abstention nên profile này ghi 498 validation errors và 249 replay errors. Không có cách hợp lệ để biến các QID chưa đủ source proof thành complete coverage mà vẫn giữ chính sách fail-closed.

### Determinism

Hai run độc lập:

```text
artifacts/runs/recovery-wave2/recovery-wave2-3828-source-sealed-20260830-r1.zip
artifacts/runs/recovery-wave2/recovery-wave2-3828-source-sealed-20260830-r2.zip
```

Cả hai có cùng SHA-256:

```text
b79fe44c110ecca5a3657ed360cc1c02f5badb4f7f7c9f4b1d456f48b20fb601
```

`cmp` trả PASS, xác nhận ZIP byte-identical.

## 7. Test và quality gates

| Gate | Kết quả |
|---|---:|
| Targeted submission/recovery tests | 11 passed |
| Handoff resolver tests | 4 passed |
| `make typecheck` | PASS, 115 source files, 0 issue |
| `make test-offline` | 2,411 passed, 42 skipped, 29 deselected |
| `make dp-test` | 2,434 passed, 0 failed, 42 skipped |
| `make test-integration` | 22 passed, 0 failed |
| `make snapshots-verify` | raw/A6/retrieval PASS |
| `git diff --check` | PASS |

Machine-readable test report:

```text
artifacts/reports/recovery-wave2-3828-e2e-20260830/test_report.json
```

## 8. Diễn giải score và quyết định nộp

Submission 3828 có score `0.3498`, tương ứng xấp xỉ 354 câu đúng trên 1,012 QID. Candidate thêm 28 answer trên các vị trí baseline abstain và không thay answer cũ.

Nếu scorer dùng mẫu số cố định và abstain/sai cùng nhận 0 như các lần trước, miền lý thuyết của Answer Accuracy là:

```text
không answer mới nào đúng: 354 / 1,012 ≈ 0.3498
toàn bộ 28 answer mới đúng: 382 / 1,012 ≈ 0.3775
```

Đây chỉ là biên lý thuyết, không phải dự báo chính thức. Candidate chưa có independent gold và leaderboard chưa chấm, nên official Answer Accuracy vẫn là `NOT_MEASURED`.

### Khuyến nghị

Candidate đủ điều kiện để dùng **một lượt upload đo lường thủ công**. Sau khi nộp cần khóa ngay:

1. submission ID và timestamp;
2. SHA-256 của ZIP đã upload;
3. toàn bộ 10 official metrics;
4. quyết định promote/rollback dựa trên score thật.

Không thay thế SAFE baseline 3828 trước khi có kết quả leaderboard.

## 9. Các thay đổi mã nguồn

- `src/text2pandas/application/usecases/wave2_recovery.py`: builder additive-only, SHA-bound, A6 execution-ready gate, clean replay trước khi ghi candidate.
- `tools/build_recovery_wave2_candidate.py`: build, validate, replay và sinh manifest.
- `configs/evaluation/recovery_wave2_review_3828_v1.json`: ledger source-adjudicated cho 31 QID.
- `tests/unit/test_wave2_recovery.py`: determinism, protected layers và fail-closed test.
- `tools/package_submission_handoff.py`: hỗ trợ run root `recovery-wave2`.

## 10. Lệnh tái lập

```bash
PYTHONPATH=src python tools/build_recovery_wave2_candidate.py \
  --run-id recovery-wave2-3828-source-sealed-20260830-r1

PYTHONPATH=src python tools/build_recovery_wave2_candidate.py \
  --run-id recovery-wave2-3828-source-sealed-20260830-r2

PYTHONPATH=src python tools/package_submission_handoff.py \
  --candidate-run-id recovery-wave2-3828-source-sealed-20260830-r1 \
  --output artifacts/handoffs/recovery-wave2-3828-source-sealed-final-20260830 \
  --release-profile competition
```
