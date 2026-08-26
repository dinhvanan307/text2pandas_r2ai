# Agent operating contract

This file defines how coding agents work in this repository. It applies to the entire repository unless a deeper `AGENTS.md` overrides a specific subtree.

## Mission

Text2Pandas answers Vietnamese financial questions from the competition corpus. It retrieves grounded tables, compiles Pandas queries, executes them, and packages reproducible evidence.

Optimize for correctness, traceability, and reproducibility. A supported abstention is safer than an ungrounded number.

## Read this context first

Load only the context required for the task:

- **Project onboarding**: `README.md`
- **Competition authority**: `docs/competition/Text2Pandas.docx` and `docs/competition/README.md`
- **Active data identities**: `configs/datasets/active_snapshot.yaml`
- **Architecture decisions**: the relevant file under `docs/adr/`
- **Current migration state**: `docs/SEMANTIC_V3_MIGRATION_STATUS.md`
- **Measured readiness**: `docs/reports/ACCEPTANCE_TEST_REPORT_2026-08-26_FINAL.md`
- **Data ownership**: `data/README.md`, `artifacts/README.md`, and `provenance/README.md`

Do not treat historical handoff files as current architecture. Verify every claim against active config, manifests, code, and tests.

## Source-of-truth order

Use this precedence when sources disagree:

1. The user request and competition authority
2. Root `AGENTS.md` and accepted architecture decision records (ADRs)
3. Active configuration and immutable manifests
4. Executable contracts and tests
5. Implementation code
6. Status, handoff, package, and historical documents

The competition document contains inconsistent statements about external data. Do not add an external dataset until an ADR records the interpretation, provenance, license, checksum, and allowed use.

## Runtime architecture

The production namespace is `text2pandas`:

```text
interface -> application -> domain
     |             |
     +------ infrastructure

raw BTC -> processed A6 -> retrieval index -> answering -> validation -> submission
```

Respect these boundaries for new code:

- `domain/`: pure types and business rules; standard library only; no I/O
- `application/`: use cases, ports, planning, binding, and execution contracts
- `infrastructure/`: file system, SQLite, parsing, retrieval, sandbox, and model adapters
- `interface/`: CLI and optional API adapters
- `pipelines/`: canonical legacy V2 implementation during the migration window

Semantic V3 follows the typed boundary. Canonical V2 still contains legacy exceptions. Do not copy those exceptions into new modules.

The following namespaces are compatibility shims:

- `data_pipeline`
- `retrieval`
- `text2pandas.answer_pipeline`

New production code must not import compatibility shims, `tools/`, `experiments/`, or generated artifacts.

## Canonical and shadow engines

- Canonical V2 produces the current validated submission
- Semantic V3 runs in shadow mode
- V3 promotion requires `configs/semantic/promotion_policy_v3.yaml` to pass
- V2 output is not gold for V3
- A typed result must equal clean Pandas replay before V3 returns it

Never switch the composition root, relax a promotion threshold, or hide a blocker to force promotion.

## Data and artifact safety

Treat every data layer as immutable and addressable:

- `data/raw/btc/`: original competition reports and questions; never write generated output here
- `data/processed/a6/build_id/`: normalized tables and observations for one build
- `data/indexes/retrieval/a6_build_id/index_id/`: index bound to one A6 build
- `data/curated/`: governed evaluation and gold inputs
- `artifacts/`: generated runs, reports, packages, and submissions; ignored by default
- `provenance/`: small tracked identities, checksums, and audit seals

Never select a snapshot by `latest`, modification time, or directory order. Read `configs/datasets/active_snapshot.yaml`.

Every generated run needs a unique immutable `run-id`. Do not overwrite, delete, or reuse a run stage. Create a new ID when a run fails.

Corpus values are the only allowed source for packaged answers and evidence. External metadata may not replace financial values from the corpus.

## Competition and model constraints

The tested production path is deterministic and does not require a language model.

Before adding any model, verify and record all constraints in `configs/models.yaml`:

