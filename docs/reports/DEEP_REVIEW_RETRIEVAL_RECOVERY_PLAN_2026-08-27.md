# Deep Review — Retrieval Candidate and Operand Grounding Recovery Plan

**Ngày review:** 2026-08-27  
**Plan được review:** `/Users/andinh307/Downloads/183_RETRIEVAL_CANDIDATE_AND_OPERAND_GROUNDING_RECOVERY_PLAN.md`  
**Project:** `text2pandas`  
**Phạm vi:** Retrieval V2, Semantic V3, entity/metric resolution, operand retrieval, joint binding, evaluation, gold, model challengers và submission grounding.

## Executive Verdict

**Không nên triển khai plan nguyên văn.** Nên giữ định hướng kiến trúc, nhưng phải viết lại thứ tự ưu tiên và loại bỏ các kết luận chưa có bằng chứng.

Verdict phù hợp nhất là:

> **APPROVE WITH MAJOR REVISION** — triển khai ngay phần deterministic P0/P1; chưa phê duyệt dense retrieval, cross-encoder, multi-vector hoặc Qwen vào production.

Lý do chính: plan cho rằng Retrieval có “hai lỗi độc lập: candidate recall và operand grounding”. Hai lỗi này có thật, nhưng không phải toàn bộ root cause. Chạy trực tiếp V3 hiện tại trên đủ 1.012 câu cho kết quả:

| Kết quả V3 | Số câu |
|---|---:|
| OK | 269 |
| ABSTAIN | 743 |
| Fail ở PARSE | 492 |
| Fail ở BIND | 217 |
| Fail ở TYPED_EXECUTE | 34 |

Như vậy, **parser/metric linking là bottleneck lớn nhất**, xảy ra trước candidate retrieval và operand binding. Trong 217 lỗi binding, xấp xỉ 108 là `AMBIGUOUS_BINDING`, 106 là `NO_CANDIDATES`, chỉ 3 là `NO_COHERENT_ASSIGNMENT`.

Phạm vi kiểm chứng của review:

- Đọc toàn bộ plan 1.279 dòng.
- Kiểm tra code V2/V3, config, snapshot, ontology, gold registry và promotion policy.
- Chạy lại full-corpus V3 trên active A6.
- Chạy 97 test semantic planning, retrieval, joint binding, `SELECT_AT_ARG`, filtered extrema, entity resolution và trace: **97/97 pass**.
- Không thay đổi source code hoặc artifact của pipeline.

## 1. Các vấn đề được xác nhận

