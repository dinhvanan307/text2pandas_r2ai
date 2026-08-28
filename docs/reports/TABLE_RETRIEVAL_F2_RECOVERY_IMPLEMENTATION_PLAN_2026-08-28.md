# TABLE RETRIEVAL F2 RECOVERY — IMPLEMENTATION PLAN

**Baseline HEAD:** `a2d3ef0308612f3025cf1a78c3d5bc470d0634f6`  
**Runtime:** Canonical V2; Semantic V3 remains shadow  
**Baseline run:** `canonical-v2-a2d3ef030861-b-e2e-01`  
**Measurement rule:** official impact is `UNKNOWN` without official hidden gold/scorer.

## Source verification

Current source implements:

```text
interface/cli/main.py
→ application/usecases/canonical_run.py
→ pipelines/retrieval/question_intent.py
→ pipelines/retrieval/filter_s1.py
→ pipelines/retrieval/rank_s2.py
→ evalkit/stages.py IdentityReranker
→ pipelines/retrieval/policy.py
→ pipelines/answering + evidence binding
→ pipelines/retrieval/submission_adapter.py
→ submission validation/package
```

Deterministic multi-entity COUNT/DIFFERENCE/AVERAGE/SUM routes already exist in
the canonical runner. Phase P5 is therefore verification/hardening, not a new
parallel implementation. V3 remains behind `shadow-v3` and its promotion policy.

## Concrete phase map

| Phase | Files/functions | Change | Tests | Gate | Artifacts |
|---|---|---|---|---|---|
| P0 freeze | Existing manifests; new immutable audit metadata | Record HEAD, snapshot IDs, DB/config/source hashes, environment, baseline metrics and ZIP SHA | JSON parse + checksum verification | Four baseline JSON files exist and match source artifacts | `artifacts/runs/retrieval/table-f2-recovery-baseline-.../` |
| P1 observability | `submission_adapter.py::SubmissionRefs/refs_for`; `canonical_run.py::run_canonical_pipeline`; new evalkit attribution module | Record compact intent, S1 IDs/count, S2/S3 ranked score components, N reason, pre/post-binding/final refs; classify stage loss only when gold is supplied | Unit contract + canonical fixture + manual-95 reproduction | Instrumentation is behavior-neutral; 95/95 S1, 554/554 items, 86/95 Hit@10, 50/95 policy hit | Versioned stage traces and attribution JSONL/metrics |
| P2 ranking | `rank_s2.py`; existing evalkit config/runner | Audit score contributions first. No production weight change without untouched held-out evidence. Candidate changes remain experiment profiles. | ranker unit, snapshot verify, paired QIDs | Hit@10/20 non-decreasing; lookup protected; held-out gate required for promotion | feature contribution and rank buckets |
| P3 output policy | `policy.py`; adapter/evaluator/rewrite callers | Add explicit policy profiles and diagnostic A/B for baseline/5/8/10/adaptive; keep production default unless gate supports promotion | policy unit + adapter integration + paired manual 95 | Select using F2/precision/recall jointly; no global N=10 shortcut | policy sweep JSON + per-QID deltas |
| P4 binding | `canonical_run.py` | Trace retrieval refs, bound evidence and final refs; evaluate loss. Any preservation rule must satisfy submission/evidence contract | canonical runner, answer/replay/submission tests | answer/replay unchanged; precision guard passes | binding attribution JSONL |
| P5 deterministic routes | Existing `answer_entity_*` routes in canonical runner | Verify unique entity/metric/period/basis gates and fail-closed behavior; only fix concrete regression | entity count/difference/average/sum unit + paired QIDs | No regression on canonical OK cases | route comparison |
| P6 parser | `question_intent.py::parse_intent`; `policy.py` | Expand explicit year ranges while decoupling output-cardinality semantics where required | parser range/fiscal/opening/closing/alias + retrieval paired | S1/Hit@10 non-decreasing; no unwanted N growth | range impact report |
| P7 serialization | submission adapter/validator | Add deterministic duplicate/locator/derived-doc checks to recovery report; do not change submission schema | submission contract and replay | 1,012 unique valid records, zero validation/replay errors | validation report JSON |
| P8–P10 E2E | Existing CLI plus recovery evaluator | Run tests, manual-95 diagnostic and full 1,012 baseline/upgraded with identical snapshots | `make ci`, integration, strict validation/replay | All previous gates pass | paired JSONL/metrics, final run/package |
| P11 provenance/report | manifests and reports | Bind exact run, ZIP, SHA, HEAD/config/snapshot identities; do not upload without user-controlled credential/action | checksum verification | package reproducible and exact mapping recorded | final report/metrics/manifest/SHA |

## Stop conditions

- P0/P1 mismatch with frozen baseline: stop before behavior changes.
- No untouched held-out ranking gold: ranking candidate may be measured but not promoted.
- Binding preservation hurts answer replay or diagnostic precision: reject.
- Year-range patch expands noisy output or lowers Hit@10: rollback.
- Validation/replay error: no publishable ZIP.

## Planned decision vocabulary

Every result is labeled `MEASURED`, `DIAGNOSTIC`, `UNKNOWN` or
`NOT_MEASURED`. Final recommendation is exactly one of `PROMOTE`,
`PROMOTE WITH CAUTION`, `KEEP BASELINE`, `ROLLBACK` or `BLOCKED`.
