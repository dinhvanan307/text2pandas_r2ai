# P0 Metric Answer Baseline Freeze — 2026-08-29

## Kết luận gate P0.0

Baseline leaderboard `0.2787` đã được đóng băng bằng đúng ZIP do người dùng cung cấp. Artifact vượt strict validation và clean replay; có thể dùng làm đối chứng bất biến cho differential P0.

Không có MODEL_GOLD generation nào được resume. Checkpoint 71 record và raw attempts được giữ nguyên.

## Artifact bất biến

| Thuộc tính | Giá trị |
|---|---:|
| Baseline ID | `p0-answer-baseline-02787-20260829` |
| ZIP | `artifacts/submissions/submission_p0_baseline_02787_20260829.zip` |
| ZIP SHA-256 | `179d2c10425c96d55304183e27c5326b5bd2072d8d02fe74e211d23df3a060ad` |
| `submission.json` SHA-256 | `c2c34a3eec0ac0aff0752621539fbe5ab220eb4325cf840ddc3194e2a6576153` |
| Số record | 1.012 |
| Query/evidence/answer khác 0 | 604 / 604 / 604 |
| CSV members | 1.036 |
| Leaderboard Answer Accuracy | `0.2787` — user-reported official result |

Provenance máy đọc nằm tại `provenance/submissions/p0_answer_baseline_02787_20260829.json`.

## Validation và replay

```text
strict validation: PASS
records:           1012
errors:            0
warnings:          0

clean replay:      PASS
executed:          604
matched:           604
no evidence:       408
execution errors:  0
```

Gate này chứng minh package hợp lệ và query tái lập đúng answer đã đóng gói. Nó không tự chứng minh 604 answer đúng theo gold.

## Data identity

| Layer | Identity |
|---|---|
| Raw | `vifinqa-btc-2026` / `ca033190f2e9e99f` |
| A6 | `c6887fb633374fad` |
| Retrieval | `872ccb0dda9a2bb6` |
| Repo HEAD khi nhận ZIP | `5e32eb38eebbcaa48a90f72b1db33ddc4702514e` |

Repo HEAD ở trên chỉ là thời điểm nhận artifact. Commit và runtime flags đã sinh ZIP không được cung cấp, vì vậy được ghi `null`, không suy đoán. Differential P0 phải so theo exact ZIP SHA và công bố hạn chế provenance này.

## MODEL_GOLD freeze

| Thuộc tính | Giá trị |
|---|---:|
| Generator resumed | `false` |
| Completed | 71 |
| RESOLVED / AMBIGUOUS / UNRESOLVED | 51 / 0 / 20 |
| `PARTIAL_CHECKPOINT.json` SHA-256 | `2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636` |
| `generation_state.json` SHA-256 | `b306c8fc96a818ce8da7162afac14976636224572b33f074ebd506df942f3a8d` |

MODEL_GOLD không được dùng làm runtime prediction hoặc làm bằng chứng accuracy cho P0.

## Gate sang P0.1

`PASS` với giới hạn rõ ràng: exact package và score đã được seal, nhưng generation commit/config của artifact là `UNKNOWN`. P0.1 được phép triển khai contract `MetricSpec/SelectorSpec`; behavior submission vẫn giữ nguyên cho đến khi shadow differential chứng minh có lợi.
