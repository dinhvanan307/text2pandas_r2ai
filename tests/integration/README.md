# Integration tests

Integration tests may require materialized raw/A6/retrieval/submission artifacts.
They fail closed with the missing path when prerequisites are absent.

- Offline gate: `pytest -m "not integration"`
- Materialized gate: `pytest -m integration`

H0 requires `artifacts/execution/h0/` plus legacy comparison submissions; it is
intentionally not converted to a false-green skip.
