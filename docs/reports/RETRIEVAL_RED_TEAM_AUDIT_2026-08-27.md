# Retrieval Red-Team Audit — PROJECT_NEW vs PROJECT_OLD

**Ngày audit:** 2026-08-27  
**PROJECT_NEW:** `text2pandas/`  
**PROJECT_OLD:** `Text2Pandas-1/`  
**Phạm vi:** retrieval, search/ranking, dữ liệu/index, evaluation, lineage và tác động tới competition score.  
**Chế độ:** read-only đối với code, config, data, snapshot và artifact hiện hữu. Phép đo mới chỉ sinh output tạm dưới `/private/tmp`; thay đổi duy nhất trong project là report này.

**Cập nhật score:** report đã được bổ sung bảng điểm 27/08 do user cung cấp. `Execution Accuracy = 0.2549` là dòng duy nhất khớp rõ với baseline artifact 22/08. Các nhãn còn lại được giữ nguyên như input và đánh dấu chờ reconciliation vì bảng input lặp `Docs MRR@5` và không khớp key/value của `OFFICIAL_SCORE.json` ngày 22/08.

Quy ước bằng chứng:

- **Official:** metric do hệ thống chấm/score artifact báo lại; không suy diễn trọng số.
- **Local gold:** nhãn thủ công/source-grounded trong repo, không phải organiser-held gold.
- **Proxy:** nhãn sinh bằng heuristic; chỉ dùng chẩn đoán.
- **Diagnostic:** metric kỹ thuật như Hit@K, MRR, nDCG, latency.
- **Mechanical:** schema, replay, evidence/path, ZIP validity; PASS không đồng nghĩa answer đúng.

## 1. Executive Summary

**Verdict: `NOT READY`.** NEW có snapshot/index được định danh tốt hơn OLD và canonical run fail-closed, nhưng retrieval hiện có các lỗi đã chứng minh có thể làm mất điểm trực tiếp:

1. **Hard-filter entity làm gold không thể hồi phục.** Q508 mất STB do alias sai; 2/4 bảng gold bị loại ngay S1. Q783 và Q792 bị mất EIB vì canonical dùng alias A6 không chứa `Eximbank`. Q464 không resolve entity và nhận đúng 0 candidate.
2. **Có regression OLD-correct → NEW-wrong.** Canonical NEW dùng file brand A6 có 68 giá trị bị nối literal `...`; Q586 từ gold rank 5/6 ở OLD xuống 25/29 ở NEW. Trên cùng 95 QID: OLD Hit@10 `86/95`, NEW `85/95`; category B có đúng Q586.
3. **Output policy chưa được chứng minh cho score.** NEW pre-bind dùng `N = entities × years`, cap 10; OLD official freeze khai `clamp(3 × n_o, 1, 30)`. Trên local gold 95, NEW pre-bind Tables F2 chỉ `0.3035`, trong khi áp policy `3×` lên cùng ranking cho `0.4624`. Final evidence rewrite nâng lên `0.3814`, nhưng tạo 14 positive và 10 negative hit flips, nên score retrieval phụ thuộc downstream binding.
4. **Multi-entity là điểm gãy lớn nhất downstream.** Trên 31 answer-gold: `multi = 0/12`, `max_min = 0/3`, `count = 0/1`; full canonical report ghi 180 abstention `MULTI_ENTITY_OPERATION_NOT_SUPPORTED`. Đây là direct Answer/Execution score loss, không phải lỗi validator.
5. **Đã có score 27/08 nhưng chưa đủ để tuyên bố production.** Dòng không mơ hồ cho thấy Execution Accuracy tăng từ `0.1225` lên `0.2549` (`+0.1324`). Hai dòng F2 do user cung cấp đều giảm (`−0.1027`, `−0.1215`), nhưng mapping Docs/Tables đang xung đột với artifact 22/08. Ngoài ra, 95 retrieval labels đã bị dùng cho feature engineering; 31 answer cases chỉ chiếm 3.06% đề và registry ghi `promotion_eligible_records: 0`.

Những điểm NEW chắc chắn tốt hơn: active snapshot là immutable, verifier kiểm được lineage DB; evidence của answer được map từ exact bound table; ranking tie-break ổn định; S3 learned model không bị promote khi thiếu held-out. Score mới chứng minh **Execution Accuracy cao hơn mốc 22/08**, nhưng chưa chứng minh retrieval tốt hơn; theo chính bảng do user cung cấp, cả hai dòng F2 đều giảm.

## 2. Problem / Competition Objective

### Hợp đồng bài toán

- **Input:** 1,012 record `{id: int, question: string}` bằng tiếng Việt.
- **Output:** ZIP có đúng một JSON ở root và thư mục `data/` chứa CSV evidence. Mỗi answer record gồm `id`, `question`, `answer`, `relevant_docs`, `relevant_tables`, `evidence[{variable,csv_path}]`, `pandas_query`.
- **Mục tiêu:** tìm đúng tài liệu/bảng, sinh truy vấn Pandas chạy được trên evidence, và trả numeric answer đúng tolerance.
- **Official metrics được competition document nêu:** macro Precision, Recall, F2 cho retrieval; Answer Accuracy; Execution Accuracy.
- **Trọng số/overall aggregation:** `NOT SPECIFIED` trong tài liệu local được audit. Không được tự cộng hoặc suy trọng số.

### Metric trực tiếp và metric phụ

- Trực tiếp: Answer Accuracy, Execution Accuracy, retrieval Precision/Recall/F2; dashboard artifact của OLD còn hiển thị Tables và Docs tách riêng.
- Diagnostic: Hit@K, MRR, nDCG, candidate recall, stage funnel, latency.
- Operational/mechanical: coverage, replay consistency, evidence validity, ZIP/submission validity.
- Không được dùng để tuyên bố success: proxy metrics, replay PASS, validator PASS, số answer emitted, parser field coverage hoặc V3 shadow coverage khi chưa có correctness gold.

## 3. Official Scorecard

### Score update do user cung cấp — giữ nguyên nhãn

| Metric theo input | Trước — 22/08 | Sau — 27/08 | Thay đổi | Reconciliation status |
|---|---:|---:|---:|---|
| **Execution Accuracy** | **0.1225** | **0.2549** | **+0.1324** | Khớp artifact 22/08; new value chưa có receipt/ZIP checksum trong repo |
| F2 Macro Docs | 0.3538 | 0.2511 | −0.1027 | Baseline `0.3538` là `tables_f2_macro` trong artifact 22/08 |
| F2 Macro Tables | 0.7536 | 0.6321 | −0.1215 | Baseline `0.7536` là `docs_f2_macro` trong artifact 22/08 |
| Tables Recall | 0.1933 | 0.2904 | **+0.0971** | Baseline `0.1933` là `tables_precision` trong artifact 22/08 |
| Docs MRR@5 — dòng 1 | 0.4744 | 0.2475 | −0.2269 | Baseline `0.4744` là `tables_recall` trong artifact 22/08 |
| Docs Precision | 0.4066 | 0.3375 | −0.0691 | Baseline `0.4066` là `tables_mrr5` trong artifact 22/08 |
| Docs Recall | 0.5062 | 0.6877 | **+0.1815** | Baseline `0.5062` là `docs_precision` trong artifact 22/08 |
| Docs MRR@5 — dòng 2 | 0.8941 | 0.6253 | −0.2688 | Baseline `0.8941` là `docs_recall` trong artifact 22/08; nhãn bị lặp |
| Answer Accuracy | 0.7841 | 0.7650 | −0.0191 | Baseline `0.7841` là `docs_mrr5`; artifact ghi Answer Accuracy `0.1225` |

**Kết luận reconciliation:** report không tự hoán đổi các nhãn 27/08 khi chưa có raw score JSON, dashboard screenshot hoặc submission receipt. Có thể dùng chắc chắn dòng Execution Accuracy. Các delta còn lại là **user-provided score rows with unresolved metric mapping**, không phải exact-ZIP causal evidence.

### Scorecard đã phân loại theo mức bằng chứng

