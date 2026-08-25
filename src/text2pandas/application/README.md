# application — Use case

Điều phối luồng nghiệp vụ. Phụ thuộc `domain`; **không** phụ thuộc `infrastructure`
— mọi truy cập ra ngoài đi qua `ports/`.

| Thư mục | Nội dung |
|---|---|
| `ports/`    | Ba cổng trừu tượng: LLMPort, StoragePort, SearchPort |
| `usecases/` | Mỗi use case ánh xạ 1-1 với nhóm module trong `docs/MODULES.md` |

Ánh xạ use case ↔ module: `build_catalog` (M01–M03) · `parse_tables` (M04–M08) ·
`build_fact_store` (M09–M12) · `build_index` (M13–M14) · `answer_question` (M15–M29) ·
`build_submission` (M30–M31)
