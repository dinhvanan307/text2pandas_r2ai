# Review độc lập — E2E Runbook to `submission.zip`

**Ngày:** 2026-08-28 · Tài liệu được review: `E2E_TO_SUBMISSION_RUNBOOK_2026-08-28.md`
**Reviewer:** audit độc lập (tiếp nối chuỗi FULL_INDEPENDENT_AUDIT 27/08 → PLAN_REVIEW → BACKLOG_FLOW 28/08)
**Phương pháp:** đối chiếu từng lệnh, flag CLI, gate và claim trạng thái với code/artifact trên đĩa.

---

## 1. Verdict

```text
KẾT LUẬN:  APPROVE WITH CHANGES
           Runbook chính xác về mặt cơ học ở mức hiếm thấy: 100% lệnh và
           contract kiểm được đều khớp code thật (bảng mục 2). Các trạng thái
           RED tự khai đều đúng với audit độc lập. Thứ tự gate hợp lý, stop
           conditions đúng văn hóa fail-closed.

           Nhưng có 1 lỗ hổng P0 về PHẠM VI DIFF (workspace chứa một thay đổi
           làm ĐỔI HÀNH VI V2 mà runbook mặc định coi là V3-only) và 2 điểm P1
           về mục đích/kinh tế của lần nộp. Sửa xong 3 điểm này thì runbook
           đủ điều kiện thực thi.

BẢN CHẤT:  Đây là plan RELEASE-ENGINEERING (tạo ZIP sạch, truy vết được),
           KHÔNG phải plan tăng điểm. ZIP tạo ra vẫn mang đầy đủ các tổn thất
           đã biết: ~450 abstain nộp answer=0.0 (trần EXEC ≈ 55%), N policy
           min(e×y,10), entity STB/EIB. Kỳ vọng EXEC ≈ 0,25 (561 × ~45%).
           Điều đó KHÔNG làm runbook sai — nhưng người bấm nút nộp phải biết
           mình đang mua gì bằng 1 lượt quota.
```

---

## 2. Kiểm chứng cơ học (đối chiếu code)

| Claim / lệnh trong runbook | Kết quả | Bằng chứng |
|---|---|---|
| `run --limit/--offset/--question-id/--no-package` tồn tại; partial run bắt buộc `--no-package` | ✅ | `main.py:198-201, 871-894` — runbook tuân thủ đúng ràng buộc mà chính CLI enforce |
| Publish chỉ khi validator + replay sạch; ZIP về `artifacts/submissions/submission_<run_id>.zip`; exit 1 nếu fail | ✅ | `main.py:298-306` — `package_ok = val.ok and error==0 and matched==executed` |
| `submission_manifest.json` có `status VALIDATED`, `validation.records/errors/warnings`, `replay.matched/executed`, `package.published_path` | ✅ | `run_manifest.py:81-108` — script assertion Phase 7 dùng đúng key |
| `dp-env-check` báo `lock_has_hashes / lock_matches_installed / lock_covers_imports / source_tree_dirty / untracked_in_source_paths` | ✅ | `tools/env_check.py` chứa đủ các field |
| `requirements.lock` tồn tại | ✅ | repo root |
| `download_vifinqa.py --verify-only --skip-github` | ✅ | `download_vifinqa.py:633-635` |
| `artifacts/submissions/` trống (RED "chưa có bài nộp canonical") | ✅ | glob 0 file |
| 7 integration fail do thiếu 3 legacy artifacts | ✅ | khớp implementation report 28/08 + audit 27/08 |
| Smoke QIDs "pre-registered từ qid_slices.json" | ✅ | 587/592/813/817 có mặt trong `data/curated/evaluation/legacy/qid_slices.json` |
| `snapshots-verify` không hash payload → tách shasum thành gate riêng | ✅ **đúng và đáng khen** | khớp finding audit 27/08 (`snapshots.py:132-137` size-only); runbook là tài liệu đầu tiên bù lỗ hổng này |
| Baseline V2 676s/1.012 câu → ước 25-35 phút cho 2 run | ✅ hợp lý | ACCEPTANCE 27/08: 675,98s |
| HEAD `b0d7b84`, dirty 13 file, Python chỉ 3.13/3.14, disk 52GiB | ⚠️ `UNKNOWN` | không chạy được git/python trong phiên audit; chấp nhận theo khai báo |

