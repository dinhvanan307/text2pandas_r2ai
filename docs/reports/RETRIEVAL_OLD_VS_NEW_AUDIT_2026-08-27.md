# Retrieval Audit: OLD vs NEW

**Ngày audit:** 2026-08-27  
**Phạm vi:** Chỉ tầng retrieval/search/ranking và tác động quan sát được của retrieval lên answer; không đánh giá toàn bộ chất lượng hệ thống.  
**PROJECT_OLD:** `../Text2Pandas-1`  
**PROJECT_NEW:** repository hiện tại (`text2pandas`)  
**Kết luận bắt buộc:** metric từ proxy không được coi là gold; retrieval success không được coi là answer success; số không có bằng chứng được ghi `NOT MEASURED` hoặc `INSUFFICIENT EVIDENCE`.

Nguồn bằng chứng chính được đọc trực tiếp gồm code retrieval, cấu hình, SQLite schema/index, manifest/provenance, checkpoint eval, official freeze, gold thủ công và các báo cáo acceptance. Audit không rebuild index, không sửa pipeline, không chạy lệnh phá huỷ và không thay đổi dữ liệu. Phép đo paired bổ sung chỉ mở hai DB ở chế độ read-only.

## 1. Executive Summary

**Kết luận ngắn:** NEW là lựa chọn tốt hơn để vận hành và phát triển tiếp, nhưng **không có bằng chứng rằng canonical V2 retrieval của NEW chính xác hơn OLD** trên gold dùng chung. Trên 95 câu gold đáng tin cậy, hai hệ cùng đúng top-10 ở đúng 86 câu, cùng sai ở 9 câu, không có positive flip và không có regression flip. McNemar exact two-sided có `p = 1.0`.

| Phát hiện trọng yếu | Kết luận |
|---|---|
| Candidate coverage trên manual gold 95 | OLD = NEW = `95/95` |
| Hit@10 trên cùng gold, cùng câu hỏi | OLD = NEW = `86/95 = 90.5263%` |
| Paired flip | `0` OLD-wrong→NEW-correct; `0` OLD-correct→NEW-wrong |
| Ranking | MRR@10 NEW thấp hơn `0.000877`; nDCG@10 thấp hơn `0.000730`; khác biệt cực nhỏ, chưa có ý nghĩa thực dụng được chứng minh |
| Nút thắt | Cả 9 lỗi đều là rank miss, không phải hard-filter false negative trên gold 95 |
| S3 production | Identity/pass-through; reranker linear tồn tại nhưng chưa được promote |
| Gold vs proxy | Proxy làm méo kết luận; trên cùng 28 câu, proxy tăng Hit@1/MRR nhưng giảm Hit@10/Recall so với manual gold |
| Lợi thế thật của NEW | Snapshot bất biến, manifest/checksum, active snapshot SSOT, checkpoint fingerprint, evidence binding, taxonomy/eval rõ hơn, đường mở rộng V3 |
| Rủi ro production hiện tại | Git object database của NEW đang hỏng; một số config/script retrieval vẫn ghim build/index cũ; held-out reranker chưa có nhãn độc lập |

**Verdict:** `YES WITH CONDITIONS`. Có thể chọn NEW làm retrieval layer thay OLD vì không có paired quality regression và control plane tốt hơn. Không được quảng bá đây là một quality upgrade cho ranking cho tới khi có held-out độc lập và materialized paired report đủ rộng.

## 2. OLD Retrieval Architecture

Canonical retrieval của OLD nằm tại `src/retrieval/` và đi theo đường:

`question → intent/entity/year/basis → S1 hard-filter → S2 FTS5 BM25 + structural bonuses → S3 identity/truncate → submission refs`

Các thành phần chính:

- **Data/index:** `artifacts/retrieval/work.db`, được copy từ A6 Silver rồi thêm bốn index `ix_tc_ticker_year`, `ix_tc_stmt_ticker`, `ix_doc_tky`, `ix_obs_tab_period` và chạy `ANALYZE`.
- **Intent:** rule-based, dùng ticker/company aliases, năm, basis, mode `single/screen/compare/related`.
- **S1:** lọc theo ticker, khoảng `doc_year`, `retrieval_ready=1`; basis chỉ lọc khi `basis_mode=hard`; không lọc cứng `statement_type`.
- **S2:** FTS5 `MATCH` trên table-card text, lấy BM25 rồi cộng prior kỳ, đơn vị, statement, basis và metric code.
- **S3:** identity; chỉ giữ thứ tự S2 và truncate.
- **Output:** ánh xạ `table_uid` sang `relevant_tables`/`relevant_docs` phục vụ submission.

OLD có hai loại bằng chứng cần tách riêng:

1. Official freeze trên submission 3236: table/document retrieval score của hệ đã nộp.
2. Evalkit nội bộ trên proxy/manual gold: dùng để phân tích ranking nhưng không thay official score.

Điểm yếu kiến trúc của OLD là `work.db` được mô tả đúng là “DB làm việc dẫn xuất, không phải gói chứng nhận”; provenance có nhưng contract bất biến và point-in-time selection yếu hơn NEW. Answer tooling lịch sử còn dùng DB/ZIP theo những đường riêng, nên official `relevant_tables` không luôn là evidence mà answer thực sự bind.

## 3. NEW Retrieval Architecture

NEW có hai đường retrieval khác nhau và phải phân biệt:

### Canonical V2 production path

`active_snapshot.yaml → immutable retrieval.db → parse_intent → HardFilterGenerator → Bm25StructuralRanker → IdentityReranker → RetrievalToSubmission → answer candidate pool/evidence binding`

