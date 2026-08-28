# FULL INDEPENDENT AUDIT — text2pandas (NEW)

**Ngày:** 2026-08-27 · **Auditor:** độc lập, không thuộc chuỗi report trước
**Chế độ:** read-only. Không sửa code, không rebuild artifact. Thay đổi duy nhất trong repo là report này.
**Giới hạn môi trường:** sandbox Linux của phiên audit bị `No space left on device` (4 lần liên tiếp) → **không chạy được pytest / sqlite / git / retrieval run**. Đây là **cùng một lỗi môi trường** mà chính team đã gặp 5 lần khi viết `docs/E2E_EXECUTION_PLAN_2026-08-27.md:59`. Do đó mọi kết luận trong report này thuộc một trong ba nhãn:

- `STATIC-VERIFIED` — đọc trực tiếp code / config / data / artifact, trích dẫn file:line;
- `ARTIFACT` — số liệu lấy từ artifact/manifest đã ghi trong repo, không tái đo;
- `UNKNOWN` — cần runtime mới xác nhận được; không đoán.

---

## A. Executive Verdict

```text
PROJECT STATUS:  NOT READY (cho một submission cạnh tranh)
                 — ZIP hợp lệ về mặt cơ học thì TẠO ĐƯỢC (V2 canonical),
                   nhưng 44,57% số câu nộp answer=0.0 và các lỗi entity/alias
                   P0 đã được xác nhận trong code đang trực tiếp mất điểm.

P0: 4   (alias/entity hard-filter ×3 gộp thành 1 · alias "..." hỏng trong nhánh
         production · 451 abstain nộp thành 0.0 · lineage git fail-open)
P1: 7   (N policy · refs bị binder ghi đè · ~89 file đo trên snapshot cũ ·
         0 regression test cho các QID đã biết · reranker gate tautology ·
         gold promotion-eligible = 0 · score 27/08 không có receipt trong repo)
P2: 7   (chi tiết mục C)

TEAM ASSESSMENT ACCURACY: HIGH
  Red-team audit 27/08 của team chính xác ở mọi claim P0/P1 tôi kiểm được
  (10/10 claim code-level tái xác nhận đúng đến từng dòng). Sai lệch chỉ ở:
  (1) một số doc 27/08 đã STALE vì payload dữ liệu sau đó được khôi phục;
  (2) con số "64 hardcode" thực tế là ~89 file;
  (3) mâu thuẫn số liệu V3 giữa các doc cùng ngày (269 vs 207 vs 271) chưa ai chốt.
```

---

## B. Master Issue Table

Trạng thái: `CONFIRMED` / `FIXED` / `PARTIALLY_FIXED` / `NOT_REPRODUCIBLE` / `FALSE_ALARM` / `UNKNOWN`.

