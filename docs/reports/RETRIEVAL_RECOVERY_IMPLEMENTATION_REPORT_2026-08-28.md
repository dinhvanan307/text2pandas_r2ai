# Báo cáo triển khai Retrieval Recovery

**Ngày thực thi:** 2026-08-28

**Repository:** `text2pandas`

**Plan/handoff nguồn:** `docs/reports/RETRIEVAL_RECOVERY_DEV_HANDOFF_2026-08-28.md` (user-supplied)

**Trạng thái:** Hoàn tất gói nâng cấp retrieval an toàn; Semantic V3 vẫn ở chế độ shadow và chưa đủ điều kiện promotion.

## 1. Tóm tắt kết quả

Gói triển khai đã xử lý các hạng mục P0/P1 có thể thực thi an toàn ở tầng retrieval mà không sửa dữ liệu nguồn, không hạ gold gate và không đưa mô hình neural chưa được kiểm định vào default pipeline:

- Sửa lỗi sinh YAML làm alias corpus-attested bị gắn literal `...`.
- Bổ sung alias STB/EIB có provenance tới câu hỏi và raw snapshot cụ thể.
- Thêm bộ chuẩn hóa nhãn fact tất định cho punctuation, đánh số, Roman prefix, formula suffix và hierarchy.
- Mở rộng candidate contract với source identity và match provenance.
- Tách hard table whitelist khỏi soft table-rank prior.
- Chuẩn hóa failure taxonomy tại retrieval/binding.
- Hợp nhất chính sách số bảng nộp tối đa vào một nguồn sự thật.
- Bump Evalkit lên `evalkit-11` và khóa checkpoint bằng bytes của alias artifact.
- Thêm regression test trực tiếp cho Q464/Q508/Q586/Q783/Q792.

Kết quả Semantic V3 full-corpus trên cùng active A6 và cùng alias:

| Chỉ số | Matcher cũ | Fact matcher mới | Delta |
|---|---:|---:|---:|
| Câu hỏi | 1.012 | 1.012 | 0 |
| V3 `OK` | 269 | 287 | **+18** |
| V3 `ABSTAIN` | 743 | 725 | **-18** |
| Operand request `METRIC_REJECT_ALL` | 201 | 165 | **-36** |
| Operand request `SCOPE_EMPTY` | 2 | 2 | 0 |
| `BINDING_TIE` | 109 | 102 | -7 |
| Thời gian | 47,041 giây | 47,676 giây | +0,635 giây |

Như vậy matcher mới giảm 17,9% số operand request bị metric matcher loại sạch và tạo net gain 18 câu trả lời V3, với overhead full-corpus khoảng 1,35%. Kết quả này là coverage/behavior measurement, chưa phải answer-accuracy claim.

## 2. Baseline, dữ liệu và nguyên tắc triển khai

Mọi phép đo dùng đúng active lineage:

| Thành phần | Identity |
|---|---|
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Câu hỏi | 1.012 |
| Báo cáo tài chính raw | 1.973 |
| Table cards A6 | 146.246 |
| Retrieval DB | 4.239.663.104 bytes |

Các ràng buộc được giữ nguyên:

- V2 vẫn là canonical; V3 chỉ là shadow.
- Không sửa `data/raw`, `data/processed` hoặc active snapshot identity.
- Không bổ sung fact tài chính từ nguồn ngoài corpus.
- Không tăng top-K mù, không thêm BGE/ColBERT/cross-encoder/Qwen vào default.
- Không hạ semantic/evidence/answer gold gate.
- Không tự thêm ontology alias cho khái niệm chưa có gold review.

## 3. Công việc đã thực hiện

### 3.1. Entity alias và provenance

`tools/attest_brands.py` trước đây gọi `yaml.safe_dump()` cho từng scalar. PyYAML sinh document-end marker `...`, sau đó marker này trở thành một phần của alias và làm matching thất bại im lặng.

Đã thay bằng cách dump toàn bộ mapping trong một YAML document rồi đọc lại để kiểm số lượng. Artifact `configs/retrieval/company_brand_attested_v1.yaml` được tái sinh với kết quả:

- 68/77 tên được chứng thực trực tiếp trong corpus.
- 47 ticker có ít nhất một tên được chứng thực.
- 9 tên không được đưa vào nhánh corpus-attested.
- 0 alias còn suffix `...`.

Đã thêm `configs/retrieval/company_question_attested_v1.yaml`:

