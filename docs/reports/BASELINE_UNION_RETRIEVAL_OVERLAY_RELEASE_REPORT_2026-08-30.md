# Baseline Union + Retrieval Overlay — Release Report

**Ngày:** 2026-08-30

**Trạng thái:** `FINAL_READY_LOCAL_NOT_UPLOADED`

**Candidate được chọn:** `FINAL`

**P0:** OFF

**MODEL_GOLD:** không sử dụng, không resume

## 1. Kết luận

Đã tạo đủ ba ZIP bất biến theo chiến lược được duyệt:

1. `SAFE`: baseline official `0.2787` giữ nguyên;
2. `UNION`: SAFE + 21 answer Canonical-only đã clean replay;
3. `FINAL`: UNION + retrieval overlay từ official retrieval winner.

Candidate đề xuất nộp là:

`artifacts/submissions/submission_baseline-union-retrieval-overlay-20260830-01.zip`

SHA-256:

`535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933`

Release gate đạt toàn bộ:

| Gate | Kết quả |
|---|---:|
| Records/unique IDs | 1.012 / 1.012 |
| Strict validation | PASS — 0 error, 0 warning |
| Clean replay | PASS — 625/625 |
| Baseline answer unchanged | 604/604 |
| Baseline query unchanged | 604/604 |
| Baseline evidence unchanged | 604/604 |
| Baseline table list preserved as prefix | 1.012/1.012 |
| Build A/B ZIP byte-identical | PASS |
| P0 answer patch | không áp dụng |

Không có thao tác upload nào được thực hiện. Official Answer/Execution/Tables/Docs
metrics của FINAL vẫn là `NOT_MEASURED` cho đến khi leaderboard chấm.

## 2. Ba artifact nộp bài

| Candidate | Path | SHA-256 | Emitted |
|---|---|---|---:|
| SAFE | `artifacts/submissions/submission_p0_baseline_02787_20260829.zip` | `179d2c10425c96d55304183e27c5326b5bd2072d8d02fe74e211d23df3a060ad` | 604 |
| UNION | `artifacts/submissions/submission_baseline-union-20260830-01.zip` | `97429bc3a3070c286b474ef36b4d9dc756e5a64013d0c1efb4654d7931b70b68` | 625 |
| **FINAL** | `artifacts/submissions/submission_baseline-union-retrieval-overlay-20260830-01.zip` | `535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933` | **625** |

`submission.json` SHA-256:

- UNION: `633178c201af38126bb271abf19b60115a488be5367e1e67f11e1e062fa0ffab`;
- FINAL: `9402898d7329efeeb218e7814e2bb38840860b0799ba1da876a7c8205b6ff153`.

## 3. Input identities

### SAFE baseline

| Thuộc tính | Giá trị |
|---|---|
| Official score | `0.2787` — user-reported |
| ZIP SHA-256 | `179d2c10425c96d55304183e27c5326b5bd2072d8d02fe74e211d23df3a060ad` |
| Records | 1.012 |
| Emitted | 604 |
| Strict validation / replay | PASS / 604/604 |

### Current Canonical source

| Thuộc tính | Giá trị |
|---|---|
| Records | `artifacts/runs/answer/p0-shadow-full-1012-20260829-01/records.jsonl` |
| SHA-256 | `4179da8814bcac1c03a4ab7a1755a55cadbe8a78c01082591d69717ebf91907e` |
| Source commit | `097ab24ab6545d586e0b00bb7256879ceeaaab79` |
| Emitted | 585 |
| Metric mode | shadow, nhưng selected output vẫn là legacy |

P0 trace không được lấy làm answer source.

### Retrieval winner

| Thuộc tính | Giá trị |
|---|---|
| ZIP | `artifacts/submissions/submission_actual-table-retrieval-safe-3966500-20260829-01.zip` |
| SHA-256 | `15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169` |
| Source commit | `39665000ceee411ad87c858f1839c8d2344903df` |
| `score_margin` | 0,50 |
| `primary_boost` | 0,60 |
| Normal cap | 10 tables |

