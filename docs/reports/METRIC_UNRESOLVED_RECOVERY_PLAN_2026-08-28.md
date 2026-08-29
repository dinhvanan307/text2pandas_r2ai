# Kế hoạch xử lý duy nhất `METRIC_UNRESOLVED` — Semantic V3

**Ngày audit:** 2026-08-28

**Phạm vi:** chỉ lỗi `METRIC_UNRESOLVED` của Semantic V3

**Trạng thái:** CONDITIONALLY READY — chỉ được bắt đầu Phase 1 sau khi Phase 0 seal được baseline sạch, môi trường và reviewer protocol

**Loại tài liệu:** kế hoạch triển khai dựa trên bằng chứng; tài liệu này không triển khai hay thay đổi production code

**Review đã hợp nhất:** `docs/reports/PLAN_REVIEW_METRIC_UNRESOLVED_2026-08-28.md`; disposition từng mục ở Appendix C

## 1. Problem statement

Ở baseline Semantic V3 hiện tại, full corpus có:

| Kết quả | Số lượng |
|---|---:|
| `OK` | 287 |
| Abstain tổng cộng | 725 |
| `METRIC_UNRESOLVED` | 198 |
| Tổng câu hỏi | 1.012 |

Toàn bộ 198 trường hợp `METRIC_UNRESOLVED` kết thúc ở stage `PARSE`. Trace của cả 198 đều có `formula_id=null` và `metric_ids=[]`. Vì vậy, lỗi đang xét không phải lỗi top-K retrieval, binding hay execution: pipeline chưa tạo được `MetricRef`, chưa tạo `OperandRequest`, và chưa gọi candidate retrieval.

Mục tiêu của thay đổi là tách riêng rồi xử lý có kiểm soát ba khái niệm hiện đang bị trộn:

1. cụm từ metric xuất hiện trong câu hỏi;
2. metric canonical hoặc hàng nguồn A6 mà cụm từ đó có thể ánh xạ tới;
3. vai trò của metric trong biểu thức, ví dụ rank key, selected value, filter predicate, numerator hay denominator.

Thay đổi phải fail closed khi không đủ bằng chứng. Giảm số lượng `METRIC_UNRESOLVED` chỉ là một chỉ số coverage; không được xem là bằng chứng correctness hay điều kiện tự động promote V3.

## 2. Evidence from repo

### 2.1 Reference baseline và baseline sạch bắt buộc

| Thành phần | Identity / artifact |
|---|---|
| Raw snapshot | `ca033190f2e9e99f` |
| Active A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| A6 silver DB | `data/processed/a6/c6887fb633374fad/silver.db` |
| V3 records | `artifacts/runs/semantic-v3/retrieval-recovery-v2-pre-gates-20260828/records.jsonl` |
| V3 manifest | `artifacts/runs/semantic-v3/retrieval-recovery-v2-pre-gates-20260828/manifest.json` |
| Retrieval eval | `artifacts/runs/retrieval/evalkit/ek_retrieval_recovery_v11_064d5c72466be010.jsonl` |
| Ontology fingerprint | `f45411be42f4e55413d31416b6b120115a6f52952a56f160051dd3eef97aae7c` |
| Source commit được manifest ghi | `193dab480a60f4ffbd0c6e112e0975ba8427e7ec` |
| Source cleanliness | `git_dirty=true` |
| Reference runtime | `47.676 s` (xấp xỉ 47,7 giây, không phải 47.676 giây theo cách viết hàng nghìn) |

Artifact này là **reference baseline** dùng để xác định cohort lịch sử H198 và các bằng chứng trong Mục 2–4. Nó không đủ điều kiện làm acceptance baseline vì source tree đã bẩn. Các con số 287/725/198 vì thế là con số tham chiếu đã đo, chưa phải baseline tái lập cuối cùng.

Trước khi sửa production code, Phase 0 phải tạo baseline B0 mới trong một clean worktree tách biệt, từ một commit được chỉ định rõ. Không commit/stash hay làm sạch cưỡng bức workspace hiện tại của người dùng. B0 manifest bắt buộc chứa:

- `git_commit` khác `null` và `git_dirty=false`;
- SHA-256 của questions, ontology, resolver-disabled config và cohort file;
- raw/A6/retrieval identities ở bảng trên;
- OS/build, CPU architecture, Python executable/version, dependency-lock checksum;
- cold/warm run protocol và wall-clock từng lần chạy.

Current tracked HEAD tại thời điểm bổ sung plan là `b0d7b84ec0a97ccaec274ae47c4c6d29cd421982`; git hoạt động và không có tracked diff, nhưng workspace có các tài liệu untracked nên vẫn không dùng trực tiếp làm clean release worktree. Commit này đã chứa bản sửa serialization alias bằng whole-mapping `yaml.safe_dump`, file `configs/retrieval/company_brand_attested_v1.yaml` không còn literal `...`, và `tests/test_retrieval_recovery_p0.py` đã có invariant tương ứng. Reference commit `193dab4…` chưa có bản sửa đó. Do đó:

1. không triển khai lại alias fix trong plan này;
2. selected B0 commit phải chứa alias fix và invariant phải pass;
3. B0 phải chạy lại sau precondition alias, không được tái sử dụng artifact dirty cũ;
4. nếu B0 không tái hiện 287 `OK` và H198 đúng 198 câu, dừng trước Phase 1 và cập nhật lại denominator/các gate trong tài liệu này; không được tự điều chỉnh gate sau khi đã thấy kết quả implementation.

H198 luôn được giữ như frozen diagnostic cohort từ artifact cũ. Zero-drift và acceptance chính thức dùng B0 sạch; mọi báo cáo phải trình bày cả H198 và cohort B0 nếu chúng khác nhau.

### 2.2 Luồng code thực tế

Semantic V3 hiện chạy theo chuỗi:

`SemanticParser` → `compile_execution_plan` → `retrieve_operands` → binder → typed execution → pandas compile/replay.

Bằng chứng chính:

- `src/text2pandas/application/usecases/semantic_v3.py`: parse failure trả kết quả ngay ở stage `PARSE`, trước planning/retrieval/binding.
- `src/text2pandas/application/parsing/parser.py:129`: `_base_expression()` trả `None` dẫn tới `METRIC_UNRESOLVED`.
- `src/text2pandas/application/parsing/parser.py:168`: `_base_expression()` yêu cầu ít nhất một `MetricMention`.
- `src/text2pandas/application/parsing/parser.py:185`: metric mặc định được lấy bằng `mentions[-1]`.
- `src/text2pandas/application/parsing/parser.py:380`: `_metric_mentions()` vừa dò literal alias vừa trả metric canonical; không có bước độc lập để giữ surface/span chưa ánh xạ.
- `src/text2pandas/application/planning/planner.py:45`: planner chỉ tạo request sau khi đã có `MetricRef` và yêu cầu `metric_id` tồn tại trong ontology hiện tại.
- `src/text2pandas/infrastructure/retrieval/operand.py:85`: `UNKNOWN_METRIC` chỉ có thể xuất hiện sau planning.
- `src/text2pandas/infrastructure/retrieval/operand.py:146`: `METRIC_REJECT_ALL` chỉ có thể xuất hiện sau khi đã scan candidate.

Kết luận: 198 lỗi hiện tại bị chặn trước tất cả các nhánh retrieval/binding nói trên.

### 2.3 Ontology và nguồn A6

Ontology đang load từ `configs/semantic/ontology_v3.yaml`, gồm:

- 368 metrics: 28 reviewed, 340 reported-derived từ registry;
- 28 formulas;
- 376 metric aliases và 65 formula aliases;
- reported branch chỉ lấy tập nhãn phổ biến giới hạn từ A6 registry và lọc bỏ các hàng structural/generic.

Cùng một alias set hiện được dùng để nhận diện ngôn ngữ câu hỏi và để match hàng nguồn. Hai nhiệm vụ này không tương đương: câu hỏi có thể dùng diễn đạt đầy đủ, viết tắt khác, từ đồng nghĩa, hoặc chỉ nhắc ý nghĩa nằm trong hierarchy của bảng.