| Ticker | Alias | Provenance |
|---|---|---|
| EIB | `Eximbank` | Q783, Q792 |
| STB | `Ngân hàng TMCP Sài Gòn Thương Tín` | Q508, Q624 |

Artifact ghi raw snapshot `ca033190f2e9e99f` và QID nguồn. Alias STB được giữ ở dạng đầy đủ để không va chạm với SCR. Lớp question-attested được nạp trong cả ba nhánh `full`, `a6`, `off` vì đây là evidence từ chính question corpus, không phải external brand knowledge.

Kết quả entity regression:

- Q508: `ACB`, `OCB`, `STB`.
- Q586: `ACV`.
- Q783: `MBB`, `EIB`, đúng thứ tự phép trừ.
- Q792: `EIB`, `MBB`.

### 3.2. Deterministic fact-label normalization

Đã thêm `normalize_fact_label()` và `fact_label_segments()` tại `infrastructure/retrieval/fact_label.py`.

Pipeline chuẩn hóa:

1. Dùng normalization tiếng Việt hiện hữu của domain.
2. Loại leading enumerator dạng số, số phân cấp, chữ cái và Roman numeral.
3. Loại numeric/formula suffix, ví dụ `(100 = 110 + 120)`.
4. Chuẩn hóa punctuation thành khoảng trắng.
5. Giữ semantic parenthetical như `(ngân hàng mẹ)`.
6. Tách hierarchy trên `›`, `>`, `→`, `»`.

Hai hàm được cache có giới hạn để tránh chuẩn hóa lại cùng row label qua hàng nghìn operand request. Dấu `/` không được coi là hierarchy separator để không phá ngày hoặc nhãn có slash.

### 3.3. Fact matcher `fact-retrieval-v2`

`SqliteOperandRetriever` nay dựng metric pattern một lần khi khởi tạo và match theo các evidence surface sau:

- Source-normalized raw row leaf.
- Fact-normalized row leaf.
- Fact-normalized `metric_label_clean` khi khác row leaf.
- Generic total leaf kết hợp hierarchy parent.
- Aggregate prefix `tổng cộng`, `tổng`, `cộng`.

Negative constraints `forbidden_prefixes` và `forbidden_contains` vẫn được áp dụng ở cả raw và fact-normalized surface.

Để bảo vệ hành vi cũ, raw exact match nhận tie-break rất nhỏ so với fact-normalized exact. Tie-break này không đủ lớn để lấn át period/document evidence. Regression `test_exact_leaf_bonus_does_not_override_stronger_period_context` khóa bất biến đó.

Hierarchy parent chỉ được dùng khi leaf là generic total (`tổng`, `tổng cộng`, `cộng`, `total`). Một descendant bình thường như `Tài sản ngắn hạn › Tiền` không được nhận nhầm thành `current_assets`.

Phân bố match trên full-corpus run mới, 1.985 candidate batches:

| Match method | Số candidate trước top-K |
|---|---:|
| `row_leaf_prefix` | 7.540 |
| `row_leaf_raw_exact` | 5.928 |
| `row_leaf_aggregate_prefix` | 905 |
| `row_leaf_exact` sau fact normalization | 726 |
| `row_hierarchy_parent` | 2 |

### 3.4. Candidate contract và table constraints

`ObservationCandidate` được mở rộng với:

- `row_uid`.
- Nullable `source_metric_code`.
- `matched_metric_id` độc lập với source code.
- `match_method`.
- `match_features`.

Retriever tự kiểm schema A6 bằng `PRAGMA table_info(observations)`. Active A6 trả source identity thật; fixture/legacy schema không có cột mới vẫn chạy được với giá trị nullable.

API table constraint được tách rõ:

- `hard_allowed_table_uids`: tạo SQL `IN`, thực sự loại candidate.
- `table_rank_priors`: chỉ cộng bounded score prior, không loại candidate.

Regression test xác nhận soft prior không biến thành whitelist. Shadow CLI hiện chưa nhận upstream V2 ranked-table list nên `table_prior_count=0`; contract đã sẵn sàng nhưng wiring V2 rank → V3 operand requests là hạng mục tiếp theo, không được giả là đã hoàn thành.

### 3.5. Failure taxonomy và binder

Candidate batch trace nay phân biệt:

