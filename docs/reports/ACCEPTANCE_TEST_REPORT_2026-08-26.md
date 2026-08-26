# Text2Pandas acceptance test report

Status date: 2026-08-26

Test authority: `docs/competition/Text2Pandas.docx`

Authority SHA-256: `45a8afcf228d12fe90af0ef4d7d163032b0b0d8003af724d8449e58e862e3081`

Source commit: `a7bbd21207ab441a4913875e33716560962e452e`

Source tree at test start: clean

## Executive verdict

**Overall: CONDITIONAL PASS — submission-contract ready, score readiness not proven.**

- The canonical V2 candidate passes data lineage, submission schema, grounding,
  clean pandas replay and full-corpus packaging gates.
- Every executable automated test passed in a clean, hash-locked environment.
- The project must not be described as fully production-ready or accuracy-proven:
  official Answer Accuracy and Execution Accuracy require organiser-held answer
  gold, which is not available locally.
- Canonical V2 answers 511/1,012 questions and abstains on 501. Its executable
  coverage is therefore 50.49%, even though replay consistency on the 511
  executed queries is 100%.
- Semantic V3 remains a shadow engine and is correctly blocked from promotion.

## Scope and methodology

The test plan traces the competition requirements to executable evidence:

1. Verify the immutable `raw -> A6 -> retrieval index` lineage.
2. Recreate a clean Python environment from `requirements.lock` using
   `--require-hashes` and run the complete automated suite.
3. Evaluate the Vietnamese parser on the available independently annotated
   semantic set.
4. Recollect retrieval results for all 1,012 questions and score the 95 cases
   with local manual table gold.
5. Run the canonical V2 engine on all 1,012 questions, build the actual ZIP,
   validate every record/locator/path, and replay every generated pandas query.
6. Run Semantic V3 on all 1,012 questions in shadow mode and compare it with the
   newly generated canonical run.
7. Separate coverage, replay consistency and local-gold metrics from official
   hidden-gold accuracy. Missing gold is reported as `NOT MEASURED`, never as a
   pass or zero.

## Requirement traceability

| ID | Competition requirement | Executable evidence | Verdict |
|---|---|---|---|
| R01 | Retrieve the correct company, year and relevant financial tables | Snapshot verifier; full canonical run; 95-case manual retrieval evaluation | **PARTIAL** — pipeline coverage is high, but local table gold covers only 9.39% of questions |
| R02 | Understand Vietnamese financial questions, comparisons, multiple companies/years and derived metrics | 40-case semantic gold evaluation; parser/AST unit tests; semantic route coverage | **PARTIAL** — core parser fields score strongly, but metric/operand gold is unreliable and multi-entity execution remains incomplete |
| R03 | Generate runnable pandas code with correct logic/schema/unit/period | Full ZIP validator; restricted-query safety checks; clean replay | **CONDITIONAL PASS** — 511/511 generated queries replay, but only 511/1,012 questions contain executable evidence |
| R04 | Provide transparent company/report/table/position grounding | Strict document and locator validation; evidence-path validation; relevant-doc derivation | **PASS** for all emitted answers |
| R05 | Avoid hallucinated numbers and nonexistent sources | Fail-closed abstention; finite-number validation; real document/locator checks; typed/pandas equality in V3 | **PASS for safety**, **PARTIAL for usefulness** because 501 canonical questions abstain |
| R06 | Report retrieval Precision/Recall/F2, Answer Accuracy and Execution Accuracy | Evalkit manual-gold report; canonical replay manifest | **PARTIAL** — retrieval is locally measured; official answer/execution correctness is not measurable without organiser gold |
| R07 | Submit exactly one JSON plus referenced CSV files under `data/` in a ZIP | Full submission builder and strict validator | **PASS** |
| R08 | Reproducible use of supplied data and permitted runtime | Hash-locked clean environment; snapshot identities; source inspection for network/closed-LLM clients | **PASS** for the tested runtime |

## Environment and reproducibility

Clean acceptance environment:

| Item | Value |
|---|---|
| OS | Darwin 25.5.0 arm64 |
| Python | 3.13.13 |
| SQLite | 3.51.2 |
| pandas | 2.3.3 |
| pyarrow | 25.0.0 |
| PyYAML | 6.0.3 |
| pytest | 9.1.1 |
| Lock pins / hashes | 23 / 781 |
| `lock_matches_installed` | `true` |
| `lock_covers_imports` | `true` |
| Source hash | `ba60fe8813076541` |
| Config hash | `d100aaffa5755c01` |
| Corpus structural hash | `69236b829d53c8e6` |

