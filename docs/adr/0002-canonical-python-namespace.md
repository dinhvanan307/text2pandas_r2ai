# ADR-0002: One public Python namespace

- Status: Accepted with compatibility window
- Date: 2026-08-25

## Decision

`text2pandas` is the only public runtime namespace. A6, retrieval and answering
implementations live under `text2pandas.pipelines` and shared unit semantics live
under `text2pandas.domain`.

The old `data_pipeline`, `retrieval` and `text2pandas.answer_pipeline` modules are
aliases to canonical modules for one migration window. Production code must not
add new imports from compatibility namespaces, `tools`, or `experiments`.

## Consequences

- Existing commands and downstream imports retain behavior during migration.
- Compatibility modules can be deleted only after repository and downstream
  import audits reach zero.
- Moving a module and changing its behavior belong in separate commits.
