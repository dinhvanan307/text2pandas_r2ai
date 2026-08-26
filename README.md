# Text2Pandas

Text2Pandas converts Vietnamese financial questions into grounded Pandas queries over listed-company financial reports. The repository contains the data pipeline, retrieval system, semantic parser, typed execution engine, evidence packaging, and production validation gates.

## Project status

The project uses a strangler migration. Canonical V2 remains the submission engine while Semantic V3 runs in shadow mode.

| Runtime | Current state | Latest full-corpus result |
|---|---|---:|
| Canonical V2 | Validated submission candidate | 566 answers and 446 fail-closed abstentions |
| Semantic V3 | Shadow only; promotion blocked | 206 answers and 806 fail-closed abstentions |

The latest acceptance run validated all 1,012 output records and replayed 566 of 566 emitted Pandas queries. On the independently adjudicated local slice, 14 of 31 answers are correct and executable (45.16% local Answer and Execution Accuracy; 100% replay consistency among emitted answers). Official Answer Accuracy and Execution Accuracy remain `NOT_MEASURED` because organiser-held gold is unavailable.

Read the [current acceptance report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md) before making a production-readiness claim.

## System architecture

The runtime preserves a traceable path from source reports to the submitted answer:

```text
Vietnamese question
        |
        v
semantic parsing -> operand planning -> retrieval -> joint binding
        |                                              |
        +---------------- typed execution <------------+
                               |
                               v
                    Pandas compilation and replay
                               |
                               v
                    evidence and submission ZIP
```

The data lineage remains independent from runtime code:

```text
data/raw/btc
    -> data/processed/a6/build_id
    -> data/indexes/retrieval/a6_build_id/index_id
    -> artifacts/runs/answer/run_id
    -> artifacts/submissions/submission_run_id.zip
```

Each layer records the identity of its source. The runtime never selects an implicit `latest` directory.

## Repository capabilities

- Parse Vietnamese entities, periods, bases, units, operations, and financial formulas
- Normalize source tables into A6 documents, tables, observations, and table cards
- Retrieve tables with lexical and structural signals
- Plan independent operands and bind them under global coherence constraints
- Execute typed decimal expressions with unit validation
- Compile restricted Pandas queries and replay them in a clean environment
- Derive documents, table locators, and CSV evidence from selected observations
- Validate the exact JSON and ZIP submission contract
- Compare Semantic V3 with canonical V2 without promoting unmeasured behavior

## Prerequisites

Use Python 3.11 or newer. A full A6 rebuild requires at least 40 GB of free disk space. Offline development tests do not require materialized raw, A6, or retrieval payloads.

The repository stores large runtime payloads outside Git. Materialized integration tests require the active paths declared in `configs/datasets/active_snapshot.yaml`.

## Install a reproducible environment

Use the hash-locked environment for acceptance and release work:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
make dp-env-check
```

The environment check must report `lock_matches_installed=True`, `lock_has_hashes=True`, and no untracked source paths.

For local feature development, install the project and development extras:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

This development path is not a frozen acceptance environment.

## Verify the active data lineage

The active snapshot config is the only source of runtime data identities:

| Layer | Active identity | Canonical path |
|---|---|---|
| Raw BTC | `ca033190f2e9e99f` | `data/raw/btc/` |
| A6 processed | `c6887fb633374fad` | `data/processed/a6/c6887fb633374fad/` |
| Retrieval index | `872ccb0dda9a2bb6` | `data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/` |

Run all lineage checks:

```bash
make paths-check
make snapshots-verify
python tools/data_acquisition/download_vifinqa.py --verify-only --skip-github
```

The active dataset contains 1,973 financial reports, 1,012 questions, and 100 tickers. The active A6 build contains 146,246 table cards.

You can mount data and generated artifacts outside the repository:

```bash
export T2P_DATA_ROOT=/srv/text2pandas/data
export T2P_ARTIFACT_ROOT=/srv/text2pandas/artifacts
```

## Run the canonical engine

Every run ID is immutable. Use a new ID for every attempt.

Run a ten-question smoke test without packaging:

```bash
text2pandas run \
  --run-id local_smoke_001 \
  --offset 0 \
  --limit 10 \
  --no-package
```

Run all questions and build a submission candidate:

```bash
text2pandas run --run-id submission_candidate_001
```

The command publishes a ZIP only when strict validation and clean replay pass. Failed stages remain under `artifacts/runs/answer/` for investigation.

## Run Semantic V3 in shadow mode

V3 writes an immutable differential run and never changes the canonical output:

```bash
text2pandas shadow-v3 \
  --run-id semantic_v3_shadow_001 \
  --operand-k 20 \
  --legacy-run-id submission_candidate_001
