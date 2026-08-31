# Audit Table Retrieval — Giải thích Tables F2-Macro = 0.2500

**Ngày audit:** 2026-08-28  
**Submission hiện tại:** 3757  
**Submission so sánh:** 3721  
**Phạm vi:** read-only audit; không sửa source code  
**Verdict:** Không thể reproduce submission 3757 từ repository vì thiếu ZIP/receipt/checksum gắn với ID đó và thiếu gold/scorer chính thức. Vì vậy chưa có cơ sở gán phần trăm lỗi chính thức cho candidate generation, ranking hay mapping. Bằng chứng mạnh nhất hiện có cho thấy `relevant_tables` cuối cùng bị chi phối bởi truncation policy và downstream binding, nên Tables F2 đang đo nhiều hơn “retrieval thuần”.

## 1. Metric chính xác

Tài liệu cuộc thi [`Text2Pandas.docx`](../competition/Text2Pandas.docx) định nghĩa:

- Relevant table: bảng chứa một phần hoặc toàn bộ dữ liệu cần để tính đáp án.
- Precision, Recall và F2 được tính cho từng query, rồi lấy trung bình macro trên query.
- Predicted table được nộp dưới dạng `"<report_id>|<position_in_report>"`, ví dụ `VNM_01_2025|350`.

Với mỗi câu `q`:

- `G_q`: tập gold table, `g = |G_q|`.
- `S_q`: tập table nộp, `n = |S_q|`.
- `h = |G_q ∩ S_q|`.
- `P_q = h/n`.
- `R_q = h/g`.
- `F2_q = 5P_qR_q/(4P_q+R_q) = 5h/(4g+n)`.

Sau đó:

```text
P_macro  = mean(P_q)
R_macro  = mean(R_q)
F2_macro = mean(F2_q)
```

Đây không phải F2 của hai số macro P/R. Kiểm tra trực tiếp:

- 3757: `F2(0.2921, 0.2461) = 0.254103`, khác `0.2500`.
- 3721: `F2(0.2904, 0.2475) = 0.255035`, khác `0.2511`.

Local evalkit triển khai đúng dạng per-query `5h/(4g+N)` tại [`metrics.py`](../../src/text2pandas/pipelines/retrieval/evalkit/metrics.py), nhưng đây không phải scorer của ban tổ chức.

| Thuộc tính | Kết luận |
|---|---|
| Đơn vị macro | `question` — xác nhận |
| Gold table | Hidden organizer gold; chỉ có định nghĩa khái niệm |
| Predicted table | Các chuỗi trong `relevant_tables` |
| Document + table ID | Cùng nằm trong composite locator; scorer match exact hay normalized là `UNKNOWN` |
| Normalization | `UNKNOWN` |
| Duplicate trên server | `UNKNOWN`; local validator từ chối duplicate |
| Multiple gold | Công thức hỗ trợ; số lượng hidden gold `UNKNOWN` |
| Empty prediction | Spec không định nghĩa zero-division; local evalkit cho P/F2 bằng 0 |
| Câu không có gold | `UNKNOWN`; local evalkit loại khỏi mẫu số |
| F2 top-k | Không công bố; có thể chấm toàn bộ danh sách đã nộp, nhưng `UNKNOWN` |
| MRR5 | Không có trong DOCX; local code dùng reciprocal rank của gold đầu tiên trong top 5 |
| Mapping trước scoring | `UNKNOWN` |

Local MRR@K nằm trong [`metrics.py`](../../src/text2pandas/pipelines/retrieval/evalkit/metrics.py). Local validator yêu cầu locator `doc|positive_line`, không duplicate, và `relevant_docs` phải suy ra đúng từ `relevant_tables` trong [`submission.py`](../../src/text2pandas/application/usecases/submission.py).

## 2. Scoring pipeline được reconstruct

```text
Organizer hidden questions
→ hidden relevant documents                       UNKNOWN implementation
→ hidden relevant tables                          UNKNOWN implementation
→ submission.relevant_tables
→ server-side normalization/mapping                UNKNOWN
→ table-ID matching                                UNKNOWN exact semantics
→ TP/FP/FN per question
→ Pq, Rq, F2q
→ mean over questions
→ Tables Precision / Recall / F2-Macro
```

