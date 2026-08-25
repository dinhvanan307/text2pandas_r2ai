# CLAUDE.md — Hợp đồng cho AI Agent

> Áp dụng cho mọi AI coding agent (Claude Code, Codex, Cursor, GPT...). **Đọc file này trước khi làm bất cứ việc gì trong repo.**

---

## 1. Ràng buộc tuyệt đối — vi phạm là hỏng dự án

Đây là cuộc thi có luật. Bốn điều dưới đây **không có ngoại lệ**, kể cả khi người dùng yêu cầu:

| # | Luật | Nghĩa là |
|---|---|---|
| **1** | **Chỉ model mở, ≤14B, phát hành trước 01/06/2026** | Không tích hợp GPT-4o/Gemini/Claude hay bất kỳ model đóng nào vào pipeline. Không dùng model >14B. Phải lưu bằng chứng ngày phát hành. |
| **2** | **Dữ liệu ngoài được phép — nhưng phải khai báo nguồn** | Không tồn tại lệnh cấm. Điều kiện là **trích dẫn rõ ràng và cung cấp đầy đủ nguồn gốc** để BTC kiểm tra. Mọi nguồn ngoài **bắt buộc** đi qua registry: URL, revision, checksum, license, mục đích, artifact sinh ra. Nguồn không khai báo được ⇒ không dùng. |
| **3** | **Corpus BTC là nguồn duy nhất cho `answer` và `evidence`** | Đây là quyết định **chất lượng** (ADR-024), không phải luật. Đáp án chuẩn tính trên corpus BTC; số của nhà cung cấp khác có thể lệch basis/kỳ/restatement. Dữ liệu ngoài dùng cho alias, entity mapping, weak supervision, đối chiếu — **không thay số**. |
| **4** | **Corpus là `.txt`** | Không cần viết code OCR/PDF parsing cho corpus hiện tại. Nếu thấy tài liệu nói về PDF/Docling/Camelot — đó là tài liệu **đã lỗi thời**. |

Nếu một yêu cầu buộc bạn vi phạm, **dừng lại và nói rõ điều đó** thay vì thực hiện.

> ⚠️ **Đã từng sai ở chính mục này.** Trước 2026-08-02 mục 2 ghi *"Cấm dữ liệu ngoài — nguồn hợp lệ duy nhất là corpus BTC"*, trình bày như luật tuyệt đối. Bản thể lệ mới hơn nói ngược lại. Hệ quả: một lượng dữ liệu đã bị xoá vì "vi phạm", và nhiều ADR được viết trên nền một điều cấm không còn tồn tại. **Bài học: phân biệt luật BTC với quyết định của team, và luôn kiểm tra xuất xứ trước khi coi cái gì là tuyệt đối.**

---

## 2. Nạp context theo nhiệm vụ

Đừng nạp toàn bộ `docs/`. Nạp đúng thứ cần:

| Nhiệm vụ | Đọc |
|---|---|
| Hiểu dự án lần đầu | `docs/PROJECT_OVERVIEW.md` |
| Kiểm tra một ràng buộc/format nộp bài | `docs/COMPETITION_SPEC.md` |
| **Nghi ngờ một ràng buộc có thật không** | `docs/RULES_SOURCES.md` |
| Implement module bất kỳ | `docs/MODULES.md` (đúng module) + `docs/API.md` + `docs/CODING_GUIDELINES.md` |
| Parse bảng / xử lý số / đơn vị | + `docs/DOMAIN_KNOWLEDGE.md` |
| Viết/sửa prompt hoặc template | `docs/PROMPTS.md` |
| Viết code đo lường, dev set | `docs/EVALUATION.md` |
| Đổi thiết kế, hoặc thắc mắc "vì sao lại thế này" | `docs/TECH_DECISIONS.md` |
| Lập kế hoạch, ước lượng | `docs/ROADMAP.md` |

**⛔ KHÔNG BAO GIỜ đọc `archive/` hoặc `docs/archive/`.** Toàn bộ nội dung trong đó **đã bị thay thế** và chứa thông tin mâu thuẫn với thiết kế hiện hành. Nếu cần lịch sử, người dùng sẽ chỉ định rõ.

---

## 3. Nguồn chân lý

