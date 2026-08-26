# ADR 0008: Semantic Query Engine v3

- Status: accepted
- Date: 2026-08-26

## Context

The canonical runtime currently interprets a question through separate models:

- retrieval builds a metadata `Intent`;
- answering builds a scalar `QuestionSemanticFrame` and `OperationIR`;
- formula and multi-entity questions are dispatched to independent engines.

Those models cannot express nested operations such as “select metric B at the
entity where metric A is maximal”.  They also force retrieval to rank a shared
table pool before the required operands are known, and force binding to choose
operands greedily.  Adding more operation-specific branches would increase the
number of semantic implementations and make differential evaluation harder.

## Decision

Introduce Semantic Query Engine v3 around one immutable, serialisable
`QuestionAST` owned by the domain layer.

The production flow will become:

1. parse question spans into a `QuestionAST`;
2. compile every `MetricRef` into an operand-aware retrieval request;
3. bind all operands jointly under entity, period, basis, metric and unit
   constraints;
4. evaluate the bound AST with typed quantities;
5. compile the same bound AST to the restricted pandas expression contract;
6. validate typed and pandas results against one another;
7. derive evidence exclusively from bound observations.

The migration uses a strangler boundary.  V2 remains the canonical runtime
until V3 passes locked semantic, retrieval, binding, replay and submission
gates.  V2 and V3 run in shadow mode on the same immutable snapshots; a
difference must have a taxonomy reason before V3 promotion.

## Invariants

- Domain semantic modules import only the Python standard library.
- Operation composition is represented by AST nesting, never by QID branches.
- Entity and period are axes, not special operation families.
- A metric is referenced by canonical ID; aliases belong to the versioned
  ontology, not execution code.
- Retrieval is recall-preserving and operand-aware.  Answering remains
  fail-closed.
- Binding is a global assignment.  Greedy selection is not a V3 contract.
- Every successful scalar is replayable and grounded in all bound operands.
- Rerankers are promoted only on an untouched held-out gold split.

## Consequences

- Existing `entity_*` and formula engines become compatibility implementations
  and are removed only after V3 parity and quality gates pass.
- Parser rules may annotate lexical spans but may not directly emit pandas.
- Metric and formula registries must be unified behind one validated ontology.
- Retrieval checkpoints and run manifests must record the semantic schema,
  ontology and ranker fingerprints.

