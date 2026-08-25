# text2pandas — gói MÃ NGUỒN

**Commit:** `fbd36c8` · **ngày commit:** 2026-08-17
**Đóng gói bằng:** `scripts/dong_goi_source.sh` → `tools/package_release.py` (tất định)

## Gói này CÓ

`src/` `tools/` `tests/` `configs/` `evaluation/` `identity/` `ops/` `scripts/`
+ `Makefile` `pyproject.toml` `requirements.lock` `README.md` `CLAUDE.md` `HANDOFF.md`

## Gói này KHÔNG có, và vì sao

| Bị loại | Dung lượng | Lý do |
|---|---|---|
| `artifacts/` | 64 G | artifact dẫn xuất (`work.db` 4,2 G, `rc2/` 60 G) |
| `data/silver/` | 7,3 G | Silver SSOT — dựng lại bằng `make dp-build` |
| `data/external/` | 379 M | corpus ViFinQA — tải lại bằng `tools/data_acquisition/` |
| `data/submissions/` | 20 M | bài nộp ZIP |
| `silver_release.zip` | 1,5 G | gói phát hành |
| `reports/` | 75 M | số liệu đo |
| `docs/` | 5,8 M | 168 tài liệu (loại theo yêu cầu) |
| `to_read/`, `_TO_DELETE/`, `dist/`, `sync_122_*` | — | tạm / bản sao |
| `.venv-build/`, `.venv-review/` | 529 M | môi trường ảo |
| `.git/` | 11 M | lịch sử |

## Chạy

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
python3 -m pytest tests/ -q --continue-on-collection-errors
```

⚠️ **Đã biết:** không có `conftest.py` ⇒ `pytest tests/` (không cờ) dừng ở
3 lỗi collect (`test_a5_row_path_period`, `test_a5_scale_applicability`,
`test_a6_manifest_identity` — `ModuleNotFoundError: data_pipeline`). Cài
`pip install -e .` trước, hoặc dùng `--continue-on-collection-errors`.
Xem `docs/179_TECHNICAL_ARCHITECTURE_AUDIT.md` §P0-2.

Phần lớn `tools/` cần `artifacts/retrieval/work.db` và `data/silver/`; không
có hai thứ đó thì chỉ đọc và chạy test đơn vị được.
