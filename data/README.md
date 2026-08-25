# Runtime data

Thư mục này là data root mặc định và không được commit payload lớn vào Git.

```text
raw/btc/                                      dữ liệu gốc bất biến của BTC
processed/a6/<build_id>/                      dữ liệu A6 đã xử lý
indexes/retrieval/<a6_build_id>/<index_id>/   index dẫn xuất từ A6
curated/dev/                                  nhãn dev được quản trị
curated/gold/                                 gold data được quản trị
```

Có thể đặt dữ liệu trên volume khác bằng `T2P_DATA_ROOT`. Active versions được
chọn trong `configs/datasets/active_snapshot.yaml`, không chọn ngầm theo tên
`latest` hoặc thời gian sửa file.

Chỉ `README.md`, `manifest.json` và checksum nhỏ được phép vào Git.
