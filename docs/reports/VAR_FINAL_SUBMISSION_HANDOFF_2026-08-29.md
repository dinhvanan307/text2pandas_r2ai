# VAR final submission handoff — 2026-08-29

## 1. Kết quả bàn giao

Toàn bộ phần có thể triển khai bằng code trong optimization plan đã hoàn tất.
Gói gửi leaderboard đã được materialize riêng, kiểm tra lại từ ZIP sạch và sẵn
sàng upload thủ công:

- ZIP: [`submission.zip`](../../artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/submission.zip)
- SHA-256: `bc9bd017c595764c4f370f5c47a55cc5df1da09bae3983f676246dfb8ae587c6`
- Candidate run: `hybrid-safe-current-final-20bc8c1-20260829-01`
- Records: `1.012`
- Executable/replay: `606/606`, mismatch `0`, error `0`
- Submission validation: error `0`, warning `0`
- Trạng thái: `READY_FOR_MANUAL_LEADERBOARD_UPLOAD_EXPERIMENTAL`

Upload đúng file trong handoff, không upload ZIP ở thư mục run hoặc toàn bộ thư
mục handoff. Metadata và checksum nằm tại
[`HANDOFF.json`](../../artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/HANDOFF.json)
và
[`SHA256SUMS`](../../artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/SHA256SUMS).

## 2. Các phần đã triển khai hoàn chỉnh

| Workstream | Kết quả |
|---|---|
| Governed hybrid composer | Candidate tăng executable `585 → 606`, không thay numeric value đã có của Canonical |
| Safe policy và fail-closed promotion | Không thể promote bằng config khi thiếu metric/gold/source eligibility |
| Deterministic packaging | ZIP timestamp cố định, checksum khóa, `submission.json` + evidence CSV đầy đủ |
| Clean replay | Re-execute toàn bộ 606 answer từ gói, khớp 606/606 |
| Human diagnostic backlog | Packet 300 QID, gồm 247 priority failure và 53 deterministic filler |
| Independent semantic gold | Packet 300 QID prediction-blind, audit completeness và immutable sealer |
| Semantic promotion evaluator | Chấm AST, candidate recall, binding exact, answer accuracy, reranker và submission gates |
| Reranker held-out | Packet A/B/C 120 QID prediction-blind, sealer, one-shot paired A/B evaluator |
| Traceability | V3 trace-ready run chứa candidate observation/table UID cho recall và binding audit |
| Operational interface | Make targets cho prepare, audit, seal, evaluate và submission handoff |

Các artifact vận hành:

- Diagnostic review:
  [`semantic-v3-failure-review-20260829-v1`](../../artifacts/runs/evaluation/semantic-v3-failure-review-20260829-v1/manifest.json)
- Independent semantic packet:
  [`independent-gold-v1-packet-20260827`](../../artifacts/runs/evaluation/independent-gold-v1-packet-20260827/manifest.json)
- Semantic completeness audit:
  [`independent-gold-v1-completeness-20260829.json`](../../artifacts/reports/evaluation/independent-gold-v1-completeness-20260829.json)
- Reranker review packet:
  [`reranker-heldout-v1-review-packet-20260829`](../../artifacts/runs/evaluation/reranker-heldout-v1-review-packet-20260829/manifest.json)
- Trace-ready V3 run:
  [`semantic-v3-promotion-trace-e920483-20260829-01`](../../artifacts/runs/semantic-v3/semantic-v3-promotion-trace-e920483-20260829-01/manifest.json)

## 3. Phần chưa thể hoàn tất trong code

| Dependency | Trạng thái hiện tại | Lý do không tự động hóa/giả lập |
|---|---:|---|
| Independent semantic annotation | A `0/300`, B `0/300`, adjudication `0/300` | Promotion protocol bắt buộc ba reviewer độc lập, có source review và attestation; model không được tự sinh nhãn để tự chấm |
| Reranker evidence annotation | `0/120`, packet đang mở | One-shot held-out phải prediction-blind; dùng development/model output làm gold sẽ gây leakage |
| Official leaderboard score | Chưa có post-change result | Official scorer và credentials nằm ngoài repository; local metric không được trình bày như official uplift |

Đây là external evidence gap, không phải code gap. Hệ thống cố ý trả
`BLOCKED_PENDING_HUMAN_REVIEW`/exit code khác 0 cho đến khi đủ dữ liệu thật.

## 4. Runbook hoàn tất promotion evidence

Chạy các lệnh từ repository root với `PY=.venv/bin/python`.

### 4.1 Independent semantic gold — 300 QID

1. Reviewer A điền `annotator_a.jsonl`, reviewer B điền
   `annotator_b.jsonl`; cả hai không xem model output.