- Runtime đọc active A6/retrieval identity từ `configs/datasets/active_snapshot.yaml`.
- Snapshot đang active là A6 `c6887fb633374fad`, retrieval index `872ccb0dda9a2bb6`.
- Builder tạo thư mục `<source_build_id>/<index_id>`, stage DB, kiểm schema/count/checksum/`quick_check`, rồi atomic rename; từ chối overwrite output đã tồn tại.
- Eval checkpoint bind cả config fingerprint lẫn active snapshot identity và kiểm manifest/database bytes.
- Canonical adapter vẫn khởi tạo `IdentityReranker`; S3 production là pass-through.
- Canonical answer run lấy tối đa 50 ranked table làm answer pool. Khi answer bind được table cụ thể, chính table đã bind được dùng làm `relevant_tables`/`relevant_docs`; với abstain, retrieval refs ban đầu được giữ.

### Semantic V3 shadow path

NEW còn có observation-level operand retrieval tại `infrastructure/retrieval/operand.py`. Nó chấm theo metric alias/code, unit dimension, period role, basis, statement, section/qualifier, document period, restated penalty và upstream table rank. Đây là bước tiến về typed evidence retrieval, nhưng hiện là **shadow/non-canonical** và không phải bằng chứng rằng V2 table retrieval đã tốt hơn OLD.

Không tìm thấy vector embedding, ANN, dense retriever hoặc hybrid sparse+dense trong canonical V2. “Semantic” ở V3 là typed/ontology-aware retrieval, không phải vector search.

## 4. OLD vs NEW Architecture Diff

| Hạng mục | OLD | NEW | Đánh giá |
|---|---|---|---|
| S1 core | Rule/SQL hard filter | Gần như cùng implementation | Chất lượng lõi không đổi trên paired 95 |
| Query terms | Lexical normalization/FTS terms | File tương đương OLD | Không phải quality delta |
| S2 core | BM25 + fixed structural bonus | Thuật toán tương đương; thêm `zip(..., strict=True)` | Safety improvement, không phải ranking innovation |
| Intent/entity | Substring-oriented aliases | Boundary-safe aliases, merge ticker/name, giữ legal name dài, thêm cues | Code tốt hơn; 95 câu không đổi intent nào, nên impact rộng chưa đo |
| Metric hints | Phrase/code map cơ bản | Thêm VAS `220/221/227`, ưu tiên maximal overlapping phrase | Cải thiện hợp lý nhưng chưa có isolated held-out effect |
| S3 | Identity | Production identity; có linear reranker development-only | Production behavior vẫn pass-through |
| Snapshot | `work.db` + provenance | Immutable, content-bound manifest, active SSOT, verifier | **Significantly better** |
| Eval | Config-bound checkpoints; MRR S2/S3 từng có cutoff khác | Snapshot-bound checkpoints; same-cutoff MRR | **Significantly better** |
| Submission evidence | Retrieval refs và answer evidence có thể tách | Bound answer evidence là authoritative | **Significantly better** cho auditability |
| Operand retrieval | Không có typed V3 path | Có observation-level shadow path | Extensibility tốt hơn; chưa là production proof |
| Config hygiene | Freeze khớp OLD build | Active SSOT mới nhưng một số frozen/dev script ghim identity cũ | NEW còn migration debt |

Kiến trúc NEW do đó là một **control-plane and evidence-contract upgrade**, không phải một measured ranking-quality upgrade.

## 5. Data / Index Comparison

| Thuộc tính | OLD | NEW active | Delta/ý nghĩa |
|---|---:|---:|---|
| A6/source build | `b3e9684004679ffb` | `c6887fb633374fad` | Khác lineage |
| Retrieval index ID | historical `286973b134a189ee`; work DB provenance riêng | `872ccb0dda9a2bb6` | NEW content/config fingerprinted |
| Documents | 1,973 | 1,973 | Bằng nhau |
| Tickers | 100 | 100 | Bằng nhau |
| Tables/table cards | 146,246 | 146,246 | Bằng nhau |
| Rows | 1,524,071 | 1,524,071 | Bằng nhau |
| Observations | 2,633,554 | 2,634,120 | NEW `+566` |
| `retrieval_ready=1` cards | 146,246 | 146,246 | Hard predicate hiện không loại card nào |
| DB bytes | 4,240,060,416 | 4,239,663,104 | NEW nhỏ hơn 397,312 byte; không suy ra chất lượng |

NEW manifest ghi:

- retrieval DB SHA-256: `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf`
- source A6 DB SHA-256: `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8`

OLD provenance ghi source A6 DB SHA-256 `6622b913c3cc3d8b20cf1d45840da8eda6147230cfeb82df4f357fee4123b269` và source package SHA-256 `23c3b96e4338e8785c2dcfcdfebf147dc7b7b6438c46c590be1ecbfe2453be`.

Hai DB có cùng bốn retrieval index bắt buộc và cùng FTS5 definition:

```text
table_cards_fts(table_uid UNINDEXED, ticker, section_text,
                context_clean, row_labels, col_labels,
                tokenize='unicode61 remove_diacritics 2')
```

Không có bằng chứng cho thấy `+566` observations tự thân cải thiện table retrieval. Paired hit kết quả không đổi là bằng chứng thực nghiệm mạnh hơn suy luận từ count.

## 6. Algorithm Comparison

### S0: intent/query understanding

Cả hai dùng rules và aliases, không dùng LLM. NEW bổ sung boundary-safe company phrase matching, merge ticker/name matches, ordered tickers cho directional comparison, thêm comparison/screen cues và tách `answer_basis` khỏi retrieval basis mặc định.

### S1: candidate generation

Luật thực tế của cả hai:

