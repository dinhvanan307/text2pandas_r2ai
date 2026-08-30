# GROUNDED V6 — NEW CODE PULL, AUDIT VÀ E2E

**Ngày chạy:** 2026-08-30  
**Branch:** `mentor-grounded-v6`  
**Source commit:** `88ad7b04b66d00ade3fdb0f1c58e479f6c525a38`  
**Kết luận release:** `BLOCKED_NO_PUBLISHABLE_HANDOFF`  
**Official score của candidate mới:** `NOT_MEASURED`

## 1. Kết luận điều hành

Đã fetch code mới từ GitHub và xác định code mentor không nằm trên
`origin/main`, mà nằm trên branch:

```text
origin/feat/grounded-v6-architecture
```

Local main cũ được giữ tại ref `backup/main-a18-20260830`; code mentor được
checkout thành tracking branch riêng `mentor-grounded-v6`. Không merge mù 28
local commits với 40 remote commits.

Source, snapshots và tests cốt lõi của branch mentor đều tốt. Hai E2E run mới
đã hoàn thành trên 1.012 QID. Candidate tốt nhất theo local proxy là:

```text
artifacts/runs/grounded-v5/
  grounded-v6-downloaded-replace-trusted-20260830-r1.zip
SHA-256: 3c208ac537d6af42a66f9ed1c2f52bf19664ee0124a4876768feecaf4ebf7685
```

Candidate này:

- giữ 31/31 Answer và Execution cases đúng trên local development gold;
- không có paired regression trên 31 cases;
- tăng cả 8 retrieval proxy metrics so với seed tải về;
- deterministic byte-identical qua hai run;
- replay sạch 736/736 câu có evidence/query.

Tuy nhiên candidate **không publishable theo HEAD mới** vì còn 276 abstentions.
Strict contract yêu cầu 1.012/1.012 QID đều có evidence và query, nên tạo 552
validation errors và 276 replay errors. Formal handoff gate đã từ chối và không
tạo thư mục upload. ZIP trên chỉ là diagnostic artifact, không phải bài nộp.

## 2. Official submission 3821

Người dùng cung cấp official leaderboard row:

| Metric | Submission 3821 |
|---|---:|
| Execution Accuracy | 0.3399 |
| Answer Accuracy | 0.3399 |
| Tables F2-macro | 0.3151 |
| Docs F2-macro | 0.7361 |
| Tables Precision | 0.2797 |
| Tables Recall | 0.3571 |
| Tables MRR@5 | 0.3939 |
| Docs Precision | 0.6534 |
| Docs Recall | 0.7952 |
| Docs MRR@5 | 0.8162 |

Thời điểm người dùng cung cấp: 2026-08-30 12:55 Asia/Ho_Chi_Minh.

Entry đã được thêm vào `configs/evaluation/submission_ledger_v1.json` dưới phân
loại `USER_REPORTED_OFFICIAL_UNATTRIBUTED`. Chưa được phép gắn score này với một
ZIP cụ thể vì thiếu leaderboard receipt, exact uploaded SHA, source commit và
config identity.

Một file phù hợp về tên và nội dung được tìm thấy:

```text
/Users/andinh307/Downloads/grounded-v6-final-replace-trusted-2.zip
SHA-256: 91089cec71f0aa409b8543e5c0201c17ce7b1482b8d73f8c86f62004737ab918
records: 1,012
executable: 712
unresolved: 300
```

File được download lúc 15:56, sau thời điểm submission 3821, không có manifest
hay receipt đi kèm. Vì vậy đây là candidate mạnh đang audit, **không được tự động
coi là exact ZIP 3821**.

Timeline Git cũng cho thấy cần phân biệt code đã submit và code hiện tại:

| Mốc | Thời gian local |
|---|---|
| Official 3821 | 12:55 |
| `e1d7f74` rebuild Grounded architecture | 12:58:59 |
| `af276c4` enforce complete replay | 13:37:22 |
| `88ad7b0` latest hardening | 15:34:38 |

Do đó official 3821 không thể được dùng làm bằng chứng trực tiếp cho behavior
của latest HEAD `88ad7b0`.

## 3. Pull và bảo toàn Git

Trước fetch:

```text
main...origin/main [ahead 28]
HEAD: 43835e668c47c9d0e1d8763c5f3a39dec691971e
```

Sau `git fetch --prune origin`:

- `origin/main` vẫn ở `b9f07ec`; không có code mentor mới trên main;
- xuất hiện `origin/feat/grounded-v6-architecture` tại `88ad7b0`;
- branch mentor có 40 commits kể từ common base;
- local main có 28 commits riêng.

Đã tạo:

```text
backup/main-a18-20260830 -> 43835e6
mentor-grounded-v6      -> 88ad7b0, tracking origin/feat/grounded-v6-architecture
```

