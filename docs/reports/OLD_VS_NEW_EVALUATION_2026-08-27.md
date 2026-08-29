# Đánh giá toàn diện PROJECT_OLD vs PROJECT_NEW

**Ngày:** 2026-08-27 · **Phạm vi:** `Text2Pandas-1` (OLD) vs `text2pandas` (NEW) · **Vai trò:** independent reviewer

---

## 0. Điều kiện đo và giới hạn của báo cáo này

Người dùng yêu cầu mức verify **"Full: test + benchmark + replay"**. **Không đạt được.**

| Hạng mục | Trạng thái | Lý do |
|---|---|---|
| Đọc code, config, docs, artifact | ✅ Hoàn tất | — |
| Chạy `pytest` / `make ci` trên hai repo | ❌ **KHÔNG CHẠY ĐƯỢC** | Sandbox Linux trả `no space left on device`, hỏng ở tầng hạ tầng, không phải lỗi repo |
| Benchmark latency/throughput | ❌ **NOT MEASURED** | Như trên |
| Replay pipeline end-to-end | ❌ **KHÔNG CHẠY ĐƯỢC** | Như trên, **và** NEW không có payload dữ liệu (xem R3) |

**Hệ quả bắt buộc phải nhớ khi đọc:** mọi con số về test-pass, coverage, accuracy, replay trong báo cáo này là **CLAIM do repo tự ghi**, không phải phép đo độc lập của reviewer. Những gì được xác minh trực tiếp là **cấu trúc code, hợp đồng, và nội dung artifact đã ghi trên đĩa** — những thứ này gán nhãn FACT.

Quy ước nhãn: **FACT** = đọc trực tiếp trong file · **INFERENCE** = suy luận từ FACT · **CLAIM** = repo tuyên bố, chưa kiểm chứng · **UNKNOWN** = chưa đủ dữ liệu.

Xác định phiên bản (FACT): OLD git dừng ở `fbd36c8`, 17/08/2026, worktree bẩn. NEW 118 commit, mới nhất `193dab4`, 27/08/2026, conventional commits.

---

## I. KẾT LUẬN TRƯỚC — 5 con số quyết định

Trước mọi phân tích kiến trúc, đây là dữ kiện định lượng chi phối toàn bộ đánh giá:

| # | Dữ kiện | Nhãn | Nguồn |
|---|---|---|---|
| 1 | OLD có **điểm chính thức thật**: EXECUTION = **0,1225**, submission ID 3392, hạng 28 | **FACT** | `Text2Pandas-1/reports/answer_v2/OFFICIAL_SCORE.json:3,9,11` |
| 2 | OLD phát ra đáp án cho **1011/1012** câu (1 câu `NO_QUERY`) | **FACT** | `Text2Pandas-1/reports/answer_v2/clean_replay.json:6-9` |
| 3 | NEW phát ra **561/1012** (V2) và **269/1012** (V3 r17) | CLAIM | `text2pandas/README.md:11-12` |
| 4 | NEW **chưa có bất kỳ điểm chính thức nào**. `Official Answer Accuracy and Execution Accuracy remain NOT_MEASURED` | **FACT** | `text2pandas/README.md:20-21` |
| 5 | Bằng chứng **accuracy end-to-end** duy nhất của NEW là **14/31 = 45,16%** trên slice tự dán nhãn, và chính báo cáo ghi *"This slice is not the organiser test gold"* | **FACT** | `docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md:154` |

⚠️ **Cảnh báo nguồn số V3:** `README.md:12` ghi V3 = **269 OK / 743 abstain** (r17), nhưng `ACCEPTANCE_TEST_REPORT_2026-08-27.md:158,162` ghi V3 = **207 OK / 805 abstain** (r5). Hai tài liệu **cùng đề ngày 27/08**. Báo cáo này dùng số r17 (mới hơn) nhưng **con số V3 phải coi là chưa ổn định**.

### Phép tính trần điểm — phần quan trọng nhất của báo cáo

Vì abstain được ghi vào file nộp dưới dạng `0.0` (xem §VI-R1), mỗi câu abstain gần như chắc chắn = 0 điểm. Coverage do đó là **trần cứng** của EXECUTION.

**Đọc đúng đại lượng 14/31 — điểm dễ sai nhất.** `ACCEPTANCE…:154` định nghĩa: *"31 evaluable… V2 emits 14 correct and executable answers **on this denominator**. Local Answer Accuracy and Execution Accuracy are both 14/31"*. ⇒ **14/31 là accuracy trên toàn bộ 31 câu, đã bao gồm câu abstain** — **cùng dạng đại lượng với EXECUTION trên 1012 câu**, KHÔNG phải precision-on-emitted. Nhân nó với coverage là **đếm hai lần hình phạt abstain**.

| Engine | Câu phát | **Trần EXEC** (coverage) | Precision cần để **hoà** 0,1225 | **Accuracy local (n=31)** = ước lượng EXEC trực tiếp | Precision-on-emitted (local) |
|---|---:|---:|---:|---:|---:|
| OLD (đã nộp) | 1011 | 0,9990 | — | **0,1225** (đo thật, n=1012) | ≈ 12,3% |
| **NEW V2** | 561 | **0,5543** | 22,10% | **0,4516** | không công bố |
| **NEW V3 r17** | 269 | **0,2658** | 46,09% | **0,1935** | **6/6 = 100%** (`README.md:19`) |

Kiểm tính nhất quán: 0,4516 < 0,5543 ✓ và 0,1935 < 0,2658 ✓ — cả hai ước lượng nằm dưới trần của chính nó, nên nội tại hợp lệ.

Đọc bảng này như sau:

- **NEW V2 có cửa thắng.** Nếu slice n=31 đại diện → EXEC ≈ **0,45**, tức **~3,7× OLD**. Nhưng **caveat phải đọc trước con số**: n=31, Wald CI95 = **[27,6% ; 62,7%]** (±17,5 điểm phần trăm). Cận dưới vẫn trên 0,1225 gấp đôi — nhưng đây là suy luận từ mẫu **3,06% tổng câu hỏi**, và slice này do chính team dán nhãn. **Không phải bằng chứng.**
- **NEW V3 ước lượng 0,1935 — trên 0,1225, không dưới.** *(Đính chính: bản nháp trước của báo cáo này nhân 19,35% với coverage và kết luận V3 "kém OLD 2,4 lần". Đó là lỗi đếm hai lần; kết luận đó bị rút lại.)* V3 vẫn là engine yếu hơn V2 và bị **trần 0,2658 chặn cứng** — nhưng nó **không tệ hơn OLD**, và precision-on-emitted 6/6 cho thấy khi V3 chịu trả lời thì nó trả lời đúng. **Nút thắt của V3 là coverage, không phải precision** — và đó là kết luận có thể hành động được.

> **Kết luận chiến lược:** NEW đánh đổi **coverage lấy precision**. Dữ liệu hiện có **ủng hộ** cược này (cả hai engine ước lượng trên OLD), nhưng toàn bộ bằng chứng nằm trên **31 bản ghi tự dán nhãn**. Cược có vẻ đúng — nhưng vẫn là **cược chưa lật bài**.

---

## II. PHÂN TÍCH PROJECT_OLD — baseline

### 1. Architecture

**Kết luận: kiến trúc sạch chỉ là lớp sơn; sản phẩm thật nằm ở `tools/`.**

| Khía cạnh | Phát hiện | Nhãn |
|---|---|---|
| Layering | Có `domain/application/infrastructure/interface`, nhưng **6 slot rỗng** (`application/ports/`, `infrastructure/{llm,sandbox,storage}/`, `interface/api/`, `domain/entities/` — chỉ `.gitkeep`) | FACT |
| Vi phạm nặng nhất | `domain/rules/table_features.py:25` import `text2pandas.infrastructure.parsing.html_table` — tầng trong cùng phụ thuộc tầng ngoài cùng | FACT |
| Vi phạm thứ hai | `answer_pipeline/adapters.py:18-20` **chèn `sys.path` để import từ `tools/measure_v4`** ⇒ package không cài đặt độc lập được | FACT |
| Cưỡng chế | `pyproject.toml:52` chỉ là **comment**. Không import-linter, không CI | FACT |
| **Điểm nối production thật** | `tools/answer_a6/06_dong_goi.py` **vá một ZIP cũ**: đọc `submission_P0G2.zip` (`:11`), ghi đè `answer`/`pandas_query`/`evidence` từ JSONL (`:43`), **đóng băng `relevant_tables`/`relevant_docs`** — thay đổi là abort (`:46-50`) | FACT |

**Hệ quả của điểm nối vá-ZIP:** trường `relevant_docs`/`relevant_tables` của mọi bài nộp OLD là **kế thừa từ tổ tiên**, không được sinh lại. Đó là lý do `delta_vs_parent.tables_f2 = 0.0` (`OFFICIAL_SCORE.json:24`) — grader đã xác nhận retrieval byte-identical.

**Có 5 thế hệ sinh đáp án cùng tồn tại, không cái nào bị xoá** (FACT): `tools/answer_v2/`, `tools/answer_v3/`, `tools/answer_a6/`, `tools/so_hoc/`, `src/text2pandas/answer_pipeline/`. Cái có thiết kế tốt nhất (`answer_pipeline`, có reason code + eval sandbox) **chỉ được gọi từ script đo lường**, chưa bao giờ ship.

### 2. Code Quality

- **Không hardcode path tuyệt đối** (FACT — grep `/Users/`, `/home/` trong `src/` và `tools/`: 0 hit thật). Điểm cộng thật.
- **Nhưng hardcode artifact identity trong đường ship**: `tools/answer_a6/06_dong_goi.py:11-16` ghim cứng `submission_P0G2.zip` → chỉ sinh được đúng một candidate. Đây là lý do tồn tại **6 packager gần trùng nhau** (`answer_a6/06`, `answer_a6/07`, `answer_v2/03`, `answer_v3/02`, `so_hoc/07`, `execution/dong_goi_tat_dinh.py`).
- **Magic number mâu thuẫn**: `run_pipeline.py:68-69` nhận `n_docs=5` rồi `:122` lại cắt `hits[:5]` bằng hằng số riêng, bỏ qua tham số — đúng loại lỗi mà `CLAUDE.md §4` cấm.
- `.gitignore` 187 dòng có trầm tích rõ: `__pycache__/` khai 2 lần, `.DS_Store` 3 lần, `_TO_DELETE/` 6 lần (FACT).

### 3. Functionality

Làm được: build Silver từ corpus `.txt` (1.973 báo cáo → 146.246 bảng → 2,6M observation), retrieval S0/S1/S2 bằng BM25, sinh đáp án tra-cứu-một-ô + số học đơn giản, đóng gói ZIP.

**Giới hạn cấu trúc — điều quan trọng nhất về OLD** (FACT): `answer_pipeline/router.py:48`

```python
common = dict(metric_id=frame.metric_id, basis=frame.basis, entity=frame.entity)
```

dict này được splat vào **mọi** operand slot, và `metric_id` là scalar `Optional[str]` (`frame.py:129`). ⇒ tử số và mẫu số **buộc phải cùng metric**. Debt/Equity **không biểu diễn được về mặt cấu trúc**. `OperationIR` là `op + tuple phẳng` (`ir.py:80-89`), không đệ quy ⇒ **độ sâu tối đa = 1**.

Số liệu tương ứng (FACT, `reports/answer_v2/route_report_1012.json:6-27`): `HAI_TANG_CHUA_HO_TRO` = 125 câu, `DIEU_KIEN_CHUA_HO_TRO` = 43 câu. Chỉ **10/1012** câu từng vào route R2, 6 thành công.

### 4. Performance

**NOT MEASURED.** Không tìm thấy benchmark latency/throughput/memory nào trong repo OLD.

### 5. Correctness

