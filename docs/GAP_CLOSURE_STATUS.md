# Gap closure status

Updated: 2026-08-26

## Measurement boundary

`make semantic-coverage` chạy deterministic trên 1.012 câu hỏi curated và dùng
đúng router/formula registry của canonical runtime. Kết quả hiện tại:

- Static route eligible: **578/1.012 (57,1146%)**.
- Named semantic gaps: **434/1.012**.
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

## Open semantic gaps

| Priority | Gap family | Questions | Fill strategy / exit gate |
|---|---|---:|---|
| P1 | Multi-entity aggregation/ranking | 248 | Typed entity axis; bind one fact per entity; prove no entity reuse; add COUNT/rank emitters and multi-entity gold slices |
| P1 | Unreviewed relational formulas | 41 | Curate formula + metric ontology; forbid generic numerator/denominator guessing; require reviewed formula tests and real-corpus smokes |
| P1 | Complex extrema | 49 | Derived ranking: 5; filtered extrema: 9; select-at-arg: 33; insufficient periods: 2. Add separate rank metric/result metric and predicate IR |
| P2 | Requested unit unresolved | 38 | Extend question-unit lexicon with reviewed corpus examples; keep `UNKNOWN_REQUESTED_UNIT` fail-closed |
| P2 | Operand/period arity unresolved | 42 | AVG: 12; SUBTRACT: 16; SUM: 13; GROWTH: 1. Improve list/range extraction before changing binders |
| P2 | Formula composition mismatch | 15 | Support formula inside aggregate/extremum/subtract only after nested typed IR and complete evidence are implemented |
| P3 | Entity alias miss | 1 | Adjudicate alias against A6 evidence, then update attested alias registry |

## Non-semantic engineering debt

| Priority | Gap | Exit gate |
|---|---|---|
| P1 | End-to-end score for the new canonical engine chưa được khóa trên gold | Report retrieval → bind → execute accuracy by slice; never infer accuracy from 57,1146% route coverage |
| P2 | Retrieval snapshot đang copy đầy đủ A6 thay vì sidecar-only | Ordered top-K parity + manifest/storage migration test |
| P3 | Compatibility shims và historical tools còn tồn tại | Downstream import inventory, deprecation window sign-off, then removal commit |

## Governance rule

Mọi thay đổi router/formula phải cập nhật có chủ đích
`tests/fixtures/semantic_coverage_baseline.json`. CI failure do baseline drift là
review gate, không được sửa snapshot chỉ để làm test xanh.