| Claim trong plan | Kết luận và bằng chứng | Root cause thực | Impact | Mức độ / confidence |
|---|---|---|---|---|
| Alias entity có thể làm mất gold từ S1 | **TRUE.** `tools/attest_brands.py` dùng `yaml.safe_dump(...).strip()` bên trong inline YAML. 68 alias brand đang có literal ` ...`. | Serialization artifact bị coi là nội dung alias. | Q586 tụt từ rank 5/6 xuống 25/29 trong V2 canonical. | **P0 / High** |
| Alias entity còn thiếu hoặc sai | **TRUE.** STB không có “Sài Gòn Thương Tín”; alias hiện có “Sài Gòn Tài Lộc”. Eximbank không được ánh xạ trong các case tương ứng. | Question-attested alias coverage thiếu; một alias canonical sai nội dung. | Q508 thiếu STB; Q783/Q792 chỉ resolve MBB. | **P0 / High** |
| V2 hard-filter có thể xóa gold trước ranking | **TRUE.** V2 dùng entity/year/retrieval-ready trong S1. Trên answer-gold31, giữ 114/116 gold tables; hai bảng mất đều thuộc Q508. | Entity resolution là hard gate quá sớm. | Candidate complete chỉ 30/31 dù individual recall là 98,3%. | **P0 / High** |
| Rank bảng V2 chưa truyền vào V3 | **TRUE.** Shadow CLI mở A6 trực tiếp và khởi tạo `SqliteOperandRetriever` không có table prior. | Hai retrieval path chưa có contract tích hợp. | V2 ranking signal bị bỏ phí; V3 quét observation độc lập. | **P1 / High** |
| `allowed_table_uids` có nguy cơ thành hard whitelist | **TRUE, thậm chí API hiện đang trộn hai nghĩa.** Khi có danh sách này, retriever vừa thêm `IN (...)` hard filter, vừa dùng rank làm bonus. | Candidate restriction và ranking prior dùng chung một tham số. | Không thể thêm soft prior đúng nghĩa nếu không đổi API. | **P1 / High** |
| Candidate metric được chép từ request | **TRUE.** Candidate luôn nhận `metric_id=request.metric_id`. | Candidate không lưu identity độc lập của row/metric source. | Trace có thể tự xác nhận hypothesis ban đầu thay vì chứng minh nó. | **P1 / High** |
| Hierarchy của row chưa được dùng đầy đủ để xác nhận metric | **TRUE một phần.** Scoring dùng row/column/section context, nhưng `_metric_match` chỉ match leaf sau dấu `›`. | Match metric và contextual constraint bị tách quá mạnh. | Dễ nhầm total/detail hoặc metric cùng leaf khác parent. | **P1 / High** |
| Parser có xu hướng lấy mention cuối | **TRUE trong `_base_expression`.** Code dùng `mentions[-1]`. | Default composition chưa biểu diễn uncertainty/top-M. | Gây sai base metric ở câu nhiều metric. | **P1 / High** |
| Binder thiếu confidence gate | **TRUE có điều kiện.** Binder đã tính winner margin, nhưng chỉ abstain khi điểm bằng nhau và assignment khác nghĩa. | Margin đã được quan sát nhưng chưa calibrate thành policy. | Candidate “thắng sát nút” vẫn có thể được trả lời. | **P1 / High** |
| Gold không đủ để promotion | **TRUE và nghiêm trọng hơn plan mô tả.** Answer usable 31, semantic usable 6, evidence usable 0; tất cả có `promotion_eligible_records: 0`. | Thiếu independent dual annotation và ordered operand evidence. | Không đo được parser EM, binding EM hoặc answer accuracy production-grade. | **P0 / High** |
| Top-K là vấn đề ranking, không chỉ recall | **TRUE.** Current manual95: candidate 95/95, H1 33/95, H10 85/95, H20 90/95, H50 92/95. | Gold thường tồn tại nhưng xếp thấp; final table policy làm mất thêm. | Final any-hit với cap 20 chỉ 50/95. | **P1 / High** |
| V2/V3 phải giữ final evidence grounding | **TRUE.** V2 thành công đã thay final refs bằng đúng evidence tables. | Đây là invariant đúng cần giữ. | Tránh tối ưu internal top-K nhưng làm hỏng `relevant_tables/docs`. | **P0 invariant / High** |

## 2. Root cause plan đang hiểu chưa đúng hoặc chưa đủ

### 2.1 “Hai lỗi độc lập” là framing thiếu

Plan cần chuyển từ hai lớp sang ít nhất bốn lớp:

```text
Entity/scope resolution
        ↓
Semantic parse + metric/formula linking
        ↓
Operand candidate generation
        ↓
Joint binding + execution + final grounding
```

Dữ liệu full-corpus cho thấy parser chiếm 492/743 abstentions, tương đương 66,2% số abstain. Vì vậy candidate và operand không thể là hai root cause duy nhất.

### 2.2 Candidate recall V2 không phải bottleneck lớn nhất trên manual95

Manual95 hiện có candidate hit 95/95. Vấn đề lớn hơn là:

- Rank quality: H10 chỉ 85/95.
- Final output policy: cap/ước lượng số bảng làm any-hit còn 50/95.
- Slice không chứa Q464/Q508/Q783/Q792 nên không đại diện cho entity/open-universe P0.

Do đó không nên dùng `95/95` để kết luận candidate generation đã tốt toàn hệ, nhưng cũng không nên nói V2 candidate recall nói chung đang “vỡ”.

### 2.3 Q464 không chỉ là open-universe failure

V2 Q464 có S1=0, nhưng V3 hiện fail ở:

```text
SELECT_AT_ARG_SELECTED_EXPRESSION_UNRESOLVED
```

Nghĩa là thêm open-universe candidate path chưa đủ. Parser phải xác định được:

- Trục rank.
- Metric dùng để rank.
- Metric/value cần trả về tại argmax/argmin.

### 2.4 Q508 không chỉ là thiếu alias STB

Q508 có ít nhất ba lỗi:

