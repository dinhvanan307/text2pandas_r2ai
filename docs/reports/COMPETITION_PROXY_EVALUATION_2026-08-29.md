# Competition proxy evaluation — 2026-08-29

## Kết luận

Đã triển khai một scorer thống nhất cho đúng vector 10 chỉ số đang hiển thị
trên leaderboard. Scorer dùng công thức macro-per-query trong đề bài, replay
`pandas_query` từ ZIP và fail-closed khi candidate regression bất kỳ metric
nào so với baseline.

Candidate `hybrid-safe-current-final-20bc8c1-20260829-01` tăng trên cả 10
local proxy metrics so với Canonical control, không có metric regression.

Đây là `LOCAL_DEVELOPMENT_PROXY_NOT_OFFICIAL`: BTC giữ kín gold và chưa công
bố tolerance Answer/Execution, do đó kết quả không bảo đảm bằng điểm official.

## Score vector

| Metric | Canonical control | Hybrid-safe | Delta |
|---|---:|---:|---:|
| Execution Accuracy | 0,4516 | **0,4839** | **+0,0323** |
| Tables F2-macro | 0,4677 | **0,4808** | **+0,0131** |
| Docs F2-macro | 0,7391 | **0,7567** | **+0,0175** |
| Tables Precision | 0,4525 | **0,4595** | **+0,0070** |
| Tables Recall | 0,5160 | **0,5318** | **+0,0158** |
| Tables MRR@5 | 0,5526 | **0,5768** | **+0,0242** |
| Docs Precision | 0,6806 | **0,6911** | **+0,0105** |
| Docs Recall | 0,7885 | **0,8096** | **+0,0211** |
| Docs MRR@5 | 0,7851 | **0,8114** | **+0,0263** |
| Answer Accuracy | 0,4516 | **0,4839** | **+0,0323** |

Denominator:

- retrieval: 95 development-gold questions;
- answer/execution: 31 adjudicated development-gold questions;
- package contract: 1.012 submission records;
- tolerance local: relative 0,5% với absolute floor; official tolerance chưa
  được BTC công bố.

Q506 là improvement duy nhất trên answer/execution slice; không có QID
regression. Candidate đạt 15/31, Canonical đạt 14/31.

Machine-readable report:
[`competition-proxy-hybrid-safe-vs-canonical-20260829.json`](../../artifacts/reports/evaluation/competition-proxy-hybrid-safe-vs-canonical-20260829.json).

## Metric semantics đã khóa bằng test

- Precision, Recall và F2 được tính từng query rồi mới macro-average.
- F2 không được tính lại từ hai số macro Precision/Recall.
- MRR@5 bằng reciprocal rank của relevant item đầu tiên trong top 5; hit sau
  vị trí 5 nhận 0.
- Duplicate prediction không được tăng số relevant hit.
- Missing QID vẫn nằm trong denominator và nhận 0.
- `line:<n>` nội bộ và locator `<n>` trong submission được chuẩn hóa về cùng
  một identity; `_extracted` không tạo document identity mới.
- Answer Accuracy chấm trường `answer`; Execution Accuracy chấm giá trị replay
  của `pandas_query`. Hai metric không bị gộp tautology.
- Query chỉ được chạy qua restricted AST evaluator, evidence đọc trực tiếp từ
  ZIP được submit.
- Candidate-vs-baseline gate yêu cầu cả 10 delta không âm.

Unit suite:
[`test_competition_evaluation.py`](../../tests/unit/test_competition_evaluation.py).

Production implementation:
[`competition_evaluation.py`](../../src/text2pandas/application/usecases/competition_evaluation.py)
và
[`evaluate_competition_proxy.py`](../../tools/evaluation/evaluate_competition_proxy.py).

## Cách chạy

```bash
make competition-proxy-eval PY=.venv/bin/python \
  CANDIDATE=artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/submission.zip \
  BASELINE=artifacts/submissions/submission_canonical-hybrid-control-fe6667e-20260829-01.zip \
  OUTPUT=artifacts/reports/evaluation/competition-proxy-next-run.json
```

Exit codes:

- `0`: package hợp lệ và không regression cả 10 metrics;
- `2`: submission contract validation fail;
- `3`: ít nhất một metric regression so với baseline.

Output là immutable; mỗi evaluation phải dùng tên report mới để giữ lineage.

## Giới hạn và chiến lược tối ưu đúng

Không thể chứng minh “best official score” chỉ bằng development gold vì:

1. BTC không cung cấp train/dev và giữ kín test gold.
2. 95/31 local cases nhỏ hơn 1.012 test questions và đã tham gia development.
3. Official Answer/Execution tolerance chưa công bố.
4. Phân phối private test có thể khác public/local cohort.

Vì vậy scorer này dùng để chọn candidate theo paired regression, không dùng để
tuyên bố điểm leaderboard. Bước nâng độ tin cậy tiếp theo là hoàn thành 300
independent semantic labels và 120 reranker held-out labels đã materialize;
sau đó chạy promotion evaluator. Không tối ưu trực tiếp bằng cách thử nhiều
submission lên leaderboard vì giới hạn 10 lượt/ngày và 5 lượt private tổng.
