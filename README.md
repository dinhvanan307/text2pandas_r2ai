# Text-to-Pandas — Trợ lý truy vấn Báo cáo tài chính Việt Nam

Hệ thống AI nhận **câu hỏi tiếng Việt** về báo cáo tài chính doanh nghiệp niêm yết, tự **truy hồi đúng bảng dữ liệu**, **sinh mã Pandas**, **thực thi an toàn** và trả về **con số đã kiểm chứng kèm dẫn nguồn**.

Dự án dự thi **R2AI 2026 — Text-to-Pandas** (AI Guru / Dagoras Group).

---

## Bắt đầu từ đâu

| Bạn là | Đọc theo thứ tự |
|---|---|
| **Người mới** | `docs/PROJECT_OVERVIEW.md` → `docs/COMPETITION_SPEC.md` → `docs/ARCHITECTURE.md` |
| **Dev implement module** | `docs/MODULES.md` (module của bạn) → `docs/API.md` → `docs/CODING_GUIDELINES.md` |
| **AI agent** | `CLAUDE.md` (bắt buộc đọc trước) |
| **Muốn biết "vì sao"** | `docs/TECH_DECISIONS.md` |

---

## Bản đồ tài liệu

```
docs/sources/                     # ⭐ Bản chụp thể lệ BTC — BẤT BIẾN, không sửa, không xoá
README.md                         # bạn đang ở đây
CLAUDE.md                         # hợp đồng cho AI agent
docs/
├── PROJECT_OVERVIEW.md           # bối cảnh · mục tiêu · phạm vi · thuật ngữ
├── COMPETITION_SPEC.md           # ràng buộc C01–C20 · metric · format nộp · câu hỏi mở
├── DOMAIN_KNOWLEDGE.md           # Mã số VAS · glossary · công thức chỉ số · bẫy nghiệp vụ
├── ARCHITECTURE.md               # kiến trúc 3 tầng · mô hình dữ liệu · các luồng
├── MODULES.md                    # đặc tả M01–M32 + demo D01–D05
├── API.md                        # contract Python + REST endpoint
├── EVALUATION.md                 # dẫn xuất F2 · dev set tự sinh · chống rò rỉ
├── TECH_DECISIONS.md             # ADR log — vì sao chọn, vì sao loại
├── CODING_GUIDELINES.md          # chuẩn code · bảo mật · số kiểu VN · test
├── PROMPTS.md                    # prompt & template sinh mã
├── ROADMAP.md                    # giai đoạn · phân công · rủi ro
└── archive/                      # ⛔ tài liệu đã bị thay thế — KHÔNG dùng
```

**Thứ tự ưu tiên khi mâu thuẫn:** `docs/sources/` › `docs/RULES_SOURCES.md` › `docs/` › code › `archive/`

---

## Nguyên tắc bất di bất dịch

Vi phạm bất kỳ dòng nào dưới đây ⇒ **bị loại khỏi cuộc thi**. Chi tiết: `docs/COMPETITION_SPEC.md`.

1. **Chỉ dùng model mở, ≤14B, phát hành trước 01/06/2026** (C05–C07) — không GPT/Gemini/Claude.
2. **Dữ liệu ngoài được phép, nhưng phải khai báo nguồn đầy đủ** (C04) — mọi nguồn ngoài đi qua registry: URL, revision, checksum, license, mục đích.
3. **Corpus BTC là nguồn duy nhất cho `answer`/`evidence`** — đây là quyết định chất lượng của team (ADR-024), **không phải luật BTC**.
4. **Corpus là `.txt`** (C01) — không có PDF, không cần OCR.

> ⚠️ Bản trước của mục này ghi "cấm dữ liệu ngoài" như luật tuyệt đối. Sai — xem `docs/RULES_SOURCES.md §5`.

Và một bất biến kỹ thuật: **`answer` luôn bằng kết quả thực thi thật của `pandas_query`** trên đúng CSV nằm trong ZIP nộp bài.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Chạy test offline (không cần corpus)
pytest tests/ -v

# Sinh bài nộp từ corpus + test set
python -m tools.run_submission --corpus data/corpus --test data/test.json --out submission.zip

# Chạy API demo
python -m src.api.app          # → http://localhost:8000
```

---

## Trạng thái

Giai đoạn **G0 — dựng khung** (trước 01/08/2026). Corpus chính thức chưa được cấp; mọi module phát triển trên mock corpus theo contract trong `docs/API.md`.

Mốc quan trọng: public test **01–31/08** · private test **01–03/09** (chỉ 5 lượt nộp) · kết quả **06/09**.
