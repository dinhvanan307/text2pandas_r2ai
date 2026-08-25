# Experiments

Code trong thư mục này phục vụ ablation, re-audit và phân tích offline; không
được import bởi production package dưới `src/text2pandas/`.

- `retrieval/ablation/`: các thí nghiệm E1/E2 và evidence builder.
- `retrieval/reaudit/`: chuỗi kiểm toán retrieval M1–M15.

Mọi output phải ghi vào `artifacts/runs/<pipeline>/<run_id>/`, không ghi cạnh
source. Script được chạy từ repository root trên environment đã `pip install -e .`.