Đây là artifact đã tăng official Tables F2 `0.2500 → 0.3000`, Tables Recall
`0.2461 → 0.3435`, Docs F2 `0.6326 → 0.7086` mà không giảm Answer/Execution
trong submission 3770. FINAL chỉ tái sử dụng table/document references của
artifact này; không lấy answer hoặc evidence của nó.

## 4. UNION — bổ sung 21 answer không đụng baseline

Logic thực thi:

```text
baseline emitted
→ giữ nguyên toàn bộ answer/query/evidence

baseline abstain + current Canonical emitted
→ clean replay source record
→ PASS thì lấy answer/query/evidence
→ FAIL thì giữ baseline abstain
```

Kết quả:

| Chỉ tiêu | Số lượng |
|---|---:|
| Baseline emitted | 604 |
| Current Canonical emitted | 585 |
| Canonical-only eligible | 21 |
| Source replay PASS | 21/21 |
| Source replay rejected | 0 |
| UNION emitted | **625** |
| Delta coverage | **+21** |

QID được bổ sung:

```text
8, 11, 50, 112, 181, 214, 250, 358, 589, 599, 612,
624, 625, 630, 639, 649, 770, 786, 830, 889, 909
```

Không có CSV thiếu và không có collision cùng filename nhưng khác bytes.

Independent local answer gold 31 QID:

| Candidate | Correct |
|---|---:|
| SAFE | 17/31 |
| UNION | 17/31 |
| FINAL | 17/31 |

Không có local-gold win hoặc loss. Đây không phải official accuracy; 21 QID mới
không giao với các local gold cases đang đúng.

## 5. FINAL — retrieval overlay bảo toàn nền

Trên mỗi QID:

1. giữ toàn bộ UNION table refs theo nguyên thứ tự;
2. append refs từ retrieval winner nếu chưa có;
3. dừng khi đạt 10 refs;
4. derive `relevant_docs` từ final table order để giữ submission contract;
5. không thay answer/query/evidence.

Kết quả:

| Chỉ tiêu | Kết quả |
|---|---:|
| QID có table additions | 419 |
| Table refs được append | 2.478 |
| Mean tables/QID | 5,0563 |
| Max tables/QID | 18 |
| Baseline table prefix preserved | 1.012/1.012 |

### Ngoại lệ cap 10

SAFE baseline đã có 15 QID vượt cap 10, tối đa 18 refs:

```text
377, 399, 402, 431, 438, 442, 443, 447, 451, 455,
472, 473, 478, 552, 568
```

Hai yêu cầu “không xóa bảng baseline” và “tổng tối đa 10 bảng” không thể cùng
đúng trên các QID này. Composer ưu tiên preservation: giữ nguyên refs và không
append thêm. Với các QID còn lại, cap 10 được áp dụng.

### Giới hạn metric claim

FINAL không byte-equivalent với official retrieval winner vì baseline refs luôn
đứng trước và không bị xóa. Do đó official Tables/Docs gain của submission 3770
là evidence định hướng, không phải số điểm được bảo đảm cho FINAL. Tables/Docs
metrics của FINAL vẫn là `NOT_MEASURED` trước upload.

## 6. Audit 16 P0 differences

Phạm vi gồm 14 `BOTH_DIFFERENT_ANSWER` và 2 `P0_ONLY` từ shadow run.

