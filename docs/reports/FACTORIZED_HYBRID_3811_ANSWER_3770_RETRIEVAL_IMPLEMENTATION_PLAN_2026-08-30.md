# Factorized Hybrid 3811 Answer × 3770 Retrieval — Implementation Plan

**Ngày:** 2026-08-30

**Trạng thái:** `IMPLEMENTED — READY_TO_UPLOAD_LOCAL — NOT_UPLOADED`

**Phạm vi:** chỉ compose submission từ hai ZIP đã có bằng phép thay thế theo
field; không chạy lại answer generation hoặc retrieval.

**Candidate mục tiêu:** `3811-ANSWER × 3770-RETRIEVAL`

## 1. Kết luận điều hành

Candidate tiếp theo sẽ được tạo theo phép ghép factorized, không dùng append
hoặc union:

```text
Answer layer    = giữ nguyên từ submission 3811
Retrieval layer = giữ nguyên từ submission 3770
Evidence CSV    = giữ nguyên từ submission 3811
```

Quy tắc sở hữu field trên từng QID:

| Field output | Nguồn duy nhất | Gate |
|---|---|---|
| `id` | 3811 | cùng QID set và cùng thứ tự với 3811 |
| `question` | 3811 | phải đồng thời bằng 3770 và dữ liệu câu hỏi gốc |
| `answer` | 3811 | exact equality 1.012/1.012 |
| `evidence` | 3811 | exact deep equality 1.012/1.012 |
| `pandas_query` | 3811 | exact string equality 1.012/1.012 |
| `relevant_tables` | 3770 | exact list/order equality 1.012/1.012 |
| `relevant_docs` | 3770 | exact list/order equality 1.012/1.012 |
| `data/*.csv` | 3811 | chỉ copy CSV được evidence 3811 tham chiếu, byte-identical |

Không có field nào được merge, append, rerank, normalize hoặc regenerate.
Nếu bất kỳ gate exact-equality nào không đạt, candidate bị chặn và không được
đưa vào `artifacts/submissions/`.

## 2. Cơ sở lựa chọn

### 2.1 Official evidence do người dùng cung cấp

| Submission | Answer/Execution | Tables F2 | Tables Recall | Docs F2 | Vai trò |
|---:|---:|---:|---:|---:|---|
| 3811 | **0,2826** | 0,2522 | 0,2495 | 0,6373 | Answer owner |
| 3770 | 0,2589 | **0,3000** | **0,3435** | **0,7086** | Retrieval owner |

Đây là hai kết quả official độc lập tốt nhất hiện có cho hai layer. Candidate
factorized nhằm kiểm tra giả thuyết scorer tách Answer và Retrieval đủ độc lập
để giữ Answer của 3811 và phục hồi retrieval của 3770.

Số điểm dự kiến chỉ là giả thuyết:

```text
Answer/Execution: kỳ vọng gần 0,2826
Tables F2:        kỳ vọng gần 0,3000
Docs F2:          kỳ vọng gần 0,7086
```

Không được ghi các giá trị này là kết quả của candidate trước khi có leaderboard
receipt gắn với đúng SHA-256 của ZIP.

### 2.2 Hai input đã được xác minh local

| Thuộc tính | Submission 3811 | Submission 3770 |
|---|---|---|
| ZIP | `artifacts/submissions/submission_baseline-union-retrieval-overlay-20260830-01.zip` | `artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip` |
| ZIP SHA-256 | `535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933` | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| `submission.json` SHA-256 | `9402898d7329efeeb218e7814e2bb38840860b0799ba1da876a7c8205b6ff153` | `9f2c45e54ccd1309a31caaef91f1305c45183400a5dde7b7eee6bd5ab919c38f` |
| Records | 1.012 | 1.012 |
| Emitted answer | 625 | 564 |
| CSV members | 1.070 | 869 |
| Max tables/QID | 18 | **10** |
| Duplicate table list | — | 0 QID |
| Docs không suy ra đúng từ tables | — | 0 QID |

Cross-input audit hiện tại:

| Gate | Kết quả |
|---|---:|
| QID set giống nhau | 1.012/1.012 |
| Question giống nhau | 1.012/1.012 |
| Exact table order hiện đã giống nhau | 836/1.012 |
| Exact docs order hiện đã giống nhau | 861/1.012 |
| QID sẽ đổi ít nhất một retrieval field | **176** |

Phép transplant vì vậy có phạm vi rõ ràng: không đụng Answer layer, chỉ thay
retrieval fields trên 176 QID chưa giống retrieval winner.

## 3. Non-goals bắt buộc

- Không chạy lại answer generation.
- Không bật P0 Metric Resolver/Selector.
- Không dùng hoặc resume `MODEL_GOLD`.
- Không chạy lại retrieval và không thay profile 3770.
- Không append refs của 3811 vào refs của 3770.
- Không giữ các baseline retrieval refs dư thừa.
- Không sửa câu trả lời, query hoặc evidence của 3811, kể cả khi audit thủ công
  cho rằng một câu có thể cải thiện.
- Không đổi embedding, reranker, parser, ontology, binder hoặc executor.
- Không tự upload; upload là external action riêng sau khi user duyệt ZIP và
  exact SHA-256.

P0 tiếp tục `OFF`; MODEL_GOLD tiếp tục `FROZEN`.

## 4. Thiết kế implementation nhỏ nhất

### 4.1 File cần thêm

```text
tools/submission/build_factorized_hybrid.py
tests/unit/test_factorized_hybrid.py
```

Không sửa `tools/submission/build_baseline_union_overlay.py`; công cụ đó thuộc
lineage của submission 3811 và phải được giữ làm đối chứng.

### 4.2 Contract của composer

CLI dự kiến:

```bash
.venv/bin/python tools/submission/build_factorized_hybrid.py \
  --answer-zip artifacts/submissions/submission_baseline-union-retrieval-overlay-20260830-01.zip \
  --retrieval-zip artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip \
  --corpus-root data/raw/btc/financial_statements \
  --output artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a/submission.zip \
  --report artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a/composition_report.json \
  --expect-answer-sha256 535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933 \
  --expect-retrieval-sha256 15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169
```

Lệnh trên chỉ là interface phải implement; tại thời điểm viết plan, tool và
candidate chưa tồn tại.

`configs/datasets/active_snapshot.yaml` đặt raw snapshot tại `data/raw/btc`,
nhưng submission validator nhận thư mục chứa trực tiếp các ticker. Vì vậy
`--corpus-root` phải trỏ tới subdirectory canonical
`data/raw/btc/financial_statements`.

Composer phải:

1. kiểm SHA-256 của cả hai input trước khi đọc;
2. yêu cầu đúng một `submission.json` ở root mỗi ZIP;
3. parse thành ordered record list và index theo `id`;
4. reject duplicate ID, thiếu ID, thừa ID hoặc record không phải object;
5. yêu cầu đúng 1.012 QID và hai QID set giống nhau;
6. yêu cầu `question` giống nhau trên 1.012/1.012;
7. tạo mỗi output record theo ownership table ở mục 1;
8. copy đúng các CSV được `evidence` output tham chiếu từ ZIP 3811;
9. reject CSV thiếu hoặc member cùng tên nhưng payload không truy xuất được;
10. serialize deterministic và không overwrite output đã tồn tại;
11. tự chạy layer diff, strict validation và clean replay;
12. exit code khác 0 nếu bất kỳ hard gate nào fail.

### 4.3 Deterministic ZIP contract

- Giữ record order đúng như 3811.
- Field order cố định:
  `id`, `question`, `answer`, `relevant_docs`, `relevant_tables`, `evidence`,
  `pandas_query`.
- JSON dùng `ensure_ascii=False`, `indent=1`, không chứa metadata runtime.
- CSV members sort theo archive path.
- ZIP timestamp cố định `1980-01-01 00:00:00`.
- Compression `ZIP_DEFLATED`, level 6.
- Unix mode cố định `0644`.
- Không ghi absolute path, mtime, hostname, git status hoặc run timestamp vào
  payload ZIP.

## 5. Flow triển khai và gate theo phase

### Phase 0 — Seal input authority

Thực hiện:

1. chạy `git status --short`;
2. xác nhận hai ZIP input tồn tại;
3. tính lại ZIP SHA-256 và `submission.json` SHA-256;
4. lưu immutable input manifest trong report của run;
5. xác nhận P0 `OFF`, MODEL_GOLD không được đọc và không có model process được
   khởi chạy.

Gate PASS:

```text
answer ZIP SHA = 535ee597...f79933
retrieval ZIP SHA = 15c1854d...8e169
records = 1012 / 1012
same QID set = 1012 / 1012
same questions = 1012 / 1012
```

Fail-closed nếu một digest hoặc identity lệch.

### Phase 1 — Implement composer core

Implement các pure operations:

```text
read_bundle
verify_input_digest
validate_record_identity
compose_record
collect_required_csvs
copy_answer_csv_payloads
write_deterministic_zip
```

`compose_record` không nhận strategy flag; mapping field phải cố định để tránh
vô tình biến tool thành một kiến trúc merge thứ ba.

Gate PASS:

- không import answer engine, retrieval engine, P0 hoặc model adapter;
- không gọi network;
- không mutate input ZIP;
- output schema chỉ có đúng bảy field submission.

Commit khi PASS:

```text
feat(submission): compose factorized answer retrieval candidate
```

### Phase 2 — Unit tests fail-closed

Test tối thiểu:

1. answer/query/evidence lấy chính xác từ answer ZIP;
2. tables/docs và thứ tự lấy chính xác từ retrieval ZIP;
3. output question lấy từ answer ZIP nhưng reject nếu hai source lệch;
4. reject SHA mismatch;
5. reject QID set mismatch;
6. reject duplicate QID;
7. reject missing evidence CSV;
8. reject extra submission field;
9. reject retrieval record có hơn 10 tables;
10. reject duplicate table/doc refs;
11. reject `relevant_docs` không suy ra đúng từ `relevant_tables`;
12. hai fixture builds sinh ZIP byte-identical;
13. output đã tồn tại thì reject, không overwrite.

Gate:

```bash
.venv/bin/python -m pytest -q tests/unit/test_factorized_hybrid.py
.venv/bin/python -m ruff check tools/submission/build_factorized_hybrid.py \
  tests/unit/test_factorized_hybrid.py
git diff --check
```

Commit khi PASS:

```text
test(submission): lock factorized hybrid ownership gates
```

### Phase 3 — Build A và layer differential

Output A:

```text
artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a/
├── submission.zip
└── composition_report.json
```

Hard gates trên đủ 1.012 QID:

| Gate | Điều kiện PASS |
|---|---:|
| ID order vs 3811 | 1.012/1.012 exact |
| Question vs 3811 | 1.012/1.012 exact |
| Answer vs 3811 | 1.012/1.012 exact |
| Query vs 3811 | 1.012/1.012 exact |
| Evidence vs 3811 | 1.012/1.012 exact |
| Tables vs 3770 | 1.012/1.012 exact list/order |
| Docs vs 3770 | 1.012/1.012 exact list/order |
| Emitted answers | 625 |
| Required evidence CSV present | 1.070/1.070 |
| Evidence CSV bytes vs 3811 | 1.070/1.070 exact SHA |
| Duplicate IDs/tables/docs | 0/0/0 |
| Max tables/QID | <= 10 |
| QID retrieval fields changed vs 3811 | 176 |

Không được chỉ so set; Tables và Docs phải deep-equal theo đúng thứ tự vì ranking
metric có thể phụ thuộc order.

### Phase 4 — Strict package validation

Chạy validator production trên chính ZIP output, với questions và corpus active:

```text
records: 1012
unique IDs: 1012
validator errors: 0
validator warnings: 0
one root JSON: PASS
missing evidence CSV: 0
orphan CSV: 0
unsafe members: 0
invalid table/doc locators: 0
```

Đây là gate cấu trúc và grounding; không được gọi là Answer Accuracy.

### Phase 5 — Clean replay

Chạy lại mọi query từ CSV nằm trong chính candidate ZIP:

```text
executed: 625
matched: 625
no evidence: 387
replay errors: 0
```

