# Gói dữ liệu Silver — ViFinQA (R2AI 2026)

Bản dựng `c6887fb633374fad` · hồ sơ `slim` · 2026-08-26T16:55:30Z

Copy thư mục này về máy là dùng được ngay. **Không cần** cài pipeline, không
cần corpus gốc, không cần chạy lại bản dựng 10 phút.

## Có gì bên trong

| | |
|---|---:|
| Tài liệu (báo cáo) | 1,973 |
| Bảng | 146,246 |
| Observation (ô số đã chuẩn hoá) | 2,634,120 |
| Thẻ bảng đã đánh chỉ mục toàn văn | 146,246 |

## Cấu trúc thư mục

```
silver_release/
├── silver.db              SQLite: PK, FK, chỉ mục, FTS5 — dùng ngay
├── data_preview.html      MỞ CÁI NÀY TRƯỚC — xem toàn bộ dữ liệu bằng trình duyệt
├── README.md              tệp này
├── DATA_OVERVIEW.md       dữ liệu là gì, phủ tới đâu, cái gì KHÔNG có trong gói
├── KNOWN_ISSUES.md        ĐỌC TRƯỚC KHI TIN — chỗ còn sai, còn thiếu, còn nợ
├── USAGE_GUIDE.md         công thức cho từng dạng câu hỏi + bốn luật bắt buộc
├── SILVER_REPORT.md       các bước xử lý, thống kê, lỗi đã sửa, cổng chất lượng
├── DATA_DICTIONARY.md     lược đồ, ý nghĩa từng cột, quan hệ giữa các bảng
├── manifest.json          thống kê, phiên bản, SHA-256 đầy đủ mọi tệp, thời điểm tạo
├── metadata/              documents.json · pages.json · tables.jsonl
├── dataframe/
│   ├── csv/               một tệp mỗi bảng dữ liệu (bảng lớn nén .gz)
│   │   └── by_table/      CSV từng bảng báo cáo — long/ và wide/
│   └── parquet/           cùng dữ liệu, nén zstd, đọc nhanh hơn nhiều
├── logs/                  nhật ký dựng + kết quả kiểm chất lượng
└── examples/              4 script chạy được ngay
```

## Đọc theo thứ tự nào

| Bạn là | Đọc | Vì sao |
|---|---|---|
| **Bất kỳ ai** | `KNOWN_ISSUES.md` | Biết trước gói này sai ở đâu, thay vì tự phát hiện vào tuần thứ ba. Mọi số trong đó truy vấn từ chính `silver.db` này. |
| **Text-to-Pandas** | `USAGE_GUIDE.md` §4, §5 | Bốn luật bắt buộc + công thức cho 10 dạng câu hỏi, kể cả *khi nào phải TỪ CHỐI trả lời*. |
| **Retrieval** | `USAGE_GUIDE.md` §6 · `DATA_OVERVIEW.md` §3 | Cách dùng `table_cards` + FTS5, và độ phủ thật theo mã × năm. |
| **Người kiểm toán** | `SILVER_REPORT.md` · `DATA_DICTIONARY.md` | Các bước xử lý, cổng chất lượng, lược đồ đầy đủ. |

## Bắt đầu trong 30 giây

Mở `data_preview.html` bằng trình duyệt. Không cần cài gì, không cần mở SQLite:
lược đồ từng bảng, 20 dòng mẫu, tỷ lệ rỗng theo cột, trùng lặp, sơ đồ quan hệ,
biểu đồ phân bố và độ phủ mã chứng khoán × năm đều nằm trong đó.

```bash
python examples/01_open_sqlite.py       # truy vấn SQLite
python examples/02_read_parquet.py      # nạp DataFrame
python examples/03_search_tables.py     # tìm bảng bằng FTS5
python examples/04_verify_package.py    # đối chiếu checksum
```

## Mở SQLite

```python
import sqlite3
conn = sqlite3.connect("file:silver.db?mode=ro", uri=True)   # chỉ đọc
conn.execute("PRAGMA foreign_keys=ON")

conn.execute("""
    SELECT row_path_text, period_end, value_decimal_text, unit_kind, confidence
    FROM observations
    WHERE ticker = 'VNM' AND doc_year = 2018
      AND statement_type = 'balance_sheet'
      AND confidence = 'high'
    LIMIT 20
""").fetchall()
```

## Đọc DataFrame

