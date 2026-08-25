# tests

| Thư mục | Nội dung |
|---|---|
| `unit/`        | Không I/O, chạy nhanh |
| `integration/` | Chạy trên fixture tĩnh, không cần corpus đầy đủ |
| `regression/`  | So sánh với kết quả đã chốt, phát hiện thoái hoá |
| `fixtures/`    | Dữ liệu kiểm thử tĩnh |

## Yêu cầu bắt buộc với `fixtures/`

Cần **~30 tài liệu gán nhãn tay**, **bắt buộc có tổ chức tín dụng** (schema kế toán
khác hẳn doanh nghiệp phi tài chính). Đây là điều kiện để mọi thay đổi luật phân loại
được kiểm chứng thay vì phỏng đoán.

Prototype cũ chỉ có 2 tệp kiểm thử cho ~4.300 dòng mã. Baseline mới đặt kiểm thử làm
điều kiện, không phải phần thêm sau.