- không có target ticker → trả `[]`;
- ticker phải nằm trong target set;
- nếu có years, `doc_year BETWEEN min(years) AND max(years)+1`;
- basis chỉ là hard predicate ở `basis_mode=hard`; production dùng `soft`;
- `retrieval_ready=1`;
- không hard-filter `statement_type`;
- `clean_ratio` là multiplier ở ranking, không phải filter.

Việc `no target → []` mâu thuẫn với một số mô tả thiết kế cũ nói có thể non-filter khi entity unresolved. Code runtime là nguồn sự thật.

### S2: lexical + structural ranking

Query text bỏ entity aliases, tickers, years và stop terms; sau đó xây FTS `OR` từ phrase/token. BM25 raw được đổi dấu và mặc định min-max normalize trong candidate pool.

Điểm mặc định:

```text
score = bm25_norm
      + 0.35 * period_hit
      + 0.15 * unit_hit
      + 0.10 * statement_hit
      + 0.30 * basis_hit
      + 0.45 * metric_code_hit

score *= 0.70 + 0.30 * clean_ratio
```

FTS column weights là `[0, 0, 2, 1, 4, 1.5]` cho `table_uid, ticker, section_text, context_clean, row_labels, col_labels`. Tie-break là `table_uid`, S2 giữ top-50.

Các knob như rank norm, max norm, per-ticker fanout và primary statement boost có trong eval framework nhưng mặc định production không bật. Vì vậy không được cộng kết quả experiment của chúng vào điểm NEW production.

### S3

OLD và NEW production đều identity. NEW có implementation linear-feature reranker thật, SHA-bound và deterministic, nhưng nó không được canonical adapter sử dụng.

### Khác biệt bản chất

Canonical V2 vẫn là sparse lexical retrieval + hand-authored structural priors ở cả hai project. Chênh lệch lớn nằm ở contract, provenance và integration; không nằm ở loại thuật toán truy hồi.

## 7. Metrics Comparison

### Phép đo paired trực tiếp, cùng manual gold 95

Gold ở hai repo có cùng SHA-256 `0d40d66c583327937c15fd83541b32d036d809bedc2ab17d86d31d6a68107337`; 120 dòng, trong đó 95 dòng có trusted table gold và không `uncertain`. Audit mở DB read-only, warm-up 10 câu và đảo thứ tự chạy OLD/NEW theo QID để giảm bias thứ tự. Đây là diagnostic trên Python hiện có của máy, không phải release benchmark được khóa.

| Metric | OLD | NEW | NEW − OLD |
|---|---:|---:|---:|
| Candidate hit | 95/95 = 1.000000 | 95/95 = 1.000000 | 0 |
| Hit@1 | 33/95 = 0.347368 | 33/95 = 0.347368 | 0 |
| Hit@10 | 86/95 = 0.905263 | 86/95 = 0.905263 | 0 |
| Macro Precision@10 | 0.212632 | 0.212632 | 0 |
| Macro Recall@10 | 0.711742 | 0.711742 | 0 |
| Macro F2@10 | 0.384460 | 0.384460 | 0 |
| MRR@10 | 0.545919 | 0.545042 | -0.000877 |
| nDCG@10 | 0.552317 | 0.551587 | -0.000730 |
| S1 pool median | 501 | 501 | 0 |
| S1 pool p90 | 2,084 | 2,084 | 0 |

MRR/nDCG có thay đổi thứ tự rất nhỏ trong những ca đã hit, nhưng không có thay đổi ở outcome Hit@10. Chưa có confidence interval cho hai metric rank delta này; không nên diễn giải là regression thực dụng.

### Official score

| Evidence | OLD | NEW | Có so trực tiếp được không? |
|---|---:|---:|---|
| Official TABLES F2 | 0.3538 | `NOT MEASURED` | Không |
| Official TABLES Precision | 0.1933 | `NOT MEASURED` | Không |
| Official TABLES Recall | 0.4744 | `NOT MEASURED` | Không |
| Official DOCS F2 | 0.7536 | `NOT MEASURED` | Không |
| Official DOCS Precision | 0.5062 | `NOT MEASURED` | Không |
| Official DOCS Recall | 0.8941 | `NOT MEASURED` | Không |
| Official TABLES MRR@5 | 0.4066 | `NOT MEASURED` | Không |
| Official DOCS MRR@5 | 0.7841 | `NOT MEASURED` | Không |

OLD official freeze gắn với submission 3236. Không có NEW official retrieval score trên cùng evaluator, nên mọi tuyên bố NEW tốt hơn official là không hợp lệ.

### OLD full proxy evidence

OLD evalkit có 1,006/1,012 câu measurable bằng proxy: candidate hit `0.998012`, Hit@1 `0.725646`, Hit@10 `0.915507`, F2@10 `0.474807`, MRR full-ranked `0.785310`. Đây là **proxy measurement**, không được đặt cạnh manual 95 hoặc official score như cùng một thước đo.

## 8. Gold vs Proxy Analysis

Artifact `gold_tay_eval.json` cho phép so manual và proxy trên đúng cùng 28 QID:

| Metric | Manual gold | Proxy gold | Proxy − Manual |
|---|---:|---:|---:|
| Hit@1 | 0.392857 | 0.750000 | +0.357143 |
| Hit@3 | 0.857143 | 0.821429 | -0.035714 |
| Hit@5 | 0.928571 | 0.892857 | -0.035714 |
| Hit@10 | 1.000000 | 0.928571 | -0.071429 |
| Recall@10 | 1.000000 | 0.657232 | -0.342768 |
| F2@10 | 0.378401 | 0.497791 | +0.119390 |
| MRR | 0.619940 | 0.797215 | +0.177275 |
| Median gold size | 1 | 8 | +7 tables |

