# dataset_report.md — Báo cáo tải & kiểm tra toàn vẹn ViFinQA

> **Trạng thái:** ✅ ĐẠT — 13/13 mục kiểm tra khớp Dataset Card
> **Sinh tự động bởi:** `download_vifinqa.py`
> **Phạm vi:** CHỈ tải và kiểm kê. Không tiền xử lý, không parse bảng, không dựng DataFrame, không embedding, không OCR, không xây dựng module AI.

---

## 1. Nguồn tải

| Mục | Giá trị |
|---|---|
| Dataset (Hugging Face) | `AIGuruTinix/ViFinQA` |
| Loại repo | `dataset` |
| URL | https://huggingface.co/datasets/AIGuruTinix/ViFinQA |
| Codebase (GitHub) | https://github.com/DSKT-NOWJ/ViFinQA.git |
| Phương thức | `huggingface_hub.snapshot_download` (idempotent, resumable) |

## 2. Ngày tải & phiên bản

| Mục | Giá trị |
|---|---|
| Ngày tải (UTC) | 2026-08-01 07:44:09 |
| Revision dataset (commit sha) | `0450088ab22ec946f04f097586967ca405955b3b` |
| Sửa đổi gần nhất trên Hub | 2026-07-31 16:30:49+00:00 |
| Commit codebase | `a1c09cc0ed8a0474e27749a40e5c3ac174a660da` |
| File log | `/Users/andinh307/Documents/Dagoras-R2AI/text2pandas/Text2Pandas/data/external/_logs/download_vifinqa_20260801T073909Z.log` |

## 3. License

- **Corpus báo cáo tài chính:** CC BY-NC 4.0 (corpus nguồn TiniX); license riêng cho phần annotation câu hỏi: KHÔNG nêu
- Corpus nguồn: `tinixai/ocr_annual_financials` — **CC BY-NC 4.0**
  (Creative Commons Attribution-NonCommercial 4.0 International)
- **Ràng buộc:** phải giữ ghi công (attribution) và **chỉ dùng phi thương mại**.
- **Lưu ý:** Dataset Card nêu rõ *không có file license riêng cho phần annotation câu hỏi*; không được giả định quyền rộng hơn những gì đã được cấp tường minh.

## 4. Kích thước & tổng số file

| Mục | Giá trị |
|---|---|
| Tổng số file dữ liệu | **1,978** |
| Tổng dung lượng dữ liệu | **362.86 MiB** |
| Dung lượng riêng phần báo cáo `.txt` | 362.62 MiB |
| Tổng số file (gồm cả codebase & metadata) | 6,258 |

**Phân bố theo phần mở rộng:**

| Đuôi file | Số lượng |
|---|---:|
| `.txt` | 1,973 |
| `.md` | 2 |
| `<no-ext>` | 1 |
| `.csv` | 1 |
| `.jsonl` | 1 |

## 5. Cấu trúc thư mục

```text
vifinqa/
├── financial_statements/
│   ├── AAA/
│   │   ├── 2015/
│   │   │   └── AAA_financial_statements_2015_consolidated/
│   │   │       └── AAA_financial_statements_2015_consolidated_extracted.txt
│   │   └── ... (9 năm khác)
│   │   ├── 2016/
│   │   │   └── AAA_financial_statements_2016_consolidated/
│   │   │       └── AAA_financial_statements_2016_consolidated_extracted.txt
│   │   └── ... (9 năm khác)
│   ├── ABB/
│   │   ├── 2020/
│   │   │   └── ABB_financial_statements_2020_consolidated/
│   │   │       └── ABB_financial_statements_2020_consolidated_extracted.txt
│   │   └── ... (4 năm khác)
│   │   ├── 2021/
│   │   │   └── ABB_financial_statements_2021_consolidated/
│   │   │       └── ABB_financial_statements_2021_consolidated_extracted.txt
│   │   └── ... (4 năm khác)
│   ├── ACB/
│   │   ├── 2015/
│   │   │   └── ACB_financial_statements_2015_consolidated/
│   │   │       └── ACB_financial_statements_2015_consolidated_extracted.txt
│   │   └── ... (9 năm khác)
│   │   ├── 2016/
│   │   │   └── ACB_financial_statements_2016_consolidated/
│   │   │       └── ACB_financial_statements_2016_consolidated_extracted.txt
│   │   └── ... (9 năm khác)
│   └── ... (97 ticker khác)
├── questions/
│   └── questions.jsonl
└── code_stock.csv
```