Ví dụ có bằng chứng trực tiếp:

| QID | Câu hỏi / hành vi hiện tại | Bằng chứng A6 | Kết luận |
|---|---|---|---|
| Q5 | “Chi phí phạt … SCR 2017”; parser không có metric | Có hàng execution-ready `Chi phí phạt`, row path `Chi phí khác › Chi phí phạt`, bảng `ade6cad33d7ef1fa` | metric nguồn tồn tại nhưng không có alias ontology tương ứng |
| Q15 | “Thù lao … Chu Thị Bình”; parser không có metric | Leaf label là `Chu Thị Bình`, còn ý nghĩa “thù lao” nằm ở hierarchy/table context, bảng `2a570eb1e1c4143c` | không thể chỉ dùng flat row label; phải giữ surface và hierarchy evidence |
| Q89 | “Chi phí thuế thu nhập hiện hành”; parser không có metric | A6 có `Chi phí thuế TNDN hiện hành`, source metric code `51`, bảng `93e24eaeeeb156a0`; metric này đã có trong reported ontology | alias/paraphrase gap, không phải thiếu dữ liệu hay thiếu metric registry |
| Q100 | “Tổng số lượng cổ phần … BVH 2018”; không có phrase proxy duy nhất | Có nhiều hàng gần nghĩa: cổ phiếu phổ thông, đang lưu hành, đã bán ra công chúng, đăng ký phát hành | phải abstain với lý do specificity/ambiguity, không ép top-1 |
| Q426 | select-at-arg giữa CFO, LNST và biểu thức được chọn | A6 có chuỗi `Lưu chuyển tiền thuần từ hoạt động kinh doanh` code 20 và `Lợi nhuận sau thuế TNDN` code 60 | có nhiều vai trò nhưng parser dừng trước role resolution |
| Q502 | select-at-arg giữa `Lãi dự thu` và số dư quỹ bình ổn | Cả hai chuỗi hàng tồn tại, execution-ready | compile order chặn `_select_at_arg_roles()` |
| Q870 | count/filter theo lưu chuyển tiền đầu tư | A6 có `Lưu chuyển tiền thuần từ hoạt động đầu tư`, code 30 | cần giữ predicate metric thay vì yêu cầu một base metric mặc định trước |

### 2.4 SSOT và ranh giới legacy

SSOT cần sửa của Semantic V3 là:

- AST: `src/text2pandas/domain/semantic/ast.py`;
- parser: `src/text2pandas/application/parsing/parser.py` và contracts cùng package;
- planner: `src/text2pandas/application/planning/`;
- ontology entrypoint: `configs/semantic/ontology_v3.yaml`;
- composition root: `src/text2pandas/interface/cli/main.py`.

V2 lexical behavior đang được V3 gọi qua `src/text2pandas/infrastructure/semantic/legacy_annotator.py`. `src/text2pandas/answer_pipeline/` chỉ là compatibility alias; `tools/answer_v2/` là đường prototype/legacy. Không được triển khai logic Semantic V3 mới trong hai đường này và không được để production import từ `tools/`.

## 3. Root cause

### 3.1 Root cause trực tiếp

`_metric_mentions()` đang gộp hai bước “phát hiện một cụm từ có vẻ là metric” và “ánh xạ cụm từ đó sang ontology metric”. Nó chỉ tạo mention nếu normalized question chứa literal ontology alias. Khi alias không match, parser không giữ lại surface, span hay bất kỳ hypothesis nào; `_base_expression()` nhận tuple rỗng và trả `METRIC_UNRESOLVED`.

### 3.2 Root cause mô hình dữ liệu

`MetricRef` lưu `metric_id` cùng context execution nhưng không lưu:

- surface/span trong câu hỏi;
- cách metric được resolve;
- nhãn hàng nguồn hoặc `source_metric_code` đã hỗ trợ quyết định;
- tập hypothesis và bằng chứng dùng để chọn/abstain.

`OperandRequest` cũng chỉ có `metric_id` và constraints, nên planner/retriever không thể truyền một binding hint nguồn đã được kiểm chứng. Ngược lại, source-specific evidence chỉ xuất hiện ở candidate sau retrieval — quá muộn cho 198 câu hiện bị dừng ở parser.

### 3.3 Root cause về vai trò operand

V3 AST có thể biểu diễn nhiều vai trò qua cấu trúc, ví dụ:

- `SelectAtArg.rank.by`;
- `SelectAtArg.expression`;
- `Filter.predicate`;
- các nhánh trái/phải của arithmetic/formula.

Vì vậy vấn đề không phải AST hoàn toàn “chỉ hỗ trợ một metric”. Vấn đề là parser bắt buộc phải tạo generic base expression trước khi gọi composer theo operation; đồng thời generic base chọn `mentions[-1]`. Với Q426/Q502, không có recognized mention nên role resolver không bao giờ được gọi. Với Q508, operation/return mode và clause grammar khiến parser xây sai vai trò dù entity đã đúng.

### 3.4 Những gì không phải root cause của 198 trường hợp

- Không phải retrieval top-K: cả 198 chưa gọi retrieval.
- Không phải binder threshold/tie: chưa có `OperandRequest` hay candidate batch.
- Không phải `reported-derived` gate: chưa tới gate đó.
- Không có bằng chứng rằng A6 thiếu dữ liệu cho 198 câu. Có 197/198 câu có ít nhất một scoped row-label proxy; Q100 có dữ liệu gần nghĩa nhưng chưa đủ specificity để chọn duy nhất.

## 4. Failure taxonomy của 198 trường hợp

### 4.1 Phân loại theo stage quan sát được

| Nhóm | Số lượng | Diễn giải |
|---|---:|---|
| Parser không tạo được metric/formula mention | 198 | Quan sát trực tiếp: `stage_failed=PARSE`, `metric_ids=[]`, `formula_id=null` |
| Đã tạo `MetricRef` nhưng planner thất bại | 0 | Không có trường hợp nào trong cohort 198 đi tới đây |
| Có `OperandRequest` nhưng candidate rỗng/bị reject | 0 | Không có trường hợp nào trong cohort 198 đi tới retrieval |
| Binding ambiguity/tie quan sát được | 0 | Không đi tới binder |
| Reported-derived rejection quan sát được | 0 | Không đi tới gate này |

Số 0 ở các hàng sau không chứng minh hệ thống không có ambiguity hay candidate rejection; nó chỉ chứng minh trace hiện tại đã làm mất cơ hội quan sát các trạng thái đó.

### 4.2 Phân loại theo operation/return mode

| Operation / return mode | Số lượng |
|---|---:|
| lookup / value | 117 |
| subtract / value | 26 |
| extremum / value | 15 |
| extremum / member | 6 |
| extremum / select-at-arg | 2 |
| average / value | 14 |
| growth / value | 10 |
| divide / value | 4 |
| count / value | 3 |
| sum / value | 1 |
| **Tổng** | **198** |

Ít nhất 9 câu có cấu trúc đa vai trò quan sát được ngay từ operation: 4 divide, 2 select-at-arg và 3 count/filter. Đây là lower bound, không phải nhãn semantic gold cho toàn bộ cohort.

### 4.3 Phân loại theo bằng chứng surface từ retrieval eval

Phân loại này dùng matching proxy trên A6, không phải semantic gold:

| Tier bằng chứng | Số lượng | Tỷ lệ | Ý nghĩa |
|---|---:|---:|---|
| T1: row n-gram liên tiếp, dài ít nhất 3 token | 124 | 62,63% | bằng chứng surface mạnh |
| T2: row bigram | 55 | 27,78% | bằng chứng vừa; dễ va chạm hơn |
| T3: token-AND, không có phrase chặt | 18 | 9,09% | nguy cơ ambiguity/hierarchy cao |
| Không có phrase proxy duy nhất | 1 | 0,51% | Q100; cần abstain specificity |
| **Tổng** | **198** | **100%** | |

