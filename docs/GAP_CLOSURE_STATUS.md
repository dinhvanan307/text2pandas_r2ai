# Gap closure status

Updated: 2026-08-27

> Semantic Query Engine v3 is available in shadow mode. Its architecture, full-corpus differential baselines and promotion blockers are recorded in `docs/SEMANTIC_V3_MIGRATION_STATUS.md`. V2 remains canonical until the code-enforced V3 promotion policy passes.

## Measurement boundary

`make semantic-coverage` chạy deterministic trên 1.012 câu hỏi curated và dùng đúng router/formula registry của canonical runtime. Kết quả hiện tại:

- Static route eligible: **669/1.012 (66,1067%)**.
- Named semantic gaps: **343/1.012**.
- Corpus SHA-256: `59effd1ee7cf7214caee430b05b9305f5a71ed3fd57ba19eb1a6ff2f9c3ffa5d`.

Đây không phải accuracy. Retrieval recall, operand binding và giá trị answer chỉ được kết luận bằng materialized evaluation/replay.

## Closed gaps

| Area | Delivered contract |
|---|---|
| Data lifecycle | `raw → processed/a6 → indexes/retrieval`, active snapshot preflight, immutable run outputs |
| Lineage | Raw/A6/retrieval identities và portable run/submission manifests |
| Submission | Exact schema, raw-corpus grounding, AST sandbox, replay, deterministic ZIP, fail-closed publish |
| Extrema | Typed `MAX/MIN/ARGMAX/ARGMIN`, period result kind và policy guards |
| Reviewed formulas | 27 công thức trên 28 metric đã review, gồm expense/COGS intensity, explicit ending-assets return, debt/equity ratios, fixed-asset and receivable shares, interest/borrowings, CFO/PBT và financial-income/financial-expense; per-metric statement/period/context binding, per-leaf unit conversion, same-report/same-currency coherence |
| Formula binding hardening | Ưu tiên closing balance thay movement column, statement-type contract, section relevance, unanimous explicit table-scale inheritance và stable row index khi observation trùng |
| A6 H0 | 34 provenance records, 22 materialized gates, two clean deterministic rebuilds |
| Coverage governance | Per-QID status/reason, corpus digest, CLI/Make command và CI baseline |
| Question unit parsing | Colloquial `mấy`, `trăm tỷ`, parenthesized/trailing units, share-count và year-count wording |
| Operation precision | Aggregate metric vs SUM, weighted-average metric vs AVG, report-scope `trên` vs DIVIDE, signed less-than subtraction |
| Period COUNT | Typed threshold/negative predicates over explicit years, reviewed metric aliases, sandboxed comparisons and fail-closed existence semantics |
| Entity adjudication | Không để short nested brand xoá legal name độc lập; nhận `hiệu số` là comparison; 12 false mismatch được phân loại lại theo runtime scope thật |
| Entity resolver P0-d | Word-boundary aliases, merge explicit ticker + company-name evidence, directional/`chênh lệch với` comparison cues; 6 strict xfails converted to regression passes |
| Two-entity difference | Typed absolute difference cho đúng 2 entity/1 kỳ/1 metric, distinct evidence, same-metric gate và per-operand unit conversion |
| Share scale | `nghìn/triệu/tỷ cổ phiếu` là scaled `SHARES`, không còn bị đọc nhầm thành money |
| Entity COUNT | Typed sign/threshold (`hơn`, `vượt`) predicate cho explicit entity set, one fact per entity, distinct evidence; `tổng số công ty` cue; compound multi-metric predicates fail-closed |
| Entity average | Typed mean cho reviewed direct monetary/share metrics, one fact per entity, distinct evidence và per-operand unit conversion; percent/ratio, filtered cohort và unreviewed metric fail-closed |
| Entity SUM | Typed cross-company sum cho reviewed direct metrics, explicit sum cue, one fact per entity, expense sign policy, distinct evidence và per-operand unit conversion |

## Open semantic gaps