| QID | Source audit | Quyết định |
|---:|---|---|
| 18 | original 2015 và comparative opening 2016 khác nhau; chưa có adjudication restatement | AMBIGUOUS, không sửa |
| 40 | P0 lấy đúng `Lợi nhuận sau thuế`; legacy lấy `Lợi nhuận trước thuế` | P0 source-win, nhưng baseline đã khóa |
| 96 | câu hỏi yêu cầu child `Chi phí trả trước ngắn hạn khác`; P0 lấy parent | P0 loss |
| 118 | P0 lấy đúng `Dự phòng chung`; legacy lấy cash-flow loan row | P0 source-win, nhưng baseline đã khóa |
| 127 | legacy lấy tổng tài sản; P0 lấy tổng TSCĐ hữu hình, cả hai thiếu child `khác` | không có proven winner |
| 190 | legacy lấy đúng dự phòng chung của chứng khoán AFS; P0 lấy loan provision | P0 loss |
| 197 | P0 đúng metric nhưng output âm; sign contract cho “tổng số dư” chưa được chứng minh | không promote |
| 209 | legacy khớp `phải thu về cho vay dài hạn`; P0 nhầm sang `vay dài hạn` | P0 loss |
| 291 | P0 giữ đúng đơn vị nguồn `Ngàn VND`; legacy scale thêm 1.000 | P0 source-win, nhưng baseline đã khóa |
| 582 | balance-sheet và note loan values khác nhau | AMBIGUOUS, không sửa |
| 588 | cả hai lấy parent `phải thu ngắn hạn khác`, chưa ground qualifier `các bên liên quan` | không có proven winner |
| 651 | comparative 2018 và original 2017 khác nhau | AMBIGUOUS, không sửa |
| 816 | P0 dùng đủ ba consolidated short-term loan values và tính average | một P0-only source-win |
| 905 | P0 lấy đúng `Doanh thu hoạt động tài chính`; legacy lấy total revenue | P0 source-win, nhưng baseline đã khóa |
| 947 | 2017 original và 2018 comparative khác nhau | AMBIGUOUS, không sửa |
| 956 | câu hỏi yêu cầu `khu vực Miền Bắc`; P0 lấy total bank PBT, không có region grounding | P0-only loss |

14 answer khác nhau đều nằm trong 604 baseline emitted đã khóa, nên không được
thay dù có một số source-win chẩn đoán. Chỉ Q816 và Q956 là baseline abstain:

```text
P0-only audit: 1 win / 1 loss
required gate: >= 3 wins / 0 loss
decision: FAIL — không tạo answer patch
```

## 7. Validation, replay và determinism

### UNION

```text
records:          1012
validator errors: 0
warnings:         0
executed:         625
matched:          625
no evidence:      387
replay errors:    0
```

### FINAL

```text
records:          1012
validator errors: 0
warnings:         0
executed:         625
matched:          625
no evidence:      387
replay errors:    0
```

Archive inspection cho cả hai:

- đúng một `submission.json` ở ZIP root;
- 1.012 unique IDs;
- 1.070 CSV members, tất cả được tham chiếu;
- 0 orphan CSV;
- 0 missing CSV;
- `unzip -t`: PASS.

### Two-build determinism

| Artifact | Build A SHA-256 | Build B SHA-256 | Result |
|---|---|---|---|
| UNION | `97429bc3a3070c286b474ef36b4d9dc756e5a64013d0c1efb4654d7931b70b68` | giống A | PASS |
| FINAL | `535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933` | giống A | PASS |

Build B được giữ tại:

`artifacts/runs/submission/baseline-union-overlay-20260830-b/`.

## 8. Repository gates

| Gate | Kết quả |
|---|---|
| Composer unit tests | 3/3 PASS |
| `make ci` | PASS — typecheck 92 files, docs 0 broken links, 2.204 tests PASS |
| `make test-integration` | 23 PASS |
| `make snapshots-verify` | PASS toàn bộ Raw/A6/Retrieval |
| `git diff --check` | PASS |

Composer commit: `3a69690bb7b72475b42b8122cf010a7ca421cab2`.

## 9. MODEL_GOLD preservation

Không gọi generator/model và không đọc MODEL_GOLD để tạo prediction.

| Thuộc tính | Giá trị |
|---|---:|
| Completed records | 71 |
| Raw attempts | 203 |
| `PARTIAL_CHECKPOINT.json` SHA-256 | `2ad024612f131f1781f482b6929effdf40fbc8d0b223665e1177f0e0ca124636` |
| `generation_state.json` SHA-256 | `b306c8fc96a818ce8da7162afac14976636224572b33f074ebd506df942f3a8d` |

## 10. Release decision

```text
SAFE:  READY, rollback artifact
UNION: READY, answer-coverage candidate
FINAL: READY, recommended upload candidate
P0:    OFF
MODEL_GOLD: FROZEN
UPLOAD: NOT PERFORMED
```

Nếu quota chỉ còn một lượt, artifact được đề xuất là FINAL với exact SHA-256
`535ee597e8b87662451a60d46c147189f0919b397dda63c472ac94a07cf79933`.
