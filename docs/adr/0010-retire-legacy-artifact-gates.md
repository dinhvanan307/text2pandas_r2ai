# ADR 0010: Retire legacy artifact gates from current acceptance

- Status: Accepted
- Date: 2026-08-26

## Context

Forty-two tests conditionally consume pre-refactor RC1/evidence-bundle files:
`answer_operation_precheck.jsonl`, runbook 37, RC1 build databases, the old
corpus-freeze manifest, `replay_report.json`, and
`SNAPSHOT_DECLARATION.json`. These artifacts are not inputs to the active
`raw -> A6 -> retrieval -> canonical answer` lineage and are intentionally not
tracked in the refactored repository.

Treating their absence as an active production gate conflates two incompatible
architectures. Recreating placeholder files would manufacture evidence. Deleting
the tests would remove useful historical regression monitors.

## Decision

- The active acceptance path is the snapshot verifier, current integration
  suite, strict submission validator, and clean query replay.
- Legacy artifact-dependent tests remain in the repository as optional
  historical monitors. They execute automatically when their authentic inputs
  are mounted.
- Every allowed skip is declared in
  `configs/testing/approved_skips_v1.yaml` with an exact path/reason boundary
  and a maximum count.
- Pytest fails the session for any unapproved skip, reason drift, or count above
  the approved maximum. A lower count is valid because it means an authentic
  historical artifact became available.
- Adding or widening an allowance requires a new ADR or an explicit amendment
  to this decision. Missing dependencies are never allowlisted.

## Consequences

Current CI reports 42 approved historical skips instead of presenting them as
unclassified coverage loss. The skips do not support a current acceptance
claim. Materialized production gates remain mandatory and have no skip
allowance.
