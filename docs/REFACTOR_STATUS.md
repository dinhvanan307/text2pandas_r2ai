# Folder refactor status

Updated: 2026-08-26

## Completed

- Git baseline and pre-move checksums for raw BTC, A6 and retrieval.
- Canonical physical layout: `raw → processed/a6 → indexes/retrieval`.
- Central `ProjectPaths`, environment root overrides and reviewed active snapshot.
- Machine-readable manifests and committed provenance identities.
- Runtime path migration; no active hard-code to the former external locations.
- Canonical `text2pandas.pipelines.{a6,retrieval,answering}` namespaces.
- Retrieval experiments separated from reusable tooling.
- Reviewed evaluation fixtures moved to `data/curated/evaluation`.
- Unified CLI snapshot verifier and reproducible Make/CI offline gates.
- Offline suite separated from materialized H0 integration gates.
- Canonical answering runtime đọc trực tiếp active A6 + retrieval snapshots,
  dùng immutable run directory và machine-readable lineage manifest.
- Submission ZIP deterministic, strict schema/grounding validation, AST-restricted
  replay và fail-closed publish policy.
- Typed period extrema (`MAX/MIN/ARGMAX/ARGMIN`) với guards cho metric drift,
  signed extrema, filtered/derived ranking và select-at-arg chưa hỗ trợ.
- Reviewed formula engine cho 16 công thức tài chính (`debt/current/quick ratios`,
  margins, ending-assets return, current-liabilities/equity, SG&A và expense
  intensities, fixed-assets/total-assets): bind từng metric leaf, quy đổi unit trước phép toán,
  bắt buộc operands cùng report/currency, sandbox execution và fail-closed với
  công thức chưa review. Answer pool mặc định 50 bảng để không cắt mất operand
  hợp lệ ở các báo cáo ngân hàng phân mảnh.
- Typed period COUNT cho threshold/negative predicates với explicit years,
  reviewed metric aliases, safe comparison AST và existence questions fail-closed
  khi chưa có negative-evidence completeness contract.
- Entity resolver giữ full legal-name evidence khi short brand bị nested trong
  tên counterparty, nhận diện `hiệu số` là comparison; coverage không còn đánh
  tráo 11 câu multi-entity và 1 select-at-arg thành alias mismatch.
- Resolver P0-d dùng word-boundary aliases, hợp nhất explicit ticker với
  company-name evidence và giữ đủ hai vế của directional comparisons; 6 known
  strict xfails đã thành regression passes.
- Typed absolute difference cho đúng 2 entity, 1 kỳ và 1 metric với distinct
  evidence, same-metric policy, reviewed cross-label aliases và share-count
  scaling (`nghìn/triệu/tỷ cổ phiếu`).
- Typed entity COUNT cho one-metric sign/threshold predicate trên explicit
  entity set; compound multi-metric/scenario predicates tiếp tục fail-closed.
- Typed entity average cho reviewed direct monetary/share metrics trên explicit
  entity set; metric registry bắt buộc, distinct-cell evidence và per-operand
  unit conversion. Percent/ratio, cohort filters và unreviewed metrics tiếp tục
  fail-closed.
- Static semantic coverage contract cho đủ 1.012 câu, có corpus digest, per-QID
  reason code, CLI/Make entry point và CI baseline. Scope được ghi rõ là route
  coverage, không đánh tráo với retrieval/binding/answer accuracy.

## Intentionally retained

- Compatibility shims for `data_pipeline`, `retrieval` and
  `text2pandas.answer_pipeline`. Remove after a downstream-import deprecation window.
- Legacy tools and test-local `sys.path` bridges that load historical scripts.
  Production source no longer imports `tools`; converting all historical tools is
  a separate behavior-sensitive cleanup.
- Retrieval is still a full A6-derived SQLite copy. A sidecar-only redesign is a
  storage/behavior change and requires ordered-result parity before migration.
- Generated legacy artifacts remain locally available but ignored; no destructive
  cleanup was performed during the layout migration.

## Current gates

- Offline: green.
- Static semantic route: `644/1.012` eligible (`63,6364%`), `368` named gaps;
  baseline được khóa trong offline suite.
- Raw/A6/retrieval identity and lineage: green for the active local snapshots.
- H0 materialized integration: green trên active local materialization (`22/22`).
  Adjudication ledger được dẫn xuất từ 34 record có provenance
  `A6_DEFECT_FIXED`; determinism report được tạo từ hai clean package builds bằng
  `make materialize-h0`.
- Phase 6 removal/tagging: pending compatibility-window sign-off.
