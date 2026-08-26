# Semantic Query Engine v3 migration status

Updated: 2026-08-26

## Decision

V3 is implemented as a shadow runtime. V2 remains canonical until the locked
promotion policy passes.  This is a deliberate strangler migration, not a
second production implementation.

## Delivered architecture

| Capability | V3 contract |
|---|---|
| Semantic model | Immutable and serialisable `QuestionAST` with nested arithmetic, aggregate, rank, predicate, formula and select-at-arg nodes |
| Ontology | One checksum-locked API over 24 reviewed metrics, 24 reviewed formulas and 346 reported lookup metrics |
| Parser | Vietnamese annotator port followed by compositional AST compilation and structural validation |
| Planning | Every `MetricRef` expands to a stable operand request per entity-period scope |
| Retrieval | SQLite A6 retrieval per operand, not one shared table pool for the whole question |
| Binding | Beam-search global assignment with per-scope formula document/currency/distinctness constraints |
| Execution | Decimal/unit typed visitor and independent restricted-pandas compiler |
| Grounding | Tables and documents are derived only from selected observation UIDs |
| Verification | Typed result must equal clean pandas replay or the answer is rejected |
| Rollout | Immutable `shadow-v3` run, V2 differential taxonomy and explicit promotion gate |

## Full-corpus shadow baselines

All runs used all 1,012 questions, active A6 build `b3e9684004679ffb` and
operand top-K 20. The final audited shadow compares against canonical run
`production-final-v3-20260826`.

| Metric | Reviewed-only baseline | Reported-catalog baseline | Final audited shadow |
|---|---:|---:|---:|
| V3 OK | 162 | 285 | 298 |
| V3 abstain | 850 | 727 | 714 |
| Metric unresolved | 589 | 198 | 198 |
| Reported metric blocked for derived operation | 0 | 263 | 249 |
| Typed/pandas replay mismatch | 0 | 0 | 0 |
| Both V2/V3 OK and equal | 62 | 103 | 121 |
| Both OK but value differs | 56 | 126 | 137 |
| V3-only OK | 44 | 56 | 40 |
| Runtime | 86.415 s | 87.483 s | 89.685 s |

Artifacts:

- `artifacts/runs/semantic-v3/semantic-v3-baseline-20260826/manifest.json`
- `artifacts/runs/semantic-v3/semantic-v3-reported-catalog-20260826/manifest.json`
- `artifacts/runs/semantic-v3/semantic-v3-final-20260826/manifest.json`

These are coverage and differential measurements, not accuracy. The 137 current value
differences cannot be promoted or labelled as improvements until adjudicated
against independent evidence/answer gold.

## Promotion state

Status: **BLOCKED by policy**, as intended.

The policy in `configs/semantic/promotion_policy_v3.yaml` requires:

- a full 1,012-question run;
- at least 300 semantic-gold and 300 evidence-gold records;
- AST exact match >= 0.95;
- candidate recall >= 0.99;
- binding exact match >= 0.90;
- answer accuracy >= 0.80;
- zero typed/pandas replay mismatches;
- zero submission errors.

Missing metrics are `NOT_MEASURED` and block promotion.  They are never treated
as zero, pass or not-applicable.

## Remaining migration waves

1. Adjudicate a stratified V3 Gold set, beginning with the 137 V2/V3 value
   differences and all `V3_ONLY_OK` cases.
2. Promote reported metrics to reviewed canonical metrics by family; derived
   operations remain blocked until promotion.
3. Add predicate compilation for filtered COUNT/extrema and complete nested
   formula composition.
4. Evaluate operand rank features and binding exactness on held-out evidence;
   train a reranker only if the deterministic baseline is beaten.
5. Run V3 submission packaging/replay in shadow, pass the promotion policy,
   then switch the canonical composition root and remove compatibility engines.
