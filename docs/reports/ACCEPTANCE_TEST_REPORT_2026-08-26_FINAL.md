# Text2Pandas final acceptance test report

Status date: 2026-08-26

Test authority: [`../competition/Text2Pandas.docx`](../competition/Text2Pandas.docx)

Authority SHA-256: `45a8afcf228d12fe90af0ef4d7d163032b0b0d8003af724d8449e58e862e3081`

Frozen runtime source commit: `d604ddc500bc5471bfc103a6e25caa456aa61f9c`

Source tree at canonical and V3 test start: clean

## Executive verdict

**Overall: CONDITIONAL PASS — production-grade submission pipeline; competition
accuracy and full question coverage are not yet proven.**

- Raw/A6/retrieval lineage, output cardinality, schema, locator grounding,
  restricted Pandas execution, packaging and replay pass.
- Canonical V2 emits 559 grounded executable answers and fail-closes on 453 of
  1,012 questions. All 559 emitted queries replay exactly.
- On the independent local answer-gold slice, the engine emits 14 of 31
  evaluable cases; all 14 match gold and replay. Local Answer Accuracy and
  Execution Accuracy are therefore 14/31 (45.16%), while replay consistency on
  emitted cases is 14/14 (100%). This is not an official score.
- Semantic V3 remains correctly blocked: it emits 298 answers but disagrees in
  value with V2 on 137 cases and lacks promotion-grade independent gold.
- No unapproved skip, static typing error, package validation error or replay
  error is accepted by the tested gates.

The project must not be represented as “all 1,012 answers correct” or
“accuracy-proven”. The safe claim is: **validated, replayable and auditable
submission pipeline with measured coverage gaps**.

## Acceptance boundary

The suite verifies locally testable requirements and keeps four measurements
separate:

1. semantic route/parser coverage;
2. retrieval candidate/ranking quality;
3. executable/replay coverage;
4. answer correctness against independent gold.

Missing organiser gold is reported as `NOT_MEASURED`, never inferred from
replay or converted into a local pass.

## Requirement verdict

| ID | Requirement | Evidence | Verdict |
|---|---|---|---|
| RQ-F01 | Correct company, period and table retrieval | Active snapshot preflight; 95-case manual table gold; locator validation | **PARTIAL**: candidate hit 100%, F2@10 0.3845; gold covers 9.39% |
| RQ-F02 | Understand Vietnamese, comparisons, multiple entities/periods and derived metrics | 40-case semantic evaluation; 1,012-case route coverage; V3 AST tests | **PARTIAL**: stable core fields, 350 named route gaps |
| RQ-F03 | Runnable Pandas with correct logic/unit/period | Restricted AST validator; clean package replay; local answer gold | **PARTIAL**: 559/559 replay; 453 questions have no executable evidence |
| RQ-F04 | Multi-company/year and derived calculations | Typed entity/formula engines and regression tests | **OPEN**: filtered rank/select-at-arg and broad multi-entity composition remain incomplete |
| RQ-F05 | Transparent source citations | Bound observation IDs derive evidence, table locators and documents | **PASS for emitted answers** |
| RQ-F06 | No hallucinated values/sources | Fail-closed gates, finite-value checks, real-locator validation and replay | **PASS for safety; PARTIAL for coverage** |
| RQ-C01/C02 | Supplied corpus only | Raw/A6/retrieval checksums; corpus-only ADR and network policy | **PASS** |
| RQ-C03/C04 | Eligible open model only; no closed API dependency | Canonical model manifests are null; offline runtime | **PASS for current no-model runtime** |
| RQ-E01 | Macro retrieval P/R/F2 | Versioned 95-case evalkit report | **PARTIAL**: locally measured, not organiser gold |
| RQ-E02/E03 | Answer/Execution Accuracy | 31-case adjudicated local slice and official-scope declaration | **LOCAL 45.16%; OFFICIAL NOT_MEASURED** |
| RQ-E04 | Evaluate every test question | Exact 1,012-ID package contract | **PASS** |
| RQ-S01–S04 | ZIP/JSON/data/evidence/query contract | Strict package validator and clean replay | **PASS** |

## Environment and data lineage