| Metric | Definition / scope | Class | Weight/impact | Dataset | Current NEW | OLD artifact | Status |
|---|---|---|---|---|---:|---:|---|
| Answer Accuracy | Answer đúng trong tolerance / toàn bộ câu | Official | Direct; weight `NOT SPECIFIED` | Organiser hidden | User table: `0.7650` | `0.1225` | **Label/baseline conflict; do not compare yet** |
| Execution Accuracy | Code chạy **và** result đúng / toàn bộ câu | Official | Direct; weight `NOT SPECIFIED` | Organiser hidden | `0.2549` | `0.1225` | `+0.1324`; identity receipt still missing |
| Tables Precision | Macro precision của `relevant_tables` | Official/dashboard | Direct; weight `NOT SPECIFIED` | Organiser hidden | `NOT IDENTIFIABLE` from supplied labels | `0.1933` | User table calls baseline `Tables Recall` |
| Tables Recall | Macro recall của `relevant_tables` | Official/dashboard | Direct; weight `NOT SPECIFIED` | Organiser hidden | User table: `0.2904` | `0.4744` | **Label/baseline conflict; do not compare yet** |
| Tables F2 | Macro F2, recall nặng hơn precision | Official/dashboard | Direct; weight `NOT SPECIFIED` | Organiser hidden | User table labelled Tables: `0.6321`; local final-output `0.3814`/95 | `0.3538` | **Docs/Tables labels appear swapped** |
| Docs Precision | Macro precision của `relevant_docs` | Organiser dashboard | Weight `NOT SPECIFIED` | Organiser hidden | User table: `0.3375`; local `0.7168`/95 | `0.5062` | **Label/baseline conflict**; local not comparable |
| Docs Recall | Macro recall của `relevant_docs` | Organiser dashboard | Weight `NOT SPECIFIED` | Organiser hidden | User table: `0.6877`; local `0.6557`/95 | `0.8941` | **Label/baseline conflict**; local not comparable |
| Docs F2 | Macro F2 của docs | Organiser dashboard | Weight `NOT SPECIFIED` | Organiser hidden | User table labelled Docs: `0.2511`; local `0.6636`/95 | `0.7536` | **Docs/Tables labels appear swapped** |
| Tables/Docs MRR@5 | Reciprocal rank đầu tiên | Dashboard/diagnostic | Direct weight `UNKNOWN` | Organiser hidden | Supplied rows `0.2475`, `0.6253`, plus `0.7650` labelled Answer | Tables `0.4066`; Docs `0.7841` | Mapping unresolved; `Docs MRR@5` appears twice |
| Retrieval Hit@10 | Có ≥1 gold table trong top 10 | Local diagnostic | Không phải official score | Manual 95 | `85/95 = 0.8947` | `86/95 = 0.9053` | Paired canonical |
| Retrieval P/R/F2@10 | Macro trên fixed top-10 | Local diagnostic | Không phải actual submission N | Manual 95 | P `0.2105`; R `0.7012`; F2 `0.3786` | P `0.2126`; R `0.7117`; F2 `0.3845` | NEW thấp hơn do Q586 |
| MRR / nDCG@10 | Rank quality | Local diagnostic | Không được gọi là official | Manual 95 | `0.5456` / `0.5481` | `0.5459` / `0.5523` | — |
| Candidate recall | Gold còn sau S1 | Local diagnostic | Chẩn đoán hard-filter | Manual 95 | `95/95` | `95/95` | Không phủ Q508/Q783/Q792/Q464 |
| Answer Accuracy local | Correct / 31 evaluable | Local gold | Diagnostic only | Answer gold 31 | `14/31 = 0.4516` | `NOT COMPARABLE` | Wilson 95% CI `[0.2916, 0.6223]` |
| Execution Accuracy local | Correct + clean replay / 31 | Local gold | Diagnostic only | Answer gold 31 | `14/31 = 0.4516` | `NOT COMPARABLE` | — |
| Coverage | Có answer / 1,012 | Operational | Có thể tạo ceiling nhưng không là accuracy | Full corpus | `561/1012 = 0.5543` | Không cùng pipeline | — |
| Replay consistency | Query emitted replay khớp answer | Mechanical | Không chứng minh answer đúng | Full canonical | `561/561 = 1.0` | Historical evidence khác | PASS |
| Evidence validity | Path/variable/query contract hợp lệ | Mechanical | Submission gate | Full canonical | PASS trên acceptance artifact | Historical | Không phải relevance/correctness |
| Submission validity | 1,012 records, schema/ZIP đúng | Mechanical | Invalid có thể score collapse | Full canonical | PASS trên acceptance artifact | Historical | Current Git lineage đang hỏng |

## 4. End-to-End Score Dependency

Canonical NEW không phải một chuỗi tuyến tính duy nhất; sau ranking có hai nhánh và nhánh answer có thể ghi đè retrieval refs:

```text
Question
  -> parse entity/year/basis/mode
  -> S1 hard filters (ticker, year range, retrieval_ready)
  -> S2 BM25 + structural bonuses
  -> S3 identity top-50
       |-> top-N refs ---------------------------> fallback submission refs
       |-> top-50 answer pool -> cell binding -> Pandas -> execution -> answer
                                            |-> exact bound tables overwrite refs
  -> package -> validate/replay -> official evaluation
```

| Failure | Immediate effect | Downstream effect | Score at risk |
|---|---|---|---|
| Entity/year hard-filter drops gold | Gold absent from S1 | Ranking/binding cannot recover | Tables/Docs F2; usually Answer/Execution |
| Candidate present but below top-50 | Answer pool misses operand | Bind abstains hoặc binds alternative | Answer/Execution; retrieval refs may still miss |
| Candidate in top-50 but below output N | Answer may still succeed; fallback refs miss | Answered records rewrite refs, abstains do not | Tables/Docs score depends on route |
| Wrong rank/entity/year/basis | Wrong table selected | Wrong cell/unit/formula | All four score families |
| Correct retrieval, wrong binding/operation | Retrieval score may pass | Wrong/abstained answer | Answer/Execution only |
| Correct answer from alternative table | Answer passes local numeric gold | Exact table-gold may appear wrong | Shows table labels are non-exhaustive |
| Validator/replay PASS but value wrong | Mechanical gates pass | Official correctness fails | Answer/Execution |

## 5. OLD Retrieval Audit

| Stage | Implementation | Input → output | Algorithm/parameters | Failure modes / coverage |
|---|---|---|---|---|
| S0 intent | `Text2Pandas-1/src/retrieval/question_intent.py` | question → tickers, years, basis, mode | Rules + full aliases/brands | Alias ambiguity; no open-universe retrieval |
| S1 candidate | `filter_s1.py:filter_tables` | intent → table candidates | `ticker IN`, year `[min,max+1]`, `retrieval_ready=1`; basis soft | Wrong entity makes gold unreachable |
| S2 rank | `rank_s2.py`, `evalkit/stages.py` | candidate pool → top-50 | FTS5 BM25 + period/unit/basis/code/clean bonuses | Global top-K; broad OR; hand weights |
| S3 | `IdentityReranker` | top-50 → bounded list | Pass-through | **NO ACTUAL RERANKING** |
| Submission refs | Frozen refs artifact | ranked refs → docs/tables | Official freeze says `clamp(3*n_o,1,30)` | Source adapter itself says product cap-10; lineage is inconsistent |
| Answer path | Multiple historical tools/overlays | separate retrieval/fact path | Frozen parent ZIP + patches | Retrieval refs and answer path were not one clean causal pipeline |

OLD reported official score is useful as a historical anchor, but `official_identity_status.json` says `OFFICIAL_IDENTITY_NOT_INDEPENDENTLY_VERIFIED`; therefore it cannot prove exact-ZIP causal deltas.

## 6. NEW Retrieval Audit

| Stage | File/function | Input → output | Actual production behavior | Key assumptions / failure |
|---|---|---|---|---|
| Alias load | `canonical_run.py:538`, `alias_store.load_aliases("a6")` | tracked YAML → ticker aliases | 100 tickers + 68 attested brand entries | 68 entries contain literal `...`; 9 useful brands excluded |
| Intent | `question_intent.py:parse_intent` | question → `Intent` | boundary-aware company/ticker match; mode; years; basis | Missing alias becomes missing ticker before S1 |
| S1 | `filter_s1.py:filter_tables` | intent → `Candidate[]` | hard ticker, loose year range, readiness; basis soft | Empty targets return `[]`; wrong target is unrecoverable |
| Query terms | `query_terms.py` | question/aliases → ≤24 terms | alias stripping, year removal, folded stop words | Alias literal mismatch; diacritic collisions; tail truncation |
| FTS/BM25 | `rank_s2.py:rank` | S1 candidates + FTS query → scores | weights `(0,0,2,1,4,1.5)`; min-max per query | Bonus can dominate; OR query broad |
| Structural score | same | metadata → score bonus | period `.35`, unit `.15`, stmt `.10`, basis `.30`, code `.45`, clean multiplier `.70–1.0` | Metadata coverage sparse; weights not held-out calibrated |
| S3 | `submission_adapter.py:109` | top-50 → top-50 | `IdentityReranker` | **NO ACTUAL RERANKING** |
| Output N | `submission_adapter.py:113-116` | intent → refs count | `min(entity_count × year_count, 10)` | Not same as OLD official freeze policy |
| Answer pool | `canonical_run.py` | ranked top-50 → cells | rule/typed binders | Multi/rank/conditional routes incomplete |
| Final refs | `canonical_run.py:695-708` | bound evidence → docs/tables | Successful answer overwrites retrieval refs | Retrieval score coupled to binding correctness |

