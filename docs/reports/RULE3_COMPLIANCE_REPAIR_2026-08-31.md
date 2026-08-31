# Rule 3 compliance repair — 2026-08-31

## Kết luận

Candidate `rule3-3842-20260831-r1` đã qua gate tuân thủ quy định CSV/Pandas
query ở profile competition. Candidate này chưa đủ điều kiện tự động upload vì
còn 214 câu unresolved và chưa đo official answer accuracy.

## Scope và identity

- Baseline: `artifacts/official/submission-3842/submission.zip`
- Baseline SHA-256: `2a3457ee2af0b43ef849cc1a5e0d9c46c78cc94e34e560369796a02defa93d76`
- Source commit: `901267b6c2fcf71d21d5d2b3aaca2eeadc50e5be`
- Active A6 SHA-256: `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8`
- Repair ledger: `configs/evaluation/rule3_compliance_repair_3842_v1.json`

## Thay đổi

- 72 query được sửa: 51 query bỏ kết quả trung gian được mã hóa bằng
  `0 * data`, và 21 query trả năm được viết lại thành phép chọn `max` trực tiếp
  trên CSV.
- Sandbox từ chối query không có effective CSV dependency, query dùng
  zero-multiplier để giả tham chiếu dữ liệu, và query đọc cột kết quả lưu sẵn.
- Bộ sinh Semantic V5 không còn phát sinh zero-multiplier cho arg-period,
  select-at-arg, arg-key, true-key và top-k mask.
- Giữ nguyên 1.012 answer, 1.012 evidence object và toàn bộ 1.193 CSV payload.
- 351 QID được rebind `relevant_docs`/`relevant_tables` về đúng locator của các
  UID thực sự có trong CSV.

## Gate để review

1. Input identity: SHA của baseline, A6, questions và repair ledger phải khớp.
2. Static query gate: 0 query hằng, 0 zero-multiplier trên dữ liệu, 0 cột kết
   quả lưu sẵn.
3. Traceability gate: mọi dòng CSV phải khớp A6 UID/value/raw source hoặc xuất
   hiện nguyên văn trong bảng raw BTC được khai báo.
4. Preservation gate: answer/evidence/CSV payload không thay đổi; chỉ 72 query
   và locator nguồn được phép đổi.
5. Package gate: đúng 1 JSON ở root, mọi CSV ở `data/`, ZIP integrity pass,
   competition validation có 0 error.
6. Replay gate: 798/798 query thực thi phải khớp answer; 0 replay error; 214
   unresolved phải được báo riêng.
7. Determinism gate: hai build độc lập phải byte-identical.
8. Promotion gate: chỉ upload sau đánh giá độc lập; replay không được gọi là
   answer accuracy.

Lệnh tái tạo:

```bash
PYTHONPATH=src python tools/build_rule3_compliance_candidate.py \
  --run-id <new-immutable-run-id>
```

Các gate code đã chạy:

```bash
make lint typecheck
make test-offline
make test-integration
git diff --check
unzip -t artifacts/runs/rule3-compliance/rule3-3842-20260831-r1.zip
```

Kết quả: lint PASS; strict mypy PASS; offline 2.493 passed, 42 skipped;
integration 22 passed; ZIP integrity PASS. `make ci` dừng tại `docs-check` vì
15 link tới artifact lịch sử đã thiếu từ trước; lint và typecheck bên trong CI
đã PASS. Đây là blocker vệ sinh tài liệu, không được che giấu hoặc tính là
gate đã đạt.

## Candidate result

- ZIP SHA-256: `9024a29819714a220b3e6fe8d3c82a0a40f0dc3cd19e6b1ba4944680eac5e39f`
- Competition validation: 0 errors, 428 warnings do 214 câu unresolved.
- Clean replay: 798 executed, 798 matched, 0 errors.
- CSV traceability: 16.530/16.530 rows PASS.
- Determinism: PASS, two builds byte-identical.
- Complete profile: FAIL do 214 unresolved.
- Official answer accuracy: `NOT_MEASURED`.
