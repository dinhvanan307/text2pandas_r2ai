# HUMAN SEMANTIC GOLD V2 — Protocol thiết kế cuối cùng

**Ngày:** 2026-08-29 · **Tác giả:** audit/design độc lập (chuỗi 27-29/08)
**Phương pháp:** inspect toàn bộ implementation trước khi thiết kế (STEP 1). Mọi khẳng định về repo có evidence file:line. Không tạo bất kỳ human gold nào trong tài liệu này.

---

## A. Repository findings — cái gì ĐÃ tồn tại

Kết luận quan trọng nhất của bước audit: **phần lớn hạ tầng WP0-WP2 đã được implement và test xong; cái thiếu không phải thiết kế mà là (1) con người, (2) 5 tool cuối chuỗi, (3) một số defect nhỏ trong guideline/vocabulary tôi liệt kê ở mục G/M.**

| Thành phần | Trạng thái | Evidence |
|---|---|---|
| Schema v2 (JSON Schema 2020-12) | ✅ HOÀN CHỈNH | `configs/evaluation/semantic_gold_v2_schema.json` — 222 dòng, đã đọc toàn bộ: span zero-based half-open, entity/metric/period/basis/unit/operation_tree/operands/field_status, attestations 7 trường, basis if/then (implicit ⇒ UNSPECIFIED), unit if/then (scale chỉ cho MONEY ∈ {0,3,6,9,12}) |
| Operation vocabulary v1 | ✅ (DRAFT_FOR_CALIBRATION) | `semantic_operation_vocabulary_v1.yaml` — 17 operations, 14 operand roles, 7 period roles, 8 output shapes |
| Metric concepts v1 | ✅ nhưng MỎNG | `semantic_metric_concepts_v1.yaml` — **39 concepts**, mỗi concept có definition_vi + inclusion/exclusion examples; policy `mark_UNRESOLVED_do_not_invent`, mở rộng chỉ trong calibration |
| Protocol config | ✅ | `semantic_gold_v2_protocol.yaml` — pin parser commit `08907c36…`, question SHA `64a428d9…`, ≥2 annotator + distinct adjudicator, release 100-150 records, guideline pointer |
| Sampling manifest | ✅ ĐÃ SEAL | `semantic_gold_v2_sampling.yaml` — CORE 100 (seed + SHA-256 hash-order) / DIAGNOSTIC 20 (9 strata regex, precedence tường minh) / RESERVE 30 |
| Packet chính danh | ✅ | `artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-01/` — manifest SHA `522e87ff…`, 11 file, blank templates A/B/C 360/360 pass schema, `access_log.jsonl` rỗng, roster `UNASSIGNED`. **Hai packet cũ `phase1.5-packet-…-01/-03` đã bị supersede** (ledger 221 thiếu `reason`, không có `selection.authority`) — cần đánh dấu tránh dùng nhầm |
| Contamination ledger | ✅ | 259 QID nhiễm / 753 eligible / 0 nhiễm trong core; 325 entries `{qid, source, reason}`; bổ sung tay 60 QID qua `semantic_gold_v2_known_development_qids.jsonl` |
| Protected surface | ✅ | 11 file production fingerprint trước/sau byte-identical (`protected_surface.json` SHA `804a3c08…`) |
| Guideline | ✅ DRAFT-1 | `data/curated/gold/semantic_gold_v2/README.md` — 13 mục, đã đọc toàn bộ; chính là guideline (không phải README thường) |
| LOCAL_SYNTHETIC lane | ✅ chạy xong, dán nhãn trung thực | `semantic_gold_v2_local.py` (1.357 dòng) + `run_semantic_gold_v2_local_e2e.py`; 120 records, 30 RESOLVED/90 UNRESOLVED; provenance 5-key bắt buộc; cấm ghi vào `data/curated/gold/` |
| Tests | ✅ 57 | `test_semantic_gold_v2.py` (25), `…_sampling.py` (7), `…_local.py` (8), v1 `test_semantic_gold.py` (17) |
| Tools chuỗi human | ⚠️ **2/7** | Có: `prepare`, `local-e2e` (Makefile:72-86). **THIẾU: validate / agreement / seal / export-predictions / evaluate** (đều được plan §14 chỉ định tên nhưng chưa có file) |
| Gold thật | ❌ KHÔNG TỒN TẠI | `data/curated/gold/semantic_gold_v2/` chỉ có README; registry vẫn ghi v1: 40 records/6 usable/promotion 0 |

