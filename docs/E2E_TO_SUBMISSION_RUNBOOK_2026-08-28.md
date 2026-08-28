# E2E runbook: current workspace to `submission.zip`

**Ngày khảo sát:** 2026-08-28 (Asia/Ho_Chi_Minh)  
**Mục tiêu:** chạy và kiểm tra toàn bộ đường production từ source/data hiện có tới một file ZIP đủ điều kiện nộp.  
**Đường production được chọn:** Canonical V2. Semantic V3 tiếp tục là shadow và không được dùng làm bài nộp production khi promotion policy còn `BLOCKED`.

## 1. Kết quả cuối cần tạo

Artifact gốc, bất biến:

```text
artifacts/submissions/submission_<run_id>.zip
```

Alias cuối để người dùng tải lên:

```text
artifacts/submissions/submission.zip
```

`submission.zip` chỉ được tạo bằng cách copy không ghi đè từ một candidate đã qua toàn bộ gate. Artifact mang `run_id` vẫn được giữ làm nguồn provenance.

## 2. Trạng thái hiện tại đã kiểm tra

| Layer | Trạng thái | Bằng chứng ngày 2026-08-28 |
|---|---|---|
| Competition contract | PASS | ZIP phải có đúng một JSON ở root và các CSV được tham chiếu dưới `data/`; toàn bộ câu hỏi phải có mặt |
| Runtime selection | PASS có điều kiện | Canonical V2 là production; V3 là shadow theo ADR-0008 và promotion policy |
| Git/source identity | **RED** | HEAD `b0d7b84...`, branch `main` ahead 1; 13 tracked files đang sửa và có untracked files trong `src/`, `tools/`, `configs/` |
| Python acceptance environment | **RED** | Không có `.venv`; máy chỉ thấy Python 3.13/3.14, trong khi lock được sinh bằng Python 3.11; system Python thiếu PyYAML |
| Disk | PASS cho đường reuse | Khoảng 52 GiB trống. Không cần rebuild A6/index nếu active snapshots tiếp tục pass |
| Raw BTC | PASS về identity/count | `ca033190f2e9e99f`; 1.973 report, 1.012 question, 100 ticker |
| A6 | PASS | `c6887fb633374fad`; `silver.db` 4.140.924.928 byte; SHA-256 `fa6c46d6...dc3c8` |
| Retrieval | PASS | `872ccb0dda9a2bb6`; `retrieval.db` 4.239.663.104 byte; SHA-256 `72d307f8...b6daf` |
| Snapshot verifier | PASS diagnostic | Tất cả raw/A6/retrieval checks pass bằng môi trường tạm |
| Static/offline CI | PASS diagnostic | Ruff, mypy 85 files, 50 Markdown links; 2.076 passed, 42 approved skips, 27 integration deselected |
| Materialized integration | **RED** | 20 passed, 7 failed; thiếu authentic `submission_P0G2.zip`, `submission_C1R_LOCAL.zip`, `determinism_report_v2.json` |
| Current V3 candidate | YELLOW, shadow only | 362 OK/650 abstain; package 1.012 records, validation 0 lỗi, replay 362/362; 93-case queue chưa adjudicate |
| Current canonical artifact | **RED** | Không có `artifacts/runs/answer/<run_id>` và không có file trong `artifacts/submissions/` |

Kết luận hiện trạng: **data plane đã sẵn sàng; source/environment/integration-release plane chưa sẵn sàng; chưa có bài nộp canonical.**

## 3. Đường găng

```text
G0 source sạch và được định danh
  -> G1 Python 3.11 hash-locked
  -> G2 active raw/A6/retrieval + checksum
  -> G3 static/offline CI
  -> G4 materialized integration
  -> G5 canonical smoke
  -> G6 canonical full run A + validate/replay
  -> G7 canonical full run B + deterministic comparison
  -> G8 final inspection + submission.zip
```

Nếu một gate đỏ, dừng tại gate đó. Không sửa manifest, không nới validator, không thêm skip, không tái sử dụng `run_id`, và không xóa run hỏng.

## 4. Phase 0 — Freeze source identity

### Mục tiêu

Chạy từ một source commit có thể truy ngược và không làm mất các thay đổi đang có của người dùng.

### Việc cần làm

1. Review toàn bộ thay đổi đang có, đặc biệt implementation `metric_resolution_v1` và các report/test đi kèm.
2. Chọn một trong hai cách:
   - commit toàn bộ thay đổi có chủ đích trên một branch release; hoặc
   - tạo một clean release worktree từ commit được chọn, giữ nguyên workspace bẩn hiện tại.
3. Không stash/reset/clean tự động.

### Gate G0

```bash
git status --short --branch
git diff --check
git rev-parse HEAD
```

PASS khi:

- `git diff --check` exit 0;
- release workspace không có tracked modification;
- không có untracked file dưới `src/`, `tools/`, `configs/`;
- commit SHA được ghi vào evidence.

Khuyến nghị release: worktree sạch hoàn toàn, kể cả tài liệu, để `git_dirty=false` trong run manifest.

## 5. Phase 1 — Rebuild acceptance environment

### Mục tiêu

Tạo `.venv` từ đúng Python 3.11 và `requirements.lock` có hash. Không dùng system Python 3.14 hoặc temporary metric venv để phát hành.

### Commands

```bash
PY311=/absolute/path/to/python3.11
"$PY311" -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps -e .
make dp-env-check
```

### Gate G1

PASS khi:

- Python là 3.11.x;
- pandas, pyarrow, PyYAML, lxml, pytest, Ruff và mypy có đủ;
- `lock_has_hashes=True`;
- `lock_matches_installed=True`;
- `lock_covers_imports=True`;
- `source_tree_dirty=False`;
- `untracked_in_source_paths=[]`.

Hiện tại Python 3.11 chưa có trong `PATH`; đây là blocker đầu tiên cần đóng khi bắt đầu execution.

## 6. Phase 2 — Verify every data layer

### Mục tiêu

Reuse active payload 21 GiB đang có. Không rebuild raw/A6/retrieval nếu identity và byte checksum đều khớp.

### Commands

```bash
make paths-check
make snapshots-verify
shasum -a 256 \
  data/processed/a6/c6887fb633374fad/silver.db \
  data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db
python tools/data_acquisition/download_vifinqa.py --verify-only --skip-github
```

### Gate G2

PASS khi:

- raw: 1.973 reports, 1.012 questions, 100 tickers;
- A6 build ID: `c6887fb633374fad`;
- `silver.db` SHA-256: `fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8`;
- retrieval index ID: `872ccb0dda9a2bb6`;
- `retrieval.db` SHA-256: `72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf`;
- bốn retrieval indexes bắt buộc có mặt;
- SQLite quick/integrity check pass nếu được thêm vào verifier.

Gap cần ghi rõ: `snapshots-verify` kiểm count/schema/size nhưng chưa tái tính `payload_tree_sha256` của raw và chưa so SHA của DB. Hai SHA DB vì vậy phải giữ là gate riêng. Trước release-grade run nên bổ sung một verifier read-only có version cho raw payload tree, thay vì tự suy diễn thuật toán hash trong runbook.

### Contingency khi G2 fail

- Nếu chỉ thiếu payload: khôi phục từ nguồn/provenance hợp lệ.
- Nếu hash lệch: dừng; không sửa manifest cho khớp.
- Chỉ đi vào `dp-build -> dp-release -> build_retrieval_snapshot.py` khi active payload thực sự hỏng hoặc chủ đích tạo snapshot mới. Với trạng thái hiện tại, rebuild là không cần thiết và tăng rủi ro.

## 7. Phase 3 — Code and offline quality gates

### Commands

```bash
make ci
git diff --check
make semantic-coverage
```

### Gate G3

PASS khi:

- Ruff exit 0;
- strict mypy exit 0;
- docs links exit 0;
- offline pytest có 0 failure/error;
- skip count không vượt allowlist và không có reason drift;
- semantic coverage phân loại đủ 1.012 câu.

Coverage, replay consistency và accuracy phải được báo cáo riêng. Không gọi route coverage là Answer Accuracy.

## 8. Phase 4 — Close materialized integration blocker

### Current blocker

`make test-integration` hiện có 20 PASS và 7 FAIL. Bảy failure không nằm trong active raw/A6/retrieval path; chúng đọc ba artifact H0/legacy đang vắng:

```text
artifacts/submissions/legacy/submission_P0G2.zip
artifacts/submissions/legacy/submission_C1R_LOCAL.zip
artifacts/execution/h0/determinism_report_v2.json
```

`make materialize-h0` không tự giải quyết được nếu thiếu `submission_P0G2.zip`; tool cần baseline này làm input.

### Resolution order

1. Ưu tiên khôi phục hai ZIP authentic từ artifact storage/handoff tin cậy, ghi nguồn và SHA-256.
2. Chạy `make materialize-h0`; tool phải tạo lại adjudication ledger và determinism report, đồng thời chứng minh C1R rebuild khớp canonical.
3. Nếu authentic legacy ZIP không còn ở bất kỳ nguồn nào, không tạo ZIP giả. Mở một thay đổi kiến trúc riêng:
   - amend ADR-0010;
   - chuyển đúng các monitor legacy sang historical scope;
   - thay bằng materialized gates tương đương trên active canonical candidate;
   - review và commit thay đổi trước khi tiếp tục release.

### Resolution executed on 2026-08-28