- Entity set thiếu STB.
- AST hiện compile thành aggregate không đúng cấu trúc select-at-arg.
- ACB không có candidate phù hợp cho reported metric; 1.348 observation được scan nhưng đều bị metric reject.

Sửa alias chỉ phục hồi một phần.

### 2.5 Q586 là lỗi V2, không phải root cause V3 hiện tại

V3 resolve ACV đúng, sau đó abstain vì:

```text
REPORTED_METRIC_REQUIRES_REVIEW_FOR_DERIVED_OPERATION
```

Vì vậy plan phải tách rõ:

- Alias serialization fix cứu V2 rank.
- Ontology review/formula safety mới cứu V3 end-to-end.

### 2.6 “V2 answering chủ yếu là một generic lexical selector” là quá đơn giản

Canonical V2 có nhiều specialized path: entity count, difference, average, sum, count periods và reviewed formula.

Generic router đúng là có defect: DIVIDE tạo numerator và denominator cùng một `metric_id`. Nhưng canonical formula path đã bypass nhiều trường hợp đó. Plan cần ghi rõ phạm vi lỗi, nếu không sẽ thiết kế lại phần đã có route chuyên biệt.

### 2.7 `OperandRequest.metric_id` đơn không tự nó là lỗi

Một concrete operand request nên có đúng một metric. Top-M uncertainty nên được biểu diễn thành:

- Nhiều `MetricHypothesis`.
- Fan-out thành nhiều request/candidate batch.
- Joint search chọn hypothesis + evidence.

Không nên biến `OperandRequest.metric_id` thành một list mơ hồ rồi đẩy uncertainty vào mọi tầng.

## 3. Những phần plan coi là chưa có nhưng thực tế đã được giải quyết

Các hạng mục này không nên được lập lại như greenfield Phase R2:

1. **Typed semantic AST đã tồn tại**, gồm `Filter`, `Rank`, `SelectAtArg`.
2. **Planner đã tạo request per metric leaf × entity × period**.
3. **Metric trong filter predicate đã được thu thập riêng**.
4. **Rank metric và selected metric đã là hai expression khác nhau** qua `SelectAtArg`.
5. **Joint binder đã tồn tại**, dùng beam search, hard constraints và global assignment.
6. **Score margin đã được tính và trace**, chỉ còn thiếu calibration/policy.
7. **Typed execution, independent Pandas replay và evidence UID grounding đã có.**
8. **V3 shadow/V2 canonical strangler migration đã là quyết định chính thức**, không cần tái thiết kế.
9. Bộ test liên quan đang pass: **97/97**.

R2 nên đổi tên thành:

> “Audit semantic contracts, fill unsupported constructions, and build promotion gold”

thay vì “thiết kế slot schema từ đầu”.

## 4. Những kết luận hiện chưa đủ bằng chứng

| Kết luận | Trạng thái |
|---|---|
| Candidate recall toàn hệ đạt yêu cầu | **NOT MEASURED.** Manual95 không chứa các P0 case quan trọng. |
| `CompleteEvidenceRecall@K` đạt ≥0,90 | **NOT MEASURED.** Evidence gold usable hiện bằng 0. |
| Binding exact ≥0,90 | **NOT MEASURED.** Không có promotion-eligible ordered operand gold. |
| Answer accuracy ≥0,80 | **NOT MEASURED.** V2 diagnostic mới 14/31; V3 chỉ trả 6/31 trên slice đó. |
| Qwen 14B là “model chính đã được chấp nhận” | **FALSE/UNVERIFIED.** Model registry đang null; config Qwen có endpoint rỗng và revision `unknown`. |
| BGE reranker là challenger tốt nhất cho project | **UNVERIFIED.** Chưa có weights/revision/manifest hoặc benchmark local. |
| Dense/multivector có ROI dương | **UNVERIFIED.** Chưa chứng minh lexical gap là nguyên nhân chính của miss hiện tại. |
| Open-universe cứu được Q464 | **UNVERIFIED.** Q464 hiện parse fail trước retrieval. |
| Threshold 0,95/0,90 trong R3/R4 đủ cho production | **Không phù hợp với policy hiện tại.** Candidate recall locked gate là 0,99. |
| 150 answer/binding gold là đủ | **Không phù hợp.** Policy hiện khóa tối thiểu 300 cho answer, semantic và evidence. |
| Không được serialize abstain thành `0.0` | **FALSE ở submission boundary.** Contract yêu cầu đủ mọi ID; code cố ý dùng `0.0` làm placeholder. Nội bộ vẫn phân biệt `answer=None/status=ABSTAIN`. |

