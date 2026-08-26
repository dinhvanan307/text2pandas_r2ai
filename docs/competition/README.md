# Competition source

`Text2Pandas.docx` là đề bài được cung cấp cho workspace, giữ nguyên bytes để
đối chiếu quy định và submission contract.

- SHA-256: `45a8afcf228d12fe90af0ef4d7d163032b0b0d8003af724d8449e58e862e3081`
- Ngày đưa vào repository: 2026-08-25

Tài liệu có các đoạn chưa nhất quán về dữ liệu ngoài: trang 4 cấm dữ liệu ngoài
ở mọi bước, trong khi trang 12 cho phép dữ liệu công khai và hợp pháp. Dự án áp
dụng cách hiểu chặt hơn, corpus-only, theo
[`ADR 0009`](../adr/0009-corpus-only-data-policy.md) cho tới khi ban tổ chức có
văn bản làm rõ.

Ma trận chuyển yêu cầu thành acceptance gate nằm tại
[`REQUIREMENTS_TRACEABILITY.md`](../REQUIREMENTS_TRACEABILITY.md).