The bounded search covered the local Dagoras-R2AI project tree and found no
authentic copy of either legacy ZIP. The ADR-0010 branch was therefore taken:

- the seven ZIP/report-dependent tests remain intact under the explicit
  `historical` marker and `make test-historical`;
- the other 20 real-data H0/integration tests remain active;
- `make test-integration` and `make dp-test` select the active architecture,
  without skip/xfail allowances;
- after full runs A/B, `make verify-active-candidate RUN_A=... RUN_B=...`
  independently enforces current manifest/source/snapshot identity, strict
  validation, clean replay, 1,012 records, and byte-identical ZIPs.

The active candidate gate is deliberately post-run because its inputs are the
two immutable current canonical outputs. It does not reconstruct or replace a
legacy artifact.

### Commands for the selected architecture

```bash
make test-integration
REPORT_REV=$(git rev-parse --short=12 HEAD)
REPORT_STAMP=$(date -u +%Y%m%dT%H%M%SZ)
make dp-test REPORT_DIR="artifacts/reports/e2e_release_${REPORT_STAMP}_${REPORT_REV}"
# after full canonical runs A and B
make verify-active-candidate RUN_A=<run-a> RUN_B=<run-b>
```

### Gate G4

PASS khi active integration suite và machine-readable active full suite có 0
failure/error. Không cho phép `xfail`, unapproved skip hoặc bỏ riêng
`test_h0_gates.py`; file này vẫn chạy toàn bộ 20 active tests. Bảy monitor cần
pre-refactor ZIP được quản trị riêng bởi scope `historical`, không được tính là
active acceptance evidence.

## 9. Phase 5 — Canonical V2 smoke

### Mục tiêu

Kiểm tra đường runtime thật trên active A6/retrieval trước khi chạy 1.012 câu.

### Commands

Mỗi lần dùng một run ID mới:

```bash
COMMIT12=$(git rev-parse --short=12 HEAD)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
SMOKE_RUN="canonical-smoke-${COMMIT12}-${STAMP}"
python -m text2pandas.interface.cli.main -v run \
  --run-id "$SMOKE_RUN" \
  --offset 0 \
  --limit 10 \
  --no-package
```

Sau đó chạy thêm một explicit slice đại diện cho lookup, arithmetic, count, multi-entity, emitted answer và fail-closed abstention:

```bash
# Pre-registered từ qid_slices.json và question_plans_1012.jsonl:
# 1 lookup; 587 percentage change; 592 difference; 366 multi-entity count;
# 817 sum; 813 argmax-year.
BOUNDARY_RUN="canonical-boundary-${COMMIT12}-${STAMP}"
python -m text2pandas.interface.cli.main -v run \
  --run-id "$BOUNDARY_RUN" \
  --question-id 1 \
  --question-id 587 \
  --question-id 592 \
  --question-id 366 \
  --question-id 817 \
  --question-id 813 \
  --no-package
```

QID phải được chọn từ versioned diagnostic/gold registry, không chọn sau khi nhìn output của candidate.

### Gate G5

PASS khi:

- preflight snapshot pass;
- `manifest.json` có đúng commit và `git_dirty=false`;
- records count bằng slice size;
- emitted records có evidence + restricted Pandas query replay được;
- abstention không rò answer/query/evidence;
- không có exception hoặc output ghi nhầm data root.

## 10. Phase 6 — Two independent canonical full runs

### Mục tiêu

Tạo hai candidate từ cùng commit/config/snapshots để kiểm actual ZIP determinism. Baseline 27/08 chạy khoảng 676 giây cho 1.012 câu; dự kiến hai run khoảng 25–35 phút tổng, chưa kể I/O.

### Commands

```bash
COMMIT12=$(git rev-parse --short=12 HEAD)
STAMP_A=$(date -u +%Y%m%dT%H%M%SZ)
RUN_A="canonical-v2-${COMMIT12}-a-${STAMP_A}"

python -m text2pandas.interface.cli.main -v run --run-id "$RUN_A"

# Tạo run ID thứ hai sau khi run A kết thúc.
STAMP_B=$(date -u +%Y%m%dT%H%M%SZ)
RUN_B="canonical-v2-${COMMIT12}-b-${STAMP_B}"
python -m text2pandas.interface.cli.main -v run --run-id "$RUN_B"
```

Mỗi command tự thực hiện:

```text
question -> V2 retrieval -> answering -> records/evidence
         -> build ZIP -> strict validation -> clean replay
         -> publish only if every gate passes
```

### Gate G6/G7

Với từng run:

- exit code 0;
- `artifacts/runs/answer/<run_id>/manifest.json` tồn tại;
- `submission_manifest.json.status == VALIDATED`;
- validation: 1.012 records, 0 error, 0 warning;
- replay: `error == 0`, `matched == executed`;
- published path không null;
- `artifacts/submissions/submission_<run_id>.zip` tồn tại;
- source commit, raw snapshot, A6 build và retrieval index giống nhau giữa A/B.