**Ba phát hiện mâu thuẫn code-vs-plan (CRITICAL RULE 10):**

1. **Kênh evidence của annotator bị hỏng trên active lineage.** Guideline §1 cho phép xem "source A6 CSVs" — nhưng build active `c6887…` **không có** `dataframe/csv/` (đã xác minh 27/08, chỉ build cũ `b3e968…` có). Annotator sẽ không mở được evidence theo đúng kênh được phép. Phải sửa trước pilot (xem G-10).
2. **Vocabulary role không nhất quán:** guideline §4 dùng `COMPARISON_ENTITY`, code LOCAL_SYNTHETIC dùng `COMPARAND` (`semantic_gold_v2_local.py`, entity role). Schema để `semantic_role` là chuỗi tự do ⇒ hai annotator sẽ viết hai kiểu và agreement giả-thấp. Phải enumerate role vào operation vocabulary + validator.
3. **Metric concept ≥0.95 gate hiện KHÔNG THỂ ĐẠT với parser pinned:** Canonical V2 tại commit `08907c3` không có public pre-bind metric phrase/concept output (LOCAL_SYNTHETIC E2E đo được 0% chính vì prediction là `MISSING_OUTPUT:…`). Gold vẫn tạo bình thường — gold độc lập với parser — nhưng phase decision sẽ là `CONTINUE_PHASE_1` một cách chắc chắn cho tới khi contract đó được implement ở một commit mới và evaluate lại **trên cùng gold đã seal**. Nói rõ trước để không ai bất ngờ.

## B. Gold definition — một record ground-truth cho cái gì

Một record = **semantic reading đúng của MỘT câu hỏi, độc lập với mọi implementation**, gồm đúng các trường schema v2:

- **Question-level:** `record_status` (RESOLVED/AMBIGUOUS/UNRESOLVED), `operation_tree` (node ∈ 17 ops, tree cho composition), `output.shape` (8 giá trị — đây là "result_kind").
- **Components:** entities (mention span + canonical_ref ticker + role), metrics (phrase span + concept_id trong 39-concept vocabulary + REPORTED/DERIVED), periods (year/quarter/point/role/explicit), basis (CONSOLIDATED/SEPARATE/UNSPECIFIED + explicit), unit (dimension/scale/currency/explicit).
- **Operand structure:** danh sách operands có role định danh (NUMERATOR/DENOMINATOR/MINUEND/SUBTRAHEND/NEW/OLD/RANK_KEY/PROJECTED_VALUE/FILTER_*…), mỗi operand trỏ `metric_ref/entity_ref/period_ref` + basis/unit riêng; `operation_tree.operands` tham chiếu `o1..oN`, **thứ tự là ngữ nghĩa** — `(A−B)/B` = `DIVIDE(o_num=SUBTRACT(...), o_den)` qua `children`.
- **Span:** NFC, zero-based, half-open `[start, end)`, `question[start:end] == text` (schema `$defs/span` + guideline §3); mỗi occurrence lặp lại là một span riêng.
- **Canonical frame:** **KHÔNG do annotator viết.** Sealer derive tất định từ components (guideline §11: NFC, enum uppercase, sort theo stable refs, giữ nguyên thứ tự operand/children, loại NOT_APPLICABLE, loại reviewer metadata). Test đã enforce: manual `full_frame` bị reject (`test_semantic_gold_v2.py:536`).

