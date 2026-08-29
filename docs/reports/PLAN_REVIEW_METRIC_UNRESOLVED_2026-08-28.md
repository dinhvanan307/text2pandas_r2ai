# Review độc lập — Plan xử lý `METRIC_UNRESOLVED` (Semantic V3)

**Ngày review:** 2026-08-28
**Tài liệu được review:** `METRIC_UNRESOLVED_RECOVERY_PLAN_2026-08-28.md`
**Reviewer:** audit độc lập (tiếp nối `FULL_INDEPENDENT_AUDIT_2026-08-27.md`)
**Chế độ:** read-only; mọi claim then chốt của plan được đối chiếu trực tiếp với code/artifact trên đĩa. Sandbox runtime vẫn chết (`no space left on device`, 5 lần) → không chạy được lệnh; các mục cần runtime gắn nhãn `UNKNOWN`.

---

## 1. Verdict

```text
KẾT LUẬN:  APPROVE WITH CHANGES
           Plan có chất lượng kỹ thuật cao nhất trong chuỗi tài liệu của dự án:
           root cause đúng, phạm vi kỷ luật, fail-closed nhất quán, gate tiền
           đăng ký. 100% claim code-level tôi kiểm được đều CHÍNH XÁC đến từng
           dòng. Tuy nhiên có 3 vấn đề mức BLOCKER phải sửa trước khi thực thi
           (M1 runtime gate tự mâu thuẫn · M2 baseline dirty-worktree · M3 phụ
           thuộc alias hỏng chưa khai báo) và 5 bổ sung mức P1/P2.

ĐỘ TIN CẬY EVIDENCE CỦA PLAN:  CAO — 12/12 điểm kiểm chứng khớp (mục 2).
RỦI RO LỚN NHẤT:               không phải kỹ thuật, mà là OPPORTUNITY COST
                               (mục 4, M7): toàn bộ nỗ lực nằm ở V3 shadow,
                               không đổi một điểm official nào cho tới khi
                               promote — trong khi V2 đang nộp 451 câu answer=0.0.
```

---

## 2. Kiểm chứng evidence của plan (đối chiếu trực tiếp)

| # | Claim trong plan | Kết quả kiểm | Bằng chứng |
|---|---|---|---|
| 1 | Baseline 287 OK / 725 abstain / 198 `METRIC_UNRESOLVED` / 1.012 câu | ✅ KHỚP | `artifacts/runs/semantic-v3/retrieval-recovery-v2-pre-gates-20260828/manifest.json:111,113,130-133` |
| 2 | Artifact baseline + retrieval eval tồn tại | ✅ | `records.jsonl` + ~1.000 CSV + `ek_retrieval_recovery_v11_064d5c72466be010.jsonl` đều trên đĩa |
| 3 | Ontology fingerprint `f45411be…` | ✅ | `manifest.json:135` |
| 4 | Parse fail → `METRIC_UNRESOLVED` trước retrieval | ✅ | `parser.py:132-133`; Q5 record: `"reason": "METRIC_UNRESOLVED", "relevant_tables": []` |
| 5 | `_base_expression` đòi ≥1 mention; chọn `mentions[-1]` | ✅ | `parser.py:183-185` |
| 6 | `_metric_mentions` chỉ literal-match ontology alias, không giữ surface chưa map | ✅ | `parser.py:380-395` — `normalized.find(alias)` trên `ontology.metrics`, không có nhánh giữ span unmapped |
| 7 | Planner đòi `metric_id` tồn tại trong ontology | ✅ | `planner.py:45,54-56` — `PlanningError("unknown ontology metric")` |
| 8 | `UNKNOWN_METRIC` chỉ sau planning; `METRIC_REJECT_ALL` chỉ sau scan | ✅ | `operand.py:85` và `operand.py:142-146` — đúng từng số dòng plan trích |
| 9 | `legacy_annotator.py` là điểm duy nhất V3 import V2 | ✅ | docstring tự khai (`legacy_annotator.py:3`); `LegacyVietnameseAnnotator` chỉ được wire ở `main.py:676` (V3) |
| 10 | 4 file test MUST-test đã tồn tại | ✅ | `tests/unit/test_semantic_{parser,ast}_v3.py`, `test_planning_and_joint_binding_v3.py`, `test_operand_retrieval_v3.py` |
| 11 | Tool `diagnose_metric_unresolved_v3.py` chưa tồn tại (sẽ viết ở Phase 0) | ✅ đúng như plan | glob không tìm thấy |
| 12 | Runtime baseline | ⚠️ **KHỚP NHƯNG DỄ ĐỌC NHẦM** | manifest ghi `"seconds": 47.676` → **~47,7 giây**, không phải 47.676 giây (13,2 giờ). Plan viết "47,676 giây" theo dấu phẩy thập phân VN — cần ghi rõ đơn vị (xem M1) |