Không reset, rebase hoặc xóa lịch sử local.

## 4. Missing artifacts của branch remote

CLI Grounded mặc định tham chiếu các artifact không có trong Git/local:

```text
artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/submission.zip
artifacts/handoffs/submission-v4-hybrid-20260829-r4-final/submission.zip
artifacts/runs/semantic-v4/semantic-v4-full-20260829-r2/records.jsonl
```

`make ci` chạy Ruff và mypy thành công, sau đó dừng ở docs-check vì 15 links trỏ
tới các handoff/report/generated artifacts chưa được chuyển cùng source branch.
Không tạo artifact giả và không sửa docs để che blocker.

Để vẫn đo được code mới, E2E dùng input minh bạch:

- baseline/secondary run đầu: exact ZIP 3818, SHA `679d7d80...65771`;
- baseline/secondary run sau: downloaded grounded seed, SHA
  `91089cec...ab918`;
- semantic-prior: JSONL rỗng có khai báo, SHA
  `01ba4719...546b`;
- deterministic-only, không gọi Ollama;
- promotion mode `replace_trusted`;
- confidence 0.7, fact limit 100, table cap 10.

Các run này không phải reproduction exact của mentor vì thiếu ba artifact nguồn
ở trên.

## 5. Environment và test gates

| Gate | Kết quả |
|---|---|
| Git source identity | clean `88ad7b0` |
| Python | 3.11.15 |
| Active raw snapshot | `ca033190f2e9e99f`, PASS |
| Active A6 | `c6887fb633374fad`, PASS |
| Active retrieval | `872ccb0dda9a2bb6`, PASS |
| Targeted Grounded tests | 181 passed |
| Ruff | PASS |
| Mypy | PASS, 113 source files |
| Offline tests | 2,401 passed, 42 skipped, 29 deselected |
| Integration tests | 22 passed, 2,450 deselected |
| Docs-check | BLOCKED, 15 missing generated artifacts |

Không có source test failure.

## 6. E2E A — latest HEAD trên baseline 3818

Run:

```text
grounded-v6-3818-replace-trusted-20260830-r1
```

| Measurement | Kết quả |
|---|---:|
| Baseline executable | 647 |
| Attempted | 1,012 |
| Generated plans | 774 |
| Promoted | 292 |
| Recovered abstentions | 92 |
| Replaced existing answers | 200 |
| Final executable | 739 |
| Remaining unresolved | 273 |
| Emitted replay matched | 739/739 |
| Strict validation errors | 546 |
| Replay errors from unresolved | 273 |

Diagnostic ZIP:

```text
artifacts/runs/grounded-v5/grounded-v6-3818-replace-trusted-20260830-r1.zip
SHA-256: 257f3b8eccd79cfb514b90a3f249446c72e5099219370cd87adafe09fe39bed1
```

Local proxy:

| Metric | Candidate |
|---|---:|
| Answer / Execution | 30/31 = 0.967742 |
| Tables F2 | 0.519972 |
| Docs F2 | 0.789161 |
| Tables Precision / Recall / MRR@5 | 0.504561 / 0.574582 / 0.619825 |
| Docs Precision / Recall / MRR@5 | 0.730117 / 0.841917 / 0.858772 |

So với 3818 local proxy: 13 answer wins, 0 loss. Q398 vẫn unresolved.

## 7. Candidate tải về

File `grounded-v6-final-replace-trusted-2.zip` có:

| Measurement | Kết quả |
|---|---:|
| Records | 1,012 |
| Executable | 712 |
| Unresolved | 300 |
| Strict validation errors | 600 |
| Local Answer / Execution | 31/31 = 1.0 |
| Local Tables F2 | 0.480767 |
| Local Docs F2 | 0.756681 |

So với exact 3818 local proxy: 14 answer wins, 0 loss. Candidate giải được Q398,
nhưng strict HEAD hiện tại vẫn phân loại là diagnostic do 300 unresolved.

## 8. E2E B — latest HEAD trên downloaded grounded seed

Hai run độc lập:

```text
grounded-v6-downloaded-replace-trusted-20260830-r1
grounded-v6-downloaded-replace-trusted-20260830-r2
```

| Measurement | Kết quả |
|---|---:|
| Seed executable | 712 |
| Attempted | 1,012 |
| Generated plans | 774 |
| Promoted | 274 |
| Recovered abstentions | 24 |
| Replaced existing answers | 250 |
| Final executable | 736 |
| Remaining unresolved | 276 |
| Emitted replay matched | 736/736 |
| Strict validation errors | 552 |
| Replay errors from unresolved | 276 |

R1/R2 đều tạo:

