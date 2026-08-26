# ADR 0005: Fingerprint subject-classifier behavior

Date: 2026-08-26

## Status

Accepted.

## Context

The entity-screen classifier now recognizes `tổng số công ty` so explicit
multi-entity COUNT questions retain the complete entity set. This changes S1
behavior. The evaluation fingerprint previously hashed `question_intent.py`
but omitted its `subject.py` dependency, so the existing gate could not detect
this class of change.

## Decision

- Include `subject.py` in the retrieval behavior fingerprint.
- Bump evaluation checkpoints from `evalkit-4` to `evalkit-5`.
- Keep prior fingerprints as immutable historical mappings.

## Consequences

New retrieval reports require recollection under `evalkit-5`; older checkpoints
must not be resumed or merged. Future changes to screen/compare/related cues are
now caught by the same version gate as S1/S2 changes.
