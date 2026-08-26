# Acceptance test report: active A6 v1.10 production baseline

This report records the locally verifiable production baseline on 2026-08-27. The canonical V2 package is valid and replayable. A6 structure accuracy, official answer accuracy, official execution accuracy, and Semantic V3 promotion remain blocked or `NOT_MEASURED` where independent gold is unavailable.

## Decision summary

The repository is operational on one traceable raw to A6 to retrieval to answer lineage. The canonical V2 submission candidate passes schema validation and clean replay for every emitted answer. It remains a partial-coverage candidate, not proof of competition accuracy.

| Area | Status | Evidence |
|---|---|---|
| Repository and CI | PASS | 2,007 offline tests, 25 materialized tests, Ruff, strict mypy, docs links |
| Raw snapshot | PASS | 1,973 reports, 1,012 questions, 100 tickers |
| A6 deterministic rebuild | PASS | Two independent 6,775,554,048-byte databases have the same SHA-256 |
| A6 no-loss and readiness | PASS | C1 10/10; 2,634,120 observations reconcile 1:1 with readiness |
| A6 Structure Gold gates | BLOCKED | `SG`, `C2`, and `C3` require two independent reviewers |
| Retrieval candidate generation | PASS on measured slice | Candidate hit 95/95 manual-gold questions |
| Retrieval top-10 ranking | PARTIAL | Top-10 hit 86/95; 9 rank misses |
| Reranking | OPEN | S3 is an identity/truncation stage with no measured uplift |
| Parser route coverage | PARTIAL | 684/1,012 routes eligible; 328 named semantic gaps |
| Canonical V2 package | VALIDATED | 1,012 records; 574 answers; 574/574 replay; zero validator errors |
| Local V2 answer and execution accuracy | PARTIAL | 14/31, or 45.16%, on local adjudicated gold |
| Official answer and execution accuracy | NOT_MEASURED | Organiser-held gold and scorer are unavailable |
| Semantic V3 | BLOCKED | Shadow only; all required promotion metrics are not measured |

Production recommendation: retain V2 as canonical and V3 as shadow. Do not claim full production readiness or official accuracy. Do not promote a learned or deterministic reranker until held-out evidence gold proves uplift.

## Tested identity

Every runtime layer resolves from `configs/datasets/active_snapshot.yaml`.

| Layer | Identity | Artifact |
|---|---|---|
| Raw | dataset `vifinqa-btc-2026`; snapshot `ca033190f2e9e99f` | `data/raw/btc/manifest.json` |
| A6 | build `c6887fb633374fad` | `data/processed/a6/c6887fb633374fad/manifest.json` |
| Retrieval | index `872ccb0dda9a2bb6` | `data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/manifest.json` |
| Canonical run | `production-a6-v1.10-v2-r3-20260827` | `artifacts/runs/answer/production-a6-v1.10-v2-r3-20260827/manifest.json` |
| V3 shadow run | `semantic-v3-a6-v1.10-r2-20260827` | `artifacts/runs/semantic-v3/semantic-v3-a6-v1.10-r2-20260827/manifest.json` |

The canonical and shadow runs used source commit `c3ff084ef55c566c74758792f1810cc24f46ec15` with `git_dirty=false`.

## A6 acceptance

### Determinism and lineage

Two clean A6 v1.10 builds produced build ID `c6887fb633374fad`. Both working databases contain 2,634,120 observations and match byte-for-byte.

| Check | Result |
|---|---:|
| Build A bytes | 6,775,554,048 |
| Build B bytes | 6,775,554,048 |
| Build A SHA-256 | `56799c0189734d5386c40215876ec17099616944e37823e240eed36696a92eb6` |
| Build B SHA-256 | `56799c0189734d5386c40215876ec17099616944e37823e240eed36696a92eb6` |
| Logical tables compared | 11 |
| C0-final | PASS |

The valid v1.9 to v1.10 differential changed exactly three observations. Every change is `scale_exponent`, every reason is `scale_reconciled`, and the audit reports zero added rows, removed rows, UID instability, unexplained changes, or out-of-contract field changes.

### Data quality and readiness

| Gate | Result |
|---|---:|
| C1 no-loss checks | 10/10 PASS |
| Unicode digit mismatch | 0 |
| Observations | 2,634,120 |
| Readiness rows | 2,634,120 |
| Ready observations | 1,817,629 |
| Ready rows with a blocking reason | 0 |
| Quality checks | 39/39 PASS |
| Acceptance replay fixtures | 10/10 PASS |