| # | Issue | Team claim | Trạng thái audit | Severity | Evidence | Impact |
|---|---|---|---|---|---|---|
| RET-001 | Q508 mất STB do alias | Alias STB sai với wording câu hỏi | **CONFIRMED** | P0 | `configs/retrieval/company_alias_v1.yaml:261-263` = "Sài Gòn Tài Lộc"; câu 508 trong `questions.jsonl` = "Sài Gòn Thương Tín"; **`data/raw/btc/metadata/companies.csv:27` cũng ghi "Sài Gòn Tài Lộc"** → đây là corpus ẩn danh hoá ≠ tên thật trong câu hỏi, không phải typo | Mất gold ngay S1 → 0 điểm mọi metric cho case |
| RET-002 | Q783/Q792 mất EIB | Nhánh A6 loại "Eximbank" | **CONFIRMED** | P0 | `company_brand_attested_v1.yaml:12` (danh sách 9 tên không attest được); production dùng nhánh này: `canonical_run.py:538 load_aliases("a6")`; câu 783/792 dùng "Eximbank"; corpus gọi EIB là "Ngân hàng TMCP Xuất nhập khẩu Việt Nam" (`companies.csv:28`) | 2 câu chắc chắn hỏng; policy corpus-only (ADR-0009) là nguyên nhân gốc |
| RET-003 | Q464 nhận 0 candidate | Empty targets → `return []` | **CONFIRMED** | P0 | `filter_s1.py:73-74`; câu 464 không nêu tên công ty nào. **Thêm:** docstring `question_intent.py:105-110` hứa "S1 phải đi nhánh không-lọc-ticker" — code không làm vậy → doc-vs-code mâu thuẫn | ≥1/1012 mất trắng; mọi câu open-universe cùng số phận |
| RET-004 | Alias attested chứa literal `...` | `safe_dump().strip()` hỏng 68 giá trị; Q586 rank 5/6→25/29 | **CONFIRMED** (cơ chế + artifact) | P0 | `tools/attest_brands.py:109` dump scalar rồi `.strip()`; file sinh ra `company_brand_attested_v1.yaml:19` = `ACV: [Cảng hàng không\n...]` → value load thành `"Cảng hàng không ..."`; bản full sạch (`company_brand_v1.yaml:25`). Số rank 5/6→25/29: `ARTIFACT`, không tái đo | Alias-stripping hỏng ở nhánh production; team đo 61 QID đổi terms |
| RET-005 | N policy khác OLD freeze | NEW `min(e×y,10)` vs OLD `clamp(3n,1,30)` | **CONFIRMED** (divergence) / **UNKNOWN** (tác động official) | P1 | `submission_adapter.py:55,113-116` (MAX_N=10); `configs/pipelines/retrieval_frozen_v1.yaml` + `provenance/retrieval/RETRIEVAL_FREEZE_v1.json` ghi `clamp(3*n_o,1,30)`. F2 local 0.3035 vs 0.4624: `ARTIFACT` | Nguy cơ giảm Tables/Docs F2 (recall-weighted) |
| RET-007 | Binder ghi đè refs | Answer thành công → refs = bound tables | **CONFIRMED** | P1 | `canonical_run.py:698-707` (success → `submission_refs_for_uids`), `:721-722` (abstain → fallback top-N); docstring thừa nhận đây là chủ đích (`submission_adapter.py:123-128`) | Điểm retrieval phụ thuộc binding; 14+/10− hit flips (`ARTIFACT`) |
| RET-010 | Multi/rank/conditional bỏ trống | 180 abstain MULTI_ENTITY; local multi 0/12 | **ARTIFACT-CONFIRMED** | P0 (score) | `ACCEPTANCE_TEST_REPORT_2026-08-27.md:152` (abstain families: multi 180, unbound 40, select-at-arg 32...); không tái chạy được | Cụm mất điểm lớn nhất của Answer/Execution |
| RET-011/012 | Không có gold promotion-eligible | registry ghi 0 | **CONFIRMED** | P1 | `configs/evaluation/gold_registry_v1.yaml:13,25,37` — cả 3 asset `promotion_eligible_records: 0` | Mọi quyết định tối ưu đang chạy trên gold nhiễm/quá nhỏ |
| RET-014 | 64 file hardcode snapshot cũ | Eval tools đo nhầm DB cũ | **CONFIRMED — nặng hơn claim** | P1 | ~**89 file**: 6 `src/` (`pipelines/retrieval/__init__.py:24 SILVER_BUILD_ID="b3e..."`, `eval_s1.py:17`, `eval_retrieval.py:77`, `goldkit.py:59`, `mine_alias.py:71`, `diag_s1_miss.py:32`), 65 `tools/`, 15 `experiments/`, 2 `configs/`, 1 `tests/answer_v2/_moitruong.py:24`. Chỉ `infrastructure/paths.py:76` + `snapshots.py` đọc `active_snapshot.yaml` | Mọi số đo qua tools/evalkit cũ có thể đo trên snapshot `b3e968.../286973...` thay vì active `c6887.../872ccb...` |
| RET-015 | Git corrupt + identity null | pack "far too short", manifest nhận null | **PARTIALLY CONFIRMED** | P0 | Cơ chế fail-open: `source_identity.py:23-29` trả `{git_commit: None, git_dirty: None}` khi git lỗi, `main.py:206,645` nhận không chặn — `STATIC-VERIFIED`. Bản thân corruption: `.git/objects/pack/pack-94eb....pack` tồn tại nhưng **không chạy được git để xác nhận** → `UNKNOWN` | Release có thể không truy được về commit nguồn |
| RET-022 | Reranker chưa đủ điều kiện + gate hỏng | SHA check tautology; uplift chọn trên dev | **CONFIRMED** | P1 | `tools/retrieval/evaluate_reranker_heldout.py:87` `reranker_model_sha256=_sha(MODEL)` — tự băm chính file, bỏ qua SHA đăng ký trước tại `configs/retrieval/eval_v1.yaml:138`; artifact `reranker_linear_v1_development.json`: train F2 **giảm** 0.3954→0.3931, epoch chọn = dev best | Gate không thể fail; giữ Identity S3 là đúng |
| RET-024 | 0 regression test cho QID đã biết | Không test 464/508/586/783 | **CONFIRMED** | P1 | Grep toàn `tests/`: 0 hit thật cho 5 QID (chỉ 792 xuất hiện làm nhãn operation ở `test_answer_operation.py:320`); không test nào assert YAML attested không chứa `...` | Lỗi P0 có thể tái xuất sau khi sửa |
| RET-026 | Score 27/08 không có receipt | Nhãn 8/9 dòng xung đột artifact 22/08 | **CONFIRMED** | P1 | Không tồn tại `OFFICIAL_SCORE*.json` nào trong `text2pandas/`. Artifact duy nhất ở repo OLD: `Text2Pandas-1/reports/answer_v2/OFFICIAL_SCORE.json` (id 3392, EXEC 0.1225, tables_f2 0.3538, docs_f2 0.7536, answer_accuracy **0.1225**, docs_mrr5 0.7841). Bảng 27/08 do user cung cấp có nhãn hoán vị so với key artifact này — mapping của red-team audit là ĐÚNG | EXEC 0.2549 mới **không thể xác minh từ repo**; cấm tối ưu theo các nhãn chưa reconcile |
| — | "Payload dữ liệu không tồn tại, phải rebuild" (E2E plan P0-1/2/3, OLD_VS_NEW R3/R5) | data/ = 0 byte payload | **FIXED / STALE-DOC** | — | Tồn tại trên đĩa: `data/processed/a6/c6887.../silver.db`, `data/processed/a6/b3e968.../silver.db`, cả 2 `retrieval.db`, `data/raw/btc/**` (~41k file), `data/curated/dev-legacy/answer_gold/*` (13 file) | Kế hoạch "must rebuild" và claim "gold mất 100%" đã lỗi thời; đừng hành động theo |
| — | Abstain nộp `answer: 0.0` | 451 câu bị chấm sai như trả lời sai | **CONFIRMED** | **P0 (score lever lớn nhất)** | `application/usecases/submission.py:104` `float(res.answer) if ... else 0.0` + comment thừa nhận "giá trị giữ chỗ". Trần EXEC = 561/1012 = 0.5543 | 44,57% số câu chắc chắn 0 điểm answer/execution trừ khi đáp án thật = 0 |
| — | V3 số liệu bất nhất | — | **CONFIRMED (doc bug)** | P1 | Cùng ngày 27/08: README/SEMANTIC_V3/QUALITY_8PLUS = **269/743** (r17); ACCEPTANCE = **207/805** (r3/r5); GAP_CLOSURE = **271/741** (r7). Route coverage 684 vs 669; mypy 78 vs 83; formula 16/24/27; test count 2124 (doc) vs 2105 (artifact `test_report.json`) vs 2086 | Không tin bất kỳ số V3 nào chưa ghi kèm run-id |
| — | `snapshots-verify` không hash payload | Manifest giả mạo vẫn PASS | **CONFIRMED (by design)** | P2 | `infrastructure/snapshots.py:132-137` docstring tự khai "deliberately avoids hashing"; chỉ check size + schema + counts (`:215-216`) | Gate yếu hơn tên gọi; chấp nhận được nếu ghi rõ |
| — | `cleaning.py` phụ thuộc hash seed | `set(found)` iteration | **CONFIRMED (masked)** | P2 | `pipelines/a6/cleaning.py:269`; `Makefile:23` export `PYTHONHASHSEED=0` che lỗi khi chạy qua make | Nợ tất định thấp; chưa chứng minh output đổi |
| — | 46 test có thể biến mất im lặng | module-level importorskip | **CONFIRMED (cơ chế)** | P2 | `test_pipeline_e2e.py:15`, `test_percent_point_e2e.py:29`, `test_policy_and_result_kind.py:16`; con số 46: `ARTIFACT` | Gate xanh giả nếu thiếu pandas |
| — | 14 test reranker mồ côi | file không khớp glob `test_*` | **CONFIRMED** | P2 | `tests/answer_v2/legacy_reranker_v1.py` tồn tại, pytest `python_files` mặc định không collect | Test không chạy mà không ai biết |
| — | Retrieval NEW = OLD trên gold 95 | 0 flip, p=1.0 (bản full-brand); bản canonical A6 có 1 regression Q586 | **ARTIFACT** — không tái đo được | P1 | `RETRIEVAL_OLD_VS_NEW_AUDIT` đo bằng full brands; `RETRIEVAL_RED_TEAM_AUDIT` §7 chỉ ra evaluation-config mismatch và tìm ra Q586 khi dùng đúng canonical A6 | Bài học: phải đo bằng đúng config production |
| — | Hit@10 86/95, candidate recall 95/95, v.v. | các số retrieval local | **UNKNOWN** (không tái đo) | — | Nhất quán giữa các artifact nhưng phiên này không chạy lại được | — |

