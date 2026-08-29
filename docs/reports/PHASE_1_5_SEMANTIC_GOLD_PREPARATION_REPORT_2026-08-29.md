# PHASE 1.5 — INDEPENDENT SEMANTIC GOLD V2 PREPARATION REPORT

Ngày thực thi: 2026-08-29

Repository: Text2Pandas / team VAR

Trạng thái tổng: **BLOCKED — OPEN FOR INDEPENDENT REVIEW**

## 1. Implementation status

| Work package | Trạng thái | Evidence |
|---|---|---|
| WP0 — Freeze authority / contamination / protected surface | **PASS** | Source, snapshot và protected before/after đều đã verify |
| WP1 — Schema / vocabulary / guideline | **PASS** | Schema quan hệ, canonical frame, governance và negative tests đã pass |
| WP2 — Prediction-blind sampler / packet builder | **PASS** | 100 core + 20 diagnostic + 30 reserve, deterministic và immutable |
| WP3 — Calibration pilot | **BLOCKED** | A/B/C chưa được gán |
| WP4–WP10 | **NOT STARTED** | Bị cấm trong task này; phụ thuộc human gold đã seal |

Kết quả hợp lệ của task là packet prediction-blind sẵn sàng bàn giao cho ba
reviewer độc lập. Không có annotation, adjudication, gold sealing, Canonical V2
prediction hay semantic accuracy nào được tạo.

## 2. Baseline đã freeze

| Thành phần | Identity |
|---|---|
| Target semantic parser commit | `08907c362d440aeb51ac024aedccf75de98a2b0f` |
| WP0–WP2 hardened implementation commit | `e8d75044165424db65d686dc81e5778bf027b389` |
| Raw snapshot | `ca033190f2e9e99f` |
| A6 build | `c6887fb633374fad` |
| Retrieval index | `872ccb0dda9a2bb6` |
| Question source | `data/raw/btc/questions/questions.jsonl` |
| Question count | 1,012 |
| Duplicate QID | 0 |
| Question SHA-256 | `64a428d90a8c5ad5d36a397d2de3b6e3aa4e4c1224dcdcb118fe3a4fca056ff0` |

Active snapshot IDs khớp plan. Source checksum được kiểm trước sampling; tool sẽ
fail trước khi tạo output nếu count, checksum hoặc snapshot identity sai.

## 3. Protected production surface

11 protected files được fingerprint với ba trường `path`, `sha256`, `size` tại
hai authority:

- before: target parser commit `08907c3`;
- after: packet-preparation worktree tại implementation commit `e8d7504`.

Kết quả:

```text
before == after: true
comparison: byte-for-byte
protected_surface.json SHA-256:
804a3c081c0d3310aa8b010db94019d161134fbd57fe1af2cc75821dd4882b9a
```

Không có thay đổi trong parser, retrieval, reranker, selector, binder, planner,
executor, answer/evidence generation hoặc Semantic V3 public wiring.

## 4. Contamination ledger

Ledger mới ghi từng entry bằng đúng ba trường:

```text
qid
source
reason
```

| Chỉ số | Kết quả |
|---|---:|
| Unique contaminated QID | 259 |
| Provenance ledger entries | 325 |
| Eligible untouched universe | 753 |
| Contaminated QID trong headline core | 0 |

Năm nguồn gold/dev cũ cho union ban đầu 221 QID. Audit chi tiết theo task phát
hiện còn thiếu real-QID parser/retrieval regression, question-attested aliases,
tracked adjudication và known-development cohorts. Các provenance này được khóa
tại
[`semantic_gold_v2_known_development_qids.jsonl`](../../configs/evaluation/semantic_gold_v2_known_development_qids.jsonl),
đưa union đúng lên 259 QID. Không coi full-corpus runtime traces là contamination
label vì làm vậy sẽ loại cả 1,012 câu và không còn untouched universe.

Contamination asset SHA-256:
`e92d7dbc084a5ad19771db8b562617a1b9a8740a82ea8f0f0e5b39e9b9768503`.

Excluded-QID checksum:
`58e187982373e21c3347a365bdd3f46f401f72a536f1505189eee81288fde72d`.

## 5. Sampling result

