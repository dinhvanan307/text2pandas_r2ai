# Recovery Wave 4 — Semantic Parsing → Composition E2E Report

**Ngày thực hiện:** 2026-08-30  
**SAFE baseline:** submission `3831`  
**Baseline Answer/Execution Accuracy:** `0.3874` (official, do người dùng cung cấp)  
**Candidate:** `recovery-wave4-3831-source6-20260830-r1`  
**Release mode:** recover-only, additive trên baseline abstention  
**Official accuracy của candidate:** `NOT_MEASURED`

---

## 1. Kết luận

Flow trong plan đã được thực thi end-to-end qua các layer:

```text
freeze 3831
→ protected sets / failure inventory
→ semantic parsing
→ metric/source resolution
→ entity/period/basis axes
→ compositional binding + consensus
→ full 1,012-QID shadow
→ source adjudication
→ deterministic candidate R1/R2
→ competition validation + clean replay
→ manual-upload handoff
```

Candidate cuối chỉ thêm sáu answer đã source-adjudicated vào sáu QID mà baseline 3831 đang abstain:

```text
Q513, Q521, Q537, Q632, Q799, Q827
```

Không answer/query/evidence nào trong 792 QID executable của baseline bị đổi. Không retrieval record nào bị đổi. Candidate đã vượt competition release gate và sẵn sàng cho một lượt leaderboard measurement thủ công, nhưng chưa được coi là production-promoted vì chưa có official score và chưa có independent promotion gold.

ZIP cần nộp:

```text
artifacts/handoffs/recovery-wave4-3831-source6-final-20260830/submission.zip
```

SHA-256:

```text
2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76
```

---

## 2. Baseline và protected contract

Baseline được freeze tại:

```text
artifacts/official/submission-3831/submission.zip
```

Identity:

| Thành phần | Giá trị |
|---|---|
| Baseline SHA-256 | `c1494ea630e7654def93a426d6f00b31f77fef05a67baac4e07e1ac7be262245` |
| Questions | `1,012` |
| Baseline executable | `792` |
| Baseline abstention | `220` |
| Baseline clean replay | `792/792` |
| A6 build | `c6887fb633374fad` |
| A6 SHA-256 | `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8` |
| Retrieval index | `872ccb0dda9a2bb6` |

Protected sets:

| Set | Kích thước | Release rule |
|---|---:|---|
| P-answer | 792 | answer/query/evidence không được đổi |
| P-retrieval | 1,012 | relevant tables/documents không được đổi |
| W4 mutation pool | 220 | chỉ được thêm answer sau source adjudication |
| P-wave3 | 29 | không rollback fill đã có |

Artifacts:

```text
artifacts/runs/evaluation/recovery-wave4-3831-inventory-20260830-v1/
artifacts/runs/evaluation/recovery-wave4-3831-protected-20260830-v1/
```

---

## 3. Thay đổi theo layer

### 3.1 Semantic parsing

Commit `788baf1` bổ sung alias HNG đã được câu hỏi chứng thực. Q782 chuyển từ lỗi entity resolution sang AST đầy đủ VNM–HNG; source adjudication về sau vẫn loại Q782 vì scale nguồn HNG không an toàn.

### 3.2 Metric/source resolution

Commit `ce981d9` thêm resolver config bất biến `metric_resolution_v2.yaml` và sửa `A6MetricMentionResolver`:

- entity aliases vẫn bị chặn ở discovery;
- scoring chỉ mask representative span của từng entity;
- không để tên công ty trở thành metric giả;
- vẫn giữ được counterparty label hợp lệ, ví dụ sở hữu tại một công ty khác;
- collision/tie không tương đương tiếp tục abstain.

S1→S2 có 12 functional changes. Ba QID mới đạt `OK` ở shadow; Q500 bị đưa về abstain vì implementation cũ chọn mức số dư thay vì mức tăng được hỏi.

### 3.3 Entity/period/basis axes

Commit `634985d` giữ đủ `ordered_tickers` cho average khi parser ban đầu chỉ đưa entity đầu vào `targets`. Rule chỉ kích hoạt cho `AVERAGE` và không sửa các AST đã có domain đầy đủ.

Q827 sau sửa có đủ bốn entity `SNZ, VIC, DXS, HPX`, cùng basis công ty mẹ, cùng thời điểm cuối năm 2019.

### 3.4 Composition và binding consensus

Commit `1efc664` thêm policy `require_answer_consensus=true` cho Semantic V4:

- tối đa 8 parse candidates;
- tối đa 3 binding candidates trên mỗi parse path;
- nếu các candidate sống sót tạo answer khác nhau thì abstain `SEMANTIC_CANDIDATE_DISAGREEMENT`;
- không chọn candidate đầu tiên hoặc candidate score cao hơn khi semantic meaning chưa được phân xử.

Policy:

```text
configs/semantic/search_v4_wave4.yaml
```

---

## 4. Full shadow/differential 1,012 QID

| Run | Scope | OK | Abstain | Functional outcome |
|---|---:|---:|---:|---|
| S0 baseline semantic | 1,012 | 488 | 524 | pre-change baseline |
| S1 parser | 1,012 | 489 | 523 | Q782 entity alias resolved |
| S2 resolver | 1,012 | 491 | 521 | entity-name false metrics reduced |
| S3 axes | 1,012 | 492 | 520 | complete average entity axes |
| S4 strict composition | 1,012 | 197 | 815 | 423 disagreement, 392 no verified program |

S4 giảm terminal `OK` có chủ đích: strict consensus chuyển các candidate có answer disagreement về abstain thay vì phát một answer không được chứng minh.

S4 manifest ghi sáu replay mismatch trong rejected alternatives của Q522. Không có mismatch trong 197 accepted S4 records. Candidate release cuối có `0` mismatch trên toàn bộ 798 answer emitted.

Full shadow artifacts:

```text
artifacts/runs/semantic-v3/semantic-v3-wave4-3831-baseline-20260830-v1/
artifacts/runs/semantic-v3/semantic-v3-wave4-3831-parser-s1-20260830-v1/
artifacts/runs/semantic-v3/semantic-v3-wave4-3831-resolver-s2-20260830-v3/
artifacts/runs/semantic-v3/semantic-v3-wave4-3831-axes-s3-20260830-v3/
artifacts/runs/semantic-v4/semantic-v4-wave4-3831-composition-s4-20260830-v1/
```

Parser/metric/binding exact accuracy trên full corpus vẫn là `NOT_MEASURED` vì không có sealed eligible gold. Các số `OK` ở trên là coverage/fail-closed diagnostics, không phải accuracy.

---

## 5. Source adjudication

Review queue gồm 22 QID: 12 S4 `OK` trong mutation pool và 10 QID S3 từng `OK` nhưng S4 abstain do disagreement.

Ledger:

```text
configs/evaluation/recovery_wave4_review_3831_v1.json
```

Ledger SHA-256:

```text
9ea971a59c494677775bab60a90ee81d5ebfad283e884f3e28b5afd048fbc84a
```

Kết quả:

| Decision | QID |
|---|---:|
| `PASS_SOURCE_PROVEN` | 6 |
| `FAIL_CLOSED` | 16 |
| Source facts trong accepted set | 34 |

### 5.1 Accepted QID

| QID | Answer | Source proof |
|---:|---:|---|
| 513 | `9.497171212` | inventory cao nhất tại 2017; lấy đúng cột `Giá gốc`, không lấy dự phòng |
| 521 | `500.688616629` | tiền và tương đương tiền cuối năm cao nhất tại 2023; lấy exact interest-expense note row |
| 537 | `9.332682344` | quỹ KH&CN lớn nhất tại 2024; projected closing investment row cùng năm |
| 632 | `26.261844792838143` | growth tài sản dài hạn mã 200 từ 2016 đến 2020; cùng scale nghìn VND |
| 799 | `-118.848765917` | công ty mẹ HBC trừ công ty mẹ SAM theo đúng thứ tự câu hỏi |
| 827 | `602.37564375975` | mean bốn parent-company balances; VIC được đổi triệu VND sang VND trước khi tính |

### 5.2 Các lỗi quan trọng bị loại

| QID/family | Lý do fail-closed |
|---|---|
| Q412 | thiếu MSN trong entity domain |
| Q435 | bỏ qua hypothetical revenue drop 10% |
| Q450 | bỏ qua median filter PAT–CFO/average assets |
| Q459 | rank theo equity thay vì liabilities/equity |
| Q495 | source metric/evidence sai family đã được review trước đó |
| Q526 | exact combined EPS fact 2023 không execution-ready |
| Q782 | HNG row ghi nghìn VND nhưng scale exponent bằng 0 |
| Q922 | DXS consolidated financial-expense row không đủ rõ; ba answer disagreement |
| Q929 | generic/issued/special bonds bị dùng thay Government bonds |
| complex filtered compositions | semantic disagreement chưa được source-resolve toàn bộ operand chain |