---

## C. Confirmed Problems (đang tồn tại thật, theo lớp)

**Data / Config**
1. Alias production (nhánh `a6`) hỏng serialization — 68 giá trị chứa ` ...` (RET-004).
2. Lexicon entity thiếu so với ngôn ngữ câu hỏi: STB ("Sài Gòn Thương Tín"), EIB ("Eximbank") — bản chất là **corpus ẩn danh hoá ≠ tên thật trong đề** (companies.csv là bằng chứng), nên "attest từ corpus" không bao giờ đóng được khoảng cách này.
3. `configs/pipelines/retrieval_frozen_v1.yaml` + `configs/execution/a6_identity.yaml` là nguồn identity thứ hai mâu thuẫn `active_snapshot.yaml`; không code nào đọc file frozen.

**Retrieval / Ranking**
4. S1 câm với câu không phân giải được entity (Q464) — trái docstring của chính nó.
5. N policy `min(e×y,10)` chưa được chứng minh, khác chính sách từng đạt điểm official.
6. S3 = Identity (không rerank) — đúng như khai báo, không phải bug.

**Answer / Submission**
7. 451/1012 câu nộp `answer: 0.0` — đòn bẩy điểm lớn nhất toàn dự án; chính `REQUIREMENTS_TRACEABILITY.md` closure gate #1 cũng tự tuyên bố điều này không đạt.
8. Multi-entity/rank/conditional routes chưa có (180 abstain riêng nhóm multi).
9. Binder ghi đè `relevant_tables/docs` → điểm retrieval phụ thuộc đường answer.