Runbook cũng đã tiếp thu đúng các điểm review trước: G0 clean worktree (M2 cũ), không hardcode "561 emitted" làm gate, nhánh ADR-0010 thay vì tạo ZIP giả, phân biệt "có ZIP" vs "đủ điều kiện nộp" (§15 — chính xác với phát hiện V3 shadow ZIP).

---

## 3. Vấn đề phải sửa

### P0-1 — Workspace diff chứa thay đổi ĐỔI HÀNH VI V2, runbook đang coi toàn bộ diff là V3-only

Phase 0 mô tả 13 file đang sửa là "implementation `metric_resolution_v1` và report/test đi kèm" và chỉ yêu cầu "review". Nhưng đã xác minh trên đĩa: **`configs/retrieval/company_brand_attested_v1.yaml` đã được regen sạch** (hết literal `...`, chuyển block style). File này là **input trực tiếp của V2 canonical** — `canonical_run.py:538` gọi `load_aliases("a6")` đọc đúng file này. Nghĩa là:

- Nếu **commit** nó vào release: hành vi retrieval V2 thay đổi so với mọi baseline lịch sử (Q586 và ~61 QID bị nhiễu alias trước đây sẽ đổi terms) → số emitted/refs sẽ trôi so với 561, và **đây nhiều khả năng là cải thiện** — nhưng phải được đo, không được để nó trôi vào release như một thay đổi "V3-only".
- Nếu **loại** nó ra: giữ byte-parity với hành vi cũ, nhưng cố tình nộp một bug đã có fix nằm sẵn trên đĩa.

**Sửa:** thêm bước **G0.5 — phân loại diff theo consumer**: mỗi file trong diff gắn nhãn `V2-affecting / V3-only / cả hai / doc-test`. Với mọi file V2-affecting (tối thiểu là YAML alias này): chạy paired retrieval eval trên gold-95 (evalkit, cùng snapshot) trước–sau, ghi expected drift vào release note, rồi mới quyết commit hay tách. Khuyến nghị của tôi: **commit fix alias** (nó sửa lỗi P0 đã confirmed từ 27/08) và chấp nhận emitted-count drift có hồ sơ.

### P1-1 — Thiếu "mục đích của lần nộp" và kinh tế quota

Runbook dừng ở "ZIP đủ điều kiện nộp" nhưng không trả lời: nộp lần này để làm gì, và tốn bao nhiêu quota? Theo trạng thái đã audit: quota private là **5 bài TỔNG**; ZIP này kỳ vọng EXEC ≈ 0,25 (trần coverage 55,43% × precision local ~45%) so với baseline official cũ 0,1225. Một lần nộp như vậy có giá trị thật — nó là **phép đo baseline NEW đầu tiên** (điều mọi report từ 27/08 đến nay đều kêu thiếu) — nhưng phải được tuyên bố là như vậy.

**Sửa:** thêm mục "Mục đích & ngân sách": (a) lần nộp này = đo baseline NEW-V2, không phải bài tốt nhất; (b) đối chiếu quota còn lại trước khi bấm; (c) tiêu chí đọc kết quả viết TRƯỚC (vd: nếu EXEC < 0,1225 → ưu tiên xem lại abstain policy trước mọi thứ khác — đúng điều kiện C3 của OLD_VS_NEW).

### P1-2 — G4 có nguy cơ treo vô hạn

Hai ZIP legacy authentic có khả năng đã mất vĩnh viễn (provenance p0i ghi original ZIP lost, root cause repack 22/08). Runbook có nhánh ADR ✓ nhưng điều kiện kích hoạt là "không còn ở bất kỳ nguồn nào" — một điều kiện không bao giờ chứng minh xong.

**Sửa:** timebox việc tìm artifact (đề xuất 0,5 ngày, ghi các nguồn đã tra); hết timebox → đi thẳng nhánh ADR-0010 (chuyển monitor sang historical scope + gate tương đương trên active candidate). Release không được phụ thuộc khảo cổ học.

### P2 — Các điểm nhỏ

