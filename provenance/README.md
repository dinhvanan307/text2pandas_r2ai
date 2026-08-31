# Provenance

Thư mục này chỉ lưu manifest, checksum và audit seal dung lượng nhỏ được quản lý
bởi Git. Dữ liệu raw, A6, retrieval index và các package lớn không được commit.

Mỗi manifest phải dùng đường dẫn tương đối, nêu rõ source identity và đủ thông tin
để kiểm tra artifact vật lý tương ứng.

`submissions/` giữ identity nhỏ của các ZIP đã được leaderboard chấm. Xác nhận
artifact, source commit, config và receipt là các trường độc lập; không được suy
diễn trường còn thiếu từ tên file hoặc thời gian sửa.
