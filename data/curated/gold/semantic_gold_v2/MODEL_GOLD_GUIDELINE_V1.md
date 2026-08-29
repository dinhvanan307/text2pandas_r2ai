# Model Semantic Gold V1 guideline

Status: `FROZEN_FOR_MODEL_SEMANTIC_GOLD_V1`

This guideline governs a single-model development gold release. It is not human
gold, independent human gold, or promotion authority.

## Allowed inputs

- Exact selected question text.
- Frozen schema, metric vocabulary, operation vocabulary, and this guideline.
- Frozen source terminology/context that was not selected by a parser, retriever,
  resolver, selector, binder, answerer, or executor.

## Forbidden inputs

- Parser or Semantic V3 predictions/traces.
- Retrieval candidates, ranks, scores, or VAS hints.
- Resolver/binder output and selected table/row/cell.
- Numeric answers, Pandas queries, execution results, and leaderboard results.
- Existing synthetic semantic labels for the selected QID.

## Semantic scope

The record describes question intent before runtime binding. It does not assert a
correct table, row, cell, numeric answer, query, or execution.

## Status

The tool derives record status from all eight field statuses:

1. any `UNRESOLVED` -> record `UNRESOLVED`;
2. else any `AMBIGUOUS` -> record `AMBIGUOUS`;
3. otherwise -> record `RESOLVED`.

`NOT_APPLICABLE` is field-level only. Ambiguity needs at least two concise
alternatives. Unresolved records require a reason in notes.

## Spans

Entity and metric strings are exact NFC substrings. The compiler records
zero-based half-open offsets and preserves source order. Use the maximal semantic
metric phrase without entity, period, unit, or question boilerplate.

## Metric concepts

Use the 39 concepts inherited from `semantic-metric-concepts-v1`. A clear niche
reported line outside that ontology uses `OTHER_REPORTED_METRIC` plus a stable,
non-empty Vietnamese `variant`. This is not a table/row identifier.

## Entity, period, basis, and unit

- Preserve entity direction and distinguish company, subsidiary, investee,
  person, industry, segment, and group.
- Expand explicit year ranges. Preserve full dates and per-operand period roles.
- Explicit `hợp nhất` is CONSOLIDATED; `công ty mẹ`/`riêng lẻ` is SEPARATE;
  otherwise UNSPECIFIED/false.
- Keep output shape separate from unit dimension. Money/share scale exponents
  include 0, 3, 6, 9, 11, and 12.

## Operations

- LOOKUP returns one named value.
- ADD is binary; SUM/AVERAGE are variadic.
- SUBTRACT and DIVIDE preserve direction.
- GROWTH is time-ordered `(NEW-OLD)/OLD`; PERCENT_CHANGE is reserved for an
  explicit non-time percent change.
- MINIMUM/MAXIMUM return values; ARGMIN/ARGMAX return the arg.
- SELECT_AT_ARG returns another metric at a ranked arg.
- FILTER carries an explicit comparator/threshold operand.
- COUNT counts a represented domain/filter node.
- MEDIAN is an operation, not a reported metric.
- MULTIPLY is unsupported in this frozen vocabulary and must be unresolved.

## Canonicalization and release

The tool, not the model, derives record status, exact spans, canonical frames,
hashes, coverage, and immutable release metadata. Regeneration creates a new
release ID and never edits a sealed release in place.
