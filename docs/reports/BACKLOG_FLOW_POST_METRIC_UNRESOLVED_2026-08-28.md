# Tồn đọng sau implementation `METRIC_UNRESOLVED` + Flow xử lý

**Ngày:** 2026-08-28 · Tiếp nối `METRIC_UNRESOLVED_IMPLEMENTATION_REPORT_2026-08-28.md`
**Đã verify trên đĩa:** `comparison_summary.json` khớp 100% số liệu report (362 OK / 75 new-OK / 0 regression / cold 64,658s / V2 SHA không drift); alias `...` đã được regen sạch (`company_brand_attested_v1.yaml` giờ là block style); cả 2 run dir baseline/candidate đủ file.

---

## 1. Tồn đọng — xếp theo mức chặn

### Nhóm A — Chặn giá trị của chính task này (phải làm trước)

| # | Tồn đọng | Số lượng | Bản chất |
|---|---|---:|---|
| A1 | **93-case review queue `UNADJUDICATED`** — 75 new-OK chưa có bằng chứng đúng/sai | 93 | Không adjudicate thì 75 câu OK mới chỉ là coverage, chưa phải giá trị. Reviewer + blind protocol **vẫn chưa tồn tại** (gold registry: `promotion_eligible_records: 0`, access_log rỗng) — đây là nút cổ chai đã cảnh báo ở review M4, giờ thành blocker thực tế |
| A2 | Kết quả **không đổi một điểm official nào** — V3 vẫn shadow | — | 362 OK chỉ sinh điểm nếu (a) promote V3 (còn xa: cần answer accuracy ≥0,80 theo policy) hoặc (b) port thành quả sang V2. Phase 2b portability (review M7) **chưa làm** |

### Nhóm B — Phần còn lại của H198 (123 câu abstain, đã có terminal reason cụ thể)

| # | Terminal reason | Count | Ghi chú ROI |
|---|---|---:|---|
| B1 | `METRIC_SOURCE_SPECIFICITY_REQUIRED` | 47 | Cụm lớn nhất. Chưa biết bao nhiêu là "mơ hồ thật" (giữ abstain — đúng) vs "thiếu rule specificity" (recover được) |
| B2 | `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 22 (162 toàn corpus) | Bottleneck kế tiếp theo chính report §17; cần capacity review formula, không phải code |
| B3 | `BINDING_TIE` | 19 (**13 thuộc T1**) | Đáng chú ý nhất về ROI: surface mạnh, đã tới binder, chỉ thua ở tie-break. 19 câu này cách `OK` đúng một chính sách tie. Binder out-of-scope của plan cũ → cần mini-plan riêng, evidence-first |
| B4 | `METRIC_HYPOTHESES_AMBIGUOUS` 10 + `QUESTION_MENTION_NO_MAPPING` 4 | 14 | Đuôi nhỏ; chỉ sửa nếu adjudication lộ pattern chung |
| B5 | `METRIC_REJECT_ALL` 7 · `BINARY_OPERANDS` 6 · `AGGREGATE_AXIS` 3 · `LOOKUP_NON_SCALAR` 2 · lẻ 3 | 21 | Gồm Q502/Q508 (role đúng, downstream fail). Q508 còn bị chặn bởi **entity lexicon STB** (RET-001, chưa sửa — `company_alias_v1.yaml` vẫn "Sài Gòn Tài Lộc") |

### Nhóm C — Ngoài phạm vi task nhưng đang mở

| # | Tồn đọng | Ghi chú |
|---|---|---|
| C1 | Entity lexicon P0: STB "Sài Gòn Thương Tín" / EIB "Eximbank" | Chặn Q508/783/792 ở **cả V2 lẫn V3**; cần lexicon từ câu hỏi + ADR (đã đề xuất từ audit 27/08) |
| C2 | `make test-integration`: 7 fail do thiếu legacy artifacts (`submission_C1R_LOCAL.zip`, `submission_P0G2.zip`, `determinism_report_v2.json`) | Repo gate đỏ; materialize hoặc chuyển skip chính danh theo ADR-0010 |
| C3 | Doc drift: `SEMANTIC_V3_MIGRATION_STATUS.md` vẫn ghi 269 OK; thực tế 362 | Chuỗi số bất nhất V3 (207→269→271→287→362) tiếp tục dài ra nếu không sync một lần |
| C4 | V2 vẫn nộp 451 câu `answer=0.0` | Vẫn là đòn bẩy điểm số 1 toàn dự án, chưa ai đo abstain-vs-fallback |

---

## 2. Flow xử lý

```text
┌─ GĐ0 · Chốt hồ sơ adjudication (0,5 ngày) ────────────────────────────────┐
│ • Định danh reviewer (≠ người viết resolver) + blind protocol             │
│   (dùng configs/evaluation/independent_gold_protocol_v1)                  │
│ • TIỀN ĐĂNG KÝ ngưỡng precision cho new-OK trước khi nhìn kết quả:        │
│   đề xuất ≥ 0,80 trên 75 câu (Wilson CI ghi kèm)                          │
│ • Seal review_queue.jsonl bằng SHA để mọi báo cáo sau trích 1 nguồn       │
└───────────────────────────────┬───────────────────────────────────────────┘
                                ▼
