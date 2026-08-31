# A18 — 3818 ABSTENTION RECOVERY — E2E EXECUTION REPORT

**Ngày khóa:** 2026-08-30  
**Trạng thái:** `BLOCKED_NOT_PROMOTED`  
**SAFE baseline:** submission 3818  
**Official score của candidate mới:** `NOT_MEASURED_NO_CANDIDATE_BUILT`

## 1. Kết luận

A18 đã được implement và test; toàn bộ cohort 365 abstentions của submission
3818 đã được chuẩn bị thành packets. Inference run bị dừng tại blocker cứng đã
khai báo trước:

```text
minimum accepted required: 170
pass-A compiler-valid completed: 3
candidate QID chưa chạy: 162
absolute acceptance upper bound: 3 + 162 = 165
result: 165 < 170 => promotion mathematically impossible
```

Vì vậy:

- không hạ validator;
- không chạy tiếp pass B sau khi promotion đã bất khả thi;
- không tạo A18 patch manifest;
- không build hoặc đề xuất một submission ZIP mới;
- giữ submission 3818 làm SAFE official baseline;
- giữ nguyên toàn bộ completed records, prompts và raw responses để audit hoặc
  resume nghiên cứu sau này;
- không đọc hoặc dùng MODEL_GOLD.

Đây là kết quả fail-closed đúng plan. Việc tiếp tục 162 QID còn lại không thể làm
candidate đạt gate 170 ngay cả trong kịch bản mọi QID đều hợp lệ.

## 2. Baseline đã khóa

Người dùng báo cáo official submission 3818 tại 2026-08-30 11:28
Asia/Ho_Chi_Minh:

| Metric | Official 3818 |
|---|---:|
| Execution Accuracy | 0.2964 |
| Answer Accuracy | 0.2964 |
| Tables F2-macro | 0.3000 |
| Docs F2-macro | 0.7086 |
| Tables Precision | 0.2707 |
| Tables Recall | 0.3435 |
| Tables MRR@5 | 0.3801 |
| Docs Precision | 0.6349 |
| Docs Recall | 0.7651 |
| Docs MRR@5 | 0.7885 |

Exact local ZIP được khóa làm baseline:

```text
artifacts/submissions/submission_tier-b9-3816-answer-3770-retrieval-20260830-01.zip
SHA-256: 679d7d80ae9e46ca6b2f11a88ca9a3550e7538599796a38556b00f3ca2265771
records: 1,012
emitted answers: 647
abstentions: 365
```

Leaderboard receipt export chưa có, vì vậy ledger phân loại đây là
`USER_REPORTED_OFFICIAL_ATTRIBUTED`, không phải receipt-complete record.

## 3. Phạm vi và invariant

A18 chỉ được phép fill các abstention của 3818. Các invariant được giữ nguyên:

- 647 answer/query/evidence đang non-empty không được sửa;
- retrieval owner tiếp tục là submission 3770;
- P0 không được bật;
- Semantic V3 không được promote;
- MODEL_GOLD không được đọc hoặc dùng cho runtime prediction;
- Qwen2.5-14B chỉ là constrained semantic planner;
- số và query cuối phải do deterministic compiler tạo từ exact A6 observation
  UID;
- mọi ambiguity, invalid unit, invalid scope hoặc pass disagreement đều reject.

Active lineage:

| Thành phần | Identity / SHA-256 |
|---|---|
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| A6 `silver.db` | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Retrieval DB | `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` |
| Retrieval owner ZIP 3770 | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| Semantic V3 package | `3e068bc697ac9d34512f16d520af5bf4d51a6e0dc3137c503a25f9acfacb54f0` |

## 4. Phần đã implement

Implementation commit:

```text
969394e1d06c2a5e8d73c99afa1a18c3bda81b4b
feat(answer): add constrained A18 abstention recovery
```

Các thành phần chính:

1. `prepare`
   - verify exact baseline/A6/retrieval hashes;
   - freeze 365 abstentions;
   - đọc P0/V3 traces và A6 immutable nhưng không đọc MODEL_GOLD;
   - rank semantic candidates bằng ontology/formula/metric code hiện có;
   - giới hạn tối đa 36 candidates/packet và fail-closed khi không có source.