197/198 có surface proxy trong scope A6. Điều này đủ để bác bỏ giả thuyết “198 câu đều thiếu dữ liệu nguồn”, nhưng không đủ để tự động chọn đúng operand hay tự động promote câu trả lời.

### 4.4 Taxonomy nguyên nhân cần ghi trong diagnostic mới

Mỗi QID phải nhận đúng một terminal diagnostic chính, kèm các evidence phụ:

1. `ENTITY_SCOPE_UNAVAILABLE`: câu hỏi cần entity-scoped resolution nhưng entity không resolve được hoặc alias scope không đáng tin; không được ghi nhầm thành lỗi metric.
2. `QUESTION_MENTION_NOT_EXTRACTED`: không tìm được metric-like surface dù đã chạy extractor độc lập.
3. `QUESTION_MENTION_NO_MAPPING`: có surface nhưng không có ontology hay source-backed hypothesis đủ ngưỡng.
4. `METRIC_HYPOTHESES_AMBIGUOUS`: có nhiều hypothesis không phân giải được an toàn.
5. `METRIC_SOURCE_SPECIFICITY_REQUIRED`: dữ liệu gần nghĩa tồn tại nhưng câu hỏi không nói rõ biến thể cần chọn, như Q100.
6. `OPERAND_ROLE_UNRESOLVED`: có các metric hypothesis nhưng không gán được vai trò trong expression.
7. `OPERAND_ROLE_CONFLICT`: cùng một span bị gán cho các role không tương thích hoặc role bắt buộc trùng ngoài quy tắc cho phép.
8. `SOURCE_BINDING_HINT_REJECTED`: parser/planner đã tạo source-backed reference nhưng retrieval không tìm được candidate thỏa matcher/constraints.
9. `METRIC_UNRESOLVED`: chỉ giữ làm umbrella external reason khi chưa có diagnostic chi tiết; không được dùng để che các nhánh trên trong artifact audit.

`ENTITY_SCOPE_UNAVAILABLE` được báo riêng trong tổng H198/B0 và bị loại khỏi mẫu tính precision/recall riêng của metric resolver, vì resolver chưa có cơ hội hoạt động trong scope đúng. Việc loại khỏi denominator chuyên biệt không được làm biến mất QID khỏi full-corpus totals.

## 5. Proposed minimal architecture

### 5.1 Nguyên tắc

- Giữ nguyên đường exact/formula/ontology hiện tại cho mọi câu đã parse thành công.
- Chỉ kích hoạt resolver fallback khi parser hiện tại không có formula và không có metric mention đủ để compose.
- Tách question mention, metric resolution và source binding.
- Dùng AST position làm SSOT cho role; không thêm một `role` enum dư thừa vào `MetricRef`.
- Deterministic, versioned, fail closed; không thêm neural model hay reranker.
- Không biến source-backed metric thành reviewed/canonical derived metric.
- Chỉ chạy entity-scoped source resolution khi entity scope đã resolve và vượt invariant alias; nếu không, trả `ENTITY_SCOPE_UNAVAILABLE` trước metric resolver.

### 5.2 Contracts mới

Thêm các value object bất biến trong application parsing contracts:

`QuestionMetricMention`

- `mention_id` ổn định trong một câu;
- `start`, `end` trên normalized question;
- `surface`, `normalized_surface`;
- `extraction_method` và evidence tối thiểu.

`MetricHypothesis`

- `metric_id` nếu ánh xạ được vào ontology;
- optional source binding hint gồm normalized source labels, source metric codes và hierarchy terms;
- `match_method`, deterministic score và evidence;
- scope đã dùng để tạo hypothesis: entity, period, basis, statement type nếu có.

`MetricResolutionResult`

- mention đầu vào;
- danh sách hypothesis đã xếp theo deterministic tuple;
- `selected` chỉ khi thắng duy nhất qua threshold/margin;
- terminal reason khi unresolved/ambiguous.

Không đưa toàn bộ top-M hypothesis vào AST. Parser trace/diagnostic giữ tập hypothesis; AST chỉ chứa lựa chọn duy nhất cùng provenance tối thiểu cần cho planning/replay.

### 5.3 Resolver fallback trên A6 immutable

Thêm một application protocol `MetricMentionResolver`, và adapter hạ tầng `A6MetricMentionResolver` đọc active A6 ở chế độ read-only.

Thứ tự matching đề xuất:

1. exact/fact-normalized ontology alias;
2. exact/fact-normalized A6 leaf label hoặc source metric label trong entity/period/basis scope;
3. abbreviation/paraphrase rule được version hóa, ví dụ `thu nhập doanh nghiệp` ↔ `TNDN`;
4. bounded n-gram trên leaf/path/hierarchy;
5. token/hierarchy conjunction chỉ dùng để tạo hypothesis, không được tự thắng nếu không có margin an toàn.

Tie-break phải là tuple xác định, không phụ thuộc thứ tự SQLite: match class, span coverage, scope match, hierarchy consistency, source code consistency, normalized label, stable id. Nếu hai hypothesis còn đồng hạng semantic, resolver trả ambiguity thay vì chọn theo thứ tự.

Mỗi abbreviation/paraphrase rule trong YAML phải có `rule_id`, ít nhất một evidence QID, ít nhất một negative example, scope áp dụng và lý do. Loader từ chối rule thiếu evidence/negative example; không cho phép rule tự do tích lũy không có test.

Phase đầu không tạo hay sửa A6 artifact. Resolver dùng cùng immutable SQLite connection, prepared statements, query có scope và cache theo khóa versioned. Nếu Phase 2 vượt performance trigger ở Mục 9.3 sau khi tối ưu các cơ chế này, materialized semantic label index trở thành **contingency được phép ngay trong Phase 2**, không còn là DEFER. Index phải là derived artifact mới dưới `data/indexes/semantic/<a6_build_id>/<resolution_index_id>/`, có manifest, source A6 checksum, resolver/config fingerprint và không thay đổi active retrieval index.

### 5.4 Source binding hint

Mở rộng `MetricRef` bằng optional `resolution`/`binding_hint` có default `None`. Hint chỉ chứa identity logic, không chứa physical table id:

- question surface/span;
- resolution method/version;
- canonical `metric_id` nếu có;
- normalized source labels;
- source metric codes;
- hierarchy terms cần thiết;
- source build identity.

Mở rộng `OperandRequest` bằng hint tương ứng. Planner chấp nhận đúng hai loại:

1. canonical metric: phải tồn tại trong ontology như hiện nay;
2. source-backed metric: phải có binding hint hợp lệ, source build đúng, cùng unit/statement constraints cần thiết; thiếu các điều kiện này thì fail closed bằng planning reason có tên.

Retriever ưu tiên đường ontology hiện tại khi hint không có. Khi hint có, retriever match trên source label/code/hierarchy trong scope và vẫn áp dụng toàn bộ entity, period, basis, unit, table quality và execution-readiness gates hiện tại.

### 5.5 Compose theo role trước generic base

Refactor parser thành thứ tự:

1. annotate operation/entity/period/basis;
2. extract tất cả question metric mentions độc lập;
3. resolve hypothesis cho từng mention;
4. nếu operation có grammar nhiều vai trò, compose role-specific AST trước;
5. chỉ dùng generic base cho operation thực sự một metric;
6. nếu thiếu hoặc mâu thuẫn role, abstain bằng reason có tên.

Xóa việc dùng `mentions[-1]` làm quyết định canonical. Có thể giữ deterministic last/longest behavior chỉ trong compatibility path exact hiện tại nếu cần bảo toàn B0 baseline, nhưng fallback mới không được dựa vào thứ tự mention đơn thuần. Compatibility exception phải có comment trỏ tới decision trong plan này để tránh bị “dọn” ngoài một phép đo A/B có kiểm soát.

### 5.6 Boundary Q508

Q508 không nằm trong 198 `METRIC_UNRESOLVED`; nó là regression boundary bắt buộc vì cho thấy entity resolution đúng nhưng role/metric sai:

- hiện parser tạo `maximum(lãi thuần từ hoạt động khác)`;
- ý định cần rank theo `chi phí chờ phân bổ` rồi chọn một metric khác;
- ACB không có candidate cho metric đang bị chọn, nên cuối cùng là `METRIC_REJECT_ALL`.

Sửa ở đường V3 adapter/parser, không sửa shared canonical V2 frame. Grammar phải tổng quát hóa clause kiểu `ngân hàng có`, không hard-code QID hay ticker. Acceptance của Q508 là AST đúng vai trò hoặc abstain role-specific; không bắt buộc `OK` nếu A6 không đủ selected value cho entity thắng.

### 5.7 Giữ nguyên ranh giới reported-derived

Source-backed lookup resolution chỉ cấp quyền bind tới observed row. Nó không cấp quyền thực hiện arithmetic/derived semantic chưa được review. Divide, growth, subtract và các biểu thức nhiều operand vẫn phải đi qua formula/operation policy hiện hữu. Không được dùng resolver này để nới reported-derived gate.

## 6. Exact files/modules

### 6.1 MUST change/add

| File | Thay đổi dự kiến |
|---|---|
| `src/text2pandas/application/parsing/contracts.py` | thêm mention/hypothesis/resolution contracts và resolver protocol |
| `src/text2pandas/application/parsing/parser.py` | tách extraction khỏi mapping, fallback có inject resolver, compose role-specific trước generic base, bỏ canonical `mentions[-1]` ở đường mới; ghi rõ compatibility exception cho exact path |
| `src/text2pandas/domain/semantic/ast.py` | thêm optional, serializable source-resolution provenance vào `MetricRef`; giữ AST path làm role SSOT |
| `src/text2pandas/application/planning/contracts.py` | thêm optional source binding hint vào `OperandRequest` |
| `src/text2pandas/application/planning/planner.py` | compile canonical hoặc validated source-backed ref; fail closed nếu thiếu contract |
| `src/text2pandas/infrastructure/semantic/a6_metric_resolver.py` | adapter mới, deterministic, read-only trên active A6 |
| `src/text2pandas/infrastructure/semantic/__init__.py` | export adapter mới theo convention package |
| `src/text2pandas/infrastructure/semantic/legacy_annotator.py` | V3-only correction cho return mode/clause signals cần thiết; không đổi canonical V2 behavior |
| `src/text2pandas/infrastructure/retrieval/operand.py` | nhận source binding hint và match label/code/hierarchy trước các gates hiện có |
| `src/text2pandas/interface/cli/main.py` | wire resolver bằng active immutable A6 connection và fingerprint config |
| `configs/semantic/metric_resolution_v1.yaml` | version, enable flag, match classes, thresholds, margin, max hypotheses, cache limits |
| `configs/semantic/ontology_v3.yaml` | chỉ thêm identity/reference tới resolution config nếu composition-root convention yêu cầu |
| `tools/diagnose_metric_unresolved_v3.py` | tool read-only tạo artifact taxonomy/evidence; production không import tool này |

Nếu manifest hiện tại không tự thu fingerprint của resolution config, cập nhật đúng composition path trong `src/text2pandas/application/usecases/run_manifest.py` hoặc module manifest thực tế được CLI dùng. Chỉ thêm file này sau khi xác nhận bằng test rằng identity chưa được ghi tự động.

Không sửa `tools/attest_brands.py` hoặc `configs/retrieval/company_brand_attested_v1.yaml` trong workstream này: serialization defect mà review nêu đã được sửa ở tracked HEAD hiện tại. Phase 0 chỉ xác nhận selected clean commit chứa fix và chạy invariant hiện hữu; nếu precondition fail, block plan và mở một upstream change riêng.

### 6.2 MUST test

| File | Coverage |
|---|---|
| `tests/unit/test_semantic_parser_v3.py` | exact path không drift; fallback; ambiguity; role composition; Q426/Q502/Q508/Q870 |
| `tests/unit/test_semantic_ast_v3.py` | round-trip schema cũ/mới và optional provenance |
| `tests/unit/test_planning_and_joint_binding_v3.py` | consumer paths/roles, canonical vs source-backed request, fail-closed invalid hint |
| `tests/unit/test_operand_retrieval_v3.py` | label/code/hierarchy match, wrong build id, scope/unit rejection, no gate bypass |
| `tests/unit/test_a6_metric_resolver.py` | deterministic ranking, abbreviation, hierarchy, ambiguity, cache isolation |
| `tests/unit/test_metric_resolution_config.py` | mọi paraphrase rule có evidence QID, negative example, scope và stable id |
| `tests/unit/test_v2_lexical_no_drift.py` | hash output `classify_operation` + `parse_intent` trên 1.012 câu không đổi qua mọi phase |
| `tests/integration/test_retrieval_recovery_qids.py` | Q5, Q15, Q89, Q100, Q426, Q502, Q870 và Q508 boundary |
| full-corpus A/B artifact test | 1.012 câu với exact baseline identity và drift report |

Phase 2 contingency, chỉ tạo nếu performance trigger nổ:

| File / artifact | Mục đích |
|---|---|
| `src/text2pandas/infrastructure/semantic/a6_metric_index.py` | reader/builder contract cho semantic label index immutable |
| `tools/build_metric_resolution_index_v3.py` | build tool; production không import từ `tools/` |
| `data/indexes/semantic/<a6_build_id>/<resolution_index_id>/manifest.json` | seal source checksum, schema, config và index checksum |

### 6.3 MUST NOT change

- `data/raw/**`, `data/processed/**` và active snapshot pointers;
- retrieval top-K, table prior, candidate scoring hiện tại ngoài việc nhận binding hint có type rõ ràng;
- binder threshold/calibration;
- promotion policy hoặc gold gate;
- canonical V2 composition trong `src/text2pandas/pipelines/answering/**`;
- `src/text2pandas/answer_pipeline/**`;
- `tools/answer_v2/**`;
- reported-derived adjudication;
- các lỗi `BINDING_TIE`, reported-derived hoặc non-executable ngoài cohort, trừ việc quan sát chúng như terminal reason mới sau khi 198 câu đi xa hơn.
- alias/entity lexicon hoặc alias generation; chúng là precondition/dependency đã được kiểm riêng, không phải target sửa của plan này.

## 7. Data/schema implications

### 7.1 Dữ liệu

- Không mutate raw, processed A6, retrieval index hay source tables.
- Mọi query của resolver chạy read-only và bị bind vào `a6_build_id=c6887fb633374fad` trong phép đo baseline.
- Cache chỉ là derived runtime state; cache key phải chứa resolver version, A6 build id và normalized scope.
- Không ghi source table id vào semantic AST vì đó là physical execution detail dễ thay đổi.
- Nếu performance contingency được kích hoạt, chỉ tạo một immutable semantic index mới; không overwrite A6, retrieval index hoặc pointer active. Index được xóa/không dùng bằng config rollback mà không ảnh hưởng source data.

### 7.2 Schema

- Các field mới trên `MetricRef` và `OperandRequest` là optional với default `None`, để artifact V3 cũ vẫn deserialize được.
- Không bump semantic AST major version chỉ vì thêm optional provenance. Thêm `metric_resolution_schema_version=1` và config fingerprint vào run manifest.
- Source-backed identity phải stable và namespaced, ví dụ hash của normalized logical matcher contract; không dùng Python hash, row ordinal hay SQLite return order.
- Parser trace mới phải ghi `mention_span`, `surface`, `hypothesis_count`, selected method, ambiguity margin và role path. Không ghi full database row payload vào trace.
- Nếu selected hypothesis không có canonical ontology metric, planner phải có đủ expected-unit/statement constraints hoặc trả reason riêng; tuyệt đối không ngầm tạo một ontology metric global.

### 7.3 Tương thích

- Exact ontology/formula path phải chạy trước fallback và giữ serialization hiện tại khi không dùng fallback.
- V2 không nhận schema hay behavior mới.
- CLI/API output chỉ thêm trace/provenance theo kiểu additive; consumers hiện tại không được buộc phải hiểu field mới để đọc status/answer cũ.
- QID thiếu entity scope được ghi `ENTITY_SCOPE_UNAVAILABLE`; metric hypothesis không được query toàn corpus như một cách lách scope.