Gold KHÔNG chứa: giá trị số của đáp án, Silver row/VAS code/table_uid làm concept (chỉ được ghi ở `source_evidence` locator), bất kỳ trường nào từ prediction.

## C. Recommended annotation protocol (một phương án duy nhất)

**Chọn: Option B chính thức (2 annotator độc lập + adjudicator riêng) cho seal, cộng một "bootstrap lane" HUMAN đơn-annotator CHỈ chạy trên pilot QIDs, không bao giờ seal.** Lý do ở mục N.

```text
Giai đoạn 0 · SỬA 3 DEFECT (G-10, G-11, G-12) + implement 5 tool thiếu (mục L)
     → bump guideline lên v2, bump vocabulary nếu đổi, re-run prepare (packet mới,
       vì guideline_sha256 nằm trong attestation contract)
Giai đoạn 1 · TUYỂN ROSTER: A, B, C — 3 người khác nhau, KHÔNG phát triển parser
     (đây là blocker tổ chức thật; xem N về nguồn tuyển)
Giai đoạn 2 · PILOT 12-15 QID lấy từ pool 259 QID ĐÃ NHIỄM (thiết kế mới — xem G-13)
     → A, B annotate độc lập → C phân loại disagreement:
       guideline defect → sửa guideline/vocabulary → bump version+SHA
       genuine ambiguity → giữ, làm ví dụ trong guideline
     → FREEZE guideline v-final; từ đây không đổi nữa (CRITICAL RULE 7 của plan)
Giai đoạn 3 · FINAL ANNOTATION: A và B mỗi người 120 records (100 core + 20 diag),
     private packet, lock riêng; access_log ghi mọi lần mở evidence
Giai đoạn 4 · validate (schema + consistency) từng packet → agreement measurement
     → checkpoint: metric concept <0.85 | operand role <0.85 | full-frame <0.70
       ⇒ DỪNG, coi là guideline defect, không ép tiếp
Giai đoạn 5 · C adjudicate 100% records (không chỉ disagreement), có evidence;
     genuine ambiguity giữ AMBIGUOUS — không ép RESOLVED để đủ 100
Giai đoạn 6 · SEAL: derive full_frame, validate toàn bộ, ghi manifest + SHA-256,
     cập nhật gold_registry_v1.yaml (lần đầu tiên promotion_eligible > 0)
Giai đoạn 7 · export predictions từ commit pinned 08907c3 (EFFECTIVE_PUBLIC_PREBIND)
     → evaluate → metrics + failure taxonomy → phase decision theo rule đã preregister
```

## D. Annotator interface — được xem gì

**ĐƯỢC XEM** (guideline §1, giữ nguyên + sửa kênh evidence):
1. Câu hỏi nguyên văn (từ `selection_*.jsonl` — đã có sẵn question + question_sha256).
2. Schema, guideline v-final, 2 vocabulary (SHA ghi trong attestation — schema bắt buộc khớp, test `:477` reject mismatch).
3. Evidence nguồn **chỉ để** xác nhận (a) công ty nào ứng với tên trong câu, (b) một cụm từ có phải reported terminology, (c) locator `{csv_path, row_path, col_label}`. Kênh: sau khi sửa G-10 — CSV per-table của build active, HOẶC raw BTC extracted text của đúng ticker/năm. **Không đưa cả silver.db** (chứa quá nhiều dẫn xuất).
4. `companies.csv` (mapping tên↔ticker — cần thiết vì corpus ẩn danh hoá: STB = "Sài Gòn Tài Lộc").

**CẤM XEM** (đã enforce một phần bằng test template-blank + prediction-shape-reject `:339`):
- Parser/resolver prediction, trace, canonical frame sinh bởi máy — kể cả LOCAL_SYNTHETIC records (chúng là output của recognizer production!);
- answer/pandas_query/evidence do runtime chọn; retrieval scores/candidates;
- label của annotator kia trước khi cả hai lock (guideline §12);
- kết quả evaluation, failure taxonomy sinh từ prediction;
- các file trong contamination_sources.