┌─ GĐ1 · Adjudicate 93-case queue (1–2 ngày) ───────────────────────────────┐
│ Thứ tự: 75 new-OK → 18 T3 → boundary risks. Mỗi case: ĐÚNG / SAI /        │
│ KHÔNG ĐỦ CĂN CỨ, kèm cell nguồn.                                          │
│                                                                           │
│   precision ≥ ngưỡng ──────────► KEEP resolver · sang GĐ2 (A+B song song) │
│   precision < ngưỡng ──────────► phân tích SAI theo match-class × tier    │
│                                  → tắt class hư qua config (rollback §12) │
│                                  → re-run (≈65s) → adjudicate lại delta   │
│   LƯU Ý: sai tập trung ở tier/class nào thì chỉ tắt đúng chỗ đó,          │
│   không rollback toàn bộ.                                                 │
└───────────────────────────────┬───────────────────────────────────────────┘
                                ▼
┌─ GĐ2 · Hai nhánh SONG SONG ───────────────────────────────────────────────┐
│                                                                           │
│ Nhánh A — Khai thác 123 câu còn lại của H198 (theo ROI):                  │
│  A1. BINDING_TIE 19 (13 T1): đọc records, phân loại tie                   │
│      (same-value tie? khác bảng cùng số? khác basis?) → nếu ≥50% là       │
│      same-value/equivalent-row → mini-plan tie-break riêng cho binder     │
│      (plan mới, gate riêng — KHÔNG sửa chung với resolver)                │
│  A2. SPECIFICITY 47: adjudicate mẫu 15 câu → chia 2 rổ:                   │
│      "mơ hồ thật" (giữ abstain, đóng hồ sơ) vs "thiếu rule"               │
│      (thêm rule versioned + ≥1 QID bằng chứng + negative example)         │
│  A3. AMBIGUOUS 10 + NO_MAPPING 4: case study, chỉ sửa khi có pattern      │
│                                                                           │
│ Nhánh B — Portability sang V2 (nơi có điểm THẬT):                         │
│  B1. Chạy thử mention extractor + paraphrase rules (TNDN…) trên           │
│      40 câu "unbound operands" của V2 (abstention family đã ghi           │
│      trong ACCEPTANCE 27/08)                                              │
│  B2. Nếu ≥10/40 bind được → mở plan port sang V2 (điểm official)          │
│      Nếu <10/40 → đóng hướng này bằng số liệu, khỏi tranh luận lại        │
└───────────────────────────────┬───────────────────────────────────────────┘
                                ▼
┌─ GĐ3 · Quyết định chiến lược nộp (0,5 ngày, sau khi có precision GĐ1) ────┐
│ So sánh kỳ vọng EXEC trên cùng công thức trần-coverage:                   │
│   V3: 362 × precision_đo_được / 1012                                      │
│   V2: 561 × ~0,45 (ước lượng local 14/31) / 1012 ≈ 0,25                   │
│ • Nếu V3 ≥ V2 → cân nhắc 1 lần submit thăm dò V3 theo quota               │
│   (LƯU Ý: package-v3 cần dataframe/csv/table_cards.csv — build active     │
│   c6887… CHƯA có; phải materialize trước, đừng để crash lúc nộp)          │
│ • Nếu V3 < V2 → V2 vẫn là engine nộp; giá trị GĐ1-2 dồn vào nhánh B       │
│ • Song song: quyết định C4 (abstain=0.0 vs fallback) bằng 1 phép đo —     │
│   vẫn là đòn bẩy lớn nhất chưa ai chạm                                    │
└───────────────────────────────┬───────────────────────────────────────────┘
                                ▼
┌─ GĐ4 · Bottleneck kế tiếp + hygiene (nền, không chặn) ────────────────────┐
│ • REPORTED_DERIVED 162: review formula theo cụm operation                 │
│   (divide/growth trước — đông nhất); đây là công việc REVIEW, lập         │
│   lịch capacity, không phải sprint code                                   │
│ • C1: entity lexicon STB/EIB + ADR (mở khóa Q508/783/792 cả 2 engine)     │
│ • C2: materialize/skip 7 integration fails theo ADR-0010                  │
│ • C3: sync SEMANTIC_V3_MIGRATION_STATUS một lần với số 362 + run-id       │
└───────────────────────────────────────────────────────────────────────────┘
```

## 3. Nguyên tắc xuyên suốt flow

1. **GĐ1 là cổng của mọi thứ** — chưa có precision thì 75 new-OK chưa được tính là giá trị, và GĐ3 không có số để quyết. Đừng nhảy cóc sang B1-B5.
2. **Ngưỡng đặt trước, không đặt sau** — precision threshold, ngưỡng 10/40 của nhánh B, tiêu chí tie-break: tất cả ghi trước khi nhìn dữ liệu (đúng kỷ luật preregistration mà plan gốc đã theo).
3. **Mỗi nhánh sửa tiếp = một mini-plan riêng** với gate riêng (tie-break ≠ specificity rules ≠ formula review). Không gộp vào một "recovery v2" to.
4. **Điểm official chỉ nằm ở 2 chỗ**: nhánh B (port sang V2) và GĐ3 (submit V3 nếu thắng số). Mọi thứ khác là hạ tầng cho hai chỗ đó.
