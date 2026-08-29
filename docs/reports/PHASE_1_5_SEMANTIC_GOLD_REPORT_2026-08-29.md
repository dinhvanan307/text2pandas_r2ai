# PHASE 1.5 Semantic Gold V2 — LOCAL_SYNTHETIC E2E Report

> [!WARNING]
> Evaluation mode: **LOCAL_SYNTHETIC**. Independent human annotation: **NOT PERFORMED**. Independent adjudication: **NOT PERFORMED**. Official submission validity: **NOT VALID**. Purpose: **LOCAL END-TO-END PIPELINE VALIDATION**.

## 1. Executive Summary

WP3–WP10 đã chạy hết bằng nhánh local riêng, không thay đổi production parser và không ghi synthetic data vào official gold registry. Local E2E đạt gate schema/provenance/determinism/protected-surface; kết quả accuracy chỉ mô tả hành vi so với automated ontology-derived reference.

- Local decision: `PASS_LOCAL_E2E_ONLY`
- E2E determinism: `PASS` (12 artifacts byte-identical)
- Protected production surface: `PASS`, before == after == target commit
- Active records: `120`; resolved synthetic records: `30`; unresolved: `90`
- Official submission: `BLOCKED` until genuine independent A/B/C work replaces all automated annotations.

## 2. Implementation and Files Changed

Implemented a fail-closed local mode, deterministic ontology-exact synthetic annotator, honest Canonical V2 pre-bind exporter, strict evaluator, Wilson CI, failure taxonomy, parser/resolver boundary report, protected-surface verifier, and two-run orchestration.

Tracked implementation files:

- `configs/evaluation/semantic_gold_v2_local_synthetic.yaml`
- `src/text2pandas/application/usecases/semantic_gold_v2_local.py`
- `tools/evaluation/run_semantic_gold_v2_local_e2e.py`
- `tests/unit/test_semantic_gold_v2_local.py`
- `Makefile`
- `docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_2026-08-29.md`

Generated local artifacts:

- `artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-20260829-44a3892-a`
- `artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-20260829-44a3892-b`

No artifact was written to `data/curated/gold/semantic_gold_v2`, and `gold_registry_v1.yaml` was not updated.

## 3. Dataset, Provenance, and Validation

```text
gold_mode=LOCAL_SYNTHETIC
annotation_source=AUTOMATED
independent_review=false
human_adjudication=false
official_submission_ready=false
```

Source packet: `artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-01`. Headline 100 and diagnostic 20 were used; reserve support is implemented but not activated.

| Validation gate | Result |
|---|---:|
| schema | PASS |
| unicode_nfc | PASS |
| span_occurrence_ordering | PASS |
| reference_integrity | PASS |
| operation_operand_closure | PASS |
| basis_contract | PASS |
| unit_scale_contract | PASS |
| canonical_frame_derivation | PASS |
| vocabulary_membership | PASS |

Synthetic status distribution: `RESOLVED=30`, `UNRESOLVED=90`. `UNRESOLVED` records are reported, never force-labeled.

Field-level coverage:

| Semantic field | RESOLVED | UNRESOLVED | NOT_APPLICABLE |
|---|---:|---:|---:|
| entities | 116 | 4 | 0 |
| metrics | 50 | 70 | 0 |
| periods | 120 | 0 | 0 |
| basis | 120 | 0 | 0 |
| unit | 105 | 15 | 0 |
| operation_tree | 120 | 0 | 0 |
| output | 120 | 0 | 0 |
| operands | 35 | 85 | 0 |

## 4. WP3–WP10 Execution

| WP | Local result | Exact substitute/action |
|---|---|---|
| WP3 | PASS_LOCAL_SYNTHETIC_EQUIVALENT | Contract calibration + full validation |
| WP4 | PASS_LOCAL_SYNTHETIC_EQUIVALENT | One automated annotation pass over 100+20 |
| WP5 | COMPLETED_AS_NOT_APPLICABLE | No fake human agreement metric |
| WP6 | COMPLETED_AS_NOT_APPLICABLE | No fake human adjudication |
| WP7 | PASS_LOCAL_ARTIFACT_FROZEN | Checksummed local artifact; not official SEALED gold |
| WP8 | PASS | Frozen Canonical V2 public pre-bind export |
| WP9 | PASS | Strict metrics + taxonomy + boundary attribution |
| WP10 | PASS | This local-only decision report |

## 5. Parser Metrics

Strict metrics score only `record_status=RESOLVED`; `NOT_APPLICABLE` is excluded and an applicable missing prediction is wrong. These figures are not human-validated accuracy.

### HEADLINE_CORE

Resolved/scored population: `25/100`.