- 80 file test, **1.059 hàm test**, **không có `conftest.py`**, `tests/{unit,integration,regression,fixtures}/` chỉ chứa `.gitkeep` (FACT).
- **20/28 điểm skip biến mất khi thiếu artifact** — và đó chính là các test kiểm determinism, fail-closed, corpus-freeze (FACT: `test_rc20_fail_closed.py:116,131,157`, `test_rc2_023_corpus_freeze.py:130`, …). **Test xanh trên checkout sạch không chứng minh gì.**
- 4 `xfail(strict=True)` mã hoá bug đã biết về entity resolution (`test_entity_resolution_trace.py:195-219`).
- Trung thực đáng ghi nhận: `reports/type_audit_v1.json:42` tự ghi *"Số câu CHẮC CHẮN sai vì sai kiểu (268) lớn hơn số câu đang đúng (~124)"*.

### 6. Reliability

Cổng tự chặn hoạt động thật: `reports/submission_gate_v1.json:9` = `"VERDICT": "HOLD_KHONG_NOP"`, với quy ước `"NOT_MEASURED ≠ PASS"` (`:4`) và một cổng **không thể mở được về mặt cấu trúc** (`:13` — "Gán hết 60 nhãn vẫn đỏ"). Đây là kỷ luật đo lường tốt hơn phần lớn dự án nghiên cứu.

Nhưng: RC1 **không tái hiện được** — revision nguồn `0450088ab2…` không resolve trong repo, đã ghi `RC-01 = WAIVED_WITH_EVIDENCE` (`HANDOFF.md:21,230`). Môi trường đóng băng `NOT_VERIFIED` (`:17`).

### 7. Developer Experience

**Kém, có bằng chứng cứng:**

- **Không có CI.** `.github/` không tồn tại (FACT). `mypy strict` và `ruff` được cấu hình nhưng không bao giờ chạy tự động.
- **Cả hai lệnh quick-start trong README đều chết**: `tools/run_submission` không tồn tại; `src/api/app` không tồn tại (FACT).
- **≥5 bản sao source tree nằm trong chính tree**: `artifacts/rc2/handoff/data_pipeline_source_c3529fe/`, `sync_122_1/source/`, `sync_122_2/`, `reports/p0/*/source_p0/`, `source_v2/` ⇒ mọi lệnh grep toàn repo đều nhân hit lên nhiều lần (FACT).
- **≥67.822 file** trong tree, gồm 2 virtualenv trên đĩa và 3,2 GB ZIP.
- **Đánh số doc đụng độ**: ba file mang số 97, hai file mang số 82; chuỗi 1–43 nằm ở `to_read/` còn 44–163 ở `docs/` ⇒ trích dẫn "doc 97" là **nhập nhằng** (FACT).

---

## III. PHÂN TÍCH PROJECT_NEW

### Thay đổi kiến trúc — và mục tiêu của từng thay đổi

| Component mới | Tồn tại để làm gì | Bằng chứng hiệu quả |
|---|---|---|
| `domain/semantic/ast.py` (378 LOC) | Thay IR phẳng depth-1 bằng **AST đệ quy có kiểu** | FACT: `Expression` là type alias tự tham chiếu (`:131-142`); `MetricRef` mang `metric_id`/`entities`/`periods`/`basis` **riêng** (`:29-41`) ⇒ hai operand độc lập |
| `application/execution/` (1.014 LOC) | Thực thi typed + đại số đơn vị, `Decimal` end-to-end | FACT: `quantities.py:16-31,53-76` — `SCALE_UNKNOWN`, `CURRENCY_MISMATCH`, `DIMENSION_MISMATCH`, `percent − percent → PERCENT_POINT`, MULTIPLY chỉ hợp lệ khi một vế là RATIO |
| `application/binding/binder.py` | Bind **liên kết** thay vì greedy từng slot | FACT: beam width 64 (`:22,65`), abstain `AMBIGUOUS_BINDING` khi hoà không tương đương ngữ nghĩa (`:71-83`) |
| `infrastructure/sandbox/query.py` (123 LOC) | Sandbox thực thi pandas query | FACT: AST **whitelist** 28 node type, builtins rỗng, attribute chỉ `.values`, cap 10.000 ký tự |
| `semantic_v3_readiness.py` | Cổng promotion fail-closed | FACT: `:174-195` biến `None` thành blocker `NOT_MEASURED:*` |
| `.github/workflows/ci.yml` | CI thật (OLD không có) | FACT: `--require-hashes`, `make ci`, `git diff --check`, least-privilege token |
| `tests/conftest.py` | Cưỡng chế allowlist skip | FACT: `:43-71` — skip không nằm trong `approved_skips_v1.yaml` ⇒ `session.exitstatus = TESTS_FAILED` |
| `tools/retrieval/train_linear_reranker.py` | S3 reranker học được | ⚠️ Xem §VII — chưa promote, có leakage, không tái lập được |

### "Why does this component exist?" — các câu KHÔNG trả lời được

| Component | Vấn đề |
|---|---|
| `application/ports/` | **File rỗng 0 byte.** `application/README.md:3-8` mô tả 3 port `LLMPort/StoragePort/SearchPort` **không tồn tại**. 12+ usecase import thẳng `infrastructure`. → **QUESTIONABLE** |
| `domain/entities/`, `infrastructure/llm/`, `infrastructure/storage/`, `interface/api/` | **4 package rỗng hoàn toàn.** Cây thư mục hứa nhiều hơn code có | 
| `application/usecases/run_pipeline.py` (175 LOC) | **Dead code** — không module nào import, không nối vào CLI |
| `build_silver.py` + `build_catalog.py` | Chạy nhánh `"legacy-build"` (`main.py:49-52`), **không sinh ra `silver.db` mà `cmd_run` đọc**. Nhánh dữ liệu thứ hai song song, không nuôi production |

---

## IV. OLD vs NEW — SO SÁNH TRỰC TIẾP

| Dimension | OLD | NEW | Change | Evidence | Verdict |
|---|---|---|---|---|---|
| **Architecture** | Layer trang trí, 6 slot rỗng, `src/` không phải sản phẩm | Layer vẫn hở (domain→infra, ports rỗng) nhưng **production thật sự chạy qua `src/`** | ↑ | `canonical_run.py:519,608-670` vs `tools/answer_a6/06_dong_goi.py:43` | **BETTER** |
| **Correctness** | EXEC 0,1225 đo được; 268/1012 sai kiểu | Chưa có điểm; 14/31 local | ↔ | `OFFICIAL_SCORE.json:11` vs `README.md:20-21` | **NOT ENOUGH EVIDENCE** |
| **Accuracy** | 0,1225 (đo thật, n=1012) | ước lượng 0,4516 (V2) / 0,1935 (V3), **n=31**, CI95 rất rộng | ↑? | §I | **NOT ENOUGH EVIDENCE** |
| **Performance** | NOT MEASURED | V3 xử lý 1012 câu / 63,22s (CLAIM) | ? | `ACCEPTANCE…:158` | **NOT ENOUGH EVIDENCE** |
| **Reliability** | Cổng tự chặn tốt; RC1 không tái hiện | Promotion gate cưỡng chế bằng code; ZIP tất định **có test byte-level** | ↑ | `test_submission_contract.py:59-65` | **BETTER** |
| **Maintainability** | 67k file, 5 bản sao tree, docs đụng số | 1 namespace, `experiments/` tách bạch, conventional commit | ↑↑ | Glob cả hai | **SIGNIFICANTLY BETTER** |
| **Scalability** | IR phẳng depth-1, metric dùng chung | AST đệ quy, binder beam 64 | ↑↑ | `ast.py:131-142` vs `router.py:48` | **SIGNIFICANTLY BETTER** |
| **Testability** | Không conftest, không CI, skip nuốt gate | conftest + allowlist skip + CI + 1.276 test fn | ↑↑ | `conftest.py:43-71`; `.github/workflows/ci.yml` | **SIGNIFICANTLY BETTER** |
| **Observability** | reports/ + identity/ phong phú | manifest + provenance + run-id bất biến | ↑ | `AGENTS.md:91` | **BETTER** |
| **Developer Experience** | 2 lệnh README đều chết | README khớp CLI thật (9 lệnh) | ↑↑ | `main.py:819-886` | **SIGNIFICANTLY BETTER** |
| **Data quality** | Có payload đầy đủ (work.db 4,24 GB, corpus, ZIP) | **0 file `.db`, 0 file `.zip`, corpus chỉ còn manifest** | ↓↓ | Glob `**/*.db` trên NEW → 0 | **SIGNIFICANTLY WORSE** |
| **Security** | `eval()` **không AST validation** | AST whitelist + zip-slip guard + bỏ `extractall` | ↑↑ | `answer_pipeline/pipeline.py:95-101` vs `sandbox/query.py:20-96` | **SIGNIFICANTLY BETTER** |
| **Complexity** | 5 thế hệ answer song song | vẫn ~10 cặp logic trùng V2/V3 + 63,3% LOC là legacy | ↔ | §VII | **SAME** |
| **Documentation** | 171 file (169 trong `docs/*.md` + 2 archive), hỗn loạn, đụng số | 20 file, sạch — nhưng **mất ~88% tri thức chẩn đoán** | ↔ | §VI-R6 | **SAME** (đổi loại vấn đề) |
| **Reproducibility** | RC1 WAIVED, môi trường NOT_VERIFIED | hash-locked env + CI, **nhưng artifact không có trên đĩa** | ↑ | `README.md:89-97` | **BETTER** |

---

## V. IMPROVEMENT INVENTORY

### Improvement 1 — AST ngữ nghĩa đệ quy thay IR phẳng ⭐ giá trị cao nhất

- **Old problem:** `router.py:48` ép mọi operand dùng chung `metric_id` ⇒ tỷ số hai chỉ số khác nhau **không biểu diễn được**. **288/1012 (28,5%) bất khả thi theo thiết kế** (`Text2Pandas-1/docs/143_NUT_THAT_GOC_TANG_DAP_AN.md:12-14`), phân rã theo **lớp chồng lấn** (`:82`): 224 câu cần ≥2 metric, 125 câu hai tầng, 50 câu có điều kiện — **các lớp này giao nhau, không cộng dồn thành 288**.
- **New solution:** `Expression` tự tham chiếu với 9 node biểu thức + 4 node vị từ; `MetricRef` mang scope riêng.
- **Technical impact:** trần kiến trúc 71,5% bị **gỡ bỏ**. Lớp hai-tầng (125 câu) từ *"không có emitter"* thành **có implement và parser với tới được** (`parser.py:504-571` `_select_at_arg_roles`).
- **Measured benefit:** ⚠️ **KHÔNG CÓ.** Không phép đo nào cho thấy 288 câu này được trả lời **đúng**. Trần được gỡ, không có bằng chứng nào được chuyển thành điểm.
- **Complexity cost:** +5.377 LOC chỉ V3 dùng (16,2% repo), đóng góp **0%** cho bài nộp hiện hành.
- **Regression risk:** thấp — V3 ở shadow mode, không đụng V2.
- **Verdict:** **HIGH VALUE — nhưng UNPROVEN.** Đây là cải tiến đúng hướng nhất của toàn bộ dự án; nó chưa được biến thành điểm.

### Improvement 2 — Đóng lỗ hổng RCE ⭐ giá trị cao

- **Old problem:** `answer_pipeline/pipeline.py:95-101` gọi `eval(query, safe, ns)` với `safe = {"__builtins__": {…7 tên…}}` và **không có AST validation**. Strip builtins **không phải sandbox**: `().__class__.__bases__[0].__subclasses__()` chạm tới `os` mà không cần builtins.
- **New solution:** `infrastructure/sandbox/query.py` — whitelist 28 AST node, không `Lambda`/comprehension/`Pow`/`Import`, `Name` phải thuộc `frames`∪`_FUNCTIONS`, attribute **chỉ `.values`**, constant chỉ `str|int|float`, cap 10.000 ký tự.
- **Measured benefit:** không tìm thấy đường escape trong grammar này (FACT, đã rà `__class__`/`__subclasses__`/`__globals__`).
- **Verdict:** **HIGH VALUE.** Đây là **net-new defense**, không phải refactor — thư mục `infrastructure/sandbox/` của OLD là stub rỗng.

