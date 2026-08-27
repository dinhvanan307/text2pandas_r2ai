# Quality 8+ closure report

Date: 2026-08-27

## Executive decision

The proposed engineering scope is complete: typed predicate/parser work,
fail-closed binding controls, independent-gold governance, learned reranker
governance, V3 evidence materialization, submission packaging, validation and
clean replay are implemented and tested.

Semantic V3 is still **BLOCKED from production promotion**. This is the correct
policy result, not unfinished code: independent human labels do not exist yet,
so parser, retrieval, binding and answer thresholds cannot be honestly measured.
Canonical V2 therefore remains the submission runtime and V3 remains shadow-only.

## Delivered outcome

| Workstream | Outcome | Acceptance evidence |
|---|---|---|
| Independent gold | Deterministic, prediction-blind 300-record selection; dual annotation; distinct adjudication; immutable sealing | Packet is `OPEN_FOR_INDEPENDENT_REVIEW`; sealer rejects identity reuse, incomplete labels, missing evidence review and model leakage |
| Predicate IR | Typed count/filter, quantified predicates, filtered cohorts, median, multi-entity aggregate and select-at-arg | Typed visitor and independent restricted-Pandas compiler tests |
| Parser | Explicit cue routing, scoped counterparty constraints, signed simultaneous count and closed select-at-arg grammar | No QID-specific production branch or generic formula guessing |
| Binding | Global coherent assignment, hard basis/context constraints and exact reviewed metric specificity | Ambiguous binding reduced from 169 to 108 |
| Safety | Two under-specified relational formulas quarantined; unsafe one-operand rank formulas rejected | Three known wrong diagnostic emissions removed; slice emitted precision 6/9 to 6/6 |
| Reranker | Deterministic learned linear S3, checksum-bound features/model/training data, untouched held-out protocol | Legacy-dev uplift measured; promotion remains blocked without held-out labels |
| Replay | V3 emits logical evidence, writes minimal CSVs, compiles restricted Pandas and clean-replays records | 269/269 r17 replay matches, zero errors/mismatches |
| Submission | V3-to-competition locator mapping, exact 1,012-record ZIP, strict corpus validation | Zero validation error/warning; package SHA recorded below |
| Promotion | One fail-closed policy covers independent release, parser, retrieval, binding, answer, reranker and replay | Missing metrics are `NOT_MEASURED` blockers, never implicit passes |

## Full-corpus Semantic V3 r17

Run: `semantic-v3-a6-v1.10-r17-20260827`, generated from clean commit
`4447c3679a34dcd9893f9233d579f75bba4be661` against A6 build
`c6887fb633374fad` and canonical V2 run
`production-a6-v1.10-v2-r5-20260827`.

| Metric | Result |
|---|---:|
| Questions | 1,012 |
| OK | 269 |
| Fail-closed abstention | 743 |
| Metric unresolved | 198 |
| Reported metric blocked for derived use | 149 |
| Ambiguous binding | 108 |
| Select-at-arg selected expression unresolved | 40 |
| Select-at-arg rank expression unresolved | 20 |
| Binary operands unresolved | 16 |
| Typed/Pandas mismatch | 0 |
| Both V2/V3 OK, equal | 157 |
| Both OK, value differs | 66 |
| V3 only OK | 46 |
| V2 only OK | 338 |

The 31-record local diagnostic slice gives 6/31 answer and execution accuracy
(19.35%), with 6/6 emitted answers correct and replayable. This is deliberately
reported as development evidence only. It does not satisfy independent-gold or
sample-size promotion gates.

## Submission and replay

| Gate | Result |
|---|---:|
| Submission records | 1,012/1,012 |
| Validation errors/warnings | 0/0 |
| Emitted queries replayed | 269/269 |
| Replay mismatches/errors | 0/0 |
| Fail-closed records with no evidence | 743 |
| Package SHA-256 | `dfe1544388e12fe7753ee2e4e0d45a6ac01a90c3b40bd0ac26b59a68b6959f10` |

## Reranker decision

On the contaminated legacy development split, learned S3 improves F2@10 from
0.3406 to 0.4231, MRR@10 from 0.5439 to 0.6391, and Hit@10 from 0.8421 to
0.9474. These figures prove implementation viability, not generalization.

The 120-question held-out selection is sealed and prediction-blind, but its
independent evidence labels are absent. The evaluator correctly returns
`BLOCKED`; learned S3 remains unpromoted.

## Verification matrix

| Gate | Result |
|---|---|
| Machine-readable full suite | PASS: 2,124 collected; 2,082 passed; 42 approved skips; 0 failed/error/xfailed/xpassed |
| Offline CI | PASS: Ruff critical rules; strict mypy 83 files; 48 Markdown files; 2,057 passed; 42 approved skips; 25 integration deselected |
| Materialized integration | PASS: 25 passed; 2,099 deselected |
| Active snapshots | PASS: raw 1,973 reports/1,012 questions/100 tickers; A6 146,246 cards; retrieval DB 4,239,663,104 bytes |
| V3 full replay | PASS: 269/269 |
| V3 package validation | PASS: 1,012 records, zero errors/warnings |
| Held-out reranker A/B | BLOCKED: independent evidence labels absent |

The 42 skips are exact allowlisted historical-artifact cases governed by
`configs/testing/approved_skips_v1.yaml`; any unapproved skip fails CI.

## Remaining external promotion blockers

1. Two independent annotators and one distinct adjudicator must complete the
   prepared 300-record answer/semantic/evidence packet.
2. The common sealed release must reach AST exact >= 0.95, candidate recall >=
   0.99, binding exact >= 0.90 and answer accuracy >= 0.80.
3. Independent evidence labels must be added to the sealed 120-question
   reranker cohort; the preregistered paired A/B gate must then pass.
4. Only after all metrics and the already-passing 1,012-record replay appear in
   one sealed promotion decision may V3 replace V2.

Therefore the accurate completion statement is: **100% of the proposed
engineering and verification mechanisms are delivered; production quality is
not yet independently certified and promotion remains fail-closed**.
