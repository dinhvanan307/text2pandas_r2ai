# ADR 0009: Corpus-only production data policy

- Status: accepted
- Date: 2026-08-26

## Context

The competition brief contains two incompatible statements:

- page 4 prohibits external data at every processing stage;
- page 12 permits public, legally usable external datasets.

Using the permissive statement could invalidate a submission under the stricter
statement. The repository also needs a clear boundary between a pretrained
model artifact and financial facts used to produce an answer.

## Decision

Apply the stricter interpretation until the organisers publish a clarification:

1. Production financial values, entities, periods, tables and evidence come
   exclusively from the supplied competition corpus.
2. No external web, market-data, knowledge-base or remote inference call is
   permitted in ingestion, retrieval, answering, packaging or replay.
3. A public open-weight pretrained model may be used only when its model card
   proves the page-4 constraints: public availability, release before
   2026-06-01 00:00 Asia/Ho_Chi_Minh, at most 14B parameters and a compatible
   license. Model artifacts may transform corpus content but may not supply
   answer facts.
4. Development-only external research must remain outside production artifacts
   and cannot be used as answer/evidence gold unless its provenance and
   independence are explicitly documented.
5. Relaxing this policy requires a new ADR quoting an authoritative organiser
   clarification and updating the compliance tests.

## Consequences

- The canonical deterministic pipeline is compliant without model metadata.
- Adding any model or dataset is fail-closed until a versioned compliance
  manifest and offline test prove the boundary.
- Potential quality gains from external financial datasets are intentionally
  forgone in exchange for submission eligibility.