Acceptance installation uses `requirements.lock --require-hashes` followed by
an editable `--no-deps` project install. Hosted CI and the materialized
self-hosted lane use the same sequence.

Frozen environment verification reports `lock_matches_installed=true`,
`lock_has_hashes=true`, no missing pins and no untracked source paths. The
machine-readable full-suite report is
`artifacts/reports/production-release-locked-20260826/full-suite/test_report.json`.

| Layer | Identity | Verified properties |
|---|---|---|
| Raw BTC | `ca033190f2e9e99f` | 1,973 reports, 1,012 questions, 100 tickers |
| A6 | `b3e9684004679ffb` | 14/24/40 runtime columns; 146,246 table cards |
| Retrieval | `286973b134a189ee` | Correct A6 parent, 4,240,060,416-byte DB, required indexes |

All active snapshot checks pass. No stage selects an implicit `latest` path.

## Automated gates

| Gate | Result |
|---|---:|
| Correctness-oriented Ruff | PASS |
| Strict production mypy | 0 errors / 77 modules |
| Documentation links | 44 tracked Markdown files / 0 broken links |
| Offline tests | 1,946 passed / 42 approved skips / 22 integration deselected |
| Materialized integration | 22 passed / 1 historical escape-sequence warning |
| Full collected suite | 2,010 tests |
| Unapproved skips | 0 |
| Snapshot lineage | PASS |

The 42 skips are exact historical-artifact monitors governed by ADR 0010 and
`configs/testing/approved_skips_v1.yaml`. A new skip, reason drift or count
increase fails the pytest session. They are not current acceptance criteria.

The integration warning originates in a historical H0 ZIP query containing a
legacy regex escape. The canonical package validator/replay path has zero
warnings and zero execution errors.

## Semantic parser evaluation

Fresh report:
`artifacts/reports/parser-final-v2-20260826/parser_vs_gold_summary.json`.
The report fingerprints the gold, worksheet and parser implementation and
refuses to overwrite an existing output directory.

The 40 records were produced by two independent model passes with disjoint
context, not a human-blinded review. Only fields on which the passes agreed are
scored.

| Field | Correct / scored | Accuracy |
|---|---:|---:|
| Operation family, strict | 40/40 | 100.0% |
| Basis and explicit-basis flag | 40/40 | 100.0% |
| Entity first / exact entity set | 39/40 | 97.5% |
| Period exact | 29/29 | 100.0% |
| Unit dimension / full unit | 40/40 | 100.0% |
| Result kind | 40/40 | 100.0% |

Metric exact match and operand-role exact match remain `NOT_MEASURED`: annotator
agreement is only 0.175 and 0.250. The set is below V3's 300-record threshold.

Static semantic route coverage is 662/1,012 (65.415%); 350 questions have a
named unsupported route. Route coverage is not answer accuracy.

## Retrieval and rerank evaluation

Artifact:
`artifacts/runs/retrieval/evalkit/metrics_acceptance_manual_20260826_184f3873addef66a.json`.

| Metric | 95 measured questions |
|---|---:|
| Candidate hit rate | 100.00% |
| Hit rate @10 | 90.53% |
| Macro recall @10 | 71.17% |
| Macro precision @10 | 21.26% |
| Competition macro F2 @10 | 38.45% |
| S2 MRR | 0.5506 |
| S3 truncated MRR | 0.5459 |
| Rank misses @10 | 9 |
| Hard-filter drops | 0 |

Only 95/1,012 questions have trusted table gold; 917 are `NOT_MEASURED`.
`screen` remains the weakest measured mode (`F2@10 = 0.2901`).

S3 is explicitly `IdentityReranker` plus truncation. It is not presented as a
quality uplift. The eval runner now passes actual post-rerank positions into
the failure taxonomy, so a future reranker can no longer hide
`F4_RERANK_MISS`. No learned/heuristic reranker is promoted without an untouched
held-out evidence set and protected-slice non-regression.

## Canonical full-corpus release candidate

Run ID: `production-release-20260826`

