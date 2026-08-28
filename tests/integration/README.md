# Integration tests

Integration tests require the active raw/A6/retrieval artifacts and fail closed
when those prerequisites are absent.

- Offline gate: `pytest -m "not integration and not historical"`
- Active materialized gate: `pytest -m "integration and not historical"`
- Historical monitor: `pytest -m historical`

The seven pre-refactor H0 submission monitors still require authentic legacy
comparison ZIPs. They are not skipped or synthesized: they run only in the
explicit historical scope when those inputs are mounted. Current candidate ZIPs
are gated after two canonical runs with `make verify-active-candidate`.