Phần xác nhận được:

```text
prediction
= submission.json[i].relevant_tables
= ["<document/report id>|<table position>", ...]
```

Phần gold construction, normalization, duplicate policy, empty/no-gold policy và server MRR5 đều không có implementation trong repository.

## 3. Reproduce submission 3757

Không tìm thấy:

- ZIP hoặc prediction mang ID `3757`.
- Receipt từ leaderboard.
- Checksum ánh xạ ID `3757` hay `3721`.
- Official scorer hoặc hidden gold.

Hai ZIP đáng chú ý:

| Artefact | SHA-256 | Trạng thái |
|---|---|---|
| Semantic V3 candidate | `3e068bc697ac9d34512f16d520af5bf4d51a6e0dc3137c503a25f9acfacb54f0` | 1.012 câu; 362 non-empty, 650 empty |
| Canonical V2 hiện tại | `a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c` | 1.012 câu; 1.011 non-empty, 1 empty |

Semantic V3 gần như chắc chắn không phải exact ZIP 3757 theo contract thông thường: chỉ 362/1.012 câu có predicted docs, nên trần macro Docs Recall là `362/1012 = 0.3577`, thấp hơn leaderboard `0.6257`. Ngoại lệ duy nhất là server loại hàng trăm câu khỏi mẫu số, điều không phù hợp với mô tả macro toàn tập.

Canonical ZIP hiện tại cũng không thể nhận là 3757: report được ghi nhận tại
`artifacts/reports/e2e_submission_a2d3ef030861/FINAL_REPORT.md` (không được
materialize trong checkout hiện tại) ghi rõ ZIP này chưa upload.

| Metric | Leaderboard 3757 | Local official reproduction | Absolute difference |
|---|---:|---:|---:|
| Tables P | 0.2921 | `NOT_MEASURED` | `UNKNOWN` |
| Tables R | 0.2461 | `NOT_MEASURED` | `UNKNOWN` |
| Tables F2 | 0.2500 | `NOT_MEASURED` | `UNKNOWN` |
| Tables MRR5 | 0.3360 | `NOT_MEASURED` | `UNKNOWN` |

Đây là measurement/identity blocker. Không được dùng proxy local như reproduction.

## 4. Diagnostic theo question

Không thể tạo bảng diagnostic chính thức vì thiếu cả exact prediction 3757 lẫn hidden gold. Vì vậy TP/FP/FN, rank gold và contribution vào F2 loss cho cả 10 bucket đều là `UNKNOWN`.

Repository ghi nhận diagnostic proxy cho 95/1.012 câu tại
`artifacts/runs/retrieval/release-paired-20260828/current_after.jsonl` (không
được materialize trong checkout hiện tại), nhưng:

- Coverage chỉ `9.387%`.
- Gold trung bình `5.83` bảng/câu, median 2; hidden gold có thể khác đáng kể.
- Registry [`gold_registry_v1.yaml`](../../configs/evaluation/gold_registry_v1.yaml) xác nhận không có gold nào promotion-eligible.

Vì thế số câu, tỷ lệ, FN contribution và F2-loss contribution của các bucket `GOLD_TABLE_NOT_IN_CANDIDATE_POOL` đến `OTHER/UNKNOWN` đều chưa đo được trên official sample.

Các khoảng hụt duy nhất có thể nói chính xác từ leaderboard là:

- Macro recall gap: `1 − 0.2461 = 0.7539`.
- Macro precision gap: `1 − 0.2921 = 0.7079`.
- F2 gap tới 1: `0.7500`.

Đây là khoảng hụt metric, không phải tỷ lệ question hay tỷ lệ nguyên nhân.

## 5. Candidate recall

Trên 95 câu local có manual labels:

| K | Hit@K: có ít nhất một gold | Gold-item Recall@K |
|---:|---:|---:|
| 1 | 0.3474 | 0.1818 |
| 5 | 0.8421 | 0.5664 |
| 10 | 0.9053 | 0.7117 |
| 20 | 0.9684 | 0.7956 |
| Full S1 pool | 1.0000 candidate hit | Full-item recall không được lưu |