## 8. Test strategy

### 8.1 Unit tests

1. Extractor giữ đúng surface/span cho câu có dấu, không dấu, viết tắt và punctuation.
2. Resolver ưu tiên exact ontology; fallback không được override một exact reviewed metric.
3. Q89 resolve được `thuế thu nhập doanh nghiệp` ↔ `thuế TNDN` bằng rule versioned.
4. Q15 dùng hierarchy evidence nhưng không biến tên người thành metric semantic global.
5. Q100 trả specificity/ambiguity, không chọn arbitrary share row.
6. Ties không bị phá bằng SQLite order hoặc `mentions[-1]`.
7. Select-at-arg tạo hai role khác nhau; filter/count giữ predicate path.
8. Source build mismatch, missing unit/context hoặc invalid matcher đều fail closed.
9. Source-backed request vẫn bị unit, period, basis, statement type và execution-readiness gates chặn như canonical request.
10. Old AST/plan fixtures round-trip không drift.
11. Missing/untrusted entity scope trả `ENTITY_SCOPE_UNAVAILABLE` và không chạy unscoped A6 fallback.
12. Mỗi paraphrase rule có positive evidence QID và negative example; negative example không tạo hypothesis thắng.
13. Alias invariant hiện hữu không có literal `...` phải pass trên selected B0 commit.

### 8.2 Targeted integration tests

| QID | Gate chính |
|---|---|
| Q5 | rời parse unresolved; plan chứa source-backed `Chi phí phạt`; candidate phải giữ đúng hierarchy |
| Q15 | surface/hierarchy được giữ; chỉ `OK` nếu person row và thù lao context cùng thỏa; nếu không thì abstain có tên |
| Q89 | map paraphrase sang metric/source code 51 mà không thay canonical exact behavior |
| Q100 | `METRIC_SOURCE_SPECIFICITY_REQUIRED` hoặc ambiguity; không `OK` |
| Q426 | AST có rank expression, positivity filter và selected expression riêng; không generic base shortcut |
| Q502 | rank/selected roles khác nhau và được planner giữ qua consumer paths |
| Q870 | count/filter predicate metric được plan; không dừng vì thiếu generic base |
| Q508 | không còn AST `maximum(lãi thuần từ hoạt động khác)`; phải là select-at-arg đúng vai trò hoặc role-specific abstain |

### 8.3 Regression tests trên B0 `OK`

Chạy exact A/B trên cùng input và so sánh tối thiểu:

- status;
- normalized answer/value/member;
- query/execution plan serialization;
- selected evidence/candidate identity;
- replay result và mismatch flags.

Gate là zero drift trên toàn bộ B0 `OK`, không chỉ giữ nguyên tổng đếm. Nếu B0 tái hiện reference baseline, denominator kỳ vọng là 287. Nếu fallback thay đổi một câu đã parse thành công, thiết kế activation order bị vi phạm.

Ngoài V3 A/B, Phase 0 phải materialize hash output của `classify_operation` và `parse_intent` trên toàn bộ 1.012 câu. Hash này phải bất biến qua mọi phase. Đây là guard chống việc “tiện tay” thay shared V2 lexical behavior trong khi sửa `legacy_annotator.py` hoặc parser V3.

### 8.4 Full corpus và offline checks

- targeted unit/integration trước;
- `make typecheck`;
- `make test-offline`;
- full-corpus 1.012 câu với artifact mới, manifest đầy đủ và diff report;
- replay toàn bộ new `OK`;
- reviewer adjudication theo Mục 8.5;
- cold run một lần và warm run ba lần trên cùng máy đo đã seal.

Không cần rerun retrieval top-K benchmark nếu implementation chỉ thêm source binding hint và giữ candidate scorer. Nếu retriever scoring/order bị thay đổi ngoài exact matcher constraint, retrieval benchmark trở thành bắt buộc.

### 8.5 Reviewer protocol

Review sử dụng `configs/evaluation/independent_gold_protocol_v1.yaml` làm policy SSOT:

- tối thiểu hai annotator độc lập;
- một adjudicator khác hai annotator;
- blind model outputs và bắt buộc kiểm source evidence;
- reviewer IDs/roles phải được ghi trong sealed manifest trước Phase 1; không ghi tên tự do vào labels.

Queue iteration đầu:

1. nếu new `OK ≤ 60`, review 100%; nếu lớn hơn 60, chọn deterministic 60 câu bằng SHA-256 seed `metric-unresolved-new-ok-v1`;
2. luôn thêm mọi new `OK` thuộc T3, mọi role-sensitive Q426/Q502/Q508/Q870 và mọi unsafe/replay discrepancy, kể cả vượt cap;
3. review riêng toàn bộ 18 T3 và Q100 cho taxonomy/specificity; phần này không tự biến chúng thành promotion gold;
4. dossier chỉ chứa câu hỏi và source evidence cần thiết, không hiển thị system answer trước khi annotator khóa nhãn độc lập.

Nếu chưa bố trí đủ hai annotator và adjudicator, engineering diagnostic có thể tiếp tục nhưng artifact phải ghi `single-reviewer` hoặc `unreviewed`, mọi new `OK` là `NON_PROMOTABLE`, và acceptance về correctness/promotion chưa đạt.

## 9. Measurement plan

### 9.1 Funnel cần ghi cho H198 và B0

Mỗi run phải báo các số riêng cho frozen H198 và, nếu khác, cohort unresolved của B0; không gộp thành “recovered”:

1. còn `METRIC_UNRESOLVED` ở parse;
2. có mention nhưng ambiguity/specificity;
3. tạo được AST;
4. tạo được execution plan;
5. có ít nhất một non-empty candidate batch cho mọi required operand;
6. tới binder;
7. terminal ở binding/execution/replay với reason cụ thể;
8. new `OK`;
9. new `OK` qua reviewer adjudication.

### 9.2 Báo cáo theo tier và operation

Breakdown phải có T1/T2/T3/Q100 và operation table ở Mục 4. Không được chỉ báo một tổng số; nếu coverage chủ yếu đến từ T3 fuzzy matching thì rủi ro cao hơn coverage đến từ T1 exact source labels.

### 9.3 Chỉ số an toàn và hiệu năng

- zero `OK → non-OK` trong B0 `OK` cohort;
- zero answer/query/evidence drift trong B0 `OK` cohort;
- zero unsafe emission và zero replay mismatch mới;
- reference `47.676 s` chỉ là số lịch sử, không dùng làm gate vì artifact dirty và chưa seal máy đo;
- trên máy B0 đã seal: một cold full-corpus run và từng warm run đều phải `≤120.0 s`; median của ba warm run phải `≤90.0 s`;
- cumulative resolver fallback time phải `≤45.0 s` trên full corpus; ghi riêng thời gian extractor, DB lookup và hypothesis ranking;
- ghi peak RSS và số query/cache hit của resolver;
- deterministic rerun: hai run cùng manifest phải có records và resolution traces giống nhau, trừ timestamp/path được chuẩn hóa.

Performance contingency được kích hoạt nếu direct-SQLite implementation, sau prepared statements và bounded cache, có cold run `>120.0 s` hoặc warm median `>90.0 s`. Khi đó Phase 2 được phép build semantic label index ở Mục 5.3 rồi đo lại. Nếu indexed implementation vẫn vượt gate, implementation bị block/rollback; không nới ngân sách sau khi đã xem kết quả.

### 9.4 Diagnostic artifact

Tool audit tạo một run directory immutable mới, tối thiểu có:

- `manifest.json`;
- `cohort_h198.jsonl` và SHA-256 của file;
- `records.jsonl` cho H198 và mapping sang B0 cohort;
- `summary.json` theo taxonomy/tier/operation;
- `drift_b0_ok.json`;
- `v2_lexical_snapshot.jsonl` cùng SHA-256;
- `performance.json` chứa machine/runtime/RSS/query/cache metrics;
- `review_queue.jsonl` cho ambiguous và new `OK`.