Không kiểm được (UNKNOWN, cần runtime): ontology counts chính xác (368/28/376/65), thành viên từng cohort T1/T2/T3, con số 197/198 proxy, hành vi parse Q508 hiện tại. Cấu trúc và tổng cohort 124+55+18+1=198 nhất quán nội bộ.

---

## 3. Điểm mạnh của plan (giữ nguyên, không sửa)

1. **Root cause analysis đúng và có tầng bậc** — tách root cause trực tiếp (extractor/mapper gộp), root cause data model (`MetricRef` không có surface/provenance), root cause role (compile order + `mentions[-1]`), và nói rõ những gì KHÔNG phải root cause (§3.4). Đây là mức phân tích mà các doc trước (doc 143) chỉ ra vấn đề nhưng chưa ra được thiết kế.
2. **Taxonomy 8 terminal diagnostic (§4.4)** — đúng bài học "log lỗi bị đặt tên như evidence" từ doc 156; ép mỗi QID một terminal reason là cách duy nhất tránh coverage giả.
3. **Kỷ luật đo lường** — funnel 9 bước (§9.1), tách "rời unresolved" khỏi "new OK" khỏi "adjudicated OK"; gate coverage tiền đăng ký (80/60/40/≤118) trên T1 thay vì hứa tổng quát.
4. **Fail-closed nhất quán** — Q100 phải abstain; T3 không được tự thắng; source-backed không nới reported-derived gate; rollback qua config flag.
5. **Ranh giới đúng** — AST position làm role SSOT (không thêm role enum dư); không đụng V2 canonical; không đụng data; không neural; MUST NOT rõ ràng.
6. **Q508 đặt làm boundary chứ không phải target** — chấp nhận abstain đúng vai trò, không hứa OK. Đúng với thực tế alias (xem M3).

---

## 4. Vấn đề phải sửa / bổ sung

### M1 — BLOCKER: Runtime gate tự mâu thuẫn với kiến trúc resolver

Baseline là **47,7 giây** cho 1.012 câu (manifest `"seconds": 47.676`). Gate §9.3/§13.3 cho phép tăng ≤10% ⇒ **ngân sách ~4,8 giây** cho toàn bộ resolver fallback: extract mention + n-gram matching trên leaf/path/hierarchy của `silver.db` **4,1 GB**, cho ~198 câu (chưa kể mention scan cho các câu khác). Với thứ tự matching 5 lớp (§5.3, trong đó lớp 4 là bounded n-gram trên row labels trong scope), khả năng rất cao gate này fail ngay cả với implementation đúng — và khi đó §5.3 lại DEFER materialized label index, tức plan tự khóa lối thoát duy nhất của chính nó.

**Sửa:**
- Ghi rõ đơn vị baseline trong plan: `47.676 s ≈ 47,7 giây`.
- Đổi gate tương đối 10% thành **ngân sách tuyệt đối tiền đăng ký** (đề xuất: tổng full-corpus ≤ 120 s trên cùng máy đo, ghi máy đo vào manifest — hai workspace của dự án đã phân kỳ, mọi số phải ghi máy).
- Nâng materialized semantic label index từ DEFER lên **Phase 2 contingency được phép** (điều kiện kích hoạt: vượt ngân sách sau khi đã dùng prepared statements + cache). Index là derived artifact read-only từ A6, không vi phạm nguyên tắc immutable nếu nằm dưới `artifacts/` với build-id + checksum riêng.

### M2 — BLOCKER: Baseline được sinh trên worktree bẩn

`manifest.json:2757-2758` của chính baseline ghi `"git_commit": "193dab4…", "git_dirty": true`. Plan §2.1 tuyên bố "không được đổi identity khi đo A/B" nhưng phía **code** của phép A/B lại không có identity sạch — dirty worktree nghĩa là không thể tái lập chính xác code đã sinh baseline.