- publicly available weights
- at most 14 billion parameters
- released before 2026-06-01 in Vietnam time
- license and release evidence
- no closed model or remote inference dependency

Production data processing and query execution must not make network calls.

## Change workflow

Before editing:

1. Run `git status --short`
2. Read the closest contract, ADR, config, and tests
3. Confirm the active raw, A6, and retrieval identities when data is involved
4. State any assumption that changes semantics, evidence, units, or submission shape

While editing:

- Preserve unrelated user changes
- Use `rg` or `rg --files` for discovery
- Use `apply_patch` for manual file edits
- Put policy and ontology data in `configs/`, not duplicated constants
- Keep monetary calculations in `Decimal` until the submission boundary
- Keep evidence derived from selected observation identifiers
- Fail closed on ambiguous entity, period, metric, unit, basis, or formula binding

After editing:

1. Run the minimum gate for the changed scope
2. Run `git diff --check`
3. Inspect manifests and generated outputs, not only exit codes
4. Report failures, skips, abstentions, and unmeasured metrics explicitly
5. Commit one logical change with a conventional message

## Test matrix

Use the smallest sufficient gate during development. Run broader gates before release.

| Changed scope | Required gate |
|---|---|
| Documentation only | Verify links and commands; run `git diff --check` |
| Domain, parser, ontology, planner, binder, executor | Targeted unit tests plus `make test-offline` |
| Retrieval behavior or ranking | `make snapshots-verify`, retrieval tests, and a versioned evalkit run |
| A6 schema or transformation | A/B deterministic build, quality gates, measurements, and package verification |
| Submission or sandbox | Submission contract tests, materialized integration tests, strict validation, and clean replay |
| Cross-cutting production change | `make ci`, `make test-integration`, and the relevant full-corpus run |

Core commands:

```bash
make paths-check
make ci
make snapshots-verify
make test-integration
make dp-env-check
make dp-test REPORT_DIR=artifacts/reports/acceptance_local_001
```

Run strict mypy on every changed typed package. `make typecheck` is the zero-error gate for the 77 production architecture modules. Full-repository mypy still contains documented historical V2 pipeline debt outside that boundary; do not move new production behavior there or conceal errors with cache.

## Evaluation discipline

Keep these measurements separate:

- route coverage
- candidate recall
- ranking Precision, Recall, and F2
- binding exact match
- replay consistency
- Answer Accuracy
- Execution Accuracy

Do not describe route coverage or replay consistency as accuracy. If gold is missing, report `NOT_MEASURED`.

Do not tune and report on the same evaluation slice. Version configs, checkpoint fingerprints, gold inputs, and output manifests.

## Submission invariants

A publishable ZIP must satisfy all constraints:

- exactly one JSON file at the archive root
- every other member is a referenced CSV under `data/`
- exactly 1,012 unique question records for the active dataset
- exact source question text
- finite numeric answers
- valid and unique evidence variables
- safe restricted Pandas queries
- real document and table locators
- `answer == eval(pandas_query)` for every emitted query
- zero validator errors and zero replay errors

Never publish a package when validation or replay fails.

## Git and commit discipline

- Use conventional commit subjects such as `feat(parser): compile semantic AST` or `fix(binding): enforce period coherence`
- Keep commits independently reviewable
- Do not amend user commits unless requested
- Do not commit virtual environments, caches, large databases, ZIP files, or generated run directories
- Commit curated fixtures, policies, ADRs, and small provenance files only when they are deliberate review inputs
- Never use destructive Git or recursive deletion without explicit authorization and validated targets

## Definition of done

A task is complete when:

- behavior matches the requested contract
- architecture boundaries remain intact
- relevant tests pass in a declared environment
- data and artifact identities are traceable
- documentation and examples match the actual CLI
- measured gaps remain visible
- the worktree contains only intentional changes
- logical changes are committed

If a required authority, gold set, external artifact, or decision is missing, stop at a documented blocker. Do not invent evidence or silently weaken a gate.