Proxy không chỉ “lạc quan hơn”. Nó đổi kích thước và hình dạng relevance set, làm Hit@1/MRR/F2 tăng nhưng Hit@3/5/10 và Recall@10 giảm trên cùng câu hỏi. Vì vậy proxy có thể đảo chiều kết luận tùy metric.

Nguyên tắc sử dụng:

- proxy dùng để tìm failure cluster hoặc regression thô trên diện rộng;
- manual gold dùng để ra quyết định ranking;
- official evaluator dùng cho production score;
- không lấy `0.474807 proxy F2` để nói tốt hơn `0.384460 manual F2`;
- 95 gold cũ đã được dùng trong feature engineering, nên chính nó cũng là development evidence, không phải untouched held-out.

## 9. Failure Analysis

Taxonomy dùng trong audit:

- **F0_UNSCORABLE:** không có gold đủ tin cậy để chấm.
- **F1_NO_RETRIEVAL_RESULT:** S1 trả rỗng.
- **F2_GOLD_DROPPED_BY_S1:** S1 có candidate nhưng không còn gold; đây là hard-filter false negative nghiêm trọng.
- **F3_RANK_MISS:** gold còn ở S1 nhưng không vào top-K.
- **F4_RERANK_REGRESSION:** S2 có gold trong cutoff nhưng S3 làm mất.
- **F5_RETRIEVAL_PASS:** có gold trong top-K.

Kết quả trên manual gold 95 ở `K=10`:

| Failure class | OLD | NEW | Diễn giải |
|---|---:|---:|---|
| F1 | 0 | 0 | Không có empty retrieval |
| F2 | 0 | 0 | Không hard-filter false negative trên sample này |
| F3 | 9 | 9 | Toàn bộ lỗi nằm ở ranking/cutoff |
| F4 | 0 | 0 | S3 identity nên không tạo flip |
| F5 | 86 | 86 | Cùng tập QID pass |

Trong 9 F3:

- 6 câu có gold ở top-50 nhưng tại hạng `11, 12, 12, 14, 16, 19`;
- 3 câu không có gold trong top-50;
- 6 câu là multi-entity `screen`, 1 `compare`, 1 `single`, 1 `related` theo trace runtime.

Q975 nhìn bề mặt là câu nhiều mã nhưng parser phân loại `related`; đây chính là lý do phải dùng trace runtime thay vì phân loại bằng mắt.

## 10. Case-Level Paired Comparison

### Paired outcome matrix

| Nhóm | Số câu | QID |
|---|---:|---|
| OLD wrong → NEW correct | 0 | — |
| OLD correct → NEW wrong | 0 | — |
| Both correct | 86 | Không liệt kê toàn bộ |
| Both wrong | 9 | 374, 376, 385, 397, 436, 542, 723, 767, 975 |

Exact McNemar trên discordant pairs: không có discordant pair, quy ước `p=1.0`. Không có bằng chứng paired improvement hay paired regression ở Hit@10.

### Chi tiết 9 rank miss

| QID | Mode | Targets | S1 candidates | Best gold rank OLD | Best gold rank NEW | Nhận định |
|---:|---|---:|---:|---:|---:|---|
| 374 | screen | 4 | 2,080 | 11 | 11 | Near miss ngay sau cutoff |
| 376 | screen | 7 | 2,084 | 12 | 12 | Global top-K không bảo đảm coverage theo ticker |
| 385 | screen | 5 | 2,052 | >50 | >50 | Ranking signal không đủ |
| 397 | screen | 8 | 2,663 | >50 | >50 | Pool rất rộng, multi-metric formula |
| 436 | screen | 6 | 1,905 | 14 | 14 | Near miss |
| 542 | screen | 3 | 1,156 | >50 | >50 | Entity/legal-name và compound metric khó; intent hiện vẫn giống OLD |
| 723 | single | 1 | 340 | 12 | 12 | Related-party note bị xếp dưới cutoff |
| 767 | compare | 2 | 467 | 19 | 19 | Separate-basis comparison; gold sâu |
| 975 | related | 4 | 1,406 | 16 | 16 | Multi-entity aggregation |

Top-10 order của OLD và NEW giống nhau ở cả 9 ca này. Điều đó củng cố kết luận rằng NEW chưa giải quyết failure cluster chính.

## 11. Query-Type Analysis

Trên 95 gold, OLD và NEW đưa ra cùng mode cho cả 95 câu:

| Mode | n | Hit@10 OLD | Hit@10 NEW | Recall@10 OLD/NEW | F2@10 OLD/NEW |
|---|---:|---:|---:|---:|---:|
| single | 52 | 0.980769 | 0.980769 | 0.944712 | 0.433733 |
| screen | 29 | 0.793103 | 0.793103 | 0.310016 | 0.290141 |
| compare | 12 | 0.916667 | 0.916667 | 0.708333 | 0.393519 |
| related | 2 | 0.500000 | 0.500000 | 0.500000 | 0.416667 |

`screen` là slice có bằng chứng đáng tin nhất về weakness: sample đủ lớn hơn `related`, Hit@10 chỉ `23/29`, recall rất thấp vì một global top-10 phải phục vụ nhiều ticker và nhiều operand. `related` có n=2 nên chỉ là tín hiệu điều tra, không đủ để kết luận tổng quát.

Full proxy 1,006 measurable của OLD cũng cho cùng hướng: screen F2@10 `0.320988`, thấp hơn single `0.515289`, compare `0.451297` và related `0.414289`. Tuy nhiên đó vẫn là proxy evidence.