```text
ZIP SHA-256: 3c208ac537d6af42a66f9ed1c2f52bf19664ee0124a4876768feecaf4ebf7685
records.jsonl SHA-256: 164390e1f1d5ea5505cd43629c199c3a2f8716d574689633b5f5f21729d64091
```

ZIP và records đều byte-identical. Manifest khác SHA đúng dự kiến vì chứa run-id
và absolute path khác nhau.

Local proxy so với downloaded seed:

| Metric | Seed | Latest candidate | Delta |
|---|---:|---:|---:|
| Answer Accuracy | 1.000000 | 1.000000 | 0 |
| Execution Accuracy | 1.000000 | 1.000000 | 0 |
| Tables F2 | 0.480767 | 0.512436 | +0.031670 |
| Docs F2 | 0.756681 | 0.790414 | +0.033732 |
| Tables Precision | 0.459474 | 0.498421 | +0.038947 |
| Tables Recall | 0.531769 | 0.564056 | +0.032287 |
| Tables MRR@5 | 0.576842 | 0.617719 | +0.040877 |
| Docs Precision | 0.691124 | 0.731871 | +0.040748 |
| Docs Recall | 0.809599 | 0.841917 | +0.032318 |
| Docs MRR@5 | 0.811404 | 0.864035 | +0.052632 |

Paired answer/execution changes trên 31-case gold: 0 wins, 0 losses vì cả hai
đều 31/31. Cả 10 proxy metrics không regression.

Machine-readable proxy report:

```text
artifacts/reports/evaluation/
  competition-proxy-grounded-v6-downloaded-seed-20260830-r1.json
SHA-256: f1e84a5974553d28c8ba8f6750364f4ad6f0136307f26a267c58547a5e08c34c
```

Proxy này dùng 31 answer cases và 95 retrieval cases đã tham gia development;
không phải estimator đáng tin cậy cho hidden leaderboard.

## 9. Formal handoff result

Đã chạy:

```text
make submission-handoff \
  RUN_ID=grounded-v6-downloaded-replace-trusted-20260830-r1 \
  OUTPUT=artifacts/handoffs/grounded-v6-downloaded-replace-trusted-20260830-r1
```

Kết quả: exit code 2, handoff absent as designed. Blocker đầu tiên là empty
evidence/query trên unresolved QID; tổng thể là 276 unresolved QIDs.

Không có file mới trong `artifacts/submissions` và không có handoff upload.

## 10. Quyết định

### Best official

Submission 3821 với Answer/Execution 0.3399 tiếp tục là best official do người
dùng báo cáo. Exact ZIP mapping vẫn `UNKNOWN`.

### Best local diagnostic

`3c208ac5...f7685` là candidate tốt nhất theo local proxy vì giữ 31/31 answer
cases, tăng cả 8 retrieval metrics và deterministic. Nhưng nó có status
`BLOCKED`, không được đưa thành bài nộp.

### Điều kiện để chạy tiếp đúng chuẩn

1. Xác nhận file nào chính xác đã được upload thành submission 3821; tốt nhất là
   cung cấp receipt hoặc exact ZIP SHA.
2. Đồng bộ ba artifact mentor không push cùng source: baseline handoff, V4
   secondary handoff và semantic records.
3. Reconcile mâu thuẫn giữa official scorer và commit `af276c4`: nếu exact 3821
   có abstentions nhưng leaderboard vẫn chấm bình thường, cần bằng chứng trước khi
   thay đổi contract; không được tự hạ gate.
4. Nếu giữ all-QID execution contract, phải giải source-grounded 276 unresolved
   QIDs; không được điền placeholder hoặc arbitrary answer.
5. Chỉ tạo upload handoff sau strict validation, complete replay và two-run
   determinism đều PASS.

## 11. Artifact index

```text
# Downloaded candidate under audit
/Users/andinh307/Downloads/grounded-v6-final-replace-trusted-2.zip

# Latest candidate R1/R2, diagnostic only
artifacts/runs/grounded-v5/grounded-v6-downloaded-replace-trusted-20260830-r1.zip
artifacts/runs/grounded-v5/grounded-v6-downloaded-replace-trusted-20260830-r2.zip

# Per-QID ledgers and manifests
artifacts/runs/grounded-v5/grounded-v6-downloaded-replace-trusted-20260830-r1/
artifacts/runs/grounded-v5/grounded-v6-downloaded-replace-trusted-20260830-r2/

# Proxy reports
artifacts/reports/evaluation/competition-proxy-downloaded-grounded-v6-20260830-r1.json
artifacts/reports/evaluation/competition-proxy-grounded-v6-3818-20260830-r1.json
artifacts/reports/evaluation/competition-proxy-grounded-v6-downloaded-seed-20260830-r1.json
```