**Sửa (Phase 0):**
- Commit/stash toàn bộ thay đổi, chạy lại baseline từ commit sạch, seal `git_commit + git_dirty=false` vào §2.1.
- Ghi chú tích cực: git **đang hoạt động trở lại** (manifest 28/08 ghi được commit) — mâu thuẫn với trạng thái "pack corrupt" ngày 27/08. Xác nhận `git status` và nhân tiện đóng RET-015 (biến `git_commit=null` thành lỗi release thay vì metadata im lặng) — plan này là chỗ rẻ nhất để làm điều đó vì đằng nào cũng phải seal baseline.
- Đồng bộ doc: baseline 287 OK khác mọi con số V3 đã công bố (269 r17 / 207 r3 / 271 r7). Khi seal baseline, cập nhật `SEMANTIC_V3_MIGRATION_STATUS.md` một lần để chấm dứt chuỗi số bất nhất.

### M3 — BLOCKER: Phụ thuộc tầng entity/alias hỏng chưa được khai báo

V3 wire alias qua `main.py:675 load_aliases("a6")` — **đúng nhánh có 68 giá trị chứa literal `...` và thiếu Eximbank** (đã CONFIRMED trong audit 27/08: `company_brand_attested_v1.yaml:19`, `attest_brands.py:109`). Resolver của plan scope hypothesis theo **entity/period/basis** (§5.2, §5.3): entity sai hoặc thiếu ⇒ scope sai ⇒ hypothesis sai hoặc rỗng, và lỗi sẽ hiện ra như `QUESTION_MENTION_NO_MAPPING`/`SCOPE_EMPTY` — tức **nhiễm nhãn taxonomy mới** bằng một lỗi tầng khác. Plan hiện không nhắc alias ở bất kỳ mục nào.

**Sửa:**
- Thêm precondition P0-ALIAS vào Phase 0: sửa serialization `attest_brands.py:109` (`yaml.safe_dump(n).strip()` → ghi scalar an toàn), regen `company_brand_attested_v1.yaml`, thêm invariant test "không giá trị nào chứa `...`". Đây là fix 1-dòng + regen, không thuộc danh sách MUST NOT của plan (không đổi data A6, không đổi snapshot), và nó làm sạch cả V2 lẫn V3.
- Quyết định Eximbank/STB (lexicon từ câu hỏi + ADR) **không** cần gộp vào plan này — chỉ cần ghi vào §11 Risks: "entity gap là confounder của mọi diagnostic entity-scoped; các QID có entity chưa resolve phải bị loại khỏi mẫu đánh giá resolver hoặc gắn cờ riêng".

### M4 — P1: "Reviewer adjudication" chưa có người và protocol

Gate 13.1 yêu cầu mọi new `OK` qua reviewer, Phase 5 yêu cầu adjudicate toàn bộ new OK + T3 + Q100. Nhưng thực trạng đã audit: `gold_registry_v1.yaml` ghi `promotion_eligible_records: 0` cho cả 3 asset, `access_log.json` rỗng, 300-record packet chưa có 2 annotator độc lập. Nếu không định nghĩa ai review, blind thế nào, bao nhiêu là đủ — gate này trở thành hoặc (a) nút cổ chai vô hạn, hoặc (b) self-review đội nhà, lặp lại đúng lỗi "same-model correlated error" đã ghi ở doc trước.

**Sửa:** trỏ tường minh sang `configs/evaluation/independent_gold_protocol_v1.yaml`; định nghĩa tối thiểu: người review không phải người viết resolver, làm việc trên blind dossier (không thấy answer của hệ thống), quorum tối thiểu cho iteration đầu (đề xuất: 100% new OK, tối đa 60 câu — vượt thì sample có seed). Nếu không có người thứ hai, ghi rõ "single-reviewer, non-promotable" ngay trong artifact.

### M5 — P1: Precondition môi trường

`make typecheck` + `make test-offline` là engineering gate bắt buộc (§13.3) nhưng môi trường sandbox hiện **không chạy được bất kỳ lệnh nào** (disk full — 5 lần liên tiếp trong phiên này, trùng lỗi team gặp ngày 27/08). Plan không có precondition môi trường.