### Improvement 3 — CI + kỷ luật skip ⭐ giá trị cao

- **Old problem:** không CI; skip không quản lý; 20/28 điểm skip nuốt đúng các cổng determinism/fail-closed.
- **New solution:** 2 workflow; `conftest.py:38-71` fail session khi có skip ngoài allowlist 10 mục / tổng 42.
- **Complexity cost:** thấp (77 dòng conftest + 37 dòng YAML).
- **Verdict:** **HIGH VALUE.** Delta lớn nhất về engineering maturity.

### Improvement 4 — ZIP tất định: từ *khẳng định* thành *được test*

- **Old:** writer tất định tồn tại (`tools/execution/dong_goi_tat_dinh.py:16-34`) nhưng **packager ship không dùng** — `06_dong_goi.py:52-68` dùng `writestr`/`write` trần, tức để `zipfile` đóng dấu `time.localtime()` mặc định. Cổng byte-level `test_h0_gates.py:198-203` đọc `determinism_report_v2.json` mà **không file nào trong repo ghi ra**.
- **New:** `_ZIP_TIME` ghim + `ZipInfo` + mode `"x"` (từ chối ghi đè) + sort theo qid, và **test so sánh byte thô của hai build** (`test_submission_contract.py:59-65`).
- **Verdict:** **HIGH VALUE.**

### Improvement 5 — Held-out cohort được seal + cổng thống kê tiền đăng ký

- **Old:** giao thức đúng đã viết ra nhưng `"trang_thai": "CHUA_CHAY"` (`fresh_audit_protocol_v2.json:15`).
- **New:** 120 QID chọn bằng `sha256(f"{SEED}:{qid}")`, packet chỉ chứa `{id, question}`, checksum ghim, drift check; cổng tiền đăng ký n≥100 · mean Δ≥0 · **bootstrap CI95-low ≥ 0** · protected-slice ≥ −0,01.
- **Verdict:** **HIGH VALUE về machinery — nhưng có lỗ hổng nghiêm trọng, xem §VII-OE4.**

### Improvement 6 — Trả nợ xfail

4 bug entity-resolution mã hoá bằng `xfail(strict=True)` ở OLD đã được **sửa thật** ở NEW; test giờ assert hành vi **đúng** (`test_entity_resolution_trace.py:100,107,145,168`). **MEDIUM VALUE**, nhưng là dấu hiệu tốt về văn hoá.

### Improvement 7 — 6 engine trả lời mới, nối thật vào production

`pipelines/answering/` thêm `formula_engine.py`, `count_engine.py`, `entity_{sum,difference,average,count}.py`, gọi từ `canonical_run.py:608-670`. Đây là số học/đa-thực-thể mà OLD chỉ có rời rạc trong `tools/so_hoc/`. **HIGH VALUE.**

### Improvement 8 — Decimal end-to-end

`Decimal(str(value))` (`executor.py:99`) tránh round-trip float nhị phân. OLD **có** import `Decimal` nhưng đổ về float ngay tại biên số học (`tools/so_hoc/02_engine.py:100-102` `-> float`, `:318` `_chia(a: float, b: float)`).

⚠️ **Không tìm thấy bằng chứng Decimal sửa được defect cụ thể nào.** Lỗi số đã ghi nhận của dự án là `parse_vn_number` (`"1.234.567"` qua `float()` kiểu Anh → sai 1000×) — lỗi **parse**, không phải lỗi tích luỹ. Ở biên độ 10⁹–10¹² VND với ≤3 phép tính, float64 còn ~15 chữ số nghĩa. **Verdict: MEDIUM VALUE** — chính đáng như quyết định về kiểu và truy vết, **không nên bán như một bản vá độ chính xác.**

---

## VI. REGRESSION ANALYSIS

Trước hết, **đính chính một giả định thường gặp**: `tools/` **không mất file nào**. 238 − 25 (chuyển sang `experiments/retrieval/`) + 8 (mới) = 221 = số file `.py` trong `tools/` của NEW (FACT). `answer_a6`, `so_hoc`, `answer_v2/v3`, `gold_*`, `funnel`, `measure_v4`, `execution`, `evalkit` đều còn đủ. Shim `data_pipeline`/`retrieval` re-export đầy đủ qua `sys.modules[__name__] = import_module(...)`. CLI giữ đủ 7 subcommand cũ + 4 lệnh mới. **⇒ Regression về inventory CODE và API: KHÔNG TÌM THẤY.**

⚠️ Đừng đọc câu trên thành "không có regression". **Code còn đủ nhưng KHÔNG CHẠY ĐƯỢC** — mất payload, mất gold, mất mốc điểm. Regression thật nằm ở **runnability, độ phủ, và bằng chứng**:

| # | Case | OLD | NEW | Severity | Root cause | Evidence |
|---|---|---|---|---|---|---|
| **R1** | **Số câu phát ra đáp án** | **1011/1012** | **561/1012** (V2), 269 (V3) | **BLOCKER** | Đổi triết lý sang fail-closed; nhưng `answer: 0.0` khi abstain ⇒ abstain **không phải là không trả lời**, mà là **trả lời 0.0** | `clean_replay.json:6` vs `submission.py:104` |
| **R2** | **Điểm chính thức** | 0,1225 (ID 3392, hạng 28) | **không có** | **BLOCKER** | Refactor chưa qua leaderboard | `OFFICIAL_SCORE.json:3,11` vs `README.md:20-21` |
| **R3** | **Payload dữ liệu** | work.db 4,24 GB, silver.db, corpus 1973 `.txt`, 68 ZIP | **0 `.db`, 0 `.zip`**, corpus chỉ còn `manifest.json` | **BLOCKER** | `.gitignore:32-40,54,59` | Glob `**/*.db` và `**/*.zip` trên NEW → 0 file |
| **R4** | Đường sinh bài nộp OLD chạy được ở NEW | ✅ | ❌ — cả 3 input đều không tồn tại | **BLOCKER** | Hệ quả R3 | `tools/answer_a6/06_dong_goi.py:11-16` trỏ `artifacts/submissions/legacy/`, `data/curated/dev-legacy/` — **không tồn tại** |
| **R5** | Gold set `data/dev/` (~35 file) | ✅ | **mất 100%** | **HIGH** | Migration khai mapping nhưng đích không được whitelist | `provenance/folder_migration_20260825.json` khai `data/dev → data/curated/dev-legacy`, thư mục rỗng. **Dangling refs sẽ nổ**: `configs/evaluation/gold_registry_v1.yaml`, `tests/test_answer_gold_provenance.py:12` (không có guard skip) |
| **R6** | Tri thức chẩn đoán | **171** file `.md` | **20** file (−88%) | **HIGH** | Refactor không mang docs sang | Doc 91/96/97/142/143/147/154 — **không có bản kế thừa nào**; chỉ còn TÊN trong `provenance/identity/source_identity.json:89,96` |
| **R7** | Comment code trỏ vào doc đã mất | Doc tồn tại | Doc mất, comment còn | **HIGH** | Hệ quả R6 | `tools/answer_v2/operand_binder.py:4` — *"ĐÂY LÀ CHỖ SỬA NÚT THẮT GỐC (doc 143 §1.1)"*; `src/text2pandas/domain/values/document_id.py:17` — *"Xem RULES_SOURCES.md [D-R04]"* — **file không tồn tại ở NEW** |
| **R8** | ADR | **31** | **11** (đều là quyết định refactor mới, không phải bản kế thừa của 31 ADR cũ) | **HIGH** | Phần lớn ADR cũ không có bản kế thừa | Mất ADR-015 dual-path+arbiter, ADR-017 adaptive N, ADR-018 bảng-là-đơn-vị-truy-hồi, ADR-030 cổng kích hoạt định lượng… |
| **R9** | ADR-024 bị đảo ngược **mà không tham chiếu tới nó** | ADR-024: dữ liệu ngoài **được phép**; corpus-first là quyết định *chất lượng* — supersede ADR-022 | `docs/adr/0009-corpus-only-data-policy.md` quay lại corpus-only | **MEDIUM** | Thiếu lịch sử quyết định | ⚖️ **Cần công bằng:** `docs/competition/README.md:9-13` **nêu rõ** mâu thuẫn trang 4 vs trang 12 và nói áp dụng cách hiểu chặt *"cho tới khi ban tổ chức có văn bản làm rõ"* ⇒ **đây là quyết định có ý thức, có ghi lý do**, KHÔNG phải "coi một bản chụp là chân lý tuyệt đối". Regression thật là hẹp hơn: NEW không biết ADR-024 tồn tại, nên **không thể ghi `Superseded by`** — mất chuỗi lịch sử, không phải mất sự cẩn trọng |
| **R9b** | Bảng "Những lỗi đã xảy ra" | `Text2Pandas-1/CLAUDE.md:75-81` — 7 lỗi đã xảy ra kèm cách phòng tránh, gồm bài học *"phân biệt luật BTC với quyết định của team"* | **không có bản kế thừa** | **HIGH** | Refactor không mang docs sang | Đây mới là mất mát thật sự nguy hiểm — nó là bộ nhớ thể chế |
| **R10** | Nguồn chân lý thể lệ | `RULES_SOURCES.md` + `COMPETITION_SPEC.md` + `docs/sources/` (2 bản chụp mâu thuẫn) | **cả 3 không tồn tại**, thay bằng `docs/competition/README.md` (17 dòng) | **HIGH** | — | Glob → 0 kết quả |
| **R11** | `reports/` (OFFICIAL_SCORE, clean_replay, determinism_run, route_report, failure_funnel) | ✅ | **không tồn tại** | **HIGH** | `.gitignore:65` | Thay thế một phần, không tương đương |
| **R12** | Ràng buộc "corpus là `.txt`" | `CLAUDE.md:14` — luật tuyệt đối #4 | chuỗi `.txt` **không xuất hiện trong AGENTS.md** | **MEDIUM** | — | Dấu vết gián tiếp còn ở `domain/values/document_id.py:47-48` |
| **R13** | Chuỗi provenance `build_id` | `build_id = f(sha256(src/data_pipeline/*.py), …)` | `src/data_pipeline/*` giờ là shim 5 dòng ⇒ hash đổi | **MEDIUM** | Đổi namespace | `provenance/retrieval/RETRIEVAL_FREEZE_v1.json:32-33` vẫn ghi đường dẫn cũ `data/dev/gold_v2.jsonl` |
| **R14** | 14 test case cell-reranker | `tests/answer_v2/test_reranker.py` — pytest thu thập | `legacy_reranker_v1.py` — **pytest KHÔNG thu thập** (thiếu tiền tố `test_`) | **LOW** | Đổi tên khi refactor | Wrapper glob `HERE.glob("test_*.py")` (`test_zz_pytest_wrapper.py:35`); guard chống trôi dùng **cùng glob** (`:71`) ⇒ **không thể phát hiện chính lỗ hổng này** |

### R1 mổ xẻ kỹ — vì đây là finding có đòn bẩy cao nhất

`application/usecases/submission.py:104`:

```python
"answer": float(res.answer) if res.answer is not None else 0.0,
```

kèm comment tự thú ở `:102-103`: *"0.0 là giá trị giữ chỗ hợp lệ kiểu float, không phải câu trả lời."* Validator **bắt buộc** số hữu hạn (`:219-224`) — format không biểu diễn được `null`.

**Hệ quả:** 451 (V2) / 743 (V3) "fail-closed abstention" được chấm **y hệt như khẳng định 0.0**. Chúng là **đáp án sai**, không phải đáp án bị giữ lại.

So sánh với OLD (`Text2Pandas-1/src/.../answer.py:214-218`): khi không khớp nhãn dòng, OLD lấy **ô đầu tiên của bảng** làm dự phòng, kèm comment *"Giá trị gần như chắc chắn sai, nhưng bất biến answer == eval(query) phải được giữ"*.