```python
import pandas as pd

# Parquet — nhanh hơn CSV nhiều lần, giữ nguyên kiểu chuỗi
obs = pd.read_parquet("dataframe/parquet/observations/part-0000.parquet")

# CSV (bảng lớn nén gzip)
obs = pd.read_csv("dataframe/csv/observations.csv.gz", compression="gzip",
                  dtype=str, keep_default_na=False)
```

## Ba điều BẮT BUỘC biết trước khi dùng

**1. `value_decimal_text` là CHUỖI, không phải số.** Corpus có giá trị tới
10¹⁵ VND; `float64` chỉ giữ chính xác 15–16 chữ số và sẽ làm tròn sai ngay.

```python
from decimal import Decimal
v = Decimal(row["value_decimal_text"])          # ĐÚNG
v = float(row["value_decimal_text"])            # SAI — mất chính xác
```

**2. Giá trị rỗng KHÔNG phải số 0.** 2,634,120 observation là
những ô **đọc được**. Ô dấu gạch ngang (`-`) trong báo cáo tài chính nghĩa là
*khuyết dữ liệu*, không phải *bằng không* — chúng cố ý không có mặt ở đây.
Điền 0 vào là tạo ra số liệu không tồn tại trong báo cáo.

**3. `confidence` có thật, hãy dùng nó.** `low` nghĩa là thiếu kỳ, hoặc đơn vị
là mặc định, hoặc cột chưa phân loại được vai trò. Tầng truy hồi nên hạ trọng
số thay vì tin như nhau.

```python
conn.execute("SELECT confidence, COUNT(*) FROM observations GROUP BY 1")
```

## Đơn vị và bậc 10

Giá trị lưu **đúng như in trên báo cáo**; `scale_exponent` cho biết phải nhân
bao nhiêu để ra VND.

```python
vnd = Decimal(row["value_decimal_text"]) * (10 ** int(row["scale_exponent"] or 0))
```

`0` = VND · `3` = nghìn đồng · `6` = triệu đồng · `9` = tỷ đồng.

## Trích dẫn bằng chứng (ràng buộc C20)

Dùng `evidence_ref` có sẵn, **đừng tự ghép chuỗi**:

```python
conn.execute("SELECT evidence_ref FROM tables WHERE table_uid=?", (uid,))
# → 'VNM_financial_statements_2018_consolidated|line:350'
```

## Tìm bảng bằng FTS5

```python
from text2pandas.pipelines.a6.text_normalize import fts_match_expr

conn.execute("""
    SELECT table_uid, ticker, section_text
    FROM table_cards_fts
    WHERE table_cards_fts MATCH ?
    LIMIT 10
""", (fts_match_expr("tiền và tương đương"),)).fetchall()
```

**Chỉ mục lưu ở DẠNG CHUẨN.** Truy vấn PHẢI đi qua `fts_match_expr()` —
`MATCH 'đồng'` viết thẳng sẽ khớp **không cái gì**, vì `remove_diacritics 2`
gập được mọi dấu tiếng Việt TRỪ `đ` (U+0111), vốn là một ký tự riêng chứ không
phải `d` + dấu. Không có dấu `đ` trong câu hỏi thì viết thẳng vẫn chạy — nhưng
đừng dựa vào đó, vì lúc nào nó hỏng thì không có gì báo.

## CSV theo từng bảng

Chế độ `primary` · 8,250 bảng, mỗi bảng hai bố cục:

- `by_table/long/` — lược đồ **cố định** cho mọi bảng (`row_path`, `value`,
  `period_end`, `unit_kind`…). Model sinh `pandas_query` chỉ phải học một lược đồ.
- `by_table/wide/` — giống báo cáo giấy. Dễ đọc, nhưng tên cột là chuỗi OCR gốc
  nên khoá không ổn định giữa các bảng.

Danh mục ở `by_table/index.json`. Chưa có bằng chứng bố cục nào cho điểm cao
hơn — không có tập train nên chỉ leaderboard trả lời được.

## Kiểm tính toàn vẹn

```bash
python examples/04_verify_package.py
```

Đối chiếu SHA-256 **đầy đủ** của mọi tệp với `manifest.json`.

## Yêu cầu môi trường

Python 3.10+, `pandas` và `pyarrow` cho Parquet. SQLite phải có FTS5 (bản đi kèm
Python trên macOS/Linux đều có).

## Trước khi dùng cho Retrieval / Embedding / Text-to-Pandas

Đọc mục **5. Vấn đề còn tồn tại** trong `SILVER_REPORT.md`. Có sáu hạng mục đã
biết và đã đo; biết trước thì thiết kế quanh được, phát hiện sau thì phải làm lại.
