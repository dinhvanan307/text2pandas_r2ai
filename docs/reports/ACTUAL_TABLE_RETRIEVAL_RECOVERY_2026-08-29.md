# Actual Table Retrieval Recovery — 2026-08-29

## Kết luận hiện tại

Đã tạo được một **local winner** thực sự thay đổi đường đi của gold table và
không thay đổi answer/status so với artifact của submission 3766. Candidate đã
qua full 1.012 QID, validator, clean replay và A/B byte determinism.

Chưa được phép kết luận official improvement: lần mở
`https://leaderboard.aiguru.com.vn/` để upload bị browser từ chối quyền truy
cập. Không có submission ID mới hoặc official receipt, nên mọi số candidate
dưới đây được ghi đúng là development proxy, không phải leaderboard score.

Q954 không được tối ưu trong task này. Ở candidate cuối, Q954 byte-equivalent
với baseline về status, answer và table refs.

## 1. Code changes và commit

Hai commit triển khai:

- `6775f276582383dcebb7ab9094d5bf3345b8071d` — adaptive Output-N, controlled
  S2 profiles, optional semantic binding preference, CLI/config provenance và
  evaluator Output-N;
- `39665000ceee411ad87c858f1839c8d2344903df` — tách scorer-facing S2 ranking
  khỏi baseline answer pool và thêm full candidate comparator.

Thay đổi chính:

- adaptive output bắt đầu từ scope-derived `base_n`, mở rộng khi S2 score còn
  trong margin `0.50`, cap `10`;
- S2 candidate dùng `primary_boost=0.60`;
- answer pool vẫn dùng baseline ranker để tránh scorer experiment làm đổi
  answer ngoài ý muốn;
- binding preference là cờ thử nghiệm, đã bị tắt trong release candidate;
- checkpoint schema được bump `evalkit-12 → evalkit-13`, có ADR và behavior
  fingerprint gate;
- comparator sinh đúng `metrics.json`, `per_qid_diff.jsonl` và
  `regression_report.json`.

Verification: `make ci` PASS với 2.102 passed, 42 skipped, 29 deselected; lint,
type-check và Markdown link-check đều PASS.

## 2. Baseline official — submission 3766

| Metric | Score |
|---|---:|
| Execution Accuracy | 0,2589 |
| Tables F2-Macro | 0,2500 |
| Tables Precision | 0,2921 |
| Tables Recall | 0,2461 |
| Tables MRR5 | 0,3360 |
| Docs F2-Macro | 0,6326 |
| Docs Precision | 0,6890 |
| Docs Recall | 0,6257 |
| Docs MRR5 | 0,7630 |
| Answer Accuracy | 0,2589 |

Baseline canonical artifact:
`artifacts/runs/answer/table-retrieval-full-recovery-7ed2bfe-a-20260828-01/records.jsonl`.

## 3. Failure matrix

Failure attribution trên 95 QID có manual gold, không đếm chồng:

| Failure stage | QID |
|---|---:|
| `OUTPUT_N_LOSS` | 23 |
| `BINDING_LOSS` | 10 |
| `S2_RANK_LOSS` | 8 |
| `NO_LOSS` | 54 |
| Tổng | 95 |

Artifact đầy đủ từng QID gồm gold, S1/S2 hit, gold rank, output N, binding và
final refs:
`artifacts/runs/retrieval/actual-table-retrieval-output-n-ce1772a-20260828-02/failure_matrix.jsonl`.

## 4. Experiment matrix — Output-N

Các metric sau là development proxy trên 95 manual-gold QID, không phải
official score.

