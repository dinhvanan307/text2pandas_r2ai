# domain — Lớp trong cùng

**Quy tắc bất khả xâm phạm:** tầng này **không import bất cứ thứ gì** từ `application`,
`infrastructure`, hay `interface`. Không I/O, không mạng, không thư viện bên thứ ba
ngoài thư viện chuẩn.

| Thư mục | Nội dung |
|---|---|
| `entities/` | Thực thể nghiệp vụ: Document, Table, Fact, Question, Answer |
| `values/`   | Value object: VNNumber, Period, Unit, MetricCode, TableRef |
| `rules/`    | Luật nghiệp vụ thuần: đẳng thức kế toán, Mã số VAS, công thức chỉ số, phân loại lỗi |

Tham chiếu: `docs/DOMAIN_KNOWLEDGE.md`