| Cohort | Records | Policy |
|---|---:|---|
| `HEADLINE_CORE` | 100 | Equal-probability hash order, contamination-free |
| `DIAGNOSTIC_SUPPLEMENT` | 20 | Question-text-only proxies, strict primary precedence |
| `RESERVE` | 30 | Preselected and checksummed; not activated |
| Active blank templates | 120 | A/B/C each receive 120 records |
| Total preselected | 150 | Cohorts disjoint |

Selection algorithm:

```text
SHA256(seed + NUL + qid + NUL + question)
sort by selection_digest, then qid
```

Manifest chứa seed, source/eligible universe checksums, toàn bộ excluded QIDs và
checksum, cùng selected QID + digest cho từng cohort.

| Selection authority | SHA-256 |
|---|---|
| Source universe | `1bbfb6bc485698a2846d9af1cab12be6635ae28e5a8edf87e439fadf0995d16a` |
| Eligible universe | `c3b73c7087e23d6bb400086e14e7ac394cad093a71cf0076bde77f11dd05cc8f` |
| Excluded QIDs | `58e187982373e21c3347a365bdd3f46f401f72a536f1505189eee81288fde72d` |

Diagnostic primary quota đều đạt, không có random top-up:

| Primary stratum | Selected / target | Available after precedence |
|---|---:|---:|
| `NESTED_COMPOSED` | 3 / 3 | 51 |
| `ARG_SELECT_PROJECT` | 3 / 3 | 42 |
| `DIVIDE_EXPLICIT_RATIO` | 4 / 4 | 27 |
| `SUBTRACT_DIRECTIONAL` | 3 / 3 | 76 |
| `GROWTH_PERCENT_CHANGE` | 2 / 2 | 40 |
| `MULTI_ENTITY_DIRECTIONAL` | 2 / 2 | 6 |
| `COUNT` | 1 / 1 | 6 |
| `BASIS_SENSITIVE` | 1 / 1 | 175 |
| `UNIT_SCALE_SENSITIVE` | 1 / 1 | 179 |

`selection_uses_predictions=false` và `model_outputs_included=false`.

## 6. Packet và hashes

Canonical packet:

```text
artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-01
```

Determinism reproduction:

```text
artifacts/runs/evaluation/semantic-gold-v2-packet-20260829-02-determinism
```

Manifest SHA-256 của cả hai packet:

```text
522e87ffcc79f399f82aca6511acd334d2ee2c6f390fc2e33dc46f49b8252eb3
```

| Asset | Records | SHA-256 |
|---|---:|---|
| `selection_core.jsonl` | 100 | `025207adce7fe694740ed92cce96a7b33c6bb59fbec706e0cd6888a866786f08` |
| `selection_diagnostic.jsonl` | 20 | `04b837305d11ae6f9dfd942012cc77f70cec76abd800d9af676b98fbd4bc0ab0` |
| `selection_reserve.jsonl` | 30 | `d7bc22729758de9284437a214a34028f127fe7f17d16b42ada95c4e78313a01f` |
| `annotator_a.jsonl` | 120 | `8ed070a90607f5db02ba04efb386eb34787db9455e24e953852745acf18fa71d` |
| `annotator_b.jsonl` | 120 | `c7e606eb951cdcc41961ce776dda5d0da3ff7b8b33f07a9e0f0b2d0591bd1a50` |
| `adjudication.jsonl` | 120 | `854bb8287106ecd65c49476fc68e42b8110a58c4a26352ace1fbb71ff16e312a` |
| `access_log.jsonl` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `coverage_matrix.json` | — | `ca65ca5d542f7136a61f8dca3f6457bf340ca359a3840c86368aecf370d29ac1` |
| `contamination_ledger.json` | — | `e92d7dbc084a5ad19771db8b562617a1b9a8740a82ea8f0f0e5b39e9b9768503` |
| `protected_surface.json` | — | `804a3c081c0d3310aa8b010db94019d161134fbd57fe1af2cc75821dd4882b9a` |

Hai packet giống nhau hoàn toàn theo `diff -qr`. Chạy lại prepare trên packet
`-01` đã tồn tại trả exit code 2 với `FileExistsError`; không file nào bị ghi đè.

## 7. WP1 contract đã hoàn thiện

- JSON Schema khóa status, basis, unit, output shape, operation, operand role,
  recursive operation tree và metric definition version.
- Pure relation validator kiểm Unicode NFC, zero-based half-open span,
  occurrence exact, ordering, reference integrity và operation/operand closure.