| Experiment | P | R | F2 | MRR5 | Mean tables | Full changed / additions / removals |
|---|---:|---:|---:|---:|---:|---:|
| E0 current | 0,4402 | 0,3746 | 0,3814 | 0,4921 | 3,34 | 0 / 0 / 0 |
| E1 fixed 5 | 0,4232 | 0,4123 | 0,3891 | 0,5137 | 3,20 | 411 / 834 / 274 |
| E2 fixed 7 | 0,4180 | 0,4368 | 0,4013 | 0,5137 | 4,15 | 438 / 1.565 / 111 |
| E3 fixed 10 | 0,4063 | 0,4833 | 0,4222 | 0,5137 | 5,57 | 422 / 2.795 / 0 |
| E4 margin 0,10 | 0,4458 | 0,4157 | 0,4121 | 0,5042 | 3,96 | 246 / 673 / 0 |
| E4 margin 0,20 | 0,4420 | 0,4327 | 0,4204 | 0,5068 | 4,37 | 327 / 1.186 / 0 |
| E4 margin 0,30 | 0,4239 | 0,4513 | 0,4261 | 0,5095 | 4,87 | 386 / 1.780 / 0 |
| **E4 margin 0,50** | **0,4162** | **0,4833** | **0,4347** | **0,5137** | **5,23** | **416 / 2.471 / 0** |
| E5 legacy scope×3 cap30 | 0,3844 | 0,4729 | 0,4343 | 0,5042 | 8,35 | 447 / 3.350 / 0 |

Winner: E4 score margin `0.50`, cap `10`. Nó có F2 cao nhất và precision tốt
hơn legacy cap30, đồng thời đạt Recall ngang fixed10.

Artifact:
`artifacts/runs/retrieval/actual-table-retrieval-output-n-ce1772a-20260828-02/metrics.json`.

## 5. Ranking experiments

Mỗi profile chỉ thay một tín hiệu và đều chạy 1.012 QID.

| Experiment | ΔF2@N* | Δhit@10 | ΔMRR | Flip in / out | Decision |
|---|---:|---:|---:|---:|---|
| `primary_boost=0.60` | +0,0219 | +0,0632 | +0,0411 | 6 / 0 | **WINNER** |
| `per_ticker_k=2` | +0,0201 | +0,0105 | -0,0001 | 1 / 0 | reject |
| `stop_mode=dau` | +0,0192 | +0,0105 | +0,0143 | 1 / 0 | reject |
| unit bonus off | F2 nhỏ tăng, không top10 flip | 0 | 0 | 0 / 0 | reject |
| period bonus off | giảm | giảm | giảm | — | reject |

Primary boost đưa gold vào top-10 cho Q374, Q376, Q385, Q436, Q542 và Q975,
không có flip-out trên manual gold. Checkpoint:
`artifacts/runs/retrieval/evalkit/metrics_manual_primary_d6c90d18315f4e96.json`.

## 6. Binding experiments

Target audit: Q305, Q342, Q351, Q354, Q636, Q743, Q748, Q780, Q860, Q910.
Conservative selector đã sửa exact evidence cho Q305, Q342, Q351, Q354 và
Q636 trong targeted run, không hard-code QID.

Tuy nhiên full 1.012 candidate có binding preference tạo:

- 12 `ANSWER_LOSS` và 12 `EXECUTION_LOSS`;
- 2 structural wins;
- answered giảm 564 → 554;
- 160 answer khác khi cả hai phía đều `OK` nhưng không có independent answer
  gold.

Vì vậy binding candidate bị loại. Release candidate giữ semantic code sau cờ
thử nghiệm nhưng đặt `prefer_retrieval_output_in_binding=false`.

Rejected artifact:
`artifacts/runs/evaluation/actual-table-retrieval-recovery-compare-binding-3966500-20260829-01/`.

## 7. Combined full 1.012 result

Release candidate chỉ combine hai winner: E4 margin 0,50 + S2 primary boost
0,60; baseline answer pool được giữ độc lập.

| Full metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Questions | 1.012 | 1.012 | 0 |
| Answered | 564 | 564 | 0 |
| Abstained | 448 | 448 | 0 |
| Empty table refs | 1 | 1 | 0 |
| Mean relevant tables | 2,5385 | 4,9901 | +2,4516 |
| Max relevant tables | 10 | 10 | 0 |
| Changed QIDs | — | 444 | — |
| Table additions | — | 2.942 | — |
| Table removals | — | 461 | — |
| `ANSWER_LOSS` | — | 0 | 0 |
| `EXECUTION_LOSS` | — | 0 | 0 |

