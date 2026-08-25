# ADR-0001: Canonical data lineage

- Status: Accepted
- Date: 2026-08-25

## Decision

The repository models data as three separate, versioned layers:

```text
data/raw/btc
  → data/processed/a6/<build_id>
  → data/indexes/retrieval/<a6_build_id>/<index_id>
```

`configs/datasets/active_snapshot.yaml` selects one reviewed identity at each
layer. Runtime code resolves roots through `ProjectPaths`; `T2P_DATA_ROOT` and
`T2P_ARTIFACT_ROOT` are the only supported root overrides.

## Consequences

- Raw BTC remains immutable and contains no generated output.
- Every retrieval index has an explicit source A6 build.
- No mutable `latest` path or developer-machine absolute path is committed.
- Payloads can live outside the Git checkout without changing logical paths.