**Evaluation / Measurement**
10. ~89 file đo lường trỏ snapshot cũ `b3e968/286973` — mọi số sinh từ `tools/`, `experiments/`, và cả `src/.../evalkit/goldkit.py` phải coi là đo trên DB CŨ cho tới khi chứng minh ngược lại.
11. Gold: promotion-eligible = 0; 95 label retrieval đã nhiễm feature-engineering; answer gold n=31.
12. Reranker held-out gate tautology (không thể fail về checksum).
13. Số liệu V3/route/mypy/test bất nhất giữa các doc cùng ngày.

**Reproducibility / Environment**
14. `git_source_identity` fail-open → manifest chấp nhận `commit=null`.
15. `package-v3` yêu cầu `a6_path/dataframe/csv/table_cards.csv` (`main.py:428`) — **build active `c6887...` không có thư mục `dataframe/`** (chỉ silver.db + docs); chỉ build cũ `b3e968...` có. V3 packaging trên lineage active sẽ crash.
16. Môi trường sandbox (cả của team lẫn của audit này) chết vì hết đĩa — mọi verification runtime đang bị chặn về mặt hạ tầng.

**Architecture (P2)**
17. `domain/rules/table_features.py:25` import `infrastructure` — vi phạm ranh giới "domain: stdlib only" của chính AGENTS.md.
18. `parse_vn_number` (đường sản xuất build_silver/answer) **không có unit test trực tiếp** (0 hit trong tests/) — dù đây là nơi từng gây bug 1000×.