**Vậy 451 câu abstain của NEW và 451 câu đoán bừa của OLD, cái nào tốt hơn?** — **CHƯA ĐO ĐƯỢC.** Hai lập luận đối nghịch, cả hai đều chưa có dữ liệu:

| Ủng hộ **fallback đoán** (như OLD) | Ủng hộ **`0.0`** (như NEW) |
|---|---|
| Ô thật trong bảng đã truy hồi có P(đúng) > 0; hằng số `0.0` chỉ đúng khi đáp án thật = 0 | Chính sách đoán của OLD **đã được đo**: 0,1225 ⇒ **87,7% lần đoán là SAI**. Nó không phải mỏ vàng |
| Không mất gì: `0.0` vẫn là phát bắt buộc | Với câu hỏi chênh lệch/tăng-giảm, đáp án thật **bằng 0** ở tỷ lệ khác 0 — chưa ai đo tỷ lệ đó |

⇒ **Phát biểu đúng:** *"abstain không phải là không trả lời — nó là trả lời `0.0`, và giá trị kỳ vọng của nó so với một fallback rẻ tiền là **CHƯA ĐO**."* (Bản nháp trước kết luận abstain "có khả năng YẾU HƠN" chính sách đoán — kết luận đó vượt quá bằng chứng và bị rút lại; xem M3/C4.)

Cái NEW **chắc chắn** mua được là **nội bộ**: truy vết, mã lý do cho từng thất bại, và khả năng đo precision-on-emitted. Đó là hàng hoá kỹ thuật thật. **Nó không phải là bảo hiểm điểm số.** Và tài liệu NEW không nói rõ điều này — `README.md:9-12` trình bày 451/743 dưới nhãn *"Latest full-corpus result"*, biến coverage thành outcome.

---

## VII. COMPLEXITY vs VALUE

### High value / Low complexity → **KEEP**

| Component | Lý do |
|---|---|
| `tests/conftest.py` + `approved_skips_v1.yaml` | 114 dòng, đóng một lớp false-green |
| `.github/workflows/ci.yml` | ~30 dòng, delta maturity lớn nhất |
| `_write_deterministic` + `_ZIP_TIME` | ~10 dòng, biến determinism từ khẳng định thành test |
| `infrastructure/sandbox/query.py` | 123 dòng, đóng một P0 RCE |

### High value / High complexity → **KEEP nhưng cần justification**

| Component | LOC | Justification hiện có | Còn thiếu |
|---|---|---|---|
| AST + parser + planner + binder + executor (V3) | ~5.377 | Gỡ trần kiến trúc 28,5% | **Chưa một phép đo nào chứng minh nó trả lời đúng hơn.** Đóng góp 0% cho bài nộp hiện hành |
| Promotion gate (`promotion_policy_v3.yaml`) | ~200 | Fail-closed cưỡng chế bằng code | **Phần lớn ngưỡng chưa có đường ống đo** — `main.py:740-750` chỉ truyền **2** metric (`questions`, `replay_mismatches`); phần còn lại mặc định `None` ⇒ biến thành blocker `NOT_MEASURED:*`. `ACCEPTANCE:172` liệt kê **7** metric thiếu |

### Low value / High complexity → **REMOVE / SIMPLIFY**

**OE1 — `pipelines/` chiếm 63,3% LOC và được miễn trừ khỏi mọi gate.**
`Makefile:44-46` chạy mypy strict chỉ trên `domain application infrastructure interface`. 21.038 trong 33.255 LOC nằm ngoài (phần dư ~78 dòng là shim `answer_pipeline/`). "Clean architecture" chỉ áp cho 36,5% code — và trong 36,5% đó, file lớn nhất (`canonical_run.py`, 763 LOC) **chủ yếu là dispatcher ủy thác xuống V2**: `:27-51` gồm 15 câu lệnh import kéo **19 tên từ `pipelines.answering`** và **6 tên từ `pipelines.retrieval`**.

⚠️ **Đính chính so với bản nháp:** câu *"đường production `run` không dùng một dòng logic trả lời nào là code mới"* là **SAI** và bị rút lại. Sáu engine `formula_engine.py`, `count_engine.py`, `entity_{sum,difference,average,count}.py` **chỉ tồn tại ở NEW** (kiểm chứng: grep `answer_formula_question|answer_entity_sum|answer_count_periods` trên toàn repo OLD → **0 hit**) và **được gọi thật** từ `canonical_run.py:608-679`. Phát biểu đúng là: **phần lớn — không phải toàn bộ — logic trả lời trên đường production là code kế thừa V2.**

**OE2 — ~10 cặp logic trùng V2/V3.** Nguy hiểm nhất:

| Chức năng | V2 | V3 | Rủi ro |
|---|---|---|---|
| Parser số VN | `pipelines/a6/number_parser.py` — `parse_number`, `detect_convention`, `_clean`, `_resolve_separators` | `domain/values/vn_number.py` — **cùng 4 tên hàm**, `detect_convention` trả **kiểu khác** (`tuple[str,int,int]` vs `SepConvention`) | Hợp nhất nhầm ⇒ tái hiện đúng lỗi `1.234.567` sai 1000× mà `CLAUDE.md §5` liệt kê |
| Period resolver | `a6/period_resolver.py` + `answering/period.py` | `domain/semantic/types.py` + planner + parser | **Ba** implementation kỳ kế toán |
| Unit resolver | `a6/unit_resolver.py:394` tự thú *"Trần độ lớn — cùng ngưỡng với `number_parser._MAX_MONEY`. Đặt lại ở đây thay…"* | `domain/units/lexicon.py` | Hằng số nhân bản **có chủ ý** |

**OE3 — `application/ports/` rỗng + 4 package rỗng khác.** Chi phí: 0 LOC. Giá trị: **âm** — README mô tả 3 port không tồn tại, gây hiểu sai cho người mới. **⇒ Xoá thư mục hoặc implement.**

**OE4 — Script đánh giá held-out đi vòng qua chính SHA tiền đăng ký của repo.**

`runner.py:183-188` kiểm `sha256(model_file) == cfg.reranker_model_sha256` rồi raise nếu lệch. Nhưng `tools/retrieval/evaluate_reranker_heldout.py:86-87` đặt:

```python
reranker_model_path=str(MODEL.relative_to(ROOT)),
reranker_model_sha256=_sha(MODEL),          # ← sha của chính file đó
```

**Phép kiểm so hash của file với hash của chính nó ⇒ không bao giờ fail được** (FACT, đã đọc trực tiếp cả hai file).

⚠️ **Đính chính so với bản nháp:** SHA tiền đăng ký **CÓ tồn tại** — `configs/retrieval/eval_v1.yaml:138`:
```yaml
reranker_model_sha256: e60a8acea32989a2be37a89cd9cbfbb92b0b4f338ea2be9a299944075e6cebfd
```
kèm comment chính sách ở `:130-132`. Đây là giá trị đã commit vào Git, tức **đã đóng băng công khai**. Vậy đây **không phải** "không có SHA ở đâu cả"; đây là **một script bỏ qua giá trị sẵn có**.

**Rủi ro còn lại là thật nhưng hẹp hơn:** ai train lại `linear_reranker_v1.json` sau khi nhãn về mà **quên cập nhật `eval_v1.yaml`** thì `evaluate_reranker_heldout.py` vẫn chấm model mới, trong khi `runner.py` lẽ ra phải chặn. **Sửa: 1 dòng** — cho `evaluate_reranker_heldout.py` đọc `eval_v1.yaml:138` thay vì `_sha(MODEL)`. Severity: **P2**, không phải P1.

**OE5 — Uplift reranker công bố là số đã bị chọn lọc.** `train_linear_reranker.py:112-118` chọn epoch tốt nhất **theo `dev`**, rồi `:201` **báo cáo chính `dev`** — và `dev` chỉ có **~19 câu** (`:53`, 20% của ~95 gold). Trên train split (n=76) linear **thua**: F2 0,3954 → 0,3931 (`artifacts/reports/reranker_linear_v1_development.json:245,251`). Báo cáo nêu contamination về feature engineering (`QUALITY_8PLUS…:73`) nhưng **im lặng về contamination chọn-epoch-trên-chính-tập-báo-cáo**.
Ghi nhận công bằng: kết luận rút ra vẫn là *"không promote"* — quyết định đúng.

---

## VIII. ARCHITECTURE QUALITY — chấm PROJECT_NEW

| Nguyên tắc | Điểm | Lý do (có bằng chứng) |
|---|---:|---|
| Separation of concerns | **6/10** | Layer tồn tại và có ý nghĩa, nhưng `canonical_run.py` (application) là dispatcher V2; `pipelines/` 63,3% LOC không thuộc layer nào được quản |
| Single responsibility | **6/10** | `parser.py` 1.102 LOC và `cli/main.py` 898 LOC là hai file quá tải; phần còn lại tách tốt |
| Dependency inversion | **2/10** | `application/ports/` **rỗng 0 byte**; 12+ usecase import thẳng `infrastructure`; `domain/rules/table_features.py:25` import `infrastructure` — **ngược chiều tuyệt đối** |
| Modularity | **7/10** | `experiments/` tách khỏi `src/`; shim cô lập; namespace đơn |
| Loose coupling | **5/10** | `canonical_run.py:27-51` có 20 import cứng từ `pipelines` |
| High cohesion | **7/10** | `domain/semantic/`, `application/execution/` gắn kết tốt |
| Explicit contracts | **8/10** | `AGENTS.md` là hợp đồng thật; submission invariants liệt kê rõ; promotion policy là YAML có code cưỡng chế |
| Deterministic execution | **7/10** | ZIP byte-identical **có test**; trừ điểm vì `pipelines/a6/cleaning.py:269` `for ent in set(found): s = s.replace(...)` — **phụ thuộc `PYTHONHASHSEED`**, nằm thượng nguồn toàn hệ thống |
| Testability | **7/10** | 1.276 test fn, conftest, CI, skip governance — nhưng **3 file fixture tĩnh** tổng cộng |
| Extensibility | **8/10** | AST đệ quy + ontology YAML là nền mở rộng thật |
| Observability | **7/10** | manifest/provenance/run-id bất biến tốt; thiếu metric runtime |
| Failure isolation | **8/10** | Fail-closed có mã lý do đặt tên; `AMBIGUOUS_BINDING`, `FORMULA_METRIC_NOT_IN_POOL:*`, `ABSTAIN_PAYLOAD_LEAK` |

**Trung bình: 6,5/10.** Điểm kéo xuống nặng nhất là **dependency inversion 2/10** — một tuyên bố kiến trúc trung tâm không được thực hiện ở bất kỳ đâu và **không có test/linter nào cưỡng chế** (`pyproject.toml:67` chỉ là comment treo cuối file).

---

## IX. ĐÁNH GIÁ AI / ML / RAG

### Data

| | OLD | NEW |
|---|---|---|
| Corpus | 1.973 `.txt`, 121.756 trang, 146.246 bảng, 2.646.976 observation | Chỉ còn `manifest.json` — **payload không có trên đĩa** |
| A6 build | `b3e9684004679ffb` | `c6887fb633374fad`, determinism 2 build cùng 6.775.554.048 byte, SHA `56799c01…` (CLAIM) |
| Point-in-time | Không cơ chế | `configs/datasets/active_snapshot.yaml` — cấm chọn `latest` (`AGENTS.md:89`) ✅ |
| Reproducibility | RC1 **WAIVED** | env hash-locked + CI, **nhưng artifact không có** |

### Retrieval — **không đổi về bản chất**

**FACT:** `pipelines/retrieval/rank_s2.py` của NEW là **cùng file** của OLD, dời chỗ. Cùng trọng số BM25 `(0.0, 0.0, 2.0, 1.0, 4.0, 1.5)`, cùng 7 bonus cấu trúc. Không embedding, không dense, không cross-encoder ở cả hai.

Chất lượng retrieval **NOT COMPARABLE** giữa hai bản, vì 3 lý do:

1. **Khác gold.** OLD headline (hit@1 0,7256; F2@10 0,4748; n=1006) đo trên **gold proxy sinh tự động bằng n-gram**, median |gold| = 8 bảng/câu. NEW (hit@1 0,3474; F2@10 0,3845; n=95) đo trên **gold dán tay**.
2. **Chính file của OLD chứng minh proxy thổi phồng:** trên **cùng 28 câu**, proxy hit@1 = 0,75 (`gold_tay_eval.json:57`) vs gold tay = 0,39285 (`:32`) — **1,9×**.
3. **Khác schema.** NEW là `evalkit-9`, fingerprint `9c5a36f7f0f09fee`; báo cáo của chính NEW ghi *"The schema bump invalidates older checkpoints"*.

Cặp gần apples-to-apples nhất: OLD gold-tay-28 hit@1 **0,3929** vs NEW gold-tay-95 hit@1 **0,3474** — khác tập câu, chỉ mang tính gợi ý.

**S3 reranker mới:** `LinearFeatureReranker` — **13 feature, 13 trọng số, không bias**, train pairwise-logistic (RankNet) 300 epoch. **Uplift đo được = +0,0000** vì production dùng `IdentityReranker` (`ACCEPTANCE…:111`). Model file có, **dữ liệu train không có trong repo** (`data/curated/dev-legacy/gold_v2.jsonl` → 0 file) ⇒ **không tái lập được**.

### Parser / Planner — nơi giá trị thật nằm

Trả lời câu hỏi trung tâm — *"NEW có giải quyết được 288/1012 không biểu diễn được không?"*:

**PARTIALLY. Phân tách chính xác** (ba lớp dưới đây **chồng lấn nhau**, tổng câu bị ảnh hưởng là 288 chứ không phải 399):

| Lớp | n | Biểu diễn được trong AST? | **Parser với tới được từ tiếng Việt?** |
|---|---:|---|---|
| Đa-metric | 224 | ✅ `Arithmetic(MetricRef_a, MetricRef_b)` | ⚠️ **CHỈ qua ontology `FormulaCall`** |
| Hai-tầng | 125 | ✅ `SelectAtArg(Rank(...), expr)` | ✅ **có — cải tiến thật** |
| Điều kiện | 50 | ✅ `Filter` + `Comparison` | ⚠️ chỉ khi có literal số tường minh |

**Giới hạn chịu lực (FACT), `parser.py:235-238`:**

```python
if operation == OperationKind.DIVIDE and not isinstance(base, FormulaCall):
    return "UNREVIEWED_RELATIONAL_FORMULA"
```

Số học đa-metric **chỉ** đi qua template ontology soạn sẵn. Từ vựng này tăng từ **13 formula_id ở OLD** (8 implement) lên **~30 ở NEW** — nhưng vẫn là **danh sách đóng**, với `roe`, `roa`, `interest_coverage`, `cagr` còn nằm trong `needs_domain_confirmation`.

Giới hạn thứ hai, tinh vi hơn: SUBTRACT/GROWTH vẫn là **cùng-metric-qua-hai-scope**, y như OLD (`_binary_scopes`, `:1061-1076` chỉ trả cặp (entity, period)). ⇒ *"doanh thu trừ chi phí"* **không parse được ở NEW nhiều hơn ở OLD**.

Ví dụ kiểm chứng — qid 369 (trung vị nhóm): `AggregateFunction.MEDIAN` **đã implement ở cả executor** (`executor.py:231-233`) **và pandas compiler** (`compiler.py:262-265`) — nhưng **parser không bao giờ phát ra nó**; không quy tắc từ vựng nào ánh xạ *"trung vị"* → MEDIAN. **Vẫn không với tới được.**

> **Kết luận:** trần **kiến trúc** đã được gỡ. Thay vào đó là trần **từ vựng/ontology**. Đây là bài toán tốt hơn nhiều để có (mở rộng YAML là tăng dần; thiết kế lại IR thì không) — nhưng **không phải là đã giải xong**, và không phép đo nào ở cả hai repo cho thấy 288 câu đó được trả lời **đúng**.

### LLM

- OLD: `tools/answer_v2/llm_client.py:39` — `Qwen/Qwen2.5-14B-Instruct` qua HTTP, `temperature=0.0, seed=0`. **Tắt mặc định** (`configs/answer_v2/llm_v1.yaml:20` endpoint rỗng), **không nằm trên đường ship** (0 import từ `answer_a6`/`so_hoc`).
- NEW: **giữ nguyên client đó**, cùng mặc định tắt.
- Claim `AGENTS.md:97` *"tested production path is deterministic and does not require a language model"* — **ĐÚNG như câu chữ** cho `src/text2pandas/**`: grep `llm|Qwen|openai|transformers|torch` → 6 hit, **toàn văn xuôi/comment, 0 import**; grep `requests|httpx|urllib|socket` → 2 hit, đều là từ "endpoint" nghĩa *đầu mút khoảng* trong `parser.py:1026,1028`.
- ⚠️ **SAI nếu đọc là "không chứa model"**: set `ANSWER_V2_LLM_ENDPOINT` là kích hoạt `cell_reranker.rerank()`.
- ⚠️ **Khoảng trống:** **không test nào cưỡng chế** thuộc tính no-model/no-network ở NEW. Nó là chính sách + kiến trúc, không phải cổng. **Đề xuất: thêm một test import-guard 5 dòng.**

### Determinism

**Một điểm phi tất định thật, cả hai repo cùng có** (FACT): `pipelines/a6/cleaning.py:269` (NEW) = `src/data_pipeline/cleaning.py:269` (OLD):

```python
for ent in set(found):
    if ent in _VALID_ENTITIES:
        s = s.replace(ent, _VALID_ENTITIES[ent])
```

Đây **không phải** kiểm tra membership — nó **duyệt** một set chuỗi và **mutate `s`**, nên khi các entity chồng lấn, thứ tự thay thế phụ thuộc thứ tự duyệt set, tức phụ thuộc `PYTHONHASHSEED`. Kết quả chảy vào nhãn dòng/cột của silver → retrieval → đáp án.

**Sửa bằng một từ: `sorted(set(found))`.** Trong một hệ thống mà tuyên bố trung tâm là tính tất định, đây là lỗi cần vá trước tiên.

Phần còn lại (~100 hit `random`/`time`/`set`) đều lành: `time.time()` cho elapsed trong report, `datetime.now()` cho metadata ngoài payload ZIP, `sorted(glob)`, `random.Random` có seed, `next(iter(...))` luôn có guard cardinality-1.

### Evaluation — proxy vs gold

| | Phủ trên 1012 câu |
|---|---|
| OLD — gold retrieval tay | 28 (2,77%) |
| OLD — gold đáp án | 45 (4,45%) |
| **OLD — điểm BTC** | **1012 (100%)** — EXEC 0,1225 |
| NEW — gold retrieval tay | 95 claim (9,39%) — **file không có trên đĩa**, 0% kiểm chứng được |
| NEW — gold ngữ nghĩa | 40 (3,95%), 31 evaluable (3,06%) |
| NEW — held-out retrieval | 120 câu, **0 đã dán nhãn** |
| **NEW — điểm BTC** | **NOT_MEASURED** |

**Proxy bị dùng để tuyên bố correctness không?**

- **OLD: hầu như không**, và kỷ luật đáng nể. Báo cáo mở đầu bằng *"PHỦ CỦA THƯỚC ĐO — đọc mục này TRƯỚC mọi con số khác"*, chú thích ô chưa đo *"không phải 'đúng', là 'không biết'"*. `submission_gate_v1.json:4` cưỡng chế `NOT_MEASURED ≠ PASS`.
- **NEW: có, ở 3 chỗ.** (1) `README.md:9-12` đặt emitted/abstained dưới nhãn *"Latest full-corpus result"* — biến **coverage thành outcome**. (2) Uplift reranker bỏ qua n=19 và bỏ qua delta âm trên train split. (3) *"100% of the proposed engineering and verification mechanisms are delivered"* làm tiêu đề cho một tài liệu tên *"Quality 8+ closure"* — **mechanism-completeness đội lốt quality**.
- Công bằng mà nói, NEW từ chối quy đổi này ở nhiều chỗ khác: *"The remaining 917 questions are NOT_MEASURED, not retrieval successes"*, *"Route coverage is not parser exact match and is not answer accuracy"* (`AGENTS.md:174`).
- ⚠️ **`README.md:28`: "emitted precision improved from 6/9 to 6/6"** — nâng precision bằng cách **chặn bớt 3 lần phát** thì đúng về số học một cách hiển nhiên. Mẫu số 9 rồi 6. Đây không phải bằng chứng cải thiện.

---

## X. TESTING & VALIDATION AUDIT

| | OLD | NEW |
|---|---:|---:|
| File test | 80 | **120** |
| Hàm `def test_` | 1.059 | **1.276** |
| `conftest.py` | **không có** | ✅ |
| CI | **không có** | ✅ 2 workflow |
| Skip governance | không | ✅ allowlist 10 mục / 42 skip, cưỡng chế bằng `session.exitstatus` |
| `xfail(strict=True)` (nợ kỹ thuật) | 4 | **0** (đã sửa thật) |
| **File fixture tĩnh** | **2** | **3** |
| Test coverage % | không đo | **không đo** (`pytest-cov` khai nhưng không dùng) |
| Test cưỡng chế layering | **không** | **không** |

### 1. Test nào thật sự chứng minh correctness?

Có, và chất lượng cao hơn kỳ vọng:

- `tests/unit/test_formula_engine.py` — assert giá trị chính xác (`2.0`, `1.5`, `20.0`, `0.25`, `30_000.0`), assert **công thức nào đã kích hoạt** (`result.formula_id == "current_ratio"`), assert **ô nào được chọn** (`"TỔNG TÀI SẢN CÓ" in result.query`), và assert **mã từ chối chính xác** (`"FORMULA_METRIC_NOT_IN_POOL:interest_expense"`, `"FORMULA_OPERANDS_NOT_COHERENT"`). **File test tốt nhất trong cả hai repo.**
- `tests/execution/test_p0_families_v1.py` — khoá 34 override scale A6 **từng cái một**, kèm comment *"Đếm tổng rồi bảo 'đã sửa' là chưa kiểm gì cả"*, và khoá một **defect của gold** (`SIGN_CONVENTION_GOLD_DEFECT`, qid 760) để không ai "sửa" emitter cho khớp gold sai. **Kỷ luật đo lường mẫu mực.**
- `tests/unit/test_submission_contract.py` — assert **byte-determinism** của ZIP, và một negative test có payload `__import__('os').system('id')`.
- `tests/unit/test_independent_gold.py` — assert việc seal gold **từ chối**: cùng reviewer hai vai → `ValueError`, bất đồng chưa xử → `"unreviewed disagreement"`, có output model → `"model output leaked"`.

### 2. Test nào chỉ chứng minh code chạy?

Khoảng 20 test đọc `src/**/*.py` **như văn bản** rồi assert nội dung: `test_unit_contract.py:189-200` grep `"1000000"|"1e6"|"1e9"` trong source EMITTERS. **Vô hiệu hoá tầm thường** bằng `10 ** 6`. `:221-228` assert không có `qid in {` — `if qid == 42 or qid == 52` lọt qua.
Ngoại lệ tốt: `test_evalkit_metrics.py:209-223` dùng **AST thật** (không phải substring) để khoá một bug đo lường cụ thể.

### 3. Rủi ro kiến trúc không được test

**Không repo nào có import-linting.** `pyproject.toml:67` là comment treo. Đây là **claim kiến trúc lớn nhất của NEW hoàn toàn không được canh gác**.

### 4. Lỗ hổng trong chính cơ chế skip governance

`pytest_runtest_logreport` chỉ bắn cho **test item**. Ba `pytest.importorskip("pandas")` ở **cấp module** (`test_pipeline_e2e.py:15`, `test_percent_point_e2e.py:29`, `test_policy_and_result_kind.py:16`) raise trong **collection** → sinh `CollectReport`, không phải `TestReport`. ⇒ nếu thiếu pandas, **46 hàm test biến mất với 0 vi phạm**. Allowlist mù với chúng.