2. `solve`
   - gọi local `qwen2.5:14b`, digest `7cdf5a0187d5`;
   - structured schema, seed cố định, context 8192;
   - model chỉ được chọn exact A6 UID và biểu diễn phép tính bằng DSL;
   - prompt/response/raw metadata được lưu append-only theo QID.
3. compiler/validator
   - compiler lại số bằng `Decimal` từ A6 raw value/scale;
   - kiểm exact UID set, entity, period, basis, operation, dimension, unit và
     output transform;
   - cấm numeric constants ngoài câu hỏi;
   - fail-closed cho syntax, scope và semantic mismatch.
4. two-pass adjudication
   - yêu cầu A/B đồng thuận tuyệt đối trên answer decimal, UID set, operation,
     entities, periods, basis và output transform;
   - predeclared promotion minimum là 170 accepted records.
5. guarded builder integration
   - hỗ trợ source kind `A6_CONSTRAINED_MODEL`;
   - chỉ được build sau adjudication manifest;
   - giữ baseline answer fields ngoài allowlist và retrieval 3770 tuyệt đối.

## 5. Cohort preparation

Run directory:

```text
artifacts/runs/answer/a18-3818-abstention-v8-20260830/
```

| Hạng mục | Kết quả |
|---|---:|
| Submission records | 1,012 |
| Baseline emitted | 647 |
| Frozen abstentions | 365 |
| Packets có candidates | 359 |
| Packets không có candidates | 6 |
| Candidate mean | khoảng 32/packet |
| Candidate max | 36/packet |
| MODEL_GOLD read | false |

Artifact seals:

| Artifact | SHA-256 |
|---|---|
| `cohort_manifest.json` | `1bf5c11b4be46f35630c7e657dcde90a967f82d7f45487932b4ccb8529cbbf30` |
| `packets.jsonl` | `37bf3730ddd257e39542482c67b7d2f3ff82f92f3b07b3dd433a1c8d505b1e34` |

## 6. Pass A checkpoint

Pass A chạy từ 2026-08-30T05:38:37Z đến 2026-08-30T08:28:36Z.
Khi upper-bound blocker được chứng minh, process được dừng có kiểm soát. QID đang
in-flight không được append; completed record cuối là Q590.

| Hạng mục | Số lượng |
|---|---:|
| Completed pass-A records | 197 |
| Raw attempt files | 197 |
| Raw `SOLVED` | 44 |
| Model `ABSTAIN` | 145 |
| Schema/parse errors | 8 |
| Compiler-valid | 3 |
| Compiler-valid QID | 346, 605, 734 |
| Candidate QID chưa chạy | 162 |
| Absolute acceptance upper bound | 165 |

`SOLVED` thô không phải accepted. Trong 44 raw solves, compiler chỉ chấp nhận 3.
Các reject chính:

| Lý do | Count |
|---|---:|
| Model abstained hoặc không có solution hợp lệ | 153 |
| Confidence `LOW` | 14 |
| Declared periods khác compiled UID scope | 8 |
| `obs()` không có đúng một UID string | 4 |
| Invalid expression syntax | 2 |
| Declared entities khác compiled UID scope | 2 |
| Invalid `select_at_argmax` form | 2 |
| Các lỗi unit/dimension/constant/scope còn lại | 9 |

Pass-A seal:

```text
solutions_a.jsonl
SHA-256: a6132d624e7d7f03f1821b313e46625c84f61d52ab6c440ab2e0ccc6544b5dac
```

## 7. Pass B và adjudication

Smoke pass B đã hoàn tất trước full pass A:

| Hạng mục | Kết quả |
|---|---:|
| Completed pass-B records | 2 |
| Two-pass agreed | 2 |
| Agreed QID | 605, 734 |

```text
solutions_b.jsonl
SHA-256: b4d4f4545ebbc675d3734aee381faa5668c9c6974ca31ea7bdaadddb875f8f25
```

Không chạy full pass B vì upper bound của pass A đã nhỏ hơn minimum. Lệnh
adjudication chính thức được chạy với gate đã khóa và trả:

