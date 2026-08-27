# Semantic Query Engine v3 migration status

Updated: 2026-08-27

## Decision

V3 is implemented as a shadow runtime. V2 remains canonical until the locked
promotion policy passes.  This is a deliberate strangler migration, not a
second production implementation.

## Delivered architecture

| Capability | V3 contract |
|---|---|
| Semantic model | Immutable and serialisable `QuestionAST` with nested arithmetic, aggregate, quantified predicate, formula and select-at-arg nodes |
| Ontology | One checksum-locked API over 24 reviewed metrics, 24 reviewed formulas and 346 reported lookup metrics |
| Parser | Vietnamese annotator port followed by compositional AST compilation and structural validation |
| Planning | Every `MetricRef` expands to a stable operand request per entity-period scope |
| Retrieval | SQLite A6 retrieval per operand plus a checksum-bound learned S3 candidate; production still uses identity S3 |
| Binding | Beam-search global assignment with per-scope formula document/currency/distinctness constraints |
| Execution | Decimal/unit typed visitor and independent restricted-pandas compiler |
| Grounding | Tables and documents are derived only from selected observation UIDs |
| Verification | Typed result must equal clean pandas replay or the answer is rejected |
| Rollout | Immutable `shadow-v3` run, V2 differential taxonomy and explicit promotion gate |

## Current full-corpus shadow baseline

The current run uses all 1,012 questions, A6 build `c6887fb633374fad`, operand top-K 20, and canonical run `production-a6-v1.10-v2-r5-20260827`.

| Metric | Result |
|---|---:|
| V3 OK | 269 |
| V3 abstain | 743 |
| Metric unresolved | 198 |
| Ambiguous binding | 108 |
| Reported metric blocked for derived operation | 149 |
| Typed/Pandas replay mismatch | 0 |
| Both V2/V3 OK and equal | 157 |
| Both OK but value differs | 66 |
| V3-only OK | 46 |
| V2-only OK | 338 |
| Runtime | 64.17 s |

Artifact: `artifacts/runs/semantic-v3/semantic-v3-a6-v1.10-r17-20260827/manifest.json`.

These are coverage and differential measurements, not accuracy. The 66 value
differences and 46 V3-only answers require independent adjudication before
promotion. On the existing 31-record diagnostic slice, r17 has 6 correct among
6 emitted answers and fail-closes on 25. It no longer emits the three known
wrong answers present before the formula/rank safety audit. External execution
accuracy remains `NOT_MEASURED`; all 269 returned answers pass typed/Pandas and
clean packaged replay.

The r17 submission candidate contains exactly 1,012 records, validates with zero
errors/warnings, and replays 269/269 emitted queries. Its package SHA-256 is
`dfe1544388e12fe7753ee2e4e0d45a6ac01a90c3b40bd0ac26b59a68b6959f10`.

## Promotion state

Status: **BLOCKED by policy**, as intended.

The policy in `configs/semantic/promotion_policy_v3.yaml` requires:

- a full 1,012-question run;
- at least 300 semantic-gold and 300 evidence-gold records;
- AST exact match >= 0.95;
- candidate recall >= 0.99;
- binding exact match >= 0.90;
- answer accuracy >= 0.80;
- at least 100 sealed held-out reranker records, non-negative paired F2 uplift,
  non-negative CI95 lower bound and no protected-slice regression below -0.01;
- zero typed/pandas replay mismatches;
- zero submission errors.

Missing metrics are `NOT_MEASURED` and block promotion.  They are never treated
as zero, pass or not-applicable.

## Remaining promotion work

1. Complete the prepared prediction-blind 300-record packet with two independent
   annotators and a distinct adjudicator, then seal the common answer, semantic
   and ordered-evidence release.
2. Promote reported metrics to reviewed canonical metrics by family; derived
   operations remain blocked until promotion.
3. Extend the closed predicate grammar beyond the currently reviewed explicit
   numeric-threshold cohort routes; do not add generic formula guessing.
4. Complete independent dual annotation for the already sealed 120-QID
   reranker held-out packet, then run the one-shot paired A/B evaluator.
5. Recompute parser, retrieval, binding and answer metrics on that one sealed
   release. Promote only if every policy threshold passes; package/replay is
   already implemented and passing.