The developer `.venv` was also tested but did not exactly match the lock. It is
not the environment used for the acceptance verdict.

## Data lineage and integrity

| Layer | Active identity | Verification result |
|---|---|---|
| Raw BTC | `ca033190f2e9e99f` | PASS: 1,973 reports, 1,012 unique question IDs, 100 tickers, years 2015–2025 |
| A6 processed | `b3e9684004679ffb` | PASS: runtime schema 14/24/40 columns and 146,246 table cards |
| Retrieval index | `286973b134a189ee` | PASS: source A6 identity matches, DB size 4,240,060,416 bytes, required SQLite indexes present |

The deep raw dataset-card audit passed 13/13 checks with zero errors and zero
warnings.

## Automated test suite

Machine-readable outputs:

- `artifacts/reports/acceptance-20260826/frozen-full-suite/test_report.json`
- `artifacts/reports/acceptance-20260826/frozen-full-suite/junit.xml`
- `artifacts/reports/acceptance-20260826/frozen-full-suite/test_report.txt`

| Gate | Result |
|---|---:|
| Collected | 1,967 |
| Passed | 1,925 |
| Failed | 0 |
| Errors / collection errors | 0 / 0 |
| Skipped | 42 |
| Dependency-related skips | 0 |
| Missing mandatory suite names | 0 |
| Critical Ruff gate | PASS |
| Targeted Semantic V3 suite | 31/31 PASS |

The 42 skips are not hidden. They require legacy external acceptance artifacts
that are absent from this workspace: 27 answer-operation precheck cases, 4
replay-report cases, 4 RC1 build-DB cases, 3 runbook cases, 2 readiness-DB
cases, 1 corpus-freeze manifest case and 1 snapshot declaration case. They do
not indicate missing dependencies, but they reduce legacy acceptance coverage.

### Static typing

Strict mypy in the clean locked environment reported **43 errors in 9 legacy
V2 files** transitively imported by the V3 language adapter. The affected areas
are unit conversion, unit lexicon, result-kind, IR, legacy binding, frame,
policy, render and legacy answering pipeline. This is a real engineering gap;
functional test success does not override it.

## Vietnamese parser evaluation

Source: 40 semantic cases produced by two independent model annotation passes
with disjoint context. This is not human-blinded gold, and only fields on which
the passes agreed are scored.

| Field | Correct / scored | Accuracy |
|---|---:|---:|
| Operation family, strict | 40/40 | 100.0% |
| Basis / explicit-basis flag | 40/40 | 100.0% |
| Entity first / entity set | 39/40 | 97.5% |
| Period exact | 29/29 | 100.0% |
| Unit dimension / full unit | 40/40 | 100.0% |
| Result kind | 40/40 | 100.0% |

Metric exact match and operand-role exact match are not reported because
annotator agreement is only 0.175 and 0.250 respectively. The current set also
falls below the V3 promotion minimum of 300 semantic-gold records.

## Retrieval and rerank evaluation

Artifact:
`artifacts/runs/retrieval/evalkit/metrics_acceptance_manual_20260826_184f3873addef66a.json`

The engine ran all 1,012 questions. Only 95 have trusted local manual table
gold, so metric coverage is 9.39%; 917 questions are `NOT MEASURED`.

| Metric | Result on 95 measured questions |
|---|---:|
| Candidate hit rate | 100.00% (95/95) |
| Hit rate @10 | 90.53% |
| Macro recall @10 | 71.17% |
| Macro precision @10 | 21.26% |
| Competition-formula macro F2 @10 | 38.45% |
| S2 MRR | 0.5506 |
| S3 MRR | 0.5459 |
| Rank misses @10 | 9 |
| Hard-filter drops | 0 |
| Rerank misses | 0 |

The current S3 implementation is an `IdentityReranker` followed by truncation.
It provides no measured ranking uplift. The small MRR reduction is caused by
the top-K boundary rather than learned or cross-encoder reranking. A real
reranker must not be promoted until it beats this deterministic baseline on a
held-out, sufficiently large evidence-gold set.

The weakest measured mode is `screen` (`F2@10 = 0.2901`, 29 measured cases).

## Canonical V2 full-corpus acceptance run

Run ID: `acceptance-v2-20260826`

| Metric | Result |
|---|---:|
| Questions / output records | 1,012 / 1,012 |
| Entity resolved | 1,011 (99.90%) |
| Year resolved | 1,011 (99.90%) |
| At least one table retrieved | 1,011 (99.90%) |
| Answered with evidence/query | 511 (50.49%) |
| Fail-closed abstentions | 501 (49.51%) |
| Runtime | 745.6 s |
| Submission validation | 0 errors, 0 warnings |
| Clean replay | 511 executed, 511 matched, 0 errors |
| Replay consistency on executed queries | 100.00% |
| Executable coverage over all questions | 50.49% |