**Tại sao:** mọi thứ ở danh sách cấm đều mang "cách máy đọc câu hỏi" — nếu lọt vào mắt annotator, gold đo agreement-với-máy thay vì đo sự thật; và LOCAL_SYNTHETIC records nguy hiểm nhất vì trông giống template hợp lệ. Đề xuất thêm: **A và B không được truy cập repo** — chỉ nhận một bundle xuất riêng (question packet + guideline + vocabularies + evidence viewer), vì trong repo mọi thứ cấm đều nằm cách một `ls`.

## E. Schema mapping — từng field được tạo thế nào

| Field | Ai tạo | Cách |
|---|---|---|
| `qid/question/question_sha256/cohort/selection_digest/primary_stratum/secondary_tags` | prepare tool | đã bind sẵn trong template — annotator KHÔNG sửa (test `:311`) |
| `reviewer_slot` | template | A/B/C cố định theo file |
| `reviewer_id` | annotator | pseudonym ổn định (vd `ANNOT_A_2026`), không dùng tên thật trong artifact |
| `attestations` (7 trường) | annotator khi lock | 4 boolean tự khai + 3 SHA copy từ packet manifest; sai SHA ⇒ validator reject |
| `entities[]` | annotator | span từ câu; `canonical_ref` = ticker tra qua companies.csv/evidence; không đoán → UNRESOLVED; role lấy từ **enum mới** (G-11) |
| `metrics[]` | annotator | maximal span + concept_id trong 39 concepts; thiếu concept → `concept_status=UNRESOLVED` + note đề xuất (chỉ nhận vào vocabulary ở calibration) |
| `periods[]` | annotator | mọi năm nêu tên; range expand đủ (guideline §6); role theo vị trí ngữ nghĩa |
| `basis` | annotator | chỉ CONSOLIDATED/SEPARATE khi có chữ; còn lại UNSPECIFIED+explicit=false — **không** lấy default consolidated của runtime |
| `unit` | annotator | theo bảng guideline §8; scale chỉ với MONEY |
| `operation_tree` + `operands[]` | annotator | tree + role; thứ tự semantic; nested qua `children` |
| `field_status` | annotator | per-field 4 trạng thái |
| `source_evidence[]` | annotator | locator hoặc NOT_LOCATED; không copy evidence của runtime |
| `ambiguity_alternatives` | annotator | bắt buộc khi AMBIGUOUS |
| `adjudication` | chỉ C | quyết định + lý do + trace disagreement |
| `full_frame` | **sealer** | derive tất định — annotator không đụng |

## F. Guideline — đánh giá và phần cần bổ sung

Guideline draft-1 (13 mục) đã đạt ~85% yêu cầu STEP 6: span, entity, metric REPORTED-vs-composed ("tỷ lệ nợ xấu" = 1 metric vs "nợ xấu trên tổng dư nợ" = DIVIDE — ví dụ đã có sẵn §5), period roles, basis mapping, unit mapping, tree/order, evidence, canonical frame, workflow A/B/C, reserve policy. **Giữ nguyên làm xương sống.** Cần BỔ SUNG trước freeze:

1. **Bảng quyết định operation từ wording** (hiện chỉ có ví dụ role): `"gấp bao nhiêu lần"` → DIVIDE + RATIO; `"tăng/giảm bao nhiêu %"` → GROWTH(NEW,OLD) + PERCENT; `"tăng/giảm bao nhiêu tỷ"` → SUBTRACT + MONEY; `"chênh lệch"` → SUBTRACT với hướng lấy theo trật tự cú pháp **không theo dấu của đáp án** (CRITICAL RULE 4); `"X hơn Y bao nhiêu"` → MINUEND=X, SUBTRAHEND=Y; `"ít hơn/kém hơn"` → đảo chiều.
2. **Enum entity role** (G-11) + quy tắc multi-entity: screening ("trong các công ty…") ⇒ entities có thể rỗng + note population; directional giữ nguyên trật tự nguồn.
3. **Điều khoản anonymized corpus:** tên trong câu là tên thật (Sacombank/Eximbank), corpus dùng tên ẩn danh — canonical_ref xác định qua companies.csv + evidence; nếu không map được → entity UNRESOLVED (đừng để annotator "biết" STB nhờ kiến thức thị trường — phải có bằng chứng trong corpus).
4. **Ví dụ chuẩn cho từng hard case ở mục G** — mỗi case 1 ví dụ dương + 1 ví dụ âm.

## G. Hard cases — quy tắc xử lý

| Case | Quy tắc |
|---|---|
| NESTED_COMPOSED | tree với `children`; node cha nhận operand là kết quả node con; không phát minh composite role |
| ARG_SELECT_PROJECT | `SELECT_AT_ARG` với RANK_KEY (metric xếp hạng) ≠ PROJECTED_VALUE (metric trả về); hai metric_ref khác nhau; nếu câu chỉ có một metric cho cả hai vai → cùng metric_ref, hai operand |
| DIVIDE_EXPLICIT_RATIO | named ratio không nêu thành phần = 1 REPORTED metric; nêu tử/mẫu = DIVIDE composed (guideline §5 đã chuẩn) |
| SUBTRACT_DIRECTIONAL | MINUEND/SUBTRAHEND theo cú pháp câu; **A−B ≠ B−A phải ra hai frame khác nhau**; cấm suy từ answer |
| GROWTH_PERCENT_CHANGE | GROWTH(NEW, OLD) khi hỏi %, SUBTRACT khi hỏi lượng tuyệt đối; "từ cuối 2021 đến cuối 2022" ⇒ OLD=2021/CLOSING, NEW=2022/CLOSING |
| MULTI_ENTITY_DIRECTIONAL | mỗi operand mang entity_ref riêng; trật tự entity theo câu; so sánh "X lớn hơn Y bao nhiêu" ⇒ MINUEND.entity=X |
| COUNT | COUNT(FILTER(...)); FILTER_OPERAND = metric bị lọc, FILTER_THRESHOLD riêng; output.shape=COUNT, unit.dimension=COUNT |
| BASIS_SENSITIVE | "công ty mẹ/riêng lẻ"→SEPARATE, "hợp nhất"→CONSOLIDATED; mixed-basis ⇒ basis per-operand |
| UNIT_SCALE_SENSITIVE | unit của OUTPUT theo câu hỏi ("bao nhiêu triệu đồng"→exponent 6); "điểm phần trăm" → PERCENT_POINT (khác PERCENT) |

**Ba defect phải sửa trước pilot (đánh số để trace):**
- **G-10 · Kênh evidence:** materialize `dataframe/csv/` cho build active `c6887…` (hoặc một evidence-viewer read-only từ silver.db xuất đúng {csv_path, row_path, col_label}); nếu không, sửa guideline sang raw BTC extracted text. Không có kênh này, `source_evidence_reviewed=true` là attestation không thể thực hiện trung thực.
- **G-11 · Enum entity semantic_role** vào `semantic_operation_vocabulary_v1.yaml` (đề xuất: `REPORTING_ENTITY, COMPARISON_ENTITY, INVESTEE, POPULATION_MEMBER`) + validator enforce; xóa lệch `COMPARAND`.
- **G-12 · Mở rộng metric concepts:** 39 concepts phủ ~50/120 phrase trong dry-run synthetic (70 UNRESOLVED). Trước pilot, chạy matcher LOCAL_SYNTHETIC (chỉ ontology, không prediction) trên 753-QID eligible để liệt kê phrase chưa phủ → C + 1 người soạn thêm concept trong calibration. Nếu để vocabulary mỏng, UNRESOLVED sẽ tràn và headline mất denominator.
- **G-13 · Pilot lấy từ pool nhiễm:** 12-15 QID chọn từ 259 contaminated QIDs (stratified qua các family khó) — chúng đã cháy với sampling nên không tốn eligible universe, còn chất lượng calibration của annotator không phụ thuộc việc parser từng thấy QID đó. Plan gốc chưa chốt nguồn pilot; đây là đề xuất chốt.

