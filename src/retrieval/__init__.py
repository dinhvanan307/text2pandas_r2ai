"""Tầng Retrieval cho VIFinQA.

RÀNG BUỘC BỐ CỤC · KHÔNG ĐƯỢC VI PHẠM
--------------------------------------
`build_id = f(source_hash, config_hash)` với

    source_hash = sha256(nội dung src/data_pipeline/*.py theo tên)
    config_hash = sha256(nội dung configs/*.yaml theo tên)

Gói Silver A6 `b3e9684004679ffb` đã được chứng nhận từ cây nguồn hiện tại. Đặt
mã của tầng này vào `src/data_pipeline/` hoặc `configs/*.yaml` sẽ đổi
`build_id` ở commit kế tiếp, và gói A6 không còn tái lập được — toàn bộ chuỗi
bằng chứng C0/C1/C5/RC-20 mất hiệu lực truy nguyên dù không một byte dữ liệu
nào đổi.

Vì vậy: mã ở `src/retrieval/**`, cấu hình ở `configs/retrieval/*.yaml` (thư
mục CON, nên không khớp `configs/*.yaml`).

Kiểm: thêm một tệp vào đây rồi chạy `make dp-env-check`; `source_hash` phải
vẫn là `f5fea1fa4e7c94c3`.
"""

RETRIEVAL_VERSION = "0.1.0"
SILVER_BUILD_ID = "b3e9684004679ffb"
