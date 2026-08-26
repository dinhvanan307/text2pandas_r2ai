# Competition requirements traceability

Status date: 2026-08-26

Authoritative source: [`competition/Text2Pandas.docx`](competition/Text2Pandas.docx)

Source SHA-256: `45a8afcf228d12fe90af0ef4d7d163032b0b0d8003af724d8449e58e862e3081`

This matrix translates the competition brief into testable engineering
contracts. Page references use the rendered DOCX page number. A `PASS` applies
only to the stated evidence boundary; it never implies hidden-gold accuracy.

## Functional requirements

| ID | Requirement and source | Engineering contract | Acceptance evidence | Status |
|---|---|---|---|---|
| RQ-F01 | Retrieve the correct company, reporting period and relevant table (pp. 2-3) | Entity and period constraints are applied before ranking; every returned locator resolves to a real raw report table | Snapshot verification, retrieval evalkit, package locator validation | **PARTIAL**: 95 trusted local cases; macro F2@10 `0.3845` |
| RQ-F02 | Understand Vietnamese financial questions, including comparisons, multiple companies/years and derived metrics (p. 3) | Versioned semantic ontology; typed composable AST; no QID-specific production rules | Parser/AST tests, semantic coverage, V3 differential run | **PARTIAL**: V2 emits 559/1,012; V3 is shadow-only |
| RQ-F03 | Generate runnable Pandas code with correct logic, schema, period and unit (p. 3) | Restricted query grammar; typed unit conversion; clean replay must reproduce the packaged answer | Submission validator and isolated replay | **PARTIAL**: 559/559 emitted V2 queries replay; 453 questions abstain |
| RQ-F04 | Support multi-company, multi-year and derived calculations (p. 3) | Entity and period are AST axes; every operand is independently retrieved and jointly bound | Multi-entity/formula regression tests and gold-slice accuracy | **OPEN**: complex aggregation, filter/rank and select-at-arg remain incomplete |
| RQ-F05 | Return transparent source citations down to the input table (p. 3) | `relevant_docs`, `relevant_tables` and `evidence` are derived only from bound observations | Strict package validation against raw/A6 lineage | **PASS for emitted answers** |
| RQ-F06 | Avoid hallucinated values and nonexistent sources (p. 3) | Fail closed on unresolved semantics/binding; reject non-finite values, unknown locators and unreferenced evidence | Policy tests, package validation, typed/Pandas equality | **PASS for safety; PARTIAL for coverage** |

## Data and model constraints

| ID | Requirement and source | Engineering contract | Acceptance evidence | Status |
|---|---|---|---|---|
| RQ-C01 | Use the supplied reports and question file (pp. 6, 12) | `data/raw/btc` is immutable; A6 and retrieval indexes declare their source identities | Active snapshot manifest and checksum verification | **PASS** |
| RQ-C02 | No external data during processing (p. 4) | Production values and evidence come exclusively from the competition corpus | ADR 0009, source/network policy tests | **PASS for current runtime** |
| RQ-C03 | Only public open pretrained models, released before 2026-06-01 00:00 VN, at most 14B parameters (p. 4) | Every model artifact requires a manifest recording license, release timestamp, parameter count and digest before use | Model-compliance manifest gate | **PASS vacuously**: canonical runtime uses no model artifact; gate required before adding one |
| RQ-C04 | No closed LLM/API dependency (p. 4) | No production network inference or credential-dependent answer path | Dependency/source inspection and offline acceptance suite | **PASS** |
| RQ-C05 | Brief permits open/legal external datasets (p. 12), conflicting with p. 4 | Apply the stricter corpus-only interpretation until organisers clarify | ADR 0009 | **RESOLVED conservatively** |

## Evaluation requirements

| ID | Requirement and source | Engineering contract | Acceptance evidence | Status |
|---|---|---|---|---|
| RQ-E01 | Report macro retrieval Precision, Recall and F2 where `F2=5PR/(4P+R)` (p. 6) | Versioned eval config; macro metrics only over trusted gold; missing labels are `NOT_MEASURED` | Evalkit report | **PARTIAL**: measured on 95/1,012 local cases |
| RQ-E02 | Report Answer Accuracy within organiser tolerance (p. 6) | Score only against independent answer gold using declared tolerance | Official scorer or independent adjudicated gold | **NOT_MEASURED officially**; local adjudicated slice is 14/31 (45.16%) |
| RQ-E03 | Report Execution Accuracy as executable-and-correct over all questions (p. 6) | Separate syntax/replay success from answer correctness; denominator is all test questions | Replay plus independent/official answer gold | **NOT_MEASURED officially**; local adjudicated slice is 14/31 (45.16%), with 14/14 emitted replay |
| RQ-E04 | Evaluate all test questions (pp. 6-7) | Exactly one output record per source question ID and exact question text | Strict submission validator | **PASS**: 1,012/1,012 records |

## Submission requirements

| ID | Requirement and source | Engineering contract | Acceptance evidence | Status |
|---|---|---|---|---|
| RQ-S01 | One JSON at ZIP root, all data under root `data/` (pp. 6-7) | Reject extra root JSON, nested/unsafe paths, missing and orphan CSVs | ZIP contract tests and validator | **PASS** |
| RQ-S02 | Each record contains `id`, `question`, numeric `answer`, `relevant_docs`, `relevant_tables`, `evidence`, `pandas_query` (pp. 6-7) | Exact required schema, unique IDs and finite answers | Schema validation | **PASS** |
| RQ-S03 | Evidence contains `variable` and `csv_path`; paths start with `data/` (p. 7) | Unique Python identifiers; every referenced CSV exists and is replay-bound | Evidence and replay validation | **PASS** |
| RQ-S04 | Pandas code runs using packaged CSV evidence (pp. 6-7) | Execute in a restricted clean namespace and compare result with `answer` | Clean replay report | **PASS for 559 emitted queries; coverage remains PARTIAL** |

## Closure gates

The project is complete against the locally verifiable contract only when all
of the following hold on one immutable release candidate:

1. No `OPEN` functional requirement remains and every one of 1,012 questions
   has a grounded executable query; fail-closed behavior remains a safety
   fallback, not a submitted zero answer.
2. Retrieval/rerank promotion passes on an untouched held-out evidence-gold
   set with the competition macro metrics and no protected-slice regression.
3. Parser, binding, unit normalization and operation accuracy pass an
   independently adjudicated answer/evidence set covering every operation and
   company/report family.
4. The locked full suite, strict typing, package validation and clean replay
   pass with no unapproved skips.
5. Official Answer Accuracy and Execution Accuracy remain explicitly
   `NOT_MEASURED` until the organiser scorer is available. This external
   limitation cannot be converted into a local `PASS`.
