# Curated evaluation data

`legacy/` chứa các evaluation fixtures nhỏ đã được review và đang được nhiều
audit/replay tools dùng như input. Chúng được commit vì là test/evaluation
contract; output mới phải ghi vào `artifacts/runs/evaluation/<run_id>/` rồi chỉ
promote vào đây qua review riêng.

Không đặt model cache, logs, submission ZIP hoặc database trong thư mục này.
