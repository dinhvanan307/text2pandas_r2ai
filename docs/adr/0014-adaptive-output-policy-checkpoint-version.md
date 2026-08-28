# ADR 0014: Version adaptive table-output behavior

- Status: accepted
- Date: 2026-08-29

## Context

Official baseline submission 3766 uses a scope-derived table limit and reports
Tables Recall 0.2461. A governed 95-question diagnostic attributes 23 of 95
cases to output truncation after the gold table has survived ranking.

The recovery experiment adds an optional policy that starts at the existing
entity×year floor and extends it while S2 candidates remain within a configured
score margin. This changes scorer-facing retrieval behavior even though the
default remains backward compatible.

## Decision

The retrieval checkpoint schema is bumped from `evalkit-12` to `evalkit-13`.
Every candidate ranking checkpoint used for promotion must be recollected on
the new schema. Candidate configuration records its score margin, maximum
table count, primary-table boost, source identity, and dataset identity.

## Consequences

Existing `evalkit-12` checkpoints remain historical evidence but cannot be
silently reused for this recovery decision. Official improvement is not
claimed from the local diagnostic; it requires a new leaderboard submission
whose Tables Recall exceeds 0.2461.