## 12. Entity / Year / Basis Analysis

### Theo số target entity

| Số target | n | Hit@10, cả OLD và NEW |
|---:|---:|---:|
| 1 | 52 | 0.980769 |
| 2 | 12 | 0.916667 |
| 3 | 8 | 0.875000 |
| 4 | 8 | 0.750000 |
| 5 | 4 | 0.750000 |
| 6 | 4 | 0.750000 |
| 7 | 5 | 0.800000 |
| 8 | 2 | 0.500000 |

Xu hướng giảm theo entity count là rõ về mặt mô tả, nhưng bucket 5–8 nhỏ. Nguyên nhân phù hợp với global cutoff và pool tăng mạnh; chưa có causal experiment riêng.

NEW có entity parser tốt hơn về code: word-boundary alias, merge ticker/name, bảo vệ legal name dài và thêm cues. Tuy nhiên `intent_changes = 0/95`, nên **impact của các sửa này trên phân bố 1,012 câu là NOT MEASURED với manual gold**.

### Theo số năm được parse

| Số năm | n | Hit@10, cả OLD và NEW |
|---:|---:|---:|
| 1 | 68 | 0.911765 |
| 2 | 19 | 0.842105 |
| 3 | 4 | 1.000000 |
| 5 | 4 | 1.000000 |

S1 dùng một khoảng liên tục từ `min(year)` đến `max(year)+1`, nên câu nhiều năm có thể kéo vào cả năm trung gian không được hỏi. Đây là lựa chọn recall-oriented; precision cost chưa được isolate.

### Basis

| Retrieval basis parse | n | Hit@10, cả OLD và NEW |
|---|---:|---:|
| consolidated | 62 | 0.870968 |
| separate | 33 | 0.969697 |

Phân loại lexical độc lập cho thấy 34 câu có từ khóa basis explicit và Hit@10 `0.970588`; 61 câu không explicit có Hit@10 `0.868852`. Đây là correlation, không phải bằng chứng rằng separate tốt hơn.

NEW tách `answer_basis` khỏi retrieval default: q767 có `retrieval basis=separate` và `answer_basis=separate`; câu không explicit không ép answer basis. Đây là thiết kế đúng hơn cho downstream binding, nhưng canonical S1 vẫn dùng `basis_mode=soft`, nên không tạo hard false negative.

## 13. Hard Filter Analysis

Hard filters production thực sự chỉ gồm ticker, year range và `retrieval_ready=1`; basis production là soft prior.

### False-negative evidence

- Manual gold 95: candidate hit `95/95`; F2 hard-filter failure = `0` cho cả OLD/NEW.
- `retrieval_ready=1` hiện đúng cho `146,246/146,246` cards ở cả DB; predicate này hiện là contract guard hơn là một filter có tác dụng.
- Khi entity không resolve, implementation trả empty list; full proxy report có một `screen_open` candidate hit 0. Manual gold hiện không cover đủ ca unresolved để định lượng risk.

### Basis hard-filter A/B trên OLD proxy, cùng 1,006 QID

| Metric | Soft basis | Hard basis | Delta |
|---|---:|---:|---:|
| Candidate hit | 0.998012 | 0.976143 | -0.021869 |
| Hit@10 | 0.915507 | 0.909543 | -0.005964 |
| F2@10 | 0.474807 | 0.422361 | -0.052446 |
| nDCG@10 | 0.716601 | 0.677328 | -0.039273 |
| S1 median | 470 | 245 | -225 |

Hard basis làm pool nhỏ hơn nhưng có 14 flip-out và chỉ 8 flip-in ở Hit@10. Dù gold là proxy, mức candidate loss đủ lớn để xác nhận lựa chọn production `soft` là an toàn hơn. Hard-filter false negative phải được coi là lỗi nghiêm trọng; không nên đổi sang hard basis nếu chưa có manual held-out bảo vệ.

Docstring S1 nói pool trung bình khoảng 75/max 248 khi lọc ticker+year+basis, nhưng paired production-soft audit có median 501 và p90 2,084. Con số docstring thuộc điều kiện cũ/hard hơn và không phản ánh workload production hiện tại.

## 14. Ranking Analysis

Ranking là nơi có failure concentration cao nhất:

- 9/9 manual failures là F3 rank miss;
- 6/9 nằm ngay hạng 11–19, cho thấy cutoff/ranking order quan trọng;
- 3/9 nằm ngoài top-50, cần signal hoặc candidate shaping tốt hơn chứ không chỉ tăng top-10;
- Hit@10 giảm từ `0.9808` ở 1 target xuống `0.75` hoặc thấp hơn ở nhiều bucket 4–8 targets.

Các vấn đề kỹ thuật:

1. **Global top-K sai đơn vị cho screen.** Một ticker có thể chiếm nhiều slot trước khi ticker khác có một slot. Code có per-ticker fanout nhưng default không bật.
2. **Fixed bonuses lớn so với BM25.** Tổng bonus tiềm năng `1.25` lớn hơn normalized BM25 range `[0,1]`; structural priors có thể lấn lexical relevance.
3. **FTS query rộng.** Historical profile OLD cho thấy `_bm25_scores` chiếm khoảng 85% cumtime; `MATCH` có thể khớp khoảng 130k/146k cards trong sample dù S1 chỉ vài trăm đến vài nghìn.
4. **Default stop mode `fold`.** Repo ghi nhận diacritic-folded stop terms có thể nuốt từ có nghĩa; implementation OLD/NEW hiện giống nhau ở phần query terms, nên weakness này chưa được NEW giải quyết.
5. **Metric code hints có lợi nhưng coverage hữu hạn.** NEW thêm code/phrase safety, nhưng không có held-out isolated delta.