**Sửa:** thêm ENV-0 vào Phase 0: giải phóng đĩa / khôi phục môi trường, chạy `make paths-check` + `make snapshots-verify` thành công, ghi máy đo + Python version vào baseline seal (bài học `MEASURED_OFF_CONTRACT_PY310` từ provenance cũ).

### M6 — P1: Thiếu gate chống drift cho V2

Plan sửa `legacy_annotator.py` (§6.1) và tuyên bố V2 không đổi (§6.3), nhưng MUST-test không có phép đo nào **enforce** điều đó. Đã verify: `legacy_annotator` chỉ được V3 import, nên rủi ro thấp — nhưng nó *gọi* `classify_operation` và `parse_intent` của V2; một sửa đổi bất cẩn kiểu "tiện tay sửa luôn hàm V2 cho đúng" sẽ lọt qua mọi gate hiện có của plan.

**Sửa:** thêm 1 fixture test rẻ: hash output của `classify_operation` + `parse_intent` trên toàn bộ 1.012 câu, snapshot trước khi bắt đầu, assert không đổi ở mọi phase. (~vài giây runtime, đóng luôn claim §6.3 bằng phép đo.)

### M7 — P1 (chiến lược): Opportunity cost phải có go/no-go tường minh

Sự thật cần nhìn thẳng: **plan này không thay đổi một điểm official nào**, kể cả khi đạt mọi gate — V3 là shadow, promotion đòi answer accuracy ≥0.80 (policy) trong khi V3 đang 6/31 local; còn V2 (đang nộp thật) có 451 câu `answer=0.0` và các lỗi alias P0 đã confirmed. 198 câu này của V3 phần lớn **cũng nằm trong** vùng V2 đang abstain/sai — nghĩa là công sức bỏ ra chỉ sinh điểm nếu (a) V3 được promote sau này, hoặc (b) thành quả port được sang V2.

**Sửa — 2 bổ sung:**
- **Checkpoint go/no-go sau Phase 2:** nếu ≤20 câu T1 tới được binder với candidate đúng (theo adjudication mẫu), dừng plan, chuyển nguồn lực về V2 (abstain policy + alias). Ghi ngưỡng này trước, đừng quyết sau khi có số.
- **Phase 2b (song song, 0,5 ngày):** đánh giá portability — abbreviation/paraphrase rules (TNDN ↔ thu nhập doanh nghiệp…) và mention extractor là các tài sản **engine-agnostic**; đo thử chúng trên nhóm 40 câu `unbound operands` của V2 (abstention family đã ghi trong ACCEPTANCE 27/08). Nếu port được, giá trị của plan tăng gấp đôi vì chạm vào nơi có điểm thật.

### M8 — P2: Các chỉnh sửa nhỏ

1. **§2.1**: sửa "47,676 giây" → "47.676 s (~47,7 giây)"; thêm `git_commit` + máy đo vào bảng identity.
2. **Package V3**: nếu Phase 5 có bước package, lưu ý `package-v3` sẽ **crash trên lineage active** vì `main.py:428` đòi `a6_path/dataframe/csv/table_cards.csv` — build `c6887…` không có thư mục `dataframe/` (đã confirmed 27/08). Plan hiện không package nên chưa chặn, nhưng phải ghi vào §11 để không ai "tiện tay" package.
3. **Taxonomy §4.4**: thêm 1 diagnostic `ENTITY_SCOPE_UNAVAILABLE` (hoặc tương đương) để tách lỗi entity khỏi lỗi metric — phục vụ M3.
4. **§5.3 lớp 3 (abbreviation rules)**: yêu cầu mỗi rule có ≥1 QID bằng chứng + negative example ngay trong YAML (chống rule-creep về sau).
5. **Cohort Appendix A**: seal danh sách QID bằng SHA-256 của file cohort để mọi báo cáo sau trích đúng một nguồn.
6. **`mentions[-1]`**: plan giữ nó cho compatibility path — đồng ý, nhưng thêm comment trong code trỏ về plan này để người sau không "sửa giúp".

---

## 5. Đánh giá từng mục của plan (tóm tắt)