---

## D. Fixed / Partially Fixed

| Claim cũ | Hiện trạng |
|---|---|
| "data/ 0 byte, phải rebuild A6 + retrieval" (E2E plan P0-1..3) | **FIXED trên đĩa** — silver.db + retrieval.db cả 2 build đều tồn tại. Nhưng SHA chưa tái xác minh (không chạy được hash) → identity khớp manifest hay không: `UNKNOWN` |
| "data/dev gold mất 100%" (OLD_VS_NEW R5) | **FIXED** — `data/curated/dev-legacy/` đầy đủ (answer_gold 13 file, gold_tay pools) |
| "curated/dev vs dev-legacy mâu thuẫn" (E2E Q1) | **RESOLVED trên đĩa** — `dev-legacy` là bản tồn tại; `tests/test_answer_gold_provenance.py:12` trỏ đúng |
| OLD P0 RCE `eval()` + zip-slip | **FIXED trong NEW** theo OLD_VS_NEW (`ARTIFACT`, sandbox AST + validator) — không tái kiểm phiên này |
| Alias STB/EIB, `...` serialization, Q586 | **CHƯA sửa** — code/config y nguyên như red-team audit mô tả |

---

## E. False / Incorrect Team Claims

1. **"NEW dùng work.db của OLD trong production"** — sai; canonical đọc active paths (team tự bác trong mục False Alarms của red-team audit — xác nhận đúng).
2. **"Retrieval NEW không regression so với OLD" (RETRIEVAL_OLD_VS_NEW_AUDIT, 0 flips)** — kết luận rút ra từ **sai config đo** (full brands thay vì canonical `a6`); bản đo đúng config tìm ra Q586. Đây là false claim đã bị chính team supersede (RET-025) — audit này xác nhận cả hai vế.
3. **"Quality 8+ = 100% delivered"** (QUALITY_8PLUS) — tiêu đề gây hiểu nhầm: 100% là *cơ chế* được giao, còn mọi gate chất lượng vẫn BLOCKED/NOT_MEASURED; bản thân doc tự khai điều này ở dòng cuối.
4. **Số "64 hardcode"** — thấp hơn thực tế (~89 file khi tính cả experiments/ và tests/).
5. **Test count "2.124 collected"** (QUALITY_8PLUS:85) — artifact chính nó ghi 2.105 (`test_report.json`). Sai chép số.
6. **Answer Accuracy baseline 0.7841** (bảng user 27/08) — artifact 22/08 ghi `answer_accuracy: 0.1225`; 0.7841 là `docs_mrr5`. Mapping của red-team audit đúng, bảng user sai nhãn.

## F. Newly Discovered Problems (ngoài các doc của team)

1. **`companies.csv` của BTC tự ghi STB = "Sài Gòn Tài Lộc"** → RET-001 không sửa được bằng "sửa alias cho đúng tên thật" một cách đơn thuần: cần **lexicon dẫn xuất từ chính 1.012 câu hỏi BTC** (vẫn là dữ liệu BTC → không vi phạm corpus-only), và một mapping tên-thật→ticker có khai báo nguồn. Đây là quyết định policy, nên ghi ADR.
2. **Build A6 active thiếu `dataframe/csv/`** trong khi build cũ có đầy đủ → (a) `package-v3` crash trên lineage active; (b) cám dỗ trỏ tool sang build cũ càng lớn → khuếch đại vấn đề RET-014.
3. **Cụm doc 27/08 đang tự mâu thuẫn về tiền đề "repo không có dữ liệu"** — E2E plan và OLD_VS_NEW viết khi payload chưa khôi phục; nếu ai thực thi kế hoạch đó bây giờ sẽ rebuild thừa ~2×10 phút/6.5GB và có nguy cơ ghi đè lineage. Cần đóng dấu STALE lên hai doc này.
4. **`tests/**/__pycache__/*.pyc` nằm trong cây repo** (hygiene; gây nhiễu diff/collect).
5. **Fail-open kép về identity**: git null (mục C.14) + snapshots-verify không hash → một release "PASS toàn bộ gate" vẫn có thể không chứng minh được nó build từ nguồn nào. Hai lỗ này cộng hưởng, từng lỗ riêng lẻ đã được team ghi nhận nhưng chưa ai ghi nhận **tổ hợp**.