Không overwrite baseline artifact.

## 10. Expected impact

### 10.1 Mục tiêu định lượng cho iteration đầu

Nếu clean B0 tái hiện reference counts, vì T1 có 124 câu với surface evidence mạnh, gate triển khai được đặt như sau:

- ít nhất 80/124 T1 rời `METRIC_UNRESOLVED`;
- ít nhất 60/124 T1 tạo execution plan hợp lệ;
- ít nhất 40/124 T1 có non-empty candidate batches cho toàn bộ required operands và tới binder;
- tổng `METRIC_UNRESOLVED` giảm từ 198 xuống không quá 118;
- toàn bộ B0 `OK` — kỳ vọng 287 — giữ zero drift.

Nếu B0 không tái hiện reference counts, Phase 0 phải dừng và phát hành revision của plan với denominator/gate mới trước khi Phase 1 bắt đầu. Không được giữ mẫu số cũ để báo coverage thuận lợi, cũng không được đặt lại gate sau khi resolver đã chạy.

Các câu rời `METRIC_UNRESOLVED` nhưng chuyển thành `METRIC_HYPOTHESES_AMBIGUOUS`, role-specific abstain, `METRIC_REJECT_ALL`, binding tie hay reported-derived rejection phải được báo đúng terminal reason. Không tính chúng là new `OK`.

### 10.2 Kỳ vọng chất lượng

- T1 là vùng chính để lấy coverage an toàn.
- T2 có thể tăng parse/plan coverage nhưng cần margin và scope chặt.
- T3 chủ yếu cải thiện chẩn đoán; không đặt kỳ vọng tự động phát answer.
- Q100 phải giữ abstain.
- Q508 phải sửa hình dạng semantic AST, không hứa trả lời thành công nếu dữ liệu selected expression không đủ.

## 11. Risks

| Rủi ro | Hậu quả | Mitigation |
|---|---|---|
| Source label collision | chọn sai metric nhưng vẫn có candidate | scope theo entity/period/basis, hierarchy evidence, margin và fail-closed ambiguity |
| Overfitting vào QID | benchmark đẹp nhưng không tổng quát | không branch theo QID/ticker; test paraphrase và negative pairs |
| Source-backed metric vượt policy | phát answer derived chưa review | lookup-safe only; giữ formula/reported-derived gates |
| Regression B0 OK | giảm trust của V3 | fallback chỉ sau exact path; byte/semantic zero-drift gate |
| Q15-like leaf/hierarchy confusion | coi entity/person label là metric | mô hình hóa leaf, path, hierarchy riêng; yêu cầu consistency |
| Runtime tăng mạnh | full corpus chậm, khó shadow | scoped queries, prepared statements, bounded cache, absolute runtime gates và Phase 2 index contingency |
| Non-deterministic ranking | kết quả thay đổi giữa run | total-order tuple và stable ids; deterministic rerun test |
| Schema consumers hỏng | artifact cũ/mới không đọc được | optional additive fields, round-trip fixtures |
| Che giấu failure reason | tưởng coverage là correctness | funnel và terminal diagnostic bắt buộc |
| Thay behavior V2 | vi phạm canonical boundary | sửa V3 adapter/parser; explicit V2 regression test |
| Dirty/non-reproducible baseline | A/B không quy về đúng source code | clean isolated worktree, non-null commit, `git_dirty=false`, cohort/config checksums |
| Entity/alias gap | metric resolver bị scope sai rồi mang nhãn lỗi metric | alias invariant là Phase 0 precondition; `ENTITY_SCOPE_UNAVAILABLE`; không chạy unscoped fallback |
| Reviewer không đủ độc lập | new `OK` không có giá trị promotion | hai annotator + adjudicator theo protocol; nếu thiếu thì đóng dấu `NON_PROMOTABLE` |
| Môi trường/disk không ổn định | test/runtime gate sai hoặc không chạy được | ENV-0, disk headroom, paths/snapshot checks, machine/Python seal |
| Opportunity cost của V3 shadow | đạt coverage nhưng không đổi official score | go/no-go sau Phase 2; portability chỉ đánh giá read-only, không mở rộng implementation scope |
| `package-v3` trên lineage hiện tại | có thể crash vì `main.py` yêu cầu `dataframe/csv/table_cards.csv` không có trong A6 build | packaging không thuộc plan; không chạy “tiện tay”; mở work item riêng nếu cần package |

## 12. Rollback plan

1. Mọi fallback được chặn bởi `enabled` trong `configs/semantic/metric_resolution_v1.yaml`.
2. Rollback tức thời: tắt resolver fallback và khởi tạo parser như baseline; canonical exact path phải trở lại nguyên trạng.
3. Không cần rollback data vì không có data mutation hay index activation change.
4. Artifact run mới được giữ nguyên để audit; không xóa hay overwrite baseline.
5. Nếu schema additive gây lỗi consumer, giữ field optional nhưng không emit provenance khi flag tắt.
6. Nếu chỉ một match class gây regression, có thể tắt riêng class đó trong config; không thay threshold runtime không fingerprint.
7. Trigger rollback bắt buộc: bất kỳ drift nào trong B0 OK, V2 lexical hash drift, unsafe emission/replay mismatch mới, nondeterministic rerun, hoặc runtime vượt absolute gate sau contingency.
8. Semantic label index contingency là artifact tách biệt; rollback bằng cách tắt config/reference, không xóa hay mutate A6/retrieval data.

## 13. Acceptance gates

### 13.0 Phase 0 preconditions — trước dòng production code đầu tiên

- [ ] Chạy trong isolated clean worktree; manifest có explicit `git_commit`, `git_dirty=false`.
- [ ] `make paths-check` và `make snapshots-verify` pass; disk headroom, OS/CPU, Python executable/version và lock checksum được seal.
- [ ] Selected commit chứa alias serialization fix; `tests/test_retrieval_recovery_p0.py` và invariant “không literal `...`” pass.
- [ ] B0 resolver-disabled run được seal. Nếu không tái hiện 287/725/H198=198, plan đã được revision và gate mới được đăng ký trước Phase 1.
- [ ] `cohort_h198.jsonl` có đúng 198 unique QID, tier totals 124/55/18/1 và SHA-256 trong manifest.
- [ ] V2 lexical snapshot/hash cho 1.012 câu đã được tạo.
- [ ] Hai annotator độc lập và một adjudicator đã được gán reviewer ID, hoặc run được tuyên bố trước là diagnostic-only/non-promotable.

### 13.1 Correctness gates bắt buộc

- [ ] H198 được tái hiện chính xác và có mapping tường minh sang B0 cohort.
- [ ] Mỗi QID có mention/resolution/role/terminal diagnostic, không còn trace rỗng không giải thích.
- [ ] Toàn bộ B0 `OK` có zero status, answer, query và evidence drift.
- [ ] V2 lexical output hash không đổi.
- [ ] Q5 và Q89 tạo đúng source/canonical binding evidence.
- [ ] Q100 không phát answer và có specificity/ambiguity reason.
- [ ] Q426/Q502 có role-separated AST hoặc abstain role-specific; không generic single-metric AST.
- [ ] Q870 giữ count predicate qua planner consumer path.
- [ ] Q508 không còn bị parse thành flat maximum của selected metric.
- [ ] Source-backed path không bypass unit, period, basis, statement, execution-ready, formula hay reported-derived gates.
- [ ] Entity scope không khả dụng được ghi `ENTITY_SCOPE_UNAVAILABLE`, không chạy unscoped fallback.
- [ ] Tất cả new `OK` replay được và đi vào reviewer queue theo Mục 8.5.
- [ ] New `OK` chỉ được gọi là independently adjudicated/promotable khi policy hai annotator + adjudicator pass; nếu không phải gắn `NON_PROMOTABLE`.

### 13.2 Coverage gates bắt buộc

