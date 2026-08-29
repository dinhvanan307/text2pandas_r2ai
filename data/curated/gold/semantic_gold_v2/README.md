# Semantic Gold v2 — independent annotation guideline

Status: `DRAFT_FOR_CALIBRATION`

This directory owns the Phase 1.5 semantic annotation policy. A release is not
gold until two independent annotation passes and one distinct adjudication pass
have completed and the sealer writes a `SEALED` manifest.

## 1. Allowed and forbidden inputs

Annotators may use:

- the exact question text;
- ordinary Vietnamese financial/accounting meaning;
- source A6 CSVs only to verify company identity, reported terminology and
  provenance location;
- the schema and vocabularies referenced by the packet manifest.

Annotators must not use:

- Canonical V2 or Semantic V3 predictions/traces;
- current answers, pandas queries or evidence selected by a runtime;
- retrieval scores, candidates or bound rows chosen by the implementation;
- another annotator's labels before both independent passes are locked;
- a parser/resolver implementation as the authority for semantic meaning.

Source evidence may confirm that a phrase is a reported concept. It must not be
used to reverse-engineer the intended semantic frame from a current answer.

## 2. Status policy

Record status:

- `RESOLVED`: every required semantic field is determined;
- `AMBIGUOUS`: the question genuinely supports more than one reading;
- `UNRESOLVED`: a required field could not be determined from allowed inputs.

Field status additionally permits `NOT_APPLICABLE`. Never force a label to
reach a target record count. Every non-resolved field requires a note or an
explicit ambiguity alternative.

## 3. Text spans

Entity and metric spans use NFC-normalized question text, zero-based half-open
character offsets. `question[start:end]` must equal `text` exactly.

Choose the maximal phrase that carries the concept:

```text
"doanh thu thuần" -> NET_REVENUE
```

Do not expand the span to company, period, unit or question boilerplate. Keep
each occurrence separately if a phrase appears more than once.

## 4. Entity annotation

Annotate the surface mention and canonical reference separately. A ticker-like
token embedded in a legal name is not automatically the reporting entity.

Example:

```text
mention:       CTCP Chứng khoán FPT
canonical_ref: FTS
```

Use `UNRESOLVED` rather than guessing a ticker from a name. Preserve source
order for multiple entity mentions and assign semantic roles such as
`REPORTING_ENTITY`, `COMPARISON_ENTITY` or `INVESTEE`.

## 5. Metric phrase and concept

A metric concept is the meaning requested by the question. It is not a Silver
row, VAS code, table ID or observation UID.

Annotate:

```text
surface span + concept ID + REPORTED/DERIVED
```

A named ratio is one reported metric when the question asks for that named
ratio without spelling out its components. It becomes a composed operation
when the question explicitly supplies numerator and denominator.

Examples:

```text
"tỷ lệ nợ xấu" -> BAD_DEBT_RATIO (reported metric)
"nợ xấu trên tổng dư nợ" -> DIVIDE(BAD_DEBT, TOTAL_LOANS)
```

If the controlled vocabulary lacks a precise concept, use `UNRESOLVED` and
propose a definition in notes. New concepts may be admitted only during the
calibration phase, before final A/B annotation begins.

## 6. Periods and roles

Annotate every named period. Expand ranges to all included years. Preserve
period point and semantic role:

```text
2024 -> CURRENT
2023 -> PREVIOUS
```

Point vocabulary:

```text
PERIOD | OPENING | CLOSING | INSTANT | UNKNOWN
```

When operands use different periods, each operand references its own period.
Do not collapse a range into one scalar year.

## 7. Basis

Map explicit wording:

```text
hợp nhất                  -> CONSOLIDATED
công ty mẹ / riêng lẻ     -> SEPARATE
no basis wording          -> UNSPECIFIED, explicit=false
```

The runtime's consolidated retrieval default is not part of the question's
semantic gold. Mixed-basis operations must retain a per-operand basis.

## 8. Unit and output

Unit dimension and scale are separate from output shape.

```text
triệu đồng  -> MONEY, exponent=6, currency=VND
tỷ đồng     -> MONEY, exponent=9, currency=VND
nghìn tỷ    -> MONEY, exponent=12, currency=VND
%           -> PERCENT
điểm %      -> PERCENT_POINT
```

Output shape vocabulary:

```text
SCALAR | ENTITY | PERIOD | COUNT | TABLE | SET | BOOLEAN | OTHER
```

## 9. Operation tree and operands

Represent composition as a tree. Operand order is semantic and must not be
sorted alphabetically.

Examples:

```text
DIVIDE(NUMERATOR, DENOMINATOR)
SUBTRACT(MINUEND, SUBTRAHEND)
GROWTH(NEW, OLD)
SELECT_AT_ARG(RANK_KEY, PROJECTED_VALUE)
```

Nested operations use nested nodes rather than invented composite role names.
A filter belongs to the population it constrains; it is not automatically an
operand of the returned value.

## 10. Evidence locator

Record `{csv_path, row_path, col_label}` when source evidence can be located.
Do not copy a runtime's selected evidence. Do not include numeric source values
in semantic gold. Use `NOT_LOCATED` when reasonable review cannot locate an
appropriate source phrase.

## 11. Canonical full frame

Annotators must not enter, copy or maintain a second `full_frame`. They edit
only the component fields in the schema. Sealing infrastructure derives the
canonical frame deterministically from those components.

Canonicalization:

- normalizes strings to Unicode NFC and enums to uppercase;
- sorts entity, metric and period membership by their stable refs;
- preserves operand order and operation-tree child order;
- preserves every applicable semantic component;
- excludes fields marked `NOT_APPLICABLE`;
- excludes reviewer identity, attestations, notes, adjudication metadata and
  source-evidence locators.

An applicable field that is missing is an error. A supplied full frame that
does not equal the derived frame is also an error.

## 12. Independent review workflow

1. Annotator A completes a private packet and locks it.
2. Annotator B independently completes a separate private packet and locks it.
3. Agreement is measured before adjudication.
4. Adjudicator C reviews every record and every disagreement using source
   evidence.
5. Genuine ambiguity remains ambiguous.
6. A release is sealed only after all identities, attestations, checksums,
   references and statuses validate.

Annotators A, B and adjudicator C must be three distinct people who did not
develop the parser being measured. Until those roles are assigned, the packet
must remain `OPEN_FOR_INDEPENDENT_REVIEW` and parser metrics remain
`NOT_MEASURED`.

Each reviewer must attest all of the following against the fixed packet:

```text
independent_of_model_development = true
blind_to_model_outputs           = true
source_evidence_reviewed         = true
guideline_version                = fixed packet value
guideline_sha256                 = fixed packet value
metric_vocabulary_sha256         = fixed packet value
operation_vocabulary_sha256      = fixed packet value
```

Before the final 120 records, A and B independently annotate a 12–15 QID pilot
that is excluded from headline, diagnostic and reserve cohorts. C classifies
disagreement as guideline defect or genuine ambiguity. Any guideline, schema
or vocabulary change must bump its version/checksum before final A/B work.

## 13. Reserve and denominator policy

The 30 reserve QIDs are preselected and checksummed with the packet. Activation
requires a manifest amendment made before viewing predictions and one of these
reasons: corrupt source record, duplicate source record, fewer than 100 final
resolved records, or missing critical semantic family.

Activation never deletes an unresolved original QID, never silently changes
the original headline denominator and never raises the release above 150 QIDs.