| Priority | Gap family | Questions | Fill strategy / exit gate |
|---|---|---:|---|
| P1 | Multi/global-entity aggregation/ranking | 243 | Extend the typed entity axis beyond reviewed difference, count, average, and sum routes; bind one fact per entity; prove no entity reuse; add rank emitters and multi-entity gold slices |
| P1 | Unreviewed relational formulas | 23 | Curate formula and metric ontology; forbid generic numerator/denominator guessing; require reviewed formula tests and real-corpus smokes |
| P1 | Complex extrema | 42 | Derived ranking: 4; filtered extrema: 6; select-at-arg: 32. Add separate rank metric/result metric and predicate IR |
| P2 | Operand/period arity unresolved | 8 | SUBTRACT: 7; GROWTH: 1. Remaining cases need explicit two-operand semantics |
| P2 | Formula composition mismatch | 11 | Support formula inside aggregate/extremum only after nested typed IR and complete evidence are implemented |
| P2 | Single-entity conditional COUNT | 2 | Complex predicate: 1; existence/absence requiring negative-evidence completeness: 1. Two additional typed routes remain retrieval-dependent at runtime |

## Repository maturity gaps

| Priority | Gap | Evidence | Exit gate |
|---|---|---|---|
| P0 | Official Answer Accuracy và Execution Accuracy chưa đo được | Không có organiser-held answer gold. Local adjudicated slice: 14/31 correct + executable, 14/14 replay | Mở rộng independent answer/evidence gold hoặc chạy official scorer; luôn report riêng local/official scope |
| P0 | Canonical executable coverage mới đạt 55,93% | V2 phát 566/1.012 answers và fail-closed 446 câu | Đóng các semantic gaps P1, bind/execute trên gold và giữ fail-closed cho route chưa đủ evidence |
| P1 | Semantic V3 chưa đủ điều kiện promotion | V3 shadow phát 206 answers, abstain 806, có 72 value disagreements và 30 V3-only answers | Adjudicate tối thiểu 300 semantic gold và 300 evidence gold; tất cả metric trong promotion policy phải measured và pass |
| P1 | Rerank S3 chỉ là identity/truncation | MRR@10 của S2 và S3 cùng bằng 0,5450; uplift `+0,0000` trên 95 manual-gold cases. S2 full-list MRR 0,5497 chỉ là diagnostic top-50 | Tạo held-out rerank gold, benchmark deterministic/open-weight candidates và chỉ promote khi uplift có ý nghĩa thống kê |
| P1 | Retrieval gold chưa đủ đại diện | 95/1.012 câu có trusted table gold; 917 câu `NOT_MEASURED` | Mở rộng stratified evidence gold cho screen, multi-entity, bank, derived-metric và hard-negative slices |
| CLOSED | Production strict typing | `make typecheck`: zero errors trên 78 source files thuộc `domain/application/infrastructure/interface` | Gate nằm trong `make ci`; legacy pipeline debt không được đưa ngược vào production boundary |
| CLOSED | CI acceptance path | Locked `--require-hashes` install, correctness Ruff, strict mypy, 46-file docs-link check và self-hosted materialized lane | Duy trì `.github/workflows/ci.yml` và `materialized-acceptance.yml` |
| CLOSED | Skip governance | 42 historical-artifact skips được ADR 0010 phê duyệt theo path/reason/max-count; 0 unapproved skip | Mọi skip mới hoặc reason/count drift làm pytest session fail |
| CLOSED | Documentation link integrity | 46 tracked Markdown files, 0 broken relative links | `make docs-check` nằm trong CI |
| P2 | Project governance còn hai quyết định owner-only | Đã có `CONTRIBUTING.md`, `SECURITY.md`, author/classifiers và Dependabot; chưa có license/CODEOWNERS/verified project URLs | Owner chốt distribution license và GitHub team/user chính xác trước khi thêm, không suy đoán |
| P2 | Retrieval snapshot đang copy đầy đủ A6 thay vì sidecar-only | Snapshot storage còn nhân bản processed corpus | Ordered top-K parity + manifest/storage migration test trước khi chuyển sang sidecar-only |
| P3 | Compatibility shims và historical tools còn tồn tại | Legacy import paths vẫn được giữ cho downstream consumers | Downstream import inventory, deprecation window sign-off, sau đó xóa trong commit riêng |

Chi tiết test evidence và release recommendation nằm trong [`reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md`](reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md).

## Governance rule

Mọi thay đổi router/formula phải cập nhật có chủ đích `tests/fixtures/semantic_coverage_baseline.json`. CI failure do baseline drift là review gate, không được sửa snapshot chỉ để làm test xanh.
