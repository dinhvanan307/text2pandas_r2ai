# ADR 0006: Boundary-safe entity resolution

Date: 2026-08-26

## Status

Accepted.

## Context

Six strict expected-failure tests documented three unresolved S1 defects:
short aliases matched inside unrelated words (`an binh` inside `Tân Bình` or
`lần bình quân`), one explicit ticker erased companies matched by name, and
`chênh lệch với`/directional comparisons were classified as related-party
lookups.

## Decision

- Match company-name aliases on normalized alphanumeric word boundaries while
  retaining legal-prefix variants.
- Merge explicit ticker matches with independent company-name matches.
- Recognize `chênh lệch với`, `nhiều hơn`, `ít hơn` and `bé hơn` as comparisons.
- Include `normalize.py`, `question_intent.py` and `subject.py` in the behavior
  fingerprint and bump checkpoints to `evalkit-6`.

## Consequences

The six P0 expected failures are now normal regression tests. Existing
`evalkit-5` checkpoints are historical only; retrieval comparisons must be
recollected under `evalkit-6`.