OLD có experiment `primary_boost=0.60` trên development gold 95: F2 `0.454886→0.499442`, Recall `0.598133→0.654453`, Precision `0.251784→0.278904`, Hit@10 `0.873684→0.936842`. Kết quả này **không phải NEW production result**, đã feature-select trên cùng gold và không được phép dùng làm promotion evidence. Nó chỉ chỉ ra một hướng thử lại trên held-out độc lập.

## 15. Reranker Analysis

### Production behavior

`RetrievalToSubmission` khởi tạo `IdentityReranker`; config `eval_v1.yaml` cũng đặt `reranker: identity`. Trace identity ghi rõ `model: null`, `passthrough: true`. Vì vậy:

- OLD S3: pass-through/truncate;
- NEW canonical V2 S3: pass-through/truncate;
- mọi claim “NEW có learned reranker production” là sai.

### Linear reranker candidate

NEW có model 13 features, deterministic tie-break, kiểm đủ feature contract và bind SHA. Artifact development ghi:

| Split | n | Identity F2@10 | Linear F2@10 | Identity Hit@10 | Linear Hit@10 | Identity MRR@10 | Linear MRR@10 |
|---|---:|---:|---:|---:|---:|---:|---:|
| train | 76 | 0.395430 | 0.393052 | 0.921053 | 0.947368 | 0.545337 | 0.583563 |
| dev | 19 | 0.340581 | 0.423062 | 0.842105 | 0.947368 | 0.543860 | 0.639098 |
| held-out | 120 | `NOT MEASURED` | `NOT MEASURED` | — | — | — | — |

Status artifact là `DEVELOPMENT_ONLY_NOT_PROMOTED`; held-out là `BLOCKED_AWAITING_INDEPENDENT_LABELS`. Gold 95 đã bị dùng cho feature engineering, và epoch được chọn theo dev-19. Dev lift đáng để tiếp tục, nhưng train F2 giảm nhẹ và chưa có independent labels. Production readiness của linear reranker hiện là **INSUFFICIENT EVIDENCE**.

Không có cross-encoder hoặc LLM reranker trong production path.

## 16. Retrieval → Answer Impact

Retrieval quality và answer quality là hai biến khác nhau:

- Retrieval hit chỉ nói ít nhất một gold table vào cutoff; nó không đảm bảo chọn đúng operand, period, unit, basis, operation hay formatting.
- Answer đúng có thể dùng một evidence set nhỏ hơn retrieval pool; NEW đã sửa contract để table thực sự bind là authoritative evidence.
- Answer sai dù retrieval đúng vẫn có thể do D1/decomposition, operand selection, arithmetic, unit hoặc abstention policy.

Evidence hiện có:

- NEW canonical V2 lịch sử tạo retrieval cho 1,011/1,012 câu, trả 561 answers và abstain 451.
- Local manual answer check được báo cáo là 14/31 correct/executable trên một sample khác.
- OLD historical funnel 31 câu ghi all-gold-tables retrieved 9/31, exact answer 5/31; first failure gồm retrieval 16, D1 4, operand 4, operation 1, unit 1.

Các số trên **không cùng sample/protocol** với paired retrieval 95. Không có per-QID joint contingency `retrieval_hit × answer_correct` trên cùng independent gold. Vì vậy:

**Causal impact của NEW retrieval lên answer accuracy: NOT MEASURED.**

Tuy nhiên, evidence contract của NEW là cải thiện thật: answer OK publish exact bound tables/docs, tránh trường hợp answer cite một top-N prior không phải nguồn đã dùng. Đây là correctness/auditability improvement, không tự động là answer-accuracy improvement.

## 17. Performance Comparison

### Diagnostic paired run hiện tại, manual gold 95

| Latency | OLD | NEW | NEW − OLD |
|---|---:|---:|---:|
| Mean | 413.95 ms | 421.23 ms | +7.28 ms (+1.76%) |
| p50 | 255.60 ms | 256.21 ms | +0.61 ms |
| p95 | 1,245.30 ms | 1,231.78 ms | -13.52 ms |

Đây là một run warmed, sequential, alternating order trên interpreter hiện tại; không khóa CPU governor, cache state, Python/SQLite build hay concurrent load. Không có bootstrap CI cho latency. Kết luận hợp lệ duy nhất là **không thấy chênh lệch hiệu năng lớn**; không thể kết luận NEW nhanh hơn hoặc chậm hơn production.

### Historical OLD profile

Artifact 1,012 câu ghi retrieval S0→S3 `342s`, mean `338ms`, p50 `252ms`, p95 `843ms`, p99 `1,167ms`; screen mean `644ms`. Profile 45 câu quy khoảng 85% thời gian cho `_bm25_scores`; sample khác cho workload CPU-bound 91–94%, RSS khoảng 235–237MB, major page fault 0.

Các số historical này không cùng môi trường với diagnostic NEW, nên không dùng để tính speedup OLD→NEW.

| Metric performance khác | Trạng thái |
|---|---|
| Retrieval snapshot build time OLD vs NEW | `NOT MEASURED` trên cùng máy/protocol |
| Peak memory NEW | `NOT MEASURED` |
| Throughput multi-worker NEW | `NOT MEASURED` |
| p99 NEW production | `NOT MEASURED` |
| Index load/cold-start | `NOT MEASURED` |

## 18. Reproducibility

### OLD

Ưu điểm:

- `PROVENANCE.json` ghi source DB/package SHA, build ID, commit và indexes thêm.
- Official freeze ghi parameters và submission identity.

Hạn chế:

- `work.db` là working derivative; quy trình copy/index không tạo một namespace immutable mạnh như NEW.
- Eval checkpoint cũ chủ yếu bind config, chưa bind đầy đủ active DB bytes/snapshot identity.
- MRR S2/S3 trong một số report cũ dùng cutoff khác nhau, dễ tạo chênh lệch giả.

### NEW

Ưu điểm:

- `active_snapshot.yaml` là point-in-time selector duy nhất cho canonical runtime.
- Retrieval manifest bind source A6 build, source DB SHA/bytes, index specs, DB SHA/bytes và row counts.
- Verifier hiện PASS toàn bộ retrieval manifest, index ID, source build, DB bytes, table/FTS schema và bốn indexes.
- Builder stage/verify/atomic-rename và từ chối overwrite snapshot đã tồn tại.
- Evalkit checkpoint bind cả config lẫn active snapshot fingerprint.
- Reranker model bind feature order và training-manifest SHA.

Rủi ro hiện tại:

1. **Git object database hỏng.** `git status` báo pack file “far too short” và `fatal: bad object HEAD`. Historical report có commit identity, nhưng source snapshot hiện tại không thể được Git xác nhận. Đây là production/release provenance blocker dù runtime DB verifier vẫn PASS.
2. `configs/pipelines/retrieval_frozen_v1.yaml` vẫn ghi A6 `b3e9684004679ffb` và index `286973b134a189ee`, trong khi active SSOT là `c688.../872...`.
3. `pipelines/retrieval/__init__.py`, `eval_s1.py`, `eval_retrieval.py`, `goldkit.py`, `mine_alias.py` còn hard-code identity cũ. Canonical runtime không dùng các path này, nhưng dev/eval tooling có nguy cơ chạy sai snapshot.
4. Diagnostic paired audit hiện được ghi aggregate trong tài liệu này, không có machine-readable per-QID artifact vì yêu cầu đầu ra chỉ một file. Replay exact latency vì vậy bị hạn chế.

Tổng hợp: NEW có thiết kế reproducibility tốt hơn rõ rệt, nhưng **current checkout source reproducibility đang bị Git corruption và config migration debt làm giảm điểm**.

## 19. Regression Analysis

### Quality regression

- Hit@1, Hit@10, P@10, R@10, F2@10: không regression, không improvement trên same-gold paired 95.
- MRR@10: `-0.000877`; nDCG@10: `-0.000730`. Đây là rank-order drift nhỏ, không làm đổi Hit@10; `INSUFFICIENT EVIDENCE` để gọi là meaningful regression.
- Candidate coverage: không đổi `95/95`.
- Intent trace: không đổi `0/95` câu.

### Operational regression risks

| Risk | Severity | Evidence |
|---|---|---|
| Git HEAD/object DB không đọc được | Critical cho release provenance | `fatal: bad object HEAD` |
| Frozen/dev retrieval identity cũ tồn tại song song active SSOT | High | b3e/286 hard-code trong config/module/script |
| Linear reranker có thể được bật nhầm ngoài promotion gate | High | Có profile/model nhưng held-out chưa label |
| V2 docs/comment về S1 pool cũ | Medium | docstring avg 75/max248 vs measured median501/p90 2084 |
| 566 observation delta chưa có semantic diff report retrieval-focused | Medium | Count khác, paired 95 không đổi |

### Improvements that reduce regression risk

- Strict positional zip ở S2;
- checkpoint snapshot fingerprint;
- same-cutoff MRR;
- fail-closed reranker feature contract;
- immutable snapshot verifier;
- exact downstream evidence publication.

## 20. Complexity vs Value

| Thay đổi NEW | Complexity | Giá trị đã chứng minh | Nhận định |
|---|---|---|---|
| Immutable retrieval snapshot + verifier | Medium | Cao | Giữ; đây là delta tốt nhất |
| Active snapshot SSOT | Low/medium | Cao | Giữ, nhưng phải xóa/đánh dấu path cũ |
| Evalkit fingerprint/taxonomy/same-cutoff metrics | Medium | Cao | Giữ |
| Namespace/layer refactor của V2 | Medium | Trung bình | Maintainability tốt hơn, quality không đổi |
| Entity/basis intent enhancements | Medium | Plausible, chưa đo rộng | Giữ; thêm isolated tests/eval |
| 13-feature linear reranker | Medium/high | Dev-only, held-out chưa đo | Không promote |
| Semantic V3 operand retrieval | High | Shadow/internal evidence có, production chưa có | Tiếp tục như track riêng |
| Nhiều dormant knobs S2 | Medium debt | Mixed/contaminated experiments | Thu gọn sau held-out decision |
| Hard-coded legacy identities còn sót | Low code, negative value | Gây snapshot ambiguity | Sửa P0/P1 |

Chi phí NEW có giá trị khi nó phục vụ determinism, auditability và typed evidence. Chi phí chưa tạo giá trị production là learned reranker/V3 khi chưa qua independent acceptance. Không nên thêm vector DB hoặc LLM reranker chỉ vì hệ hiện đại hơn; 9 lỗi hiện tại cần được giải thích bằng controlled experiments trước.

## 21. Retrieval Scorecard

Thang 0–10. Điểm là rubric engineering có giải thích, không phải official metric. Overall là trung bình đều 13 tiêu chí; không thay thế paired evaluation.

