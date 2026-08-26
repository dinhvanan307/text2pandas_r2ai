# Gap closure status

Updated: 2026-08-26

## Measurement boundary

`make semantic-coverage` chạy deterministic trên 1.012 câu hỏi curated và dùng
đúng router/formula registry của canonical runtime. Kết quả hiện tại:

- Static route eligible: **575/1.012 (56,8182%)**.
- Named semantic gaps: **437/1.012**.
- Corpus SHA-256: `59effd1ee7cf7214caee430b05b9305f5a71ed3fd57ba19eb1a6ff2f9c3ffa5d`.

Đây không phải accuracy. Retrieval recall, operand binding và giá trị answer chỉ
được kết luận bằng materialized evaluation/replay.

## Closed gaps

| Area | Delivered contract |
|---|---|
| Data lifecycle | `raw → processed/a6 → indexes/retrieval`, active snapshot preflight, immutable run outputs |
| Lineage | Raw/A6/retrieval identities và portable run/submission manifests |
| Submission | Exact schema, raw-corpus grounding, AST sandbox, replay, deterministic ZIP, fail-closed publish |
| Extrema | Typed `MAX/MIN/ARGMAX/ARGMIN`, period result kind và policy guards |
| Reviewed formulas | 8 công thức, per-metric binding, per-leaf unit conversion, same-report/same-currency coherence |
| A6 H0 | 34 provenance records, 22 materialized gates, two clean deterministic rebuilds |
| Coverage governance | Per-QID status/reason, corpus digest, CLI/Make command và CI baseline |
| Question unit parsing | Colloquial `mấy`, `trăm tỷ`, parenthesized/trailing units, share-count và year-count wording |
| Operation precision | Aggregate metric vs SUM, weighted-average metric vs AVG, report-scope `trên` vs DIVIDE, signed less-than subtraction |

## Open semantic gaps

| Priority | Gap family | Questions | Fill strategy / exit gate |
|---|---|---:|---|
| P1 | Multi/global-entity aggregation/ranking | 311 | Typed entity axis; bind one fact per entity; prove no entity reuse; add COUNT/rank emitters and multi-entity gold slices |
| P1 | Unreviewed relational formulas | 44 | Curate formula + metric ontology; forbid generic numerator/denominator guessing; require reviewed formula tests and real-corpus smokes |
| P1 | Complex extrema | 43 | Derived ranking: 4; filtered extrema: 6; select-at-arg: 32; insufficient periods: 1. Add separate rank metric/result metric and predicate IR |
| P2 | Operand/period arity unresolved | 11 | SUBTRACT: 10; GROWTH: 1. Four SUBTRACT cases are same-period derived finance metrics and require explicit two-metric IR |
| P2 | Formula composition mismatch | 12 | Support formula inside aggregate/extremum/subtract only after nested typed IR and complete evidence are implemented |
| P2 | Entity resolution mismatch | 12 | Compare runtime resolution to curated entity-set, adjudicate aliases against A6 evidence |
| P2 | Single-entity conditional COUNT | 4 | Add typed predicate over periods and COUNT result; do not reuse LOOKUP with a COUNT unit |

## Non-semantic engineering debt

| Priority | Gap | Exit gate |
|---|---|---|
| P1 | End-to-end score for the new canonical engine chưa được khóa trên gold | Report retrieval → bind → execute accuracy by slice; never infer accuracy from 56,8182% route coverage |
| P2 | Retrieval snapshot đang copy đầy đủ A6 thay vì sidecar-only | Ordered top-K parity + manifest/storage migration test |
| P3 | Compatibility shims và historical tools còn tồn tại | Downstream import inventory, deprecation window sign-off, then removal commit |

## Governance rule

Mọi thay đổi router/formula phải cập nhật có chủ đích
`tests/fixtures/semantic_coverage_baseline.json`. CI failure do baseline drift là
review gate, không được sửa snapshot chỉ để làm test xanh.