- `UNKNOWN_METRIC`.
- `SCOPE_EMPTY`.
- `METRIC_REJECT_ALL`.
- `UNIT_REJECT_ALL`.
- `CANDIDATE_EMPTY`.

Binder truyền nguyên nhân này lên terminal reason kèm operand request IDs. Trường hợp đồng điểm nhưng khác semantic assignment được đổi tên từ `AMBIGUOUS_BINDING` sang `BINDING_TIE` đúng taxonomy của plan. Nhiều failure type trong cùng plan được ghi `CANDIDATE_EMPTY_MIXED` thay vì chọn tùy ý một lý do.

Trace retrieval còn ghi:

- số row scan/reject/match/return;
- phân bố match method;
- retrieval policy version;
- hard-filter có bật hay không;
- số table prior;
- top-K truncation.

### 3.6. Một nguồn sự thật cho policy N

Đã thêm `pipelines/retrieval/policy.py` với:

```text
N = clamp(max(1, n_targets) × max(1, n_years), 1, 10)
```

Các nơi sau cùng dùng chung policy:

- public `run` CLI default `--n-tables`;
- `RetrievalToSubmission.n_for()`;
- Evalkit `policy_n_map()`;
- `tools/rewrite_submission.py`.

Điều này loại bỏ drift giữa default CLI, submission adapter và evaluator.

### 3.7. Evalkit-11 và checkpoint identity

Đã thêm `alias_artifact_sha256()` băm đúng các artifact có hiệu lực trên từng branch:

- base company aliases;
- question-attested aliases;
- selected brand layer nếu branch có brand.

Evaluation SHA nay bao gồm:

```text
config SHA + retrieval dataset SHA + effective alias artifact SHA
```

Evalkit được bump từ `evalkit-10` lên `evalkit-11`. CLI `--brands` nay hỗ trợ rõ `0`, `1`, `off`, `full`, `a6`. Quyết định được ghi tại [ADR 0012](../adr/0012-retrieval-alias-provenance-and-checkpoint-identity.md).

Versioned corpus-only run:

| Trường | Giá trị |
|---|---|
| Schema | `evalkit-11` |
| Tag | `retrieval_recovery_v11` |
| Evaluation SHA | `064d5c72466be010` |
| Config SHA | `eb8aba50596f632a` |
| Dataset SHA | `24115a85f684286d` |
| Alias SHA-256 | `d30f594a1f2479e8adf4650bf840038e77482f39f1695850e4708083f0b48da0` |
| Branch | `a6` |

## 4. Kết quả đo Retrieval Evalkit-11

Artifact:

- `artifacts/runs/retrieval/evalkit/ek_retrieval_recovery_v11_064d5c72466be010.jsonl`
- `artifacts/runs/retrieval/evalkit/metrics_retrieval_recovery_v11_064d5c72466be010.json`
- `artifacts/runs/retrieval/evalkit/failures_retrieval_recovery_v11_064d5c72466be010.csv`
- `artifacts/runs/retrieval/evalkit/report_retrieval_recovery_v11_064d5c72466be010.txt`

### 4.1. Coverage và failure buckets

| Chỉ số | Kết quả |
|---|---:|
| Đã chạy | 1.012 |
| Dựng được proxy gold tin cậy | 1.006 (99,4%) |
| Không đo được | 6 |
| Candidate hit S1 | 1.005/1.006 (99,90%) |
| `F1_NO_CANDIDATE` | 1 |
| `F2_HARD_FILTER_DROP` | 0 |
| `F3_RANK_MISS` ngoài top-10 | 87 |
| `F4_RERANK_MISS` | 0 |
| `F5_SUCCESS` trong top-10 | 918 |

Q464 là trường hợp `F1_NO_CANDIDATE` duy nhất của table retrieval, thuộc mode `screen_open`, với proxy phrase `hàng tồn kho giảm`. Đây là bằng chứng S1 chưa hỗ trợ open-universe screen, không phải lý do để nới entity/year/basis constraint.

### 4.2. Ranking metrics

| Metric | Kết quả |
|---|---:|
| Hit@1 | 0,7217 |
| Hit@10 | 0,9125 |
| MRR@10 | 0,7792 |
| Recall@10 | 0,5839 |
| F2@10 | 0,4754 |
| F2@N* theo policy thật | 0,2384 |
| Hit@N* theo policy thật | 0,7664 |
| Slice `|gold|=1` F2@1 | 0,5645 |

