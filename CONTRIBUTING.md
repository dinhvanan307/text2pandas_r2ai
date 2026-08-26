# Contributing to Text2Pandas

Text2Pandas is a data- and evaluation-sensitive system. A change is accepted
only when its behavior, evidence boundary and measurements remain auditable.

## Before opening a change

1. Read [`AGENTS.md`](AGENTS.md) and the relevant architecture decision under
   [`docs/adr/`](docs/adr/).
2. Confirm the active identities in
   [`configs/datasets/active_snapshot.yaml`](configs/datasets/active_snapshot.yaml).
3. Create a focused branch and keep generated databases, runs and ZIP files
   outside Git.
4. Do not use organiser questions, answer gold or evidence gold as
   question-ID-specific production rules.

## Implementation rules

- Add production behavior under `src/text2pandas/`; `tools/` and `experiments/`
  are not runtime dependencies.
- Preserve `data/raw/btc/` as immutable input.
- Put reviewed metrics, formulas and policies in versioned `configs/` files.
- Keep answers grounded in selected observation IDs and require clean Pandas
  replay before packaging.
- Fail closed when entity, period, basis, metric, unit or evidence is ambiguous.
- A retrieval or rerank change requires a new behavior/config fingerprint and
  a versioned evaluation artifact. Never tune and report on the same slice.

## Required verification

Run the smallest relevant gate while developing and the complete offline gate
before review:

```bash
make ci
git diff --check
```

Changes that touch materialized data, retrieval behavior, submission or replay
must also run:

```bash
make snapshots-verify
make test-integration
```

Use an immutable report directory for a release candidate:

```bash
make dp-test REPORT_DIR=artifacts/reports/<unique-report-id>
```

The change description must state test counts, skips, abstentions, local-gold
scope and every metric that remains `NOT_MEASURED`.

## Commit and review shape

- Use Conventional Commit subjects.
- Keep code, policy, migration and documentation changes independently
  reviewable where practical.
- Include regression tests for every defect.
- Do not weaken a threshold, remove evidence, accept an unsafe query or promote
  Semantic V3 merely to make a gate pass.

Security-sensitive findings should follow [`SECURITY.md`](SECURITY.md), not a
public issue.