2. Reviewer C xử lý disagreement trong `adjudication.jsonl`.
3. Mỗi record phải có reviewer identity, independence attestation, source
   evidence review và đầy đủ semantic/answer/evidence labels theo template.
4. Audit:

```bash
make independent-gold-audit PY=.venv/bin/python \
  PACKET=artifacts/runs/evaluation/independent-gold-v1-packet-20260827 \
  OUTPUT=artifacts/reports/evaluation/independent-gold-v1-completeness-final.json
```

5. Chỉ khi audit `sealable=true`, tạo immutable release:

```bash
PYTHONPATH=src .venv/bin/python tools/evaluation/seal_independent_gold.py \
  --packet artifacts/runs/evaluation/independent-gold-v1-packet-20260827 \
  --output artifacts/releases/evaluation/independent-gold-v1-final \
  --release-id independent-gold-v1-final
```

### 4.2 Reranker held-out evidence gold — 120 QID

1. Reviewer A/B/C điền ba file trong
   `artifacts/runs/evaluation/reranker-heldout-v1-review-packet-20260829`.
2. Ba identity phải khác nhau và ổn định trên toàn cohort; mỗi reviewer phải
   attest independence và xác nhận đã xem source evidence.
3. Với mọi khác biệt giữa A/B/final C, C phải đặt
   `reviewed_disagreement=true`.
4. Seal:

```bash
make reranker-review-seal PY=.venv/bin/python \
  PACKET=artifacts/runs/evaluation/reranker-heldout-v1-review-packet-20260829 \
  OUTPUT=artifacts/releases/evaluation/reranker-heldout-v1-final \
  RELEASE_ID=reranker-heldout-v1-final
```

5. Chạy one-shot A/B:

```bash
make reranker-heldout-eval PY=.venv/bin/python \
  LABELS=artifacts/releases/evaluation/reranker-heldout-v1-final/heldout_v1_gold.jsonl \
  LABEL_MANIFEST=artifacts/releases/evaluation/reranker-heldout-v1-final/heldout_v1_gold_manifest.json \
  OUTPUT=artifacts/reports/reranker-linear-v1-heldout-ab-final.json
```

### 4.3 Promotion gate

```bash
make semantic-promotion-eval PY=.venv/bin/python \
  RECORDS=artifacts/runs/semantic-v3/semantic-v3-promotion-trace-e920483-20260829-01/records.jsonl \
  GOLD_RELEASE=artifacts/releases/evaluation/independent-gold-v1-final \
  SUBMISSION_HANDOFF=artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/HANDOFF.json \
  RERANKER_REPORT=artifacts/reports/reranker-linear-v1-heldout-ab-final.json \
  OUTPUT=artifacts/reports/evaluation/semantic-v3-promotion-final.json
```

Chỉ thay production composition/policy khi report trả `promotable=true`. Không
hạ threshold, không coi missing metric là pass và không dùng diagnostic packet
làm promotion gold.

## 5. Leaderboard submission

1. Kiểm checksum ngay trước upload:

```bash
shasum -a 256 artifacts/handoffs/VAR-submission-hybrid-safe-20260829-v1/submission.zip
```

2. Upload file `submission.zip` từ handoff lên leaderboard.
3. Lưu submission ID, timestamp và đủ 10 official metrics: Execution Accuracy,
   Tables F2/P/R/MRR5, Docs F2/P/R/MRR5, Answer Accuracy.
4. So sánh với VAR submission `3770`; không suy metric từ vị trí cột hoặc
   screenshot bị crop.
5. Nếu official score regression, giữ Canonical V2 và candidate hiện tại để
   forensic; không overwrite artifact hay chạy lại cùng run ID.

## 6. Quyết định release

- `submission.zip` sẵn sàng cho một **leaderboard experiment**.
- Candidate chưa phải production-promoted Semantic V3 vì policy/source vẫn có
  blockers `POLICY_NOT_PRODUCTION_ELIGIBLE` và
  `SEMANTIC_SOURCE_NOT_PROMOTABLE:BLOCKED`.
- Các blocker chỉ được gỡ bằng sealed independent evidence và gate result thật,
  không bằng chỉnh manifest thủ công.

## 7. Final verification

Quality gates chạy sau khi hoàn tất code và runbook:

- Ruff: pass.
- Mypy: pass, 93 source files.
- Markdown links: 84 files, 0 broken links.
- Offline suite: 2.179 passed, 42 skipped, 29 deselected.
- Integration suite: 22 passed, 2.228 deselected.
- Raw/A6/retrieval snapshot lineage: tất cả checks pass.
- ZIP integrity: `unzip -t` không có lỗi.
- ZIP SHA-256 sau cùng vẫn là
  `bc9bd017c595764c4f370f5c47a55cc5df1da09bae3983f676246dfb8ae587c6`.
