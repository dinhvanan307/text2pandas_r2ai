# ADR 0011: Directional entity order and checkpoint versioning

Date: 2026-08-27

## Status

Accepted.

## Context

Entity resolution stored tickers in a `frozenset`, and comparison targets were
then sorted lexically. That representation is valid for screening membership,
but invalid for directional arithmetic: `EIB trừ ACB` was executed as
`ACB - EIB` whenever lexical order differed from mention order. The result was
finite, traceable, and wrong, so ordinary execution validation could not catch
it.

Vietnamese comparative wording also has two directions. `A lớn/cao hơn B`
means `A - B`, while `A kém/thấp/bé hơn B` means `B - A`.

## Decision

- Preserve resolved comparison entities in source mention order.
- Keep screening members lexically sorted because screening is set-valued and
  must not gain order-dependent tie behaviour.
- Represent reverse comparative direction explicitly in the operation hint and
  emit both semantic and calculation entity order in the execution trace.
- Bump retrieval evaluation checkpoints from `evalkit-8` to `evalkit-9`.
- Update the reviewed semantic coverage baseline from 669/1,012 to 684/1,012
  eligible questions after the explicit difference-cue expansion.

## Consequences

All `evalkit-8` checkpoints remain historical and cannot be mixed with new
results. Active retrieval measurements must be collected again under
`evalkit-9`. Previously answered directional comparisons must be regenerated;
absolute-value normalization is explicitly prohibited because it erases the
question's signed semantics.
