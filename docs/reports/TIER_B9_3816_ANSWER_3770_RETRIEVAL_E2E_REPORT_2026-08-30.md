# TIER-B9 — SAFE 3816 + RETRIEVAL 3770 — E2E RELEASE REPORT

**Ngày khóa:** 2026-08-30  
**Trạng thái:** `READY_NOT_SUBMITTED`  
**Candidate được chọn:** `MAX9`  
**Official score mới:** `NOT_MEASURED_UNTIL_UPLOAD`

## 1. Kết quả cuối

Đã hoàn thành end-to-end candidate kế tiếp trên nguyên tắc bảo toàn submission 3816:

- giữ nguyên toàn bộ 638 answer/query/evidence đã emitted của SAFE 3816;
- chỉ fill 9 QID mà 3816 đang abstain;
- giữ nguyên `relevant_tables` và `relevant_docs` của submission 3770 trên 1.012/1.012 QID;
- không bật P0, không dùng MODEL_GOLD, không promote Semantic V3;
- strict validation: 0 error, 0 warning;
- clean replay: 647/647 emitted answers matched, 0 error;
- build hai lần tạo ZIP byte-identical.

File đề xuất nộp:

```text
artifacts/submissions/submission_tier-b9-3816-answer-3770-retrieval-20260830-01.zip
SHA-256: 679d7d80ae9e46ca6b2f11a88ca9a3550e7538599796a38556b00f3ca2265771
Size: 1,142,102 bytes
```

Candidate dự phòng SAFE5 cũng được khóa:

```text
artifacts/submissions/submission_tier-b-safe5-3816-answer-3770-retrieval-20260830-01.zip
SHA-256: 8c53d218cfbf20921067ea4c197d29ebff9219b63e4e9a0039b2e4f0bb67c749
Size: 1,136,625 bytes
```

## 2. Baseline và phạm vi đã khóa

SAFE baseline mới là submission 3816, được người dùng báo cáo trên leaderboard:

| Metric | 3816 official |
|---|---:|
| Execution Accuracy | 0.2925 |
| Answer Accuracy | 0.2925 |
| Tables F2-macro | 0.3000 |
| Docs F2-macro | 0.7086 |
| Tables Precision | 0.2707 |
| Tables Recall | 0.3435 |
| Tables MRR@5 | 0.3801 |
| Docs Precision | 0.6349 |
| Docs Recall | 0.7651 |
| Docs MRR@5 | 0.7885 |

Exact local ZIP đã map với submission 3816:

```text
artifacts/submissions/submission_adjudicated-a17-3811-answer-3770.zip
SHA-256: f59c734e160705ee748a0573c991b65fc6007054602cd63074db16f0ff78b628
```

Retrieval owner tiếp tục là submission 3770:

```text
artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip
SHA-256: 15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169
```

Phạm vi triển khai cố ý nhỏ:

- không sửa bất kỳ answer đang non-empty của 3816;
- không thay retrieval profile;
- không sửa gold;
- không chạy lại generation;
- không refactor resolver/selector;
- không dùng local replay hoặc coverage để tuyên bố official accuracy.

## 3. Active lineage và identity gates