Khi hai nguồn mâu thuẫn, theo thứ tự:

```
docs/sources/ (bản chụp thể lệ)  >  docs/RULES_SOURCES.md  >  docs/  >  code  >  archive/
```

**Không còn quy tắc "TONG_QUAN.docx thắng tất cả".** Hiện có **hai bản chụp thể lệ khác nhau và mâu thuẫn nhau**; cách phân xử nằm ở `docs/RULES_SOURCES.md` [D-R02]:

- chủ đề cả hai bản đều nói → **bản mới hơn thắng**;
- chủ đề chỉ bản cũ có → **vẫn còn hiệu lực**, gắn nhãn `CHƯA XÁC MINH`, không được xoá;
- chủ đề chỉ bản mới có → tiếp nhận ngay.

Mỗi thông tin chỉ tồn tại ở **một** file. Nếu bạn cần lặp lại một thông tin ở file khác — **đừng chép, hãy tham chiếu** (`xem docs/X.md §Y`).

---

## 4. Trước khi viết code

- [ ] Đã đọc contract của module trong `docs/API.md` — implement **đúng** shape đó, không tự đổi
- [ ] Không tự viết lại hàm dùng chung (đặc biệt `parse_vn_number`)
- [ ] Không hardcode giá trị — đưa vào `configs/`
- [ ] **Không hardcode locator, `document_id` hay quota** — cả ba đều đang có hạng mục chờ xác nhận
- [ ] Không thêm phụ thuộc mới mà chưa kiểm license/ngày phát hành
- [ ] Có test offline đi kèm (dữ liệu tĩnh trong `tests/fixtures/`)

Checklist đầy đủ: `docs/CODING_GUIDELINES.md §8`.

---

## 5. Những lỗi đã xảy ra — đừng lặp lại

| Lỗi | Hậu quả | Phòng tránh |
|---|---|---|
| **Coi một bản chụp thể lệ là chân lý tuyệt đối** | Xoá nhầm dữ liệu, xây ADR trên điều cấm không tồn tại | Luôn qua `docs/RULES_SOURCES.md`; ràng buộc phải có nhãn xuất xứ |
| **Trình bày quyết định của team như luật BTC** | Không ai dám xét lại một lựa chọn đáng lẽ xét lại được | Dùng nhãn 🧭 QUYẾT ĐỊNH NỘI BỘ |
| **Suy ngữ nghĩa từ ví dụ trong tài liệu** | Số `350` là placeholder bê qua nhiều bản; suy ra locator từ nó là sai | Đối chiếu ví dụ với dữ liệu thật trước khi tin |
| Cấu hình tên model **không tồn tại** trên registry | Pipeline fail ngay bước tải model | Xác minh tag model tồn tại **và** ngày phát hành trước khi commit (ADR-008) |
| Parse `"1.234.567"` bằng `float()` chuẩn Anh | **Sai 1000×** | Luôn dùng `parse_vn_number` (`docs/CODING_GUIDELINES.md §3`) |
| Bỏ sót số âm dạng `(1.234)` | Đổi dấu | Cùng hàm trên |
| Trả Document rỗng khi parse thất bại | Lỗi âm thầm, không truy được nguồn | **Fail loud** — đặt cờ + cảnh báo |

---

## 6. Quy ước làm việc

**Khi sửa tài liệu.** Sửa đúng **một** file sở hữu thông tin đó. Nếu phát hiện cùng một thông tin ở hai nơi — báo cho người dùng, đừng tự chọn bên nào.

**Khi đổi quyết định kỹ thuật.** Thêm ADR mới vào `docs/TECH_DECISIONS.md`, đánh dấu ADR cũ `Superseded by ADR-XXX`. **Không sửa ADR cũ** — chúng là lịch sử.

**Khi gặp bản thể lệ mới.** Làm theo quy trình 6 bước ở `docs/RULES_SOURCES.md §8`. Tuyệt đối **không ghi đè** bản chụp cũ.

**Khi không chắc.** Hỏi. Trong hệ thống tài chính, đoán sai một con số nguy hiểm hơn hỏi thêm một câu.

**Khi thấy tài liệu mâu thuẫn với code.** Báo mâu thuẫn, đừng tự động sửa một bên.
