# ADR 0004: Version entity-resolution behavior in evaluation checkpoints

Date: 2026-08-26

## Status

Accepted.

## Context

The S1 resolver previously removed a company whenever any matched short alias
was nested in another company's name. This discarded the independently matched
full legal name of GAS in questions that also mention POW. It also classified
Vietnamese `hiệu số` questions as related-party lookups instead of comparisons.

Both changes alter retrieval targets and therefore invalidate prior evaluation
checkpoints even though the YAML configuration hash is unchanged.

## Decision

- Shadow an entity only when every matched alias is contained in a longer alias
  of another matched entity.
- Treat `hiệu số` as an explicit two-entity comparison cue.
- Bump the retrieval evaluation schema from `evalkit-3` to `evalkit-4` and pin
  the new behavior fingerprint.
- Keep the package-level and runner-level schema markers synchronized.

## Consequences

Existing `evalkit-3` checkpoints remain readable historical artifacts but must
not be resumed or combined with `evalkit-4`. Every retrieval tag used for a new
comparison must be recollected under `evalkit-4` before reporting metrics.
