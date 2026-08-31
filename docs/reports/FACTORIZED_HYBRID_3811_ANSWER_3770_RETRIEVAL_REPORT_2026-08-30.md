# Factorized Hybrid 3811 Answer × 3770 Retrieval — Implementation Report

**Ngày:** 2026-08-30

**Trạng thái:** `READY_TO_UPLOAD_LOCAL_NOT_UPLOADED`

**P0:** `OFF`

**MODEL_GOLD:** `FROZEN — NOT_USED — NOT_RESUMED`

## 1. Kết luận

Đã triển khai đúng candidate factorized, không dùng append:

```text
Answer/Query/Evidence = submission 3811
Tables/Docs           = submission 3770
Evidence CSV          = submission 3811
```

Candidate nộp bài:

`artifacts/submissions/submission_factorized-hybrid-3811-answer-3770-retrieval-20260830-01.zip`

SHA-256:

`4734e67507da46638c6587a6bdecb1187825667da3effd000631b96e03e2fe7f`

Toàn bộ release gate đã PASS:

| Gate | Kết quả |
|---|---:|
| Records/unique IDs | 1.012/1.012 |
| Answer/Query/Evidence giống 3811 | 1.012/1.012 |
| Tables/Docs giống 3770 | 1.012/1.012 |
| Evidence CSV bytes giống 3811 | 1.070/1.070 |
| Emitted answers | 625 |
| Max tables/QID | 10 |
| Strict validation | PASS — 0 error, 0 warning |
| Clean replay | PASS — 625/625, 0 error |
| Two-run ZIP determinism | PASS — byte-identical |
| Repository gates | PASS |

Không có thao tác upload nào được thực hiện. Official score của candidate vẫn
là `NOT_MEASURED` cho đến khi leaderboard receipt được gắn với đúng ZIP SHA.

## 2. Input authority

### Answer owner — submission 3811

| Thuộc tính | Giá trị |
|---|---|
| Path | `artifacts/submissions/submission_baseline-union-retrieval-overlay-20260830-01.zip` |
| ZIP SHA-256 | `535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933` |
| `submission.json` SHA-256 | `9402898d7329efeeb218e7814e2bb38840860b0799ba1da876a7c8205b6ff153` |
| Records | 1.012 |
| Emitted | 625 |
| Evidence CSV | 1.070 |
| Official Answer/Execution | 0,2826 — user-reported |

### Retrieval owner — submission 3770

| Thuộc tính | Giá trị |
|---|---|
| Path | `artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip` |
| ZIP SHA-256 | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| `submission.json` SHA-256 | `9f2c45e54ccd1309a31caaef91f1305c45183400a5dde7b7eee6bd5ab919c38f` |
| Records | 1.012 |
| Max tables/QID | 10 |
| Retrieval profile | `score_margin=0,50`, `primary_boost=0,60` |
| Official Tables F2/Recall | 0,3000 / 0,3435 — user-reported |
| Official Docs F2 | 0,7086 — user-reported |

Hai source có cùng QID set và exact question trên 1.012/1.012 records.

## 3. Implementation

Đã thêm:

- `tools/submission/build_factorized_hybrid.py`;
- `tests/unit/test_factorized_hybrid.py`.

Các commit:

| Phase | Commit |
|---|---|
| Composer | `9b1e593188610cbdfa0095ebf2839e374d542bf9` |
| Fail-closed tests | `c80ae72201c65ed482026ba0588fa0e4777508d5` |
| Correct canonical validator root | `deb2ac1f48da86e1fefe232c30b8d1b533a5f3c1` |

Composer thực hiện đúng một strategy cố định. Nó không import hoặc gọi answer
engine, retrieval engine, P0, model adapter hay network. Output đã tồn tại sẽ bị
reject thay vì overwrite.

Field ownership:

| Field | Nguồn |
|---|---|
| `id` | 3811 |
| `question` | 3811, đồng thời assert bằng 3770 |
| `answer` | 3811 |
| `evidence` | 3811 |
| `pandas_query` | 3811 |
| `relevant_tables` | 3770, giữ exact order |
| `relevant_docs` | 3770, giữ exact order |
| `data/*.csv` | 3811, byte-identical |

## 4. Blocker đã phát hiện và xử lý

Lần chạy đầu tiên được giữ tại:

`artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a/`

Candidate bytes và replay đúng, nhưng validator trả 1.377 document errors vì
CLI example ban đầu dùng:

`--corpus-root data/raw/btc`

Trong khi validator nhận thư mục chứa trực tiếp ticker, canonical path thực là:

`data/raw/btc/financial_statements`

Bằng chứng source file:

```text
data/raw/btc/financial_statements/VJC/2018/
└── VJC_financial_statements_2018_separate/
    └── VJC_financial_statements_2018_separate_extracted.txt
```

Không hạ validator, không xóa hoặc overwrite failed run. Plan được sửa ở commit
`deb2ac1`; build hợp lệ dùng run ID mới `a2`.

| Failed-run metric | Kết quả |
|---|---:|
| Layer diff | PASS |
| Replay | 625/625 |
| Validation | BLOCKED — 1.377 path-resolution errors |
| Disposition | preserved, không dùng làm release run |

Đây là caller path mismatch, không phải thay đổi candidate content. ZIP của
failed run có cùng SHA với A2/B, nhưng chỉ A2/B được công nhận là passing runs
do chạy đúng validation contract.

## 5. Full-corpus layer differential

Passing run A2:

`artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a2/`