## H. QC — validation và disagreement

Chuỗi validator (tool `validate_semantic_gold_v2.py` — cần viết, logic đã có sẵn trong `semantic_gold_v2_local.py` validation + 25 unit test làm spec):

1. JSON Schema pass từng record; đủ 120 record, đúng QID set, không duplicate.
2. Span: `question[start:end]==text`, NFC, thứ tự ổn định (test `:389,:399` đã có sẵn rule).
3. Referential closure: mọi `metric_ref/entity_ref/period_ref/operand_ref` trong tree đều tồn tại; operand thừa bị reject (`:506`); thiếu component applicable bị reject (`:516`).
4. Consistency: basis/unit if-then; operation ∈ vocabulary; role ∈ vocabulary (sau G-11); GROWTH có đúng NEW+OLD; DIVIDE có đúng NUMERATOR+DENOMINATOR…
5. Status: record RESOLVED ⇔ mọi field RESOLVED/NOT_APPLICABLE; AMBIGUOUS ⇒ có alternatives; UNRESOLVED ⇒ có note phân biệt nguyên nhân (câu mơ hồ / thiếu evidence / vocabulary thiếu concept / schema limitation) — **UNRESOLVED-vì-annotator-không-chắc không phải trạng thái hợp lệ**: không chắc ⇒ hỏi C ghi note, hoặc AMBIGUOUS với alternatives.
6. Attestation + SHA khớp packet; roster 3 người khác nhau (`:458,:487`).
7. Provenance: access_log không rỗng nếu source_evidence có LOCATED.
8. Agreement: exact-match per-field + per-record; disagreement report per-QID → **C adjudicate từng disagreement, ghi vào `adjudication.jsonl` với lý do; cấm silently chọn A hoặc B** (schema có trường `adjudication` cho việc này).
9. Canonical determinism: derive full_frame 2 lần → byte-identical.

## I. Freeze — seal procedure

Tool `seal_semantic_gold_v2.py` (cần viết) tạo release **immutable**:

```text
data/curated/gold/semantic_gold_v2/release-v2.0/
    annotations.jsonl        # bản C-final, đã derive full_frame
    agreement.json           # per-field A-vs-B trước adjudication
    adjudication.jsonl       # mọi quyết định của C + lý do
    manifest.json            # xem dưới
    guideline.md             # bản v-final đúng SHA đã attest
```

`manifest.json` bắt buộc: gold SHA-256 (của annotations.jsonl), schema_version=2 + schema SHA, guideline version+SHA, 2 vocabulary SHA, packet nguồn (`semantic-gold-v2-packet-…` + manifest SHA `522e87ff…` hoặc packet mới sau G-10..13), question source SHA `64a428d9…`, roster pseudonyms + attestations, số record theo status (resolved ≥100 theo protocol release policy), contamination ledger SHA, `status: SEALED`. Đồng thời cập nhật `configs/evaluation/gold_registry_v1.yaml` (usable/promotion_eligible/independence). **Sau seal: mọi sửa đổi = release-v2.1 mới, không ghi đè** (protocol `immutable: true` đã quy định).

## J. Evaluation — gold vs prediction

