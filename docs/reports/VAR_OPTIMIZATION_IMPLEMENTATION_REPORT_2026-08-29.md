# VAR optimization implementation report — 2026-08-29

## 1. Kết luận

Plan đã được triển khai theo kiến trúc strangler, không thay composition root
Canonical V2 và không hạ promotion gate. Candidate được chọn:

- 1.012/1.012 records, validation errors = 0;
- 606 executable answers, tăng 21 so với current Canonical control 585;
- 606/606 clean replay, 0 mismatch/error;
- 0 existing Canonical numeric value bị thay đổi;
- local adjudicated Answer/Execution Accuracy `15/31 = 48,39%`, so với
  Canonical `14/31 = 45,16%`;
- không publish tự động vì independent promotion gold chưa đủ và Semantic
  source manifest vẫn `BLOCKED`.

Final experimental ZIP:
[`hybrid-safe-current-final-20bc8c1-20260829-01.zip`](../../artifacts/runs/answer/hybrid-safe-current-final-20bc8c1-20260829-01.zip),
SHA-256 `bc9bd017c595764c4f370f5c47a55cc5df1da09bae3983f676246dfb8ae587c6`.

Manifest:
[`manifest.json`](../../artifacts/runs/answer/hybrid-safe-current-final-20bc8c1-20260829-01/manifest.json).

## 2. Official baseline được map đúng theo raw JSON

Metric được định danh bằng `column_key`, không suy theo vị trí cột trong
screenshot bị cắt ngang.

| Metric | VAR 3770 | Top 1 |
|---|---:|---:|
| Execution Accuracy | 0,2589 | 0,7115 |
| Tables F2-macro | 0,3000 | 0,6120 |
| Docs F2-macro | 0,7086 | 0,9618 |
| Tables Precision | 0,2707 | 0,5928 |
| Tables Recall | 0,3435 | 0,6261 |
| Tables MRR5 | 0,3801 | 0,6514 |
| Docs Precision | 0,6349 | 0,9587 |
| Docs Recall | 0,7651 | 0,9678 |
| Docs MRR5 | 0,7885 | 0,9806 |
| Answer Accuracy | 0,2589 | 0,7115 |

Không có post-change official scorer result trong repository. Mọi số phía dưới
là local engineering evidence và không được gọi là official uplift.

## 3. Root cause đã xử lý

| Root cause | Thay đổi |
|---|---|
| Canonical generic path thiếu semantic operand contract | Dùng V3 `QuestionAST` + metric/source resolver + typed operand requests sau artifact boundary |
| Per-operand retrieval và global binding chưa đi vào candidate | Compose replay-verified V3 result theo từng QID thay vì switch toàn runtime |
| Không có attribution V2/V3 | Sinh `per_qid_attribution.jsonl` với route, margin, value drift và decision |
| Evidence dùng để execute bị trộn với scorer refs | V3 evidence CSV mang prefix `v3_`; scorer refs có policy riêng, evidence chính xác luôn đứng trước |
| Có thể promote bằng YAML hoặc thiếu margin | Missing margin fail-closed; publish đòi đồng thời policy eligible và source `PROMOTABLE` |
| Source artifact có thể drift khỏi manifest | Bind `run_id` và SHA-256 của `records.jsonl` cho cả Canonical/Semantic manifest |
| `BINDING_TIE` cao | Thêm opt-in Canonical table-order soft prior theo question; không hard-filter operand candidates |

## 4. Thành phần đã triển khai

- Governed composer:
  [`hybrid_v3.py`](../../src/text2pandas/application/usecases/hybrid_v3.py).
- CLI `hybrid-v3` và opt-in `shadow-v3 --canonical-table-priors`:
  [`main.py`](../../src/text2pandas/interface/cli/main.py).
- Question-scoped prior API:
  [`operand.py`](../../src/text2pandas/infrastructure/retrieval/operand.py).
- Policy loader:
  [`hybrid_policy.py`](../../src/text2pandas/infrastructure/semantic/hybrid_policy.py).
- Safe policy:
  [`hybrid_candidate_safe_v1.yaml`](../../configs/semantic/hybrid_candidate_safe_v1.yaml).
- Lookup value-change experiment:
  [`hybrid_candidate_lookup_v1.yaml`](../../configs/semantic/hybrid_candidate_lookup_v1.yaml).
- Architecture decision:
  [`ADR 0015`](../adr/0015-semantic-v3-artifact-level-strangler.md).

Canonical `run` command và default Semantic V3 retrieval không đổi.

## 5. Full-corpus A/B

### 5.1 Canonical và governed hybrid

