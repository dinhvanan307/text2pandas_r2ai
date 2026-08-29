# Review độc lập — TABLE RETRIEVAL F2 RECOVERY Implementation Report

**Ngày:** 2026-08-28 · Tài liệu được review: `TABLE_RETRIEVAL_F2_RECOVERY_IMPLEMENTATION_REPORT_2026-08-28.md`
**Reviewer:** audit độc lập (chuỗi 27-28/08)
**Phương pháp:** đối chiếu code, artifact, metrics JSON trên đĩa.

---

## 1. Verdict

```text
KẾT LUẬN:      ACCEPT — quyết định `KEEP BASELINE` là ĐÚNG, và đây là một
               null-result report trung thực hiếm có: không claim cải thiện,
               giữ negative result immutable, từ chối promote trên dev gold.

GIÁ TRỊ THẬT:  Không phải ở F2 (không đổi), mà ở chỗ LẦN ĐẦU TIÊN dự án có
               ATTRIBUTION ĐỊNH LƯỢNG cho tổn thất Table F2 — xác nhận bằng số
               điều audit 27/08 chỉ nói được định tính:
                 OUTPUT_N_LOSS 23 + BINDING_LOSS 10 = 33/41 ca mất gold
                 vs S2_RANK_LOSS chỉ 8, S1_LOSS = 0.
               ⇒ N policy (RET-005) và binding overwrite (RET-007) chính thức
               là hai đòn bẩy Table F2 lớn nhất, ranking chỉ đứng thứ ba.

NÚT THẮT:      Cả 3 đòn bẩy có số local hứa hẹn (margin-N +0.05..+0.17 F2,
               union-binding +0.046) đều bị khóa bởi CÙNG MỘT thứ: chưa có
               sealed held-out table gold. Report tự nói đúng điều này ở câu
               cuối — nhưng chưa biến nó thành kế hoạch có chủ/ngày/kích thước.
```

## 2. Kiểm chứng (đối chiếu trực tiếp)

| Claim | Kết quả | Bằng chứng |
|---|---|---|
| `lexical_years`/`retrieval_years` tách khỏi semantic `years` | ✅ | `question_intent.py:55,66,74,215,237` |
| `n_for` dùng `retrieval_years` | ✅ | `submission_adapter.py:120` |
| Period bonus dùng `retrieval_years` | ✅ | `evalkit/stages.py:250` |
| Stage attribution 23/10/8/54, gate P1 (95/554/86/50) | ✅ khớp từng số | `table-f2-recovery-p1-attribution.../metrics.json` |
| ADR 0013, `attribution.py`, 3 tools mới, artifact P0-P6 đầy đủ | ✅ | tất cả tồn tại đúng đường dẫn |
| ZIP upgraded tồn tại | ✅ | `artifacts/submissions/submission_table-f2-recovery-upgraded-a2d3ef-20260828-01.zip` |
| **Phát hiện thêm ngoài report:** runbook E2E đã chạy | ✅ | `artifacts/submissions/` có `submission.zip` + `submission_canonical-v2-a2d3ef030861-{a,b}-e2e-01.zip` — hai run A/B + alias cuối đúng theo runbook đã review |

Không kiểm được (UNKNOWN): SHA byte-identical (không chạy được shasum — sandbox vẫn chết), môi trường 3.13.9, kết quả `make ci`/`test-integration` (20 pass — lưu ý: **7 fail hôm qua đã biến mất**, xem §4.5).

## 3. Ưu điểm