No vector, embedding, dense, neural-hybrid or cross-encoder retrieval exists in canonical V2. The only production search is sparse FTS5 plus rules/metadata priors.

## 7. OLD vs NEW Architecture Diff

| Area | OLD | NEW | Regression? | Evidence / impact |
|---|---|---|---|---|
| Active data identity | Mutable/frozen `work.db` lineage | Immutable active raw→A6→retrieval IDs | Improvement | Active verifier PASS |
| Alias branch | Full brands | A6-attested brands | **Yes** | Q783/Q792 lose EIB; Q586 rank regression |
| Alias serialization | Clean values | Literal `...` in 68 values | **Yes** | `attest_brands.py:109` |
| Entity parser mechanics | More substring-oriented | Boundary/nesting/order aware | Likely improvement | Mechanism tests; no broad independent-gold lift |
| Core S1/S2 | Sparse FTS + rules | Largely same | No proven improvement | Same gold rank in most cases |
| S3 | Identity | Identity | No | Learned model is dev-only |
| Official output N | Freeze says `3*n_o`, cap 30 | target×year, cap 10 | **Unvalidated change** | Local F2 sensitivity is large |
| Answer grounding | Historical refs and answer overlays separated | Exact bound evidence controls refs | Contract improvement, score effect mixed | 14 positive / 10 negative hit flips on gold95 |
| Snapshot content | 2,633,554 observations | 2,634,120 (+566) | Unproven | Lexical fields unchanged; readiness/features changed |
| Reproducibility | Historical artifact packets | Active manifest + checksums | Improvement in design | Current `.git` corruption nulls source identity |

Paired classification on canonical OLD-full vs NEW-A6, same 95 QID:

| Category | Count | QIDs |
|---|---:|---|
| A. OLD wrong → NEW correct | 0 | — |
| B. OLD correct → NEW wrong | 1 | **586** |
| C. Both correct | 85 | — |
| D. Both wrong | 9 | 374, 376, 385, 397, 436, 542, 723, 767, 975 |

McNemar exact two-sided `p=1.0` vì chỉ có một discordant pair; điều này nói sample chưa đủ power, **không phủ nhận regression case-level Q586**.

## 8. Data Audit

### Corpus identity and coverage

| Quantity | OLD | NEW | Delta |
|---|---:|---:|---:|
| Documents | 1,973 | 1,973 | 0 |
| Tickers | 100 | 100 | 0 |
| Tables/cards | 146,246 | 146,246 | 0 |
| Observations | 2,633,554 | 2,634,120 | +566 |
| Unique table IDs/evidence refs | 146,246 | 146,246 | 0 |
| Retrieval DB bytes | 4,240,060,416 | 4,239,663,104 | −397,312 (−0.009%) |

All document/table tickers, years, IDs and evidence refs passed internal consistency checks. There are no duplicate `directory_doc_id` or `evidence_ref`; all NEW values have non-null decimal values and table/doc IDs resolve.

### Missing/sparse retrieval fields in NEW

| Field | Missing/blank | Rate | Retrieval impact |
|---|---:|---:|---|
| Document basis | 55/1,973 | 2.788% | Basis prior cannot distinguish |
| Table basis | 403/146,246 | 0.276% | Table-level context incomplete |
| FTS `section_text` | 24,107/146,246 | 16.484% | Loses section signal |
| `row_terms` | 1,606/146,246 | 1.098% | Weak/no metric lexical signal |
| `metric_codes` | 136,826/146,246 | 93.559% | Code bonus almost always unavailable |
| `periods` | 15,866/146,246 | 10.849% | Period bonus unavailable |
| `units` | 12,784/146,246 | 8.741% | Unit bonus unavailable |
| Observation metric code | 2,278,635/2,634,120 | 86.505% | Downstream metric binding relies on text |
| Observation period end | 164,096/2,634,120 | 6.230% | Temporal binding gap |
| Observation unit unknown/blank | 115,497/2,634,120 | 4.385% | Unit gating/score gap |

There are 2,491 table-vs-document basis mismatches in NEW, all where document basis is NULL but table inference supplies a basis. Canonical V2 ranks on `documents.basis`, so this recovered table-level information is invisible to the basis bonus.

NEW changes 2,066 table-card semantic hashes, 3,806 `execution_ready_obs`, 2,043 `units`, 182 observation counts and 24 periods among shared table IDs. This is materially larger than the +566 new observations because readiness was also reclassified. No independent held-out report proves the rank/answer effect.

## 9. Index Audit

### Schema and analyzer

`table_cards_fts(table_uid UNINDEXED, ticker, section_text, context_clean, row_labels, col_labels, tokenize='unicode61 remove_diacritics 2')` is identical in OLD and NEW. Required indexes `ix_doc_tky`, `ix_obs_tab_period`, `ix_tc_stmt_ticker`, `ix_tc_ticker_year` exist.

| Field | Indexed/search role | Weight / use | Finding |
|---|---|---:|---|
| `table_uid` | FTS UNINDEXED | 0 | Correct identity carrier |
| `ticker` | FTS indexed | 0 | Entity already hard-filtered; no BM25 effect |
| `section_text` | FTS | 2.0 | 16.48% blank |
| `context_clean` | FTS | 1.0 | No blank values found |
| `row_labels` | FTS | 4.0 | Primary lexical signal; 1.10% blank |
| `col_labels` | FTS | 1.5 | Complete in audit |
| Year | B-tree/document filter | hard range + period bonus | Not FTS; appropriate |
| Basis | document metadata | soft `.30` | Table inference ignored |
| Unit/period/code | card metadata | structural bonus | Sparse as above |

No stemming is configured. Diacritics folding improves recall for typed/untyped Vietnamese but also collapses homographs. Query stop-word folding compounds that problem. FTS uses OR phrases/tokens; it is recall-oriented but often matches a very broad portion of the index, increasing false positives and latency.

## 10. Query Processing Audit

Production path: remove resolved entity aliases → remove years → tokenize Vietnamese → folded stop words → deduplicate → truncate to 24 terms → add 2/3-gram phrases and OR individual tokens.

Findings:

- **Canonical alias stripping is broken for 68 attested brand values.** `yaml.safe_dump(...).strip()` writes `name\n...`; YAML reload preserves `"name ..."`. Across 1,012 questions, A6 vs full alias removal changes terms in 61 QIDs.
- **Q586 proof:** full aliases remove `Cảng Hàng không`, gold ranks 5/6; A6 aliases leave `Cảng`, `Hàng`, gold ranks 25/29.
- **Folded stop words are lossy.** Source records 621/1,012 affected before canonical alias dropping; current audit finds 560/1,012 term lists differ between `fold` and `dau`. Examples: `tài→tai` collides with `tại`, `động→dong` with `đồng`, `cổ→co` with `có`.
- **But the proposed `stop_mode=dau` is not validated.** OLD proxy A/B on 990 paired QIDs makes Hit@10 worse `0.9162→0.9051`, F2@10 `0.4764→0.4664`, with 4 flip-ins and 15 flip-outs. Do not change based on linguistic intuition alone.
- **24-term truncation affects 58/1,012 questions**, max 43 content terms. Tail terms include meaningful metrics such as `lãi vay`, `tồn kho`, `biên lợi nhuận gộp`.
- No query is left with zero BM25 terms, but Q464 still gets no candidates because entity parsing is empty.

## 11. Entity Audit

Canonical distribution: 748 one-target, 75 two-target, 69 three-target, 67 four-target, 52 five-or-more, and one zero-target question. Modes: 726 single, 162 screen, 66 compare, 57 related, 1 screen_open.

### Proven entity failures

| QID | Question signal | Expected entities | Canonical entities | Effect |
|---:|---|---|---|---|
| 508 | OCB, ACB, **Ngân hàng TMCP Sài Gòn Thương Tín** | OCB, ACB, STB | OCB, ACB | 2/4 gold tables (both STB) dropped at S1; correct answer depends on STB |
| 783 | MBBank vs **Eximbank** | MBB, EIB | MBB | All EIB candidates impossible |
| 792 | **Eximbank** vs MBBank | EIB, MBB | MBB | Directional difference cannot be answered correctly |
| 464 | Open universe “trong các công ty…” | All eligible companies | none | S1 empty; all score components zero for the case |

Root causes:

- Base alias labels STB as `Sài Gòn Tài Lộc`, not the question’s `Sài Gòn Thương Tín` (`company_alias_v1.yaml:261-263`).
- A6 policy intentionally excludes unattested `Eximbank`, although the competition questions use it.
- `filter_tables` returns `[]` for no targets, contradicting the `Intent.is_resolved` documentation that says unresolved S1 should take a broad non-ticker path.

The general parser is stronger than OLD for word boundaries, nested names and directional order, but these concrete alias/data failures dominate the claim.

## 12. Year Audit

- Parsed year-count distribution: 655 questions with one year, 173 with two, 62 with three, 67 with four, 50 with five, 4 with six, and Q412 with none.
- S1 uses `doc_year BETWEEN min(years) AND max(years)+1`. This safely allows a report from the following year to contain the requested comparative column.
- On 31 answer-gold cases, year/ticker/basis S1 retains complete gold for 30/31; the only miss is Q508 and is caused by entity, not year.
- `year_slack=0` OLD proxy A/B reduced candidate hit `0.9980→0.9831`; current slack=1 is therefore safer.
- **Noise risk:** 232 questions list non-contiguous years, yet BETWEEN admits every intermediate year; max seven unasked years. Precision/latency cost is `NOT ISOLATED`.
- Q412 has no year; retrieval searches all years for three entities. The semantic interpretation of “latest/which period” is unresolved and downstream currently abstains.

## 13. Basis Audit

Production uses basis as a **soft** `.30` bonus. This avoids the proven hard-filter tradeoff: on 1,006 proxy QIDs, hard basis lowered candidate hit by 2.19 points and F2@10 by 5.24 points.

Remaining risks:

- Unqualified questions receive a consolidated prior even though the competition document reviewed here does not specify this default. It is an implementation assumption inherited from organiser parser behavior.
- 2,491 NEW table/document basis mismatches mean available table-level inference is not used by V2 ranking.
- In the 124-QID diagnostic union, explicit-basis final refs include wrong basis in Q128 and Q962. Q508 answer-gold also demonstrates that explicit separate scope does not help if the entity itself is missing.
- Soft basis is correct for recall safety, but the current output has no explicit two-tier “matching basis first, fallback only if absent” contract.

## 14. Hard Filter Audit

| Filter | Condition/order | Gold drop evidence | Severity conclusion |
|---|---|---|---|
| Entity | First: `d.ticker IN targets` | Q508 drops 2/4 gold tables; Q783/Q792 exclude EIB | **Critical/P0** |
| Empty targets | Immediate `return []` | Q464 receives 0 candidates | **Critical/P0** |
| Basis | Production soft, not WHERE | 0 drops on manual 95; hard A/B is harmful | Keep soft; no action to harden |
| Year | `[min, max+1]` | No year-caused drop on 31 gold; slack0 proxy harms recall | Current choice defensible |
| `retrieval_ready=1` | Last S1 predicate | 146,246/146,246 are 1 | Current no-op/guard |
| Statement type | No hard filter | None | Correct recall-oriented choice |

Measured answer-gold S1 funnel: 31 QIDs, 116 distinct required gold tables; S1 retains 114 and drops 2, both in Q508. Pool size on this slice: min 101, median 760, max 2,198.

## 15. Candidate Generation Audit

Canonical candidate generation is not dense/hybrid: it is metadata-filtered sparse retrieval. On manual retrieval gold 95, candidate hit is `95/95`; therefore the dominant problem on that sample is not corpus absence or S1, but ranking/cutoff.

Funnel on manual 95 for canonical NEW:

```text
95 labelled QIDs
  -> 95 S1 non-empty
  -> 95 have ≥1 gold in S1
  -> 92 have ≥1 gold in top-50
  -> 85 have ≥1 gold in top-10
```

Six of the original nine misses have gold at ranks 11–19; three are outside top-50. Q586 adds one new top-10 miss but remains recoverable at ranks 25/29, which is why the answer pool can still solve it while fallback submission refs cannot.

Large pools are normal: screen cases in gold95 reach 1,156–2,663 S1 candidates. Global top-50 and top-N do not guarantee one useful table per entity/operand.

## 16. Ranking Audit

Actual score is normalized BM25 plus fixed priors, then multiplied by clean ratio:

```text
score = bm25_minmax
      + 0.35*period + 0.15*unit + 0.10*statement
      + 0.30*basis + 0.45*metric_code
score *= 0.70 + 0.30*clean_ratio
tie-break = table_uid ascending
```

Risks:

- Combined bonuses can reach 1.25, larger than the full normalized BM25 range `[0,1]`. Incorrect metadata can overpower the text match.
- Min-max is per candidate pool, so score scale changes with pool composition.
- `metric_code` is absent from 93.56% of cards; the strongest `.45` signal has very limited coverage.
- Global cutoff is weak for multi-entity: manual `screen` Hit@10 `23/29`, F2@10 `0.2901`; 6/10 current misses are screen.
- Per-ticker fanout code exists but production passes `None`. Proxy fanout2 is mixed/slightly worse overall, so it needs protected-slice held-out evaluation rather than automatic activation.
- Development primary-statement boost reported F2 lift, but it was feature-selected on the same 95 labels and cannot support promotion.

## 17. Reranker Audit

Canonical V2 constructs `IdentityReranker`; it preserves S2 order and only truncates. **There is NO ACTUAL PRODUCTION RERANKING and no ML behavior in S3.**

NEW’s linear 13-feature reranker is deterministic and checksum-bound, but evidence is development-only:

| Split | n | Identity F2 | Linear F2 | Identity Hit@10 | Linear Hit@10 |
|---|---:|---:|---:|---:|---:|
| Train | 76 | 0.3954 | 0.3931 | 0.9211 | 0.9474 |
| Dev | 19 | 0.3406 | 0.4231 | 0.8421 | 0.9474 |
| Independent held-out | 120 IDs reserved | `NOT MEASURED` | `NOT MEASURED` | — | — |

The 95 legacy labels were already used for feature engineering; held-out artifact status is `BLOCKED_AWAITING_INDEPENDENT_LABELS`. Keeping identity in production is the correct current decision.

## 18. Retrieval Metrics Audit

### Paired same-gold result

| Metric | OLD full brands | NEW canonical A6 | Delta NEW−OLD |
|---|---:|---:|---:|
| Candidate hit | 95/95 | 95/95 | 0 |
| Hit@1 | 33/95 | 33/95 | 0 |
| Hit@10 | 86/95 | 85/95 | −1/95 |
| Precision@10 | 0.2126 | 0.2105 | −0.0021 |
| Recall@10 | 0.7117 | 0.7012 | −0.0105 |
| F2@10 | 0.3845 | 0.3786 | −0.0058 |
| MRR | 0.5459 | 0.5456 | −0.0004 |
| nDCG@10 | 0.5523 | 0.5481 | −0.0042 |

This covers only `95/1012 = 9.39%` and is contaminated development evidence. The correct claim is “Hit@10 on the labelled 95 slice,” never “retrieval accuracy.” NEW Hit@10 Wilson 95% CI is `[0.8170, 0.9418]`.

### Actual NEW submission-field behavior on the same 95

| Output variant | P | R | Macro F2 | Any-hit | Complete-gold |
|---|---:|---:|---:|---:|---:|
| Fixed top-10 diagnostic | 0.2105 | 0.7012 | 0.3786 | 85 | 57 |
| Production pre-bind N | 0.3606 | 0.2971 | 0.3035 | 50 | 15 |
| Same ranking, `3×N` cap30 | 0.2540 | 0.6101 | 0.4624 | 77 | 44 |
| Final output after evidence rewrite | 0.4402 | 0.3746 | 0.3814 | 54 | 25 |

The actual submission score cannot be inferred from fixed top-10 metrics. Output N and answer binding materially change both precision and recall.

## 19. Gold vs Proxy Audit

OLD proxy on 1,006 measurable QIDs: Hit@1 `0.7256`, Hit@10 `0.9155`, F2@10 `0.4748`, MRR `0.7853`. It is broad coverage but not truth.

On the same 28 QIDs with manual and proxy labels:

| Metric | Manual | Proxy |
|---|---:|---:|
| Hit@1 | 0.3929 | 0.7500 |
| Hit@10 | 1.0000 | 0.9286 |
| Recall@10 | 1.0000 | 0.6572 |
| F2 | 0.3784 | 0.4978 |
| MRR | 0.6199 | 0.7972 |
| Median gold tables | 1 | 8 |

Proxy materially overstates early-rank quality and changes F2 semantics by labelling many lexical matches as relevant. It is useful for broad A/B screening, not promotion, official comparison or answer correctness.

## 20. Retrieval Failure Funnel

### Manual retrieval gold 95

