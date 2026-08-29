# ADR 0015: Compose Semantic V3 through an artifact-level strangler

- Status: accepted
- Date: 2026-08-29

## Context

Canonical V2 remains the validated production runtime. Semantic V3 already
provides a typed AST, per-operand metric retrieval, global binding, typed
execution and clean Pandas replay, but independent promotion gold is missing.
A direct composition-root switch would bypass the locked promotion policy.

## Decision

Add an immutable hybrid composition stage over one Canonical V2 run and one
Semantic V3 shadow run for the same question set. Promotion is controlled by a
versioned route policy. Every QID receives a mutually exclusive decision and
the resulting candidate must pass the normal submission validator and clean
replay.

The default Canonical V2 command is unchanged. Hybrid policies are experimental
and `production_eligible=false` until the existing Semantic V3 promotion gate
passes on a sealed independent release.

Semantic evidence CSV files receive a `v3_` prefix so their observation schema
cannot collide with a Canonical V2 long-format CSV for the same table UID.
Scorer-facing table references are policy-controlled and remain distinct from
the exact evidence list.

## Consequences

- Semantic routes can be evaluated and rolled back independently.
- A candidate can recover V2 abstentions without changing existing answers.
- A correctness-first policy may test changed lookup values, but it cannot be
  declared production-eligible without independent answer and binding gold.
- Per-QID attribution makes route coverage, value drift, replay and accuracy
  separate measurements.