1. **Kỷ luật null-result** — ZIP byte-identical được báo cáo thẳng là "không phải bằng chứng F2 tăng"; thử nghiệm fail (q425, rank 5→6) được giữ làm artifact immutable thay vì xóa. Đây là chuẩn mực mà nhiều report trước (ví dụ "Quality 8+ = 100% delivered") không đạt.
2. **Đóng measurement gap đúng chỗ** — trace `Intent → S1 → S2 → N → binding → final refs` + classifier 7 nhãn mutually-exclusive, gold chỉ nằm trong evalkit (không rò vào production). Từ nay tranh luận "mất gold ở đâu" có số thay vì cảm giác.
3. **Kết quả sweep đúng là Experiment 4 của red-team audit 27/08** (N-policy sweep trên final fields) — giờ có số local: margin-0.2 cho pre-bind F2 0.472 vs baseline 0.303; margin-0.5 cho canonical-final 0.435 vs 0.381. Đòn bẩy có thật, chỉ thiếu gold để promote.
4. **Feature audit sinh ra một phát hiện mới đáng giá:** unit-hit ở **non-gold cao hơn gold** (0.630 vs 0.332) — unit bonus 0.15 có thể đang phản tác dụng; period bonus gần như không phân tách (0.980 vs 0.972) dù mang trọng số 0.35 lớn nhất nhì. Đây là hai ứng viên ablation rẻ nhất chưa ai đo.
5. **Year-range hardening đúng cách** — tách semantic domain (35/37 câu range hiểu đủ) khỏi lexical retrieval years, chứng minh behavior-neutral bằng paired run + full 1.012 unchanged; có ADR 0013 + bump evalkit-12 + tests. Sửa parser defect mà không đụng scorer-facing output.
6. **Sửa một hiểu nhầm cũ:** multi-entity routes COUNT/DIFFERENCE/AVERAGE/SUM đã tồn tại trong canonical (177 abstain là safety, không phải thiếu route) — chặn đúng một hướng "rewrite" tốn kém.
7. **Từ chối upload ZIP byte-identical** — đúng kinh tế quota: nộp bản trùng byte không tạo phép thử mới.

## 4. Nhược điểm

1. **Môi trường off-contract (P1):** toàn bộ đo trên CPython **3.13.9**, trong khi runbook (đã review sáng nay) định nghĩa acceptance env là **3.11 hash-locked** — và report tự khai điều này. Byte-identical A/B trên cùng env vẫn hợp lệ về mặt diagnostic, nhưng **không ZIP nào từ máy này đủ tư cách nộp theo chính chuẩn của team** cho tới khi re-run dưới 3.11. Nếu `submission.zip` hiện tại cũng sinh từ env này thì nó thừa kế cùng caveat.
2. **563/449 — số đã trôi so với 561/451 (27/08) mà không có attribution (P1):** 2 câu chuyển từ abstain sang answered, gần như chắc do commit alias regen (`company_brand_attested_v1.yaml` — đúng rủi ro P0-1 đã cảnh báo trong runbook review). Report không ghi 2 QID nào và vì sao. Thiếu dòng này, chuỗi doc-number-drift (269→207→271→287→362 của V3) lặp lại ở V2: 561→563.
3. **Submission ID 3757 xuất hiện lần đầu, không hồ sơ (P1):** report nhắc "causal attribution cho 3757 = UNKNOWN" và Table F2 0.2500 — nghĩa là **một submission official thật đã xảy ra** nhưng repo không có receipt/ZIP mapping. Đây là lần thứ ba pattern RET-016/026 lặp lại (3236/3241/3392 → bảng 27/08 → 3757). Cần một artifact `submission_ledger.json` bắt buộc, ghi ngay khi nộp.
4. **Hypothesis 4 dễ bị đọc sai (P2):** "S1 95/95, entity không phải bottleneck" — đúng **trên slice 95**, nhưng 4 QID entity-failure đã proven (Q464/508/783/792) nằm **ngoài** slice; slice này không chứa chúng theo thiết kế. Cần một câu caveat để người sau không generalize thành "entity xong rồi".
5. **7 integration fail hôm qua → nay "20 passed, 2.140 deselected" (P2):** hôm 28/08 sáng còn "20 passed, 7 failed" (thiếu legacy artifacts). Nay PASS — nhưng không nói rõ đã giải quyết bằng cách nào (khôi phục artifact? ADR? deselect?). Con số "2.140 deselected" gợi ý các test đó bị deselect chứ không xanh. Nếu vậy, G4 của runbook được thỏa bằng cách thu hẹp phạm vi — cần ghi tường minh, tránh dấu xanh mờ nghĩa.
6. **Diagnostic sweeps trên gold nhiễm — đã biết, nhưng "next blocker" chưa thành kế hoạch (P1):** câu cuối report nêu đúng 2 lối thoát (sealed gold HOẶC controlled submission + receipt) nhưng không ai được giao, không kích thước, không ngày. Kinh nghiệm dự án cho thấy blocker không có chủ thì tồn tại mãi (120-QID reranker cohort sealed từ 27/08 đến nay vẫn 0 nhãn).
7. Nhỏ: lý do "không có upload endpoint/credential trong repo" hơi thừa — nộp là thao tác thủ công của chủ tài khoản; lý do đúng và đủ là "byte-identical nên không tạo phép thử mới".