Contract (đã đúng trong plan, giữ nguyên): prediction export từ **đúng commit pinned** `08907c3` qua view `EFFECTIVE_PUBLIC_PREBIND` (không dùng `metric_codes_hint` làm concept — test `:154` local đã enforce nguyên tắc này); gold không derive từ prediction, prediction không sửa gold; field máy không phát ra ⇒ chấm `MISSING/NOT_EMITTED` = sai, không loại khỏi mẫu. Điểm mạnh của thiết kế này: **gold seal một lần, evaluate được nhiều commit** — sau khi Canonical V2 có public metric contract (Phase 2), chạy lại evaluator trên cùng release-v2.0 là có phép đo tiến bộ sạch.

## K. Files cần tạo/sửa

| File | Hành động | Ghi chú |
|---|---|---|
| `semantic_operation_vocabulary_v1.yaml` | SỬA (G-11) | thêm `entity_roles:`; bump SHA |
| `semantic_metric_concepts_v1.yaml` | SỬA (G-12, trong calibration) | thêm concepts; bump SHA |
| `data/curated/gold/semantic_gold_v2/README.md` | SỬA | guideline v2: bảng operation-wording, enum role, điều khoản anonymized corpus, ví dụ hard-case; bump version+SHA |
| `tools/evaluation/validate_semantic_gold_v2.py` | **TẠO** | logic rút từ local usecase |
| `tools/evaluation/measure_semantic_agreement_v2.py` | **TẠO** | exact per-field + report |
| `tools/evaluation/seal_semantic_gold_v2.py` | **TẠO** | derive full_frame + release + registry |
| `tools/evaluation/export_canonical_v2_semantics.py` | **TẠO** | tách từ `semantic_gold_v2_local.py:370` |
| `tools/evaluation/evaluate_semantic_gold_v2.py` | **TẠO** | tách từ `semantic_gold_v2_local.py:430` |
| `tests/unit/test_semantic_gold_v2_evaluator.py`, `…_export.py` | **TẠO** | plan yêu cầu, chưa có |
| Packet mới sau khi guideline/vocab bump | chạy lại prepare | packet cũ `…-01` giữ làm lịch sử; 2 packet `phase1.5-*` đánh dấu SUPERSEDED |
| `data/processed/a6/c6887…/dataframe/csv/` | materialize (G-10) | hoặc evidence-viewer thay thế |

## L. Commands

```text
1. prepare    make semantic-gold-v2-prepare PROTOCOL=configs/evaluation/semantic_gold_v2_protocol.yaml PACKET=<id>   ✅ EXISTS (Makefile:72-76)
2. annotate   COMMAND_NOT_IMPLEMENTED — theo thiết kế là con người điền JSONL ngoài repo;
              vòng lặp thực tế: editor + `validate` sau mỗi phiên (không cần UI riêng)
3. validate   COMMAND_NOT_IMPLEMENTED → tạo validate_semantic_gold_v2.py + make semantic-gold-v2-validate
4. agreement  COMMAND_NOT_IMPLEMENTED → tạo measure_semantic_agreement_v2.py + make semantic-gold-v2-agreement
5. adjudicate (thủ công bởi C trên adjudication.jsonl) + validate lại — không cần tool riêng
6. seal       COMMAND_NOT_IMPLEMENTED → tạo seal_semantic_gold_v2.py + make semantic-gold-v2-seal
7. export     COMMAND_NOT_IMPLEMENTED → tạo export_canonical_v2_semantics.py + make semantic-parser-v2-export
8. evaluate   COMMAND_NOT_IMPLEMENTED → tạo evaluate_semantic_gold_v2.py + make semantic-gold-v2-evaluate
(tham khảo: make semantic-gold-v2-local-e2e ✅ EXISTS — chỉ cho LOCAL_SYNTHETIC lane)
```

5 tool mới đều là **tách/tái dùng code đã có** trong `semantic_gold_v2_local.py` — effort ước lượng 1-2 ngày, không phải viết mới từ đầu.

## M. Risks