Per-QID classification:

| Class | Count |
|---|---:|
| `UNCHANGED` | 568 |
| `TABLE_WIN` | 36 |
| `TABLE_LOSS` / `NEW_TABLE_REGRESSION` | 7 |
| `TABLE_CHANGED_NEUTRAL` | 2 |
| `TABLE_CHANGED_UNMEASURED` | 399 |
| `ANSWER_WIN` / `ANSWER_LOSS` | 0 / 0 |
| `EXECUTION_WIN` / `EXECUTION_LOSS` | 0 / 0 |
| `NEW_ANSWER_REGRESSION` | 0 |
| `NEW_EXECUTION_REGRESSION` | 0 |

`TABLE_WIN`/`TABLE_LOSS` chỉ được gắn cho QID có manual gold. Các QID còn lại
không bị suy diễn thành win.

Development proxy trên 95 manual-gold QID:

| Metric | Baseline | Candidate | Delta |
|---|---:|---:|---:|
| Tables Precision | 0,4402 | 0,4560 | +0,0157 |
| Tables Recall | 0,3746 | 0,5265 | +0,1519 |
| Tables F2-Macro | 0,3814 | 0,4752 | +0,0938 |
| Tables MRR5 | 0,4921 | 0,5632 | +0,0711 |

Artifacts bắt buộc:

- metrics: `artifacts/runs/evaluation/actual-table-retrieval-recovery-compare-safe-3966500-20260829-01/metrics.json`;
- per-QID diff: `artifacts/runs/evaluation/actual-table-retrieval-recovery-compare-safe-3966500-20260829-01/per_qid_diff.jsonl`;
- regression report: `artifacts/runs/evaluation/actual-table-retrieval-recovery-compare-safe-3966500-20260829-01/regression_report.json`.

## 8. Candidate ZIP, provenance và determinism

Candidate ZIP:
`artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip`.

| Provenance | Value |
|---|---|
| SHA-256 | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| Bytes | 1.051.922 |
| Commit | `39665000ceee411ad87c858f1839c8d2344903df` |
| Config SHA-256 | `0a498248918be263a0111a4caae9b5f10080f8c16c03be457db0f20f1fdfa622` |
| Dataset / raw snapshot | `vifinqa-btc-2026` / `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |

Run A và B byte-identical:

| Layer | SHA-256 | Result |
|---|---|---|
| `records.jsonl` | `efd0737b4cac772d5b3b591a9640ac615aa239e3aa2d310b3702f6c85f462d77` | PASS |
| `submission.json` | `9f2c45e54ccd1309a31caaef91f1305c45183400a5dde7b7eee6bd5ab919c38f` | PASS |
| ZIP | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` | PASS |

Determinism artifact:
`artifacts/runs/evaluation/actual-table-retrieval-recovery-compare-safe-3966500-20260829-01/determinism_gate.json`.

## 9. Official submission status

| Deliverable | Status |
|---|---|
| Official submission ID | `NOT_CREATED` |
| Upload | `BLOCKED_USER_DENIED_BROWSER_PERMISSION` |
| Official before/after | baseline có; candidate `NOT_MEASURED` |
| Official delta | `NOT_MEASURED` |

Không dùng local proxy để tuyên bố leaderboard improvement. Khi browser được
cho phép, bước tiếp theo duy nhất là upload exact ZIP SHA-256 ở trên, lấy receipt
và cập nhật mục này.

## 10. Trả lời câu hỏi bắt buộc

```text
Submission 3766:
Tables Recall = 0.2461

Submission NEW:
Tables Recall = NOT_MEASURED

Delta:
NOT_MEASURED - 0.2461 = NOT_MEASURED

Result:
NOT VERIFIED — chưa được phép kết luận IMPROVED hoặc NOT IMPROVED
```

**Tables Recall có tăng thật trên leaderboard không? Chưa thể xác nhận, vì
candidate chưa được upload do quyền browser bị từ chối.**