Không QID yếu nào được ép nhận để đạt target 20–24 fills.

---

## 6. Candidate và release gates

R1/R2:

```text
artifacts/runs/recovery-wave4/recovery-wave4-3831-source6-20260830-r1.zip
artifacts/runs/recovery-wave4/recovery-wave4-3831-source6-20260830-r2.zip
```

Hai file byte-identical và cùng SHA-256:

```text
2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76
```

| Gate | Kết quả |
|---|---:|
| Records | `1,012/1,012` PASS |
| Candidate executable | `798` |
| Candidate abstention | `214` |
| Clean replay | `798/798` PASS |
| Replay mismatch/error | `0/0` |
| Competition validation errors | `0` |
| Competition warnings | `428` expected warnings = 2 × 214 abstentions |
| Protected answer/query/evidence | `792/792` unchanged |
| Retrieval preservation | `1,012/1,012` unchanged |
| Baseline CSV payload preservation | `1,187/1,187` byte-identical |
| Changed answer-layer QID | exactly `513, 521, 537, 632, 799, 827` |
| New evidence CSV | exactly 6 |
| R1/R2 deterministic | PASS |
| ZIP integrity | PASS |

Complete profile vẫn FAIL vì 214 abstention; competition profile PASS đúng release contract đã preregister.

Handoff:

```text
artifacts/handoffs/recovery-wave4-3831-source6-final-20260830/
├── submission.zip
├── HANDOFF.json
├── candidate_manifest.json
├── SHA256SUMS
└── README.md
```

---

## 7. Test results

| Gate | Kết quả |
|---|---|
| Targeted parser/resolver/planner/compiler/executor/handoff | `97 passed` |
| Offline suite | `2,422 passed, 42 skipped, 29 deselected` |
| Integration suite | `22 passed, 2,471 deselected` |
| Typecheck | `115 source files`, 0 issue |
| Snapshot verification | PASS raw/A6/retrieval identities |
| Data-product test | `2,444 passed, 42 skipped`, verdict PASS |
| `git diff --check` | PASS |

Data-product report:

```text
artifacts/reports/recovery-wave4-3831-e2e-20260830/test_report.json
```

`make ci` PASS lint/typecheck nhưng dừng ở `docs-check` do 15 broken links tới artifact lịch sử 2026-08-29 đã không còn trong workspace. Không link nào thuộc Wave 4. Các artifact lịch sử không được giả lập hoặc sửa đường dẫn trong task này; blocker này được giữ tách khỏi competition candidate gate.

---

## 8. Commits

| Commit | Phase |
|---|---|
| `91868fe` | freeze official submission 3831 |
| `b69359f` | protected sets |
| `788baf1` | question-attested HNG alias |
| `ce981d9` | metric/source resolver v2 |
| `634985d` | complete average entity axes |
| `1efc664` | strict answer consensus across semantic assignments |
| `ee754a5` | seal Wave 4 source-review ledger |
| `31c2bc9` | package recovery-wave4 candidates |

---

## 9. Accuracy expectation và submission decision

Candidate thêm sáu answer vào baseline abstentions. Do đó:

```text
worst measured answer gain if all six are wrong: 0
maximum answer gain if all six are correct: 6 / 1,012 ≈ 0.00593
maximum resulting accuracy: khoảng 0.3933
```

Đây chỉ là bound theo số fills, không phải prediction hay official accuracy. Official result vẫn phải được đo bằng leaderboard và map về exact ZIP SHA `2a3457…93d76`.

Decision sau upload:

| Official result | Action |
|---|---|
| Answer Accuracy `> 0.3874`, retrieval unchanged | promote thành SAFE mới |
| Answer Accuracy `= 0.3874` | giữ 3831; candidate không có measured gain |
| Answer Accuracy `< 0.3874` hoặc retrieval drift | rollback 3831 và audit upload mapping |

Global Semantic V3/V4 promotion vẫn `BLOCKED`: independent parser/binding/answer gold chưa đủ. Candidate này chỉ là recover-only manual leaderboard experiment.

---

## 10. File nộp

Upload trực tiếp file sau:

```text
/Users/andinh307/Documents/Dagoras-R2AI/text2pandas-main/text2pandas/artifacts/handoffs/recovery-wave4-3831-source6-final-20260830/submission.zip
```

Không upload R2, manifest hoặc toàn bộ handoff directory. Sau khi leaderboard trả kết quả, cần lưu submission ID, timestamp và đủ 10 metrics cùng SHA trên trước khi quyết định promote.