Nguồn được ghi nhận tại
`artifacts/runs/retrieval/release-paired-20260828/paired_comparison.json`
(artifact không được materialize trong checkout hiện tại).

Phân loại proxy:

- Case A, không có bất kỳ gold nào trong S1: `0/95`.
- Case B, có gold trong S1 nhưng không có gold trong top 10: `9/95 = 9.47%`.
- Với N động thực sự dùng để nộp, chỉ `50/95` có hit; `45/95 = 47.37%` mất hết gold trước scorer.
- Case C, rank cao nhưng server coi sai: `UNKNOWN`, vì không có official scorer.

Các số này không được chuyển thành A/B/C của submission 3757.

## 6. Document đúng nhưng table sai

Không thể tính `P(table correct | document correct)` từ các macro marginal riêng biệt. Cần joint outcome theo QID.

| Document | Table | Đếm official |
|---|---|---:|
| Correct | Correct | `UNKNOWN` |
| Correct | Wrong | `UNKNOWN` |
| Wrong | Wrong | `UNKNOWN` |
| Wrong | Correct | Về logic locator là bất khả nếu match exact; server behavior vẫn `UNKNOWN` |

Tỷ số:

```text
R_table / R_doc = 0.2461 / 0.6257 = 0.3933
```

Đây chỉ là heuristic “table recall giữ lại khoảng 39.33% so với doc recall”; nó không phải xác suất có điều kiện vì gold docs/tables có cardinality khác nhau và cả hai là macro-average.

Hai ZIP local đều có zero duplicate, zero malformed locator và `relevant_docs` được suy đúng từ tables. Vì vậy không có bằng chứng local cho lỗi serialization nội bộ; server-side mapping vẫn chưa được kiểm chứng.

## 7. Trace table retrieval pipeline

Canonical V2 thực tế:

| Stage | Logic | Failure/measurement |
|---|---|---|
| Question intent | Entity, alias, year, basis, mode | Alias/entity sai có thể làm S1 rỗng |
| S1 | Hard filter theo ticker/year; basis mặc định soft | Candidate hit local 95/95 |
| S2 | BM25 theo nội dung + structural bonuses, top 50 | Recall@10 local 0.7117 |
| S3 | Identity reranker, không có model | Không cải thiện thứ hạng |
| N policy | `clamp(entity_count × year_count, 1, 10)` | Policy hit chỉ 50/95 |
| Answer pool | Top 50 table → candidate cells | Binding có thể chọn table khác top-N |
| Binding | `QuestionSelector` + operation routes | Answer đúng đường thì refs bị thay bằng evidence tables |
| Abstain | Giữ retrieval top-N | Không bị empty trừ khi retrieval rỗng |
| Serialization | `table_uid → doc|line`, stripped ID, 1-based | Server base/normalization chưa xác nhận |
| Evaluator | Hidden server scorer | `UNKNOWN` |

Các đoạn quyết định:

- S1/S2/S3/N tại [`submission_adapter.py`](../../src/text2pandas/pipelines/retrieval/submission_adapter.py).
- S3 là pass-through tại [`stages.py`](../../src/text2pandas/pipelines/retrieval/evalkit/stages.py).
- Answer thành công ghi đè refs bằng exact evidence tables; abstain giữ retrieval refs tại [`canonical_run.py`](../../src/text2pandas/application/usecases/canonical_run.py).
- Locator mapping tại [`submission_adapter.py`](../../src/text2pandas/pipelines/retrieval/submission_adapter.py).

Semantic V3 là đường khác:

```text
Question
→ ontology/A6 source metric resolution
→ OperandRequest
→ A6 observation retrieval top 20
→ joint binding
→ typed execution
→ pandas compilation/replay
→ exact bound evidence tables
→ empty refs nếu bất kỳ stage nào abstain
```

V3 không dùng BM25 table pool mặc định. Nó truy observation trực tiếp từ A6 tại [`operand.py`](../../src/text2pandas/infrastructure/retrieval/operand.py), và failure trả empty refs tại [`semantic_v3.py`](../../src/text2pandas/application/usecases/semantic_v3.py).