| Stage | Count | Conversion |
|---|---:|---:|
| Total labelled | 95 | 100% |
| Parsed with targets/year | 95 | 100% |
| S1 candidate generated | 95 | 100% |
| ≥1 gold survives S1 | 95 | 100% |
| ≥1 gold in top-50 | 92 | 96.84% |
| ≥1 gold in top-10 | 85 | 89.47% |
| ≥1 gold top-1 | 33 | 34.74% |

Failure classes: F1 empty `0`, F2 hard drop `0`, F3 rank/cutoff miss `10`, F4 reranker regression `0`, F5 pass `85`. This slice does **not** include the proven hard-filter cases Q508/Q783/Q792/Q464.

### Full canonical operational funnel

```text
1,012 questions
  -> 1,011 resolve at least one entity
  -> 1,011 obtain retrieval candidates
  -> 561 produce executable answers
  -> 561/561 replay consistently
  -> official correctness NOT MEASURED
```

Replay and validity close mechanical risk only; the 451 abstentions and unknown correctness remain score risk.

## 21. Retrieval → Answer Impact

The audit reran canonical NEW on the union of retrieval and answer-gold QIDs, then joined exact answer correctness with whether **all labelled answer-gold tables** were present in the top-50 answer pool.

| Case | Count | % of 31 |
|---|---:|---:|
| Retrieval complete → Answer correct | 13 | 41.94% |
| Retrieval complete → Answer wrong | 3 | 9.68% |
| Retrieval incomplete → Answer correct | 1 | 3.23% |
| Retrieval incomplete → Answer wrong | 14 | 45.16% |

Conditional rates: answer correct `13/16 = 81.25%` when exact labelled provenance is complete, versus `1/15 = 6.67%` when incomplete. Of 17 answer failures, 14 co-occur with incomplete retrieval.

Important limits:

- This is correlation, not full causal attribution. Many incomplete cases are unsupported multi-entity operations; retrieval and route complexity share a cause.
- Answer gold provenance is not exhaustive. Q688 is answer-correct despite missing one labelled exact table, showing a valid alternative table can exist.
- Even when retrieval is complete, 3 cases fail downstream. Therefore “retrieval good ⇒ answer good” is false.
- Exact final submission refs cover all labelled provenance in only 7/31 cases, including only 7/14 correct answers; table labels are too narrow to interpret this as official relevance failure.

## 22. Operation-Type Impact

| Local operation | n | Top-50 complete | Answer correct | Main bottleneck |
|---|---:|---:|---:|---|
| Direct lookup | 7 | 7 | 7 | Strong on this small slice |
| Ratio / derived metric | 6 | 5 | 6 | Alternative provenance possible |
| Difference / arithmetic | 1 | 1 | 1 | Too small to generalize |
| Average / aggregation | 1 | 1 | 0 | Downstream multi-entity unsupported |
| Count / conditional | 1 | 0 | 0 | Retrieval breadth + route |
| Max/min / ranking | 3 | 0 | 0 | Select-at-arg and multi-table completeness |
| Multi-entity compound | 12 | 2 | 0 | Dominant failure cluster |

Mapped to requested families: direct lookup is currently strongest; arithmetic/ratio is promising but sample-small; ranking, conditional query, aggregation and multi-entity are the largest observed Answer/Execution losses. These classes overlap semantically, so counts must not be added across alternative taxonomies.

## 23. Performance Audit

Paired retrieval-only diagnostic on the same 95 questions, warm/local environment:

| Metric | OLD | NEW | Delta |
|---|---:|---:|---:|
| Mean | 396.82 ms | 394.32 ms | −2.50 ms |
| p50 | 243.03 ms | 242.07 ms | −0.96 ms |
| p95 | 1,167.57 ms | 1,151.24 ms | −16.33 ms |
| DB size | 4,240,060,416 B | 4,239,663,104 B | −0.009% |

This is not a locked cold/warm benchmark and does not prove NEW is faster. Throughput, concurrency scaling, cold-cache p95/p99, build time and peak RSS are `NOT MEASURED` on a same-protocol OLD/NEW run. Historical OLD profile says BM25 consumes roughly 85% time and RSS about 235–237 MB, but it cannot be assigned to current NEW.

## 24. Determinism Audit

Positive evidence:

- Rank sorting is `(-score, table_uid)`; linear reranker preserves original rank then UID.
- FTS query, S1 ticker set and submission refs have stable ordering.
- A two-process diagnostic over 11 risk QIDs with `PYTHONHASHSEED=1` and `2` produced the same SHA-256 `53c2776b...21fb0` for candidate counts, top-20 and output refs.
- Snapshot verifier validates DB bytes/schema/indexes/source build.

Gaps:

- Full 1,012 current canonical two-run byte identity was not regenerated during this no-overwrite audit; only historical acceptance evidence exists.
- `a6/cleaning.py:269` iterates `set(found)`, but release runner fixes `PYTHONHASHSEED=0`; no current output difference was demonstrated. Treat as low-risk debt, not a proven regression.
- Timestamps in manifests are expected nondeterministic metadata; ZIP writer itself normalizes package metadata.

## 25. Lineage/Reproducibility Audit

Active data lineage is explicit and verified:

```text
raw ca033190f2e9e99f
  -> A6 c6887fb633374fad
  -> retrieval 872ccb0dda9a2bb6
```

NEW canonical reads these active paths and does not read OLD `work.db` or OLD ZIP. The retrieval DB SHA is `72d307…6daf6`; source A6 DB SHA is `fa6c46…dc3c8`.

Blocking/major gaps:

- Current Git object pack is corrupt: `git status --short` reports “pack file is far too short” then `fatal: bad object HEAD`.
- `git_source_identity()` catches this and returns `{"git_commit": null, "git_dirty": null}`. `pipeline_manifest()` accepts those values, so a new run can be marked completed without attributable source identity.
- 64 files under `src/`, `tools/`, `configs/` hardcode the old `b3e.../286.../retrieval.db`; active config points to `c688.../872...`. Canonical runtime is correct, but many evaluation/diagnostic tools silently measure the old snapshot.
- `configs/pipelines/retrieval_frozen_v1.yaml` is historical but looks authoritative and conflicts with `configs/datasets/active_snapshot.yaml`.
- Large raw/A6/index payloads are outside Git. Existing local snapshots are reproducible-by-checksum, but a fresh-clone full rebuild was not demonstrated here and requires external acquisition plus ~40 GB.

## 26. Test Coverage Audit

| Risk | Existing test? | Coverage | Severity |
|---|---|---|---|
| Normal single-entity query | Yes | Parser/S1/S2 fixture tests | Adequate mechanism coverage |
| Entity word boundaries/nesting/order | Yes | `test_retrieval_r0_entity.py` | Good mechanism, not active dataset cases |
| Q508 STB alias + gold S1 retention | **No** | No Q508 retrieval regression | P0 gap |
| Q783/Q792 `Eximbank` under canonical A6 | **No** | Q792 only appears in operation/V3 tests | P0 gap |
| Q464 open-screen candidate behavior | **No** | No production retrieval assertion | P0 gap |
| A6 YAML values contain no `...` | **No** | Generator only checks count/readability | P1 gap |
| Q586 OLD-correct→NEW-wrong | **No** | No canonical paired rank gate | P1 gap |
| Year slack | Yes | Synthetic S1 fixture | Good mechanism coverage |
| Basis soft vs hard | Yes | Synthetic candidate tests + proxy A/B | Good, but no explicit-basis final-ref gate |
| Multi-entity fanout | Partial | Helper tested; production is disabled | P1 product gap |
| Reranker contracts | Yes | Model feature/identity tests | Good unit coverage; no held-out labels |
| No candidate / wrong candidate | Partial | Fail-closed answer tests | Does not protect relevance score |
| Submission/evidence determinism | Yes | Unit/package tests | Historical/materialized, not current Git state |
| Active-snapshot evaluation identity | Partial | Snapshot builder/verifier tests | 64 legacy hardcodes remain |

The core problem is not lack of tests in general; it is that mechanism tests do not assert the active competition questions and active alias artifact at the exact S1/top-K boundaries where score regressions occur.

## 27. Evaluation Design Audit

- Retrieval manual gold: 95/1,012 = 9.39%; stratified but already used for feature discovery and reranker training. Not untouched.
- Answer gold: 40 records, 31 evaluable = 3.06% of the corpus. Only 8/40 have tracked blinded recheck; same-model correlated error cannot be excluded.
- Evidence-binding gold: 20 blank templates, 0 usable.
- Registry explicitly records `promotion_eligible_records: 0` for answer, parser and binding assets.
- Answer 14/31 has Wilson 95% CI `[29.16%, 62.23%]`, too wide for production claims.
- Retrieval NEW 85/95 Hit@10 CI `[81.70%, 94.18%]`; mode/entity strata are much wider.
- Proxy 1,006 provides coverage but has non-exhaustive, lexical relevance semantics and demonstrably disagrees with manual labels.
- Previous report compared NEW using full brands, not the canonical `load_aliases("a6")`, hiding Q586 regression. This is an evaluation-configuration mismatch, not merely stale prose.
- A 27/08 score table is now user-provided, but eight non-Execution rows have label/baseline conflicts with the 22/08 `OFFICIAL_SCORE.json`; no raw 27/08 score artifact, receipt/checksum, official score weights or independently verified exact-ZIP mapping is available in the audited repo.