| Run | Executable | Recovered | Existing value changed | Local correct / 31 | Full replay |
|---|---:|---:|---:|---:|---:|
| Current Canonical control | 585 | — | — | 14 | local emitted 14/14 |
| Hybrid-safe, no-prior V3 | **606** | **21** | **0** | **15** | **606/606** |
| Hybrid-safe, soft-prior V3 | 603 | 18 | 0 | 15 | 603/603 |

Q506 là local-gold improvement của safe candidate: Canonical abstain, V3 trả
đúng `9,073375473961` và replay khớp. Safe policy không làm mất local correct
case nào.

Lookup policy cho phép thay existing value bị loại: trên r5 nó làm local score
giảm `14/31 → 13/31`; Q339 bị đổi từ đúng `3.227,004714155` sang sai
`40,065474562`.

### 5.2 Soft-prior experiment

| Measurement | No prior | Canonical soft prior | Delta |
|---|---:|---:|---:|
| V3 OK | 362 | 396 | +34 |
| V3 abstain | 650 | 616 | -34 |
| `BINDING_TIE` | 121 | 85 | -36 |
| Old OK → same-value OK | — | 359 | — |
| Abstain → OK | — | 37 | — |
| OK → abstain | — | 3 | — |
| Same-OK value changes | — | 0 | — |

Prior đạt mục tiêu giảm tie nhưng không thắng end-to-end hybrid: Q191, Q683 và
Q852 chuyển từ OK thành tie; current-control recovery giảm `21 → 18`. Vì vậy
flag được giữ để tiếp tục experiment, không bật mặc định và không dùng cho ZIP
được chọn.

### 5.3 Local retrieval diagnostic

Đây là development gold 95 câu đã được dùng trong feature work, chỉ dùng để
debug direction; không đủ điều kiện promotion.

| Run | Table P | Table R | Table F2 | Table MRR5 | Docs F2 | Docs MRR5 |
|---|---:|---:|---:|---:|---:|---:|
| Current Canonical control | 0,4525 | 0,5160 | 0,4677 | 0,5526 | 0,7391 | 0,7851 |
| Selected hybrid-safe | **0,4595** | **0,5318** | **0,4808** | **0,5768** | **0,7567** | **0,8114** |

## 6. Bottleneck còn lại

Full V3 soft-prior run cho thấy terminal buckets lớn nhất:

| Reason | Count | Hướng xử lý đúng |
|---|---:|---|
| Reported metric requires review for derived operation | 162 | Human/source-grounded metric-family adjudication; không tự mở formula |
| Binding tie | 85 | Calibrate tie-break trên sealed evidence gold, bảo vệ 3 regressions |
| Metric source specificity required | 47 | Review source label/section specificity |
| Select-at-arg selected expression unresolved | 40 | Ordered two-metric gold + role binding |
| Select-at-arg rank expression unresolved | 21 | Rank operand gold + distinctness constraints |
| Binary operands unresolved | 20 | Per-role evidence adjudication |
| Money/percent dimension mismatch | 18 | Formula/unit contract review |

Không nên tiếp tục tăng top-K hoặc bật lookup replacement rộng. Hai việc đó
tăng coverage nhưng chưa chứng minh correctness.

## 7. Governance và promotion state

Final manifest xác nhận:

- source commit `20bc8c1032a0486ca579382d69a5c81cd43761d3`, `git_dirty=false`;
- policy `semantic-v3-hybrid-safe-v1`, `production_eligible=false`;
- Semantic source promotion `BLOCKED`;
- publication blockers:
  `POLICY_NOT_PRODUCTION_ELIGIBLE` và
  `SEMANTIC_SOURCE_NOT_PROMOTABLE:BLOCKED`;
- validation errors/warnings = 0/0;
- 606 executed, 606 matched, 0 replay errors.

Promotion vẫn cần sealed release tối thiểu 300 answer gold, 300 semantic gold,
300 ordered-evidence gold; AST exact ≥ 0,95; candidate recall ≥ 0,99; binding
exact ≥ 0,90; answer accuracy ≥ 0,80; held-out reranker gates và zero submission
error. Không metric thiếu nào được coi là pass.

## 8. Quyết định sử dụng

- Giữ Canonical V2 là production composition root.
- Dùng final ZIP như **leaderboard experiment candidate**, không gọi là
  production-promoted release.
- Không dùng lookup replacement policy.
- Không bật Canonical soft prior mặc định ở iteration này.
- Bước có ROI cao nhất tiếp theo là adjudicate 162 reported-derived cases và
  85 binding ties trên sealed evidence/answer gold; sau đó rerun cùng gate.
