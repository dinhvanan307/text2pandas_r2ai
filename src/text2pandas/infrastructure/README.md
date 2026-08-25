# infrastructure — Adapter

Hiện thực các cổng khai báo ở `application/ports/`. Đây là nơi duy nhất được phép
chạm tới hệ tệp, tiến trình con, thư viện bên thứ ba.

| Thư mục | Trách nhiệm |
|---|---|
| `catalog/`   | Đọc/ghi Corpus Catalog |
| `parsing/`   | Bóc tách bảng từ văn bản có markup |
| `storage/`   | Bronze/Silver/Gold, định dạng cột |
| `retrieval/` | Chỉ mục từ vựng, vector, lọc có cấu trúc |
| `llm/`       | Client model open-weight (kiểm C05–C07 trước khi thêm) |
| `sandbox/`   | Thực thi mã cách ly — **không mạng**, giới hạn tài nguyên |

⚠️ **Cấm tuyệt đối:** mọi lời gọi mạng trong đường xử lý dữ liệu (ràng buộc C04).