## 28. Competition Score Risk

| Risk chain | Component | Metrics affected | Potential score impact | Confidence |
|---|---|---|---|---|
| Missing/wrong alias → ticker hard filter → gold unreachable | Entity/S1 | Tables F2, Docs F2, Answer, Execution | Direct zero/near-zero on affected QIDs | High |
| Broken A6 alias serialization → noisy BM25 → rank 5/6→25/29 | Query/rank | Retrieval score; possibly answer if outside pool | Proven one paired regression; broader 61-QID exposure | High |
| Small N policy → low recall | Submission refs | Tables/Docs P/R/F2 | Local F2 sensitivity `0.3035→0.4624` | Medium-high; official unknown |
| Binder overwrites refs | Binding/output | Tables/Docs score | 24 hit flips on gold95, mixed direction | High local, medium official |
| Global cutoff + unsupported multi route | Retrieval + answer | All metrics | 0/12 local multi; 180 full abstentions | High |
| Sparse/incorrect basis/unit/code metadata | Data/rank | Retrieval and binding | Case-dependent; no held-out estimate | Medium |
| Stale evaluation snapshot | Evaluation | All reported local metrics | Can select wrong fix or claim false pass | High |
| Git identity null | Lineage | Submission auditability, reproducibility | Candidate cannot be attributed to exact source | High |
| Small/contaminated gold | Evaluation | Decision quality | False promotion/regression risk | High |
| 27/08 metric labels conflict with 22/08 artifact | Evaluation | Retrieval/Answer attribution | Can reverse Docs/Tables/Precision/Recall conclusions | High |
| Official identity/weight unknown | Evaluation | Overall score interpretation | Cannot make exact-ZIP causal/weighted claim | High |

The new score changes one conclusion decisively: **Execution Accuracy improved by `+0.1324` (`0.1225 → 0.2549`)**. It does not close the retrieval risks. Under the labels supplied by the user, both F2 rows and all rank/precision-like declining rows worsened, while two recall-labelled rows improved. This pattern is compatible with broader retrieval increasing recall but lowering precision/rank quality; it remains a hypothesis until metric labels are reconciled.

## 29. Hidden Score Loss Risks

- Hit@10 looks high, but Hit@1 is only `33/95 = 34.74%` and actual output-N hit is `50/95` pre-bind.
- Candidate recall `95/95` hides Q508/Q783/Q792/Q464 because they are outside that retrieval sample.
- Final evidence rewrite improves aggregate local F2 but regresses exact table hit on 10 QIDs.
- Answer-correct records can cite a different table than narrow local gold; answer and retrieval metrics can move in opposite directions.
- Replay `561/561` says emitted queries are self-consistent, not that 561 values are correct.
- Validator can PASS a 1,012-record submission with 451 abstentions.
- NEW can answer Q586 because gold remains top-50 while its retrieval output refs miss the gold at N=2; Answer and Tables score diverge.
- Soft basis preserves recall but may return wrong-basis refs on explicit questions.
- V3’s 269 answers are not proof of lift; on the same 31 local cases it is 6/31 versus V2 14/31.
- OLD official score is reported but exact ZIP identity is not independently verified; official causal claims can be wrong even when numbers are real.
- The 27/08 table can support the Execution delta, but the duplicated/misaligned labels can make a Docs regression look like a Tables regression, or turn MRR into Answer Accuracy; do not optimize from those labels before reconciliation.

## 30. Architecture / Complexity Audit

| Component | Classification | Rationale |
|---|---|---|
| Active snapshot resolver/verifier | KEEP | Clear immutable lineage and current PASS |
| Single canonical retrieval implementation + compatibility module aliases | KEEP temporarily | Compatibility modules resolve to canonical objects; not duplicate logic |
| 64 hardcoded legacy DB consumers | SIMPLIFY/REMOVE | Multiple snapshot sources make evaluation unsafe |
| Historical frozen config beside active config | SIMPLIFY | Must be explicitly namespaced historical |
| Identity S3 abstraction | KEEP | Clean insertion point and truthful pass-through trace |
| Learned reranker artifact | UNPROVEN | Good engineering, no promotion gold |
| Per-ticker fanout/three normalization modes/primary boost | UNPROVEN | Experiment knobs, not production lift |
| Canonical V2 + Semantic V3 shadow | KEEP with strict labels | Useful migration pattern; current docs must not merge metrics |
| Legacy answer tooling/parent ZIP overlays | REMOVE from production path | Valuable forensic history but creates hidden dependencies if reused |
| Evidence-driven final refs | KEEP concept, re-evaluate metric contract | Strong grounding but retrieval score coupling is not controlled |

## 31. Unproven Improvements

| Feature | Claimed benefit | Evidence | Proven? |
|---|---|---|---|
| NEW boundary-safe entity parser | Fewer false entities | Unit/mechanism tests | Not proven as overall score lift; active aliases introduce new misses |
| +566 observations / +18,686 ready observations | Better answer coverage | Data counts | No paired independent downstream lift |
| A6-attested brand policy | Avoid external knowledge | Corpus provenance | Score safety disproven for Q783/Q792; rules compliance choice remains |
| Exact bound evidence refs | Better grounding | 14 positive/10 negative local hit flips | Mixed; official impact unknown |
| Linear reranker | Better ranks | Dev-19 lift, train F2 slight loss | No independent held-out |
| Primary-statement boost | Better screen retrieval | Development 95 lift | Feature-selected/contaminated |
| Per-ticker fanout | Better entity coverage | Mechanism test; proxy overall slightly worse | Needs protected manual slice |
| `stop_mode=dau` | Preserve Vietnamese content words | Linguistic rationale | Proxy A/B worse |
| Semantic V3 | Better typed coverage/safety | 269 replayable outputs; 6/31 correct | Not promoted; worse local total accuracy than V2 |
| NEW performance | Faster/leaner | Small diagnostic latency/disk deltas | Difference too small/uncontrolled |

## 32. MASTER ISSUE REGISTER

Metric abbreviations: **AA** Answer Accuracy, **EA** Execution Accuracy, **TF2** Tables F2, **DF2** Docs F2.

