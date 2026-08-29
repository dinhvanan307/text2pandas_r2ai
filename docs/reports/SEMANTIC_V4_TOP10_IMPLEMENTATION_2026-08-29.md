# Semantic V4 top-10 implementation report — 2026-08-29

## Kết luận

Candidate `submission-v4-hybrid-20260829-r4` đạt local governed proxy:

- answer accuracy: `0.5483870967741935` (`17/31`);
- execution accuracy: `0.5483870967741935` (`17/31`);
- tăng `0.09677419354838707` so với Canonical V2;
- không regression cả 8 retrieval metrics;
- không thay bất kỳ numeric answer nào đã có của Canonical V2;
- package có 1.012 records, validation `0` error/`0` warning và replay
  `604/604` matched.

Mục tiêu local `>= 0.5` đã đạt. Đây không phải cam kết official leaderboard vì
competition hidden gold và tolerance chính thức không được công bố.

## Thay đổi kiến trúc

### Temporal cohort program synthesis

Parser có grammar tổng quát cho hai họ câu:

1. lọc entity có metric dương/âm trong **mọi period**, sau đó tính tăng trưởng
   metric khác và aggregate theo entity;
2. lọc entity có tăng trưởng metric dương/âm, sau đó tính thay đổi formula và
   aggregate theo entity.

AST dùng `QuantifiedPredicate(ALL, PERIOD)`, `Arithmetic(GROWTH)` và
`Arithmetic(SUBTRACT)`. Năm trong câu được giữ là scope marker, không còn bị
parse thành numeric threshold.

Execution layer hỗ trợ vectorized alignment theo shared entity/period axis.
Typed executor và generated pandas program dùng cùng unit algebra, bao gồm
conversion `ratio <-> percent_point`.

### Fact provenance và reranking

- Currency gắn trực tiếp vào row/column path được ưu tiên hơn document-level
  currency khi local evidence chỉ ra đúng một currency. Conflicting local
  evidence không override.
- Candidate thuộc segment/component reporting bị penalty khi question không
  yêu cầu component scope. Explicit component qualifiers tắt penalty.
- Verifier cho phép cùng một observation phục vụ nhiều AST consumers chỉ khi
  chúng trỏ tới cùng semantic fact `(metric, entity, period)`; reuse khác fact
  vẫn bị chặn.

Không có QID-specific branch hoặc answer hardcode.

### Hybrid safety policy

Semantic V4 chỉ được phép recover Canonical V2 abstention. Policy khóa
`replace_legacy_value: false`, nên 87 V4/legacy value disagreements trong shadow
run không thể đi vào submission.

Hybrid result:

- promoted V4: `47`;
- recovered abstentions: `47`;
- changed legacy values: `0`;
- executable records: `604`;
- no-evidence records: `408`.

## Verification evidence

### Automated tests

```text
make PY=.venv/bin/python ci
2228 passed, 42 skipped, 29 deselected
ruff: pass
mypy --strict: pass (104 source files)
markdown links: 85 files, 0 broken links

pytest -m integration
29 passed, 2270 deselected
```

Synthetic benchmark có end-to-end cases cho temporal all-period predicate,
growth projection và formula change projection. Active A6 smoke xác nhận:

- q483: `4.1889988418160178%`, khớp local gold;
- q576: `3.9172954844846888` percentage points, khớp local gold.

### Full corpus shadow

Run: `semantic-v4-full-20260829-r2`

```text
questions:             1012
V4 OK:                  297
V4 abstain:             715
replay mismatches:        0
NO_VERIFIED_PROGRAM:     519
ANSWER_DISAGREEMENT:     176
CONFIDENCE_BELOW:         20
runtime:             714.837s
source commit: 737d6ef9a8ce0643280ae87b59ce17dec534debc
source dirty: false
```

Pure V4 package có 1.012/1.012 records, validation `0` errors và replay
`297/297` matched.

### Competition proxy

Report:
[`competition-proxy-v4-hybrid-vs-canonical-20260829-r4.json`](../../artifacts/reports/evaluation/competition-proxy-v4-hybrid-vs-canonical-20260829-r4.json)

| Metric | Candidate | Delta vs Canonical |
|---|---:|---:|
| Execution accuracy | 0.5483870968 | +0.0967741935 |
| Tables F2 macro | 0.3840172683 | 0 |
| Docs F2 macro | 0.6696471492 | 0 |
| Tables precision | 0.4399456976 | 0 |
| Tables recall | 0.3775898079 | 0 |
| Tables MRR@5 | 0.4921052632 | 0 |
| Docs precision | 0.7176697279 | 0 |
| Docs recall | 0.6624394319 | 0 |
| Docs MRR@5 | 0.7938596491 | 0 |
| Answer accuracy | 0.5483870968 | +0.0967741935 |

Improved local-gold QIDs: `483`, `506`, `576`. Regressed QIDs: none.

## Submission handoff

Upload file:
[`submission.zip`](../../artifacts/handoffs/submission-v4-hybrid-20260829-r4-final/submission.zip)

```text
SHA-256: 179d2c10425c96d55304183e27c5326b5bd2072d8d02fe74e211d23df3a060ad
records: 1012
validation errors/warnings: 0/0
replay: 604/604 matched, 0 errors, 0 mismatches
release class: experimental manual leaderboard candidate
```

Lineage và checksums nằm trong
[`HANDOFF.json`](../../artifacts/handoffs/submission-v4-hybrid-20260829-r4-final/HANDOFF.json)
và
[`SHA256SUMS`](../../artifacts/handoffs/submission-v4-hybrid-20260829-r4-final/SHA256SUMS).

## Phần chưa thể hoàn tất nội bộ

1. **Official score chưa thể xác nhận:** hidden competition gold chỉ có sau khi
   upload. Bước xử lý: upload ZIP, lưu submission ID và toàn bộ 10 metrics vào
   `refs/`, rồi chạy comparison report với candidate manifest này.
2. **Production promotion vẫn blocked:** chưa có sealed semantic/answer/evidence
   gold release theo promotion policy. Bước xử lý: tạo label release độc lập,
   chạy `semantic-promotion-eval`, và chỉ đổi policy sang production khi tất cả
   gates đạt.
3. **Leaderboard upload chưa tự động hóa:** repository không có credential/API
   upload. Bước xử lý: upload thủ công đúng file trong handoff; không đổi tên hay
   rebuild ZIP sau khi đã ghi checksum.

Các blocker này không ngăn việc submit candidate experimental để đo official
leaderboard; chúng chỉ ngăn tuyên bố production-promoted hoặc bảo đảm official
score trước khi có kết quả chấm.