Thêm nữa: `approved_skips_v1.yaml` tự ghi *"Maximums, not targets"* nhưng 42 **đúng bằng** số skip quan sát được trong cả hai báo cáo ⇒ allowlist được viết **từ output một lần chạy**. Nó chống trôi (không cho thêm skip mới), nhưng **không chứng nhận** rằng 42 skip đó *đáng* được skip.

### 5. Test adversarial — **không cải thiện**

`tests/answer_v2/test_adversarial.py` **giống hệt ở hai repo**, đúng 12 ca. Chất lượng ca thì tốt (alias nuốt tiền tố gây sai hàng chục lần, `SCOPE_MISMATCH`/`PERIOD_MISMATCH`/`ENTITY_MISMATCH`, chặn `x.__class__`/`lambda`/`eval('1')`, `LITERAL_UNSOURCED`, `TYPE_CONTRACT_VIOLATION`) — nhưng đây là **di sản, không phải cải tiến**.

### 6. Lỗ hổng test đáng lo nhất ở cả hai

**Không test nào** assert `parse_vn_number("1.234.567") == 1234567` hay `parse_vn_number("(1.234)") == -1234`, dù `CLAUDE.md §5` gọi tên đúng hai lỗi này là lỗi 1000× và lỗi đảo dấu lịch sử. Họ **có** test lớp lỗi *scale* (34 override, từng cái) — nhưng **không** test lớp lỗi *parse chuỗi*.

---

## XI. PERFORMANCE COMPARISON

| Metric | OLD | NEW | Δ | Improvement % | Evidence |
|---|---|---|---|---|---|
| Latency 1012 câu (V3) | NOT MEASURED | 63,22 s (CLAIM) | — | — | `ACCEPTANCE…:158` |
| Latency 1012 câu (V2) | NOT MEASURED | NOT MEASURED | — | — | — |
| Throughput | NOT MEASURED | NOT MEASURED | — | — | — |
| Memory | NOT MEASURED | NOT MEASURED | — | — | — |
| CPU | NOT MEASURED | NOT MEASURED | — | — | — |
| Storage (A6 build) | NOT MEASURED | 6.775.554.048 byte (CLAIM) | — | — | `ACCEPTANCE…:13,49-50` |
| Startup | NOT MEASURED | NOT MEASURED | — | — | — |
| Test suite runtime | NOT MEASURED | NOT MEASURED | — | — | — |

**Kết luận mục này: KHÔNG SO SÁNH ĐƯỢC.** Không repo nào có benchmark. Reviewer cũng không chạy được do sandbox hỏng. **Không được suy diễn bất kỳ số nào ở đây.**

Điều duy nhất nói được: NEW đặt **giới hạn tài nguyên tường minh** mà OLD không có — `MAX_LONG_ROWS = 50_000` (`answer.py:120`), `_MAX_MEMBER_BYTES = 100 MB` (`submission.py:48`), beam width 64 có cắt cứng (`binder.py:22,65`), query cap 10.000 ký tự. Đó là **thuộc tính thiết kế**, không phải phép đo.

---

## XII. MAINTAINABILITY & OPERABILITY

> **Nếu một developer mới vào project, PROJECT_NEW có dễ hiểu và sửa hơn PROJECT_OLD không?**

**CÓ, rõ rệt — và đây là chiến thắng ít gây tranh cãi nhất của NEW.** Bằng chứng:

| | OLD | NEW |
|---|---|---|
| Lệnh trong README | **cả hai đều chết** (`tools.run_submission`, `src.api.app` không tồn tại) | khớp CLI thật, 9 lệnh |
| Số file trong tree | ≥67.822, gồm **5 bản sao source tree** | không có bản sao |
| Grep toàn repo | hit bị nhân lên nhiều lần vì bản sao | sạch |
| Trích dẫn doc | "doc 97" **nhập nhằng 3 file**; "doc 82" nhập nhằng 2 file | 20 doc, tên rõ |
| Commit | tiếng Việt không quy ước, worktree bẩn | conventional commits, 118 commit |
| Hợp đồng cho agent | `CLAUDE.md` tốt nhưng mâu thuẫn với thực tế | `AGENTS.md` — hợp đồng vận hành nghiêm túc, có thứ tự nguồn chân lý |
| Onboarding | phải đọc 171 doc để biết code thật ở đâu | `README.md` + `AGENTS.md` là đủ để bắt đầu |

**Nhưng có ba cái giá phải ghi nhận:**

1. **Mất 88% tri thức chẩn đoán** (R6). NEW dễ đọc hơn một phần vì nó **quên** những gì OLD học được — trong đó có bảng "Những lỗi đã xảy ra" và cơ chế phân xử hai bản thể lệ mâu thuẫn (R9, R10).
2. **Comment trong code trỏ vào tài liệu không còn tồn tại** (R7). Developer mới đọc `operand_binder.py:4` — *"ĐÂY LÀ CHỖ SỬA NÚT THẮT GỐC (doc 143 §1.1)"* — sẽ đi vào ngõ cụt.
3. **3 tài liệu trạng thái cùng đề ngày 27/08 mâu thuẫn nhau ở 3 con số**: route coverage 669 vs 684; mypy 78 file vs 83 file; baseline V3 r7 vs r17. Chúng có commit stamp khác nhau nên hoà giải được — nhưng người đọc thường sẽ coi là **một snapshot**.

**Rollback / migration:** NEW có `run-id` bất biến, cấm ghi đè stage, mode ZIP `"x"` từ chối overwrite — tốt. **Backward compatibility:** shim `data_pipeline`/`retrieval`/`answer_pipeline` re-export đầy đủ; CLI giữ đủ 7 subcommand cũ. **Không tìm thấy breaking change về API.**

---

## XIII. SECURITY & ROBUSTNESS

| # | Sev | Repo | Vị trí | Phát hiện |
|---|---|---|---|---|
| 1 | **P0** | **OLD** | `answer_pipeline/pipeline.py:95-101` | `eval(query, safe, ns)` **không AST validation**. Strip builtins ≠ sandbox: `().__class__.__bases__[0].__subclasses__()` chạm `os` không cần builtins ⇒ **bất kỳ chuỗi nào tới `execute()` đều là arbitrary code execution**. ⚠️ *Reachability từ input người dùng CHƯA được chứng minh* — query ở đây do máy sinh từ template, không phải người dùng gõ. Xếp P0 vì đây là **lỗ hổng thiết kế** (không có rào), không phải exploit đã chứng minh. ✅ **NEW đã đóng** |
| 2 | **P1** | **OLD** | `application/usecases/submission.py:195-196` | `z.extractall(workdir)` trên ZIP không tin cậy, **không kiểm member path**. `validate_zip` chỉ kiểm "đúng 1 .json" + prefix `data/` — không `..`, không absolute, không symlink, không cap size ⇒ **zip-slip**. ✅ **NEW đã đóng** (`submission.py:154-167` + bỏ hẳn `extractall`, đọc in-memory `io.BytesIO`) |
| 3 | P1 | **CẢ HAI** | `tools/verify_package.py:146`, `tools/measure_v4/run_measurement_closure.py:41`, `run_pipeline_e2e.py:98` | 3 điểm `extractall()` không kiểm member, **giống hệt nhau ở hai repo** |
| 4 | **P2** | **NEW** | `tools/retrieval/evaluate_reranker_heldout.py:87` | **Cổng checksum model là tautology** — so hash file với hash chính nó, không bao giờ fail. SHA tiền đăng ký **có tồn tại** (`configs/retrieval/eval_v1.yaml:138`) nhưng script này bỏ qua nó ⇒ model train lại sau khi nhãn về vẫn lọt. Fix 1 dòng |
| 5 | P2 | **CẢ HAI** | NEW `sandbox/query.py:111`; OLD `pipeline.py:99` | **In-process eval, không cách ly.** Không timeout, không `resource.setrlimit`, không subprocess. Query pandas chậm/khổng lồ treo hoặc OOM tiến trình chủ |
| 6 | P2 | **NEW** | `sandbox/query.py:33,36,46` | **Khuếch đại bộ nhớ trong whitelist**: `ast.Mult` + `Constant(str)` + `Constant(int)` đều cho phép ⇒ `len(df1)*0 + len("a"*999999999)` qua validation, cấp phát ~1 GB trước khi `float()` từ chối |
| 7 | P2 | **CẢ HAI** | `tools/answer_v2/pandas_renderer.py:33-34` | `CAM` là **regex blacklist**, không phải whitelist. Thiếu `vars`, `type`, `help`, `breakpoint`, `memoryview`. Chỉ chấp nhận được vì nó canh `tools/`, không phải đường thư viện |
| 8 | **P2** | **CẢ HAI** | `pipelines/a6/cleaning.py:269` | `for ent in set(found): s = s.replace(...)` — **phụ thuộc `PYTHONHASHSEED`** ở thượng nguồn toàn hệ thống. Fix: `sorted(set(found))` |
| 9 | P3 | NEW | `sandbox/query.py:90` | Guard chết: `if node.attr != "values" or node.attr.startswith("_")` — vế hai không bao giờ tới được |
| 10 | P3 | **CẢ HAI** | — | **Sạch:** 0 `pickle`/`joblib`/`torch.load`/`yaml.load` không an toàn (reranker là **JSON thuần**). 0 `os.system`/`os.popen`/`shell=True`. Subprocess chỉ 2 chỗ, argv `git` cố định + `timeout=10`. 0 secret hardcode. Không SQL injection (tham số hoá đúng). **Không tìm thấy pattern ReDoS** — regex parser dùng lượng từ có chặn (`[a-z0-9 -]{2,100}?`, `[^,?]{0,80}`), không nested quantifier |