Proxy gold có median 8 bảng/câu nên F2@N* không được đọc như dự báo absolute score. Candidate hit và failure buckets phù hợp hơn để đánh giá regression retrieval trong gói này.

## 5. Full-corpus Semantic V3 A/B

Hai run dùng cùng code tree, active A6, alias branch và `operand_k=20`; run đối chứng thay matcher bằng implementation legacy trong process chẩn đoán.

- Baseline: `artifacts/runs/semantic-v3/retrieval-recovery-legacy-ab-20260828/`.
- Candidate: `artifacts/runs/semantic-v3/retrieval-recovery-v2-pre-gates-20260828/`.

### 5.1. Outcome delta

- 22 QID chuyển từ non-OK sang `OK`:
  `12, 67, 72, 86, 96, 168, 179, 213, 221, 249, 289, 344, 410, 460, 506, 592, 651, 778, 852, 878, 954, 967`.
- 4 QID chuyển từ `OK` sang conservative abstain:
  `147, 153, 320, 995`.
- Net gain: `+18 OK`.
- 3 QID vẫn `OK` nhưng đổi answer/evidence:
  `66, 190, 601`.

Bảy QID old-only/answer-delta trên không nằm trong sealed promotion gold hiện có. Vì vậy không dùng kết quả này để tuyên bố answer accuracy tăng. Các trường hợp answer drift được công khai thay vì che bằng tie-break quá mạnh; promotion vẫn bị chặn chờ semantic/evidence/answer adjudication.

### 5.2. Terminal bottlenecks sau nâng cấp

| Reason family | Số câu |
|---|---:|
| `METRIC_UNRESOLVED` | 198 |
| `REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION` | 150 |
| `BINDING_TIE` | 102 |
| `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED` | 40 |
| `SELECT_AT_ARG_RANK_EXPRESSION_UNRESOLVED` | 20 |
| `DIMENSION_MISMATCH:money:percent` | 16 |
| `UNREVIEWED_RELATIONAL_FORMULA` | 15 |

Nút thắt chính sau retrieval recovery tiếp tục là parser/ontology, reported-derived policy và binding calibration, đúng chẩn đoán của handoff.

## 6. Regression Q464/Q508/Q586/Q783/Q792

Các test integration khóa boundary hiện tại, không giả vờ các câu đã được giải hoàn toàn:

| QID | Retrieval recovery đạt được | Boundary còn lại |
|---:|---|---|
| 464 | Failure được đo riêng; Evalkit xác định `screen_open` S1 empty | `SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED`; cần open-universe screen + CFO/net revenue role/formula |
| 508 | Đủ `ACB/OCB/STB`, không còn mất STB ở entity resolution | `METRIC_REJECT_ALL` cho metric được parser chọn; thiếu top-M selected/rank metric roles, không thể sửa bằng alias entity |
| 586 | ACV resolve đúng | Reported metric chưa được review cho growth operation |
| 783 | MBB/EIB resolve đúng và giữ hướng `MBB - EIB` | `BINDING_TIE` trên total assets |
| 792 | EIB/MBB resolve đúng | Reported metric chưa được review cho derived comparison |

## 7. Verification và gates

### 7.1. Gates đạt

| Gate | Kết quả |
|---|---|
| Targeted retrieval/fact/binder/eval tests | `100 passed` |
| P0 identity/QID/integration subset | `22 passed` |
| `make snapshots-verify` | PASS toàn bộ raw → A6 → retrieval lineage |
| `make ci` | Ruff PASS; mypy PASS 84 source files; docs 48 files/0 broken links; `2070 passed, 42 skipped, 26 deselected` |
| Retrieval-related integration không phụ thuộc H0 legacy package | `4 passed` |
| `make semantic-coverage` | `684/1.012` eligible, đúng reviewed baseline |
| `tools/attest_brands.py --kiem` | `68/77`, exit 0 |
| `git diff --check` | PASS trước khi lập báo cáo |

### 7.2. Full integration blocker không thuộc retrieval change

`make test-integration` cho kết quả `15 passed, 11 failed`. Cả 11 failure đều nằm trong `tests/integration/test_h0_gates.py` và do thiếu materialized legacy artifacts:

- `artifacts/submissions/legacy/submission_P0G2.zip`;
- `artifacts/submissions/legacy/submission_C1R_LOCAL.zip`;
- `artifacts/execution/h0/unit_conflict_adjudication.jsonl`;
- `artifacts/execution/h0/determinism_report_v2.json`.