1. **Roster là blocker thật và duy nhất không mua được bằng code** — A/B/C phải là 3 người không phát triển parser. Rủi ro cao nhất: để lâu không tuyển được rồi "tạm" tự annotate → toàn bộ giá trị sụp về LOCAL bias. Mitigation: bootstrap lane chỉ trên pilot-QIDs nhiễm, dán nhãn `HUMAN_SINGLE_NONPROMOTABLE`.
2. **Vocabulary mỏng (39 concepts)** → UNRESOLVED tràn, headline mất denominator (synthetic dry-run: 70/120 phrase không match). G-12 phải xong trong calibration — sau freeze thì không mở rộng được nữa.
3. **Guideline SHA nằm trong attestation** → mọi chỉnh sửa sau khi A bắt đầu là re-annotate. Vì vậy pilot phải thật (không hình thức) và freeze phải muộn nhất có thể trước final pass.
4. **Metric-concept gate bất khả thi với commit pinned** (finding A-3) — không phải lỗi gold; ghi rõ vào phase-decision để tránh diễn giải "gold thất bại".
5. **Diagnostic n=20 (1-4/stratum)** — chỉ đọc định tính, cấm cộng vào headline (plan đã cấm; nhắc lại vì đây là chỗ dễ bị "tiện tay" nhất).
6. **Agreement thấp thật sự** ở operand-role cho câu nested (kinh nghiệm v1: 6/40 full-agreement) — checkpoint 0.85/0.85/0.70 đã có; nếu vỡ, sửa guideline chứ không hạ ngưỡng.
7. **Contamination gián tiếp qua evidence**: evidence CSV cho thấy row label ≈ "gợi ý metric của corpus". Chấp nhận được (guideline §1 đã giới hạn mục đích) nhưng access_log phải ghi để audit sau.
8. **Hai packet cũ dễ dùng nhầm** — đánh dấu SUPERSEDED ngay.

## N. Final recommendation

**Protocol duy nhất được chọn: Option B (A/B độc lập + C adjudicate, seal 100-150) trên hạ tầng packet hiện có, sau khi sửa G-10/11/12, pilot từ pool nhiễm (G-13), và implement 5 tool thiếu.**

Vì sao không Option A (một người): registry và lịch sử dự án chính là bằng chứng chống lại nó — semantic gold v1 40 records một-nguồn cho 6/40 full-agreement khi recheck, promotion_eligible = 0, và mọi tài liệu từ 27/08 đều bị chặn ở "gold nhiễm/không độc lập". Một người thứ hai không phải chi phí thủ tục — nó là **phép đo duy nhất cho câu hỏi "guideline có định nghĩa được sự thật không"** (agreement). Option A chỉ sống ở bootstrap lane: 1 annotator ngoài, pilot QIDs, nhãn HUMAN nhưng non-promotable, mục đích duy nhất là thử guideline sớm trong lúc tuyển đủ roster.

Về kích thước (STEP 16): **giữ nguyên 100/20/30 — không sửa sampling manifest.** 100 headline đủ cho decision rule dạng point-estimate đã preregister (≥0.95/≥0.95/≥0.90) kèm Wilson CI báo cáo trung thực; muốn claim CI-backed ≥0.95 thì cần n≥300 — không đáng chi phí ở Phase 1.5, vì mục tiêu là **phân ranh parser-vs-resolver**, không phải công bố học thuật. Reserve 30 chỉ kích hoạt theo 4 lý do đã ghi ở guideline §13, có amendment trước khi nhìn prediction.

Thứ tự thực thi: **(1)** G-10/11/12 + 5 tool + guideline v2 → **(2)** re-prepare packet → **(3)** tuyển roster (bắt đầu NGAY, song song với 1-2) → **(4)** pilot → freeze → **(5)** final A/B → agreement → adjudicate → **(6)** seal → export → evaluate → phase decision. Bước (3) là đường găng thật — mọi thứ khác cộng lại ~3-4 ngày công engineering, còn (3) là thứ đã chặn dự án từ 27/08 (120-QID reranker cohort cùng cảnh: sealed từ tuần trước, 0 nhãn đến giờ).