**Kết luận: NEW an toàn hơn OLD một cách vật chất.** Một P0 RCE và một P1 zip-slip đã được đóng bằng **phòng thủ mới hoàn toàn** (thư mục `infrastructure/sandbox/` của OLD là stub rỗng). Không hạng mục nào tệ đi. Rủi ro còn lại (#3, #5, #7, #8) hầu hết nằm ở `tools/` — được bê nguyên từ OLD sang.

---

## XIV. MIGRATION / STRANGLER QUALITY

| Câu hỏi | Trả lời | Bằng chứng |
|---|---|---|
| Route cũ còn tồn tại? | **Có** — `pipelines/` = 21.038 LOC = **63,3%** của `src/text2pandas` | Đếm file |
| Route mới có thực sự được dùng? | **KHÔNG cho bài nộp.** `SemanticV3Engine` khởi tạo **đúng 1 nơi**: `interface/cli/main.py:677`, bên trong `cmd_shadow_v3` | Grep toàn `src/` |
| Routing có rõ ràng? | **Có, rất rõ** | `main.py:885-889` dispatch table 11 lệnh |
| Duplicate implementation? | **Có, ~10 cặp** | §VII-OE2 |
| Migration strategy hợp lý? | **Có** — strangler đúng sách: V2 canonical, V3 shadow, promotion gate fail-closed | `AGENTS.md:68-76` |
| Có thể remove old path? | **Chưa** — `REFACTOR_STATUS.md:66-76` ghi Phase 6 (xoá shim/tagging) = **pending** | — |

### **PARTIAL MIGRATION / ARCHITECTURE THEATER?**

Cần phân xử cẩn thận, vì hai câu trả lời khác nhau:

**Về tuyên bố migration: KHÔNG PHẢI theater.** NEW nói thẳng ra ở 4 chỗ (`AGENTS.md:56,70-71`; `README.md:7,292`) rằng V2 là canonical và V3 là shadow. **Tuyên bố khớp code.** Đây là sự trung thực đáng ghi nhận.

**Về ranh giới layer: CÓ theater.** Ba bằng chứng:

1. `application/ports/` **rỗng 0 byte** trong khi `application/README.md:3-8` mô tả 3 port.
2. `domain/rules/table_features.py:25` import `infrastructure` — trong khi `domain/README.md:3` gọi đó là quy tắc bất khả xâm phạm.
3. **63,3% LOC được gắn nhãn "legacy" rồi miễn trừ khỏi mọi cổng** (mypy, layering). ⇒ "clean architecture" chỉ áp cho 36,5% code — và trong 36,5% đó, file lớn nhất (`canonical_run.py`) chủ yếu là dispatcher ủy thác xuống V2.

**Một ước lượng định lượng** (INFERENCE — phương pháp: cộng LOC các module xuất hiện trong import graph của `cmd_run`, **không phải phép đo coverage runtime**): trên đường chạy lệnh `run`, ~**3.690 LOC là code mới** (CLI, orchestration, manifest, I/O, đóng gói) vs ~**4.729 LOC là V2** — tức **~44% mới / ~56% cũ**.

⚠️ Trong ~44% "mới" đó, **có** logic trả lời thật (6 engine mới, xem OE1 đính chính), không chỉ orchestration. Bản nháp trước nói ngược lại và đã bị rút.

---

## XV. FINAL SCORECARD

| Category | OLD | NEW | Δ |
|---|---:|---:|---:|
| Architecture | 3/10 | 6/10 | **+3** |
| Correctness | 3/10 | 4/10 | +1 ⚠️ |
| Performance | — | — | *không chấm — NOT MEASURED cả hai* |
| Reliability | 4/10 | 6/10 | +2 |
| Maintainability | 2/10 | 7/10 | **+5** |
| Scalability | 3/10 | 6/10 | **+3** |
| Testability | 3/10 | 7/10 | **+4** |
| Observability | 5/10 | 7/10 | +2 |
| Documentation | 4/10 | 4/10 | 0 |
| Engineering maturity | 4/10 | 8/10 | **+4** |

*Ghi chú chấm điểm:* **Correctness NEW chỉ +1** — §IV kết luận chiều này là `NOT ENOUGH EVIDENCE`, nên không được thưởng điểm cho tuyên bố chưa chứng minh; +1 là cho việc *cơ chế đo* tồn tại (fail-closed có mã lý do, replay 561/561), không cho *kết quả*. **Documentation = 0** vì §IV kết luận `SAME`. **Observability OLD 5/10** dựa trên `reports/` + `identity/` + seal JSON có thật (§II.6), không phải audit đầy đủ.

**OVERALL OLD: 3,4/10** (31/9)
**OVERALL NEW: 6,1/10** (55/9)

**Nhưng điểm số không phải kết luận.** Có một cột không nằm trong bảng và nó nặng hơn mọi cột khác:

| | OLD | NEW |
|---|---|---|
| **Điểm chính thức trên metric thi** | **0,1225** | **không có** |

Một hệ thống 3,4/10 về kỹ thuật **đã ghi điểm**; một hệ thống 6,1/10 **chưa lật bài**. Điểm engineering là **điều kiện cần** cho điểm thi, không phải điều kiện đủ.

---

## XVI. FINAL VERDICT

### 1. Overall verdict

> ## **NEW IS BETTER BUT NOT READY**

Cụ thể hơn: NEW **rõ ràng tốt hơn về kỹ thuật** (kiến trúc, bảo mật, test, maintainability, năng lực biểu diễn) và **chưa chứng minh được tốt hơn về kết quả**. Đây không phải trường hợp "phức tạp hơn mà không có lợi ích" — lợi ích kỹ thuật là thật và đo được. Đây là trường hợp **lợi ích kỹ thuật chưa được chuyển hoá thành bằng chứng kết quả**.

### 2. Top 10 improvements (xếp theo giá trị thực tế)

1. **AST ngữ nghĩa đệ quy** — gỡ trần kiến trúc 28,5% câu hỏi không biểu diễn được. Giá trị tiềm năng cao nhất toàn dự án.
2. **Đóng P0 RCE** — thay `eval()` trần bằng AST whitelist. Phòng thủ mới hoàn toàn.
3. **CI + skip governance** — từ 0 lên 2 workflow + cưỡng chế allowlist. Delta maturity lớn nhất.
4. **6 engine trả lời mới nối thật vào production** — `formula_engine`, `count_engine`, `entity_{sum,difference,average,count}`.
5. **`src/` trở thành sản phẩm thật** — hết cảnh vá ZIP bằng script trong `tools/`.
6. **ZIP tất định: từ khẳng định thành test byte-level.**
7. **Đóng P1 zip-slip** + bỏ hẳn `extractall` khỏi `src/`.
8. **Joint binder với beam search + abstain khi nhập nhằng** — thay greedy per-slot.
9. **Held-out cohort seal + cổng thống kê tiền đăng ký** (bootstrap CI95) — dù còn lỗ hổng OE4.
10. **Đại số đơn vị typed + Decimal end-to-end** — `PERCENT_POINT`, `CURRENCY_MISMATCH`, `ZERO_DENOMINATOR` là mã lỗi có tên.

### 3. Top 10 remaining problems (xếp theo severity)

1. **Không có bất kỳ điểm chính thức nào.** Mọi tuyên bố "tốt hơn" hiện là suy luận.
2. **Coverage sụt 1011 → 561**, và abstain **được ghi là `0.0`** ⇒ không phải safety, là đáp án sai; giá trị so với fallback **chưa đo** (§VI-R1).
3. **Payload dữ liệu bằng 0** — 0 `.db`, 0 `.zip`, corpus chỉ còn manifest ⇒ **không repo nào chạy được end-to-end ngay lúc này**.
4. **Dependency inversion 2/10** — `ports/` rỗng, `domain` import `infrastructure`, **0 linter/test cưỡng chế**.
5. **`cleaning.py:269` phụ thuộc `PYTHONHASHSEED`** ở thượng nguồn một hệ thống lấy determinism làm tuyên bố trung tâm.
6. **Mất 88% tri thức chẩn đoán** + 20/31 ADR + `RULES_SOURCES.md`, kèm comment code trỏ vào doc đã mất.
7. **Phần lớn ngưỡng promotion chưa có đường ống đo** — `main.py:740-750` chỉ truyền 2 metric; `ACCEPTANCE:172` liệt kê 7 metric thiếu. Gate fail-closed đúng, nhưng chưa có gì để đo.
8. **Uplift reranker công bố là số đã chọn lọc** (epoch chọn trên chính dev n=19, delta âm trên train split bị bỏ qua).
9. **Số V3 chưa ổn định** — 269/743 (README) vs 207/805 (ACCEPTANCE), hai tài liệu cùng ngày.
10. **Cổng checksum reranker là tautology** (`evaluate_reranker_heldout.py:87`) — fix 1 dòng, nhưng để nguyên thì held-out A/B mất giá trị.

### 4. Top regressions

| # | Regression | Severity |
|---|---|---|
| R1 | 1011 → 561 câu phát ra; abstain = `0.0` trên file chấm. **Lưu ý:** đây là regression về *coverage*, không tự động là regression về *điểm* — ước lượng local cho thấy accuracy vẫn cao hơn (§I) | **BLOCKER** (vì chưa đo) |
| R2 | Mất điểm chính thức làm mốc | **BLOCKER** |
| R3/R4 | Mất toàn bộ payload ⇒ không chạy lại được cả OLD lẫn NEW | **BLOCKER** |
| R5 | Mất 100% gold set `data/dev/` + dangling refs sẽ raise `FileNotFoundError` | HIGH |
| R6/R7/R8/R9/R10 | Mất tri thức chẩn đoán, ADR, nguồn chân lý thể lệ; ADR bị đảo ngược | HIGH |
| R14 | 14 test case orphan; guard chống trôi dùng cùng glob nên mù | LOW |

### 5. Top over-engineering risks

1. **`pipelines/` 63,3% LOC miễn trừ khỏi mọi cổng** — "clean architecture" chỉ áp cho 36,5% code.
2. **~10 cặp logic trùng V2/V3** — nguy hiểm nhất là **hai `detect_convention` cùng tên khác kiểu trả về**.
3. **5.377 LOC V3 (16,2% repo) đóng góp 0%** cho bài nộp hiện hành.
4. **5 package rỗng hoàn toàn** — cây thư mục hứa nhiều hơn code có; `ports/` rỗng còn gây hiểu sai qua README.
5. **`run_pipeline.py` dead code**; `build_silver`/`build_catalog` chạy nhánh "legacy-build" không nuôi production.

### 6. Missing evidence — claim quan trọng chưa được chứng minh

| Claim | Trạng thái |
|---|---|
| "NEW tốt hơn OLD" | **chưa có bằng chứng kết quả** |
| Local 14/31 = 45,16% đại diện cho 561 câu | n=31, CI95 ≈ [28%, 63%] — **quá rộng để kết luận** |
| Retrieval gold 95 câu | **file không có trên đĩa**, 0% kiểm chứng được |
| Uplift reranker 0,3406→0,4231 | epoch chọn trên chính dev n=19; train split **âm** |
| "3 môi trường SHA khớp `ec774…9907`" | artifact không có trên đĩa |
| Ranh giới layer được tôn trọng | **0 test, 0 linter**; đã tìm thấy vi phạm |
| "Production không gọi model/network" | **đúng như câu chữ**, nhưng **0 test cưỡng chế** |
| Determinism xuyên nền tảng | `cleaning.py:269` phụ thuộc hashseed |

### 7. Must Fix Before Acceptance

| # | Việc | Ước lượng |
|---|---|---|
| **M1** | **Khôi phục payload dữ liệu** (corpus, `silver.db`, `retrieval.db`, ZIP parent) ra ngoài Git bằng `T2P_DATA_ROOT`, và ghi lại checksum. Không có bước này thì **không đo được gì cả** | 0,5–1 ngày |
| **M2** | **Nộp NEW V2 lên leaderboard một lần.** Đây là phép đo duy nhất kết thúc được tranh luận. Quota private còn hạn — dùng 1 slot cho việc này | 0,5 ngày |
| **M3** | **A/B chính sách abstain**: dựng nhánh fallback tất định rẻ tiền cho 451 câu abstain (heuristic ô-tốt-nhất của OLD, hoặc candidate cao điểm nhất mà binder đã tính rồi vứt đi), **giữ nguyên status `ABSTAIN` trong trace**, rồi **đo** fallback vs `0.0` trên slice có nhãn. **Không giả định fallback thắng** — phải đo (xem §VI-R1) | 1 ngày |
| **M4** | **Sửa tautology checksum reranker**: cho `evaluate_reranker_heldout.py:87` đọc `configs/retrieval/eval_v1.yaml:138` thay vì `_sha(MODEL)`. **1 dòng** | 15 phút |
| **M5** | **`sorted(set(found))`** tại `pipelines/a6/cleaning.py:269` | 1 phút |
| **M6** | **Khôi phục gold set `data/dev/`** hoặc sửa `gold_registry_v1.yaml` + `tests/test_answer_gold_provenance.py:12` để fail-loud thay vì `FileNotFoundError` | 2 giờ |
| **M7** | **Mang tri thức chẩn đoán then chốt sang**: tối thiểu là bảng "Những lỗi đã xảy ra" của `CLAUDE.md §5`, `RULES_SOURCES.md`, và **xét lại ADR-0009 đối chiếu ADR-024** | 0,5 ngày |

### 8. Should Fix

- **S1** — Thêm **import-linter** (hoặc 1 test 20 dòng) cưỡng chế `domain` không import lên tầng ngoài; sửa `table_features.py:25`.
- **S2** — Implement `application/ports/` hoặc **xoá** nó cùng 4 package rỗng, và sửa `application/README.md`.
- **S3** — Thêm test import-guard cưỡng chế "no LLM / no network trong `src/`".
- **S4** — Đổi tên `legacy_reranker_v1.py` → `test_legacy_reranker_v1.py` để 14 case chạy lại; sửa guard chống trôi để không dùng cùng glob.
- **S5** — Thêm test `parse_vn_number("1.234.567")` và `parse_vn_number("(1.234)")` ở **cả hai** repo.
- **S6** — Chuyển 3 `importorskip("pandas")` cấp module thành fixture cấp hàm để lọt vào tầm allowlist.
- **S7** — Hợp nhất **một** `detect_convention` duy nhất — cẩn thận vì hai bản khác kiểu trả về.
- **S8** — Sửa `README.md:9-12`: đừng đặt emitted/abstained dưới nhãn "result"; và bỏ claim "precision 6/9 → 6/6".
- **S9** — Hoà giải 3 con số mâu thuẫn giữa `REFACTOR_STATUS` / `GAP_CLOSURE_STATUS` / `README`.

### 9. Nice to Have

- Chạy eval trong subprocess với `setrlimit(RLIMIT_AS)` + `SIGALRM` timeout (áp dụng cho **cả hai** repo).
- Từ chối `str` constant ngoài ngữ cảnh `Subscript` trong sandbox (chặn `"a"*999999999`).
- Thêm member validation cho 3 điểm `extractall()` trong `tools/`.
- Bật `pytest-cov` và công bố coverage.
- Đo benchmark latency/memory — hiện **NOT MEASURED** ở cả hai.
- Ghim `compresslevel`/zlib version để byte-identity không phụ thuộc runtime.

---

## XVII. ACCEPTANCE DECISION

> **Nếu chỉ được chọn một version để tiếp tục phát triển, tôi chọn NEW.**

**Vì sao:**

1. **Nút thắt gốc của dự án là năng lực biểu diễn, và chỉ NEW gỡ được nó.** OLD không thể biểu diễn tỷ số hai chỉ số khác nhau **về mặt cấu trúc** (`router.py:48` — một dòng code chặn 224 câu). Không có lượng tuning nào cứu được điều đó. NEW thay bằng AST đệ quy — sửa được nguyên nhân, không phải triệu chứng.
2. **Chi phí sửa OLD cao hơn chi phí đo NEW.** Để OLD đạt tương đương NEW cần: viết lại IR, dựng CI, đóng RCE, dọn 5 bản sao tree, hợp nhất 5 thế hệ answer. Để NEW chứng minh mình cần: khôi phục data (1 ngày) + nộp 1 lần (0,5 ngày).
3. **NEW an toàn hơn một cách vật chất** — một P0 RCE và một P1 zip-slip đã đóng.
4. **NEW dễ bảo trì hơn ở mức khác biệt bậc thang** — và với một team nhỏ, đây là yếu tố quyết định tốc độ lặp về sau.

**Nhưng chọn NEW không có nghĩa là vứt OLD.** OLD giữ hai thứ NEW không có và **cần lấy lại ngay**: **payload dữ liệu** và **mốc điểm 0,1225**. OLD phải được bảo tồn nguyên trạng như **reference implementation + data vault**, không được xoá, cho tới khi NEW có điểm chính thức ≥ 0,1225.

---

### > **CONDITIONAL ACCEPT**

Điều kiện chấp nhận — **tất cả** phải đạt:

| # | Điều kiện | Cách kiểm |
|---|---|---|
| **C1** | Khôi phục payload; `make paths-check` + `make snapshots-verify` **PASS trên máy sạch** | Log lệnh + exit code |
| **C2** | **`make ci` chạy được và xanh trên môi trường thứ ba** (không phải máy build, không phải máy review) — hiện `PYTEST = NOT VERIFIED` | Log + số passed/skipped |
| **C3** | **NEW V2 được nộp và có điểm chính thức.** Nếu EXECUTION ≥ 0,1225 → ACCEPT hoàn toàn. Nếu < 0,1225 → **quay lại chính sách abstain (M3) trước khi làm bất cứ việc gì khác** | Submission ID + điểm |
| **C4** | M3 (fallback cho câu abstain) được implement, và **đo A/B được** giữa `0.0` và fallback | Báo cáo A/B trên slice có nhãn |
| **C5** | M4 (tautology checksum) + M5 (`sorted(set())`) đã sửa | Diff |
| **C6** | M6 (gold set) khôi phục hoặc fail-loud; `test_answer_gold_provenance.py` không raise `FileNotFoundError` trên checkout sạch | Log test |
| **C7** | M7: bảng "Những lỗi đã xảy ra" + `RULES_SOURCES.md` được mang sang; **ADR-0009 được xét lại đối chiếu ADR-024**, ghi kết quả bằng ADR mới (không sửa ADR cũ) | ADR mới |
| **C8** | `README.md:9-12` và claim "precision 6/9 → 6/6" được sửa lại cho đúng bản chất | Diff |

**Điều kiện KHÔNG bắt buộc để accept** (nhưng phải nằm trong backlog có ngày): import-linter, xoá package rỗng, hợp nhất `detect_convention`, benchmark hiệu năng, coverage.

---

## Phụ lục A — Nhật ký kiểm chứng (verification log)

Bản nháp của báo cáo này đã qua một vòng **fact-check độc lập**: mở lại **26 trích dẫn `file:line`** và kiểm lại toàn bộ số học. Kết quả và các đính chính đã áp dụng:

### Lỗi làm SAI kết luận — đã sửa

| # | Lỗi trong bản nháp | Đính chính | Đã xác minh lại bằng |
|---|---|---|---|
| **V1** | Coi `14/31` là **precision-on-emitted** rồi nhân với coverage ⇒ **đếm hai lần hình phạt abstain**. Dẫn tới kết luận sai *"V3 kém OLD 2,4 lần"* | `14/31` là **accuracy trên 31 câu evaluable**, cùng đại lượng với EXECUTION. Ước lượng đúng: V2 ≈ 0,4516 · V3 ≈ 0,1935 — **cả hai TRÊN 0,1225** | Đọc `ACCEPTANCE…:154` nguyên văn *"on this denominator"* |
| **V2** | *"0 dòng logic trả lời câu hỏi là code mới"* — dùng làm bằng chứng chính cho luận điểm "layer theater" | **SAI.** 6 engine `formula_engine`/`count_engine`/`entity_*` **chỉ có ở NEW** và được gọi thật | Grep `answer_formula_question\|answer_entity_sum\|answer_count_periods` trên toàn repo OLD → **0 hit** |
| **V3** | *"Không có model SHA tiền đăng ký ở bất kỳ đâu"* ⇒ xếp P1, *"lỗ leakage lớn nhất"* | **SAI.** SHA tồn tại, đã commit | Đọc `configs/retrieval/eval_v1.yaml:130-138`. Hạ xuống **P2**, fix 1 dòng |
| **V4** | *"Chính sách abstain của NEW có khả năng YẾU HƠN chính sách đoán của OLD"* | Vượt quá bằng chứng. Phản biện chưa nêu: OLD đoán **sai 87,7%**; và 561 câu của NEW có accuracy local cao hơn ~3,7× | Đổi thành **"CHƯA ĐO"**, chuyển M3 thành yêu cầu A/B |

### Lỗi trích dẫn — đã sửa

`ACCEPTANCE…:45` → `:13,49-50` (dung lượng A6) · `gold_tay_eval.json:32`/`:57` bị **đảo nguồn** · `adapters.py:18-25` → `:18-20` · `binder.py:67-80` → `:71-83` · `doc 143:86-97` → `:82` · *"20 import từ `pipelines.answering`"* → 15 câu lệnh import kéo 19 tên từ `answering` + 6 tên từ `retrieval` · V3 269/743 gán nhầm nguồn `ACCEPTANCE:20` → `README.md:12` (kèm cảnh báo mâu thuẫn 207-vs-269).

### Lỗi số học — đã sửa

`224+125+50 = 399 ≠ 288` (các lớp **chồng lấn**, không cộng dồn) · *"13/18 ngưỡng"* không có nguồn → thay bằng phát biểu định tính + `ACCEPTANCE:172` liệt kê 7 metric · docs OLD 171 → ghi rõ **169 trong `docs/*.md` + 2 archive** · scorecard NEW 6,3 → **6,1** sau khi hạ Correctness (+1 thay vì +2) và Documentation (0 thay vì +1) cho khớp với kết luận `NOT ENOUGH EVIDENCE`/`SAME` ở §IV.

### Đã kiểm và ĐÚNG (không đổi)

`submission.py:104` `answer 0.0` · `cleaning.py:269` set iteration · `evaluate_reranker_heldout.py:87` tautology · `table_features.py:25` domain→infra (**đúng ở CẢ HAI repo**) · `application/ports/__init__.py` **rỗng 0 byte** · `main.py:677` `SemanticV3Engine` **đúng 1 nơi** · `parser.py:235-238` · `conftest.py:43-71` · `approved_skips_v1.yaml` = **10 mục / tổng đúng 42** · `Makefile:44-46` · `test_zz_pytest_wrapper.py:35,71` **dùng cùng glob** · `sandbox/query.py:90` dead guard · OLD `pipeline.py:95-101`, `submission.py:195-196`, `06_dong_goi.py:11,43,46-50`, `router.py:48`, `answer.py:214-218`, `OFFICIAL_SCORE.json`, `clean_replay.json`, `route_report_1012.json` · ADR **31 vs 11** · **3 file "97", 2 file "82"** · 561/1012=0,5543 · 269/1012=0,2658 · 0,1225/0,5543=22,10% · Wald CI95 = [0,2764; 0,6268] · 238−25+8=221 · scorecard OLD 31/9=3,4.

### Giới hạn còn lại của báo cáo này

1. **Không chạy được test/benchmark/replay** (sandbox hết disk) — mọi số run là CLAIM.
2. **Ước lượng "~44% mới / ~56% cũ"** ở §XIV là cộng LOC theo import graph, **không phải đo coverage runtime**.
3. **Reachability của lỗ hổng RCE ở OLD chưa được chứng minh** — xếp P0 vì thiếu rào, không vì có exploit.
4. **Con số V3 chưa ổn định** (269 vs 207) giữa hai tài liệu cùng ngày của chính NEW.

---

## Phụ lục B — Bảng đối chiếu định lượng

| Chỉ số | OLD | NEW | Nguồn |
|---|---:|---:|---|
| File `.py` trong `src/` | 104 | 176 (+70 shim) | Glob |
| LOC `src/text2pandas` | ~21.096 | 33.255 | Đếm dòng |
| — trong đó `pipelines/` (legacy) | — | 21.038 (**63,3%**) | Đếm dòng |
| — 4 layer mới | — | 12.139 (36,5%) | Đếm dòng |
| — chỉ V3 dùng | — | ~5.377 (16,2%) | Đếm dòng |
| File `.py` trong `tools/` | 238 | 221 (+25 chuyển sang `experiments/`, +8 mới) | Glob |
| File test | 80 | 120 | Glob |
| Hàm `def test_` | 1.059 | 1.276 | Grep |
| File `.md` trong `docs/` | 171 | 20 | Glob |
| Package rỗng trong `src/` | 6 | 5 | Glob |
| File `.db` | ≥4 (work.db 4,24 GB) | **0** | Glob |
| File `.zip` | 68 | **0** | Glob |
| Câu phát ra đáp án | **1011/1012** | 561 (V2) / 269 (V3, ⚠️ 207 theo ACCEPTANCE) | Artifact |
| **EXECUTION chính thức** | **0,1225** (n=1012) | **NOT_MEASURED** | `OFFICIAL_SCORE.json:11` |
| Trần EXECUTION theo coverage | 0,9990 | 0,5543 (V2) / 0,2658 (V3) | Tính từ coverage |
| Ước lượng EXEC từ slice local | — | 0,4516 (V2) / 0,1935 (V3), **n=31** | `ACCEPTANCE:154`; `README:19` |
| Precision cần để hoà OLD | — | 22,10% (V2) / 46,09% (V3) | Tính |
| ADR | 31 | 11 | Đếm |
| CI workflow | 0 | 2 | Glob |
| Lỗ hổng P0 mở | 1 (RCE) | 0 | §XIII |
