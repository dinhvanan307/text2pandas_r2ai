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
| V3 OK | 272 |
| V3 abstain | 740 |
| Metric unresolved | 198 |
| Ambiguous binding | 109 |
| Reported metric blocked for derived operation | 141 |
| Typed/Pandas replay mismatch | 0 |
| Both V2/V3 OK and equal | 157 |
| Both OK but value differs | 67 |
| V3-only OK | 48 |
| V2-only OK | 337 |
| Runtime | 69.79 s |

Artifact: `artifacts/runs/semantic-v3/semantic-v3-a6-v1.10-r6-20260827/manifest.json`.

These are coverage and differential measurements, not accuracy. The 67 value
differences and 48 V3-only answers require independent adjudication before
promotion. On the existing diagnostic answer slice, r6 has 6 matches and 3
mismatches among nine emitted answers, unchanged from r3. External execution
accuracy remains `NOT_MEASURED`; all 272 returned answers passed internal
typed/Pandas equality.

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

## Remaining migration waves

1. Adjudicate at least 300 independent answer, semantic and evidence records,
   beginning with the 67 V2/V3 value differences and 48 `V3_ONLY_OK` cases.
2. Promote reported metrics to reviewed canonical metrics by family; derived
   operations remain blocked until promotion.
3. Extend the closed predicate grammar beyond the currently reviewed explicit
   numeric-threshold cohort routes; do not add generic formula guessing.
4. Complete independent dual annotation for the already sealed 120-QID
   reranker held-out packet, then run the one-shot paired A/B evaluator.
5. Run V3 submission packaging/replay in shadow, pass the promotion policy,
   then switch the canonical composition root and remove compatibility engines.