| Thành phần | Identity / SHA-256 | Gate |
|---|---|---|
| Raw snapshot | `ca033190f2e9e99f` | PASS |
| A6 build | `c6887fb633374fad` | PASS |
| A6 `silver.db` | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` | PASS |
| Retrieval index | `872ccb0dda9a2bb6` | PASS |
| Retrieval DB | `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` | PASS |
| Corpus files | 1.973 | PASS |
| Questions | 1.012 | PASS |

`make paths-check`, `make snapshots-verify` và `make dp-env-check` đều PASS. Environment check xác nhận source tree sạch tại commit `7708a0148e5bee6d484c4ec83e1d5c173c803331`.

## 4. Audit và allowlist 9 QID

Tất cả 9 bản ghi đều là `FILL` trên abstention của 3816; không có correction.

| QID | Answer | Source-backed semantic | Risk tier |
|---:|---:|---|---|
| 452 | 35.2215105708791 | Lọc 2/4 doanh nghiệp dưới current-ratio median, rồi bình quân gross margin | SAFE5 |
| 460 | 0.6680875037792766 | Chia nhóm theo debt/equity median; tỷ số tổng magnitude chi phí lãi vay | MAX9-only |
| 546 | 0.05010027975016958 | DLG và HHV có current ratio dưới 1; bình quân CFO/current liabilities | SAFE5 |
| 601 | 844.950578924 | Hiệu exact short-term interest-payable của KBC, đổi VND sang tỷ đồng | SAFE5 |
| 647 | 37.4626891563548 | Tăng trưởng magnitude của contra-asset loan-loss provision | MAX9-only |
| 808 | -132.690613269 | Signed difference DCM trừ DPM, đổi VND sang tỷ đồng | MAX9-only |
| 883 | 2023 | Argmax exact child label chứng khoán kinh doanh nợ | SAFE5 |
| 956 | 4517887.5 | Bình quân exact PBT khu vực Miền Bắc của SHB, bốn năm | SAFE5 |
| 967 | 40469060 | Max magnitude của loan-loss provision, đơn vị triệu đồng | MAX9-only |

Mỗi patch khóa đồng thời:

- hash câu hỏi;
- exact `table_uid` và `observation_uid` từ A6;
- phép tính pandas;
- expected answer;
- SHA của A6 DB và retrieval DB.

Manifest:

| Candidate | Manifest | SHA-256 |
|---|---|---|
| MAX9 | `configs/evaluation/adjudicated_answer_patch_tier_b9_v1.json` | `52c3ac33613ada7fc003166f7ebf671dfe840f828c0620c91b18df8ff85cac1b` |
| SAFE5 | `configs/evaluation/adjudicated_answer_patch_tier_b_safe5_v1.json` | `b779761ac15a27ecb4177a83e9993b035592b08ff49b5f3ce9ec2620a2dc0eff` |

## 5. Build, blocker và cách xử lý

### 5.1 Attempt A — BLOCKED, không promote

Run đầu tiên được giữ nguyên tại:

```text
artifacts/runs/submission/tier-b9-3816x3770-20260830-a/
```

Gate replay phát hiện 2 lỗi:

- query thủ công của Q452/Q460 chưa parse đúng;
- corpus root truyền vào builder không trỏ tới `financial_statements`.

Không có candidate nào từ attempt này được dùng. Query được sửa đúng cú pháp và build lại với corpus root chính xác; validator không bị hạ.

### 5.2 MAX9 deterministic runs

| Run | ZIP SHA-256 | Report SHA-256 | Result |
|---|---|---|---|
| `tier-b9-3816x3770-20260830-b` | `679d7d80...65771` | `ead4d6ea...8058` | PASS |
| `tier-b9-3816x3770-20260830-c` | `679d7d80...65771` | `7fab6722...5bf` | PASS |

Hai ZIP byte-identical. Report khác SHA vì chứa run/output path khác nhau; payload ZIP giống hoàn toàn.

### 5.3 SAFE5 deterministic runs

| Run | ZIP SHA-256 | Result |
|---|---|---|
| `tier-b-safe5-3816x3770-20260830-a` | `8c53d218...c749` | PASS |
| `tier-b-safe5-3816x3770-20260830-b` | `8c53d218...c749` | PASS |

## 6. Differential và validation gates

| Gate | MAX9 | SAFE5 |
|---|---:|---:|
| Records | 1.012 | 1.012 |
| Baseline emitted preserved | 638/638 | 638/638 |
| Answer fields unchanged ngoài allowlist | 1.003/1.003 | 1.007/1.007 |
| New fills | 9 | 5 |
| Corrections | 0 | 0 |
| Output emitted | 647 | 643 |
| Retrieval equal 3770 | 1.012/1.012 | 1.012/1.012 |
| Max tables | 10 | 10 |
| Duplicate IDs/tables/docs | 0/0/0 | 0/0/0 |
| Missing/orphan CSV | 0/0 | 0/0 |
| Strict validation errors | 0 | 0 |
| Strict validation warnings | 0 | 0 |
| Replay matched | 647/647 | 643/643 |
| Replay errors | 0 | 0 |
| Two-run byte-identical | PASS | PASS |

Lưu ý: builder vẫn dùng một số key báo cáo lịch sử như `answer_fields_equal_3811_outside_allowlist` và `copied_from_3811`. Đây chỉ là tên field backward-compatible. Identity trong manifest và report xác nhận answer owner thực tế của candidate này là submission 3816 với SHA `f59c...b628`.

## 7. Acceptance cấp dự án

Các gate được chạy sau khi code/config đã commit và source tree sạch:

| Gate | Kết quả |
|---|---|
| Ruff | PASS |
| Mypy | PASS, 92 source files |
| Docs links | PASS, 91 Markdown files, 0 broken link |
| Offline CI tests | 2.229 passed, 42 skipped, 30 deselected |
| Integration tests | 23 passed |
| `dp-env-check` | PASS |
| `dp-test` | 2.252 passed, 42 skipped, 0 failed/error |

Full test report:

```text
artifacts/reports/tier_b9_acceptance_20260830_01/test_report.json
SHA-256: c4bcfbf1413f13761c6772b81b899aa849067367fa18370f41ce992fbb5285ae
```

Implementation commits:

- `53b42d82c83e649c0c511eb3eaa3cec7c4879a8c` — source-backed Tier-B9 candidate;
- `7708a0148e5bee6d484c4ec83e1d5c173c803331` — SAFE5 fallback.

## 8. Score hypothesis và quyết định nộp

Từ official `0.2925`, số câu đúng tương ứng xấp xỉ 296/1.012. Đây là suy luận từ metric làm tròn, không phải hidden-gold count được quan sát trực tiếp.

| Kịch bản | Số đúng giả định | Accuracy giả định |
|---|---:|---:|
| 3816 hiện tại | ~296 | 0.29249 |
| SAFE5, 5/5 fill đúng | ~301 | 0.29743 |
| MAX9, 9/9 fill đúng | ~305 | 0.30138 |

Các con số trên chỉ là upper-bound hypothesis. Replay chứng minh query tái tạo đúng answer từ evidence, nhưng không chứng minh hidden gold đồng ý với semantic interpretation.

Quyết định:

1. Chọn MAX9 cho lượt nộp tiếp theo vì không ghi đè câu đang đúng và cả 9 fill đều có A6 source proof.
2. Giữ SAFE5 bất biến làm fallback nếu cần so sánh mức rủi ro semantic.
3. Giữ 3816 làm SAFE official baseline; không xóa hoặc thay thế artifact.
4. Sau upload, phải map submission ID và leaderboard receipt về đúng SHA `679d...65771` trước khi kết luận win/loss.

## 9. Checklist trước upload

- [x] 1.012/1.012 records.
- [x] 638/638 baseline emitted answers preserved.
- [x] Retrieval fields equal submission 3770: 1.012/1.012.
- [x] Strict validation: 0 error, 0 warning.
- [x] Clean replay: 647/647, 0 error.
- [x] Max tables: 10.
- [x] No duplicate IDs/tables/docs.
- [x] No missing/orphan evidence CSV.
- [x] Two-run deterministic ZIP.
- [x] Release SHA recorded in provenance and ledger.
- [ ] Upload receipt / submission ID.
- [ ] Official leaderboard metrics for this SHA.

Provenance seal:

```text
provenance/submissions/tier_b9_3816_answer_3770_retrieval_20260830.json
```