Các stage chính đều có unit/integration tests, nhưng không có test end-to-end đối chiếu official scorer.

## 8. Kiểm tra 14 nghi vấn trước đây

| Vấn đề | Phân loại | Bằng chứng |
|---|---|---|
| Phrase → Silver row label | `CONTRIBUTING` có điều kiện | V3 có A6 resolver nhưng vẫn abstain 47 specificity, 10 ambiguity, 4 no-mapping |
| Missing metric resolution | `NOT RELATED` với V3 candidate | Manifest ghi `METRIC_UNRESOLVED=0`; resolver đã được nối |
| Missing operand semantics | `NOT RELATED` với V3 | `OperandRequest` được materialize theo metric/entity/period/basis |
| Missing derived metric layer | `CONTRIBUTING` cho execution | 162 V3 abstain vì reported metric chưa review cho derived operation |
| Missing composition layer | `CONTRIBUTING` | Các rank/filter/count family vẫn abstain; không phải raw candidate miss |
| SelectorSpec/lookup | `NOT RELATED` | V2 spec tự khai “not yet wired” trong [`spec.py`](../../src/text2pandas/pipelines/answering/spec.py) |
| Entity alias resolution | `CONTRIBUTING` subset | Có tests và Q586 cải thiện rank 25→5; không chứng minh tác động official |
| Document → table binding | `DIRECT MECHANISM` | Final tables bị thay bằng downstream evidence |
| Candidate generator | `UNKNOWN` official | Proxy 95 tốt nhưng không có hidden-gold recall |
| Selector là stub | `NOT RELATED` canonical | Canonical inject `QuestionSelector`, không dùng base selector đơn giản |
| `metric_id` empty | `NOT RELATED` V3 | AST validation từ chối `EMPTY_METRIC_ID` |
| Fallback | `PATH-DEPENDENT` | Canonical có fallback top-N; V3 failure trả empty |
| Hai semantic path | `CONTRIBUTING`/operational risk | Hai ZIP chỉ cùng exact table set 141/1.012 câu; 163 câu cùng non-empty nhưng disjoint |
| Candidate lấy từ parent evidence | `NOT RELATED` như mô tả | Canonical lấy retrieval index; V3 lấy A6 observations, không chỉ parent evidence |

## 9. So sánh 3721 và 3757

| Metric | 3721 | 3757 | Delta |
|---|---:|---:|---:|
| Execution Accuracy | 0.2549 | 0.2589 | **+0.0040** |
| Tables F2 | 0.2511 | 0.2500 | **−0.0011** |
| Tables Precision | 0.2904 | 0.2921 | **+0.0017** |
| Tables Recall | 0.2475 | 0.2461 | **−0.0014** |
| Tables MRR5 | 0.3375 | 0.3360 | **−0.0015** |
| Docs F2 | 0.6321 | 0.6326 | **+0.0005** |

Không thể xác định chính xác code/config diff giữa hai submission. Repository có các commit retrieval `b0d7b84`, metric resolution `33cb51b`, và release hiện tại `a2d3ef0`, nhưng không có receipt ánh xạ chúng sang 3721/3757.

Kết luận từ score-level evidence:

- Retrieval table không cải thiện: F2, Recall và MRR5 đều giảm.
- Precision tăng rất nhẹ, phù hợp với danh sách hẹp hơn hoặc binding evidence chính xác hơn.
- Execution tăng trong khi retrieval gần như đứng yên/giảm.
- Vì vậy cải thiện Execution nhiều khả năng đến từ parsing, binding, query generation hoặc operation handling downstream, không phải table retrieval. Đây là inference từ score delta, chưa phải causal proof.

## 10. Xếp hạng nguyên nhân có bằng chứng