| ID | Priority | Component | Problem / root cause | Evidence | Affected metric | Expected score impact | Confidence | Fix direction — do not implement yet | Need confirmation |
|---|---|---|---|---|---|---|---|---|---|
| RET-001 | P0 | Alias/S1 | STB alias is wrong for question wording; hard ticker filter drops gold | Q508: S1 loses 2/4 gold tables; correct selector/value are STB | AA, EA, TF2, DF2 | HIGH on case; scope ≥1 | High | Correct/attest alias and add exact S1 gold regression | Yes |
| RET-002 | P0 | Alias policy/S1 | Corpus-only brand set omits `Eximbank` used by questions | Q783/Q792 resolve only MBB, while full aliases resolve EIB+MBB | AA, EA, TF2, DF2 | HIGH on affected cases | High | Derive aliases from competition questions or approved local source; rules review | Yes |
| RET-003 | P0 | Open-universe entity | Empty target returns empty candidates | Q464 has 0 candidates and known zero fields | AA, EA, TF2, DF2 | Direct 1/1,012 loss minimum | High | Define bounded open-universe candidate path/fail policy | Yes |
| RET-004 | P1 | Alias serialization/query | `safe_dump().strip()` injects literal `...`; alias removal fails | 68 bad values; 61 QIDs changed; Q586 ranks 5/6→25/29 | TF2/DF2; AA/EA if pool miss | MEDIUM; proven regression | High | Serialize scalars safely; validate exact loaded strings; paired gate | Yes |
| RET-005 | P1 | Output N policy | NEW cap-10 product policy differs from OLD official freeze `3×` | Local gold95 pre-bind F2 `0.3035`; same rank `3×` F2 `0.4624` | TF2, DF2 | HIGH potential | Medium-high | Tune policy on independent gold; keep exact protocol/CI | Yes |
| RET-006 | P1 | Multi-entity ranking | Global top-K does not guarantee entity/operand coverage | Screen F2 `0.2901`; 6/10 rank misses; target-count trend down | All | HIGH for screen/multi | High | Evaluate entity-aware candidate shaping/fanout on held-out | Yes |
| RET-007 | P1 | Retrieval→submission coupling | Successful binding overwrites refs; retrieval score depends on answer route | 14 positive + 10 negative hit flips; final F2 `0.3814` | TF2, DF2 | MEDIUM/HIGH | High local | Define score contract; evaluate final fields, not only ranked list | Yes |
| RET-008 | P1 | Rank/cutoff | 10/95 gold misses top-10; 3 outside top-50 | Canonical funnel; Q374/376/436 near cutoff | TF2/DF2; AA/EA for top-50 misses | MEDIUM/HIGH | High | Error-driven ranking experiments with untouched gold | Yes |
| RET-009 | P1 | Basis metadata/rank | Table basis recovery is hidden; soft prior can return explicit wrong basis | 2,491 mismatches; Q128/Q962 wrong-basis refs | All | MEDIUM | Medium-high | Use table-level basis; matching-first/fallback policy | Yes |
| RET-010 | P1 | Downstream operation | Multi/rank/conditional answer routes remain incomplete | 180 full multi abstentions; local multi 0/12, max/min 0/3 | AA, EA; indirect refs | HIGH | High | Implement only after separate approval; protect evidence/units | Yes |
| RET-011 | P1 | Evaluation gold | No organiser-held or promotion-eligible local gold | Registry: promotion eligible 0 for all three assets | All decision making | UNKNOWN, potentially HIGH | High | Acquire independent blinded answer/table/binding gold | Yes |
| RET-012 | P1 | Sample/leakage | 95 retrieval labels contaminated; answer n=31 too small | 9.39% and 3.06%; CI 29–62% | All | HIGH risk of false claim | High | Expand stratified untouched sets; preregister protocol | Yes |
| RET-013 | P1 | Proxy evaluation | Lexical proxy does not represent table relevance | Same-28 Hit@1 0.75 proxy vs 0.393 manual | Retrieval decisions | MEDIUM/HIGH | High | Label proxy explicitly; never use for promotion | Yes |
| RET-014 | P1 | Snapshot/eval SSOT | 64 source/tool/config files hardcode old DB | Active c688/872 vs hardcoded b3e/286 | All local metrics | HIGH measurement risk | High | Route all current tools through active snapshot resolver | Yes |
| RET-015 | P1 | Git/source lineage | Corrupt pack makes source identity null; manifest accepts null | `git status` fatal; `git_source_identity()` returns null/null | Reproducibility/submission trust | HIGH operational | High | Repair repository; make release fail on unknown identity | Yes |
| RET-016 | P1 | Official lineage | OLD ZIP↔submission ID lacks independent receipt | Official identity artifact explicitly unverified | Official causal comparisons | UNKNOWN | High | Obtain dashboard/receipt/API checksum evidence | Yes |
| RET-017 | P2 | Stop words | Fold mode removes Vietnamese content homographs | 560 current term diffs; source reports 621 raw | Rank metrics | UNKNOWN | Medium | Run manual held-out A/B; do not flip default yet | Yes |
| RET-018 | P2 | Query truncation | Fixed first 24 terms drops meaningful tail on long questions | 58/1,012 affected, max 43 terms | Rank/multi recall | UNKNOWN | Medium | Test semantic term budget/fielded weighting | Yes |
| RET-019 | P2 | Temporal filter | BETWEEN admits unasked intermediate years | 232 non-contiguous-year questions | Precision/latency | LOW/MEDIUM unknown | High mechanism | Compare set-aware vs range candidate policy | Yes |
| RET-020 | P2 | Data signal coverage | Key ranking metadata is sparse | Codes 93.56% blank; section 16.48%; periods 10.85% | Rank/binding | UNKNOWN | High | Improve metadata only with per-field downstream ablation | Yes |
| RET-021 | P2 | OLD→NEW data delta | Readiness/card changes not paired to answer relevance | +18,686 ready; 2,066 semantic hashes changed | Rank/AA/EA | UNKNOWN | Medium | Produce semantic diff + protected paired evaluation | Yes |
| RET-022 | P2 | Reranker | Production S3 is identity; learned S3 lacks held-out labels | Dev-only artifact; train F2 slight loss | Rank metrics | UNKNOWN | High | Keep identity until held-out CI non-negative | Yes |
| RET-023 | P2 | Performance | No locked current OLD/NEW benchmark | Only warm local 95; no throughput/RSS/cold cache | Operational | LOW unless time limit | High | Reproducible benchmark matrix | Yes |
| RET-024 | P1 | Tests | Critical active QIDs/artifact invariants are not regression-tested | No tests for 464/508/586/783 or attested `...` | All | HIGH recurrence risk | High | Add data-contract + active-slice gates after approval | Yes |
| RET-025 | P2 | Documentation/evaluation | Prior audit used non-canonical full brands and claimed no regression | Current canonical paired run finds category B Q586 | Decision quality | MEDIUM | High | Supersede prior conclusion; bind report to config hash | Yes |
| RET-026 | P1 | Score specification/reconciliation | Overall weights are unspecified and the supplied 27/08 table has duplicated/misaligned labels | `Docs MRR@5` appears twice; eight baselines conflict with 22/08 artifact keys | Overall score and component attribution | HIGH decision risk | High | Obtain raw 27/08 score JSON/screenshot + receipt; reconcile by key before optimization | Yes |
| RET-027 | P2 | Shadow architecture | V3 coverage is presented near production metrics without promotion evidence | V3 269 emitted; local 6/31 vs V2 14/31 | Decision quality | MEDIUM | High | Keep shadow labels and separate scorecard | Yes |

## 33. Must Fix Before E2E

For the next **authoritative** E2E/competition candidate:

1. `RET-001` — Q508/STB hard-filter gold loss.
2. `RET-002` — canonical A6 brand policy loses EIB in Q783/Q792.
3. `RET-003` — Q464 open-universe retrieval is guaranteed empty.
4. `RET-015` — repair Git/source identity and reject null lineage.
5. `RET-024` — add exact regression coverage for the confirmed P0/P1 cases after fixes are approved.
6. `RET-010` — if the goal is a competitive full-corpus E2E rather than merely a mechanically valid ZIP, the dominant multi/rank/conditional operation gaps must be closed or explicitly accepted as score loss.

## 34. Should Fix Before Submission

- `RET-004`: alias serialization and Q586 regression.
- `RET-005`: output N policy must be selected from independent final-field evaluation.
- `RET-006`: multi-entity candidate/ranking coverage.
- `RET-007`: evaluate retrieval on actual final submission fields.
- `RET-008`: top-50/top-N rank misses.
- `RET-009`: table-level basis and explicit-basis fallback behavior.
- `RET-011`/`RET-012`: independent, adequately sized gold.
- `RET-014`: active snapshot as the single evaluation source.
- `RET-016`: official identity evidence before using OLD official scores causally.

## 35. Optimization

- Entity-aware candidate shaping or fanout, protected by single/compare slices.
- Revisit N policy jointly for Tables and Docs F2, not fixed Hit@10.
- Metric-aware term selection instead of first-24 truncation.
- Table-level basis and metadata completion.
- Reranker only after independent labels exist.
- BM25 query/profile optimization after relevance behavior is locked.

## 36. Technical Debt

- Remove or clearly quarantine the 64 old-snapshot hardcodes.
- Mark `retrieval_frozen_v1.yaml` as historical/non-active.
- Remove stale `SILVER_BUILD_ID=b3e...` constants from canonical namespace.
- Make source identity failure a release error rather than null metadata.
- Replace unordered `set(found)` iteration or document why output is order-independent.
- Consolidate report/config fingerprints so a report cannot silently refer to a different alias branch.

## 37. Unproven Issues

- `RET-017` stop-mode change may help manual relevance even though proxy worsens.
- `RET-018` 24-term truncation may hurt long compound questions; case-level gold needed.
- `RET-019` non-contiguous year range may be mostly latency, not relevance.
- `RET-020` metadata sparsity may or may not be worth rebuilding.
- `RET-021` NEW readiness changes may improve binding despite no retrieval lift.
- `RET-022` learned reranker may generalize; no evidence yet.
- `RET-023` NEW may be slightly faster; current measurement is not production-grade.
- `RET-027` V3 may outperform after operation coverage closes; current local evidence does not.

## 38. False Alarms

- **“NEW uses OLD work.db in canonical production.”** False: canonical uses active c688/872 paths. Old hardcodes are in legacy/eval tooling.
- **“Basis is a production hard filter.”** False: production uses soft basis; do not switch to hard without evidence.
- **“`retrieval_ready=1` is dropping tables.”** False in current snapshot: all 146,246 cards are ready.
- **“S3 is an ML reranker in production.”** False: it is identity/pass-through.
- **“No dense/vector retrieval is automatically a defect.”** False: manual 95 candidate recall is already 100%; dense retrieval needs failure-driven evidence.
- **“Compatibility namespaces duplicate retrieval logic.”** False in current code: legacy modules alias canonical module objects and have a parity test.
- **“Replay 100% proves accuracy.”** False interpretation, not a replay bug.
- **“Hard basis would fix wrong-basis answers safely.”** False: proxy A/B proves candidate recall loss.

