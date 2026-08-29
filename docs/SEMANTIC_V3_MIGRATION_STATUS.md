# Semantic Query Engine v3 migration status

Updated: 2026-08-29

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

The current no-prior run uses all 1,012 questions, A6 build
`c6887fb633374fad`, operand top-K 20, and canonical run
`production-a6-v1.10-v2-r5-20260827`.

| Metric | Result |
|---|---:|
| V3 OK | 362 |
| V3 abstain | 650 |
| Metric unresolved | 0 |
| Binding tie | 121 |
| Reported metric blocked for derived operation | 162 |
| Typed/Pandas replay mismatch | 0 |
| Both V2/V3 OK and equal | 212 |
| Both OK but value differs | 95 |
| V3-only OK | 55 |
| V2-only OK | 254 |
| Runtime | 100.477 s |

Artifact:
`artifacts/runs/semantic-v3/semantic-v3-hybrid-fe6667e-20260829-01/manifest.json`.

These are coverage and differential measurements, not accuracy. The 95 value
differences and 55 V3-only answers require independent adjudication before
promotion. On the existing 31-record diagnostic slice, this run emits 12 and
answers 9 correctly; all 12 replay consistently. Official execution accuracy
remains `NOT_MEASURED`.

The Canonical-table soft-prior experiment increases V3 OK from `362` to `396`
and reduces binding ties from `121` to `85`. Across the two V3 runs, 359 old OK
answers remain OK with identical values, 37 abstentions become OK and 3 old OK
answers become binding ties. Because the governed hybrid recovers fewer
Canonical abstentions with this experiment (`18` versus `21`) and local table
MRR5 is lower, the prior remains opt-in and is not selected for the candidate.

## Governed hybrid candidate

The artifact-level strangler composes immutable Canonical and Semantic runs
under `configs/semantic/hybrid_candidate_safe_v1.yaml`. It may recover a
Canonical abstention or reuse a replay-identical value; it cannot replace an
existing Canonical numeric answer. Missing binding margin fails closed.

On the current 585-answer Canonical control, the selected no-prior hybrid emits
606 answers, changes zero existing values and replays 606/606. Local diagnostic
answer/execution correctness is 15/31 versus 14/31 for Canonical. The policy and
source promotion manifest are both checked before publication; the candidate
is correctly blocked because the policy is experimental and the Semantic
source status is `BLOCKED`.

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