- [ ] Nếu B0 tái hiện reference: `METRIC_UNRESOLVED ≤ 118` trên cùng 1.012 câu.
- [ ] Ít nhất 80/124 T1 rời parse unresolved.
- [ ] Ít nhất 60/124 T1 tạo plan.
- [ ] Ít nhất 40/124 T1 tới binder với non-empty candidate batches.
- [ ] Báo cáo riêng new `OK`; không dùng số “rời unresolved” thay cho accuracy.
- [ ] Báo riêng `ENTITY_SCOPE_UNAVAILABLE`; không tính các QID này vào resolver-specific denominator.

Nếu B0 không tái hiện reference, toàn bộ bốn threshold tuyệt đối ở trên phải được revision trước Phase 1; không áp dụng mẫu số 124/198 cho một cohort khác.

### 13.3 Engineering gates bắt buộc

- [ ] `make typecheck` pass.
- [ ] `make test-offline` pass.
- [ ] Targeted unit/integration tests pass.
- [ ] Hai rerun cùng manifest cho resolution output deterministic.
- [ ] Cold run và từng warm run `≤120.0 s`; warm median `≤90.0 s`; resolver cumulative `≤45.0 s`.
- [ ] Peak RSS, per-stage timing và cache/query metrics được ghi.
- [ ] Manifest chứa resolver version/config fingerprint/A6 build id.
- [ ] Không có diff trong raw/processed data, active snapshot, V2 canonical, compatibility shims hay legacy tools.

Nếu coverage gate không đạt nhưng correctness/safety đạt, implementation chưa được coi là hoàn tất; quay lại resolver evidence/rules trong đúng phạm vi. Nếu correctness gate thất bại, rollback ngay dù coverage tăng.

## 14. What we intentionally will not do

### MUST

- Tách mention extraction, metric resolution và source binding.
- Giữ role qua AST structure và planner consumer paths.
- Thêm resolver deterministic, read-only, versioned và fail closed.
- Seal H198 và B0 sạch; đo H198 cùng toàn bộ B0 OK.
- Ghi rõ ambiguity và terminal reason thay vì ép answer.
- Chặn entity-scope confounder và áp dụng independent reviewer protocol.

### MUST NOT

- Không sửa dữ liệu A6, active identities hay retrieval index.
- Không sửa top-K/ranker/binder để “cứu” lỗi parse.
- Không hard-code QID, ticker, câu hỏi đầy đủ hay expected answer.
- Không triển khai production logic trong `tools/answer_v2` hoặc `answer_pipeline` shim.
- Không thay shared V2 behavior để sửa Q508.
- Không dùng neural matcher/reranker.
- Không coi source-label proxy là gold label.
- Không nới reported-derived/promotion gates.
- Không gộp later abstain thành “recovered answer”.
- Không commit/stash/reset workspace hiện tại để tạo baseline; dùng isolated clean worktree.
- Không sửa alias generator/lexicon hoặc V2 canonical trong workstream này; precondition fail thì mở upstream work item riêng.
- Không chạy/package V3 như một bước phụ của plan này.

### CONTINGENCY ALLOWED

- Materialized semantic label index chỉ được tạo trong Phase 2 khi direct-SQLite path vượt performance trigger đã đăng ký; index phải immutable, checksummed và tách khỏi active retrieval index.

### DEFER

- Learned paraphrase model, embeddings hoặc cross-encoder.
- Mở rộng ontology toàn cục từ mọi source row.
- Sửa `BINDING_TIE`, reported-derived, non-executable tables hay calibration ngoài việc ghi nhận terminal transition.
- Promotion V3; chỉ xem xét sau reviewer adjudication và các gate hiện hữu.
- Bất kỳ implementation nào port extractor/rules sang V2; Phase 2B chỉ được đánh giá read-only.
- Sửa global source-lineage/RET-015, đồng bộ migration status và sửa `package-v3`; các việc này có owner/work item riêng sau khi B0 được seal.

## 15. Implementation order

### Phase 0 — Preconditions, clean baseline và audit harness

1. **ENV-0:** xác nhận disk headroom, bootstrap đúng project test environment, chạy `make paths-check` và `make snapshots-verify`; seal OS/build, CPU, Python executable/version và dependency-lock checksum. Current review host đã có khoảng 51 GiB trống, git hoạt động và `make paths-check` pass; tuy nhiên `.venv` chưa tồn tại và system Python 3.14 chưa có `pytest`, nên ENV-0 hiện vẫn chưa đạt. Bằng chứng tức thời này không thay cho seal ở execution time.
2. Tạo isolated clean worktree từ một explicit commit chứa alias fix hiện có; không commit/stash/reset workspace người dùng. Bắt buộc `git_dirty=false`.
3. Chạy alias invariant hiện hữu: generated A6 brands không chứa literal `...`. Entity không resolve được, ví dụ một alias chưa attested, phải được gắn confounder; không sửa lexicon trong plan này.
4. Chạy resolver-disabled full corpus để tạo B0 sạch. Nếu không tái hiện 287/725/H198=198, dừng và revision plan trước khi viết production code.
5. Materialize V2 lexical snapshot/hash cho `classify_operation` + `parse_intent` trên 1.012 câu.
6. Viết `diagnose_metric_unresolved_v3.py` ở chế độ read-only; tạo `cohort_h198.jsonl`, seal SHA-256, taxonomy/tier/operation và exact B0 OK drift fixture.
7. Thêm targeted fixtures Q5, Q15, Q89, Q100, Q426, Q502, Q870, Q508.
8. Gán reviewer IDs cho hai annotator và một adjudicator theo Mục 8.5; nếu chưa có, khóa trước trạng thái `diagnostic-only/non-promotable`.

**Exit:** tất cả gate 13.0 pass; B0 tái lập được; cohort và reviewer status đã seal; không có production behavior change.

### Phase 1 — Contracts và observability

1. Thêm mention/hypothesis/resolution contracts.
2. Thêm optional AST/plan provenance và serialization tests.
3. Ghi richer trace nhưng giữ resolver disabled.

**Exit:** old fixtures round-trip; toàn bộ B0 OK zero drift; V2 lexical hash và baseline status không đổi.

### Phase 2 — Strict source-backed resolution cho T1

1. Implement `A6MetricMentionResolver` exact/fact-normalized trên leaf label/source code và scope.
2. Wire fallback chỉ khi exact ontology/formula path rỗng.
3. Planner/retriever nhận validated binding hint.
4. Chạy Q5/Q89 và T1 cohort; đo cold/warm runtime, resolver timing, RSS, DB query/cache metrics.
5. Nếu performance trigger nổ, build semantic label index contingency rồi đo lại; không thay A6/retrieval active artifacts.
6. Lập Phase 2 review queue gồm mọi T1 tới binder, tối đa 60 theo SHA-256 seed `metric-unresolved-phase2-go-no-go-v1`; review correctness của required candidates trên source evidence.

**Go/no-go:** chỉ tiếp tục Phase 3 nếu có ít nhất 21 T1 được xác nhận có đúng required candidates và candidate precision trong reviewed queue đạt ít nhất 0,80. Nếu không đạt, dừng workstream, giữ diagnostic artifacts và chuyển quyết định nguồn lực sang owner V2; không nới matcher hoặc gate hậu nghiệm.

**Exit:** correctness/performance gates pass; go/no-go đạt; B0 và V2 zero drift.

### Phase 2B — Portability assessment read-only, không thuộc implementation scope

1. Chạy mention extractor và abbreviation rules như một diagnostic trên fixed family 40 V2 `unbound operands` trong `docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md`.
2. Chỉ báo coverage/hypothesis evidence; không sửa V2 parser/router, không emit submission answers và không tính vào acceptance của plan này.
3. Ghi một decision note riêng về khả năng tái sử dụng. Mọi port sang V2 cần work item/approval khác.

### Phase 3 — Role-preserving composition

1. Compose select/filter/count/divide roles trước generic base.
2. Bỏ `mentions[-1]` khỏi fallback decision.
3. Tổng quát hóa V3 clause grammar cần cho Q426/Q502/Q508.
4. Chạy role tests và negative tests.