Đã chạy target chuẩn `make materialize-h0`; target này cũng dừng ngay vì thiếu baseline đầu vào `submission_P0G2.zip`. Không sửa test, không tạo artifact giả và không nới gate. Đây là pre-existing artifact dependency cần được phục hồi từ nguồn phát hành legacy trước khi full integration có thể xanh.

## 8. Danh sách file thay đổi

### Production/config

- `configs/retrieval/company_brand_attested_v1.yaml`
- `configs/retrieval/company_question_attested_v1.yaml`
- `src/text2pandas/application/binding/binder.py`
- `src/text2pandas/application/retrieval/contracts.py`
- `src/text2pandas/infrastructure/retrieval/__init__.py`
- `src/text2pandas/infrastructure/retrieval/fact_label.py`
- `src/text2pandas/infrastructure/retrieval/operand.py`
- `src/text2pandas/interface/cli/main.py`
- `src/text2pandas/pipelines/retrieval/alias_store.py`
- `src/text2pandas/pipelines/retrieval/policy.py`
- `src/text2pandas/pipelines/retrieval/submission_adapter.py`
- `src/text2pandas/pipelines/retrieval/evalkit/__init__.py`
- `src/text2pandas/pipelines/retrieval/evalkit/cli.py`
- `src/text2pandas/pipelines/retrieval/evalkit/report.py`
- `src/text2pandas/pipelines/retrieval/evalkit/runner.py`
- `tools/attest_brands.py`
- `tools/rewrite_submission.py`

### Tests/docs

- `tests/test_p0_unify.py`
- `tests/test_retrieval_recovery_p0.py`
- `tests/unit/test_fact_label_v3.py`
- `tests/unit/test_operand_retrieval_v3.py`
- `tests/unit/test_planning_and_joint_binding_v3.py`
- `tests/integration/test_retrieval_recovery_qids.py`
- `docs/adr/0012-retrieval-alias-provenance-and-checkpoint-identity.md`
- `docs/reports/RETRIEVAL_RECOVERY_IMPLEMENTATION_REPORT_2026-08-28.md`

## 9. Phần chưa làm và lý do

Các mục sau được giữ lại có chủ đích vì cần review/gold hoặc thay đổi kiến trúc lớn hơn phạm vi an toàn của một recovery patch:

1. **Top-M metric-role hypotheses** cho `filter`, `rank`, `selected`, `numerator`, `denominator`. Parser hiện vẫn có 198 `METRIC_UNRESOLVED` và Q508 cho thấy chọn một mention cuối là chưa đủ.
2. **Review reported-derived metrics**. Q586/Q792 bị chặn đúng policy; không tự cho phép derived operation trên reported metric chưa adjudicate.
3. **Binding calibration theo operation family**. Q783 và 102 `BINDING_TIE` cần labeled binding set để chọn threshold/margin, không nên hard-code theo vài ví dụ.
4. **Wiring V2 table rank thành soft prior trong V3 run**. API và trace đã có; cần một contract chuyển ranked table IDs theo từng operand scope. Hiện chưa có source rank list trong `shadow-v3` command.
5. **Open-universe screen retrieval**. Q464 cần candidate-universe semantics và hai metric roles; không thể chữa bằng tăng top-K.
6. **Neural challenger**. Chỉ nên triển khai sau deterministic baseline, held-out labels, checksum-bound model và A/B gate.

## 10. Kết luận

Gói này hoàn thành phần retrieval recovery có thể kiểm chứng ngay: entity resolution có provenance, fact normalization tất định, candidate identity đầy đủ hơn, failure reason rõ, hard/soft table constraints tách biệt, policy N thống nhất và eval checkpoint không còn tái sử dụng khi alias bytes thay đổi.

Kết quả đo cho thấy cải thiện thực về coverage (`269 → 287 OK`, `201 → 165 METRIC_REJECT_ALL operand requests`) trong khi snapshot lineage, offline CI và retrieval integration vẫn ổn định. Tuy nhiên Semantic V3 chưa được promotion vì answer/evidence accuracy cho các outcome drift chưa có sealed gold và full H0 integration đang thiếu artifact legacy đầu vào. Bước tiếp theo đúng thứ tự là parser/metric roles → reported-derived adjudication → binding calibration → soft-prior wiring; không phải tăng top-K hay đưa neural reranker vào default ngay.