Không lấy 561 emitted answers làm hard-coded correctness gate. Đây là historical expectation của V2 tại commit cũ, hữu ích để phát hiện drift nhưng không thay thế diagnosis. Mọi thay đổi count phải có taxonomy và review.

### Determinism gate

```bash
ZIP_A="artifacts/submissions/submission_${RUN_A}.zip"
ZIP_B="artifacts/submissions/submission_${RUN_B}.zip"
shasum -a 256 "$ZIP_A" "$ZIP_B"
cmp "$ZIP_A" "$ZIP_B"
```

PASS khi hai file byte-identical. Nếu khác, dừng và so archive member/checksum; không chọn tùy ý một file để nộp.

## 11. Phase 7 — Final package inspection

### Manifest assertion

```bash
python -c 'import json,sys; m=json.load(open(sys.argv[1])); assert m["status"]=="VALIDATED"; assert m["validation"]["records"]==1012; assert m["validation"]["errors"]==[]; assert m["validation"]["warnings"]==[]; assert m["replay"]["error"]==0; assert m["replay"]["matched"]==m["replay"]["executed"]; assert m["package"]["published_path"]' \
  "artifacts/runs/answer/${RUN_A}/submission_manifest.json"
```

### ZIP assertions

Inspect archive root and run the repository validator/replay result against the exact published bytes. Required invariants:

- exactly one `.json` at ZIP root;
- no parent directory, absolute path, `..`, `.DS_Store` or `__MACOSX`;
- every other member is a referenced `data/*.csv`;
- exactly 1.012 unique integer IDs;
- exact source question strings;
- finite numeric answers;
- unique valid evidence variables;
- real document/table locators;
- safe restricted Pandas query;
- every emitted `answer == eval(pandas_query)`;
- 0 orphan CSV, validator error, replay error and mismatch.

## 12. Phase 8 — Create final `submission.zip`

Chỉ thực hiện sau G0–G7 PASS:

```bash
test ! -e artifacts/submissions/submission.zip
cp -n "$ZIP_A" artifacts/submissions/submission.zip
cmp "$ZIP_A" artifacts/submissions/submission.zip
shasum -a 256 artifacts/submissions/submission.zip
```

Không ghi đè alias cũ. Nếu file đã tồn tại, tạo một release directory/alias mới thay vì xóa lịch sử.

Evidence cuối cần giữ:

```text
commit SHA
git status
dp-env-check output
active_snapshot.yaml
raw/A6/retrieval verifier output
A6/retrieval DB SHA-256
CI + integration + dp-test reports
run A/B manifests
submission manifests
ZIP A/B/final SHA-256
archive member listing
known gaps and NOT_MEASURED metrics
```

## 13. Definition of done

Hoàn thành khi và chỉ khi:

- G0–G7 đều PASS trong Python 3.11 hash-locked environment;
- materialized integration blocker đã được giải quyết bằng authentic evidence hoặc một ADR/test migration được review, không bằng artifact giả;
- hai full canonical runs byte-identical;
- active candidate gate trên hai full canonical runs có status `PASS`;
- final `artifacts/submissions/submission.zip` tồn tại và có cùng SHA với candidate được chọn;
- ZIP có 1.012 records, strict validation 0 lỗi/cảnh báo và clean replay 0 lỗi/mismatch;
- source/data/config/run/package provenance đầy đủ;
- official Answer Accuracy và Execution Accuracy vẫn được ghi là `NOT_MEASURED` nếu chưa có organiser scorer.

## 14. Stop conditions

Dừng và điều tra nếu có bất kỳ điều nào:

- worktree dirty hoặc source chưa commit;
- Python/lock mismatch;
- active identity, DB byte size hoặc SHA lệch;
- unapproved skip, test failure hoặc integration artifact giả/không rõ nguồn;
- run manifest ghi `git_dirty=true`;
- validator/replay không sạch;
- A/B ZIP khác bytes;
- V3 được chọn làm production khi promotion policy còn blocked;
- ai đó đề xuất sửa manifest, threshold hoặc abstention thành answer giả chỉ để tạo ZIP.

## 15. Phân biệt “có ZIP” và “đủ điều kiện nộp”

Một V3 shadow ZIP 1.012 records đang tồn tại và validate/replay sạch, nhưng nó không phải production submission vì V3 chưa qua promotion. Tương tự, CLI canonical có thể sinh ZIP dù historical H0 gate đang thiếu artifact. Runbook này chỉ gọi file cuối là `submission.zip` khi source, environment, data, tests, integration, canonical execution, validation, replay và determinism đều đã đóng.