## 5. Những gì cần nâng cấp (thứ tự ưu tiên)

### N1 — Sealed held-out table gold (mở khóa cả 3 đòn bẩy) · P0
Một bộ 150-300 câu, stratified theo mode (single/screen/compare), gán nhãn blind bởi người không tham gia sweep, seal SHA trước khi đọc. Đây là điều kiện promote cho: (a) **margin-based N policy** (ứng viên mạnh nhất: margin-0.5 → canonical-final F2 +0.053), (b) **conditional union binding** (+0.046, nên thử biến thể "chỉ union khi bound ⊂ retrieval output" để giữ precision), (c) **unit/period bonus ablation** (§3.4). Preregister cả ba trước khi mở gold — cùng một bộ gold dùng được cho cả ba nếu chỉ đọc một lần theo protocol.

### N2 — Đóng hồ sơ submission 3757 + lập submission ledger · P0
Thu receipt/screenshot/score JSON của 3757, map `submission_id ↔ ZIP SHA ↔ commit ↔ timestamp` vào một artifact mới. Từ nay mọi lần nộp ghi ledger **trước khi** đọc điểm. Không có N2, mọi tranh luận "Table F2 0.25 là của ZIP nào" sẽ lặp lại vô hạn như bảng điểm 27/08.

### N3 — Re-run release dưới Python 3.11 hash-locked · P1
Trước bất kỳ lần nộp kế tiếp: dựng `.venv` 3.11 theo G1 của runbook, chạy lại 2 run A/B, xác nhận SHA khớp bản 3.13 (nhiều khả năng khớp — pandas/pyarrow cùng version — nhưng phải đo, không đoán). Nếu khớp: một dòng evidence đóng luôn caveat env cho cả `submission.zip` hiện có.

### N4 — Attribution cho 561→563 + sync docs · P1
Ghi 2 QID đã đổi và nguyên nhân (alias regen?) vào một note; cập nhật một lần các doc đang quote 561/451. Việc này ~30 phút và chấm dứt drift kép V2/V3.

### N5 — Làm rõ trạng thái integration gate · P2
Một đoạn ngắn: 7 test H0/legacy hiện ở trạng thái nào (artifact khôi phục / ADR-0010 historical scope / vẫn treo)? "20 passed, 2.140 deselected" chưa trả lời câu đó.

### N6 — BINDING_LOSS 10 ca: audit từng ca bằng trace mới · P2
Trace đã có sẵn để đọc 10 ca này từng dòng. Nếu đa số là "bound table đúng nhưng khác gold hẹp" (như Q688 trong audit 27/08 — gold không exhaustive), thì union policy sẽ được minh oan một phần ngay cả trước khi có sealed gold; nếu đa số là bound sai bảng, ưu tiên đổi sang binder. Chi phí: đọc 10 records.

## 6. Kết luận

Report này làm đúng việc khó nhất: **chứng minh mình không cải thiện gì** — và nhờ đó dự án lần đầu có bản đồ định lượng của tổn thất Table F2 (N 23 · binding 10 · rank 8 · S1 0), cộng hai tín hiệu ranking bất ngờ (unit ngược chiều, period không phân tách). Quyết định KEEP BASELINE, giữ tooling, không promote trên dev gold: đều đúng.

Việc cần làm không nằm trong code nữa. Ba đòn bẩy đã được định giá bằng số local; thứ duy nhất giữa chúng và production là **một bộ gold sealed (N1)** và **một hồ sơ nộp bài có receipt (N2)**. Đề xuất ở vai cộng sự: làm N2 trước (1 buổi, đóng luôn câu hỏi 3757), khởi động N1 song song (đây là lao động gán nhãn, không phải engineering — có thể bắt đầu ngay hôm nay với protocol đã có sẵn trong `configs/evaluation/independent_gold_protocol_v1.yaml`).
