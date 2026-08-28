# ADR 0013: Complete year-range intent and checkpoint versioning

Date: 2026-08-28

## Status

Accepted.

## Context

Canonical V2 extracted every four-digit year mention independently. An explicit
range such as `2019–2023` therefore became `(2019, 2023)` rather than the full
period domain. The active corpus has 37 explicit dash ranges; 35 contain one or
more interior years and were represented endpoint-only.

S1 already filters documents over `min(years)..max(years)+slack`, so the defect
usually did not remove candidates. It did affect period/operand cardinality and
the shared submission table-count policy.

## Decision

- Expand explicit ascending ranges written with hyphen, en dash or em dash in
  the semantic `Intent.years` domain.
- Clip expansion to the parser's configured year boundary.
- Do not reinterpret reversed ranges; retain their literal endpoints so later
  semantic layers can fail closed.
- Preserve literal endpoints separately as `Intent.retrieval_years`; S2 period
  bonuses and submission `N` continue to use these lexical years. This avoids
  the measured q425 regression where immediate expansion changed best-gold rank
  5→6 and raised N 2→4 without recovering a gold table.
- Preserve entity, basis and normalization behavior byte-for-byte.
- Bump retrieval checkpoints from `evalkit-11` to `evalkit-12` because intent,
  period bonuses and output `N` can change.

## Consequences

All `evalkit-11` checkpoints remain historical. New retrieval measurements
must use `evalkit-12`. S1 candidate membership, ranking and output policy remain
stable for explicit ranges because the literal endpoints are preserved at the
retrieval boundary; answer routing receives the complete semantic domain.
Promotion still requires paired regression and does not imply an official
score gain.