The release gate summary is `C0 PASS`, `C1 PASS`, `C4 PASS`, and `C5 PASS`. `SG`, `C2`, and `C3` remain `BLOCKED`. Their exact-accuracy metrics require Structure Gold with two independent reviewers and at least 90% overlap agreement. This report does not convert missing review evidence into `PASS`.

### Release reproducibility

Two deterministic A6 release packages produced the same digest:

```text
d68ccb89970f6e439d16aaebe9cbcdbcb5963bf989c850b4d91dba36b37c5205
```

Both clean-room verifications passed with 16,588 archive members, 16,587 checksum rows, zero missing members, zero unexpected members, and matching manifest/build metadata.

## Retrieval and rerank acceptance

The active retrieval snapshot is immutable and bound to A6 build `c6887fb633374fad`.

| Property | Value |
|---|---:|
| Database bytes | 4,239,663,104 |
| Database SHA-256 | `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf` |
| Documents | 1,973 |
| Tables and table cards | 146,246 |
| Observations | 2,634,120 |
| Required indexes | 4/4 present |
| SQLite quick check | `ok` |

Evalkit schema `evalkit-9` ran all 1,012 questions with config fingerprint `9c5a36f7f0f09fee`. Manual gold measures 95 questions. The remaining 917 questions are `NOT_MEASURED`, not retrieval successes. The schema bump invalidates older checkpoints after comparison entities began preserving question-source order.

| Metric | Result |
|---|---:|
| Manual-gold coverage | 95/1,012, or 9.39% |
| S1 candidate hit | 95/95, or 1.0000 |
| Top-1 hit | 33/95, or 0.3474 |
| Top-10 hit | 86/95, or 0.9053 |
| Top-10 macro recall | 0.7117 |
| Top-10 macro precision | 0.2126 |
| Top-10 macro F2 | 0.3845 |
| Top-10 nDCG | 0.5516 |
| Rank misses | 9 |

S3 uses `IdentityReranker`. S2 MRR@10 and S3 MRR@10 both equal 0.5450, so measured uplift is `+0.0000`. S2 full-list MRR is 0.5497 over top-50; it remains a diagnostic and is not compared with S3 top-10.

The nine top-10 misses are q374, q376, q385, q397, q436, q542, q723, q767, and q975. Screen mode is the weakest measured slice: top-10 hit 23/29, or 0.7931.

## Parser and semantic acceptance

`make semantic-coverage` classified all 1,012 questions against corpus digest `59effd1ee7cf7214caee430b05b9305f5a71ed3fd57ba19eb1a6ff2f9c3ffa5d`.

| Metric | Result |
|---|---:|
| Route eligible | 684/1,012, or 67.59% |
| Named gaps | 328/1,012, or 32.41% |
| Lookup operations | 426 |
| Extrema operations | 238 |
| Subtract operations | 136 |
| Average operations | 98 |
| Divide operations | 54 |
| Growth operations | 33 |
| Count operations | 23 |
| Sum operations | 4 |

The largest route-level gap is multi-entity semantics. The current classifier records 248 multi-entity unsupported/mismatch cases, 32 select-at-arg cases, 23 unreviewed divide formulas, 11 outer formula composition cases, and 8 period/operand arity cases. Route coverage is not parser exact match and is not answer accuracy.

## Canonical V2 acceptance

The canonical run completed all 1,012 questions in 685.86s.

| Metric | Result |
|---|---:|
| Questions | 1,012 |
| Entity/year/retrieval coverage | 1,011/1,012 |
| Emitted answers | 574, or 56.72% |
| Fail-closed abstentions | 438, or 43.28% |
| Validator errors | 0 |
| Validator warnings | 0 |
| Clean replay executed | 574 |
| Clean replay matched | 574 |
| Clean replay errors | 0 |

The published submission ZIP is `artifacts/submissions/submission_production-a6-v1.10-v2-r3-20260827.zip`, with SHA-256 `8d56dc96766e3311a2672969d9cf723eb00d06509afe19712aae92b88b1fccc1`.

The largest abstention families are multi-entity operation unsupported (180), unbound operands (40), select-at-arg requiring two metrics (32), value unit dimension mismatch (31), unreviewed divide formulas (27), and formula outer extrema (19). These abstentions preserve safety but prevent full functional coverage. Directional entity subtraction now preserves mention order and explicitly reverses `kém/thấp/bé hơn`; the prior lexical-order behavior was invalidated rather than normalized with `abs`.

