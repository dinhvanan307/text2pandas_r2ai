# Folder refactor status

Updated: 2026-08-26

## Completed

- Git baseline and pre-move checksums for raw BTC, A6 and retrieval.
- Canonical physical layout: `raw → processed/a6 → indexes/retrieval`.
- Central `ProjectPaths`, environment root overrides and reviewed active snapshot.
- Machine-readable manifests and committed provenance identities.
- Runtime path migration; no active hard-code to the former external locations.
- Canonical `text2pandas.pipelines.{a6,retrieval,answering}` namespaces.
- Retrieval experiments separated from reusable tooling.
- Reviewed evaluation fixtures moved to `data/curated/evaluation`.
- Unified CLI snapshot verifier and reproducible Make/CI offline gates.
- Offline suite separated from materialized H0 integration gates.

## Intentionally retained

- Compatibility shims for `data_pipeline`, `retrieval` and
  `text2pandas.answer_pipeline`. Remove after a downstream-import deprecation window.
- Legacy tools and test-local `sys.path` bridges that load historical scripts.
  Production source no longer imports `tools`; converting all historical tools is
  a separate behavior-sensitive cleanup.
- Retrieval is still a full A6-derived SQLite copy. A sidecar-only redesign is a
  storage/behavior change and requires ordered-result parity before migration.
- Generated legacy artifacts remain locally available but ignored; no destructive
  cleanup was performed during the layout migration.

## Current gates

- Offline: green.
- Raw/A6/retrieval identity and lineage: green for the active local snapshots.
- H0 materialized integration: fail-closed until its adjudication and determinism
  artifacts are generated under `artifacts/execution/h0/`.
- Phase 6 removal/tagging: pending compatibility-window sign-off.