| Tiêu chí | OLD | NEW | Cơ sở |
|---|---:|---:|---|
| Candidate recall | 9.0 | 9.0 | 95/95 manual; proxy gần 1.0 |
| Ranking quality | 6.5 | 6.5 | Cùng Hit/F2; 9 rank miss |
| Precision | 4.5 | 4.5 | Macro P@10 0.2126 |
| Entity handling | 6.5 | 7.5 | NEW parser an toàn hơn, impact rộng chưa đo |
| Year handling | 7.0 | 7.0 | Recall-oriented slack; range có thể rộng |
| Basis handling | 6.5 | 7.0 | Soft basis tốt; NEW tách answer_basis |
| Robustness | 6.0 | 7.5 | NEW fail-closed contracts; current debt còn |
| Determinism | 7.0 | 8.5 | NEW snapshot/model/tie contracts tốt hơn |
| Reproducibility | 6.5 | 6.5 | NEW design tốt hơn nhưng checkout Git đang hỏng |
| Latency | 6.0 | 6.0 | Gần ngang; benchmark production thiếu |
| Maintainability | 5.5 | 8.0 | NEW package/config structure tốt hơn |
| Extensibility | 5.5 | 8.5 | Linear S3 + typed operand V3 |
| Observability | 6.5 | 8.5 | Stage trace, taxonomy, snapshot-bound checkpoints |
| **Overall** | **6.35** | **7.31** | Engineering maturity, không phải relevance lift |

Điểm overall NEW cao hơn chủ yếu do hệ thống kiểm soát, không do retrieval relevance. Nếu chỉ chấm paired relevance trên gold 95, hai hệ hòa ở các metric chính.

## 22. Final Verdict

### Verdict: YES WITH CONDITIONS

**Chọn NEW làm retrieval layer production kế tiếp**, với diễn giải chính xác:

- NEW không làm giảm paired Hit@10/F2 trên manual gold 95;
- NEW không làm tăng paired Hit@10/F2 trên manual gold 95;
- NEW vượt OLD về snapshot immutability, lineage, checkpoint identity, evidence publication, observability và khả năng mở rộng;
- production reranker vẫn là identity;
- answer-accuracy impact chưa đo được;
- official NEW retrieval score chưa có.

Các điều kiện phải hoàn thành trước khi gọi release “production-ready” theo nghĩa đầy đủ:

1. phục hồi Git object database và xác nhận commit/tree sạch, có thể replay;
2. thống nhất mọi retrieval config/tool về active snapshot hoặc đánh dấu file cũ là historical-only;
3. tạo independent held-out labels và chạy promotion protocol cho identity vs linear reranker;
4. materialize paired retrieval report có per-QID trace trên sample lớn hơn, đặc biệt screen/multi-entity;
5. đo joint retrieval→answer contingency trên cùng QID/gold;
6. chạy performance benchmark được khóa môi trường nếu latency là SLO.

Nếu các điều kiện trên chưa xong, NEW vẫn phù hợp cho controlled production candidate/canary, nhưng không đủ bằng chứng để tuyên bố quality superiority hoặc promote learned reranker.

## 23. Recommended Next Actions

| Ưu tiên | Action | Success criterion | Lý do |
|---|---|---|---|
| P0 | Phục hồi `.git` từ nguồn tin cậy, chạy `git fsck`, xác nhận HEAD/tree/dirty state | Git đọc được toàn bộ object; commit identity được ghi vào acceptance artifact | Không có source provenance thì snapshot DB tốt vẫn chưa đủ cho release |
| P0 | Hợp nhất retrieval identity | Canonical, frozen và dev/eval tools đều resolve active SSOT; legacy file ghi rõ historical-only | Loại nguy cơ chạy nhầm b3e/286 thay vì c688/872 |
| P0 | Gán nhãn độc lập held-out 120 và khóa trước protocol | n≥100; identity vs linear có paired F2/Hit/MRR, bootstrap CI và protected slices | Điều kiện bắt buộc để quyết định reranker |
| P1 | Mở rộng manual gold lên ít nhất 300 câu stratified | Đủ screen, compare, related, bank/non-bank, basis, 1–8 entities; provenance/annotation agreement rõ | 95 development gold quá nhỏ và đã bị feature engineering chạm |
| P1 | A/B per-ticker fanout/primary prior/ranking weights **từng biến một** | Không giảm candidate hit; Hit/F2/Recall và CI cải thiện trên held-out; screen protected slice không giảm | Nhắm đúng 6 screen miss và global-cutoff bottleneck |
| P1 | Tạo case report cho 9 miss | Với từng QID: S1 membership, S2 features, rank, missing metric/code/statement, expected table | Biết sửa signal hay cutoff thay vì thêm complexity mù |
| P1 | Đo joint retrieval→binding→answer | Ma trận per-QID: retrieval hit, operand hit, executable, answer correct, abstain | Tách đúng tác động retrieval khỏi answer pipeline |
| P1 | Benchmark retrieval chuẩn hóa | Cold/warm p50/p95/p99, throughput, CPU/RSS, single/multi worker, cùng DB/cache protocol | Hiện chưa có performance conclusion production |
| P2 | Tối ưu FTS breadth sau quality gates | Giảm MATCH work/latency mà paired relevance CI không âm | Hotspot hiện nằm ở FTS scan, nhưng thay query sẽ đổi ranking |
| P2 | Chỉ thử dense/hybrid hoặc cross-encoder khi error study yêu cầu | Có baseline, latency/cost budget, independent lift và rollback | Tránh tăng stack khi candidate recall đã 100% trên gold 95 |
| P2 | Thu gọn dormant knobs và tài liệu stale | Mỗi production knob có owner, default, evidence, retirement rule | Giảm cấu hình khó audit |

**Thứ tự thực thi đề nghị:** provenance/config hygiene → independent labels → paired ranking experiments → joint answer impact → performance optimization. Không promote linear reranker, không bật hard basis và không thêm vector layer trước khi ba bước đầu hoàn tất.