- Basis implicit chỉ hợp lệ với `UNSPECIFIED`; scale chỉ gắn với `MONEY`.
- Canonical frame được derive từ components, giữ ordered operands và tree-child
  order, bỏ reviewer metadata/notes/evidence locator và field `NOT_APPLICABLE`.
- Annotator không có trường manual `full_frame`.
- Reviewer A/B/C bắt buộc distinct; attestations và contract bindings phải đầy
  đủ, cùng version/checksum.
- Metric vocabulary tách surface phrase khỏi semantic concept, có definition,
  inclusion và exclusion examples; không dùng Silver row/VAS/table/observation
  identity làm concept authority.

## 8. Files changed

Implementation ban đầu `3941ce4` và hardening commit `e8d7504` tạo/hoàn thiện:

- [`Makefile`](../../Makefile);
- [`semantic_gold_v2_protocol.yaml`](../../configs/evaluation/semantic_gold_v2_protocol.yaml);
- [`semantic_gold_v2_sampling.yaml`](../../configs/evaluation/semantic_gold_v2_sampling.yaml);
- [`semantic_gold_v2_schema.json`](../../configs/evaluation/semantic_gold_v2_schema.json);
- [`semantic_metric_concepts_v1.yaml`](../../configs/evaluation/semantic_metric_concepts_v1.yaml);
- [`semantic_operation_vocabulary_v1.yaml`](../../configs/evaluation/semantic_operation_vocabulary_v1.yaml);
- [`semantic_gold_v2_known_development_qids.jsonl`](../../configs/evaluation/semantic_gold_v2_known_development_qids.jsonl);
- [`semantic_gold_v2.py`](../../src/text2pandas/application/usecases/semantic_gold_v2.py);
- [`prepare_semantic_gold_v2.py`](../../tools/evaluation/prepare_semantic_gold_v2.py);
- [`semantic_gold_v2/README.md`](../../data/curated/gold/semantic_gold_v2/README.md);
- [`test_semantic_gold_v2.py`](../../tests/unit/test_semantic_gold_v2.py);
- [`test_semantic_gold_v2_sampling.py`](../../tests/unit/test_semantic_gold_v2_sampling.py).

## 9. Verification results

| Gate | Result |
|---|---|
| Semantic Gold v2 + independent-gold targeted tests | **54 passed** |
| Full `make ci PY=/opt/anaconda3/bin/python` | **PASS** |
| Full offline pytest | **2,154 passed, 42 skipped, 29 deselected** |
| Ruff | **PASS** |
| Strict mypy / full typecheck | **86 source files — PASS** |
| Docs check | **67 Markdown files, 0 broken links** |
| `make snapshots-verify` | **PASS** |
| Draft 2020-12 JSON Schema | **360/360 A/B/C templates valid** |
| Packet byte determinism | **PASS; no diff** |
| Existing output immutability | **PASS; exit 2, no overwrite** |
| Protected surface before/after | **PASS; byte-identical** |
| `git diff --check` | **PASS** |

## 10. Outputs chưa được phép tạo

| Output | Status |
|---|---|
| Annotated semantic gold dataset | `NOT_CREATED` |
| Resolved / ambiguous / unresolved distribution | `NOT_ANNOTATED` |
| Inter-annotator agreement | `NOT_MEASURED` |
| Sealed gold SHA-256 | `NOT_CREATED` |
| Canonical V2 semantic metrics | `NOT_MEASURED` |
| Failure taxonomy | `NOT_MEASURED` |
| Parser vs Resolver boundary decision | `NOT_MEASURED` |
| Phase decision | `NOT_PERMITTED` |

Đây là trạng thái thật, không phải placeholder số và không được thay bằng nhãn
do model tự sinh.

## 11. Current blockers và exact next action

```text
INDEPENDENT_ANNOTATOR_A_UNASSIGNED
INDEPENDENT_ANNOTATOR_B_UNASSIGNED
DISTINCT_ADJUDICATOR_C_UNASSIGNED
```

Exact next action:

> Assign three independent reviewers A/B/C and run WP3 calibration pilot on
> 12–15 excluded QIDs. Do not generate Canonical V2 predictions before the
> semantic gold is sealed.

Final Phase 1.5 report và parser decision chỉ được tạo sau WP10 tại
`docs/reports/PHASE_1_5_SEMANTIC_GOLD_REPORT_<YYYY-MM-DD>.md`.