| Metric | Correct | Scored | Skipped | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|---:|---:|
| Entity Reference Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Metric Phrase Exact Match | 0 | 25 | 75 | 0.00% | 0.0000–0.1332 |
| Metric Concept Accuracy | 0 | 25 | 75 | 0.00% | 0.0000–0.1332 |
| Period Exact Match | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Period Role Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Basis Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Unit Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Operation Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Result Kind Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Operand Count Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Operand Role Accuracy | 25 | 25 | 75 | 100.00% | 0.8668–1.0000 |
| Operand Metric Accuracy | 0 | 25 | 75 | 0.00% | 0.0000–0.1332 |
| Operand Role+Metric Accuracy | 0 | 25 | 75 | 0.00% | 0.0000–0.1332 |
| Full Semantic Frame Exact | 0 | 25 | 75 | 0.00% | 0.0000–0.1332 |

### DIAGNOSTIC_SUPPLEMENT

Resolved/scored population: `5/20`.

| Metric | Correct | Scored | Skipped | Accuracy | Wilson 95% CI |
|---|---:|---:|---:|---:|---:|
| Entity Reference Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Metric Phrase Exact Match | 0 | 5 | 15 | 0.00% | 0.0000–0.4345 |
| Metric Concept Accuracy | 0 | 5 | 15 | 0.00% | 0.0000–0.4345 |
| Period Exact Match | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Period Role Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Basis Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Unit Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Operation Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Result Kind Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Operand Count Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Operand Role Accuracy | 5 | 5 | 15 | 100.00% | 0.5655–1.0000 |
| Operand Metric Accuracy | 0 | 5 | 15 | 0.00% | 0.0000–0.4345 |
| Operand Role+Metric Accuracy | 0 | 5 | 15 | 0.00% | 0.0000–0.4345 |
| Full Semantic Frame Exact | 0 | 5 | 15 | 0.00% | 0.0000–0.4345 |

Canonical V2 correctly exposes entity/period/basis/unit/operation/role structure on the resolved synthetic subset, but it has no public pre-bind metric phrase/concept output. Therefore metric concept, operand metric, and full-frame exact scores are zero rather than being backfilled from VAS hints.

## 6. Diagnostic-Stratum Performance

| Stratum | Records | Resolved | Full-frame correct/scored | Accuracy |
|---|---:|---:|---:|---:|
| ARG_SELECT_PROJECT | 3 | 1 | 0/1 | 0.00% |
| BASIS_SENSITIVE | 1 | 0 | 0/0 | NOT_MEASURABLE |
| COUNT | 1 | 1 | 0/1 | 0.00% |
| DIVIDE_EXPLICIT_RATIO | 4 | 1 | 0/1 | 0.00% |
| GROWTH_PERCENT_CHANGE | 2 | 0 | 0/0 | NOT_MEASURABLE |
| MULTI_ENTITY_DIRECTIONAL | 2 | 0 | 0/0 | NOT_MEASURABLE |
| NESTED_COMPOSED | 3 | 0 | 0/0 | NOT_MEASURABLE |
| SUBTRACT_DIRECTIONAL | 3 | 1 | 0/1 | 0.00% |
| UNIT_SCALE_SENSITIVE | 1 | 1 | 0/1 | 0.00% |

## 7. Failure Taxonomy

Failed resolved QIDs: `30`. Primary failures: `MISSING_OUTPUT=30`.

The dominant failure is deliberately `MISSING_OUTPUT`: Canonical V2 does not emit metric phrase/concept before binding. `failure_taxonomy.jsonl` retains secondary field mismatches and prediction-source provenance.

## 8. Parser vs Resolver Boundary

All measurable failures in this run are attributed at the parser boundary. Metric resolver, selector/binder, and downstream answer accuracy are `NOT_MEASURABLE`: the local packet contains no independent binding, answer, or evidence reference. VAS code hints were recorded diagnostically and were not promoted into concept predictions.

Boundary counts: `PARSER=30`.

## 9. Determinism and Production Safety

Two complete runs were created independently. The following artifact classes were compared byte-for-byte:

| Artifact | Run A SHA-256 | Run B SHA-256 | Identical |
|---|---|---|---:|
| selected_qids.json | `a74de18eaade2ac1d425989e23e04925bdc302fb91fc064e55b376e82582fe4e` | `a74de18eaade2ac1d425989e23e04925bdc302fb91fc064e55b376e82582fe4e` | PASS |
| annotator_local.jsonl | `8243e4a6528789d81b239c889ed198ed17152b759f6261cea505f3e11dcb1536` | `8243e4a6528789d81b239c889ed198ed17152b759f6261cea505f3e11dcb1536` | PASS |
| canonical_gold_frames.jsonl | `24e3a7c6c1bcbb659d9af01a8b816fd7f22c8f96f3c3c3a0d6a4a6540a437282` | `24e3a7c6c1bcbb659d9af01a8b816fd7f22c8f96f3c3c3a0d6a4a6540a437282` | PASS |
| parser_predictions.jsonl | `3b030fa539fa6ad92384732c6c7f3dd3a3c1fea3f4f6f53bb730d6f5c4931444` | `3b030fa539fa6ad92384732c6c7f3dd3a3c1fea3f4f6f53bb730d6f5c4931444` | PASS |
| canonical_prediction_frames.jsonl | `c793b41af17cc0c294b464b13ae2edf122dc137b51354576b6b9f0878dbbef3c` | `c793b41af17cc0c294b464b13ae2edf122dc137b51354576b6b9f0878dbbef3c` | PASS |
| metrics.json | `95b84c9c509d562b25926e533c4043dff1db38da15925101a84d09d26228bad2` | `95b84c9c509d562b25926e533c4043dff1db38da15925101a84d09d26228bad2` | PASS |
| failure_taxonomy.jsonl | `523096f106d444e4a07c8b855624591625c63272bbcd63bbb18440ee77a573cf` | `523096f106d444e4a07c8b855624591625c63272bbcd63bbb18440ee77a573cf` | PASS |
| resolver_boundary.json | `840c400e9791f63b6ceae080f0535bd978363059cba6cec4188dadcaa2570f98` | `840c400e9791f63b6ceae080f0535bd978363059cba6cec4188dadcaa2570f98` | PASS |
| validation.json | `0ad2f62c53f47de4dd862982bab9401345e562cea1eef610c6b8161c492d6605` | `0ad2f62c53f47de4dd862982bab9401345e562cea1eef610c6b8161c492d6605` | PASS |
| workflow.json | `1914cb0c58f9f29be910a9f87159be7e349f3073ebf898e0573398ca0d396e38` | `1914cb0c58f9f29be910a9f87159be7e349f3073ebf898e0573398ca0d396e38` | PASS |
| protected_surface.json | `de6eac34a3b0b53a9cb778935990d7de3153cd5bf92d16524607598facce5feb` | `de6eac34a3b0b53a9cb778935990d7de3153cd5bf92d16524607598facce5feb` | PASS |
| manifest.json | `bf31cba64a106ee2dc8e5f614820a1127f38b6244bd343b68da27066db56d367` | `bf31cba64a106ee2dc8e5f614820a1127f38b6244bd343b68da27066db56d367` | PASS |

`E2E_DETERMINISM=PASS`.

Protected parser/retrieval/answering files were hashed before and after both runs and compared with target commit `08907c362d440aeb51ac024aedccf75de98a2b0f`: `PASS`, byte-identical.

## 10. Tests and Reproduction

Primary reproduction command (use fresh explicit output IDs because run directories are immutable):

```bash
make semantic-gold-v2-local-e2e PY=/opt/anaconda3/bin/python \
  MODE=LOCAL_SYNTHETIC \
  PACKET=artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-01 \
  RUN_A=artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-<run-id>-a \
  RUN_B=artifacts/runs/evaluation/semantic-gold-v2-local-synthetic-<run-id>-b \
  REPORT=docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<date-or-run-id>.md
```

Verification completed:

- targeted Semantic Gold V2 tests: `57 passed`;
- full `make ci`: Ruff `PASS`, mypy `PASS` on 87 source files, docs `67` Markdown files / `0` broken links, pytest `2,162 passed`, `42 skipped`, `29 deselected`;
- active raw/A6/retrieval snapshot verification: `PASS`;
- protected diff against target parser commit: `PASS`;
- tracked Draft 2020-12 schema, semantic relation validation, canonical derivation, vocabulary membership, and two-run byte determinism: `PASS`.

## 11. Remaining Blockers

Local E2E has no remaining blocker. Official submission remains blocked by:

- independent annotator A not assigned/completed;
- independent annotator B not assigned/completed;
- distinct adjudicator C not assigned/completed;
- no human inter-annotator agreement or adjudication evidence;
- automated ontology matches are not official semantic gold;
- resolver/binding/answer correctness is not independently measured here.

## 12. Required Replacement Before Official Submission

Replace `annotator_local.jsonl` with schema-valid, source-evidence-backed independent A and B annotations; compute agreement before C; adjudicate every record with a distinct C; activate reserve if the resolved count is below the official minimum; seal a new immutable release; only then export predictions and rerun the same evaluator against that release. Synthetic artifacts must never be copied into the official gold directory or registry.

Exact next engineering task after human gold exists: implement a public pre-bind metric phrase/concept contract (without row-binding leakage), then measure it on the sealed independent release.