```

The manifest records the ontology fingerprint, differential taxonomy, replay status, and promotion decision. `configs/semantic/promotion_policy_v3.yaml` blocks promotion when required metrics are absent.

## Test the project

Use the gate that matches the changed scope:

| Gate | Command | Purpose |
|---|---|---|
| Critical static checks | `make lint` | Syntax, import, and undefined-name failures |
| Offline CI | `make ci` | Static checks plus unit, contract, and regression tests |
| Materialized integration | `make test-integration` | Raw, A6, retrieval, H0, submission, and replay contracts |
| Semantic route coverage | `make semantic-coverage` | Classify all 1,012 questions; not an accuracy metric |
| Machine-readable full suite | `make dp-test REPORT_DIR=artifacts/reports/local_test_001` | JSON, text, and JUnit reports |

Run offline and integration suites separately when you need explicit counts:

```bash
make test-offline
make test-integration
git diff --check
```

Strict mypy is enforced on all production architecture modules under `domain`, `application`, `infrastructure`, and `interface`; the current gate checks 78 source files with zero errors. Historical V2 pipeline modules remain outside this typed boundary and are governed as migration debt.

## Evaluate retrieval and ranking

Retrieval evaluation separates candidate generation, ranking, and reranking. It reports `NOT_MEASURED` for questions without trusted gold.

Collect and report a versioned manual-gold checkpoint:

```bash
python -m text2pandas.pipelines.retrieval.evalkit.cli collect \
  --tag local_manual_001 \
  --gold-source manual \
  --loop

python -m text2pandas.pipelines.retrieval.evalkit.cli report \
  --tag local_manual_001 \
  --gold-source manual
```

Do not compare checkpoints with different config fingerprints or evaluation schemas.

## Submission contract

A publishable package contains one JSON file at the root and referenced CSV files under `data/`:

```text
submission.zip
|-- submission.json
`-- data/
    |-- table_001.csv
    `-- table_002.csv
```

Every record contains these fields:

- `id`
- `question`
- `answer`
- `relevant_docs`
- `relevant_tables`
- `evidence`
- `pandas_query`

The validator rejects missing questions, unsafe paths, invalid locators, orphan CSV files, unsafe queries, duplicate evidence variables, and mismatched source question text. Replay rejects any emitted answer that differs from its Pandas result.

## Project layout

| Path | Responsibility |
|---|---|
| `src/text2pandas/domain/` | Pure semantic types, value objects, and business rules |
| `src/text2pandas/application/` | Use cases, ports, parser, planner, binder, compiler, and executor |
| `src/text2pandas/infrastructure/` | SQLite, file system, retrieval, ontology, parsing, and sandbox adapters |
| `src/text2pandas/interface/` | Unified CLI and optional API boundary |
| `src/text2pandas/pipelines/` | Canonical legacy V2 pipelines during migration |
| `configs/` | Active identities, policies, registries, formulas, and ontology |
| `data/` | Raw, processed, indexed, and curated data classes |
| `tests/` | Unit, contract, regression, and materialized integration tests |
| `artifacts/` | Generated runs, reports, packages, and submissions |
| `experiments/` | Ablations and re-audits; never imported by production |
| `provenance/` | Tracked checksums, identities, and audit seals |
| `docs/` | Competition source, ADRs, migration state, and test reports |

`data_pipeline`, `retrieval`, and `text2pandas.answer_pipeline` are compatibility namespaces. New production code must import from `text2pandas` instead.

## Engineering constraints

Read [`AGENTS.md`](AGENTS.md) before changing code, configuration, data, or evaluation behavior.

The non-negotiable rules are:

- Keep `data/raw/btc/` immutable
- Resolve active data from `configs/datasets/active_snapshot.yaml`
- Keep production imports out of `tools/`, `experiments/`, and compatibility shims
- Keep packaged values grounded in the competition corpus
- Preserve exact evidence and Pandas replay
- Report missing gold as `NOT_MEASURED`
- Keep V3 in shadow mode until promotion policy passes
- Do not add a closed model, remote inference dependency, or production network call
- Do not commit large generated databases, caches, run directories, or ZIP files

## Documentation map

- [Agent operating contract](AGENTS.md)
- [Contribution workflow](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Competition requirements traceability](docs/REQUIREMENTS_TRACEABILITY.md)
- [Data ownership and lifecycle](data/README.md)
- [Refactor plan](docs/REFACTOR_PLAN.md)
- [Refactor status](docs/REFACTOR_STATUS.md)
- [Gap closure status](docs/GAP_CLOSURE_STATUS.md)
- [Semantic V3 migration status](docs/SEMANTIC_V3_MIGRATION_STATUS.md)
- [Current acceptance test report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-27.md)
- [Final acceptance test report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-26_FINAL.md)
- [Historical acceptance test report](docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-26.md)
- [Architecture decisions](docs/adr/)
- [Competition source](docs/competition/README.md)

## Known readiness gaps

The project is structurally valid and replayable, but several measured gaps remain:

- official Answer Accuracy and Execution Accuracy are unavailable without organiser gold
- canonical executable coverage is 55.93%
- multi-entity execution and operand binding cause most V2 abstentions
- the current V2 reranker is an identity stage without measured uplift
- Semantic V3 lacks enough adjudicated semantic and evidence gold for promotion
- full-repository legacy V2 modules remain outside the zero-error production mypy gate
- 42 approved historical-artifact tests skip under the exact allowlist in `configs/testing/approved_skips_v1.yaml`; unapproved skips fail CI
- A6 Structure Gold gates `SG`, `C2`, and `C3` remain blocked until two independent reviewers produce the required adjudicated set

Use the acceptance report as the numeric baseline. Update that report or create a dated successor after behavior, gold, or active snapshots change.
