# ADR-0003: Generated artifact retention

- Status: Accepted
- Date: 2026-08-25

## Decision

Git stores source, config, curated fixtures, manifests, checksums and provenance.
Generated databases, Parquet, archives, submissions, reports and intermediate runs
live under `artifacts/` or the configured artifact root and are ignored by default.

Large raw/A6/retrieval payloads are materialized from their manifest and verified
locally. Git LFS is not introduced until a remote, retention policy and access
model are explicitly selected.

## Consequences

- A fresh Git clone is small but does not contain materialized integration data.
- Offline tests are the CI default; materialized integration gates fail closed.
- Deletion of legacy payloads requires checksum, parity and backup sign-off.