| Mục | Đánh giá | Ghi chú |
|---|---|---|
| §1-2 Problem/Evidence | ✅ Xuất sắc | 12/12 điểm kiểm khớp; chỉ sai đơn vị runtime (M1) |
| §3 Root cause | ✅ Đúng | Cả 3 tầng + §3.4 "không phải root cause" đều chính xác theo code |
| §4 Taxonomy | ✅ Tốt | Bổ sung 1 diagnostic entity (M8.3) |
| §5 Architecture | ✅ Đúng hướng, tối giản | Thứ tự matching hợp lý; DEFER index phải hạ xuống contingency (M1) |
| §6 Files/modules | ✅ Chính xác | Mọi file MUST-change tồn tại đúng vị trí; ranh giới V2/V3 verified |
| §7 Data/schema | ✅ | Optional additive fields + không bump major — đúng chuẩn |
| §8 Test strategy | ⚠️ Thiếu 1 gate | Bổ sung V2 no-drift fixture (M6) |
| §9 Measurement | ⚠️ | Funnel tốt; runtime gate phải đổi (M1); thêm máy đo |
| §10 Expected impact | ✅ Thận trọng đúng mức | 80/60/40/≤118 là preregistered — giữ nguyên |
| §11 Risks | ⚠️ Thiếu 3 rủi ro | alias/entity confounder (M3), reviewer vacuum (M4), env (M5) |
| §12 Rollback | ✅ | Config-flag rollback + trigger rõ |
| §13 Gates | ⚠️ | Sửa runtime gate; thêm điều kiện reviewer định danh |
| §14 MUST/MUST NOT/DEFER | ✅ | Chuyển 1 item DEFER→contingency (M1) |
| §15 Phases | ⚠️ | Thêm ENV-0, P0-ALIAS, V2-snapshot vào Phase 0; go/no-go sau Phase 2 (M7) |

---

## 6. Phase 0 sửa đổi (phiên bản hợp nhất để thực thi)

```text
Phase 0 — Freeze baseline và precondition (bổ sung so với plan gốc)
  0.0  ENV-0: khôi phục môi trường; make paths-check + snapshots-verify PASS;
       ghi máy đo + Python version.                                   [M5]
  0.1  Git sạch: commit/stash; git status sạch; nếu git lỗi → dừng, sửa
       trước (RET-015). Re-run baseline từ commit sạch, seal identity. [M2]
  0.2  P0-ALIAS: sửa attest_brands.py:109, regen YAML, test invariant
       "no '...'", chạy lại baseline (alias đổi ⇒ baseline phải re-seal
       — đây là lý do làm TRƯỚC khi freeze, không phải sau).           [M3]
  0.3  V2 no-drift snapshot: hash classify_operation + parse_intent
       trên 1.012 câu.                                                [M6]
  0.4  (như plan) diagnose tool read-only + taxonomy artifact + fixtures
       8 QID + seal cohort bằng SHA.                                  [M8.5]
  0.5  Định danh reviewer + blind protocol cho gate 13.1.             [M4]
  Exit: baseline sạch tái lập được, cohort sealed, reviewer xác định.
```

Các phase 1-5 giữ nguyên, cộng: ngân sách runtime tuyệt đối (M1), go/no-go + Phase 2b portability (M7).

---

## 7. Kết luận

Plan này là tài liệu kỹ thuật đúng chuẩn nhất của dự án đến thời điểm này: evidence thật, phạm vi kỷ luật, gate tiền đăng ký, fail-closed xuyên suốt. **Approve với điều kiện 3 blocker M1-M3 được nhập vào plan trước dòng code đầu tiên**, vì cả ba đều thuộc loại "rẻ để sửa bây giờ, đắt để phát hiện sau": gate runtime sai đơn vị sẽ giết implementation đúng ở Phase 2; baseline dirty sẽ vô hiệu toàn bộ phép A/B ở Phase 5; alias hỏng sẽ nhiễm taxonomy ngay từ Phase 0.

Và một câu thẳng thắn ở vai cộng sự: nếu mục tiêu quý này là **điểm leaderboard**, thứ tự đúng vẫn là (1) V2 abstain policy, (2) alias/entity P0, (3) rồi mới đến plan này — trừ khi Phase 2b chứng minh được thành quả port sang V2. Plan đã tự nói điều tương tự ở §1 ("giảm METRIC_UNRESOLVED không phải bằng chứng correctness"); M7 chỉ biến nhận thức đó thành một checkpoint có ngưỡng.
