# ADR 0012: Retrieval alias provenance and checkpoint identity

Date: 2026-08-28

## Status

Accepted.

## Context

The active question corpus contains entity mentions for STB and EIB that are
not represented correctly by the source company-name metadata. The generated
corpus-attested brand artifact also contained literal YAML document terminators
because scalar values were serialized independently. Both defects can prevent
otherwise valid questions from reaching fact retrieval.

Evalkit checkpoints previously recorded the alias branch name but not the bytes
of the alias artifacts. Editing an alias file could therefore reuse a
checkpoint produced under different entity-resolution behavior.

## Decision

- Keep source company metadata immutable.
- Add a versioned question-attested alias layer whose entries carry source
  question IDs and the active raw snapshot identity.
- Load that layer in every alias branch because it is corpus evidence, not an
  experimental external brand list.
- Serialize the generated attested-brand mapping as one YAML document.
- Hash every effective alias artifact into the evalkit evaluation identity.
- Bump retrieval evaluation checkpoints from `evalkit-10` to `evalkit-11`.
- Keep the submission table cap in one policy module shared by CLI, adapter,
  evaluator, and rewrite tooling.

## Consequences

All `evalkit-10` checkpoints remain historical and cannot be mixed with the
new alias behavior. A change to the base aliases, question-attested aliases, or
selected brand layer now creates a different checkpoint path even if the
configuration values and retrieval snapshot are unchanged.

This decision does not promote Semantic V3 or weaken any semantic, evidence,
or answer-gold gate.
