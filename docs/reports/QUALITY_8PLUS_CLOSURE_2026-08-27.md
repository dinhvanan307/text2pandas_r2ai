# Quality 8+ closure report

Date: 2026-08-27

## Executive decision

The codebase is materially stronger, but Semantic V3 is **not promotable** and
the project must not be represented as independently proven 8+/10 yet. The
remaining blocker is evidence, not an unhandled exception: there is no sealed
independent answer/semantic/evidence gold release and the new 120-question
reranker held-out cohort is intentionally still unlabeled.

Canonical V2 remains production/submission runtime. V3 remains shadow-only.

## Delivered in this closure wave

| Workstream | Delivered outcome | Evidence |
|---|---|---|
| Independent gold | Registry validates checksum, independence, sealing and promotion eligibility separately | All tracked diagnostic assets are honestly marked `promotion_eligible_records: 0` |
| Predicate IR | `QuantifiedPredicate(ALL/ANY)`, filtered cohort projection, median, multi-entity aggregate and select-at-arg composition | Unit and materialized integration tests compare typed and restricted-Pandas execution |
| Parser | Closed explicit threshold-cohort grammar; V3-only ontology extensions checksum-bound to V2 | No QID-specific branch and no generic numerator/denominator guessing |
| Binding | Exact reviewed metric specificity, bounded exact-leaf ranking bonus and consolidated soft prior for unmarked basis | V3 ambiguity 169 to 109; explicit basis remains hard |
| Counterparty binding | Explicit `từ Công ty X của <subject>` becomes a hard context phrase, not a soft token bonus | Q503 no longer substitutes May Hòa Thọ/Vinatex/Nam Định for Coats Phong Phú |
| Abstention | V3 r7 emits 271/1,012 versus 207/1,012 at r3 | +64 safe answers; existing nine-answer diagnostic slice stays 6 match / 3 mismatch |
| Reranker | Real deterministic learned S3 with immutable feature order and checksum-bound model/training manifest | Model SHA `e60a8acea32989a2be37a89cd9cbfbb92b0b4f338ea2be9a299944075e6cebfd` |
| Held-out protocol | 120 QIDs excluded from all legacy gold, selected before training using deterministic hash, question-only blind packet | Packet SHA `cd1753b777ff7dce1778f22d274fd83c89f481642aded2fa4a30802e49f292d6` |
| Promotion | One policy requires parser, retrieval, binding, answer, reranker held-out and submission replay on a single sealed release | Missing metrics are blocking `NOT_MEASURED`, never pass/default zero |

## Full-corpus Semantic V3 r7

Run: `semantic-v3-a6-v1.10-r7-20260827` from clean commit `ae160762bdae41ef90dedce9d4d0ff92d0c2b630`.

| Metric | Result |
|---|---:|
| Questions | 1,012 |
| OK | 271 |
| Fail-closed abstention | 741 |
| Metric unresolved | 198 |
| Reported metric blocked for derived use | 141 |
| Ambiguous binding | 109 |
| Select-at-arg selected expression unresolved | 44 |
| Select-at-arg rank expression unresolved | 20 |
| Typed/Pandas mismatch | 0 |
| Both V2/V3 OK, equal | 157 |
| Both OK, value differs | 67 |
| V3 only OK | 47 |
| V2 only OK | 337 |

This is a coverage/differential result. It is not answer accuracy.

## Reranker evaluation

The legacy 95-record retrieval gold was used in earlier feature engineering,
so it is development evidence only. A deterministic 76/19 split produced:

| Metric on legacy dev19 | Identity S3 | Linear S3 | Delta |
|---|---:|---:|---:|
| F2@10 | 0.3406 | 0.4231 | +0.0825 |
| MRR@10 | 0.5439 | 0.6391 | +0.0952 |
| Hit@10 | 0.8421 | 0.9474 | +0.1053 |

The candidate is not promoted. `evaluate_reranker_heldout.py` currently returns
`BLOCKED` with reason `independent held-out labels are absent`. After dual annotation and independent
adjudication, the one-shot evaluator requires at least 100 records, non-negative
paired F2 delta, CI95 lower bound at least zero, and protected `single`/`compare`
slice delta no worse than -0.01.

## Test report

The final command matrix and exact counts are recorded below. No test result
substitutes for missing independent labels.

| Gate | Result |
|---|---|
| Machine-readable full suite | PASS: 2,105 collected; 2,063 passed; 42 approved skips; 0 failed/error/xfailed/xpassed |
| Offline CI | PASS: Ruff; mypy 81 files; 48 Markdown files; 2,038 tests passed, 42 approved skips, 25 integration deselected |
| Materialized integration | PASS: 25 tests, 2,080 deselected; one existing Python `SyntaxWarning` |
| Active snapshot verification | PASS: raw 1,973 reports/1,012 questions/100 tickers; A6 146,246 cards; retrieval DB 4,239,663,104 bytes |
| Held-out selection integrity | PASS: 120 records, packet checksum stable |
| Held-out A/B | BLOCKED: independent labels absent |
| Canonical V2 replay | Previous immutable run PASS: 561/561 |

## Promotion blockers

1. Answer gold: 31 usable diagnostic records, 0 independently promotion-eligible.
2. Semantic parser gold: 6 usable diagnostic records, 0 promotion-eligible.
3. Evidence/binding gold: tracked worksheet is blank, 0 usable.
4. Reranker held-out: 120 questions sealed, independent labels not yet supplied.
5. Consequently parser AST exactness, binding exactness and answer accuracy are
   `NOT_MEASURED` on one common sealed release.
6. V3 submission packaging/replay has not run over 1,012 records because V3 is
   not eligible to become the canonical submission engine.

## Required external work to claim 8+/10

- Two independent annotators label at least 300 answer, semantic and ordered
  evidence records; a separate adjudicator seals disagreements.
- The same release measures AST exact >= 0.95, candidate recall >= 0.99,
  binding exact >= 0.90 and answer accuracy >= 0.80.
- The sealed 120-QID reranker cohort is labeled without exposing model output
  on first pass, then evaluated once under the preregistered gates.
- A 1,012-record V3 submission candidate passes strict validation and replay
  with zero mismatch/error.

Until then, the professional decision is `BLOCKED`, not a fabricated 8+ score.
