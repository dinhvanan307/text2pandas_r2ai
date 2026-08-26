# ADR 0007: Maximal metric hints and checkpoint versioning

Date: 2026-08-26

## Status

Accepted.

## Context

Metric-code hints used independent substring matches. A specific phrase such
as `tổng tài sản cố định hữu hình` therefore emitted both code 221 and the
overlapping shorter code 270 (`tổng tài sản`). Because a code hit is a strong
S2/binding signal, the shorter phrase could select the balance-sheet total and
silently answer the wrong metric.

## Decision

- Add reviewed VAS codes 220, 221 and 227 for fixed assets.
- Keep only maximal overlapping metric phrases before emitting code hints.
- Bump retrieval evaluation checkpoints from `evalkit-6` to `evalkit-7`.

## Consequences

Existing `evalkit-6` checkpoints remain historical and must not be mixed with
new results. Retrieval measurements affected by metric hints must be collected
again under `evalkit-7`.