## G. Critical Risks (xếp theo tác động điểm)

1. **Abstain=0.0 trên 44,57% câu** — trần EXEC 0.5543; mọi thứ khác là thứ yếu so với việc hoặc (a) mở rộng coverage (multi/rank/conditional — RET-010), hoặc (b) có fallback có căn cứ thay vì 0.0. Chưa có phép đo nào chứng minh 0.0 tốt hơn fallback rẻ.
2. **Entity/alias trước S1** (RET-001/002/003/004) — lỗi cấu trúc, mất trắng theo case, đã xác nhận trong code; chưa có test chặn tái phát.
3. **Đo lường trên snapshot sai + gold nhiễm + doc bất nhất** — rủi ro "tối ưu nhầm hướng" cao hơn rủi ro thiếu tối ưu.
4. **N policy + refs-overwrite** — ảnh hưởng trực tiếp Tables/Docs F2, hướng chưa chứng minh trên official.
5. **Provenance fail-open** — nếu BTC yêu cầu truy vết, không chứng minh được ZIP ↔ nguồn.

## H. Final Verdict

**Nếu dùng repo hiện tại chạy evaluation/submission NGAY BÂY GIỜ, điều gì làm điểm sai/thấp?**

1. Phải nộp bằng **V2 canonical** — V3 chỉ 269 câu, 6/31 đúng local, và `package-v3` sẽ **crash** trên lineage active vì thiếu `dataframe/csv/table_cards.csv`.
2. Với V2: **451 câu nộp answer=0.0** → tối đa 55,43% câu có cơ hội điểm answer/execution. Đây là lý do số 1 điểm có thể thấp hơn cả baseline OLD 0.1225-coverage-99,9% nếu độ chính xác phần emitted không đủ ~22,1%.
3. Các câu nhắc **Eximbank / Sài Gòn Thương Tín / open-universe** (tối thiểu Q464, Q508, Q783, Q792) mất trắng ngay S1; ~61 QID khác bị nhiễu ranking vì alias chứa ` ...`.
4. `relevant_tables/docs` của câu trả lời được lấy từ binder chứ không phải top-N retrieval → điểm retrieval sẽ khác mọi số Hit@K nội bộ từng báo cáo; N=min(e×y,10) chưa từng được chứng minh trên official.
5. Mọi số nội bộ dùng để dự đoán điểm (Hit@10 0.9053, F2 0.3845, 14/31...) đo trên 9,39% mẫu đã nhiễm, một phần bằng tool trỏ **snapshot cũ** → không có căn cứ dự báo leaderboard; con số 27/08 (EXEC 0.2549) **không có receipt trong repo** để đối chiếu.
6. Nếu grader/BTC yêu cầu truy vết: git identity có thể null, snapshot verify không hash payload → không chứng minh được nguồn gốc ZIP.

**Khuyến nghị thứ tự (không thực thi trong audit này):** (1) quyết định policy abstain-vs-fallback bằng một phép đo; (2) sửa `attest_brands.py` serialization + lexicon entity từ câu hỏi (kèm ADR); (3) thêm regression test cho Q464/508/586/783/792 và invariant "YAML không chứa `...`"; (4) sửa git identity thành fail-closed; (5) chỉ sau đó mới bàn N policy / rerank / multi-entity theo đúng thứ tự experiment 1–12 của red-team audit.

---
*Mọi trích dẫn file:line trong report này đã được đọc trực tiếp trong phiên audit. Các con số không tái đo được đều gắn nhãn ARTIFACT hoặc UNKNOWN.*