Nếu `executed != 625`, `matched != executed` hoặc có bất kỳ replay error nào,
candidate bị `BLOCKED`. Replay PASS chỉ chứng minh answer khớp query/evidence,
không chứng minh answer đúng với câu hỏi.

### Phase 6 — Build B và byte determinism

Build lại từ hai ZIP nguồn vào run ID khác:

```text
artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-b/
├── submission.zip
└── composition_report.json
```

So sánh:

```text
submission.json A == B: byte-identical
all CSV A == B:         byte-identical
ZIP A SHA == ZIP B SHA: PASS
```

Không copy ZIP A sang path B. Hai lần phải chạy composer độc lập.

### Phase 7 — Repository gates

Sau khi candidate gates đã xanh:

```bash
make snapshots-verify
make ci
make test-integration
git diff --check
```

Phải inspect nội dung report và archive, không chỉ dựa vào exit code. Nếu test
fail vì lỗi ngoài phạm vi, ghi rõ exact failure và giữ candidate ở trạng thái
`BLOCKED`; không hạ validator hoặc skip test.

### Phase 8 — Seal release artifact

Chỉ khi Phase 0–7 đều PASS, copy đúng ZIP A sang tên publish bất biến:

```text
artifacts/submissions/submission_factorized-hybrid-3811-answer-3770-retrieval-20260830-01.zip
```

Sau copy phải tính lại SHA-256 và yêu cầu bằng ZIP A. Không overwrite nếu path
đã tồn tại.

Tạo tracked provenance:

```text
provenance/submissions/factorized_hybrid_3811_answer_3770_retrieval_20260830.json
```

Provenance tối thiểu:

- candidate ID và trạng thái;
- input paths, ZIP SHA-256 và `submission.json` SHA-256;
- source official submission IDs 3811/3770;
- field ownership mapping;
- output ZIP path, ZIP SHA-256 và `submission.json` SHA-256;
- 1.012 field-equality counts;
- validation/replay/determinism results;
- P0 `false`, MODEL_GOLD `false`;
- source commit và commits của composer/tests/report;
- upload status `NOT_UPLOADED`.

Tạo implementation report sau khi chạy:

```text
docs/reports/FACTORIZED_HYBRID_3811_ANSWER_3770_RETRIEVAL_REPORT_2026-08-30.md
```

Commit khi toàn bộ release gate PASS:

```text
docs(submission): seal factorized hybrid candidate
```

## 6. Release gate tổng hợp

Candidate chỉ được gắn `READY_TO_UPLOAD` khi đồng thời đạt:

```text
[ ] input SHA-256 đúng hai sealed ZIP
[ ] 1.012/1.012 records và unique IDs
[ ] question giống nhau giữa hai source: 1.012/1.012
[ ] answer/query/evidence giống 3811: 1.012/1.012
[ ] relevant_tables/docs giống 3770: 1.012/1.012
[ ] evidence CSV bytes giống 3811: 1.070/1.070
[ ] emitted answers: 625
[ ] max tables: 10
[ ] strict validation: 0 error, 0 warning
[ ] clean replay: 625/625, 0 error
[ ] archive: 1 root JSON, 0 missing CSV, 0 orphan CSV
[ ] build A/B ZIP byte-identical
[ ] snapshots-verify PASS
[ ] make ci PASS
[ ] make test-integration PASS
[ ] git diff --check PASS
[ ] provenance và final report ghi đúng output SHA-256
```

Bất kỳ checkbox nào chưa đạt thì trạng thái là `BLOCKED`, không phải
`READY_WITH_WARNING`.

## 7. Blocker và quyết định fail-closed

| Blocker | Hành động |
|---|---|
| Input digest lệch | dừng; không dùng ZIP mới dưới cùng tên |
| Hai source lệch QID/question | dừng; không tự align bằng index hoặc text fuzzy |
| Retrieval 3770 có >10 tables hoặc duplicate | dừng; không truncate hoặc deduplicate |
| Evidence CSV của 3811 thiếu | dừng; không lấy CSV cùng tên từ 3770 |
| Answer/query/evidence khác 3811 dù chỉ một QID | dừng; xuất diff QID |
| Tables/docs khác 3770 dù chỉ một QID | dừng; xuất diff QID |
| Strict validator warning | coi như fail cùng error |
| Replay mismatch | dừng; không sửa answer/query tự động |
| A/B ZIP khác bytes | dừng; audit ordering, timestamp và serialization |
| Repo gate fail | không publish cho đến khi phân loại và xử lý blocker |