Các paper được chọn nhìn chung hỗ trợ đúng pattern kiến trúc: tách evidence khỏi program trong [FinQA](https://aclanthology.org/2021.emnlp-main.300/) và [TAT-QA](https://aclanthology.org/2021.acl-long.254/), giữ hierarchy trong [MultiHiertt](https://aclanthology.org/2022.acl-long.454/), dùng relational linking trong [RAT-SQL](https://aclanthology.org/2020.acl-main.677/), hoặc fusion bằng [RRF](https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf). Tuy nhiên, chúng **không chứng minh** BGE, ColBERT hay Qwen sẽ có ROI dương trên corpus này.

[BGE-M3](https://arxiv.org/abs/2402.03216), [ColBERTv2](https://arxiv.org/abs/2112.01488), [APOLLO](https://aclanthology.org/2024.lrec-main.122/) và [PICARD](https://aclanthology.org/2021.emnlp-main.779/) chỉ nên được dùng làm nguồn thiết kế challenger/constraint.

Claim “FinQA từng có lỗi serialization leakage” chưa có source chính xác trong plan; nên bỏ hoặc bổ sung evidence cụ thể.

## 5. Những thiếu sót quan trọng của plan

1. **Không đặt source integrity thành Gate 0.** Git object pack hiện bị hỏng; `git status` không thể hoàn thành đáng tin cậy. Hàm source identity sẽ im lặng trả `git_commit=None`, `git_dirty=None` khi Git lỗi. Không nên chạy A/B promotion khi source identity chưa xác định.

2. **Không xử lý config drift của output policy.** Canonical function mặc định 10 bảng, CLI thực tế mặc định 20, trong khi submission adapter/eval report vẫn khóa `MAX_N=10`.

3. **Không đưa full-corpus stage funnel vào executive diagnosis.** Con số 492 parse fail phải là dữ liệu đầu tiên để ưu tiên roadmap.

4. **Không phân biệt rõ `NO_CANDIDATES` với `AMBIGUOUS_BINDING`.** Hai nhánh cần fix hoàn toàn khác nhau.

5. **Không ghi nhận V3 semantic stack hiện có**, dẫn tới trùng effort R2.

6. **Ontology/status documentation đang drift.** Runtime hiện load 368 metrics: 28 reviewed + 340 reported, và 28 formulas; status doc vẫn ghi 24/346/24.

7. **EvidenceCard chưa phản ánh sparsity của source identity.** A6 có `row_uid` và `metric_code`, nhưng chỉ khoảng 355.485/2.634.120 observations có `metric_code` không rỗng, khoảng 13,5%. `source_metric_id` phải nullable và không được coi là canonical ground truth.

8. **Không có regression tests trực tiếp cho Q464/Q508/Q586/Q783/Q792.**

9. **Run artifacts được tài liệu tham chiếu không phải lúc nào cũng có trong checkout.** Plan cần gate “artifact exists + SHA verified”, không chỉ ghi path trong report.

10. **Không tách internal abstention khỏi submission placeholder.** Đây là hai contract khác nhau.

## 6. Các fix nên giữ nguyên về hướng đi

| Fix | Đánh giá |
|---|---|
| Giữ V2 canonical và V3 shadow | **KEEP.** Rủi ro thấp, phù hợp promotion policy. |
| Sửa alias serialization và bổ sung question-attested alias có provenance | **KEEP, P0.** ROI rất cao, complexity thấp. |
| Tách `source_metric_id` khỏi `matched_metric_id` | **KEEP.** Chữa circular self-confirmation trong candidate trace. |
| EvidenceCard chứa row path, column path, section, table/document/entity/period/basis/unit | **KEEP.** Hỗ trợ audit và hierarchy-aware ranking. |
| V2 table rank chỉ là soft prior | **KEEP.** Nhưng phải sửa API như phần 7. |
| Progressive relaxation có điều kiện | **KEEP.** Explicit entity/year/basis không được silently relax. |
| Hierarchical row/metric representation | **KEEP.** Tập trung trước vào lexical/SQL hierarchy, chưa cần dense. |
| Per-stage trace và failure taxonomy | **KEEP, nâng thành P0.** |
| `CompleteEvidenceRecall@K`, per-slot recall, binding EM, risk–coverage | **KEEP.** Đây là đúng metric family. |
| Joint assignment với hard semantic constraints | **KEEP.** V3 đã có nền tảng. |
| A/B từng thay đổi một | **KEEP.** Đặc biệt cần thiết trước model experiments. |
| Đo delta trên final submission fields | **KEEP.** Không chỉ đo internal shortlist. |

## 7. Các fix cần chỉnh sửa trước khi triển khai

| Đề xuất hiện tại | Cách sửa đề xuất | Lý do |
|---|---|---|
| `MetricHypothesis` top-M rồi để request mang nhiều khả năng | Giữ request đơn-metric; fan-out top-M thành nhiều hypothesis/request có provenance. | Giữ contract rõ ràng và binder dễ kiểm chứng. |
| `allowed_table_uids` + V2 soft prior | Tách thành `hard_allowed_table_uids` và `table_rank_priors`. Shadow mặc định chỉ truyền prior. | API hiện biến prior thành whitelist. |
| Quota entity × slot ở mọi nơi | V3 đã retrieve riêng theo request; quota chỉ cần ở pool chung, open-universe hoặc khi metric hypotheses cạnh tranh. | Tránh complexity không tạo lift. |
| Chạy toàn bộ exact/SQL/BM25/char/dense/sparse/multivector rồi union | Bắt đầu exact/SQL/BM25/char; chỉ kích hoạt model channel cho failure slice đã chứng minh lexical gap. | Giảm latency, noise và không che root cause parser. |
| Open-universe như một retrieval rescue độc lập | Chỉ chạy sau khi AST xác định được axis, rank expression và selected expression; domain phải bounded/precomputed. | Q464 hiện fail trước retrieval. |
| BGE reranker top 50–100 | Chỉ thử sau khi có ≥100 held-out labeled pools và candidate recall đã ổn. | Nếu candidate thiếu hoặc parser sai, reranker không giúp. |
| Binder threshold chung | Calibrate riêng lookup, arithmetic, multi-entity, rank/filter và open-universe; báo risk–coverage. | Distribution score khác nhau mạnh giữa operation families. |
| `ANSWER/RETRY_BROADER/ABSTAIN` | Giữ ba trạng thái nội bộ; retry chỉ relax trường không explicit, có budget và trace. Submission vẫn serialize placeholder theo contract. | Tránh rescue vô hạn hoặc silently đổi nghĩa câu hỏi. |
| EvidenceCard dùng `source_metric_id` | Đổi thành `source_metric_code: Optional`, `matched_metric_id`, `match_method`, `match_features`, `source_identity_confidence`. | `metric_code` A6 quá sparse để là canonical identity. |
| Gold “300 retrieval/linking + 150 answer/binding” | Dùng locked policy: **300 semantic + 300 evidence + 300 answer** từ cùng sealed release. | Không hạ gate hiện hữu. |
| R3/R4 gate 0,95 | Giữ 0,95 làm diagnostic milestone nếu muốn; promotion candidate recall vẫn 0,99. | Tránh hai định nghĩa “pass production”. |
| Qwen constrained rerank/composition | Để thành optional P3 challenger; cần pinned revision, offline manifest, latency và held-out lift. | Hiện chưa có model production hợp lệ. |

## 8. Những phần nên bỏ khỏi plan

1. **Bỏ câu “Qwen 14B được chấp nhận làm model chính”.** Hiện không có bằng chứng runtime, revision hay model manifest.
2. **Bỏ BGE dense/sparse/multivector khỏi mandatory production cascade.** Chuyển thành experiments có stop condition.
3. **Bỏ Phase R2 dưới dạng xây semantic slot/AST từ đầu.** Thay bằng audit và gap closure trên implementation hiện có.
4. **Bỏ rule “ABSTAIN không được serialize thành `answer=0.0`”.** Thay bằng internal `status=ABSTAIN`, `answer=None`; submission dùng `answer=0.0` placeholder nếu official contract yêu cầu đủ record.
5. **Bỏ ngưỡng 150 answer/binding gold.** Nó làm yếu policy khóa sẵn.
6. **Bỏ claim FinQA leakage nếu không bổ sung source chính xác.**
7. **Bỏ ý tưởng chạy tất cả retrieval channels trước khi có failure attribution.**
8. **Bỏ giả định Q508 chỉ cần alias và Q464 chỉ cần open-universe.**

## 9. Bottleneck thực sự theo thứ tự hiện tại

| Hạng | Bottleneck | Bằng chứng | Hướng xử lý |
|---:|---|---|---|
| 1 | Parser/metric/formula linking | 492/1.012 fail ở PARSE; riêng `METRIC_UNRESOLVED=198`, reported-derived block=149 | Ontology coverage, metric hypotheses, operation composition, regression QIDs |
| 2 | Binding ambiguity | 108 `AMBIGUOUS_BINDING` | Better evidence identity, hard constraints, calibrated margin |
| 3 | Operand no-candidate | Khoảng 106 binding failures | Hierarchical lexical retrieval, source identity, scoped relaxation |
| 4 | V2 ranking/final table policy | H10 85/95; final cap20 any-hit 50/95 | Rank features, per-entity protection, unify N policy |
| 5 | Entity resolution P0 | Q508/Q783/Q792; alias serialization ảnh hưởng Q586 | Fix artifact và curated aliases |
| 6 | Typed execution gaps | 34 câu | Handle sau khi correct AST/evidence đã sẵn sàng |
| 7 | Neural retrieval/reranking | Chưa chứng minh là bottleneck | Conditional A/B only |

## 10. Thứ tự ưu tiên mới

### P0 — Reproducibility và measurement integrity

1. Sửa/khôi phục Git source identity.
2. Khóa một active snapshot duy nhất:
   - Raw `ca033190f2e9e99f`
   - A6 `c6887fb633374fad`
   - Retrieval `872ccb0dda9a2bb6`
3. Đồng bộ `MAX_N`, CLI defaults, eval config và final output policy.
4. Yêu cầu mọi report trỏ tới artifact tồn tại và SHA kiểm được.
5. Sinh full-corpus failure funnel theo stage/reason.

### P0 — Entity regressions

6. Sửa YAML alias serialization.
7. Review alias STB/EIB/MBB/ACV từ nguồn được phép.
8. Thêm direct regression tests Q464/Q508/Q586/Q783/Q792.
9. Đo lại entity exact set, S1 gold retention và final F2.

### P0 — Gold

10. Hoàn tất sealed 300-record common release cho semantic, ordered evidence và answer.
11. Không train/calibrate trên held-out packet.
12. Không tuyên bố production lift trước khi promotion-eligible count lớn hơn 0.

### P1 — Parser và ontology

13. Xử lý 198 `METRIC_UNRESOLVED`.
14. Review/promote reported metric families đang chặn 149 derived questions.
15. Thay last-mention fallback bằng top-M hypothesis có span/role provenance.
16. Hoàn thiện các AST gap thực tế qua failure slices, không viết lại AST.

### P1 — Candidate contract

17. Thêm `row_uid`, nullable `source_metric_code`, match provenance.
18. Tách V2 prior khỏi hard whitelist.
19. Dùng full row/column/section hierarchy trong metric match.
20. Thêm scoped relaxation và conditional open-universe.

### P1 — Binding

21. Calibrate winner score/margin theo operation family.
22. Đo `CompleteEvidenceRecall`, `BindingExactMatch`, swap rate và constraint violations.
23. Chỉ retry broader khi constraint bị relax không phải explicit.

### P2/P3 — Model challengers

24. BM25/char/hierarchy ablation trước.
25. BGE dense/RRF sau khi chứng minh lexical gap.
26. Cross-encoder sau khi có labeled pool.
27. Qwen chỉ là challenger cuối cùng.

## 11. Hướng kiến trúc nên dùng

```text
Question
  → Entity/scope resolver
  → AST + top-M metric hypotheses
  → one concrete OperandRequest per hypothesis × entity × period
  → deterministic observation channels
      exact / metric-code / fielded BM25 / char hierarchy
  → optional neural channels, only when enabled by experiment
  → union + dedupe + explainable feature vector
  → joint hypothesis/evidence binding
  → calibrated ANSWER | RETRY_BROADER | ABSTAIN
  → typed execution + Pandas replay
  → final evidence-derived tables/docs
  → submission adapter
```

Các invariant bắt buộc:

- Candidate không tự xác nhận metric chỉ vì request đã mang metric đó.
- Explicit entity/year/basis là hard constraint.
- V2 rank không bao giờ tạo hard ceiling cho V3 recall.
- Mỗi answer phải trace ngược tới exact observation UIDs.
- Internal abstention không bị lẫn với numeric zero.
- Không model nào được production-enable nếu thiếu revision/hash/license/latency/held-out lift.

## 12. Final Verdict

**Có nên triển khai?** Có, nhưng chỉ sau khi viết lại plan theo thứ tự trên.

### Giữ lại

- V2 canonical/V3 shadow.
- Per-operand candidate generation.
- Hierarchical evidence cards.
- Independent source-vs-matched metric identity.
- Soft V2 prior.
- Progressive relaxation.
- Joint binding, calibrated abstention.
- Sealed gold, oracle ladder, ablation và final-field evaluation.

### Phải thay đổi

- Thay framing “hai lỗi” bằng pipeline bốn lớp.
- Đưa parser/ontology lên trước hybrid retrieval.
- Đổi R2 từ xây mới sang audit/gap closure.
- Tách table prior khỏi whitelist.
- Dùng locked 300/300/300 gold policy.
- Tách internal ABSTAIN khỏi submission placeholder.
- Đặt source integrity/config consistency thành Gate 0.

### Loại bỏ hoặc hoãn

- Qwen là model chính.
- BGE/ColBERT/multivector trong default cascade.
- Cross-encoder trước khi có held-out pool.
- Open-universe trước khi semantic parse thành công.
- Các threshold tùy ý thấp hơn promotion policy.
- Các claim từ paper không có project-local evidence.

### Thứ tự triển khai cuối cùng

> Source integrity → measurement/gold → alias/entity regressions → parser/ontology → candidate identity/hierarchy → calibrated binder → lexical ablation → dense/reranker → optional Qwen.

Ở trạng thái hiện tại, triển khai nguyên plan có rủi ro tiêu phần lớn effort vào dense/reranking trong khi bottleneck lớn nhất vẫn là parser/metric linking và hệ thống chưa có gold đủ điều kiện để chứng minh improvement.

## Appendix A — Evidence Map

Các vị trí code/config chính được dùng trong review:

- `tools/attest_brands.py:109` — cách serialize alias gây literal `...`.
- `src/text2pandas/application/usecases/canonical_run.py:529-543` — answer pool và V2 retrieval adapter.
- `src/text2pandas/application/usecases/canonical_run.py:607-691` — các specialized answer routes.
- `src/text2pandas/application/usecases/canonical_run.py:695-727` — final evidence grounding và abstention.
- `src/text2pandas/interface/cli/main.py:670-680` — V3 shadow mở trực tiếp A6, chưa truyền V2 rank.
- `src/text2pandas/interface/cli/main.py:843-844` — CLI mặc định 20/50 bảng.
- `src/text2pandas/pipelines/retrieval/submission_adapter.py:35-55` — `MAX_N=10`.
- `src/text2pandas/application/parsing/parser.py:168-198` — last-mention base expression.
- `src/text2pandas/application/planning/planner.py:129-173` — request per leaf/entity/period và filter/rank/select collection.
- `src/text2pandas/infrastructure/retrieval/operand.py:34-106` — SQL candidate generation.
- `src/text2pandas/infrastructure/retrieval/operand.py:203-216` — upstream table prior và copied metric identity.
- `src/text2pandas/infrastructure/retrieval/operand.py:231-259` — leaf-only metric match.
- `src/text2pandas/application/binding/binder.py:67-99` — global winner và margin.
- `src/text2pandas/application/usecases/submission.py:95-108` — submission placeholder `0.0`.
- `configs/evaluation/gold_registry_v1.yaml` — promotion-eligible gold bằng 0.
- `configs/semantic/promotion_policy_v3.yaml` — locked 300/300/300 promotion policy.
- `configs/models.yaml` — production model registry chưa có model.
- `configs/answer_v2/llm_v1.yaml` — Qwen endpoint rỗng, revision chưa pin.
- `docs/SEMANTIC_V3_MIGRATION_STATUS.md` — V3 shadow status và promotion blockers.