| Gate | Kết quả |
|---|---:|
| Records | 1.012 |
| ID order giống 3811 | 1.012/1.012 |
| Question giống 3811 | 1.012/1.012 |
| Answer giống 3811 | 1.012/1.012 |
| Evidence giống 3811 | 1.012/1.012 |
| Pandas query giống 3811 | 1.012/1.012 |
| Relevant tables giống 3770 | 1.012/1.012 |
| Relevant docs giống 3770 | 1.012/1.012 |
| Retrieval fields thay đổi so với 3811 | 176 QID |
| Emitted | 625 |
| Max tables | 10 |
| Duplicate IDs | 0 |
| QID có duplicate tables/docs | 0/0 |

Phép so sánh Tables/Docs là exact deep equality có order, không phải set
equality. Candidate không giữ baseline refs dư thừa và không append ref nào.

## 6. Evidence và archive audit

| Gate | Kết quả |
|---|---:|
| Evidence CSV required | 1.070 |
| CSV copied từ 3811 | 1.070 |
| CSV byte identity | 1.070/1.070 |
| ZIP members | 1.071 |
| Root `submission.json` | 1 |
| CSV members | 1.070 |
| Missing CSV | 0 |
| Orphan CSV | 0 |
| `unzip -t` | PASS |

`submission.json` SHA-256 của candidate:

`a01d33718d5c1158c93d7258b854c5dc2eac6a95fcf0d05fb2074bb2e324bb28`

## 7. Strict validation và clean replay

Validation được chạy với corpus root canonical
`data/raw/btc/financial_statements`:

```text
records:  1012
errors:   0
warnings: 0
status:   PASS
```

Clean replay trực tiếp từ evidence CSV trong ZIP:

```text
total:       1012
executed:     625
matched:      625
no_evidence:  387
error:          0
```

Replay PASS chỉ chứng minh `answer == eval(pandas_query)` trên evidence đã đóng
gói. Nó không phải phép đo Answer Accuracy.

## 8. Two-build determinism

Hai composer runs độc lập:

| Run | Path | ZIP SHA-256 |
|---|---|---|
| A2 | `artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-a2/submission.zip` | `4734e67507da46638c6587a6bdecb1187825667da3effd000631b96e03e2fe7f` |
| B | `artifacts/runs/submission/factorized-hybrid-3811x3770-20260830-b/submission.zip` | `4734e67507da46638c6587a6bdecb1187825667da3effd000631b96e03e2fe7f` |

Kết quả:

```text
ZIP bytes:             identical
member order:          identical — 1.071/1.071
submission.json bytes: identical
CSV bytes:             identical — 1.070/1.070
```

## 9. Repository gates

| Gate | Kết quả |
|---|---|
| Factorized unit tests | PASS — 13/13 |
| Ruff targeted | PASS |
| `make snapshots-verify` | PASS |
| `make ci` | PASS — typecheck 92 files; 0 broken links; 2.217 passed, 42 skipped, 30 deselected |
| `make test-integration` | PASS — 23 passed |
| `git diff --check` | PASS |

Active lineage được xác minh:

```text
raw snapshot:    ca033190f2e9e99f
A6 build:        c6887fb633374fad
retrieval index: 872ccb0dda9a2bb6
```

## 10. Final release artifact

Passing ZIP A2 được copy byte-identical sang immutable submission path:

`artifacts/submissions/submission_factorized-hybrid-3811-answer-3770-retrieval-20260830-01.zip`

Final audit:

| Thuộc tính | Giá trị |
|---|---|
| ZIP SHA-256 | `4734e67507da46638c6587a6bdecb1187825667da3effd000631b96e03e2fe7f` |
| `submission.json` SHA-256 | `a01d33718d5c1158c93d7258b854c5dc2eac6a95fcf0d05fb2074bb2e324bb28` |
| Records | 1.012 |
| Emitted | 625 |
| Max tables | 10 |
| Strict validation | PASS — 0/0 |
| Replay | PASS — 625/625 |
| ZIP integrity | PASS |

Provenance:

`provenance/submissions/factorized_hybrid_3811_answer_3770_retrieval_20260830.json`

## 11. Official-score boundary

Candidate giữ chính xác các layer đã được leaderboard chứng minh riêng:

| Metric | 3811 Answer owner | 3770 Retrieval owner | Factorized |
|---|---:|---:|---:|
| Answer Accuracy | 0,2826 | 0,2589 | `NOT_MEASURED` |
| Execution Accuracy | 0,2826 | 0,2589 | `NOT_MEASURED` |
| Tables F2 | 0,2522 | 0,3000 | `NOT_MEASURED` |
| Tables Recall | 0,2495 | 0,3435 | `NOT_MEASURED` |
| Docs F2 | 0,6373 | 0,7086 | `NOT_MEASURED` |

Giả thuyết là giữ Answer/Execution gần 0,2826 và phục hồi retrieval gần mức
3770. Đây không phải cam kết điểm: chỉ leaderboard mới đo được coupling thực tế
giữa các field/layer.

## 12. Release decision

```text
COMPOSER:       PASS
FIELD GATES:    PASS
VALIDATION:     PASS
REPLAY:         PASS
DETERMINISM:    PASS
REPOSITORY:     PASS
P0:             OFF
MODEL_GOLD:     FROZEN / NOT USED
CANDIDATE:      READY_TO_UPLOAD_LOCAL
UPLOAD:         NOT_PERFORMED
OFFICIAL SCORE: NOT_MEASURED
```

Nếu nộp, phải upload đúng file ở mục 10 và đối chiếu SHA-256 trước upload. Không
zip lại candidate qua Finder hoặc thay đổi member order. Sau khi leaderboard trả
kết quả, receipt phải được bind vào exact SHA-256
`4734e67507da46638c6587a6bdecb1187825667da3effd000631b96e03e2fe7f`.