## 39. TOP 10 SCORE RISKS

1. **RET-010 — Multi/rank/conditional operation gap.** AA/EA; 180 full abstentions, local multi 0/12. Expected HIGH. Experiment: stratified independent end-to-end gold by operation.
2. **RET-001 — STB alias hard drop.** All metrics; Q508 loses 2/4 gold tables. Expected HIGH per case. Experiment: exact S1 gold regression over all no-ticker company-name questions.
3. **RET-002 — A6 alias policy loses EIB.** All metrics; Q783/Q792 become one-entity. Expected HIGH per case. Experiment: compare canonical entity sets to question-derived approved lexicon over 1,012.
4. **RET-005 — Output N policy under-recall.** TF2/DF2; local F2 `0.3035` vs `0.4624` for `3×`. Expected HIGH potential. Experiment: preregister N-policy sweep on untouched final-field gold.
5. **RET-006 — Global multi-entity cutoff.** All metrics; screen F2 `0.2901`, 6/10 misses. Expected HIGH/MEDIUM. Experiment: entity/operand coverage-aware retrieval with protected slices.
6. **RET-004 — Broken attested aliases.** Retrieval and possible AA/EA; Q586 rank 5/6→25/29. Expected MEDIUM, proven. Experiment: corrected serialization paired on all 1,012 plus manual gold.
7. **RET-007 — Binder changes scored refs.** TF2/DF2; 24 hit flips. Expected MEDIUM/HIGH. Experiment: score pre-bind and final refs with exhaustive alternative-table labels.
8. **RET-011/012 — No independent sufficient gold.** All decisions; current promotion eligibility zero. Expected HIGH risk of false optimization. Experiment: blinded, untouched 300+ retrieval and 150+ answer cases.
9. **RET-014 — Evaluation reads stale snapshot.** All local claims; 64 hardcodes. Expected HIGH measurement risk. Experiment: assert every evaluator’s resolved DB SHA equals active SHA.
10. **RET-015 — Source lineage can become null.** Reproducibility/submission trust; current Git corrupt. Expected HIGH operational. Experiment: clean-clone release dry run that fails on unknown commit/dirty state.

## 40. Recommended Experiments

Run only after issue groups are confirmed; preregister metrics and do not tune on the report set.

| Order | Experiment | Dataset/protocol | Pass criterion |
|---:|---|---|---|
| 1 | Entity completeness gate | All 1,012 questions + manual audit of no-ticker names | No known entity omitted; Q464 policy explicit |
| 2 | Alias serialization A/B | Corrected A6 vs current A6, same DB, paired QID | Fix Q586/Q783/Q792; no protected-slice regression |
| 3 | S1 gold retention | ≥300 untouched table-gold, report each hard filter | Zero unexplained gold drop; exact dropped QIDs |
| 4 | Final-field N policy sweep | `1×`, `2×`, `3×`, adaptive, caps 10/20/30 | CI-backed TF2/DF2 gain on final output, no AA/EA regression |
| 5 | Entity-aware rank/fanout | screen/compare/multi protected strata | Improve complete-entity recall and F2 with non-negative overall CI |
| 6 | Retrieval→answer causal ablation | Oracle tables vs production top-50 on same answer gold | Quantify retrieval-attributable failure count |
| 7 | Basis strategy | document vs table basis; matching-first fallback | No hard-drop increase; explicit-basis precision improves |
| 8 | Stop/truncation experiments | `fold` vs `dau`; first24 vs metric-aware terms | Held-out relevance lift, latency budget respected |
| 9 | Learned reranker held-out | Sealed 120 IDs with independent labels | Paired F2 CI lower bound ≥0 and no mode regression |
| 10 | Release reproducibility | Clean clone, locked env, materialized checksummed data, two runs | Same output SHA; non-null commit; no old-snapshot reads |
| 11 | Performance benchmark | Cold/warm, p50/p95/p99, RSS, throughput, 1/4 workers | Meets competition time/memory limit; limits must be recorded |
| 12 | Official reconciliation | Raw 27/08 score export/screenshot plus controlled submission receipt/checksum | Reconcile every metric key, close exact ZIP↔score identity and weight ambiguity |

## 41. FINAL VERDICT

### CURRENT RETRIEVAL STATUS

[ ] PRODUCTION READY  
[ ] E2E READY WITH CONDITIONS  
[x] NOT READY  
[ ] INSUFFICIENT EVIDENCE

The status is `NOT READY` because confirmed P0/P1 defects exist, not merely because evidence is incomplete. Even after those defects are fixed, production readiness will still require independent evaluation.

**Ảnh hưởng của score update:** verdict không đổi. Execution Accuracy tăng `+0.1324` là tiến bộ thực tế đáng kể, nhưng bảng mới đồng thời báo hai F2 giảm và chưa có mapping metric đáng tin cậy cho tám dòng còn lại. Các P0 hard-filter và P1 retrieval/evaluation vẫn tồn tại.

### A. Những thứ NEW chắc chắn tốt hơn OLD

- Active raw/A6/retrieval snapshot identities and DB verification are clearer and immutable.
- Successful answers publish exact bound evidence rather than unrelated prior top-N refs.
- Entity parsing mechanics have safer boundaries, nested-name handling and directional order.
- Ranking and package paths have explicit deterministic tie-break/contracts.
- Learned reranker is correctly blocked from production without held-out evidence.
- Reported Execution Accuracy improves from `0.1225` to `0.2549` (`+0.1324`), pending exact-ZIP receipt reconciliation.

### B. Những thứ NEW chắc chắn tệ hơn OLD

- Canonical A6 alias path creates one paired top-10 regression: Q586.
- Q783/Q792 lose EIB under A6 aliases while full OLD aliases resolve both entities.
- Current source lineage is worse operationally because Git corruption produces null identity.
- NEW has not retained the OLD official freeze’s broader result-count policy; local recall/F2 sensitivity is adverse.
- Under the labels supplied on 27/08, both macro-F2 rows decline (`−0.1027`, `−0.1215`) and the three MRR/precision-like declining rows fall by `−0.0691` to `−0.2688`; exact component names still need reconciliation.

### C. Những thứ NEW có vẻ tốt hơn nhưng chưa chứng minh

- +566 observations and improved readiness metadata.
- Exact evidence rewrite as an official retrieval-score improvement.
- Linear reranker, primary prior, fanout and Semantic V3.
- Small latency/disk reduction.
- The supplied recall gains (`+0.0971`, `+0.1815`) may indicate broader coverage, but their metric labels conflict with the 22/08 artifact.

### D. Những lỗi đang trực tiếp làm mất điểm

- RET-001: Q508 entity hard drop.
- RET-002: Q783/Q792 missing EIB.
- RET-003: Q464 empty candidate set.
- RET-004: Q586 paired ranking regression.
- RET-010: unsupported multi/rank/conditional questions produce abstentions.

### E. Những lỗi có khả năng làm mất điểm lớn nhất

- Multi-entity/conditional operation gap.
- Output N policy and global multi-entity cutoff.
- Alias/entity completeness before S1.
- Final retrieval-ref coupling to binding.
- Lack of independent gold, which can drive the wrong optimization.

### F. Những thứ KHÔNG nên sửa

- Do not enable hard basis filtering.
- Do not promote the learned reranker from dev-19 results.
- Do not switch stop mode solely from linguistic rationale.
- Do not add dense/vector retrieval without a candidate-miss study.
- Do not treat replay/validator/coverage as correctness.
- Do not use OLD official scores for exact-ZIP causal claims until identity is closed.

### G. Những experiment cần chạy trước khi quyết định sửa

- Entity completeness and alias A/B.
- Final-output N-policy sweep.
- Protected multi-entity fanout/ranking A/B.
- Oracle-table retrieval→answer ablation.
- Independent reranker and basis evaluation.
- Clean-clone deterministic release and official receipt reconciliation.

### H. Những issue cần CONFIRM trước implementation

- RET-001
- RET-002
- RET-003
- RET-004
- RET-005
- RET-006
- RET-007
- RET-008
- RET-009
- RET-010
- RET-011
- RET-012
- RET-013
- RET-014
- RET-015
- RET-016
- RET-017
- RET-018
- RET-019
- RET-020
- RET-021
- RET-022
- RET-023
- RET-024
- RET-025
- RET-026
- RET-027