Không có fallback sang overlay, P0 hoặc MODEL_GOLD trong cùng run.

## 8. Upload và official measurement

Upload không nằm trong implementation tự động. Sau khi user duyệt candidate:

1. báo exact final path và SHA-256;
2. upload đúng file đó, không zip lại qua Finder hoặc công cụ khác;
3. lưu submission ID/timestamp/score receipt;
4. bind receipt vào exact ZIP SHA-256 trong provenance;
5. so official metrics với cả 3811 và 3770.

Bảng hậu kiểm:

| Metric | 3811 | 3770 | Factorized | Kết luận |
|---|---:|---:|---:|---|
| Answer Accuracy | 0,2826 | 0,2589 | `NOT_MEASURED` | giữ/mất answer layer |
| Execution Accuracy | 0,2826 | 0,2589 | `NOT_MEASURED` | giữ/mất execution layer |
| Tables F2 | 0,2522 | 0,3000 | `NOT_MEASURED` | retrieval transplant |
| Tables Recall | 0,2495 | 0,3435 | `NOT_MEASURED` | retrieval transplant |
| Docs F2 | 0,6373 | 0,7086 | `NOT_MEASURED` | retrieval transplant |

Promotion rule:

```text
Nếu Answer/Execution >= 0,2826 và retrieval cải thiện rõ so với 3811
→ promote factorized candidate.

Nếu Answer giảm hoặc retrieval không tăng
→ giữ 3811 làm rollback winner; không suy diễn scorer độc lập.
```

## 9. Artifact cuối kỳ vọng

Khi execution hoàn tất và mọi gate PASS, phải có:

```text
artifacts/submissions/
└── submission_factorized-hybrid-3811-answer-3770-retrieval-20260830-01.zip

artifacts/runs/submission/
├── factorized-hybrid-3811x3770-20260830-a/
│   ├── submission.zip
│   └── composition_report.json
└── factorized-hybrid-3811x3770-20260830-b/
    ├── submission.zip
    └── composition_report.json

provenance/submissions/
└── factorized_hybrid_3811_answer_3770_retrieval_20260830.json

docs/reports/
├── FACTORIZED_HYBRID_3811_ANSWER_3770_RETRIEVAL_IMPLEMENTATION_PLAN_2026-08-30.md
└── FACTORIZED_HYBRID_3811_ANSWER_3770_RETRIEVAL_REPORT_2026-08-30.md
```

## 10. Tài liệu liên quan

- [Baseline Union + Retrieval Overlay release report](./BASELINE_UNION_RETRIEVAL_OVERLAY_RELEASE_REPORT_2026-08-30.md)
- [Official retrieval winner report](./ACTUAL_TABLE_RETRIEVAL_RECOVERY_2026-08-29.md)
- [P0 Metric Resolver/Selector implementation report](./P0_METRIC_RESOLVER_SELECTOR_IMPLEMENTATION_REPORT_2026-08-29.md)

## 11. Trạng thái sau implementation

```text
PLAN:          COMPLETE
IMPLEMENTATION: COMPLETE
CANDIDATE ZIP: BUILT
VALIDATION:    PASS — 1012 records, 0 error, 0 warning
REPLAY:        PASS — 625/625
DETERMINISM:   PASS — A2/B byte-identical
UPLOAD:        NOT_PERFORMED
OFFICIAL SCORE: NOT_MEASURED
```

Kết quả triển khai và exact artifact SHA được ghi tại
[implementation report](./FACTORIZED_HYBRID_3811_ANSWER_3770_RETRIEVAL_REPORT_2026-08-30.md).
Các gate local không phải bằng chứng candidate đã tăng điểm; official score chỉ
được xác nhận sau khi leaderboard receipt được bind với đúng ZIP SHA-256.