## 6. Kiểm tra tính đầy đủ

Đối chiếu số đếm thực tế với con số **công bố trong Dataset Card**.

| Mục kiểm tra | Card công bố | Thực tế | Kết quả |
|---|---:|---:|:---:|
| Số câu hỏi | 1012 | 1012 | ✅ |
| Số id câu hỏi duy nhất | 1012 | 1012 | ✅ |
| id nhỏ nhất | 1 | 1 | ✅ |
| id lớn nhất | 1012 | 1012 | ✅ |
| Số báo cáo (.txt) | 1973 | 1973 | ✅ |
| Số công ty (code_stock.csv) | 100 | 100 | ✅ |
| Số ticker trong cây thư mục | 100 | 100 | ✅ |
| Năm nhỏ nhất | 2015 | 2015 | ✅ |
| Năm lớn nhất | 2025 | 2025 | ✅ |
| Báo cáo loại 'consolidated' | 957 | 957 | ✅ |
| Báo cáo loại 'separate' | 954 | 954 | ✅ |
| Báo cáo loại 'aggregated' | 7 | 7 | ✅ |
| Báo cáo loại 'other' | 55 | 55 | ✅ |

**Tổng kết: 13/13 mục khớp.**

### 6.1. Chi tiết `questions/questions.jsonl`

| Mục | Giá trị |
|---|---|
| Số dòng hợp lệ | 1,012 |
| Số `id` duy nhất | 1,012 |
| Khoảng `id` | [1 .. 1012] |
| `id` trùng lặp | 0 |
| `id` thiếu so với 1..1012 | 0 |
| `id` ngoài dải 1..1012 | 0 |
| Dòng JSON hỏng | 0 |
| Câu hỏi rỗng | 0 |
| Kích thước file | 219.80 KiB |

### 6.2. Chi tiết `code_stock.csv`

| Mục | Giá trị |
|---|---|
| Số dòng | 100 |
| Cột | `['Mã CK', 'Tên công ty']` |
| Mã CK duy nhất | 100 |
| Mã CK trùng | 0 |

### 6.3. Chi tiết `financial_statements/`

| Mục | Giá trị |
|---|---|
| Số file `.txt` đúng cấu trúc `TICKER/YEAR/DOC/` | 1,973 |
| File `.txt` nằm sai độ sâu | 0 |
| Số ticker trong cây thư mục | 100 |
| Khoảng năm | [2015 .. 2025] |
| Thư mục năm không phải số | [] |
| Số báo cáo/ticker (min–max) | 6–29 |
| File rỗng (0 byte) | 0 |

**Phân bố theo loại báo cáo** (phân loại theo tên file):

| Loại | Card công bố | Thực tế |
|---|---:|---:|
| consolidated | 957 | 957 |
| separate | 954 | 954 |
| aggregated | 7 | 7 |
| other | 55 | 55 |

**Phân bố theo năm:**

| Năm | Số báo cáo |
|---|---:|
| 2015 | 125 |
| 2016 | 146 |
| 2017 | 164 |
| 2018 | 173 |
| 2019 | 180 |
| 2020 | 196 |
| 2021 | 193 |
| 2022 | 201 |
| 2023 | 195 |
| 2024 | 200 |
| 2025 | 200 |

## 7. Lỗi & cảnh báo phát hiện

Không phát hiện lỗi hay cảnh báo nào.
## 8. Vị trí lưu trữ

```
/Users/andinh307/Documents/Dagoras-R2AI/text2pandas/Text2Pandas/data/external/vifinqa
```

Toàn bộ tên file và cấu trúc thư mục **giữ nguyên như nguồn**. Không đổi tên, không sửa nội dung, không chuyển đổi định dạng.

---

*Sinh tự động lúc 2026-08-01 07:44:09 UTC. Script chỉ tải và kiểm kê — không thực hiện bất kỳ bước xử lý dữ liệu nào.*