| Rank | Root cause | Impact | Confidence | Cost |
|---:|---|---|---|---|
| 1 | P0 measurement identity: thiếu exact ZIP/receipt/scorer/gold | Chặn toàn bộ diagnosis official | Rất cao | Thấp |
| 2 | Final table output bị coupling với binding và N policy | Có thể đổi cả P/R dù S1 không đổi | Cao về cơ chế, chưa biết official magnitude | Trung bình |
| 3 | Ranking/truncation: S3 identity, N động quá hẹp | Proxy policy mất toàn bộ hit ở 45/95 câu | Trung bình | Trung bình |
| 4 | Downstream semantic/binding abstention | Canonical hiện tại 449 abstain; V3 650 abstain | Cao với local artefact, chưa ánh xạ 3757 | Trung bình–cao |
| 5 | Entity/alias subset | Đã quan sát Q586 cải thiện; không có top-10 regression trên 95 | Trung bình | Thấp |
| — | Candidate recall P0 | Chưa chứng minh trên hidden gold | `UNKNOWN` | `UNKNOWN` |
| — | Server mapping/scorer mismatch | Thiếu scorer và receipt | `UNKNOWN` | Có thể thấp nếu chỉ format |

Điểm quan trọng: “candidate recall là nguyên nhân chính” hiện chưa được chứng minh. Proxy hiện tại lại nghiêng về lỗi từ ranking/truncation/final prediction hơn S1 candidate generation.

## 11. Nút thắt thực sự và ba phương án

Nếu buộc chọn một thay đổi code để tăng Execution Accuracy, lựa chọn có evidence tốt nhất là xử lý có kiểm soát family `MULTI_ENTITY_OPERATION_NOT_SUPPORTED` của canonical V2, không tiếp tục tinh chỉnh retriever.

Artefact canonical hiện tại có:

- 563 OK, 449 abstain.
- 177/1.012 câu thuộc family multi-entity unsupported, tức theoretical affected set `17.49%`.
- Đây là ceiling cơ hội, không phải dự báo tăng 17.49 điểm.
- Retrieval changes giữa 3721→3757 không đem lại uplift, còn downstream có uplift.

### Option A — An toàn nhất trước deadline

Không đổi logic. Dùng exact canonical ZIP `a96ecc3c1113af69895d3a131876f2ae48e3827651a6112f0cf7066adc00445c` làm controlled leaderboard measurement, lưu receipt + submission ID + SHA-256 ngay sau upload. Điều này đóng blocker lớn nhất và tránh tối ưu nhầm artefact.

### Option B — ROI cao nhất

Giữ nguyên retrieval/table refs, chỉ hỗ trợ các subtype deterministic trong 177 câu multi-entity: sum, average, difference hoặc count khi operands bind duy nhất và replay khớp. Fail closed cho ambiguity và A/B per-Q để không làm regression 563 câu đang OK.

Đây là phương án được chọn nếu bắt buộc sửa một thứ để tăng Execution Accuracy.

### Option C — Kiến trúc đúng dài hạn

Hợp nhất canonical và Semantic V3 thành một typed operand path; tách rõ:

```text
retrieval ranking prediction
≠
answer evidence/binding
```

Sau đó đánh giá bằng scorer-compatible gold theo QID trước khi thay production. Không nên promote toàn bộ V3 hiện tại: promotion manifest đang `BLOCKED` và coverage thấp hơn canonical.

## Kết luận

1. Tables F2-Macro là trung bình theo question của `5h/(4g+n)`, chấm các composite table locator trong `relevant_tables`; nó không phải F2 tính từ macro Precision/Recall.
2. Điểm 0.2500 trực tiếp đến từ macro Recall 0.2461 và Precision 0.2921; nguyên nhân pipeline mạnh nhất có bằng chứng là final table list bị truncation và downstream binding chi phối, nhưng chưa thể chứng minh đây là nguyên nhân chính thức của 3757.
3. Tỷ lệ official do candidate/ranking/mapping/scorer/downstream đều `UNKNOWN`; proxy 95 câu cho `0%` mất toàn bộ gold tại S1, `9.47%` mất tại top-10 và `47.37%` mất dưới N policy.
4. Trước deadline, hãy đóng receipt/checksum trước; nếu bắt buộc sửa code, ưu tiên family multi-entity của canonical V2 với 177 câu bị ảnh hưởng và giữ nguyên retrieval.
5. Không nên tiếp tục tune S1 aliases/BM25 theo proxy 95 câu, không blanket-relax semantic safety gates, và không promote toàn bộ V3 khi chưa có official-compatible gold/scorer.
