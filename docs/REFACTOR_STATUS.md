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
- Reviewed formula engine cho 8 công thức tài chính (`debt/current/quick ratios`,
  margins và intensities): bind từng metric leaf, quy đổi unit trước phép toán,
  bắt buộc operands cùng report/currency, sandbox execution và fail-closed với
  công thức chưa review. Answer pool mặc định 50 bảng để không cắt mất operand
  hợp lệ ở các báo cáo ngân hàng phân mảnh.

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
- Raw/A6/retrieval identity and lineage: green for the active local snapshots.
- H0 materialized integration: green trên active local materialization (`22/22`).
  Adjudication ledger được dẫn xuất từ 34 record có provenance
  `A6_DEFECT_FIXED`; determinism report được tạo từ hai clean package builds bằng
  `make materialize-h0`.
- Phase 6 removal/tagging: pending compatibility-window sign-off.