1. **G1/Python 3.11:** máy chỉ có 3.13/3.14 → ghi lệnh cài cụ thể (`pyenv install 3.11` / `uv python install 3.11`) để không ai "tiện tay" chạy 3.14; bài học `MEASURED_OFF_CONTRACT_PY310` đã có tiền lệ trong provenance.
2. **Determinism contingency:** nếu buộc phải rebuild A6 (nhánh contingency G2), phải chạy qua `make` để ăn `PYTHONHASHSEED=0` — `cleaning.py:269` vẫn iterate `set()` (nợ đã audit, chỉ bị che bởi make env). Đường reuse-payload không ảnh hưởng.
3. **Sau khi BTC chấm:** thêm bước lưu **receipt** — score JSON/screenshot + mapping `submission_id ↔ SHA-256 ZIP` ngay khi có kết quả. Đây chính là lỗ hổng RET-016/026: bảng điểm 27/08 đến giờ không reconcile được vì thiếu đúng thứ này. Evidence list ở §12 hiện dừng ở ZIP SHA.
4. **`shasum` 2 DB ~8,4GB** mất vài phút — nên note để không ai tưởng treo.
5. **Q366/Q1** trong boundary slice: 587/592/813/817 đã verify có trong `qid_slices.json`; xác nhận nốt 1 và 366 khi chạy (không kiểm được hết trong phiên này).

---

## 4. Những gì KHÔNG cần sửa (đã cân nhắc và đồng ý)

- **Chọn V2, giữ V3 shadow** — đúng; V3 362 OK chưa adjudicate (93-case queue), promotion policy chặn là chặn đúng.
- **Reuse payload, không rebuild** — đúng; rebuild chỉ thêm rủi ro khi identity + SHA khớp.
- **Không hardcode 561** — đúng, và càng đúng nếu P0-1 commit alias fix (số sẽ trôi có chủ đích).
- **Hai run byte-identical làm determinism gate** — khả thi: ZIP writer đã deterministic (`_write_deterministic`, `submission.py`), run manifest nằm ngoài ZIP.
- **Stop condition "không biến abstention thành answer giả chỉ để tạo ZIP"** — giữ nguyên. Việc thay đổi abstain policy (nếu làm) phải là một plan riêng có phép đo, không phải một quyết định lúc release.

---

## 5. Thứ tự thực thi khuyến nghị (runbook + sửa đổi)

```text
G0   Freeze source  ──►  G0.5 Phân loại diff V2/V3 [P0-1]
                          └─ V2-affecting → paired eval gold-95 → release note
G1   Python 3.11 hash-locked  [+ lệnh cài cụ thể]
G2   Verify data (reuse; shasum 2 DB là gate riêng)
G3   make ci
G4   Integration: timebox 0,5d tìm legacy ZIP → hết giờ đi nhánh ADR-0010 [P1-2]
G5   Smoke 10 câu + boundary slice (--no-package)
G6/7 Hai full run A/B → byte-identical
G8   Inspection + submission.zip
G9*  [MỚI] Tuyên bố mục đích nộp + check quota + tiêu chí đọc kết quả [P1-1]
G10* [MỚI] Sau khi có điểm: lưu receipt score ↔ SHA (đóng RET-016/026) [P2.3]
```

## 6. Kết luận

Runbook này là mảnh ghép đúng và đang thiếu của dự án: từ 27/08 đến nay mọi tài liệu đều nói "chưa có bài nộp canonical NEW" — đây là con đường có kỷ luật để tạo ra nó. Chất lượng cơ học xuất sắc (mọi lệnh khớp code, mọi RED tự khai đều thật). Ba việc phải làm trước khi chạy: **phân loại diff V2-affecting (P0-1 — nếu bỏ qua, release sẽ mang một thay đổi hành vi V2 không hồ sơ, hoặc cố tình nộp bug đã có fix)**, tuyên bố mục đích nộp + quota (P1-1), và timebox cho G4 (P1-2). Sau lần nộp này, con số official đầu tiên của NEW sẽ thay thế toàn bộ tranh luận ước lượng 0,25-vs-0,1225 bằng một phép đo thật — với điều kiện receipt được lưu (G10).
