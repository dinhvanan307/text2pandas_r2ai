# MODEL_SEMANTIC_GOLD_V1 — PARTIAL CHECKPOINT

## 1. Kết luận

Generation đã được dừng thủ công và **không được resume** trong lần checkpoint này.

Tại thời điểm chốt `2026-08-29T13:01:03Z` (`2026-08-29 20:01:03 +07`), run có **71/150 completed records**. Toàn bộ 71 record đã qua kiểm định schema và semantic contract; không có record lỗi, QID trùng hoặc QID nằm ngoài frozen selection.

Trạng thái release là **`PARTIAL_CHECKPOINT / NOT_SEALED`**. Không tạo hoặc seal gold release từ dữ liệu chưa đủ 150 record.

## 2. Số liệu checkpoint

| Chỉ tiêu | Kết quả |
|---|---:|
| Target records | 150 |
| Completed records thực tế | **71** |
| Tỷ lệ hoàn tất | **47.33%** |
| Chưa hoàn tất | 79 |
| Record hợp lệ | **71/71** |
| Record lỗi validation | 0 |
| QID trùng | 0 |
| QID ngoài frozen selection | 0 |

### Phân bố trạng thái

| `record_status` | Số lượng | Tỷ lệ trên completed |
|---|---:|---:|
| `RESOLVED` | **51** | 71.83% |
| `AMBIGUOUS` | **0** | 0.00% |
| `UNRESOLVED` | **20** | 28.17% |
| **Tổng** | **71** | **100.00%** |

Toàn bộ 20 `UNRESOLVED` có `status_reason = GENERATION_FAILURE`; các record này vẫn là completed records hợp lệ theo contract fail-closed.

### Phân bố cohort

| Cohort | Completed |
|---|---:|
| `HEADLINE_CORE` | 54 |
| `DIAGNOSTIC_SUPPLEMENT` | 7 |
| `RESERVE` | 10 |
| **Tổng** | **71** |

### Phân bố số lần thử của completed records

| `attempt_count` | Records |
|---:|---:|
| 1 | 38 |
| 2 | 12 |
| 3 | 21 |

## 3. Phạm vi validation

Validation được thực hiện chỉ-đọc trên từng file trong `records/` và bao gồm:

1. parse JSON;
2. đối chiếu tên file với `qid`;
3. xác nhận QID thuộc frozen 150-record selection;
4. validate JSON Schema của `MODEL_SEMANTIC_GOLD_V1`;
5. validate semantic contract bằng cùng validator của generation tool;
6. kiểm tra uniqueness của QID;
7. đối chiếu `generation_state.json` với protocol, selection digest, contract hashes và model identity hiện hành;
8. parse toàn bộ raw-attempt JSON để xác nhận audit trail không bị hỏng.

Kết quả: **PASS cho cả 71 completed records**. `generation_state` khớp hoàn toàn frozen contract và cả 203 raw-attempt files đều parse được.

Không chạy lệnh generator, không gọi model và không dùng full-release validator đòi đủ 150 record trong quá trình checkpoint.

## 4. Candidate đang dở và raw audit trail

QID **539** không có completed record. Thư mục raw attempts chứa response và validation-error artifacts cho attempts 1 và 2, nhưng không có `records/0539.json`.

Theo chỉ đạo dừng thủ công:

- không promote bất kỳ candidate nào của QID 539;
- không tạo record `UNRESOLVED` thay thế;
- không xóa hai raw responses hoặc hai error artifacts;
- không bắt đầu attempt tiếp theo;
- giữ QID 539 ở trạng thái incomplete để có thể resume trong một task sau nếu được yêu cầu rõ ràng.

## 5. Artifact được bảo toàn

Run directory:

`artifacts/runs/evaluation/model-semantic-gold-v1-generation-20260829-02`

| Artifact | Inventory / SHA-256 |
|---|---|
| `generation_state.json` | `b306c8fc96a818ce8da7162afac14976636224572b33f074ebd506df942f3a8d` |
| Completed record files | 71 |
| Aggregate completed-record fingerprint | `e6cb4bdc1e011ef45cd04abab249118d18d9f94ce8d43e93b63e10d215ee0af2` |
| Raw-attempt files | 203 = 127 response files + 76 error files |
| Aggregate raw-attempt fingerprint | `88e8037c329264178ac61a2db098a998131ee8708057e8180ddfea1a05c9539d` |
| Machine-readable checkpoint | `PARTIAL_CHECKPOINT.json` |

Aggregate fingerprints được tính từ danh sách đã sort theo tên file, mỗi dòng gồm SHA-256 của nội dung và tên file. Chúng dùng để kiểm tra artifact không đổi khi resume về sau.

`generation_state.json`, 71 completed records và 203 raw-attempt files được giữ nguyên. Checkpoint chỉ bổ sung báo cáo, không sửa hoặc rollback các artifact generation hiện có.

## 6. Completed QIDs

```text
14, 17, 22, 23, 25, 27, 34, 37, 38, 40, 44, 66, 70, 71, 73, 74,
79, 90, 104, 108, 109, 117, 159, 174, 180, 183, 184, 186, 192, 197,
206, 219, 239, 240, 243, 247, 249, 251, 254, 264, 275, 277, 278, 287,
294, 299, 300, 301, 325, 326, 341, 345, 365, 369, 391, 403, 417, 427,
440, 452, 455, 459, 472, 480, 487, 489, 505, 521, 522, 524, 526
```

## 7. Quyết định kết thúc task

- Generation: **STOPPED**.
- Resume/generate thêm QID: **KHÔNG THỰC HIỆN**.
- Completed records: **GIỮ NGUYÊN 71**.
- Candidate dở của QID 539: **RAW ONLY, NOT COMMITTED**.
- Gold release: **NOT SEALED**.
- Khả năng resume về sau: **ĐƯỢC BẢO TOÀN** nhờ giữ nguyên `generation_state` và raw attempts.

Checkpoint được lập trên tool commit `b08643892d589817b42420480058cf86c92afe71`.