```text
BLOCKED: accepted 2 is below the predeclared minimum 170
exit code: 2
```

Fail-closed được xác nhận:

```text
configs/evaluation/a18_abstention_recovery_v1.json: ABSENT_AS_DESIGNED
artifacts/runs/answer/a18-3818-abstention-v8-20260830/adjudication_report.json: ABSENT_AS_DESIGNED
```

Không có manifest nên builder không được phép chạy. Do đó không có candidate ZIP
A18 để nộp.

## 8. Test và regression gates

| Gate | Kết quả |
|---|---|
| Ruff targeted | PASS |
| Unit tests targeted | 24 passed |
| `make dp-test` | 2,269 passed, 42 skipped, 0 failed/error |
| Required suites missing | 0 |
| Source tree tại acceptance | clean |
| Source commit | `969394e1d06c2a5e8d73c99afa1a18c3bda81b4b` |

Full test report:

```text
artifacts/reports/a18_abstention_recovery_20260830_01/test_report.json
SHA-256: 109c366b490c7379c3405642dd9bf9eb24f6ff13b2fc89c8d599b4cc2c0aba81
```

Baseline ZIP không bị thay đổi; SHA vẫn là `679d7d80...65771`. Vì không có
candidate mới, strict submission validation, clean replay và two-run ZIP
determinism không áp dụng cho A18 (`NOT_RUN_NO_MANIFEST`), không được ghi là
PASS giả.

## 9. Mục tiêu +0.10 Answer Accuracy

Tăng từ 0.2964 lên ít nhất 0.3964 cần khoảng 102 net correct answers mới trên
1.012 câu. Đây là yêu cầu về hidden-gold correctness, không phải chỉ emitted
coverage.

A18 hiện tại không đủ quy mô và độ tin cậy:

- chỉ 3/197 completed records compiler-valid;
- chỉ 2 records có two-pass agreement;
- kể cả upper bound lý thuyết cũng không đạt promotion gate 170;
- accepted coverage, nếu có, vẫn không chứng minh số net wins official.

Vì vậy không có cơ sở trung thực để tuyên bố hoặc kỳ vọng A18 hiện tại mang lại
+0.10. Upload một ZIP từ 2–3 fills sẽ tiêu quota nhưng không có bằng chứng đủ
mạnh để đạt mục tiêu.

## 10. Quyết định và bước tiếp theo

Quyết định release:

1. Giữ nguyên submission 3818 làm SAFE baseline.
2. Không nộp A18 checkpoint.
3. Không resume cùng A18 configuration; upper bound đã chứng minh gate bất khả
   thi.
4. Giữ toàn bộ 13 MB run artifacts và raw attempts để phân tích lỗi.
5. Không sửa MODEL_GOLD hoặc validator để biến reject thành accepted.

Hướng kỹ thuật nên làm tiếp không phải tăng generation coverage bằng cùng prompt,
mà là sửa upstream semantic candidate construction trên các failure pool lớn:

- multi-entity operation và entity binding;
- reviewed formula coverage;
- period/basis binding;
- select-at-arg/extremum routing;
- unit/dimension contract.

Mọi phiên bản tiếp theo phải chạy shadow/differential trên 3818, giữ 647 baseline
answers và retrieval 3770 bất biến, rồi chỉ dùng quota khi có independent
correctness evidence. Official score của bất kỳ candidate tương lai vẫn là
`NOT_MEASURED` cho đến khi leaderboard trả kết quả gắn với exact ZIP SHA.

## 11. Ledger và provenance

Official submission 3818 đã được thêm/khóa tại:

```text
configs/evaluation/submission_ledger_v1.json
SHA-256: 642532087eb9b78b0e443a9eb94d6490a211c18842cc30f4d8c994420dfe4414
```

Release provenance đã chuyển thành `SUBMITTED_OFFICIAL_BASELINE`:

```text
provenance/submissions/tier_b9_3816_answer_3770_retrieval_20260830.json
SHA-256: 0405e91dfab51ac7742267a14f206fb48bc5a7ba06f711b09a9d5ab1d345f30a
```

Receipt vẫn thiếu và được ghi rõ, không tự tạo bằng chứng upload.