| Metric | Result |
|---|---:|
| Questions / records | 1,012 / 1,012 |
| Entity resolved | 1,011 (99.90%) |
| Period resolved | 1,011 (99.90%) |
| Retrieval non-empty | 1,011 (99.90%) |
| Executable answers | 559 (55.24%) |
| Fail-closed abstentions | 453 (44.76%) |
| Package validation | 0 errors / 0 warnings |
| Clean replay | 559 executed / 559 matched / 0 errors |
| Replay consistency | 100.00% of emitted answers |

Largest abstention families are multi-entity unsupported (195), unbound
operands (46), select-at-arg requiring two metrics (33), value unit mismatch
(29), unreviewed relational formula (27), cross-period metric drift (18) and
entity-difference metric drift (13).

The release artifact and its SHA-256 are recorded in the immutable
`submission_manifest.json` under the run directory. The manifest records the
frozen source commit, active snapshots, parameters, validation and replay.

## Independent local Answer/Execution Accuracy

Gold: `data/curated/dev-legacy/answer_gold/answer_gold_wave1_final.jsonl`

Gold SHA-256:
`e14248e8480afe783444eba70e824ad23184c78c4dee962a1f663d358f2ca3e2`

The pre-recheck validation report and post-recheck conservative merge report
are independently checksum-gated. Final population: 40 total records, 31
`OK`, 9 `GOLD_UNCERTAIN`; only the 31 `OK` records enter the denominator.

| Metric | Result |
|---|---:|
| Local Answer Accuracy | 14/31 = 45.16% |
| Local Execution Accuracy | 14/31 = 45.16% |
| Executable coverage on slice | 14/31 = 45.16% |
| Replay consistency among emitted | 14/14 = 100.00% |
| Emitted but answer-wrong | 0 |

Correct emitted families: 7 lookup, 6 ratio and 1 difference. The 17 abstained
gold cases are compound COUNT/filter/rank/select-at-arg/multi-entity queries.
This slice is independent local engineering evidence, not an organiser score
and not representative enough for a global accuracy claim.

## Semantic V3 shadow decision

Run ID: `semantic-v3-final-20260826`

| Metric | Result |
|---|---:|
| V3 OK / abstain | 298 / 714 |
| V2/V3 both OK and equal | 121 |
| Both OK, value differs | 137 |
| V3-only / V2-only OK | 40 / 301 |
| Runtime | 89.685 s |
| Promotion | `BLOCKED` |

The policy blocks seven missing measurements: promotion-grade semantic and
evidence gold counts, parser AST exactness, candidate recall, binding exactness,
answer accuracy and V3 submission errors. This is the expected fail-closed
decision. V2 output is not used as V3 gold.

## Remaining non-conformities

| ID | Severity | Gap | Required closure |
|---|---|---|---|
| NC-01 | Critical | Official Answer/Execution Accuracy unavailable | Obtain organiser score or an organiser-equivalent blind evaluation; retain `NOT_MEASURED` until then |
| NC-02 | Critical | 453/1,012 questions lack executable evidence | Implement typed predicate/rank/select-at-arg and broad multi-entity composition; validate on independent gold |
| NC-03 | High | S3 has no measured rerank uplift | Build untouched stratified evidence gold; compare deterministic/open-weight candidates and promote only a statistically defensible winner |
| NC-04 | High | V3 has 137 unadjudicated value differences and insufficient promotion gold | Adjudicate at least 300 semantic and 300 evidence records, then satisfy every locked threshold |
| NC-05 | High | Local evaluation sets are small | Expand table gold beyond 95, semantic gold beyond 40 and answer gold beyond 31 evaluable cases without tuning on the reporting slice |
| NC-06 | Medium | Historical V2 pipelines are outside the production mypy boundary | Continue strangler isolation; do not add new production behavior to legacy modules |
| NC-07 | Owner decision | Distribution license and CODEOWNERS are unspecified | Repository owner selects license and verified GitHub user/team; automation must not invent them |

## Release recommendation

- **Canonical ZIP:** approved as a structurally valid, grounded and replayable
  submission candidate. Score risk remains material because executable coverage
  is 55.24% and official accuracy is unknown.
- **Semantic V3:** shadow only; do not promote or package as canonical.
- **Production wording:** “production-grade pipeline and acceptance controls”
  is supported. “Complete solution for every question” and “accuracy proven”
  are not supported by current evidence.
