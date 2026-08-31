# ADR-0016: Separate competition validity from complete execution coverage

## Status

Accepted on 2026-08-30 for the Grounded V6 recovery line.

## Context

The user-confirmed official submission 3821 artifact was accepted and scored by
the organiser with 1,012 records, 712 emitted queries and 300 explicit
abstentions.  Every emitted query replays to its packaged answer, while the
previous internal release gate treated each abstention as an execution error and
therefore could not represent the already accepted artifact.

Replay consistency, coverage and official correctness are different
measurements.  None may be reported as a substitute for another.

## Decision

Submission validation and handoff expose two explicit profiles:

- `complete`: every expected QID must contain evidence and a query and must
  replay successfully;
- `competition`: the ZIP must contain the complete question scope and all
  structural, locator, evidence and query-safety checks remain mandatory, but an
  explicit abstention is reported as coverage debt rather than an emitted-query
  execution failure.

Under both profiles, every emitted query must execute and match its packaged
answer.  The competition profile may ignore only the two warnings for empty
evidence and empty query.  Other warnings remain publication blockers.

## Consequences

- Full execution remains the internal quality target and the default profile.
- Competition handoffs must declare their profile and executable/unresolved
  coverage.
- A competition-valid artifact is not evidence of Answer Accuracy.
- Promotion policies remain fail-closed for ambiguous semantic binding.
- The source commit, config identity and leaderboard receipt of submission 3821
  remain unknown even though its exact ZIP identity is user-confirmed.