The local adjudicated answer set contains 40 records, of which 31 are evaluable. V2 emits 14 correct and executable answers on this denominator. Local Answer Accuracy and Execution Accuracy are both 14/31, or 45.16%. Replay consistency among those 14 emitted answers is 100%. This slice is not the organiser test gold.

## Semantic V3 shadow acceptance

V3 processed all 1,012 questions in 62.39s and returned 207 answers. Every returned answer passed internal typed/Pandas equality. The shadow run does not produce a publishable submission package.

| Metric | Result |
|---|---:|
| V3 OK | 207 |
| V3 abstain | 805 |
| Both V2/V3 OK and equal | 104 |
| Both OK with value difference | 73 |
| V3-only OK | 30 |
| V2-only OK | 397 |
| Typed/Pandas mismatch | 0 |

The top V3 blockers are unresolved metrics (198), ambiguous binding (169), and reported metrics requiring review before derived operations (143). Local answer gold measures 6/31 correct answers. External execution accuracy remains `NOT_MEASURED` because V3 shadow records do not materialize the evidence contract consumed by the external evaluator.

Promotion policy status is `BLOCKED`. The run lacks the minimum 300 semantic-gold records, 300 evidence-gold records, parser AST exact match, candidate recall, binding exact match, answer accuracy, and submission error metric.

## Test suite evidence

The locked Python environment is `/private/tmp/text2pandas-acceptance-venv.eC3DqF/venv`. Commands used `PYTHONPATH=src` or the Makefile equivalent.

| Command | Result |
|---|---|
| `make ci` | PASS: Ruff; strict mypy on 78 files; 46 Markdown files and zero broken links; 2,007 passed, 42 approved skips, 25 integration tests deselected |
| `make test-integration` | PASS: 25 passed, 2,049 deselected |
| `make dp-test REPORT_DIR=artifacts/reports/production-final-r3-20260827` | PASS: 2,074 collected; 2,032 passed; 42 approved skips; zero failures, errors, xfails, or xpasses |
| `make semantic-coverage` | PASS: 1,012 classified; 684 eligible; 328 gaps |
| `make snapshots-verify` | PASS: every raw, A6, retrieval identity, schema, count, size, and index check |
| Evalkit manual-gold full corpus | PASS: 1,012 checkpoint rows under one config and snapshot fingerprint |

One integration replay of the immutable historical `submission_C1R_LOCAL.zip` emits a Python `SyntaxWarning` for q766 because that legacy query embeds LaTeX `\(` without repr escaping. The active V2 submission compiles all 574 queries with zero syntax warnings. The warning is historical fixture debt, not active output behavior.

## Requirements closure and remaining work

The following work remains before a full production-ready claim:

1. Build Structure Gold v1 with two independent reviewers. Re-run `SG`, `C2`, and `C3` exact-accuracy gates.
2. Expand stratified manual evidence gold beyond 95 questions. Include screen, bank, multi-entity, derived metric, and hard-negative slices.
3. Replace identity reranking only after held-out A/B evaluation proves statistically meaningful top-K uplift without protected-slice regression.
4. Implement multi-entity and select-at-arg semantics in the typed intermediate representation. Preserve one-fact-per-entity and exact evidence contracts.
5. Expand independent answer/evidence gold across every operation. Re-measure parser exactness, binding exactness, Answer Accuracy, and Execution Accuracy.
6. Materialize V3 evidence and submission validation in shadow before any promotion review.
7. Obtain organiser-held gold or run the official scorer. Until then, official Answer Accuracy and Execution Accuracy remain `NOT_MEASURED`.

## Evidence index

- A6 acceptance: `artifacts/acceptance/a6-c6887fb633374fad-20260826/`
- Final A6 release: `artifacts/releases/a6-c6887fb633374fad-final-20260826/`
- Deterministic packages: `artifacts/packages/a6-c6887fb633374fad-20260826/`
- Retrieval metrics: `artifacts/runs/retrieval/evalkit/metrics_a6-v1.10-manual-evalkit9-20260827_9c5a36f7f0f09fee.json`
- Canonical run: `artifacts/runs/answer/production-a6-v1.10-v2-r3-20260827/`
- Canonical local evaluation: `artifacts/reports/answer/adjudicated-production-a6-v1.10-v2-r3-20260827.json`
- V3 shadow run: `artifacts/runs/semantic-v3/semantic-v3-a6-v1.10-r2-20260827/`
- V3 local evaluation: `artifacts/reports/semantic-v3/adjudicated-semantic-v3-a6-v1.10-r2-20260827.json`
- Machine-readable full test report: `artifacts/reports/production-final-r3-20260827/test_report.json`