Largest abstention causes:

| Cause | Count |
|---|---:|
| Multi-entity operation unsupported | 195 |
| Unbound operands | 89 |
| Select-at-arg requires two metrics | 33 |
| Divide requires reviewed formula | 30 |
| Money/percent unit mismatch | 27 |
| Cross-period metric drift | 19 |
| Entity-difference metric drift | 15 |

Submission artifact:

| Item | Value |
|---|---|
| ZIP | `artifacts/submissions/submission_acceptance-v2-20260826.zip` |
| Size | 926,463 bytes |
| Members | 792 |
| SHA-256 | `9299986b0c50531a6b744e8fb8cd24974f400e9408d0337ddd70bcbc9347dae2` |
| JSON records | 1,012 |
| Status | `VALIDATED` |

Replay consistency proves `answer == eval(pandas_query)` for emitted queries.
It does not prove that the selected tables, operands or values match organiser
gold. Therefore official Answer Accuracy and Execution Accuracy remain
`NOT MEASURED`.

## Semantic V3 full shadow run

Run ID: `acceptance-v3-final-20260826`

| Metric | Result |
|---|---:|
| Questions | 1,012 |
| V3 OK | 285 |
| V3 abstain | 727 |
| Accepted typed/pandas mismatches | 0 |
| Runtime | 87.01 s |
| V2/V3 both OK and equal | 103 |
| V2/V3 both OK but different value | 126 |
| V3-only OK | 56 |
| V2-only OK | 282 |
| Promotion | `BLOCKED` |

The 126 value differences require independent evidence adjudication. V2 cannot
be used as V3 gold because that would create circular validation.

Promotion blockers are missing semantic/evidence gold, AST exact match,
candidate recall, binding exact match, answer accuracy and V3 submission error
measurement. The block is expected and confirms that the governance layer
fails closed.

## Submission contract checks

The generated ZIP passed all tested competition constraints:

- exactly one JSON file at archive root;
- all other members are CSV files directly under `data/`;
- 1,012 unique integer IDs with exact source question text;
- finite numeric answers;
- evidence variables are unique valid Python identifiers;
- every `csv_path` starts with `data/` and exists in the ZIP;
- no orphan CSV, duplicate archive member or unsafe path;
- `relevant_docs` is derived exactly from `relevant_tables`;
- every document exists and every locator points to a real table opening line;
- every non-empty query passes the restricted pandas safety validator;
- all 511 non-empty queries run and reproduce their packaged answer.

## Open non-conformities and required actions

| ID | Severity | Non-conformity | Required closure |
|---|---|---|---|
| NC-01 | Critical | Official Answer Accuracy and Execution Accuracy are unknown | Obtain organiser scoring or build independent adjudicated answer/evidence gold; never infer accuracy from replay |
| NC-02 | Critical | Canonical executable coverage is 50.49% | Close multi-entity, binding, reviewed-formula, select-at-arg and unit-policy gaps using measured gold |
| NC-03 | High | S3 reranker is identity/truncation and shows no uplift | Establish held-out rerank gold, train/evaluate candidate models, promote only on statistically defensible improvement |
| NC-04 | High | Semantic/evidence gold is below promotion minimum; V3 has 126 value disagreements | Adjudicate at least 300 semantic and 300 evidence cases, prioritising all V2/V3 disagreements and V3-only answers |
| NC-05 | Medium | Strict mypy reports 43 errors in legacy V2 transitive modules | Type legacy adapter dependencies or isolate them behind fully typed ports; rerun mypy with no incremental cache |
| NC-06 | Medium | 42 legacy tests skip because acceptance artifacts are absent | Materialise and checksum required artifacts or retire obsolete suites with an approved ADR |
| NC-07 | Medium | Local retrieval gold covers only 95/1,012 questions | Expand stratified evidence gold, especially `screen`, multi-entity, bank and derived-metric slices |

## Release recommendation

- **V2 ZIP:** acceptable as a structurally valid submission candidate. Expected
  score risk remains high because 49.51% of questions abstain and hidden-gold
  correctness is unknown.
- **V3:** continue shadow only. Do not switch the canonical composition root or
  package V3 for production until the locked promotion policy passes.
- **Production claim:** use “validated/replayable submission pipeline”, not
  “accuracy-proven production system”, until NC-01 through NC-04 are closed.