**Exit:** Q426/Q502/Q870 đúng cấu trúc; Q508 đúng boundary; không yêu cầu mọi câu `OK`.

### Phase 4 — Bounded paraphrase/hierarchy

1. Thêm rule abbreviation versioned cho các gap có bằng chứng như TNDN.
2. Thêm hierarchy-aware hypotheses cho Q15-like cases.
3. Với mỗi rule, thêm evidence QID và negative example vào YAML/tests.
4. T2/T3 chỉ được chọn khi thắng threshold/margin; còn lại trả ambiguity/specificity.

**Exit:** Q100 vẫn abstain; deterministic ranking; không unsafe emission.

### Phase 5 — Full-corpus A/B và quyết định

1. Chạy 1.012 câu trên cùng identities.
2. Sinh funnel, tier/operation breakdown, drift report, runtime/RSS và review queue.
3. Reviewer adjudicate queue đúng protocol Mục 8.5; thiếu quorum thì đóng dấu `NON_PROMOTABLE`.
4. Chỉ đánh dấu implementation hoàn tất khi tất cả acceptance gates pass.
5. Không chạy `package-v3` trong phase này; packaging/lineage status update là work item riêng.

## Appendix A — QID cohorts dùng để tái lập phép đo

Danh sách dưới đây là human-readable display của H198. Phase 0 phải materialize cùng nội dung thành `cohort_h198.jsonl`, kiểm unique/count và ghi `cohort_sha256` vào B0 manifest. Cho tới khi bước đó hoàn tất, checksum có trạng thái `TO_BE_SEALED`; không được copy thủ công Appendix A làm input cho các run sau.

### T1 — 124 QID

`5, 19, 20, 26, 35, 39, 48, 52, 56, 65, 70, 74, 78, 81, 89, 94, 95, 97, 102, 103, 106, 115, 116, 117, 120, 134, 137, 140, 150, 158, 159, 161, 162, 165, 166, 174, 175, 194, 215, 217, 219, 223, 241, 242, 243, 248, 252, 260, 261, 262, 265, 266, 269, 274, 277, 287, 288, 294, 300, 305, 311, 327, 330, 338, 339, 345, 355, 359, 498, 501, 502, 580, 585, 597, 603, 610, 611, 621, 626, 649, 654, 658, 703, 704, 715, 725, 726, 729, 733, 745, 751, 753, 761, 769, 784, 797, 800, 802, 807, 811, 812, 814, 815, 818, 825, 828, 836, 857, 864, 865, 870, 889, 896, 921, 932, 937, 939, 942, 949, 950, 951, 969, 1010, 1012`

### T2 — 55 QID

`32, 42, 60, 75, 79, 99, 110, 128, 129, 133, 149, 156, 173, 183, 188, 191, 200, 233, 236, 263, 270, 275, 314, 319, 331, 333, 346, 351, 360, 426, 436, 594, 596, 617, 638, 657, 664, 682, 683, 689, 714, 721, 741, 742, 779, 806, 882, 887, 895, 912, 918, 963, 974, 1006, 1011`

### T3 — 18 QID

`15, 37, 125, 187, 220, 238, 284, 285, 296, 306, 336, 637, 645, 666, 677, 685, 925, 993`

### Không có phrase proxy duy nhất

`100`

## Appendix B — Trả lời các câu hỏi audit bắt buộc

1. **Có bao nhiêu câu parser không extract được metric mention?** 198 theo trace hiện tại. Do extractor và mapper đang gộp, con số này nghĩa chính xác là “không tạo được ontology-backed `MetricMention`”, chưa phân biệt không thấy surface với thấy surface nhưng không map.
2. **Có bao nhiêu câu extract được mention nhưng không map được sang metric hiện tại?** 0 quan sát được trong schema trace hiện tại, vì mention chưa map không được lưu. A6 proxy cho thấy 197/198 có metric-like source surface; resolver diagnostic mới phải đo lại câu hỏi này đúng nghĩa.
3. **Có bao nhiêu câu có nhiều metric nhưng schema chỉ hỗ trợ một `metric_id`?** Không thể kết luận 198 câu bị schema một metric; AST V3 đã hỗ trợ nhiều `MetricRef`. Lower bound 9 câu có role đa operand từ operation. Lỗi thực là compile order, mapping và role assignment.
4. **Có bao nhiêu câu cần specificity?** Q100 là trường hợp chắc chắn từ bằng chứng hiện có. T2/T3 là risk cohorts, không được gán toàn bộ là specificity nếu chưa adjudicate.
5. **Có bao nhiêu câu metric tồn tại trong row label A6 nhưng không được map?** 197/198 có row-label proxy; đây không phải 197 semantic gold matches. T1=124 là cohort bằng chứng mạnh nhất.
6. **Có bao nhiêu câu mất vai trò rank/filter/value?** Trong cohort có lower bound 9 theo operation; Q426/Q502 chứng minh role resolver không chạy. Q508 ở ngoài cohort chứng minh role có thể bị chọn sai dù có mention. Cần diagnostic mới để có con số exact theo span/role.
7. **Có bao nhiêu câu candidate tồn tại nhưng resolver vẫn reject?** 0 trong đúng cohort 198 vì retrieval chưa chạy. Q508 là boundary ngoài cohort và hiện có `METRIC_REJECT_ALL` cho operand bị parse sai.
8. **Có bao nhiêu câu thật sự mơ hồ?** 0 được ghi nhận chính thức vì parser không giữ hypothesis; Q100 chắc chắn cần specificity, 18 T3 là high-risk ambiguity cohort. Không được biến risk cohort thành fact.
9. **Có bao nhiêu câu là derived question nhưng không thuộc reported-derived issue?** Ít nhất 4 divide và các cấu trúc arithmetic/select-at-arg như Q426 là derived theo operation, nhưng cả 198 dừng trước reported-derived gate. Kế hoạch này chỉ đưa chúng qua parsing/roles; không thay policy derived.

---

## Appendix C — Disposition của independent review

| Review item | Disposition trong plan hoàn thiện |
|---|---|
| M1 runtime | **ACCEPTED**: sửa đơn vị `47.676 s`; thay gate +10% bằng cold/warm absolute budgets; index được nâng thành Phase 2 contingency |
| M2 dirty baseline | **ACCEPTED WITH MODIFICATION**: dùng isolated clean worktree, không commit/stash workspace người dùng; reference artifact chỉ giữ để freeze H198 |
| M3 alias/entity | **PARTIALLY ACCEPTED**: serialization defect đã được sửa trong current tracked HEAD và đã có invariant test; plan thêm precondition + `ENTITY_SCOPE_UNAVAILABLE`, không sửa lại alias trong workstream này |
| M4 reviewer | **ACCEPTED**: dùng `independent_gold_protocol_v1.yaml`, định nghĩa queue/quorum/blinding và trạng thái `NON_PROMOTABLE` |
| M5 environment | **ACCEPTED**: thêm ENV-0 và machine/Python/lock seal |
| M6 V2 drift | **ACCEPTED**: thêm full-corpus V2 lexical snapshot/hash gate |
| M7 opportunity cost | **ACCEPTED WITH SCOPE GUARD**: thêm Phase 2 go/no-go và Phase 2B read-only; không port hay sửa V2 trong plan này |
| M8 minor items | **ACCEPTED**: package risk, entity diagnostic, rule evidence/negative tests, cohort checksum và compatibility comment đều đã được đưa vào |
| RET-015/migration status/package fix | **DEFERRED AS SEPARATE WORK**: plan chỉ fail closed trên baseline identity; không mở rộng sang release-wide/source-lineage/package repair |

---

**Quyết định cuối của audit sau review:** Kiến trúc resolver vẫn đủ cơ sở để triển khai, nhưng trạng thái là conditional. Không được viết production code trước khi B0 sạch, cohort checksum, V2 hash, môi trường và reviewer status được seal. Chưa có bằng chứng để nới promotion gate, tự động coi 197 proxy matches là đáp án đúng, hoặc sửa retrieval/binding nhằm giảm số `METRIC_UNRESOLVED`.
